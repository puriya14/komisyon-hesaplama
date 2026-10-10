"""İleriye dönük ölçüm: bahis adayı olmasa bile maç öncesi A/B/C tahminlerini kaydetme (FORECAST_RECORD).

"Takip edilecek bahis adayı yok" ile "kaydedilecek model tahmini yok" ayrı durumlardır. Bu modül mevcut değişmez
defteri (``goals.ledger.Ledger``) yeniden kullanır; ikinci bir kayıt sistemi kurmaz:

* ``FORECAST_RECORD``: önceden tanımlı uygunluk koşullarını sağlayan maçın model tahmini (stake 0). Koşulu sağlamayan
  aday maçlar da olasılıksız ``TAHMIN_YOK`` kaydı olarak nedenleriyle yazılır (tahmin uydurulmaz).
* ``BET_CANDIDATE_RECORD``: yalnızca karar motorunun ``VALUE_CANDIDATE`` dediği, zamanı doğrulanmış gerçek oranlı
  adaylar (``service.record_decisions``). Diğer karar kayıtları ``KARAR_KAYDI`` türündedir.
* Sonuç ayrı olay olarak eklenir (``service.settle_pending``); eski tahmin değiştirilmez. Geçersiz ilan da ayrı ve
  gerekçeli bir kayıttır (``FORECAST_GECERSIZ_ILAN``); değerlendirmede hem dahil hem hariç sayılar gösterilir.

Zaman kuralı (protokol ``ileriye-donuk-olcum-v1``): hedef karar anı = maç günü 00:00 Europe/Istanbul. Fiilî kayıt
anı (defterin ``created_at`` alanı, sistem saati) hedeften önce olmalıdır; değilse olasılık yazılmaz
(``PENCERE_KACIRILDI``). Sonucu bilinen veya protokol dondurma anından önce oynanan maç ileriye dönük kabul edilmez.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..data.leagues import LEAGUES
from ..timeutil import ISTANBUL, kickoff_utc
from .ledger import Ledger, event_id
from .markets import PRIMARY_YES, label_frame
from .model import FEATURE_VERSION, MODEL_VERSION

RECORD_FORECAST = "FORECAST_RECORD"
RECORD_BET = "BET_CANDIDATE_RECORD"
RECORD_DECISION = "KARAR_KAYDI"  # karar motoru kaydı (aday değil); eski kayıtlar da bu türde sayılır
RECORD_INVALIDATION = "FORECAST_GECERSIZ_ILAN"

STATUS_FORECAST = "TAHMIN"
STATUS_NO_FORECAST = "TAHMIN_YOK"

REASONS = {
    "PENCERE_KACIRILDI": "Kayıt anı hedef karar anından (maç günü 00:00 İstanbul) sonra; olasılık yazılmaz.",
    "MAC_SONUCU_BILINIYOR": "Maçın sonucu veri deposunda var; ileriye dönük kayıt olamaz.",
    "PROTOKOLDEN_ONCE": "Maç günü protokol dondurma anından önce; ileriye dönük örnekleme girmez.",
    "MODEL_YOK": "Eğitilmiş gol pazarları modeli yok.",
    "LIG_MODEL_KAPSAMI_DISI": "Lig modelin eğitim verisinde yok.",
    "VERI_GUNCEL_DEGIL": "Geçmiş veri güncel değil (arada oynanmış ama veride olmayan maç var veya doğrulanamıyor).",
    "TAKIM_GECMISI_YETERSIZ": "Takım güçleri hesaplanamadı veya son 365 günde yeterli maç yok.",
    "OLASILIK_GECERSIZ": "Model olasılığı geçersiz (NaN veya [0,1] dışı).",
}

# ----------------------------------------------------------------------------
# Protokol (dondurulmuş gövde). Değişiklik = yeni sürüm; eski sürümün sonuçları ayrı raporlanır.
# ----------------------------------------------------------------------------

PROTOCOL_VERSION = "ileriye-donuk-olcum-v1"
PROTOCOL_BODY = {
    "surum": PROTOCOL_VERSION,
    "amac": ("A/B/C pazarlarında maç öncesi model olasılıklarının gerçek zamanında kaydedilip sonradan "
             "değerlendirilmesi. Bahis önerisi veya getiri iddiası değildir."),
    "pazarlar": list(PRIMARY_YES),
    "ligler": ("Veri deposundaki 22 lig (T1, E0, E1, E2, E3, EC, SC0, SC1, SC2, SC3, D1, D2, I1, I2, SP1, SP2, F1, F2, "
               "N1, B1, P1, G1). Hiçbir lig sonuçlara bakılarak çıkarılmaz; tüm ligler birlikte ve lig bazında raporlanır."),
    "fikstur_kaynagi": ("Çalışma anında kullanımına izin verilmiş kaynaklar (source_registry.allowed_sources): "
                        "openfootball (CC0) ve yalnızca kullanıcı onayı varsa football-data.co.uk. Kaynak ve hak "
                        "durumu her kayıtta saklanır. İzinli fikstür kaynağı olmayan ligde aday maç oluşmaz; bu ligler "
                        "kapsam raporunda 'fikstür kaynağı yok' olarak sayılır. Takım adı eşleşmeyen fikstür maçı "
                        "fikstür katmanında elenir ve deftere girmez; sayısı güncelleme uyarısında görünür (bilinen "
                        "sınırlama)."),
    "karar_penceresi": {
        "hedef": "maç günü 00:00 Europe/Istanbul",
        "gerekce": ("Uygulamada otomatik zamanlayıcı yok ve veri günlük/elle güncelleniyor; başlama saati her ligde "
                    "kaynakta bulunmayabiliyor. T−60 dakika penceresi her maç için elle çalıştırma gerektirir ve mevcut "
                    "veri akışı bunu desteklemez."),
        "gec_kayit": "Hedeften sonra yapılan kayıt olasılık içermez (PENCERE_KACIRILDI); geriye dönük doldurma yapılmaz.",
    },
    "uygunluk": [
        "Kayıt anı < hedef karar anı.",
        "Maç günü > protokol dondurma anı (İstanbul tarihi).",
        "Maçın sonucu kayıt anında veri deposunda yok.",
        "Model eğitilmiş ve lig modelin kapsamında.",
        "Geçmiş veri güncel: fikstür kaynağı oynanmış maçları listeliyorsa veri deposunda eksik oynanmış maç yok; "
        "listelemiyorsa ligin son kayıtlı maçı karar anından en fazla 21 gün önce.",
        "Her iki takımın gücü hesaplanabilir ve son 365 günde ligde en az 10 maçı var.",
        "Olasılık sonlu ve (0, 1) aralığında.",
    ],
    "model": {
        "uretim_modeli": "GoalEngine (M10_ipf_kosullu), MODEL_VERSION/FEATURE_VERSION kayıtta",
        "surum_kohortu": ("model sürümü + özellik sürümü + eğitim verisi özeti + eğitim zamanı → kohort kimliği. "
                          "Yeniden eğitim yeni kohorttur; kohortlar birleştirilmez."),
        "referans": "Lig taban oranı: karar anından önceki son 3 tamamlanmış sezonun gerçekleşme oranı.",
    },
    "olcutler": [
        "log-kayıp ve Brier (model ve referans)",
        "ΔLL = model_log_kayip − referans_log_kayip (negatif model lehine), maç günü kümeli bootstrap %95 aralığı",
        "kalibrasyon eğimi/kesişimi ve güvenilirlik bölmeleri",
        "ekonomik değerlendirme yalnızca zamanı doğrulanmış (quoted_at < hedef karar anı) gerçek oranla; aksi halde "
        "ROI_UNAVAILABLE",
    ],
    "orneklem": ("Kohort × pazar için resmî değerlendirme koşulu: en az 300 sonuçlanmış tahmin ve en az 50 pozitif olay. "
                 "Karşılanmazsa sonuç 'yetersiz örneklem' olarak açıklanır."),
    "ara_rapor": "Ayda bir, yalnızca tanımlayıcı (sayılar, kapsam, kalibrasyon tablosu); hipotez testi ve durdurma yok.",
    "birincil_degerlendirme": ("2027-07-01 (2026/27 sezonu sonu). Örneklem eşiği karşılanmadıysa süre uzatılmaz; "
                               "sonuç açıklanır ve yeni protokol sürümü ayrıca başlatılabilir."),
    "durdurma": ("Yalnızca bütünlük nedenleriyle (kayıt zinciri bozulması, 30 günden uzun veri kesintisi, modelin "
                 "geçersiz ilanı). Olumlu veya olumsuz sonuç nedeniyle durdurma yok."),
    "aciklama": "Tüm kohortlar, ligler ve pazarlar sonuç ne olursa olsun raporlanır; başarılı alt kümeler seçilmez.",
    "veri_haklari": ("Model eğitim verisinin (football-data.co.uk / xgabora yedeği) kullanım hakkı belgeyle "
                     "doğrulanmadı; ölçüm kişisel analiz kapsamındadır ve bu durum raporlarda gösterilir."),
}

# Dondurma: gövdenin özeti ve gerçek sistem saatinden alınan dondurma anı (reports/kabul_s2_01/ altındaki JSON ile aynı).
PROTOCOL_FROZEN = {
    "dondurma_zamani_utc": "2026-10-10T11:52:58+00:00",
    "govde_sha256": "3946a6e2865f4ea5386156e20cb5ccb7ccd8a4c1520c3dc65fdd4e2a6814fddf",
}

LEAGUE_STALE_DAYS = 21
MIN_TEAM_MATCHES = 10
REFERENCE_SEASONS = 3
MIN_SETTLED = 300
MIN_POSITIVE = 50
N_BOOT = 1000


def protocol_sha256(body: dict | None = None) -> str:
    body = PROTOCOL_BODY if body is None else body
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def protocol_document() -> dict:
    """Depoya yazılan dondurulmuş protokol belgesi (gövde + özet + dondurma anı)."""
    return {"protokol": PROTOCOL_BODY, "govde_sha256": protocol_sha256(), **{k: v for k, v in PROTOCOL_FROZEN.items()
                                                                              if k != "govde_sha256"}}


def freeze_time() -> dt.datetime:
    return dt.datetime.fromisoformat(PROTOCOL_FROZEN["dondurma_zamani_utc"])


def decision_target(match_date) -> dt.datetime:
    """Hedef karar anı: maç günü 00:00 Europe/Istanbul (UTC'ye çevrilmiş, zaman dilimli)."""
    d = pd.Timestamp(match_date).date()
    return dt.datetime(d.year, d.month, d.day, tzinfo=ISTANBUL).astimezone(dt.timezone.utc)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ----------------------------------------------------------------------------
# Model kohortu ve referans
# ----------------------------------------------------------------------------

def model_cohort(engine) -> dict:
    """Model sürüm kimliği: aynı spesifikasyon yeniden eğitilse bile veri/zaman değişirse yeni kohort."""
    info = {"model_version": f"{MODEL_VERSION}/{getattr(engine, 'variant', '?')}", "feature_version": FEATURE_VERSION,
            "data_sha256": getattr(engine, "data_sha", ""), "trained_at": getattr(engine, "trained_at", ""),
            "data_cutoff": getattr(engine, "data_cutoff", "")}
    info["kohort"] = hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest()[:16]
    return info


def _season_year(d) -> int:
    t = pd.Timestamp(d)
    return t.year if t.month >= 7 else t.year - 1


def league_reference(matches: pd.DataFrame, league: str, before, seasons: int = REFERENCE_SEASONS) -> dict:
    """Lig taban oranı: ``before`` tarihinden önceki son ``seasons`` TAMAMLANMIŞ sezonun gerçekleşme oranı."""
    cur = _season_year(before)
    m = matches[(matches["league"] == league) & (pd.to_datetime(matches["date"]) < pd.Timestamp(before))]
    sy = pd.to_datetime(m["date"]).map(_season_year)
    m = m[(sy < cur) & (sy >= cur - seasons)]
    out = {}
    if m.empty:
        return {k: {"p": None, "n": 0} for k in PRIMARY_YES}
    lab = label_frame(m, PRIMARY_YES)
    for k in PRIMARY_YES:
        v = lab[k].dropna()
        out[k] = {"p": float(v.mean()) if len(v) else None, "n": int(len(v))}
    return out


# ----------------------------------------------------------------------------
# Uygunluk ve kayıt üretimi
# ----------------------------------------------------------------------------

@dataclass
class FreshnessCheck:
    stale: bool
    detail: str
    missing_played: int | None


def check_freshness(matches: pd.DataFrame, league: str, match_date, missing_played: int | None = None) -> FreshnessCheck:
    """Geçmiş verinin karar anına göre güncelliği.

    ``missing_played``: fikstür kaynağı oynanmış maçları da listeliyorsa, bu ligde veri deposunun son tarihinden sonra
    oynanmış ama depoda olmayan maç sayısı. Verilmezse ligin son kayıtlı maçı ile karar günü arasındaki gün sayısına
    bakılır (≤ ``LEAGUE_STALE_DAYS``)."""
    lm = matches[matches["league"] == league]
    if lm.empty:
        return FreshnessCheck(True, "ligde kayıtlı maç yok", missing_played)
    last = pd.Timestamp(lm["date"].max()).normalize()
    if missing_played is not None:
        if missing_played > 0:
            return FreshnessCheck(True, f"son kayıtlı lig maçı {last.date()}; fikstür kaynağına göre arada "
                                        f"{missing_played} oynanmış maç veride yok", missing_played)
        return FreshnessCheck(False, f"son kayıtlı lig maçı {last.date()}; fikstür kaynağına göre eksik oynanmış maç yok",
                              0)
    gap = (pd.Timestamp(match_date).normalize() - last).days
    if gap > LEAGUE_STALE_DAYS:
        return FreshnessCheck(True, f"son kayıtlı lig maçı {last.date()} ({gap} gün önce); arada oynanmış maç olup "
                                    "olmadığı doğrulanamıyor", None)
    return FreshnessCheck(False, f"son kayıtlı lig maçı {last.date()} ({gap} gün önce)", None)


def missing_played_openfootball(data: bytes, matches: pd.DataFrame, league: str) -> int | None:
    """openfootball sezon dosyasında, veri deposundaki son lig maçından SONRA oynanmış (skoru olan) maç sayısı.

    Bu maçlar tanım gereği veride yoktur → geçmiş veri güncel değildir. Dosya okunamazsa None (gün kuralına düşülür).
    """
    try:
        obj = json.loads(data.decode("utf-8-sig") if isinstance(data, bytes) else data)
    except (ValueError, UnicodeDecodeError):
        return None
    lm = matches[matches["league"] == league] if matches is not None else pd.DataFrame()
    last = pd.Timestamp(lm["date"].max()).normalize() if not lm.empty else pd.Timestamp("1900-01-01")
    n = 0
    for m in obj.get("matches", []):
        score = m.get("score")
        played = (bool(score.get("ft")) if isinstance(score, dict) else
                  (isinstance(score, list) and len(score) >= 2 and score[0] is not None and score[1] is not None))
        played = played or (m.get("score1") is not None and m.get("score2") is not None)
        d = pd.to_datetime(m.get("date"), errors="coerce")
        if played and pd.notna(d) and d.normalize() > last:
            n += 1
    return n


def _base_record(r, target: dt.datetime, cohort: dict, source_rights: str) -> dict:
    lg = LEAGUES.get(r.league)
    ko = kickoff_utc(r.date, getattr(r, "time", "") or "", getattr(r, "source", "") or "", lg.country if lg else "")
    return {
        "kayit_turu": RECORD_FORECAST, "protokol": PROTOCOL_VERSION, "protokol_sha256": protocol_sha256(),
        "event_id": event_id(r.league, r.date, r.home, r.away), "league": r.league, "home": r.home, "away": r.away,
        "mac_tarihi": str(pd.Timestamp(r.date).date()),
        "baslama_utc_kayitta": ko.isoformat() if ko else None, "baslama_saati_biliniyor": ko is not None,
        "decision_time": target.isoformat(), "hedef_karar_ani": target.isoformat(),
        "fikstur_kaynagi": getattr(r, "source", "") or "", "fikstur_kaynak_hak_durumu": source_rights,
        "model_version": cohort["model_version"], "feature_version": cohort["feature_version"],
        "model_kohort": cohort["kohort"], "model_egitim_zamani": cohort["trained_at"],
        "model_veri_sha256": cohort["data_sha256"], "data_cutoff": cohort["data_cutoff"],
        "stake_units": 0.0, "strategy_version": PROTOCOL_VERSION,
    }


def _no_forecast(base: dict, market: str, code: str, detail: str = "") -> dict:
    return {**base, "market_key": market, "p": None, "p_low": None, "p_high": None, "referans_p": None,
            "decision_status": STATUS_NO_FORECAST, "uygun": False,
            "reasons": [code] + ([detail] if detail else []), "veri_kalitesi": code, "oran": None,
            "ekonomik_statu": "TAHMIN_YOK"}


def _quote_block(ledger: Ledger | None, eid: str, market: str, target: dt.datetime) -> tuple[dict | None, str]:
    """Karar anından önceki en güncel gerçek oran (defterdeki zamanı doğrulanmış kayıtlar)."""
    if ledger is None:
        return None, "ORAN_YOK"
    q = ledger.latest_quote(eid, market, target)
    if q is None:
        return None, "ORAN_YOK"
    blk = {"decimal_odds": q.decimal_odds, "provider": q.provider, "bookmaker": q.bookmaker,
           "quoted_at": q.quoted_at.astimezone(dt.timezone.utc).isoformat(),
           "fetched_at": q.fetched_at.astimezone(dt.timezone.utc).isoformat(),
           "zaman_dogrulandi": bool(q.quoted_at < target)}
    return blk, ("ZAMANI_DOGRULANMIS_ORAN" if blk["zaman_dogrulandi"] else "HISTORICAL_REFERENCE_ONLY")


def build_forecast_records(engine, fixtures: pd.DataFrame, matches: pd.DataFrame, ledger: Ledger | None = None,
                           now: dt.datetime | None = None, missing_played: dict | None = None,
                           source_rights: dict | None = None) -> list[dict]:
    """Fikstürdeki her maç × A/B/C için kayıt sözlükleri üretir (yazmaz).

    ``missing_played``: {lig: eksik oynanmış maç sayısı} (fikstür kaynağı oynanmış maçları listeliyorsa).
    ``source_rights``: {fikstür kaynağı: hak durumu metni}.
    """
    if fixtures is None or fixtures.empty:
        return []
    now = now or _now()
    missing_played = missing_played or {}
    source_rights = source_rights or {}
    cohort = model_cohort(engine) if engine is not None else {"model_version": "-", "feature_version": FEATURE_VERSION,
                                                              "data_sha256": "", "trained_at": "", "data_cutoff": "",
                                                              "kohort": "-"}
    played = set()
    if matches is not None and not matches.empty:
        played = {event_id(a, b, c, d) for a, b, c, d in zip(matches["league"], matches["date"], matches["home"],
                                                             matches["away"])}
    freeze_day = freeze_time().astimezone(ISTANBUL).date()
    out: list[dict] = []
    for r in fixtures.itertuples(index=False):
        target = decision_target(r.date)
        base = _base_record(r, target, cohort, source_rights.get(getattr(r, "source", "") or "", "belirtilmedi"))
        code, detail = None, ""
        if now >= target:
            code = "PENCERE_KACIRILDI"
            detail = f"kayıt anı {now.isoformat(timespec='seconds')} ≥ hedef {target.isoformat()}"
        elif base["event_id"] in played:
            code = "MAC_SONUCU_BILINIYOR"
        elif pd.Timestamp(r.date).date() <= freeze_day:
            code = "PROTOKOLDEN_ONCE"
        elif engine is None or not getattr(engine, "trained", False):
            code = "MODEL_YOK"
        elif r.league not in getattr(engine, "states", {}):
            code = "LIG_MODEL_KAPSAMI_DISI"
        else:
            fr = check_freshness(matches, r.league, r.date, missing_played.get(r.league))
            base["veri_guncellik"] = fr.detail
            if fr.stale:
                code, detail = "VERI_GUNCEL_DEGIL", fr.detail
        if code is not None:
            out.extend(_no_forecast(base, k, code, detail) for k in PRIMARY_YES)
            continue
        pred = engine.predict_fixtures(pd.DataFrame([r._asdict()]), with_interval=True)
        if not pred:
            out.extend(_no_forecast(base, k, "LIG_MODEL_KAPSAMI_DISI") for k in PRIMARY_YES)
            continue
        pr = pred[0]
        if any("hesaplanamadı" in n or "son 365 günde" in n for n in pr.data_notes):
            out.extend(_no_forecast(base, k, "TAKIM_GECMISI_YETERSIZ", "; ".join(pr.data_notes)) for k in PRIMARY_YES)
            continue
        ref = league_reference(matches, r.league, pd.Timestamp(r.date))
        for k in PRIMARY_YES:
            p = pr.p(k)
            if not (isinstance(p, float) and math.isfinite(p) and 0.0 < p < 1.0):
                out.append(_no_forecast(base, k, "OLASILIK_GECERSIZ"))
                continue
            lo, hi = pr.interval(k)
            quote, econ = _quote_block(ledger, base["event_id"], k, target)
            out.append({**base, "market_key": k, "p": float(p), "p_low": lo, "p_high": hi,
                        "referans_p": ref[k]["p"], "referans_n": ref[k]["n"], "decision_status": STATUS_FORECAST,
                        "uygun": True, "reasons": [], "veri_kalitesi": "UYGUN", "veri_notlari": list(pr.data_notes),
                        "oran": quote, "ekonomik_statu": econ})
    return out


def _existing_keys(ledger: Ledger) -> set[tuple]:
    keys = set()
    for rec in ledger.predictions():
        if rec.get("kayit_turu") == RECORD_FORECAST:
            keys.add((rec["event_id"], rec["market_key"], rec.get("protokol"), rec.get("model_kohort")))
    return keys


def record_forecasts(ledger: Ledger, records: list[dict]) -> dict:
    """Kayıtları değişmez deftere yazar. Aynı (maç, pazar, protokol, kohort) ikinci kez yazılmaz.

    Yazma anında saat yeniden kontrol edilir: hedef karar anı geçmişse olasılık yazılmaz (PENCERE_KACIRILDI)."""
    existing = _existing_keys(ledger)
    written, skipped, late = 0, 0, 0
    ids = []
    for rec in records:
        key = (rec["event_id"], rec["market_key"], rec.get("protokol"), rec.get("model_kohort"))
        if key in existing:
            skipped += 1
            continue
        target = dt.datetime.fromisoformat(rec["hedef_karar_ani"])
        if rec.get("p") is not None and _now() >= target:
            base = {k: v for k, v in rec.items() if k not in ("p", "p_low", "p_high", "referans_p", "oran")}
            rec = _no_forecast(base, rec["market_key"], "PENCERE_KACIRILDI", "yazma anında hedef karar anı geçmişti")
            late += 1
        ids.append(ledger.record_prediction(rec))
        existing.add(key)
        written += 1
    return {"yazilan": written, "atlanan_mukerrer": skipped, "gec_kalan": late, "kimlikler": ids}


def invalidate_forecast(ledger: Ledger, forecast_id: str, reason: str) -> str:
    """Bir tahmini geçersiz ilan eden AYRI kayıt ekler (orijinal kayıt değişmez)."""
    if not reason:
        raise ValueError("Geçersiz ilan için gerekçe zorunlu")
    target = next((r for r in ledger.predictions() if r["id"] == forecast_id), None)
    if target is None or target.get("kayit_turu") != RECORD_FORECAST:
        raise KeyError(forecast_id)
    return ledger.record_prediction({
        "kayit_turu": RECORD_INVALIDATION, "gecersiz_ilan_edilen": forecast_id, "gerekce": reason,
        "event_id": target["event_id"], "market_key": target["market_key"], "decision_time": target["decision_time"],
        "model_version": target["model_version"], "feature_version": target["feature_version"],
        "data_cutoff": target["data_cutoff"], "p": None, "decision_status": "GECERSIZ_ILAN", "reasons": [reason],
        "stake_units": 0.0, "strategy_version": PROTOCOL_VERSION, "protokol": target.get("protokol"),
        "model_kohort": target.get("model_kohort"),
    })


# ----------------------------------------------------------------------------
# Değerlendirme (kohort × pazar; kohortlar birleştirilmez)
# ----------------------------------------------------------------------------

def _ll(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    return -(y * np.log(p) + (1 - y) * np.log1p(-p))


def _cluster_boot(diff: np.ndarray, clusters: np.ndarray, reps: int = N_BOOT, seed: int = 20261010) -> tuple[float, float]:
    _, inv = np.unique(clusters, return_inverse=True)
    s = np.bincount(inv, weights=diff)
    c = np.bincount(inv)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(s), size=(reps, len(s)))
    boot = s[draws].sum(axis=1) / c[draws].sum(axis=1)
    return float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))


def evaluate_forecasts(ledger: Ledger) -> dict:
    """Sonuçlanmış FORECAST_RECORD kayıtlarının kohort × pazar değerlendirmesi ve kapsam sayıları."""
    recs = ledger.predictions()
    invalid = {r["gecersiz_ilan_edilen"] for r in recs if r.get("kayit_turu") == RECORD_INVALIDATION}
    fc = [r for r in recs if r.get("kayit_turu") == RECORD_FORECAST]
    coverage: dict[str, int] = {}
    for r in fc:
        k = STATUS_FORECAST if r.get("decision_status") == STATUS_FORECAST else (r.get("reasons") or ["?"])[0]
        coverage[k] = coverage.get(k, 0) + 1
    groups: dict[tuple, list] = {}
    for r in fc:
        if r.get("decision_status") != STATUS_FORECAST or r.get("p") is None:
            continue
        groups.setdefault((r.get("model_kohort"), r["market_key"]), []).append(r)
    out = []
    for (cohort, market), rows in sorted(groups.items()):
        for excl in (False, True):
            use = [r for r in rows if not (excl and r["id"] in invalid)]
            settled = [r for r in use if r.get("outcome") and r["outcome"].get("label") in ("TRUE", "FALSE")]
            rec = {"kohort": cohort, "pazar": market, "gecersiz_ilanlar_haric": excl, "kayit": len(use),
                   "sonuclanan": len(settled)}
            if settled:
                y = np.array([1.0 if r["outcome"]["label"] == "TRUE" else 0.0 for r in settled])
                p = np.array([r["p"] for r in settled], dtype=float)
                rec.update({"pozitif": int(y.sum()), "log_kayip": float(_ll(y, p).mean()),
                            "brier": float(np.mean((p - y) ** 2))})
                ref_ok = np.array([r.get("referans_p") is not None for r in settled])
                if ref_ok.any():
                    pr = np.array([r["referans_p"] for r in settled if r.get("referans_p") is not None], dtype=float)
                    d = _ll(y[ref_ok], p[ref_ok]) - _ll(y[ref_ok], pr)
                    days = np.array([r["mac_tarihi"] for r in settled if r.get("referans_p") is not None])
                    lo, hi = _cluster_boot(d, days) if len(np.unique(days)) > 1 else (float("nan"), float("nan"))
                    rec.update({"delta_ll_model_eksi_referans": float(d.mean()), "delta_ll_alt": lo, "delta_ll_ust": hi,
                                "delta_ll_tanimi": "model − referans (negatif model lehine)"})
                verified = [r for r in settled if (r.get("oran") or {}).get("zaman_dogrulandi")]
                rec["zamani_dogrulanmis_oranli"] = len(verified)
                rec["ekonomik_statu"] = "HESAPLANABILIR" if verified else "ROI_UNAVAILABLE"
                rec["resmi_degerlendirme_esigi"] = bool(len(settled) >= MIN_SETTLED and y.sum() >= MIN_POSITIVE)
            else:
                rec["resmi_degerlendirme_esigi"] = False
            out.append(rec)
    return {"protokol": PROTOCOL_VERSION, "kapsam": coverage, "kohort_pazar": out,
            "not": ("Kohortlar birleştirilmez. Eşik karşılanmadan yapılan sayımlar yalnızca tanımlayıcıdır. Oran zamanı "
                    "doğrulanmamış kayıtlar ekonomik doğrulamaya girmez.")}

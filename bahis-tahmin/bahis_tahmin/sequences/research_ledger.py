"""Dizi araştırması için ileriye dönük sanal takip defteri (sözleşme §5 "İleriye dönük", §9 ``PAPER_TRADING``).

* ``goals.ledger.Ledger`` yeniden kullanılır (SQLite, yalnızca ekleme, özet zinciri) ama AYRI bir dosyadadır
  (varsayılan ``dizi_arastirma.sqlite``); ana sanal takip defterine (``gol_pazarlari.sqlite``) yazılmaz, karar
  motoruna bağlanmaz. Bütün kayıtlar sanaldır: stake 0.
* Tahmin yalnızca karar zamanından (maç günü 00:00 Europe/Istanbul, çağıran verir) ÖNCE kaydedilebilir; zaman
  dilimsiz veya geç zaman reddedilir. Gerçek kayıt anı (saat) da karar zamanından önce olmalıdır (geriye tarihleme
  engeli). Yalnızca sözleşme tarihinden sonra oynanan maçlar ileriye dönük sayılır.
* Değerlendirme noktası: ≥ ``config.PAPER_MIN_ROWS`` nitelikli takım satırı veya ``config.PAPER_MAX_SEASONS`` sezon
  (önce gelen). Kural, test dönemiyle aynıdır: S0 + gösterge log-kaybı S0'dan düşük, lig-sezon kümeli bootstrap üst
  sınırı < 0 ve tek yönlü p < α/k. Başarısızsa ``NO_ADDED_VALUE``; uzatma yoktur (noktadan sonraki satırlar
  kullanılmaz).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from typing import Callable

import numpy as np
from scipy.stats import norm

from ..goals.ledger import Ledger
from ..timeutil import ISTANBUL, now_utc
from . import config as C

DEFAULT_NAME = "dizi_arastirma.sqlite"
LEDGER_KIND = "dizi_arastirma"
MAIN_LEDGER_NAMES = ("gol_pazarlari.sqlite",)  # ana sanal takip defteri; araştırma kayıtları oraya yazılmaz
RECORD_STATUS = "PAPER_TRADING"
LABEL_DELAY = dt.timedelta(days=1)  # label_known_at = maç günü + 1 (aynı maç hedefi; sözleşme §4)
OUTCOME_KNOWN, OUTCOME_UNKNOWN, OUTCOME_PENDING = "BILINIYOR", "BILINMIYOR", "BEKLIYOR"
PRIOR_STATUSES = ("OUT_OF_SAMPLE_SUPPORTED", "PAPER_TRADING")


# ----------------------------------------------------------------------------
# Zaman yardımcıları
# ----------------------------------------------------------------------------

def decision_time_for(match_date) -> dt.datetime:
    """Karar zamanı = maç günü 00:00 (Europe/Istanbul)."""
    d = match_date if isinstance(match_date, dt.date) and not isinstance(match_date, dt.datetime) else None
    if d is None:
        d = dt.date.fromisoformat(str(match_date)[:10])
    return dt.datetime(d.year, d.month, d.day, tzinfo=ISTANBUL)


def _aware(name: str, t) -> dt.datetime:
    if isinstance(t, str):
        t = dt.datetime.fromisoformat(t)
    if not isinstance(t, dt.datetime):
        raise ValueError(f"{name} bir datetime olmalı")
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError(f"{name} zaman dilimi bilgisi içermeli (zaman dilimsiz zaman reddedilir)")
    return t


def _local_date(t: dt.datetime) -> dt.date:
    return t.astimezone(ISTANBUL).date()


def _season_year(d: dt.date) -> int:
    return d.year if d.month >= 7 else d.year - 1


def _parse_season(s) -> int:
    if isinstance(s, (int, np.integer)) and not isinstance(s, bool):
        return int(s)
    txt = str(s).strip()
    if len(txt) >= 4 and txt[:4].isdigit():
        return int(txt[:4])
    raise ValueError(f"Sezon anlaşılamadı: {s!r} (ör. 2026 veya '2026/27')")


def _forward_from() -> dt.date:
    return dt.date.fromisoformat(C.FORWARD_FROM)


def _prob(name: str, v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} sayı olmalı") from None
    if not (math.isfinite(f) and 0.0 < f < 1.0):
        raise ValueError(f"{name} (0, 1) aralığında olmalı")
    return f


def _text(name: str, v) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{name} boş olmayan metin olmalı")
    return v


# ----------------------------------------------------------------------------
# Defter
# ----------------------------------------------------------------------------

class ResearchLedger:
    """Dizi örüntüleri için ayrı, yalnızca eklemeli ileriye dönük tahmin defteri.

    ``path``: dizin (içinde ``dizi_arastirma.sqlite`` kullanılır) veya dosya yolu. ``clock``: zaman dilimli şimdiki
    zamanı döndüren işlev (test için; varsayılan gerçek UTC saati).
    """

    def __init__(self, path: Path, clock: Callable[[], dt.datetime] | None = None):
        p = Path(path)
        if p.is_dir() or p.suffix == "":
            p = p / DEFAULT_NAME
        if p.name in MAIN_LEDGER_NAMES:
            raise ValueError("Araştırma defteri ana sanal takip defteriyle aynı dosyayı kullanamaz")
        self.path = p
        self._clock = clock or now_utc
        self._ledger = Ledger(p)
        conn = self._ledger.conn
        kind = conn.execute("SELECT value FROM meta WHERE key='ledger_kind'").fetchone()
        n_pred = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        if kind is None and n_pred:
            self._ledger.close()
            raise ValueError("Bu dosya başka bir defter (araştırma defteri değil)")
        if kind is not None and kind[0] != LEDGER_KIND:
            self._ledger.close()
            raise ValueError(f"Bu dosya başka türde bir defter: {kind[0]}")
        with conn:
            conn.execute("INSERT OR IGNORE INTO meta VALUES ('ledger_kind', ?)", (LEDGER_KIND,))

    def close(self) -> None:
        self._ledger.close()

    def verify_chain(self) -> tuple[bool, str]:
        return self._ledger.verify_chain()

    def _now(self) -> dt.datetime:
        return _aware("clock()", self._clock())

    # ---------------------------------------------------------------- kayıt
    def record_forecast(self, pattern_id: str, event_id: str, target: str, decision_time: dt.datetime,
                        created_at: dt.datetime, p0: float, p_pattern: float, contract_version: str, config_hash: str,
                        s0_model_hash: str, *, is_home: bool, league: str, season: str, note: str = "") -> str:
        """Maç öncesi sanal tahmin kaydı (stake 0). Kimlik döner.

        Reddedilir (ValueError): zaman dilimsiz ``created_at``/``decision_time``; ``created_at >= decision_time``;
        gerçek kayıt anı ``decision_time``'dan sonra; ``decision_time`` maç günü 00:00 (İstanbul) değil; maç
        sözleşme tarihinden sonra değil; farklı sözleşme/parametre özeti; aynı (örüntü, olay, hedef, taraf) tekrar.
        """
        for name, v in (("pattern_id", pattern_id), ("event_id", event_id), ("target", target),
                        ("s0_model_hash", s0_model_hash), ("league", league), ("season", season)):
            _text(name, v)
        if not isinstance(is_home, (bool, np.bool_)):
            raise ValueError("is_home True/False olmalı")
        created_at = _aware("created_at", created_at)
        decision_time = _aware("decision_time", decision_time)
        loc = decision_time.astimezone(ISTANBUL)
        if (loc.hour, loc.minute, loc.second, loc.microsecond) != (0, 0, 0, 0):
            raise ValueError("decision_time maç günü 00:00 (Europe/Istanbul) olmalı")
        if contract_version != C.CONTRACT_VERSION or config_hash != C.config_hash():
            raise ValueError("Sözleşme sürümü veya parametre özeti güncel değil; yeni deney kaydı gerekir")
        if created_at >= decision_time:
            raise ValueError("Geç kayıt reddedildi: created_at karar zamanından (maç günü 00:00) önce olmalı")
        now = self._now()
        if now >= decision_time:
            raise ValueError("Geç kayıt reddedildi: kayıt anı karar zamanından sonra (geriye tarihleme yapılamaz)")
        if created_at > now:
            raise ValueError("created_at gelecekte olamaz")
        match_date = loc.date()
        if match_date <= _forward_from():
            raise ValueError(f"İleriye dönük takip yalnızca {C.FORWARD_FROM} sonrasında oynanan maçlar içindir")
        p0f, ppf = _prob("p0", p0), _prob("p_pattern", p_pattern)
        key = (pattern_id, event_id, target, bool(is_home))
        if any((r["pattern_id"], r["event_id"], r["target"], bool(r["is_home"])) == key for r in self._forecasts()):
            raise ValueError("Bu örüntü/olay/hedef/taraf için tahmin zaten kayıtlı (değiştirilemez)")
        record = {
            "kind": LEDGER_KIND, "event_id": event_id, "market_key": f"DIZI:{target}",
            "decision_time": decision_time.astimezone(dt.timezone.utc).isoformat(),
            "model_version": f"S0+{pattern_id}", "feature_version": contract_version,
            "data_cutoff": decision_time.astimezone(dt.timezone.utc).isoformat(),
            "p": ppf, "decision_status": RECORD_STATUS,
            "reasons": ["ileriye dönük sanal takip (araştırma); stake 0"], "stake_units": 0,
            "strategy_version": config_hash,
            "pattern_id": pattern_id, "target": target, "is_home": bool(is_home), "p0": p0f, "p_pattern": ppf,
            "forecast_created_at": created_at.astimezone(dt.timezone.utc).isoformat(),
            "contract_version": contract_version, "config_hash": config_hash, "s0_model_hash": s0_model_hash,
            "league": league, "season": season, "cluster": f"{league}|{season}",
            "match_date": match_date.isoformat(), "season_year": _season_year(match_date), "virtual": True,
            "note": note,
        }
        return self._ledger.record_prediction(record)

    def record_outcome(self, forecast_id: str, y, source: str, note: str = "") -> None:
        """Gerçekleşen hedef (1/0; bilinmiyorsa None). Yalnızca label_known_at (maç günü + 1) sonrasında."""
        _text("source", source)
        rec = next((r for r in self._forecasts() if r["id"] == forecast_id), None)
        if rec is None:
            raise KeyError(forecast_id)
        known_at = dt.datetime.fromisoformat(rec["decision_time"]) + LABEL_DELAY
        if self._now() < known_at:
            raise ValueError("Sonuç, hedefin bilindiği andan (maç günü + 1, 00:00) önce kaydedilemez")
        if y is None:
            settlement, label = OUTCOME_UNKNOWN, "UNKNOWN"
        else:
            f = float(y)
            if f not in (0.0, 1.0):
                raise ValueError("y 0, 1 veya None olmalı")
            settlement, label = OUTCOME_KNOWN, str(int(f))
        self._ledger.record_outcome(forecast_id, settlement, label, source, note)

    # ------------------------------------------------------------- okuma
    def _forecasts(self) -> list[dict]:
        return [r for r in self._ledger.predictions() if r.get("kind") == LEDGER_KIND]

    def records_with_outcomes(self, pattern_id: str | None = None) -> list[dict]:
        """``paper_evaluation`` girdisi: tahmin alanları + ``outcome_state`` ve ``y`` (1.0/0.0/None)."""
        out = []
        for r in self._forecasts():
            if pattern_id is not None and r["pattern_id"] != pattern_id:
                continue
            oc = r.get("outcome")
            if oc is None:
                state, y = OUTCOME_PENDING, None
            elif oc["settlement"] == OUTCOME_KNOWN:
                state, y = OUTCOME_KNOWN, float(oc["label"])
            else:
                state, y = OUTCOME_UNKNOWN, None
            out.append({k: r[k] for k in (
                "id", "created_at", "pattern_id", "event_id", "target", "is_home", "decision_time",
                "forecast_created_at", "p0", "p_pattern", "contract_version", "config_hash", "s0_model_hash",
                "league", "season", "cluster", "match_date")} | {"outcome_state": state, "y": y})
        return out

    def evaluate(self, pattern_id: str, start_season, **kw) -> dict:
        return paper_evaluation(self.records_with_outcomes(pattern_id), start_season, pattern_id=pattern_id, **kw)


# ----------------------------------------------------------------------------
# Değerlendirme
# ----------------------------------------------------------------------------

def _log_loss(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    return -(y * np.log(p) + (1.0 - y) * np.log1p(-p))


def _cluster_bootstrap(diff: np.ndarray, clusters: np.ndarray, reps: int, seed: int) -> np.ndarray:
    """Lig-sezon kümeleri yerine koymalı yeniden örneklenir; ortalama farkın bootstrap dağılımı."""
    _, inv = np.unique(clusters, return_inverse=True)
    s = np.bincount(inv, weights=diff)
    c = np.bincount(inv).astype(float)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(s), size=(reps, len(s)))
    return s[draws].sum(axis=1) / c[draws].sum(axis=1)


def _classify(rec: dict, start: int, seen: set) -> tuple[str, dict | None]:
    """Satırı sınıflar: 'nitelikli' veya dışlama nedeni. Nitelikli satır için çözümlenmiş alanlar döner."""
    try:
        dtime = _aware("decision_time", rec["decision_time"])
        fca = _aware("forecast_created_at", rec["forecast_created_at"])
        lca = _aware("created_at", rec["created_at"]) if rec.get("created_at") else None
    except (KeyError, ValueError):
        return "gecersiz_zaman", None
    mdate = _local_date(dtime)
    info = {"decision_time": dtime, "match_date": mdate, "season_year": _season_year(mdate)}
    if rec.get("contract_version") != C.CONTRACT_VERSION or rec.get("config_hash") != C.config_hash():
        return "farkli_surum", info
    if fca >= dtime or (lca is not None and lca >= dtime):
        return "gec_kayit", info
    if mdate <= _forward_from():
        return "ileriye_donuk_degil", info
    if info["season_year"] < start:
        return "baslangic_oncesi", info
    try:
        info["p0"], info["pp"] = _prob("p0", rec["p0"]), _prob("p_pattern", rec["p_pattern"])
    except (KeyError, ValueError):
        return "gecersiz_olasilik", info
    key = (rec.get("pattern_id"), rec.get("event_id"), rec.get("target"), bool(rec.get("is_home")))
    if key in seen:
        return "tekrar", info
    seen.add(key)
    state = rec.get("outcome_state")
    y = rec.get("y")
    if state == OUTCOME_PENDING or (state is None and y is None):
        return "bekleyen", info
    if state == OUTCOME_UNKNOWN or y is None:
        return "sonuc_bilinmiyor", info
    if float(y) not in (0.0, 1.0):
        return "gecersiz_sonuc", info
    info["y"] = float(y)
    info["cluster"] = str(rec.get("cluster") or f"{rec.get('league')}|{rec.get('season')}")
    info["id"] = str(rec.get("id") or f"{key[0]}|{key[1]}|{key[2]}|{int(key[3])}")
    info["sort"] = (mdate, dtime, str(rec.get("event_id")), str(rec.get("target")), bool(rec.get("is_home")))
    return "nitelikli", info


def _created_key(rec: dict) -> tuple[float, str]:
    try:
        t = _aware("forecast_created_at", rec.get("forecast_created_at")).timestamp()
    except (TypeError, ValueError):
        t = math.inf
    return t, str(rec.get("id"))


def _as_of_date(as_of) -> dt.date:
    """Sezon kuralı için gün: saf tarih / 'YYYY-MM-DD' olduğu gibi; zaman dilimli an → İstanbul tarihi."""
    if isinstance(as_of, str) and len(as_of.strip()) == 10:
        return dt.date.fromisoformat(as_of.strip())
    if isinstance(as_of, (dt.datetime, str)):
        return _local_date(_aware("as_of", as_of))
    if isinstance(as_of, dt.date):
        return as_of
    raise ValueError("as_of tarih veya zaman dilimli datetime olmalı")


def paper_evaluation(records_with_outcomes: list[dict], start_season, *, pattern_id: str | None = None,
                     as_of=None, k_family: int = 1, n_boot: int = 1000, seed: int = C.SEED,
                     prior_status: str = "OUT_OF_SAMPLE_SUPPORTED") -> dict:
    """İleriye dönük takip değerlendirmesi (tek örüntü).

    Değerlendirme noktası (önce gelen): nitelikli satır sayısının ``config.PAPER_MIN_ROWS``'a ulaştığı maç günü
    (o günün tüm satırları dahil) veya ``start_season``'dan itibaren ``config.PAPER_MAX_SEASONS`` sezonun bittiği
    1 Temmuz. Noktadan sonraki satırlar KULLANILMAZ (uzatma yok); noktadan önce sonucu beklenen satır varsa
    değerlendirme bekler. ``as_of`` (tarih/zaman dilimli an): sezon kuralı için bugünün tarihi; verilmezse kayıtlardaki
    en geç maç günü (tekrarlanabilir). ``k_family``: ileriye dönük takipteki örüntü sayısı (Holm'un ilk adımı α/k).

    Başarı kuralı (test dönemiyle aynı): ortalama log-kayıp farkı (örüntü − S0) < 0, lig-sezon kümeli bootstrap
    %95 üst sınırı < 0 ve tek yönlü p < α/k. Sonuç: ``PAPER_TRADING`` (sürüyor ya da başarılı; ``succeeded``
    bayrağıyla) veya başarısızlıkta ``NO_ADDED_VALUE``.
    """
    if prior_status not in PRIOR_STATUSES:
        raise ValueError("İleriye dönük takip yalnızca OUT_OF_SAMPLE_SUPPORTED örüntüler içindir")
    if n_boot < 1000:
        raise ValueError("Sözleşme gereği bootstrap tekrar sayısı en az 1000 olmalı")
    if int(k_family) != k_family or k_family < 1:
        raise ValueError("k_family pozitif tam sayı olmalı")
    start = _parse_season(start_season)
    fwd_season = _season_year(_forward_from())
    if start < fwd_season:
        raise ValueError(f"İleriye dönük takip en erken {fwd_season} sezonunda başlar")
    recs = list(records_with_outcomes)
    pids = sorted({str(r.get("pattern_id")) for r in recs})
    if pattern_id is None:
        if len(pids) > 1:
            raise ValueError(f"Birden fazla örüntü var ({pids}); pattern_id verin")
        pattern_id = pids[0] if pids else None
    recs = [r for r in recs if str(r.get("pattern_id")) == str(pattern_id)]
    alpha_level = C.ALPHA / int(k_family)
    season_end = dt.date(start + C.PAPER_MAX_SEASONS, 7, 1)

    excluded: dict[str, int] = {}
    qual, pending_dates, all_dates = [], [], []
    seen: set = set()
    for r in sorted(recs, key=_created_key):  # tekrar eden tahminde en erken kayıt tutulur
        cls, info = _classify(r, start, seen)
        if info is not None:
            all_dates.append(info["match_date"])
        if cls == "nitelikli":
            qual.append(info)
            continue
        excluded[cls] = excluded.get(cls, 0) + 1
        if cls == "bekleyen":
            pending_dates.append(info["match_date"])
    window = sorted((q for q in qual if q["match_date"] < season_end), key=lambda q: q["sort"])
    after_window = sum(1 for q in qual if q["match_date"] >= season_end)

    trigger, point = None, None
    count = 0
    for k, q in enumerate(window):
        count += 1
        last_of_day = k + 1 == len(window) or window[k + 1]["match_date"] != q["match_date"]
        if last_of_day and count >= C.PAPER_MIN_ROWS:
            trigger, point = "satir", q["match_date"]
            break
    if trigger is None:
        if as_of is not None:
            today = _as_of_date(as_of)
        else:
            today = max(all_dates) if all_dates else None
        if today is not None and today >= season_end:
            trigger, point = "sezon", season_end - dt.timedelta(days=1)

    base = {
        "pattern_id": pattern_id, "start_season": start, "season_end": season_end.isoformat(),
        "min_rows": C.PAPER_MIN_ROWS, "max_seasons": C.PAPER_MAX_SEASONS, "n_records": len(recs),
        "n_qualifying_in_window": len(window), "n_qualifying_after_window": after_window,
        "excluded": dict(sorted(excluded.items())), "alpha_level": alpha_level, "k_family": int(k_family),
        "no_extension": True, "contract": C.CONTRACT_VERSION, "config_hash": C.config_hash(),
        "note": "Varsayımsal/sanal takip (stake 0); değerlendirme noktasından sonra uzatma yoktur.",
    }
    if trigger is None:
        return {**base, "status": "PAPER_TRADING", "evaluation_point_reached": False, "succeeded": None,
                "trigger": None, "evaluation_point": None,
                "reason": (f"Değerlendirme noktasına ulaşılmadı: {len(window)}/{C.PAPER_MIN_ROWS} nitelikli satır, "
                           f"sezon sınırı {season_end.isoformat()}.")}
    waiting = sum(1 for d in pending_dates if d <= point)
    if waiting:
        return {**base, "status": "PAPER_TRADING", "evaluation_point_reached": False, "succeeded": None,
                "trigger": trigger, "evaluation_point": point.isoformat(), "waiting_outcomes": waiting,
                "reason": f"Değerlendirme noktasından önceki {waiting} tahminin sonucu bekleniyor."}

    used = [q for q in window if q["match_date"] <= point]
    rows_hash = hashlib.sha256(json.dumps(sorted(q["id"] for q in used)).encode()).hexdigest()
    res = {**base, "evaluation_point_reached": True, "trigger": trigger, "evaluation_point": point.isoformat(),
           "n_used": len(used), "n_not_used_after_point": len(window) - len(used) + after_window,
           "rows_sha256": rows_hash, "reps": int(n_boot), "seed": int(seed)}
    clusters = np.array([q["cluster"] for q in used], dtype=object)
    n_clusters = int(len(np.unique(clusters))) if len(used) else 0
    res["n_clusters"] = n_clusters
    if len(used) == 0 or n_clusters < 2:
        return {**res, "status": "NO_ADDED_VALUE", "succeeded": False,
                "reason": ("Değerlendirme noktasında yeterli nitelikli satır/küme yok; katkı gösterilemedi "
                           "(uzatma yok).")}
    y = np.array([q["y"] for q in used])
    p0 = np.array([q["p0"] for q in used])
    pp = np.array([q["pp"] for q in used])
    lp, l0 = _log_loss(y, pp), _log_loss(y, p0)
    diff = lp - l0
    boot = _cluster_bootstrap(diff, clusters, int(n_boot), int(seed))
    d = float(diff.mean())
    se = float(np.std(boot, ddof=1))
    p_one = float(norm.cdf(d / se)) if se > 0 else float("nan")
    ci_lo, ci_hi = float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))
    succeeded = bool(d < 0 and ci_hi < 0 and np.isfinite(p_one) and p_one < alpha_level)
    res.update({
        "ll_pattern": float(lp.mean()), "ll_s0": float(l0.mean()), "diff": d, "ci_lo": ci_lo, "ci_hi": ci_hi,
        "se": se, "p_one_sided": p_one, "brier_pattern": float(((pp - y) ** 2).mean()),
        "brier_s0": float(((p0 - y) ** 2).mean()), "base_rate": float(y.mean()), "s0_expected": float(p0.sum()),
        "observed": float(y.sum()), "succeeded": succeeded,
        "status": "PAPER_TRADING" if succeeded else "NO_ADDED_VALUE",
        "reason": ("İleriye dönük dönemde S0 + gösterge log-kaybı S0'dan anlamlı düşük (bootstrap üst sınır < 0, "
                   f"tek yönlü p < {alpha_level:g})." if succeeded else
                   "İleriye dönük dönemde log-kayıp katkısı doğrulanmadı; uzatma yok."),
    })
    assert res["status"] in C.STATUSES
    return res

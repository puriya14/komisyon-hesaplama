"""Tek ligde gerçek veri pilotu (S4-PILOT-01): openfootball sonuçlarıyla İngiltere Premier League (E0).

Akış: kaynak (sabit commit) → sonuç ayrıştırma ve karantina → köken kaydı → takım kimliği → takvim kapsamı →
mevcut gol motoruyla ayrı pilot eğitimi → ortak veri uygunluk kontrolü → ayrı pilot defterine A/B/C kaydı.

Bütün yazmalar YALNIZCA açıkça verilen pilot klasörüne yapılır. Klasör kullanıcının uygulama veri klasörüyle aynı
olamaz, onu içeremez veya onun içinde olamaz; boş olmayan ve pilot işareti (``pilot.json``) taşımayan klasöre
yazılmaz. Mevcut veri deposu, defter, model ve ayarlar okunmaz/değiştirilmez. Yeni tahmin motoru yoktur: mevcut
``GoalEngine``, ``eligibility`` ve ``forecast_log`` kullanılır. Gerçek oran yoktur; bahis adayı ve stake üretilmez.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import app_home_path
from .data.leagues import LEAGUES, openfootball_season, season_label, season_start_year
from .data.parsers import (
    OPENFOOTBALL_RESULT_LABEL,
    OPENFOOTBALL_RESULT_PARSER,
    parse_openfootball_results,
)
from .data.provenance import OPENFOOTBALL_REPO, SourceFile, rows_sha256, verified_labels, verify_results
from .timeutil import ISTANBUL

PILOT_VERSION = "s4-pilot-v1"
PILOT_LEAGUE = "E0"
MARKER = "pilot.json"
MAX_SEASON_FILES = 17
RAW_BASE = "https://raw.githubusercontent.com/openfootball/football.json"
COMMITS_API = "https://api.github.com/repos/openfootball/football.json/commits/master"
GOAL_ENGINE_FILE = "goal_engine.joblib"
LEDGER_FILE = "gol_pazarlari.sqlite"
MODEL_INFO = "pilot_model.json"
PARTICIPANTS_COPY = "referans/katilimcilar.json"
SOURCE_RIGHTS = {"openfootball": "CC0 1.0 (openfootball/football.json LICENSE.md; doğruluk garantisi ve üçüncü kişi "
                                 "hakları kapsamı dışında)"}
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class PilotError(RuntimeError):
    """Pilot işlemi güvenli biçimde yapılamıyor (yol, kaynak veya hak sorunu)."""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ----------------------------------------------------------------------------
# Yalıtılmış pilot klasörü
# ----------------------------------------------------------------------------

def check_pilot_dir(home, create: bool = False) -> Path:
    """Pilot klasörünü doğrular (ve ``create`` ise oluşturur). Kullanıcı uygulama klasörüyle çakışırsa reddeder."""
    if home is None or not str(home).strip():
        raise PilotError("Pilot klasörü açıkça verilmeli (--ev).")
    path = Path(home).expanduser().resolve()
    user = app_home_path().expanduser().resolve()
    if path == user or user in path.parents or path in user.parents:
        raise PilotError(f"Pilot klasörü kullanıcı uygulama klasörüyle çakışıyor ({user}); ayrı bir klasör verin.")
    if path.exists() and not path.is_dir():
        raise PilotError(f"{path} bir klasör değil.")
    if path.exists() and any(path.iterdir()) and not (path / MARKER).is_file():
        raise PilotError(f"{path} boş değil ve pilot işareti ({MARKER}) taşımıyor; başka verinin üzerine yazılmaz.")
    if create:
        path.mkdir(parents=True, exist_ok=True)
        if not (path / MARKER).is_file():
            (path / MARKER).write_text(json.dumps({"pilot": PILOT_VERSION, "lig": PILOT_LEAGUE,
                                                   "olusturma_utc": _now().isoformat(timespec="seconds")},
                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    elif not (path / MARKER).is_file():
        raise PilotError(f"{path} hazırlanmış bir pilot klasörü değil (önce pilot-hazirla).")
    return path


def _store(home: Path):
    from .data.store import DataStore

    st = DataStore(home)
    if not st.load():
        raise PilotError("Pilot veri deposu yok veya okunamadı (önce pilot-hazirla).")
    return st


# ----------------------------------------------------------------------------
# Kaynak: sabit commit, sezon dosyaları
# ----------------------------------------------------------------------------

def pilot_seasons(today: dt.date, completed: int) -> list[str]:
    """İçinde bulunulan sezon + önceki ``completed`` tamamlanmış sezonun openfootball klasör adları."""
    if completed < 1 or completed + 1 > MAX_SEASON_FILES:
        raise PilotError(f"Tamamlanmış sezon sayısı 1–{MAX_SEASON_FILES - 1} olmalı.")
    y = season_start_year(today)
    return [f"{y - k}-{(y - k + 1) % 100:02d}" for k in range(completed + 1)]


def resolve_ref(ref: str | None, session=None) -> tuple[str, str | None, str]:
    """(commit, commit tarihi, nasıl). Verilmezse GitHub API'den master ucunu okur; çözülemezse hata (sabitlenmemiş
    indirme yapılmaz)."""
    if ref:
        ref = ref.strip().lower()
        if not _SHA40.match(ref):
            raise PilotError("--ref 40 karakterlik commit özeti olmalı.")
        return ref, None, "verilen"
    import requests

    s = session or requests.Session()
    try:
        r = s.get(COMMITS_API, timeout=(10, 30), headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        body = r.json()
        sha = str(body["sha"]).lower()
        date = (body.get("commit") or {}).get("committer", {}).get("date")
    except Exception as e:  # ağ, kota veya biçim
        raise PilotError(f"Kaynak commit'i çözülemedi ({e}); --ref ile 40 karakterlik commit verin.") from e
    if not _SHA40.match(sha):
        raise PilotError("GitHub yanıtında geçerli commit yok; --ref verin.")
    return sha, date, "github-api"


def _fetch_files(home: Path, ref: str, folders: list[str], downloader, previous: dict) -> tuple[dict, list[str]]:
    """Sabit commit'teki sezon dosyalarını önbelleğe alır. Önceki kayıt aynı commit ve özetse yeniden indirmez.
    İndirme her zaman yeni bir geçici yola yapılır: başarısızlıkta eski (başka commit'ten) dosya kullanılmaz."""
    from .data.sources import DownloadError

    lg = LEAGUES[PILOT_LEAGUE]
    out, missing = {}, []
    for folder in folders:
        rel_path = f"{folder}/{lg.openfootball}.json"
        cache_rel = f"openfootball/{rel_path}"
        final = home / "raw" / cache_rel
        old = previous.get(cache_rel)
        if old and old.get("ref") == ref and final.is_file() and \
                hashlib.sha256(final.read_bytes()).hexdigest() == old.get("sha256"):
            out[folder] = (final.read_bytes(), old["retrieved_at"], old["url"], rel_path, cache_rel)
            continue
        url = f"{RAW_BASE}/{ref}/{rel_path}"
        tmp_rel = f"openfootball/.indirme/{ref}/{rel_path}"
        try:
            data = downloader.get(url, tmp_rel, None, True)
        except DownloadError as e:
            if e.status == 404:
                missing.append(folder)
                continue
            raise PilotError(f"{rel_path} indirilemedi: {e}") from e
        at = _now().isoformat(timespec="seconds")
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(data)
        (home / "raw" / tmp_rel).unlink(missing_ok=True)
        out[folder] = (data, at, url, rel_path, cache_rel)
    tmp_root = home / "raw" / "openfootball" / ".indirme"
    if tmp_root.is_dir():  # yalnızca boş kalan geçici klasörler silinir
        for d in sorted((p for p in tmp_root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()
        if not any(tmp_root.iterdir()):
            tmp_root.rmdir()
    return out, missing


# ----------------------------------------------------------------------------
# Bağımsız katılımcı referansı (kullanıcının resmî kaynaktan hazırladığı dosya)
# ----------------------------------------------------------------------------

def load_participants(path, store_teams) -> tuple[dict, dict]:
    """Bağımsız katılımcı referansı: ``{"lig": "E0", "kaynak": URL, "alinma_utc": ISO, "sezonlar": {"2025/26":
    [adlar]}}``. Adlar pilot deposundaki adlara KESİN kimlikle eşlenmeli; eşlenemeyen veya belirsiz ad o sezonu
    geçersiz kılar (tahmin edilmez). Döner: ((lig, sezon) -> ad kümesi, rapor)."""
    from .data.teams import resolve_teams

    raw = Path(path).read_bytes()
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as e:
        raise PilotError(f"Katılımcı referansı okunamadı: {e}") from e
    if not isinstance(obj, dict) or obj.get("lig") != PILOT_LEAGUE or not isinstance(obj.get("sezonlar"), dict):
        raise PilotError("Katılımcı referansı biçimi: {\"lig\": \"E0\", \"kaynak\", \"alinma_utc\", \"sezonlar\": {...}}")
    if not str(obj.get("kaynak") or "").startswith("http") or not obj.get("alinma_utc"):
        raise PilotError("Katılımcı referansında kaynak adresi ve alınma anı zorunlu.")
    teams = sorted(set(store_teams))
    parts, report = {}, {"kaynak": obj["kaynak"], "alinma_utc": obj["alinma_utc"],
                         "dosya_sha256": hashlib.sha256(raw).hexdigest(), "sezonlar": {}}
    for season, names in obj["sezonlar"].items():
        if not isinstance(names, list) or not all(isinstance(n, str) and n.strip() for n in names):
            report["sezonlar"][season] = {"durum": "GECERSIZ_BICIM"}
            continue
        res = resolve_teams(names, teams, PILOT_LEAGUE, None)
        bad = sorted(n for n, m in res.items() if not m.exact)
        mapped = {m.team for m in res.values() if m.exact}
        ok = not bad and len(mapped) == len(set(names)) and len(mapped) >= 4
        report["sezonlar"][season] = {"ad": len(set(names)), "eslesen": len(mapped), "eslesmeyen": len(bad),
                                      "durum": "GECERLI" if ok else "ESLESMEYEN_AD",
                                      # yalnızca yazımı düzeltmek için öneri; kimlik kanıtı DEĞİLDİR
                                      "eslesmeyen_adlar": {n: list(res[n].candidates or res[n].suggestions)[:3]
                                                           for n in bad}}
        if ok:
            parts[(PILOT_LEAGUE, str(season))] = frozenset(mapped)
    return parts, report


def _saved_participants(home: Path, st) -> tuple[dict | None, dict | None]:
    ref = (st.meta or {}).get("katilimci_referansi")
    path = home / PARTICIPANTS_COPY
    if not ref or not path.is_file():
        return None, None
    if hashlib.sha256(path.read_bytes()).hexdigest() != ref.get("dosya_sha256"):
        return None, {"durum": "KOPYA_DEGISMIS"}
    teams = set(st.matches["home"]) | set(st.matches["away"])
    return load_participants(path, teams)


# ----------------------------------------------------------------------------
# Hazırlama (veri)
# ----------------------------------------------------------------------------

@dataclass
class _CachedDownloader:
    """Fikstür adaptörüne (``DataStore._update_fixtures``) sabit commit'teki önbellek dosyasını verir."""
    files: dict
    stats: dict = None

    def __post_init__(self):
        self.stats = {"network": 0, "cache": 0, "failed": 0}

    def host_down(self, url):
        return False

    def get(self, url, cache_rel, max_age_hours=None, force=False):
        from .data.sources import DownloadError

        if cache_rel not in self.files:
            raise DownloadError(url, "pilot önbelleğinde yok", 404)
        self.stats["cache"] += 1
        return self.files[cache_rel]


def prepare(home, ref: str | None = None, completed: int = 10, fixture_days: int = 10,
            participants_file=None, downloader=None, now: dt.datetime | None = None) -> dict:
    """Pilot veri deposunu hazırlar (yalnızca pilot klasörüne yazar). Döner: sayısal özet (maç satırı yok)."""
    from .data.sources import Downloader
    from .data.store import DataStore

    home = check_pilot_dir(home, create=True)
    now = now or _now()
    today = now.astimezone(ISTANBUL).date()
    folders = pilot_seasons(today, completed)
    sha, commit_date, how = resolve_ref(ref)
    old = DataStore(home)
    previous = {}
    if old.load():
        previous = {r["cache_rel"]: r for r in (old.meta.get("kaynak_kokeni") or [])}
    dl = downloader or Downloader(home / "raw", retries=3, polite_delay=1.0)
    files, missing = _fetch_files(home, sha, folders, dl, previous)
    if folders[0] in missing:
        raise PilotError(f"İçinde bulunulan sezon dosyası ({folders[0]}) bu commit'te yok.")
    lg = LEAGUES[PILOT_LEAGUE]
    frames, records, olcum = [], [], {}
    for folder in folders:
        if folder not in files:
            continue
        data, at, url, rel_path, cache_rel = files[folder]
        label = season_label(int(folder[:4]), lg.calendar_year)
        res = parse_openfootball_results(data, PILOT_LEAGUE, label)
        frames.append(res.matches)
        records.append(SourceFile(OPENFOOTBALL_REPO, rel_path, sha, url, at, res.sha256, PILOT_LEAGUE, label,
                                  OPENFOOTBALL_RESULT_PARSER, len(res.matches), rows_sha256(res.matches),
                                  cache_rel).to_dict())
        stale = sum(1 for d in res.tamamlanmamis_tarihler if dt.date.fromisoformat(d) < today)
        olcum[label] = {**res.ozet(), "bilgi_kesiminden_once_sonucsuz": stale, "dosya_sha256": res.sha256}
    matches = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    st = DataStore(home)
    st.matches = matches.sort_values(["date", "home"], kind="mergesort").reset_index(drop=True)
    cur_rel = f"openfootball/{folders[0]}/{lg.openfootball}.json"
    fdl = _CachedDownloader({f"openfootball/{openfootball_season(today, lg.calendar_year)}/{lg.openfootball}.json":
                             files[folders[0]][0]})
    rep = type("R", (), {"warnings": []})()
    st.fixtures = st._update_fixtures(fdl, [PILOT_LEAGUE], st.matches, today, fixture_days, rep, False,
                                      {"openfootball"}).reset_index(drop=True)
    st.meta.update({
        "pilot": PILOT_VERSION, "kaynak_kokeni": records, "kaynak_commit": sha, "kaynak_commit_tarihi": commit_date,
        "kaynak_commit_nasil": how, "pilot_olcum": olcum, "eksik_sezon_dosyasi": missing,
        "eslesmeyen_fikstur": list(st._last_unmatched), "hazirlama_utc": now.isoformat(timespec="seconds"),
        "bilgi_kesimi": str(today), "fikstur_uyarilari": rep.warnings, "guncel_sezon_dosyasi": cur_rel})
    if participants_file is not None:
        teams = set(st.matches["home"]) | set(st.matches["away"])
        _, preport = load_participants(participants_file, teams)
        dest = home / PARTICIPANTS_COPY
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(Path(participants_file).read_bytes())
        st.meta["katilimci_referansi"] = preport
    elif old.meta.get("katilimci_referansi") and (home / PARTICIPANTS_COPY).is_file():
        st.meta["katilimci_referansi"] = old.meta["katilimci_referansi"]
    st.save()
    ok, problems = verify_results(st.matches, records, st.raw_dir)
    return {**summary(home), "koken_dogrulandi": ok, "koken_sorunlari": problems}


# ----------------------------------------------------------------------------
# Salt okunur özet
# ----------------------------------------------------------------------------

def summary(home) -> dict:
    """Pilotun salt okunur kapsam özeti (yalnızca sayılar ve kimlikler; maç satırı yok)."""
    home = check_pilot_dir(home)
    st = _store(home)
    m = st.meta or {}
    ok, problems = verify_results(st.matches, m.get("kaynak_kokeni") or [], st.raw_dir)
    parts, preport = _saved_participants(home, st)
    seasons = sorted((m.get("pilot_olcum") or {}).items())
    feat_ok = None
    model = None
    info = home / MODEL_INFO
    if info.is_file():
        model = json.loads(info.read_text(encoding="utf-8"))
        feat_ok = model.get("egitim_satiri")
    led = home / LEDGER_FILE
    counts = None
    if led.is_file():
        from .goals.ledger import Ledger

        lg = Ledger(led)
        try:
            recs = lg.predictions()
        finally:
            lg.close()
        counts = {"kayit": len(recs), "tahmin": sum(r.get("decision_status") == "TAHMIN" for r in recs),
                  "tahmin_yok": sum(r.get("decision_status") == "TAHMIN_YOK" for r in recs)}
    return {"pilot": m.get("pilot"), "lig": PILOT_LEAGUE, "kaynak_commit": m.get("kaynak_commit"),
            "kaynak_commit_tarihi": m.get("kaynak_commit_tarihi"), "hazirlama_utc": m.get("hazirlama_utc"),
            "bilgi_kesimi": m.get("bilgi_kesimi"), "sezonlar": dict(seasons),
            "sonuc_satiri": int(len(st.matches)), "fikstur": int(len(st.fixtures)),
            "eslesmeyen_fikstur": len(m.get("eslesmeyen_fikstur") or []),
            "eksik_sezon_dosyasi": m.get("eksik_sezon_dosyasi") or [],
            "koken_dogrulandi": ok, "koken_sorunlari": problems,
            "katilimci_referansi": preport if preport else "YOK (bağımsız katılımcı listesi verilmedi)",
            "gecerli_katilimci_sezonu": sorted(s for _, s in (parts or {})),
            "model": ({k: model.get(k) for k in ("egitim_utc", "durum", "dogrulama", "egitim_satiri", "veri_sha256")}
                      if model else None),
            "ozellik_tamam_satir": feat_ok, "defter": counts}


# ----------------------------------------------------------------------------
# Eğitim (mevcut GoalEngine; ayrı pilot model dosyası)
# ----------------------------------------------------------------------------

def train(home, progress=None) -> dict:
    """Mevcut gol motorunu YALNIZCA pilot verisiyle bir kez eğitir ve pilot klasörüne kaydeder. Eşikler, varyant ve
    iç zaman sıralı doğrulama değişmez; eğitim hakkı ve veri kökeni ortak kontrolden geçmelidir."""
    from .eligibility import reason_texts, training_rights_codes
    from .goals.engine import MIN_TRAIN_ROWS, GoalDataError, GoalEngine
    from .goals.features import build_goal_features
    from .goals.model import ht_rows, usable_rows

    home = check_pilot_dir(home)
    st = _store(home)
    labels = set(st.matches["source"].dropna().astype(str))
    if labels != {OPENFOOTBALL_RESULT_LABEL}:
        raise PilotError(f"Pilot deposunda beklenmeyen kaynak etiketi: {sorted(labels)}")
    codes = training_rights_codes(st.matches, {}, verified_labels(st))
    if codes:
        raise PilotError("Eğitim yapılmadı: " + reason_texts(codes))
    feat, _ = build_goal_features(st.matches)
    n_ok = int((usable_rows(feat) & ht_rows(feat)).sum())
    info = {"egitim_satiri": n_ok, "en_az": MIN_TRAIN_ROWS, "ham_mac": int(len(st.matches)),
            "ilk_yari_skorlu": int(st.matches["hthg"].notna().sum())}
    eng = GoalEngine()
    try:
        eng.train(st.matches, progress=progress)
    except GoalDataError as e:
        (home / MODEL_INFO).write_text(json.dumps({**info, "durum": "VERI_YETERSIZ", "neden": str(e)},
                                                  ensure_ascii=False, indent=1), encoding="utf-8")
        return {**info, "durum": "VERI_YETERSIZ", "neden": str(e)}
    eng.save(home / GOAL_ENGINE_FILE)
    out = {**info, "durum": "EGITILDI", **model_summary(eng), "kaynak_commit": (st.meta or {}).get("kaynak_commit"),
           "durum_ozetleri": {lg: list(getattr(s, "row_digest", ()) or ()) for lg, s in eng.states.items()}}
    (home / MODEL_INFO).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return out


def model_summary(eng) -> dict:
    """Eğitilmiş motorun kimliği ve iç zaman sıralı doğrulama ölçütleri (Δ LL = model − taban; pozitif daha kötü)."""
    from .goals.model import FEATURE_VERSION, MODEL_VERSION

    metrics = {}
    for k, r in (eng.validation or {}).items():
        mm = r.get("modeller", {}).get(eng.variant, {})
        metrics[k] = {"test_mac": r.get("n"), "pozitif": r.get("pozitif"), "ll_fark": mm.get("ll_fark_ref"),
                      "ll_fark_alt": mm.get("ll_fark_alt"), "ll_fark_ust": mm.get("ll_fark_ust"),
                      "kal_egim": mm.get("kal_egim"), "ece": mm.get("ece")}
    return {"egitim_utc": eng.state_available_since.isoformat(timespec="seconds"),
            "model_surumu": f"{MODEL_VERSION}/{eng.variant}", "ozellik_surumu": FEATURE_VERSION,
            "veri_sha256": eng.data_sha, "veri_kesimi": eng.data_cutoff, "dogrulama_sezonlari": eng.validation_years,
            "dogrulama": {k: eng.status_text(k) for k in eng.validated}, "olcutler": metrics,
            "kaynaklar": eng.manifest.get("sources")}


# ----------------------------------------------------------------------------
# Tahmin kaydı (ortak uygunluk kontrolü; ayrı pilot defteri)
# ----------------------------------------------------------------------------

def forecast(home, apply: bool = False, now: dt.datetime | None = None) -> dict:
    """Yaklaşan pilot fikstürleri için A/B/C kayıtları. Varsayılan kuru çalıştırma; ``apply`` ise pilot defterine
    değişmez kayıt yazar (yazma anında karar penceresi yeniden denetlenir). Uygunluk geçmeyen maç nedenli
    TAHMIN_YOK olur; oran yoksa stake 0 ve bahis adayı yok."""
    from .eligibility import build_context
    from .goals.engine import GoalEngine
    from .goals.forecast_log import ACTIVE_PROTOCOL, build_forecast_records, record_forecasts
    from .goals.ledger import Ledger
    from .goals.markets import PRIMARY_YES

    home = check_pilot_dir(home)
    st = _store(home)
    eng, err = GoalEngine.load(home / GOAL_ENGINE_FILE)
    now = now or _now()
    today = now.astimezone(ISTANBUL).date()
    parts, _ = _saved_participants(home, st)
    ctx = build_context(st, eng, {}, today=today, participants=parts or {})
    led_path = home / LEDGER_FILE
    led = Ledger(led_path) if (apply or led_path.exists()) else None
    try:
        recs = build_forecast_records(eng, st.fixtures, st.matches, ledger=led, now=now, ctx=ctx,
                                      unmatched=st.unmatched_fixtures, source_rights=SOURCE_RIGHTS)
        reasons: dict[str, int] = {}
        for r in recs:
            key = "TAHMIN" if r["decision_status"] == "TAHMIN" else (r.get("reasons") or ["?"])[0]
            reasons[key] = reasons.get(key, 0) + 1
        all_codes: dict[str, int] = {}
        for r in recs:
            for c in ((r.get("veri_uygunlugu") or {}).get("nedenler") or []):
                all_codes[c] = all_codes.get(c, 0) + 1
        out = {"protokol": ACTIVE_PROTOCOL, "hesaplama_utc": now.isoformat(timespec="seconds"),
               "bilgi_kesimi": str(today), "model_yuklendi": eng is not None, "model_hatasi": err,
               # Olasılık kalitesi etiketi (oranla bahis avantajı değil); doğrulanmamış model böyle görünür
               "model_dogrulama": {k: eng.status_text(k) for k in PRIMARY_YES} if eng is not None else None,
               "aday_kayit": len(recs), "mac": len({r["event_id"] for r in recs}),
               "tahmin": sum(r["decision_status"] == "TAHMIN" for r in recs), "birincil_neden": reasons,
               "tum_nedenler": all_codes, "stake_toplam": float(sum(r.get("stake_units") or 0 for r in recs)),
               # Gerçek oran yoksa ekonomik değerlendirme yok: bahis adayı üretilmez
               "zamani_dogrulanmis_oranli": sum(r.get("ekonomik_statu") == "ZAMANI_DOGRULANMIS_ORAN" for r in recs),
               "bahis_adayi": 0, "yazildi": None}
        if apply:
            out["yazildi"] = {k: v for k, v in record_forecasts(led, recs).items() if k != "kimlikler"}
        return out
    finally:
        if led is not None:
            led.close()

"""GitHub veri ve tarihsel arşiv (S5-GITHUB-01).

Yalnızca kullanıcının seçtiği dört GitHub kaynağı (``data.github_kaynak.REPOS``) kullanılır; bütün yazmalar ayrı bir
çalışma klasörüne yapılır (kullanıcı uygulama klasörüyle çakışamaz). Kullanıcı veri deposu, pilot, model ve defter
değişmez; model eğitilmez; tahmin, olasılık veya bahis adayı üretilmez.

* Ham dosyalar kaynak bazında ayrı kalır (``GitHubCache``: depo + commit + yol). Her kaynak dosyası bir "blok"tur;
  katalog her blok için depo, commit, yol, dosya özeti, alım anı ve yöntemi, ayrıştırıcı, son geçerli maç, MS/İY
  kapsamı, olay/xG/oran alanlarının varlığı ve kapsamın tam/kısmi/bilinmiyor oluşunu saklar.
* Kullanım kapsamı kaynak ve işlem bazındadır (``source_registry.ARCHIVE_SCOPES``): tarihsel analizi kapalı kaynakların
  satırları analiz tablosuna girmez, yalnızca envanter sayıları katalogda görünür.
* Yüklemede her analiz bloğunun ham dosyası ve satır özeti yeniden doğrulanır; değiştirilmiş ham dosya veya etiketi
  değiştirilmiş satır kullanılmaz.
* Birleşik görünümde aynı gerçek maç bir kez sayılır (aynı lig-sezon bağlamında kesin takım kimliği + aynı tarih);
  tarih farkı toleransla bağlanmaz, incelemeye ayrılır. Skor çelişkisi çoğunlukla veya en yeni commit'le çözülmez:
  maç özetlerden çıkarılır ve kaynak kimlikleriyle listelenir. Aynı asıl kökenden beslenen iki kopyanın uyuşması
  bağımsız doğrulama sayılmaz.
* Pazar etiketleri merkezi pazar kaydından (``goals.markets``) gelir; eksik İY 0-0 yapılmaz (yalnızca v2'deki MS 0-0
  istisnası, işaretli olarak korunur).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import app_home_path
from .data.github_kaynak import (
    FETCHED,
    IMPORTED,
    REPOS,
    STATUS_TEXT,
    VERIFIED_CACHE,
    GitHubCache,
    GitHubError,
    GitHubTransport,
)
from .data.source_registry import SOURCES, archive_allowed, archive_scope

ARCHIVE_VERSION = "github-arsiv-v1"
MARKER = "arsiv.json"
CATALOG = "katalog.json"
ROWS = "satirlar.pkl"  # analiz izinli kaynakların maç satırları (yalnızca yerel çalışma klasöründe)
ARCHIVE_NOTE = ("Tarihsel gerçekleşme oranıdır; bugünkü bir maç için olasılık, model güveni veya bahis avantajı "
                "değildir.")
SOURCE_KEYS = ("openfootball-sonuc", "football-datasets", "github-mirror", "statsbomb-acik")
SHORT_NAMES = {"openfootball": "openfootball-sonuc", "datasets": "football-datasets", "xgabora": "github-mirror",
               "hudl": "statsbomb-acik"}
PRIORITY = SOURCE_KEYS  # birleşik görünümde takım adlarının bağlamı (ilk bulunan kaynak)
UPSTREAM = {"openfootball-sonuc": "openfootball", "football-datasets": "football-data.co.uk",
            "github-mirror": "football-data.co.uk", "statsbomb-acik": "statsbomb"}
HUDL_SAMPLE_MAX = 12
HUDL_SAMPLE_RULE = ("Premier League 2015/16 (yarışma 2, sezon 27) maçları maç tarihine, sonra maç kimliğine göre artan "
                    "sırada; ilk N maç (sonuçlara bakılmadan, önceden tanımlı kural)")
ROW_COLUMNS = ["kaynak", "etiket", "asil_kaynak", "blok", "league", "season", "date", "time", "home", "away", "fthg",
               "ftag", "hthg", "htag", "iy_mantiksal", "olay_durumu", "saglayici_mac_id", "xg_h", "xg_a", "sut_h",
               "sut_a"]


class ArchiveError(RuntimeError):
    """Arşiv işlemi güvenli biçimde yapılamıyor (klasör, kaynak veya hak sorunu)."""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def archive_home_path() -> Path:
    """Varsayılan arşiv çalışma klasörü: uygulama klasörünün KARDEŞİ (``<uygulama>-Arsiv``); ``BAHIS_TAHMIN_ARSIV``
    ile değiştirilebilir. Uygulama klasörünün içinde olamaz."""
    env = os.environ.get("BAHIS_TAHMIN_ARSIV")
    if env:
        return Path(env)
    base = app_home_path()
    return base.with_name(base.name + "-Arsiv")


def check_archive_dir(home=None, create: bool = False) -> Path:
    path = Path(home if home not in (None, "") else archive_home_path()).expanduser().resolve()
    user = app_home_path().expanduser().resolve()
    if path == user or user in path.parents or path in user.parents:
        raise ArchiveError(f"Arşiv klasörü kullanıcı uygulama klasörüyle çakışıyor ({user}); ayrı bir klasör verin.")
    if path.exists() and not path.is_dir():
        raise ArchiveError(f"{path} bir klasör değil.")
    if path.exists() and any(path.iterdir()) and not (path / MARKER).is_file():
        raise ArchiveError(f"{path} boş değil ve arşiv işareti ({MARKER}) taşımıyor; başka verinin üzerine yazılmaz.")
    if create:
        path.mkdir(parents=True, exist_ok=True)
        if not (path / MARKER).is_file():
            (path / MARKER).write_text(json.dumps({"arsiv": ARCHIVE_VERSION, "olusturma_utc": _now().isoformat(
                timespec="seconds")}, ensure_ascii=False), encoding="utf-8")
    elif not (path / MARKER).is_file():
        raise ArchiveError(f"{path} hazırlanmış bir arşiv klasörü değil (önce arsiv-hazirla).")
    return path


def rows_digest(df: pd.DataFrame) -> str:
    """Blok satırlarının içerik özeti (sıra bağımsız; kaynak etiketi dahil)."""
    cols = ["etiket", "league", "season", "date", "home", "away", "fthg", "ftag", "hthg", "htag", "iy_mantiksal",
            "saglayici_mac_id"]

    def cell(v) -> str:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return ""
        if isinstance(v, (pd.Timestamp, dt.date)):
            return str(pd.Timestamp(v).date())
        if isinstance(v, (float, np.floating)) and float(v) == int(v):
            return str(int(v))
        return str(v)

    keys = sorted("|".join(cell(r[c]) for c in cols) for _, r in df.reindex(columns=cols).iterrows())
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


def _status(cf) -> str:
    return IMPORTED if cf.record.get("yontem") == IMPORTED and cf.status == VERIFIED_CACHE else cf.status


def _empty_rows() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=object) for c in ROW_COLUMNS})


def _expected_matches(n_teams: int) -> int:
    return n_teams * (n_teams - 1)


# ----------------------------------------------------------------------------
# Pilotun doğrulanmış önbelleğini kopyalama (pilot salt okunur)
# ----------------------------------------------------------------------------

def import_pilot_cache(cache: GitHubCache, pilot_home) -> list[dict]:
    """Pilotun kaynak kökeni kayıtlarındaki openfootball dosyalarını, özetleri doğrulanarak arşiv önbelleğine kopyalar.
    Pilot klasörüne yazılmaz; özeti uyuşmayan dosya kopyalanmaz."""
    meta_path = Path(pilot_home) / "data_meta.json"
    if not meta_path.is_file():
        raise ArchiveError(f"Pilot veri kaydı yok: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    out = []
    known = cache.ref_history()
    for rec in meta.get("kaynak_kokeni") or []:
        spec = REPOS.get(rec.get("repo"))
        if spec is None:
            out.append({"yol": rec.get("path"), "durum": "SECILI_DEPO_DEGIL"})
            continue
        p = Path(pilot_home) / "raw" / rec["cache_rel"]
        if not p.is_file():
            out.append({"yol": rec.get("path"), "durum": "PILOT_DOSYASI_YOK"})
            continue
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() != rec.get("sha256"):
            out.append({"yol": rec.get("path"), "durum": "OZET_UYUSMAZ"})
            continue
        cache.put(rec["repo"], rec["ref"], rec["path"], data, IMPORTED, url=rec.get("url"),
                  retrieved_at=rec.get("retrieved_at"), extra={"pilot_klasoru": str(Path(pilot_home).resolve())})
        if not known.get(spec.repo):  # yalnızca kayıt yoksa: daha yeni çözülmüş uç geriye alınmaz
            cache.record_ref(spec.repo, spec.branch, rec["ref"], "pilot-kaydi")
            known = cache.ref_history()
        out.append({"yol": rec["path"], "commit": rec["ref"], "durum": IMPORTED})
    return out


# ----------------------------------------------------------------------------
# Kaynak işleyicileri
# ----------------------------------------------------------------------------

@dataclass
class _Run:
    cache: GitHubCache
    transport: GitHubTransport | None
    offline: bool
    today: dt.date
    blocks: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    progress: object = None

    def get(self, spec, commit: str, path: str):
        return self.cache.get(self.transport, spec.repo, commit, path, self.offline)

    def say(self, p: int, msg: str) -> None:
        if self.progress:
            self.progress(p, msg)


def _block(key: str, spec, commit: str, path: str, cf, parser: str, league: str | None, season: str | None,
           **info) -> dict:
    return {"kaynak": key, "depo": spec.repo, "commit": commit, "yol": path, "dosya_sha256": cf.record["sha256"],
            "boyut": cf.record.get("boyut"), "alinma_utc": cf.record.get("alinma_utc"), "durum": _status(cf),
            "durum_aciklama": STATUS_TEXT.get(_status(cf), ""), "ayristirici": parser, "lig": league, "sezon": season,
            "asil_kaynak": spec.origin, **info}


def _openfootball(run: _Run, key: str, spec, commit: str, leagues, seasons) -> None:
    from .data.leagues import LEAGUES, openfootball_season, season_label
    from .data.parsers import OPENFOOTBALL_RESULT_PARSER, parse_openfootball_results

    for lg in leagues:
        info = LEAGUES.get(lg)
        if info is None or not info.openfootball:
            continue
        cur = openfootball_season(run.today, info.calendar_year)
        last = int(cur[:4])
        first = int(seasons[0]) if seasons else last - 11
        for y in range(first, last + 1):
            folder = f"{y}-{(y + 1) % 100:02d}"
            path = f"{folder}/{info.openfootball}.json"
            label = season_label(y, info.calendar_year)
            try:
                cf = run.get(spec, commit, path)
            except GitHubError as e:
                run.blocks.append({"kaynak": key, "depo": spec.repo, "commit": commit, "yol": path, "lig": lg,
                                   "sezon": label, "durum": e.kind, "hata": str(e)})
                continue
            res = parse_openfootball_results(cf.data, lg, label)
            m = res.matches
            n_teams = res.takim or 0
            stale = sum(1 for d in res.tamamlanmamis_tarihler if dt.date.fromisoformat(d) < run.today)
            complete = (res.oynanmamis == 0 and not res.karantina and n_teams > 0
                        and len(m) == _expected_matches(n_teams))
            rows = pd.DataFrame({
                "kaynak": key, "etiket": spec.label, "asil_kaynak": UPSTREAM[key], "league": m["league"],
                "season": m["season"], "date": m["date"], "time": m["time"], "home": m["home"], "away": m["away"],
                "fthg": m["fthg"].astype(float), "ftag": m["ftag"].astype(float), "hthg": m["hthg"], "htag": m["htag"],
                "iy_mantiksal": m["iy_mantiksal"].astype(bool), "olay_durumu": None, "saglayici_mac_id": None,
                "xg_h": np.nan, "xg_a": np.nan, "sut_h": np.nan, "sut_a": np.nan}).reindex(columns=ROW_COLUMNS)
            blk = _block(key, spec, commit, path, cf, OPENFOOTBALL_RESULT_PARSER, lg, label,
                         mac=int(len(m)), ms_gecerli=int(len(m)), iy_gecerli=int(m["hthg"].notna().sum()),
                         iy_mantiksal=int(res.iy_mantiksal), oynanmamis=int(res.oynanmamis),
                         tarihi_gecmis_sonucsuz=int(stale), karantina=dict(_count(res.karantina)),
                         takim=int(n_teams), son_gecerli_mac=res.son_tamamlanan,
                         kapsam="TAM" if complete else "KISMI", olay_verisi=False, xg=False, gercek_oran=False)
            _add_rows(run, blk, rows, key)


def _count(items) -> dict:
    return Counter(str(k.get("neden")) for k in items)


def _add_rows(run: _Run, blk: dict, rows: pd.DataFrame, key: str) -> None:
    blk["blok"] = len(run.blocks)
    blk["tarihsel_analiz"] = archive_allowed(key, "tarihsel_analiz")
    if blk["tarihsel_analiz"] and len(rows):
        rows = rows.copy()
        rows["blok"] = blk["blok"]
        blk["satir_ozeti"] = rows_digest(rows)
        blk["satir"] = int(len(rows))
        run.rows.append(rows)
    run.blocks.append(blk)


def _football_datasets(run: _Run, key: str, spec, commit: str, leagues) -> None:
    from .data.parsers import FOOTBALL_DATASETS_PARSER, football_datasets_season, parse_football_datasets

    folders = {"E0": "premier-league"}
    for lg in leagues:
        folder = folders.get(lg)
        if folder is None:
            continue
        dp_path = f"datasets/{folder}/datapackage.json"
        try:
            dp = json.loads(run.get(spec, commit, dp_path).data.decode("utf-8"))
        except (GitHubError, ValueError) as e:
            run.sources[key]["hata"] = f"datapackage okunamadı: {e}"
            continue
        resources = sorted({str(r.get("path")) for r in dp.get("resources", []) if str(r.get("path", "")).endswith(".csv")})
        run.sources[key]["datapackage"] = {"yol": dp_path, "kaynak_sayisi": len(resources),
                                           "lisans": [x.get("name") for x in dp.get("licenses", []) if isinstance(x, dict)]}
        for res_path in resources:
            label = football_datasets_season(res_path)
            path = f"datasets/{folder}/{res_path.rsplit('/', 1)[-1]}"
            if label is None:
                run.blocks.append({"kaynak": key, "yol": path, "durum": "SEZON_ADI_COZULEMEDI"})
                continue
            try:
                cf = run.get(spec, commit, path)
            except GitHubError as e:
                run.blocks.append({"kaynak": key, "depo": spec.repo, "commit": commit, "yol": path, "lig": lg,
                                   "sezon": label, "durum": e.kind, "hata": str(e)})
                continue
            m, rep = parse_football_datasets(cf.data, lg, label)
            n_teams = len(set(m["home"]) | set(m["away"]))
            complete = (len(m) == _expected_matches(n_teams) and not rep["karantina"] and n_teams > 0)
            rows = pd.DataFrame({
                "kaynak": key, "etiket": spec.label, "asil_kaynak": UPSTREAM[key], "league": m["league"],
                "season": m["season"], "date": m["date"], "time": m["time"], "home": m["home"], "away": m["away"],
                "fthg": m["fthg"], "ftag": m["ftag"], "hthg": m["hthg"], "htag": m["htag"], "iy_mantiksal": False,
                "olay_durumu": None, "saglayici_mac_id": None, "xg_h": np.nan, "xg_a": np.nan, "sut_h": np.nan,
                "sut_a": np.nan}).reindex(columns=ROW_COLUMNS)
            blk = _block(key, spec, commit, path, cf, FOOTBALL_DATASETS_PARSER, lg, label,
                         mac=rep.get("gecerli_mac", 0), ms_gecerli=rep.get("ms_gecerli", 0),
                         iy_gecerli=rep.get("iy_gecerli", 0), birebir_tekrar=rep.get("birebir_tekrar", 0),
                         karantina=rep["karantina"], takim=n_teams, son_gecerli_mac=rep.get("son_tarih"),
                         alan_kapsami=rep.get("alan_kapsami", {}), eksik_sutun=rep.get("eksik_sutun", []),
                         kapsam="TAM" if complete else "KISMI", olay_verisi=False, xg=False,
                         gercek_oran=bool(rep["oran_sutunu"]))
            _add_rows(run, blk, rows, key)


XGABORA_RAW = ("Division", "MatchDate", "MatchTime", "HomeTeam", "AwayTeam", "FTHome", "FTAway", "FTResult", "HTHome",
               "HTAway", "HTResult", "HomeShots", "AwayShots", "HomeTarget", "AwayTarget", "HomeFouls", "AwayFouls",
               "HomeCorners", "AwayCorners", "HomeYellow", "AwayYellow", "HomeRed", "AwayRed")
XGABORA_DERIVED = ("HomeElo", "AwayElo", "Form3Home", "Form5Home", "Form3Away", "Form5Away", "C_LTH", "C_LTA",
                   "C_VHD", "C_VAD", "C_HTB", "C_PHB")
XGABORA_MARKET = ("OddHome", "OddDraw", "OddAway", "MaxHome", "MaxDraw", "MaxAway", "Over25", "Under25", "MaxOver25",
                  "MaxUnder25", "HandiSize", "HandiHome", "HandiAway")


def _xgabora(run: _Run, key: str, spec, commit: str, leagues) -> None:
    from .data.parsers import normalize_mirror

    path = "data/Matches.csv"
    try:
        cf = run.get(spec, commit, path)
    except GitHubError as e:
        run.blocks.append({"kaynak": key, "depo": spec.repo, "commit": commit, "yol": path, "durum": e.kind,
                           "hata": str(e)})
        return
    raw = pd.read_csv(io.BytesIO(cf.data), low_memory=False)
    cols = set(raw.columns)
    run.sources[key]["sutunlar"] = {"ham": [c for c in XGABORA_RAW if c in cols],
                                    "turetilmis_model_girdisi_degil": [c for c in XGABORA_DERIVED if c in cols],
                                    "piyasa_orani": [c for c in XGABORA_MARKET if c in cols],
                                    "eksik_ham": [c for c in XGABORA_RAW if c not in cols]}
    run.sources[key]["toplam_satir"] = int(len(raw))
    m = normalize_mirror(raw, list(leagues))
    for (lg, season), g in m.groupby(["league", "season"]):
        n_teams = len(set(g["home"]) | set(g["away"]))
        rows = pd.DataFrame({
            "kaynak": key, "etiket": spec.label, "asil_kaynak": UPSTREAM[key], "league": g["league"],
            "season": g["season"], "date": g["date"], "time": g["time"], "home": g["home"], "away": g["away"],
            "fthg": g["fthg"], "ftag": g["ftag"], "hthg": g["hthg"], "htag": g["htag"], "iy_mantiksal": False,
            "olay_durumu": None, "saglayici_mac_id": None, "xg_h": np.nan, "xg_a": np.nan, "sut_h": np.nan,
            "sut_a": np.nan}).reindex(columns=ROW_COLUMNS)
        blk = _block(key, spec, commit, path, cf, "xgabora-normalize-mirror", lg, str(season), mac=int(len(g)),
                     ms_gecerli=int(g["fthg"].notna().sum()), iy_gecerli=int(g["hthg"].notna().sum()),
                     takim=n_teams, son_gecerli_mac=str(pd.Timestamp(g["date"].max()).date()),
                     kapsam="TAM" if len(g) == _expected_matches(n_teams) else "KISMI", olay_verisi=False, xg=False,
                     gercek_oran=bool(set(XGABORA_MARKET) & cols),
                     not_="Elo/form/küme/oran sütunları türetilmiş veya piyasa alanıdır; model girdisi yapılmaz.")
        _add_rows(run, blk, rows, key)


def _hudl(run: _Run, key: str, spec, commit: str, leagues, sample: int) -> None:
    from .data.statsbomb import (
        COMPETITION_TO_LEAGUE,
        OK,
        STATSBOMB_PARSER,
        parse_competitions,
        parse_matches,
        score_from_events,
    )
    from .data.statsbomb import season_label as sb_season

    try:
        comps = parse_competitions(run.get(spec, commit, "data/competitions.json").data)
    except (GitHubError, ValueError) as e:
        run.sources[key]["hata"] = f"competitions.json okunamadı: {e}"
        return
    wanted = {cid for cid, lg in COMPETITION_TO_LEAGUE.items() if lg in leagues}
    cat = []
    for c in comps:
        cat.append({"yarisma_id": c.get("competition_id"), "sezon_id": c.get("season_id"),
                    "yarisma": c.get("competition_name"), "sezon": c.get("season_name"), "ulke": c.get("country_name"),
                    "cinsiyet": c.get("competition_gender"), "lig": COMPETITION_TO_LEAGUE.get(c.get("competition_id"))})
    run.sources[key]["yarisma_katalogu"] = {"kayit": len(cat), "bu_uygulamanin_ligleri": [x for x in cat if x["lig"]]}
    sample = max(0, min(int(sample), HUDL_SAMPLE_MAX))
    for c in [x for x in cat if x["yarisma_id"] in wanted]:
        path = f"data/matches/{c['yarisma_id']}/{c['sezon_id']}.json"
        try:
            cf = run.get(spec, commit, path)
        except GitHubError as e:
            run.blocks.append({"kaynak": key, "depo": spec.repo, "commit": commit, "yol": path, "durum": e.kind,
                               "hata": str(e)})
            continue
        ms = parse_matches(cf.data)
        teams = {x["home"] for x in ms} | {x["away"] for x in ms}
        per_team = pd.Series([t for x in ms for t in (x["home"], x["away"])]).value_counts()
        full = len(ms) == _expected_matches(len(teams)) and len(teams) > 0
        kapsam = "TAM_SEZON" if full else (f"SECILI_MACLAR ({per_team.index[0]} maçları)"
                                           if len(per_team) and per_team.iloc[0] == len(ms) else "SECILI_MACLAR")
        lg = COMPETITION_TO_LEAGUE[c["yarisma_id"]]
        season = sb_season(c["sezon"])
        blk = _block(key, spec, commit, path, cf, STATSBOMB_PARSER, lg, season, mac=len(ms), takim=len(teams),
                     kapsam=kapsam, olay_verisi=True, xg=True, gercek_oran=False,
                     son_gecerli_mac=max((x["date"] for x in ms), default=None), tur="mac_listesi")
        blk["blok"] = len(run.blocks)
        blk["tarihsel_analiz"] = archive_allowed(key, "tarihsel_analiz")
        run.blocks.append(blk)
        if not (full and sample and blk["tarihsel_analiz"]):
            continue
        chosen = sorted(ms, key=lambda x: (str(x["date"]), int(x["match_id"])))[:sample]
        run.sources[key]["olay_ornegi"] = {"kural": HUDL_SAMPLE_RULE, "n": len(chosen), "lig": lg, "sezon": season,
                                           "uyari": "Örneklemdir; bütün sezon analizi olarak raporlanmaz."}
        for x in chosen:
            ev_path = f"data/events/{x['match_id']}.json"
            try:
                ecf = run.get(spec, commit, ev_path)
            except GitHubError as e:
                run.blocks.append({"kaynak": key, "yol": ev_path, "durum": e.kind, "hata": str(e)})
                continue
            sc = score_from_events(json.loads(ecf.data.decode("utf-8")), x)
            ok = sc["durum"] == OK
            rows = pd.DataFrame([{
                "kaynak": key, "etiket": spec.label, "asil_kaynak": UPSTREAM[key], "league": lg, "season": season,
                "date": pd.Timestamp(x["date"]), "time": str(x.get("kick_off") or "")[:5], "home": x["home"],
                "away": x["away"], "fthg": float(sc["ms"][0]) if ok else np.nan,
                "ftag": float(sc["ms"][1]) if ok else np.nan, "hthg": float(sc["iy"][0]) if ok else np.nan,
                "htag": float(sc["iy"][1]) if ok else np.nan, "iy_mantiksal": False, "olay_durumu": sc["durum"],
                "saglayici_mac_id": str(x["match_id"]), "xg_h": sc["xg"]["h"], "xg_a": sc["xg"]["a"],
                "sut_h": sc["sut"]["h"], "sut_a": sc["sut"]["a"]}]).reindex(columns=ROW_COLUMNS)
            eblk = _block(key, spec, commit, ev_path, ecf, STATSBOMB_PARSER, lg, season, mac=1,
                          ms_gecerli=int(ok), iy_gecerli=int(ok), olay_durumu=sc["durum"], olay_sorunlari=sc["sorunlar"],
                          uzatma=sc["uzatma"], kendi_kalesine=sc["kendi_kalesine"], olay_sayisi=sc["olay_sayisi"],
                          kapsam="ORNEK", olay_verisi=True, xg=True, gercek_oran=False, son_gecerli_mac=x["date"],
                          tur="olay")
            _add_rows(run, eblk, rows, key)


# ----------------------------------------------------------------------------
# Hazırlama
# ----------------------------------------------------------------------------

def build(home=None, *, sources=SOURCE_KEYS, leagues=("E0",), pilot_home=None, transport=None, offline: bool = False,
          consent=(), openfootball_from: int | None = 2010, hudl_sample: int = HUDL_SAMPLE_MAX, today=None,
          progress=None) -> dict:
    """Seçilen GitHub kaynaklarını sabit commit'lerden arşiv klasörüne alır, kaynak bazlı katalog ve analiz tablosu
    yazar. Döner: sayısal özet (maç satırı yok). Kullanıcı veri deposuna, pilota veya modele dokunmaz.

    ``consent``: kullanım koşulları onay gerektiren kaynaklar için kullanıcının bu çalıştırmadaki ERİŞİM onayı (hak
    vermez; yalnızca indirmeyi kapsar). ``pilot_home``: openfootball dosyaları pilotun doğrulanmış önbelleğinden
    kopyalanır (pilot salt okunur)."""
    home = check_archive_dir(home, create=True)
    cache = GitHubCache(home)
    run = _Run(cache, None if offline else (transport or GitHubTransport()), offline,
               today or dt.datetime.now(dt.timezone.utc).date(), progress=progress)
    unknown = [s for s in sources if s not in REPOS_BY_KEY]
    if unknown:
        raise ArchiveError(f"Bilinmeyen kaynak: {', '.join(unknown)}")
    imported = import_pilot_cache(cache, pilot_home) if pilot_home else []
    for i, key in enumerate(sources):
        spec = REPOS_BY_KEY[key]
        scope = archive_scope(key)
        st = run.sources.setdefault(key, {"depo": spec.repo, "dal": spec.branch, "asil_kaynak": spec.origin,
                                          "kapsam": scope, "kimlik_notu": spec.identity_note or None})
        run.say(int(90 * i / max(1, len(sources))), f"{spec.repo} okunuyor...")
        if not archive_allowed(key, "alma_saklama"):
            st["durum"] = "KULLANIM_KAPSAMI_NEDENIYLE_KAPALI"
            continue
        if SOURCES[key].requires_consent and key not in set(consent):
            st["durum"] = "ERISIM_ONAYI_YOK"
            continue
        try:
            commit, ref_status, note = cache.resolve(run.transport, spec, offline)
        except GitHubError as e:
            st.update({"durum": "ERISILEMEDI", "hata": str(e), "hata_turu": e.kind})
            continue
        st.update({"commit": commit, "uc_durumu": ref_status, "uc_notu": note})
        n0 = len(run.blocks)
        try:
            if key == "openfootball-sonuc":
                _openfootball(run, key, spec, commit, leagues, [openfootball_from] if openfootball_from else None)
            elif key == "football-datasets":
                _football_datasets(run, key, spec, commit, leagues)
            elif key == "github-mirror":
                _xgabora(run, key, spec, commit, leagues)
            elif key == "statsbomb-acik":
                _hudl(run, key, spec, commit, leagues, hudl_sample)
        except GitHubError as e:
            st.update({"durum": "ERISILEMEDI", "hata": str(e), "hata_turu": e.kind})
            continue
        mine = run.blocks[n0:]
        ok = [b for b in mine if "dosya_sha256" in b]
        st["blok"] = len(ok)
        st["hatali_blok"] = len(mine) - len(ok)
        st["durumlar"] = dict(Counter(b["durum"] for b in mine))
        st["durum"] = ("TARIHSEL_ANALIZ_ETKIN" if archive_allowed(key, "tarihsel_analiz") else
                       "YALNIZCA_ENVANTER (tarihsel analiz kullanım kapsamı nedeniyle kapalı)") if ok else "VERI_YOK"
    rows = pd.concat(run.rows, ignore_index=True) if run.rows else _empty_rows()
    rows = rows.reindex(columns=ROW_COLUMNS)
    rows["date"] = pd.to_datetime(rows["date"])
    for c in ("fthg", "ftag", "hthg", "htag", "xg_h", "xg_a", "sut_h", "sut_a"):
        rows[c] = pd.to_numeric(rows[c], errors="coerce").astype(float)
    rows["iy_mantiksal"] = rows["iy_mantiksal"].fillna(False).astype(bool)
    catalog = {"arsiv": ARCHIVE_VERSION, "olusturma_utc": _now().isoformat(timespec="seconds"),
               "bilgi_kesimi": str(run.today), "kaynaklar": run.sources, "bloklar": run.blocks,
               "pilot_kopyasi": imported, "uclar": cache.ref_history(),
               "guncel_veri": current_status(run.blocks, run.today, run.sources)}
    (home / ROWS).parent.mkdir(parents=True, exist_ok=True)
    rows.to_pickle(home / ROWS)
    (home / CATALOG).write_text(json.dumps(catalog, ensure_ascii=False, indent=1, default=_json), encoding="utf-8")
    run.say(100, "Arşiv hazır.")
    return brief(catalog, rows)


REPOS_BY_KEY = {spec.source_key: spec for spec in REPOS.values()}


def _json(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (pd.Timestamp, dt.date)):
        return str(v)
    return str(v)


def current_status(blocks: list, today: dt.date, sources: dict | None = None) -> dict:
    """İçinde bulunulan sezon için güncel sonuç durumu (lig başına): VERIFIED_AVAILABLE / STALE / UNAVAILABLE.

    VERIFIED_AVAILABLE yalnızca: kaynağın dal ucu BUGÜN çözüldü (eski kopya veya çevrimdışı değil) ve tarihi geçmiş
    sonuçsuz maç yok. STALE: tarihi geçmiş ama sonucu kaynakta olmayan maç var veya uç bugün doğrulanamadı.
    Tarihsel arşiv görünümünü KAPATMAZ; güncel tahmin uygunluğunu da GEÇİRMEZ."""
    from .data.leagues import LEAGUES, season_label, season_start_year

    sources = sources or {}
    out = {}
    for lg in sorted({b.get("lig") for b in blocks if b.get("lig")}):
        info = LEAGUES.get(lg)
        cur = season_label(season_start_year(today), info.calendar_year) if info else None
        mine = [b for b in blocks if b.get("lig") == lg and b.get("sezon") == cur and "dosya_sha256" in b
                and "tarihi_gecmis_sonucsuz" in b]
        per = {}
        for b in mine:
            fresh = (sources.get(b["kaynak"]) or {}).get("uc_durumu") == FETCHED
            per[b["kaynak"]] = {"son_gecerli_mac": b.get("son_gecerli_mac"),
                                "tarihi_gecmis_sonucsuz": b.get("tarihi_gecmis_sonucsuz"),
                                "uc_bugun_dogrulandi": fresh,
                                "durum": ("VERIFIED_AVAILABLE" if fresh and b.get("tarihi_gecmis_sonucsuz") == 0
                                          else "STALE")}
        if not per:
            state = "UNAVAILABLE"
        elif any(v["durum"] == "VERIFIED_AVAILABLE" for v in per.values()):
            state = "VERIFIED_AVAILABLE"
        else:
            state = "STALE"
        out[lg] = {"sezon": cur, "durum": state, "kaynaklar": per,
                   "not": "Güncel veri durumu güncel tahmin uygunluğunu geçirmez; tahmin ekranı kendi kurallarını "
                          "uygular. Tarihsel arşiv bu durumdan bağımsız kullanılabilir."}
    return out


def brief(catalog: dict, rows: pd.DataFrame) -> dict:
    blocks = [b for b in catalog["bloklar"] if "dosya_sha256" in b]
    return {"arsiv": catalog["arsiv"], "olusturma_utc": catalog["olusturma_utc"],
            "kaynaklar": {k: {x: v.get(x) for x in ("durum", "commit", "uc_durumu", "uc_notu", "blok", "hatali_blok",
                                                       "hata")} for k, v in catalog["kaynaklar"].items()},
            "blok": len(blocks), "analiz_satiri": int(len(rows)),
            "blok_durumlari": dict(Counter(b["durum"] for b in blocks)),
            "guncel_veri": {k: v["durum"] for k, v in catalog.get("guncel_veri", {}).items()}}


# ----------------------------------------------------------------------------
# Yükleme (köken yeniden doğrulanır)
# ----------------------------------------------------------------------------

@dataclass
class Archive:
    home: Path
    catalog: dict
    rows: pd.DataFrame  # doğrulanmış analiz satırları (kaynak bazında ayrı)
    rejected: list  # doğrulanamayan bloklar

    def blocks(self) -> list:
        return [b for b in self.catalog["bloklar"] if "dosya_sha256" in b]

    def coverage_frame(self) -> pd.DataFrame:
        cols = ["kaynak", "lig", "sezon", "yol", "commit", "durum", "son_gecerli_mac", "mac", "ms_gecerli",
                "iy_gecerli", "iy_mantiksal", "kapsam", "tarihsel_analiz", "olay_verisi", "xg", "gercek_oran",
                "alinma_utc"]
        df = pd.DataFrame([{c: b.get(c) for c in cols} for b in self.blocks()], columns=cols)
        if not df.empty:
            df["commit"] = df["commit"].astype(str).str[:12]
            rej = {(r["kaynak"], r["yol"]) for r in self.rejected}
            df.loc[[(k, y) in rej for k, y in zip(df["kaynak"], df["yol"])], "durum"] = "KOKEN_DOGRULANAMADI"
        return df


def load(home=None) -> Archive:
    home = check_archive_dir(home)
    catalog = json.loads((home / CATALOG).read_text(encoding="utf-8"))
    rows = pd.read_pickle(home / ROWS) if (home / ROWS).is_file() else _empty_rows()
    cache = GitHubCache(home)
    rejected, keep = [], []
    for b in catalog.get("bloklar", []):
        if "satir_ozeti" not in b:
            continue
        reason = None
        try:
            cf = cache.read(b["depo"], b["commit"], b["yol"])
            if cf is None:
                reason = "HAM_DOSYA_YOK"
            elif cf.record["sha256"] != b["dosya_sha256"]:
                reason = "HAM_DOSYA_KATALOGLA_UYUSMUYOR"
        except GitHubError as e:
            reason = e.kind
        part = rows[rows["blok"] == b["blok"]] if "blok" in rows else rows.iloc[0:0]
        if reason is None and (not archive_allowed(b["kaynak"], "tarihsel_analiz")
                               or set(part["etiket"]) != {REPOS_BY_KEY[b["kaynak"]].label}
                               or set(part["kaynak"]) != {b["kaynak"]}):
            reason = "KAYNAK_ETIKETI_UYUMSUZ"
        if reason is None and rows_digest(part) != b["satir_ozeti"]:
            reason = "SATIRLAR_KAYITLA_UYUSMUYOR"
        if reason is None:
            keep.append(b["blok"])
        else:
            rejected.append({"kaynak": b["kaynak"], "yol": b["yol"], "neden": reason})
    valid = rows[rows["blok"].isin(keep)].reset_index(drop=True) if len(rows) else rows
    return Archive(home, catalog, valid, rejected)


# ----------------------------------------------------------------------------
# Birleşik görünüm (aynı maç bir kez; çelişki görünür)
# ----------------------------------------------------------------------------

def _map_names(names: list, primary: list, league: str, src: str, primary_src: str) -> dict:
    """Bir kaynağın adlarını aynı lig-sezondaki bağlam adlarına KESİN kimlikle eşler (data.teams sözleşmesi);
    belirsiz veya eşleşmeyen ad eşlenmez. Doğrulanmış takma adlar iki yönde de denenir."""
    from collections import Counter

    from .data.teams import resolve_teams

    of = "openfootball"
    res = resolve_teams(names, primary, league, of if src == "openfootball-sonuc" else None)
    mapping = {n: m.team for n, m in res.items() if m.exact}
    missing = [n for n in names if n not in mapping]
    if missing:
        inv = resolve_teams(primary, names, league, of if primary_src == "openfootball-sonuc" else None)
        back: dict = {}
        for p, m in inv.items():
            if m.exact:
                back.setdefault(m.team, []).append(p)
        for n in missing:
            if len(back.get(n, [])) == 1:
                mapping[n] = back[n][0]
    hits = Counter(mapping.values())
    return {n: t for n, t in mapping.items() if hits[t] == 1}


def unified(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(birleşik maçlar, çelişkiler, inceleme). Birleşik satır: ``durum`` = TAMAM / CELISKI / TARIH_UYUSMAZ; yalnızca
    TAMAM satırlar özetlere girer."""
    from .goals.ledger import event_id

    cols = ["mac_kimligi", "league", "season", "date", "time", "home", "away", "fthg", "ftag", "hthg", "htag",
            "iy_mantiksal", "kaynaklar", "asil_kaynaklar", "bagimsiz_kaynak", "saglayici_mac_id", "xg_h", "xg_a",
            "sut_h", "sut_a", "durum"]
    if rows is None or rows.empty:
        return pd.DataFrame(columns=cols), pd.DataFrame(), pd.DataFrame()
    r = rows.copy()
    r["k_home"], r["k_away"] = None, None
    for (lg, season), g in r.groupby(["league", "season"], sort=False):
        present = [s for s in PRIORITY if s in set(g["kaynak"])]
        prim = present[0]
        pn = sorted(set(g.loc[g["kaynak"] == prim, "home"]) | set(g.loc[g["kaynak"] == prim, "away"]))
        for s in present:
            gi = g[g["kaynak"] == s]
            names = sorted(set(gi["home"]) | set(gi["away"]))
            mp = {n: n for n in names} if s == prim else _map_names(names, pn, lg, s, prim)
            r.loc[gi.index, "k_home"] = gi["home"].map(mp)
            r.loc[gi.index, "k_away"] = gi["away"].map(mp)
    unresolved = r["k_home"].isna() | r["k_away"].isna()
    review = r[unresolved].assign(neden="TAKIM_KIMLIGI_KESIN_DEGIL")
    ok = r[~unresolved].copy()
    ok["_day"] = pd.to_datetime(ok["date"]).dt.normalize()
    out, conflicts = [], []

    def pairs(g, a, b):
        return {(x, y) for x, y in zip(g[a], g[b]) if pd.notna(x) and pd.notna(y)}

    for (lg, day, h, a), g in ok.groupby(["league", "_day", "k_home", "k_away"], sort=True):
        ft, ht = pairs(g, "fthg", "ftag"), pairs(g, "hthg", "htag")
        real_ht = pairs(g[~g["iy_mantiksal"]], "hthg", "htag")
        status = "CELISKI" if (len(ft) > 1 or len(ht) > 1) else "TAMAM"
        if status == "CELISKI":
            for _, x in g.iterrows():
                conflicts.append({"mac_kimligi": event_id(lg, day, h, a), "kaynak": x["kaynak"], "blok": x["blok"],
                                  "asil_kaynak": x["asil_kaynak"], "ms": (x["fthg"], x["ftag"]),
                                  "iy": (x["hthg"], x["htag"])})
        f = next(iter(ft)) if len(ft) == 1 else (np.nan, np.nan)
        hh = next(iter(ht)) if len(ht) == 1 else (np.nan, np.nan)
        sid = [str(v) for v in g["saglayici_mac_id"] if v not in (None, "") and pd.notna(v)]
        out.append({"mac_kimligi": event_id(lg, day, h, a), "league": lg, "season": g["season"].iloc[0], "date": day,
                    "time": next((t for t in g["time"] if isinstance(t, str) and t), ""), "home": h, "away": a,
                    "fthg": f[0] if status == "TAMAM" else np.nan, "ftag": f[1] if status == "TAMAM" else np.nan,
                    "hthg": hh[0] if status == "TAMAM" else np.nan, "htag": hh[1] if status == "TAMAM" else np.nan,
                    "iy_mantiksal": bool(status == "TAMAM" and len(ht) == 1 and not real_ht),
                    "kaynaklar": ",".join(sorted(set(g["kaynak"]))), "asil_kaynaklar": ",".join(sorted(set(g["asil_kaynak"]))),
                    "bagimsiz_kaynak": len(set(g["asil_kaynak"])), "saglayici_mac_id": ",".join(sid) or None,
                    "xg_h": g["xg_h"].dropna().iloc[0] if g["xg_h"].notna().any() else np.nan,
                    "xg_a": g["xg_a"].dropna().iloc[0] if g["xg_a"].notna().any() else np.nan,
                    "sut_h": g["sut_h"].dropna().iloc[0] if g["sut_h"].notna().any() else np.nan,
                    "sut_a": g["sut_a"].dropna().iloc[0] if g["sut_a"].notna().any() else np.nan,
                    "durum": status})
    merged = pd.DataFrame(out, columns=cols)
    # Aynı lig-sezonda aynı ev/deplasman eşleşmesi farklı tarihlerde: toleransla bağlanmaz, incelemeye ayrılır
    if len(merged):
        dup = merged.duplicated(subset=["league", "season", "home", "away"], keep=False)
        merged.loc[dup, "durum"] = "TARIH_UYUSMAZ"
        if dup.any():
            review = pd.concat([review, merged[dup].assign(neden="AYNI_ESLESME_FARKLI_TARIH")], ignore_index=True)
    return merged.reset_index(drop=True), pd.DataFrame(conflicts), review.reset_index(drop=True)


def filter_matches(merged: pd.DataFrame, kaynak=None, lig=None, sezon=None, takim=None, yer=None, bas=None,
                   son=None) -> pd.DataFrame:
    """Kaynak, lig, sezon, takım (birleşik görünümdeki tam ad), ev/deplasman (takım verildiyse) ve tarih aralığı."""
    m = merged
    if m.empty:
        return m
    if kaynak:
        m = m[m["kaynaklar"].str.split(",").map(lambda xs: kaynak in xs)]
    if lig:
        m = m[m["league"] == lig]
    if sezon:
        m = m[m["season"] == sezon]
    if takim:
        if yer == "ev":
            m = m[m["home"] == takim]
        elif yer == "deplasman":
            m = m[m["away"] == takim]
        else:
            m = m[(m["home"] == takim) | (m["away"] == takim)]
    if bas:
        m = m[m["date"] >= pd.Timestamp(bas)]
    if son:
        m = m[m["date"] <= pd.Timestamp(son)]
    return m


def labelled(merged: pd.DataFrame) -> pd.DataFrame:
    """Pazar etiketleri (A/B/C) ve İY/MS — merkezi pazar kaydından; yalnızca TAMAM satırlarda, diğerleri bilinmiyor."""
    from .goals.markets import PRIMARY_YES, SHORT, frame_issues, htft_frame, label_frame

    m = merged.copy()
    if m.empty:
        for c in ("A", "B", "C", "iy_ms", "veri_kalitesi"):
            m[c] = pd.Series(dtype=object)
        return m
    ok = m["durum"] == "TAMAM"
    labs = label_frame(m, PRIMARY_YES)
    for key in PRIMARY_YES:
        m[SHORT[key]] = labs[key].where(ok)
    m["iy_ms"] = htft_frame(m).where(ok)
    issues = frame_issues(m)
    m["veri_kalitesi"] = np.where(~ok, m["durum"], np.where(issues != "", issues, np.where(
        m["hthg"].isna(), "IY_YOK", np.where(m["iy_mantiksal"], "IY_MANTIKSAL_0_0", "TAM"))))
    return m


def summary(merged: pd.DataFrame) -> dict:
    """Toplu tarihsel gerçekleşme özeti (geçerli örnek sayılarıyla). Olasılık veya bahis avantajı değildir."""
    from .goals.markets import HTFT_KEYS, MARKETS, PRIMARY_YES, SHORT

    m = labelled(merged)
    ok = m[m["durum"] == "TAMAM"] if len(m) else m
    out = {"aciklama": ARCHIVE_NOTE, "mac": int(len(m)), "birlesik_gecerli": int(len(ok)),
           "celiskili": int((m["durum"] == "CELISKI").sum()) if len(m) else 0,
           "incelemede": int((m["durum"] == "TARIH_UYUSMAZ").sum()) if len(m) else 0,
           "karantina": int(m["veri_kalitesi"].isin(["GECERSIZ_MAC_SONU", "GECERSIZ_ILK_YARI",
                                                     "ILK_YARI_MAC_SONUNU_ASIYOR"]).sum()) if len(m) else 0,
           "ms_gecerli": int(ok["fthg"].notna().sum()) if len(ok) else 0,
           "iy_gecerli": int(ok["hthg"].notna().sum()) if len(ok) else 0,
           "iy_mantiksal_0_0": int(ok["iy_mantiksal"].sum()) if len(ok) else 0, "pazarlar": {}, "iy_ms": {}}
    for key in PRIMARY_YES:
        col = ok[SHORT[key]] if len(ok) else pd.Series(dtype=float)
        n = int(col.notna().sum())
        yes = int((col == 1.0).sum())
        out["pazarlar"][SHORT[key]] = {"anahtar": key, "ad": MARKETS[key].name_tr, "evet": yes, "gecerli": n,
                                       "bilinmiyor": int(len(ok) - n), "gerceklesme_orani": (yes / n) if n else None}
    codes = ok["iy_ms"].dropna() if len(ok) else pd.Series(dtype=object)
    out["iy_ms_gecerli"] = int(len(codes))
    out["iy_ms"] = {k: int((codes == k).sum()) for k in HTFT_KEYS}
    return out


def resolve_source(name):
    """CLI/arayüz kısa adı (openfootball, datasets, xgabora, hudl) veya kayıt anahtarı -> kayıt anahtarı."""
    if name in (None, ""):
        return None
    key = SHORT_NAMES.get(name, name)
    if key not in SOURCE_KEYS:
        raise ArchiveError(f"Bilinmeyen kaynak: {name}")
    return key


def explore(archive: Archive, **filters) -> tuple[pd.DataFrame, dict]:
    """Filtrelenmiş birleşik maç listesi (pazar etiketli) ve aynı filtreyle toplu özet. Özet ayrıca kimlik incelemesine
    ayrılan satırları ve kaynak dosyalarında karantinaya alınan kayıtları (filtreye uyan bloklardan) sayar."""
    if filters.get("kaynak"):
        filters["kaynak"] = resolve_source(filters["kaynak"])
    merged, conflicts, review = unified(archive.rows)
    sel = filter_matches(merged, **filters)
    out = summary(sel)
    rv = review
    for col, key in (("league", "lig"), ("season", "sezon")):
        if filters.get(key) and len(rv):
            rv = rv[rv[col] == filters[key]]
    if filters.get("kaynak") and len(rv) and "kaynak" in rv:
        rv = rv[rv["kaynak"].fillna("").astype(str).str.contains(filters["kaynak"], regex=False)
                | rv.get("kaynaklar", pd.Series("", index=rv.index)).fillna("").astype(str).str.contains(
                    filters["kaynak"], regex=False)]
    out["kimlik_veya_tarih_incelemesi"] = int(len(rv))
    blocks = [b for b in archive.blocks() if b.get("tarihsel_analiz") and b.get("tur") != "mac_listesi"
              and (not filters.get("lig") or b.get("lig") == filters["lig"])
              and (not filters.get("sezon") or b.get("sezon") == filters["sezon"])
              and (not filters.get("kaynak") or b.get("kaynak") == filters["kaynak"])]
    kar: dict = {}
    for b in blocks:
        for k, v in (b.get("karantina") or {}).items():
            kar[k] = kar.get(k, 0) + int(v)
    out["kaynak_karantinasi"] = kar
    out["dogrulanamayan_blok"] = len(archive.rejected)
    out["celiski_kaydi"] = int(len(conflicts))
    return labelled(sel), out


def event_card_for(archive: Archive, mac_kimligi: str, team: str) -> dict:
    """Seçilen geçmiş maç için mevcut dizi olay kartı (``sequences.timeline.event_card``). Yeni hipotez taraması veya
    model eğitimi yapılmaz; kart yalnızca geçmiş incelemedir."""
    from .data.parsers import MATCH_COLUMNS
    from .sequences.timeline import build_team_matches, event_card

    merged, _, _ = unified(archive.rows)
    row = merged[merged["mac_kimligi"] == mac_kimligi]
    if row.empty:
        raise ArchiveError("Maç arşivde yok.")
    lg = row["league"].iloc[0]
    m = merged[(merged["league"] == lg) & (merged["durum"] == "TAMAM")].copy()
    m["source"] = m["kaynaklar"]
    frame = m.reindex(columns=MATCH_COLUMNS)
    tm = build_team_matches(frame)
    hit = tm.index[(tm["event_id"] == mac_kimligi) & (tm["team_raw"] == team)]
    if not len(hit):
        raise ArchiveError("Takım bu maçta yok veya maçın skoru doğrulanmadı (çelişki/inceleme).")
    return event_card(tm, int(hit[0]), data_meta={"updated_at": archive.catalog.get("olusturma_utc")})

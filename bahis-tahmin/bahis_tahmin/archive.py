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
            rejected.append({"kaynak": b["kaynak"], "yol": b["yol"], "neden": reason, "blok": b.get("blok"),
                             "lig": b.get("lig"), "sezon": b.get("sezon")})
    valid = rows[rows["blok"].isin(keep)].reset_index(drop=True) if len(rows) else rows
    return Archive(home, catalog, valid, rejected)


# ----------------------------------------------------------------------------
# Görünümler: TEK KAYNAK / BİRLEŞTİRİLMİŞ (S5-ARSIV-02)
# ----------------------------------------------------------------------------
#
# Tek kaynak görünümünde kaynak filtresi BİRLEŞTİRMEDEN ÖNCE ham kaynak satırlarına uygulanır: kimlik eşleme,
# tekilleştirme ve etiketleme yalnızca o kaynağın kayıtlarıyla yapılır; başka kaynaktan İY, xG, şut, saat veya başka
# alan taşınmaz, eksik alan eksik kalır. Birleştirilmiş görünümde analizi açık bütün kaynaklar birleşir; aynı maç bir
# kez sayılır ve her gösterilen alanın kaynağı satırda yazılır. Listeler, özet sayaçları ve olay kartı aynı görünümden
# ve aynı filtreden üretilir. Hiçbir görünüm model eğitimi veya tahmin gösterimi izni değildir.

MERGED_VIEW = "birlesik"
VIEW_SINGLE, VIEW_MERGED = "TEK_KAYNAK", "BIRLESIK"
MERGED_NOTE = ("Birleştirilmiş görünüm: tek bir kaynak değildir. Tarihsel analizi açık bütün kaynakların kayıtları "
               "birleştirilir; aynı maç bir kez sayılır, kaynaklar satırda yazılır. Bu görünüm kaynaklar arası alan "
               "birleştirmesi içerir (ör. İY, saat, xG/şut başka bir kaynaktan gelebilir; alan kökeni sütunlarda).")
SINGLE_NOTE = ("Tek kaynak görünümü ({kaynak}): yalnızca bu kaynağın kayıtları; başka kaynaktan alan taşınmaz, eksik alan "
               "eksik kalır.")
CLOSED_NOTE = ("{kaynak}: tarihsel analiz kullanım kapsamı nedeniyle kapalı; bu görünümde maç yok ve başka kaynaktan veri "
               "gösterilmez.")
USE_NOTE = "Hiçbir görünüm model eğitimi veya tahmin gösterimi izni değildir."
QUARANTINE_NOTE = ("Seçili kaynak/lig/sezon dosyalarındaki toplam karantina (dosya düzeyi kaynak kaydı); takım ve tarih "
                   "filtresine indirgenemez.")
CARD_SCOPE_NOTE = ("Önce/sonra pencereleri bu görünümün aynı ligdeki doğrulanmış (TAMAM) maçlarından alınır; seçili "
                   "listenin sezon, takım ve tarih filtresiyle sınırlı değildir ve önceki/sonraki sezona taşabilir. "
                   "Çelişkili veya incelemedeki maçlar pencerelere girmez.")
UNITS = {"mac": "benzersiz maç (tarih uyuşmazlığındaki eşleşme bir kez sayılır)",
         "liste_satiri": "listede görünen satır",
         "kaynak_satiri": "kaynak kaydı (bir maçın birden çok kaynak kaydı olabilir)",
         "blok_sayisi": "kaynak dosyası / lig-sezon bloğu"}
FIELD_COLUMNS = ("ms_kaynaklari", "iy_kaynaklari", "saat_kaynagi", "xg_kaynagi", "sut_kaynagi", "alan_birlesimi")
SOURCE_SHORT = {v: k for k, v in SHORT_NAMES.items()}


def _map_names(names: list, primary: list, league: str, src: str, primary_src: str) -> dict:
    """Bir kaynağın adlarını aynı lig-sezondaki bağlam adlarına KESİN kimlikle eşler (data.teams sözleşmesi);
    belirsiz veya eşleşmeyen ad eşlenmez. Doğrulanmış takma adlar iki yönde de denenir."""
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


def _txt(v) -> str:
    return v if isinstance(v, str) else ""


def unified(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Verilen kaynak satırlarından (birleşik maçlar, çelişkiler, inceleme). Birleşik satır: ``durum`` = TAMAM / CELISKI
    / TARIH_UYUSMAZ; yalnızca TAMAM satırlar özetlere girer. Yalnızca VERİLEN satırlar kullanılır: tek kaynak görünümü
    için satırlar önceden süzülmelidir (``view``). Alan kökeni (``ms_kaynaklari``, ``iy_kaynaklari``, ``saat_kaynagi``,
    ``xg_kaynagi``, ``sut_kaynagi``) ve ``alan_birlesimi`` (gösterilen bir alan maçın bütün kaynaklarından gelmiyor)
    satırda yazılır. Sonuç girdi satırlarının sırasından bağımsızdır."""
    from .goals.ledger import event_id

    cols = ["mac_kimligi", "league", "season", "date", "time", "home", "away", "fthg", "ftag", "hthg", "htag",
            "iy_mantiksal", "kaynaklar", "asil_kaynaklar", "bagimsiz_kaynak", "saglayici_mac_id", "xg_h", "xg_a",
            "sut_h", "sut_a", "durum", "kaynak_satiri", "bloklar", *FIELD_COLUMNS]
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
    # Belirli seçim: kaynak önceliği, blok ve değerlerle sıralanır (girdi satır sırası sonucu değiştirmez)
    ok["_prio"] = ok["kaynak"].map({k: i for i, k in enumerate(PRIORITY)}).fillna(len(PRIORITY))
    ok["_blok"] = pd.to_numeric(ok["blok"], errors="coerce").fillna(-1)
    ok["_time"] = ok["time"].map(_txt)
    ok["_sid"] = ok["saglayici_mac_id"].map(lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v))
                                            else str(v))
    ok = ok.sort_values(["league", "_day", "k_home", "k_away", "_prio", "_blok", "_time", "_sid", "fthg", "ftag",
                         "hthg", "htag", "xg_h", "xg_a", "sut_h", "sut_a"], kind="mergesort", na_position="last")
    out, conflicts = [], []
    # Maç grupları: groupby(sort=True) ile aynı gruplar, aynı grup sırası ve grup içinde aynı (öncelik) satır
    # sırası; anahtarı eksik satır gruba girmez (ngroup NaN). Grup başına küçük DataFrame seçimi yerine sütun
    # listeleri kullanılır (S6-PERF-03); alan kuralları değişmedi.
    gid = ok.groupby(["league", "_day", "k_home", "k_away"], sort=True).ngroup().to_numpy(dtype=float,
                                                                                           na_value=np.nan)
    pos = np.flatnonzero(np.isfinite(gid) & (gid >= 0))
    pos = pos[np.argsort(gid[pos], kind="stable")]
    starts = np.flatnonzero(np.r_[True, gid[pos][1:] != gid[pos][:-1]]) if len(pos) else np.zeros(0, dtype=int)
    col = {c: ok[c].tolist() for c in ("league", "_day", "k_home", "k_away", "season", "kaynak", "blok", "asil_kaynak",
                                        "fthg", "ftag", "hthg", "htag", "iy_mantiksal", "_time", "_sid", "_blok",
                                        "xg_h", "xg_a", "sut_h", "sut_a")}
    src = col["kaynak"]

    def pairs(g, a, b):
        xa, xb = col[a], col[b]
        return {(xa[i], xb[i]) for i in g if pd.notna(xa[i]) and pd.notna(xb[i])}

    def first_pair(g, a, b):
        """İki alanı birlikte dolu ilk satır (öncelik sırasıyla): (değer_a, değer_b, kaynak)."""
        xa, xb = col[a], col[b]
        for i in g:
            if pd.notna(xa[i]) and pd.notna(xb[i]):
                return xa[i], xb[i], src[i]
        return np.nan, np.nan, None

    for s0, s1 in zip(starts.tolist(), [*starts[1:].tolist(), len(pos)]):
        g = pos[s0:s1].tolist()  # bu maçın satırları (konum), öncelik sırasıyla
        i0 = g[0]
        lg, day, h, a = col["league"][i0], col["_day"][i0], col["k_home"][i0], col["k_away"][i0]
        ft, ht = pairs(g, "fthg", "ftag"), pairs(g, "hthg", "htag")
        real_ht = pairs([i for i in g if not bool(col["iy_mantiksal"][i])], "hthg", "htag")
        status = "CELISKI" if (len(ft) > 1 or len(ht) > 1) else "TAMAM"
        mid = event_id(lg, day, h, a)
        if status == "CELISKI":
            for i in g:
                conflicts.append({"mac_kimligi": mid, "kaynak": src[i], "blok": col["blok"][i],
                                  "asil_kaynak": col["asil_kaynak"][i], "ms": (col["fthg"][i], col["ftag"][i]),
                                  "iy": (col["hthg"][i], col["htag"][i])})
        f = next(iter(ft)) if len(ft) == 1 else (np.nan, np.nan)
        hh = next(iter(ht)) if len(ht) == 1 else (np.nan, np.nan)
        srcs = sorted({src[i] for i in g})
        ms_src = sorted({src[i] for i in g if pd.notna(col["fthg"][i]) and pd.notna(col["ftag"][i])})
        iy_src = sorted({src[i] for i in g if pd.notna(col["hthg"][i]) and pd.notna(col["htag"][i])})
        timed = [i for i in g if col["_time"][i] != ""]
        t, t_src = (col["_time"][timed[0]], src[timed[0]]) if timed else ("", None)
        xh, xa, x_src = first_pair(g, "xg_h", "xg_a")
        sh, sa, s_src = first_pair(g, "sut_h", "sut_a")
        shown = [set(ms_src) if status == "TAMAM" and ms_src else None,
                 set(iy_src) if status == "TAMAM" and iy_src else None,
                 {t_src} if t_src else None, {x_src} if x_src else None, {s_src} if s_src else None]
        sid = sorted({col["_sid"][i] for i in g if col["_sid"][i]})
        origins = {col["asil_kaynak"][i] for i in g}
        out.append({"mac_kimligi": mid, "league": lg, "season": col["season"][i0], "date": day, "time": t,
                    "home": h, "away": a,
                    "fthg": f[0] if status == "TAMAM" else np.nan, "ftag": f[1] if status == "TAMAM" else np.nan,
                    "hthg": hh[0] if status == "TAMAM" else np.nan, "htag": hh[1] if status == "TAMAM" else np.nan,
                    "iy_mantiksal": bool(status == "TAMAM" and len(ht) == 1 and not real_ht),
                    "kaynaklar": ",".join(srcs), "asil_kaynaklar": ",".join(sorted(origins)),
                    "bagimsiz_kaynak": len(origins), "saglayici_mac_id": ",".join(sid) or None,
                    "xg_h": xh, "xg_a": xa, "sut_h": sh, "sut_a": sa, "durum": status, "kaynak_satiri": len(g),
                    "bloklar": ",".join(str(int(b)) for b in sorted({col["_blok"][i] for i in g}) if b >= 0),
                    "ms_kaynaklari": ",".join(ms_src), "iy_kaynaklari": ",".join(iy_src), "saat_kaynagi": t_src,
                    "xg_kaynagi": x_src, "sut_kaynagi": s_src,
                    "alan_birlesimi": bool(len(srcs) > 1 and any(s is not None and s != set(srcs) for s in shown))})
    merged = pd.DataFrame(out, columns=cols)
    # Aynı lig-sezonda aynı ev/deplasman eşleşmesi farklı tarihlerde: toleransla bağlanmaz, incelemeye ayrılır
    if len(merged):
        dup = merged.duplicated(subset=["league", "season", "home", "away"], keep=False)
        merged.loc[dup, "durum"] = "TARIH_UYUSMAZ"
        if dup.any():
            review = pd.concat([review, merged[dup].assign(neden="AYNI_ESLESME_FARKLI_TARIH")], ignore_index=True)
    conflicts = pd.DataFrame(conflicts)
    if len(conflicts):
        conflicts = conflicts.sort_values(["mac_kimligi", "kaynak", "blok"], kind="mergesort").reset_index(drop=True)
    if len(review):
        keys = review.reindex(columns=["neden", "league", "season", "date", "kaynak", "home", "away"]).astype(str)
        review = review.loc[keys.sort_values(list(keys.columns), kind="mergesort").index]
    return merged.reset_index(drop=True), conflicts, review.reset_index(drop=True)


@dataclass
class ArchiveView:
    """Tek kaynak (``kaynak`` dolu) veya birleştirilmiş (``kaynak`` None) görünüm: listeler, sayaçlar ve olay kartı
    bunu ortak bağlam olarak kullanır."""
    kaynak: str | None
    rows: pd.DataFrame  # görünüme giren kaynak satırları
    merged: pd.DataFrame
    conflicts: pd.DataFrame
    review: pd.DataFrame
    kapali: bool = False  # seçilen kaynağın tarihsel analizi kapalı

    @property
    def tur(self) -> str:
        return VIEW_MERGED if self.kaynak is None else VIEW_SINGLE

    def aciklama(self) -> str:
        if self.kaynak is None:
            return MERGED_NOTE
        return (CLOSED_NOTE if self.kapali else SINGLE_NOTE).format(kaynak=self.kaynak)

    def teams(self) -> list:
        m = self.merged
        return sorted(set(m["home"]) | set(m["away"])) if len(m) else []


def view(archive: Archive, kaynak=None) -> ArchiveView:
    """Görünüm kur. ``kaynak`` (kısa ad veya kayıt anahtarı) verilirse YALNIZCA o kaynağın satırları birleştirilir;
    None veya ``"birlesik"`` birleştirilmiş görünümdür. Tarihsel analizi kapalı kaynak seçilirse görünüm boştur (başka
    kaynaktan veri getirilmez)."""
    key = resolve_source(kaynak)
    rows = archive.rows
    if len(rows):  # savunma: yalnızca tarihsel analizi açık kaynakların satırları
        rows = rows[rows["kaynak"].map(lambda k: archive_allowed(str(k), "tarihsel_analiz"))]
    closed = key is not None and not archive_allowed(key, "tarihsel_analiz")
    if key is not None and len(rows):
        rows = rows[rows["kaynak"] == key]
    rows = rows.reset_index(drop=True)
    merged, conflicts, review = unified(rows)
    return ArchiveView(key, rows, merged, conflicts, review, closed)


def filter_matches(merged: pd.DataFrame, kaynak=None, lig=None, sezon=None, takim=None, yer=None, bas=None,
                   son=None) -> pd.DataFrame:
    """Lig, sezon, takım (görünümdeki tam ad), ev/deplasman (takım verildiyse) ve tarih aralığı. ``kaynak`` yalnızca
    geriye uyum içindir ve birleşik satırın kaynak listesine bakar; tek kaynak görünümü için ``view`` kullanılmalıdır
    (birleştirmeden önce süzer)."""
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


def _in_filter(league, season, day, home, away, flt: dict) -> bool:
    """Tek bir maç ``filter_matches`` ile aynı kurallarla filtreye giriyor mu (olay kartı pencereleri için)."""
    if flt.get("lig") and league != flt["lig"]:
        return False
    if flt.get("sezon") and str(season) != flt["sezon"]:
        return False
    takim, yer = flt.get("takim"), flt.get("yer")
    if takim:
        if yer == "ev" and home != takim:
            return False
        if yer == "deplasman" and away != takim:
            return False
        if yer not in ("ev", "deplasman") and takim not in (home, away):
            return False
    day = pd.Timestamp(day).normalize()
    if flt.get("bas") and day < pd.Timestamp(flt["bas"]):
        return False
    if flt.get("son") and day > pd.Timestamp(flt["son"]):
        return False
    return True


def _identity_review(review: pd.DataFrame, lig=None, sezon=None, takim=None, yer=None, bas=None,
                     son=None) -> tuple[pd.DataFrame, int | None]:
    """Takım kimliği kesinleşmeyen kaynak satırları, maç listesiyle aynı filtreyle. Takım filtresinde, ilgili tarafı
    çözülemediği için seçili takıma ait olup olmadığı BİLİNEMEYEN satırlar ayrıca sayılır (takım filtresi yoksa None)."""
    if review is None or review.empty or "neden" not in review:
        return pd.DataFrame(), (0 if takim else None)
    x = review[review["neden"] == "TAKIM_KIMLIGI_KESIN_DEGIL"]
    if lig:
        x = x[x["league"] == lig]
    if sezon:
        x = x[x["season"] == sezon]
    if bas:
        x = x[pd.to_datetime(x["date"]).dt.normalize() >= pd.Timestamp(bas)]
    if son:
        x = x[pd.to_datetime(x["date"]).dt.normalize() <= pd.Timestamp(son)]
    if not takim or x.empty:
        return x, (0 if takim else None)
    home_is = (x["k_home"] == takim) | (x["home"] == takim)
    away_is = (x["k_away"] == takim) | (x["away"] == takim)
    home_unknown = x["k_home"].isna() & (x["home"] != takim)
    away_unknown = x["k_away"].isna() & (x["away"] != takim)
    if yer == "ev":
        hit, unk = home_is, ~home_is & home_unknown
    elif yer == "deplasman":
        hit, unk = away_is, ~away_is & away_unknown
    else:
        hit = home_is | away_is
        unk = ~hit & (home_unknown | away_unknown)
    return x[hit], int(unk.sum())


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
    """Verilen (filtrelenmiş) birleşik satırların toplu tarihsel gerçekleşme özeti; bütün sayılar AYNI satırlardan.
    Birimler: ``mac`` benzersiz maç (tarih uyuşmazlığındaki eşleşme bir kez), ``liste_satiri`` listede görünen satır,
    ``kaynak_satiri`` kaynak kaydı, ``blok_sayisi`` kaynak dosyası/lig-sezon bloğu. Olasılık veya bahis avantajı
    değildir."""
    from .goals.markets import HTFT_KEYS, MARKETS, PRIMARY_YES, SHORT

    m = labelled(merged)
    ok = m[m["durum"] == "TAMAM"] if len(m) else m
    tu = m[m["durum"] == "TARIH_UYUSMAZ"] if len(m) else m
    tu_pairs = int(tu.groupby(["league", "season", "home", "away"]).ngroups) if len(tu) else 0
    has = (lambda c: c in m.columns and len(m) > 0)
    out = {"aciklama": ARCHIVE_NOTE, "birimler": UNITS,
           "mac": int(m["durum"].isin(["TAMAM", "CELISKI"]).sum()) + tu_pairs if len(m) else 0,
           "liste_satiri": int(len(m)),
           "kaynak_satiri": int(pd.to_numeric(m["kaynak_satiri"]).sum()) if has("kaynak_satiri") else int(len(m)),
           "blok_sayisi": (len({b for s in m["bloklar"] for b in str(s).split(",") if b}) if has("bloklar")
                           else None),
           "birlesik_gecerli": int(len(ok)),
           "celiskili": int((m["durum"] == "CELISKI").sum()) if len(m) else 0,
           "incelemede": tu_pairs, "incelemede_liste_satiri": int(len(tu)),
           "tarih_uyusmaz_kaynak_satiri": (int(pd.to_numeric(tu["kaynak_satiri"]).sum())
                                           if len(tu) and "kaynak_satiri" in tu.columns else int(len(tu))),
           "karantina": int(m["veri_kalitesi"].isin(["GECERSIZ_MAC_SONU", "GECERSIZ_ILK_YARI",
                                                     "ILK_YARI_MAC_SONUNU_ASIYOR"]).sum()) if len(m) else 0,
           "ms_gecerli": int(ok["fthg"].notna().sum()) if len(ok) else 0,
           "iy_gecerli": int(ok["hthg"].notna().sum()) if len(ok) else 0,
           "iy_mantiksal_0_0": int(ok["iy_mantiksal"].sum()) if len(ok) else 0,
           "alan_birlesimi_iceren_mac": int(m["alan_birlesimi"].astype(bool).sum()) if has("alan_birlesimi") else 0,
           "pazarlar": {}, "iy_ms": {}}
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
    """CLI/arayüz kısa adı (openfootball, datasets, xgabora, hudl) veya kayıt anahtarı -> kayıt anahtarı; boş veya
    ``"birlesik"`` -> None (birleştirilmiş görünüm)."""
    if name in (None, "", MERGED_VIEW):
        return None
    key = SHORT_NAMES.get(name, name)
    if key not in SOURCE_KEYS:
        raise ArchiveError(f"Bilinmeyen kaynak: {name}")
    return key


def field_origin(row) -> str:
    """Birleştirilmiş görünüm satırında gösterilen alanların kaynakları (kısa adlarla); alan birleştirmesi yoksa ''."""
    if not bool(row.get("alan_birlesimi")):
        return ""

    def short(s):
        return "+".join(SOURCE_SHORT.get(x, x) for x in str(s).split(",") if x) if isinstance(s, str) and s else ""

    parts = []
    for label, col in (("MS", "ms_kaynaklari"), ("İY", "iy_kaynaklari"), ("saat", "saat_kaynagi"),
                       ("xG", "xg_kaynagi"), ("şut", "sut_kaynagi")):
        if short(row.get(col)):
            parts.append(f"{label}: {short(row.get(col))}")
    return " · ".join(parts)


def explore_view(archive: Archive, v: ArchiveView, lig=None, sezon=None, takim=None, yer=None, bas=None,
                 son=None) -> tuple[pd.DataFrame, dict]:
    """Görünüm + filtre -> (pazar etiketli maç listesi, özet). Liste, pazar paydaları, İY/MS, çelişki ve inceleme
    sayaçları AYNI filtrelenmiş seçimden gelir. Takım/tarihe indirgenemeyen dosya düzeyi sayılar ayrı alanlarda ve
    açıklamalı; bütün arşiv sayıları yalnızca ``genel_arsiv_durumu`` altındadır."""
    flt = {"lig": lig, "sezon": sezon, "takim": takim, "yer": yer, "bas": bas, "son": son}
    sel = filter_matches(v.merged, **flt)
    out = summary(sel)
    out["gorunum"] = {"tur": v.tur, "kaynak": v.kaynak, "aciklama": v.aciklama(), "kullanim": USE_NOTE,
                      "tarihsel_analiz_kapali": v.kapali}
    out["filtre"] = {"kaynak": v.kaynak or MERGED_VIEW, **{k: x for k, x in flt.items() if x}}
    ids = set(sel.loc[sel["durum"] == "CELISKI", "mac_kimligi"]) if len(sel) else set()
    out["celiskili_mac"] = out["celiskili"]
    out["celiski_kaynak_satiri"] = int(v.conflicts["mac_kimligi"].isin(ids).sum()) if len(v.conflicts) else 0
    out["celiski_kaydi"] = out["celiski_kaynak_satiri"]  # geriye uyum: artık seçili filtrenin kaynak satırları
    kim, unknown = _identity_review(v.review, **flt)
    out["kimlik_incelemesi_kaynak_satiri"] = int(len(kim))
    out["kimlik_incelemesi_takima_indirgenemeyen"] = unknown
    out["kimlik_veya_tarih_incelemesi"] = int(len(kim))  # geriye uyum; tarih uyuşmazlığı ``incelemede`` altında
    if takim and takim not in v.teams():
        out["takim_gorunumde_yok"] = ("Bu görünümde bu adla takım yok; tek kaynak görünümünde takım adları kaynağın "
                                      "kendi adlarıdır.")
    in_view = (lambda k: (k == v.kaynak) if v.kaynak is not None else archive_allowed(str(k), "tarihsel_analiz"))
    blocks = [b for b in archive.blocks() if b.get("tarihsel_analiz") and b.get("tur") != "mac_listesi"
              and in_view(b.get("kaynak")) and (not lig or b.get("lig") == lig)
              and (not sezon or b.get("sezon") == sezon)]
    kar: dict = {}
    for b in blocks:
        for k, n in (b.get("karantina") or {}).items():
            kar[k] = kar.get(k, 0) + int(n)
    out["kaynak_karantinasi"] = kar
    out["kaynak_karantinasi_kapsami"] = {
        "birim": "kaynak kaydı (dosya düzeyi)", "kaynak": v.kaynak or "tarihsel analizi açık bütün kaynaklar",
        "lig": lig, "sezon": sezon, "blok_sayisi": len(blocks), "toplam": int(sum(kar.values())),
        "takim_tarih_filtresine_indirgenebilir": False, "takim_tarih_filtresi_var": bool(takim or yer or bas or son),
        "not": QUARANTINE_NOTE}
    rej = [x for x in archive.rejected if in_view(x.get("kaynak")) and (not lig or x.get("lig") in (lig, None))
           and (not sezon or x.get("sezon") in (sezon, None))]
    out["dogrulanamayan_blok"] = len(rej)  # seçili kaynak/lig/sezon (dosya düzeyi; takım/tarihe indirgenemez)
    out["genel_arsiv_durumu"] = {"aciklama": "Filtreden bağımsız, bütün arşiv.",
                                 "dogrulanamayan_blok": len(archive.rejected),
                                 "analiz_kaynak_satiri": int(len(archive.rows)), "blok": len(archive.blocks())}
    lab = labelled(sel)
    if len(lab):
        lab["alan_kokeni"] = [field_origin(r) for _, r in lab.iterrows()]
    else:
        lab["alan_kokeni"] = pd.Series(dtype=object)
    return lab, out


def explore(archive: Archive, **filters) -> tuple[pd.DataFrame, dict]:
    """Filtrelenmiş maç listesi (pazar etiketli) ve aynı seçimden özet. ``kaynak`` verilirse tek kaynak görünümü
    (birleştirmeden ÖNCE süzülür); verilmezse veya ``"birlesik"`` ise birleştirilmiş görünüm."""
    filters = dict(filters)
    v = view(archive, filters.pop("kaynak", None))
    return explore_view(archive, v, **filters)


def _card_scope(card: dict, v: ArchiveView, liste_filtresi: dict | None) -> dict:
    by_id: dict = {}
    for block in ("PRE_EVENT", "POST_EVENT", "RAKIP_PRE_EVENT"):
        for w in card.get(block, {}).values():
            for rec in w.get("maclar", []):
                by_id[rec["event_id"]] = rec
    flt = {k: x for k, x in (liste_filtresi or {}).items() if x and k != "kaynak"}
    outside = 0
    for eid, rec in by_id.items():
        lg, day, home, away = str(eid).split("|", 3)
        if not _in_filter(lg, rec.get("season"), day, home, away, flt):
            outside += 1
    days = sorted(pd.Timestamp(rec["date"]).normalize() for rec in by_id.values())
    return {"tur": v.tur, "kaynak": v.kaynak, "aciklama": v.aciklama(), "pencere_kapsami": CARD_SCOPE_NOTE,
            "pencere_maci": len(by_id), "pencere_sezonlari": sorted({str(rec.get("season")) for rec in by_id.values()}),
            "pencere_tarih_araligi": [str(days[0].date()), str(days[-1].date())] if days else None,
            "liste_filtresi": flt, "liste_disi_pencere_maci": outside if flt else None}


def event_card_for(archive: Archive, mac_kimligi: str, team: str, kaynak=None, liste_filtresi: dict | None = None,
                   gorunum: ArchiveView | None = None) -> dict:
    """Seçilen geçmiş maç için mevcut dizi olay kartı (``sequences.timeline.event_card``), listeyle AYNI görünümde:
    ``gorunum`` (veya ``kaynak``) verilmezse birleştirilmiş görünüm. Kartın ``gorunum`` bloğu kaynak bağlamını ve
    pencerelerin seçili listenin dışına taşan maç sayısını yazar. Yeni hipotez taraması veya model eğitimi yapılmaz;
    kart yalnızca geçmiş incelemedir."""
    v = gorunum if gorunum is not None else view(archive, kaynak)
    merged = v.merged
    row = merged[merged["mac_kimligi"] == mac_kimligi] if len(merged) else merged
    if row.empty:
        raise ArchiveError("Maç bu görünümde yok.")
    tm = team_matches(v, row["league"].iloc[0])
    return event_card_in(archive, v, tm, mac_kimligi, team, liste_filtresi)


def team_matches(v: ArchiveView, league: str) -> pd.DataFrame:
    """Görünümün bir ligdeki doğrulanmış (TAMAM) maçlarından takım-maç tablosu (``sequences.timeline``); olay kartı
    pencereleri bu tablodan alınır. Aynı görünümde birden çok kart için bir kez kurulup ``event_card_in`` ile
    yeniden kullanılabilir."""
    from .data.parsers import MATCH_COLUMNS
    from .sequences.timeline import build_team_matches

    merged = v.merged
    m = merged[(merged["league"] == league) & (merged["durum"] == "TAMAM")].copy()
    m["source"] = m["kaynaklar"]
    return build_team_matches(m.reindex(columns=MATCH_COLUMNS))


def event_card_in(archive: Archive, v: ArchiveView, tm: pd.DataFrame, mac_kimligi: str, team: str,
                  liste_filtresi: dict | None = None, pre=(5, 10), post=(1, 3, 5)) -> dict:
    """``event_card_for`` ile aynı kart, hazır takım-maç tablosundan (``team_matches(v, lig)``)."""
    from .sequences.timeline import event_card

    hit = tm.index[(tm["event_id"] == mac_kimligi) & (tm["team_raw"] == team)]
    if not len(hit):
        raise ArchiveError("Takım bu maçta yok veya maçın skoru doğrulanmadı (çelişki/inceleme).")
    card = event_card(tm, int(hit[0]), pre=pre, post=post,
                      data_meta={"updated_at": archive.catalog.get("olusturma_utc")})
    card["gorunum"] = _card_scope(card, v, liste_filtresi)
    return card

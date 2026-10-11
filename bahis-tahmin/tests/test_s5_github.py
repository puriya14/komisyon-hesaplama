"""S5-GITHUB-01: GitHub veri profili, sürümlü önbellek, kaynak okuyucular ve tarihsel arşiv.

Bütün testler sentetik veriyle ve sahte HTTP oturumuyla çalışır (gerçek ham veri veya ağ gerekmez).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import pytest

from bahis_tahmin import archive as A
from bahis_tahmin.data.github_kaynak import (
    FETCHED,
    GITHUB_HOSTS,
    IMPORTED,
    REPOS,
    STALE_COPY,
    VERIFIED_CACHE,
    GitHubCache,
    GitHubError,
    GitHubTransport,
    host_of,
)
from bahis_tahmin.data.source_registry import ARCHIVE_OPERATIONS, allowed_sources, archive_allowed, archive_scope
from bahis_tahmin.data.sources import Downloader, DownloadError
from bahis_tahmin.data.statsbomb import INCOMPLETE, MISMATCH, OK, score_from_events

C_OF, C_DS, C_XG, C_HU = "a" * 40, "b" * 40, "c" * 40, "d" * 40
COMMITS = {"openfootball/football.json": C_OF, "datasets/football-datasets": C_DS,
           "xgabora/Club-Football-Match-Data-2000-2025": C_XG, "hudl/open-data": C_HU}
TODAY = dt.date(2025, 6, 1)
ALL = ("football-datasets", "github-mirror")


class Resp:
    def __init__(self, status: int, content: bytes = b"", headers: dict | None = None):
        self.status_code, self.content, self.headers = status, content, headers or {}


class FakeSession:
    """requests.Session yerine: adres -> yanıt; bilinmeyen adres 404. Bütün çağrılar kaydedilir."""

    def __init__(self, routes: dict | None = None, default: int = 404):
        self.routes, self.default, self.calls = dict(routes or {}), default, []

    def get(self, url, headers=None, timeout=None, allow_redirects=True):
        self.calls.append(url)
        r = self.routes.get(url)
        return r if r is not None else Resp(self.default)


def adv(refs: dict) -> bytes:
    def pkt(s: str) -> bytes:
        b = s.encode()
        return f"{len(b) + 4:04x}".encode() + b

    out = pkt("# service=git-upload-pack\n") + b"0000"
    for i, (ref, sha) in enumerate(refs.items()):
        out += pkt(f"{sha} {ref}" + ("\0multi_ack side-band-64k" if i == 0 else "") + "\n")
    return out + b"0000"


def raw(repo: str, commit: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{quote(path)}"


def refs_url(repo: str) -> str:
    return f"https://github.com/{repo}.git/info/refs?service=git-upload-pack"


def of_season(extra: list | None = None) -> bytes:
    matches = [
        {"round": "Matchday 1", "date": "2024-08-17", "team1": "Arsenal FC", "team2": "Chelsea FC",
         "score": {"ht": [1, 0], "ft": [2, 1]}},
        {"round": "Matchday 1", "date": "2024-08-17", "team1": "Liverpool FC", "team2": "Everton FC",
         "score": {"ft": [0, 0]}},  # İY yok, MS 0-0: v2'de mantıksal 0-0 (işaretli)
        {"round": "Matchday 2", "date": "2024-08-24", "team1": "Chelsea FC", "team2": "Liverpool FC",
         "score": {"ft": [3, 1]}},  # İY yok: bilinmiyor (0-0 yapılmaz)
        {"round": "Matchday 2", "date": "2024-08-24", "team1": "Everton FC", "team2": "Arsenal FC",
         "score": {"ht": [0, 0], "ft": [0, 2]}},  # gerçek 0-0 İY
    ] + (extra or [])
    return json.dumps({"name": "Premier League 2024/25", "matches": matches}).encode()


DS_CSV = (b"Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR\n"
          b"17/08/2024,Arsenal,Chelsea,2,1,H,1,0,H\n"
          b"17/08/2024,Arsenal,Chelsea,2,1,H,1,0,H\n"  # birebir tekrar: bir kez sayılır
          b"24/08/2024,Everton,Arsenal,0,2,A,3,0,H\n")  # İY > MS: karantina
XG_CSV = (b"Division,MatchDate,MatchTime,HomeTeam,AwayTeam,HomeElo,AwayElo,Form3Home,FTHome,FTAway,FTResult,HTHome,"
          b"HTAway,HTResult,OddHome,OddDraw,OddAway\n"
          b"E0,2024-08-17,15:00,Arsenal,Chelsea,1900,1850,7,2,1,H,1,0,H,1.8,3.5,4.2\n")


def ev(period, type_id, team_id, outcome=None, xg=None):
    e = {"period": period, "type": {"id": type_id}, "team": {"id": team_id}}
    if type_id == 16:
        e["shot"] = {"outcome": {"id": outcome}, "statsbomb_xg": xg}
    return e


def half(team_id=1):
    return [{"period": 1, "type": {"id": 35}, "team": {"id": team_id}},
            {"period": 2, "type": {"id": 35}, "team": {"id": team_id}}]


HUDL_MATCHES = [
    {"match_id": 101, "match_date": "2015-08-08", "kick_off": "12:45:00.000",
     "competition": {"competition_id": 2, "competition_name": "Premier League"}, "season": {"season_name": "2015/2016"},
     "home_team": {"home_team_id": 1, "home_team_name": "Arsenal", "home_team_gender": "male"},
     "away_team": {"away_team_id": 2, "away_team_name": "Chelsea", "away_team_gender": "male"},
     "home_score": 1, "away_score": 0, "match_status": "available"},
    {"match_id": 102, "match_date": "2015-12-01", "kick_off": "20:00:00.000",
     "competition": {"competition_id": 2, "competition_name": "Premier League"}, "season": {"season_name": "2015/2016"},
     "home_team": {"home_team_id": 2, "home_team_name": "Chelsea", "home_team_gender": "male"},
     "away_team": {"away_team_id": 1, "away_team_name": "Arsenal", "away_team_gender": "male"},
     "home_score": 2, "away_score": 2, "match_status": "available"},
]
EV_101 = half() + [ev(1, 16, 1, 97, 0.31), ev(2, 16, 2, 98, 0.12), ev(2, 16, 2, 100, 0.2)]
# 102: Chelsea (2) ev sahibi. 1. devre: Chelsea golü + Arsenal lehine kendi kalesine gol (25 + 20 çifti);
# 2. devre: birer gol. İY 1-1, MS 2-2.
EV_102 = half(2) + [ev(1, 16, 2, 97, 0.5), {"period": 1, "type": {"id": 25}, "team": {"id": 1}},
                    {"period": 1, "type": {"id": 20}, "team": {"id": 2}}, ev(2, 16, 2, 97, 0.4), ev(2, 16, 1, 97, 0.2)]


def routes(of_bytes: bytes | None = None) -> dict:
    r = {refs_url(repo): Resp(200, adv({f"refs/heads/{REPOS[repo].branch}": c})) for repo, c in COMMITS.items()}
    of = "openfootball/football.json"
    r[raw(of, C_OF, "2024-25/en.1.json")] = Resp(200, of_bytes if of_bytes is not None else of_season())
    ds = "datasets/football-datasets"
    r[raw(ds, C_DS, "datasets/premier-league/datapackage.json")] = Resp(200, json.dumps(
        {"licenses": [{"name": "ODC-PDDL-1.0"}], "resources": [{"path": "season-2425.csv"}]}).encode())
    r[raw(ds, C_DS, "datasets/premier-league/season-2425.csv")] = Resp(200, DS_CSV)
    r[raw("xgabora/Club-Football-Match-Data-2000-2025", C_XG, "data/Matches.csv")] = Resp(200, XG_CSV)
    hu = "hudl/open-data"
    r[raw(hu, C_HU, "data/competitions.json")] = Resp(200, json.dumps([
        {"competition_id": 2, "season_id": 27, "competition_name": "Premier League", "season_name": "2015/2016",
         "country_name": "England", "competition_gender": "male"},
        {"competition_id": 11, "season_id": 90, "competition_name": "La Liga", "season_name": "2020/2021",
         "country_name": "Spain", "competition_gender": "male"}]).encode())
    r[raw(hu, C_HU, "data/matches/2/27.json")] = Resp(200, json.dumps(HUDL_MATCHES).encode())
    r[raw(hu, C_HU, "data/events/101.json")] = Resp(200, json.dumps(EV_101).encode())
    r[raw(hu, C_HU, "data/events/102.json")] = Resp(200, json.dumps(EV_102).encode())
    return r


def transport(session) -> GitHubTransport:
    return GitHubTransport(session=session, polite_delay=0)


def build(tmp_path, session=None, **kw):
    session = session or FakeSession(routes())
    home = tmp_path / "arsiv"
    kw.setdefault("consent", ALL)
    out = A.build(home, transport=transport(session), today=TODAY, openfootball_from=2024, **kw)
    return home, out, session


def snapshot(*dirs) -> dict:
    out = {}
    for d in dirs:
        for p in sorted(Path(d).rglob("*")):
            if p.is_file():
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ----------------------------------------------------------------------------- GitHub profili ve taşıma

def test_transport_refuses_non_github_before_any_request():
    s = FakeSession()
    t = transport(s)
    for url in ("https://www.football-data.co.uk/mmz4281/2425/E0.csv", "https://api.football-data.org/v4/matches",
                "http://raw.githubusercontent.com/x/y/z", "https://datahub.io/core/english-premier-league"):
        with pytest.raises(GitHubError) as e:
            t.get(url)
        assert e.value.kind == "IZINSIZ_ADRES"
    assert s.calls == []


def test_redirect_off_github_stops_and_is_not_followed():
    target = "https://www.football-data.co.uk/E0.csv"
    s = FakeSession({raw("x/y", C_OF, "f.csv"): Resp(302, headers={"Location": target})})
    with pytest.raises(GitHubError) as e:
        transport(s).fetch("x/y", C_OF, "f.csv")
    assert e.value.kind == "YONLENDIRME_DISARI"
    assert target not in s.calls
    # Uygulamanın indiricisi de profil verildiğinde aynı kuralı uygular
    d = Downloader(Path("unused"), allowed_hosts=GITHUB_HOSTS, polite_delay=0, retries=0)
    d.session = FakeSession({"https://raw.githubusercontent.com/a/b/c": Resp(301, headers={"Location": target})})
    with pytest.raises(DownloadError) as e2:
        d._download("https://raw.githubusercontent.com/a/b/c")
    assert e2.value.policy and target not in d.session.calls


def test_downloader_profile_blocks_football_data_even_from_cache(tmp_path):
    d = Downloader(tmp_path, allowed_hosts=GITHUB_HOSTS, polite_delay=0)
    d.session = FakeSession()
    (tmp_path / "fd").mkdir()
    (tmp_path / "fd" / "fixtures.csv").write_text("eski")
    with pytest.raises(DownloadError) as e:
        d.get("https://www.football-data.co.uk/fixtures.csv", "fd/fixtures.csv")
    assert e.value.policy and not e.value.network
    assert d.session.calls == []


def test_access_errors_are_explicit_not_success(tmp_path):
    s = FakeSession(default=403)
    with pytest.raises(GitHubError) as e:
        transport(s).resolve_ref("openfootball/football.json", "master")
    assert e.value.kind == "KOTA"
    assert len(s.calls) == 1  # sınırsız yeniden deneme yok
    home, out, _ = build(tmp_path, session=FakeSession(default=403))
    assert all(v["durum"] == "ERISILEMEDI" for v in out["kaynaklar"].values())
    assert out["blok"] == 0 and out["analiz_satiri"] == 0
    assert out["guncel_veri"] == {}


def test_stale_cache_is_labelled_and_not_current(tmp_path):
    # Uygulama indiricisi: indirme başarısız, eski kopya -> ayrıca sayılır
    d = Downloader(tmp_path, polite_delay=0, retries=0)
    d.session = FakeSession(default=404)
    (tmp_path / "x.csv").write_text("eski")
    import os
    import time

    os.utime(tmp_path / "x.csv", (time.time() - 10 * 3600, time.time() - 10 * 3600))
    assert d.get("https://example.invalid/x.csv", "x.csv", max_age_hours=1) == b"eski"
    assert d.stats["stale"] == 1 and d.stale_files == ["x.csv"]
    # Arşiv: ilk hazırlama başarılı; ikinci hazırlamada uç çözülemez -> son kayıtlı commit, açıkça eski kopya
    home, out, _ = build(tmp_path, sources=("openfootball-sonuc",))
    assert out["guncel_veri"]["E0"] == "VERIFIED_AVAILABLE"
    out2 = A.build(home, sources=("openfootball-sonuc",), transport=transport(FakeSession(default=403)), today=TODAY,
                   openfootball_from=2024)
    st = out2["kaynaklar"]["openfootball-sonuc"]
    assert st["uc_durumu"] == STALE_COPY and st["commit"] == C_OF
    assert out2["guncel_veri"]["E0"] == "STALE"  # eski kopya güncel sayılmaz


def test_github_profile_update_uses_only_github_and_pins_commits(tmp_path):
    from bahis_tahmin.data.store import DataStore

    gh = FakeSession(routes())
    fd_session = FakeSession()
    dl = Downloader(tmp_path / "store" / "raw", allowed_hosts=GITHUB_HOSTS, polite_delay=0)
    dl.session = fd_session
    st = DataStore(tmp_path / "store")
    rep = st.update(["E0"], 3, today=TODAY, downloader=dl, allowed=allowed_sources({"github-mirror": "x"}),
                    profile="github", github_transport=transport(gh))
    assert fd_session.calls == []
    assert gh.calls and all(host_of(u) in GITHUB_HOSTS for u in gh.calls)
    assert not any("football-data" in u for u in gh.calls)
    raw_calls = [u for u in gh.calls if "raw.githubusercontent.com" in u]
    assert raw_calls and all(f"/{C_XG}/" in u or f"/{C_OF}/" in u for u in raw_calls)  # dal adıyla dosya alınmaz
    assert rep.profile == "github" and st.meta["veri_profili"] == "github"
    assert st.meta["github_kaynak"]["xgabora/Club-Football-Match-Data-2000-2025"]["commit"] == C_XG
    assert len(st.matches) == 1 and "football-data" not in " ".join(rep.blocked_sources)
    assert "yalnızca GitHub" in rep.summary()
    # İkinci güncelleme: uç çözülemez -> doğrulanmış eski kopya, açıkça işaretli; football-data'ya geçilmez
    rep2 = DataStore(tmp_path / "store").update(["E0"], 3, today=TODAY, downloader=dl,
                                                allowed=allowed_sources({"github-mirror": "x"}), profile="github",
                                                github_transport=transport(FakeSession(default=403)))
    assert rep2.stale >= 1 and "ESKİ kopya" in rep2.summary()
    assert fd_session.calls == []


def test_github_profile_without_any_copy_skips_source(tmp_path):
    from bahis_tahmin.data.store import DataStore

    fd_session = FakeSession()
    dl = Downloader(tmp_path / "raw", allowed_hosts=GITHUB_HOSTS, polite_delay=0)
    dl.session = fd_session
    rep = DataStore(tmp_path / "s").update(["E0"], 3, today=TODAY, downloader=dl,
                                           allowed=allowed_sources({"github-mirror": "x", "football-data": "x"}),
                                           profile="github", github_transport=transport(FakeSession(default=403)))
    assert rep.n_matches == 0 and fd_session.calls == []
    assert any("başka kaynağa geçilmedi" in w for w in rep.warnings)


def test_settings_profile_validation():
    from bahis_tahmin.config import Settings

    s = Settings()
    assert s.data_profile == "varsayilan"
    s.data_profile = "football-data-org"
    s.validate()
    assert s.data_profile == "varsayilan"
    s.data_profile = "github"
    s.save()
    assert Settings.load().data_profile == "github"


# ----------------------------------------------------------------------------- sürümlü önbellek ve köken

def test_pinned_commit_and_hash_verified_cache(tmp_path):
    s = FakeSession(routes())
    c = GitHubCache(tmp_path)
    t = transport(s)
    with pytest.raises(GitHubError):
        t.fetch("openfootball/football.json", "master", "2024-25/en.1.json")  # yalnızca sabit commit
    f1 = c.get(t, "openfootball/football.json", C_OF, "2024-25/en.1.json")
    assert f1.status == FETCHED and f1.record["sha256"] == hashlib.sha256(f1.data).hexdigest()
    n = len(s.calls)
    f2 = c.get(t, "openfootball/football.json", C_OF, "2024-25/en.1.json")
    assert f2.status == VERIFIED_CACHE and len(s.calls) == n
    with pytest.raises(GitHubError) as e:
        c.put("openfootball/football.json", C_OF, "2024-25/en.1.json", b"farkli", FETCHED)
    assert e.value.kind == "OZET_UYUSMAZ"  # eski kopya ezilmez
    assert c.read("openfootball/football.json", C_OF, "2024-25/en.1.json").data == f1.data


def test_tampered_raw_fails_provenance(tmp_path):
    home, out, _ = build(tmp_path, sources=("openfootball-sonuc",))
    assert len(A.load(home).rows) == 4
    p = GitHubCache(home).path("openfootball/football.json", C_OF, "2024-25/en.1.json")
    p.write_bytes(p.read_bytes().replace(b'"ft": [2, 1]', b'"ft": [5, 1]'))
    ar = A.load(home)
    assert len(ar.rows) == 0
    assert ar.rejected and ar.rejected[0]["neden"] == "OZET_UYUSMAZ"
    assert (ar.coverage_frame()["durum"] == "KOKEN_DOGRULANAMADI").all()


def test_refetch_does_not_duplicate(tmp_path):
    home, out1, s1 = build(tmp_path)
    files1 = snapshot(home / "github")
    out2 = A.build(home, transport=transport(FakeSession(routes())), today=TODAY, openfootball_from=2024, consent=ALL)
    assert out2["analiz_satiri"] == out1["analiz_satiri"] and out2["blok"] == out1["blok"]
    assert out2["kaynaklar"]["openfootball-sonuc"]["uc_notu"] == "uç değişmedi"
    assert set(out2["blok_durumlari"]) == {VERIFIED_CACHE}  # yeniden indirilmedi
    files2 = snapshot(home / "github")
    assert {k: v for k, v in files2.items() if not k.endswith("uclar.json")} == \
        {k: v for k, v in files1.items() if not k.endswith("uclar.json")}


def test_new_commit_kept_separately_and_reported(tmp_path):
    home, _, _ = build(tmp_path, sources=("openfootball-sonuc",))
    new = "e" * 40
    r = routes()
    r[refs_url("openfootball/football.json")] = Resp(200, adv({"refs/heads/master": new}))
    extra = [{"round": "Matchday 3", "date": "2024-08-31", "team1": "Arsenal FC", "team2": "Liverpool FC",
              "score": {"ht": [1, 1], "ft": [1, 2]}}]
    r[raw("openfootball/football.json", new, "2024-25/en.1.json")] = Resp(200, of_season(extra))
    out = A.build(home, sources=("openfootball-sonuc",), transport=transport(FakeSession(r)), today=TODAY,
                  openfootball_from=2024)
    assert out["kaynaklar"]["openfootball-sonuc"]["uc_notu"].startswith("uç değişti")
    assert GitHubCache(home).read("openfootball/football.json", C_OF, "2024-25/en.1.json") is not None  # eski duruyor
    assert out["analiz_satiri"] == 5


def test_pilot_cache_import_is_verified_and_read_only(tmp_path):
    pilot = tmp_path / "pilot"
    data = of_season()
    (pilot / "raw" / "openfootball" / "2024-25").mkdir(parents=True)
    (pilot / "raw" / "openfootball" / "2024-25" / "en.1.json").write_bytes(data)
    (pilot / "data_meta.json").write_text(json.dumps({"kaynak_kokeni": [
        {"repo": "openfootball/football.json", "path": "2024-25/en.1.json", "ref": C_OF,
         "url": raw("openfootball/football.json", C_OF, "2024-25/en.1.json"), "retrieved_at": "2025-05-01T00:00:00+00:00",
         "sha256": hashlib.sha256(data).hexdigest(), "cache_rel": "openfootball/2024-25/en.1.json"},
        {"repo": "baska/depo", "path": "x.json", "ref": C_OF, "sha256": "0" * 64, "cache_rel": "x.json"}]}))
    before = snapshot(pilot)
    s = FakeSession(routes())
    home, out, _ = build(tmp_path, session=s, sources=("openfootball-sonuc",), pilot_home=pilot)
    assert snapshot(pilot) == before
    assert raw("openfootball/football.json", C_OF, "2024-25/en.1.json") not in s.calls
    ar = A.load(home)
    assert ar.blocks()[0]["durum"] == IMPORTED
    assert [x["durum"] for x in ar.catalog["pilot_kopyasi"]] == [IMPORTED, "SECILI_DEPO_DEGIL"]
    # Özeti tutmayan pilot dosyası kopyalanmaz
    (pilot / "raw" / "openfootball" / "2024-25" / "en.1.json").write_bytes(data + b" ")
    home2 = tmp_path / "arsiv2"
    A.build(home2, sources=("openfootball-sonuc",), transport=transport(FakeSession(routes())), today=TODAY,
            openfootball_from=2024, pilot_home=pilot)
    assert A.load(home2).catalog["pilot_kopyasi"][0]["durum"] == "OZET_UYUSMAZ"


# ----------------------------------------------------------------------------- kaynak okuyucular

def test_four_sources_statuses_and_rights_gating(tmp_path):
    home, out, s = build(tmp_path)
    k = out["kaynaklar"]
    assert k["openfootball-sonuc"]["durum"] == "TARIHSEL_ANALIZ_ETKIN"
    assert k["statsbomb-acik"]["durum"] == "TARIHSEL_ANALIZ_ETKIN"
    assert k["football-datasets"]["durum"].startswith("YALNIZCA_ENVANTER")
    assert k["github-mirror"]["durum"].startswith("YALNIZCA_ENVANTER")
    ar = A.load(home)
    assert set(ar.rows["kaynak"]) == {"openfootball-sonuc", "statsbomb-acik"}  # envanter satırları analize girmez
    ds = [b for b in ar.blocks() if b["kaynak"] == "football-datasets"][0]
    assert ds["mac"] == 1 and ds["birebir_tekrar"] == 1 and ds["karantina"] == {"IY_MS_CELISKI": 1}
    assert ds["gercek_oran"] is False and ds["iy_gecerli"] == 1
    xg = ar.catalog["kaynaklar"]["github-mirror"]["sutunlar"]
    assert {"HomeElo", "AwayElo", "Form3Home"} <= set(xg["turetilmis_model_girdisi_degil"])
    assert {"OddHome"} <= set(xg["piyasa_orani"]) and "HomeElo" not in xg["ham"]
    assert "olay_ornegi" in ar.catalog["kaynaklar"]["statsbomb-acik"]
    assert not any("/three-sixty/" in u for u in s.calls)  # 360 verisi indirilmez


def test_consent_required_sources_need_explicit_access(tmp_path):
    home, out, s = build(tmp_path, consent=())
    assert out["kaynaklar"]["football-datasets"]["durum"] == "ERISIM_ONAYI_YOK"
    assert out["kaynaklar"]["github-mirror"]["durum"] == "ERISIM_ONAYI_YOK"
    assert not any("football-datasets" in u or "xgabora" in u for u in s.calls)


def test_openfootball_missing_ht_vs_real_zero_and_logical_flag(tmp_path):
    home, _, _ = build(tmp_path, sources=("openfootball-sonuc",))
    lab, out = A.explore(A.load(home))
    by = lab.set_index("home")
    assert by.loc["Arsenal FC", "veri_kalitesi"] == "TAM" and by.loc["Arsenal FC", "C"] == 0.0
    assert by.loc["Liverpool FC", "veri_kalitesi"] == "IY_MANTIKSAL_0_0" and by.loc["Liverpool FC", "hthg"] == 0
    assert by.loc["Chelsea FC", "veri_kalitesi"] == "IY_YOK"
    assert np.isnan(by.loc["Chelsea FC", "C"]) and np.isnan(by.loc["Chelsea FC", "A"])  # eksik İY bilinmiyor
    assert by.loc["Chelsea FC", "B"] == 1.0  # MS pazarı İY'siz de bilinir
    assert by.loc["Everton FC", "veri_kalitesi"] == "TAM" and by.loc["Everton FC", "iy_ms"] == "HTFT_X_2"
    assert out["iy_gecerli"] == 3 and out["iy_mantiksal_0_0"] == 1
    assert out["pazarlar"]["C"]["gecerli"] == 3 and out["pazarlar"]["C"]["bilinmiyor"] == 1


def test_football_datasets_schema_variants():
    from bahis_tahmin.data.parsers import football_datasets_season, parse_football_datasets

    assert football_datasets_season("season-9394.csv") == "1993/94"
    assert football_datasets_season("season-0001.csv") == "2000/01"
    assert football_datasets_season("season-0003.csv") is None
    no_ht = b"Date,HomeTeam,AwayTeam,FTHG,FTAG\n13/08/1994,A,B,0,0\n20/08/1994,B,A,1,1\n"
    m, rep = parse_football_datasets(no_ht, "E0", "1994/95")
    assert len(m) == 2 and m["hthg"].isna().all()  # İY sütunu yok: 0-0 yapılmaz
    assert rep["iy_gecerli"] == 0 and "HTHG" in rep["eksik_sutun"]
    mixed = (b"Date,HomeTeam,AwayTeam,FTHG,FTAG,HTHG,HTAG,B365H\n"
             b"2024-08-17,A,B,1,0,,,1.5\n"        # boş İY: eksik
             b"2024-08-18,C,D,0,0,0,0,2.0\n"      # gerçek 0-0
             b"2024-08-19,E,F,x,1,0,0,2.0\n"      # geçersiz skor
             b"2024-08-20,G,H,1,1,0,0,2.0\n"
             b"2024-08-20,G,H,2,1,0,0,2.0\n")     # aynı maç farklı skor: ikisi de karantina
    m, rep = parse_football_datasets(mixed, "E0", "2024/25")
    assert list(m["home"]) == ["A", "C"] and np.isnan(m.loc[0, "hthg"]) and m.loc[1, "hthg"] == 0
    assert rep["karantina"] == {"SKOR_GECERSIZ": 1, "CELISKILI_KAYIT": 2}
    assert rep["oran_sutunu"] is True and "B365H" not in m.columns


# ----------------------------------------------------------------------------- Hudl / StatsBomb olayları

MATCH = {"home_id": 1, "away_id": 2, "home_score": 1, "away_score": 0}


def test_statsbomb_normal_and_disallowed_shot():
    sc = score_from_events(EV_101, MATCH)
    assert sc["durum"] == OK and sc["iy"] == (1, 0) and sc["ms"] == (1, 0)
    assert sc["sut"] == {"h": 1, "a": 2} and sc["xg"] == {"h": 0.31, "a": 0.32}
    # Gol sonucu (97) olmayan şut gol sayılmaz
    extra = EV_101 + [ev(2, 16, 2, 101, 0.4)]
    assert score_from_events(extra, MATCH)["ms"] == (1, 0)


def test_statsbomb_extra_time_and_penalties():
    events = half() + [ev(1, 16, 1, 97), ev(2, 16, 2, 97), {"period": 3, "type": {"id": 35}, "team": {"id": 1}},
                       ev(3, 16, 1, 97), {"period": 5, "type": {"id": 35}, "team": {"id": 1}}, ev(5, 16, 2, 97),
                       ev(5, 16, 2, 97), ev(5, 16, 1, 97)]
    sc = score_from_events(events, {"home_id": 1, "away_id": 2, "home_score": 2, "away_score": 1})
    assert sc["durum"] == OK and sc["uzatma"] and sc["penalti_atislari"]
    assert sc["iy"] == (1, 0) and sc["ms"] == (1, 1) and sc["uzatma_sonu"] == (2, 1)  # penaltılar hiçbir skora girmez


def test_statsbomb_own_goals_counted_once_and_pairing_checked():
    sc = score_from_events(EV_102, {"home_id": 2, "away_id": 1, "home_score": 2, "away_score": 2})
    assert sc["durum"] == OK and sc["iy"] == (1, 1) and sc["ms"] == (2, 2) and sc["kendi_kalesine"] == 1
    unpaired = [e for e in EV_102 if e["type"]["id"] != 20]
    bad = score_from_events(unpaired, {"home_id": 2, "away_id": 1, "home_score": 2, "away_score": 2})
    assert bad["durum"] == INCOMPLETE and bad["ms"] is None and "KENDI_KALESINE_GOL_ESLESMEDI" in bad["sorunlar"]


def test_statsbomb_metadata_mismatch_and_unknown_team_not_fabricated():
    mm = score_from_events(EV_101, {**MATCH, "home_score": 2})
    assert mm["durum"] == MISMATCH and mm["ms"] is None and mm["iy"] is None and mm["olaydan_ms"] == (1, 0)
    unk = score_from_events(EV_101 + [ev(1, 16, 99, 97)], MATCH)
    assert unk["durum"] == INCOMPLETE and "TAKIM_KIMLIGI_UYUSMAZ" in unk["sorunlar"]
    no_half = score_from_events([ev(1, 16, 1, 97)], MATCH)
    assert no_half["durum"] == INCOMPLETE and "NORMAL_DEVRE_EKSIK" in no_half["sorunlar"]


def test_hudl_coverage_reports_selected_matches_not_full_season(tmp_path):
    r = routes()
    partial = [dict(HUDL_MATCHES[0])]  # tek takımın tek maçı: tam sezon değil, olay örneği alınmaz
    r[raw("hudl/open-data", C_HU, "data/matches/2/27.json")] = Resp(200, json.dumps(partial).encode())
    home, out, s = build(tmp_path, session=FakeSession(r), sources=("statsbomb-acik",))
    blk = A.load(home).blocks()[0]
    assert blk["kapsam"].startswith("SECILI_MACLAR")
    assert not any("/events/" in u for u in s.calls)
    full_home, _, s2 = build(tmp_path / "tam", sources=("statsbomb-acik",))
    ar = A.load(full_home)
    assert ar.blocks()[0]["kapsam"] == "TAM_SEZON"
    assert sum("/events/" in u for u in s2.calls) == 2 and len(ar.rows) == 2
    assert set(ar.rows["olay_durumu"]) == {OK}


# ----------------------------------------------------------------------------- birleşik görünüm

def rows(*recs) -> pd.DataFrame:
    base = {"etiket": None, "asil_kaynak": None, "blok": 0, "league": "E0", "season": "2024/25", "time": "",
            "hthg": np.nan, "htag": np.nan, "iy_mantiksal": False, "olay_durumu": None, "saglayici_mac_id": None,
            "xg_h": np.nan, "xg_a": np.nan, "sut_h": np.nan, "sut_a": np.nan}
    out = []
    for r in recs:
        x = {**base, **r}
        x["asil_kaynak"] = x["asil_kaynak"] or A.UPSTREAM[x["kaynak"]]
        x["date"] = pd.Timestamp(x["date"])
        out.append(x)
    return pd.DataFrame(out).reindex(columns=A.ROW_COLUMNS)


def test_same_match_from_two_sources_counted_once():
    r = rows({"kaynak": "openfootball-sonuc", "date": "2024-08-17", "home": "Arsenal FC", "away": "Chelsea FC",
              "fthg": 2, "ftag": 1, "hthg": 1, "htag": 0},
             {"kaynak": "statsbomb-acik", "date": "2024-08-17", "home": "Arsenal", "away": "Chelsea", "fthg": 2,
              "ftag": 1, "hthg": 1, "htag": 0, "saglayici_mac_id": "101", "xg_h": 1.2, "xg_a": 0.4})
    m, c, rv = A.unified(r)
    assert len(m) == 1 and m.iloc[0]["durum"] == "TAMAM" and c.empty and rv.empty
    assert m.iloc[0]["kaynaklar"] == "openfootball-sonuc,statsbomb-acik" and m.iloc[0]["bagimsiz_kaynak"] == 2
    assert m.iloc[0]["saglayici_mac_id"] == "101"
    assert A.summary(m)["birlesik_gecerli"] == 1


def test_mirrors_with_same_upstream_are_not_independent_and_conflicts_visible():
    r = rows({"kaynak": "football-datasets", "date": "2024-08-17", "home": "Arsenal", "away": "Chelsea", "fthg": 2,
              "ftag": 1},
             {"kaynak": "github-mirror", "date": "2024-08-17", "home": "Arsenal", "away": "Chelsea", "fthg": 2,
              "ftag": 1})
    m, _, _ = A.unified(r)
    assert len(m) == 1 and m.iloc[0]["bagimsiz_kaynak"] == 1  # aynı asıl köken: bağımsız doğrulama değil
    r2 = rows({"kaynak": "openfootball-sonuc", "date": "2024-08-17", "home": "Arsenal FC", "away": "Chelsea FC",
               "fthg": 2, "ftag": 1},
              {"kaynak": "football-datasets", "date": "2024-08-17", "home": "Arsenal", "away": "Chelsea", "fthg": 2,
               "ftag": 2},
              {"kaynak": "github-mirror", "date": "2024-08-17", "home": "Arsenal", "away": "Chelsea", "fthg": 2,
               "ftag": 2})
    m2, c2, _ = A.unified(r2)
    assert len(m2) == 1 and m2.iloc[0]["durum"] == "CELISKI"
    assert np.isnan(m2.iloc[0]["fthg"])  # çoğunluk oyu veya en yeni kaynak seçilmez
    assert set(c2["kaynak"]) == {"openfootball-sonuc", "football-datasets", "github-mirror"}
    s = A.summary(m2)
    assert s["celiskili"] == 1 and s["birlesik_gecerli"] == 0 and s["pazarlar"]["B"]["gecerli"] == 0


def test_date_mismatch_and_team_category_go_to_review():
    r = rows({"kaynak": "openfootball-sonuc", "date": "2024-08-17", "home": "Arsenal FC", "away": "Chelsea FC",
              "fthg": 2, "ftag": 1},
             {"kaynak": "statsbomb-acik", "date": "2024-08-18", "home": "Arsenal", "away": "Chelsea", "fthg": 2,
              "ftag": 1},
             {"kaynak": "statsbomb-acik", "date": "2024-08-24", "home": "Arsenal Women", "away": "Chelsea", "fthg": 1,
              "ftag": 0})
    m, c, rv = A.unified(r)
    assert set(m["durum"]) == {"TARIH_UYUSMAZ"} and len(m) == 2  # tarih toleransıyla bağlanmaz
    assert set(rv["neden"]) == {"TAKIM_KIMLIGI_KESIN_DEGIL", "AYNI_ESLESME_FARKLI_TARIH"}
    assert "Arsenal Women" in set(rv["home"].dropna())  # yaş/kategori farkı aynı takım sayılmaz
    assert A.summary(m)["birlesik_gecerli"] == 0


# ----------------------------------------------------------------------------- haklar ve güvenlik

def test_rights_scopes_and_label_spoof_fail(tmp_path):
    for op in ARCHIVE_OPERATIONS:
        assert archive_scope("bilinmeyen")[op] == "DOGRULANAMADI"
    assert not archive_allowed("football-datasets", "tarihsel_analiz")
    assert not archive_allowed("github-mirror", "model_egitimi")
    assert not archive_allowed("statsbomb-acik", "ticari_kullanim") and not archive_allowed("statsbomb-acik",
                                                                                            "model_egitimi")
    assert archive_allowed("statsbomb-acik", "tarihsel_analiz")
    home, _, _ = build(tmp_path)
    rows_ = pd.read_pickle(home / A.ROWS)
    orig = rows_.copy()
    # 1) Etiket değişikliği: openfootball satırlarına başka etiket
    rows_.loc[rows_["kaynak"] == "openfootball-sonuc", "etiket"] = "football-data.co.uk"
    rows_.to_pickle(home / A.ROWS)
    ar = A.load(home)
    assert {r["neden"] for r in ar.rejected} == {"KAYNAK_ETIKETI_UYUMSUZ"}
    assert "openfootball-sonuc" not in set(ar.rows["kaynak"])
    # 2) Analizi kapalı kaynağın satırını izinli kaynak gibi gösterme: satır özeti tutmaz
    spoof = orig.copy()
    blk = int(spoof.loc[spoof["kaynak"] == "openfootball-sonuc", "blok"].iloc[0])
    fake = spoof[spoof["blok"] == blk].iloc[[0]].assign(date=pd.Timestamp("2024-09-01"), home="Arsenal FC",
                                                        away="Fulham FC")
    pd.concat([spoof, fake], ignore_index=True).to_pickle(home / A.ROWS)
    assert {r["neden"] for r in A.load(home).rejected} == {"SATIRLAR_KAYITLA_UYUSMUYOR"}
    # 3) Katalogda analizi kapalı kaynağa satır özeti eklemek analiz hakkı vermez
    cat = json.loads((home / A.CATALOG).read_text(encoding="utf-8"))
    ds = next(b for b in cat["bloklar"] if b["kaynak"] == "football-datasets" and "dosya_sha256" in b)
    ds["satir_ozeti"], ds["tarihsel_analiz"] = A.rows_digest(orig.iloc[0:0]), True
    (home / A.CATALOG).write_text(json.dumps(cat), encoding="utf-8")
    orig.to_pickle(home / A.ROWS)
    ar3 = A.load(home)
    assert any(r["kaynak"] == "football-datasets" and r["neden"] == "KAYNAK_ETIKETI_UYUMSUZ" for r in ar3.rejected)
    assert "football-datasets" not in set(ar3.rows["kaynak"])


def test_stale_current_season_does_not_block_historical_view(tmp_path):
    extra = [{"round": "Matchday 38", "date": "2025-05-25", "team1": "Arsenal FC", "team2": "Liverpool FC"}]
    home, out, _ = build(tmp_path, session=FakeSession(routes(of_season(extra))), sources=("openfootball-sonuc",))
    assert out["guncel_veri"]["E0"] == "STALE"  # tarihi geçmiş, sonucu olmayan maç
    lab, s = A.explore(A.load(home), sezon="2024/25")
    assert s["birlesik_gecerli"] == 4 and len(lab) == 4


def test_historical_view_produces_no_probabilities_or_bet_candidates(tmp_path):
    home, _, _ = build(tmp_path)
    lab, s = A.explore(A.load(home))

    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield str(k)
                yield from keys(v)

    forbidden = {"olasilik", "probability", "edge", "ev_degeri", "stake", "kelly", "aday", "bahis", "oran",
                 "o_h", "o_d", "o_a", "guven"}
    assert not (set(keys(s)) & forbidden)
    assert not ({c.lower() for c in lab.columns} & forbidden)
    assert not any(c.startswith(("o_", "omax_", "b365_", "p_")) for c in lab.columns)
    assert s["aciklama"] == A.ARCHIVE_NOTE


def test_archive_dir_never_overlaps_user_app_dir(tmp_path, tmp_home):
    with pytest.raises(A.ArchiveError):
        A.check_archive_dir(tmp_home, create=True)
    with pytest.raises(A.ArchiveError):
        A.check_archive_dir(tmp_home / "arsiv", create=True)
    with pytest.raises(A.ArchiveError):
        A.check_archive_dir(tmp_home.parent, create=True)  # uygulama klasörünü içeren klasör
    busy = tmp_path / "dolu"
    busy.mkdir()
    (busy / "baska.txt").write_text("x")
    with pytest.raises(A.ArchiveError):
        A.check_archive_dir(busy, create=True)
    with pytest.raises(A.ArchiveError):
        A.load(tmp_path / "yok")
    assert A.archive_home_path() == tmp_home.with_name(tmp_home.name + "-Arsiv")


def test_user_data_pilot_and_model_files_unchanged(tmp_path, tmp_home):
    for name, data in (("settings.json", b"{}"), ("matches.pkl", b"m"), ("goal_engine.joblib", b"g"),
                       ("gol_pazarlari.sqlite", b"l"), ("data_meta.json", b"{}")):
        (tmp_home / name).write_bytes(data)
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    (pilot / "data_meta.json").write_text(json.dumps({"kaynak_kokeni": []}))
    (pilot / "pilot_model.json").write_text("{}")
    before = snapshot(tmp_home, pilot)
    build(tmp_path, pilot_home=pilot)
    assert snapshot(tmp_home, pilot) == before


def test_cli_archive_commands(tmp_path, capsys):
    from bahis_tahmin.cli import main

    home, _, _ = build(tmp_path)
    assert main(["arsiv-katalog", "--ev", str(home)]) == 0
    out = capsys.readouterr().out
    assert "TARIHSEL_ANALIZ_ETKIN" in out and "YALNIZCA_ENVANTER" in out and "tarihsel_analiz=DOGRULANAMADI" in out
    assert main(["arsiv-maclar", "--ev", str(home), "--kaynak", "openfootball", "--sezon", "2024/25"]) == 0
    out = capsys.readouterr().out
    assert "E0|2024-08-17|Arsenal FC|Chelsea FC" in out and A.ARCHIVE_NOTE in out
    assert main(["arsiv-ozet", "--ev", str(home), "--takim", "Arsenal FC", "--yer", "ev"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["mac"] == 1 and s["pazarlar"]["B"]["gecerli"] == 1
    assert main(["arsiv-kart", "--ev", str(home), "--mac", "E0|2024-08-24|Everton FC|Arsenal FC", "--takim",
                 "Arsenal FC"]) == 0
    card = json.loads(capsys.readouterr().out)
    assert card["kimlik"]["event_id"] == "E0|2024-08-24|Everton FC|Arsenal FC"
    assert "PRE_EVENT" in card and "POST_EVENT" in card
    assert main(["arsiv-katalog", "--ev", str(tmp_path / "yok")]) == 3


def test_ui_data_page_does_not_autoload_or_download(tmp_path, monkeypatch, tmp_home):
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    home, _, _ = build(tmp_path)
    monkeypatch.setenv("BAHIS_TAHMIN_ARSIV", str(home))

    def no_net(*a, **k):
        raise AssertionError("arayüz açılırken ağ isteği yapılmamalı")

    monkeypatch.setattr(GitHubTransport, "get", no_net)
    monkeypatch.setattr(Downloader, "_download", no_net)
    app = QApplication.instance() or QApplication([])
    from bahis_tahmin.ui.controller import AppController
    from bahis_tahmin.ui.pages.data import DataPage

    before = snapshot(home)
    ctl = AppController()
    page = DataPage(ctl)
    panel = page.archive_panel
    assert panel.archive is None and panel.match_model.frame.empty  # açılışta okunmaz, indirilmez
    assert snapshot(home) == before
    assert ctl.open_archive(panel.show_archive)
    ctl.wait()
    app.processEvents()
    assert panel.archive is not None and snapshot(home) == before  # salt okunur
    cols = set(panel.match_model.frame.columns)
    # S5-ARSIV-02: birleştirilmiş görünümde alan kökeni sütunu eklendi
    assert cols == {"mac_kimligi", "iy", "ms", "A", "B", "C", "iy_ms", "kalite", "kaynaklar", "xg", "alan_kokeni"}
    assert A.ARCHIVE_NOTE in panel.summary.text()
    assert set(panel.cov_model.frame.loc[panel.cov_model.frame["kaynak"] == "openfootball-sonuc", "alan"]) == {
        "yok / yok / yok"}  # sahte oran/olay gösterilmez
    page.cb_profile.setCurrentIndex(page.cb_profile.findData("github"))
    assert ctl.settings.data_profile == "github" and not ctl.busy  # seçim indirme başlatmaz

"""FIKSTUR-03: football.json'da güncel sezon dosyası olmayan ligler (ör. Süper Lig 2026-27) için openfootball'un
Football.TXT metin depolarından fikstür, takvim ve eksik dönem. Yalnızca SENTETİK veri ve sahte indirici (ağ yok).
"""

from __future__ import annotations

import datetime as dt
import io
import json

import pandas as pd
import pytest
from test_s5_github import FakeSession, Resp, adv, raw, refs_url, transport
from test_store import FakeDownloader

from bahis_tahmin import eligibility as E
from bahis_tahmin.data.completion import COMPLETION_LABEL, verify_completion
from bahis_tahmin.data.football_txt import (
    TXT_CONVERTER,
    TXT_FILES,
    convert_football_txt,
    converted_origin,
    parse_football_txt,
)
from bahis_tahmin.data.github_kaynak import GITHUB_HOSTS, host_of
from bahis_tahmin.data.provenance import verified_labels
from bahis_tahmin.data.source_registry import allowed_sources
from bahis_tahmin.data.sources import MIRROR_URL, OPENFOOTBALL_BASE, Downloader
from bahis_tahmin.data.store import DataStore
from bahis_tahmin.data.teams import resolve_teams

TODAY = dt.date(2026, 10, 12)
ALL = {"football-data", "github-mirror", "openfootball"}
FD = ["Galatasaray", "Fenerbahce", "Konyaspor", "Amedspor"]  # yedek veri (football-data) adları
# Metin dosyasındaki adlar: aksanlı yazım (aynı ad) ve FIKSTUR-03'te kanıtla eklenen iki takma ad
TX = {"Galatasaray": "Galatasaray", "Fenerbahce": "Fenerbahçe", "Konyaspor": "Atiker Konyaspor", "Amedspor": "Amed"}
PAIRS = [(0, 1, 2, 3), (0, 2, 1, 3), (0, 3, 1, 2)]
TXT_URL = TXT_FILES["T1"][0].url("2026-27")
JSON_URL = f"{OPENFOOTBALL_BASE}/2026-27/tr.1.json"


def _round_games(k: int):
    a, b, c, d = PAIRS[k % 3]
    return [(FD[a], FD[b]), (FD[c], FD[d])] if k % 2 == 0 else [(FD[b], FD[a]), (FD[d], FD[c])]


def _rounds():
    """[(sezon, tarih, [(ev, deplasman), ...])]: 2025/26 (geçmiş) + 2026/27 23 Ağustos'tan itibaren haftalık."""
    out = [("2025/26", pd.Timestamp("2025-08-16") + pd.Timedelta(days=7 * k), _round_games(k)) for k in range(30)]
    out += [("2026/27", pd.Timestamp("2026-08-23") + pd.Timedelta(days=7 * k), _round_games(k)) for k in range(12)]
    return out


def _score(i: int):
    return (i % 3, (i + 1) % 2), (i % 2, 0)


def _indexed():
    i = 0
    for season, d, games in _rounds():
        for h, a in games:
            yield i, season, d, h, a
            i += 1


def _mirror(until: str = "2026-09-06") -> bytes:
    rows = []
    for i, _, d, h, a in _indexed():
        if d > pd.Timestamp(until):
            continue
        (fh, fa), (hh, ha) = _score(i)
        rows.append({"Division": "T1", "MatchDate": d.strftime("%Y-%m-%d"), "MatchTime": "19:00:00", "HomeTeam": h,
                     "AwayTeam": a, "FTHome": fh, "FTAway": fa, "HTHome": min(hh, fh), "HTAway": min(ha, fa),
                     "OddHome": 2.0, "OddDraw": 3.3, "OddAway": 3.6})
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode()


def _txt(played_until: str = "2026-10-04", timed_until: str = "2026-10-11") -> bytes:
    """europe deposu biçiminde (skor takımların arasında; saat yalnızca değişince yazılır; gol satırları)."""
    lines = ["= Turkey | Süper Lig 2026/27", "", "# Teams    4", ""]
    k = 0
    for i, season, d, h, a in _indexed():
        if season != "2026/27":
            continue
        if k % 2 == 0:
            lines += ["", f"▪ Regular Season - {k // 2 + 1}", f"{d:%a %b} {d.day}" + (" 2026" if k == 0 else "")]
        if d <= pd.Timestamp(played_until):
            (fh, fa), (hh, ha) = _score(i)
            t = "  19:00   " if k % 2 == 0 else "          "
            lines.append(f"{t}{TX[h]}  {fh}-{fa} ({min(hh, fh)}-{min(ha, fa)})  {TX[a]}   ")
            if fh:
                lines.append("                  (Oyuncu 10';")
                lines.append("                   Diğer 80')")
        else:
            t = "  19:00   " if (k % 2 == 0 and d <= pd.Timestamp(timed_until)) else "          "
            lines.append(f"{t}{TX[h]}   v   {TX[a]}   ")
        k += 1
    return ("\n".join(lines) + "\n").encode("utf-8")


def _files(**kw):
    return {MIRROR_URL: _mirror(kw.pop("mirror_until", "2026-09-06")), TXT_URL: _txt(**kw)}


def _update(home, files):
    st = DataStore(home)
    st.load()
    rep = st.update(["T1"], 3, today=TODAY, downloader=FakeDownloader(files, fd_down=True), allowed=ALL)
    return st, rep


# ============================================================ dönüştürücü

EUROPE = """= Turkey | Süper Lig 2026/27

# Dates    Fri Aug 14 2026 - Sun May 23 2027 (282d)

▪ Regular Season - 1
Fri Aug 14 2026
  21:30   Galatasaray  2-2 (0-0)  Çorum
                  (Victor OSIMHEN 53', 90';
                   Alexandros Kyziridis 59', Jesus RAMIREZ 61')
Sat Aug 15
  19:00   Atiker Konyaspor  0-1 (0-0)  Çaykur Rizespor
          Kasimpasa  1-1 (0-1)  Trabzonspor

▪ Regular Season - 8
Sun Oct 18
          Gençlerbirligi   v   Galatasaray
"""

OPENLIGA = """###
#  converted from openligadb.de json to Football.TXT

= 2. Fußball-Bundesliga 2026/2027

▪ 1. Spieltag
Fri Aug 7 2026
  20:30  VfL Bochum               v Hertha BSC                 0-1 (0-1)
            (0-1  Sebastian Grönning 39')
Sat Aug 8
  13:00  1. FC Heidenheim 1846    v VfL Osnabrück              4-3 (3-2)
            (1-0  B. Zivzivadze 10'
             4-3  R. Meißner 90+2' (p))
         SV Darmstadt 98          v Hannover 96

▪ 8. Spieltag
Sun Oct 18
  13:30  VfL Wolfsburg            v 1. FC Heidenheim 1846
         Hannover 96              v FC St. Pauli
         Karlsruher SC            v SV Darmstadt 98
         Dynamo Dresden           v 1. FC Magdeburg
"""


def test_converter_reads_both_layouts():
    r = parse_football_txt(EUROPE.encode(), "2026-27")
    assert r.name == "Turkey | Süper Lig 2026/27" and not r.skipped
    m = r.matches
    assert [x["date"] for x in m] == ["2026-08-14", "2026-08-15", "2026-08-15", "2026-10-18"]
    assert m[0]["score"] == {"ft": [2, 2], "ht": [0, 0]} and m[0]["time"] == "21:30"
    assert m[2]["team1"] == "Kasimpasa" and m[2]["time"] == "19:00"  # saat yazılmayan satır önceki saati taşır
    assert "score" not in m[3] and m[3]["time"] == "" and m[3]["team2"] == "Galatasaray"
    assert E.round_number(m[3]["round"]) == 8 and E.round_number("1st Phase - 3") == 3
    assert E.round_number("Championship Round - 1") is None  # bölünme sonrası aşama normal sezon turu değildir

    r = parse_football_txt(OPENLIGA.encode(), "2026-27")
    m = r.matches
    assert not r.skipped and len(m) == 7  # gol satırları (çok satırlı blok dahil) maç sayılmaz
    assert m[1]["score"] == {"ft": [4, 3], "ht": [3, 2]} and m[1]["team1"] == "1. FC Heidenheim 1846"
    assert m[2]["team2"] == "Hannover 96" and "score" not in m[2] and m[2]["time"] == "13:00"
    # Hiç oynanmamış turun bütün maçları aynı gün ve saatte: openligadb yer tutucusu, saat boşaltılır
    assert r.placeholder_times == 4 and all(x["time"] == "" for x in m[3:])


def test_converter_never_guesses():
    text = """= X 2026/27

▪ Regular Season - 1
Fri Aug 15 2026
  20:00   A  1-0  B
Sat Dec 19
  15:00   C  2-1  D
Sat Jan 2
          E  0-0  F
  TBC (yeni tarih bekleniyor)
    --:--  G                       v H
  19:00   I  1-1 (1-0)  J
▪ Regular Season - 2
  K v L
▪ Regular Season - 3
Sun Aug 23
  20:00  M                v N                3-0    [awarded]
  20:00  O                4-2 a.e.t. (2-2, 1-1)  P
  20:00  Q                v R (*)
  20:00  S  1-0  S
Mon Aug 3 2020
  20:00  T  v  U
▪ Regular Season - 4
Sun Aug 30
  20:00  V  2-0  W
                  (Gol 10'
▪ Regular Season - 5
Sun Sep 6
  20:00  X  v  Y
"""
    r = parse_football_txt(text.encode(), "2026-27")
    got = {(x["team1"], x["team2"]): x for x in r.matches}
    # 15 Ağustos 2026 Cumartesi: "Fri" uyuşmuyor, maç atlanır (tarih düzeltilmez)
    assert ("A", "B") not in got and r.skipped["TARIH_GUN_UYUSMAZ"] == 1
    assert got[("C", "D")]["date"] == "2026-12-19" and got[("E", "F")]["date"] == "2027-01-02"  # yıl geçişi
    assert got[("E", "F")]["time"] == ""  # saat yalnızca aynı gün içinde taşınır
    assert got[("Q", "R")]["date"] == "2026-08-23"  # geriye dönen tarih (ertelenen maç bloğu) doğru yılda
    # TBC altındaki maçlar ve tarih satırı olmayan tur tarihsizdir (önceki turun tarihi taşınmaz)
    assert ("G", "H") not in got and ("I", "J") not in got and ("K", "L") not in got and r.skipped["TARIH_YOK"] == 3
    assert ("M", "N") not in got and r.skipped["NOT_ISARETI"] == 1  # hükmen sonuç normal süre sonucu değildir
    assert ("O", "P") not in got and r.skipped["MAC_SATIRI_OKUNAMADI"] == 1  # uzatmalı skor okunmaz
    assert got[("Q", "R")]["date"] == "2026-08-23" and "score" not in got[("Q", "R")]  # dipnot işareti atılır
    assert r.skipped["TAKIM_GECERSIZ"] == 1 and r.skipped["TARIH_SEZON_DISI"] == 1 and ("T", "U") not in got
    # Kapanmayan gol bloğu kalan dosyayı yutmaz
    assert got[("V", "W")]["score"]["ft"] == [2, 0] and ("X", "Y") in got and r.skipped["GOL_BLOGU_KAPANMADI"] == 1
    # Deterministik çıktı ve köken alanı
    a, _ = convert_football_txt(text.encode(), "2026-27", "openfootball/europe:x.txt")
    b, _ = convert_football_txt(text.encode(), "2026-27", "openfootball/europe:x.txt")
    assert a == b and converted_origin(a)["donusturucu"] == TXT_CONVERTER and converted_origin(b"{}") is None


def test_calendar_year_and_bracket_dates():
    text = "▪ Matchday 1\n  [Sat Apr/4]\n    16:00  A  v  B\n  2026-04-05\n    18:00  C v D 1-1\n"
    m = parse_football_txt(text.encode(), "2026").matches
    assert [(x["date"], x["time"]) for x in m] == [("2026-04-04", "16:00"), ("2026-04-05", "18:00")]
    assert m[1]["score"] == {"ft": [1, 1]}


# ============================================================ takma adlar


def test_txt_aliases_resolve_only_in_their_country_context():
    t1 = ["Amedspor", "Alanyaspor", "Konyaspor", "Erzurumspor", "Galatasaray"]
    res = resolve_teams(["Amed", "Aytemiz Alanyaspor", "Atiker Konyaspor", "BB Erzurumspor"], t1, "T1", "openfootball")
    assert {k: v.team for k, v in res.items()} == {"Amed": "Amedspor", "Aytemiz Alanyaspor": "Alanyaspor",
                                                   "Atiker Konyaspor": "Konyaspor", "BB Erzurumspor": "Erzurumspor"}
    g1 = ["Aris", "Iraklis", "OFI Crete", "Volos NFC"]
    assert all(v.exact for v in resolve_teams(["Aris Thessaloniki", "Iraklis 1908", "OFI", "Volos"], g1, "G1",
                                              "openfootball").values())
    assert resolve_teams(["Saint Johnstone FC"], ["St Johnstone"], "SC0", "openfootball")["Saint Johnstone FC"].exact
    assert resolve_teams(["Energie Cottbus"], ["Cottbus"], "D2", "openfootball")["Energie Cottbus"].exact
    # Başka ülkenin bağlamında ve başka kaynakta takma ad uygulanmaz
    assert not resolve_teams(["Amed"], ["Amedspor"], "G1", "openfootball")["Amed"].exact
    assert not resolve_teams(["Amed"], ["Amedspor"], "T1", "football-data")["Amed"].exact


# ============================================================ veri deposu


def test_txt_fallback_fills_gap_and_fixtures_with_verified_provenance(tmp_home):
    files = _files()
    st, rep = _update(tmp_home, files)
    assert rep.txt_sources == {"T1": "openfootball/europe:turkey/2026-27_tr1.txt"}
    assert "openfootball metin dosyaları" in rep.summary()
    gap = st.matches[st.matches["source"] == COMPLETION_LABEL]
    # Yedek veri 6 Eylül'de bitiyor; metin dosyası 13 Eylül - 4 Ekim arası 4 turu oynanmış gösteriyor
    assert rep.completed == {"T1": 8} and len(gap) == 8 and set(gap["home"]) | set(gap["away"]) == set(FD)
    rec = st.meta["tamamlama_kokeni"][0]
    assert rec["bicim"] == "football.txt" and rec["donusturucu"] == TXT_CONVERTER
    assert rec["kaynak"] == "openfootball/europe:turkey/2026-27_tr1.txt"
    assert (st.raw_dir / rec["cache_rel"]).read_bytes() == files[TXT_URL]  # kanıt ASIL metin dosyasıdır
    assert verified_labels(st) == {COMPLETION_LABEL}
    assert E.training_rights_codes(st.matches, {"github-mirror": "t"}, verified_labels(st),
                                   {"github-mirror": "t"}) == []
    st2 = DataStore(tmp_home)
    assert st2.load() and verified_labels(st2) == {COMPLETION_LABEL}
    # Fikstür: 18 Ekim turu (pencere 12-22 Ekim), depo adlarıyla; saat kaynakta yok
    fx = st.fixtures
    assert len(fx) == 2 and set(fx["date"]) == {pd.Timestamp("2026-10-18")}
    assert set(fx["home"]) | set(fx["away"]) == set(FD) and (fx["time"] == "").all()
    assert st.unmatched_fixtures.empty
    assert any("saati kaynakta yok" in w for w in rep.warnings)
    assert not any("kaynak geride" in w for w in rep.warnings)
    # Uygunluk kontrolü dönüştürülmüş takvimi okur (ağ isteği yok)
    covs = E.cached_coverages(st.raw_dir, ["T1"], TODAY, {"T1": FD})
    cov = covs["T1"][-1]
    assert len(cov.matches) == 24 and {m.home for m in cov.matches} == set(FD) and not cov.unmapped_names


def test_tampered_txt_copy_or_converter_change_loses_rights(tmp_home):
    st, _ = _update(tmp_home, _files())
    recs = st.meta["tamamlama_kokeni"]
    assert verify_completion(st.matches, recs, st.raw_dir)[0]
    changed = [{**recs[0], "donusturucu": "football-txt-v0"}]
    ok, problems = verify_completion(st.matches, changed, st.raw_dir)
    assert not ok and "dönüştürücü" in problems[0]
    m = st.matches.copy()
    m.loc[m.index[m["source"] == COMPLETION_LABEL][0], "fthg"] = 9  # depodaki skor değiştirildi
    ok, problems = verify_completion(m, recs, st.raw_dir)
    assert not ok and "üretilemiyor" in problems[0]
    path = st.raw_dir / recs[0]["cache_rel"]
    path.write_bytes(path.read_bytes() + b"\n")  # saklanan metin dosyası değişti
    ok, problems = verify_completion(st.matches, recs, st.raw_dir)
    assert not ok and "özeti" in problems[0]
    assert COMPLETION_LABEL not in verified_labels(st)


def test_stale_source_is_reported(tmp_home):
    # Metin dosyası 20 Eylül'den sonra güncellenmemiş: 27 Eylül ve 4 Ekim turlarının sonucu hiçbir kaynakta yok
    _, rep = _update(tmp_home, _files(played_until="2026-09-20"))
    assert rep.completed == {"T1": 4}
    assert any("kaynak geride" in w and "4 maç" in w for w in rep.warnings)


def test_football_json_is_preferred_when_it_exists(tmp_home):
    files = _files()
    st, rep = _update(tmp_home, files)
    conv = st.raw_dir / "openfootball" / "2026-27" / "tr.1.txt.json"
    assert rep.txt_sources and conv.is_file()
    files[JSON_URL] = convert_football_txt(files[TXT_URL], "2026-27")[0]  # aynı içerik, football.json biçiminde
    st, rep = _update(tmp_home, files)
    assert rep.txt_sources == {} and rep.completed == {"T1": 8} and not conv.exists()
    assert "bicim" not in st.meta["tamamlama_kokeni"][0] and verified_labels(st) == {COMPLETION_LABEL}


def test_no_txt_file_means_no_fixtures_and_no_error(tmp_home):
    files = _files()
    del files[TXT_URL]
    st, rep = _update(tmp_home, files)
    assert rep.txt_sources == {} and rep.completed == {} and st.fixtures.empty


def test_github_profile_reads_txt_from_pinned_commit(tmp_path):
    c_xg, c_of, c_eu = "c" * 40, "a" * 40, "e" * 40
    routes = {
        refs_url("xgabora/Club-Football-Match-Data-2000-2025"): Resp(200, adv({"refs/heads/main": c_xg})),
        refs_url("openfootball/football.json"): Resp(200, adv({"refs/heads/master": c_of})),
        refs_url("openfootball/europe"): Resp(200, adv({"refs/heads/master": c_eu})),
        raw("xgabora/Club-Football-Match-Data-2000-2025", c_xg, "data/Matches.csv"): Resp(200, _mirror()),
        raw("openfootball/europe", c_eu, "turkey/2026-27_tr1.txt"): Resp(200, _txt()),
    }
    gh = FakeSession(routes)
    fd_session = FakeSession()
    dl = Downloader(tmp_path / "s" / "raw", allowed_hosts=GITHUB_HOSTS, polite_delay=0)
    dl.session = fd_session
    st = DataStore(tmp_path / "s")
    rep = st.update(["T1"], 3, today=TODAY, downloader=dl, allowed=allowed_sources({"github-mirror": "x"}),
                    profile="github", github_transport=transport(gh))
    assert fd_session.calls == [] and all(host_of(u) in GITHUB_HOSTS for u in gh.calls)
    raw_calls = [u for u in gh.calls if "raw.githubusercontent.com" in u]
    assert any("/openfootball/europe/" in u for u in raw_calls)
    assert all(any(f"/{c}/" in u for c in (c_xg, c_of, c_eu)) for u in raw_calls)  # dal adıyla dosya alınmaz
    assert rep.txt_sources == {"T1": "openfootball/europe:turkey/2026-27_tr1.txt"} and rep.completed == {"T1": 8}
    assert st.meta["github_kaynak"]["openfootball/europe"]["commit"] == c_eu
    assert len(st.fixtures) == 2 and verified_labels(st) == {COMPLETION_LABEL}


def test_missing_file_does_not_overwrite_repo_status(tmp_path):
    from bahis_tahmin.data.store import UpdateReport, _GitHubFiles, _GitHubUnavailable

    c_eu = "e" * 40
    routes = {refs_url("openfootball/europe"): Resp(200, adv({"refs/heads/master": c_eu})),
              raw("openfootball/europe", c_eu, "turkey/2026-27_tr1.txt"): Resp(200, b"x")}
    rep = UpdateReport()
    gh = _GitHubFiles(tmp_path, transport(FakeSession(routes)), rep)
    assert gh.get("openfootball/europe", "turkey/2026-27_tr1.txt") == b"x"
    with pytest.raises(_GitHubUnavailable):
        gh.get("openfootball/europe", "france/2026-27_fr2.txt")  # ligin o sezon dosyası yok
    st = rep.github["openfootball/europe"]
    assert st["commit"] == c_eu and "alınamadı" not in st["aciklama"]


@pytest.mark.parametrize("code", sorted(TXT_FILES))
def test_txt_catalogue_only_for_leagues_with_openfootball_code(code):
    from bahis_tahmin.data.leagues import LEAGUES

    assert LEAGUES[code].openfootball
    for f in TXT_FILES[code]:
        assert f.repo.startswith("openfootball/") and "{season}" in f.path
        assert json.dumps(f.url("2026-27")).startswith('"https://raw.githubusercontent.com/openfootball/')

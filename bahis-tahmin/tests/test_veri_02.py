"""VERI-02: eksik dönemin openfootball sonuçlarıyla tamamlanması ve son sonuçların yayın gecikmesi.

Kullanıcıda football-data.co.uk erişilemiyor ve GitHub yedek veri seti güncel sezonda haftalarca geride kalıyordu:
bütün maçlar "Uyarılı (DEPODA_EKSIK_MAC)" görünüyordu. Yalnızca SENTETİK veri ve sahte indirici (ağ yok).
"""

from __future__ import annotations

import datetime as dt
import io
import json

import pandas as pd
import pytest
from test_store import FakeDownloader
from uygunluk_yardim import AS_OF, full_context, recent_synthetic

from bahis_tahmin import eligibility as E
from bahis_tahmin.data.completion import COMPLETION_LABEL, verify_completion
from bahis_tahmin.data.provenance import verified_labels
from bahis_tahmin.data.sources import MIRROR_URL, OPENFOOTBALL_BASE
from bahis_tahmin.data.store import DataStore

TODAY = dt.date(2026, 10, 12)
ALL = {"football-data", "github-mirror", "openfootball"}
FD = ["Arsenal", "Chelsea", "Coventry", "Hull"]  # football-data adları
OF = {"Arsenal": "Arsenal FC", "Chelsea": "Chelsea FC", "Coventry": "Coventry City FC", "Hull": "Hull City AFC"}
PAIRS = [(0, 1, 2, 3), (0, 2, 1, 3), (0, 3, 1, 2)]  # her turda iki maç


def _round_games(k: int):
    a, b, c, d = PAIRS[k % 3]
    return [(FD[a], FD[b]), (FD[c], FD[d])] if k % 2 == 0 else [(FD[b], FD[a]), (FD[d], FD[c])]


def _schedule():
    """2025/26 (geçmiş) + 2026/27: 23 Ağustos'tan itibaren haftalık turlar."""
    out = []
    d = pd.Timestamp("2025-08-16")
    for k in range(30):
        out += [("2025/26", d + pd.Timedelta(days=7 * k), h, a) for h, a in _round_games(k)]
    d = pd.Timestamp("2026-08-23")
    for k in range(12):
        out += [("2026/27", d + pd.Timedelta(days=7 * k), h, a) for h, a in _round_games(k)]
    return out


def _score(i: int):
    return (i % 3, (i + 1) % 2), (i % 2, 0)


def _mirror(until: str) -> bytes:
    rows = []
    for i, (_, d, h, a) in enumerate(_schedule()):
        if d > pd.Timestamp(until):
            continue
        (fh, fa), (hh, ha) = _score(i)
        rows.append({"Division": "E0", "MatchDate": d.strftime("%Y-%m-%d"), "MatchTime": "15:00:00", "HomeTeam": h,
                     "AwayTeam": a, "FTHome": fh, "FTAway": fa, "HTHome": min(hh, fh), "HTAway": min(ha, fa),
                     "OddHome": 2.0, "OddDraw": 3.3, "OddAway": 3.6})
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode()


def _openfootball(played_until: str) -> bytes:
    ms = []
    for i, (season, d, h, a) in enumerate(_schedule()):
        if season != "2026/27":
            continue
        k = (d - pd.Timestamp("2026-08-23")).days // 7
        m = {"round": f"Matchday {k + 1}", "date": d.strftime("%Y-%m-%d"), "time": "15:00", "team1": OF[h],
             "team2": OF[a]}
        if d <= pd.Timestamp(played_until):
            (fh, fa), (hh, ha) = _score(i)
            m["score"] = {"ht": [min(hh, fh), min(ha, fa)], "ft": [fh, fa]}
        ms.append(m)
    return json.dumps({"name": "Premier League 2026/27", "matches": ms}).encode()


def _files(mirror_until="2026-09-06", played_until="2026-10-04"):
    return {MIRROR_URL: _mirror(mirror_until),
            f"{OPENFOOTBALL_BASE}/2026-27/en.1.json": _openfootball(played_until)}


def _update(home, files):
    st = DataStore(home)
    st.load()
    rep = st.update(["E0"], 3, today=TODAY, downloader=FakeDownloader(files, fd_down=True), allowed=ALL)
    return st, rep


def test_gap_is_filled_from_openfootball_with_verified_provenance(tmp_home):
    st, rep = _update(tmp_home, _files())
    gap = st.matches[st.matches["source"] == COMPLETION_LABEL]
    # Yedek veri 6 Eylül'de bitiyor; openfootball 13 Eylül - 4 Ekim arası 4 turu (8 maç) oynanmış gösteriyor
    assert rep.completed == {"E0": 8} and len(gap) == 8 and "openfootball sonuçlarıyla tamamlandı" in rep.summary()
    assert set(gap["home"]) | set(gap["away"]) == set(FD)  # kaynak adları kesin kimlikle football-data adlarına
    assert gap["date"].min() > pd.Timestamp("2026-09-06") and gap["date"].max() <= pd.Timestamp("2026-10-04")
    assert gap[["o_h", "o_d", "o_a"]].isna().all().all()  # oran uydurulmaz
    assert not st.matches.duplicated(["league", "date", "home", "away"]).any()
    assert verified_labels(st) == {COMPLETION_LABEL}
    assert E.training_rights_codes(st.matches, {"github-mirror": "t"}, verified_labels(st),
                                   {"github-mirror": "t"}) == []
    # Diskten yeniden yükleme: köken kaydı ve kopya dosya ile yine doğrulanır
    st2 = DataStore(tmp_home)
    assert st2.load() and verified_labels(st2) == {COMPLETION_LABEL}
    # Fikstür: oynanmamış maçlar yaklaşan maç olarak kalır, tamamlanan maçlar fikstüre girmez
    assert (st.fixtures["date"] >= pd.Timestamp(TODAY)).all()


def test_tampered_or_relabelled_rows_lose_rights(tmp_home):
    st, _ = _update(tmp_home, _files())
    raw = st.raw_dir
    recs = st.meta["tamamlama_kokeni"]
    m = st.matches.copy()
    i = m.index[m["source"] == COMPLETION_LABEL][0]
    m.loc[i, "fthg"] = 9
    ok, problems = verify_completion(m, recs, raw)
    assert not ok and "üretilemiyor" in problems[0]
    st.matches = m
    assert COMPLETION_LABEL not in verified_labels(st)
    assert "KAYNAK_KOKENI_DOGRULANAMADI" in E.training_rights_codes(m, {"github-mirror": "t"}, verified_labels(st),
                                                                     {"github-mirror": "t"})
    # Yedek veri satırının etiketini değiştirmek hak kazandırmaz
    st, _ = _update(tmp_home, _files())
    m = st.matches.copy()
    j = m.index[m["source"] == "github-yedek"][-1]
    m.loc[j, "source"] = COMPLETION_LABEL
    assert not verify_completion(m, st.meta["tamamlama_kokeni"], st.raw_dir)[0]
    # Dosya değişirse kayıt tutmaz
    (st.raw_dir / recs[0]["cache_rel"]).write_bytes(b"{}")
    assert not verify_completion(st.matches, recs, st.raw_dir)[0]


def test_completion_is_rebuilt_each_update_and_stops_when_source_catches_up(tmp_home):
    st, rep = _update(tmp_home, _files())
    assert rep.completed == {"E0": 8}
    st, rep = _update(tmp_home, _files())  # aynı girdiler: aynı satırlar, çoğalma yok
    assert rep.completed == {"E0": 8} and (st.matches["source"] == COMPLETION_LABEL).sum() == 8
    st, rep = _update(tmp_home, _files(mirror_until="2026-10-04"))  # yedek veri yetişti: tamamlama gerekmez
    assert rep.completed == {} and (st.matches["source"] == COMPLETION_LABEL).sum() == 0
    assert st.meta["tamamlama_kokeni"] == [] and verified_labels(st) == set()


def test_unmatched_names_are_not_added(tmp_home):
    files = _files()
    obj = json.loads(files[f"{OPENFOOTBALL_BASE}/2026-27/en.1.json"])
    for mt in obj["matches"]:
        if mt["team1"] == "Hull City AFC":
            mt["team1"] = "Kingsbridge Town"  # takma adı olmayan ad
    files[f"{OPENFOOTBALL_BASE}/2026-27/en.1.json"] = json.dumps(obj).encode()
    st, rep = _update(tmp_home, files)
    gap = st.matches[st.matches["source"] == COMPLETION_LABEL]
    assert 0 < len(gap) < 8 and "Kingsbridge Town" not in set(gap["home"]) and verified_labels(st) == {COMPLETION_LABEL}


@pytest.fixture(scope="module")
def ctx_parts():
    from bahis_tahmin.goals.engine import GoalEngine

    m = recent_synthetic()
    eng = GoalEngine()
    eng.train(m)
    return m, eng


def test_recent_unpublished_results_are_a_note_only_in_standart(ctx_parts):
    """Bilgi kesiminden 2 gün önce oynanması gereken ama sonucu henüz hiçbir yerde olmayan maç: sıkı modda v2 gibi
    belirsiz (tahmin yok), standart modda olağan yayın gecikmesi (not; tahmin ve bahis engeli değil)."""
    m, eng = ctx_parts
    start = AS_OF.date() - dt.timedelta(days=2)
    teams = sorted(set(m["home"]))
    out = {}
    for mode in E.POLICY_MODES:
        ctx = full_context(m, eng, AS_OF, start, mode=mode)
        first = next(x for x in ctx.coverages["T1"][-1].matches if x.date == start)
        opp = next(t for t in teams if t not in (first.home, first.away))
        out[mode] = ctx.evaluate(league="T1", date=start + dt.timedelta(days=7), home=first.home, away=opp,
                                 as_of=AS_OF, markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert out["siki"].reasons == ("KAYNAK_DURUMU_BELIRSIZ",) and not out["siki"].forecast_ok
    e = out["standart"]
    assert e.reasons == ("SON_SONUC_BEKLENIYOR",) and e.forecast_ok and e.bet_ok and e.status_label == "Kullanılabilir"
    assert "henüz yayımlanmadı" in e.short_text()
    # Gecikme penceresinden eski bilinmeyen sonuç standart modda da bahsi engeller
    late = AS_OF + dt.timedelta(days=E.PENDING_GRACE_DAYS + 1)
    ctx = full_context(m, eng, late, start, mode="standart")
    first = next(x for x in ctx.coverages["T1"][-1].matches if x.date == start)
    opp = next(t for t in teams if t not in (first.home, first.away))
    e = ctx.evaluate(league="T1", date=late.date() + dt.timedelta(days=3), home=first.home, away=opp, as_of=late,
                     markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert "KAYNAK_DURUMU_BELIRSIZ" in e.reasons and e.forecast_ok and not e.bet_ok


def test_labels_carry_a_turkish_reason():
    assert set(E.SHORT_TEXT) == set(E.REASONS)
    assert E._short("TAKIM_GECMISI_YETERSIZ") == "takımın bu ligde az maçı var (TAKIM_GECMISI_YETERSIZ)"

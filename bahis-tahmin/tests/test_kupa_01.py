"""KUPA-01: kupa ve Avrupa maçları — veri, takım kimliği, köken, ligler arası model, uygunluk, arayüz ve CLI.

Yalnızca SENTETİK veri (``kupa_yardim``); ağ isteği yok. Uygunluk testleri tam uygun bir olumlu kontrolden başlar ve
her denetimi tek tek bozar (her bozulmanın kendi nedeni görünmeli)."""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from kupa_yardim import (
    AS_OF,
    CUP_DAY,
    SLAVIA_KEY,
    FakeCupDownloader,
    espn_event,
    espn_world,
    league_context,
    openfootball_files,
    world,
    write_cup_calendar,
)

UTC = dt.timezone.utc
TODAY = dt.date(2026, 1, 20)  # güncelleme testleri: 2025/26 sezonunun ortası
HK, AK = "İngiltere|Arsenal", "Türkiye|Galatasaray"


@pytest.fixture(scope="module")
def w():
    return world()


@pytest.fixture(scope="module")
def engine(w):
    from bahis_tahmin.kupa.motor import CupEngine

    dom, cups = w
    eng = CupEngine()
    eng.train(dom, cups)
    return eng


# =============================================================================================== openfootball


CUP_TXT = """= UEFA Champions League 2024/25

▪ League, Matchday 1
  Tue Sep 17 2024
    18:45  Arsenal FC (ENG)       v Galatasaray AŞ (TUR)     2-0 (1-0)
           Fenerbahçe SK (TUR)    v Chelsea FC (ENG)         1-1
    21:00  Liverpool FC (ENG)     v Beşiktaş JK (TUR)        3-1 (4-0)
  Mon Sep 18 2024
    21:00  Chelsea FC (ENG)       v Arsenal FC (ENG)         1-0
  Wed Oct 2
    21:00  Galatasaray AŞ (TUR)   v Liverpool FC (ENG)       0-0 [cancelled]
    21:00  Chelsea FC (ENG)       v Fenerbahçe SK (TUR)      2-1 a.e.t.
    21:00  Liverpool FC (ENG)     v Arsenal FC (ENG)         1-0 [awarded]
bu satır tanınmaz
  Tue Dec 10
    21:00  Arsenal FC (ENG)       v Chelsea FC (ENG)
▪ Finals, Final
  Sat May 31 2025
    21:00  Arsenal FC (ENG)       v Fenerbahçe SK (TUR)      4-3 pen. 1-1 a.e.t. (1-1, 0-1)
  Sat Jun 13 2026
    21:00  Arsenal FC (ENG)       v Chelsea FC (ENG)         1-0
"""


def test_cup_txt_parser_keeps_90_minute_scores_and_never_guesses():
    from bahis_tahmin.kupa.openfootball import parse_cup_txt

    pr = parse_cup_txt(CUP_TXT.encode("utf-8"), "2024-25")
    got = {(m["date"], m["team1"], m["team2"]): m for m in pr.matches}
    assert len(pr.matches) == 4
    a = got[("2024-09-17", "Arsenal FC", "Galatasaray AŞ")]
    assert a["score"] == {"ft": [2, 0], "ht": [1, 0]} and a["cc1"] == "ENG" and a["cc2"] == "TUR"
    assert a["time"] == "18:45" and a["neutral"] is False
    b = got[("2024-09-17", "Fenerbahçe SK", "Chelsea FC")]
    assert b["score"] == {"ft": [1, 1]} and b["time"] == "18:45"  # saat önceki satırdan; ilk yarı yazılmamış
    assert "score" not in got[("2024-12-10", "Arsenal FC", "Chelsea FC")]  # oynanmamış maç (fikstür)
    final = got[("2025-05-31", "Arsenal FC", "Fenerbahçe SK")]
    # Uzatmalı maç: normal süre parantez içindeki ilk skor; penaltılar yalnızca bilgi; final tarafsız sahada
    assert final["score"] == {"ft": [1, 1], "et": [1, 1], "ht": [0, 1], "pen": [4, 3]} and final["neutral"] is True
    assert dict(pr.skipped) == {"SKOR_OKUNAMADI": 1, "TARIH_GUN_UYUSMAZ": 1, "NOT_IPTAL": 1,
                                "UZATMA_NORMAL_SURE_YOK": 1, "NOT_HUKMEN": 1, "BILINMEYEN_SATIR": 1,
                                "TARIH_SEZON_DISI": 1}
    assert parse_cup_txt(CUP_TXT.encode("utf-8"), "2024-25").matches == pr.matches  # belirlenimci


# =============================================================================================== ESPN okuyucu


def test_espn_extra_time_reads_regulation_score_only_for_cups():
    from bahis_tahmin.data.espn import parse_scoreboard

    evs = [
        # 90 dk 1-1 (ilk yarı 0-1), uzatmada ev sahibi bir gol daha: maç skoru 2-1
        espn_event("A", "2025-03-11", "Arsenal", "PSV", "1", "2", ft=(2, 1), name="STATUS_FINAL_AET",
                   linescores=([0, 1, 1, 0], [1, 0, 0, 0])),
        # Penaltılar: dönem skorları yok -> normal süre bilinmez, atlanır
        espn_event("B", "2025-03-12", "Inter", "Bayern", "3", "4", ft=(1, 1), name="STATUS_FINAL_PEN",
                   linescores=([1], [1])),
        # Dönem toplamı skorla uyuşmuyor -> atlanır (tahmin yok)
        espn_event("C", "2025-03-12", "Lille", "Porto", "5", "6", ft=(2, 2), name="STATUS_FINAL_AET",
                   linescores=([1, 0, 0, 0], [1, 1, 0, 0])),
        espn_event("D", "2025-05-31", "PSG", "Inter", "7", "3", ft=(5, 0), ht=(2, 0), neutral=True),
    ]
    data = json.dumps({"events": evs}).encode()
    league = parse_scoreboard(data, "İngiltere")  # lig yolu: uzatmalı maç hiç okunmaz
    assert [e.event_id for e in league.events] == ["D"] and league.skipped["NORMAL_SURE_DISI"] == 3
    cup = parse_scoreboard(data, "", allow_extra_time=True)
    by = {e.event_id: e for e in cup.events}
    assert set(by) == {"A", "D"} and cup.skipped["NORMAL_SURE_DISI"] == 2
    assert by["A"].ft == (1, 1) and by["A"].ht == (0, 1) and by["A"].extra_time is True
    assert (by["A"].home_id, by["A"].away_id) == ("1", "2")
    assert by["D"].neutral is True and by["D"].extra_time is False and by["D"].ft == (5, 0)


# =============================================================================================== takım kimliği


def test_openfootball_identity_is_country_scoped_and_needs_evidence(w):
    from bahis_tahmin.kupa.kimlik import map_openfootball

    dom, _ = w
    recs = [{"team1": "Arsenal FC", "cc1": "ENG", "team2": "Galatasaray AŞ", "cc2": "TUR"},
            {"team1": "Manchester City FC", "cc1": "ENG", "team2": "SK Slavia Praha", "cc2": "CZE"},
            {"team1": "Unknown United FC", "cc1": "ENG", "team2": "Arsenal FC", "cc2": "ESP"}]
    m = map_openfootball({"2024-25/cl.txt": recs}, dom)
    g = lambda cc, n: m.get("2024-25/cl.txt", cc, n)  # noqa: E731
    assert g("ENG", "Arsenal FC").key == "İngiltere|Arsenal" and g("ENG", "Arsenal FC").mapped
    assert g("TUR", "Galatasaray AŞ").key == "Türkiye|Galatasaray"
    assert g("ENG", "Manchester City FC").key == "İngiltere|Man City"  # doğrulanmış takma ad
    # Ligi veride olmayan ülke: ayrı kimlik, hiçbir lig takımıyla birleşmez
    assert g("CZE", "SK Slavia Praha").key == SLAVIA_KEY and not g("CZE", "SK Slavia Praha").mapped
    # Aynı ad başka ülkede (İspanya verisi yok): İngiliz Arsenal'le birleşmez
    assert g("ESP", "Arsenal FC").key == "ESP|arsenal" and not g("ESP", "Arsenal FC").mapped
    # Ülkesi kapsamda ama depoda yok: eşlenmez ve raporda görünür (benzerlikle eşleme yok)
    assert not g("ENG", "Unknown United FC").mapped and ("ENG", "Unknown United FC") in m.unmapped


def _of_df(rows):
    cols = ["comp", "date", "fthg", "ftag", "hthg", "htag", "home", "away", "home_key", "away_key", "home_country",
            "away_country", "home_mapped", "away_mapped"]
    return pd.DataFrame(rows, columns=cols)


def _ev(eid, d, hid, aid, ft, home="H", away="A"):
    from bahis_tahmin.data.espn import EspnEvent

    return EspnEvent(eid, pd.Timestamp(d).date(), "21:00", home, away, "post", "STATUS_FULL_TIME", ft, None, hid, aid)


def test_espn_identity_needs_unanimous_evidence_and_conflicts_are_dropped():
    from bahis_tahmin.kupa.kimlik import MIN_CUP_EVIDENCE, map_espn

    assert MIN_CUP_EVIDENCE == 2
    of = _of_df([
        ("UEL", "2024-09-19", 3, 0, 0, 0, "Slavia Praha", "Galatasaray", SLAVIA_KEY, HK.replace("İngiltere|Arsenal",
                                                                                                 "Türkiye|Galatasaray"),
         "CZE", "Türkiye", False, True),
        ("UEL", "2024-10-24", 1, 3, 1, 1, "Trabzonspor", "Slavia Praha", "Türkiye|Trabzonspor", SLAVIA_KEY,
         "Türkiye", "CZE", True, False),
        ("UCL", "2024-09-17", 2, 0, 1, 0, "Arsenal", "Chelsea", HK, "İngiltere|Chelsea", "İngiltere", "İngiltere",
         True, True),
        ("UCL", "2024-10-01", 1, 0, 0, 0, "Arsenal", "Liverpool", HK, "İngiltere|Liverpool", "İngiltere",
         "İngiltere", True, True),
    ])
    events = {"UEL": [_ev("e1", "2024-09-19", "999", "200", (3, 0)), _ev("e2", "2024-10-25", "203", "999", (1, 3))],
              "UCL": [_ev("e3", "2024-09-17", "100", "101", (2, 0)), _ev("e4", "2024-10-01", "100", "102", (1, 0))]}
    # Lig kanıtı numara 100'ü Chelsea'ye bağlıyor, kupa kanıtı (2 maç) Arsenal'e: çelişki -> bağlanmaz
    domestic = {"100": ("İngiltere", "Chelsea", "espn_lig_kaniti"), "200": ("Türkiye", "Galatasaray", "espn_lig_kaniti")}
    em = map_espn(events, domestic, of)
    assert em.by_id["999"].key == SLAVIA_KEY and em.by_id["999"].basis == "kupa_kaniti 2 maç"  # tarih ±1 gün
    assert "100" not in em.by_id and "100" in em.conflicts
    assert em.by_id["200"].key == "Türkiye|Galatasaray" and em.by_id["200"].mapped
    assert "101" not in em.by_id and "102" not in em.by_id  # tek kupa maçı kanıtı yetmez
    assert em.get("101", "Chelsea").key == "ESPN|101" and not em.get("101", "Chelsea").mapped
    # Tek kupa maçı: Slavia bağlanmaz
    em1 = map_espn({"UEL": events["UEL"][:1]}, {}, of)
    assert "999" not in em1.by_id


# =============================================================================================== güncelleme ve köken


@pytest.fixture(scope="module")
def updated(w, tmp_path_factory):
    from bahis_tahmin.kupa.veri import update_cups

    dom, cups = w
    raw = tmp_path_factory.mktemp("kupa_raw")
    of = openfootball_files(cups[cups["season"] < "2025/26"])
    dl = FakeCupDownloader(of, espn_world(dom, cups, TODAY), raw / "onbellek")
    res = update_cups(raw, dl, None, ["UCL", "UEL"], 5, dom, TODAY, 60, {"openfootball", "espn"})
    return res, raw, dl


def test_update_merges_openfootball_history_and_espn_current_season(updated, w):
    res, raw, _ = updated
    _, cups = w
    m = res.matches
    assert res.warnings == []
    src = m.groupby("season")["source"].unique().map(list).to_dict()
    assert all(src[s] == ["openfootball-kupa"] for s in ("2021/22", "2022/23", "2023/24", "2024/25"))
    assert src["2025/26"] == ["espn"]  # içinde bulunulan sezon ESPN'den (bitmiş sezonlar openfootball)
    played = cups[(cups["season"] == "2025/26") & (cups["date"] < pd.Timestamp(TODAY))]
    assert (m["season"] == "2025/26").sum() == len(played)
    assert len(m) == (cups["season"] < "2025/26").sum() + len(played)
    # Kimlik: bütün lig takımları depodaki adlarına, Slavia ayrı kimliğine; ESPN'de de aynı anahtarlar
    keys = set(m["home_key"]) | set(m["away_key"])
    assert keys == set(cups["home_key"]) | set(cups["away_key"])
    esp = res.meta["eslesme"]["espn"]
    assert esp["999"]["anahtar"] == SLAVIA_KEY and esp["999"]["kanit"].startswith("kupa_kaniti")
    assert esp["103"]["anahtar"] == "İngiltere|Man City"  # ESPN "Manchester City" -> depodaki ad
    assert res.meta["eslesme"]["espn_celiski"] == {}
    # Skorlar kaynakla aynı (ESPN satırları dahil)
    j = m.merge(cups, on=["comp", "date", "home_key", "away_key"], suffixes=("", "_w"))
    assert len(j) == len(m) and (j["fthg"] == j["fthg_w"]).all() and (j["ftag"] == j["ftag_w"]).all()
    fx = res.fixtures
    assert len(fx) and (fx["source"] == "espn").all() and fx["date"].min() >= pd.Timestamp(TODAY)
    assert fx["date"].max() <= pd.Timestamp(TODAY + dt.timedelta(days=60))


def test_espn_calendars_are_written_and_stale_ones_removed(updated, tmp_path):
    from bahis_tahmin.kupa.veri import EspnMap, read_calendars, write_calendars

    res, raw, _ = updated
    cal = read_calendars(raw)
    assert set(cal) == {("UCL", "2024/25"), ("UCL", "2025/26"), ("UEL", "2024/25"), ("UEL", "2025/26")}
    recs = cal[("UCL", "2025/26")][1]
    fx = res.fixtures.iloc[0]
    eid = fx["provider_id"].split(":", 1)[1]
    hit = [r for r in recs if r["id"] == eid]
    assert hit and hit[0]["home_key"] == fx["home_key"] and "ft" not in hit[0]
    # ESPN'den gelmeyen turnuvanın eski takvimi silinir (onay geri alındıysa kanıt olarak kullanılmaz)
    t = tmp_path / "raw"
    write_cup_calendar(t, "UECL", "2025/26", [], AS_OF)
    write_calendars(t, {}, EspnMap(), TODAY)
    assert read_calendars(t) == {}


def test_provenance_proof_copy_reproduces_rows_and_detects_tampering(updated, tmp_path):
    import shutil

    from bahis_tahmin.kupa.veri import rows_sha256, verify_cup_rows

    res, raw, _ = updated
    m, recs = res.matches, res.meta["koken"]
    assert verify_cup_rows(m, recs, raw) == (True, [])
    assert {r["sezon"] for r in recs} == {"2021/22", "2022/23", "2023/24", "2024/25"}
    i = m.index[m["source"] == "openfootball-kupa"][5]
    bad = m.copy()
    bad.loc[i, "fthg"] = bad.loc[i, "fthg"] + 1
    ok, why = verify_cup_rows(bad, recs, raw)
    assert not ok and "kaynak dosyasından üretilenlerle aynı değil" in why[0]
    assert not verify_cup_rows(m.drop(index=i), recs, raw)[0]  # eksik satır da yakalanır
    # İki bağımsız denetim: (1) kayıttaki satır özeti uydurulsa da satırlar dosyadan yeniden üretilemez;
    # (2) satırlar dosyayla aynı olsa da kayıttaki satır özeti değiştirilmişse kabul edilmez
    key = (bad.loc[i, "comp"], str(bad.loc[i, "season"]))
    g = bad[(bad["comp"] == key[0]) & (bad["season"].astype(str) == key[1]) & (bad["source"] == "openfootball-kupa")]
    forged = [dict(r, satir_ozeti=rows_sha256(g)) if (r["turnuva"], r["sezon"]) == key else r for r in recs]
    assert not verify_cup_rows(bad, forged, raw)[0]
    changed = [dict(r, satir_ozeti="0" * 64) if (r["turnuva"], r["sezon"]) == key else r for r in recs]
    assert not verify_cup_rows(m, changed, raw)[0]
    alt = tmp_path / "raw"
    shutil.copytree(raw, alt)
    proof = alt / recs[0]["kopya"]
    proof.write_bytes(proof.read_bytes() + b"\n")
    ok, why = verify_cup_rows(m, recs, alt)
    assert not ok and any("özeti kayıtla uyuşmuyor" in x for x in why)
    proof.unlink()
    assert any("kopyası yok" in x for x in verify_cup_rows(m, recs, alt)[1])
    assert not verify_cup_rows(m, [], raw)[0]  # köken kaydı yoksa doğrulanmış sayılmaz
    # Kaynak satırı olmayan depo (yalnızca ESPN): openfootball etiketi doğrulanmış sayılmaz
    assert not verify_cup_rows(m[m["source"] == "espn"], recs, raw)[0]


def test_without_consent_espn_is_never_requested(w, tmp_path):
    from bahis_tahmin.kupa.veri import update_cups

    dom, cups = w
    of = openfootball_files(cups[cups["season"] < "2025/26"])
    dl = FakeCupDownloader(of, espn_world(dom, cups, TODAY), tmp_path / "c")
    res = update_cups(tmp_path / "raw", dl, None, ["UCL"], 5, dom, TODAY, 60, {"openfootball"})
    assert not any("espn" in u for u in dl.requested)
    assert set(res.matches["source"]) == {"openfootball-kupa"} and res.fixtures.empty
    res0 = update_cups(tmp_path / "raw0", dl, None, ["UCL"], 5, dom, TODAY, 60, set())
    assert res0.matches.empty


def test_store_keeps_cups_when_untouched_and_clears_on_empty_selection(w, tmp_home, updated):
    from bahis_tahmin.data.store import DataStore, UpdateReport

    dom, _ = w
    res, _raw, _ = updated
    st = DataStore(tmp_home)
    st.matches = dom
    st.cup_matches, st.cup_fixtures = res.matches, res.fixtures
    st.save()
    again = DataStore(tmp_home)
    again.load()
    pd.testing.assert_frame_equal(again.cup_matches.reset_index(drop=True), res.matches.reset_index(drop=True))
    assert len(again.cup_fixtures) == len(res.fixtures)
    rep = UpdateReport()
    again._update_cups(None, None, [], 5, TODAY, 60, set(), rep, False, lambda p, m: None)  # seçim boş: temizlenir
    assert again.cup_matches.empty and again.cup_fixtures.empty and again.meta["kupa"] == {"turnuvalar": []}


# =============================================================================================== model ve doğrulama


def test_model_learns_league_gap_from_cups_and_is_validated(engine):
    from bahis_tahmin.kupa.motor import DOGRULANDI, DOGRULANMADI, MIN_VALIDATION

    rep = engine.report
    g = rep.groups["UEFA"]
    assert engine.status["UEFA"] == DOGRULANDI and g["n"] >= MIN_VALIDATION
    assert g["ll"] < g["ll_taban"] and g["ll_fark_ust95"] < 0
    # Yurt içi kupa / diğer kıta maçı yok: doğrulanmadı (nedenli)
    assert engine.status["YURTICI"] == DOGRULANMADI and "örneklem dışı" in rep.groups["YURTICI"]["neden"]
    lt = engine.league_table()
    assert list(lt["lig"]) == ["E0", "T1"]  # İngiltere ligi kupa maçlarından daha güçlü öğrenilir
    assert lt.iloc[0]["Güç"] - lt.iloc[1]["Güç"] > 0.5  # gerçek fark 1,0 (hücum 0,5 + savunma 0,5)
    a, b, _d, _g = engine.calib
    assert 0.5 < b < 1.5 and abs(a) < 1.0  # kalibrasyon makul aralıkta


def test_cup_history_line_for_likely_selections(engine):
    """En Olası Seçimler'de kartlar lig modelinindir; kupa modelinin aynı eşikteki örneklem dışı geçmişi ayrı yazılır."""
    from bahis_tahmin.fmt import fmt_pct
    from bahis_tahmin.kupa.gorunum import likely_history_line
    from bahis_tahmin.kupa.motor import DOGRULANMADI

    oos, om = engine.oos, engine.oos_markets
    assert len(om) == len(oos)
    np.testing.assert_allclose(om["pmk_1"], oos["ph"], atol=1e-4)
    sel = oos["ph"] >= 0.6
    hit = float((oos.loc[sel, "y"] == 0).mean())
    line = likely_history_line(engine, ["1"], 0.6, True)
    assert f"geçmişte gerçekleşme: {fmt_pct(hit)} ({int(sel.sum())} seçim, ortalama olasılık" in line
    assert line.endswith("örneklem dışı, doğrulanmış gruplar).")
    eng = copy.copy(engine)
    eng.status = dict(engine.status, UEFA=DOGRULANMADI)  # doğrulanmamış grubun geçmişi kullanılmaz
    assert "bu eşikte geçmiş seçim yok" in likely_history_line(eng, ["1"], 0.6, True)
    assert likely_history_line(None, ["1"], 0.6, True) == ""


def test_walk_forward_never_sees_the_matches_it_scores(w, engine):
    """İleriye dönük doğrulama: bir haftanın tahmini yalnızca o haftadan önceki maçlarla kurulur. Son sezonun kupa
    sonuçları değişse de önceki haftaların ham tahminleri aynı kalır; ilk örneklem dışı sezon yalnızca kalibrasyon
    içindir (ölçüme girmez)."""
    from bahis_tahmin.kupa.motor import WARMUP_DAYS, CupEngine

    dom, cups = w
    oos = engine.oos
    first_day = pd.Timestamp(dom["date"].min())
    assert oos["date"].min() >= first_day + pd.Timedelta(days=WARMUP_DAYS)
    assert "2023/24" not in set(oos["season"])  # ilk örneklem dışı sezon: yalnızca kalibrasyon
    cut = pd.Timestamp("2026-02-02")  # pazartesi: bu haftanın maçları da yalnızca bu günden önceki verilerle tahmin edilir
    alt = cups.copy()
    late = alt["date"] >= cut
    alt.loc[late, ["fthg", "ftag"]] = alt.loc[late, ["ftag", "fthg"]].to_numpy() + 3
    eng2 = CupEngine()
    eng2.train(dom, alt)
    same_week = cut + pd.Timedelta(days=7)
    a = engine.oos[engine.oos["date"] < same_week].set_index("i")
    b = eng2.oos[eng2.oos["date"] < same_week].set_index("i")
    assert len(a) > 100 and a.index.equals(b.index) and (a["date"] >= cut).sum() >= 6
    np.testing.assert_allclose(a["lam"], b["lam"], rtol=1e-9)
    np.testing.assert_allclose(a["nu"], b["nu"], rtol=1e-9)
    after = engine.oos["date"] >= same_week
    assert not np.allclose(engine.oos.loc[after, "lam"].to_numpy(), eng2.oos.loc[after.to_numpy(), "lam"].to_numpy())


def test_too_few_cup_matches_are_not_validated(w):
    from bahis_tahmin.kupa.motor import DOGRULANMADI, CupEngine

    dom, cups = w
    eng = CupEngine()
    eng.train(dom, cups[cups.index % 6 == 0])
    assert eng.trained and eng.status["UEFA"] == DOGRULANMADI
    assert "örneklem dışı maç sayısı az" in eng.report.groups["UEFA"]["neden"]


def test_prediction_is_coherent_and_neutral_site_removes_home_advantage(engine):
    p = engine.predict("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "21:00")
    n = engine.predict("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "21:00",
                       neutral=True)
    r = engine.predict("UCL", AK, HK, "Galatasaray", "Arsenal", "Türkiye", "İngiltere", pd.Timestamp(CUP_DAY), "21:00")
    assert p.league == "UCL" and p.info["kupa"] and p.p_market is None and p.state_digest == engine.digest
    assert abs(sum(p.p_final) - 1) < 1e-9 and abs(p.markets["1X"] - p.p_final[0] - p.p_final[1]) < 1e-6
    assert abs(p.markets["O2.5"] + p.markets["U2.5"] - 1) < 1e-9 and abs(p.markets["BTTS_Y"] - p.btts_final) < 1e-6
    assert p.info["home_league"] == "E0" and p.info["away_league"] == "T1"
    assert p.p_final[0] > n.p_final[0] > r.p_final[2]  # iç saha avantajı; tarafsızda yok
    assert abs(n.info["lam_raw"] - r.info["nu_raw"]) < 1e-9  # ham modelde iç saha terimi yalnızca ev sahibinde
    # Tarafsız sahada takımların yeri değişince tahmin simetrik (kalibrasyonun iç saha terimi de uygulanmaz)
    n2 = engine.predict("UCL", AK, HK, "Galatasaray", "Arsenal", "Türkiye", "İngiltere", pd.Timestamp(CUP_DAY),
                        neutral=True)
    np.testing.assert_allclose(n2.p_final[::-1], n.p_final, atol=1e-12)
    # Ligi veride olmayan takım: kendi kupa geçmişiyle tahmin edilir; modelde olmayan takım: tahmin yok
    s = engine.predict("UEL", "Türkiye|Fenerbahce", SLAVIA_KEY, "Fenerbahce", "Slavia Praha", "Türkiye", "CZE",
                       pd.Timestamp(CUP_DAY))
    assert s is not None and s.info["away_league"] == "X:CZE"
    assert engine.predict("UCL", HK, "ESPN|1", "Arsenal", "Yeni", "İngiltere", "", pd.Timestamp(CUP_DAY)) is None


def test_engine_save_load_roundtrip(engine, tmp_path):
    from bahis_tahmin.kupa.motor import CupEngine

    engine.save(tmp_path / "kupa_engine.joblib")
    back = CupEngine.load(tmp_path / "kupa_engine.joblib")
    assert back is not None and back.digest == engine.digest and back.status == engine.status
    a = engine.predict("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY))
    b = back.predict("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY))
    np.testing.assert_allclose(a.p_final, b.p_final)
    assert CupEngine.load(tmp_path / "yok.joblib") is None


# =============================================================================================== uygunluk


@pytest.fixture
def cupctx(w, engine, tmp_path, monkeypatch):
    """Tam uygun SENTETİK kupa bağlamı: iki ligin tam takvimi, turnuvanın ESPN takvimi, sentetik haklar."""
    from uygunluk_yardim import register_synthetic_source

    from bahis_tahmin.kupa.uygunluk import CupContext

    register_synthetic_source(monkeypatch)
    dom, cups = w
    raw = tmp_path / "raw"
    write_cup_calendar(raw, "UCL", "2026/27", [{"id": "777", "date": str(CUP_DAY), "time": "21:00", "home_key": HK,
                                                 "away_key": AK, "status": "STATUS_SCHEDULED"}],
                       AS_OF - dt.timedelta(hours=3))

    def make(mode="standart", eng=engine, matches=dom, cup_rows=cups, dctx="lig"):
        store = SimpleNamespace(matches=matches, cup_matches=cup_rows, raw_dir=raw, meta={})
        lctx = league_context(matches, mode=mode) if dctx == "lig" else dctx
        return CupContext(store, eng, lctx, {}, {}, mode, verified=set())

    return make, raw


def _verdict(cctx, engine, home_key=HK, away_key=AK, source="espn", pid="espn:777", comp="UCL", day=CUP_DAY,
             as_of=AS_OF, names=("Arsenal", "Galatasaray"), countries=("İngiltere", "Türkiye")):
    p = engine.predict(comp, home_key, away_key, names[0], names[1], countries[0], countries[1], pd.Timestamp(day),
                       "21:00", False, source)
    e = cctx.evaluate(comp=comp, season="2026/27", date=pd.Timestamp(day), home=names[0], away=names[1],
                      home_key=home_key, away_key=away_key, home_country=countries[0], away_country=countries[1],
                      as_of=as_of, source=source, provider_id=pid, prediction=p)["1X2"]
    return p, e


@pytest.mark.parametrize("mode", ["standart", "siki"])
def test_eligibility_positive_control(cupctx, engine, mode):
    make, _ = cupctx
    _, e = _verdict(make(mode), engine)
    assert e.reasons == () and e.forecast_ok and e.bet_ok and e.freshness == "VERIFIED_CURRENT"
    assert e.data_scope["kupa"] and e.state_scope["tur"] == "kupa" and e.state_scope["durum_ozeti"] == engine.digest
    assert set(e.data_scope["takimlar"]) == {"Arsenal", "Galatasaray"}


def test_outside_league_team_is_never_a_bet_candidate(cupctx, engine):
    make, raw = cupctx
    write_cup_calendar(raw, "UEL", "2026/27", [{"id": "5", "date": str(CUP_DAY), "time": "21:00",
                                                 "home_key": "Türkiye|Fenerbahce", "away_key": SLAVIA_KEY,
                                                 "status": "STATUS_SCHEDULED"}], AS_OF - dt.timedelta(hours=3))
    for mode, forecast in (("standart", True), ("siki", False)):
        _, e = _verdict(make(mode), engine, "Türkiye|Fenerbahce", SLAVIA_KEY, pid="espn:5", comp="UEL",
                        names=("Fenerbahce", "Slavia Praha"), countries=("Türkiye", "CZE"))
        assert "KUPA_TAKIM_LIGI_VERIDE_YOK" in e.reasons and not e.bet_ok
        assert e.forecast_ok is forecast  # sıkı modda güncellik kanıtı olmadan tahmin de gösterilmez


def test_unknown_or_thin_team_gets_no_prediction(cupctx, engine, w):
    from bahis_tahmin.kupa.uygunluk import gated_cup_predictions
    from bahis_tahmin.kupa.veri import CUP_FIXTURE_COLUMNS

    make, _ = cupctx
    cctx = make()
    fx = pd.DataFrame([{"comp": "UCL", "season": "2026/27", "stage": "", "date": pd.Timestamp(CUP_DAY), "time": "21:00",
                        "home": "Arsenal", "away": "Yeni Takım", "home_key": HK, "away_key": "ESPN|4242",
                        "home_country": "İngiltere", "away_country": "", "home_mapped": True, "away_mapped": False,
                        "neutral": False, "source": "espn", "provider_id": "espn:778"}], columns=CUP_FIXTURE_COLUMNS)
    preds, missing = gated_cup_predictions(engine, cctx, fx, AS_OF)
    assert preds == [] and len(missing) == 1
    v = missing[0].first()
    assert {"KUPA_TAKIM_VERISI_YOK", "TAKIM_ESLESMESI_DOGRULANAMADI"} <= set(v.reasons) and not v.forecast_ok
    # 5'ten az maç (son 365 gün): tahmin yok — takımın maçları depodan silinir
    dom, cups = w
    thin = cups[~((cups["home_key"] == AK) | (cups["away_key"] == AK))]
    dthin = dom[~((dom["league"] == "T1") & ((dom["home"] == "Galatasaray") | (dom["away"] == "Galatasaray"))
                  & (dom["date"] > pd.Timestamp("2025-10-01")))]
    _, e = _verdict(make(matches=dthin, cup_rows=thin), engine)
    assert "KUPA_TAKIM_VERISI_YOK" in e.reasons and not e.forecast_ok


def test_unvalidated_model_group_blocks_bets_but_shows_forecast(cupctx, engine):
    from bahis_tahmin.kupa.motor import DOGRULANMADI

    make, _ = cupctx
    eng = copy.copy(engine)
    eng.status = dict(engine.status, UEFA=DOGRULANMADI)
    _, e = _verdict(make(eng=eng), eng)
    assert e.reasons == ("KUPA_MODEL_DOGRULANMADI",) and e.forecast_ok and not e.bet_ok


def test_calendar_and_fixture_identity_checks(cupctx, engine):
    make, raw = cupctx
    # ESPN fikstürünün numarası/takımları takvimde yeniden bulunmalı
    _, e = _verdict(make(), engine, pid="espn:999999")
    assert "TAKIM_ESLESMESI_DOGRULANAMADI" in e.reasons and not e.forecast_ok
    # Maç Analizi (elle): takımlar modelin listesinden seçilir, kimlik denetimi seçimin kendisidir
    _, e = _verdict(make(), engine, source="manuel", pid="")
    assert e.reasons == () and e.bet_ok
    # Turnuvanın takvimi yok: standart modda uyarı değil; sıkı modda güncellik kanıtı yok -> tahmin yok
    (raw / "espn_kupa" / "2026-27" / "UCL.json").unlink()
    _, e = _verdict(make("standart"), engine, source="manuel", pid="")
    assert "KUPA_TAKVIMI_YOK" in e.reasons and e.forecast_ok
    _, e = _verdict(make("siki"), engine, source="manuel", pid="")
    assert "KUPA_TAKVIMI_YOK" in e.reasons and not e.forecast_ok and e.freshness != "VERIFIED_CURRENT"


def test_cup_calendar_result_missing_from_store_is_flagged(cupctx, engine, w):
    make, raw = cupctx
    dom, cups = w
    last = cups[(cups["home_key"] == HK) | (cups["away_key"] == HK)].iloc[-1]
    drop = cups.drop(index=last.name)
    write_cup_calendar(raw, last["comp"], "2025/26", [{"id": "1", "date": str(last["date"].date()), "time": "21:00",
                                                        "home_key": last["home_key"], "away_key": last["away_key"],
                                                        "status": "STATUS_FULL_TIME", "ft": [1, 0]}],
                       AS_OF - dt.timedelta(hours=3))
    _, e = _verdict(make(cup_rows=drop), engine)
    assert "DEPODA_EKSIK_MAC" in e.reasons and not e.bet_ok
    _, e = _verdict(make(cup_rows=cups), engine)  # satır depoda: sorun yok
    assert "DEPODA_EKSIK_MAC" not in e.reasons


def test_cup_rows_without_documented_rights_block_everything(engine, w, tmp_path):
    from bahis_tahmin.kupa.uygunluk import CupContext

    dom, cups = w  # "sentetik" etiketi kaynak kaydında yok (bu testte kaydedilmedi)
    store = SimpleNamespace(matches=dom, cup_matches=cups, raw_dir=tmp_path, meta={})
    cctx = CupContext(store, engine, league_context(dom), {}, {}, "standart", verified=set())
    _, e = _verdict(cctx, engine, source="manuel", pid="")
    assert not e.forecast_ok and any(r.startswith("KAYNAK_HAKKI") for r in e.reasons)


def test_past_match_and_state_after_decision_time(cupctx, engine):
    make, _ = cupctx
    _, e = _verdict(make(), engine, source="manuel", pid="", day=dt.date(2026, 9, 1))
    assert "MAC_GECMISTE" in e.reasons and not e.forecast_ok
    # Model durumu karar anından sonra oluştu ve karar anından sonraki maçları içeriyor: kullanılamaz
    early = dt.datetime(2026, 3, 1, 12, tzinfo=UTC)
    _, e = _verdict(make(), engine, source="manuel", pid="", day=dt.date(2026, 3, 3), as_of=early)
    assert "DURUM_KARAR_ANINDAN_SONRA" in e.reasons and not e.forecast_ok


# =============================================================================================== ayarlar, çekirdek


def test_settings_default_cups_follow_leagues_and_drop_unknown_codes(tmp_home):
    from bahis_tahmin.config import Settings
    from bahis_tahmin.kupa.turnuvalar import default_for_leagues

    s = Settings.load()
    assert s.kupalar == default_for_leagues(s.leagues) and "UCL" in s.kupalar
    s.leagues = ["T1"]
    s.kupalar = None
    s.validate()
    assert "TRC" in s.kupalar and "FAC" not in s.kupalar and "UECL" in s.kupalar
    s.kupalar = ["UCL", "YOK", "FAC"]
    s.validate()
    assert s.kupalar == ["UCL", "FAC"]
    s.kupalar = []
    s.save()
    assert Settings.load().kupalar == []  # boş seçim korunur (varsayılana dönmez)


def test_next_cup_engine_rule():
    from bahis_tahmin.core import next_cup_engine

    s = SimpleNamespace(kupalar=["UCL"])
    assert next_cup_engine("eski", None, s) == "eski" and next_cup_engine("eski", "yeni", s) == "yeni"
    assert next_cup_engine("eski", "yeni", SimpleNamespace(kupalar=[])) is None


# =============================================================================================== web


def _web(tmp_home, w, engine, monkeypatch):
    pytest.importorskip("flask")
    from uygunluk_yardim import register_synthetic_source

    from bahis_tahmin.data.store import DataStore
    from bahis_tahmin.kupa.veri import CUP_FIXTURE_COLUMNS
    from bahis_tahmin.web import create_app

    register_synthetic_source(monkeypatch)
    dom, cups = w
    app = create_app(load=False)
    app.config["TESTING"] = True
    core = app.extensions["bahis_tahmin"].core
    st = DataStore(core.home)
    st.matches, st.cup_matches = dom, cups
    st.cup_fixtures = pd.DataFrame([
        {"comp": "UCL", "season": "2026/27", "stage": "", "date": pd.Timestamp(CUP_DAY), "time": "21:00",
         "home": "Arsenal", "away": "Galatasaray", "home_key": HK, "away_key": AK, "home_country": "İngiltere",
         "away_country": "Türkiye", "home_mapped": True, "away_mapped": True, "neutral": False, "source": "espn",
         "provider_id": "espn:777"}], columns=CUP_FIXTURE_COLUMNS)
    write_cup_calendar(st.raw_dir, "UCL", "2026/27", [{"id": "777", "date": str(CUP_DAY), "time": "21:00",
                                                        "home_key": HK, "away_key": AK,
                                                        "status": "STATUS_SCHEDULED"}], AS_OF - dt.timedelta(hours=3))
    ctx = league_context(dom)
    core.store, core.cup_engine, core.loaded = st, engine, True
    core.clock = lambda: AS_OF
    core.eligibility_context = lambda eng: ctx
    core.refresh_predictions()
    c = app.test_client()
    c.environ_base.update({"HTTP_HOST": "127.0.0.1:8765"})
    return app, core, c


def test_web_lists_cup_match_with_detail_analysis_ratings_and_data(tmp_home, w, engine, monkeypatch):
    app, core, c = _web(tmp_home, w, engine, monkeypatch)
    assert [p.league for p in core.predictions] == ["UCL"] and not core.predictions[0].data_block(AS_OF)
    html = c.get("/tahminler?lig=@kupa").get_data(as_text=True)
    assert "Arsenal" in html and "Galatasaray" in html and "Şampiyonlar Ligi" in html
    key = re.search(r'href="/mac\?k=([^"&]+)', html).group(1)
    d = c.get(f"/mac?k={key}").get_data(as_text=True)
    assert "Model doğrulaması (UEFA turnuvaları (elemeler dahil)): doğrulandı" in d
    assert "Ortak ölçekte güç" in d and "son maçlar (lig + kupa)" in d
    assert "Bu maç için piyasa oranı yok" not in d  # lig maçlarının genel notu kupada gösterilmez
    # Lig filtresi kupa maçını göstermez
    assert "Galatasaray" not in c.get("/tahminler?lig=T1").get_data(as_text=True)
    g = c.get("/guc?lig=@avrupa").get_data(as_text=True)
    tbl = g[g.index("Liglerin gücü"):]
    assert tbl.index("Premier League") < tbl.index("Süper Lig")
    o = c.get("/en-olasi").get_data(as_text=True)
    assert "Arsenal - Galatasaray" in o and "Kupa modelinde aynı eşikte geçmişte gerçekleşme" in o
    v = c.get("/veri").get_data(as_text=True)
    assert 'name="kupa_UCL"' in v and "Kupa modeli doğrulaması" in v and "doğrulandı" in v
    tok = re.search(r'data-csrf="([^"]+)"', c.get("/analiz?mod=kupa").get_data(as_text=True)).group(1)
    r = c.post("/analiz", data={"csrf": tok, "mod": "kupa", "turnuva": "UCL", "ev_k": AK, "dep_k": HK,
                                "tarih": str(CUP_DAY), "o_1": "6.5", "o_X": "4.2", "o_2": "1.5"})
    t = r.get_data(as_text=True)
    assert r.status_code == 200 and "Galatasaray" in t and "Arsenal" in t and "Beklenen değer" in t
    r = c.post("/analiz", data={"csrf": tok, "mod": "kupa", "turnuva": "UCL", "ev_k": AK, "dep_k": AK})
    assert "iki farklı takım" in r.get_data(as_text=True)


def test_web_data_page_saves_cup_selection(tmp_home, w, engine, monkeypatch):
    from bahis_tahmin.web import state as W

    app, core, c = _web(tmp_home, w, engine, monkeypatch)
    called = {}
    monkeypatch.setattr(W.WebState, "start_update", lambda self, force=False: called.setdefault("ok", True))
    monkeypatch.setattr(W, "needs_consent", lambda s: False, raising=False)
    import bahis_tahmin.web.views as V

    monkeypatch.setattr(V, "needs_consent", lambda s: False)
    tok = re.search(r'data-csrf="([^"]+)"', c.get("/veri").get_data(as_text=True)).group(1)
    c.post("/veri/guncelle", data={"csrf": tok, "kaydet": "1", "lig_T1": "1", "kupa_UCL": "1", "kupa_TRC": "1",
                                   "kupa_YOK": "1"})
    assert core.settings.kupalar == ["UCL", "TRC"] and called.get("ok")
    from bahis_tahmin.config import Settings

    assert Settings.load().kupalar == ["UCL", "TRC"]


# =============================================================================================== CLI


def test_cli_cup_commands(tmp_home, w, engine, monkeypatch, capsys):
    from uygunluk_yardim import register_synthetic_source

    from bahis_tahmin.cli import _parse_cups, main
    from bahis_tahmin.data.store import DataStore

    assert main(["kupa-turnuvalar"]) == 0
    out = capsys.readouterr().out
    assert "UCL" in out and "Şampiyonlar Ligi" in out and "(kod doğrulanmadı)" in out
    assert main(["kupa-tahmin"]) == 2  # kupa modeli yok
    assert main(["kupa-rapor"]) == 0 and "Kupa verisi yok" in capsys.readouterr().out
    assert _parse_cups("varsayilan", ["T1"])[:7] == ["UCL", "UCLQ", "UEL", "UELQ", "UECL", "UECLQ", "USC"]
    assert _parse_cups("yok", ["T1"]) == [] and _parse_cups("ucl, fac", []) == ["UCL", "FAC"]
    assert _parse_cups("XYZ", []) is None
    dom, cups = w
    st = DataStore(tmp_home)
    st.matches, st.cup_matches = dom, cups
    st.save()
    assert main(["kupa-egit"]) == 3  # "sentetik" kaynağın hakkı belgeli değil: eğitilmez
    register_synthetic_source(monkeypatch)
    capsys.readouterr()
    assert main(["kupa-egit"]) == 0
    out = capsys.readouterr().out
    assert "UEFA turnuvaları (elemeler dahil)" in out and "doğrulandı" in out
    assert (Path(tmp_home) / "kupa_engine.joblib").exists()
    assert main(["kupa-rapor"]) == 0 and "Şampiyonlar Ligi" in capsys.readouterr().out


# =============================================================================================== masaüstü


def test_desktop_cup_views(tmp_home, w, engine, monkeypatch):
    import os
    import sys

    if sys.platform != "win32" and not os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from uygunluk_yardim import register_synthetic_source

    from bahis_tahmin.data.store import DataStore
    from bahis_tahmin.kupa.veri import CUP_FIXTURE_COLUMNS
    from bahis_tahmin.ui.main_window import MainWindow
    from bahis_tahmin.ui.match_view import MatchDialog
    from bahis_tahmin.ui.pages.data import DataPage
    from bahis_tahmin.ui.pages.likely import LikelyPage
    from bahis_tahmin.ui.pages.match import MatchPage
    from bahis_tahmin.ui.pages.ratings import AVRUPA, RatingsPage
    from bahis_tahmin.ui.theme import apply_theme

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    apply_theme(app)
    register_synthetic_source(monkeypatch)
    dom, cups = w
    win = MainWindow()
    ctl = win.ctl
    st = DataStore(tmp_home)
    st.matches, st.cup_matches = dom, cups
    st.cup_fixtures = pd.DataFrame([
        {"comp": "UCL", "season": "2026/27", "stage": "", "date": pd.Timestamp(CUP_DAY), "time": "21:00",
         "home": "Arsenal", "away": "Galatasaray", "home_key": HK, "away_key": AK, "home_country": "İngiltere",
         "away_country": "Türkiye", "home_mapped": True, "away_mapped": True, "neutral": False, "source": "espn",
         "provider_id": "espn:777"}], columns=CUP_FIXTURE_COLUMNS)
    write_cup_calendar(st.raw_dir, "UCL", "2026/27", [{"id": "777", "date": str(CUP_DAY), "time": "21:00",
                                                        "home_key": HK, "away_key": AK,
                                                        "status": "STATUS_SCHEDULED"}], AS_OF - dt.timedelta(hours=3))
    ctx = league_context(dom)
    ctl.store, ctl.cup_engine = st, engine
    ctl.clock = lambda: AS_OF
    ctl.eligibility_context = lambda eng: ctx
    ctl.dataChanged.emit()
    ctl.modelChanged.emit()
    ctl.refresh_predictions()
    try:
        cup = [p for p in ctl.predictions if p.league == "UCL"]
        assert len(cup) == 1 and not cup[0].data_block(AS_OF)
        dlg = MatchDialog(ctl, cup[0])
        assert "doğrulandı" in dlg.detail.note.text() and dlg.detail.mk_model.rowCount() == 14
        assert dlg.detail.form_home.rowCount() == 8 and "lig + kupa" in dlg.detail._form_titles[0].text()
        dlg.close()
        mp = win.page(MatchPage)
        mp.cb_mode.setCurrentIndex(mp.cb_mode.findData("kupa"))
        assert mp.lbl_league.text() == "Turnuva" and mp.chk_neutral.isVisibleTo(mp) and mp.btn.isEnabled()
        mp.cb_home.setCurrentIndex(mp.cb_home.findData(AK))
        mp.cb_away.setCurrentIndex(mp.cb_away.findData(HK))
        assert mp.cb_home.currentData() == AK
        mp.odds["1"].setValue(6.5)
        mp.analyze()
        p = mp.detail.pred
        assert p is not None and p.home == "Galatasaray" and p.info["kupa"] and p.eligibility is not None
        assert p.odds.get("1") == 6.5 and mp.detail.mk_model.rowCount() == 14
        mp.cb_mode.setCurrentIndex(mp.cb_mode.findData("lig"))
        assert mp.lbl_league.text() == "Lig"
        rp = win.page(RatingsPage)
        rp.cb_league.setCurrentIndex(rp.cb_league.findData(AVRUPA))
        assert rp.cup_box.isVisibleTo(rp) and not rp.tabs.isVisibleTo(rp)
        assert rp.cl_model.rowCount() == 2 and rp.ct_model.rowCount() > 10
        assert "eğitilmedi" not in rp.cup_note.text()
        lp = win.page(LikelyPage)
        lp.refresh()
        assert "Arsenal - Galatasaray" in set(lp.model.frame["match"])
        assert lp.cup_note.text().startswith("Kupa ve Avrupa maçları ayrı modelden")
        dp = win.page(DataPage)
        assert dp.cup_model.rowCount() == 2 and dp.rep_model.rowCount() >= 3
        dp._check_cups({"UCL", "FAC"})
        monkeypatch.setattr(ctl, "needs_consent", lambda: False)
        monkeypatch.setattr(ctl, "update_and_train", lambda force=False: True)
        dp._apply()
        assert ctl.settings.kupalar == ["UCL", "FAC"]
    finally:
        win.close()

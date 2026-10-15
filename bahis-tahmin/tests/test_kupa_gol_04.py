"""KUPA-GOL-04: maç sonu 0-0 biten kupa maçları gol pazarı ölçümünde ve sonuçlandırmada İY 0-0.

openfootball dosyaları 0-0 maçlarda devre skorunu neredeyse hiç yazmaz (gerçek veride 441 maçın 440'ı). v2 kuralında bu
maçlar "İY skoru yok" diye ölçümden düşüyor, ölçülen örneklem gol yönünde seçilmiş oluyordu. Yalnızca SENTETİK veri
(``kupa_yardim``) ve elle kurulmuş satırlar; ağ isteği yok."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from kupa_yardim import CUP_DAY, world

HK, AK = "İngiltere|Arsenal", "Türkiye|Galatasaray"
A, B, C = "BTTS_BOTH_HALVES_YES", "FT_OVER_3_5", "FH_OVER_1_5"
NAN = float("nan")


@pytest.fixture(scope="module")
def w():
    return world()


@pytest.fixture(scope="module")
def engines(w):
    """(İY skoru 0-0'da yazılmış, İY skoru 0-0'da yazılmamış — openfootball gibi) iki motor."""
    from bahis_tahmin.kupa.motor import CupEngine

    dom, cups = w
    nil = (cups["fthg"] == 0) & (cups["ftag"] == 0)
    assert nil.sum() > 50 and cups.loc[nil, ["hthg", "htag"]].notna().all().all()
    blank = cups.copy()
    blank.loc[nil, ["hthg", "htag"]] = NAN
    e1, e2 = CupEngine(), CupEngine()
    e1.train(dom, cups)
    e2.train(dom, blank)
    return e1, e2, blank


def _frame(rows):
    return pd.DataFrame(rows, columns=["fthg", "ftag", "hthg", "htag"]).astype(float)


def test_ht_scores_fill_only_goalless_matches_without_any_half_time():
    from bahis_tahmin.kupa.gol import ht_mask, ht_scores, labels

    df = _frame([[0, 0, NAN, NAN], [0, 0, 0, 0], [1, 0, NAN, NAN], [0, 0, NAN, 0], [2, 1, 1, 0], [0, 0, 1, 0],
                 [0, 2, NAN, NAN]])
    before = df.copy()
    hh, ha = ht_scores(df)
    np.testing.assert_array_equal(hh, [0, 0, NAN, NAN, 1, 1, NAN])
    np.testing.assert_array_equal(ha, [0, 0, NAN, 0, 0, 0, NAN])
    pd.testing.assert_frame_equal(df, before)  # ham satır değişmez
    # 0-0 ve İY yok: geçerli; golü olan maçta eksik İY tahmin edilmez; tek tarafı yazılmış kayıt tamamlanmaz;
    # İY'si maç sonunu aşan çelişkili kayıt geçersiz kalır
    np.testing.assert_array_equal(ht_mask(df), [True, True, False, False, True, False, False])
    lab = labels(df)
    for k in "ABC":
        assert lab[k][0] == lab[k][1] == 0.0


def test_first_half_share_is_unchanged_by_goalless_matches():
    from bahis_tahmin.kupa.gol import first_half_share

    base = _frame([[2, 1, 1, 0], [3, 0, 2, 0], [1, 1, 0, 1]])
    more = pd.concat([base, _frame([[0, 0, NAN, NAN]] * 5 + [[0, 0, 0, 0]] * 3)], ignore_index=True)
    assert first_half_share(base) == first_half_share(more)


def test_parser_keeps_source_blank_and_measurement_uses_implied_zero():
    """Okuyucu kaynağı olduğu gibi okur (0-0'da İY yok); ölçüm İY 0-0 kullanır."""
    from bahis_tahmin.kupa.gol import ht_mask, labels
    from bahis_tahmin.kupa.openfootball import parse_cup_txt

    txt = """= Coppa Italia 2023/24
▪ Round 1
Sat Aug 12 2023
  18:00  Genoa CFC                0-0  Modena FC
         Millwall FC              v Gillingham FC            3-1 pen. (0-0)
         US Lecce                 1-0  Parma Calcio
"""
    pr = parse_cup_txt(txt.encode("utf-8"), "2023-24", default_cc="ITA")
    sc = {r["team1"]: r["score"] for r in pr.matches}
    assert sc["Genoa CFC"] == {"ft": [0, 0]} and sc["Millwall FC"] == {"ft": [0, 0], "pen": [3, 1]}
    df = _frame([[s["ft"][0], s["ft"][1], *(s.get("ht") or [NAN, NAN])] for s in sc.values()])
    np.testing.assert_array_equal(ht_mask(df), [True, True, False])
    assert all(labels(df)[k][:2].sum() == 0 for k in "ABC")


def test_measurement_with_blank_goalless_half_time_equals_written_one(engines):
    """Kaynak 0-0 maçlarda devre skorunu yazmasa da gol pazarı ölçümü, taban oranları, ilk yarı payı, turnuva İY oranı
    ve tahminler, devre skoru yazılmış gibi aynıdır."""
    e1, e2, _ = engines
    g1, g2 = e1.goal, e2.goal
    assert g1.n_ht == g2.n_ht and g1.share == g2.share and g1.share_by_group == g2.share_by_group
    assert g1.comp_ht_share == g2.comp_ht_share and all(v == 1.0 for v in g2.comp_ht_share.values())
    assert g1.base == g2.base and g1.validated == g2.validated
    a, b = g1.oos.set_index("i"), g2.oos.set_index("i")
    assert a.index.equals(b.index) and len(a) == len(e1.oos)  # ölçülmüş bütün kupa maçları
    for col in ("pA", "pB", "pC", "bA", "bB", "bC", "yA", "yB", "yC"):
        np.testing.assert_allclose(a[col], b[col], rtol=1e-12)
    for vg in g1.results:
        for k in (A, B, C):
            r1, r2 = g1.results[vg][k], g2.results[vg][k]
            keys = ("n", "pozitif", "log_loss", "ll_taban", "statu")
            assert {x: r1.get(x) for x in keys} == {x: r2.get(x) for x in keys}
    assert g2.results["UEFA"][B]["n"] == len(e2.oos)
    args = ("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "21:00", False,
            "espn")
    assert e1.predict_goals(*args).probs == e2.predict_goals(*args).probs


def test_excluding_goalless_matches_would_select_a_goal_rich_sample(engines):
    """Eski kural (yalnızca yazılmış İY): 0-0 maçlar düşer, her pazarın gerçekleşme oranı yapay olarak yükselir."""
    from bahis_tahmin.kupa.gol import ht_mask, labels

    _, e2, blank = engines
    old = blank[["hthg", "htag"]].notna().all(axis=1).to_numpy()
    new = ht_mask(blank)
    lab = labels(blank)
    assert new.sum() > old.sum() and not (old & ~new).any()
    for k in "ABC":
        assert lab[k][old].mean() > lab[k][new].mean()
    assert len(e2.goal.oos) == len(e2.oos)


def test_settlement_of_goalless_cup_match_and_upgrade_from_unknown(tmp_path):
    from bahis_tahmin.goals.ledger import Ledger
    from bahis_tahmin.goals.service import settle_pending

    led = Ledger(tmp_path / "gol.sqlite")
    base = dict(decision_time="2026-09-14T12:00:00+00:00", model_version="m", feature_version="f",
                data_cutoff="2026-09-13", p=0.4, decision_status="VALUE_CANDIDATE", reasons=[], stake_units=1.0,
                strategy_version="s")
    e0, e1, e2 = ("UCL|2026-09-16|Arsenal|Galatasaray", "UCL|2026-09-16|Chelsea|Fenerbahce",
                  "UCL|2026-09-16|Liverpool|Besiktas")
    ids = {(e, k): led.record_prediction(dict(base, event_id=e, market_key=k))
           for e in (e0, e1, e2) for k in (A, C, "FH_UNDER_1_5", B)}
    led.record_outcome(ids[(e0, C)], "UNKNOWN", "UNKNOWN", "eski sürüm")  # düzeltmeden önce yazılmış sonuç
    m = pd.DataFrame([
        {"league": "UCL", "date": pd.Timestamp(CUP_DAY), "home": "Arsenal", "away": "Galatasaray", "fthg": 0,
         "ftag": 0, "hthg": NAN, "htag": NAN},
        {"league": "UCL", "date": pd.Timestamp(CUP_DAY), "home": "Chelsea", "away": "Fenerbahce", "fthg": 0,
         "ftag": 1, "hthg": NAN, "htag": NAN},
        {"league": "UCL", "date": pd.Timestamp(CUP_DAY), "home": "Liverpool", "away": "Besiktas", "fthg": 0,
         "ftag": 0, "hthg": NAN, "htag": 0.0}])
    settle_pending(led, m)
    out = {(r["event_id"], r["market_key"]): r["outcome"] for r in led.predictions()}
    # 0-0: İY de 0-0 → iki yarıda KG ve İY 1,5 Üst kaybeder, İY 1,5 Alt kazanır
    assert out[(e0, A)]["settlement"] == "LOSS" and out[(e0, C)]["settlement"] == "LOSS"
    assert out[(e0, "FH_UNDER_1_5")]["settlement"] == "WIN" and out[(e0, B)]["settlement"] == "LOSS"
    assert out[(e0, C)]["note"] == "sonuç verisi tamamlandı (önceki sonuç: UNKNOWN)"
    # Golü olan maçta eksik devre skoru tahmin edilmez: ilk yarı pazarları belirsiz, maç sonu pazarı sonuçlanır
    assert out[(e1, A)]["settlement"] == "UNKNOWN" and out[(e1, C)]["settlement"] == "UNKNOWN"
    assert out[(e1, B)]["settlement"] == "LOSS"
    # Tek tarafı yazılmış devre skoru tamamlanmaz (kayıt eksik/çelişkili olabilir)
    assert out[(e2, A)]["settlement"] == "UNKNOWN" and out[(e2, C)]["settlement"] == "UNKNOWN"
    settle_pending(led, m)  # ikinci çalıştırma yeni sonuç eklemez, zincir bozulmaz
    assert {(r["event_id"], r["market_key"]): r["outcome"] for r in led.predictions()} == out
    ok, _msg = led.verify_chain()
    assert ok
    led.close()


def test_versions():
    from bahis_tahmin.kupa.gol import GOAL_MODEL_VERSION, GOAL_RULE
    from bahis_tahmin.kupa.motor import CUP_ENGINE_VERSION

    assert GOAL_RULE.startswith("kupa-gol-dogrulama-v3:") and "0-0" in GOAL_RULE
    assert CUP_ENGINE_VERSION >= 5  # eski örneklemle ölçülmüş kayıtlı model yeniden eğitilir
    assert GOAL_MODEL_VERSION == "kupa-gol-v2"  # tahmin değişmedi (0-0 maçlar ilk yarı payını değiştirmez)

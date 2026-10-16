"""KUPA-ROV-07: kupa motorunda rövanş etkisi (kullanıcı kararıyla uygulandı). Yalnızca SENTETİK veri; ağ yok.

Rövanşın ev sahibinin ilk maç gol farkı d, x = d [−3, 3] aralığına kırpılmış: ev sahibi × e^(−βx), deplasman × e^(+βx).
Ölçümde β yalnızca önceki haftaların rövanşlarından; tahminde bütün örneklem dışı rövanşlardan."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kupa_yardim import CUP_DAY, world

ROOT = Path(__file__).resolve().parents[1]
HK, AK = "İngiltere|Arsenal", "Türkiye|Galatasaray"
MIN = 20


def _tool():
    spec = importlib.util.spec_from_file_location("kupa_rovans", ROOT / "tools" / "research" / "kupa_rovans.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _world_with_first_leg():
    """Sentetik dünya + CUP_DAY'den bir hafta önce oynanmış bir ilk maç (Galatasaray 3-0 Arsenal, son 16)."""
    dom, cups = world()
    first = cups.iloc[0].copy()
    first.update({"comp": "UCL", "season": "2026/27", "stage": "Round of 16",
                  "date": pd.Timestamp(CUP_DAY) - pd.Timedelta(days=7), "home": "Galatasaray", "away": "Arsenal",
                  "home_key": AK, "away_key": HK, "home_country": "Türkiye", "away_country": "İngiltere",
                  "fthg": 3, "ftag": 0, "hthg": 1.0, "htag": 0.0, "provider_id": "syn:ilk-mac"})
    return dom, pd.concat([cups, first.to_frame().T.astype(cups.dtypes.to_dict())], ignore_index=True)


@pytest.fixture(scope="module")
def engines():
    from bahis_tahmin.kupa import rovans as R
    from bahis_tahmin.kupa.motor import CupEngine

    dom, cups = _world_with_first_leg()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(R, "MIN_LEGS", MIN)  # sentetik dünyada rastlantısal eşleşmeler az: eşik küçültülür
        on, off = CupEngine(), CupEngine(rovans=False)
        on.train(dom, cups)
        off.train(dom, cups)
    return on, off, cups


# ------------------------------------------------------------------------------------------------ paket
def test_package_ties_are_the_research_tools_ties():
    from bahis_tahmin.kupa.rovans import ties

    tool = _tool()
    _, cups = world()
    c = cups.sort_values("date", kind="mergesort").reset_index(drop=True)
    a, b = tool.ties(c), ties(c)
    assert len(a) > 50 and a.equals(b)
    rng = np.random.default_rng(1)
    c2 = c.copy()
    c2["stage"] = rng.choice(["Group A", "Round of 16", "Playoffs", "League phase"], len(c2))
    c2.loc[c2.index[:40], "comp"] = "FAC"
    assert tool.ties(c2).equals(ties(c2))


def test_fit_beta_recovers_effect_and_standard_error():
    from bahis_tahmin.kupa.rovans import fit_beta

    rng = np.random.default_rng(3)
    n = 20000
    d = rng.integers(-4, 5, n).astype(float)
    lam, nu = rng.uniform(0.8, 2.2, n), rng.uniform(0.6, 1.8, n)
    x = np.clip(d, -3, 3)
    hg, ag = rng.poisson(lam * np.exp(-0.1 * x)), rng.poisson(nu * np.exp(0.1 * x))
    b, se = fit_beta(lam, nu, hg, ag, d)
    assert b == pytest.approx(0.1, abs=3 * se) and 0 < se < 0.01
    tool = _tool()  # araştırma aracının V1 kestirimiyle aynı
    frame = pd.DataFrame({"d": d, "lam_c": lam, "nu_c": nu, "hg": hg, "ag": ag})
    assert tool.fit(frame, "V1")[0] == pytest.approx(b, abs=1e-6)
    assert fit_beta([], [], [], [], [])[0] == 0.0

    def nll(beta):  # standart hata = 1/√(NLL'nin ikinci türevi), sayısal türevle
        return float(np.sum(lam * np.exp(-beta * x) + beta * x * hg) + np.sum(nu * np.exp(beta * x) - beta * x * ag))

    eps = 1e-3
    h = (nll(b + eps) - 2 * nll(b) + nll(b - eps)) / eps ** 2
    assert se == pytest.approx(1 / np.sqrt(h), rel=1e-4)


def test_factors_clip_and_nan():
    from bahis_tahmin.kupa.rovans import factors

    fh, fa = factors([-5.0, -1.0, 0.0, 2.0, np.nan], 0.1)
    assert fh.tolist() == pytest.approx(np.exp([0.3, 0.1, 0.0, -0.2, 0.0]).tolist())
    assert fa.tolist() == pytest.approx(np.exp([-0.3, -0.1, 0.0, 0.2, 0.0]).tolist())


def test_beta_series_uses_only_earlier_weeks():
    from bahis_tahmin.kupa.rovans import beta_series, fit_beta

    rng = np.random.default_rng(5)
    n = 600
    ev = pd.DataFrame({"week": np.repeat(np.arange(60) * 7, 10), "lam_b": rng.uniform(0.8, 2, n),
                       "nu_b": rng.uniform(0.6, 1.6, n), "hg": rng.poisson(1.4, n), "ag": rng.poisson(1.1, n),
                       "rovans_d": np.where(rng.random(n) < 0.5, rng.integers(-3, 4, n), np.nan).astype(float)})
    b = beta_series(ev, min_legs=40)
    leg = np.isfinite(ev["rovans_d"]).to_numpy()
    for i in (5, 35, 75, 200, 350, 599):  # 35: önceki haftalarda 40'tan az rövanş → β = 0
        past = leg & (ev["week"] < ev["week"].iloc[i]).to_numpy()
        exp = fit_beta(*(ev.loc[past, c] for c in ("lam_b", "nu_b", "hg", "ag", "rovans_d")))[0] \
            if past.sum() >= 40 else 0.0
        assert (b[i] == pytest.approx(exp, abs=1e-12)) if leg[i] else b[i] == 0.0
    # Sızıntı yok: bir haftadan sonraki sonuçlar değişse de o haftanın ve öncekilerin β'sı aynı
    alt = ev.copy()
    late = alt["week"] >= 300
    alt.loc[late, "hg"] = alt.loc[late, "hg"] + 3
    b2 = beta_series(alt, min_legs=40)
    upto = (ev["week"] <= 300).to_numpy()
    np.testing.assert_allclose(b[upto], b2[upto], rtol=0, atol=0)
    assert not np.allclose(b[~upto], b2[~upto])


def test_first_leg_rules():
    from bahis_tahmin.kupa.rovans import first_leg, results_table

    D = pd.Timestamp
    rows = [("UCL", "2025/26", "Round of 16", D("2026-02-10"), "A", "B", 2, 0),
            ("UCL", "2025/26", "Group A", D("2025-10-01"), "C", "D", 1, 0),
            ("FAC", "2025/26", "Round 3", D("2026-01-05"), "E", "F", 1, 1),
            ("UEL", "2024/25", "Playoffs", D("2026-02-10"), "G", "H", 1, 0),
            ("UCL", "2025/26", "Quarter-final", D("2026-03-20"), "X", "Y", 0, 0)]  # tahmin gününden sonra: kullanılmaz
    tab = results_table(pd.DataFrame([dict(zip(("comp", "season", "stage", "date", "home_key", "away_key", "fthg",
                                                  "ftag"), r)) for r in rows]))
    leg = first_leg(tab, "UCL", "2025/26", "Round of 16", "B", "A", D("2026-03-04"))
    assert leg == {"d": -2.0, "tarih": "2026-02-10", "skor": "2-0"}
    assert first_leg(tab, "UCL", "2025/26", None, "B", "A", D("2026-03-04"))["d"] == -2.0  # tur bilinmiyor
    assert first_leg(tab, "UCL", "2025/26", np.nan, "B", "A", D("2026-03-04"))["d"] == -2.0
    assert first_leg(tab, "UCL", "2025/26", "Round of 16", "A", "B", D("2026-03-04")) is None  # aynı yön
    assert first_leg(tab, "UCL", "2025/26", "Round of 16", "B", "A", D("2026-02-12")) is None  # 2 gün: aralık dışı
    assert first_leg(tab, "UCL", "2025/26", "Round of 16", "B", "A", D("2026-05-01")) is None  # 80 gün
    assert first_leg(tab, "UCL", "2025/26", "Group A", "B", "A", D("2026-03-04")) is None  # grup aşaması
    assert first_leg(tab, "UCL", "2025/26", None, "D", "C", D("2025-10-22")) is None  # ilk maç grup, tur bilinmiyor
    assert first_leg(tab, "UCL", "2025/26", "Group A", "D", "C", D("2025-10-22")) is None
    assert first_leg(tab, "UCL", "2025/26", "Round 1", "D", "C", D("2025-10-22"))["d"] == -1.0  # tur eleme
    assert first_leg(tab, "FAC", "2025/26", "Round 3", "F", "E", D("2026-01-15")) is None  # FA Cup tekrar maçı
    assert first_leg(tab, "UEL", "2025/26", "Playoffs", "H", "G", D("2026-02-17")) is None  # başka sezon
    assert first_leg(None, "UCL", "2025/26", None, "B", "A", D("2026-03-04")) is None


# ------------------------------------------------------------------------------------------------ motor
def test_measurement_applies_past_week_factors(engines):
    from bahis_tahmin.kupa.rovans import beta_series, factors, fit_beta

    on, off, _ = engines
    ev = on.oos
    legs = np.isfinite(ev["rovans_d"]).to_numpy()
    assert legs.sum() >= MIN and (ev.loc[legs, "rovans_beta"] != 0).any()
    np.testing.assert_allclose(ev["rovans_beta"], beta_series(ev, min_legs=MIN), rtol=0, atol=1e-15)
    fh, fa = factors(ev["rovans_d"], ev["rovans_beta"])
    np.testing.assert_allclose(ev["lam_c"], ev["lam_b"] * fh, rtol=1e-12)
    np.testing.assert_allclose(ev["nu_c"], ev["nu_b"] * fa, rtol=1e-12)
    np.testing.assert_allclose(ev.loc[~legs, "lam_c"], ev.loc[~legs, "lam_b"], rtol=0)
    # Rövanşsız beklentiler etkisiz motorla aynı; etkisiz motorda çarpan yok
    b = off.oos.set_index("i")
    a = ev.set_index("i")
    np.testing.assert_allclose(a["lam_b"], b.loc[a.index, "lam_c"], rtol=1e-12)
    assert np.isnan(off.oos["rovans_d"]).all() and off.rovans["beta"] == 0.0
    # Tahminde kullanılan β: bütün örneklem dışı rövanşlardan
    exp, se = fit_beta(*(ev.loc[legs, c] for c in ("lam_b", "nu_b", "hg", "ag", "rovans_d")))
    assert on.rovans["beta"] == pytest.approx(exp, abs=1e-12) and on.rovans["n"] == int(legs.sum())
    # Ölçüm (1X2) çarpanlı beklentilerden
    from bahis_tahmin.kupa.motor import probs_from_rates

    P, _, _ = probs_from_rates(ev["lam_c"], ev["nu_c"])
    np.testing.assert_allclose(ev[["ph", "pd", "pa"]].to_numpy(), P, rtol=1e-12)


def test_prediction_applies_the_first_leg(engines):
    on, off, _ = engines
    e0 = copy.copy(on)
    e0.rovans_on = False  # aynı motor, etki kapalı
    args = (HK, AK, "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "UCL", False)
    r = on.rates(*args, stage="Round of 16", season="2026/27")
    r0 = e0.rates(*args, stage="Round of 16", season="2026/27")
    rv = r["rovans"]
    beta = on.rovans["beta"]
    assert rv["d"] == -3.0 and rv["skor"] == "3-0" and rv["beta"] == beta and r0["rovans"] is None
    assert r["lam"] == pytest.approx(r0["lam"] * np.exp(3 * beta), rel=1e-12)
    assert r["nu"] == pytest.approx(r0["nu"] * np.exp(-3 * beta), rel=1e-12)
    # Tur ve sezon verilmezse (elle seçim) aynı ilk maç bulunur; başka maçta çarpan yok
    assert on.rates(*args)["rovans"]["d"] == -3.0
    assert on.rates(AK, HK, "Türkiye", "İngiltere", pd.Timestamp(CUP_DAY), "UCL", False)["rovans"] is None
    # 1X2 ve gol pazarları aynı çarpanı taşır; belirsizlik aralığı da
    p = on.predict("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "21:00",
                   stage="Round of 16", season="2026/27")
    assert p.info["rovans"]["d"] == -3.0 and p.info["lam"] == pytest.approx(r["lam"])
    g = on.predict_goals("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY),
                         "21:00", False, "espn", stage="Round of 16", season="2026/27")
    g0 = e0.predict_goals("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY),
                          "21:00", False, "espn", stage="Round of 16", season="2026/27")
    assert g.info["rovans"]["d"] == -3.0 and g0.info["rovans"] is None
    if beta != 0:
        assert g.intervals["FT_OVER_3_5"] != g0.intervals["FT_OVER_3_5"]
    # Belirsizlik aralığının çekilişleri de iki çarpanı taşır: büyük β ile nokta tahmin aralığın içinde kalır
    big = copy.copy(on)
    big.rovans = {**on.rovans, "beta": 0.5}
    gb = big.predict_goals("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY),
                           "21:00", False, "espn", stage="Round of 16", season="2026/27")
    g0b = e0.predict_goals("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY),
                           "21:00", False, "espn", stage="Round of 16", season="2026/27")
    from bahis_tahmin.goals.markets import PRIMARY_YES, SHORT

    assert gb.probs["B"] > g0b.probs["B"] + 0.05  # 3,5 Üst; ev ×e^1,5, deplasman ×e^−1,5: toplam artar
    for k in PRIMARY_YES:
        lo, hi = gb.intervals[k]
        assert lo <= gb.probs[SHORT[k]] <= hi, k
    # Piyasa düzeyli yeniden tahmin (ORAN-04) rövanşı korur
    from bahis_tahmin.goals.piyasa import from_odds

    q = on.market_prediction(g, from_odds(1.8, 2.0, "x"))
    assert q.info["rovans"]["d"] == -3.0


def test_cards_versions_and_roundtrip(engines, tmp_path):
    from bahis_tahmin.kupa.gorunum import goal_model_card, notes, rovans_line
    from bahis_tahmin.kupa.motor import CUP_ENGINE_VERSION, MODEL_VERSION, CupEngine

    on, off, _ = engines
    assert CUP_ENGINE_VERSION == 7 and MODEL_VERSION == "kupa-model-v4"
    p = on.predict("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "21:00",
                   stage="Round of 16", season="2026/27")
    assert any("rövanş" in n for n in notes(p, on))
    g = on.predict_goals("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY),
                         "21:00", False, "espn", stage="Round of 16", season="2026/27")
    card = goal_model_card(g, on)["version"]
    assert "rövanş: ilk maç" in card and "kullanıcı kararıyla" in card
    assert "Rövanş etkisi" in rovans_line(on) and rovans_line(off) == "" and rovans_line(None) == ""
    path = tmp_path / "kupa.joblib"
    on.save(path)
    e2 = CupEngine.load(path)
    assert e2.rovans == on.rovans and e2.cup_results.equals(on.cup_results)
    assert e2.rates(HK, AK, "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "UCL", False)["rovans"]["d"] == -3.0
    assert on.digest != off.digest

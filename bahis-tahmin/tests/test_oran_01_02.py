"""ORAN-01/02: gerçek oran sınama araçlarının hesapları (``tools/research/ou25_oran.py``, ``oran_avantaj.py``).

Elle kurulmuş satırlar; model ve özellikler ileriye dönük hat testinde sahte nesnelerle değiştirilir. Ağ yok."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / "research" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ou():
    return _load("ou25_oran")


@pytest.fixture(scope="module")
def av():
    return _load("oran_avantaj")


def _ou_rows(p, o_over, o_under, goals, max_over=None, max_under=None, week=None):
    n = len(p)
    return pd.DataFrame({
        "league": ["E0"] * n, "date": pd.Timestamp("2022-01-01"), "fold": 2021,
        "week": week if week is not None else np.arange(n), "p_o25": p, "o_o25": o_over, "o_u25": o_under,
        "omax_o25": max_over if max_over is not None else o_over,
        "omax_u25": max_under if max_under is not None else o_under,
        "y": (np.asarray(goals) >= 3).astype(float),
    })


# ------------------------------------------------------------------------------------------- ORAN-01
def test_market_probability_removes_the_margin_proportionally(ou):
    assert ou.market_prob([1.9], [1.9])[0] == pytest.approx(0.5)
    p = ou.market_prob([1.5], [2.5])[0]
    assert p == pytest.approx((1 / 1.5) / (1 / 1.5 + 1 / 2.5))
    assert 1 / 1.5 > p  # marj çıkınca ham başabaş olasılığından küçük


def test_bets_pick_one_side_per_match_by_ev_and_threshold(ou):
    # 1: p=0,60, Üst EV 0,14, Alt EV −0,24 → Üst. 2: p=0,30, Alt EV 0,26 → Alt. 3: iki taraf EV < 0 → yok.
    d = _ou_rows([0.60, 0.30, 0.50], [1.9, 2.4, 1.8], [2.0, 1.8, 1.9], goals=[3, 3, 0])
    b = ou.bets(d, 0.0)
    assert list(b["taraf"]) == ["Üst", "Alt"] and len(b) == 2
    assert b["ev"].tolist() == pytest.approx([0.6 * 1.9 - 1, 0.7 * 1.8 - 1])
    assert b["kar"].tolist() == pytest.approx([0.9, -1.0])  # 1. maç Üst kazandı; 2. maçta 3 gol: Alt kaybetti
    assert len(ou.bets(d, 0.2)) == 1 and len(ou.bets(d, 0.15)) == 1  # yalnızca EV ≥ eşik olan (Alt, 0,26)
    assert len(ou.bets(d, 0.6 * 1.9 - 1)) == 2  # eşiğe eşit EV oynanır
    # Ödeme oranı ayrı: seçim ortalama oranla, ödeme en yüksek oranla
    d2 = _ou_rows([0.60], [1.9], [2.0], goals=[4], max_over=[2.05], max_under=[2.1])
    assert ou.bets(d2, 0.0, pay=("omax_o25", "omax_u25"))["kar"].iloc[0] == pytest.approx(1.05)
    # Seçim de en yüksek oranla: EV'ler değişir
    sel = ou.bets(d2, 0.0, pick=("omax_o25", "omax_u25"))
    assert sel["ev"].iloc[0] == pytest.approx(0.6 * 2.05 - 1) and sel["oran"].iloc[0] == pytest.approx(2.05)


def test_threshold_selection_needs_min_bets(ou, monkeypatch):
    rows = {0.0: 900, 0.02: 600, 0.04: 400}
    rois = {0.0: -0.05, 0.02: -0.01, 0.04: 0.10}
    monkeypatch.setattr(ou, "GRID", tuple(rows))
    monkeypatch.setattr(ou, "bets", lambda dev, e: e)
    monkeypatch.setattr(ou, "roi", lambda e: {"n": rows[e], "roi": rois[e]})
    e, grid = ou.select_threshold(None)
    assert e == 0.02 and len(grid) == 3  # 0,04 en yüksek ROI ama 500 bahisten az
    monkeypatch.setattr(ou, "roi", lambda e: {"n": 10, "roi": rois[e]})
    assert ou.select_threshold(None)[0] == 0.0  # hiçbiri yeterli değil: ızgaranın ilki


def test_verdict_mapping(ou, av):
    for mod in (ou, av):
        assert mod.verdict({"n": 0}) == "bahis yok"
        assert mod.verdict({"n": 5, "alt": 0.01, "ust": 0.2}) == "kazandırıyor (bu veride)"
        assert mod.verdict({"n": 5, "alt": -0.2, "ust": -0.01}) == "kaybettiriyor"
        assert mod.verdict({"n": 5, "alt": -0.1, "ust": 0.1}) == "belirsiz"


def test_sample_keeps_only_complete_rows(ou):
    pred = pd.DataFrame({
        "league": "E0", "date": pd.to_datetime(["2022-01-01", "2022-01-02", "2022-01-03", "2022-01-04"]),
        "fold": 2021, "p_o25": [0.5, np.nan, 0.5, 0.5], "o_o25": [1.9, 1.9, np.nan, 1.9],
        "o_u25": [1.9, 1.9, 1.9, 1.9], "fthg": [2, 1, 1, np.nan], "ftag": [1, 1, 1, 0],
        "omax_o25": 2.0, "omax_u25": 2.0,
    })
    s = ou.sample(pred)
    assert len(s) == 1 and s["y"].iloc[0] == 1.0 and s["p_mkt"].iloc[0] == pytest.approx(0.5)


def test_walk_forward_trains_only_on_earlier_seasons(ou, monkeypatch):
    import bahis_tahmin.goals.features as F
    import bahis_tahmin.goals.model as M

    dates = pd.to_datetime([f"{y}-{m:02d}-15" for y in range(2016, 2021) for m in (9, 3)])
    matches = pd.DataFrame({"league": "E0", "date": dates, "home": [f"H{i}" for i in range(len(dates))],
                            "away": [f"A{i}" for i in range(len(dates))], "fthg": 1, "ftag": 2,
                            "o_o25": 1.9, "o_u25": 1.9, "omax_o25": 2.0, "omax_u25": 2.0})
    seen = []

    class FakeModel:
        def __init__(self, variant):
            self.variant = variant

        def fit(self, train):
            self.train = train
            return self

        def predict(self, test):
            seen.append((sorted(set(self.train["fold"])), sorted(set(test["fold"]))))
            return {"FT_O25": np.full(len(test), 0.4)}

    monkeypatch.setattr(F, "build_goal_features", lambda m: (m[["league", "date", "home", "away", "fthg", "ftag"]],
                                                             {}))
    monkeypatch.setattr(M, "GoalModel", FakeModel)
    monkeypatch.setattr(M, "usable_rows", lambda df: np.ones(len(df), dtype=bool))
    with pytest.raises(ValueError):  # küçük veride (eğitim < 2000 satır) bütün sezonlar atlanır: tahmin yok
        ou.walk_forward_ou(matches, variant="X", progress=None)
    seen.clear()
    big =pd.concat([matches.assign(home=matches["home"] + f"_{k}") for k in range(1000)], ignore_index=True)
    pred = ou.walk_forward_ou(big, variant="X", progress=None)
    assert seen and all(max(tr) < te[0] and min(tr) >= ou.WARMUP_YEAR for tr, te in seen)
    assert [te[0] for _, te in seen] == [2017, 2018, 2019, 2020]  # 2016 ısınma, tahmin edilmez
    assert len(pred) == len(big[pd.Series(ou.season_year(big["date"])) > 2016]) and (pred["p_o25"] == 0.4).all()
    assert pred["o_o25"].notna().all()  # oranlar anahtarla birebir eklendi


# ------------------------------------------------------------------------------------------- ORAN-02
def _ax_rows():
    """İki maç: 1X2 ortalama/en yüksek oranlar ve 2,5 Üst/Alt."""
    return pd.DataFrame({
        "league": "E0", "date": pd.to_datetime(["2022-01-01", "2022-01-09"]), "home": ["A", "C"], "away": ["B", "D"],
        "fthg": [2, 0], "ftag": [1, 0],
        "o_h": [2.0, 1.5], "o_d": [3.4, 4.0], "o_a": [3.6, 6.0],
        "omax_h": [2.1, 1.55], "omax_d": [3.6, 4.4], "omax_a": [4.2, 6.2],
        "o_o25": [1.9, 2.0], "o_u25": [1.9, 1.8], "omax_o25": [2.0, 2.05], "omax_u25": [1.95, 1.85],
    })


def test_margin_and_consensus(av):
    avg = np.array([[2.0, 3.4, 3.6]])
    assert av.margin(avg)[0] == pytest.approx(1 / 2 + 1 / 3.4 + 1 / 3.6 - 1)
    c = av.consensus(avg)
    assert c.sum() == pytest.approx(1.0) and c[0, 0] == pytest.approx(0.5 / (1 + av.margin(avg)[0]))


def test_market_frame_filters_and_outcomes(av):
    d = _ax_rows()
    d.loc[1, "omax_d"] = np.nan
    f = av.market_frame(d, "1X2")
    assert len(f) == 1 and f["fold"].iloc[0] == 2021
    assert av.outcomes(f, "1X2").tolist() == [[1.0, 0.0, 0.0]]
    assert av.outcomes(av.market_frame(_ax_rows(), "OU25"), "OU25").tolist() == [[1.0, 0.0], [0.0, 1.0]]
    assert av.outcomes(av.market_frame(_ax_rows(), "1X2"), "1X2").tolist() == [[1, 0, 0], [0, 1, 0]]  # 0-0 beraberlik


def test_bet_all_roi(av):
    d = av.market_frame(_ax_rows(), "OU25")
    r = av.bet_all(d, "OU25", "max")
    # maç 1: Üst kazandı (2,0 − 1 = +1), Alt −1; maç 2: Alt kazandı (+0,85), Üst −1
    assert r["n"] == 4 and r["roi"] == pytest.approx((1.0 - 1 - 1 + 0.85) / 4)
    assert av.bet_all(d, "OU25", "avg")["roi"] == pytest.approx((0.9 - 1 - 1 + 0.8) / 4)


def test_consensus_strategy_picks_best_ev_and_pays_max(av):
    d = av.market_frame(_ax_rows(), "1X2")
    p = av.consensus(d[["o_h", "o_d", "o_a"]].to_numpy(float))
    ev = p * d[["omax_h", "omax_d", "omax_a"]].to_numpy(float) - 1
    b = av.strategy(d, "1X2", -1.0)  # eşik çok düşük: her maçta en iyi EV'li seçenek
    assert list(b["secenek"]) == [["1", "X", "2"][k] for k in ev.argmax(axis=1)]
    k0 = ev[0].argmax()
    win0 = k0 == 0  # 1. maç ev sahibi kazandı
    assert b["kar"].iloc[0] == pytest.approx(d[["omax_h", "omax_d", "omax_a"]].iloc[0, k0] - 1 if win0 else -1.0)
    assert len(av.strategy(d, "1X2", ev.max(axis=1).min() + 1e-9)) == 1  # eşik yalnızca birini geçirir
    pa = av.strategy(d, "1X2", -1.0, pay="avg")
    assert pa["oran"].tolist() == pytest.approx(
        [d[["o_h", "o_d", "o_a"]].to_numpy(float)[i, k] for i, k in enumerate(ev.argmax(axis=1))])

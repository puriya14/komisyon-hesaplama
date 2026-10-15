"""KUPA-ROT-05: kupada rotasyon sınama aracı (``tools/research/kupa_rotasyon.py``). Elle kurulmuş satırlar; ağ yok."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
EPOCH = pd.Timestamp("2000-01-01")


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("kupa_rotasyon", ROOT / "tools" / "research" / "kupa_rotasyon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_rest_gap_and_known(tool):
    sched = {"K": np.array([100, 104, 110])}
    assert tool.rest_gap(sched, "K", 104) == (4.0, 6.0)  # aynı gün sayılmaz
    assert tool.rest_gap(sched, "K", 107) == (3.0, 3.0)
    r, g = tool.rest_gap(sched, "K", 100)
    assert np.isnan(r) and g == 4.0
    r, g = tool.rest_gap(sched, "K", 120)
    assert r == 10.0 and np.isnan(g)
    assert all(np.isnan(tool.rest_gap(sched, "YOK", 5)))
    lg = {"K": np.array([100])}
    assert tool.known(lg, "K", 160) and tool.known(lg, "K", 40) and not tool.known(lg, "K", 161)
    assert not tool.known(lg, "K", 39) and not tool.known(lg, "YOK", 100)


def test_early_round_definition(tool):
    assert tool.is_early("YURTICI", "Round 3") and tool.is_early("YURTICI", "Round of 16")
    for late in ("Quarterfinals", "Semifinals", "Final", "Finals, Round of 16"):
        assert not tool.is_early("YURTICI", late)
    assert not tool.is_early("UEFA", "Round 1") and tool.is_early("YURTICI", None)


def test_schedules_combine_league_and_cup(tool):
    m = pd.DataFrame({"league": ["E0", "E0"], "date": pd.to_datetime(["2024-01-01", "2024-01-08"]),
                      "home": ["Arsenal", "Chelsea"], "away": ["Chelsea", "Arsenal"]})
    c = pd.DataFrame({"date": pd.to_datetime(["2024-01-04"]), "home_key": ["İngiltere|Arsenal"],
                      "away_key": ["X|Kucuk"]})
    allday, league = tool.schedules(m, c)
    d0 = (pd.Timestamp("2024-01-01") - EPOCH).days
    assert list(allday["İngiltere|Arsenal"]) == [d0, d0 + 3, d0 + 7]
    assert list(league["İngiltere|Arsenal"]) == [d0, d0 + 7] and "X|Kucuk" not in league


def _rows(tool, n=4000, a=0.0, b=0.0, seed=3, cand="R1"):
    rng = np.random.default_rng(seed)
    d = pd.DataFrame({"lam_c": rng.uniform(0.6, 2.6, n), "nu_c": rng.uniform(0.4, 2.0, n),
                      "early": rng.random(n) < 0.5, "busy_h": rng.random(n) < 0.4, "busy_a": rng.random(n) < 0.4,
                      "week_b": np.arange(n) // 10})
    d["fav_home"] = d["lam_c"] >= d["nu_c"]
    xh, xa = tool.design(d, cand)
    lam = d["lam_c"] * np.exp(xh @ np.array([a, b]))
    nu = d["nu_c"] * np.exp(xa @ np.array([a, b]))
    d["hg"], d["ag"] = rng.poisson(lam), rng.poisson(nu)
    return d


def test_design_matrices(tool):
    d = pd.DataFrame({"lam_c": [2.0, 1.0, 1.5], "nu_c": [1.0, 2.0, 1.0], "early": [True, True, False],
                      "busy_h": [True, False, True], "busy_a": [False, True, True]})
    d["fav_home"] = d["lam_c"] >= d["nu_c"]
    xh, xa = tool.design(d, "R1")
    assert xh.tolist() == [[1, 0], [0, 1], [0, 0]] and xa.tolist() == [[0, 1], [1, 0], [0, 0]]
    xh, xa = tool.design(d, "R2")
    assert xh.tolist() == [[1, 0], [0, 1], [1, 1]] and xa.tolist() == [[0, 1], [1, 0], [1, 1]]
    lam, nu = tool.rates(d, "R1", [np.log(2), np.log(0.5)])
    assert lam.tolist() == pytest.approx([4.0, 0.5, 1.5]) and nu.tolist() == pytest.approx([0.5, 4.0, 1.0])
    with pytest.raises(KeyError):
        tool.design(d, "R9")


def test_fit_recovers_effect_and_selection_uses_aic(tool):
    d = _rows(tool, a=np.log(0.8), b=np.log(1.25), cand="R1")
    th = tool.fit(d, "R1")
    assert np.exp(th) == pytest.approx([0.8, 1.25], rel=0.06)
    best, res = tool.select(d)
    assert best == "R1" and res["R1"]["daic"] < res["R2"]["daic"] and res["R1"]["daic"] < 0
    flat = _rows(tool, seed=9)  # etkisiz veri: ΔAIC ≥ 0, model değişmez
    best0, res0 = tool.select(flat)
    assert best0 == "R0" and all(r["daic"] >= 0 for r in res0.values())
    # ΔAIC = 2k − 2Δℓ
    assert res["R1"]["daic"] == pytest.approx(4 - 2 * res["R1"]["dll"])


def test_compare_and_accept(tool):
    d = _rows(tool, a=np.log(0.7), b=np.log(1.4), cand="R1", n=6000)
    th = tool.fit(d, "R1")
    r = tool.compare(d, "R1", th)
    assert r["skor"]["ust"] < 0 and r["n"] == 6000
    s0 = tool.score_nll(d, d["lam_c"].to_numpy(), d["nu_c"].to_numpy())
    s1 = tool.score_nll(d, *tool.rates(d, "R1", th))
    assert r["skor"]["fark"] == pytest.approx(float((s1 - s0).mean()))
    assert tool.accept({"skor": {"ust": -0.01}, "x2": {"alt": -0.001}})
    assert not tool.accept({"skor": {"ust": 0.001}, "x2": {"alt": -0.001}})
    assert not tool.accept({"skor": {"ust": -0.01}, "x2": {"alt": 0.0001}})

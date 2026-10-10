import numpy as np
import pandas as pd
import pytest

from bahis_tahmin.betting.backtest import BacktestConfig, run_backtest
from bahis_tahmin.config import Settings
from bahis_tahmin.models.engine import (
    MARKET_GROUPS,
    PMK_COLS,
    PredictionEngine,
    confidence_report,
    market_odds_matrix,
    verify_selection,
)


def test_engine_trains_and_predicts(trained_engine):
    eng = trained_engine
    assert eng.trained
    m = eng.report.metrics
    assert m["n"] > 300
    assert 0.3 < m["acc_model"] < 0.8
    # Model, sabit (lig ortalaması) tahminden daha iyi olmalı
    assert m["ll_model_all"] < m["ll_baseline"]
    p = eng.predict_match("T1", "Takım A", "Takım B", "2025-06-01")
    assert p.p_final.sum() == pytest.approx(1.0)
    assert p.markets["1"] == pytest.approx(p.p_final[0], abs=1e-6)
    assert p.matrix.sum() == pytest.approx(1.0)
    assert p.p_market is None


def test_market_blend_uses_odds(trained_engine):
    eng = trained_engine
    p0 = eng.predict_match("T1", "Takım A", "Takım B")
    p1 = eng.predict_match("T1", "Takım A", "Takım B", market_odds={"1": 1.25, "X": 6.0, "2": 12.0})
    assert p1.p_market is not None
    assert p1.p_final[0] > p0.p_final[0] or p1.p_final[0] > 0.6
    rows = p1.value_rows(Settings(), {"1": 3.0})
    r1 = next(r for r in rows if r["market"] == "1")
    assert r1["ev"] == pytest.approx(p1.markets["1"] * 3.0 - 1)


def test_unknown_team_and_league(trained_engine):
    p = trained_engine.predict_match("T1", "Yepyeni Takım", "Takım C")
    assert np.isfinite(p.p_final).all()
    with pytest.raises(KeyError):
        trained_engine.predict_match("E0", "A", "B")


def test_save_and_load(trained_engine, tmp_path):
    path = tmp_path / "engine.joblib"
    trained_engine.save(path)
    eng = PredictionEngine.load(path)
    assert eng is not None and eng.trained
    assert PredictionEngine.load(tmp_path / "yok.joblib") is None


def test_oos_markets_and_confidence(trained_engine):
    oos = trained_engine.oos
    assert set(PMK_COLS) <= set(oos.columns)
    P = oos[PMK_COLS].to_numpy()
    assert np.allclose(P[:, 0] + P[:, 1] + P[:, 2], 1.0, atol=1e-6)
    conf = confidence_report(oos)
    assert {"top1x2", "best", "per_market_90"} <= set(conf)
    rows = [r for r in conf["best"] if r["n"] > 30]
    # Kalibrasyon: eşik yükseldikçe isabet artar, kapsam azalır
    assert rows[0]["kapsam"] >= rows[-1]["kapsam"]
    keys = [k for g in MARKET_GROUPS.values() for k in g]
    v = verify_selection(oos, keys, 0.8)
    assert v["n"] > 0 and 0 <= v["isabet"] <= 1
    O = market_odds_matrix(oos)
    assert O.shape == (len(oos), len(PMK_COLS))


def test_backtest_profit_is_exact():
    oos = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        "league": "T1", "season": "2023/24", "fold": 2023, "home": ["A", "B", "C"], "away": ["D", "E", "F"],
        "fthg": [2, 0, 1], "ftag": [0, 1, 1], "y_res": [0, 2, 1], "y_o25": [0, 0, 0],
        "pf_h": [0.6, 0.6, 0.2], "pf_d": [0.2, 0.2, 0.5], "pf_a": [0.2, 0.2, 0.3],
        "pf_o25": [0.5, 0.5, 0.5],
        "o_h": [2.0, 2.0, 5.0], "o_d": [3.5, 3.5, 2.5], "o_a": [5.0, 5.0, 3.0],
        "oc_h": np.nan, "oc_d": np.nan, "oc_a": np.nan, "o_o25": np.nan, "o_u25": np.nan,
    })
    cfg = BacktestConfig(markets=("1X2",), min_ev=0.05, min_prob=0.1, staking="flat", bankroll=100, flat_stake_pct=0.01)
    r = run_backtest(oos, cfg)
    # Maç 1: MS1 @2.0 (EV +0.2) kazandı +1; maç 2: MS1 kaybetti -1; maç 3: X @2.5 (EV +0.25) kazandı +1.5
    assert r.summary["bahis"] == 3
    assert r.summary["kar"] == pytest.approx(1.5)
    assert r.summary["isabet"] == pytest.approx(2 / 3)
    assert list(r.bets["selection"]) == ["MS 1", "MS 1", "MS X"]

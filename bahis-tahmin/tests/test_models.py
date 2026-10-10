import numpy as np
import pandas as pd
import pytest

from bahis_tahmin.betting.odds import expected_value, implied_probs, kelly_fraction
from bahis_tahmin.data.teams import match_team
from bahis_tahmin.models.dixon_coles import DCConfig, DCTracker, score_matrix, tau
from bahis_tahmin.models.elo import EloTracker
from bahis_tahmin.models.features import FEATURES, build_features
from bahis_tahmin.models.markets import (
    MARKET_KEYS,
    adjust_matrix,
    batch_adjust,
    batch_markets,
    batch_score_matrices,
    market_outcomes,
    markets_from_matrix,
)


# ---------------------------------------------------------------- oranlar
def test_implied_probs_methods():
    odds = np.array([[1.9, 3.5, 4.2], [1.2, 6.5, 13.0]])
    for method in ("power", "proportional"):
        p = implied_probs(odds, method)
        assert np.allclose(p.sum(axis=1), 1.0)
        assert np.all(p > 0)
    pw = implied_probs(odds, "power")
    pr = implied_probs(odds, "proportional")
    # Üs yöntemi favori-sürpriz yanlılığını düzeltir: sürprize daha az olasılık verir
    assert pw[1, 2] < pr[1, 2]
    assert np.isnan(implied_probs([[2.0, np.nan, 3.0]])).all()


def test_ev_and_kelly():
    assert expected_value(0.5, 2.2) == pytest.approx(0.1)
    assert kelly_fraction(0.5, 2.2) == pytest.approx(0.1 / 1.2)
    assert kelly_fraction(0.4, 2.0) == 0.0
    assert kelly_fraction(0.6, 3.0, fraction=0.25, cap=0.05) == pytest.approx(0.05)


def test_team_name_matching():
    known = ["Man United", "Man City", "Wolves", "Nott'm Forest", "Arsenal", "Coventry", "Buyuksehyr", "Goztep"]
    assert match_team("Manchester United FC", known) == "Man United"
    assert match_team("Wolverhampton Wanderers FC", known) == "Wolves"
    assert match_team("Nottingham Forest FC", known) == "Nott'm Forest"
    assert match_team("Arsenal FC", known) == "Arsenal"
    assert match_team("Coventry City FC", known) == "Coventry"
    assert match_team("İstanbul Başakşehir", known) == "Buyuksehyr"
    assert match_team("Göztepe", known) == "Goztep"
    assert match_team("Totally Unknown FC", known) is None


# ---------------------------------------------------------- Dixon-Coles
def test_score_matrix_and_tau():
    m = score_matrix(1.5, 1.1, -0.1)
    assert m.shape == (11, 11)
    assert m.sum() == pytest.approx(1.0)
    assert tau(0, 0, 1.5, 1.1, 0.0) == 1.0
    assert tau(1, 1, 1.5, 1.1, -0.1) == pytest.approx(1.1)


def test_dixon_coles_recovers_strengths():
    rng = np.random.default_rng(3)
    n = 10
    att = rng.normal(0, 0.35, n)
    dfn = rng.normal(0, 0.35, n)
    tr = DCTracker(DCConfig(ridge=0.5, xi=0.0))
    day = 0
    for _ in range(6):
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                lam = np.exp(0.2 + 0.25 + att[i] - dfn[j])
                nu = np.exp(0.2 + att[j] - dfn[i])
                tr.add(day, f"T{i}", f"T{j}", int(rng.poisson(lam)), int(rng.poisson(nu)))
                day += 1
    model = tr.fit(day + 1)
    est_a = np.array([model.params(f"T{i}")[0] for i in range(n)])
    est_d = np.array([model.params(f"T{i}")[1] for i in range(n)])
    assert np.corrcoef(est_a, att)[0, 1] > 0.85
    assert np.corrcoef(est_d, dfn)[0, 1] > 0.85
    assert 0.1 < model.home_adv < 0.4
    # Hiç görülmemiş takım "yeni takım" parametreleri alır
    assert model.params("Bilinmeyen") == (model.new_attack, model.new_defense)


# ------------------------------------------------------------------- Elo
def test_elo_updates_and_promoted_teams():
    elo = EloTracker()
    elo.start_season("2020/21")
    for _ in range(5):
        elo.update("A", "B", 3, 0)
        elo.update("C", "D", 1, 1)
    assert elo.rating("A") > 1500 > elo.rating("B")
    elo.start_season("2021/22")
    assert elo.is_new("Yeni") and not elo.is_new("A")
    assert elo.rating("Yeni") == pytest.approx(elo.promoted_rating)
    assert elo.promoted_rating < 1500 + 1e-9


# ---------------------------------------------------------------- marketler
def test_adjust_matrix_matches_targets_and_batch_agrees():
    base = score_matrix(1.6, 1.0, -0.08)
    target = (0.5, 0.27, 0.23)
    m = adjust_matrix(base, target, 0.55, 0.52)
    mk = markets_from_matrix(m)
    assert (mk["1"], mk["X"], mk["2"]) == pytest.approx(target, abs=1e-9)
    assert mk["O2.5"] == pytest.approx(0.55, abs=1e-6)
    assert mk["BTTS_Y"] == pytest.approx(0.52, abs=1e-6)
    assert mk["1X"] == pytest.approx(mk["1"] + mk["X"])
    bm = batch_adjust(batch_score_matrices([1.6], [1.0], [-0.08]), [target], [0.55], [0.52])
    bp = batch_markets(bm)[0]
    assert np.allclose(bp, [mk[k] for k in MARKET_KEYS], atol=1e-8)


def test_market_outcomes():
    w = market_outcomes(np.array([2, 0, 1]), np.array([1, 0, 1]))
    keys = {k: i for i, k in enumerate(MARKET_KEYS)}
    assert w[0, keys["1"]] and w[0, keys["O2.5"]] and w[0, keys["BTTS_Y"]]
    assert w[1, keys["X"]] and w[1, keys["U1.5"]] and w[1, keys["BTTS_N"]]
    assert w[2, keys["X"]] and w[2, keys["O1.5"]] and not w[2, keys["O2.5"]]


# ---------------------------------------------------------------- özellikler
def test_features_have_no_future_leakage(synthetic):
    """Bir maçın özellikleri, ondan SONRA oynanan maçların sonuçlarından etkilenmemeli."""
    feat_a, _ = build_features(synthetic)
    changed = synthetic.copy()
    cut = changed["date"].iloc[len(changed) // 2]
    later = changed["date"] > cut
    changed.loc[later, "fthg"] = 9
    changed.loc[later, "ftag"] = 0
    feat_b, _ = build_features(changed)
    early = feat_a["date"] <= cut
    a = feat_a.loc[early, FEATURES].to_numpy(dtype=float)
    b = feat_b.loc[early, FEATURES].to_numpy(dtype=float)
    assert np.allclose(np.nan_to_num(a, nan=-1), np.nan_to_num(b, nan=-1))
    # Sonraki maçlar ise değişmeli (özellikler gerçekten geçmişe bakıyor)
    assert not np.allclose(
        np.nan_to_num(feat_a.loc[later, FEATURES].to_numpy(dtype=float), nan=-1),
        np.nan_to_num(feat_b.loc[later, FEATURES].to_numpy(dtype=float), nan=-1),
    )


def test_features_targets(synthetic):
    feat, states = build_features(synthetic)
    assert set(states) == {"T1"}
    r = feat.iloc[-1]
    assert r["y_res"] == (0 if r["fthg"] > r["ftag"] else 1 if r["fthg"] == r["ftag"] else 2)
    assert r["y_o25"] == int(r["fthg"] + r["ftag"] >= 3)
    assert feat["dc_ph"].notna().mean() > 0.8
    assert isinstance(feat["date"].iloc[0], pd.Timestamp)

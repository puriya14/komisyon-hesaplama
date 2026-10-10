"""Gol pazarları motoru: tutarlılık, sızıntı, doğrulama statüsü, model dosyası, karar ve sanal takip.

Tüm testler sentetik (açıkça test amaçlı) veriyle ve geçici dizinlerde çalışır; gerçek veri
kaynaklarına veya kullanıcı verisine dokunmaz.
"""

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from bahis_tahmin.goals.engine import GoalDataError, GoalEngine
from bahis_tahmin.goals.features import build_goal_features
from bahis_tahmin.goals.ledger import Ledger
from bahis_tahmin.goals.model import GoalModel
from bahis_tahmin.goals.service import SELECTIONS, decisions_for, record_decisions, settle_pending
from bahis_tahmin.goals.value import OddsQuote
from bahis_tahmin.selftest import synthetic_matches

UTC = dt.timezone.utc


@pytest.fixture(scope="module")
def ht_matches():
    return synthetic_matches(n_seasons=8, n_teams=16, seed=1, half_time=True)


@pytest.fixture(scope="module")
def goal_engine(ht_matches):
    eng = GoalEngine()
    eng.train(ht_matches)
    return eng


@pytest.fixture(scope="module")
def fixtures(ht_matches):
    fx = ht_matches.tail(6)[["league", "date", "time", "home", "away", "source"]].copy()
    fx["date"] = pd.Timestamp("2026-10-12")
    return fx


def _check_relations(p, tol=1e-9):
    a, b, c, bc = (np.asarray(p[k], dtype=float) for k in ("A", "B", "C", "BC"))
    ok = np.isfinite(a)
    assert ok.any()
    for v in (a, b, c, bc):
        assert ((v[ok] >= 0) & (v[ok] <= 1)).all()
    assert (a[ok] <= bc[ok] + tol).all()
    assert (bc[ok] <= np.minimum(b[ok], c[ok]) + tol).all()


def test_engine_predictions_are_consistent(goal_engine, fixtures):
    preds = goal_engine.predict_fixtures(fixtures)
    assert len(preds) == len(fixtures)
    for p in preds:
        _check_relations({k: [p.probs[k]] for k in ("A", "B", "C", "BC")})
        # Hayır/Alt tarafı tümleyendir; aralıklar da tümleyen olarak döner
        assert p.p("FT_UNDER_3_5") == pytest.approx(1 - p.p("FT_OVER_3_5"))
        assert p.p("BTTS_BOTH_HALVES_NO") == pytest.approx(1 - p.p("BTTS_BOTH_HALVES_YES"))
        lo, hi = p.interval("FT_OVER_3_5")
        lo2, hi2 = p.interval("FT_UNDER_3_5")
        assert lo <= hi and lo2 == pytest.approx(1 - hi) and hi2 == pytest.approx(1 - lo)
        assert p.kickoff_utc is not None and p.kickoff_utc.tzinfo is not None


@pytest.mark.parametrize("variant", ["M3_kosullu", "M5_kalibre", "M9_ipf", "M10_ipf_kosullu"])
def test_model_variants_respect_market_relations(ht_matches, variant):
    feat, _ = build_goal_features(ht_matches)
    tr, te = feat[feat["date"] < "2026-08-01"], feat[feat["date"] >= "2026-08-01"]
    p = GoalModel(variant).fit(tr).predict(te)
    _check_relations(p)


def test_ipf_matches_calibrated_marginals(ht_matches):
    feat, _ = build_goal_features(ht_matches)
    tr, te = feat[feat["date"] < "2026-08-01"], feat[feat["date"] >= "2026-08-01"]
    m = GoalModel("M9_ipf").fit(tr)
    p = m.predict(te)
    cal = m.calibrator.predict(te)
    ok = np.isfinite(p["B"])
    assert np.allclose(p["B"][ok], cal["B"][ok], atol=1e-6)
    assert np.allclose(p["C"][ok], cal["C"][ok], atol=1e-6)


def test_interval_is_reproducible(goal_engine, fixtures):
    a = goal_engine.predict_fixtures(fixtures)[0]
    b = goal_engine.predict_fixtures(fixtures)[0]
    assert a.intervals["FT_OVER_3_5"] == b.intervals["FT_OVER_3_5"]
    assert a.intervals["meta"]["seed"] == b.intervals["meta"]["seed"]


def test_without_holdout_models_are_not_validated(goal_engine):
    # Sentetik veri zaman sıralı doğrulama için yetersiz: hiçbir pazar doğrulanmış sayılmamalı
    assert goal_engine.validated and not any(goal_engine.validated.values())
    assert goal_engine.status_text("FT_OVER_3_5") == "MODEL_NOT_VALIDATED"


def test_no_halftime_data_is_reported_not_faked():
    m = synthetic_matches(n_seasons=5, n_teams=14, seed=1)  # ilk yarı skoru yok
    with pytest.raises(GoalDataError, match="ilk yarı"):
        GoalEngine().train(m)


def test_goal_features_do_not_leak_future_or_same_day(ht_matches):
    base, _ = build_goal_features(ht_matches)
    cols = ["l1h", "l1a", "l2h", "l2a", "lh", "la", "bA", "bB", "bC", "h_sc1", "a_cc2"]
    day = ht_matches["date"].iloc[len(ht_matches) // 2]
    later = ht_matches.copy()
    idx_same = later.index[later["date"] == day][0]
    future = later["date"] > day
    later.loc[future, ["fthg", "ftag", "hthg", "htag"]] = [9, 9, 5, 5]
    later.loc[idx_same, ["fthg", "ftag", "hthg", "htag"]] = [8, 8, 4, 4]
    changed, _ = build_goal_features(later)
    upto = ht_matches["date"] <= day
    a = base.loc[upto.to_numpy(), cols].to_numpy(dtype=float)
    b = changed.loc[upto.to_numpy(), cols].to_numpy(dtype=float)
    assert np.allclose(np.nan_to_num(a, nan=-1), np.nan_to_num(b, nan=-1))


def test_save_load_and_reject_tampered(goal_engine, tmp_path):
    path = tmp_path / "goal.joblib"
    goal_engine.save(path)
    man = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assert man["kind"] == "goal-engine"
    assert man["feature_schema"] and man["data_cutoff"] and man["validation_rule"]
    eng, err = GoalEngine.load(path)
    assert err is None and eng.trained
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF
    path.write_bytes(bytes(data))
    eng, err = GoalEngine.load(path)
    assert eng is None and err


def _quote(event, key, odds, at):
    from bahis_tahmin.goals.markets import MARKETS

    m = MARKETS[key]
    return OddsQuote(event, key, m.period, m.line, m.selection, "manuel", "test", odds, at, at)


def _synthetic_ok(pred, now):
    """Karar mantığı testleri için açıkça SENTETİK "veri uygun" sonucu (aynı model durumuna bağlı; S3-GATE-01)."""
    from bahis_tahmin.goals.markets import PRIMARY_YES
    from uygunluk_yardim import verified

    return {k: verified(pred.event_id, k, now, state_digest=pred.state_digest) for k in PRIMARY_YES}


def test_decisions_require_validation_and_real_odds(goal_engine, fixtures, tmp_path):
    pred = goal_engine.predict_fixtures(fixtures)[0]
    now = dt.datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
    # Uygunluk bağlamı verilmeden: hiçbir seçim aday olamaz ve olasılık taşınmaz
    assert all(d.status == "DATA_NOT_ELIGIBLE" and d.p != d.p for d in decisions_for(pred, goal_engine, None, now))
    elig = _synthetic_ok(pred, now)
    decs = decisions_for(pred, goal_engine, None, now, eligibility=elig)
    assert [d.market_key for d in decs] == list(SELECTIONS)
    assert all(d.status != "VALUE_CANDIDATE" for d in decs)
    assert all(d.odds is None and d.ev is None for d in decs)  # gerçek oran yoksa EV de yok

    ledger = Ledger(tmp_path / "l.sqlite")
    p_over = pred.p("FT_OVER_3_5")
    odds = round(1.15 / max(pred.interval("FT_OVER_3_5")[0], 0.05), 2)  # belirsizlik alt sınırıyla da +%15
    ledger.add_odds([_quote(pred.event_id, "FT_OVER_3_5", odds, now - dt.timedelta(minutes=5))])
    by = {d.market_key: d for d in decisions_for(pred, goal_engine, ledger, now, eligibility=elig)}
    d = by["FT_OVER_3_5"]
    assert d.odds == pytest.approx(odds) and d.ev == pytest.approx(p_over * odds - 1)
    assert d.status != "VALUE_CANDIDATE"  # model doğrulanmadı

    goal_engine.validated["FT_OVER_3_5"] = True
    try:
        by = {d.market_key: d for d in decisions_for(pred, goal_engine, ledger, now, eligibility=elig)}
        assert by["FT_OVER_3_5"].status in ("VALUE_CANDIDATE", "HIGH_UNCERTAINTY", "SUSPICIOUS_EDGE", "INSUFFICIENT_DATA")
        # Karar anından SONRA girilen oran kullanılamaz
        by_early = {d.market_key: d for d in decisions_for(pred, goal_engine, ledger, now - dt.timedelta(hours=1),
                                                           eligibility=elig)}
        assert by_early["FT_OVER_3_5"].status == "ODDS_UNAVAILABLE" or by_early["FT_OVER_3_5"].odds is None
    finally:
        goal_engine.validated["FT_OVER_3_5"] = False
    ledger.close()


def test_record_and_settle_is_idempotent(goal_engine, fixtures, tmp_path):
    pred = goal_engine.predict_fixtures(fixtures)[0]
    now = dt.datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
    ledger = Ledger(tmp_path / "l.sqlite")
    decs = decisions_for(pred, goal_engine, ledger, now, eligibility=_synthetic_ok(pred, now))
    ids = record_decisions(ledger, pred, decs, goal_engine)
    assert len(ids) == len(SELECTIONS)
    assert all(r["stake_units"] == 0 for r in ledger.predictions())  # aday yoksa sanal stake yok
    res = pd.DataFrame([{"league": pred.league, "date": pred.date, "home": pred.home, "away": pred.away,
                         "fthg": 3, "ftag": 2, "hthg": 1, "htag": 1}])
    out = settle_pending(ledger, res)
    assert out["sonuclanan"] == len(SELECTIONS)
    st = {r["market_key"]: r["outcome"]["settlement"] for r in ledger.predictions()}
    assert st["FT_OVER_3_5"] == "WIN" and st["FT_UNDER_3_5"] == "LOSS"
    assert st["FH_OVER_1_5"] == "WIN" and st["BTTS_BOTH_HALVES_YES"] == "WIN"
    assert settle_pending(ledger, res)["sonuclanan"] == 0  # ikinci kez sonuç eklenmez
    ok, _ = ledger.verify_chain()
    assert ok
    ledger.close()

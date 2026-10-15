"""ORAN-04: piyasanın 2,5 Üst/Alt oranından maçın gol düzeyi (lig ve kupa gol pazarları). Yalnızca SENTETİK veri; ağ
yok. Ön kayıtlı sınama aracı ``tools/research/piyasa_duzey.py`` (P1) ile uygulama aynı yöntemi kullanır."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from uygunluk_yardim import AS_OF, recent_synthetic

from bahis_tahmin.goals.ledger import Ledger
from bahis_tahmin.goals.markets import MARKETS
from bahis_tahmin.goals.piyasa import (
    MARKET_SUFFIX,
    S_HI,
    from_fixture,
    from_ledger,
    from_odds,
    market_prob,
    market_scale,
    poisson_scale,
    scaled,
)
from bahis_tahmin.goals.value import OddsQuote

ROOT = Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc
DAY = pd.Timestamp("2026-11-04")


@pytest.fixture(scope="module")
def eng():
    from bahis_tahmin.goals.engine import GoalEngine

    e = GoalEngine()
    e.train(recent_synthetic())
    return e


@pytest.fixture(scope="module")
def teams(eng):
    return sorted(eng.states["T1"].elo.cur_teams or eng.states["T1"].elo.prev_teams)


def _feature_row(eng, home, away, date=DAY):
    from bahis_tahmin.goals.features import GOAL_FEATURES

    snap = eng.states["T1"].snapshot_for(date)
    X = pd.DataFrame([snap.features(home, away, int((date - pd.Timestamp("2000-01-01")).days))], columns=GOAL_FEATURES)
    X["issues"], X["hthg"], X["htag"] = "", 0.0, 0.0
    return X


def _q(event, key, odds, t, book="B1"):
    m = MARKETS[key]
    return OddsQuote(event, key, m.period, m.line, m.selection, "manuel", book, odds, t, t)


# --------------------------------------------------------------------------------------------- kaynaklar
def test_market_probability_and_sources():
    assert market_prob(1.9, 1.9) == pytest.approx(0.5)
    ml = from_odds(1.7, 2.2, "girilen oran", "B")
    assert ml.p == pytest.approx((1 / 1.7) / (1 / 1.7 + 1 / 2.2)) and ml.over == 1.7 and ml.bookmaker == "B"
    for bad in ((1.0, 2.0), (2.0, None), (float("nan"), 2.0), ("x", 2.0), (2.0, 1001.0)):
        assert from_odds(*bad, "x") is None
    row = type("R", (), {"o_o25": 1.8, "o_u25": 2.0})
    assert from_fixture(row).source == "fikstür ortalama oranı" and from_fixture(object()) is None


def test_ledger_source_needs_both_sides_same_book_before_decision(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    ev = "T1|2026-11-04|A|B"
    t0 = dt.datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    assert from_ledger(led, ev, AS_OF) is None and from_ledger(None, ev, AS_OF) is None
    led.add_odds([_q(ev, "FT_OVER_2_5", 1.8, t0)])
    assert from_ledger(led, ev, AS_OF) is None  # tek taraf yetmez
    led.add_odds([_q(ev, "FT_UNDER_2_5", 2.0, t0 + dt.timedelta(minutes=2), book="B2")])
    assert from_ledger(led, ev, AS_OF) is None  # farklı şirket
    led.add_odds([_q(ev, "FT_UNDER_2_5", 2.05, t0 + dt.timedelta(minutes=3))])
    ml = from_ledger(led, ev, AS_OF)
    assert ml.p == pytest.approx(market_prob(1.8, 2.05)) and ml.source == "girilen oran" and ml.bookmaker == "B1"
    led.add_odds([_q(ev, "FT_OVER_2_5", 1.6, AS_OF + dt.timedelta(hours=1)),
                  _q(ev, "FT_UNDER_2_5", 2.4, AS_OF + dt.timedelta(hours=1))])
    assert from_ledger(led, ev, AS_OF).over == 1.8  # karar anından sonraki oran kullanılmaz
    assert from_ledger(led, ev, AS_OF + dt.timedelta(hours=2)).over == 1.6
    led.close()


# --------------------------------------------------------------------------------------------- lig motoru
def test_scale_matches_market_and_is_independently_reproduced(eng, teams):
    from scipy.optimize import brentq

    X = _feature_row(eng, teams[0], teams[1])
    base = eng.model.base
    for p_m in (0.35, 0.55, 0.7):
        s = market_scale(eng.model, X, [p_m])[0]
        # Bağımsız yeniden hesap: kök bulucu ile aynı s
        s2 = brentq(lambda z: base.predict(scaled(X, z))["FT_O25"][0] - p_m, 0.25, 4.0, xtol=1e-12)
        assert s == pytest.approx(s2, rel=1e-6)
        assert base.predict(scaled(X, s))["FT_O25"][0] == pytest.approx(p_m, abs=1e-8)
    assert market_scale(eng.model, X, [0.9999])[0] == pytest.approx(S_HI, rel=1e-6)  # ulaşılamaz: sınırda kırpılır


def test_engine_market_prediction(eng, teams):
    import copy

    e = copy.copy(eng)
    e.validated = {k: True for k in eng.validated}
    e.validated_market = {k: False for k in eng.validated}
    p0 = e.predict_match("T1", teams[0], teams[1], DAY)
    lo, hi = from_odds(2.6, 1.5, "girilen oran"), from_odds(1.5, 2.6, "girilen oran")
    p_lo = e.predict_match("T1", teams[0], teams[1], DAY, market=lo)
    p_hi = e.predict_match("T1", teams[0], teams[1], DAY, market=hi)
    # Temel tahmin değişmedi (piyasasız yol aynen) ve kendi motor statüsünü kullanır
    assert p0.validated is None and "piyasa" not in p0.info
    for p, ml in ((p_lo, lo), (p_hi, hi)):
        assert p.probs["FT_O25"] == pytest.approx(ml.p, abs=1e-7)
        assert p.info["piyasa"]["p"] == ml.p and p.info["model_version"].endswith(MARKET_SUFFIX)
        assert p.validated == {k: False for k in eng.validated}  # piyasa düzeyli: kendi statüsü
    for s in ("A", "B", "C"):
        assert p_lo.probs[s] < p0.probs[s] < p_hi.probs[s] or p_lo.probs[s] < p_hi.probs[s]
    assert p_lo.probs["B"] < p_hi.probs["B"] and p_lo.probs["C"] < p_hi.probs["C"]
    # Bağımsız yeniden hesap: ölçeklenmiş girdilerle modelin tahmini
    X = _feature_row(eng, teams[0], teams[1])
    s = p_hi.info["piyasa"]["olcek"]
    ref = eng.model.predict(scaled(X, s))
    for k in ("A", "B", "C", "BC"):
        assert p_hi.probs[k] == pytest.approx(float(ref[k][0]), rel=1e-12)
    lo_i, hi_i = p_hi.intervals["FT_OVER_3_5"]
    assert lo_i <= p_hi.probs["B"] <= hi_i
    # market_prediction: aynı olasılıklar, maç saati ve kimlik önceki tahminden
    q = e.market_prediction(p0, hi)
    assert q.probs == p_hi.probs and q.kickoff_text == p0.kickoff_text and q.event_id == p0.event_id


def test_old_engine_without_market_validation_is_not_validated(eng, teams):
    import copy

    e = copy.copy(eng)
    del e.__dict__["validated_market"]
    p = e.predict_match("T1", teams[0], teams[1], DAY, market=from_odds(1.8, 2.0, "x"))
    assert p.validated == {k: False for k in eng.validated}
    from bahis_tahmin.goals.piyasa import market_status_text

    assert "yeniden eğitin" in market_status_text(e)


def test_fixtures_use_their_own_odds_only(eng, teams):
    fx = pd.DataFrame([{"league": "T1", "date": DAY, "time": "", "home": teams[2 * i], "away": teams[2 * i + 1],
                        "source": "x", "o_o25": o, "o_u25": u} for i, (o, u) in
                       enumerate(((1.7, 2.2), (np.nan, np.nan), (2.5, 1.55)))])
    preds = eng.predict_fixtures(fx)
    plain = eng.predict_fixtures(fx.drop(columns=["o_o25", "o_u25"]))
    # Oranı olmayan fikstür temel tahminle aynı (IPF yakınsaması partiye bağlı: 1e-9 göreli)
    assert "piyasa" not in preds[1].info and preds[1].validated is None
    for k, val in plain[1].probs.items():
        assert preds[1].probs[k] == pytest.approx(val, rel=1e-9, abs=1e-12)
    for i in (0, 2):
        ml = from_odds(fx.loc[i, "o_o25"], fx.loc[i, "o_u25"], "x")
        assert preds[i].probs["FT_O25"] == pytest.approx(ml.p, abs=1e-7)
        assert preds[i].info["piyasa"]["kaynak"] == "fikstür ortalama oranı"
        single = eng.predict_match("T1", teams[2 * i], teams[2 * i + 1], DAY, market=ml)
        assert preds[i].probs["B"] == pytest.approx(single.probs["B"], rel=1e-9)


def test_market_verdict_uses_ledger_odds(eng, teams, tmp_path):
    import copy
    import dataclasses

    from bahis_tahmin.goals.service import gated_goal_match, market_short, market_verdict

    v = gated_goal_match(eng, None, "T1", teams[0], teams[1], DAY, AS_OF)
    led = Ledger(tmp_path / "l.sqlite")
    ev = v.prediction.event_id
    assert market_verdict(v, eng, led, AS_OF) is v and market_short(v.prediction) == "-"
    t = AS_OF - dt.timedelta(hours=1)
    led.add_odds([_q(ev, "FT_OVER_2_5", 1.7, t), _q(ev, "FT_UNDER_2_5", 2.2, t)])
    w = market_verdict(v, eng, led, AS_OF)
    assert w is not v and w.by_market is v.by_market and w.prediction.probs["FT_O25"] == pytest.approx(
        market_prob(1.7, 2.2), abs=1e-7)
    assert market_short(w.prediction).startswith("×") and "girilen oran" in market_short(w.prediction)
    assert market_verdict(v, eng, led, t - dt.timedelta(minutes=1)) is v  # oran karar anından sonra
    # Veri kodları değişirse (uygunluk başka girdiyle değerlendirilmiş olurdu) tahmin değiştirilmez
    e2 = copy.copy(eng)
    e2.market_prediction = lambda p, ml: dataclasses.replace(p, data_codes=("TAKIM_N365_AZ",))
    assert market_verdict(v, e2, led, AS_OF) is v
    assert market_verdict(v, None, led, AS_OF) is v
    led.close()


def test_recorded_decisions_carry_market_level(eng, teams, tmp_path):
    from bahis_tahmin.goals.service import decisions_for, gated_goal_match, record_decisions

    v = gated_goal_match(eng, None, "T1", teams[0], teams[1], DAY, AS_OF, market=from_odds(1.7, 2.2, "girilen oran"))
    led = Ledger(tmp_path / "l.sqlite")
    record_decisions(led, v.prediction, decisions_for(v.prediction, eng, led, AS_OF, eligibility=v), eng,
                     record_time=AS_OF)
    recs = led.predictions()
    assert recs and all(r["model_version"].endswith(MARKET_SUFFIX) for r in recs)
    assert all(r["piyasa_duzeyi"]["ust"] == 1.7 for r in recs)
    v0 = gated_goal_match(eng, None, "T1", teams[0], teams[1], DAY, AS_OF)
    n = len(recs)
    record_decisions(led, v0.prediction, decisions_for(v0.prediction, eng, led, AS_OF, eligibility=v0), eng,
                     record_time=AS_OF)
    assert all("piyasa_duzeyi" not in r and not r["model_version"].endswith(MARKET_SUFFIX)
               for r in led.predictions()[n:])
    led.close()


# --------------------------------------------------------------------------------------- doğrulama hattı
@pytest.fixture(scope="module")
def big():
    from bahis_tahmin.goals.engine import GoalEngine

    m = recent_synthetic(n_seasons=5, n_teams=40, seed=4)
    e = GoalEngine()
    e.train(m)
    return m, e


def test_training_measures_market_level_separately(big):
    from bahis_tahmin.goals.engine import validated_by_rule

    m, e = big
    mv = f"{e.variant}{MARKET_SUFFIX}"
    assert e.validation and e.validation_market
    for key, r in e.validation_market.items():
        assert mv in r["modeller"] and r["n"] > 500
    assert e.validated_market == validated_by_rule(e.validation_market, mv)
    assert set(e.validated_market) == set(e.validated)


def test_validation_rule_reads_each_measurement_separately(big):
    """Piyasa düzeyli statü piyasa ölçümünden, modelin statüsü kendi ölçümünden (birbirinden kopyalanmaz)."""
    import copy

    _, e0 = big
    e = copy.deepcopy(e0)
    mv = f"{e.variant}{MARKET_SUFFIX}"
    good = {"ll_fark_ust": -0.01, "kal_egim": 1.0, "ece": 0.005}
    bad = {"ll_fark_ust": +0.01, "kal_egim": 1.0, "ece": 0.005}
    keys = list(e.validated)
    e.validation = {k: {"pozitif": 500, "modeller": {e.variant: dict(good if i == 0 else bad)}}
                    for i, k in enumerate(keys)}
    e.validation_market = {k: {"pozitif": 500, "modeller": {mv: dict(bad if i == 0 else good)}}
                           for i, k in enumerate(keys)}
    e.apply_validation_rule()
    assert e.validated == {k: i == 0 for i, k in enumerate(keys)}
    assert e.validated_market == {k: i != 0 for i, k in enumerate(keys)}
    e.validation_market[keys[1]]["pozitif"] = 199  # kuralın her koşulu: en az 200 pozitif
    e.validation_market[keys[2]]["modeller"][mv]["ece"] = 0.03  # ECE ≤ 0,02
    e.apply_validation_rule()
    assert e.validated_market == {k: False for k in keys}


def test_walk_forward_market_columns_are_the_scaled_model(big):
    from bahis_tahmin.goals.engine import with_market_odds
    from bahis_tahmin.goals.features import build_goal_features
    from bahis_tahmin.goals.model import GoalModel
    from bahis_tahmin.goals.validation import season_year, walk_forward

    m, e = big
    feat, _ = build_goal_features(m)
    f = with_market_odds(feat, m)
    assert f.index.equals(feat.index) and f["o_o25"].notna().all()
    f.loc[f.index[-5:], "o_o25"] = np.nan  # oranı olmayan satırlar: piyasa sütunu boş
    y = int(season_year(f["date"]).max())
    pred, _ = walk_forward(f, [y], ["M0_taban", e.variant], market=True)
    mv = f"{e.variant}{MARKET_SUFFIX}"
    assert np.isnan(pred[f"{mv}:B"].to_numpy()[-5:]).all()
    yrs = season_year(f["date"])
    train, test = f[(yrs < y) & (yrs > 2002)], f[yrs == y].iloc[:30]
    mod = GoalModel(e.variant).fit(train)
    pm = market_prob(test["o_o25"], test["o_u25"])
    ref = mod.predict(scaled(test, market_scale(mod, test, pm)))
    np.testing.assert_allclose(pred[f"{mv}:B"].to_numpy()[:30], ref["B"], rtol=1e-10)
    np.testing.assert_allclose(pred[f"{mv}:C"].to_numpy()[:30], ref["C"], rtol=1e-10)


def test_research_tool_and_app_use_the_same_method(big):
    spec = importlib.util.spec_from_file_location("piyasa_duzey", ROOT / "tools" / "research" / "piyasa_duzey.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    _, e = big
    X = _feature_row(e, *sorted(e.states["T1"].elo.cur_teams)[:2])
    for p_m in (0.4, 0.62):
        assert tool.market_scale(e.model, X, [p_m])[0] == pytest.approx(market_scale(e.model, X, [p_m])[0], rel=1e-12)
    assert (tool.S_LO, tool.S_HI, tool.S_ITERS, tool.RATE_COLS) == (0.25, 4.0, 30, ("l1h", "l1a", "l2h", "l2a", "lh",
                                                                                     "la"))


def test_forecast_protocol_ignores_fixture_odds(eng, teams, monkeypatch):
    """İleriye dönük ölçüm protokolü temel modelin tahminlerini ölçer: fikstür oranları tahmine girmez."""
    import bahis_tahmin.goals.service as S
    from bahis_tahmin.goals import forecast_log as F

    seen = []
    real = S.gated_goal_predictions

    def spy(engine, ctx, fixtures, as_of, **kw):
        if fixtures is not None:
            seen.append(set(fixtures.columns))
        return real(engine, ctx, fixtures, as_of, **kw)

    monkeypatch.setattr(S, "gated_goal_predictions", spy)
    fx = pd.DataFrame([{"league": "T1", "date": pd.Timestamp("2026-11-20"), "time": "", "home": teams[0],
                        "away": teams[1], "source": "x", "o_o25": 1.7, "o_u25": 2.2}])
    F.build_forecast_records(eng, fx, recent_synthetic(), now=AS_OF)
    assert seen and all("o_o25" not in c and "o_u25" not in c for c in seen)


# ------------------------------------------------------------------------------------------------- kupa
def test_cup_market_level_scales_goal_expectations():
    from kupa_yardim import CUP_DAY, world

    from bahis_tahmin.kupa.gorunum import goal_model_card
    from bahis_tahmin.kupa.motor import CupEngine

    on = CupEngine()
    on.train(*world())
    args = ("UCL", "İngiltere|Arsenal", "Türkiye|Galatasaray", "Arsenal", "Galatasaray", "İngiltere", "Türkiye",
            pd.Timestamp(CUP_DAY), "21:00", False, "espn")
    p0 = on.predict_goals(*args)
    ml = from_odds(1.55, 2.5, "girilen oran")
    p1 = on.predict_goals(*args, market=ml)
    lam, nu = p0.info["lam"], p0.info["nu"]
    k = p1.info["piyasa"]["olcek"]
    assert k == pytest.approx(poisson_scale(lam + nu, ml.p))
    m = k * (lam + nu)
    assert 1 - np.exp(-m) * (1 + m + m * m / 2) == pytest.approx(ml.p, abs=1e-8)
    assert abs(k - 1) > 0.02 and np.sign(p1.probs["B"] - p0.probs["B"]) == np.sign(k - 1)
    assert np.sign(p1.probs["C"] - p0.probs["C"]) == np.sign(k - 1)
    assert p1.info["model_version"].endswith(MARKET_SUFFIX)
    # Belirsizlik aralığı da aynı ölçekle (aynı tohum: ölçeksiz aralıktan farklı ve aynı yönde kaymış)
    lo0, hi0 = p0.intervals["FT_OVER_3_5"]
    lo1, hi1 = p1.intervals["FT_OVER_3_5"]
    assert np.sign(lo1 - lo0) == np.sign(k - 1) and np.sign(hi1 - hi0) == np.sign(k - 1)
    assert p1.info["piyasa"]["kupa_sinanmadi"] and p1.validated == p0.validated
    card = goal_model_card(p1, on)
    assert "SINANMADI" in card["version"] and "2,5 Üst/Alt oranı" in card["inputs"]
    assert "SINANMADI" not in goal_model_card(p0, on)["version"]
    q = on.market_prediction(p0, ml)
    assert q.probs == p1.probs and q.kickoff_text == p0.kickoff_text
    assert json.dumps(p1.info["piyasa"])  # kayda yazılabilir

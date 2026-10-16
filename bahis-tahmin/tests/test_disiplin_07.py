"""DISIPLIN-07: bahis disiplini — defter düzeyi portföy kuralları, stake yöntemi (sabit / kesirli Kelly) ve önceden
yazılmış gerçek para hazırlık ölçütü. Elle kurulmuş kayıtlar; ağ yok."""

from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from bahis_tahmin.goals.decision import Decision, DecisionPolicy
from bahis_tahmin.goals.disiplin import (
    FLAT_VERSION,
    HAZIRLIK_KURALI,
    HAZIRLIK_SHA256,
    MIN_CLV,
    MIN_SETTLED,
    SANAL_KASA,
    Staking,
    match_day,
    portfolio_block,
    readiness,
    readiness_text,
    rule_fingerprint,
    virtual_bankroll,
)
from bahis_tahmin.goals.ledger import Ledger, event_id
from bahis_tahmin.goals.service import ledger_rows, record_decisions

ROOT = Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
ENG = SimpleNamespace(variant="t", data_cutoff="2026-10-16")


def _pred(home, away, league="E0", day="2026-10-17", hour=18):
    d = pd.Timestamp(day)
    return SimpleNamespace(event_id=event_id(league, d.date(), home, away), league=league, home=home, away=away,
                           date=d, kickoff_utc=dt.datetime.combine(d.date(), dt.time(hour), UTC), info={})


def _dec(pred, market="FT_OVER_3_5", status="VALUE_CANDIDATE", p=0.5, p_safe=0.46, odds=2.4):
    return Decision(event_id=pred.event_id, market_key=market, status=status, reasons=[], p=p, p_safe=p_safe,
                    fair_odds=1 / p, odds=odds, breakeven=1 / odds, ev=p * odds - 1, ev_safe=p_safe * odds - 1,
                    min_odds=None, no_vig=None, policy_version="t", decision_time=NOW.isoformat(),
                    data_eligibility={"tahmin_uygun": True, "bahis_veri_uygun": True})


@pytest.fixture
def led(tmp_path):
    lg = Ledger(tmp_path / "l.sqlite")
    yield lg
    lg.close()


def _bets(led):
    return [r for r in led.predictions() if (r.get("stake_units") or 0) > 0]


# ------------------------------------------------------------------------------------------------ ön kayıt
def test_rule_is_preregistered_and_fingerprinted():
    assert rule_fingerprint() == HAZIRLIK_SHA256
    doc = (ROOT / "docs" / "DISIPLIN_07.md").read_text(encoding="utf-8")
    assert HAZIRLIK_SHA256 in doc
    for line in HAZIRLIK_KURALI.strip().splitlines():  # kural metni belgede aynen
        assert line.strip() in doc, line
    assert (MIN_SETTLED, MIN_CLV) == (200, 100)


# ------------------------------------------------------------------------------------------------ portföy
def test_one_virtual_bet_per_match_across_records(led):
    a = _pred("Arsenal", "Chelsea")
    record_decisions(led, a, [_dec(a, "FT_OVER_3_5"), _dec(a, "FH_OVER_1_5")], ENG, record_time=NOW)
    bets = _bets(led)
    assert len(bets) == 1 and bets[0]["market_key"] == "FT_OVER_3_5"  # aynı işlemde ikinci aday stake almaz
    second = [r for r in led.predictions() if r["market_key"] == "FH_OVER_1_5"][0]
    assert second["kayit_turu"] == "KARAR_KAYDI" and second["stake_units"] == 0.0
    assert any("zaten sanal bahis" in x for x in second["reasons"])
    # Daha sonraki bir kayıt işleminde aynı maça (başka pazar) yine stake yok
    record_decisions(led, a, [_dec(a, "BTTS_BOTH_HALVES_YES")], ENG, record_time=NOW + dt.timedelta(minutes=5))
    assert len(_bets(led)) == 1
    last = led.predictions()[-1]
    assert last["stake_units"] == 0.0 and any("zaten sanal bahis" in x for x in last["reasons"])
    assert last["decision_status"] == "VALUE_CANDIDATE"  # karar değişmez; yalnızca stake konmaz
    # Avantaj adayı olmayan kararlar ve stake'siz kayıtlar sınırları doldurmaz
    b = _pred("Everton", "Fulham")
    record_decisions(led, b, [_dec(b, "FT_OVER_3_5", status="NO_VALUE")], ENG, record_time=NOW)
    record_decisions(led, b, [_dec(b, "FT_OVER_3_5")], ENG, record_time=NOW)
    assert len(_bets(led)) == 2


def test_day_and_league_day_limits_count_earlier_records(led):
    pol = DecisionPolicy(max_candidates_per_day=3, max_candidates_per_league_day=2)
    for i, lg in enumerate(["E0", "E0", "E0", "SP1", "SP1"]):
        p = _pred(f"H{i}", f"A{i}", league=lg)
        record_decisions(led, p, [_dec(p)], ENG, record_time=NOW, policy=pol)
    recs = led.predictions()
    assert [r["stake_units"] > 0 for r in recs] == [True, True, False, True, False]
    assert any("Aynı lig ve maç gününde zaten 2" in x for x in recs[2]["reasons"])
    assert any("Bu maç gününde zaten 3" in x for x in recs[4]["reasons"])
    # Başka maç günü ayrı sayılır
    p = _pred("H9", "A9", day="2026-10-18")
    record_decisions(led, p, [_dec(p)], ENG, record_time=NOW, policy=pol)
    assert led.predictions()[-1]["stake_units"] == 1.0 and led.predictions()[-1]["mac_gunu"] == "2026-10-18"
    # Varsayılan politika: karar motorunun sınırlarıyla aynı (günde 10, lig-günde 3)
    assert (DecisionPolicy().max_candidates_per_day, DecisionPolicy().max_candidates_per_league_day) == (10, 3)


def test_legacy_records_count_by_kickoff_day(led):
    led.record_prediction({"event_id": "E0|2026-10-17|X|Y", "league": "E0", "kickoff": "2026-10-17T18:00:00+00:00",
                           "market_key": "FT_OVER_3_5", "decision_time": NOW.isoformat(), "model_version": "t",
                           "feature_version": "t", "data_cutoff": "t", "p": 0.5, "odds": 2.0,
                           "decision_status": "VALUE_CANDIDATE", "reasons": [], "stake_units": 1.0,
                           "strategy_version": FLAT_VERSION})
    old = led.predictions()[0]
    assert match_day(old) == "2026-10-17"
    assert portfolio_block([old], "E0|2026-10-17|Q|W", "E0", "2026-10-17",
                           DecisionPolicy(max_candidates_per_league_day=1)) is not None
    assert portfolio_block([old], "E0|2026-10-17|Q|W", "SP1", "2026-10-17",
                           DecisionPolicy(max_candidates_per_league_day=1)) is None
    assert portfolio_block([old], "E0|2026-10-17|X|Y", "E0", "2026-10-18") is not None  # aynı maç


# ------------------------------------------------------------------------------------------------ stake
def test_flat_staking_is_the_default(led):
    a = _pred("Arsenal", "Chelsea")
    record_decisions(led, a, [_dec(a), _dec(a, "FH_UNDER_1_5", status="NO_VALUE")], ENG, record_time=NOW)
    bet, other = led.predictions()
    assert bet["stake_units"] == 1.0 and bet["strategy_version"] == FLAT_VERSION == "sanal-sabit-birim-v1"
    assert bet["stake_yontemi"] == "sabit" and bet["sanal_kasa"] == SANAL_KASA
    assert bet["disiplin_version"] == "disiplin-v1" and bet["mac_gunu"] == "2026-10-17"
    assert "stake_yontemi" not in other and other["stake_units"] == 0.0
    assert ledger_rows(led)[0]["Sanal birim"] == 1.0


def test_fractional_kelly_uses_safe_probability_cap_and_bankroll(led):
    k = Staking("kelly", fraction=0.25, cap=0.05)
    a = _pred("Arsenal", "Chelsea")
    record_decisions(led, a, [_dec(a, p_safe=0.46, odds=2.4)], ENG, record_time=NOW, staking=k)
    r = led.predictions()[0]
    f = 0.25 * (0.46 * 2.4 - 1) / 1.4
    assert r["stake_units"] == pytest.approx(100 * f, abs=1e-4)
    assert r["strategy_version"] == "sanal-kesirli-kelly-v1 (kesir 0.25, tavan 0.05)" and r["stake_yontemi"] == "kelly"
    led.record_outcome(r["id"], "LOSS", "NO", "test")
    assert virtual_bankroll(led.predictions()) == pytest.approx(100 - 100 * f, abs=1e-4)
    # Kasa küçülünce stake da küçülür; tavan: tek bahiste kasanın en fazla %5'i
    b = _pred("Everton", "Fulham")
    record_decisions(led, b, [_dec(b, p_safe=0.8, odds=2.4)], ENG, record_time=NOW, staking=k)
    r2 = led.predictions()[-1]
    assert r2["stake_units"] == pytest.approx(0.05 * (100 - 100 * f), abs=1e-4)
    assert r2["sanal_kasa"] == pytest.approx(100 - 100 * f, abs=1e-4)
    # Kasa tükendiyse stake yok (gerekçeli)
    d = _dec(b)
    assert k.stake(d, 0.0) == 0.0 and k.stake(d, -5.0) == 0.0 and Staking().stake(d, -5.0) == 1.0
    assert Staking("kelly").stake(_dec(b, p_safe=float("nan")), 100.0) == 0.0


def test_settings_choose_the_method(tmp_home):
    from bahis_tahmin.config import Settings

    s = Settings()
    assert Staking.from_settings(s).method == "sabit"
    s.sanal_stake_yontemi, s.kelly_fraction, s.max_stake_pct = "kelly", 0.5, 0.02
    k = Staking.from_settings(s)
    assert (k.method, k.fraction, k.cap) == ("kelly", 0.5, 0.02)
    s.sanal_stake_yontemi = "martingale"
    s.validate()
    assert s.sanal_stake_yontemi == "sabit"


# ------------------------------------------------------------------------------------------------ hazırlık
def _fill(led, results, odds=2.0, stakes=None, clv_n=0, close=1.9, close_opp=1.95, start=0):
    """Sonuçlanmış sanal bahisler: ``results`` 'WIN'/'LOSS'/'VOID'/None (bekleyen); ilk ``clv_n`` bahiste kapanış oranı."""
    kick = dt.datetime(2026, 10, 17, 18, 0, tzinfo=UTC)
    for j, res in enumerate(results):
        i = start + j
        ev = f"E0|2026-10-17|H{i}|A{i}"
        pid = led.record_prediction({
            "event_id": ev, "league": "E0", "kickoff": kick.isoformat(), "market_key": "FT_OVER_3_5",
            "decision_time": (NOW + dt.timedelta(seconds=i)).isoformat(), "model_version": "t", "feature_version": "t",
            "data_cutoff": "t", "p": 0.55, "odds": odds, "decision_status": "VALUE_CANDIDATE", "reasons": [],
            "stake_units": stakes[j] if stakes else 1.0, "strategy_version": FLAT_VERSION})
        if res:
            led.record_outcome(pid, res, "YES" if res == "WIN" else "NO", "test")
        if j < clv_n:
            c = close + (0.02 if j % 2 else -0.02)
            led.record_closing(ev, "FT_OVER_3_5", c, kick - dt.timedelta(minutes=30), "B", "manuel", close_opp)


def _cond(r):
    return {k: ok for k, ok, _ in r["conditions"]}


def test_empty_ledger_is_not_ready():
    r = readiness(None)
    assert not r["ok"] and r["settled"] == 0 and _cond(r)["zincir"] and not _cond(r)["sonuclanan"]
    t = readiness_text(r)
    assert "karşılanmadı (2/6)" in t and "sanal takibe devam edin" in t and "0/200" in t


def test_all_six_conditions_met(led):
    res = ["WIN"] * 110 + ["LOSS"] * 90
    rng = np.random.default_rng(0)
    rng.shuffle(res)
    _fill(led, list(res), clv_n=120)
    _fill(led, ["VOID", None, None], start=500)  # iade ve bekleyen: paydaya girmez
    r = readiness(led)
    assert r["settled"] == 200 and r["clv_n"] == 120 and r["clv_alt"] > 0
    assert r["yield"] == pytest.approx(0.10) and r["ok"], r["conditions"]
    x = np.array([1.0 if v == "WIN" else -1.0 for v in res])
    assert r["yield_ust"] == pytest.approx(x.mean() + 1.96 * x.std(ddof=1) / math.sqrt(len(x)), rel=1e-9)
    assert "KARŞILANDI (6/6)" in readiness_text(r) and "kâr garantisi değildir" in readiness_text(r)


@pytest.mark.parametrize("case", ["az_bahis", "az_clv", "clv_negatif", "zararda", "dusus"])
def test_each_condition_can_fail(led, case):
    res = ["WIN", "LOSS"] * 100
    kw = {"clv_n": 120}
    if case == "az_bahis":
        res = res[:199]
    elif case == "az_clv":
        kw["clv_n"] = MIN_CLV - 1
    elif case == "clv_negatif":
        kw.update(close=2.2, close_opp=1.7)  # kapanış alınan orandan yüksek: CLV negatif
    elif case == "zararda":
        res = ["LOSS"] * 140 + ["WIN"] * 60  # yield −%40
    elif case == "dusus":
        res = ["LOSS", "WIN"] * 50 + ["LOSS"] * 30 + ["WIN"] * 30 + ["WIN", "LOSS"] * 20  # zirve 100'den 70'e
    _fill(led, res, **kw)
    r = readiness(led)
    failed = {k for k, ok in _cond(r).items() if not ok}
    expect = {"az_bahis": {"sonuclanan"}, "az_clv": {"clv_n"}, "clv_negatif": {"clv_alt"},
              "zararda": {"getiri_ust", "dusus"}, "dusus": {"dusus"}}[case]
    assert failed == expect and not r["ok"]
    if case == "dusus":
        assert r["drawdown"] == pytest.approx(0.30)  # tam %30: "< %30" sağlanmaz


def test_drawdown_just_below_limit_passes(led):
    _fill(led, ["LOSS", "WIN"] * 50 + ["LOSS"] * 29 + ["WIN"] * 29 + ["WIN", "LOSS"] * 21, clv_n=120)
    r = readiness(led)
    assert r["drawdown"] == pytest.approx(0.29) and _cond(r)["dusus"]


def test_variable_stakes_use_ratio_estimator(led):
    rng = np.random.default_rng(4)
    stakes = list(rng.uniform(0.5, 3.0, 60))
    res = list(rng.choice(["WIN", "LOSS"], 60))
    _fill(led, res, odds=2.1, stakes=stakes)
    r = readiness(led)
    s = np.array(stakes)
    net = np.where(np.array(res) == "WIN", s * 1.1, -s)
    y = net.sum() / s.sum()
    n = len(s)
    hi = y + 1.96 * math.sqrt(n / (n - 1) * ((net - y * s) ** 2).sum()) / s.sum()
    assert r["yield"] == pytest.approx(y) and r["yield_ust"] == pytest.approx(hi)
    k = SANAL_KASA + np.cumsum(net)
    peak = np.maximum.accumulate(np.concatenate([[SANAL_KASA], k]))[1:]
    assert r["drawdown"] == pytest.approx(max(0.0, ((peak - k) / peak).max()))


def test_broken_chain_fails_readiness(tmp_path):
    p = tmp_path / "l.sqlite"
    lg = Ledger(p)
    _fill(lg, ["WIN", "LOSS"] * 90 + ["WIN"] * 20, clv_n=120)
    assert readiness(lg)["ok"]
    lg.close()
    con = sqlite3.connect(p)
    seq, payload = con.execute("SELECT seq, payload FROM predictions ORDER BY seq LIMIT 1").fetchone()
    rec = json.loads(payload)
    rec["model_version"] = "sonradan-degisti"
    con.execute("DROP TRIGGER predictions_no_update")  # dosyanın uygulama dışında değiştirilmesi
    con.execute("UPDATE predictions SET payload=? WHERE seq=?", (json.dumps(rec), seq))
    con.commit()
    con.close()
    lg = Ledger(p)
    r = readiness(lg)
    lg.close()
    assert {k for k, ok in _cond(r).items() if not ok} == {"zincir"}  # yalnızca zincir bozuk
    assert not r["ok"] and "BOZUK" in readiness_text(r)

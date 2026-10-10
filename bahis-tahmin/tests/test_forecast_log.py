"""İleriye dönük ölçüm kaydı (FORECAST_RECORD): bahis adayı olmadan tahmin kaydı, uygunluk nedenleri, zaman kuralları,
değişmezlik, geçersiz ilan, sonuçlandırma ve değerlendirme.

YALNIZCA sentetik (açıkça test amaçlı) veri ve geçici dizinler kullanılır; kullanıcı defterine veya gerçek veriye
dokunulmaz. Gerçek fikstür entegrasyonu bu testlerle DOĞRULANMIŞ sayılmaz (yalnızca kod yolu).
"""

import datetime as dt
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from bahis_tahmin.goals import forecast_log as F
from bahis_tahmin.goals.engine import GoalEngine
from bahis_tahmin.goals.ledger import Ledger, event_id
from bahis_tahmin.goals.markets import MARKETS, PRIMARY_YES
from bahis_tahmin.goals.service import SELECTIONS, decisions_for, record_decisions, settle_pending
from bahis_tahmin.goals.value import OddsQuote
from bahis_tahmin.selftest import synthetic_matches

UTC = dt.timezone.utc
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ht_matches():
    return synthetic_matches(n_seasons=8, n_teams=16, seed=1, half_time=True)


@pytest.fixture(scope="module")
def engine(ht_matches):
    eng = GoalEngine()
    eng.train(ht_matches)
    return eng


def _future_fixtures(ht_matches, days=3, n=4):
    fx = ht_matches.tail(n)[["league", "date", "time", "home", "away", "source"]].copy()
    fx["date"] = pd.Timestamp(dt.date.today() + dt.timedelta(days=days))
    fx["time"] = ""
    fx["source"] = "TEST-FIKSTUR"
    return fx.reset_index(drop=True)


def _fresh(fx):
    return {lg: 0 for lg in fx["league"].unique()}  # kaynak "eksik oynanmış maç yok" diyor (test girdisi)


def test_forecasts_are_recorded_without_any_bet_candidate(engine, ht_matches, tmp_path):
    fx = _future_fixtures(ht_matches)
    recs = F.build_forecast_records(engine, fx, ht_matches, missing_played=_fresh(fx))
    assert len(recs) == len(fx) * 3
    ok = [r for r in recs if r["decision_status"] == F.STATUS_FORECAST]
    assert ok, "uygun maçlar için tahmin üretilmeli"
    for r in ok:
        assert r["kayit_turu"] == F.RECORD_FORECAST and r["stake_units"] == 0.0
        assert 0 < r["p"] < 1 and r["market_key"] in PRIMARY_YES
        for k in ("event_id", "hedef_karar_ani", "baslama_saati_biliniyor", "data_cutoff", "model_version",
                  "feature_version", "model_kohort", "p_low", "p_high", "oran", "veri_kalitesi", "reasons",
                  "fikstur_kaynagi", "protokol_sha256"):
            assert k in r
        assert r["ekonomik_statu"] == "ORAN_YOK"  # gerçek oran yok → ekonomik değerlendirme yok
    led = Ledger(tmp_path / "l.sqlite")
    res = F.record_forecasts(led, recs)
    assert res["yazilan"] == len(recs)
    s = led.summary()
    assert s["sanal_bahis"] == 0 and s["kayit"] == len(recs)  # bahis adayı sıfır, tahmin kaydı var
    led.close()


def test_no_forecast_reasons_are_recorded(engine, ht_matches):
    fx = _future_fixtures(ht_matches, n=2)
    by_reason = {}
    for recs in (F.build_forecast_records(None, fx, ht_matches, missing_played=_fresh(fx)),
                 F.build_forecast_records(engine, fx.assign(league="XX"), ht_matches),
                 F.build_forecast_records(engine, fx, ht_matches, missing_played={lg: 3 for lg in fx["league"]}),
                 F.build_forecast_records(engine, fx.assign(home="Bilinmeyen Takım"), ht_matches,
                                          missing_played=_fresh(fx))):
        for r in recs:
            assert r["decision_status"] == F.STATUS_NO_FORECAST and r["p"] is None and r["reasons"]
            by_reason.setdefault(r["reasons"][0], 0)
            by_reason[r["reasons"][0]] += 1
    assert {"MODEL_YOK", "LIG_MODEL_KAPSAMI_DISI", "VERI_GUNCEL_DEGIL", "TAKIM_GECMISI_YETERSIZ"} <= set(by_reason)
    # kaynak oynanmış maçları listelemiyorsa gün kuralı (son kayıtlı lig maçı ile karar günü arası ≤ 21 gün)
    today = pd.Timestamp(dt.date.today())
    old_data = ht_matches[ht_matches["date"] < today - pd.Timedelta(days=60)]
    recs = F.build_forecast_records(engine, fx, old_data)
    assert recs and all(r["reasons"] and r["reasons"][0] == "VERI_GUNCEL_DEGIL" for r in recs)
    recent = ht_matches[ht_matches["date"] < today - pd.Timedelta(days=5)]
    recs = F.build_forecast_records(engine, fx, recent)
    assert all(not r["reasons"] or r["reasons"][0] != "VERI_GUNCEL_DEGIL" for r in recs)


def test_past_or_known_matches_are_not_forward_records(engine, ht_matches):
    past = _future_fixtures(ht_matches, days=-1, n=1)
    r = F.build_forecast_records(engine, past, ht_matches, missing_played=_fresh(past))
    assert {x["reasons"][0] for x in r} == {"PENCERE_KACIRILDI"} and all(x["p"] is None for x in r)
    fut = _future_fixtures(ht_matches, n=1)
    known = pd.concat([ht_matches, fut.assign(fthg=1, ftag=0, hthg=0.0, htag=0.0)], ignore_index=True)
    r = F.build_forecast_records(engine, fut, known, missing_played=_fresh(fut))
    assert {x["reasons"][0] for x in r} == {"MAC_SONUCU_BILINIYOR"}
    freeze_day = F.freeze_time().astimezone(F.ISTANBUL).date()
    old = fut.assign(date=pd.Timestamp(freeze_day))
    now = F.decision_target(freeze_day) - dt.timedelta(hours=1)
    r = F.build_forecast_records(engine, old, ht_matches, now=now, missing_played=_fresh(old))
    assert {x["reasons"][0] for x in r} == {"PROTOKOLDEN_ONCE"}


def test_write_time_rechecks_the_decision_window(engine, ht_matches, tmp_path, monkeypatch):
    fx = _future_fixtures(ht_matches, n=1)
    recs = F.build_forecast_records(engine, fx, ht_matches, missing_played=_fresh(fx))
    assert any(r["p"] is not None for r in recs)
    late = dt.datetime.fromisoformat(recs[0]["hedef_karar_ani"]) + dt.timedelta(hours=1)
    monkeypatch.setattr(F, "_now", lambda: late)
    led = Ledger(tmp_path / "l.sqlite")
    res = F.record_forecasts(led, recs)
    assert res["gec_kalan"] == sum(r["p"] is not None for r in recs)
    assert all(r["p"] is None and r["reasons"][0] == "PENCERE_KACIRILDI" for r in led.predictions())
    led.close()


def test_recorded_forecasts_never_change_silently(engine, ht_matches, tmp_path):
    fx = _future_fixtures(ht_matches, n=1)
    recs = F.build_forecast_records(engine, fx, ht_matches, missing_played=_fresh(fx))
    led = Ledger(tmp_path / "l.sqlite")
    F.record_forecasts(led, recs)
    before = json.dumps(led.predictions(), sort_keys=True, default=str)
    again = F.record_forecasts(led, F.build_forecast_records(engine, fx, ht_matches, missing_played=_fresh(fx)))
    assert again["yazilan"] == 0 and again["atlanan_mukerrer"] == len(recs)  # aynı maç/pazar/kohort tekrar yazılmaz
    with pytest.raises(sqlite3.DatabaseError):
        led.conn.execute("UPDATE predictions SET payload = '{}' WHERE seq = 1")
    with pytest.raises(sqlite3.DatabaseError):
        led.conn.execute("DELETE FROM predictions WHERE seq = 1")
    target = next(r for r in led.predictions() if r["p"] is not None)
    F.invalidate_forecast(led, target["id"], "test: veri hatası bildirimi")
    with pytest.raises(ValueError):
        F.invalidate_forecast(led, target["id"], "")
    after = [r for r in led.predictions() if r.get("kayit_turu") == F.RECORD_FORECAST]
    assert json.dumps(after, sort_keys=True, default=str) == before  # orijinal kayıtlar aynen
    ok, _ = led.verify_chain()
    assert ok
    led.close()


def test_settlement_and_evaluation_by_cohort(engine, ht_matches, tmp_path):
    fx = _future_fixtures(ht_matches, n=4)
    recs = F.build_forecast_records(engine, fx, ht_matches, missing_played=_fresh(fx))
    recs += F.build_forecast_records(None, fx, ht_matches, missing_played=_fresh(fx))  # olasılıksız kayıtlar
    led = Ledger(tmp_path / "l.sqlite")
    F.record_forecasts(led, recs)
    res = fx.assign(fthg=3, ftag=2, hthg=1.0, htag=1.0)
    out = settle_pending(led, res)
    n_fc = sum(r["p"] is not None for r in recs)
    assert out["sonuclanan"] == n_fc  # TAHMIN_YOK kayıtları sonuçlandırılmaz
    ev = F.evaluate_forecasts(led)
    assert ev["kapsam"][F.STATUS_FORECAST] == n_fc and ev["kapsam"]["MODEL_YOK"] == len(fx) * 3
    rows = [r for r in ev["kohort_pazar"] if not r["gecersiz_ilanlar_haric"]]
    assert {r["pazar"] for r in rows} == set(PRIMARY_YES)
    for r in rows:
        assert r["sonuclanan"] == len(fx) and r["resmi_degerlendirme_esigi"] is False
        assert r["ekonomik_statu"] == "ROI_UNAVAILABLE"
        assert r["delta_ll_tanimi"].startswith("model − referans")
    led.close()


def test_unverified_odds_never_get_economic_status(engine, ht_matches, tmp_path):
    fx = _future_fixtures(ht_matches, n=1)
    led = Ledger(tmp_path / "l.sqlite")
    eid = event_id(fx.loc[0, "league"], fx.loc[0, "date"], fx.loc[0, "home"], fx.loc[0, "away"])
    target = F.decision_target(fx.loc[0, "date"])
    m = MARKETS["FT_OVER_3_5"]
    t0 = dt.datetime.now(UTC) - dt.timedelta(minutes=5)
    led.add_odds([OddsQuote(eid, "FT_OVER_3_5", m.period, m.line, m.selection, "manuel", "test", 2.4, t0, t0)])
    recs = F.build_forecast_records(engine, fx, ht_matches, ledger=led, missing_played=_fresh(fx))
    over = next(r for r in recs if r["market_key"] == "FT_OVER_3_5")
    assert over["p"] is not None
    assert over["oran"]["zaman_dogrulandi"] is True and over["ekonomik_statu"] == "ZAMANI_DOGRULANMIS_ORAN"
    assert dt.datetime.fromisoformat(over["oran"]["quoted_at"]) < target
    # geçerlilik anı karar anından önce ama sisteme karar anından SONRA alınmış (ör. sonradan elle girilmiş) oran
    m_c = MARKETS["FH_OVER_1_5"]
    led.add_odds([OddsQuote(eid, "FH_OVER_1_5", m_c.period, m_c.line, m_c.selection, "manuel", "test", 2.2, t0,
                            target + dt.timedelta(hours=1))])
    fh = next(r for r in F.build_forecast_records(engine, fx, ht_matches, ledger=led, missing_played=_fresh(fx))
              if r["market_key"] == "FH_OVER_1_5")
    assert fh["oran"]["zaman_dogrulandi"] is False and fh["ekonomik_statu"] == "HISTORICAL_REFERENCE_ONLY"
    # zamanı bilinmeyen oran (ör. tarihsel CSV) → ekonomik doğrulamaya girmez
    other = [dict(r, oran={"decimal_odds": 2.0, "kaynak": "tarihsel CSV"}) for r in recs if r["p"] is not None]
    F.record_forecasts(led, other)
    settle_pending(led, fx.assign(fthg=3, ftag=2, hthg=1.0, htag=1.0))
    for row in F.evaluate_forecasts(led)["kohort_pazar"]:
        if row["pazar"] != "FT_OVER_3_5" and row.get("sonuclanan"):
            assert row["zamani_dogrulanmis_oranli"] == 0 and row["ekonomik_statu"] == "ROI_UNAVAILABLE"
    led.close()


def test_bet_candidate_records_are_separate_from_decisions(engine, ht_matches, tmp_path):
    fx = _future_fixtures(ht_matches, n=1)
    pred = engine.predict_fixtures(fx)[0]
    now = dt.datetime.now(UTC)
    led = Ledger(tmp_path / "l.sqlite")
    record_decisions(led, pred, decisions_for(pred, engine, led, now), engine)
    for r in led.predictions():
        assert r["kayit_turu"] == (F.RECORD_BET if r["decision_status"] == "VALUE_CANDIDATE" else F.RECORD_DECISION)
    assert len(led.predictions()) == len(SELECTIONS)
    led.close()


def test_missing_played_matches_from_open_fixture_file(ht_matches):
    lg = ht_matches["league"].iloc[0]
    last = pd.Timestamp(ht_matches.loc[ht_matches["league"] == lg, "date"].max())
    doc = {"matches": [
        {"date": str((last + pd.Timedelta(days=7)).date()), "team1": "A", "team2": "B", "score": {"ft": [1, 0]}},
        {"date": str((last + pd.Timedelta(days=8)).date()), "team1": "C", "team2": "D", "score": {"ft": [2, 2]}},
        {"date": str((last + pd.Timedelta(days=30)).date()), "team1": "A", "team2": "C"},
        {"date": str(last.date()), "team1": "X", "team2": "Y", "score": {"ft": [0, 0]}},
    ]}
    assert F.missing_played_openfootball(json.dumps(doc).encode(), ht_matches, lg) == 2
    assert F.missing_played_openfootball(b"{bozuk", ht_matches, lg) is None


def test_model_cohorts_are_not_pooled(engine, ht_matches, tmp_path):
    fx = _future_fixtures(ht_matches, n=2)
    led = Ledger(tmp_path / "l.sqlite")
    F.record_forecasts(led, F.build_forecast_records(engine, fx, ht_matches, missing_played=_fresh(fx)))
    old = engine.trained_at
    engine.trained_at = "2000-01-01T00:00:00"  # yeniden eğitilmiş başka sürüm gibi
    try:
        F.record_forecasts(led, F.build_forecast_records(engine, fx, ht_matches, missing_played=_fresh(fx)))
    finally:
        engine.trained_at = old
    cohorts = {r["model_kohort"] for r in led.predictions() if r.get("p") is not None}
    assert len(cohorts) == 2
    settle_pending(led, fx.assign(fthg=1, ftag=1, hthg=0.0, htag=1.0))
    rows = [r for r in F.evaluate_forecasts(led)["kohort_pazar"] if not r["gecersiz_ilanlar_haric"]]
    assert {r["kohort"] for r in rows} == cohorts and all(r["sonuclanan"] == len(fx) for r in rows)
    led.close()


def test_protocol_is_frozen_and_matches_the_report_copy():
    assert F.PROTOCOL_FROZEN["govde_sha256"] == F.protocol_sha256(), "protokol gövdesi dondurmadan sonra değişmiş"
    frozen = dt.datetime.fromisoformat(F.PROTOCOL_FROZEN["dondurma_zamani_utc"])
    assert frozen.tzinfo is not None
    doc = json.loads((REPO / "reports" / "kabul_s2_01" / "ileriye_donuk_protokol_v1.json").read_text(encoding="utf-8"))
    assert doc == json.loads(json.dumps(F.protocol_document(), ensure_ascii=False))

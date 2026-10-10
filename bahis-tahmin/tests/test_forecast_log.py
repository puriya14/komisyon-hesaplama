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
from uygunluk_yardim import AS_OF, FIXTURE_DAY, full_context, recent_synthetic

UTC = dt.timezone.utc
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ht_matches():
    return recent_synthetic()


@pytest.fixture(scope="module")
def engine(ht_matches):
    eng = GoalEngine()
    eng.train(ht_matches)
    return eng


@pytest.fixture(scope="module")
def ctx(ht_matches, engine):
    return full_context(ht_matches, engine, AS_OF, FIXTURE_DAY)


def _future_fixtures(ht_matches, days=0, n=4):
    """Farklı takımlardan ``n`` sentetik yaklaşan maç (FIXTURE_DAY + days)."""
    teams = sorted(set(ht_matches["home"]))
    rows = [{"league": "T1", "date": pd.Timestamp(FIXTURE_DAY + dt.timedelta(days=days)), "time": "",
             "home": teams[2 * i], "away": teams[2 * i + 1], "source": "TEST-FIKSTUR"} for i in range(n)]
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    """Yazma anı denetimi de sabit sentetik saatle yapılır (gerçek saatten bağımsız)."""
    monkeypatch.setattr(F, "_now", lambda: AS_OF + dt.timedelta(minutes=1))


def build(engine, fx, matches, ctx=None, **kw):
    kw.setdefault("now", AS_OF)
    return F.build_forecast_records(engine, fx, matches, ctx=ctx, **kw)


def test_forecasts_are_recorded_without_any_bet_candidate(engine, ht_matches, ctx, tmp_path):
    fx = _future_fixtures(ht_matches)
    recs = build(engine, fx, ht_matches, ctx)
    assert len(recs) == len(fx) * 3
    ok = [r for r in recs if r["decision_status"] == F.STATUS_FORECAST]
    assert ok, "uygun maçlar için tahmin üretilmeli"
    for r in ok:
        assert r["kayit_turu"] == F.RECORD_FORECAST and r["stake_units"] == 0.0
        assert 0 < r["p"] < 1 and r["market_key"] in PRIMARY_YES
        for k in ("event_id", "hedef_karar_ani", "baslama_saati_biliniyor", "data_cutoff", "model_version",
                  "feature_version", "model_kohort", "p_low", "p_high", "oran", "veri_kalitesi", "reasons",
                  "fikstur_kaynagi", "protokol_sha256", "hesaplama_ani", "bilgi_kesimi", "veri_uygunlugu"):
            assert k in r
        assert r["protokol"] == F.PROTOCOL_V2_VERSION
        assert r["veri_uygunlugu"]["tahmin_uygun"] is True and r["veri_uygunlugu"]["guncellik"] == "VERIFIED_CURRENT"
        assert r["ekonomik_statu"] == "ORAN_YOK"  # gerçek oran yok → ekonomik değerlendirme yok
    led = Ledger(tmp_path / "l.sqlite")
    res = F.record_forecasts(led, recs)
    assert res["yazilan"] == len(recs)
    s = led.summary()
    assert s["sanal_bahis"] == 0 and s["kayit"] == len(recs)  # bahis adayı sıfır, tahmin kaydı var
    led.close()


def test_no_forecast_reasons_are_recorded(engine, ht_matches, ctx):
    fx = _future_fixtures(ht_matches, n=2)
    # Kaynak takvimi tam; depodan takımın bir maçı çıkarılarak "bilinen eksik" bırakılır
    t = fx.loc[0, "home"]
    last = ht_matches[(ht_matches["home"] == t) | (ht_matches["away"] == t)].index[-3]
    stale = full_context(ht_matches.drop(index=last), engine, AS_OF, FIXTURE_DAY, schedule=ht_matches)
    from bahis_tahmin.eligibility import EligibilityContext, state_view

    by_reason = {}
    for recs in (build(None, fx, ht_matches, full_context(ht_matches, None, AS_OF, FIXTURE_DAY)),
                 build(engine, fx.assign(league="XX"), ht_matches, ctx),
                 build(engine, fx.iloc[[0]], ht_matches.drop(index=last), stale),  # yalnızca etkilenen takımın maçı
                 build(engine, fx, ht_matches, EligibilityContext(ht_matches, state_view(engine))),  # kapsam yok
                 build(engine, fx, ht_matches, None),  # bağlam yok
                 build(engine, fx.assign(home="Bilinmeyen Takım"), ht_matches, ctx)):
        for r in recs:
            assert r["decision_status"] == F.STATUS_NO_FORECAST and r["p"] is None and r["reasons"]
            by_reason.setdefault(r["reasons"][0], 0)
            by_reason[r["reasons"][0]] += 1
    assert {"MODEL_YOK", "LIG_MODEL_KAPSAMI_DISI", "DEPODA_EKSIK_MAC", "KAYNAK_KAPSAMI_YOK", "BAGLAM_YOK",
            "TAKIM_DURUMDA_YOK"} <= set(by_reason), by_reason


def test_unmatched_fixtures_get_candidate_id_records(engine, ht_matches, ctx):
    un = pd.DataFrame([{"league": "T1", "date": pd.Timestamp(FIXTURE_DAY), "time": "", "raw_home": "Takim Zeta FK",
                        "raw_away": "Takım A", "source": "openfootball"}])
    recs = build(engine, _future_fixtures(ht_matches, n=1), ht_matches, ctx, unmatched=un)
    um = [r for r in recs if not r["kanonik_kimlik"]]
    assert len(um) == 3 and {r["market_key"] for r in um} == set(PRIMARY_YES)
    for r in um:
        assert r["event_id"].startswith("aday:") and r["p"] is None and r["reasons"][0] == "TAKIM_ESLESMEDI"
        assert r["home"] == "Takim Zeta FK"  # sahte takım atanmaz; ham ad saklanır
        assert r["veri_uygunlugu"]["kanonik_kimlik"] is False
    # Zaman kuralları eşleşmeyen fikstüre de uygulanır (eşleşmeme ikinci neden)
    freeze_day = F.freeze_time(F.ACTIVE_PROTOCOL).astimezone(F.ISTANBUL).date()
    old = build(engine, pd.DataFrame(), ht_matches, ctx, unmatched=un.assign(date=pd.Timestamp(freeze_day)),
                now=F.decision_target(freeze_day) - dt.timedelta(hours=1))
    assert all(r["reasons"][:2] == ["PROTOKOLDEN_ONCE", "TAKIM_ESLESMEDI"] for r in old)
    late = build(engine, pd.DataFrame(), ht_matches, ctx, unmatched=un,
                 now=F.decision_target(FIXTURE_DAY) + dt.timedelta(hours=1))
    assert all(r["reasons"][:2] == ["PENCERE_KACIRILDI", "TAKIM_ESLESMEDI"] for r in late)


def test_past_or_known_matches_are_not_forward_records(engine, ht_matches, ctx):
    past = _future_fixtures(ht_matches, n=1)
    r = build(engine, past, ht_matches, ctx, now=F.decision_target(FIXTURE_DAY) + dt.timedelta(hours=1))
    assert {x["reasons"][0] for x in r} == {"PENCERE_KACIRILDI"} and all(x["p"] is None for x in r)
    fut = _future_fixtures(ht_matches, n=1)
    known = pd.concat([ht_matches, fut.assign(fthg=1, ftag=0, hthg=0.0, htag=0.0)], ignore_index=True)
    r = build(engine, fut, known, ctx)
    assert {x["reasons"][0] for x in r} == {"MAC_SONUCU_BILINIYOR"}
    freeze_day = F.freeze_time(F.ACTIVE_PROTOCOL).astimezone(F.ISTANBUL).date()
    old = fut.assign(date=pd.Timestamp(freeze_day))
    now = F.decision_target(freeze_day) - dt.timedelta(hours=1)
    r = build(engine, old, ht_matches, ctx, now=now)
    assert {x["reasons"][0] for x in r} == {"PROTOKOLDEN_ONCE"}


def test_write_time_rechecks_the_decision_window(engine, ht_matches, ctx, tmp_path, monkeypatch):
    fx = _future_fixtures(ht_matches, n=1)
    recs = build(engine, fx, ht_matches, ctx)
    assert any(r["p"] is not None for r in recs)
    late = dt.datetime.fromisoformat(recs[0]["hedef_karar_ani"]) + dt.timedelta(hours=1)
    monkeypatch.setattr(F, "_now", lambda: late)
    led = Ledger(tmp_path / "l.sqlite")
    res = F.record_forecasts(led, recs)
    assert res["gec_kalan"] == sum(r["p"] is not None for r in recs)
    assert all(r["p"] is None and r["reasons"][0] == "PENCERE_KACIRILDI" for r in led.predictions())
    led.close()


def test_recorded_forecasts_never_change_silently(engine, ht_matches, ctx, tmp_path):
    fx = _future_fixtures(ht_matches, n=1)
    recs = build(engine, fx, ht_matches, ctx)
    led = Ledger(tmp_path / "l.sqlite")
    F.record_forecasts(led, recs)
    before = json.dumps(led.predictions(), sort_keys=True, default=str)
    again = F.record_forecasts(led, build(engine, fx, ht_matches, ctx))
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


def test_settlement_and_evaluation_by_cohort(engine, ht_matches, ctx, tmp_path):
    fx = _future_fixtures(ht_matches, n=4)
    recs = build(engine, fx, ht_matches, ctx)
    recs += build(None, fx, ht_matches, full_context(ht_matches, None, AS_OF, FIXTURE_DAY))  # olasılıksız kayıtlar
    led = Ledger(tmp_path / "l.sqlite")
    F.record_forecasts(led, recs)
    res = fx.assign(fthg=3, ftag=2, hthg=1.0, htag=1.0)
    out = settle_pending(led, res)
    n_fc = sum(r["p"] is not None for r in recs)
    assert out["sonuclanan"] == n_fc  # TAHMIN_YOK kayıtları sonuçlandırılmaz
    ev = F.evaluate_forecasts(led)
    json.dumps(ev, allow_nan=False)  # tek maç günü: aralık hesaplanamaz → boş (NaN değil)
    cov = ev["kapsam"][F.PROTOCOL_V2_VERSION]  # protokol sürümleri ayrı raporlanır
    assert cov[F.STATUS_FORECAST] == n_fc and cov["MODEL_YOK"] == len(fx) * 3
    rows = [r for r in ev["kohort_pazar"] if not r["gecersiz_ilanlar_haric"]]
    assert {r["protokol"] for r in rows} == {F.PROTOCOL_V2_VERSION}
    assert {r["pazar"] for r in rows} == set(PRIMARY_YES)
    for r in rows:
        assert r["sonuclanan"] == len(fx) and r["resmi_degerlendirme_esigi"] is False
        assert r["ekonomik_statu"] == "ROI_UNAVAILABLE"
        assert r["delta_ll_tanimi"].startswith("model − referans")
    led.close()


def test_unverified_odds_never_get_economic_status(engine, ht_matches, ctx, tmp_path):
    fx = _future_fixtures(ht_matches, n=1)
    led = Ledger(tmp_path / "l.sqlite")
    eid = event_id(fx.loc[0, "league"], fx.loc[0, "date"], fx.loc[0, "home"], fx.loc[0, "away"])
    target = F.decision_target(fx.loc[0, "date"])
    m = MARKETS["FT_OVER_3_5"]
    t0 = AS_OF - dt.timedelta(minutes=5)
    led.add_odds([OddsQuote(eid, "FT_OVER_3_5", m.period, m.line, m.selection, "manuel", "test", 2.4, t0, t0)])
    recs = build(engine, fx, ht_matches, ctx, ledger=led)
    over = next(r for r in recs if r["market_key"] == "FT_OVER_3_5")
    assert over["p"] is not None
    assert over["oran"]["zaman_dogrulandi"] is True and over["ekonomik_statu"] == "ZAMANI_DOGRULANMIS_ORAN"
    assert dt.datetime.fromisoformat(over["oran"]["quoted_at"]) < target
    # geçerlilik anı karar anından önce ama sisteme karar anından SONRA alınmış (ör. sonradan elle girilmiş) oran
    m_c = MARKETS["FH_OVER_1_5"]
    led.add_odds([OddsQuote(eid, "FH_OVER_1_5", m_c.period, m_c.line, m_c.selection, "manuel", "test", 2.2, t0,
                            target + dt.timedelta(hours=1))])
    fh = next(r for r in build(engine, fx, ht_matches, ctx, ledger=led) if r["market_key"] == "FH_OVER_1_5")
    assert fh["oran"]["zaman_dogrulandi"] is False and fh["ekonomik_statu"] == "HISTORICAL_REFERENCE_ONLY"
    # zamanı bilinmeyen oran (ör. tarihsel CSV) → ekonomik doğrulamaya girmez
    other = [dict(r, oran={"decimal_odds": 2.0, "kaynak": "tarihsel CSV"}) for r in recs if r["p"] is not None]
    F.record_forecasts(led, other)
    settle_pending(led, fx.assign(fthg=3, ftag=2, hthg=1.0, htag=1.0))
    for row in F.evaluate_forecasts(led)["kohort_pazar"]:
        if row["pazar"] != "FT_OVER_3_5" and row.get("sonuclanan"):
            assert row["zamani_dogrulanmis_oranli"] == 0 and row["ekonomik_statu"] == "ROI_UNAVAILABLE"
    led.close()


def test_bet_candidate_records_are_separate_from_decisions(engine, ht_matches, ctx, tmp_path):
    from bahis_tahmin.goals.service import gated_goal_predictions

    fx = _future_fixtures(ht_matches, n=1)
    v = gated_goal_predictions(engine, ctx, fx, AS_OF)[0]
    pred = v.prediction
    led = Ledger(tmp_path / "l.sqlite")
    record_decisions(led, pred, decisions_for(pred, engine, led, AS_OF, eligibility=v), engine)
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


def test_model_cohorts_are_not_pooled(engine, ht_matches, ctx, tmp_path):
    fx = _future_fixtures(ht_matches, n=2)
    led = Ledger(tmp_path / "l.sqlite")
    F.record_forecasts(led, build(engine, fx, ht_matches, ctx))
    old = engine.trained_at
    engine.trained_at = "2000-01-01T00:00:00"  # yeniden eğitilmiş başka sürüm gibi
    try:
        F.record_forecasts(led, build(engine, fx, ht_matches, ctx))
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


def test_protocol_v2_is_frozen_separately_and_v1_is_unchanged():
    """Uygunluk anlamı değiştiği için yeni sürüm (v2); v1 gövdesi, özeti ve dondurma anı aynen (S3-GATE-01)."""
    assert F.PROTOCOL_FROZEN == {"dondurma_zamani_utc": "2026-10-10T11:52:58+00:00",
                                 "govde_sha256": "3946a6e2865f4ea5386156e20cb5ccb7ccd8a4c1520c3dc65fdd4e2a6814fddf"}
    assert F.ACTIVE_PROTOCOL == F.PROTOCOL_V2_VERSION != F.PROTOCOL_VERSION
    assert F.PROTOCOL_V2_FROZEN["govde_sha256"] == F.protocol_sha256(F.PROTOCOL_V2_BODY)
    assert F.freeze_time(F.PROTOCOL_V2_VERSION) > F.freeze_time(F.PROTOCOL_VERSION)
    doc = json.loads((REPO / "reports" / "s3_gate_01" / "ileriye_donuk_protokol_v2.json").read_text(encoding="utf-8"))
    assert doc == json.loads(json.dumps(F.protocol_document(F.PROTOCOL_V2_VERSION), ensure_ascii=False))
    assert F.PROTOCOL_V2_BODY["karar_penceresi"] == F.PROTOCOL_BODY["karar_penceresi"]  # 00:00 penceresi aynı

"""Ortak veri uygunluk kontrolü (S3-GATE-01): zorunlu 22 senaryo.

YALNIZCA açıkça SENTETİK veri (kaynak etiketi ``sentetik``), sentetik kaynak takvimi ve sentetik hak kaydı ile geçici
dizinler kullanılır. Gerçek veri deposuna, kullanıcı defterine veya kullanıcı ayarlarına dokunulmaz; bu testler gerçek
maç analizi veya gerçek entegrasyon kanıtı değildir. Senaryo numaraları görev tanımındaki sırayı izler (T01…T22).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from uygunluk_yardim import (
    AS_OF,
    FIXTURE_DAY,
    UTC,
    full_context,
    recent_synthetic,
    synthetic_rights,
    verified,
)

from bahis_tahmin import eligibility as E
from bahis_tahmin.goals import forecast_log as F
from bahis_tahmin.goals.engine import GoalEngine
from bahis_tahmin.goals.ledger import Ledger
from bahis_tahmin.goals.markets import MARKETS, PRIMARY_YES, MatchStatus, PeriodScore, label
from bahis_tahmin.goals.service import (
    SELECTIONS,
    decisions_for,
    gated_goal_match,
    gated_goal_predictions,
    ledger_csv,
    ledger_rows,
    record_decisions,
)
from bahis_tahmin.goals.value import OddsQuote

REPO = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ ortak sentetik düzen
@pytest.fixture(scope="module")
def m():
    return recent_synthetic()


@pytest.fixture(scope="module")
def eng(m):
    e = GoalEngine()
    e.train(m)
    return e


_ENGINES: dict = {}


def engine_for(store: pd.DataFrame) -> GoalEngine:
    """Verilen (sentetik) depoyla eğitilmiş gol motoru: model durumu depoyla tutarlı (önbellekli)."""
    key = tuple(store.index)
    if key not in _ENGINES:
        e = GoalEngine()
        e.train(store)
        _ENGINES[key] = e
    return _ENGINES[key]


@pytest.fixture(scope="module")
def ctx(m, eng):
    return full_context(m, eng, AS_OF, FIXTURE_DAY)


@pytest.fixture(scope="module")
def teams(m):
    return sorted(set(m["home"]))


def fixtures(teams, n=4, day=FIXTURE_DAY, start=0):
    return pd.DataFrame([{"league": "T1", "date": pd.Timestamp(day), "time": "", "home": teams[start + 2 * i],
                          "away": teams[start + 2 * i + 1], "source": "SENTETIK-FIKSTUR"} for i in range(n)])


def team_match_index(m, team, k=-3):
    return m[(m["home"] == team) | (m["away"] == team)].index[k]


def quote(eid, key, odds, at=None):
    mk = MARKETS[key]
    at = at or AS_OF - dt.timedelta(minutes=5)
    return OddsQuote(eid, key, mk.period, mk.line, mk.selection, "manuel", "test", float(odds), at, at)


@pytest.fixture
def validated(eng):
    old = dict(eng.validated)
    for k in PRIMARY_YES:
        eng.validated[k] = True
    yield eng
    eng.validated.clear()
    eng.validated.update(old)


def generous_odds(pred, key):
    """Belirsizlik alt sınırıyla da yaklaşık +%6 beklenen getiri veren (sentetik) oran."""
    lo, _ = pred.interval(key)
    return round(1.06 / max(lo, 0.05), 2)


# =========================================================== T01 bilinen eksik maç
def test_t01_known_missing_match_never_becomes_value_candidate(m, eng, teams, validated, tmp_path, monkeypatch,
                                                               capsys):
    fx = fixtures(teams, n=1)
    team = fx.loc[0, "home"]
    stale_store = m.drop(index=team_match_index(m, team))
    stale_eng = engine_for(stale_store)  # model de aynı (eksik) depoyla eğitilmiş: eksik ancak kaynakla görülür
    stale = full_context(stale_store, stale_eng, AS_OF, FIXTURE_DAY, schedule=m)
    fresh = full_context(m, eng, AS_OF, FIXTURE_DAY)
    led = Ledger(tmp_path / "t01.sqlite")
    v_fresh = gated_goal_predictions(eng, fresh, fx, AS_OF)[0]
    v_stale = gated_goal_predictions(stale_eng, stale, fx, AS_OF)[0]
    pred = v_stale.prediction
    led.add_odds([quote(pred.event_id, k, generous_odds(v_fresh.prediction, k)) for k in PRIMARY_YES])
    # Kontrol grubu: aynı oran ve doğrulama ile veri tamken karar motoru normal çalışır
    assert any(d.status == "VALUE_CANDIDATE"
               for d in decisions_for(v_fresh.prediction, eng, led, AS_OF, eligibility=v_fresh))
    # Karar yolu (tamamlayıcı Hayır/Alt dahil)
    for e in v_stale.by_market.values():
        assert e.freshness == E.KNOWN_STALE and "DEPODA_EKSIK_MAC" in e.reasons and not e.forecast_ok
    old = dict(stale_eng.validated)
    stale_eng.validated.update({k: True for k in PRIMARY_YES})
    try:
        decs = decisions_for(pred, stale_eng, led, AS_OF, eligibility=v_stale)
    finally:
        stale_eng.validated.clear()
        stale_eng.validated.update(old)
    assert len(decs) == len(SELECTIONS) and all(d.status == "DATA_NOT_ELIGIBLE" for d in decs)
    # Olasılıktan türetilen hiçbir değer (aralık, güvenli olasılık, gereken oran) taşınmaz
    for d in decs:
        assert d.p != d.p and d.p_safe is None and d.min_odds is None and d.ev is None and d.ev_safe is None
        assert not any(r.startswith("Belirsizlik aralığı") for r in d.reasons)
    # Kayıt yolu: bahis adayı kaydı yok, stake 0, olasılık yazılmaz
    record_decisions(led, pred, decs, stale_eng, record_time=AS_OF)
    for r in led.predictions():
        assert r["kayit_turu"] == F.RECORD_DECISION and r["stake_units"] == 0.0 and r["p"] is None
        assert r["p_low"] is None and "DEPODA_EKSIK_MAC" in r["veri_uygunlugu"]["nedenler"]
    # İleriye dönük ölçüm kaydı yolu
    recs = F.build_forecast_records(stale_eng, fx, stale_store, now=AS_OF, ctx=stale)
    assert {r["reasons"][0] for r in recs} == {"DEPODA_EKSIK_MAC"} and all(r["p"] is None for r in recs)
    led.close()
    # CLI yolları (geçici uygulama dizini; kaynak takvimi önbellek dosyası olarak; eşleşmeyen bir fikstür de var)
    _write_store_and_calendar(stale_store, m, stale_eng)
    from bahis_tahmin import cli
    from bahis_tahmin.models.engine import PredictionEngine

    monkeypatch.setattr(cli, "_now_utc", lambda: AS_OF)
    monkeypatch.setattr(F, "_now", lambda: AS_OF)
    st = cli._store()
    st.fixtures = fx.reindex(columns=st.fixtures.columns)
    st.meta["eslesmeyen_fikstur"] = [{"league": "T1", "date": str(FIXTURE_DAY), "time": "", "raw_home": "Qwerty Kulubu",
                                      "raw_away": teams[5], "source": "openfootball"}]
    st.save()
    me = PredictionEngine()
    me.train(stale_store)
    me.save(st.home / "engine.joblib")
    assert cli.main(["gol-tahmin"]) == 0
    out = capsys.readouterr().out
    assert "DEPODA_EKSIK_MAC" in out and "Eksik veri" in out and "DEĞER" not in out
    assert "kanonik değil" in out and "TAKIM_ESLESMEDI" in out  # eşleşmeyen fikstür düşürülmez
    assert cli.main(["predict"]) == 0
    out = capsys.readouterr().out
    line = next(x for x in out.splitlines() if team in x)
    assert "TAHMİN YOK" in line and "DEPODA_EKSIK_MAC" in line and "%" not in line.split("—")[0]
    assert "DEĞER" not in out and "kanonik değil" in out
    assert cli.main(["en-olasi", "--threshold", "0.3"]) == 0
    out = capsys.readouterr().out
    assert "listelenmeyen maç: 2" in out and "adil oran" not in out
    assert cli.main(["gol-olcum-kaydet"]) == 0  # kuru çalıştırma: yazmaz
    out = capsys.readouterr().out
    assert "DEPODA_EKSIK_MAC" in out and "0 tahmin" in out
    assert not (st.home / "gol_pazarlari.sqlite").exists()


def _write_store_and_calendar(store_matches, schedule, eng):
    """Geçici uygulama dizinine sentetik depo, gol modeli ve openfootball biçiminde sentetik takvim dosyaları."""
    from bahis_tahmin.config import app_home
    from bahis_tahmin.data.store import DataStore

    home = app_home()
    st = DataStore(home)
    st.matches = store_matches.reset_index(drop=True)
    st.save()
    eng.save(home / "goal_engine.joblib")
    stamp = (AS_OF - dt.timedelta(hours=1)).timestamp()
    last = schedule[schedule["season"] == "2025/26"]
    doc = {"matches": [{"date": str(pd.Timestamp(r.date).date()), "team1": r.home, "team2": r.away,
                        "score": {"ft": [int(r.fthg), int(r.ftag)]}} for r in last.itertuples()]}
    teams = sorted(set(schedule["home"]))
    pairs = [(h, a) for h in teams for a in teams if h != a]
    nxt = {"matches": [{"date": str(FIXTURE_DAY + dt.timedelta(days=7 * (k // 8))), "team1": h, "team2": a}
                       for k, (h, a) in enumerate(pairs)]}
    for season, body in (("2025-26", doc), ("2026-27", nxt)):
        path = home / "raw" / "openfootball" / season / "tr.1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body), encoding="utf-8")
        os.utime(path, (stamp, stamp))


# ============================================ T02 ligde yeni kayıt var, takımın eski maçı eksik
def test_t02_older_team_gap_is_caught_even_when_league_is_recent(m, teams):
    fx = fixtures(teams, n=1)
    team = fx.loc[0, "home"]
    idx = team_match_index(m, team, k=-4)
    store = m.drop(index=idx)
    eng = engine_for(store)  # model de aynı eksik depoyla eğitilmiş (durum ↔ depo tutarlı; eksik kaynakla görülür)
    assert store["date"].max() > m.loc[idx, "date"]  # ligin daha yeni maçları depoda
    # v1 kuralı (son tarih sonrası eksik maç sayısı) bu boşluğu görmez
    assert not F.check_freshness(store, "T1", FIXTURE_DAY, missing_played=0).stale
    e = full_context(store, eng, AS_OF, FIXTURE_DAY, schedule=m).evaluate(
        league="T1", date=FIXTURE_DAY, home=team, away=fx.loc[0, "away"], as_of=AS_OF, markets=E.GOAL_MARKETS,
        prediction_codes=())["FT_OVER_3_5"]
    assert e.freshness == E.KNOWN_STALE and "DEPODA_EKSIK_MAC" in e.reasons
    assert str(m.loc[idx, "date"].date()) in e.data_scope["ayrinti"]["depoda_eksik"][team]
    # Diğer takımlar için bu tek eksik yalnızca lig düzeyi bilgidir (ilgisiz eksik bütün tahminleri kapatmaz)
    other = [t for t in teams if t not in (m.loc[idx, "home"], m.loc[idx, "away"])][:2]
    e2 = full_context(store, eng, AS_OF, FIXTURE_DAY, schedule=m).evaluate(
        league="T1", date=FIXTURE_DAY, home=other[0], away=other[1], as_of=AS_OF, markets=("FT_OVER_3_5",),
        prediction_codes=())["FT_OVER_3_5"]
    assert e2.forecast_ok and "LIG_DURUMU_KISMEN_EKSIK" in e2.reasons


# ============================================ T03 kapsam doğrulanamıyor → UNKNOWN
def test_t03_unverifiable_scope_is_unknown_never_eligible(m, eng, teams):
    near = dt.datetime(2026, 3, 5, 12, tzinfo=UTC)  # son lig maçından 4 gün sonra
    assert not F.check_freshness(m, "T1", near.date()).stale  # v1 gün kuralı "güncel" derdi
    no_cov = E.EligibilityContext(m, E.state_view(eng), rights=synthetic_rights())
    e = no_cov.evaluate(league="T1", date=dt.date(2026, 3, 8), home=teams[0], away=teams[1], as_of=near,
                        markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert e.freshness == E.UNKNOWN and not e.forecast_ok and not e.bet_ok
    assert "KAYNAK_KAPSAMI_YOK" in e.reasons and e.status_label == "Doğrulanamıyor"
    # Kaynak dosyası değerlendirme anından SONRA alınmışsa o anın kanıtı olamaz
    late = full_context(m, eng, near, dt.date(2026, 8, 10), retrieved=near + dt.timedelta(days=30))
    e = late.evaluate(league="T1", date=dt.date(2026, 3, 8), home=teams[0], away=teams[1], as_of=near,
                      markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert e.freshness == E.UNKNOWN and "KAYNAK_KARAR_ANINDAN_SONRA" in e.reasons


# ============================================ T04 kaynak boş veya kısmi
def test_t04_empty_or_partial_source_is_not_no_missing(m, eng, teams):
    known = set(m["home"])
    at = AS_OF - dt.timedelta(hours=1)
    empty = E.coverage_from_openfootball(b'{"matches": []}', "T1", "2025/26", at, known)
    broken = E.coverage_from_openfootball(b"{bozuk", "T1", "2025/26", at, known)
    season = m[m["season"] == "2025/26"].head(40)  # yalnızca ilk turlar
    partial = E.coverage_from_openfootball(json.dumps({"matches": [
        {"date": str(r.date.date()), "team1": r.home, "team2": r.away, "score": {"ft": [r.fthg, r.ftag]}}
        for r in season.itertuples()]}).encode(), "T1", "2025/26", at, known)
    assert not empty.complete and not broken.complete and not partial.complete
    for cov in (empty, broken, partial):
        c = E.EligibilityContext(m, E.state_view(eng), {"T1": [cov]}, rights=synthetic_rights())
        e = c.evaluate(league="T1", date=FIXTURE_DAY, home=teams[0], away=teams[1], as_of=AS_OF,
                       markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
        assert e.freshness == E.UNKNOWN and "KAYNAK_KAPSAMI_KISMI" in e.reasons and not e.forecast_ok
        assert "kontrol" not in e.data_scope  # "eksik maç = 0" iddiası üretilmez


# ============================================ T05 doğrulanmış sezon arası
def test_t05_verified_season_break_is_not_stale(m, eng, teams):
    summer = dt.datetime(2026, 7, 20, 12, tzinfo=UTC)
    first = dt.date(2026, 8, 10)
    assert F.check_freshness(m, "T1", first).stale  # v1 gün kuralı sezon arasını "güncel değil" sayardı
    c = full_context(m, eng, summer, first)
    e = c.evaluate(league="T1", date=first, home=teams[0], away=teams[1], as_of=summer, markets=("FT_OVER_3_5",),
                   prediction_codes=())["FT_OVER_3_5"]
    assert e.freshness == E.VERIFIED_CURRENT and e.forecast_ok, e.reasons
    assert e.data_cutoff == "2026-03-01"


# ============================================ T06 ertelenen/iptal/oynanmamış maç
def test_t06_postponed_cancelled_unplayed_are_not_missing_completed(m, eng, teams):
    assert E._status_of({"status": "postponed"}) == "POSTPONED"
    assert E._status_of({"score": {"ft": [1, 0]}}) == E.FINISHED
    assert E._status_of({"date": "2026-02-01"}) == E.SCHEDULED_OR_UNKNOWN
    h, a = teams[0], teams[1]
    base = full_context(m, eng, AS_OF, FIXTURE_DAY)
    extra = [E.ScheduledMatch(dt.date(2026, 2, 26), h, a, h, a, "POSTPONED"),
             E.ScheduledMatch(dt.date(2026, 2, 27), a, h, a, h, "CANCELLED")]
    covs = {"T1": [dataclasses.replace(c, matches=c.matches + tuple(extra)) if c.season == "2025/26" else c
                   for c in base.coverages["T1"]]}
    c = E.EligibilityContext(m, E.state_view(eng), covs, rights=synthetic_rights())
    e = c.evaluate(league="T1", date=FIXTURE_DAY, home=h, away=a, as_of=AS_OF, markets=("FT_OVER_3_5",),
                   prediction_codes=())["FT_OVER_3_5"]
    assert e.forecast_ok and "DEPODA_EKSIK_MAC" not in e.reasons
    # Geçmiş tarihli ama sonucu bilinmeyen (oynandığı doğrulanamayan) maç: eksik tamamlanmış maç DEĞİL, belirsiz
    unk = [E.ScheduledMatch(dt.date(2026, 2, 28), h, a, h, a, E.SCHEDULED_OR_UNKNOWN)]
    covs = {"T1": [dataclasses.replace(c, matches=c.matches + tuple(unk)) if c.season == "2025/26" else c
                   for c in base.coverages["T1"]]}
    e = E.EligibilityContext(m, E.state_view(eng), covs, rights=synthetic_rights()).evaluate(
        league="T1", date=FIXTURE_DAY, home=h, away=a, as_of=AS_OF, markets=("FT_OVER_3_5",),
        prediction_codes=())["FT_OVER_3_5"]
    assert e.freshness == E.UNKNOWN and "KAYNAK_DURUMU_BELIRSIZ" in e.reasons and "DEPODA_EKSIK_MAC" not in e.reasons


# ============================================ T07 depo güncel, kullanılan durum eski
@pytest.fixture(scope="module")
def old_eng(m):
    e = GoalEngine()
    e.train(m[m["date"] < pd.Timestamp("2026-02-15")])
    return e


def test_t07_current_store_with_old_state_is_caught(m, old_eng, teams):
    c = full_context(m, old_eng, AS_OF, FIXTURE_DAY)
    v = gated_goal_predictions(old_eng, c, fixtures(teams, n=1), AS_OF)[0]
    for e in v.by_market.values():
        assert e.freshness == E.KNOWN_STALE and "DURUM_DEPODAN_GERIDE" in e.reasons and not e.forecast_ok
        assert e.state_scope["lig_durum_son_mac"] < "2026-02-15" <= e.data_cutoff
    # Karar anında başka (yeniden eğitilmiş) bir durumla üretilmiş tahmin, eski uygunluk sonucuyla eşleşmez
    pred = v.prediction
    other = dataclasses.replace(pred, state_digest="baska-durum")
    assert all(d.status == "DATA_NOT_ELIGIBLE" for d in decisions_for(other, old_eng, None, AS_OF, eligibility=v))


# ============================================ T08 eski eğitim tarihi tek başına engel değil
def test_t08_old_training_date_alone_does_not_block(m, eng, teams):
    import copy

    e_old = copy.copy(eng)  # aynı lig durumu; yalnızca model parametrelerinin eğitim kesimi eski görünür
    e_old.data_cutoff = "2019-06-30"
    e_old.trained_at = "2019-07-01T00:00:00"
    c = full_context(m, e_old, AS_OF, FIXTURE_DAY)
    e = c.evaluate(league="T1", date=FIXTURE_DAY, home=teams[0], away=teams[1], as_of=AS_OF,
                   markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert e.forecast_ok and e.state_scope["model_egitim_kesimi"] == "2019-06-30"
    assert e.state_scope["lig_durum_son_mac"] == "2026-03-01"  # dinamik özellik kesimi ayrı tutulur


# ============================================ T09 gelecek sonuç geçmiş as-of sonucunu değiştirmez
def test_t09_future_results_do_not_change_past_as_of(m, eng, teams):
    fx = fixtures(teams, n=1)
    future = pd.concat([
        m.tail(1).assign(date=pd.Timestamp("2026-11-08"), season="2026/27", home=teams[4], away=teams[5]),
        # bilgi kesimi ile maç günü arasında, analiz edilen takımı içeren sonuç (AS_OF'tan sonra oynanmış)
        m.tail(1).assign(date=pd.Timestamp("2026-11-02"), season="2026/27", home=teams[0], away=teams[6])])
    c1 = full_context(m, eng, AS_OF, FIXTURE_DAY)
    c2 = full_context(pd.concat([m, future], ignore_index=True), eng, AS_OF, FIXTURE_DAY, schedule=m)
    assert c1.fingerprint != c2.fingerprint  # depo değişti (önbellek ayrı)
    v1 = gated_goal_predictions(eng, c1, fx, AS_OF)[0]
    v2 = gated_goal_predictions(eng, c2, fx, AS_OF)[0]
    for k in PRIMARY_YES:
        assert v1.get(k).fingerprint == v2.get(k).fingerprint and v1.get(k).reasons == v2.get(k).reasons
    assert v1.prediction.probs == v2.prediction.probs  # tahmin de aynı (model yeniden eğitilmedi)


# ============================================ T10 aynı gün, yayın/bitiş saati bilinmeyen sonuç
def test_t10_same_day_results_follow_conservative_rule(m, teams):
    day = pd.Timestamp("2026-03-01")
    same = m[m["date"] == day]
    drop = same.index[0]
    h = m.loc[drop, "home"]
    a = next(t for t in teams if t not in (m.loc[drop, "home"], m.loc[drop, "away"]))
    store = m.drop(index=drop)
    eng = engine_for(store)  # model durumu depoyla tutarlı (o maçı da içermiyor)
    eve = dt.datetime(2026, 3, 1, 15, tzinfo=UTC)  # İstanbul 18:00, aynı gün
    c = full_context(store, eng, eve, dt.date(2026, 8, 10), schedule=m)
    e = c.evaluate(league="T1", date=dt.date(2026, 3, 8), home=h, away=a, as_of=eve, markets=("FT_OVER_3_5",),
                   prediction_codes=())["FT_OVER_3_5"]
    assert e.info_cutoff == "2026-03-01" and "DEPODA_EKSIK_MAC" not in e.reasons  # aynı gün beklenmez
    # Model durumu aynı günün sonuçlarını içeriyor ve o andan önce var olduğu bilinmiyor → kullanılamaz
    assert "DURUM_KARAR_ANINDAN_SONRA" in e.reasons and not e.forecast_ok
    sv = dataclasses.replace(E.state_view(eng), available_since=eve - dt.timedelta(hours=1))
    c_live = E.EligibilityContext(store, sv, c.coverages, rights=synthetic_rights())
    e = c_live.evaluate(league="T1", date=dt.date(2026, 3, 8), home=h, away=a, as_of=eve, markets=("FT_OVER_3_5",),
                        prediction_codes=())["FT_OVER_3_5"]
    assert "DURUM_KARAR_ANINDAN_SONRA" not in e.reasons and e.forecast_ok, e.reasons
    # Ertesi gün aynı maç artık beklenir: depoda yoksa bilinen eksik
    nxt = dt.datetime(2026, 3, 2, 9, tzinfo=UTC)
    e = c_live.evaluate(league="T1", date=dt.date(2026, 3, 8), home=h, away=a, as_of=nxt, markets=("FT_OVER_3_5",),
                        prediction_codes=())["FT_OVER_3_5"]
    assert "DEPODA_EKSIK_MAC" in e.reasons and e.freshness == E.KNOWN_STALE


# ============================================ T11 gerekli alan: pazar ve gerçek model bağımlılığı
def test_t11_required_fields_follow_model_dependency_not_labelability(ctx, teams):
    # 3,5 Üst'ün sonucu yalnızca maç sonu skoruyla etiketlenebilir…
    assert label("FT_OVER_3_5", PeriodScore(fthg=3, ftag=1, status=MatchStatus.FINISHED)).value == "TRUE"
    # …ama gol modeli üç pazarı da yarı bazlı güçlerden üretir: güç yoksa üçü de tahmin edilemez
    by = ctx.evaluate(league="T1", date=FIXTURE_DAY, home=teams[0], away=teams[1], as_of=AS_OF,
                      markets=E.GOAL_MARKETS, prediction_codes=("TAKIM_GUCU_YOK",))
    assert all("GEREKLI_ALAN_EKSIK" in e.reasons and e.required_fields == "EKSIK" and not e.forecast_ok
               for e in by.values())
    # 1X2 motoru ilk yarı verisine bağlı değildir: aynı kod 1X2 tahminini engellemez
    one = ctx.evaluate(league="T1", date=FIXTURE_DAY, home=teams[0], away=teams[1], as_of=AS_OF,
                       markets=E.MATCH_MARKETS, prediction_codes=("TAKIM_GUCU_YOK",))["1X2"]
    assert "GEREKLI_ALAN_EKSIK" not in one.reasons
    # Pazar başına geçersiz olasılık yalnızca o pazarı engeller
    by = ctx.evaluate(league="T1", date=FIXTURE_DAY, home=teams[0], away=teams[1], as_of=AS_OF,
                      markets=E.GOAL_MARKETS, prediction_codes=("OLASILIK_GECERSIZ:FH_OVER_1_5",))
    assert not by["FH_OVER_1_5"].forecast_ok and by["FT_OVER_3_5"].forecast_ok
    # Gerekli alanlar hiç denetlenmediyse (tahmin kodu yok) uygun sayılmaz
    e = ctx.evaluate(league="T1", date=FIXTURE_DAY, home=teams[0], away=teams[1], as_of=AS_OF,
                     markets=("FT_OVER_3_5",))["FT_OVER_3_5"]
    assert e.required_fields == "KONTROL_EDILMEDI" and not e.forecast_ok


# ============================================ T12 takım eşleşmiyor
def test_t12_unmatched_team_gives_reasoned_candidate_not_silent_loss(eng, ctx, tmp_home):
    un = pd.DataFrame([{"league": "T1", "date": pd.Timestamp(FIXTURE_DAY), "time": "19:00", "raw_home": "Foo FC",
                        "raw_away": "Bar FC", "source": "openfootball"}])
    v1 = gated_goal_predictions(eng, ctx, pd.DataFrame(), AS_OF, unmatched=un)
    v2 = gated_goal_predictions(eng, ctx, pd.DataFrame(), AS_OF, unmatched=un)
    assert len(v1) == 1 and v1[0].prediction is None and not v1[0].canonical_id
    assert v1[0].candidate_id.startswith("aday:") and v1[0].candidate_id == v2[0].candidate_id  # kararlı
    assert set(v1[0].by_market) == set(PRIMARY_YES)
    for e in v1[0].by_market.values():
        assert e.lead_code == "TAKIM_ESLESMEDI" and e.team_mapping == "ESLESMEDI" and not e.canonical_id
        assert e.home == "Foo FC"  # sahte takım atanmaz
    # Veri deposu güncellemesi eşleşmeyen fikstürü düşürmez, ham adlarıyla saklar
    from bahis_tahmin.data.sources import OPENFOOTBALL_BASE, DownloadError
    from bahis_tahmin.data.store import DataStore

    class Fake:
        stats = {"network": 0, "cache": 0, "failed": 0}

        def host_down(self, url):
            return False

        def cache_path(self, rel):
            return Path("/nonexistent") / rel

        def get(self, url, cache_rel, max_age_hours=None, force=False):
            if url == f"{OPENFOOTBALL_BASE}/2026-27/tr.1.json":
                return (b'{"matches": [{"date": "2026-10-12", "time": "19:00", "team1": "Takim A", '
                        b'"team2": "Takim B"}, {"date": "2026-10-13", "time": "20:00", "team1": "Qwerty Kulubu", '
                        b'"team2": "Zyx Gucu"}]}')
            raise DownloadError(url, "yok (404)", 404)

    st = DataStore(tmp_home)
    st.matches = recent_synthetic().assign(home=lambda d: d["home"].str.replace("ı", "i"),
                                           away=lambda d: d["away"].str.replace("ı", "i"))
    fx = st._update_fixtures(Fake(), ["T1"], st.matches, dt.date(2026, 10, 10), 10, type("R", (), {
        "warnings": []})(), False, {"openfootball"})
    assert len(fx) == 1
    assert st._last_unmatched and st._last_unmatched[0]["raw_home"] == "Qwerty Kulubu"
    # update() → save() → load() akışında kalıcılık: test_store.py::test_mirror_fallback_and_openfootball_fixtures
    v0 = gated_goal_predictions(eng, None, pd.DataFrame(), AS_OF, unmatched=un)[0]
    assert not v0.canonical_id and not v0.first().canonical_id  # bağlamsız sonuç da kanonik iddia etmez


# ============================================ T13 veri uygun, oran yok
def test_t13_eligible_data_without_odds_keeps_forecast_and_bet_separate(m, eng, ctx, teams, validated, tmp_path):
    v = gated_goal_predictions(eng, ctx, fixtures(teams, n=1), AS_OF)[0]
    assert v.forecast_ok and all(e.bet_ok for e in v.by_market.values())
    led = Ledger(tmp_path / "t13.sqlite")
    decs = decisions_for(v.prediction, eng, led, AS_OF, eligibility=v)
    by = {d.market_key: d for d in decs}
    assert by["FT_OVER_3_5"].status == "ODDS_UNAVAILABLE" and np.isfinite(by["FT_OVER_3_5"].p)
    assert "VALUE_CANDIDATE" not in {d.status for d in decs}
    recs = F.build_forecast_records(eng, fixtures(teams, n=1), m, now=AS_OF, ctx=ctx)
    assert all(r["decision_status"] == F.STATUS_FORECAST and r["ekonomik_statu"] == "ORAN_YOK" for r in recs)
    led.close()


# ============================================ T14 veri uygun, model doğrulanmamış
def test_t14_unvalidated_model_allows_experimental_record_not_bet(m, eng, ctx, teams, tmp_path):
    assert not any(eng.validated.values())
    v = gated_goal_predictions(eng, ctx, fixtures(teams, n=1), AS_OF)[0]
    pred = v.prediction
    led = Ledger(tmp_path / "t14.sqlite")
    led.add_odds([quote(pred.event_id, k, generous_odds(pred, k)) for k in PRIMARY_YES])
    decs = decisions_for(pred, eng, led, AS_OF, eligibility=v)
    assert {d.status for d in decs} >= {"MODEL_NOT_VALIDATED"} and "VALUE_CANDIDATE" not in {d.status for d in decs}
    record_decisions(led, pred, decs, eng)
    for r in led.predictions():
        assert r["kayit_turu"] == F.RECORD_DECISION and r["stake_units"] == 0.0
    assert any(r["p"] is not None for r in led.predictions())  # deneysel kayıt olasılığı taşır (bahis değil)
    recs = F.build_forecast_records(eng, fixtures(teams, n=1), m, now=AS_OF, ctx=ctx)
    assert all(r["kayit_turu"] == F.RECORD_FORECAST and r["stake_units"] == 0.0 and r["p"] for r in recs)
    led.close()


# ============================================ T15 bağlamsız doğrudan karar servisi
def test_t15_decision_service_without_context_is_not_bypassed(eng, ctx, teams, validated, tmp_path, trained_engine):
    v = gated_goal_predictions(eng, ctx, fixtures(teams, n=1), AS_OF)[0]
    pred = v.prediction
    led = Ledger(tmp_path / "t15.sqlite")
    led.add_odds([quote(pred.event_id, k, generous_odds(pred, k)) for k in PRIMARY_YES])
    assert any(d.status == "VALUE_CANDIDATE" for d in decisions_for(pred, eng, led, AS_OF, eligibility=v))
    for elig in (None, {}, {"FT_OVER_3_5": "uygun"}):  # bağlam yok / boş / sahte nesne
        assert all(d.status == "DATA_NOT_ELIGIBLE" for d in decisions_for(pred, eng, led, AS_OF, eligibility=elig))
    # Başka maça, başka güne ait uygunluk sonucu kullanılamaz
    other_day = AS_OF + dt.timedelta(days=1)
    assert all(d.status == "DATA_NOT_ELIGIBLE" for d in decisions_for(pred, eng, led, other_day, eligibility=v))
    wrong = {k: dataclasses.replace(e, candidate_id="T1|2026-11-04|X|Y") for k, e in v.by_market.items()}
    assert all(d.status == "DATA_NOT_ELIGIBLE" for d in decisions_for(pred, eng, led, AS_OF, eligibility=wrong))
    assert E.check_for_decision(None, pred.event_id, "FT_OVER_3_5", AS_OF) == ["BAGLAM_YOK"]
    # 1X2 değer satırları da bağlamsız öneri üretmez
    p1 = trained_engine.predict_match("T1", "Takım A", "Takım B", "2026-11-04")
    from bahis_tahmin.config import Settings

    s = Settings()
    key = max(("1", "X", "2"), key=lambda k: p1.markets[k])
    odds = {key: min(s.max_odds, round((1 + s.min_ev + 0.10) / p1.markets[key], 2))}
    rows = p1.value_rows(s, odds, now=AS_OF)
    assert not any(r["value"] for r in rows) and all(r["stake"] == 0 for r in rows)
    assert rows[0]["veri_engeli"] == ["BAGLAM_YOK"]
    p1.eligibility = verified(p1.event_id, "1X2", AS_OF, state_digest=p1.state_digest)
    assert any(r["value"] for r in p1.value_rows(s, odds, now=AS_OF))  # sentetik "uygun" ile normal
    led.close()


# ============================================ T16 kaynak hakkı bilinmiyor
def test_t16_unknown_rights_cannot_be_verified_by_consent_or_flag(m, eng, teams, tmp_home, capsys):
    from bahis_tahmin import cli
    from bahis_tahmin.config import Settings
    from bahis_tahmin.data.source_registry import SOURCES, USE_RIGHTS

    # Yapılandırılmış alanlar mevcut metinlerle aynı; yeni hak verilmedi
    assert SOURCES["football-data"].model_training.startswith("Doğrulanamadı")
    assert USE_RIGHTS["football-data"]["model_egitimi"] == "DOGRULANAMADI"
    assert USE_RIGHTS["github-mirror"]["model_egitimi"] == "DOGRULANAMADI"
    real = m.assign(source="football-data.co.uk")
    no_consent = E.rights_from_registry({"football-data.co.uk"}, {})
    assert no_consent.codes({"football-data.co.uk"}, set()) == ["KAYNAK_ERISIM_IZNI_YOK",
                                                                 "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI"]
    # Kullanıcı onayı (arayüz veya `update --accept-terms` bayrağının sonucu) yalnızca erişimi açar
    s = Settings.load()
    s.source_consent["football-data"] = "2026-10-31T10:00:00"
    s.save()
    consented = E.rights_from_registry({"football-data.co.uk"}, Settings.load().source_consent)
    assert consented.by_label["football-data.co.uk"].erisim == "ONAY_VAR"
    base = full_context(real, eng, AS_OF, FIXTURE_DAY, rights=consented)
    # Model durumunun football-data.co.uk verisiyle eğitildiği varsayımı (sentetik): eğitim kaynağı bu etiket
    sv = dataclasses.replace(E.state_view(eng), train_sources=("football-data.co.uk",))
    c = E.EligibilityContext(real, sv, base.coverages, rights=consented)
    by = c.evaluate(league="T1", date=FIXTURE_DAY, home=teams[0], away=teams[1], as_of=AS_OF,
                    markets=E.GOAL_MARKETS, prediction_codes=())
    for e in by.values():
        assert e.forecast_ok and not e.bet_ok  # tahmin (yerel analiz) evet, bahis adayı hayır
        assert {"KAYNAK_EGITIM_HAKKI_DOGRULANAMADI", "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI"} <= set(e.reasons)
        assert e.source_use["football-data.co.uk"]["model_egitimi"] == "DOGRULANAMADI"
    # Kayıtlı olmayan kaynak etiketi: hak bilinmiyor → tahmin de yok
    unk = E.rights_from_registry({"bilinmeyen-kaynak"}, {"football-data": "x"})
    assert unk.codes({"bilinmeyen-kaynak"}, set()) == ["KAYNAK_HAKKI_BILINMIYOR"]
    # Tahmin/kayıt komutlarında uygunluğu atlatan bir bayrak yok
    for cmd in ("predict", "gol-tahmin", "gol-olcum-kaydet", "en-olasi"):
        with pytest.raises(SystemExit):
            cli.main([cmd, "--help"])
        assert not re.search(r"--(force|zorla|uygunluk|atla|skip)", capsys.readouterr().out), cmd


# ============================================ T17 geçerli sentetik uçtan uca senaryo
def test_t17_valid_synthetic_end_to_end_can_reach_expected_decision(eng, ctx, teams, validated, tmp_path):
    led = Ledger(tmp_path / "t17.sqlite")
    verdicts = gated_goal_predictions(eng, ctx, fixtures(teams, n=4), AS_OF)
    assert verdicts and all(v.forecast_ok and v.first().freshness == E.VERIFIED_CURRENT for v in verdicts)
    found = None
    for v in verdicts:
        pred = v.prediction
        led.add_odds([quote(pred.event_id, k, generous_odds(pred, k)) for k in PRIMARY_YES])
        decs = decisions_for(pred, eng, led, AS_OF, eligibility=v)
        if any(d.status == "VALUE_CANDIDATE" for d in decs):
            found = (pred, decs)
            break
    assert found, "geçerli sentetik senaryoda kontrol göstermelik olarak her şeyi engellememeli"
    pred, decs = found
    record_decisions(led, pred, decs, eng, record_time=AS_OF)
    bets = [r for r in led.predictions() if r["kayit_turu"] == F.RECORD_BET]
    assert len(bets) == 1 and bets[0]["stake_units"] == 1.0 and bets[0]["veri_uygunlugu"]["bahis_veri_uygun"]
    led.close()


# ============================================ T18 geçersiz olasılık kamuya açık çıktıya taşınmaz
def test_t18_invalid_probabilities_never_reach_public_json_csv(eng, ctx, teams, tmp_path):
    v = gated_goal_predictions(eng, ctx, fixtures(teams, n=1), AS_OF)[0]
    pred = dataclasses.replace(v.prediction, probs=dict(v.prediction.probs, A=float("nan"), C=float("inf")))
    from bahis_tahmin.goals.service import prediction_codes

    codes = prediction_codes(pred)
    assert "OLASILIK_GECERSIZ:BTTS_BOTH_HALVES_YES" in codes and "OLASILIK_GECERSIZ:FH_OVER_1_5" in codes
    by = ctx.evaluate(league=pred.league, date=pred.date, home=pred.home, away=pred.away, as_of=AS_OF,
                      markets=E.GOAL_MARKETS, prediction_codes=codes, event_id=pred.event_id)
    assert not by["BTTS_BOTH_HALVES_YES"].forecast_ok and by["FT_OVER_3_5"].forecast_ok
    led = Ledger(tmp_path / "t18.sqlite")
    decs = decisions_for(pred, eng, led, AS_OF, eligibility=by)
    record_decisions(led, pred, decs, eng)
    for (payload,) in led.conn.execute("SELECT payload FROM predictions"):
        rec = json.loads(payload, parse_constant=lambda c: pytest.fail(f"JSON içinde {c}"))
        assert rec["p"] is None or 0 < rec["p"] < 1  # NaN/sonsuz yok, sahte 0 yok
    rows = ledger_rows(led)
    text = ledger_csv(rows + [dict(rows[0], Olasılık=float("nan"), Oran=float("inf"))])
    assert not re.search(r"(?i)\bnan\b|\binf\b", text)
    for e in by.values():
        json.dumps(e.to_dict(), allow_nan=False)
    recs = F.build_forecast_records(eng, fixtures(teams, n=1), recent_synthetic(), now=AS_OF, ctx=ctx)
    json.dumps(recs, allow_nan=False, default=str)
    assert E.finite_or_none(float("nan")) is None and E.finite_or_none(0.0) == 0.0
    led.close()


# ============================================ T19 ana üç pazarın matematiksel ilişkisi
def test_t19_market_relations_are_preserved(eng, ctx, teams):
    fx = fixtures(teams, n=4)
    raw = {p.event_id: p.probs for p in eng.predict_fixtures(fx)}
    for v in gated_goal_predictions(eng, ctx, fx, AS_OF):
        p = v.prediction.probs
        assert p == raw[v.prediction.event_id]  # uygunluk kontrolü olasılığı değiştirmez
        assert p["A"] <= p["BC"] + 1e-9 <= min(p["B"], p["C"]) + 2e-9
        assert v.prediction.p("FT_UNDER_3_5") == pytest.approx(1 - p["B"])
        assert v.prediction.p("BTTS_BOTH_HALVES_NO") == pytest.approx(1 - p["A"])


# ============================================ T20 mevcut kayıtlar okunur ve değişmez
def test_t20_existing_records_stay_readable_and_unchanged(eng, ctx, teams, tmp_path):
    from bahis_tahmin.goals.service import settle_pending

    led = Ledger(tmp_path / "t20.sqlite")
    old_fc = {"kayit_turu": F.RECORD_FORECAST, "protokol": F.PROTOCOL_VERSION, "event_id": "T1|2026-10-20|Takım A|Takım B",
              "league": "T1", "home": "Takım A", "away": "Takım B", "mac_tarihi": "2026-10-20",
              "market_key": "FT_OVER_3_5", "decision_time": "2026-10-19T21:00:00+00:00",
              "hedef_karar_ani": "2026-10-19T21:00:00+00:00", "model_version": "eski", "feature_version": "eski",
              "model_kohort": "eski", "data_cutoff": "2026-09-03", "p": 0.31, "p_low": 0.28, "p_high": 0.34,
              "referans_p": 0.29, "decision_status": F.STATUS_FORECAST, "reasons": [], "stake_units": 0.0,
              "strategy_version": F.PROTOCOL_VERSION, "oran": None}
    old_dec = dict(old_fc, kayit_turu=F.RECORD_DECISION, decision_status="NO_VALUE", p=0.4, odds=1.9,
                   strategy_version="sanal-sabit-birim-v1", policy_version="karar-politikasi-v1.1")
    led.record_prediction(old_fc)
    led.record_prediction(old_dec)
    before = [row for row in led.conn.execute("SELECT id, created_at, payload, hash FROM predictions")]
    # Yeni kod yolları: v2 kaydı ekle, oku, dışa aktar, değerlendir, sonuçlandır
    F.record_forecasts(led, F.build_forecast_records(eng, fixtures(teams, n=1), recent_synthetic(), now=AS_OF,
                                                     ctx=ctx))
    rows = ledger_rows(led)
    assert rows[0]["Veri uygunluğu"].startswith("- (kayıt veri uygunluk") and rows[0]["Olasılık"] == 0.31
    ev = F.evaluate_forecasts(led)
    assert set(ev["kapsam"]) == {F.PROTOCOL_VERSION, F.PROTOCOL_V2_VERSION}  # sürümler ayrı
    settle_pending(led, pd.DataFrame([{"league": "T1", "date": pd.Timestamp("2026-10-20"), "home": "Takım A",
                                       "away": "Takım B", "fthg": 3, "ftag": 1, "hthg": 1, "htag": 0}]))
    after = [row for row in led.conn.execute("SELECT id, created_at, payload, hash FROM predictions")][:2]
    assert after == before  # eski kayıtların olasılık, statü ve zamanları değişmedi
    ok, _ = led.verify_chain()
    assert ok
    led.close()


# ============================================ T21 önbellek: veri/durum/kapsam değişince eski sonuç kullanılmaz
def test_t21_cache_is_invalidated_when_data_state_or_scope_changes(m, eng, old_eng, teams):
    kw = dict(league="T1", date=FIXTURE_DAY, home=teams[0], away=teams[1], markets=("FT_OVER_3_5",),
              prediction_codes=())
    c = full_context(m, eng, AS_OF, FIXTURE_DAY)
    a = c.evaluate(as_of=AS_OF, **kw)["FT_OVER_3_5"]
    b = c.evaluate(as_of=AS_OF + dt.timedelta(minutes=5), **kw)["FT_OVER_3_5"]
    assert a.forecast_ok and len(c._cache) == 1 and a.fingerprint == b.fingerprint
    assert b.evaluated_at != a.evaluated_at  # önbellekten gelse de gerçek değerlendirme anı yazılır
    idx = team_match_index(m, teams[0])
    variants = {
        "veri": full_context(m.drop(index=idx), eng, AS_OF, FIXTURE_DAY, schedule=m),
        "durum": full_context(m, old_eng, AS_OF, FIXTURE_DAY),
        "kapsam": E.EligibilityContext(m, E.state_view(eng), {"T1": c.coverages["T1"][:-1]},  # yeni sezon takvimi yok
                                       rights=synthetic_rights()),
        "haklar": full_context(m, eng, AS_OF, FIXTURE_DAY, rights=synthetic_rights(model_training="DOGRULANAMADI")),
    }
    for name, cv in variants.items():
        assert cv.fingerprint != c.fingerprint, name
        e = cv.evaluate(as_of=AS_OF, **kw)["FT_OVER_3_5"]
        assert not (e.forecast_ok and e.bet_ok), name
    # Bir sonraki gün önbellek anahtarı değişir (bilgi kesimi farklı)
    c.evaluate(as_of=AS_OF + dt.timedelta(days=1), **kw)
    assert len(c._cache) == 2


def test_t21_controller_context_cache_key_tracks_changes(app_qt, m, eng, tmp_home):
    from bahis_tahmin.ui.controller import AppController

    ctl = AppController()
    ctl.clock = lambda: AS_OF
    ctl.store.matches = m
    c1 = ctl.eligibility_context(eng)
    assert ctl.eligibility_context(eng) is c1  # değişiklik yoksa aynı bağlam
    ctl.store.matches = m.drop(index=m.index[-1])
    c2 = ctl.eligibility_context(eng)
    assert c2 is not c1 and c2.fingerprint != c1.fingerprint
    ctl.settings.source_consent["football-data"] = "x"
    assert ctl.eligibility_context(eng) is not c2
    raw = tmp_home / "raw" / "openfootball" / "2026-27"
    raw.mkdir(parents=True)
    (raw / "tr.1.json").write_text('{"matches": []}', encoding="utf-8")
    c3 = ctl.eligibility_context(eng)
    assert c3.coverages.get("T1") and ctl.eligibility_context(eng) is c3


@pytest.fixture(scope="module")
def app_qt():
    qw = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    return qw.QApplication.instance() or qw.QApplication([])


# ============================================ T22 temiz kod dışa aktarımı
def test_t22_suite_does_not_depend_on_local_raw_audit_files():
    """Yalnızca yerelde tutulan ham denetim dosyaları (S2-KORUMA-02) kod veya testlerce okunmaz; temiz bir
    `git archive` dışa aktarımında da testler çalışır (komut ve sonuç raporda)."""
    ignored = [line.strip().lstrip("/") for line in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
               if line.strip().startswith("/reports/kabul_s2_01/denetim/")]
    assert len(ignored) == 10
    names = {Path(p).name for p in ignored}
    for base in (REPO / "bahis_tahmin", REPO / "tests"):
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            hits = [n for n in names if n in text]
            assert not hits, (path, hits)
    assert (REPO / "reports" / "s3_gate_01" / "ileriye_donuk_protokol_v2.json").exists()


# ============================================ ek: elle seçilen maç aynı kontrolü kullanır
def test_manual_match_uses_the_same_gate(eng, ctx, teams):
    v = gated_goal_match(eng, ctx, "T1", teams[0], teams[1], FIXTURE_DAY, AS_OF)
    assert v.forecast_ok and v.prediction is not None and set(v.by_market) == set(PRIMARY_YES)
    v_none = gated_goal_match(eng, None, "T1", teams[0], teams[1], FIXTURE_DAY, AS_OF)
    assert not v_none.any_forecast_ok and v_none.first().lead_code == "BAGLAM_YOK"
    assert [d.status for d in decisions_for(v_none.prediction, eng, None, AS_OF, eligibility=v_none)] == \
        ["DATA_NOT_ELIGIBLE"] * len(SELECTIONS)
    out = gated_goal_match(eng, ctx, "XX", teams[0], teams[1], FIXTURE_DAY, AS_OF)
    assert out.prediction is None and out.first().lead_code == "LIG_MODEL_KAPSAMI_DISI"


# ============================================ inceleme bulguları (S3-GATE-01 çekişmeli inceleme) için ek testler
def test_day_change_never_reuses_previous_days_result(eng, ctx, teams, trained_engine):
    """Gösterim de bağlam denetiminden geçer: önceki günün "uygun" sonucu ertesi gün kullanılmaz."""
    v = gated_goal_predictions(eng, ctx, fixtures(teams, n=1), AS_OF)[0]
    nxt = AS_OF + dt.timedelta(days=1)
    assert v.all_usable(AS_OF) and not v.any_usable(nxt)
    assert v.display_codes("FT_OVER_3_5", nxt) == ["BAGLAM_UYUSMUYOR"]
    p1 = trained_engine.predict_match("T1", "Takım A", "Takım B", "2026-11-04")
    p1.eligibility = verified(p1.event_id, "1X2", AS_OF, state_digest=p1.state_digest)
    assert p1.forecast_ok_at(AS_OF) and not p1.forecast_ok_at(nxt)
    # Başka model durumuna ait sonuç da gösterilmez
    p1.eligibility = verified(p1.event_id, "1X2", AS_OF, state_digest="baska")
    assert p1.display_codes(AS_OF) == ["BAGLAM_UYUSMUYOR"]


def test_recorded_candidate_is_revalidated_at_record_time(eng, ctx, teams, validated, tmp_path):
    led = Ledger(tmp_path / "rec.sqlite")
    for v in gated_goal_predictions(eng, ctx, fixtures(teams, n=4), AS_OF):
        pred = v.prediction
        led.add_odds([quote(pred.event_id, k, generous_odds(pred, k)) for k in PRIMARY_YES])
        decs = decisions_for(pred, eng, led, AS_OF, eligibility=v)
        if any(d.status == "VALUE_CANDIDATE" for d in decs):
            break
    else:
        pytest.fail("aday bulunamadı")
    # Karar dün hesaplandı, kayıt ertesi gün (maç günü) yapılıyor → bahis adayı kaydı ve stake yok
    record_decisions(led, pred, decs, eng, record_time=AS_OF + dt.timedelta(days=3))
    recs = led.predictions()
    assert all(r["kayit_turu"] == F.RECORD_DECISION and r["stake_units"] == 0.0 for r in recs)
    assert any("geçerliliğini yitirdi" in " ".join(r["reasons"]) for r in recs if r["decision_status"] ==
               "VALUE_CANDIDATE")
    led.close()


def test_state_built_from_different_rows_is_caught(m, eng, teams):
    """Durum ↔ depo karşılaştırması yalnızca son günlere değil, durumun kurulduğu maç kümesine bakar."""
    fx = fixtures(teams, n=1)
    involved = set(fx.loc[0, ["home", "away"]])
    middle = m[(m["season"] == "2023/24") & ~m["home"].isin(involved) & ~m["away"].isin(involved)].index[:30]
    old_mid = engine_for(m.drop(index=middle))  # ara dönemde 30 maçı olmadan eğitilmiş durum, depo tam
    e = full_context(m, old_mid, AS_OF, FIXTURE_DAY).evaluate(
        league="T1", date=FIXTURE_DAY, home=fx.loc[0, "home"], away=fx.loc[0, "away"], as_of=AS_OF,
        markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert "DURUM_DEPODAN_GERIDE" in e.reasons and e.freshness == E.KNOWN_STALE and not e.forecast_ok
    assert e.data_scope["ayrinti"]["durum_satirlari"] == {"durum": len(m) - 30, "depo": len(m)}
    # Köken bilgisi olmayan (eski) model dosyası: uydurulmaz, UNKNOWN
    import copy

    legacy = copy.deepcopy(eng)
    for st in legacy.states.values():
        del st.row_digest
    e = full_context(m, legacy, AS_OF, FIXTURE_DAY).evaluate(
        league="T1", date=FIXTURE_DAY, home=fx.loc[0, "home"], away=fx.loc[0, "away"], as_of=AS_OF,
        markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert "DURUM_KOKENI_YOK" in e.reasons and e.freshness == E.UNKNOWN and not e.forecast_ok
    assert not hasattr(next(iter(legacy.states.values())), "row_digest")  # dosya/nesne sessizce güncellenmez


def test_league_share_is_per_season_and_not_diluted_by_more_evidence(m, teams):
    fx = fixtures(teams, n=1)
    involved = set(fx.loc[0, ["home", "away"]])
    cur = m[(m["season"] == "2025/26") & (m["date"] >= pd.Timestamp("2025-11-01"))
            & ~m["home"].isin(involved) & ~m["away"].isin(involved)]
    drop = cur.index[: int(len(cur) * 0.10) + 1]  # pencere içindeki diğer-takım maçlarının ~%10'u eksik
    store = m.drop(index=drop)
    e = full_context(store, engine_for(store), AS_OF, FIXTURE_DAY, schedule=m).evaluate(
        league="T1", date=FIXTURE_DAY, home=fx.loc[0, "home"], away=fx.loc[0, "away"], as_of=AS_OF,
        markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert "LIG_DURUMU_EKSIK" in e.reasons and not e.forecast_ok  # 6 sezonluk kanıt eşiği seyreltmez


def test_previous_season_store_evidence_must_be_complete_for_the_whole_league(m, teams):
    summer = dt.datetime(2026, 7, 20, 12, tzinfo=UTC)
    first = dt.date(2026, 8, 10)
    retrieved = summer - dt.timedelta(hours=1)
    from uygunluk_yardim import next_season_schedule

    nxt = next_season_schedule(m, first, retrieved, "2026/27")
    kw = dict(league="T1", date=first, home=teams[0], away=teams[1], as_of=summer, markets=("FT_OVER_3_5",),
              prediction_codes=())
    e = E.EligibilityContext(m, E.state_view(engine_for(m)), {"T1": [nxt]}, rights=synthetic_rights()).evaluate(**kw)
    e = e["FT_OVER_3_5"]
    assert e.forecast_ok, e.reasons  # depoda sezon düzeyinde tam kapanmış sezon + yeni sezon takvimi
    others = m[(m["season"] == "2025/26") & ~m["home"].isin(teams[:2]) & ~m["away"].isin(teams[:2])].index[:20]
    store = m.drop(index=others)
    e = E.EligibilityContext(store, E.state_view(engine_for(store)), {"T1": [nxt]},
                             rights=synthetic_rights()).evaluate(**kw)["FT_OVER_3_5"]
    assert "KAYNAK_ARALIK_DISI" in e.reasons and not e.forecast_ok  # diğer takımların eksikleri gizlenmez


def test_quarantined_record_is_not_counted_as_present(m, teams):
    fx = fixtures(teams, n=1)
    team = fx.loc[0, "home"]
    idx = team_match_index(m, team)
    store = m.copy()
    store.loc[idx, ["hthg", "fthg"]] = [5.0, 1]  # ilk yarı > maç sonu: karantina; model bu maçı işlemez
    e = full_context(store, engine_for(store), AS_OF, FIXTURE_DAY, schedule=m).evaluate(
        league="T1", date=FIXTURE_DAY, home=team, away=fx.loc[0, "away"], as_of=AS_OF, markets=("FT_OVER_3_5",),
        prediction_codes=())["FT_OVER_3_5"]
    assert "DEPODA_GECERSIZ_SKOR" in e.reasons and e.freshness == E.KNOWN_STALE and not e.forecast_ok


def test_pair_tolerance_applies_at_the_cutoff_boundary(m, eng, teams):
    base = full_context(m, eng, AS_OF, FIXTURE_DAY)
    row = m[m["date"] == pd.Timestamp("2026-02-22")].iloc[0]
    shifted = []
    for c in base.coverages["T1"]:
        if c.season == "2025/26":
            ms = tuple(dataclasses.replace(x, date=x.date - dt.timedelta(days=1))
                       if (x.home, x.away, x.date) == (row.home, row.away, row.date.date()) else x for x in c.matches)
            c = dataclasses.replace(c, matches=ms)
        shifted.append(c)
    c = E.EligibilityContext(m, E.state_view(eng), {"T1": shifted}, rights=synthetic_rights())
    day = dt.datetime(2026, 2, 22, 12, tzinfo=UTC)  # kaynakta D-1, depoda D tarihli aynı maç; değerlendirme D günü
    e = c.evaluate(league="T1", date=dt.date(2026, 2, 28), home=row.home, away=row.away, as_of=day,
                   markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert "DEPODA_EKSIK_MAC" not in e.reasons


def test_cache_key_respects_source_availability_within_the_day(m, eng, teams):
    c = full_context(m, eng, AS_OF, FIXTURE_DAY, retrieved=AS_OF - dt.timedelta(seconds=1))
    kw = dict(league="T1", date=FIXTURE_DAY, home=teams[0], away=teams[1], markets=("FT_OVER_3_5",),
              prediction_codes=())
    assert c.evaluate(as_of=AS_OF, **kw)["FT_OVER_3_5"].forecast_ok
    early = c.evaluate(as_of=AS_OF - dt.timedelta(seconds=3), **kw)["FT_OVER_3_5"]
    assert not early.forecast_ok and "KAYNAK_KARAR_ANINDAN_SONRA" in early.reasons


def test_eligibility_evaluated_after_decision_time_is_rejected(ctx, teams):
    e = ctx.evaluate(league="T1", date=FIXTURE_DAY, home=teams[0], away=teams[1], as_of=AS_OF,
                     markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert E.check_for_decision(e, e.candidate_id, "FT_OVER_3_5", AS_OF) == []
    assert E.check_for_decision(e, e.candidate_id, "FT_OVER_3_5", AS_OF - dt.timedelta(hours=1)) == \
        ["BAGLAM_UYUSMUYOR"]


def test_team_history_rule_is_enforced(ctx, teams):
    late = dt.datetime(2027, 3, 15, 12, tzinfo=UTC)  # son lig maçından bir yıldan fazla sonra
    e = ctx.evaluate(league="T1", date=dt.date(2027, 3, 20), home=teams[0], away=teams[1], as_of=late,
                     markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert "TAKIM_GECMISI_YETERSIZ" in e.reasons and not e.forecast_ok
    by = ctx.evaluate(league="T1", date=FIXTURE_DAY, home=teams[0], away=teams[1], as_of=AS_OF,
                      markets=E.GOAL_MARKETS, prediction_codes=("TAKIM_N365_AZ",))
    assert all("TAKIM_GECMISI_YETERSIZ" in x.reasons and not x.forecast_ok for x in by.values())


def test_unverified_rights_block_every_bet_path_but_keep_forecast(m, eng, teams, validated, tmp_path,
                                                                   trained_engine):
    """bet_ok=False (doğrulanamayan sonuç kullanımı / model eğitimi hakkı) karar, kayıt ve 1X2 değer yollarına
    gerçekten uygulanır; tahmin (yerel analiz) gösterilebilir."""
    real = m.assign(source="football-data.co.uk")
    consented = E.rights_from_registry({"football-data.co.uk"}, {"football-data": "x"})
    base = full_context(real, eng, AS_OF, FIXTURE_DAY, rights=consented)
    sv = dataclasses.replace(E.state_view(eng), train_sources=("football-data.co.uk",))
    c = E.EligibilityContext(real, sv, base.coverages, rights=consented)
    led = Ledger(tmp_path / "hak.sqlite")
    for v in gated_goal_predictions(eng, c, fixtures(teams, n=4), AS_OF):
        pred = v.prediction
        assert v.all_usable(AS_OF) and not any(e.bet_ok for e in v.by_market.values())
        led.add_odds([quote(pred.event_id, k, generous_odds(pred, k)) for k in PRIMARY_YES])
        decs = decisions_for(pred, eng, led, AS_OF, eligibility=v)
        assert all(d.status == "DATA_NOT_ELIGIBLE" and np.isfinite(d.p) for d in decs)
        assert any("KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI" in r for d in decs for r in d.reasons)
        record_decisions(led, pred, decs, eng, record_time=AS_OF)
    assert not any(r["kayit_turu"] == F.RECORD_BET or r["stake_units"] for r in led.predictions())
    led.close()
    from bahis_tahmin.config import Settings

    p1 = trained_engine.predict_match("T1", "Takım A", "Takım B", "2026-11-04")
    p1.eligibility = verified(p1.event_id, "1X2", AS_OF, bet_ok=False, state_digest=p1.state_digest,
                              reasons=("KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI",))
    s = Settings()
    key = max(("1", "X", "2"), key=lambda k: p1.markets[k])
    odds = {key: min(s.max_odds, round((1 + s.min_ev + 0.10) / p1.markets[key], 2))}
    rows = p1.value_rows(s, odds, now=AS_OF)
    assert p1.forecast_ok_at(AS_OF) and not any(r["value"] for r in rows) and all(r["stake"] == 0 for r in rows)
    assert rows[0]["veri_engeli"] == ["KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI"]
    assert p1.best_value(s, now=AS_OF) is None


def test_match_paths_keep_unmatched_and_unmodelled_fixtures(synthetic, trained_engine):
    c = E.EligibilityContext(synthetic, E.state_view(trained_engine), rights=synthetic_rights())
    fx = pd.DataFrame([{"league": "XX", "date": pd.Timestamp(FIXTURE_DAY), "time": "", "home": "A", "away": "B",
                        "source": "S"}])
    un = pd.DataFrame([{"league": "T1", "date": pd.Timestamp(FIXTURE_DAY), "time": "", "raw_home": "Qwerty Kulubu",
                        "raw_away": "Takım A", "source": "openfootball"}])
    preds, missing = E.gated_match_predictions(trained_engine, c, fx, AS_OF, unmatched=un)
    assert preds == [] and len(missing) == 2
    by = {v.league: v for v in missing}
    assert by["XX"].first().lead_code == "LIG_MODEL_KAPSAMI_DISI" and by["XX"].canonical_id
    u = by["T1"]
    assert u.candidate_id.startswith("aday:") and not u.canonical_id and u.first().lead_code == "TAKIM_ESLESMEDI"
    _, none_ctx = E.gated_match_predictions(trained_engine, None, fx.iloc[0:0], AS_OF, unmatched=un)
    assert not none_ctx[0].first().canonical_id  # bağlamsız sonuç da aday kimliği kanonik saymaz


def test_league_share_early_season_is_not_diluted_by_previous_season(m, teams):
    """Sezon başında pencere iki sezonu kapsar: içinde bulunulan sezonun eksikleri önceki sezonla seyreltilmez."""
    as_of = dt.datetime(2025, 9, 20, 12, tzinfo=UTC)
    involved = set(teams[:2])
    past = m[m["date"] < pd.Timestamp("2025-09-20")]
    cur = past[(past["season"] == "2025/26") & ~past["home"].isin(involved) & ~past["away"].isin(involved)]
    k = int(np.ceil(0.20 * len(cur)))
    store = past.drop(index=cur.index[:k])
    prev = past[(past["season"] == "2024/25") & (past["date"] >= pd.Timestamp("2024-09-20"))
                & ~past["home"].isin(involved) & ~past["away"].isin(involved)]
    assert k / (len(prev) + len(cur)) < E.LEAGUE_MISSING_SHARE  # birleşik payda seyreltirdi (önkoşul)
    c = full_context(store, engine_for(store), as_of, dt.date(2026, 8, 10), schedule=m)
    e = c.evaluate(league="T1", date=dt.date(2025, 9, 21), home=teams[0], away=teams[1], as_of=as_of,
                   markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert "LIG_DURUMU_EKSIK" in e.reasons and not e.forecast_ok, e.reasons


# ============================================ ikinci doğrulama turu bulguları için ek testler
def test_store_only_season_evidence_requires_exact_double_round_robin(m):
    sg = m[m["season"] == "2024/25"]
    assert E.EligibilityContext._store_season_complete("T1", sg)
    assert not E.EligibilityContext._store_season_complete("T1", sg.drop(index=sg.index[:1]))  # bir maç eksik
    assert not E.EligibilityContext._store_season_complete("T1", pd.concat([sg, sg.head(1)]))  # fazladan maç
    # Split/play-off'lu lig: toplam maç sayısı depodan bilinemez → depo-içi kanıt kabul edilmez
    assert not E.EligibilityContext._store_season_complete("SC0", sg.assign(league="SC0"))


def test_score_change_after_training_is_a_state_mismatch(m, eng, teams):
    fx = fixtures(teams, n=1)
    idx = team_match_index(m, fx.loc[0, "home"])
    store = m.copy()
    store.loc[idx, ["fthg", "hthg"]] = [int(store.loc[idx, "fthg"]) + 3, float(store.loc[idx, "hthg"] or 0) + 1]
    e = full_context(store, eng, AS_OF, FIXTURE_DAY, schedule=m).evaluate(
        league="T1", date=FIXTURE_DAY, home=fx.loc[0, "home"], away=fx.loc[0, "away"], as_of=AS_OF,
        markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert "DURUM_VERIYLE_UYUSMUYOR" in e.reasons and not e.forecast_ok  # satır sayısı aynı, skor farklı


def test_quarantined_record_is_caught_without_a_source_calendar(m, teams):
    fx = fixtures(teams, n=1)
    team = fx.loc[0, "home"]
    store = m.copy()
    idx = team_match_index(m, team)
    store.loc[idx, ["hthg", "fthg"]] = [5.0, 1]
    from uygunluk_yardim import next_season_schedule

    nxt = next_season_schedule(m, FIXTURE_DAY, AS_OF - dt.timedelta(hours=1), "2026/27")
    c = E.EligibilityContext(store, E.state_view(engine_for(store)), {"T1": [nxt]}, rights=synthetic_rights())
    e = c.evaluate(league="T1", date=FIXTURE_DAY, home=team, away=fx.loc[0, "away"], as_of=AS_OF,
                   markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert "DEPODA_GECERSIZ_SKOR" in e.reasons and not e.forecast_ok


def test_single_missing_match_in_a_small_season_sample_is_informational(m, teams):
    as_of = dt.datetime(2025, 8, 20, 12, tzinfo=UTC)  # yeni sezonun 2. haftası
    involved = set(teams[:2])
    past = m[m["date"] < pd.Timestamp("2025-08-20")]
    cur = past[(past["season"] == "2025/26") & ~past["home"].isin(involved) & ~past["away"].isin(involved)]
    store = past.drop(index=cur.index[:1])
    c = full_context(store, engine_for(store), as_of, dt.date(2026, 8, 10), schedule=m)
    e = c.evaluate(league="T1", date=dt.date(2025, 8, 24), home=teams[0], away=teams[1], as_of=as_of,
                   markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert "LIG_DURUMU_EKSIK" not in e.reasons and "LIG_DURUMU_KISMEN_EKSIK" in e.reasons and e.forecast_ok, e.reasons
    store2 = past.drop(index=cur.index[:2])  # iki eksik: küçük örneklemde de engel
    c2 = full_context(store2, engine_for(store2), as_of, dt.date(2026, 8, 10), schedule=m)
    e2 = c2.evaluate(league="T1", date=dt.date(2025, 8, 24), home=teams[0], away=teams[1], as_of=as_of,
                     markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert "LIG_DURUMU_EKSIK" in e2.reasons and not e2.forecast_ok

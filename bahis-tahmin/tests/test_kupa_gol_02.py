"""KUPA-GOL-02: kupa ve Avrupa maçlarında gol pazarları (A: iki yarıda KG, B: 3,5 Üst, C: İY 1,5 Üst).

Yalnızca SENTETİK veri (``kupa_yardim``: iki lig + Avrupa kupası; ilk yarı golleri binom(%45)); ağ isteği yok."""

from __future__ import annotations

import copy
import datetime as dt
import re
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy.stats import poisson

from kupa_yardim import AS_OF, CUP_DAY, SLAVIA_KEY, league_context, world, write_cup_calendar

from bahis_tahmin.kupa.gol import GOAL_MODEL_VERSION, GOAL_RULE

UTC = dt.timezone.utc
HK, AK = "İngiltere|Arsenal", "Türkiye|Galatasaray"
A, B, C = "BTTS_BOTH_HALVES_YES", "FT_OVER_3_5", "FH_OVER_1_5"
GOAL_RULE_ID = GOAL_RULE.split(":")[0]


@pytest.fixture(scope="module")
def w():
    return world()


@pytest.fixture(scope="module")
def engine(w):
    from bahis_tahmin.kupa.motor import CupEngine

    eng = CupEngine()
    eng.train(*w)
    return eng


def _pred(engine, home=HK, away=AK, names=("Arsenal", "Galatasaray"), countries=("İngiltere", "Türkiye"),
          neutral=False, comp="UCL", source="espn"):
    return engine.predict_goals(comp, home, away, names[0], names[1], countries[0], countries[1],
                                pd.Timestamp(CUP_DAY), "21:00", neutral, source)


# =============================================================================================== model


def test_goal_part_is_built_from_cup_history_with_walk_forward_measurement(engine, w):
    from bahis_tahmin.kupa.gol import first_half_share, ht_mask

    _, cups = w
    g = engine.goal
    assert g is not None and g.n_ht == int(ht_mask(cups).sum())
    assert abs(g.share - first_half_share(cups)) < 1e-12 and 0.40 < g.share < 0.50  # sentetik pay %45
    res = g.results["UEFA"]
    assert set(res) == {A, B, C} and all(res[k]["n"] > 300 for k in res)
    assert all(isinstance(g.validated["UEFA"][k], bool) for k in res)
    assert g.validated["UEFA"] == {k: bool(res[k]["statu"]) for k in res}
    # Ölçülen maçlar kupa motorunun ölçülen (kalibre) örneklem dışı tahminleridir; ilk sezon yalnızca kalibrasyon
    assert set(g.oos["i"]) <= set(engine.oos["i"]) and "2023/24" not in set(g.oos["season"])
    np.testing.assert_allclose(g.oos.set_index("i")["lam_c"], engine.oos.set_index("i").loc[g.oos["i"], "lam_c"])


def test_season_share_and_base_rates_use_only_earlier_cups(w):
    """Bir sezonun ilk yarı payı ve taban oranları yalnızca o sezondan önceki kupa maçlarından: son sezonun ilk yarı
    skorları değişse de önceki sezonların gol pazarı tahminleri ve taban oranları değişmez."""
    from bahis_tahmin.kupa.motor import CupEngine

    dom, cups = w
    e1 = CupEngine()
    e1.train(dom, cups)
    alt = cups.copy()
    last = alt["season"] == "2025/26"
    alt.loc[last, "hthg"] = alt.loc[last, "fthg"]  # bütün goller ilk yarıda
    alt.loc[last, "htag"] = alt.loc[last, "ftag"]
    e2 = CupEngine()
    e2.train(dom, alt)
    a = e1.goal.oos[e1.goal.oos["season"] < "2025/26"].set_index("i")
    b = e2.goal.oos[e2.goal.oos["season"] < "2025/26"].set_index("i")
    assert len(a) > 100 and a.index.equals(b.index)
    for col in ("pA", "pB", "pC", "bA", "bB", "bC"):
        np.testing.assert_allclose(a[col], b[col], rtol=1e-12)
    assert e2.goal.share > e1.goal.share  # tahmin anındaki pay bütün geçmişten


def test_prediction_is_one_coherent_joint_distribution(engine):
    p = _pred(engine)
    pr = p.probs
    lam, nu, s = p.info["lam"], p.info["nu"], p.info["share"]
    # Yarılar bağımsız Poisson: maç sonu toplamı Poisson(λ+ν), ilk yarı toplamı Poisson(s(λ+ν))
    assert abs(pr["B"] - (1 - poisson.cdf(3, lam + nu))) < 1e-6
    assert abs(pr["C"] - (1 - poisson.cdf(1, s * (lam + nu)))) < 1e-6
    a_exact = (1 - np.exp(-s * lam)) * (1 - np.exp(-s * nu)) * (1 - np.exp(-(1 - s) * lam)) * (1 - np.exp(-(1 - s) * nu))
    assert abs(pr["A"] - a_exact) < 1e-6
    assert pr["A"] <= pr["BC"] + 1e-12 <= min(pr["B"], pr["C"]) + 2e-12  # A ⊆ B∩C (kırpma yok)
    assert p.league == "UCL" and p.info["kupa"] and p.event_id == f"UCL|{CUP_DAY}|Arsenal|Galatasaray"
    assert p.state_digest == engine.digest and p.validated == engine.goal.validated["UEFA"]
    assert p.info["model_version"].endswith(f"/{GOAL_MODEL_VERSION}") and p.base_rates == engine.goal.base["UEFA"]
    # Belirsizlik aralığı: nokta tahmini içerir, sıfır genişlikte değil, kayıtlı tohum ve yöntem
    for key, s_ in ((A, "A"), (B, "B"), (C, "C")):
        lo, hi = p.intervals[key]
        assert lo < pr[s_] < hi and hi - lo < 0.25
    assert p.intervals["meta"]["seed"] == 20261015 and p.intervals["meta"]["draws"] == 200
    assert _pred(engine).intervals == p.intervals  # belirlenimci
    # Tarafsız sahada yer değişimi simetrik; ev sahibi avantajı ilk yarı ev golünü artırır
    n1 = _pred(engine, neutral=True)
    n2 = _pred(engine, AK, HK, ("Galatasaray", "Arsenal"), ("Türkiye", "İngiltere"), neutral=True)
    for k in ("A", "B", "C"):
        assert abs(n1.probs[k] - n2.probs[k]) < 1e-12
    assert abs(n1.probs["h1_home"] - n2.probs["h1_away"]) < 1e-12 and p.probs["h1_home"] > n1.probs["h1_home"]


def test_kickoff_and_missing_team(engine):
    p = _pred(engine)
    assert p.kickoff_utc == dt.datetime(2026, 9, 16, 18, 0, tzinfo=UTC)  # ESPN UEFA saatleri İstanbul saati
    o = _pred(engine, source="openfootball-kupa")
    assert o.kickoff_utc == dt.datetime(2026, 9, 16, 19, 0, tzinfo=UTC)  # openfootball: Orta Avrupa saati
    s = _pred(engine, "Türkiye|Fenerbahce", SLAVIA_KEY, ("Fenerbahce", "Slavia Praha"), ("Türkiye", "CZE"), comp="UEL")
    assert s is not None and s.info["away_league"] == "X:CZE"
    assert _pred(engine, HK, "ESPN|1", ("Arsenal", "Yeni"), ("İngiltere", "")) is None


def test_log_rate_covariance_is_psd_and_reflects_information(engine):
    par = engine.params
    day = int((pd.Timestamp(CUP_DAY) - pd.Timestamp("2000-01-01")).days)
    cov = par.log_rate_cov(HK, AK, engine.league_for(HK, "İngiltere", day), engine.league_for(AK, "Türkiye", day), "U",
                           False)
    assert cov.shape == (2, 2) and np.allclose(cov, cov.T) and np.all(np.linalg.eigvalsh(cov) > 0)
    cov_s = par.log_rate_cov("Türkiye|Fenerbahce", SLAVIA_KEY, "T1", "X:CZE", "U", False)
    assert cov_s[1, 1] > cov[1, 1]  # az maçlı (ligi veride olmayan) takımın gücü daha belirsiz
    assert par.log_rate_cov(HK, "ESPN|1", "E0", None, "U", False) is None
    # Bağımsız denetim: log λ, log ν parametrelerde doğrusal; her parametreyi 1 artırıp ``rates`` ile türev çıkar,
    # Gᵀ H⁻¹ G kovaryansı ``log_rate_cov`` ile aynı olmalı (gradyanın hangi parametrelere düştüğü sınanır)
    from scipy.sparse.linalg import spsolve

    o_H, o_A, o_D, o_a, o_d = par.offsets
    th = np.concatenate([[par.mu], list(par.homes.values()), par.lg_attack, par.lg_defense, par.attack, par.defense])
    assert len(th) == par.hess.shape[0]

    def at(t):
        q = copy.copy(par)
        q.mu, q.homes = float(t[0]), {k: float(t[o_H + i]) for i, k in enumerate(par.homes)}
        q.lg_attack, q.lg_defense, q.attack, q.defense = t[o_A:o_D], t[o_D:o_a], t[o_a:o_d], t[o_d:]
        return q

    for args in ((HK, AK, "E0", "T1", "U", False), (HK, AK, "E0", "T1", "U", True),
                 ("Türkiye|Fenerbahce", SLAVIA_KEY, "T1", "X:CZE", "U", False)):
        base = np.log(at(th).rates(*args))
        G = np.zeros((len(th), 2))
        for k in range(len(th)):
            t = th.copy()
            t[k] += 1.0
            G[k] = np.log(at(t).rates(*args)) - base
        ref = G.T @ np.asarray(spsolve(par.hess, G)).reshape(G.shape)
        np.testing.assert_allclose(par.log_rate_cov(*args), ref, rtol=1e-6, atol=1e-12)
    # Aralık: ham (log λ, log ν) ORTAK çekilir, her çekilişte kalibrasyon + ortak dağılım yeniden (bağımsız yeniden hesap)
    from bahis_tahmin.kupa.gol import market_probs
    from bahis_tahmin.kupa.model import calibrate_rates

    for neutral in (False, True):  # tarafsız sahada iç saha düzeltmesi çekilişlerde de uygulanmaz
        r = engine.rates(HK, AK, "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "UCL", neutral)
        cv = par.log_rate_cov(HK, AK, r["home_league"], r["away_league"], r["group"], neutral)
        d = np.random.default_rng(20261015).multivariate_normal(np.zeros(2), cv, size=200, method="cholesky")
        lc, nc = calibrate_rates(r["lam_raw"] * np.exp(d[:, 0]), r["nu_raw"] * np.exp(d[:, 1]), engine.calib,
                                 np.full(200, neutral))
        ref = market_probs(lc, nc, engine.goal.share)
        p = _pred(engine, neutral=neutral)
        for key, s in ((A, "A"), (B, "B"), (C, "C")):
            np.testing.assert_allclose(p.intervals[key], np.quantile(ref[s], [0.1, 0.9]), rtol=1e-9)


def test_validation_rule_components():
    from bahis_tahmin.kupa.gol import ece_noise_q95, measure

    rng = np.random.default_rng(3)
    n = 4000
    p = rng.uniform(0.15, 0.6, n)
    y = (rng.random(n) < p).astype(float)
    weeks = np.arange(n) // 8
    base = np.full(n, y.mean())
    good = measure(y, p, base, weeks)
    assert good["statu"] and good["neden"] == "" and good["ll_fark_ust"] < 0 and 0.8 <= good["kal_egim"] <= 1.25
    # Aşırı uç tahminler: kalibrasyon eğimi düşer
    sharp = 1 / (1 + np.exp(-3 * np.log(p / (1 - p))))
    assert "kalibrasyon eğimi" in measure(y, sharp, base, weeks)["neden"]
    # Taban orandan iyi olmayan tahmin
    assert "log-kayıp" in measure(y, base, base, weeks)["neden"]
    # Sistematik kayma: eğim makul kalsa da kalibrasyon hatası (ECE) eşiği aşar
    shifted = measure(y, np.clip(p + 0.07, 0.01, 0.99), base, weeks)
    assert "ECE" in shifted["neden"] and "eğimi" not in shifted["neden"] and shifted["ece"] > shifted["ece_esik"]
    # Az pozitif örnek (<200)
    few = measure(y[:300], p[:300], base[:300], weeks[:300])
    assert "gerçekleşen örnek az" in few["neden"] and not few["statu"]
    # ECE eşiği örneklemle ölçeklenir: küçük örneklemde kusursuz kalibrasyonun gürültüsü 0,02'yi aşar
    assert ece_noise_q95(p[:500]) > 0.02 > ece_noise_q95(np.tile(p, 10)[:40000])


# =============================================================================================== uygunluk ve karar


@pytest.fixture
def cupctx(w, engine, tmp_path, monkeypatch):
    from uygunluk_yardim import register_synthetic_source

    from bahis_tahmin.kupa.uygunluk import CupContext

    register_synthetic_source(monkeypatch)
    dom, cups = w
    raw = tmp_path / "raw"
    write_cup_calendar(raw, "UCL", "2026/27", [{"id": "777", "date": str(CUP_DAY), "time": "21:00", "home_key": HK,
                                                 "away_key": AK, "status": "STATUS_SCHEDULED"}],
                       AS_OF - dt.timedelta(hours=3))

    def make(mode="standart", eng=engine):
        store = SimpleNamespace(matches=dom, cup_matches=cups, raw_dir=raw, meta={})
        return CupContext(store, eng, league_context(dom, mode=mode), {}, {}, mode, verified=set())

    return make


def _fixtures():
    from bahis_tahmin.kupa.veri import CUP_FIXTURE_COLUMNS

    return pd.DataFrame([
        {"comp": "UCL", "season": "2026/27", "stage": "", "date": pd.Timestamp(CUP_DAY), "time": "21:00",
         "home": "Arsenal", "away": "Galatasaray", "home_key": HK, "away_key": AK, "home_country": "İngiltere",
         "away_country": "Türkiye", "home_mapped": True, "away_mapped": True, "neutral": False, "source": "espn",
         "provider_id": "espn:777"},
        {"comp": "UCL", "season": "2026/27", "stage": "", "date": pd.Timestamp(CUP_DAY), "time": "21:00",
         "home": "Arsenal", "away": "Yeni Takım", "home_key": HK, "away_key": "ESPN|4242", "home_country": "İngiltere",
         "away_country": "", "home_mapped": True, "away_mapped": False, "neutral": False, "source": "espn",
         "provider_id": "espn:778"}], columns=CUP_FIXTURE_COLUMNS)


@pytest.mark.parametrize("mode", ["standart", "siki"])
def test_goal_markets_eligibility_positive_control_and_missing(cupctx, engine, mode):
    from bahis_tahmin.eligibility import GOAL_MARKETS
    from bahis_tahmin.kupa.motor import DOGRULANMADI
    from bahis_tahmin.kupa.uygunluk import gated_cup_goal_predictions

    vs = gated_cup_goal_predictions(engine, cupctx(mode), _fixtures(), AS_OF)
    ok, miss = vs
    assert ok.prediction is not None and set(ok.by_market) == set(GOAL_MARKETS)
    for e in ok.by_market.values():
        assert e.reasons == () and e.forecast_ok and e.bet_ok and e.freshness == "VERIFIED_CURRENT"
    assert ok.all_usable(AS_OF) and ok.candidate_id == ok.prediction.event_id
    assert miss.prediction is None and not miss.any_usable(AS_OF)
    assert "KUPA_TAKIM_VERISI_YOK" in miss.first().reasons
    # 1X2 modelinin doğrulama statüsü gol pazarlarını engellemez (gol pazarında doğrulama karar motorundadır)
    eng = copy.copy(engine)
    eng.status = {k: DOGRULANMADI for k in engine.status}
    ok2 = gated_cup_goal_predictions(eng, cupctx(mode, eng), _fixtures().iloc[:1], AS_OF)[0]
    assert all(e.bet_ok and "KUPA_MODEL_DOGRULANMADI" not in e.reasons for e in ok2.by_market.values())


def test_goal_prediction_codes_reach_markets(cupctx, engine):
    from bahis_tahmin.eligibility import GOAL_MARKETS

    cctx = cupctx()
    p = _pred(engine)
    kw = dict(comp="UCL", season="2026/27", date=pd.Timestamp(CUP_DAY), home="Arsenal", away="Galatasaray",
              home_key=HK, away_key=AK, home_country="İngiltere", away_country="Türkiye", as_of=AS_OF, source="espn",
              provider_id="espn:777", markets=GOAL_MARKETS)
    by = cctx.evaluate(prediction_codes=("TAKIM_N365_AZ",), **kw)
    assert all("TAKIM_GECMISI_YETERSIZ" in e.reasons and e.forecast_ok and not e.bet_ok for e in by.values())
    by = cctx.evaluate(prediction_codes=(f"OLASILIK_GECERSIZ:{B}",), **kw)
    assert not by[B].forecast_ok and by[A].forecast_ok
    by = cctx.evaluate(prediction_codes=None, **kw)  # motor kodları yok: gerekli alanlar denetlenmedi
    assert not any(e.forecast_ok for e in by.values())
    assert p.data_codes == ()  # yeterli maçı olan takımlar
    # Turnuvada geçerli ilk yarı skoru oranı düşükse tahmin gösterilir, bahis adayı olmaz
    eng = copy.copy(engine)
    eng.goal = copy.copy(engine.goal)
    eng.goal.comp_ht_share = {**engine.goal.comp_ht_share, "UCL": 0.5}
    low = _pred(eng)
    assert low.data_codes == ("LIG_IY_ORANI_DUSUK",) and "%50" in " ".join(low.data_notes)
    from bahis_tahmin.goals.service import prediction_codes

    by = cctx.evaluate(prediction_codes=prediction_codes(low), **kw)
    assert all("LIG_IY_ORANI_DUSUK" in e.reasons and e.forecast_ok and not e.bet_ok for e in by.values())


def _forced(engine, **flags):
    eng = copy.copy(engine)
    eng.goal = copy.copy(engine.goal)
    eng.goal.validated = {vg: dict(v) for vg, v in engine.goal.validated.items()}
    eng.goal.validated["UEFA"].update(flags)
    return eng


def test_decisions_use_cup_validation_and_record_settle(cupctx, engine, w, tmp_path):
    from bahis_tahmin.goals.ledger import Ledger
    from bahis_tahmin.goals.markets import MARKETS
    from bahis_tahmin.goals.service import decisions_for, record_decisions, settle_pending, settlement_matches
    from bahis_tahmin.goals.value import OddsQuote
    from bahis_tahmin.kupa.uygunluk import gated_cup_goal_predictions

    eng = _forced(engine, **{A: False, B: True, C: False})
    v = gated_cup_goal_predictions(eng, cupctx(eng=eng), _fixtures().iloc[:1], AS_OF)[0]
    p = v.prediction
    # Sentetik dünyada aralık geniş; karar yolunu sınamak için B aralığını daraltıyoruz (eşikler aynı kalır)
    p.intervals = dict(p.intervals)
    p.intervals[B] = (p.probs["B"] * 0.97, p.probs["B"] * 1.03)
    led = Ledger(tmp_path / "gol.sqlite")
    lo, _hi = p.interval(B)
    odds = round(1.06 / lo, 2)
    m = MARKETS[B]
    led.add_odds([OddsQuote(p.event_id, B, m.period, m.line, m.selection, "manuel", "test", odds, AS_OF, AS_OF)])
    decs = {d.market_key: d for d in decisions_for(p, None, led, AS_OF, eligibility=v)}  # motor gerekmez (kupa)
    assert decs[A].status == "MODEL_NOT_VALIDATED" and decs[C].status == "MODEL_NOT_VALIDATED"
    assert decs[B].status == "VALUE_CANDIDATE", decs[B].reasons
    assert decs["FT_UNDER_3_5"].status == "ODDS_UNAVAILABLE"
    # Uygunluk verilmezse koruma aşılmaz
    assert all(d.status == "DATA_NOT_ELIGIBLE" for d in decisions_for(p, eng, led, AS_OF))
    ids = record_decisions(led, p, list(decs.values()), eng, record_time=AS_OF)
    recs = {r["market_key"]: r for r in led.predictions() if r["id"] in ids}
    assert recs[B]["stake_units"] == 1.0 and recs[B]["model_version"].endswith(f"/{GOAL_MODEL_VERSION}")
    assert recs[B]["data_cutoff"] == p.info["data_cutoff"] and recs[A]["stake_units"] == 0.0
    # Sonuç kupa maçından gelir (turnuva kodu = lig alanı); ilk yarı skoru A ve C için gerekir
    dom, cups = w
    played = pd.DataFrame([{"comp": "UCL", "date": pd.Timestamp(CUP_DAY), "home": "Arsenal", "away": "Galatasaray",
                            "fthg": 3, "ftag": 2, "hthg": 1.0, "htag": 1.0}])
    store = SimpleNamespace(matches=dom, cup_matches=pd.concat([cups, played], ignore_index=True))
    res = settle_pending(led, settlement_matches(store))
    assert res["sonuclanan"] >= 6
    out = {r["market_key"]: r["outcome"]["settlement"] for r in led.predictions() if r["id"] in ids}
    assert out[B] == "WIN" and out["FT_UNDER_3_5"] == "LOSS" and out[A] == "WIN" and out[C] == "WIN"
    ok, _msg = led.verify_chain()
    assert ok
    led.close()


# =============================================================================================== çekirdek, web, CLI


def _install(core, w, engine):
    from bahis_tahmin.data.store import DataStore
    from bahis_tahmin.kupa.veri import CUP_FIXTURE_COLUMNS

    dom, cups = w
    st = DataStore(core.home)
    st.matches, st.cup_matches = dom, cups
    st.cup_fixtures = _fixtures().iloc[:1].reindex(columns=CUP_FIXTURE_COLUMNS)
    write_cup_calendar(st.raw_dir, "UCL", "2026/27", [{"id": "777", "date": str(CUP_DAY), "time": "21:00",
                                                        "home_key": HK, "away_key": AK,
                                                        "status": "STATUS_SCHEDULED"}], AS_OF - dt.timedelta(hours=3))
    ctx = league_context(dom)
    core.store, core.cup_engine = st, engine
    core.clock = lambda: AS_OF
    core.eligibility_context = lambda eng: ctx
    return st


def test_core_goal_verdicts_include_cups_without_league_goal_engine(tmp_home, w, engine, monkeypatch):
    from uygunluk_yardim import register_synthetic_source

    from bahis_tahmin.core import AppCore

    register_synthetic_source(monkeypatch)
    core = AppCore(tmp_home)
    _install(core, w, engine)
    assert core.goal_engine is None
    vs = core.compute_goal_verdicts()
    assert [v.league for v in vs] == ["UCL"] and vs[0].all_usable(AS_OF)
    core.settings.kupalar = []  # turnuva seçimi boş: kupa maçı yok
    assert core.compute_goal_verdicts() == []


def test_web_goal_pages_show_cup_matches_and_record(tmp_home, w, engine, monkeypatch):
    pytest.importorskip("flask")
    from uygunluk_yardim import register_synthetic_source

    from bahis_tahmin.web import create_app

    register_synthetic_source(monkeypatch)
    app = create_app(load=False)
    app.config["TESTING"] = True
    core = app.extensions["bahis_tahmin"].core
    _install(core, w, _forced(engine, **{B: True}))
    core.loaded = True
    core.set_goal_verdicts(core.compute_goal_verdicts())
    c = app.test_client()
    c.environ_base.update({"HTTP_HOST": "127.0.0.1:8765"})
    h = c.get("/gol/").get_data(as_text=True)
    assert "Arsenal - Galatasaray" in h and "Kupa ve Avrupa maçları (ligler arası ortak model)" in h
    assert "Kupa ve Avrupa maçları bu sayfada yer almaz" not in h
    # Lig gol motoru yokken de kupa maçının kararları üretilir (kupa doğrulaması: yalnız B; oran girilmedi)
    assert "DOĞRULANMADI / ORAN YOK / DOĞRULANMADI" in h and "TAHMİN YOK" not in h
    aday = re.search(r'aday=(UCL[^"&]+)', h).group(1)
    d = c.get(f"/gol/?sekme=mac&aday={aday}").get_data(as_text=True)
    assert "kupa taban oranı" in d and GOAL_MODEL_VERSION in d and "lig taban oranı" not in d
    assert "sanal takip için doğrulandı" in d and "DOĞRULANMADI" in d
    m = c.get("/gol/?sekme=mac&turnuva=UCL&ev_k=T%C3%BCrkiye%7CGalatasaray&ev=&dep_k=%C4%B0ngiltere%7CArsenal")
    t = m.get_data(as_text=True)
    assert "Galatasaray - Arsenal" in t and "kupa taban oranı" in t
    assert "Seçilen maç bulunamadı" in c.get("/gol/?sekme=mac&turnuva=UCL&ev_k=x&dep_k=y").get_data(as_text=True)
    tok = re.search(r'data-csrf="([^"]+)"', d).group(1)
    r = c.post("/gol/kaydet", data={"csrf": tok, "aday": aday.replace("%7C", "|").replace("%20", " ")})
    assert r.status_code == 302 and "takip" in r.headers["Location"]
    with core.ledger(create=False) as led:
        recs = led.predictions()
    assert len(recs) == 6 and all(x["model_version"].endswith(f"/{GOAL_MODEL_VERSION}") for x in recs)
    v = c.get("/gol/?sekme=dogrulama").get_data(as_text=True)
    assert GOAL_RULE_ID in v and "UEFA turnuvaları (elemeler dahil)" in v
    k = c.get("/gol/?sekme=kapsam").get_data(as_text=True)
    assert "Kupa ve Avrupa maçlarında ilk yarı skoru" in k and "Şampiyonlar Ligi" in k


def test_cli_cup_goal_command(tmp_home, w, engine, monkeypatch, capsys):
    from uygunluk_yardim import register_synthetic_source

    from bahis_tahmin.cli import main
    from bahis_tahmin.data.store import DataStore

    assert main(["kupa-gol-tahmin"]) == 2
    register_synthetic_source(monkeypatch)
    st = DataStore(tmp_home)
    st.matches, st.cup_matches = w
    st.cup_fixtures = _fixtures().iloc[:1]
    st.save()
    assert main(["kupa-egit"]) == 0
    out = capsys.readouterr().out
    assert f"Gol pazarları (kural {GOAL_RULE_ID}" in out and "Maç sonu 3,5 Üst" in out
    assert main(["kupa-gol-tahmin", "--turnuva", "UCL"]) == 0
    out = capsys.readouterr().out
    assert "Arsenal - Galatasaray" in out and "UEFA turnuvaları" in out


def test_desktop_goal_page_cup(tmp_home, w, engine, monkeypatch):
    import os
    import sys

    if sys.platform != "win32" and not os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from uygunluk_yardim import register_synthetic_source

    from bahis_tahmin.ui.main_window import MainWindow
    from bahis_tahmin.ui.pages.goals import GoalsPage
    from bahis_tahmin.ui.theme import apply_theme

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    apply_theme(app)
    register_synthetic_source(monkeypatch)
    win = MainWindow()
    ctl = win.ctl
    eng = _forced(engine, **{B: True})
    _install(ctl, w, eng)
    ctl.dataChanged.emit()
    ctl.modelChanged.emit()
    ctl.refresh_goal_predictions()
    ctl.wait()
    for _ in range(100):
        app.processEvents()
        if ctl.goal_verdicts:
            break
    try:
        assert [v.league for v in ctl.goal_verdicts] == ["UCL"]
        pg = win.page(GoalsPage)
        pg.refresh_all()
        df = pg.scan_model.frame
        assert list(df["league"]) == ["UCL"] and np.isfinite(df["B"].iloc[0])
        assert "Kupa ve Avrupa maçları (ligler arası ortak model)" in pg.status_banner.text()
        pg.cb_fixture.setCurrentIndex(1)
        app.processEvents()
        assert pg._current is not None and pg._current.info["kupa"] and pg._panel_valid()
        assert GOAL_MODEL_VERSION in pg.used.toPlainText() and pg.dec_model.rowCount() == 6
        pg._record()
        recs = ctl.ledger.predictions()
        assert len(recs) == 6 and all(r["model_version"].endswith(f"/{GOAL_MODEL_VERSION}") for r in recs)
        pg.cb_khome.setCurrentIndex(pg.cb_khome.findData(AK))
        pg.cb_kaway.setCurrentIndex(pg.cb_kaway.findData(HK))
        pg._analyze_manual_cup()
        assert (pg._current.home, pg._current.away) == ("Galatasaray", "Arsenal")
        assert pg.cup_val_model.rowCount() == 3 and pg.cup_cov_model.rowCount() >= 5
        # Kupa motoru değişirse paneldeki kupa tahmini geçersiz olur (eski durumla kayıt yapılmaz)
        ctl.cup_engine = copy.copy(eng)
        ctl.cup_engine.digest = "baska"
        assert not pg._panel_valid()
    finally:
        win.close()

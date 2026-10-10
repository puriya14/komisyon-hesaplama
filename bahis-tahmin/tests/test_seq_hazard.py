"""Olaylar arası süre ve ayrık zamanlı tehlike modeli (sözleşme §8, F4) — yalnızca sentetik veri."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest
from scipy.special import expit, logit

from bahis_tahmin.sequences import config as C
from bahis_tahmin.sequences import hazard as H
from bahis_tahmin.sequences.frame import build_frame
from bahis_tahmin.sequences.synthetic import synthetic_frame
from bahis_tahmin.sequences.timeline import build_team_matches

EV = "IY_GERIDE_MS_GALIP"
SYN = {"n_leagues": 4, "n_teams": 10}


@pytest.fixture(scope="module")
def syn0():
    return synthetic_frame(seed=0, **SYN)


def _with_y(fr, event, y):
    return dataclasses.replace(fr, y={**fr.y, event: y})


def _with_market(fr):
    """Sentetik 'piyasa': S0'ın kendi 1X2 olasılıkları (ek bilgi taşımaz) → 7b/5 piyasa kontrolü çalışır."""
    mkt = np.column_stack([fr.p0["GALIBIYET"], fr.p0["BERABERLIK"], fr.p0["MAGLUBIYET"]])
    return dataclasses.replace(fr, mkt=mkt)


def _simulate_duration_effect(fr, event, delta, seed):
    """Bilinen süre etkisi: logit P = logit p0 + delta[kategori(son gözlenen olaydan beri maç)] (blok içinde sıralı)."""
    block, _ = H.observation_blocks(fr.tm)
    p0 = np.clip(fr.p0[event], 1e-9, 1 - 1e-9)
    known = np.isfinite(fr.y[event])
    rng = np.random.default_rng(seed)
    y = np.where(known, 0.0, np.nan)
    prev_b, last, pos = None, None, 0
    for r in np.where(block >= 0)[0]:
        if block[r] != prev_b:
            prev_b, last, pos = block[r], None, 0
        eta = logit(p0[r]) + (delta[H.duration_bin(pos - last)] if last is not None else 0.0)
        if known[r] and rng.random() < expit(eta):
            y[r] = 1.0
            last = pos
        pos += 1
    return _with_y(fr, event, y)


# ----------------------------------------------------------------------------
# Aralıklar ve Kaplan–Meier
# ----------------------------------------------------------------------------

def test_km_hand_example_keeps_censored():
    gaps = pd.DataFrame({"matches": [1, 2, 3, 3, 5, 4], "event_end": [True, False, True, False, True, True],
                         "censored": [False, True, False, True, False, False],
                         "left_truncated": [False, False, False, False, False, True],
                         "at_risk": [True, True, True, True, True, False]})
    km = H.km_survival(gaps)
    s = dict(zip(km["t"], km["survival"]))
    assert s[1] == pytest.approx(0.8)
    assert s[2] == pytest.approx(0.8)
    assert s[3] == pytest.approx(0.8 * 2 / 3)
    assert s[5] == pytest.approx(0.0)
    assert km["n_censored"].sum() == 2 and km.attrs["n_censored"] == 2
    assert km.attrs["n_excluded_left_truncated"] == 1 and km.attrs["excluded_left_truncated_matches"] == 4
    assert list(km["n_at_risk"]) == [5, 4, 3, 1]
    # Sansürlüleri atmak farklı (yanlış) bir eğri verir: S(3) = 1/3
    naive = H.km_survival(gaps[~gaps["censored"]])
    assert dict(zip(naive["t"], naive["survival"]))[3] == pytest.approx(1 / 3)


def test_km_on_gaps_keeps_all_censored_intervals(syn0):
    fr, _, _ = syn0
    gaps = H.event_gaps(fr, EV)
    km = H.km_survival(gaps)
    risk = gaps[gaps["at_risk"]]
    n_cens = int((gaps["kind"] == "CENSORED").sum())
    assert n_cens > 0 and gaps.attrs["n_censored"] == n_cens
    assert km["n_censored"].sum() == n_cens == km.attrs["n_censored"]
    assert km["n_events"].sum() == int((gaps["kind"] == "COMPLETED").sum())
    assert km["n_at_risk"].iloc[0] == len(risk)
    assert km.attrs["n_censored_total"] == int(gaps["censored"].sum())
    assert set(gaps.loc[gaps["censored"], "censor_reason"]) == {"RIGHT_CENSORED"}
    assert (np.diff(km["survival"].to_numpy()) <= 1e-12).all()
    assert (gaps["tum_resmi_mac"] == "DATA_QUALITY_BLOCKED").all()
    assert (gaps["teknik_direktor_kadro_donemi"] == "DATA_QUALITY_BLOCKED").all()
    # Tamamlanmış aralık ölçüleri: gün ve sezon geçişi tutarlı
    comp = gaps[gaps["kind"] == "COMPLETED"]
    assert (comp["matches"] >= 1).all() and (comp["days"] > 0).all()
    assert (comp["season_transitions"] >= 0).all()
    one = H.event_gaps(fr, EV, team=gaps["team"].iloc[0])
    assert set(one["team"]) == {gaps["team"].iloc[0]}
    assert len(one) == int((gaps["team"] == gaps["team"].iloc[0]).sum())


def test_left_truncated_segment_excluded_but_counted(syn0):
    fr, _, _ = syn0
    gaps = H.event_gaps(fr, EV)
    lt = gaps[gaps["left_truncated"]]
    n_blocks = gaps.attrs["n_blocks"]
    assert len(lt) == n_blocks  # her blokta tam bir sol kesik dilim
    assert not lt["at_risk"].any()
    assert gaps.attrs["left_truncated_matches"] == int(lt["matches"].sum()) > 0
    # risk süresi = sol kesik olmayan aralıkların maçları = 'son olaydan beri' tanımlı satır sayısı
    since = H.since_last_event(fr, EV)
    assert np.isfinite(since).sum() == gaps.attrs["at_risk_matches"]
    km = H.km_survival(gaps)
    assert km.attrs["n_excluded_left_truncated"] == len(lt)
    # Bir takımın ilk olayına kadar (dahil) satırlar risk dışında; sonraki maç since = 1
    tm = fr.tm
    team = gaps["team"].iloc[0]
    rows = np.where((tm["team"] == team).to_numpy() & tm["in_seq"].to_numpy())[0]
    first_ev = rows[np.where(fr.y[EV][rows] == 1)[0][0]]
    assert np.isnan(since[rows[rows <= first_ev]]).all()
    assert since[rows[rows > first_ev][0]] == 1
    ds = H.hazard_dataset(fr, EV)
    assert not np.isin(rows[rows <= first_ev], ds["row_id"].to_numpy()).any()
    a = ds.attrs
    assert a["n_left_truncated_rows"] > 0
    assert a["n_candidates"] == a["n_rows"] + a["n_left_truncated_rows"] + a["n_no_frailty"]
    assert (ds["since"] >= 1).all() and (ds["bin"] >= 0).all()
    assert ds.loc[ds["since"] <= 3, "bin_name"].eq("1-3").all()
    assert ds.loc[ds["since"] >= 41, "bin_name"].eq("41+").all()
    assert set(H.BIN_COLS) <= set(ds.columns) and "bin_4-10" not in ds.columns


def test_censor_reasons_and_incomplete_season(syn0):
    _, m, probs = syn0
    m = m.copy()
    y0 = pd.to_datetime(m["date"])
    sy = np.where(y0.dt.month >= 7, y0.dt.year, y0.dt.year - 1)
    leaver, gapper = "T1-Takım A", "N1-Takım B"
    drop = ((m["home"] == leaver) | (m["away"] == leaver)) & (sy >= 2010)  # kapsamdan çıkış
    drop |= ((m["home"] == gapper) | (m["away"] == gapper)) & np.isin(sy, (2014, 2015))  # > 400 gün ara
    inc = np.where(((m["league"] == "E0") & (sy == 2012)).to_numpy())[0]
    drop_arr = drop.to_numpy().copy()
    drop_arr[inc[::8]] = True  # E0 2012/13 lig-sezonu eksik (< %97)
    m2 = m[~drop_arr].reset_index(drop=True)
    # D1 sezon etiketleri 2010'dan itibaren bir yıl kaydırılır → 2009/10'dan sonra 2011/12 (sezon atlaması, ara < 400 gün)
    sy2 = np.where(pd.to_datetime(m2["date"]).dt.month >= 7, pd.to_datetime(m2["date"]).dt.year,
                   pd.to_datetime(m2["date"]).dt.year - 1)
    shift = (m2["league"] == "D1").to_numpy() & (sy2 >= 2010)
    m2.loc[shift, "season"] = [f"{y + 1}/{(y + 2) % 100:02d}" for y in sy2[shift]]
    tm = build_team_matches(m2)
    fr = build_frame(tm, probs, with_s1=False)
    gaps = H.event_gaps(fr, EV)
    reasons = set(gaps.loc[gaps["censored"], "censor_reason"])
    assert {"RIGHT_CENSORED", "COVERAGE_EXIT", "GAP_GT_400D", "INCOMPLETE_SEASON", "SEASON_SKIP"} <= reasons
    # Sezon atlaması bloğu keser: atlama satırında yeni blok başlar ve 'son olaydan beri' sıfırlanır (sol kesik)
    block, why = H.observation_blocks(tm)
    sk = np.where(tm["season_skip"].to_numpy())[0]
    assert len(sk) == 10 and (tm["league"].to_numpy()[sk] == "D1").all()
    assert (block[sk] != block[sk - 1]).all() and {why[b] for b in block[sk - 1]} == {"SEASON_SKIP"}
    assert np.isnan(H.since_last_event(fr, EV)[sk]).all()
    assert set(gaps.loc[gaps["team"] == leaver, "censor_reason"].dropna()) == {"COVERAGE_EXIT"}
    assert "GAP_GT_400D" in set(gaps.loc[gaps["team"] == gapper, "censor_reason"].dropna())
    # Eksik sezon satırları hiçbir bloğa girmez; tehlike risk kümesinde değildir
    inc_rows = (tm["league"] == "E0").to_numpy() & (tm["season_year"] == 2012).to_numpy()
    assert not tm.loc[inc_rows, "season_complete"].any()
    assert np.isnan(H.since_last_event(fr, EV)[inc_rows]).all()
    block, _ = H.observation_blocks(tm)
    assert (block[inc_rows] == -1).all()
    # Sansürlü aralıklar KM'de kaybolmaz
    km = H.km_survival(gaps)
    assert km["n_censored"].sum() == int((gaps["kind"] == "CENSORED").sum())


def test_since_and_features_use_only_earlier_days(syn0):
    fr, _, _ = syn0
    tm = fr.tm
    dates = pd.to_datetime(tm["date"]).to_numpy()
    D = np.datetime64("2010-01-15")
    rng = np.random.default_rng(9)
    y = fr.y[EV].copy()
    fut = (dates >= D) & np.isfinite(y)
    y[fut] = (rng.random(fut.sum()) < 0.3).astype(float)  # D ve sonrası tamamen bozulur
    pert = _with_y(fr, EV, y)
    past = dates <= D  # D günündeki satırın özellikleri yalnızca önceki günlerden
    np.testing.assert_array_equal(H.since_last_event(fr, EV)[past], H.since_last_event(pert, EV)[past])
    a, b = H.hazard_dataset(fr, EV), H.hazard_dataset(pert, EV)
    a, b = a[a["date"] <= D].reset_index(drop=True), b[b["date"] <= D].reset_index(drop=True)
    assert len(a) > 1000
    cols = ["row_id", "since", "bin", "frailty", "offset"] + list(H.BIN_COLS)
    pd.testing.assert_frame_equal(a[cols], b[cols])
    # Satırın kendi sonucu kendi 'son olaydan beri' değerini değiştirmez; yalnızca takımın sonraki maçını etkiler
    since0 = H.since_last_event(fr, EV)
    r = int(np.where(np.isfinite(since0) & (fr.y[EV] == 0) & (since0 > 2))[0][0])
    nxt = r + 1
    assert tm["team"].iat[nxt] == tm["team"].iat[r] and since0[nxt] == since0[r] + 1
    y1 = fr.y[EV].copy()
    y1[r] = 1.0
    since1 = H.since_last_event(_with_y(fr, EV, y1), EV)
    assert since1[r] == since0[r] and since1[nxt] == 1


# ----------------------------------------------------------------------------
# Kırılganlık ortak değişkeni (zaman güvenliği)
# ----------------------------------------------------------------------------

def test_frailty_unaffected_by_future_seasons(syn0):
    fr, _, _ = syn0
    sy = fr.tm["season_year"].to_numpy()
    base = H.frailty_covariate(fr, EV)
    Y = 2010
    rng = np.random.default_rng(5)
    y = fr.y[EV].copy()
    fut = (sy >= Y) & np.isfinite(y)
    y[fut] = (rng.random(fut.sum()) < 0.5).astype(float)  # mevcut ve gelecek sezonları boz
    pert = H.frailty_covariate(_with_y(fr, EV, y), EV)
    upto = sy <= Y
    for col in ("frailty", "frailty_base", "frailty_n"):
        np.testing.assert_array_equal(base[col].to_numpy()[upto], pert[col].to_numpy()[upto])
    assert not np.allclose(base["frailty"].to_numpy()[sy == Y + 1], pert["frailty"].to_numpy()[sy == Y + 1])
    # Önceki sezonu değiştirmek etkiler (sağlama) ve formül (O + 50·base)/(n + 50)
    y2 = fr.y[EV].copy()
    prev = (sy == Y - 1) & np.isfinite(y2)
    y2[prev] = 1.0 - y2[prev]
    pert2 = H.frailty_covariate(_with_y(fr, EV, y2), EV)
    assert not np.allclose(base["frailty"].to_numpy()[sy == Y], pert2["frailty"].to_numpy()[sy == Y])
    tm = fr.tm
    i = int(np.where(sy == Y)[0][0])
    team, lg = tm["team"].iloc[i], tm["league"].iloc[i]
    yy = fr.y[EV]
    own = (tm["team"] == team).to_numpy() & np.isin(sy, (Y - 1, Y - 2)) & tm["in_seq"].to_numpy() & np.isfinite(yy)
    lgm = (tm["league"] == lg).to_numpy() & np.isin(sy, (Y - 1, Y - 2)) & tm["in_seq"].to_numpy() & np.isfinite(yy)
    b = yy[lgm].mean()
    assert base["frailty"].iloc[i] == pytest.approx((yy[own].sum() + 50 * b) / (own.sum() + 50))
    # Veri seti aynı değeri taşır
    ds = H.hazard_dataset(fr, EV)
    np.testing.assert_allclose(ds["frailty"].to_numpy(), base["frailty"].to_numpy()[ds["row_id"].to_numpy()])


# ----------------------------------------------------------------------------
# Wald testi: süre bağımlılığı yokken reddetmez, enjekte edilmiş etkide reddeder
# ----------------------------------------------------------------------------

def test_wald_does_not_reject_without_duration_dependence(syn0):
    ps = {ev: [] for ev in C.HAZARD_EVENTS}
    for seed in (0, 1, 2):
        fr = syn0[0] if seed == 0 else synthetic_frame(seed=seed, **SYN)[0]
        for ev in C.HAZARD_EVENTS:
            ds = H.hazard_dataset(fr, ev, mask=(fr.period == "kesif"))
            fit = H.fit_hazard(ds, bins=True)
            assert fit.converged and fit.wald["df"] == 4 and fit.n_clusters >= 30
            assert set(ds["period"]) == {"kesif"}
            assert 0 <= fit.wald["p_score"] <= 1
            ps[ev].append((fit.wald["p"], fit.wald["p_score"]))
    for ev, vals in ps.items():
        assert sum(p >= 0.01 for p, _ in vals) >= 2, (ev, vals)
        assert sum(q >= 0.01 for _, q in vals) >= 2, (ev, vals)


def test_wald_rejects_injected_duration_effect(syn0):
    fr = _simulate_duration_effect(_with_market(syn0[0]), EV, delta=np.array([1.5, 0.0, -0.6, -0.9, -1.2]), seed=11)
    ds = H.hazard_dataset(fr, EV, mask=(fr.period == "kesif"))
    fit = H.fit_hazard(ds, bins=True)
    assert fit.wald["p"] < 0.01 and fit.wald["p_chi2"] < 0.01 and fit.wald["p_score"] < 0.05
    coef = dict(zip(fit.names, fit.coef))
    assert coef["bin_1-3"] > 0 and coef["bin_41+"] < 0
    fit0 = H.fit_hazard(ds, bins=False)
    assert fit0.wald is None and not any(n.startswith("bin_") for n in fit0.names)
    oos = H.oos_compare(fr, EV)
    assert oos["parametre"]["diff"] < 0 and oos["test"]["diff"] < 0
    te = oos["test"]
    assert te["p_one_sided"] < 0.01 and te["ci_hi"] < 0 and te["iso_week"]["ci_hi"] < 0
    assert te["ll_bins"] < te["ll_no_bins"] and te["rel_diff"] < 0
    f = te["falsification"]
    assert f["1_lig_takim_cikarma"]["gecti"] and f["3_sezon_yonu"]["gecti"]
    assert f["5_piyasa"]["durum"] == "OK" and f["5_piyasa"]["gecti"]  # S0'ın kendi 1X2'si etkiyi açıklamaz
    assert f["4_eslestirilmis_ampirik"]["gecti"] is None and len(f["6_karsi_ornekler"]) == 20


def test_fit_matches_newton_and_team_cr1_sandwich(syn0):
    """Bağımsız hesap: Newton–Raphson ML + elle takım kümeli CR1 sandviç + Wald istatistiği."""
    fr = syn0[0]
    ds = H.hazard_dataset(fr, EV, mask=(fr.period == "kesif"))
    fit = H.fit_hazard(ds, bins=True)
    X = np.column_stack([np.ones(len(ds))] + [ds[c].to_numpy(float) for c in fit.names[1:]])
    y, off = ds["y"].to_numpy(float), ds["offset"].to_numpy(float)
    b = np.zeros(X.shape[1])
    for _ in range(50):
        p = expit(off + X @ b)
        step = np.linalg.solve(X.T @ (X * (p * (1 - p))[:, None]), X.T @ (y - p))
        b += step
        if np.abs(step).max() < 1e-13:
            break
    p = expit(off + X @ b)
    bread = np.linalg.inv(X.T @ (X * (p * (1 - p))[:, None]))
    cl = pd.factorize(ds["team"])[0]
    G, (n, k) = cl.max() + 1, X.shape
    S = np.zeros((G, k))
    np.add.at(S, cl, X * (y - p)[:, None])
    V = G / (G - 1) * (n - 1) / (n - k) * bread @ S.T @ S @ bread
    np.testing.assert_allclose(fit.coef, b, atol=1e-8)
    np.testing.assert_allclose(fit.cov, V, rtol=1e-6, atol=1e-12)
    bi = [i for i, nm in enumerate(fit.names) if nm.startswith("bin_")]
    W = b[bi] @ np.linalg.solve(V[np.ix_(bi, bi)], b[bi])
    assert fit.wald["stat"] == pytest.approx(W, rel=1e-6) and fit.n_clusters == G == ds["team"].nunique()
    assert fit.loglik == pytest.approx(float(np.sum(y * np.log(p) + (1 - y) * np.log1p(-p))), rel=1e-10)


def test_sandwich_matches_simple_logit_without_clustering_effect():
    rng = np.random.default_rng(3)
    n = 4000
    ds = pd.DataFrame({"y": 0.0, "offset": rng.normal(-2.5, 0.3, n), "frailty": rng.uniform(0.02, 0.06, n),
                       "team": np.arange(n)})
    for c in H.BIN_COLS:
        ds[c] = 0.0
    beta = np.array([0.2, 10.0])
    p = expit(ds["offset"] + beta[0] + beta[1] * ds["frailty"])
    ds["y"] = (rng.random(n) < p).astype(float)
    fit = H.fit_hazard(ds, bins=True)
    assert fit.names == ["intercept", "frailty"]  # satırı olmayan kategoriler düşer
    assert {d["name"] for d in fit.dropped} == set(H.BIN_COLS)
    # Kümeler tekil satır → sandviç ≈ model tabanlı (Hessian⁻¹) kovaryans
    X = np.column_stack([np.ones(n), ds["frailty"]])
    pp = fit.predict(ds)
    Hm = np.linalg.inv(X.T @ (X * (pp * (1 - pp))[:, None]))
    np.testing.assert_allclose(fit.se, np.sqrt(np.diag(Hm)), rtol=0.15)
    assert abs(fit.coef[1] - beta[1]) < 4 * fit.se[1]


# ----------------------------------------------------------------------------
# Örneklem dışı karşılaştırma ve aile
# ----------------------------------------------------------------------------

def test_oos_frozen_and_purged(syn0, monkeypatch):
    fr = _with_market(syn0[0])
    calls = []
    real = H.fit_hazard

    def spy(ds, bins=True, **kw):
        fit = real(ds, bins=bins, **kw)
        calls.append((set(ds["period"]), ds["date"].max(), bins, tuple(kw.get("extra", ())), fit))
        return fit

    monkeypatch.setattr(H, "fit_hazard", spy)
    out = H.oos_compare(fr, EV, n_boot=1000)
    # her dönem: kategorili + kategorisiz (+ 7b/5 piyasa kontrolünde aynı ikili); test içinde yeniden uyum yok
    assert len(calls) == 8
    for i, (periods, dmax, bins, extra, _) in enumerate(calls):
        cut, allowed = (("2013-07-01", {"kesif"}) if i < 4 else ("2019-07-01", {"kesif", "parametre"}))
        assert periods <= allowed
        assert dmax + pd.Timedelta(days=1) < pd.Timestamp(cut)
        assert bins == (i % 2 == 0) and extra == (() if i % 4 < 2 else H.MKT_EXTRA)
    # Dondurulmuş tahmin: test log-kaybı, test öncesi uyumların katsayılarıyla birebir aynı
    ds = H.hazard_dataset(fr, EV)
    te = ds[ds["period"] == "test"]
    yv = te["y"].to_numpy()
    for fit, key in ((calls[4][4], "ll_bins"), (calls[5][4], "ll_no_bins")):
        assert H._log_loss(yv, fit.predict(te)).mean() == pytest.approx(out["test"][key], rel=1e-12)
    assert H._log_loss(yv, te["p0"].to_numpy()).mean() == pytest.approx(out["test"]["ll_s0"], rel=1e-12)
    for name in ("parametre", "test"):
        r = out[name]
        assert r["status"] == "OK" and r["refit_in_eval"] is False and r["reps"] >= 1000
        assert r["ci_lo"] <= r["diff"] <= r["ci_hi"]
        assert 0 <= r["p_one_sided"] <= 1
        assert r["base_rate"] == pytest.approx(r["n_events"] / r["n"])
        assert {"bins", "no_bins", "s0"} == set(r["calibration"]) and r["iso_week"]["n_clusters"] > r["n_clusters"]
        assert pd.Timestamp(r["train_last_date"]) + pd.Timedelta(days=1) < pd.Timestamp(r["cutoff"])
    again = H.oos_compare(fr, EV, n_boot=1000)
    assert again["test"]["ci_lo"] == out["test"]["ci_lo"]  # config.SEED ile tekrarlanabilir
    with pytest.raises(ValueError):
        H.oos_compare(fr, EV, n_boot=999)


def test_oos_purge_excludes_label_known_at_cutoff(syn0):
    """Keşifin son maç günü 30.06.2013'e taşınır: label_known_at = 01.07.2013 = kesim → parametre uyumundan çıkar."""
    fr = syn0[0]
    tm = fr.tm.copy()
    d = pd.to_datetime(tm["date"])
    last = d[fr.period == "kesif"].max()
    tm.loc[(d == last).to_numpy(), "date"] = pd.Timestamp("2013-06-30")
    fr2 = dataclasses.replace(fr, tm=tm)
    ds = H.hazard_dataset(fr2, EV)
    edge = (ds["date"] == pd.Timestamp("2013-06-30")).to_numpy()
    assert edge.sum() >= 5 and set(ds.loc[edge, "period"]) == {"kesif"}
    out = H.oos_compare(fr2, EV)
    kesif = (ds["period"] == "kesif").to_numpy()
    assert out["parametre"]["train_n"] == int((kesif & ~edge).sum())
    assert out["parametre"]["train_last_date"] < "2013-06-30"
    both = ds["period"].isin(["kesif", "parametre"]).to_numpy()
    assert out["test"]["train_n"] == int(both.sum())  # test kesimi (2019) için bu satırlar eğitimde kalır


def test_run_hazard_family_holm_and_statuses(syn0):
    fr, _, _ = syn0
    res = H.run_hazard_family(fr)
    assert res["family"] == "F4" and res["multiple_testing"]["k"] == 2
    assert set(res["events"]) == set(C.HAZARD_EVENTS)
    for e, r in res["events"].items():
        assert r["status"] in C.STATUSES
        assert r["p_wald_holm"] >= r["p_wald"] - 1e-15
        assert r["p_param_holm"] >= r["oos"]["parametre"]["p_one_sided"] - 1e-15
        assert r["p_test_holm"] >= r["oos"]["test"]["p_one_sided"] - 1e-15
        assert r["gaps"]["n_censored"] == r["km_summary"]["n_censored"]
        assert r["discovery"]["dataset"]["n_left_truncated_rows"] > 0
        assert np.isfinite(r["discovery"]["wald"]["p_score"])
        for per in ("parametre", "test"):
            f = r["oos"][per]["falsification"]
            assert {"1_lig_takim_cikarma", "2_en_cok_katki_yuzde1", "3_sezon_yonu", "4_eslestirilmis_ampirik",
                    "5_piyasa", "6_karsi_ornekler", "gecti"} == set(f)
            assert f["5_piyasa"]["durum"] == "VERI_YOK" and f["gecti"] is False  # sentetik veride oran yok
        assert r["status"] != "OUT_OF_SAMPLE_SUPPORTED"
    assert res["blocked"]["TUM_RESMI_MACLAR"]["status"] == "DATA_QUALITY_BLOCKED"
    assert res["blocked"]["TEKNIK_DIREKTOR_KADRO_DONEMI"]["status"] == "DATA_QUALITY_BLOCKED"
    text = repr(res).lower()
    for bad in ("şike", "garanti", "kesin"):
        assert bad not in text
    with pytest.raises(ValueError):
        H.event_gaps(fr, "GALIBIYET")


def _te_frame(diff, league, team, season):
    n = len(diff)
    return pd.DataFrame({"league": league, "team": team, "season_year": season,
                         "cluster": [f"{lg}|{se}" for lg, se in zip(league, season)], "row_id": np.arange(n),
                         "date": pd.Timestamp("2020-01-01"), "since": 5, "y": 0.0})


def test_falsification_rules():
    rng = np.random.default_rng(0)
    n = 4000
    league = np.array(["L1", "L2", "L3", "L4"])[np.arange(n) % 4]
    team = np.array([f"T{i}" for i in range(40)])[np.arange(n) % 40]
    season = 2019 + (np.arange(n) // 40) % 5
    te = _te_frame(np.zeros(n), league, team, season)
    good = -0.01 + 0.001 * rng.standard_normal(n)
    f = H._falsification(te, good, 1000, 1)
    assert f["1_lig_takim_cikarma"]["gecti"] and f["2_en_cok_katki_yuzde1"]["gecti"] and f["3_sezon_yonu"]["gecti"]
    assert f["2_en_cok_katki_yuzde1"]["cikarilan"] == 40 and f["4_eslestirilmis_ampirik"]["gecti"] is None
    # Bütün katkı tek ligden: o lig çıkınca yön değişir
    one = np.where(league == "L1", -0.05, 0.004)
    assert not H._falsification(te, one, 1000, 1)["1_lig_takim_cikarma"]["gecti"]
    # Katkı satırların %1'inde yoğun: o satırlar çıkınca aralık 0'ı dışlamaz
    spike = np.full(n, 0.0005)
    spike[rng.choice(n, 30, replace=False)] = -0.5
    fs = H._falsification(te, spike, 1000, 1)
    assert spike.mean() < 0 and fs["1_lig_takim_cikarma"]["gecti"] and not fs["2_en_cok_katki_yuzde1"]["gecti"]
    # Yalnızca 2/5 sezonda iyileşme (< %60)
    seas = np.where(np.isin(season, (2019, 2020)), -0.05, 0.001)
    f3 = H._falsification(te, seas, 1000, 1)["3_sezon_yonu"]
    assert f3["pay"] == pytest.approx(0.4) and not f3["gecti"]
    top = H._falsification(te, one, 1000, 1)["6_karsi_ornekler"]
    assert len(top) == 20 and all(r["fark"] == pytest.approx(0.004) for r in top) and "team" not in top[0]


def test_status_rules():
    ok = {"gecti": True}
    fals = {"1_lig_takim_cikarma": ok, "2_en_cok_katki_yuzde1": ok, "3_sezon_yonu": ok,
            "4_eslestirilmis_ampirik": {"gecti": None}, "5_piyasa": ok, "6_karsi_ornekler": [], "gecti": True}

    def oos(f_par=fals, f_te=fals, ci_hi=-0.001, te_status="OK"):
        return {"parametre": {"status": "OK", "ci_hi": -0.001, "falsification": f_par},
                "test": {"status": te_status, "ci_hi": ci_hi, "falsification": f_te}}

    st, why = H._status(oos(), 0.01, 0.01)
    assert st == "OUT_OF_SAMPLE_SUPPORTED" and "ileriye dönük" in why
    bad_mkt = {**fals, "5_piyasa": {"gecti": False}, "gecti": False}
    st, why = H._status(oos(f_te=bad_mkt), 0.01, 0.01)
    assert st == "NO_ADDED_VALUE" and "piyasa" in why
    bad2 = {**fals, "2_en_cok_katki_yuzde1": {"gecti": False}, "gecti": False}
    st, why = H._status(oos(f_par=bad2), 0.01, 0.01)
    assert st == "NO_ADDED_VALUE" and "parametre:2_en_cok_katki_yuzde1" in why
    missing = oos()
    del missing["test"]["falsification"]  # 7b hiç değerlendirilmemişse destek statüsü yok
    assert H._status(missing, 0.01, 0.01)[0] == "NO_ADDED_VALUE"
    assert H._status(oos(), 0.2, 0.01)[0] == "NO_ADDED_VALUE"
    assert H._status(oos(ci_hi=0.001), 0.01, 0.01)[0] == "NO_ADDED_VALUE"
    assert H._status(oos(te_status="NO_FIT"), 0.01, np.nan)[0] == "EXPLORATORY"
    assert H._status(oos(te_status="NO_FIT"), 0.2, np.nan)[0] == "NO_ADDED_VALUE"
    assert H._status({}, np.nan, np.nan)[0] == "INSUFFICIENT_EVIDENCE"
    for st_ in ("OUT_OF_SAMPLE_SUPPORTED", "NO_ADDED_VALUE", "EXPLORATORY", "INSUFFICIENT_EVIDENCE"):
        assert st_ in C.STATUSES


def test_holm():
    np.testing.assert_allclose(H.holm([0.01, 0.04]), [0.02, 0.04])
    np.testing.assert_allclose(H.holm([0.03, 0.02]), [0.04, 0.04])
    np.testing.assert_allclose(H.holm([0.6, 0.9]), [1.0, 1.0])  # monotonluk korunur
    out = H.holm([np.nan, 0.02])
    assert np.isnan(out[0]) and out[1] == pytest.approx(0.02)


def test_prob_next_k():
    assert H.prob_next_k(0.1, 1) == pytest.approx(0.1)
    assert H.prob_next_k(0.1, 3) == pytest.approx(1 - 0.9 ** 3)
    assert H.prob_next_k([0.1, 0.2, 0.3, 0.9], 3) == pytest.approx(1 - 0.9 * 0.8 * 0.7)
    assert H.prob_next_k([0.25, 0.5], 1) == pytest.approx(0.25)  # "sonraki maç" = p_1
    mat = H.prob_next_k(np.array([[0.1, 0.1], [0.5, 0.0]]), 2)
    np.testing.assert_allclose(mat, [1 - 0.81, 0.5])
    vals = [H.prob_next_k(0.05, k) for k in range(1, 6)]
    assert all(b > a for a, b in zip(vals, vals[1:]))
    assert H.prob_next_k(0.0, 10) == 0.0 and H.prob_next_k(1.0, 2) == 1.0
    for bad in ((0.1, 0), (0.1, 1.5), ([0.1, 0.2], 3), (1.2, 1)):
        with pytest.raises(ValueError):
            H.prob_next_k(*bad)


def test_market_check_frees_s0_weight():
    """7b/5: piyasa kontrolünde S0 logitine serbest katsayı eklenir (S0 sıcaklığı); offset tek başına bırakılmaz."""
    assert H.MKT_EXTRA[0] == "s0_logit" and set(H.MKT_COLS) <= set(H.MKT_EXTRA)

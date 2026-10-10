"""S0'a ek katkı modelleri, ortak değerlendirme, A/B/C kontrolü ve ekonomik değer (sözleşme §6, §9, §10).

Yalnızca sentetik veri: bilinen İY/MS olasılıklarıyla üretilen maçlara, gerçek 1X2 olasılıklarından marjlı ve
gürültülü varsayımsal oranlar eklenir (maçların ~%5'inde oran yok).
"""

from __future__ import annotations

import dataclasses
import json
import math

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import check_grad
from scipy.special import expit

from bahis_tahmin.goals.ledger import event_id
from bahis_tahmin.goals.markets import HTFT_KEYS
from bahis_tahmin.sequences import config as C
from bahis_tahmin.sequences import models as M
from bahis_tahmin.sequences.frame import build_frame
from bahis_tahmin.sequences.synthetic import synthetic_matches
from bahis_tahmin.sequences.timeline import build_team_matches

SMALL_K = (20, 60)  # testlerde hız için küçük k ızgarası (gerçek çalışma config.S2_K kullanır)
FORBIDDEN = ("şike", "garanti", "kesin")


def _synthetic_with_odds(seed: int = 0, missing: float = 0.05):
    m, probs = synthetic_matches(seed=seed, n_leagues=4, n_teams=10)
    eid = [event_id(lg, d, h, a) for lg, d, h, a in zip(m["league"], m["date"], m["home"], m["away"])]
    P = probs.set_index("event_id").reindex(eid)[list(HTFT_KEYS)].to_numpy()
    ft = np.array([k.split("_")[2] for k in HTFT_KEYS])
    p3 = np.column_stack([P[:, ft == c].sum(axis=1) for c in ("1", "X", "2")])
    rng = np.random.default_rng(seed + 1)
    odds = 1.0 / (p3 * 1.05) * np.exp(rng.normal(0.0, 0.08, p3.shape))
    odds[rng.random(len(m)) < missing] = np.nan
    m = m.copy()
    m["o_h"], m["o_d"], m["o_a"] = odds[:, 0], odds[:, 1], odds[:, 2]
    return build_frame(build_team_matches(m), probs)


@pytest.fixture(scope="module")
def fr():
    return _synthetic_with_odds()


@pytest.fixture(scope="module")
def models(fr):
    return M.fit_models(fr, C.TARGETS_Q1, ks=SMALL_K)


@pytest.fixture(scope="module")
def space(fr):
    return M.s2_space(fr)[0]


# ----------------------------------------------------------------------------
# Offset destekli lojistik
# ----------------------------------------------------------------------------

def _logit_data(n=40_000, seed=3):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 3)) * np.array([1.0, 2.0, 0.5]) + np.array([0.0, 1.0, -2.0])
    off = rng.normal(-1.0, 0.6, n)
    beta, b0 = np.array([0.8, -0.25, 0.0]), 0.3
    y = (rng.random(n) < expit(off + b0 + X @ beta)).astype(float)
    return X, y, off, beta, b0


def test_offset_logistic_recovers_known_coefficients():
    X, y, off, beta, b0 = _logit_data()
    fit = M.fit_offset_logistic(X, y, off, 1e-8)
    assert fit.converged
    assert np.allclose(fit.coef, beta, atol=0.05)
    assert fit.intercept == pytest.approx(b0, abs=0.05)
    # Ölçek çağırandan: ortalama/std verilince katsayılar standart ölçektedir, tahminler aynıdır
    mu, sd = X.mean(axis=0), X.std(axis=0)
    fs = M.fit_offset_logistic(X, y, off, 1e-8, means=mu, stds=sd)
    assert np.allclose(fs.coef / sd, beta, atol=0.05)
    assert np.allclose(fs.predict(X, off), fit.predict(X, off), atol=1e-4)


def test_offset_logistic_analytic_gradient():
    X, y, off, _, _ = _logit_data(n=2_000, seed=5)
    for lam, icpt in ((0.0, True), (0.3, True), (0.1, False)):
        k = 4 if icpt else 3
        theta = np.random.default_rng(1).normal(0, 0.3, k)
        err = check_grad(lambda t: M._objective(t, X, y, off, lam, icpt)[0],
                         lambda t: M._objective(t, X, y, off, lam, icpt)[1], theta)
        assert err < 1e-5


def test_offset_logistic_lam_inf_is_offset_plus_intercept_only():
    X, y, off, _, _ = _logit_data(n=20_000, seed=7)
    fit = M.fit_offset_logistic(X, y, off, math.inf)
    assert np.all(fit.coef == 0.0) and len(fit.coef) == 3
    # Tek parametreli olabilirlik denklemi: Σ σ(offset + b0) = Σ y
    assert expit(off + fit.intercept).mean() == pytest.approx(y.mean(), abs=1e-6)
    none = M.fit_offset_logistic(X, y, off, math.inf, intercept=False)
    assert none.intercept == 0.0 and np.all(none.coef == 0.0)
    assert np.allclose(none.predict(X, off), expit(off))


def test_offset_logistic_penalty_shrinks_slopes_not_intercept():
    X, y, off, _, _ = _logit_data(n=20_000, seed=9)
    norms = [np.linalg.norm(M.fit_offset_logistic(X, y, off, lam).coef) for lam in (1e-4, 1e-2, 1.0, 100.0)]
    assert all(a > b for a, b in zip(norms, norms[1:]))
    big = M.fit_offset_logistic(X, y, off, 1e6)
    inf = M.fit_offset_logistic(X, y, off, math.inf)
    assert big.intercept == pytest.approx(inf.intercept, abs=1e-3)  # sabit terim cezasız


# ----------------------------------------------------------------------------
# Ortak satırlar ve S1
# ----------------------------------------------------------------------------

def test_shared_rows_definition_and_hash(fr):
    t = "GALIBIYET"
    mask, sha = M.shared_rows(fr, t, "parametre")
    expect = fr.eligible & (fr.period == "parametre") & np.isfinite(fr.y[t]) & np.isfinite(fr.p0[t])
    assert np.array_equal(mask, expect) and mask.sum() > 0
    mk, sha_mk = M.shared_rows(fr, t, "parametre", need_market=True)
    assert np.all(mask[mk]) and 0 < mk.sum() < mask.sum()
    assert np.isfinite(fr.mkt[mk]).all()
    assert sha != sha_mk and sha == M.shared_rows(fr, t, "parametre")[1]
    assert len(sha) == 64


def test_s1_protocol_select_refit_freeze(fr, models):
    t = "IY_GERIDE_MS_GALIP"
    r = models.s1[t]
    assert r.lam in C.S1_LAMBDAS
    assert [s["lam"] for s in r.selection] == [float(v) for v in C.S1_LAMBDAS]
    best = min(r.selection, key=lambda s: s["ll_parametre"])["ll_parametre"]
    assert next(s for s in r.selection if s["lam"] == r.lam)["ll_parametre"] == pytest.approx(best, abs=1e-12)
    # Arındırma: eğitim etiketleri değerlendirme döneminin ilk gününden önce bilinir
    assert pd.Timestamp(r.info["egitim_kesif"]["son_tarih"]) + pd.Timedelta(days=1) < pd.Timestamp("2013-07-01")
    assert pd.Timestamp(r.info["egitim_final"]["son_tarih"]) + pd.Timedelta(days=1) < pd.Timestamp("2019-07-01")
    assert r.info["egitim_final"]["n"] > r.info["egitim_kesif"]["n"]
    assert r.info["test_icinde_yeniden_uyum"] is False
    # Parametre tahminleri keşif uyumundan, test tahminleri dondurulmuş son uyumdan
    Xi, _, _, _ = M.s1_design(fr)
    off = M._logit(fr.p0[t])
    te = (fr.period == "test") & np.isfinite(fr.p0[t])
    pa = (fr.period == "parametre") & np.isfinite(fr.p0[t])
    assert np.allclose(r.pred[te], r.fit_final.predict(Xi[te], off[te]))
    assert np.allclose(r.pred[pa], r.fit_kesif.predict(Xi[pa], off[pa]))
    other = ~M._in_periods(fr, ("parametre", "test"))
    assert np.isnan(r.pred[other]).all()
    # Eksik yok (keşif ortalamasıyla doldurulur); tüm-NaN sütun (piyasa sürprizi) 0 sabitine iner
    assert np.isfinite(Xi).all()


# ----------------------------------------------------------------------------
# S2
# ----------------------------------------------------------------------------

def test_s2_adjust_formula_hand_example():
    p0, O, E, n, kappa = 0.3, 12.0, 8.0, 20.0, 5.0
    pbar = E / n
    lg = lambda v: math.log(v / (1 - v))  # noqa: E731
    expect = expit(lg(p0) + lg((O + kappa * pbar) / (n + kappa)) - lg((E + kappa * pbar) / (n + kappa)))
    assert M.s2_adjust(p0, O, E, n, kappa) == pytest.approx(expect, abs=1e-12)
    assert M.s2_adjust(0.3, 0.0, 0.0, 0.0, 5.0) == pytest.approx(0.3)  # komşu yoksa S0
    assert M.s2_adjust(0.3, 8.0, 8.0, 20.0, 80.0) == pytest.approx(0.3)  # O = E → düzeltme yok


def test_s2_neighbors_exclusions_cap_and_exactness(fr, space):
    """Kütüphane bilerek sorgu dönemiyle çakışır (arındırılmamış): kurallar komşu seçiminde uygulanmalı."""
    meta = M._nn_meta(fr)
    lib = fr.eligible & M._in_periods(fr, ("kesif", "parametre")) & np.isfinite(fr.y["GALIBIYET"])
    cand = np.where(fr.eligible & (fr.period == "parametre"))[0]
    rng = np.random.default_rng(0)
    q = np.zeros(len(fr.tm), dtype=bool)
    q[rng.choice(cand, 25, replace=False)] = True
    k = 40
    q_rows, nb, cnt = M.knn_neighbors(fr, lib, q, k, space=space, fetch_factor=1)  # küçük getirme → büyütme yolu
    assert nb.shape == (25, k)
    lib_rows = np.where(lib)[0]
    mirror = fr.tm["mirror_row"].to_numpy()
    for i, r in enumerate(q_rows):
        sel = nb[i][nb[i] >= 0]
        assert len(sel) == cnt[i] == k
        assert np.all(meta.day[sel] + 1 < meta.day[r])  # label_known_at < decision_time (yalnız önceki satırlar)
        assert np.all(meta.pair[sel] != meta.pair[r]) and mirror[r] not in sel and lib[mirror[r]]
        assert np.all(meta.day[sel] != meta.day[r])
        assert len(np.unique(meta.ts[sel])) == len(sel)  # takım-sezon başına en fazla 1
        # Kaba kuvvet: izinli satırlar, takım-sezon başına en yakın satır, en yakın k takım-sezon
        okl = lib_rows[(meta.day[lib_rows] + 1 < meta.day[r]) & (meta.pair[lib_rows] != meta.pair[r])]
        d = np.linalg.norm(space[okl] - space[r], axis=1)
        df = pd.DataFrame({"row": okl, "d": d, "ts": meta.ts[okl]}).sort_values(["d", "row"])
        expect = df.drop_duplicates("ts").head(k)["row"].to_numpy()
        assert set(expect) == set(sel)
        assert np.all(np.diff(np.linalg.norm(space[sel] - space[r], axis=1)) >= -1e-6)  # mesafe sırası


def test_s2_fit_libraries_selection_and_effective_sample(fr, models):
    r = models.s2["GALIBIYET"]
    assert r.k in SMALL_K and r.kappa in C.S2_KAPPA
    assert len(r.selection) == len(SMALL_K) * len(C.S2_KAPPA)
    assert r.info["test_icinde_yeniden_uyum"] is False and r.info["kutuphane_ornekleme"].startswith("yok")
    for period in ("parametre", "test"):
        e = r.eff[period]
        start = pd.Timestamp(C.PERIODS[period][0], 7, 1)
        assert pd.Timestamp(e["kutuphane_son_tarih"]) + pd.Timedelta(days=1) < start  # yalnızca önceki etiketler
        assert e["takim_sezon_min"] <= e["takim_sezon_ort"] <= r.k
        assert 1 <= e["takim_min"] <= e["takim_ort"] <= e["takim_sezon_ort"]
        assert e["mac_ort"] <= e["takim_sezon_ort"]
    assert r.eff["test"]["kutuphane_satir"] > r.eff["parametre"]["kutuphane_satir"]
    ev, _ = M.shared_rows(fr, "GALIBIYET", "test")
    assert np.isfinite(r.pred[ev]).all()
    assert np.nanmax(r.eff_rows["takim_sezon"]) <= r.k


def test_s2_default_grid_on_single_target(fr, space):
    """config ızgarası (200/500/1000 × 5/20/80): seçim ızgara içinde; k, takım-sezon sayısıyla sınırlı."""
    r = M.fit_s2(fr, "MAGLUBIYET")["MAGLUBIYET"]
    assert r.k in C.S2_K and r.kappa in C.S2_KAPPA and len(r.selection) == 9
    e = r.eff["parametre"]
    assert e["takim_sezon_ort"] <= min(r.k, e["kutuphane_takim_sezon"])


# ----------------------------------------------------------------------------
# S0p ve ortak değerlendirme
# ----------------------------------------------------------------------------

def test_p0_market_nan_without_odds(fr):
    t = "GALIBIYET"
    tr = M.train_mask(fr, t, ("kesif",), "parametre")
    ap = fr.period == "parametre"
    p, fit = M.p0_market(fr, t, tr, ap, return_fit=True)
    has = np.isfinite(fr.mkt).all(axis=1)
    assert np.isnan(p[ap & ~has]).all() and (ap & ~has).any()
    assert np.isfinite(p[ap & has & np.isfinite(fr.p0[t])]).all()
    assert np.isnan(p[~ap]).all()
    assert fit.n == int((tr & has).sum())


def test_models_evaluated_on_identical_rows(fr, models):
    for t in ("GALIBIYET", "IY_ONDE_MS_MAGLUP"):
        res = M.compare_models(fr, t, models)
        for period in ("parametre", "test"):
            rec = res["donemler"][period]
            _, sha_shared = M.shared_rows(fr, t, period, need_market=True)
            assert rec["satir_sha256"] == sha_shared == rec["satir_sha256_ortak_kume"]
            shas = {m: v["satir_sha256"] for m, v in rec["modeller"].items()}
            assert set(shas) == {"S0", "S0p", "S1", "S2"} and len(set(shas.values())) == 1
            assert len({v["n"] for v in rec["modeller"].values()}) == 1 and rec["n"] > 0
            assert rec["dislanan"]["n"] > 0  # oransız satırlar ayrıca raporlanır
            assert rec["etiket"] == M.PERIOD_LABELS[period] and rec["donem"] == period
            for name in ("S0p", "S1", "S2"):
                d = rec["s0_fark"][name]
                assert d["reps"] >= 1000 and d["ci_lo"] <= d["diff"] <= d["ci_hi"]
                assert "iso_hafta" in d and d["iso_hafta"]["n_clusters"] > d["n_clusters"]
            for v in rec["modeller"].values():
                assert {"log_kayip", "brier", "kal_egim", "kal_kesisim", "ece", "taban_oran"} <= set(v)
    with pytest.raises(ValueError):
        M.compare_models(fr, "GALIBIYET", models, n_boot=100)


def test_run_f3_holm_family(fr, models):
    res = M.run_f3(fr, models=models)
    assert res["hipotez_sayisi"] == 8 and len(res["holm"]) == 8
    for row in res["holm"]:
        assert row["statu"] in C.STATUSES
        assert row["p_holm_test"] >= row["p_test"] - 1e-12
    # Holm: en küçük p'nin düzeltmesi m·p
    p = np.array([r["p_test"] for r in res["holm"]])
    adj = np.array([r["p_holm_test"] for r in res["holm"]])
    i = int(np.argmin(p))
    assert adj[i] == pytest.approx(min(1.0, 8 * p[i]))
    text = json.dumps(res, default=float, ensure_ascii=False).lower()
    assert not any(w in text for w in FORBIDDEN)


def test_f3_status_rules():
    ok_neg = {"durum": "OK", "ci_hi": -0.001}
    ok_pos = {"durum": "OK", "ci_hi": 0.001}
    none = {"durum": "SATIR_YOK"}
    assert M._f3_status(ok_neg, ok_neg, 0.01, 0.01)[0] == "OUT_OF_SAMPLE_SUPPORTED"
    assert M._f3_status(ok_neg, ok_pos, 0.01, 0.01)[0] == "NO_ADDED_VALUE"  # test üst sınırı ≥ 0
    assert M._f3_status(ok_neg, ok_neg, 0.2, 0.01)[0] == "NO_ADDED_VALUE"  # parametre Holm geçmedi
    assert M._f3_status(none, none, np.nan, np.nan)[0] == "INSUFFICIENT_EVIDENCE"
    assert M._f3_status(ok_neg, none, 0.01, np.nan)[0] == "EXPLORATORY"
    assert M._f3_status(ok_neg, none, 0.3, np.nan)[0] == "NO_ADDED_VALUE"
    cases = (ok_neg, ok_pos, none)
    assert all(M._f3_status(a, b, p, q)[0] in C.STATUSES
               for a in cases for b in cases for p in (0.01, 0.5) for q in (0.01, 0.5))


def test_holm_hand_example():
    assert np.allclose(M.holm([0.01, 0.04, 0.03]), [0.03, 0.06, 0.06])
    out = M.holm([0.02, np.nan])
    assert out[0] == pytest.approx(0.02) and np.isnan(out[1])


# ----------------------------------------------------------------------------
# Küme bootstrap
# ----------------------------------------------------------------------------

def test_cluster_bootstrap_reproducible_with_seed():
    rng = np.random.default_rng(0)
    a, b = rng.normal(1.0, 1.0, 600), rng.normal(1.1, 1.0, 600)
    cl = np.repeat(np.arange(30), 20).astype(str)
    r1 = M.cluster_bootstrap_diff(a, b, cl, 1000, seed=C.SEED)
    r2 = M.cluster_bootstrap_diff(a, b, cl, 1000, seed=C.SEED)
    r3 = M.cluster_bootstrap_diff(a, b, cl, 1000, seed=C.SEED + 1)
    assert r1 == r2
    assert (r1["ci_lo"], r1["ci_hi"]) != (r3["ci_lo"], r3["ci_hi"])
    assert r1["diff"] == pytest.approx((a - b).mean()) and r1["n_clusters"] == 30
    with pytest.raises(ValueError):
        M.cluster_bootstrap_diff(a, b, cl, 999)


# ----------------------------------------------------------------------------
# Ekonomik değer (F6)
# ----------------------------------------------------------------------------

def test_economic_htft_targets_roi_unavailable(fr):
    mask = M.shared_rows(fr, "IY_GERIDE_MS_GALIP", "test")[0]
    for t in ("IY_GERIDE_MS_GALIP", "IY_ONDE_MS_MAGLUP", "IY_BERABERE_MS_GALIP"):
        res = M.economic_eval(fr, t, {"S0": fr.p0["GALIBIYET"]}, mask)
        assert res["roi"] == C.ROI_UNAVAILABLE and res["kaynaklar"]["S0"]["roi"] == C.ROI_UNAVAILABLE
        assert res["etiket"] == "varsayımsal (oran zamanı doğrulanamaz)"


def test_economic_one_bet_per_event_and_selection(fr):
    t = "GALIBIYET"
    mask = M.shared_rows(fr, t, "test")[0]
    probs = {"S0": fr.p0[t], "iyimser": np.clip(fr.p0[t] * 1.3, 0, 1)}
    res = M.economic_eval(fr, t, probs, mask, return_bets=True)
    for name, rec in res["kaynaklar"].items():
        keys = rec["bahis_anahtarlari"]
        assert len(keys) == len(set(keys)) == rec["n_bahis"] > 0
        assert all(k.rsplit("|", 1)[1] in ("1", "2") for k in keys)
    # İkiz/yinelenen satır: iki ev satırı aynı event_id'yi taşırsa aynı seçim (ev galibiyeti) tek bahistir
    rows = np.where(mask & fr.tm["is_home"].to_numpy() & np.isfinite(fr.tm["o_h"].to_numpy()))[0][:2]
    tm2 = fr.tm.copy()
    tm2.loc[rows[1], "event_id"] = tm2.loc[rows[0], "event_id"]
    fr2 = dataclasses.replace(fr, tm=tm2)
    res2 = M.economic_eval(fr2, t, probs, mask)
    assert res2["dislanan"]["yinelenen_mac_secim"] == 1
    assert res2["n_mac"] == res["n_mac"] - 1


def test_economic_loss_target_uses_opponent_win_odds_and_settles(fr):
    t = "MAGLUBIYET"
    mask = M.shared_rows(fr, t, "test")[0]
    res = M.economic_eval(fr, t, {"hep": np.ones(len(fr.tm))}, mask)  # p = 1 → oran ≥ 1,05 olan her maçta bahis
    tm = fr.tm
    home = tm["is_home"].to_numpy()
    o = np.where(home, tm["o_a"].to_numpy(), tm["o_h"].to_numpy())
    ok = mask & np.isfinite(o) & (o > 1) & np.isfinite(fr.y[t])
    bet = ok & (o - 1 >= C.EV_THRESHOLD)
    net = np.where(fr.y[t][bet] == 1, o[bet] - 1, -1.0).sum()
    rec = res["kaynaklar"]["hep"]
    assert res["n_mac"] == int(ok.sum())
    assert rec["n_bahis"] == int(bet.sum())
    assert rec["net"] == pytest.approx(net)
    assert rec["roi"] == pytest.approx(net / bet.sum())
    assert rec["roi_alt"] <= rec["roi"] <= rec["roi_ust"]


def test_economic_same_event_set_and_missing_odds(fr):
    t = "GALIBIYET"
    mask = M.shared_rows(fr, t, "test")[0]  # oransız satırlar dahil
    p_hole = fr.p0[t].copy()
    hole = np.where(mask)[0][:50]
    p_hole[hole] = np.nan
    res = M.economic_eval(fr, t, {"S0": fr.p0[t], "delikli": p_hole}, mask)
    tm = fr.tm
    o = np.where(tm["is_home"].to_numpy(), tm["o_h"].to_numpy(), tm["o_a"].to_numpy())
    has = np.isfinite(o) & (o > 1)
    assert res["dislanan"]["oran_yok"] == int((mask & ~has).sum()) > 0
    common = mask & has & np.isfinite(p_hole)
    assert res["n_mac"] == int(common.sum())  # her iki kaynak aynı maç kümesinde
    # Hiç oran yoksa ROI tanımsızdır (0 değil)
    tm2 = tm.copy()
    tm2[["o_h", "o_d", "o_a"]] = np.nan
    res2 = M.economic_eval(dataclasses.replace(fr, tm=tm2), t, {"S0": fr.p0[t]}, mask)
    assert res2["roi"] == C.ROI_UNAVAILABLE and res2["kaynaklar"]["S0"]["roi"] == C.ROI_UNAVAILABLE
    assert res2["kaynaklar"]["S0"]["roi"] != 0
    # Eşiği geçen bahis yoksa da ROI_UNAVAILABLE
    res3 = M.economic_eval(fr, t, {"dusuk": np.full(len(tm), 0.01)}, mask)
    assert res3["kaynaklar"]["dusuk"]["n_bahis"] == 0 and res3["kaynaklar"]["dusuk"]["roi"] == C.ROI_UNAVAILABLE


def test_run_f6_shapes(fr, models):
    res = M.run_f6(fr, models)
    assert set(res["hedefler"]) == set(C.TARGETS_Q1)
    for t in ("IY_GERIDE_MS_GALIP", "IY_ONDE_MS_MAGLUP"):
        assert res["hedefler"][t]["roi"] == C.ROI_UNAVAILABLE
    g = res["hedefler"]["GALIBIYET"]
    assert set(g["kaynaklar"]) == {"S0", "S0p", "S1", "S2", "Bet365_marjsiz"}
    assert g["n_mac"] > 0 and all(r["n_bahis"] >= 0 for r in g["kaynaklar"].values())
    text = json.dumps(res, default=float, ensure_ascii=False).lower()
    assert not any(w in text for w in FORBIDDEN)


# ----------------------------------------------------------------------------
# F5: A/B/C ek kontrolü
# ----------------------------------------------------------------------------

def test_abc_check_match_level_holm_and_exploratory_label(fr):
    tm = fr.tm
    home = tm["is_home"].to_numpy()
    rates = {s: float(np.nanmean(tm[s].to_numpy(dtype=float))) for s in M.ABC_MARKETS}
    s0 = pd.DataFrame({"event_id": tm.loc[home, "event_id"].to_numpy(), **{s: rates[s] for s in M.ABC_MARKETS}})
    res = M.abc_check(fr, s0)
    assert set(res["pazarlar"]) == set(M.ABC_MARKETS) and len(res["ozellikler"]) == 16
    n_pairs = int((fr.eligible & home & fr.eligible[tm["mirror_row"].to_numpy()] & (fr.period == "parametre")).sum())
    p_raw, p_adj = [], []
    for s, rec in res["pazarlar"].items():
        par, te = rec["donemler"]["parametre"], rec["donemler"]["test"]
        assert 0 < par["n"] <= n_pairs  # maç başına bir satır
        assert te["etiket"] == "EXPLORATORY"
        assert rec["statu"] in C.STATUSES and rec["statu"] != "OUT_OF_SAMPLE_SUPPORTED"
        assert pd.Timestamp(rec["egitim_son_tarih"]) + pd.Timedelta(days=1) < pd.Timestamp("2013-07-01")
        p_raw.append(rec["p_parametre"])
        p_adj.append(rec["p_holm_parametre"])
    assert np.allclose(M.holm(p_raw), p_adj)
    with pytest.raises(ValueError):
        M.abc_check(fr, pd.concat([s0, s0.head(1)]))

"""S4-MODEL-01: ölçütlerin bağımsız doğrulaması, aşama tanılaması, satır/etiket eşleşmesi ve sızıntı denetimi.

YALNIZCA açıkça SENTETİK veri (uydurma takımlar ve skorlar, sahte commit, ağ yok) kullanılır. Gerçek pilot sonuçları bu
testlerle doğrulanmış sayılmaz; testler kod yolunun doğruluğunu sınar.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bahis_tahmin.goals import diagnostics as G
from bahis_tahmin.goals.markets import PRIMARY_YES, SHORT, label_frame
from bahis_tahmin.goals.validation import calibration_slope, evaluate, season_year, walk_forward

RNG = np.random.default_rng(20261011)


def _logit(p):
    return np.log(p / (1 - p))


def _calibrated(n=4000, b=1.0, a=0.0, seed=0):
    """Gerçek olasılığı p olan sentetik sonuçlar; raporlanan tahmin r için logit P = a + b·logit r."""
    rng = np.random.default_rng(seed)
    r = 1 / (1 + np.exp(-rng.normal(-0.5, 0.8, n)))
    p_true = 1 / (1 + np.exp(-(a + b * _logit(r))))
    return rng.binomial(1, p_true).astype(float), r


# =============================================================== 1) bağımsız ölçütler
def test_independent_metrics_match_reference_libraries():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, roc_auc_score
    from sklearn.metrics import log_loss as sk_log_loss

    y, p = _calibrated()
    assert G.log_loss(y, p) == pytest.approx(sk_log_loss(y, p), abs=1e-12)
    # doğrudan formül, sınıf seçimi açık: y=1 için −ln p
    assert G.log_loss(np.array([1.0, 0.0]), np.array([0.8, 0.8])) == pytest.approx(-(np.log(0.8) + np.log(0.2)) / 2)
    assert G.brier(y, p) == pytest.approx(brier_score_loss(y, p), abs=1e-12)
    assert G.auc(y, p) == pytest.approx(roc_auc_score(y, p), abs=1e-12)
    from scipy.optimize import minimize

    fit = G.calibration_fit(y, p)
    ref = LogisticRegression(C=np.inf, tol=1e-12, max_iter=10000).fit(_logit(p)[:, None], y)
    assert fit["durum"] == G.KAL_TAMAM
    assert fit["egim"] == pytest.approx(ref.coef_[0, 0], abs=1e-6)
    assert fit["kesisim"] == pytest.approx(ref.intercept_[0], abs=1e-6)
    x = _logit(p)
    nll = lambda t: float(np.sum(np.logaddexp(0, t[0] + t[1] * x) - y * (t[0] + t[1] * x)))  # noqa: E731
    sp = minimize(nll, np.zeros(2), method="BFGS", options={"gtol": 1e-10})
    assert fit["kesisim"] == pytest.approx(sp.x[0], abs=1e-5) and fit["egim"] == pytest.approx(sp.x[1], abs=1e-5)
    # ürün fonksiyonu (sklearn, C=1e6) aynı eğimi verir; eğim gerçek değere yakın
    b, a = calibration_slope(y, p)
    assert b == pytest.approx(fit["egim"], abs=1e-4) and a == pytest.approx(fit["kesisim"], abs=1e-4)
    assert 0.85 < fit["egim"] < 1.15


@pytest.mark.parametrize("b_true", [1.0, 0.5, -1.0])
def test_slope_sign_and_reversed_predictions(b_true):
    y, p = _calibrated(b=b_true, seed=3)
    fit = G.calibration_fit(y, p)
    assert np.sign(fit["egim"]) == np.sign(b_true) and abs(fit["egim"] - b_true) < 0.2
    rev = G.calibration_fit(y, 1 - p)  # ters sıralama eğimin işaretini çevirir, büyüklüğü korur
    assert rev["egim"] == pytest.approx(-fit["egim"], abs=1e-8)
    assert G.auc(y, 1 - p) == pytest.approx(1 - G.auc(y, p), abs=1e-12)


def test_degenerate_inputs_never_produce_a_fake_slope():
    y, _ = _calibrated(n=500)
    for p in (np.full(500, 0.3), np.full(500, 0.6)):
        f = G.calibration_fit(y, p)
        assert f["durum"] == G.KAL_SABIT and f["egim"] != f["egim"]
        b, a = calibration_slope(y, p)  # S4-MODEL-01 düzeltmesi: ürün de sahte eğim üretmez
        assert b != b and a != a
    x = np.random.default_rng(1).normal(size=500)
    sep_y, sep_p = (x > 0).astype(float), 1 / (1 + np.exp(-x))
    assert G.calibration_fit(sep_y, sep_p)["durum"] == G.KAL_AYRISMA
    assert calibration_slope(sep_y, sep_p)[0] != calibration_slope(sep_y, sep_p)[0]
    assert G.calibration_fit(np.zeros(50), np.linspace(0.1, 0.9, 50))["durum"] == G.KAL_TEK_SINIF
    assert G.auc(np.zeros(50), np.linspace(0.1, 0.9, 50)) != G.auc(np.zeros(50), np.linspace(0.1, 0.9, 50))
    bad_p = np.r_[np.full(10, 0.3), np.nan]
    bad_y = np.r_[np.ones(5), np.zeros(5), np.nan]
    assert G.calibration_fit(np.r_[np.ones(5), np.zeros(6)], bad_p)["durum"] == G.KAL_GECERSIZ
    assert G.calibration_fit(bad_y, np.full(11, 0.3))["durum"] == G.KAL_GECERSIZ  # eksik hedef
    assert G.calibration_fit(np.r_[np.ones(5), np.zeros(5)], np.r_[np.full(9, 0.3), 1.2])["durum"] == G.KAL_GECERSIZ
    assert calibration_slope(np.r_[np.ones(5), np.zeros(6)], bad_p)[0] != calibration_slope(
        np.r_[np.ones(5), np.zeros(6)], bad_p)[0]
    with pytest.raises(ValueError):
        G.log_loss(np.r_[np.ones(5), np.zeros(6)], bad_p)
    with pytest.raises(ValueError):
        G.brier(bad_y, np.full(11, 0.3))


def test_narrow_prediction_range_has_wide_slope_uncertainty():
    """Çok dar olasılık aralığında eğim belirsizliği büyüktür; aralık gizlenmez (bootstrap)."""
    rng = np.random.default_rng(5)
    p = 0.35 + rng.normal(0, 0.003, 1200)
    y = rng.binomial(1, 0.35, 1200).astype(float)
    blocks = np.repeat(np.arange(120), 10)
    boot = G.block_bootstrap(y, p, np.full(1200, 0.35), blocks, reps=200)
    lo, hi = boot["egim_ara"]
    assert hi - lo > 10  # dar aralıkta eğim neredeyse tanımsız ölçüde belirsiz
    y2, p2 = _calibrated(n=1200, seed=6)
    lo2, hi2 = G.block_bootstrap(y2, p2, np.full(1200, y2.mean()), blocks, reps=200)["egim_ara"]
    assert hi2 - lo2 < 1.0 and lo2 < 1 < hi2


def test_season_shift_can_make_pooled_slope_negative_while_within_season_is_positive():
    """Sezon düzeyi kayma: her sezon içinde doğru sıralama, sezonlar arasında ters ortalama → toplu eğim negatif
    olabilir; sezon sabit etkili eğim içerideki ilişkiyi gösterir."""
    rng = np.random.default_rng(7)
    ys, ps, gs = [], [], []
    for g, (pred_shift, true_rate) in enumerate(((0.15, 0.25), (-0.15, 0.45))):
        r = np.clip(0.33 + rng.normal(0, 0.01, 1500), 0.01, 0.99)
        p_true = 1 / (1 + np.exp(-(_logit(true_rate) + 1.0 * (_logit(r) - _logit(0.33)))))
        ys.append(rng.binomial(1, p_true))
        ps.append(np.clip(r + pred_shift, 0.01, 0.99))
        gs.append(np.full(1500, g))
    y, p, grp = np.concatenate(ys).astype(float), np.concatenate(ps), np.concatenate(gs)
    assert G.calibration_fit(y, p)["egim"] < 0
    assert G.calibration_fit_grouped(y, p, grp)["egim"] > 0


def test_bins_and_distribution_are_order_independent():
    y, p = _calibrated(n=1000, seed=9)
    perm = RNG.permutation(1000)
    assert G.bins_table(y, p) == G.bins_table(y[perm], p[perm])
    d1, d2 = G.distribution(p), G.distribution(p[perm])
    assert d1.keys() == d2.keys() and all(d1[k] == pytest.approx(d2[k], abs=1e-15) for k in d1)


# =============================================================== 2) etiketler ve sınıf yönü
def test_market_labels_and_positive_class_direction():
    df = pd.DataFrame({"fthg": [2, 3, 1, 0, 2], "ftag": [2, 1, 0, 0, 1], "hthg": [1, 2, 0, 0, np.nan],
                       "htag": [1, 0, 0, 0, np.nan]})
    lab = label_frame(df, PRIMARY_YES)
    # A: iki yarıda da iki takım gol; B: MS toplam ≥ 4; C: İY toplam ≥ 2; İY yoksa A ve C bilinmiyor (0 değil)
    assert lab["BTTS_BOTH_HALVES_YES"].tolist()[:4] == [1.0, 0.0, 0.0, 0.0]
    assert lab["FT_OVER_3_5"].tolist() == [1.0, 1.0, 0.0, 0.0, 0.0]
    assert lab["FH_OVER_1_5"].tolist()[:4] == [1.0, 1.0, 0.0, 0.0]
    assert np.isnan(lab.loc[4, "BTTS_BOTH_HALVES_YES"]) and np.isnan(lab.loc[4, "FH_OVER_1_5"])
    assert SHORT == {"BTTS_BOTH_HALVES_YES": "A", "FT_OVER_3_5": "B", "FH_OVER_1_5": "C"}


def test_challenger_probability_column_is_the_positive_class():
    from bahis_tahmin.goals.model import C1_FEATURES, ChallengerLR

    n = 3000
    rng = np.random.default_rng(11)
    df = pd.DataFrame({f: rng.normal(size=n) for f in C1_FEATURES})
    for k in ("l1h", "l1a", "l2h", "l2a", "lh", "la", "s1"):
        df[k] = np.abs(df[k]) + 0.5
    df["rho1"] = 0.0
    z = 1.5 * (df["lh"] - df["lh"].mean())
    for key in PRIMARY_YES:
        df[key] = rng.binomial(1, 1 / (1 + np.exp(-z))).astype(float)
    m = ChallengerLR(C1_FEATURES).fit(df)
    p = m.predict(df)
    for key, s in SHORT.items():
        assert list(m.models[key][-1].classes_) == [0, 1]
        assert np.corrcoef(p[s], df[key])[0, 1] > 0.2  # P(Y=1) artan gerçekleşmeyle artar


# =============================================================== 3) aşamalar ve satır eşlemesi
@pytest.fixture(scope="module")
def synth_feat():
    from bahis_tahmin.goals.features import build_goal_features
    from bahis_tahmin.selftest import synthetic_matches

    m = synthetic_matches(n_seasons=7, n_teams=20, seed=3, start_year=2015, half_time=True)
    feat, _ = build_goal_features(m)
    years = season_year(feat["date"])
    return m, feat, [int(years.max())]


@pytest.fixture(scope="module")
def stage_run(synth_feat):
    _, feat, years = synth_feat
    rows, folds = G.stage_walk_forward(feat, years)
    pred, _ = walk_forward(feat, years, ["M0_taban", "M10_ipf_kosullu"])
    return rows, folds, pred


def test_stage_run_reproduces_product_walk_forward_exactly(stage_run):
    rows, folds, pred = stage_run
    assert len(rows) == len(pred) and (rows.index == pred.index).all()
    for s in "ABC":
        assert np.array_equal(rows[f"S4_nihai:{s}"].to_numpy(), pred[f"M10_ipf_kosullu:{s}"].to_numpy(), equal_nan=True)
        assert np.array_equal(rows[f"S0_M0:{s}"].to_numpy(), pred[f"M0_taban:{s}"].to_numpy(), equal_nan=True)
    cmp = G.compare_validation(evaluate(G.as_validation_pred(rows), ["M10_ipf_kosullu"]),
                               evaluate(pred, ["M10_ipf_kosullu"]))
    assert cmp["birebir"] and cmp["max_mutlak_fark"] == 0.0
    # optimizasyon kayıtları: M5 iki tur + q kalibrasyonu; LR yakınsama bilgisi
    f = folds[0]
    assert [o["cagiran"] for o in f["optimizasyon"]] == ["_fit_calibrated", "_fit_calibrated", "_fit_qcal"]
    assert set(f["lojistik"]) == {"A", "B", "C"} and all("yakinsadi" in v for v in f["lojistik"].values())
    assert f["egitim_son"] < f["test_ilk"]  # eğitim test döneminden önce biter


def test_stage_relations_hold(stage_run):
    rows, _, _ = stage_run
    chk = G.structural_checks(rows)
    for st in ("S1_yapisal", "S3_ipf", "S4_nihai"):
        assert chk[st]["n"] > 0
        assert chk[st]["A>BC"] == chk[st]["A>B"] == chk[st]["A>C"] == chk[st]["BC>B"] == chk[st]["BC>C"] == 0
        assert chk[st]["aralik_disi"] == 0
    assert chk["B_S3_S4_max_fark"] == 0.0 and chk["C_S3_S4_max_fark"] == 0.0  # A kalibrasyonu B/C'yi değiştirmez
    assert chk["B_S3_hedef_max_fark"] < 1e-9 and chk["C_S3_hedef_max_fark"] < 1e-9  # IPF hedeflere oturur
    assert chk["S1_yapisal_vs_base_predict_B_max_fark"] < 1e-9
    q = rows["q_kal"].to_numpy(dtype=float)
    assert np.all((q[np.isfinite(q)] > 0) & (q[np.isfinite(q)] < 1))


def test_predictions_are_tied_to_rows_not_positions(synth_feat):
    """Satır sırası karıştırılınca her olayın tahmini aynı kalır; yalnızca tahminler kayarsa olay kimliği yakalar."""
    from bahis_tahmin.goals.model import GoalModel

    _, feat, years = synth_feat
    f = feat.copy()
    f["fold"] = season_year(f["date"])
    train = f[f["fold"] < years[0]]
    test = f[f["fold"] == years[0]]
    m = GoalModel("M10_ipf_kosullu").fit(train)
    a = G._stage_frame(m, test)
    shuffled = test.sample(frac=1.0, random_state=1)
    b = G._stage_frame(m, shuffled).loc[a.index]
    cols = [c for c in a.columns if ":" in c]
    assert np.allclose(a[cols].to_numpy(dtype=float), b[cols].to_numpy(dtype=float), equal_nan=True, atol=1e-12)
    one = G._stage_frame(m, test.iloc[[5]])  # tek satır tahmini toplu tahminle aynı (satırlar arası bulaşma yok)
    assert np.allclose(one[cols].to_numpy(dtype=float), a.iloc[[5]][cols].to_numpy(dtype=float), equal_nan=True)


def test_metrics_invariant_to_joint_shuffle_but_not_to_misaligned_predictions(stage_run):
    rows, _, _ = stage_run
    key, s = "FT_OVER_3_5", "B"
    mask = G.eval_mask(rows, key)
    y = rows.loc[mask, key].to_numpy(dtype=float)
    p = rows.loc[mask, f"S4_nihai:{s}"].to_numpy(dtype=float)
    perm = np.random.default_rng(2).permutation(len(y))
    assert G.log_loss(y[perm], p[perm]) == pytest.approx(G.log_loss(y, p), abs=1e-15)
    assert G.calibration_fit(y[perm], p[perm])["egim"] == pytest.approx(G.calibration_fit(y, p)["egim"], abs=1e-9)
    assert G.log_loss(y, p[perm]) != pytest.approx(G.log_loss(y, p), abs=1e-6)
    ev = rows.loc[mask, "event_id"].to_numpy()
    assert len(set(ev)) == len(ev)  # olay kimliği tekil: kayan eşleşme kimlikle yakalanır
    shifted = pd.Series(p[perm], index=ev[perm])
    assert not np.array_equal(shifted.reindex(ev).to_numpy(), p[perm])


def test_stage_report_uses_one_sample_per_market(stage_run):
    rows, _, _ = stage_run
    rep = G.stage_report(rows, with_boot=False)
    for key in PRIMARY_YES:
        mk = rep[SHORT[key]]
        assert mk["n"] == int(G.eval_mask(rows, key).sum())
        assert {v["n"] for v in mk["asamalar"].values()} == {mk["n"]}
        assert mk["asamalar"]["S0_M0"]["dll_ref"] == 0.0
    assert rep["B"]["n"] >= rep["A"]["n"]  # B yalnızca MS ister; A/C ilk yarı skoru ister


# =============================================================== 4) gelecek bilgisi sızıntısı
def test_league_base_rate_feature_uses_only_previous_days():
    """bB (M0 taban) bağımsız hesapla: yalnızca daha önceki günlerin etiketleri, zamanla azalan ağırlık."""
    from bahis_tahmin.goals.features import BASE_XI, EPOCH, build_goal_features
    from bahis_tahmin.selftest import synthetic_matches

    m = synthetic_matches(n_seasons=2, n_teams=10, seed=4, start_year=2020, half_time=True)
    feat, _ = build_goal_features(m)
    feat = feat.sort_values(["date", "home"], kind="mergesort")
    lab = (feat["fthg"] + feat["ftag"] >= 4).astype(float).to_numpy()
    days = ((feat["date"] - EPOCH).dt.days).to_numpy()
    expected = []
    for d in days:
        prev = days < d
        w = np.exp(-BASE_XI * (d - days[prev]))
        last = days[prev].max() if prev.any() else d
        # önsel (0.5 × 2 sözde gözlem) son güncelleme gününe kadar sönümlenir
        prior_w = 2.0 * np.exp(-BASE_XI * (last - days[prev].min())) if prev.any() else 2.0
        prior_w *= np.exp(-BASE_XI * (d - last)) if prev.any() else 1.0
        expected.append((0.5 * prior_w + np.sum(w * lab[prev])) / (prior_w + np.sum(w)))
    assert np.allclose(feat["bB"].to_numpy(), expected, atol=1e-9)


def test_same_day_and_own_results_do_not_change_features():
    from bahis_tahmin.goals.features import build_goal_features
    from bahis_tahmin.selftest import synthetic_matches

    m = synthetic_matches(n_seasons=3, n_teams=10, seed=8, start_year=2020, half_time=True)
    feat, _ = build_goal_features(m)
    day = m["date"].iloc[len(m) // 2]
    same = m.index[m["date"] == day]
    m2 = m.copy()
    m2.loc[same, ["fthg", "ftag", "hthg", "htag"]] = [9, 9, 4, 4]  # o günün bütün sonuçları değişir
    feat2, _ = build_goal_features(m2)
    cols = ["bA", "bB", "bC", "s1", "l1h", "l2a", "lh", "h_o35", "a_sc1", "h2h_B"]
    assert np.allclose(feat.loc[same, cols].to_numpy(dtype=float), feat2.loc[same, cols].to_numpy(dtype=float),
                       equal_nan=True)
    later = m.index[m["date"] > day]
    assert not np.allclose(feat.loc[later, "bB"].to_numpy(), feat2.loc[later, "bB"].to_numpy())


# =============================================================== 5) pilot tanılama aracı
TEAMS20 = [f"Pilot Takim {c}" for c in "ABCDEFGHIJKLMNOPQRST"]


def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def diag_pilot(tmp_path_factory):
    """20 sentetik takım, 6 tamamlanmış + devam eden sezon; eğitilmiş pilot modeli (bir doğrulama katı)."""
    import test_s4_pilot as T
    from takvim_yardim import circle_rounds

    from bahis_tahmin import pilot as PL

    def season_bytes(y, played_before=None):
        rng = np.random.default_rng(y)
        start, ms = T._season_start(y), []
        for r, pairs in enumerate(circle_rounds(TEAMS20, 2)):
            day = start + dt.timedelta(days=7 * r)
            for h, a in pairs:
                mm = T._m(str(day), h, a, rnd=f"Matchday {r + 1}")
                if played_before is None or day < played_before:
                    hg, ag = int(rng.poisson(1.5)), int(rng.poisson(1.2))
                    # kaynağın kuralı: MS 0-0 maçta İY alanı yazılmaz
                    mm["score"] = [0, 0] if hg == ag == 0 else {
                        "ht": [int(rng.integers(0, hg + 1)), int(rng.integers(0, ag + 1))], "ft": [hg, ag]}
                ms.append(mm)
        return T._of(ms)

    base = tmp_path_factory.mktemp("s4m")
    mp = pytest.MonkeyPatch()
    mp.setenv("BAHIS_TAHMIN_HOME", str(base / "kullanici"))
    try:
        files = {T._folder(T.Y): season_bytes(T.Y, T.AS_OF.date())}
        for k in range(1, 7):
            files[T._folder(T.Y - k)] = season_bytes(T.Y - k)
        home = base / "pilot"
        PL.prepare(home, ref=T.REF_A, completed=6, downloader=T._StubDownloader(files), now=T.AS_OF)
        trained = PL.train(home)
    finally:
        mp.undo()
    return {"home": home, "base": base, "train": trained}


def test_diagnose_reproduces_saved_validation_and_leaves_pilot_unchanged(diag_pilot, tmp_path, monkeypatch):
    from bahis_tahmin import pilot as PL

    monkeypatch.setenv("BAHIS_TAHMIN_HOME", str(diag_pilot["base"] / "kullanici"))
    home = diag_pilot["home"]
    before = _snapshot(home)
    out = PL.diagnose(home, tmp_path / "tani")
    assert _snapshot(home) == before  # pilot verisi, modeli ve bilgileri değişmedi
    assert out["ayni_deney"] is True and out["max_mutlak_fark"] == 0.0
    names = {p.name for p in (tmp_path / "tani").iterdir()}
    assert names == {PL.DIAG_MARKER, PL.DIAG_SUMMARY, PL.DIAG_ROWS, "on_kayit.json"}
    summ = json.loads((tmp_path / "tani" / PL.DIAG_SUMMARY).read_text("utf-8"))
    assert summ["veri_sha256"] == diag_pilot["train"]["veri_sha256"]
    for s in "ABC":
        assert set(summ["olcutler"][s]["asamalar"]) == set(G.STAGES)
        assert summ["olcutler"][s]["asamalar"]["S4_nihai"]["bootstrap"]["tohum"] == G.BOOT_SEED
    rows = pd.read_csv(tmp_path / "tani" / PL.DIAG_ROWS)
    assert rows["event_id"].is_unique and rows["event_id"].str.startswith("E0|").all()


def test_diagnose_refuses_unsafe_or_untrusted_inputs(diag_pilot, tmp_path, monkeypatch):
    import shutil

    from bahis_tahmin import pilot as PL

    user = diag_pilot["base"] / "kullanici"
    monkeypatch.setenv("BAHIS_TAHMIN_HOME", str(user))
    home = diag_pilot["home"]
    for bad in (home, home / "tani", user, user / "tani"):
        with pytest.raises(PL.PilotError):
            PL.diagnose(home, bad)
    other = tmp_path / "dolu"
    other.mkdir()
    (other / "x.txt").write_text("x", encoding="utf-8")
    with pytest.raises(PL.PilotError):
        PL.diagnose(home, other)
    with pytest.raises(PL.PilotError):
        PL.diagnose(home, "")
    # model dosyası değiştirilirse (manifest özeti tutmaz) yüklenmez ve ölçüt üretilmez
    copy = tmp_path / "pilot_kopya"
    shutil.copytree(home, copy)
    with open(copy / PL.GOAL_ENGINE_FILE, "ab") as fh:
        fh.write(b"0")
    with pytest.raises(PL.PilotError, match="Model yüklenmedi"):
        PL.diagnose(copy, tmp_path / "t1")
    assert not (tmp_path / "t1" / PL.DIAG_SUMMARY).exists()
    # veri modelin eğitildiği veriden farklıysa model yüklenmeden reddedilir
    copy2 = tmp_path / "pilot_kopya2"
    shutil.copytree(home, copy2)
    info = json.loads((copy2 / PL.MODEL_INFO).read_text("utf-8"))
    info["veri_sha256"] = "0" * 64
    (copy2 / PL.MODEL_INFO).write_text(json.dumps(info), encoding="utf-8")
    with pytest.raises(PL.PilotError, match="göstermiyor"):
        PL.diagnose(copy2, tmp_path / "t2")
    # model yoksa
    copy3 = tmp_path / "pilot_kopya3"
    shutil.copytree(home, copy3)
    (copy3 / PL.GOAL_ENGINE_FILE).unlink()
    with pytest.raises(PL.PilotError):
        PL.diagnose(copy3, tmp_path / "t3")


def test_cli_pilot_diagnose_help_and_errors(tmp_home, tmp_path, capsys):
    from bahis_tahmin.cli import main

    with pytest.raises(SystemExit) as e:
        main(["pilot-tani", "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "--ev" in out and "--cikti" in out
    with pytest.raises(SystemExit):
        main(["pilot-tani", "--ev", str(tmp_path)])  # --cikti zorunlu
    capsys.readouterr()
    assert main(["pilot-tani", "--ev", str(tmp_path / "yok"), "--cikti", str(tmp_path / "t")]) == 3
    assert "hazırlanmış bir pilot klasörü değil" in capsys.readouterr().err
    assert not (tmp_path / "t").exists()
    assert sorted(p.name for p in tmp_home.iterdir()) == []


def test_profiles_describe_missing_halftime_and_quarantine():
    m = pd.DataFrame({"season": ["2030/31"] * 4 + ["2031/32"] * 2, "home": list("ABCDAB"), "away": list("BCDABC"),
                      "fthg": [0, 2, 3, 1, 4, 0], "ftag": [0, 1, 2, 0, 1, 1],
                      "hthg": [0, np.nan, 1, 0, np.nan, 0], "htag": [0, np.nan, 1, 0, 1, 0]})
    prof = G.ht_missing_profile(m)
    assert prof["toplam"] == 2 and prof["sezon"]["2030/31"] == {"eksik": 1, "mac": 4}
    assert prof["ms_gol_grubu"]["4+"]["eksik"] == 1 and prof["ms_gol_grubu"]["2-3"]["eksik"] == 1
    data = json.dumps({"matches": [
        {"round": "Matchday 1", "date": "2030-08-10", "team1": "A", "team2": "B", "score": {"ft": [1, 0]}},
        {"round": "Matchday 38", "date": "2030-07-20", "team1": "C", "team2": "D", "score": {"ft": [1, 1]}}]}).encode()
    q = G.quarantine_profile(data, "E0", "2030/31")
    assert q["karantina"]["TARIH_SEZON_DISI"]["sayi"] == 1 and q["karantina"]["TARIH_SEZON_DISI"]["yillar"] == ["2030"]
    assert q["gecerli_ilk"] == "2030-08-10"


# =============================================================== 6) kanıtlanmış kusurların düzeltmeleri (S4-MODEL-01)
def _mle_slope(y, p):
    from scipy.optimize import minimize

    x = _logit(p)
    xc = x - x.mean()
    sd = xc.std()
    z = xc / sd
    nll = lambda t: float(np.sum(np.logaddexp(0, t[0] + t[1] * z) - y * (t[0] + t[1] * z)))  # noqa: E731
    return minimize(nll, np.zeros(2), method="BFGS", options={"gtol": 1e-12}).x[1] / sd


def test_near_constant_predictions_give_the_mle_not_a_solver_artifact():
    """Önceki çözüm (ölçeksiz tasarım + varsayılan tolerans) dar aralıkta veriden bağımsız ~0,93 eğim veriyordu."""
    rng = np.random.default_rng(4)
    y = rng.binomial(1, 0.068, 1131).astype(float)
    p = 0.068 + rng.uniform(0, 1e-3, 1131)
    b, _ = calibration_slope(y, p)
    assert b == pytest.approx(_mle_slope(y, p), rel=1e-4)
    f = G.calibration_fit(y, p)
    assert f["durum"] == G.KAL_TAMAM and f["egim"] == pytest.approx(b, rel=1e-4)
    near = np.zeros(20)
    near[[0, 8]] = 1
    f = G.calibration_fit(near, 0.1 + np.arange(20) * 1e-9)  # önce LinAlgError fırlatıyordu
    assert f["durum"] in (G.KAL_TAMAM, G.KAL_YAKINSAMADI, G.KAL_SABIT)


def test_out_of_range_probabilities_are_rejected_not_clipped():
    y = np.array([0, 1, 0, 1, 1, 0, 0, 1.0])
    p = np.array([0.2, 0.3, 0.5, 0.6, 1.5, 0.4, 0.7, 0.45])
    assert calibration_slope(y, p)[0] != calibration_slope(y, p)[0]
    assert calibration_slope(y, np.r_[p[:4], -0.1, p[5:]])[0] != calibration_slope(y, np.r_[p[:4], -0.1, p[5:]])[0]
    assert G.calibration_fit(y, p)["durum"] == G.KAL_GECERSIZ


def test_existing_valid_slopes_are_unchanged_by_the_fix():
    y, p = _calibrated(n=3000, seed=12)
    from sklearn.linear_model import LogisticRegression

    ref = LogisticRegression(C=np.inf, tol=1e-12, max_iter=10000).fit(_logit(p)[:, None], y)
    b, a = calibration_slope(y, p)
    assert b == pytest.approx(ref.coef_[0, 0], abs=1e-6) and a == pytest.approx(ref.intercept_[0], abs=1e-6)


def test_logical_half_time_for_nil_nil_reaches_labels_and_halftime_features():
    """v2: MS 0-0 maçın İY'si 0-0 kaydedilir → A ve C etiketleri 0 (bilinmiyor değil) ve İY güç izleyicileri bu maçı
    görür; v1'de bu maçlar İY'ye bağlı her bileşenden dışlanıyordu (rastgele olmayan seçim)."""
    from bahis_tahmin.data.parsers import OPENFOOTBALL_RESULT_PARSER, OPENFOOTBALL_RESULT_PARSER_V1, parse_openfootball_results
    from bahis_tahmin.goals.features import build_goal_features

    rng = np.random.default_rng(13)
    teams = [f"T{i}" for i in range(8)]
    ms = []
    start = dt.date(2030, 8, 3)
    for r in range(28):
        for i in range(0, 8, 2):
            h, a = teams[(i + r) % 8], teams[(i + 1 + 2 * r) % 8]
            if h == a:
                continue
            hg, ag = int(rng.poisson(1.2)), int(rng.poisson(1.0))
            score = [0, 0] if hg == ag == 0 else {"ht": [min(hg, 1), 0], "ft": [hg, ag]}
            ms.append({"round": f"Matchday {r + 1}", "date": str(start + dt.timedelta(days=7 * r)), "team1": h,
                       "team2": a, "score": score})
    data = json.dumps({"matches": ms}).encode()
    v1 = parse_openfootball_results(data, "E0", "2030/31", OPENFOOTBALL_RESULT_PARSER_V1).matches
    v2 = parse_openfootball_results(data, "E0", "2030/31", OPENFOOTBALL_RESULT_PARSER).matches
    nil = (v2["fthg"] == 0) & (v2["ftag"] == 0)
    assert nil.sum() > 0 and v2.loc[nil, "iy_mantiksal"].all() and (v2.loc[nil, ["hthg", "htag"]] == 0).all().all()
    l1, l2 = label_frame(v1, PRIMARY_YES), label_frame(v2, PRIMARY_YES)
    assert l1.loc[nil, "BTTS_BOTH_HALVES_YES"].isna().all() and l1.loc[nil, "FH_OVER_1_5"].isna().all()
    assert (l2.loc[nil, "BTTS_BOTH_HALVES_YES"] == 0).all() and (l2.loc[nil, "FH_OVER_1_5"] == 0).all()
    assert l1["FT_OVER_3_5"].equals(l2["FT_OVER_3_5"])  # MS'ye bağlı etiket değişmez
    f1, _ = build_goal_features(v1)
    f2, _ = build_goal_features(v2)
    later = f2["date"] > v2.loc[nil, "date"].min()
    assert not np.allclose(f1.loc[later, "bC"].to_numpy(), f2.loc[later, "bC"].to_numpy())  # 0-0'lar taban orana girer
    assert np.allclose(f1["bB"].to_numpy(), f2["bB"].to_numpy())


def test_provenance_verifies_records_of_both_parser_versions(tmp_path):
    from bahis_tahmin.data.parsers import OPENFOOTBALL_RESULT_PARSER, OPENFOOTBALL_RESULT_PARSER_V1, parse_openfootball_results
    from bahis_tahmin.data.provenance import OPENFOOTBALL_REPO, SourceFile, rows_sha256, verify_results

    data = json.dumps({"matches": [
        {"round": "Matchday 1", "date": "2030-08-10", "team1": "A", "team2": "B", "score": [0, 0]},
        {"round": "Matchday 1", "date": "2030-08-10", "team1": "C", "team2": "D",
         "score": {"ht": [1, 0], "ft": [2, 1]}}]}).encode()
    rel = "openfootball/2030-31/en.1.json"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_bytes(data)
    for ver in (OPENFOOTBALL_RESULT_PARSER_V1, OPENFOOTBALL_RESULT_PARSER):
        res = parse_openfootball_results(data, "E0", "2030/31", ver)
        rec = SourceFile(OPENFOOTBALL_REPO, "2030-31/en.1.json", "a" * 40, "u", "t", res.sha256, "E0", "2030/31", ver,
                         len(res.matches), rows_sha256(res.matches), rel).to_dict()
        assert verify_results(res.matches, [rec], tmp_path) == (True, [])
        other = OPENFOOTBALL_RESULT_PARSER if ver == OPENFOOTBALL_RESULT_PARSER_V1 else OPENFOOTBALL_RESULT_PARSER_V1
        assert verify_results(res.matches, [dict(rec, parser=other)], tmp_path)[0] is False  # sürüm karıştırılamaz
    with pytest.raises(ValueError):
        parse_openfootball_results(data, "E0", "2030/31", "baska-v9")


def test_diagnose_comparative_rerun_with_other_parser(diag_pilot, tmp_path, monkeypatch):
    from bahis_tahmin import pilot as PL
    from bahis_tahmin.data.parsers import OPENFOOTBALL_RESULT_PARSER, OPENFOOTBALL_RESULT_PARSER_V1

    monkeypatch.setenv("BAHIS_TAHMIN_HOME", str(diag_pilot["base"] / "kullanici"))
    home = diag_pilot["home"]
    before = _snapshot(home)
    same = PL.diagnose(home, tmp_path / "ayni", parser=OPENFOOTBALL_RESULT_PARSER)  # depo zaten v2: yeniden üretim
    assert same["mod"] == "yeniden_uretim" and same["ayni_deney"] is True
    out = PL.diagnose(home, tmp_path / "v1", parser=OPENFOOTBALL_RESULT_PARSER_V1)
    assert _snapshot(home) == before  # pilot verisi ve modeli değişmez; yeni model yazılmaz
    assert out["mod"] == "karsilastirmali_tekrar" and out["ayni_deney"] is False
    ch = out["karsilastirma_verisi"]
    assert ch["ms_ayni"] and ch["iy_degisen_mac"] > 0 and ch["iy_degisen_mac"] == ch["iy_degisen_ms_0_0"]
    summ = json.loads((tmp_path / "v1" / PL.DIAG_SUMMARY).read_text("utf-8"))
    assert summ["ayristirici"] == OPENFOOTBALL_RESULT_PARSER_V1 and summ["ilk_yari_eksik"]["toplam"] == ch["iy_degisen_mac"]
    with pytest.raises(PL.PilotError):
        PL.diagnose(home, tmp_path / "x", parser="baska-v9")

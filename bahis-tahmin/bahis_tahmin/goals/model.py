"""Gol pazarları modelleri: referanslar, ortak yarı-gol modeli ve karşılaştırma sınıflandırıcısı.

Modeller (hepsi yalnızca walk-forward özelliklerden beslenir):
  M0_taban      : ligin zamanla azalan ağırlıklı geçmiş taban oranı (her pazar ayrı).
  M1_ft_bolme   : maç sonu Poisson güçleri, lig ilk yarı gol payıyla yarılara bölünür; yarılar bağımsız.
  M2_yari_dc    : ilk yarı ve ikinci yarı için ayrı takım güçleri; yarılar bağımsız (+İY ρ düzeltmesi).
  M3_kosullu    : M2 + İY skor durumuna bağlı ikinci yarı çarpanları (geçmişten öğrenilir).
  M4_kirilgan   : M3 + ortak maç temposu (gama kırılganlığı φ) + yarı yoğunluk ölçekleri (k1, k2).
  M5_kalibre    : yarı gol yoğunlukları log ölçekte öğrenilen katsayılarla yeniden ölçeklenir
                  (yarıya özel ve maç sonu güç tahminlerinin karışımı + küçültme), + durum çarpanları + φ.
                  Katsayılar ortak olabilirlik en büyüklenerek YALNIZCA eğitim döneminde öğrenilir.
  M6_kalibre_form: M5 + takımların yakın dönem yarı bazlı gol atma/yeme sıklıkları.
  M7_negbin     : M5 yapısı, ancak yarı-takım golleri negatif binom (fazla dağılım α1, α2 öğrenilir).
  M8_negbin_form: M7 + yarı bazlı form sıklıkları.
  M9_ipf        : M5 ortak dağılımı, B ve C marjinalleri kalibre edilmiş lojistik tahminlere üstel eğimle
                  (IPF / I-projeksiyon) eşitlenir; A ve dört koşul aynı eğilmiş dağılımdan türetilir.
  M10_ipf_kosullu: M9 + A'nın B∩C içindeki koşullu payı q = P(A | B∩C) iki parametreli lojistikle
                  kalibre edilir (yalnızca eğitimde B∩C gerçekleşmiş maçlarda öğrenilir). A = P(B∩C)·q_kal
                  olduğundan A ≤ P(B∩C) ≤ min(B, C) yapısal olarak korunur; kırpma kullanılmaz.
  C1_lojistik   : her pazar için ayrı lojistik regresyon (yalnızca karşılaştırma; pazarlar arası
                  tutarlılığı garanti etmez, bu yüzden öneri motorunda kullanılmaz).

M1–M4 tüm pazarları tek bir ortak dağılımdan türetir.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .joint import (
    N_STATES, OUTPUT_KEYS, htft_regions, joint_probs, joint_regions, loglik_nb, loglik_params, loglik_rates,
    tilt_to_targets,
)
from .markets import PRIMARY_YES

VARIANTS = ("M0_taban", "M1_ft_bolme", "M2_yari_dc", "M3_kosullu", "M4_kirilgan", "M5_kalibre", "M6_kalibre_form",
            "M7_negbin", "M8_negbin_form", "M9_ipf", "M10_ipf_kosullu")
IPF_VARIANTS = ("M9_ipf", "M10_ipf_kosullu")
CALIBRATED = ("M5_kalibre", "M6_kalibre_form", "M7_negbin", "M8_negbin_form")
NEGBIN = ("M7_negbin", "M8_negbin_form")
FORM_VARIANTS = ("M6_kalibre_form", "M8_negbin_form")
JOINT_VARIANTS = VARIANTS[1:]
MODEL_VERSION = "goal-joint-1.0"
FEATURE_VERSION = "goal-feat-1.0"
REQUIRED = ["l1h", "l1a", "l2h", "l2a", "lh", "la", "s1"]


def usable_rows(df: pd.DataFrame) -> np.ndarray:
    """Model girdileri hazır satırlar (takım güçleri kurulmuş)."""
    return df[REQUIRED].notna().all(axis=1).to_numpy()


def ht_rows(df: pd.DataFrame) -> np.ndarray:
    return (df["issues"] == "").to_numpy() & df[["hthg", "htag"]].notna().all(axis=1).to_numpy()


@dataclass
class GoalModel:
    variant: str = "M4_kirilgan"
    shrink: float = 30.0  # durum çarpanları için sözde gol sayısı (küçülme)
    mult_h: np.ndarray = field(default_factory=lambda: np.ones(N_STATES))
    mult_a: np.ndarray = field(default_factory=lambda: np.ones(N_STATES))
    k1: float = 1.0
    k2: float = 1.0
    phi: float = 0.0
    n_train: int = 0
    trained_until: str = ""
    version: str = MODEL_VERSION
    coef: np.ndarray | None = None  # M5–M8 log-yoğunluk katsayıları
    base: "GoalModel | None" = None  # M9: yapı modeli (M5)
    calibrator: "ChallengerLR | None" = None  # M9: B ve C marjinal kalibratörü
    alpha1: float = 0.0  # negatif binom fazla dağılımı (İY)
    alpha2: float = 0.0  # (2Y)
    form_means: dict = field(default_factory=dict)
    qcal: tuple | None = None  # M10: (a, b) — logit q_kal = a + b·logit q

    # ----------------------------------------------------------------- yardımcı
    def _rates(self, df: pd.DataFrame):
        if self.variant == "M1_ft_bolme":
            s1 = df["s1"].to_numpy(dtype=float)
            lh, la = df["lh"].to_numpy(dtype=float), df["la"].to_numpy(dtype=float)
            return s1 * lh, s1 * la, (1 - s1) * lh, (1 - s1) * la, None
        return (
            df["l1h"].to_numpy(dtype=float), df["l1a"].to_numpy(dtype=float),
            df["l2h"].to_numpy(dtype=float), df["l2a"].to_numpy(dtype=float),
            df["rho1"].to_numpy(dtype=float),
        )

    # ------------------------------------------------- M5/M6 tasarım matrisleri
    _FORM = {
        "r1h": ("h_sc1", "a_cc1"), "r1a": ("a_sc1", "h_cc1"),
        "r2h": ("h_sc2", "a_cc2"), "r2a": ("a_sc2", "h_cc2"),
    }

    def _design(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        """Her yoğunluk için açıklayıcı değişkenler (log ölçek)."""
        lg = lambda v: np.log(np.clip(np.asarray(v, dtype=float), 1e-3, None))  # noqa: E731
        s1 = np.clip(df["s1"].to_numpy(dtype=float), 0.2, 0.8)
        lh, la = df["lh"].to_numpy(dtype=float), df["la"].to_numpy(dtype=float)
        cols = {
            "r1h": [lg(df["l1h"]), lg(lh * s1)], "r1a": [lg(df["l1a"]), lg(la * s1)],
            "r2h": [lg(df["l2h"]), lg(lh * (1 - s1))], "r2a": [lg(df["l2a"]), lg(la * (1 - s1))],
        }
        if self.variant in FORM_VARIANTS:
            for r, feats in self._FORM.items():
                for f in feats:
                    v = df[f].to_numpy(dtype=float)
                    mean = self.form_means.get(f, 0.5)
                    v = np.clip(np.where(np.isfinite(v), v, mean), 0.05, 0.95)
                    cols[r].append(np.log(v / (1 - v)) - np.log(mean / (1 - mean)))
        return {k: np.column_stack(v) for k, v in cols.items()}

    def _cal_rates(self, D: dict, theta: np.ndarray) -> np.ndarray:
        """θ = [a1h, a1a, a2h, a2a, β1(k), β2(k), log φ]; aynı yarıda ev/deplasman eğimleri ortaktır."""
        k = D["r1h"].shape[1]
        a1h, a1a, a2h, a2a = theta[:4]
        b1, b2 = theta[4:4 + k], theta[4 + k:4 + 2 * k]
        return np.column_stack([
            np.exp(a1h + D["r1h"] @ b1), np.exp(a1a + D["r1a"] @ b1),
            np.exp(a2h + D["r2h"] @ b2), np.exp(a2a + D["r2a"] @ b2),
        ])

    def _fit_calibrated(self, d: pd.DataFrame) -> None:
        if self.variant in FORM_VARIANTS:
            self.form_means = {f: float(np.nanmean(d[f].to_numpy(dtype=float)))
                               for feats in self._FORM.values() for f in feats}
        D = self._design(d)
        h1h, h1a = d["hthg"].to_numpy(dtype=int), d["htag"].to_numpy(dtype=int)
        x = np.column_stack([h1h, h1a, d["fthg"].to_numpy(dtype=int) - h1h, d["ftag"].to_numpy(dtype=int) - h1a]).astype(float)
        c = np.minimum(h1h, 2) * 3 + np.minimum(h1a, 2)
        k = D["r1h"].shape[1]
        nb = self.variant in NEGBIN
        n_extra = 2 if nb else 1  # NB: log α1, log α2 ; diğer: log φ
        theta = np.concatenate([[0.0] * 4, [0.5, 0.5] + [0.0] * (k - 2), [0.5, 0.5] + [0.0] * (k - 2),
                                [np.log(0.05)] * n_extra])
        mh, ma = np.ones(N_STATES), np.ones(N_STATES)

        pen = 1e-3

        def nll(th):
            lam = self._cal_rates(D, th[:-n_extra])
            lam[:, 2] *= mh[c]
            lam[:, 3] *= ma[c]
            if nb:
                ll = loglik_nb(x, lam, float(np.exp(th[-2])), float(np.exp(th[-1])))
            else:
                ll = loglik_rates(x, lam, float(np.exp(th[-1])))
            return -float(ll.sum()) + 0.5 * float(np.sum(th[:-n_extra] ** 2)) * pen

        def nll_grad(th):
            """Katsayılar için analitik gradyan; dağılım parametreleri için merkezi fark."""
            lam = self._cal_rates(D, th[:-n_extra])
            lam[:, 2] *= mh[c]
            lam[:, 3] *= ma[c]
            if nb:
                a = (float(np.exp(th[-2])),) * 2 + (float(np.exp(th[-1])),) * 2
                g = np.empty_like(lam)
                for j in range(4):
                    if a[j] <= 1e-8:
                        g[:, j] = x[:, j] - lam[:, j]
                    else:
                        sz = 1.0 / a[j]
                        g[:, j] = x[:, j] - (x[:, j] + sz) * lam[:, j] / (sz + lam[:, j])
            else:
                phi = float(np.exp(th[-1]))
                if phi <= 1e-8:
                    g = x - lam
                else:
                    X = x.sum(axis=1, keepdims=True)
                    L = lam.sum(axis=1, keepdims=True)
                    g = x - (X + 1.0 / phi) * phi * lam / (1.0 + phi * L)
            kk = D["r1h"].shape[1]
            grad = np.zeros_like(th)
            grad[0], grad[1], grad[2], grad[3] = g[:, 0].sum(), g[:, 1].sum(), g[:, 2].sum(), g[:, 3].sum()
            grad[4:4 + kk] = D["r1h"].T @ g[:, 0] + D["r1a"].T @ g[:, 1]
            grad[4 + kk:4 + 2 * kk] = D["r2h"].T @ g[:, 2] + D["r2a"].T @ g[:, 3]
            grad = -grad
            grad[:-n_extra] += pen * th[:-n_extra]
            f0 = nll(th)
            for j in range(len(th) - n_extra, len(th)):
                e = np.zeros_like(th)
                e[j] = 1e-5
                grad[j] = (nll(th + e) - nll(th - e)) / 2e-5
            return f0, grad

        for _ in range(2):  # yoğunluk katsayıları ↔ durum çarpanları (iki tur yeterli)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = minimize(nll_grad, theta, method="L-BFGS-B", jac=True,
                               bounds=[(None, None)] * (len(theta) - n_extra) + [(np.log(1e-4), np.log(2.0))] * n_extra)
            theta = res.x
            lam = self._cal_rates(D, theta[:-n_extra])
            kk = self.shrink
            mh = (np.bincount(c, weights=x[:, 2], minlength=N_STATES) + kk) / (
                np.bincount(c, weights=lam[:, 2], minlength=N_STATES) + kk)
            ma = (np.bincount(c, weights=x[:, 3], minlength=N_STATES) + kk) / (
                np.bincount(c, weights=lam[:, 3], minlength=N_STATES) + kk)
        self.coef = theta[:-n_extra]
        if nb:
            self.alpha1, self.alpha2 = float(np.exp(theta[-2])), float(np.exp(theta[-1]))
            self.phi = 0.0
        else:
            self.phi = float(np.exp(theta[-1]))
            if self.phi < 2e-4:
                self.phi = 0.0
        self.mult_h, self.mult_a = mh, ma

    # -------------------------------------------------------------------- eğit
    def fit(self, train: pd.DataFrame) -> "GoalModel":
        ok = usable_rows(train) & ht_rows(train)
        d = train[ok]
        self.n_train = int(len(d))
        self.trained_until = str(pd.Timestamp(train["date"].max()).date()) if len(train) else ""
        if self.variant in ("M0_taban", "M1_ft_bolme", "M2_yari_dc") or len(d) < 500:
            return self
        if self.variant in CALIBRATED:
            self._fit_calibrated(d)
            return self
        if self.variant in IPF_VARIANTS:
            self.base = GoalModel("M5_kalibre", shrink=self.shrink).fit(train)
            self.calibrator = ChallengerLR(C1_FEATURES).fit(train)
            if self.variant == "M10_ipf_kosullu":
                self._fit_qcal(d)
            return self
        h1h, h1a = d["hthg"].to_numpy(dtype=int), d["htag"].to_numpy(dtype=int)
        h2h = d["fthg"].to_numpy(dtype=int) - h1h
        h2a = d["ftag"].to_numpy(dtype=int) - h1a
        l1h, l1a, l2h, l2a, _ = self._rates(d)
        c = np.minimum(h1h, 2) * 3 + np.minimum(h1a, 2)
        k = self.shrink
        obs_h = np.bincount(c, weights=h2h, minlength=N_STATES)
        exp_h = np.bincount(c, weights=l2h, minlength=N_STATES)
        obs_a = np.bincount(c, weights=h2a, minlength=N_STATES)
        exp_a = np.bincount(c, weights=l2a, minlength=N_STATES)
        self.mult_h = (obs_h + k) / (exp_h + k)
        self.mult_a = (obs_a + k) / (exp_a + k)
        if self.variant == "M4_kirilgan":
            def nll(z):
                k1, k2, phi = np.exp(z[0]), np.exp(z[1]), np.exp(z[2])
                return -loglik_params(h1h, h1a, h2h, h2a, l1h, l1a, l2h, l2a, self.mult_h, self.mult_a, k1, k2, phi)

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = minimize(nll, x0=np.log([1.0, 1.0, 0.05]), method="L-BFGS-B",
                               bounds=[(np.log(0.5), np.log(2.0)), (np.log(0.5), np.log(2.0)), (np.log(1e-4), np.log(1.0))])
            self.k1, self.k2, self.phi = (float(v) for v in np.exp(res.x))
            if self.phi < 2e-4:
                self.phi = 0.0
        return self

    # ------------------------------------------------------------------ tahmin
    def predict(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        n = len(df)
        if self.variant == "M0_taban":
            out = {k: np.full(n, np.nan) for k in OUTPUT_KEYS}
            out["A"], out["B"], out["C"] = (df[c].to_numpy(dtype=float) for c in ("bA", "bB", "bC"))
            out["tail"] = np.zeros(n)
            return out
        if self.variant in IPF_VARIANTS:
            out = self._predict_ipf(df)
            if self.variant == "M10_ipf_kosullu" and self.qcal is not None:
                out["A"] = out["BC"] * self._q_cal(out["A"], out["BC"])
            return out
        l1h, l1a, l2h, l2a, rho1 = self._rates(df)
        bad = ~(np.isfinite(l1h) & np.isfinite(l1a) & np.isfinite(l2h) & np.isfinite(l2a))
        if self.variant in CALIBRATED:
            bad |= ~(np.isfinite(df["lh"].to_numpy(dtype=float)) & np.isfinite(df["s1"].to_numpy(dtype=float)))
            if self.coef is None:
                raise RuntimeError("Model eğitilmedi")
            lam = self._cal_rates(self._design(df), self.coef)
            lam = np.where(bad[:, None], 1.0, lam)
            out = joint_probs(lam[:, 0], lam[:, 1], lam[:, 2], lam[:, 3], None,
                              mult_h=self.mult_h, mult_a=self.mult_a, phi=self.phi,
                              alpha1=self.alpha1, alpha2=self.alpha2)
            for k in out:
                out[k] = np.where(bad, np.nan, out[k])
            return out
        safe = lambda x: np.where(bad, 1.0, x)  # noqa: E731 - geçersiz satırlar sonra NaN yapılır
        out = joint_probs(
            safe(l1h), safe(l1a), safe(l2h), safe(l2a), rho1,
            mult_h=self.mult_h if self.variant in ("M3_kosullu", "M4_kirilgan") else None,
            mult_a=self.mult_a if self.variant in ("M3_kosullu", "M4_kirilgan") else None,
            phi=self.phi if self.variant == "M4_kirilgan" else 0.0,
            k1=self.k1 if self.variant == "M4_kirilgan" else 1.0,
            k2=self.k2 if self.variant == "M4_kirilgan" else 1.0,
        )
        for k in out:
            out[k] = np.where(bad, np.nan, out[k])
        return out

    def structural_rates(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """M5 yapısının (çarpanlar hariç) dört yarı yoğunluğu ve geçersiz satır maskesi."""
        m = self.base if self.variant in IPF_VARIANTS else self
        bad = ~usable_rows(df)
        lam = m._cal_rates(m._design(df), m.coef)
        return np.where(bad[:, None], 1.0, lam), bad

    @staticmethod
    def _logit_q(a: np.ndarray, bc: np.ndarray) -> np.ndarray:
        q = np.clip(np.where(bc > 0, a / np.where(bc > 0, bc, 1.0), 0.5), 1e-6, 1 - 1e-6)
        return np.log(q / (1 - q))

    def _q_cal(self, a: np.ndarray, bc: np.ndarray) -> np.ndarray:
        ca, cb = self.qcal
        return 1.0 / (1.0 + np.exp(-(ca + cb * self._logit_q(a, bc))))

    def _fit_qcal(self, d: pd.DataFrame) -> None:
        """q = P(A | B∩C) kalibrasyonu: yalnızca B ve C'nin gerçekleştiği eğitim maçlarında A'nın lojistik modeli."""
        yb, yc, ya = (d[k].to_numpy(dtype=float) for k in ("FT_OVER_3_5", "FH_OVER_1_5", "BTTS_BOTH_HALVES_YES"))
        sel = (yb == 1) & (yc == 1) & np.isfinite(ya)
        if sel.sum() < 200:
            self.qcal = None
            return
        p = self._predict_ipf(d[sel])
        z = self._logit_q(p["A"], p["BC"])
        y = ya[sel]
        ok = np.isfinite(z)
        z, y = z[ok], y[ok]

        def nll(t):
            eta = t[0] + t[1] * z
            return float(np.sum(np.logaddexp(0.0, eta) - y * eta))

        def grad(t):
            r = 1.0 / (1.0 + np.exp(-(t[0] + t[1] * z))) - y
            return np.array([r.sum(), (r * z).sum()])

        res = minimize(nll, np.array([0.0, 1.0]), jac=grad, method="L-BFGS-B")
        self.qcal = (float(res.x[0]), float(res.x[1]))

    def _predict_ipf(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        if self.base is None or self.calibrator is None:
            raise RuntimeError("Model eğitilmedi")
        out = self.base.predict(df)  # yapısal (eğilmemiş) dağılım: ikincil pazarlar için
        lam, bad = self.structural_rates(df)
        reg = joint_regions(lam[:, 0], lam[:, 1], lam[:, 2], lam[:, 3], self.base.mult_h, self.base.mult_a, self.base.phi)
        cal = self.calibrator.predict(df)
        t_b = np.clip(np.nan_to_num(cal["B"], nan=0.5), 1e-4, 1 - 1e-4)
        t_c = np.clip(np.nan_to_num(cal["C"], nan=0.5), 1e-4, 1 - 1e-4)
        tilted = tilt_to_targets(reg, t_b, t_c)
        for k in ("A", "B", "C", "BC", "h1_home", "h1_away", "h2_home", "h2_away"):
            out[k] = np.where(bad | ~np.isfinite(cal["B"]) | ~np.isfinite(cal["C"]), np.nan, tilted[k])
        out["structural_A"], out["structural_B"], out["structural_C"] = reg["A"], reg["BC"] + reg["BnC"], reg["BC"] + reg["nBC"]
        return out

    def htft_probs(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        """9 İY/MS olasılığı, A/B/C ile AYNI dağılımdan (``predict`` çıktısını değiştirmez).

        Yapısal dağılımın İY sonucu × MS sonucu × bölge kütleleri (``joint.htft_regions``), ``predict``'in
        kullandığı ağırlıklarla yeniden ağırlıklandırılır: IPF varyantlarında B/C bölge eğimleri, M10'da ek
        olarak B∩C içindeki A payının kalibrasyonu (A ve (B∩C)∖A bölgelerine ayrı çarpan). Böylece İY/MS
        hücrelerinin bölge toplamları ``predict``'in A, B, C değerleriyle tutarlıdır. İY ızgarası dışındaki
        kuyruk kütlesinin İY/MS dağılımı bilinmediği için ``HTFT_KUYRUK`` olarak ayrı raporlanır (9 hücre +
        kuyruk = 1); yeniden ölçekleme yapılmaz.
        """
        if self.variant not in IPF_VARIANTS and not (self.variant in CALIBRATED and self.alpha1 == 0 and self.alpha2 == 0):
            raise NotImplementedError(f"{self.variant} için İY/MS türetimi tanımlı değil")
        m = self.base if self.variant in IPF_VARIANTS else self
        if m is None or m.coef is None:
            raise RuntimeError("Model eğitilmedi")
        lam, bad = self.structural_rates(df)
        H = htft_regions(lam[:, 0], lam[:, 1], lam[:, 2], lam[:, 3], m.mult_h, m.mult_a, m.phi)
        n = len(df)
        if self.variant in IPF_VARIANTS:
            reg = joint_regions(lam[:, 0], lam[:, 1], lam[:, 2], lam[:, 3], m.mult_h, m.mult_a, m.phi)
            cal = self.calibrator.predict(df)
            t_b = np.clip(np.nan_to_num(cal["B"], nan=0.5), 1e-4, 1 - 1e-4)
            t_c = np.clip(np.nan_to_num(cal["C"], nan=0.5), 1e-4, 1 - 1e-4)
            til = tilt_to_targets(reg, t_b, t_c)
            w = til["weights"]
            w_a = w_bcna = w["BC"]
            if self.variant == "M10_ipf_kosullu" and self.qcal is not None:
                q = reg["A"] / np.maximum(reg["BC"], 1e-300)
                qc = self._q_cal(til["A"], til["BC"])
                w_a = w["BC"] * qc / np.maximum(q, 1e-300)
                w_bcna = w["BC"] * (1 - qc) / np.maximum(1 - q, 1e-300)
            w5 = np.stack([w_a, w_bcna, w["BnC"], w["nBC"], w["nn"]], axis=1)
            bad = bad | ~np.isfinite(cal["B"]) | ~np.isfinite(cal["C"])
        else:
            w5 = np.ones((n, 5))
        T = (H * w5[:, None, None, :]).sum(axis=3)  # (n, 3, 3)
        codes = ("1", "X", "2")
        out = {f"HTFT_{codes[i]}_{codes[j]}": np.where(bad, np.nan, T[:, i, j]) for i in range(3) for j in range(3)}
        out["HTFT_KUYRUK"] = np.where(bad, np.nan, 1.0 - T.sum(axis=(1, 2)))
        return out

    def interval(self, df: pd.DataFrame, draws: int = 200, seed: int = 20261010, level: float = 0.8):
        """Girdi belirsizliğinden olasılık aralığı (Monte Carlo).

        Yöntem: takım gücü tahminlerinin (log λ) standart hataları Poisson modellerinin ters Hessian'ından
        gelir. Her taraf (ev/deplasman) için ilk yarı ve ikinci yarı hataları BAĞIMSIZ çekilir (farklı gol
        verisinden kestirilirler); maç sonu hatası, λ_MS ≈ λ_İY + λ_2Y ilişkisinden yarı hatalarının
        yoğunluk ağırlıklı birleşimi olarak türetilir ve kendi standart hatasına ölçeklenir. (Aynı takım
        gücünün üç tahminini bağımsız bozmak, kalibratördeki zıt işaretli katsayılar nedeniyle aralığı
        yapay olarak genişletir.) Her çekilişte tüm tahmin hattı (kalibratör + ortak dağılım + IPF)
        yeniden çalışır. Kalibratör katsayı belirsizliği yok sayılır. Tohum ve tekrar sayısı kayıtlıdır.
        Bu aralık model varsayımlarına bağlıdır; gerçek olasılığın kesin sınırı DEĞİLDİR.
        """
        if self.variant == "M0_taban":
            return None
        rng = np.random.default_rng(seed)
        n = len(df)

        def col(name, default=np.nan):
            return df[name].to_numpy(dtype=float) if name in df.columns else np.full(n, default)

        # Tüm çekilişler tek bir büyük tabloda (çekiliş-major sıra) tahmin edilir
        pert = df.iloc[np.tile(np.arange(n), draws)].reset_index(drop=True)
        for side in ("h", "a"):
            l1, l2, lf = col(f"l1{side}"), col(f"l2{side}"), col(f"l{side}")
            s1 = np.nan_to_num(col(f"se1{side}"), nan=0.3)
            s2 = np.nan_to_num(col(f"se2{side}"), nan=0.3)
            sf = np.nan_to_num(col(f"se{side}"), nan=0.3)
            d1 = rng.normal(0.0, 1.0, (draws, n)) * s1
            d2 = rng.normal(0.0, 1.0, (draws, n)) * s2
            w1 = np.nan_to_num(l1, nan=0.5)
            w2 = np.nan_to_num(l2, nan=0.5)
            sd = np.sqrt((w1 * s1) ** 2 + (w2 * s2) ** 2) / np.maximum(w1 + w2, 1e-9)
            df_noise = (w1 * d1 + w2 * d2) / np.maximum(w1 + w2, 1e-9) * (sf / np.maximum(sd, 1e-9))
            pert[f"l1{side}"] = (l1 * np.exp(d1)).ravel()
            pert[f"l2{side}"] = (l2 * np.exp(d2)).ravel()
            pert[f"l{side}"] = (lf * np.exp(df_noise)).ravel()
        p = self.predict(pert)
        res = {key: p[s].reshape(draws, n) for key, s in
               (("BTTS_BOTH_HALVES_YES", "A"), ("FT_OVER_3_5", "B"), ("FH_OVER_1_5", "C"))}
        lo, hi = (1 - level) / 2, 1 - (1 - level) / 2
        out = {k: (np.nanquantile(v, lo, axis=0), np.nanquantile(v, hi, axis=0)) for k, v in res.items()}
        out["meta"] = {"draws": draws, "seed": seed, "level": level,
                       "method": "girdi belirsizliği Monte Carlo (ters Hessian SH; yarı hataları bağımsız, "
                                 "maç sonu hatası yarıların birleşimi)"}
        return out


# ----------------------------------------------------------------------------
# Karşılaştırma (challenger) sınıflandırıcısı
# ----------------------------------------------------------------------------

C1_FEATURES = [
    "l1h", "l1a", "l2h", "l2a", "lh", "la", "bA", "bB", "bC", "s1",
    "h_sc1", "h_cc1", "h_sc2", "h_cc2", "h_both", "h_o35", "h_cs",
    "a_sc1", "a_cc1", "a_sc2", "a_cc2", "a_both", "a_o35", "a_cs",
    "h_rest", "a_rest", "season_n",
]
C1_H2H = ["h2h_n", "h2h_B", "h2h_C"]


class ChallengerLR:
    """Her pazar için ayrı düzenlileştirilmiş lojistik regresyon (yalnızca kıyas amaçlı)."""

    def __init__(self, features=None, C: float = 0.1):
        self.features = list(features or C1_FEATURES)
        self.C = C
        self.models = {}

    def fit(self, train: pd.DataFrame) -> "ChallengerLR":
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        ok = usable_rows(train)
        for key in PRIMARY_YES:
            m = ok & train[key].notna().to_numpy()
            y = train.loc[m, key].to_numpy(dtype=int)
            if len(np.unique(y)) < 2:
                continue
            pipe = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                 LogisticRegression(C=self.C, max_iter=2000))
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.models[key] = pipe.fit(train.loc[m, self.features], y)
        return self

    def predict(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        out = {}
        for key, short in zip(PRIMARY_YES, ("A", "B", "C")):
            m = self.models.get(key)
            out[short] = m.predict_proba(df[self.features])[:, 1] if m is not None else np.full(len(df), np.nan)
        return out

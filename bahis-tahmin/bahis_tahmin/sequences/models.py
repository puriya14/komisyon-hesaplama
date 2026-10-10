"""S0'a ek katkı modelleri ve ortak değerlendirme (sözleşme §6, §9 F3/F5/F6, §10).

* ``fit_offset_logistic``: S0 logiti sabit (offset) lojistik regresyon; L-BFGS + analitik gradyan; sabit terim
  cezasız; amaç = ortalama log-kayıp + (λ/2)·‖β‖² (glmnet kuralı; sklearn C = 1/(n·λ)); λ = ∞ → yalnız offset + sabit.
* S1: ``fr.s1`` özellikleri (eksikler keşif ortalamasıyla doldurulur, gösterge sütunları ``features``'ta hazır),
  ölçek keşiften; keşifte uyum → parametre döneminde λ seçimi → keşif + parametre (arındırılmış) yeniden uyum →
  test için DONDURMA (test içinde yeniden uyum yok).
* S2 (kNN): S1 özellikleri + takım/rakip S0 gücü; keşiften standart ölçek; Öklid uzaklığı (sklearn
  ``NearestNeighbors``, kaba kuvvet). Komşular yalnızca ``label_known_at < decision_time`` (maç günü + 1 < sorgu
  günü) kütüphane satırlarından; aynı pair_id ve aynı gün dışlanır; takım-sezon başına en fazla 1 (mesafe sırasında
  her takım-sezonun ilk = en yakın satırı). Kütüphane: parametre değerlendirmesi için keşif, test için keşif +
  parametre (arındırılmış). (k, κ) parametre döneminde seçilir. Kütüphane ÖRNEKLENMEZ (tam arama); bellek, sorgu
  parçalarıyla sınırlanır (``chunk_cells``) ve yetmeyen sorgularda getirilen komşu sayısı uyarlanarak büyütülür.
* S0p: kalibre S0 logiti offset + [S0 sıcaklığı (logit p0), logit piyasa galip, logit piyasa mağlup] (takım
  perspektifi, marjsız Bet365) ile hedef başına cezasız lojistik; oran yoksa NaN.
* ``compare_models``: S0, S0p, S1, S2 her dönemde TEK ortak satır kümesinde (kesişim; satır kimliği SHA-256);
  S1/S2 için 7b yanlışlama uyarlaması (1 lig/takım çıkarma, 2 en çok katkı veren %1, 3 sezon yönü, 5 piyasa
  kontrolü: S1 özellikleri S0p offsetiyle / S2 düzeltmesi S0p üzerine, 6 karşı örnekler).
  ``run_f3``: 4 hedef × 2 model tek yönlü Holm; OUT_OF_SAMPLE_SUPPORTED ayrıca 7b'nin iki dönemde geçmesini ister.
  ``abc_check`` (F5), ``economic_eval`` / ``run_f6`` (F6, varsayımsal).

Tüm belirsizlik aralıkları lig-sezon kümeli bootstrap (``fr.cluster``; ISO hafta blokları duyarlılık);
rastgelelik ``config.SEED`` tabanlı ``np.random.default_rng``.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Iterator, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import norm

from ..goals.validation import calibration_bins, calibration_slope
from ..goals.value import expected_value
from . import config as C
from .features import S1_FEATURES
from .frame import ResearchFrame

EPS = 1e-9
EVAL_PLAN = (("parametre", ("kesif",)), ("test", ("kesif", "parametre")))  # (değerlendirme dönemi, uyum dönemleri)
PERIOD_LABELS = {
    "parametre": "Parametre dönemi (2013/14–2018/19): S1 λ ve S2 (k, κ) bu dönemde seçildi — seçim iyimserliği içerir.",
    "test": ("Test dönemi (2019/20–2025/26): tek seferlik, dondurulmuş uyum. Koşullu örüntüler için ön-kayıtlı; "
             "S0 İY/MS kalibrasyonu test döneminde görülmüş (sözleşme §5)."),
}
F3_MODELS = ("S1", "S2")
S2_EXTRA = ("s0_guc", "rakip_s0_guc")
ABC_FEATURES = ("trail5", "lead5", "comeback10", "leadloss10", "ppg5", "form10", "gd2h10", "improve10")
ABC_MARKETS = ("A", "B", "C")
ECON_LABEL = "varsayımsal (oran zamanı doğrulanamaz)"
# Hedef → (ev satırında oran sütunu, deplasman satırında oran sütunu, ev satırı seçimi, deplasman satırı seçimi)
ECON_TARGETS = {
    "GALIBIYET": ("o_h", "o_a", "1", "2"),
    "MAGLUBIYET": ("o_a", "o_h", "2", "1"),  # mağlubiyet = rakibin galibiyeti (rakip galip oranı)
}
MIN_BOOT = 1000


# ----------------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------------

def _logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p) - np.log1p(-p)


def _log_loss(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return -(y * np.log(p) + (1 - y) * np.log1p(-p))


def _days(fr: ResearchFrame) -> np.ndarray:
    """Maç günü (1970'ten gün sayısı, yerel tarih)."""
    return pd.to_datetime(fr.tm["date"]).to_numpy().astype("datetime64[D]").astype(np.int64)


def _period_start_day(period: str) -> int:
    return int(np.datetime64(f"{C.PERIODS[period][0]}-07-01", "D").astype(np.int64))


def _in_periods(fr: ResearchFrame, names: Sequence[str]) -> np.ndarray:
    out = np.zeros(len(fr.period), dtype=bool)
    for name in names:
        out |= fr.period == name
    return out


def rows_sha256(fr: ResearchFrame, mask: np.ndarray) -> str:
    """Satır kimliği özeti: maskedeki ``row_id``'lerin artan sırada little-endian int64 baytlarının SHA-256'sı."""
    ids = np.sort(fr.tm["row_id"].to_numpy()[np.asarray(mask, dtype=bool)]).astype("<i8")
    return hashlib.sha256(ids.tobytes()).hexdigest()


def train_mask(fr: ResearchFrame, target: str, train_periods: Sequence[str], eval_period: str) -> np.ndarray:
    """Arındırılmış uyum satırları: uygun, dönemde, hedef ve S0 biliniyor, ``label_known_at`` (maç günü + 1) <
    değerlendirme döneminin ilk günü (1 Temmuz 00:00)."""
    cut = _period_start_day(eval_period)
    return (fr.eligible & _in_periods(fr, train_periods) & np.isfinite(fr.y[target]) & np.isfinite(fr.p0[target])
            & (_days(fr) + 1 < cut))


def shared_rows(fr: ResearchFrame, target: str, period: str, need_market: bool = False) -> tuple[np.ndarray, str]:
    """Ortak değerlendirme satırları: uygun ∧ dönem ∧ hedef biliniyor ∧ S0 var (∧ marjsız 1X2 var) + SHA-256."""
    mask = (fr.eligible & (fr.period == period) & np.isfinite(fr.y[target]) & np.isfinite(fr.p0[target]))
    if need_market:
        mask &= np.isfinite(fr.mkt).all(axis=1)
    return mask, rows_sha256(fr, mask)


def _impute_scale(X: np.ndarray, ref: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Eksikleri ``ref`` satırlarının ortalamasıyla doldurur; ölçek (ortalama, std) ``ref`` satırlarından.

    ``ref``'te hiç gözlemi olmayan sütun 0 ile doldurulur; sabit sütunun std'si 1 alınır (katkısı sıfır kalır).
    """
    X = np.asarray(X, dtype=float)
    R = X[ref]
    fin = np.isfinite(R)
    cnt = fin.sum(axis=0)
    means = np.where(cnt > 0, np.where(fin, R, 0.0).sum(axis=0) / np.maximum(cnt, 1), 0.0)
    Xi = np.where(np.isfinite(X), X, means[None, :])
    stds = Xi[ref].std(axis=0) if ref.any() else np.ones(X.shape[1])
    stds = np.where(np.isfinite(stds) & (stds > 1e-12), stds, 1.0)
    return Xi, means, stds


def holm(pvals) -> np.ndarray:
    """Holm adım adım düzeltilmiş p değerleri (NaN'lar ailede sayılmaz ve NaN kalır; sabit aile boyu için
    ``holm_family``)."""
    p = np.asarray(pvals, dtype=float)
    out = np.full(p.shape, np.nan)
    ok = np.where(np.isfinite(p))[0]
    m = len(ok)
    if m == 0:
        return out
    order = ok[np.argsort(p[ok], kind="mergesort")]
    out[order] = np.minimum(1.0, np.maximum.accumulate((m - np.arange(m)) * p[order]))
    return out


def holm_family(pvals) -> np.ndarray:
    """Ön-kayıtlı aile boyu k korunarak Holm: değerlendirilemeyen (NaN) hipotez p = 1 sayılır (aile küçülmez);
    çıktıda yine NaN kalır."""
    p = np.asarray(pvals, dtype=float)
    adj = holm(np.where(np.isfinite(p), p, 1.0))
    return np.where(np.isfinite(p), adj, np.nan)


def _ratio_boot(num: np.ndarray, den: np.ndarray, clusters: np.ndarray, reps: int, seed: int) -> np.ndarray:
    """Kümeler yerine koymalı yeniden örneklenir; Σnum/Σden oranının bootstrap dağılımı."""
    if reps < MIN_BOOT:
        raise ValueError(f"Sözleşme gereği bootstrap tekrar sayısı en az {MIN_BOOT} olmalı")
    _, inv = np.unique(np.asarray(clusters).astype(str), return_inverse=True)
    s = np.bincount(inv, weights=num)
    c = np.bincount(inv, weights=den)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(s), size=(reps, len(s)))
    tot = c[draws].sum(axis=1)
    return np.where(tot > 0, s[draws].sum(axis=1) / np.where(tot > 0, tot, 1.0), np.nan)


def cluster_bootstrap_diff(loss_a, loss_b, clusters, reps: int = MIN_BOOT, seed: int = C.SEED) -> dict:
    """Ortalama kayıp farkı (a − b; negatif = a daha iyi) ve küme bootstrap'ı (varsayılan: lig-sezon kümeleri).

    Tek yönlü p (H1: fark < 0): bootstrap standart hatasıyla normal yaklaşım; ayrıca bootstrap oranı p.
    Aynı ``seed`` ve girdilerle sonuç birebir aynıdır.
    """
    a, b = np.asarray(loss_a, dtype=float), np.asarray(loss_b, dtype=float)
    diff = a - b
    if len(diff) == 0:
        return {"diff": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan"), "se": float("nan"),
                "p_one_sided": float("nan"), "p_boot": float("nan"), "reps": int(reps), "n_clusters": 0,
                "seed": int(seed)}
    boot = _ratio_boot(diff, np.ones_like(diff), clusters, reps, seed)
    d = float(diff.mean())
    se = float(np.std(boot, ddof=1))
    return {
        "diff": d, "ci_lo": float(np.quantile(boot, 0.025)), "ci_hi": float(np.quantile(boot, 0.975)), "se": se,
        "p_one_sided": float(norm.cdf(d / se)) if se > 0 else float("nan"),
        "p_boot": float((1 + (boot >= 0).sum()) / (reps + 1)), "reps": int(reps),
        "n_clusters": int(len(np.unique(np.asarray(clusters).astype(str)))), "seed": int(seed),
    }


def _iso_weeks(fr: ResearchFrame, mask: np.ndarray) -> np.ndarray:
    return pd.to_datetime(fr.tm["date"].to_numpy()[mask]).strftime("%G-%V").to_numpy()


# ----------------------------------------------------------------------------
# Offset destekli lojistik regresyon
# ----------------------------------------------------------------------------

@dataclass
class OffsetLogit:
    """logit p = offset + sabit + ((X − ortalama) / std) · β."""

    coef: np.ndarray
    intercept: float
    lam: float
    means: np.ndarray
    stds: np.ndarray
    n: int
    loss: float  # eğitim ortalama log-kaybı (ceza hariç)
    converged: bool
    n_iter: int
    names: list = field(default_factory=list)

    def linear(self, X: np.ndarray, offset: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float).reshape(len(offset), -1)
        z = np.asarray(offset, dtype=float) + self.intercept
        if len(self.coef):
            z = z + ((X - self.means) / self.stds) @ self.coef
        return z

    def predict(self, X: np.ndarray, offset: np.ndarray) -> np.ndarray:
        return expit(self.linear(X, offset))

    def summary(self) -> dict:
        names = self.names or [f"x{i}" for i in range(len(self.coef))]
        return {"lam": self.lam, "sabit": float(self.intercept), "n": int(self.n), "egitim_log_kayip": float(self.loss),
                "yakinsadi": bool(self.converged), "iterasyon": int(self.n_iter),
                "katsayilar_std": {k: float(v) for k, v in zip(names, self.coef)}}


def _objective(theta: np.ndarray, Z: np.ndarray, y: np.ndarray, offset: np.ndarray, lam: float,
               intercept: bool) -> tuple[float, np.ndarray]:
    """Ortalama log-kayıp + (λ/2)‖β‖² ve analitik gradyan; theta = [sabit, β] (``intercept``) veya [β]."""
    n = len(y)
    b0 = theta[0] if intercept else 0.0
    beta = theta[1:] if intercept else theta
    z = offset + b0
    if Z.shape[1]:
        z = z + Z @ beta
    f = float(np.mean(np.logaddexp(0.0, z) - y * z))
    r = (expit(z) - y) / n
    g_beta = Z.T @ r + lam * beta if Z.shape[1] else np.zeros(0)
    f += 0.5 * lam * float(beta @ beta) if Z.shape[1] else 0.0
    g = np.concatenate([[r.sum()], g_beta]) if intercept else g_beta
    return f, g


def fit_offset_logistic(X, y, offset, lam: float, intercept: bool = True, means=None, stds=None,
                        names: Sequence[str] | None = None, max_iter: int = 1000) -> OffsetLogit:
    """S0 offsetli lojistik regresyon (L-BFGS, analitik gradyan).

    ``lam``: gözlem başına ceza, ortalama log-kayıp üzerine (λ/2)·‖β‖²; sabit terim cezasız. ``lam = inf`` →
    β = 0 (yalnız offset + sabit). ``means``/``stds`` verilirse X içeride (X − means)/stds ile standartlaştırılır
    (çağıran tarafından belirlenen ölçek, ör. keşif dönemi); verilmezse X olduğu gibi kullanılır.
    """
    y = np.asarray(y, dtype=float)
    offset = np.asarray(offset, dtype=float)
    if len(y) == 0:
        raise ValueError("Uyum için satır yok")
    X = np.asarray(X, dtype=float).reshape(len(y), -1)
    p = X.shape[1]
    means = np.zeros(p) if means is None else np.asarray(means, dtype=float)
    stds = np.ones(p) if stds is None else np.asarray(stds, dtype=float)
    if not (np.isfinite(y).all() and np.isfinite(offset).all() and np.isfinite(X).all()):
        raise ValueError("Uyum girdilerinde NaN/sonsuz değer var")
    if lam < 0:
        raise ValueError("λ negatif olamaz")
    free = math.isfinite(lam)
    Z = (X - means) / stds if free else np.zeros((len(y), 0))
    lam_eff = float(lam) if free else 0.0
    k = (1 if intercept else 0) + Z.shape[1]
    if k == 0:
        loss = float(np.mean(_log_loss(y, expit(offset))))
        return OffsetLogit(np.zeros(p), 0.0, float(lam), means, stds, len(y), loss, True, 0, list(names or []))
    res = minimize(_objective, np.zeros(k), args=(Z, y, offset, lam_eff, intercept), jac=True, method="L-BFGS-B",
                   options={"maxiter": max_iter, "gtol": 1e-9, "ftol": 1e-14})
    theta = res.x
    b0 = float(theta[0]) if intercept else 0.0
    beta = (theta[1:] if intercept else theta) if free else np.zeros(p)
    fit = OffsetLogit(np.asarray(beta, dtype=float), b0, float(lam), means, stds, len(y), 0.0, bool(res.success),
                      int(res.nit), list(names or []))
    fit.loss = float(np.mean(_log_loss(y, fit.predict(X, offset))))
    return fit


# ----------------------------------------------------------------------------
# S1
# ----------------------------------------------------------------------------

@dataclass
class S1Result:
    target: str
    lam: float
    selection: list
    fit_kesif: OffsetLogit  # keşifte uyum (seçilen λ) → parametre dönemi tahminleri
    fit_final: OffsetLogit  # keşif + parametre yeniden uyum, DONDURULMUŞ → test tahminleri
    pred: np.ndarray  # tm'ye hizalı; parametre ve test dönemi satırları, diğerleri NaN
    info: dict = field(default_factory=dict)


def s1_design(fr: ResearchFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """S1 tasarım matrisi (eksikler keşif ortalamasıyla dolu), keşif ölçeği (ortalama, std) ve sütun adları."""
    if fr.s1 is None:
        raise ValueError("Çerçevede S1 özellikleri yok (build_frame(with_s1=True) gerekli)")
    names = list(S1_FEATURES)
    X = fr.s1[names].to_numpy(dtype=float)
    Xi, means, stds = _impute_scale(X, fr.eligible & (fr.period == "kesif"))
    return Xi, means, stds, names


def _mask_of(n: int, rows: np.ndarray) -> np.ndarray:
    m = np.zeros(n, dtype=bool)
    m[rows] = True
    return m


def _last_date(fr: ResearchFrame, mask: np.ndarray) -> str | None:
    return str(pd.Timestamp(fr.tm["date"].to_numpy()[mask].max()).date()) if mask.any() else None


def fit_s1(fr: ResearchFrame, target: str, lambdas: Sequence[float] = C.S1_LAMBDAS,
           design: tuple | None = None) -> S1Result:
    """S1 protokolü: keşifte uyum, parametre döneminde λ seçimi (ortalama log-kayıp), keşif + parametre (arındırılmış)
    yeniden uyum, test için dondurma. Eşitlikte daha büyük λ (daha sade model) seçilir."""
    Xi, means, stds, names = design or s1_design(fr)
    off = _logit(fr.p0[target])
    y = fr.y[target]
    tr1 = train_mask(fr, target, ("kesif",), "parametre")
    ev1, _ = shared_rows(fr, target, "parametre")
    if not tr1.any() or not ev1.any():
        raise ValueError(f"{target}: keşif uyumu veya parametre seçimi için satır yok")
    selection, fits = [], {}
    best_i, best_ll = None, math.inf
    for i, lam in enumerate(lambdas):
        f = fit_offset_logistic(Xi[tr1], y[tr1], off[tr1], lam, means=means, stds=stds, names=names)
        ll = float(np.mean(_log_loss(y[ev1], f.predict(Xi[ev1], off[ev1]))))
        fits[i] = f
        selection.append({"lam": float(lam), "ll_parametre": ll, "n_egitim": int(tr1.sum()),
                          "n_parametre": int(ev1.sum()),
                          "yakinsadi": f.converged})
        if best_i is None or ll < best_ll - 1e-12 or (abs(ll - best_ll) <= 1e-12 and lam > lambdas[best_i]):
            best_i, best_ll = i, min(ll, best_ll)
    lam_sel = float(lambdas[best_i])
    tr2 = train_mask(fr, target, ("kesif", "parametre"), "test")
    final = fit_offset_logistic(Xi[tr2], y[tr2], off[tr2], lam_sel, means=means, stds=stds, names=names)
    pred = np.full(len(y), np.nan)
    pm = (fr.period == "parametre") & np.isfinite(fr.p0[target])
    tmask = (fr.period == "test") & np.isfinite(fr.p0[target])
    pred[pm] = fits[best_i].predict(Xi[pm], off[pm])
    pred[tmask] = final.predict(Xi[tmask], off[tmask])
    info = {"olcek": "keşif", "eksik_doldurma": "keşif ortalaması", "ozellikler": names,
            "egitim_kesif": {"n": int(tr1.sum()), "son_tarih": _last_date(fr, tr1)},
            "egitim_final": {"n": int(tr2.sum()), "son_tarih": _last_date(fr, tr2)},
            "test_icinde_yeniden_uyum": False, "ceza": "ortalama log-kayıp + (λ/2)·‖β‖², sabit cezasız"}
    return S1Result(target, lam_sel, selection, fits[best_i], final, pred, info)


# ----------------------------------------------------------------------------
# S2 (kNN)
# ----------------------------------------------------------------------------

def s2_space(fr: ResearchFrame) -> tuple[np.ndarray, list[str]]:
    """S2 uzayı: S1 özellikleri + takım/rakip S0 gücü; eksikler keşif ortalaması; keşif ölçeğiyle standart."""
    if fr.s1 is None:
        raise ValueError("Çerçevede S1 özellikleri yok (build_frame(with_s1=True) gerekli)")
    names = list(S1_FEATURES) + list(S2_EXTRA)
    X = np.column_stack([fr.s1[list(S1_FEATURES)].to_numpy(dtype=float), fr.p_win, fr.opp_strength])
    Xi, means, stds = _impute_scale(X, fr.eligible & (fr.period == "kesif"))
    return (Xi - means) / stds, names


@dataclass
class _NNMeta:
    day: np.ndarray
    pair: np.ndarray
    ts: np.ndarray  # takım-sezon kimliği
    team: np.ndarray


def _nn_meta(fr: ResearchFrame) -> _NNMeta:
    tm = fr.tm
    ts, _ = pd.factorize(tm["team"].astype(str) + "|" + tm["season"].astype(str))
    team, _ = pd.factorize(tm["team"].astype(str))
    return _NNMeta(_days(fr), tm["pair_id"].to_numpy().astype(np.int64), ts.astype(np.int64), team.astype(np.int64))


def _pick(ind: np.ndarray, q_day: np.ndarray, q_pair: np.ndarray, lday: np.ndarray, lpair: np.ndarray,
          lts: np.ndarray, lok: np.ndarray | None, k_max: int) -> tuple[np.ndarray, np.ndarray]:
    """Mesafe sırasındaki kütüphane konumlarından (``ind``) izinli olanları süzer ve farklı takım-sezonların ilk
    k_max'ını seçer (her takım-sezonun ilk = en yakın satırı).

    İzinli: maç günü + 1 < sorgu günü (label_known_at < decision_time), farklı pair_id, farklı gün ve ``lok``
    (kütüphane satırında hedef biliniyor). Dönen: (c, k_max) kütüphane konumları (yoksa −1) ve komşu sayısı.
    """
    c, f = ind.shape
    valid = (lday[ind] + 1 < q_day[:, None]) & (lpair[ind] != q_pair[:, None]) & (lday[ind] != q_day[:, None])
    if lok is not None:
        valid &= lok[ind]
    col = np.arange(f, dtype=np.int64)
    big = (np.int64(lts.max()) + 2) * f
    key = np.where(valid, lts[ind] * f + col[None, :], big)
    key.sort(axis=1)
    grp = key // f
    first = np.ones_like(valid)
    first[:, 1:] = grp[:, 1:] != grp[:, :-1]
    first &= key < big
    fpos = np.where(first, key - grp * f, f)
    fpos.sort(axis=1)
    fpos = fpos[:, :k_max]
    ok = fpos < f
    out = np.full((c, k_max), -1, dtype=np.int64)
    r, j = np.nonzero(ok)
    out[r, j] = ind[r, fpos[r, j]]
    return out, ok.sum(axis=1)


def _iter_neighbors(Z: np.ndarray, meta: _NNMeta, lib_rows: np.ndarray, q_rows: np.ndarray, k_max: int,
                    lib_ok: Sequence[np.ndarray | None] = (None,), chunk_cells: int = 2_000_000,
                    fetch_factor: int = 4) -> Iterator[tuple[np.ndarray, list, list]]:
    """Sorgu parçaları için (sorgu tm satırları, [komşu tm satırları (c, k_max; −1 = yok)], [komşu sayıları]).

    ``lib_ok``: grup başına kütüphane satırı geçerliliği (hedefin bilindiği satırlar; None = hepsi). Tek komşu
    araması bütün gruplarca paylaşılır; geçersiz satırların atlanması, o grubun kendi kütüphanesinde arama yapmakla
    birebir aynı sonucu verir. Önce ``fetch_factor``·k_max en yakın satır getirilir; herhangi bir grupta izinli farklı
    takım-sezon sayısı k_max'a ulaşmayan sorgularda getirilen sayı 4 kat büyütülür (en fazla tüm kütüphane) → kütüphane
    örneklenmez, sonuç tam aramayla aynıdır. Bellek: sorgu parçası × getirilen ≤ ``chunk_cells``.
    """
    from sklearn.metrics import pairwise_distances
    from sklearn.neighbors import NearestNeighbors

    n_lib, ng = len(lib_rows), len(lib_ok)
    if len(q_rows) == 0:
        return
    if n_lib == 0:
        for s in range(0, len(q_rows), 10_000):
            q = q_rows[s:s + 10_000]
            yield (q, [np.full((len(q), k_max), -1, dtype=np.int64) for _ in range(ng)],
                   [np.zeros(len(q), dtype=np.int64) for _ in range(ng)])
        return
    Zlib = Z[lib_rows]
    nn = NearestNeighbors(algorithm="brute", metric="euclidean").fit(Zlib)
    lday, lpair, lts = meta.day[lib_rows], meta.pair[lib_rows], meta.ts[lib_rows]
    f0 = int(min(n_lib, max(fetch_factor * k_max, k_max)))
    if len(np.unique(lts)) <= k_max:  # takım-sezon sayısı k_max'ı aşmıyorsa her sorgu tüm kütüphaneyi gerektirir
        f0 = n_lib
    step = max(1, chunk_cells // f0)

    def pick(qq, f):
        if f >= n_lib:  # tüm kütüphane gerekiyorsa tam mesafe matrisi + kararlı sıralama (yığın sıralamasından hızlı)
            ind = np.argsort(pairwise_distances(Z[qq], Zlib), axis=1, kind="stable")
        else:
            ind = nn.kneighbors(Z[qq], n_neighbors=f, return_distance=False)
        res = [_pick(ind, meta.day[qq], meta.pair[qq], lday, lpair, lts, ok, k_max) for ok in lib_ok]
        return [r[0] for r in res], [r[1] for r in res]

    for s in range(0, len(q_rows), step):
        q = q_rows[s:s + step]
        pos, cnt = pick(q, f0)
        f = f0
        short = np.zeros(len(q), dtype=bool)
        for cg in cnt:
            short |= cg < k_max
        need = np.where(short & (f < n_lib))[0]
        while len(need):
            f = int(min(n_lib, f * 4))
            sub = max(1, chunk_cells // f)
            for a in range(0, len(need), sub):
                idx = need[a:a + sub]
                p2, c2 = pick(q[idx], f)
                for g in range(ng):
                    pos[g][idx], cnt[g][idx] = p2[g], c2[g]
            short = np.zeros(len(need), dtype=bool)
            for cg in cnt:
                short |= cg[need] < k_max
            need = need[short & (f < n_lib)]
        yield q, [np.where(pg >= 0, lib_rows[np.maximum(pg, 0)], -1) for pg in pos], cnt


def knn_neighbors(fr: ResearchFrame, lib_mask: np.ndarray, query_mask: np.ndarray, k: int,
                  space: np.ndarray | None = None, **kw) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sorgu satırları için S2 komşuları: (sorgu tm satırları, komşu tm satırları (n_q, k; −1 = yok), sayılar).

    Kurallar: kütüphane satırının maç günü + 1 < sorgu günü (label_known_at < decision_time), aynı pair_id ve aynı
    gün dışlanır, takım-sezon başına en fazla 1 (mesafe sırasında ilk = en yakın satır).
    """
    Z = s2_space(fr)[0] if space is None else space
    meta = _nn_meta(fr)
    q_rows = np.where(query_mask)[0]
    parts = list(_iter_neighbors(Z, meta, np.where(lib_mask)[0], q_rows, int(k), **kw))
    if not parts:
        return q_rows, np.zeros((0, int(k)), dtype=np.int64), np.zeros(0, dtype=np.int64)
    return q_rows, np.vstack([p[1][0] for p in parts]), np.concatenate([p[2][0] for p in parts])


def _distinct_per_row(ids: np.ndarray) -> np.ndarray:
    """Satır başına farklı (≥ 0) değer sayısı."""
    if ids.shape[1] == 0:
        return np.zeros(len(ids), dtype=np.int64)
    s = np.sort(ids, axis=1)
    new = np.ones_like(s, dtype=bool)
    new[:, 1:] = s[:, 1:] != s[:, :-1]
    return (new & (s >= 0)).sum(axis=1)


def _s2_aggregate(fr: ResearchFrame, Z: np.ndarray, meta: _NNMeta, groups: Sequence[Sequence[str]],
                  lib_rows: np.ndarray, lib_ok: Sequence[np.ndarray], q_rows: np.ndarray, ks: Sequence[int],
                  **kw) -> list[dict]:
    """Grup başına, her k için O (gözlenen), E (S0 beklenen), n (takım-sezon), farklı takım ve maç sayıları."""
    nq, nk = len(q_rows), len(ks)
    k_max = int(max(ks))
    outs = [{"n": np.zeros((nq, nk)), "team": np.zeros((nq, nk)), "match": np.zeros((nq, nk)),
             "O": {t: np.zeros((nq, nk)) for t in grp}, "E": {t: np.zeros((nq, nk)) for t in grp}} for grp in groups]
    start = 0
    for q, nbs, cnts in _iter_neighbors(Z, meta, lib_rows, q_rows, k_max, lib_ok=lib_ok, **kw):
        sl = slice(start, start + len(q))
        start += len(q)
        for grp, out, nb, cnt in zip(groups, outs, nbs, cnts):
            okm = nb >= 0
            safe = np.maximum(nb, 0)
            for i, k in enumerate(ks):
                kk = int(min(k, k_max))
                out["n"][sl, i] = np.minimum(cnt, kk)
                out["team"][sl, i] = _distinct_per_row(np.where(okm[:, :kk], meta.team[safe[:, :kk]], -1))
                out["match"][sl, i] = _distinct_per_row(np.where(okm[:, :kk], meta.pair[safe[:, :kk]], -1))
            for t in grp:
                cy = np.cumsum(np.where(okm, fr.y[t][safe], 0.0), axis=1)
                cp = np.cumsum(np.where(okm, fr.p0[t][safe], 0.0), axis=1)
                for i, k in enumerate(ks):
                    kk = int(min(k, k_max)) - 1
                    out["O"][t][sl, i] = cy[:, kk]
                    out["E"][t][sl, i] = cp[:, kk]
    return outs


def s2_logit_adj(O, E, n, kappa: float) -> np.ndarray:
    """S2 logit düzeltmesi: logit((O + κ·p̄)/(n + κ)) − logit((E + κ·p̄)/(n + κ)), p̄ = E/n; n = 0 → 0."""
    O, E, n = (np.asarray(v, dtype=float) for v in (O, E, n))
    has = n > 0
    nn_ = np.where(has, n, 1.0)
    pbar = np.where(has, E / nn_, 0.5)
    adj = _logit((O + kappa * pbar) / (nn_ + kappa)) - _logit((E + kappa * pbar) / (nn_ + kappa))
    return np.where(has, adj, 0.0)


def s2_adjust(p0, O, E, n, kappa: float) -> np.ndarray:
    """logit p = logit p0 + [logit((O + κ·p̄)/(n + κ)) − logit((E + κ·p̄)/(n + κ))], p̄ = E/n; n = 0 → p0."""
    return expit(_logit(p0) + s2_logit_adj(O, E, n, kappa))


@dataclass
class S2Result:
    target: str
    k: int
    kappa: float
    selection: list
    pred: np.ndarray  # tm'ye hizalı; parametre (keşif kütüphanesi) ve test (keşif + parametre kütüphanesi)
    eff: dict  # dönem → etkili örnek özeti (seçilen k)
    eff_rows: dict  # "takim_sezon"/"takim"/"mac": tm'ye hizalı satır başına sayılar (seçilen k)
    info: dict = field(default_factory=dict)
    adj: np.ndarray | None = None  # tm'ye hizalı seçilen (k, κ) logit düzeltmesi (7b/5: S0p üzerine eklenir)


def _eff_summary(n: np.ndarray, team: np.ndarray, match: np.ndarray, lib: dict) -> dict:
    if len(n) == 0:
        return {"sorgu": 0, **lib}
    return {"sorgu": int(len(n)), "takim_sezon_ort": float(n.mean()), "takim_sezon_medyan": float(np.median(n)),
            "takim_sezon_min": int(n.min()), "takim_ort": float(team.mean()), "takim_min": int(team.min()),
            "mac_ort": float(match.mean()), "mac_min": int(match.min()), **lib}


def _lib_stats(fr: ResearchFrame, meta: _NNMeta, lib_rows: np.ndarray) -> dict:
    return {"kutuphane_satir": int(len(lib_rows)), "kutuphane_takim_sezon": int(len(np.unique(meta.ts[lib_rows]))),
            "kutuphane_takim": int(len(np.unique(meta.team[lib_rows]))),
            "kutuphane_son_tarih": _last_date(fr, _mask_of(len(fr.tm), lib_rows))}


def fit_s2(fr: ResearchFrame, targets: str | Sequence[str] = C.TARGETS_Q1, ks: Sequence[int] = C.S2_K,
           kappas: Sequence[float] = C.S2_KAPPA, **kw) -> dict[str, S2Result]:
    """S2 protokolü: parametre döneminde (keşif kütüphanesi) (k, κ) seçimi (ortalama log-kayıp); test için keşif +
    parametre kütüphanesi (arındırılmış) ve seçilen (k, κ) DONDURULUR. Hedefin bilindiği satırları aynı olan hedefler
    bir grup oluşturur; her dönemde tek komşu araması bütün gruplarca paylaşılır (sonuç grup başına tam aramayla
    aynı)."""
    targets = [targets] if isinstance(targets, str) else list(targets)
    Z, names = s2_space(fr)
    meta = _nn_meta(fr)
    day = meta.day
    known = {t: np.isfinite(fr.y[t]) & np.isfinite(fr.p0[t]) for t in targets}
    gkeys: dict[bytes, list[str]] = {}
    for t in targets:
        gkeys.setdefault(np.packbits(known[t]).tobytes(), []).append(t)
    groups = list(gkeys.values())
    any_known = np.zeros(len(fr.tm), dtype=bool)
    for t in targets:
        any_known |= known[t]
    stages = {}
    for period, lib_periods in EVAL_PLAN:
        lib_rows = np.where(fr.eligible & _in_periods(fr, lib_periods) & (day + 1 < _period_start_day(period))
                            & any_known)[0]
        q_rows = np.where(fr.eligible & (fr.period == period) & np.isfinite(fr.p_win))[0]
        lib_ok = [known[g[0]][lib_rows] for g in groups]
        agg = _s2_aggregate(fr, Z, meta, groups, lib_rows, lib_ok, q_rows, ks, **kw)
        stages[period] = (lib_rows, lib_ok, q_rows, agg)
    results: dict[str, S2Result] = {}
    for gi, grp in enumerate(groups):
        for t in grp:
            _, _, q_rows, aggs = stages["parametre"]
            agg = aggs[gi]
            ev = np.isfinite(fr.y[t][q_rows]) & np.isfinite(fr.p0[t][q_rows])
            if not ev.any():
                raise ValueError(f"{t}: parametre döneminde S2 seçimi için satır yok")
            selection, best = [], None
            for i, k in enumerate(ks):
                for kappa in kappas:
                    p = s2_adjust(fr.p0[t][q_rows][ev], agg["O"][t][ev, i], agg["E"][t][ev, i], agg["n"][ev, i], kappa)
                    ll = float(np.mean(_log_loss(fr.y[t][q_rows][ev], p)))
                    selection.append({"k": int(k), "kappa": float(kappa), "ll_parametre": ll,
                                      "n_parametre": int(ev.sum())})
                    if best is None or ll < best[0] - 1e-12:
                        best = (ll, i, int(k), float(kappa))
            _, bi, k_sel, kappa_sel = best
            n_tm = len(fr.tm)
            pred = np.full(n_tm, np.nan)
            adj = np.full(n_tm, np.nan)
            eff, eff_rows = {}, {"takim_sezon": np.full(n_tm, np.nan), "takim": np.full(n_tm, np.nan),
                                 "mac": np.full(n_tm, np.nan)}
            for period, _ in EVAL_PLAN:
                lib_rows, lib_ok, q_rows, aggs = stages[period]
                agg = aggs[gi]
                qk = np.isfinite(fr.p0[t][q_rows])
                qr = q_rows[qk]
                adj[qr] = s2_logit_adj(agg["O"][t][qk, bi], agg["E"][t][qk, bi], agg["n"][qk, bi], kappa_sel)
                pred[qr] = expit(_logit(fr.p0[t][qr]) + adj[qr])
                eff_rows["takim_sezon"][q_rows] = agg["n"][:, bi]
                eff_rows["takim"][q_rows] = agg["team"][:, bi]
                eff_rows["mac"][q_rows] = agg["match"][:, bi]
                eff[period] = _eff_summary(agg["n"][:, bi], agg["team"][:, bi], agg["match"][:, bi],
                                           _lib_stats(fr, meta, lib_rows[lib_ok[gi]]))
            info = {"uzay": names, "olcek": "keşif", "uzaklik": "Öklid", "takim_sezon_siniri": 1,
                    "kutuphane": {"parametre": "keşif", "test": "keşif + parametre (arındırılmış)"},
                    "kutuphane_ornekleme": "yok (tüm kütüphane)", "test_icinde_yeniden_uyum": False,
                    "hedef_grubu": list(grp),
                    "not": "Ham benzerlik yüzdesi olasılık değildir; S2 yalnızca S0'a göre O/E düzeltmesidir."}
            results[t] = S2Result(t, k_sel, kappa_sel, selection, pred, eff, eff_rows, info, adj)
    return results


# ----------------------------------------------------------------------------
# S0p (piyasa kontrolü)
# ----------------------------------------------------------------------------

S0P_NAMES = ["logit_s0_sicaklik", "logit_piyasa_galip", "logit_piyasa_maglup"]


def _market_design(fr: ResearchFrame, target: str) -> np.ndarray:
    """S0p ortak değişkenleri: [logit p0 (sıcaklık terimi), logit piyasa galip, logit piyasa mağlup]."""
    return np.column_stack([_logit(fr.p0[target]), _logit(fr.mkt[:, 0]), _logit(fr.mkt[:, 2])])


def s0p_temperature(fit: OffsetLogit) -> float:
    """S0p uyumundaki S0 sıcaklığı τ (logit p0 katsayısı = 1 + β_sıcaklık / std)."""
    return float(1.0 + fit.coef[0] / fit.stds[0])


def p0_market(fr: ResearchFrame, target: str, fit_mask: np.ndarray, apply_mask: np.ndarray,
              return_fit: bool = False):
    """S0p (piyasa kontrolü): logit p = τ·logit p0 + sabit + β₁·logit(piyasa galip) + β₂·logit(piyasa mağlup)
    (takım perspektifi, marjsız Bet365; zamanı doğrulanamaz). Sözleşme §6'daki "sıcaklık": S0 logiti offset olarak
    girer ve ayrıca ortak değişkendir (katsayı τ − 1), böylece piyasa S0'ı gerektiği kadar AZALTABİLİR; τ sabit 1
    olsaydı S0'ın piyasanın bilmediği gürültüsü kontrolde kalır ve piyasa bilgisi taşıyan özellikler (ör. geçmiş
    piyasa sürprizi) "ek katkı" gibi görünürdü. ``fit_mask`` satırlarında (hedef, S0 ve oran olanlar) cezasız uyum;
    ``apply_mask`` satırlarında tahmin, oran yoksa NaN. Zaman güvenliği (arındırma) çağıranın sorumluluğundadır."""
    has = np.isfinite(fr.mkt).all(axis=1) & np.isfinite(fr.p0[target])
    y = fr.y[target]
    fit_rows = np.asarray(fit_mask, dtype=bool) & has & np.isfinite(y)
    if not fit_rows.any() or np.unique(y[fit_rows]).size < 2:
        raise ValueError(f"{target}: S0p uyumu için oranlı ve iki sınıflı satır yok")
    X = np.where(has[:, None], _market_design(fr, target), 0.0)
    off = _logit(fr.p0[target])
    mu = X[fit_rows].mean(axis=0)
    sd = X[fit_rows].std(axis=0)
    sd = np.where(sd > 1e-12, sd, 1.0)
    fit = fit_offset_logistic(X[fit_rows], y[fit_rows], off[fit_rows], 0.0, means=mu, stds=sd, names=S0P_NAMES)
    out = np.full(len(y), np.nan)
    ap = np.asarray(apply_mask, dtype=bool) & has
    out[ap] = fit.predict(X[ap], off[ap])
    return (out, fit) if return_fit else out


def s0p_predict(fr: ResearchFrame, target: str) -> tuple[np.ndarray, dict]:
    """Dönem planıyla S0p: parametre satırları keşif uyumuyla, test satırları keşif + parametre uyumuyla
    (dondurulmuş)."""
    out = np.full(len(fr.tm), np.nan)
    info = {}
    for period, train_periods in EVAL_PLAN:
        tr = train_mask(fr, target, train_periods, period)
        try:
            p, fit = p0_market(fr, target, tr, fr.period == period, return_fit=True)
        except ValueError as exc:
            info[period] = {"durum": "UYUM_YOK", "neden": str(exc)}
            continue
        sel = fr.period == period
        out[sel] = p[sel]
        info[period] = {"durum": "OK", "uyum": fit.summary(), "s0_sicaklik": s0p_temperature(fit),
                        "egitim_son_tarih": _last_date(fr, tr & np.isfinite(fr.mkt).all(axis=1))}
    return out, info


def s1_market_predict(fr: ResearchFrame, target: str, s1: S1Result, design: tuple | None = None
                      ) -> tuple[np.ndarray, dict]:
    """7b/5 piyasa kontrolü için S1 özellikleri S0p OFFSETİYLE: logit p = logit S0p + sabit + β·x.

    Aynı dönem planı ve arındırma (``train_mask``): S0p, ``s0p_predict`` ile aynı eğitim satırlarında uyumlanır
    (değerlendirme satırlarında ``s0p_predict`` ile aynı değerler); S1 özellikleri o satırların oranlı olanlarında,
    S1'in seçilmiş λ'sıyla (yeniden seçim yok) uyumlanır ve değerlendirme dönemine DONDURULMUŞ uygulanır.
    Karşılaştırma S0p iledir: katkı piyasa kontrolünde sürmeli.
    """
    Xi, means, stds, names = design or s1_design(fr)
    y = fr.y[target]
    out = np.full(len(y), np.nan)
    info = {}
    for period, train_periods in EVAL_PLAN:
        tr = train_mask(fr, target, train_periods, period)
        sel = fr.period == period
        try:
            p_mkt = p0_market(fr, target, tr, tr | sel)
        except ValueError as exc:
            info[period] = {"durum": "UYUM_YOK", "neden": str(exc)}
            continue
        trm = tr & np.isfinite(p_mkt)
        off = _logit(p_mkt)
        fit = fit_offset_logistic(Xi[trm], y[trm], off[trm], s1.lam, means=means, stds=stds, names=names)
        ap = sel & np.isfinite(p_mkt)
        out[ap] = fit.predict(Xi[ap], off[ap])
        info[period] = {"durum": "OK", "lam": float(s1.lam), "n_egitim": int(trm.sum()),
                        "egitim_son_tarih": _last_date(fr, trm), "yakinsadi": fit.converged}
    return out, info


# ----------------------------------------------------------------------------
# Ortak değerlendirme (F3)
# ----------------------------------------------------------------------------

def _metrics(y: np.ndarray, p: np.ndarray) -> dict:
    if len(y) == 0:
        return {"n": 0}
    ll = _log_loss(y, p)
    slope, icpt = calibration_slope(y, p)
    bins = calibration_bins(y, p)
    ece = float(np.sum([b["n"] * abs(b["tahmin"] - b["gercek"]) for b in bins]) / len(y))
    return {"n": int(len(y)), "taban_oran": float(y.mean()), "ort_tahmin": float(p.mean()),
            "log_kayip": float(ll.mean()),
            "brier": float(np.mean((p - y) ** 2)), "kal_egim": slope, "kal_kesisim": icpt, "ece": ece}


@dataclass
class FittedModels:
    """Hedef başına S1, S2 ve S0p tahminleri (tm'ye hizalı) — aynı uyumlar F3, F6 ve arayüzde yeniden kullanılır."""

    s1: dict
    s2: dict
    s0p: dict
    s0p_info: dict
    s1_mkt: dict = field(default_factory=dict)  # 7b/5: S1 özellikleri S0p offsetiyle (s1_market_predict)
    s1_mkt_info: dict = field(default_factory=dict)


def fit_models(fr: ResearchFrame, targets: Sequence[str] = C.TARGETS_Q1, **s2_kw) -> FittedModels:
    design = s1_design(fr)
    s1 = {t: fit_s1(fr, t, design=design) for t in targets}
    s2 = fit_s2(fr, targets, **s2_kw)
    s0p, s0p_info, s1m, s1m_info = {}, {}, {}, {}
    for t in targets:
        s0p[t], s0p_info[t] = s0p_predict(fr, t)
        s1m[t], s1m_info[t] = s1_market_predict(fr, t, s1[t], design=design)
    return FittedModels(s1, s2, s0p, s0p_info, s1m, s1m_info)


def market_controlled_predictions(fr: ResearchFrame, target: str, models: FittedModels) -> dict[str, np.ndarray]:
    """7b/5 piyasa kontrolü tahminleri: S1 → S0p offsetli S1 uyumu; S2 → aynı S2 logit düzeltmesi S0p üzerine.

    S2 düzeltmesi S0'a göre komşu O/E'sinden gelir; S0p'nin zaten bildiği bilgiyi taşıyorsa S0p üzerine eklenmesi
    log-kaybı kötüleştirir (tutucu kontrol). Hesaplanamayan model için anahtar yoktur (kontrol değerlendirilmez).
    """
    out = {}
    if target not in models.s1_mkt and target in models.s1:
        models.s1_mkt[target], models.s1_mkt_info[target] = s1_market_predict(fr, target, models.s1[target])
    if target in models.s1_mkt:
        out["S1"] = models.s1_mkt[target]
    s2 = models.s2.get(target)
    if s2 is not None and s2.adj is not None:
        out["S2"] = expit(_logit(models.s0p[target]) + s2.adj)
    return out


def model_predictions(fr: ResearchFrame, target: str, models: FittedModels) -> dict[str, np.ndarray]:
    return {"S0": fr.p0[target], "S0p": models.s0p[target], "S1": models.s1[target].pred, "S2": models.s2[target].pred}


FALS_TOP_SHARE = 0.01  # 7b/2: farka en çok katkı veren satır payı (sözleşme: %1)
FALS_SEASON_SHARE = 0.6  # 7b/3: aynı yönde olması gereken sezon payı (sözleşme: %60)
FALS_N_COUNTER = 20  # 7b/6: listelenen en büyük karşı örnek sayısı (sözleşme: 20)


def _falsification(fr: ResearchFrame, mask: np.ndarray, diff: np.ndarray, y: np.ndarray, reps: int,
                   seed: int) -> dict:
    """Sözleşme 7b'nin F3 modellerine uyarlanmış hâli (fark = model − S0 satır log-kaybı; ön-kayıtlı yön < 0).

    1 bir lig veya bir takım çıkarıldığında ortalama fark < 0 kalmalı; 2 farka en çok katkı veren %1 satır (en negatif
    fark) çıkarıldığında fark < 0 ve lig-sezon kümeli bootstrap üst sınırı < 0; 3 sezonların ≥ %60'ında fark < 0;
    4 eşleştirilmiş ampirik karşılaştırma bu modellerde uygulanamaz (koşul/tümleyen yok); 5 piyasa kontrolü
    ``_market_check``'te; 6 en büyük 20 karşı örnek (modelin S0'a göre en kötü olduğu satırlar; yalnızca satır
    kimliği, tarih, sonuç ve fark — takım/kulüp adı yazılmaz). Gruplar raporda adla değil sayıyla özetlenir.
    """
    tm = fr.tm
    n = len(diff)
    tot = float(diff.sum())
    out: dict = {}
    loo, ok1 = {}, True
    for col, lab in (("league", "lig"), ("team", "takim")):
        _, inv = np.unique(tm[col].to_numpy()[mask].astype(str), return_inverse=True)
        s = np.bincount(inv, weights=diff)
        rest = n - np.bincount(inv).astype(float)
        m = (tot - s[rest > 0]) / rest[rest > 0]
        loo[lab] = {"n_grup": int(len(s)), "en_buyuk_fark": float(m.max()) if len(m) else float("nan"),
                    "yon_degisen": int((m >= 0).sum())}
        ok1 = ok1 and len(m) > 0 and bool((m < 0).all())
    out["1_lig_takim_cikarma"] = {"gecti": bool(ok1), **loo}
    k = int(np.ceil(FALS_TOP_SHARE * n))
    keep = np.ones(n, dtype=bool)
    keep[np.argsort(diff, kind="mergesort")[:k]] = False
    b = cluster_bootstrap_diff(diff[keep], np.zeros(int(keep.sum())), fr.cluster[mask][keep], reps, seed)
    out["2_en_cok_katki_yuzde1"] = {"gecti": bool(np.isfinite(b["diff"]) and b["diff"] < 0 and b["ci_hi"] < 0),
                                    "cikarilan": k, **b}
    seasons = tm["season"].to_numpy()[mask].astype(str)
    per_season = pd.Series(diff).groupby(seasons).mean()
    share = float((per_season < 0).mean()) if len(per_season) else float("nan")
    out["3_sezon_yonu"] = {"gecti": bool(len(per_season) > 0 and share >= FALS_SEASON_SHARE), "pay": share,
                           "esik": FALS_SEASON_SHARE}
    out["4_eslestirilmis_ampirik"] = {
        "gecti": None, "durum": "UYGULANAMAZ",
        "neden": "Modellerde koşul/tümleyen yoktur; karşılaştırma aynı satırlarda S0 iledir."}
    rows = np.where(mask)[0]
    top = np.argsort(-diff, kind="mergesort")[:FALS_N_COUNTER]
    dates = pd.to_datetime(tm["date"].to_numpy()[rows[top]])
    out["6_karsi_ornekler"] = [{"row_id": int(tm["row_id"].iat[rows[i]]), "tarih": str(d.date()), "y": int(y[i]),
                                "fark": float(diff[i])} for i, d in zip(top, dates)]
    return out


def _market_check(y: np.ndarray, p_ctrl: np.ndarray | None, p_s0p: np.ndarray, clusters: np.ndarray, reps: int,
                  seed: int) -> dict:
    """7b/5: piyasa kontrolünde (S0p offseti) katkı sürmeli — fark = log-kayıp(model | S0p) − log-kayıp(S0p) < 0 ve
    lig-sezon kümeli bootstrap üst sınırı < 0. Hesaplanamazsa geçmedi sayılır."""
    if p_ctrl is None:
        return {"gecti": False, "durum": "DEGERLENDIRILMEDI", "neden": "Piyasa kontrollü tahmin yok."}
    if not (np.isfinite(p_ctrl).all() and np.isfinite(p_s0p).all()):
        return {"gecti": False, "durum": "VERI_YOK",
                "neden": "Ortak satırların bir kısmında piyasa kontrollü tahmin yok.",
                "n_eksik": int((~np.isfinite(p_ctrl)).sum())}
    lc, l0 = _log_loss(y, p_ctrl), _log_loss(y, p_s0p)
    b = cluster_bootstrap_diff(lc, l0, clusters, reps, seed)
    return {"gecti": bool(b["diff"] < 0 and b["ci_hi"] < 0), "durum": "OK", "n": int(len(y)),
            "ll_model_piyasa": float(lc.mean()), "ll_s0p": float(l0.mean()), **b}


def compare_models(fr: ResearchFrame, target: str, models: FittedModels | None = None, n_boot: int = MIN_BOOT,
                   seed: int = C.SEED) -> dict:
    """S0, S0p, S1, S2'yi her dönemde TEK ortak satır kümesinde karşılaştırır (sözleşme §6, §9).

    Ölçütler: n, taban oran, log-kayıp, Brier, kalibrasyon eğimi/kesişimi, ECE; S0'a göre ΔLL (model − S0; negatif =
    iyileşme), lig-sezon kümeli bootstrap aralığı ve tek yönlü p, ISO hafta blokları duyarlılığı, sezon kararlılığı.
    S1 ve S2 için ``s0_fark[model]["yanlislama"]``: 7b uyarlaması (``_falsification`` + ``_market_check``).
    Oransız satırlar (S0p tanımsız) ortak kümeden çıkar ve ``dislanan`` altında ayrıca raporlanır.
    """
    if n_boot < MIN_BOOT:
        raise ValueError(f"Sözleşme gereği bootstrap tekrar sayısı en az {MIN_BOOT} olmalı")
    models = models or fit_models(fr, [target])
    preds = model_predictions(fr, target, models)
    ctrl = market_controlled_predictions(fr, target, models)
    y_all = fr.y[target]
    out = {"target": target, "aile": "F3", "sozlesme": C.CONTRACT_VERSION, "donemler": {},
           "secim": {"S1_lam": models.s1[target].lam, "S1_secim": models.s1[target].selection,
                     "S2_k": models.s2[target].k, "S2_kappa": models.s2[target].kappa,
                     "S2_secim": models.s2[target].selection, "S0p": models.s0p_info.get(target)},
           "etkili_ornek_S2": models.s2[target].eff}
    for k, (period, _) in enumerate(EVAL_PLAN):
        base, base_sha = shared_rows(fr, target, period, need_market=True)
        mask = base.copy()
        for p in preds.values():
            mask &= np.isfinite(p)
        sha = rows_sha256(fr, mask)
        rec = {"donem": period, "etiket": PERIOD_LABELS[period], "n": int(mask.sum()), "satir_sha256": sha,
               "satir_sha256_ortak_kume": base_sha, "modeller": {}, "s0_fark": {}, "sezon_kararliligi": {}}
        y = y_all[mask]
        losses = {}
        for name, p in preds.items():
            rec["modeller"][name] = {**_metrics(y, p[mask]), "satir_sha256": rows_sha256(fr, mask & np.isfinite(p))}
            losses[name] = _log_loss(y, p[mask]) if mask.any() else np.zeros(0)
        cl = fr.cluster[mask]
        weeks = _iso_weeks(fr, mask) if mask.any() else np.zeros(0, dtype=object)
        seasons = fr.tm["season"].to_numpy()[mask].astype(str)
        for name in ("S0p", "S1", "S2"):
            if not mask.any():
                rec["s0_fark"][name] = {"durum": "SATIR_YOK"}
                continue
            boot = cluster_bootstrap_diff(losses[name], losses["S0"], cl, n_boot, seed + k)
            wk = cluster_bootstrap_diff(losses[name], losses["S0"], weeks, n_boot, seed + k)
            ll0 = float(losses["S0"].mean())
            b0 = float(np.mean((preds["S0"][mask] - y) ** 2))
            bm = float(np.mean((preds[name][mask] - y) ** 2))
            rec["s0_fark"][name] = {
                "durum": "OK", **boot, "mutlak_iyilesme": ll0 - float(losses[name].mean()),
                "goreli_iyilesme": (ll0 - float(losses[name].mean())) / ll0 if ll0 > 0 else float("nan"),
                "brier_beceri": 1.0 - bm / b0 if b0 > 0 else float("nan"),
                "iso_hafta": {"ci_lo": wk["ci_lo"], "ci_hi": wk["ci_hi"], "se": wk["se"],
                              "p_one_sided": wk["p_one_sided"],
                              "n_clusters": wk["n_clusters"]},
            }
            d = losses[name] - losses["S0"]
            per_season = pd.Series(d).groupby(seasons).mean()
            share = float((per_season < 0).mean()) if len(per_season) else float("nan")
            rec["sezon_kararliligi"][name] = {"sezon_fark": {s: float(v) for s, v in per_season.items()},
                                              "iyilesen_sezon_payi": share}
            if name in F3_MODELS:  # 7b yanlışlama uyarlaması (OUT_OF_SAMPLE_SUPPORTED için iki dönemde geçmeli)
                fals = _falsification(fr, mask, d, y, n_boot, seed + 200 + k)
                pc = ctrl.get(name)
                fals["5_piyasa"] = _market_check(y, pc[mask] if pc is not None else None, preds["S0p"][mask], cl,
                                                 n_boot, seed + 300 + k)
                fals["gecti"] = all(v["gecti"] for v in fals.values() if isinstance(v, dict)
                                    and v.get("gecti") is not None)
                rec["s0_fark"][name]["yanlislama"] = fals
        excl = shared_rows(fr, target, period, need_market=False)[0] & ~mask
        rec["dislanan"] = {"n": int(excl.sum()), "neden": "oran yok (S0p tanımsız) veya model tahmini yok",
                           "log_kayip": {name: (float(np.mean(_log_loss(y_all[excl], p[excl])))
                                                if excl.any() and np.isfinite(p[excl]).all() else None)
                                         for name, p in preds.items() if name != "S0p"}}
        out["donemler"][period] = rec
    return out


_HONESTY = ("Test dönemi koşullu örüntüler için ön-kayıtlıdır; S0 İY/MS kalibrasyonu test döneminde görülmüştür. "
            "Tamamen temiz kanıt yalnızca ileriye dönük dönemdir.")


def _failed_checks(par: dict, te: dict) -> list[str] | None:
    """İki dönemde geçmeyen 7b kontrolleri; herhangi bir dönemde 7b değerlendirilmediyse None."""
    out = []
    for name, rec in (("parametre", par), ("test", te)):
        fals = rec.get("yanlislama")
        if not isinstance(fals, dict) or fals.get("gecti") is None:
            return None
        out += [f"{name}:{key}" for key, v in fals.items() if isinstance(v, dict) and v.get("gecti") is False]
    return out


def _f3_status(par: dict, te: dict, p_par: float, p_te: float) -> tuple[str, str]:
    """F3 statüsü (sözleşme §9): OUT_OF_SAMPLE_SUPPORTED için parametre ve test dönemlerinde ayrı ayrı tek yönlü Holm,
    testte ΔLL bootstrap üst sınırı < 0 VE 7b uyarlaması (1, 2, 3, 5) iki dönemde geçmeli."""
    par_ok, te_ok = par.get("durum") == "OK", te.get("durum") == "OK"
    if not par_ok and not te_ok:
        return "INSUFFICIENT_EVIDENCE", "Örneklem dışı değerlendirme yapılamadı (ortak satır yok)."
    par_pass = par_ok and np.isfinite(p_par) and p_par < C.ALPHA
    te_pass = te_ok and np.isfinite(p_te) and p_te < C.ALPHA and te.get("ci_hi", np.inf) < 0
    if par_pass and te_pass:
        failed = _failed_checks(par, te)
        if failed is None:
            return "NO_ADDED_VALUE", "7b yanlışlama uyarlaması değerlendirilmedi; destek statüsü verilmez."
        if not failed:
            return "OUT_OF_SAMPLE_SUPPORTED", (
                "Parametre ve test dönemlerinde ayrı ayrı tek yönlü Holm geçti; test ΔLL lig-sezon kümeli bootstrap "
                "üst sınırı < 0; 7b uyarlaması (1, 2, 3, 5) iki dönemde geçti. " + _HONESTY)
        if all(f.endswith("5_piyasa") for f in failed):
            return "NO_ADDED_VALUE", "Piyasa kontrolünde (S0p offseti) katkı sürmedi (piyasa/temel model bilgisi)."
        return "NO_ADDED_VALUE", "Holm ve bootstrap geçti; 7b yanlışlama uyarlaması geçmedi: " + ", ".join(failed)
    if par_ok and te_ok:
        return "NO_ADDED_VALUE", "Örneklem dışı log-kayıp katkısı Holm düzeltmesiyle doğrulanmadı."
    if (par_ok and not par_pass) or (te_ok and not te_pass):
        return "NO_ADDED_VALUE", "Değerlendirilebilen örneklem dışı dönemde log-kayıp katkısı yok."
    return "EXPLORATORY", "Yalnızca bir örneklem dışı dönem değerlendirilebildi (geçti); ikinci dönem yok."


def run_f3(fr: ResearchFrame, targets: Sequence[str] = C.TARGETS_Q1, models: FittedModels | None = None,
           n_boot: int = MIN_BOOT, seed: int = C.SEED) -> dict:
    """F3: S1 ve S2'nin S0'a katkısı, 4 hedef × 2 model; her dönemde tek yönlü (ΔLL < 0) Holm (k = 8)."""
    models = models or fit_models(fr, targets)
    res = {t: compare_models(fr, t, models, n_boot=n_boot, seed=seed) for t in targets}
    keys = [(t, m) for t in targets for m in F3_MODELS]
    holm_tab = {}
    for period, _ in EVAL_PLAN:
        p = [res[t]["donemler"][period]["s0_fark"][m].get("p_one_sided", np.nan) for t, m in keys]
        holm_tab[period] = holm_family(p)
    rows = []
    for i, (t, m) in enumerate(keys):
        par = res[t]["donemler"]["parametre"]["s0_fark"][m]
        te = res[t]["donemler"]["test"]["s0_fark"][m]
        st, why = _f3_status(par, te, holm_tab["parametre"][i], holm_tab["test"][i])
        if m == "S1" and not math.isfinite(models.s1[t].lam) and st == "OUT_OF_SAMPLE_SUPPORTED":
            st, why = "NO_ADDED_VALUE", "λ = ∞ seçildi: S1 = S0 + sabit; dizi özelliklerinin katkısı yok."
        rows.append({"hedef": t, "model": m, "p_parametre": par.get("p_one_sided"),
                     "p_holm_parametre": float(holm_tab["parametre"][i]),
                     "p_test": te.get("p_one_sided"), "p_holm_test": float(holm_tab["test"][i]),
                     "dll_test": te.get("diff"), "dll_test_ust": te.get("ci_hi"),
                     "yanlislama_parametre": par.get("yanlislama", {}).get("gecti"),
                     "yanlislama_test": te.get("yanlislama", {}).get("gecti"),
                     "piyasa_kontrolu_test": te.get("yanlislama", {}).get("5_piyasa", {}).get("gecti"),
                     "statu": st, "gerekce": why})
    return {"aile": "F3", "sozlesme": C.CONTRACT_VERSION, "config_hash": C.config_hash(), "hipotez_sayisi": len(keys),
            "holm": rows, "hedefler": res,
            "not": ("Holm ailesi: 4 hedef × {S1, S2}; tek yönlü H1: ΔLL(model − S0) < 0. S0p piyasa kontrolüdür, "
                    "aileye girmez. OUT_OF_SAMPLE_SUPPORTED ayrıca 7b uyarlamasını (1 lig/takım çıkarma, 2 en çok "
                    "katkı veren %1, 3 sezon yönü, 5 S0p offsetiyle katkının sürmesi) iki dönemde gerektirir.")}


# ----------------------------------------------------------------------------
# F5: A/B/C ek kontrolü
# ----------------------------------------------------------------------------

def abc_check(fr: ResearchFrame, s0_table: pd.DataFrame, n_boot: int = MIN_BOOT, seed: int = C.SEED,
              lam: float = 0.0) -> dict:
    """F5: maç düzeyi A/B/C (pair_id başına bir satır = ev satırı) için saklı walk-forward M10 A/B/C logiti offset +
    ev ve deplasman takımlarının dizi özellikleri (``ABC_FEATURES``).

    Keşifte uyum (arındırılmış; λ = ``lam``, varsayılan 0 = seçimsiz en çok olabilirlik; değerlendirme dönemi seçimde
    kullanılmaz), parametre döneminde değerlendirme ve 3 pazar üzerinde tek yönlü Holm. Birincil karşılaştırma
    "M10 + sabit" (yalnız sabitin yeniden kalibrasyonu) iledir; ham M10'a göre fark ayrıca verilir. 2019+ (test dönemi)
    rakamları aynı dondurulmuş keşif uyumuyla hesaplanır ve yalnızca ``EXPLORATORY`` etiketlidir (önceki görevin final
    testi; temiz test değildir).
    """
    if n_boot < MIN_BOOT:
        raise ValueError(f"Sözleşme gereği bootstrap tekrar sayısı en az {MIN_BOOT} olmalı")
    if fr.s1 is None:
        raise ValueError("Çerçevede S1 özellikleri yok")
    tm = fr.tm
    home = np.where(tm["is_home"].to_numpy())[0]
    if pd.Series(tm["pair_id"].to_numpy()[home]).duplicated().any():
        raise ValueError("pair_id başına birden fazla ev satırı var")
    away = tm["mirror_row"].to_numpy()[home]
    s0 = s0_table.drop_duplicates("event_id")
    if len(s0) != len(s0_table):
        raise ValueError("S0 tablosunda bir maç için birden fazla tahmin var")
    s0 = s0.set_index("event_id")
    elig = fr.eligible[home] & fr.eligible[away]
    per = fr.period[home]
    day = _days(fr)[home]
    F = fr.s1[list(ABC_FEATURES)].to_numpy(dtype=float)
    X = np.column_stack([F[home], F[away]])
    names = [f"ev_{c}" for c in ABC_FEATURES] + [f"dep_{c}" for c in ABC_FEATURES]
    Xi, means, stds = _impute_scale(X, elig & (per == "kesif"))
    clusters = fr.cluster[home]
    cut = _period_start_day("parametre")
    out = {"aile": "F5", "sozlesme": C.CONTRACT_VERSION, "ozellikler": names, "lam": float(lam), "pazarlar": {},
           "not": ("Keşifte uyum, parametre döneminde değerlendirme (Holm, k = 3). 2019+ rakamları yalnızca "
                   "EXPLORATORY: o dönem önceki görevde A/B/C final testi olarak kullanıldı.")}
    p_param = []
    for s in ABC_MARKETS:
        if s in s0.columns:
            p = s0[s].reindex(tm["event_id"].to_numpy()[home]).to_numpy(dtype=float)
        else:
            p = np.full(len(home), np.nan)
        y = tm[s].to_numpy(dtype=float)[home]
        ok = elig & np.isfinite(p) & (p > 0) & (p < 1) & np.isfinite(y)
        off = _logit(p)
        tr = ok & (per == "kesif") & (day + 1 < cut)
        rec = {"pazar": s, "n_egitim": int(tr.sum()), "egitim_son_tarih": None, "donemler": {}}
        if tr.sum() == 0 or np.unique(y[tr]).size < 2:
            rec["durum"] = "UYUM_YOK"
            out["pazarlar"][s] = rec
            p_param.append(np.nan)
            continue
        rec["egitim_son_tarih"] = str(pd.Timestamp(tm["date"].to_numpy()[home][tr].max()).date())
        fit_f = fit_offset_logistic(Xi[tr], y[tr], off[tr], lam, means=means, stds=stds, names=names)
        fit_0 = fit_offset_logistic(Xi[tr], y[tr], off[tr], math.inf, means=means, stds=stds, names=names)
        rec["uyum"] = fit_f.summary()
        rec["uyum_sabit"] = fit_0.summary()
        for k, period in enumerate(("parametre", "test")):
            ev = ok & (per == period)
            if not ev.any():
                rec["donemler"][period] = {"durum": "SATIR_YOK", "n": 0}
                continue
            yv = y[ev]
            l_raw = _log_loss(yv, p[ev])
            l_0 = _log_loss(yv, fit_0.predict(Xi[ev], off[ev]))
            l_f = _log_loss(yv, fit_f.predict(Xi[ev], off[ev]))
            d = cluster_bootstrap_diff(l_f, l_0, clusters[ev], n_boot, seed + k)
            d_raw = cluster_bootstrap_diff(l_f, l_raw, clusters[ev], n_boot, seed + k)
            prec = {"durum": "OK", "n": int(ev.sum()), "taban_oran": float(yv.mean()),
                    "satir_sha256": rows_sha256(fr, _mask_of(len(tm), home[ev])),
                    "ll_m10": float(l_raw.mean()), "ll_m10_sabit": float(l_0.mean()), "ll_m10_dizi": float(l_f.mean()),
                    "fark_m10_sabit": d,
                    "fark_m10_ham": {kk: d_raw[kk] for kk in ("diff", "ci_lo", "ci_hi", "p_one_sided")}}
            if period == "test":
                prec["etiket"] = "EXPLORATORY"
                prec["not"] = "2019+ yalnızca keşif amaçlı; statü üretmez."
            rec["donemler"][period] = prec
        par = rec["donemler"].get("parametre", {})
        p_param.append(par.get("fark_m10_sabit", {}).get("p_one_sided", np.nan) if par.get("durum") == "OK" else np.nan)
        out["pazarlar"][s] = rec
    adj = holm_family(p_param)
    for s, pa, ph in zip(ABC_MARKETS, p_param, adj):
        rec = out["pazarlar"][s]
        rec["p_parametre"] = float(pa) if np.isfinite(pa) else None
        rec["p_holm_parametre"] = float(ph) if np.isfinite(ph) else None
        par = rec.get("donemler", {}).get("parametre", {})
        if par.get("durum") != "OK":
            rec["statu"], rec["gerekce"] = "INSUFFICIENT_EVIDENCE", "Parametre döneminde değerlendirme yapılamadı."
        elif np.isfinite(ph) and ph < C.ALPHA and par["fark_m10_sabit"]["ci_hi"] < 0:
            rec["statu"] = "EXPLORATORY"
            rec["gerekce"] = ("Parametre döneminde Holm geçti; temiz test dönemi yok (2019+ görülmüş) → yalnızca "
                              "ileriye dönük takip doğrulayabilir.")
        else:
            rec["statu"] = "NO_ADDED_VALUE"
            rec["gerekce"] = "Parametre döneminde dizi özelliklerinin ek katkısı doğrulanmadı."
    return out


# ----------------------------------------------------------------------------
# F6: ekonomik değer (tanımlayıcı, varsayımsal)
# ----------------------------------------------------------------------------

def _unavailable(target: str, names: Sequence[str], reason: str) -> dict:
    return {"target": target, "etiket": ECON_LABEL, "roi": C.ROI_UNAVAILABLE, "neden": reason,
            "esik": C.EV_THRESHOLD, "komisyon": 0.0, "n_mac": 0,
            "kaynaklar": {n: {"n_bahis": 0, "roi": C.ROI_UNAVAILABLE} for n in names}}


def economic_eval(fr: ResearchFrame, target: str, probs: dict, mask: np.ndarray, n_boot: int = MIN_BOOT,
                  seed: int = C.SEED, return_bets: bool = False) -> dict:
    """Araştırmaya özel 1X2 sonuçlandırma (GALIBIYET/MAGLUBIYET; Bet365 oranları, zamanı doğrulanamaz → varsayımsal).

    Takım galibiyeti: ev satırında o_h, deplasman satırında o_a; mağlubiyet hedefi rakibin galibiyet oranını kullanır.
    Maç (event_id) başına seçim başına TEK bahis (ikiz/yinelenen satırlar çift sayılmaz). Tüm kaynaklar aynı maç
    kümesinde (oran ve her olasılık var, hedef biliniyor); bahis: p·oran − 1 ≥ ``config.EV_THRESHOLD``
    (``goals.value.expected_value``, komisyon 0), sabit 1 birim. ROI aralığı lig-sezon kümeli bootstrap.
    İY/MS ve İY-MS geçiş hedefleri: ``config.ROI_UNAVAILABLE``; bahis yoksa ROI de ``ROI_UNAVAILABLE`` (asla 0).
    """
    names = list(probs)
    if target not in ECON_TARGETS:
        reason = ("İY/MS ve İY-MS geçiş hedefleri için doğru pazarın zaman damgalı oranı yok; 1X2'den İY/MS oranı "
                  "türetilmez." if target not in ("BERABERLIK",) else "Beraberlik araştırma hedefi değil.")
        return _unavailable(target, names, reason)
    if n_boot < MIN_BOOT:
        raise ValueError(f"Sözleşme gereği bootstrap tekrar sayısı en az {MIN_BOOT} olmalı")
    tm = fr.tm
    col_h, col_a, sel_h, sel_a = ECON_TARGETS[target]
    is_home = tm["is_home"].to_numpy().astype(bool)
    odds = np.where(is_home, tm[col_h].to_numpy(dtype=float), tm[col_a].to_numpy(dtype=float))
    selection = np.where(is_home, sel_h, sel_a)
    y = fr.y[target]
    cand = np.asarray(mask, dtype=bool) & np.isfinite(y)
    has_odds = np.isfinite(odds) & (odds > 1.0)
    p_ok = np.ones(len(tm), dtype=bool)
    for p in probs.values():
        p = np.asarray(p, dtype=float)
        p_ok &= np.isfinite(p) & (p >= 0) & (p <= 1)
    common = cand & has_odds & p_ok
    rows = np.where(common)[0]
    keys = np.array([f"{e}|{s}" for e, s in zip(tm["event_id"].to_numpy()[rows], selection[rows])], dtype=str)
    _, first = np.unique(keys, return_index=True)
    keep = np.sort(first)
    n_dup = len(rows) - len(keep)
    rows, keys = rows[keep], keys[keep]
    excluded = {"oran_yok": int((cand & ~has_odds).sum()), "olasilik_yok": int((cand & has_odds & ~p_ok).sum()),
                "yinelenen_mac_secim": int(n_dup)}
    if len(rows) == 0:
        res = _unavailable(target, names, "Ortak kümede oranı ve tüm olasılıkları olan maç yok.")
        res["dislanan"] = excluded
        return res
    o = odds[rows]
    yy = y[rows]
    payoff = np.where(yy == 1, o - 1.0, -1.0)
    cl = fr.cluster[rows]
    out = {"target": target, "etiket": ECON_LABEL, "esik": C.EV_THRESHOLD, "komisyon": 0.0, "birim": 1.0,
           "n_mac": int(len(rows)),
           "mac_kumesi_sha256": hashlib.sha256("\n".join(sorted(keys.tolist())).encode()).hexdigest(),
           "dislanan": excluded, "kaynaklar": {},
           "not": ("Bet365 1X2 oranlarının yayımlanma zamanı doğrulanamaz; sonuçlar varsayımsaldır. Benzerlik puanı "
                   "olasılığa eklenmez.")}
    for j, (name, p) in enumerate(probs.items()):
        pv = np.asarray(p, dtype=float)[rows]
        ev = np.array([expected_value(float(a), float(b), commission=0.0) for a, b in zip(pv, o)])
        bet = ev >= C.EV_THRESHOLD
        nb = int(bet.sum())
        rec = {"n_bahis": nb}
        if nb == 0:
            rec["roi"] = C.ROI_UNAVAILABLE
            rec["neden"] = "Eşiği geçen bahis yok."
        else:
            prof = payoff[bet]
            boot = _ratio_boot(prof, np.ones(nb), cl[bet], n_boot, seed + j)
            rec.update({"kazanan": int((yy[bet] == 1).sum()), "net": float(prof.sum()), "roi": float(prof.sum() / nb),
                        "roi_alt": float(np.nanquantile(boot, 0.025)), "roi_ust": float(np.nanquantile(boot, 0.975)),
                        "ort_ev": float(ev[bet].mean()), "ort_oran": float(o[bet].mean()),
                        "n_kume": int(len(np.unique(cl[bet].astype(str))))})
        if return_bets:
            rec["bahis_anahtarlari"] = keys[bet].tolist()
        out["kaynaklar"][name] = rec
    return out


def run_f6(fr: ResearchFrame, models: FittedModels, period: str = "test", targets: Sequence[str] = C.TARGETS_Q1,
           n_boot: int = MIN_BOOT, seed: int = C.SEED) -> dict:
    """F6 (tanımlayıcı): S0, S0p, S1, S2 ve marjsız Bet365 aynı maç kümesinde (F3 ortak satırları) varsayımsal ROI.
    İY-MS geçiş hedefleri ``ROI_UNAVAILABLE``."""
    out = {"aile": "F6", "donem": period, "donem_etiketi": PERIOD_LABELS.get(period), "etiket": ECON_LABEL,
           "hedefler": {}}
    for t in targets:
        preds = model_predictions(fr, t, models)
        if t in ECON_TARGETS:
            preds["Bet365_marjsiz"] = fr.mkt[:, 0] if t == "GALIBIYET" else fr.mkt[:, 2]
        mask, _ = shared_rows(fr, t, period, need_market=True)
        out["hedefler"][t] = economic_eval(fr, t, preds, mask, n_boot=n_boot, seed=seed)
    return out


__all__ = [
    "OffsetLogit", "fit_offset_logistic", "shared_rows", "rows_sha256", "train_mask", "S1Result", "fit_s1", "s1_design",
    "S2Result", "fit_s2", "s2_space", "knn_neighbors", "s2_adjust", "s2_logit_adj", "p0_market", "s0p_predict",
    "s0p_temperature",
    "s1_market_predict", "FittedModels", "fit_models", "model_predictions", "market_controlled_predictions",
    "compare_models", "run_f3", "abc_check", "economic_eval", "run_f6",
    "cluster_bootstrap_diff", "holm", "holm_family",
]

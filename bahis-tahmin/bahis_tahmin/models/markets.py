"""Skor olasılık matrisi ve bahis marketleri."""

from __future__ import annotations

import math

import numpy as np

MAX_GOALS = 10
_G = np.arange(MAX_GOALS + 1)
_FACT = np.array([math.factorial(k) for k in range(MAX_GOALS + 1)], dtype=float)
_I, _J = np.meshgrid(_G, _G, indexing="ij")

MASK_H = _I > _J
MASK_D = _I == _J
MASK_A = _I < _J
MASK_O15 = (_I + _J) >= 2
MASK_O25 = (_I + _J) >= 3
MASK_O35 = (_I + _J) >= 4
MASK_BTTS = (_I >= 1) & (_J >= 1)

# Market kodu -> (Türkçe ad, grup)
MARKETS = {
    "1": ("MS 1", "1X2"),
    "X": ("MS X", "1X2"),
    "2": ("MS 2", "1X2"),
    "1X": ("ÇŞ 1-X", "Çifte Şans"),
    "12": ("ÇŞ 1-2", "Çifte Şans"),
    "X2": ("ÇŞ X-2", "Çifte Şans"),
    "O1.5": ("1.5 Üst", "Alt/Üst 1.5"),
    "U1.5": ("1.5 Alt", "Alt/Üst 1.5"),
    "O2.5": ("2.5 Üst", "Alt/Üst 2.5"),
    "U2.5": ("2.5 Alt", "Alt/Üst 2.5"),
    "O3.5": ("3.5 Üst", "Alt/Üst 3.5"),
    "U3.5": ("3.5 Alt", "Alt/Üst 3.5"),
    "BTTS_Y": ("KG Var", "Karşılıklı Gol"),
    "BTTS_N": ("KG Yok", "Karşılıklı Gol"),
}


def poisson_vec(lam: float) -> np.ndarray:
    return np.exp(-lam) * lam ** _G / _FACT


def score_matrix(lam: float, nu: float, rho: float = 0.0) -> np.ndarray:
    m = np.outer(poisson_vec(lam), poisson_vec(nu))
    m[0, 0] *= max(1.0 - lam * nu * rho, 1e-9)
    m[0, 1] *= max(1.0 + lam * rho, 1e-9)
    m[1, 0] *= max(1.0 + nu * rho, 1e-9)
    m[1, 1] *= max(1.0 - rho, 1e-9)
    return m / m.sum()


def adjust_matrix(m: np.ndarray, p_res=None, p_o25=None, p_btts=None, iters: int = 300, tol: float = 1e-10):
    """Skor matrisini (iteratif oransal uydurma ile) hedef olasılıklara uyarlar.

    Böylece doğru skor, diğer alt/üst baremleri gibi marketler de nihai
    1X2 / 2.5 Alt-Üst / KG olasılıklarıyla tutarlı olur.
    """
    m = np.array(m, dtype=float, copy=True)
    parts = []
    # Sıra önemli: en son uygulanan (1X2) hedefe tam olarak oturur.
    if p_btts is not None and np.isfinite(p_btts):
        parts.append(((MASK_BTTS, ~MASK_BTTS), (float(p_btts), 1.0 - float(p_btts))))
    if p_o25 is not None and np.isfinite(p_o25):
        parts.append(((MASK_O25, ~MASK_O25), (float(p_o25), 1.0 - float(p_o25))))
    if p_res is not None and np.all(np.isfinite(p_res)):
        parts.append(((MASK_H, MASK_D, MASK_A), tuple(float(x) for x in p_res)))
    for _ in range(iters):
        dev = 0.0
        for masks, targets in parts:
            for mask, t in zip(masks, targets):
                s = m[mask].sum()
                if s > 0:
                    dev = max(dev, abs(s - t))
                    m[mask] *= t / s
        if dev < tol:
            break
    return m / m.sum()


def markets_from_matrix(m: np.ndarray) -> dict[str, float]:
    ph, pd_, pa = m[MASK_H].sum(), m[MASK_D].sum(), m[MASK_A].sum()
    o15, o25, o35 = m[MASK_O15].sum(), m[MASK_O25].sum(), m[MASK_O35].sum()
    btts = m[MASK_BTTS].sum()
    return {
        "1": ph, "X": pd_, "2": pa,
        "1X": ph + pd_, "12": ph + pa, "X2": pd_ + pa,
        "O1.5": o15, "U1.5": 1 - o15,
        "O2.5": o25, "U2.5": 1 - o25,
        "O3.5": o35, "U3.5": 1 - o35,
        "BTTS_Y": btts, "BTTS_N": 1 - btts,
    }


def top_scores(m: np.ndarray, n: int = 10) -> list[tuple[int, int, float]]:
    flat = np.argsort(m, axis=None)[::-1][:n]
    return [(int(i), int(j), float(m[i, j])) for i, j in zip(*np.unravel_index(flat, m.shape))]


def expected_goals_from_matrix(m: np.ndarray) -> tuple[float, float]:
    return float((m.sum(axis=1) * _G).sum()), float((m.sum(axis=0) * _G).sum())


# ----------------------------------------------------------------------------
# Toplu (vektörel) hesaplar: geçmiş testlerde binlerce maç için
# ----------------------------------------------------------------------------

MARKET_KEYS = list(MARKETS)
_MASKS = {
    "1": MASK_H, "X": MASK_D, "2": MASK_A,
    "1X": MASK_H | MASK_D, "12": MASK_H | MASK_A, "X2": MASK_D | MASK_A,
    "O1.5": MASK_O15, "U1.5": ~MASK_O15, "O2.5": MASK_O25, "U2.5": ~MASK_O25,
    "O3.5": MASK_O35, "U3.5": ~MASK_O35, "BTTS_Y": MASK_BTTS, "BTTS_N": ~MASK_BTTS,
}


def batch_score_matrices(lam, nu, rho) -> np.ndarray:
    lam = np.asarray(lam, dtype=float)[:, None]
    nu = np.asarray(nu, dtype=float)[:, None]
    rho = np.nan_to_num(np.asarray(rho, dtype=float), nan=0.0)
    ph = np.exp(-lam) * lam ** _G / _FACT
    pa = np.exp(-nu) * nu ** _G / _FACT
    m = ph[:, :, None] * pa[:, None, :]
    lam, nu = lam[:, 0], nu[:, 0]
    m[:, 0, 0] *= np.maximum(1.0 - lam * nu * rho, 1e-9)
    m[:, 0, 1] *= np.maximum(1.0 + lam * rho, 1e-9)
    m[:, 1, 0] *= np.maximum(1.0 + nu * rho, 1e-9)
    m[:, 1, 1] *= np.maximum(1.0 - rho, 1e-9)
    return m / m.sum(axis=(1, 2), keepdims=True)


def batch_adjust(m: np.ndarray, p_res=None, p_o25=None, p_btts=None, iters: int = 60, tol: float = 1e-9):
    """adjust_matrix'in çok maçlı hızlı sürümü (matris çarpımlarıyla)."""
    n = m.shape[0]
    flat = m.reshape(n, -1).copy()
    groups = []
    if p_btts is not None:
        pb = np.asarray(p_btts, dtype=float)
        groups.append((np.stack([MASK_BTTS.ravel(), ~MASK_BTTS.ravel()]).astype(float), np.column_stack([pb, 1 - pb])))
    if p_o25 is not None:
        po = np.asarray(p_o25, dtype=float)
        groups.append((np.stack([MASK_O25.ravel(), ~MASK_O25.ravel()]).astype(float), np.column_stack([po, 1 - po])))
    if p_res is not None:
        groups.append((np.stack([MASK_H.ravel(), MASK_D.ravel(), MASK_A.ravel()]).astype(float), np.asarray(p_res, dtype=float)))
    for _ in range(iters):
        dev = 0.0
        for masks, targets in groups:
            sums = flat @ masks.T  # (n, K)
            ok = np.isfinite(targets) & (sums > 0)
            if not ok.any():
                continue
            dev = max(dev, float(np.max(np.abs(np.where(ok, sums - targets, 0.0)))))
            f = np.where(ok, targets / np.where(sums > 0, sums, 1.0), 1.0)
            flat *= f @ masks
        if dev < tol:
            break
    flat /= flat.sum(axis=1, keepdims=True)
    return flat.reshape(m.shape)


def batch_markets(m: np.ndarray) -> np.ndarray:
    """(n, 11, 11) matrislerden (n, 14) market olasılıkları (MARKET_KEYS sırasıyla)."""
    return np.column_stack([m[:, _MASKS[k]].sum(axis=1) for k in MARKET_KEYS])


def market_outcomes(hg, ag) -> np.ndarray:
    """Gerçekleşen skorlardan (n, 14) market sonuçları (True = kazandı)."""
    hg = np.asarray(hg)
    ag = np.asarray(ag)
    t = hg + ag
    btts = (hg > 0) & (ag > 0)
    return np.column_stack([
        hg > ag, hg == ag, hg < ag, hg >= ag, hg != ag, hg <= ag,
        t >= 2, t <= 1, t >= 3, t <= 2, t >= 4, t <= 3, btts, ~btts,
    ])

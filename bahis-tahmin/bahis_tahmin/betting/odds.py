"""Oran → olasılık dönüşümleri, beklenen değer (EV) ve Kelly hesabı."""

from __future__ import annotations

import numpy as np


def implied_probs(odds, method: str = "power") -> np.ndarray:
    """Bahis şirketi marjı temizlenmiş olasılıklar.

    odds: (n, k) dizisi (ör. 1-X-2 için k=3). Eksik oran içeren satırlar NaN döner.
    method: "proportional" (basit normalizasyon) veya "power" (favori-sürpriz
    yanlılığını daha iyi düzelten üs yöntemi).
    """
    o = np.atleast_2d(np.asarray(odds, dtype=float))
    out = np.full(o.shape, np.nan)
    ok = np.all(np.isfinite(o) & (o > 1.0), axis=1)
    if not ok.any():
        return out
    inv = 1.0 / o[ok]
    if method == "proportional":
        out[ok] = inv / inv.sum(axis=1, keepdims=True)
        return out
    k = np.ones(inv.shape[0])
    log_inv = np.log(inv)
    for _ in range(100):
        p = inv ** k[:, None]
        f = p.sum(axis=1) - 1.0
        d = (p * log_inv).sum(axis=1)
        step = np.where(np.abs(d) > 1e-12, f / d, 0.0)
        k = np.clip(k - step, 0.2, 5.0)
        if np.max(np.abs(step)) < 1e-12:
            break
    p = inv ** k[:, None]
    out[ok] = p / p.sum(axis=1, keepdims=True)
    return out


def overround(odds) -> np.ndarray:
    o = np.atleast_2d(np.asarray(odds, dtype=float))
    return (1.0 / o).sum(axis=1) - 1.0


def expected_value(prob, odds):
    """Birim bahis başına beklenen kâr: p·oran − 1."""
    return np.asarray(prob, dtype=float) * np.asarray(odds, dtype=float) - 1.0


def kelly_fraction(prob, odds, fraction: float = 1.0, cap: float = 1.0):
    """Kasanın yatırılması önerilen oranı (kesirli Kelly, üst sınırlı)."""
    p = np.asarray(prob, dtype=float)
    o = np.asarray(odds, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        f = (p * o - 1.0) / (o - 1.0)
    f = np.where(np.isfinite(f), f, 0.0)
    return np.clip(f * fraction, 0.0, cap)


def fair_odds(prob):
    p = np.asarray(prob, dtype=float)
    with np.errstate(divide="ignore"):
        return np.where(p > 0, 1.0 / p, np.inf)

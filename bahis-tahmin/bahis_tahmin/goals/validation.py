"""Gol pazarları için zaman sıralı (walk-forward) doğrulama, kalibrasyon ve deney günlüğü.

Bölme kuralı (sezon yılı = Temmuz başından itibaren):
  * Isınma (yalnızca takım güçlerinin oturması): veri başlangıcı – 2002/03
  * Geliştirme (model/parametre seçimi): 2008/09 – 2018/19
  * Kapalı final test: 2019/20 – güncel sezon (seçim kararlarında kullanılmaz)
Her test sezonu, yalnızca o sezondan ÖNCEKİ satırlarla eğitilmiş modelle tahmin edilir.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd

from .markets import PRIMARY_YES, SHORT
from .model import FEATURE_VERSION, MODEL_VERSION, ChallengerLR, GoalModel, usable_rows

BURN_IN_LAST = 2002
DEV_YEARS = tuple(range(2008, 2019))
TEST_FIRST = 2019


def season_year(dates) -> np.ndarray:
    d = pd.to_datetime(dates)
    return np.where(d.dt.month >= 7, d.dt.year, d.dt.year - 1)


def walk_forward(feat: pd.DataFrame, years, variants, challengers: dict | None = None, progress=None):
    """Her sezon için yalnızca geçmişle eğitip tahmin üretir. Dönen tablo: satır başına tahminler."""
    feat = feat.copy()
    feat["fold"] = season_year(feat["date"])
    parts, params = [], []
    for Y in years:
        train = feat[(feat["fold"] < Y) & (feat["fold"] > BURN_IN_LAST)]
        test = feat[feat["fold"] == Y]
        if test.empty or len(train) < 2000:
            continue
        if progress:
            progress(Y)
        out = test[["league", "season", "date", "fold", "home", "away", "fthg", "ftag", "hthg", "htag", "issues",
                    *PRIMARY_YES]].copy()
        out["usable"] = usable_rows(test)
        for v in variants:
            m = GoalModel(v).fit(train)
            p = m.predict(test)
            for s in ("A", "B", "C"):
                out[f"{v}:{s}"] = p[s]
            if v != "M0_taban":
                for k in ("h1_home", "h1_away", "h2_home", "h2_away", "BC", "tail"):
                    out[f"{v}:{k}"] = p[k]
            params.append({"fold": int(Y), "variant": v, "k1": m.k1, "k2": m.k2, "phi": m.phi,
                           "mult_h": np.round(m.mult_h, 4).tolist(), "mult_a": np.round(m.mult_a, 4).tolist(),
                           "n_train": m.n_train})
        for name, make in (challengers or {}).items():
            p = make().fit(train).predict(test)
            for s in ("A", "B", "C"):
                out[f"{name}:{s}"] = p[s]
        parts.append(out)
    return (pd.concat(parts) if parts else pd.DataFrame()), params


# ----------------------------------------------------------------------------
# Ölçütler
# ----------------------------------------------------------------------------

def _ll(y, p):
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def calibration_bins(y, p, n_bins: int = 10) -> list[dict]:
    """Eşit sayıda örnek içeren bölmelerde tahmin ortalaması ve gerçekleşme (Wilson %95 aralığı)."""
    order = np.argsort(p)
    rows = []
    for idx in np.array_split(order, n_bins):
        if len(idx) == 0:
            continue
        k, n = y[idx].sum(), len(idx)
        phat = k / n
        z = 1.96
        den = 1 + z * z / n
        c = (phat + z * z / (2 * n)) / den
        h = z * np.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / den
        rows.append({"tahmin": float(p[idx].mean()), "gercek": float(phat), "n": int(n),
                     "alt": float(max(0.0, c - h)), "ust": float(min(1.0, c + h))})
    return rows


def calibration_slope(y, p) -> tuple[float, float]:
    """logit(gerçekleşme) ≈ a + b·logit(p) — b≈1 ve a≈0 iyi kalibrasyon.

    Eğim tanımsızsa (nan, nan) döner, sayı uydurulmaz: tek sınıf, sabit tahmin (eğim kesişimden ayrılamaz; S4-MODEL-01
    öncesinde cezalandırılmış uyum sabite göre ±0,41 gibi sahte eğimler veriyordu), tam/yarı tam ayrışma (en çok
    olabilirlik kestirimi sonlu değil) veya geçersiz girdi."""
    from sklearn.linear_model import LogisticRegression

    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    nan = (float("nan"), float("nan"))
    if len(y) == 0 or len(y) != len(p) or not (np.isfinite(p).all() and np.isin(y, (0.0, 1.0)).all()):
        return nan
    lp = np.log(np.clip(p, 1e-9, 1 - 1e-9) / (1 - np.clip(p, 1e-9, 1 - 1e-9)))
    if len(np.unique(y)) < 2 or np.ptp(lp) < 1e-9:
        return nan
    x1, x0 = lp[y == 1], lp[y == 0]
    if x1.min() >= x0.max() or x1.max() <= x0.min():
        return nan
    m = LogisticRegression(C=1e6, max_iter=1000).fit(lp[:, None], y)
    return float(m.coef_[0, 0]), float(m.intercept_[0])


def block_bootstrap_diff(loss_a, loss_b, blocks, reps: int = 1000, seed: int = 7) -> tuple[float, float, float]:
    """Hafta blokları korunarak ortalama kayıp farkı (a − b) ve %95 aralığı."""
    diff = loss_a - loss_b
    codes, inv = np.unique(blocks, return_inverse=True)
    s = np.bincount(inv, weights=diff)
    c = np.bincount(inv).astype(float)
    rng = np.random.default_rng(seed)
    nb = len(codes)
    draws = rng.integers(0, nb, size=(reps, nb))
    means = s[draws].sum(axis=1) / c[draws].sum(axis=1)
    return float(diff.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def evaluate(pred: pd.DataFrame, models: list[str], reference: str = "M0_taban") -> dict:
    """Pazar ve model bazında olasılık kalitesi (ortak örneklem üzerinde)."""
    from sklearn.metrics import average_precision_score

    res = {}
    weeks = pd.to_datetime(pred["date"]).dt.strftime("%G-%V").to_numpy()
    for key in PRIMARY_YES:
        s = SHORT[key]
        cols = [f"{m}:{s}" for m in models]
        ok = pred[key].notna().to_numpy() & pred["usable"].to_numpy()
        for c in cols + [f"{reference}:{s}"]:
            ok &= np.isfinite(pred[c].to_numpy(dtype=float))
        y = pred.loc[ok, key].to_numpy(dtype=float)
        wk = weeks[ok]
        ref = pred.loc[ok, f"{reference}:{s}"].to_numpy(dtype=float)
        ref_loss = _ll(y, ref)
        market = {"n": int(ok.sum()), "pozitif": int(y.sum()), "taban_oran": float(y.mean()) if len(y) else float("nan"),
                  "modeller": {}}
        for m in models:
            p = pred.loc[ok, f"{m}:{s}"].to_numpy(dtype=float)
            loss = _ll(y, p)
            brier = float(np.mean((p - y) ** 2))
            ref_brier = float(np.mean((ref - y) ** 2))
            d, lo, hi = block_bootstrap_diff(loss, ref_loss, wk) if m != reference else (0.0, 0.0, 0.0)
            slope, icpt = calibration_slope(y, p)
            bins = calibration_bins(y, p)
            ece = float(np.sum([b["n"] * abs(b["tahmin"] - b["gercek"]) for b in bins]) / max(len(y), 1))
            market["modeller"][m] = {
                "log_loss": float(loss.mean()), "brier": brier,
                "brier_skill": float(1 - brier / ref_brier) if ref_brier > 0 else float("nan"),
                "ll_fark_ref": d, "ll_fark_alt": lo, "ll_fark_ust": hi,
                "ap": float(average_precision_score(y, p)) if 0 < y.sum() < len(y) else float("nan"),
                "kal_egim": slope, "kal_kesisim": icpt, "ece": ece,
                "ort_tahmin": float(p.mean()), "kalibrasyon": bins,
            }
        res[key] = market
    return res


def consistency(pred: pd.DataFrame, models: list[str], tol: float = 1e-9) -> dict:
    out = {}
    for m in models:
        a, b, c = (pred[f"{m}:{s}"].to_numpy(dtype=float) for s in ("A", "B", "C"))
        ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(c)
        out[m] = {"n": int(ok.sum()), "A>B": int((a[ok] > b[ok] + tol).sum()), "A>C": int((a[ok] > c[ok] + tol).sum()),
                  "aralik_disi": int(((a[ok] < 0) | (a[ok] > 1) | (b[ok] < 0) | (b[ok] > 1) | (c[ok] < 0) | (c[ok] > 1)).sum())}
    return out


def data_manifest(matches: pd.DataFrame) -> dict:
    h = hashlib.sha256()
    cols = ["league", "date", "home", "away", "fthg", "ftag", "hthg", "htag"]
    h.update(pd.util.hash_pandas_object(matches[cols], index=False).values.tobytes())
    return {
        "n_matches": int(len(matches)),
        "leagues": sorted(matches["league"].unique().tolist()),
        "first_date": str(matches["date"].min().date()),
        "last_date": str(matches["date"].max().date()),
        # Kaynak etiketi olmayan satırlar açıkça "etiketsiz" kaydedilir (köken bilinmiyor; uygunlukta hak engeli)
        "sources": sorted(matches["source"].dropna().astype(str).unique().tolist()
                          + (["etiketsiz"] if matches["source"].isna().any() else [])),
        "sha256": h.hexdigest(),
    }


def log_experiment(path: Path, record: dict) -> None:
    """Deney günlüğüne (JSONL) ekler; başarısız deneyler dahil hiçbir kayıt silinmez."""
    record = {"zaman": dt.datetime.now().isoformat(timespec="seconds"), "python": platform.python_version(),
              "model_surumu": MODEL_VERSION, "ozellik_surumu": FEATURE_VERSION, **record}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=float) + "\n")


def default_challengers():
    from .model import C1_FEATURES, C1_H2H

    return {
        "C1_lojistik": lambda: ChallengerLR(C1_FEATURES),
        "C1_lojistik+H2H": lambda: ChallengerLR(C1_FEATURES + C1_H2H),
    }

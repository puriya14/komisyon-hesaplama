"""Araştırma temel modeli S0: maç başına tek saklı örneklem dışı tahmin ("S0 soy kaydı") ve 9 hücreli kalibrasyon.

* Özellikler, takım adları ``aliases`` ile kanonikleştirilmiş BİR KOPYA veri üzerinde yeniden kurulur
  (üretim modelleri ham adla çalışmaya devam eder; sezon ortası ad değişikliğinde S0 soğuk başlamaz).
* Her sezon yılı Y için M10 (ortak gol dağılımı) yalnızca ``S0_TRAIN_FIRST ≤ sezon < Y`` satırlarıyla eğitilir
  ve Y maçlarını tahmin eder: A/B/C ve aynı dağılımdan 9 İY/MS hücresi (+ ızgara kuyruğu).
* Her maçın S0 tahmini tektir (event_id anahtarlı; fold, eğitim son tarihi ve model özeti ile). Aşağı akıştaki
  her kullanım (beklenen puan, kalibrasyon, referans süreç, S2) yalnızca bu tabloyu okur.
* Kalibrasyon: 9 hücre için çok sınıflı lojistik — log S0 olasılıkları × sıcaklık + 8 serbest hücre sabiti —
  sezon Y için yalnızca daha önceki sezonların SAKLI örneklem dışı tahminleriyle öğrenilir; en az bir tam
  örneklem dışı sezon oluşana kadar özdeşliktir. Hem beklenen değer hem referans süreç bu dağılımı kullanır.
"""

from __future__ import annotations

import hashlib
import pickle
from typing import Callable

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from ..data.leagues import LEAGUES
from ..goals.markets import HTFT_KEYS
from .aliases import AliasMap
from .timeline import season_year

S0_VARIANT = "M10_ipf_kosullu"
S0_TRAIN_FIRST = 2001  # 2000/01 yalnızca takım güçlerinin ısınması
S0_FIRST_FOLD = 2002
MIN_TRAIN_ROWS = 2000
CELL_COLS = list(HTFT_KEYS)  # sıra: 1_1, 1_X, 1_2, X_1, X_X, X_2, 2_1, 2_X, 2_2


def canonical_matches(matches: pd.DataFrame, alias_map: AliasMap | None = None) -> pd.DataFrame:
    """Takım adları kanonikleştirilmiş kopya (ham tablo değişmez). event_id için ham adlar ayrıca saklanır."""
    alias_map = alias_map or AliasMap.from_matches(matches)
    m = matches.copy()
    country = m["league"].map(lambda c: LEAGUES[c].country if c in LEAGUES else c)
    m["home_raw"], m["away_raw"] = m["home"], m["away"]
    m["home"] = [alias_map.canonical(t, c) for t, c in zip(m["home"], country)]
    m["away"] = [alias_map.canonical(t, c) for t, c in zip(m["away"], country)]
    return m


def _model_hash(model) -> str:
    return hashlib.sha256(pickle.dumps(model, protocol=4)).hexdigest()[:16]


def build_s0(matches: pd.DataFrame, feat: pd.DataFrame | None = None, last_fold: int | None = None,
             progress: Callable[[str], None] | None = None, alias_map: AliasMap | None = None) -> pd.DataFrame:
    """Walk-forward S0 tahmin tablosu (maç düzeyi). ``feat`` verilirse (aynı kanonik veriden) yeniden kurulmaz.

    Dönen sütunlar: event_id, league, date, fold, train_until, model_hash, A, B, C, HTFT_* (9), HTFT_KUYRUK.
    """
    from ..goals.features import build_goal_features
    from ..goals.ledger import event_id
    from ..goals.model import GoalModel

    progress = progress or (lambda s: None)
    cm = canonical_matches(matches, alias_map)
    if feat is None:
        progress("S0: yarı bazlı takım güçleri kanonik adlarla hesaplanıyor...")
        feat, _ = build_goal_features(cm.drop(columns=["home_raw", "away_raw"]))
    if len(feat) != len(cm):
        raise ValueError("Özellik tablosu maç tablosuyla aynı uzunlukta değil")
    # build_goal_features satır sırasını korumaz olabilir: (lig, tarih, ev, dep) ile eşle
    key = ["league", "date", "home", "away"]
    raw = cm[key + ["home_raw", "away_raw"]]
    feat = feat.merge(raw, on=key, how="left", validate="one_to_one")
    feat["fold"] = season_year(feat["date"])
    last_fold = int(feat["fold"].max()) if last_fold is None else last_fold
    out = []
    for Y in range(S0_FIRST_FOLD, last_fold + 1):
        train = feat[(feat["fold"] >= S0_TRAIN_FIRST) & (feat["fold"] < Y)]
        test = feat[feat["fold"] == Y]
        if test.empty or len(train) < MIN_TRAIN_ROWS:
            continue
        progress(f"S0: {Y}/{(Y + 1) % 100:02d} sezonu için model (eğitim {len(train):,} maç)")
        model = GoalModel(S0_VARIANT).fit(train)
        p = model.predict(test)
        h = model.htft_probs(test)
        part = pd.DataFrame({
            "event_id": [event_id(lg, d, hr, ar) for lg, d, hr, ar in zip(test["league"], test["date"], test["home_raw"], test["away_raw"])],
            "league": test["league"].to_numpy(), "date": test["date"].to_numpy(), "fold": Y,
            "train_until": str(pd.Timestamp(train["date"].max()).date()), "model_hash": _model_hash(model),
            "A": p["A"], "B": p["B"], "C": p["C"], **{k: h[k] for k in CELL_COLS}, "HTFT_KUYRUK": h["HTFT_KUYRUK"],
        })
        assert pd.Timestamp(train["date"].max()) < pd.Timestamp(test["date"].min()), "S0 eğitimi tahmin edilen maçlardan önce bitmeli"
        out.append(part)
    s0 = pd.concat(out, ignore_index=True)
    if s0["event_id"].duplicated().any():
        raise ValueError("Bir maç için birden fazla S0 tahmini oluştu")
    return s0


# ----------------------------------------------------------------------------
# 9 hücreli kalibrasyon
# ----------------------------------------------------------------------------

def _cal_apply(P: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """q_k ∝ p_k^T · exp(b_k); theta = [log T, b_1..b_8] (b_0 = 0)."""
    T = np.exp(theta[0])
    b = np.concatenate([[0.0], theta[1:]])
    z = T * np.log(np.clip(P, 1e-12, None)) + b[None, :]
    z -= z.max(axis=1, keepdims=True)
    q = np.exp(z)
    return q / q.sum(axis=1, keepdims=True)


def fit_calibration(P: np.ndarray, y: np.ndarray, ridge: float = 1e-3) -> np.ndarray:
    """Çok sınıflı lojistik kalibrasyon parametreleri (y: 0..8 hücre dizini; P: (n, 9) olasılıklar)."""
    P = P / P.sum(axis=1, keepdims=True)  # ızgara kuyruğu (≤1e-5) yalnızca kalibrasyon girdisinde normalize edilir
    logP = np.log(np.clip(P, 1e-12, None))
    Y = np.zeros_like(P)
    Y[np.arange(len(y)), y] = 1.0

    def f(theta):
        T = np.exp(theta[0])
        b = np.concatenate([[0.0], theta[1:]])
        z = T * logP + b[None, :]
        zmax = z.max(axis=1, keepdims=True)
        lse = zmax[:, 0] + np.log(np.exp(z - zmax).sum(axis=1))
        nll = float((lse - (z * Y).sum(axis=1)).sum())
        q = np.exp(z - lse[:, None])
        r = q - Y
        g_logt = float((r * logP).sum() * T)
        g_b = r.sum(axis=0)[1:]
        return nll + 0.5 * ridge * float(theta @ theta), np.concatenate([[g_logt], g_b]) + ridge * theta

    res = minimize(f, np.zeros(9), jac=True, method="L-BFGS-B")
    return res.x


def calibrated_cells(s0: pd.DataFrame, cells: pd.Series) -> tuple[pd.DataFrame, dict]:
    """Sezon sezon genişleyen pencereyle kalibre edilmiş 9 hücre (ev perspektifi ham İY/MS).

    ``cells``: s0 satırlarıyla hizalı gerçekleşen ham hücre dizini (0..8; bilinmiyorsa -1).
    Sezon Y'nin parametreleri yalnızca Y'den önceki sezonların saklı S0 tahminleri ve sonuçlarıyla öğrenilir.
    """
    P = s0[CELL_COLS].to_numpy(dtype=float)
    out = np.full_like(P, np.nan)
    params = {}
    folds = s0["fold"].to_numpy()
    yv = np.asarray(cells)
    ok_all = np.isfinite(P).all(axis=1)
    for Y in sorted(np.unique(folds)):
        cur = (folds == Y) & ok_all
        prev = (folds < Y) & ok_all & (yv >= 0)
        if prev.sum() < 5000:  # en az bir tam örneklem dışı sezon yoksa özdeşlik
            theta = np.zeros(9)
        else:
            theta = fit_calibration(P[prev], yv[prev])
        params[int(Y)] = theta.tolist()
        out[cur] = _cal_apply(P[cur] / P[cur].sum(axis=1, keepdims=True), theta)
    q = s0[["event_id"]].copy()
    for i, k in enumerate(CELL_COLS):
        q[k] = out[:, i]
    return q, params

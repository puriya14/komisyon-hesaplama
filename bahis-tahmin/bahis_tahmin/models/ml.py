"""Makine öğrenmesi modelleri: lojistik regresyon + gradient boosting topluluğu
ve model olasılıklarını piyasa olasılıklarıyla birleştiren harmanlayıcı."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, TransformerMixin
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURES

EPS = 1e-6
LARGE_N = 15000  # bu kadar eğitim satırının üstünde tam topluluk doğrudan kullanılır
COMPACT = [
    "dc_ph", "dc_pd", "dc_pa", "dc_o25", "dc_btts", "dc_lh", "dc_la",
    "elo_diff", "mr_z", "mr_t", "sot_lh", "sot_la",
]


class QuantileClipper(BaseEstimator, TransformerMixin):
    """Aşırı değerleri eğitim verisinin %0.5-%99.5 aralığına kırpar (az veride kararlılık için)."""

    def __init__(self, lo: float = 0.005, hi: float = 0.995):
        self.lo = lo
        self.hi = hi

    def fit(self, X, y=None):
        a = np.asarray(X, dtype=float)
        self.lo_ = np.nanquantile(a, self.lo, axis=0)
        self.hi_ = np.nanquantile(a, self.hi, axis=0)
        return self

    def transform(self, X):
        a = np.asarray(X, dtype=float)
        return np.clip(a, self.lo_, self.hi_)


class ColumnSelect(BaseEstimator, TransformerMixin):
    def __init__(self, columns: list[str]):
        self.columns = columns

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        return X[self.columns]


class DCPassthrough(BaseEstimator, ClassifierMixin):
    """Dixon-Coles olasılıklarını doğrudan kullanan referans "model"."""

    def __init__(self, target: str = "res"):
        self.target = target

    def fit(self, X, y):
        self.classes_ = np.unique(y)
        self.base_ = np.bincount(np.asarray(y, dtype=int), minlength=len(self.classes_)) / len(y)
        return self

    def predict_proba(self, X):
        if self.target == "res":
            p = X[["dc_ph", "dc_pd", "dc_pa"]].to_numpy(dtype=float)
            bad = ~np.all(np.isfinite(p), axis=1)
            p[bad] = self.base_
            return p / p.sum(axis=1, keepdims=True)
        col = "dc_o25" if self.target == "o25" else "dc_btts"
        q = X[col].to_numpy(dtype=float)
        q = np.where(np.isfinite(q), q, self.base_[1])
        q = np.clip(q, EPS, 1 - EPS)
        return np.column_stack([1 - q, q])


def _lr(C: float = 0.5, columns: list[str] | None = None):
    steps = [ColumnSelect(columns)] if columns else []
    steps += [
        SimpleImputer(strategy="median"), QuantileClipper(), StandardScaler(), LogisticRegression(C=C, max_iter=3000)
    ]
    return make_pipeline(*steps)


def _hgb(seed: int = 0):
    return HistGradientBoostingClassifier(
        max_depth=3,
        learning_rate=0.05,
        max_iter=400,
        min_samples_leaf=100,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=30,
        random_state=seed,
    )


def _candidates(target: str, n: int) -> dict[str, list]:
    """Veri miktarına uygun aday modeller (her biri olasılıkları ortalanan bir model listesi)."""
    c = {
        "dc": [DCPassthrough(target)],
        "basit": [_lr(0.1, COMPACT)],
        "tam": [_lr(0.05 if n < 5000 else 0.2), _hgb()],
    }
    return c


def _ll(y, probs) -> float:
    p = np.clip(probs[np.arange(len(y)), np.searchsorted(np.arange(probs.shape[1]), y)], 1e-9, 1.0)
    return float(-np.mean(np.log(p)))


class OutcomeModel:
    """Maç sonucu (1X2), Alt/Üst 2.5 ve Karşılıklı Gol için olasılık modeli.

    Büyük veride lojistik regresyon + gradient boosting topluluğu kullanılır. Az veride
    aday modeller (yalnızca Dixon-Coles, sade lojistik regresyon, tam topluluk) eğitim
    verisinin en yeni %25'lik kısmında zaman sırasına uygun olarak sınanır ve en iyisi seçilir.
    """

    TARGETS = ("res", "o25", "btts")

    def __init__(self, features: list[str] | None = None):
        self.features = list(features or FEATURES)
        self.models: dict[str, list] = {}
        self.chosen: dict[str, str] = {}
        self.n_train = 0

    def fit(self, df: pd.DataFrame) -> "OutcomeModel":
        df = df.sort_values("date", kind="mergesort") if "date" in df.columns else df
        X = df[self.features]
        n = len(df)
        self.n_train = n
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for t in self.TARGETS:
                y = df[f"y_{t}"].to_numpy()
                if n >= LARGE_N:
                    self.models[t] = [_lr(), _hgb()]
                    self.chosen[t] = "tam"
                else:
                    cut = int(n * 0.75)
                    scores = {}
                    for name, models in _candidates(t, cut).items():
                        try:
                            fitted = [m.fit(X.iloc[:cut], y[:cut]) for m in models]
                            probs = np.mean([m.predict_proba(X.iloc[cut:]) for m in fitted], axis=0)
                            scores[name] = _ll(y[cut:], probs)
                        except ValueError:
                            continue
                    best = min(scores, key=scores.get) if scores else "dc"
                    self.chosen[t] = best
                    self.models[t] = _candidates(t, n)[best]
                for m in self.models[t]:
                    m.fit(X, y)
        return self

    def predict(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        X = df[self.features]
        out = {}
        for t in self.TARGETS:
            probs = np.mean([m.predict_proba(X) for m in self.models[t]], axis=0)
            out[t] = probs if t == "res" else probs[:, 1]
        return out


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


class MarketBlender:
    """Model ve piyasa olasılıklarını geçmiş performansa göre ağırlıklandırarak birleştirir.

    Eğitim verisi modelin örneklem dışı (out-of-sample) tahminleridir; böylece
    harmanlayıcı modelin piyasaya göre ne kadar güvenilir olduğunu öğrenir.
    """

    def __init__(self):
        self.res: LogisticRegression | None = None
        self.o25: LogisticRegression | None = None
        self.coef_res: list[float] = []
        self.coef_o25: list[float] = []

    @staticmethod
    def _x_res(pm, pk):
        return np.column_stack([np.log(np.clip(pm, EPS, 1)), np.log(np.clip(pk, EPS, 1))])

    @staticmethod
    def _x_o25(pm, pk):
        return np.column_stack([_logit(pm), _logit(pk)])

    def fit(self, pm_res, pk_res, y_res, pm_o25, pk_o25, y_o25) -> "MarketBlender":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ok = np.all(np.isfinite(pk_res), axis=1)
            if ok.sum() >= 500 and len(np.unique(y_res[ok])) == 3:
                self.res = LogisticRegression(C=0.1, max_iter=3000).fit(
                    self._x_res(pm_res[ok], pk_res[ok]), y_res[ok]
                )
                self.coef_res = self.res.coef_.ravel().round(3).tolist()
            ok = np.isfinite(pk_o25)
            if ok.sum() >= 500 and len(np.unique(y_o25[ok])) == 2:
                self.o25 = LogisticRegression(C=0.1, max_iter=3000).fit(
                    self._x_o25(pm_o25[ok], pk_o25[ok]), y_o25[ok]
                )
                self.coef_o25 = self.o25.coef_.ravel().round(3).tolist()
        return self

    def blend_res(self, pm: np.ndarray, pk: np.ndarray) -> np.ndarray:
        """pm, pk: (n, 3). Piyasa olasılığı olmayan satırlarda model olasılığı döner."""
        pm = np.atleast_2d(pm)
        pk = np.atleast_2d(pk)
        out = pm.copy()
        ok = np.all(np.isfinite(pk), axis=1)
        if ok.any():
            if self.res is not None:
                out[ok] = self.res.predict_proba(self._x_res(pm[ok], pk[ok]))
            else:
                out[ok] = pk[ok]
        return out

    def blend_o25(self, pm: np.ndarray, pk: np.ndarray) -> np.ndarray:
        pm = np.atleast_1d(np.asarray(pm, dtype=float))
        pk = np.atleast_1d(np.asarray(pk, dtype=float))
        out = pm.copy()
        ok = np.isfinite(pk)
        if ok.any():
            if self.o25 is not None:
                out[ok] = self.o25.predict_proba(self._x_o25(pm[ok], pk[ok]))[:, 1]
            else:
                out[ok] = pk[ok]
        return out

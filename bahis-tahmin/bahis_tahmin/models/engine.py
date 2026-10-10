"""Tahmin motoru: eğitim (walk-forward), örneklem dışı tahminler ve maç tahmini."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .. import __version__
from ..betting.odds import expected_value, implied_probs, kelly_fraction
from ..data.leagues import league_name
from ..data.parsers import ODDS_COLUMNS
from .features import FEATURES, LeagueState, build_features, day_number
from .markets import (
    MARKET_KEYS,
    MARKETS,
    adjust_matrix,
    batch_adjust,
    batch_markets,
    batch_score_matrices,
    expected_goals_from_matrix,
    market_outcomes,
    markets_from_matrix,
    score_matrix,
)
from .ml import MarketBlender, OutcomeModel

log = logging.getLogger(__name__)

ENGINE_VERSION = 5
MIN_TRAIN_ROWS = 1500

# Oran türü -> (1, X, 2, Üst 2.5, Alt 2.5) sütunları
ODDS_SETS = {
    "avg": ("o_h", "o_d", "o_a", "o_o25", "o_u25"),
    "max": ("omax_h", "omax_d", "omax_a", "omax_o25", "omax_u25"),
    "b365": ("b365_h", "b365_d", "b365_a", "o_o25", "o_u25"),
    "pinnacle": ("ps_h", "ps_d", "ps_a", "o_o25", "o_u25"),
}
ODDS_TYPE_LABELS = {
    "avg": "Piyasa ortalaması",
    "max": "En yüksek oran (varsayımsal)",
    "b365": "Bet365",
    "pinnacle": "Pinnacle",
}

KEEP_COLS = (
    ["league", "season", "date", "home", "away", "fthg", "ftag", "y_res", "y_o25", "y_btts",
     "dc_lh", "dc_la", "dc_rho"]
    + ODDS_COLUMNS
)
PMK_COLS = [f"pmk_{k}" for k in MARKET_KEYS]
CONF_THRESHOLDS = (0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.92, 0.95)

ProgressFn = Callable[[int, str], None]


def season_year(dates: pd.Series) -> np.ndarray:
    """Temmuz başından itibaren yeni "sezon yılı" (takvim yılı ligleri için de ortak dilim)."""
    d = pd.to_datetime(dates)
    return np.where(d.dt.month >= 7, d.dt.year, d.dt.year - 1)


def market_probs(df: pd.DataFrame, method: str = "power") -> tuple[np.ndarray, np.ndarray]:
    """Piyasa (marjsız) olasılıkları: önce ortalama oran, yoksa Bet365, yoksa Pinnacle."""
    pk = np.full((len(df), 3), np.nan)
    for cols in (("o_h", "o_d", "o_a"), ("b365_h", "b365_d", "b365_a"), ("ps_h", "ps_d", "ps_a")):
        miss = ~np.all(np.isfinite(pk), axis=1)
        if not miss.any():
            break
        pk[miss] = implied_probs(df.loc[miss, list(cols)].to_numpy(dtype=float), method)
    pko = implied_probs(df[["o_o25", "o_u25"]].to_numpy(dtype=float), method)[:, 0]
    return pk, pko


def market_odds_matrix(df: pd.DataFrame, odds_type: str = "avg") -> np.ndarray:
    """(n, 14) GERÇEK teklif edilen oranlar (MARKET_KEYS sırasıyla).

    Veride yalnızca 1X2 ve 2.5 Alt/Üst oranları vardır. Çifte Şans, 1.5/3.5 Alt/Üst ve KG oranları
    başka oranlardan TÜRETİLMEZ; bu marketler için getiri hesaplanamaz (NaN).
    """
    c = ODDS_SETS.get(odds_type, ODDS_SETS["avg"])
    o1, ox, o2, oo, ou = (df[col].to_numpy(dtype=float) if col in df.columns else np.full(len(df), np.nan) for col in c)
    nan = np.full(len(df), np.nan)
    cols = {
        "1": o1, "X": ox, "2": o2, "1X": nan, "12": nan, "X2": nan,
        "O1.5": nan, "U1.5": nan, "O2.5": oo, "U2.5": ou, "O3.5": nan, "U3.5": nan,
        "BTTS_Y": nan, "BTTS_N": nan,
    }
    return np.column_stack([cols[k] for k in MARKET_KEYS])


def confidence_report(oos: pd.DataFrame, thresholds=CONF_THRESHOLDS) -> dict:
    """Güven eşiğine göre isabet oranı / kapsam tabloları (örneklem dışı)."""
    if oos is None or oos.empty or PMK_COLS[0] not in oos.columns:
        return {}
    P = oos[PMK_COLS].to_numpy(dtype=float)
    W = market_outcomes(oos["fthg"].to_numpy(), oos["ftag"].to_numpy())
    O = market_odds_matrix(oos, "avg")
    n = len(oos)
    rows_1x2, rows_best = [], []
    p1 = P[:, :3]
    pick = p1.argmax(axis=1)
    top = p1.max(axis=1)
    win1 = W[np.arange(n), pick]
    odd1 = O[np.arange(n), pick]
    # "En iyi seçim": tüm marketlerde en yüksek olasılıklı seçenek
    best = P.argmax(axis=1)
    bp = P.max(axis=1)
    bw = W[np.arange(n), best]
    bo = O[np.arange(n), best]
    for t in thresholds:
        for rows, mask, wins, odds, probs in ((rows_1x2, top >= t, win1, odd1, top), (rows_best, bp >= t, bw, bo, bp)):
            k = int(mask.sum())
            if k == 0:
                rows.append({"esik": t, "n": 0, "kapsam": 0.0, "isabet": float("nan"), "ort_olasilik": float("nan"),
                             "roi": float("nan"), "roi_n": 0, "ort_oran": float("nan")})
                continue
            has_o = mask & np.isfinite(odds)
            roi = float(np.mean(np.where(wins[has_o], odds[has_o] - 1.0, -1.0))) if has_o.any() else float("nan")
            rows.append({
                "esik": t, "n": k, "kapsam": k / n, "isabet": float(wins[mask].mean()),
                "ort_olasilik": float(probs[mask].mean()), "roi": roi, "roi_n": int(has_o.sum()),
                "ort_oran": float(np.mean(odds[has_o])) if has_o.any() else float("nan"),
            })
    per_market = []
    for j, key in enumerate(MARKET_KEYS):
        m = P[:, j] >= 0.9
        if m.sum() == 0:
            continue
        has_o = m & np.isfinite(O[:, j])
        per_market.append({
            "market": key, "label": MARKETS[key][0], "n": int(m.sum()), "isabet": float(W[m, j].mean()),
            "ort_olasilik": float(P[m, j].mean()),
            "roi": float(np.mean(np.where(W[has_o, j], O[has_o, j] - 1.0, -1.0))) if has_o.any() else float("nan"),
            "roi_n": int(has_o.sum()),
        })
    return {"top1x2": rows_1x2, "best": rows_best, "per_market_90": per_market, "n": n}


def _ll3(y, p) -> float:
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1.0)
    p = p / p.sum(axis=1, keepdims=True)
    return float(-np.mean(np.log(p[np.arange(len(y)), y])))


def _ll2(y, p) -> float:
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _brier3(y, p) -> float:
    onehot = np.zeros_like(p)
    onehot[np.arange(len(y)), y] = 1
    return float(np.mean(np.sum((p - onehot) ** 2, axis=1)))


def evaluate(oos: pd.DataFrame) -> dict:
    """Örneklem dışı tahminlerin kalite ölçüleri (model / piyasa / nihai)."""
    if oos is None or oos.empty:
        return {}
    y = oos["y_res"].to_numpy()
    pm = oos[["pm_h", "pm_d", "pm_a"]].to_numpy()
    pk = oos[["pk_h", "pk_d", "pk_a"]].to_numpy()
    pf = oos[["pf_h", "pf_d", "pf_a"]].to_numpy()
    hm = np.all(np.isfinite(pk), axis=1)
    res = {
        "n": int(len(oos)),
        "n_market": int(hm.sum()),
        "acc_model": float(np.mean(pm.argmax(1) == y)),
        "ll_model_all": _ll3(y, pm),
        "brier_model_all": _brier3(y, pm),
    }
    if hm.any():
        res.update({
            "ll_model": _ll3(y[hm], pm[hm]),
            "ll_market": _ll3(y[hm], pk[hm]),
            "ll_final": _ll3(y[hm], pf[hm]),
            "acc_market": float(np.mean(pk[hm].argmax(1) == y[hm])),
            "acc_final": float(np.mean(pf[hm].argmax(1) == y[hm])),
            "acc_model_m": float(np.mean(pm[hm].argmax(1) == y[hm])),
            "brier_model": _brier3(y[hm], pm[hm]),
            "brier_market": _brier3(y[hm], pk[hm]),
        })
    yo = oos["y_o25"].to_numpy()
    res["ll_o25_model"] = _ll2(yo, oos["pm_o25"].to_numpy())
    ho = np.isfinite(oos["pk_o25"].to_numpy())
    if ho.any():
        res["ll_o25_model_m"] = _ll2(yo[ho], oos["pm_o25"].to_numpy()[ho])
        res["ll_o25_market"] = _ll2(yo[ho], oos["pk_o25"].to_numpy()[ho])
        res["acc_o25_model"] = float(np.mean((oos["pm_o25"].to_numpy()[ho] > 0.5) == yo[ho]))
    yb = oos["y_btts"].to_numpy()
    res["ll_btts_model"] = _ll2(yb, oos["pm_btts"].to_numpy())
    res["acc_btts_model"] = float(np.mean((oos["pm_btts"].to_numpy() > 0.5) == yb))
    # Basit referans: her zaman lig ortalaması (önceki sezonlardan bağımsız sabit oran)
    base = np.bincount(y, minlength=3) / len(y)
    res["ll_baseline"] = _ll3(y, np.tile(base, (len(y), 1)))
    return res


@dataclass
class TrainReport:
    trained_at: str = ""
    duration: float = 0.0
    n_matches: int = 0
    n_train: int = 0
    leagues: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    per_season: list[dict] = field(default_factory=list)
    blend_coef: dict = field(default_factory=dict)
    confidence: dict = field(default_factory=dict)


@dataclass
class MatchPrediction:
    league: str
    home: str
    away: str
    date: pd.Timestamp
    time: str
    p_model: np.ndarray
    p_market: np.ndarray | None
    p_final: np.ndarray
    o25_model: float
    o25_market: float
    o25_final: float
    btts_final: float
    matrix: np.ndarray
    markets: dict[str, float]
    odds: dict[str, float]
    info: dict
    source: str = ""

    @property
    def exp_goals(self) -> tuple[float, float]:
        return expected_goals_from_matrix(self.matrix)

    def value_rows(self, settings, odds: dict[str, float] | None = None) -> list[dict]:
        """Her market için olasılık, adil oran, EV ve önerilen bahis miktarı."""
        odds = self.odds if odds is None else odds
        rows = []
        for key, (label, group) in MARKETS.items():
            p = float(self.markets[key])
            o = odds.get(key)
            o = float(o) if o is not None and np.isfinite(o) and o > 1.0 else None
            ev = float(expected_value(p, o)) if o else float("nan")
            k = float(kelly_fraction(p, o, settings.kelly_fraction, settings.max_stake_pct)) if o else 0.0
            is_value = bool(
                o is not None
                and ev >= settings.min_ev
                and p >= settings.min_prob
                and settings.min_odds <= o <= settings.max_odds
            )
            show_stake = bool(getattr(settings, "stake_suggestions", False))
            rows.append({
                "market": key, "label": label, "group": group, "prob": p,
                "fair": 1.0 / p if p > 0 else float("inf"), "odds": o, "ev": ev,
                "kelly": k, "stake": k * settings.bankroll if (is_value and show_stake) else 0.0, "value": is_value,
            })
        return rows

    def best_value(self, settings) -> dict | None:
        rows = [r for r in self.value_rows(settings) if r["value"]]
        return max(rows, key=lambda r: r["ev"]) if rows else None


class PredictionEngine:
    def __init__(self):
        self.version = ENGINE_VERSION
        self.app_version = __version__
        self.states: dict[str, LeagueState] = {}
        self.model: OutcomeModel | None = None
        self.blender: MarketBlender | None = None
        self.oos: pd.DataFrame | None = None
        self.report: TrainReport | None = None
        self.margin_method = "power"
        self.data_signature = ""
        self.last_match_date: pd.Timestamp | None = None

    # ------------------------------------------------------------- persist
    @property
    def trained(self) -> bool:
        return self.model is not None and bool(self.states)

    last_load_error: str | None = None

    def save(self, path: Path) -> None:
        from .artifacts import save_artifact

        rep = self.report
        save_artifact(self, path, "match-engine", ENGINE_VERSION, meta={
            "trained_at": rep.trained_at if rep else None,
            "data_cutoff": str(self.last_match_date.date()) if self.last_match_date is not None else None,
            "n_matches": rep.n_matches if rep else None,
            "leagues": rep.leagues if rep else [],
            "data_signature": self.data_signature,
            "feature_schema": list(self.model.features) if self.model else [],
            "validation": {k: v for k, v in (rep.metrics if rep else {}).items() if isinstance(v, (int, float))},
        })

    @staticmethod
    def load(path: Path) -> "PredictionEngine | None":
        from .artifacts import load_artifact

        eng, _man, err = load_artifact(path, "match-engine", ENGINE_VERSION)
        PredictionEngine.last_load_error = err
        if err:
            log.info("Model yüklenmedi: %s", err)
            return None
        if not isinstance(eng, PredictionEngine):
            PredictionEngine.last_load_error = "Beklenmeyen model nesnesi."
            return None
        return eng

    @staticmethod
    def signature(matches: pd.DataFrame, margin_method: str = "power") -> str:
        if matches.empty:
            return ""
        h = hashlib.sha1()
        h.update(f"{ENGINE_VERSION}|{margin_method}|{len(matches)}".encode())
        for lg, g in matches.groupby("league"):
            h.update(f"{lg}:{len(g)}:{g['date'].max()}:{int(g['fthg'].sum())}:{int(g['ftag'].sum())}".encode())
        return h.hexdigest()

    # --------------------------------------------------------------- train
    def train(
        self,
        matches: pd.DataFrame,
        progress: ProgressFn | None = None,
        margin_method: str = "power",
    ) -> TrainReport:
        progress = progress or (lambda p, m: None)
        t0 = time.time()
        self.margin_method = margin_method
        progress(1, "Özellikler hesaplanıyor...")

        def fprog(frac: float, lg: str) -> None:
            if lg:
                progress(2 + int(43 * frac), f"Güç reytingleri ve form hesaplanıyor: {league_name(lg)}")

        feat, states = build_features(matches, progress=fprog)
        if feat.empty:
            raise ValueError("Eğitim için maç verisi yok.")
        pk, pko = market_probs(feat, margin_method)
        feat[["pk_h", "pk_d", "pk_a"]] = pk
        feat["pk_o25"] = pko
        years = season_year(feat["date"])
        feat["fold"] = years
        first = int(years.min())
        train_start = pd.Timestamp(first + 1, 7, 1)
        usable = feat[(feat["date"] >= train_start) & feat["dc_ph"].notna()]
        if len(usable) < MIN_TRAIN_ROWS:
            # Kısa geçmişte ilk sezonu da eğitime kat
            usable = feat[feat["dc_ph"].notna()]
        if len(usable) < 300:
            raise ValueError("Eğitim için yeterli maç yok (en az birkaç sezon gerekli).")

        fold_years = sorted(set(int(y) for y in usable["fold"].unique()))
        # Kısa geçmişlerde (az lig/yıl) daha küçük eğitim kümelerine izin ver
        min_rows = max(200, min(MIN_TRAIN_ROWS, len(usable) // 3))
        oos_parts = []
        n_folds = max(len(fold_years), 1)
        for k, Y in enumerate(fold_years):
            progress(45 + int(45 * k / n_folds), f"Geriye dönük test için model eğitiliyor: {Y}/{(Y + 1) % 100:02d}")
            cut = pd.Timestamp(Y, 7, 1)
            tr = usable[usable["date"] < cut]
            te = usable[usable["fold"] == Y]
            if len(tr) < min_rows or te.empty:
                continue
            m = OutcomeModel().fit(tr)
            pr = m.predict(te)
            part = te[KEEP_COLS + ["pk_h", "pk_d", "pk_a", "pk_o25", "fold"]].copy()
            part[["pm_h", "pm_d", "pm_a"]] = pr["res"]
            part["pm_o25"] = pr["o25"]
            part["pm_btts"] = pr["btts"]
            oos_parts.append(part)

        oos = pd.concat(oos_parts) if oos_parts else pd.DataFrame()
        if not oos.empty:
            pf = np.full((len(oos), 3), np.nan)
            pfo = np.full(len(oos), np.nan)
            for Y in sorted(oos["fold"].unique()):
                prev = oos[oos["fold"] < Y]
                cur = (oos["fold"] == Y).to_numpy()
                b = self._fit_blender(prev) if len(prev) >= 500 else MarketBlender()
                pf[cur] = b.blend_res(oos.loc[cur, ["pm_h", "pm_d", "pm_a"]].to_numpy(),
                                      oos.loc[cur, ["pk_h", "pk_d", "pk_a"]].to_numpy())
                pfo[cur] = b.blend_o25(oos.loc[cur, "pm_o25"].to_numpy(), oos.loc[cur, "pk_o25"].to_numpy())
            oos[["pf_h", "pf_d", "pf_a"]] = pf
            oos["pf_o25"] = pfo
            oos["pf_btts"] = oos["pm_btts"]
            progress(89, "Tüm marketler için olasılıklar hesaplanıyor...")
            lam = oos["dc_lh"].fillna(oos["dc_lh"].median()).to_numpy()
            nu = oos["dc_la"].fillna(oos["dc_la"].median()).to_numpy()
            mats = batch_adjust(batch_score_matrices(lam, nu, oos["dc_rho"].to_numpy()), pf, pfo, oos["pm_btts"].to_numpy())
            oos[PMK_COLS] = batch_markets(mats)
            del mats

        progress(91, "Nihai model tüm verilerle eğitiliyor...")
        self.model = OutcomeModel().fit(usable)
        self.blender = self._fit_blender(oos) if len(oos) >= 500 else MarketBlender()
        self.states = states
        self.oos = oos.reset_index(drop=True) if not oos.empty else oos
        self.data_signature = self.signature(matches, margin_method)
        self.last_match_date = pd.Timestamp(matches["date"].max())

        per_season = []
        if not oos.empty:
            for Y, g in oos.groupby("fold"):
                ev = evaluate(g)
                ev["season"] = f"{Y}/{(Y + 1) % 100:02d}"
                per_season.append(ev)
        self.report = TrainReport(
            trained_at=dt.datetime.now().isoformat(timespec="seconds"),
            duration=time.time() - t0,
            n_matches=int(len(matches)),
            n_train=int(len(usable)),
            leagues=sorted(states),
            metrics=evaluate(oos),
            per_season=per_season,
            blend_coef={"1x2": self.blender.coef_res, "o25": self.blender.coef_o25},
            confidence=confidence_report(oos),
        )
        progress(100, "Model hazır.")
        return self.report

    @staticmethod
    def _fit_blender(oos: pd.DataFrame) -> MarketBlender:
        return MarketBlender().fit(
            oos[["pm_h", "pm_d", "pm_a"]].to_numpy(),
            oos[["pk_h", "pk_d", "pk_a"]].to_numpy(),
            oos["y_res"].to_numpy(),
            oos["pm_o25"].to_numpy(),
            oos["pk_o25"].to_numpy(),
            oos["y_o25"].to_numpy(),
        )

    # ------------------------------------------------------------- predict
    def teams(self, league: str) -> list[str]:
        st = self.states.get(league)
        if st is None:
            return []
        teams = st.elo.cur_teams or st.elo.prev_teams
        return sorted(teams)

    def predict_match(
        self,
        league: str,
        home: str,
        away: str,
        date=None,
        time_str: str = "",
        market_odds: dict[str, float] | None = None,
        offered_odds: dict[str, float] | None = None,
        source: str = "",
    ) -> MatchPrediction:
        """Tek maç tahmini.

        market_odds: piyasa ortalaması oranları (1, X, 2, O2.5, U2.5) - harmanlama için.
        offered_odds: değer hesabında kullanılacak oranlar (verilmezse market_odds).
        """
        if self.states.get(league) is None:
            raise KeyError(f"{league_name(league)} için model yok.")
        return self._predict_many([{
            "league": league, "home": home, "away": away, "date": date, "time": time_str,
            "market": market_odds or {}, "offered": offered_odds, "source": source,
        }])[0]

    def _predict_many(self, items: list[dict]) -> list[MatchPrediction]:
        if not self.trained:
            raise RuntimeError("Model henüz eğitilmedi.")
        snaps, feats = [], []
        for it in items:
            date = pd.Timestamp(it["date"] if it["date"] is not None else dt.date.today()).normalize()
            it["date"] = date
            snap = self.states[it["league"]].snapshot_for(date)
            snaps.append(snap)
            feats.append(snap.features(it["home"], it["away"], day_number(date)))
        X = pd.DataFrame(feats, columns=FEATURES)
        pr = self.model.predict(X)
        blender = self.blender or MarketBlender()
        out = []
        for i, (it, snap, f) in enumerate(zip(items, snaps, feats)):
            pm = pr["res"][i]
            pm_o25 = float(pr["o25"][i])
            pm_btts = float(pr["btts"][i])
            market = it["market"] or {}
            pk = None
            o1x2 = [market.get(k) for k in ("1", "X", "2")]
            if all(o is not None and np.isfinite(o) and o > 1 for o in o1x2):
                pk = implied_probs(np.array([o1x2], dtype=float), self.margin_method)[0]
            pk_o25 = float("nan")
            oou = [market.get(k) for k in ("O2.5", "U2.5")]
            if all(o is not None and np.isfinite(o) and o > 1 for o in oou):
                pk_o25 = float(implied_probs(np.array([oou], dtype=float), self.margin_method)[0, 0])
            pf = blender.blend_res(pm[None, :], (pk if pk is not None else np.full(3, np.nan))[None, :])[0]
            pf_o25 = float(blender.blend_o25(np.array([pm_o25]), np.array([pk_o25]))[0])
            dc = snap.dc.model
            if dc is not None:
                lam, nu = dc.expected_goals(it["home"], it["away"])
                rho = dc.rho
            else:
                lam, nu, rho = snap.lg_hg, snap.lg_ag, 0.0
            m = adjust_matrix(score_matrix(lam, nu, rho), pf, pf_o25, pm_btts)
            info = dict(f)
            info.update({"dc_lambda": lam, "dc_nu": nu, "hfa": snap.elo.hfa})
            offered = it["offered"] if it["offered"] is not None else market
            out.append(MatchPrediction(
                league=it["league"], home=it["home"], away=it["away"], date=it["date"], time=it["time"] or "",
                p_model=pm, p_market=pk, p_final=pf,
                o25_model=pm_o25, o25_market=pk_o25, o25_final=pf_o25, btts_final=pm_btts,
                matrix=m, markets=markets_from_matrix(m),
                odds={k: float(v) for k, v in offered.items() if v is not None and np.isfinite(v)},
                info=info, source=it.get("source", ""),
            ))
        return out

    def predict_fixtures(self, fixtures: pd.DataFrame, odds_type: str = "avg") -> list[MatchPrediction]:
        if fixtures is None or fixtures.empty or not self.trained:
            return []
        offered_cols = ODDS_SETS.get(odds_type, ODDS_SETS["avg"])
        items = []
        for r in fixtures.itertuples(index=False):
            if r.league not in self.states:
                continue
            row = r._asdict()
            market = _odds_dict(row, ODDS_SETS["avg"])
            if not all(np.isfinite(market.get(k, np.nan)) for k in ("1", "X", "2")):
                market.update({k: v for k, v in _odds_dict(row, ODDS_SETS["b365"]).items() if k in ("1", "X", "2")})
            offered = _odds_dict(row, offered_cols)
            for k, v in market.items():  # seçilen türde oran yoksa ortalamaya düş
                if not np.isfinite(offered.get(k, np.nan)):
                    offered[k] = v
            items.append({
                "league": r.league, "home": r.home, "away": r.away, "date": r.date, "time": r.time or "",
                "market": {k: v for k, v in market.items() if np.isfinite(v)},
                "offered": {k: v for k, v in offered.items() if np.isfinite(v)},
                "source": r.source,
            })
        if not items:
            return []
        try:
            return self._predict_many(items)
        except Exception as e:  # toplu tahmin başarısızsa maç maç dene
            log.warning("Toplu tahmin hatası: %s", e)
            out = []
            for it in items:
                try:
                    out.extend(self._predict_many([it]))
                except Exception as e2:
                    log.warning("Tahmin hatası %s %s-%s: %s", it["league"], it["home"], it["away"], e2)
            return out

    # ------------------------------------------------------------- ratings
    def ratings(self, league: str) -> pd.DataFrame:
        st = self.states.get(league)
        if st is None:
            return pd.DataFrame()
        teams = self.teams(league)
        dc = st.dc.model
        rows = []
        for t in teams:
            a, d = dc.params(t) if dc is not None else (np.nan, np.nan)
            if dc is not None:
                gf = float(np.exp(dc.mu + dc.home_adv / 2 + a))
                ga = float(np.exp(dc.mu + dc.home_adv / 2 - d))
            else:
                gf = ga = np.nan
            ir = st.mr.teams.get(t) if st.mr.r is not None else None
            form = st.forms.get(t)
            last = "".join("G" if r[4] == 3 else "B" if r[4] == 1 else "M" for r in list(form.all)[-5:]) if form else ""
            rows.append({
                "team": t, "elo": st.elo.rating(t), "attack": a, "defense": d,
                "xg_for": gf, "xg_against": ga, "xg_diff": gf - ga,
                "market": float(st.mr.r[ir]) if ir is not None else np.nan,
                "form": last,
            })
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        return df.sort_values("elo", ascending=False).reset_index(drop=True)


def _odds_dict(row: dict, cols: tuple[str, ...]) -> dict[str, float]:
    keys = ("1", "X", "2", "O2.5", "U2.5")
    out = {}
    for k, c in zip(keys, cols):
        v = row.get(c)
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = float("nan")
        out[k] = v if v > 1.0 else float("nan")
    return out


MARKET_GROUPS = {
    "1X2": ("1", "X", "2"),
    "Çifte Şans": ("1X", "12", "X2"),
    "Alt/Üst": ("O1.5", "U1.5", "O2.5", "U2.5", "O3.5", "U3.5"),
    "Karşılıklı Gol": ("BTTS_Y", "BTTS_N"),
}


def verify_selection(oos: pd.DataFrame, keys: list[str], threshold: float, one_per_match: bool = True) -> dict:
    """Seçilen marketlerde olasılığı eşiğin üzerinde olan seçimlerin geçmiş (örneklem dışı) başarısı."""
    res = {"n": 0, "isabet": float("nan"), "kapsam": 0.0, "ort_olasilik": float("nan"),
           "roi": float("nan"), "roi_n": 0, "ort_oran": float("nan"), "n_mac": 0}
    if oos is None or oos.empty or not keys or PMK_COLS[0] not in oos.columns:
        return res
    idx = [MARKET_KEYS.index(k) for k in keys]
    P = oos[PMK_COLS].to_numpy(dtype=float)[:, idx]
    W = market_outcomes(oos["fthg"].to_numpy(), oos["ftag"].to_numpy())[:, idx]
    O = market_odds_matrix(oos, "avg")[:, idx]
    n_total = len(oos)
    res["n_mac"] = n_total
    if one_per_match:
        j = P.argmax(axis=1)
        r = np.arange(n_total)
        p, w, o = P[r, j], W[r, j], O[r, j]
        mask = p >= threshold
        p, w, o = p[mask], w[mask], o[mask]
        covered = int(mask.sum())
    else:
        mask = P >= threshold
        p, w, o = P[mask], W[mask], O[mask]
        covered = int(mask.any(axis=1).sum())
    if len(p) == 0:
        return res
    has_o = np.isfinite(o)
    res.update({
        "n": int(len(p)),
        "isabet": float(w.mean()),
        "kapsam": covered / n_total,
        "ort_olasilik": float(p.mean()),
        "roi": float(np.mean(np.where(w[has_o], o[has_o] - 1.0, -1.0))) if has_o.any() else float("nan"),
        "roi_n": int(has_o.sum()),
        "ort_oran": float(o[has_o].mean()) if has_o.any() else float("nan"),
    })
    return res

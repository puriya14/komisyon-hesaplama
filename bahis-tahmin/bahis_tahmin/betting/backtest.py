"""Geriye dönük test: modelin geçmiş sezonlardaki örneklem dışı tahminleriyle
bahis stratejisi simülasyonu."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ODDS_FOR_BETTING = {
    "avg": (("o_h", "o_d", "o_a"), ("o_o25", "o_u25")),
    "max": (("omax_h", "omax_d", "omax_a"), ("omax_o25", "omax_u25")),
    "b365": (("b365_h", "b365_d", "b365_a"), ("o_o25", "o_u25")),
    "pinnacle": (("ps_h", "ps_d", "ps_a"), ("o_o25", "o_u25")),
}
SEL_LABELS_1X2 = ("MS 1", "MS X", "MS 2")
SEL_LABELS_OU = ("2.5 Üst", "2.5 Alt")


@dataclass
class BacktestConfig:
    leagues: list[str] | None = None
    seasons: list[int] | None = None  # sezon başlangıç yılları (fold)
    markets: tuple[str, ...] = ("1X2", "OU25")
    odds_type: str = "avg"
    prob_source: str = "final"  # "final" (model + piyasa) veya "model"
    min_ev: float = 0.05
    min_prob: float = 0.15
    min_odds: float = 1.30
    max_odds: float = 8.0
    staking: str = "flat"  # "flat" veya "kelly"
    kelly_fraction: float = 0.25
    max_stake_pct: float = 0.05
    bankroll: float = 1000.0
    flat_stake_pct: float = 0.01


@dataclass
class BacktestResult:
    bets: pd.DataFrame
    summary: dict
    by_league: pd.DataFrame
    by_market: pd.DataFrame
    by_season: pd.DataFrame
    calibration: pd.DataFrame = field(default_factory=pd.DataFrame)


def _candidates(oos: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    """Her maç ve market için en yüksek EV'li seçimi döndürür (filtrelerden geçenler)."""
    src = "pf" if cfg.prob_source == "final" else "pm"
    cols_1x2, cols_ou = ODDS_FOR_BETTING.get(cfg.odds_type, ODDS_FOR_BETTING["avg"])
    frames = []
    base_cols = ["date", "league", "season", "fold", "home", "away", "fthg", "ftag"]
    if "1X2" in cfg.markets:
        p = oos[[f"{src}_h", f"{src}_d", f"{src}_a"]].to_numpy(dtype=float)
        o = oos[list(cols_1x2)].to_numpy(dtype=float)
        oc = oos[["oc_h", "oc_d", "oc_a"]].to_numpy(dtype=float)
        frames.append(_best(oos, base_cols, p, o, oc, oos["y_res"].to_numpy(), SEL_LABELS_1X2, "1X2", cfg))
    if "OU25" in cfg.markets:
        po = oos[f"{src}_o25"].to_numpy(dtype=float)
        p = np.column_stack([po, 1 - po])
        o = oos[list(cols_ou)].to_numpy(dtype=float)
        oc = np.full_like(o, np.nan)
        y = np.where(oos["y_o25"].to_numpy() == 1, 0, 1)
        frames.append(_best(oos, base_cols, p, o, oc, y, SEL_LABELS_OU, "Alt/Üst 2.5", cfg))
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_values(["date", "league"], kind="mergesort").reset_index(drop=True)


def _best(oos, base_cols, p, o, oc, y, labels, market, cfg) -> pd.DataFrame:
    with np.errstate(invalid="ignore"):
        ev = p * o - 1.0
    ok = (
        np.isfinite(ev)
        & (ev >= cfg.min_ev)
        & (p >= cfg.min_prob)
        & (o >= cfg.min_odds)
        & (o <= cfg.max_odds)
    )
    ev_masked = np.where(ok, ev, -np.inf)
    best = ev_masked.argmax(axis=1)
    rows = np.isfinite(ev_masked[np.arange(len(best)), best])
    if not rows.any():
        return pd.DataFrame()
    idx = np.nonzero(rows)[0]
    b = best[idx]
    df = oos.iloc[idx][base_cols].copy()
    df["market"] = market
    df["selection"] = [labels[k] for k in b]
    df["prob"] = p[idx, b]
    df["odds"] = o[idx, b]
    df["ev"] = ev[idx, b]
    df["closing"] = oc[idx, b]
    df["won"] = y[idx] == b
    return df


def run_backtest(oos: pd.DataFrame, cfg: BacktestConfig) -> BacktestResult:
    data = oos
    if cfg.leagues:
        data = data[data["league"].isin(cfg.leagues)]
    if cfg.seasons:
        data = data[data["fold"].isin(cfg.seasons)]
    bets = _candidates(data, cfg) if not data.empty else pd.DataFrame()
    if bets.empty:
        empty = pd.DataFrame()
        return BacktestResult(bets, _summary(bets, cfg), empty, empty, empty, calibration(data, cfg.prob_source))

    bank = cfg.bankroll
    stakes, profits, banks = [], [], []
    for odds, prob, won in zip(bets["odds"].to_numpy(), bets["prob"].to_numpy(), bets["won"].to_numpy()):
        if cfg.staking == "kelly":
            f = (prob * odds - 1.0) / (odds - 1.0) * cfg.kelly_fraction
            stake = max(0.0, min(f, cfg.max_stake_pct)) * bank
        else:
            stake = cfg.flat_stake_pct * cfg.bankroll
        stake = min(stake, max(bank, 0.0))
        profit = stake * (odds - 1.0) if won else -stake
        bank += profit
        stakes.append(stake)
        profits.append(profit)
        banks.append(bank)
    bets["stake"] = stakes
    bets["profit"] = profits
    bets["bankroll"] = banks
    bets["unit_profit"] = np.where(bets["won"], bets["odds"] - 1.0, -1.0)

    def agg(g: pd.DataFrame) -> pd.Series:
        staked = g["stake"].sum()
        return pd.Series({
            "bahis": len(g),
            "kazanan": int(g["won"].sum()),
            "isabet": g["won"].mean(),
            "ort_oran": g["odds"].mean(),
            "yatırılan": staked,
            "kâr": g["profit"].sum(),
            "roi": g["profit"].sum() / staked if staked > 0 else np.nan,
            "birim_roi": g["unit_profit"].mean(),
        })

    by_league = bets.groupby("league").apply(agg, include_groups=False).reset_index()
    by_market = bets.groupby(["market", "selection"]).apply(agg, include_groups=False).reset_index()
    by_season = bets.groupby("season").apply(agg, include_groups=False).reset_index()
    return BacktestResult(
        bets, _summary(bets, cfg), by_league, by_market, by_season, calibration(data, cfg.prob_source)
    )


def _summary(bets: pd.DataFrame, cfg: BacktestConfig) -> dict:
    if bets.empty:
        return {"bahis": 0, "baslangic": cfg.bankroll, "bitis": cfg.bankroll}
    staked = float(bets["stake"].sum())
    profit = float(bets["profit"].sum())
    units = bets["unit_profit"].to_numpy()
    n = len(units)
    mean = float(units.mean())
    se = float(units.std(ddof=1) / math.sqrt(n)) if n > 1 else float("nan")
    curve = np.concatenate([[cfg.bankroll], bets["bankroll"].to_numpy()])
    peak = np.maximum.accumulate(curve)
    dd = float(np.max((peak - curve) / np.where(peak > 0, peak, 1)))
    streak = longest = 0
    for w in bets["won"].to_numpy():
        streak = 0 if w else streak + 1
        longest = max(longest, streak)
    clv = bets["odds"] / bets["closing"] - 1.0
    clv = clv[np.isfinite(clv)]
    # Tek taraflı z testi: birim ROI > 0 mı?
    z = mean / se if se and se > 0 else float("nan")
    p_value = 0.5 * math.erfc(z / math.sqrt(2)) if np.isfinite(z) else float("nan")
    return {
        "bahis": n,
        "kazanan": int(bets["won"].sum()),
        "isabet": float(bets["won"].mean()),
        "ort_oran": float(bets["odds"].mean()),
        "ort_ev": float(bets["ev"].mean()),
        "yatirilan": staked,
        "kar": profit,
        "roi": profit / staked if staked > 0 else float("nan"),
        "birim_roi": mean,
        "roi_ci_low": mean - 1.96 * se if np.isfinite(se) else float("nan"),
        "roi_ci_high": mean + 1.96 * se if np.isfinite(se) else float("nan"),
        "p_value": p_value,
        "max_dusus": dd,
        "en_uzun_kayip": longest,
        "baslangic": cfg.bankroll,
        "bitis": float(curve[-1]),
        "clv": float(clv.mean()) if len(clv) else float("nan"),
        "clv_n": int(len(clv)),
    }


def calibration(oos: pd.DataFrame, prob_source: str = "final", bins: int = 10) -> pd.DataFrame:
    """Tahmin edilen olasılık ile gerçekleşen sıklığın karşılaştırması (1X2, tüm sonuçlar)."""
    if oos is None or oos.empty:
        return pd.DataFrame()
    src = "pf" if prob_source == "final" else "pm"
    p = oos[[f"{src}_h", f"{src}_d", f"{src}_a"]].to_numpy(dtype=float).ravel()
    y = np.zeros((len(oos), 3))
    y[np.arange(len(oos)), oos["y_res"].to_numpy()] = 1
    y = y.ravel()
    ok = np.isfinite(p)
    p, y = p[ok], y[ok]
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        if m.sum() < 20:
            continue
        rows.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "tahmin": p[m].mean(), "gercek": y[m].mean(), "n": int(m.sum())})
    return pd.DataFrame(rows)

"""Sızıntısız (walk-forward) özellik üretimi.

Her maç için özellikler yalnızca o maçtan ÖNCE oynanmış maçlar kullanılarak
hesaplanır; böylece geçmiş üzerinde yapılan testler gerçekçi olur.
"""

from __future__ import annotations

import copy
from collections import deque
from typing import Callable

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ..betting.odds import implied_probs
from ..data.leagues import LEAGUES, season_for_date
from .dixon_coles import DCConfig, DCTracker, MarketRatingTracker
from .elo import EloConfig, EloTracker
from .markets import MASK_A, MASK_BTTS, MASK_D, MASK_H, MASK_O25, score_matrix

EPOCH = pd.Timestamp("2000-01-01")
REFIT_DAYS = 7

FEATURES = [
    "elo_h", "elo_a", "elo_diff", "elo_p",
    "dc_lh", "dc_la", "dc_ph", "dc_pd", "dc_pa", "dc_o25", "dc_btts",
    "sot_lh", "sot_la", "mr_z", "mr_t", "mr_z2", "mr_t2",
    "h_ppg6", "h_gf6", "h_ga6", "h_sotf6", "h_sota6",
    "a_ppg6", "a_gf6", "a_ga6", "a_sotf6", "a_sota6",
    "h_home_ppg5", "h_home_gd5", "a_away_ppg5", "a_away_gd5",
    "h_rest", "a_rest", "h_nseason", "a_nseason", "h_new", "a_new",
    "lg_hg", "lg_ag", "lg_draw",
]
# Modele girmeyen ama skor matrisi için saklanan ek sütunlar
EXTRA_COLUMNS = ["dc_rho"]


def day_number(ts) -> int:
    return int((pd.Timestamp(ts) - EPOCH).days)


# Alt/Üst 2.5 olasılığından beklenen toplam gole dönüşüm tablosu (Poisson varsayımı)
_T_GRID = np.linspace(0.2, 8.0, 4000)
_P_OVER_GRID = 1.0 - np.exp(-_T_GRID) * (1.0 + _T_GRID + _T_GRID ** 2 / 2.0)


def market_targets(odds_1x2: np.ndarray, odds_ou: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Oranlardan piyasa reytingi hedefleri: z = log(P1/P2), t = log(beklenen toplam gol)."""
    p = implied_probs(odds_1x2, "power")
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.log(p[:, 0] / p[:, 2])
    po = implied_probs(odds_ou, "power")[:, 0]
    t = np.full(len(po), np.nan)
    ok = np.isfinite(po)
    t[ok] = np.log(np.interp(po[ok], _P_OVER_GRID, _T_GRID))
    return z, t


def _nanmean(vals) -> float:
    vals = [v for v in vals if v == v]  # NaN filtrele
    return float(sum(vals) / len(vals)) if vals else float("nan")


class TeamForm:
    __slots__ = ("all", "home", "away", "last_day", "season", "n_season")

    def __init__(self):
        self.all: deque = deque(maxlen=6)
        self.home: deque = deque(maxlen=5)
        self.away: deque = deque(maxlen=5)
        self.last_day: int | None = None
        self.season: str | None = None
        self.n_season = 0


class LeagueState:
    """Bir ligin o ana kadarki durumu: Elo, Dixon-Coles, form ve lig ortalamaları."""

    def __init__(self, league: str, dc_cfg: DCConfig | None = None, elo_cfg: EloConfig | None = None):
        self.league = league
        self.calendar_year = LEAGUES[league].calendar_year if league in LEAGUES else False
        self.elo = EloTracker(elo_cfg)
        self.dc = DCTracker(dc_cfg)
        self.sot = DCTracker(DCConfig(xi=0.0025, ridge=2.0, promoted_attack=-0.1, promoted_defense=-0.1), fit_rho=False)
        self.mr = MarketRatingTracker()  # hızlı: son haftaların oranları (yarı ömür ≈ 35 gün)
        self.mr_slow = MarketRatingTracker(xi=0.004, ridge=1.0, window_days=730)  # yavaş: uzun dönem gücü
        self.forms: dict[str, TeamForm] = {}
        self.lg_hg = 1.50
        self.lg_ag = 1.15
        self.lg_draw = 0.26
        self.last_day: int | None = None
        self.season: str | None = None
        self._alpha = 0.005

    # -------------------------------------------------------------- helpers
    def _form(self, team: str) -> TeamForm:
        f = self.forms.get(team)
        if f is None:
            f = TeamForm()
            self.forms[team] = f
        return f

    def new_teams(self) -> set[str]:
        return {t for t in self.elo.cur_teams if self.elo.is_new(t)}

    def start_season(self, season: str) -> None:
        if season != self.season:
            self.elo.start_season(season)
            self.season = season

    def refit_if_needed(self, day: int, force: bool = False) -> None:
        if force or self.dc.fit_day is None or day - self.dc.fit_day >= REFIT_DAYS:
            new = self.new_teams()
            self.dc.fit(day, new)
            self.sot.fit(day, new)
            self.mr.fit(day, new)
            self.mr_slow.fit(day, new)

    # ------------------------------------------------------------- features
    def features(self, home: str, away: str, day: int) -> dict:
        f: dict[str, float] = {}
        eh, ea = self.elo.rating(home), self.elo.rating(away)
        f["elo_h"], f["elo_a"] = eh, ea
        f["elo_diff"] = eh + self.elo.hfa - ea
        f["elo_p"] = 1.0 / (1.0 + 10.0 ** (-f["elo_diff"] / 400.0))
        model = self.dc.model
        if model is not None:
            lam, nu = model.expected_goals(home, away)
            m = score_matrix(lam, nu, model.rho)
            f["dc_lh"], f["dc_la"] = lam, nu
            f["dc_ph"] = float(m[MASK_H].sum())
            f["dc_pd"] = float(m[MASK_D].sum())
            f["dc_pa"] = float(m[MASK_A].sum())
            f["dc_o25"] = float(m[MASK_O25].sum())
            f["dc_btts"] = float(m[MASK_BTTS].sum())
            f["dc_rho"] = model.rho
        else:
            for k in ("dc_lh", "dc_la", "dc_ph", "dc_pd", "dc_pa", "dc_o25", "dc_btts", "dc_rho"):
                f[k] = float("nan")
        if self.sot.model is not None:
            f["sot_lh"], f["sot_la"] = self.sot.model.expected_goals(home, away)
        else:
            f["sot_lh"] = f["sot_la"] = float("nan")
        f["mr_z"], f["mr_t"] = self.mr.predict(home, away)
        f["mr_z2"], f["mr_t2"] = self.mr_slow.predict(home, away)
        for side, team in (("h", home), ("a", away)):
            tf = self.forms.get(team)
            if tf is None or not tf.all:
                for k in ("ppg6", "gf6", "ga6", "sotf6", "sota6"):
                    f[f"{side}_{k}"] = float("nan")
                f[f"{side}_rest"] = float("nan")
                f[f"{side}_nseason"] = 0.0
            else:
                rows = tf.all
                n = len(rows)
                f[f"{side}_ppg6"] = sum(r[4] for r in rows) / n
                f[f"{side}_gf6"] = sum(r[2] for r in rows) / n
                f[f"{side}_ga6"] = sum(r[3] for r in rows) / n
                f[f"{side}_sotf6"] = _nanmean([r[5] for r in rows])
                f[f"{side}_sota6"] = _nanmean([r[6] for r in rows])
                f[f"{side}_rest"] = float(min(day - tf.last_day, 30)) if tf.last_day is not None else float("nan")
                f[f"{side}_nseason"] = float(min(tf.n_season, 38)) if tf.season == self.season else 0.0
            f[f"{side}_new"] = 1.0 if self.elo.is_new(team) else 0.0
        th = self.forms.get(home)
        ta = self.forms.get(away)
        if th is not None and th.home:
            f["h_home_ppg5"] = sum(r[4] for r in th.home) / len(th.home)
            f["h_home_gd5"] = sum(r[2] - r[3] for r in th.home) / len(th.home)
        else:
            f["h_home_ppg5"] = f["h_home_gd5"] = float("nan")
        if ta is not None and ta.away:
            f["a_away_ppg5"] = sum(r[4] for r in ta.away) / len(ta.away)
            f["a_away_gd5"] = sum(r[2] - r[3] for r in ta.away) / len(ta.away)
        else:
            f["a_away_ppg5"] = f["a_away_gd5"] = float("nan")
        f["lg_hg"], f["lg_ag"], f["lg_draw"] = self.lg_hg, self.lg_ag, self.lg_draw
        return f

    # --------------------------------------------------------------- update
    def update(
        self, day: int, home: str, away: str, hg: int, ag: int, stats: tuple, market: tuple = (np.nan, np.nan)
    ) -> None:
        h_sot, a_sot = stats
        self.elo.update(home, away, hg, ag)
        self.dc.add(day, home, away, hg, ag)
        if h_sot == h_sot and a_sot == a_sot:
            self.sot.add(day, home, away, int(h_sot), int(a_sot))
        self.mr.add(day, home, away, market[0], market[1])
        self.mr_slow.add(day, home, away, market[0], market[1])
        ph = 3 if hg > ag else 1 if hg == ag else 0
        pa = 3 if ag > hg else 1 if hg == ag else 0
        for team, gf, ga, pts, sf, sa, is_home in (
            (home, hg, ag, ph, h_sot, a_sot, True),
            (away, ag, hg, pa, a_sot, h_sot, False),
        ):
            tf = self._form(team)
            rec = (day, is_home, gf, ga, pts, sf, sa)
            tf.all.append(rec)
            (tf.home if is_home else tf.away).append(rec)
            tf.last_day = day
            if tf.season != self.season:
                tf.season = self.season
                tf.n_season = 0
            tf.n_season += 1
        a = self._alpha
        self.lg_hg = (1 - a) * self.lg_hg + a * hg
        self.lg_ag = (1 - a) * self.lg_ag + a * ag
        self.lg_draw = (1 - a) * self.lg_draw + a * (1.0 if hg == ag else 0.0)
        self.last_day = day

    # ------------------------------------------------------------ prediction
    def snapshot_for(self, date) -> "LeagueState":
        """Gelecekteki bir tarih için (gerekirse yeni sezonu başlatarak) durum kopyası."""
        season = season_for_date(pd.Timestamp(date).date(), self.calendar_year)
        if season == self.season:
            return self
        st = copy.copy(self)
        st.elo = copy.deepcopy(self.elo)
        st.start_season(season)
        return st


def build_features(
    matches: pd.DataFrame,
    dc_cfg: DCConfig | None = None,
    elo_cfg: EloConfig | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> tuple[pd.DataFrame, dict[str, LeagueState]]:
    """Tüm maçlar için walk-forward özellikler ve liglerin son durumları."""
    # Binlerce küçük matris işleminde çok iş parçacıklı BLAS çok yavaşlatır (≈10 kat)
    with threadpool_limits(limits=1, user_api="blas"):
        return _build_features(matches, dc_cfg, elo_cfg, progress)


def _build_features(matches, dc_cfg, elo_cfg, progress):
    progress = progress or (lambda p, m: None)
    out_frames = []
    states: dict[str, LeagueState] = {}
    leagues = list(dict.fromkeys(matches["league"]))
    for li, lg in enumerate(leagues):
        progress(li / max(len(leagues), 1), lg)
        df = matches[matches["league"] == lg].sort_values("date", kind="mergesort")
        st = LeagueState(lg, dc_cfg, elo_cfg)
        days = ((df["date"] - EPOCH).dt.days).to_numpy()
        seasons = df["season"].astype(str).to_numpy()
        homes = df["home"].to_numpy()
        aways = df["away"].to_numpy()
        hgs = df["fthg"].to_numpy(dtype=int)
        ags = df["ftag"].to_numpy(dtype=int)
        hsot = df["h_sot"].to_numpy(dtype=float)
        asot = df["a_sot"].to_numpy(dtype=float)
        mz, mt = market_targets(
            df[["o_h", "o_d", "o_a"]].to_numpy(dtype=float), df[["o_o25", "o_u25"]].to_numpy(dtype=float)
        )
        feats = []
        n = len(df)
        i = 0
        while i < n:
            j = i
            while j < n and days[j] == days[i]:
                j += 1
            day = int(days[i])
            st.start_season(seasons[i])
            st.refit_if_needed(day)
            for k in range(i, j):
                feats.append(st.features(homes[k], aways[k], day))
            for k in range(i, j):
                if seasons[k] != st.season:
                    st.start_season(seasons[k])
                st.update(
                    day, homes[k], aways[k], int(hgs[k]), int(ags[k]), (hsot[k], asot[k]), (mz[k], mt[k])
                )
            i = j
        if st.last_day is not None:
            st.refit_if_needed(st.last_day + 1, force=True)
        states[lg] = st
        fdf = pd.DataFrame(feats, index=df.index, columns=FEATURES + EXTRA_COLUMNS)
        out_frames.append(pd.concat([df, fdf], axis=1))
    progress(1.0, "")
    if not out_frames:
        return pd.DataFrame(), states
    feat = pd.concat(out_frames).sort_values(["date", "league"], kind="mergesort")
    feat["y_res"] = np.where(feat["fthg"] > feat["ftag"], 0, np.where(feat["fthg"] == feat["ftag"], 1, 2))
    feat["y_o25"] = ((feat["fthg"] + feat["ftag"]) >= 3).astype(int)
    feat["y_btts"] = ((feat["fthg"] >= 1) & (feat["ftag"] >= 1)).astype(int)
    return feat, states

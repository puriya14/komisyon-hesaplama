"""Gol pazarları için zaman güvenli (walk-forward) özellik hattı.

Her maçın özellikleri, karar zamanı = maç günü 00:00 (yalnızca tarih bilinir) kabul edilerek,
yalnızca DAHA ÖNCEKİ günlerde tamamlanmış maçlardan üretilir. Aynı gün oynanan maçların saatleri
güvenilir olmadığından, o günün hiçbir sonucu aynı günün başka bir maçına sızdırılmaz.

Takım güçleri üç ayrı zaman ağırlıklı Poisson modeliyle tutulur:
  * İlk yarı golleri (H1), ikinci yarı golleri (H2) ve maç sonu golleri (FT).
Ayrıca lig ortamı (zamanla azalan taban oranlar), takımların yakın dönem yarı bazlı gol
sıklıkları ve karşılıklı maç (H2H) geçmişi üretilir (son ikisi yalnızca karşılaştırma modeli için).
"""

from __future__ import annotations

import copy
import warnings
from collections import deque
from typing import Callable

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ..data.leagues import LEAGUES, season_for_date
from ..models.dixon_coles import DCConfig, DCTracker
from ..models.elo import EloTracker
from .markets import PRIMARY_YES, label_frame

EPOCH = pd.Timestamp("2000-01-01")
REFIT_DAYS = 7
HALF_CFG = DCConfig(xi=0.0019, ridge=3.0, promoted_attack=-0.1, promoted_defense=-0.1, min_matches=60)
BASE_XI = 0.001  # lig taban oranları için günlük sönüm (yarı ömür ≈ 1.9 yıl)
FORM_N = 10

MODEL_COLUMNS = [
    "l1h", "l1a", "rho1", "l2h", "l2a", "lh", "la", "rho",
    "se1h", "se1a", "se2h", "se2a", "seh", "sea",
]
BASE_COLUMNS = ["bA", "bB", "bC", "s1"]
FORM_COLUMNS = [
    "h_sc1", "h_cc1", "h_sc2", "h_cc2", "h_both", "h_o35", "h_cs",
    "a_sc1", "a_cc1", "a_sc2", "a_cc2", "a_both", "a_o35", "a_cs",
    "h_rest", "a_rest", "h_n365", "a_n365", "season_n",
]
H2H_COLUMNS = ["h2h_n", "h2h_B", "h2h_C"]
GOAL_FEATURES = MODEL_COLUMNS + BASE_COLUMNS + FORM_COLUMNS + H2H_COLUMNS


class _Decayed:
    """Zamanla azalan ağırlıklı ortalama (yalnızca geçmiş gözlemlerle)."""

    __slots__ = ("num", "den", "day", "xi")

    def __init__(self, xi: float, prior: float = 0.5, prior_n: float = 2.0):
        self.num = prior * prior_n
        self.den = prior_n
        self.day = None
        self.xi = xi

    def add(self, day: int, value: float, weight: float = 1.0) -> None:
        if self.day is not None and day > self.day:
            f = np.exp(-self.xi * (day - self.day))
            self.num *= f
            self.den *= f
        self.day = day if self.day is None else max(self.day, day)
        self.num += weight * value
        self.den += weight

    @property
    def value(self) -> float:
        return self.num / self.den if self.den > 0 else float("nan")


class GoalLeagueState:
    def __init__(self, league: str):
        self.league = league
        self.calendar_year = LEAGUES[league].calendar_year if league in LEAGUES else False
        self.h1 = DCTracker(HALF_CFG, fit_rho=True, keep_cov=True)
        self.h2 = DCTracker(HALF_CFG, fit_rho=False, keep_cov=True)
        self.ft = DCTracker(DCConfig(), fit_rho=True, keep_cov=True)
        self.elo = EloTracker()  # yalnızca sezon / yükselen takım takibi için
        self.base = {k: _Decayed(BASE_XI) for k in PRIMARY_YES}
        self.share1 = _Decayed(BASE_XI, prior=0.44, prior_n=2.0)
        self.forms: dict[str, deque] = {}
        self.dates: dict[str, deque] = {}
        self.last_day: dict[str, int] = {}
        self.h2h: dict[tuple, deque] = {}
        self.season: str | None = None
        self.season_n = 0
        self.last_match_day: int | None = None

    def start_season(self, season: str) -> None:
        if season != self.season:
            self.elo.start_season(season)
            self.season = season
            self.season_n = 0

    def new_teams(self) -> set[str]:
        return {t for t in self.elo.cur_teams if self.elo.is_new(t)}

    def refit_if_needed(self, day: int, force: bool = False) -> None:
        if force or self.h1.fit_day is None or day - self.h1.fit_day >= REFIT_DAYS:
            new = self.new_teams()
            self.h1.fit(day, new)
            self.h2.fit(day, new)
            self.ft.fit(day, new)

    # -------------------------------------------------------------- özellikler
    def features(self, home: str, away: str, day: int) -> dict:
        f: dict[str, float] = {}
        nan = float("nan")
        m1, m2, mf = self.h1.model, self.h2.model, self.ft.model
        if m1 is not None and m2 is not None:
            f["l1h"], f["l1a"] = m1.expected_goals(home, away)
            f["rho1"] = m1.rho
            f["l2h"], f["l2a"] = m2.expected_goals(home, away)
            f["se1h"], f["se1a"] = m1.log_rate_se(home, away)
            f["se2h"], f["se2a"] = m2.log_rate_se(home, away)
        else:
            for k in ("l1h", "l1a", "rho1", "l2h", "l2a", "se1h", "se1a", "se2h", "se2a"):
                f[k] = nan
        if mf is not None:
            f["lh"], f["la"] = mf.expected_goals(home, away)
            f["rho"] = mf.rho
            f["seh"], f["sea"] = mf.log_rate_se(home, away)
        else:
            f["lh"] = f["la"] = f["rho"] = f["seh"] = f["sea"] = nan
        f["bA"], f["bB"], f["bC"] = (self.base[k].value for k in PRIMARY_YES)
        f["s1"] = self.share1.value
        for side, team in (("h", home), ("a", away)):
            rows = self.forms.get(team)
            if rows:
                arr = np.array(rows, dtype=float)
                m = np.nanmean(arr, axis=0) if np.isfinite(arr).any() else np.full(arr.shape[1], np.nan)
                for k, v in zip(("sc1", "cc1", "sc2", "cc2", "both", "o35", "cs"), m):
                    f[f"{side}_{k}"] = float(v)
            else:
                for k in ("sc1", "cc1", "sc2", "cc2", "both", "o35", "cs"):
                    f[f"{side}_{k}"] = nan
            last = self.last_day.get(team)
            f[f"{side}_rest"] = float(min(day - last, 30)) if last is not None else nan
            dq = self.dates.get(team)
            f[f"{side}_n365"] = float(sum(1 for d in dq if d >= day - 365)) if dq else 0.0
        f["season_n"] = float(self.season_n)
        key = tuple(sorted((home, away)))
        hist = self.h2h.get(key)
        if hist:
            arr = np.array(hist, dtype=float)
            f["h2h_n"] = float(len(arr))
            f["h2h_B"] = float(np.nanmean(arr[:, 0])) if np.isfinite(arr[:, 0]).any() else nan
            f["h2h_C"] = float(np.nanmean(arr[:, 1])) if np.isfinite(arr[:, 1]).any() else nan
        else:
            f["h2h_n"] = 0.0
            f["h2h_B"] = f["h2h_C"] = nan
        return f

    # ------------------------------------------------------------- güncelleme
    def update(self, day: int, home: str, away: str, fthg: int, ftag: int, hthg, htag, labels: tuple) -> None:
        """Maç sonucu öğrenildikten SONRA çağrılır. hthg/htag NaN olabilir (ilk yarı yok)."""
        self.elo.update(home, away, fthg, ftag)
        self.ft.add(day, home, away, fthg, ftag)
        ht_ok = hthg == hthg and htag == htag
        if ht_ok:
            hthg, htag = int(hthg), int(htag)
            self.h1.add(day, home, away, hthg, htag)
            self.h2.add(day, home, away, fthg - hthg, ftag - htag)
            tot = fthg + ftag
            if tot > 0:
                self.share1.add(day, (hthg + htag) / tot, weight=tot)
        for key, lab in zip(PRIMARY_YES, labels):
            if lab == lab:
                self.base[key].add(day, lab)
        o35 = 1.0 if fthg + ftag >= 4 else 0.0
        for team, gf, ga, h1f, h1a in ((home, fthg, ftag, hthg, htag), (away, ftag, fthg, htag, hthg)):
            if ht_ok:
                sc1, cc1 = float(h1f >= 1), float(h1a >= 1)
                sc2, cc2 = float(gf - h1f >= 1), float(ga - h1a >= 1)
                both = float(sc1 and sc2)
            else:
                sc1 = cc1 = sc2 = cc2 = both = float("nan")
            rec = (sc1, cc1, sc2, cc2, both, o35, float(ga == 0))
            self.forms.setdefault(team, deque(maxlen=FORM_N)).append(rec)
            self.dates.setdefault(team, deque(maxlen=60)).append(day)
            self.last_day[team] = day
        key = tuple(sorted((home, away)))
        c = float(hthg + htag >= 2) if ht_ok else float("nan")
        self.h2h.setdefault(key, deque(maxlen=6)).append((o35, c))
        self.season_n += 1
        self.last_match_day = day

    def snapshot_for(self, date) -> "GoalLeagueState":
        season = season_for_date(pd.Timestamp(date).date(), self.calendar_year)
        if season == self.season:
            return self
        st = copy.copy(self)
        st.elo = copy.deepcopy(self.elo)
        st.start_season(season)
        return st


def build_goal_features(
    matches: pd.DataFrame, progress: Callable[[float, str], None] | None = None
) -> tuple[pd.DataFrame, dict[str, GoalLeagueState]]:
    with threadpool_limits(limits=1, user_api="blas"):
        return _build(matches, progress)


def _build(matches, progress):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # tamamen boş form pencerelerinde nanmean uyarısı
        return _build_inner(matches, progress)


def _build_inner(matches, progress):
    progress = progress or (lambda p, m: None)
    labs = label_frame(matches, PRIMARY_YES)
    frames, states = [], {}
    leagues = list(dict.fromkeys(matches["league"]))
    for li, lg in enumerate(leagues):
        progress(li / max(len(leagues), 1), lg)
        idx = matches.index[matches["league"] == lg]
        df = matches.loc[idx].sort_values("date", kind="mergesort")
        lab = labs.loc[df.index]
        clean = (lab["issues"] == "").to_numpy()
        st = GoalLeagueState(lg)
        days = ((df["date"] - EPOCH).dt.days).to_numpy()
        seasons = df["season"].astype(str).to_numpy()
        homes, aways = df["home"].to_numpy(), df["away"].to_numpy()
        fh, fa = df["fthg"].to_numpy(dtype=float), df["ftag"].to_numpy(dtype=float)
        hh, ha = df["hthg"].to_numpy(dtype=float), df["htag"].to_numpy(dtype=float)
        lv = lab[list(PRIMARY_YES)].to_numpy(dtype=float)
        feats = []
        n, i = len(df), 0
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
                if not clean[k] or fh[k] != fh[k] or fa[k] != fa[k]:
                    continue  # karantinadaki kayıt modele girmez
                st.update(day, homes[k], aways[k], int(fh[k]), int(fa[k]), hh[k], ha[k], tuple(lv[k]))
            i = j
        if st.last_match_day is not None:
            st.refit_if_needed(st.last_match_day + 1, force=True)
        states[lg] = st
        fdf = pd.DataFrame(feats, index=df.index, columns=GOAL_FEATURES)
        out = pd.concat([df[["league", "season", "date", "home", "away", "fthg", "ftag", "hthg", "htag"]], fdf, lab], axis=1)
        frames.append(out)
    progress(1.0, "")
    if not frames:
        return pd.DataFrame(), states
    return pd.concat(frames).sort_values(["date", "league"], kind="mergesort"), states

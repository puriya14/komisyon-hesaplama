"""Lig bazlı Elo güç puanları (gol farkı çarpanı ve uyarlanır ev sahibi avantajı ile)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class EloConfig:
    k: float = 30.0
    home_adv: float = 60.0
    hfa_lr: float = 1.0
    init: float = 1500.0
    season_regress: float = 0.15
    promoted_quantile: float = 0.2


def mov_multiplier(goal_diff: int) -> float:
    gd = abs(goal_diff)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11.0 + gd) / 8.0


class EloTracker:
    def __init__(self, cfg: EloConfig | None = None):
        self.cfg = cfg or EloConfig()
        self.ratings: dict[str, float] = {}
        self.hfa = self.cfg.home_adv
        self.season: str | None = None
        self.prev_teams: set[str] = set()
        self.cur_teams: set[str] = set()
        self.promoted_rating: float | None = None
        self.n_seasons = 0

    def start_season(self, season: str) -> None:
        if season == self.season:
            return
        if self.season is not None and self.cur_teams:
            vals = np.array([self.ratings[t] for t in self.cur_teams if t in self.ratings])
            mean = float(vals.mean())
            for t in self.cur_teams:
                self.ratings[t] = mean + (1.0 - self.cfg.season_regress) * (self.ratings[t] - mean)
            vals = np.array([self.ratings[t] for t in self.cur_teams])
            self.promoted_rating = float(np.quantile(vals, self.cfg.promoted_quantile))
            self.prev_teams = set(self.cur_teams)
        self.season = season
        self.cur_teams = set()
        self.n_seasons += 1

    def is_new(self, team: str) -> bool:
        """Takım bu sezon lige yeni mi katıldı (geçen sezon bu ligde yoktu)."""
        return bool(self.prev_teams) and team not in self.prev_teams

    def rating(self, team: str) -> float:
        if team in self.cur_teams or (team in self.ratings and not self.is_new(team)):
            return self.ratings[team]
        if self.is_new(team) and self.promoted_rating is not None:
            return self.promoted_rating
        return self.ratings.get(team, self.cfg.init)

    def expected(self, home: str, away: str) -> float:
        d = self.rating(home) + self.hfa - self.rating(away)
        return 1.0 / (1.0 + 10.0 ** (-d / 400.0))

    def update(self, home: str, away: str, hg: int, ag: int) -> None:
        for t in (home, away):
            if t not in self.cur_teams:
                self.ratings[t] = self.rating(t)
                self.cur_teams.add(t)
        exp_h = self.expected(home, away)
        score = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
        delta = self.cfg.k * mov_multiplier(hg - ag) * (score - exp_h)
        self.ratings[home] += delta
        self.ratings[away] -= delta
        self.hfa = float(np.clip(self.hfa + self.cfg.hfa_lr * (score - exp_h), 0.0, 150.0))

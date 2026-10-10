"""Zaman ağırlıklı Dixon-Coles gol modeli.

Ev sahibi gol beklentisi:  λ = exp(μ + ev_avantajı + hücum_ev − savunma_deplasman)
Deplasman gol beklentisi:  ν = exp(μ + hücum_dep − savunma_ev)

Parametreler ağırlıklı Poisson olabilirlik + L2 (ridge) cezası ile Newton
yöntemiyle bulunur; düşük skorlar için Dixon-Coles ρ düzeltmesi ayrıca tahmin edilir.
Eski maçların ağırlığı exp(−ξ·gün) ile azalır.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import poisson


@dataclass
class DCConfig:
    xi: float = 0.0019  # günlük zaman sönümü (yarı ömür ≈ 1 yıl)
    ridge: float = 2.0  # takım parametreleri için L2 cezası
    window_days: int = 1100
    promoted_attack: float = -0.15
    promoted_defense: float = -0.15
    max_goals: int = 10
    max_iter: int = 25
    tol: float = 1e-6
    min_matches: int = 60


@dataclass
class DCModel:
    teams: list[str]
    attack: np.ndarray
    defense: np.ndarray
    mu: float
    home_adv: float
    rho: float
    new_attack: float = -0.15
    new_defense: float = -0.15
    index: dict[str, int] = field(default_factory=dict)
    cov: np.ndarray | None = None  # parametre kovaryansı (ters Hessian), istenirse
    ridge: float = 2.0

    def __post_init__(self):
        if not self.index:
            self.index = {t: i for i, t in enumerate(self.teams)}

    def params(self, team: str) -> tuple[float, float]:
        """(hücum, savunma); modelde olmayan takım ligde yeni (ör. yükselen) kabul edilir."""
        i = self.index.get(team)
        if i is None:
            return self.new_attack, self.new_defense
        return float(self.attack[i]), float(self.defense[i])

    def log_rate_se(self, home: str, away: str) -> tuple[float, float]:
        """log(λ) ve log(ν) tahminlerinin standart hatası (parametre belirsizliği, delta yöntemi).

        Modelde olmayan takımın parametreleri için ön dağılım varyansı (1/ridge) eklenir.
        """
        if self.cov is None:
            return float("nan"), float("nan")
        n = len(self.teams)
        out = []
        for att, dfn, home_row in ((home, away, True), (away, home, False)):
            x = np.zeros(2 * n + 2)
            extra = 0.0
            x[0] = 1.0
            if home_row:
                x[1] = 1.0
            ia, idf = self.index.get(att), self.index.get(dfn)
            if ia is None:
                extra += 1.0 / self.ridge
            else:
                x[2 + ia] = 1.0
            if idf is None:
                extra += 1.0 / self.ridge
            else:
                x[2 + n + idf] = -1.0
            out.append(float(np.sqrt(max(x @ self.cov @ x + extra, 0.0))))
        return out[0], out[1]

    def expected_goals(self, home: str, away: str) -> tuple[float, float]:
        ah, dh = self.params(home)
        aa, da = self.params(away)
        lam = np.exp(self.mu + self.home_adv + ah - da)
        nu = np.exp(self.mu + aa - dh)
        return float(lam), float(nu)

    def score_matrix(self, home: str, away: str, max_goals: int = 10) -> np.ndarray:
        lam, nu = self.expected_goals(home, away)
        return score_matrix(lam, nu, self.rho, max_goals)


def tau(x, y, lam, nu, rho):
    """Dixon-Coles düşük skor düzeltme çarpanı (vektörel)."""
    t = np.ones(np.broadcast(x, y, lam, nu).shape)
    t = np.where((x == 0) & (y == 0), 1.0 - lam * nu * rho, t)
    t = np.where((x == 0) & (y == 1), 1.0 + lam * rho, t)
    t = np.where((x == 1) & (y == 0), 1.0 + nu * rho, t)
    t = np.where((x == 1) & (y == 1), 1.0 - rho, t)
    return t


def score_matrix(lam: float, nu: float, rho: float = 0.0, max_goals: int = 10) -> np.ndarray:
    """P(ev = i, deplasman = j) matrisi (satır: ev golü, sütun: deplasman golü)."""
    g = np.arange(max_goals + 1)
    m = np.outer(poisson.pmf(g, lam), poisson.pmf(g, nu))
    m[0, 0] *= max(1.0 - lam * nu * rho, 1e-9)
    m[0, 1] *= max(1.0 + lam * rho, 1e-9)
    m[1, 0] *= max(1.0 + nu * rho, 1e-9)
    m[1, 1] *= max(1.0 - rho, 1e-9)
    return m / m.sum()


def fit_dixon_coles(
    home_idx: np.ndarray,
    away_idx: np.ndarray,
    hg: np.ndarray,
    ag: np.ndarray,
    weights: np.ndarray,
    n_teams: int,
    prior_attack: np.ndarray,
    prior_defense: np.ndarray,
    cfg: DCConfig,
    init: np.ndarray | None = None,
    fit_rho: bool = True,
    return_cov: bool = False,
):
    """θ = [μ, ev_avantajı, hücum(n), savunma(n)] ve ρ döndürür."""
    n = n_teams
    p = 2 * n + 2
    m = len(hg)
    # Tasarım matrisi: önce ev golleri, sonra deplasman golleri satırları
    X = np.zeros((2 * m, p))
    r = np.arange(m)
    X[r, 0] = 1.0
    X[r, 1] = 1.0
    X[r, 2 + home_idx] = 1.0
    X[r, 2 + n + away_idx] -= 1.0
    X[m + r, 0] = 1.0
    X[m + r, 2 + away_idx] = 1.0
    X[m + r, 2 + n + home_idx] -= 1.0
    y = np.concatenate([hg, ag]).astype(float)
    w = np.concatenate([weights, weights]).astype(float)

    pen = np.zeros(p)
    pen[2:] = cfg.ridge
    prior = np.zeros(p)
    prior[2:2 + n] = prior_attack
    prior[2 + n:] = prior_defense

    if init is None or len(init) != p:
        theta = prior.copy()
        mean_goals = max(np.average(y, weights=w), 0.1)
        theta[0] = np.log(mean_goals)
        theta[1] = 0.25
    else:
        theta = init.astype(float).copy()

    def loglik(th):
        eta = X @ th
        return float(np.sum(w * (y * eta - np.exp(eta))) - 0.5 * np.sum(pen * (th - prior) ** 2))

    ll = loglik(theta)
    for _ in range(cfg.max_iter):
        eta = X @ theta
        rate = np.exp(eta)
        grad = X.T @ (w * (y - rate)) - pen * (theta - prior)
        H = (X * (w * rate)[:, None]).T @ X
        H[np.diag_indices(p)] += pen
        try:
            step = np.linalg.solve(H, grad)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(H, grad, rcond=None)[0]
        t = 1.0
        while True:
            cand = theta + t * step
            ll_new = loglik(cand)
            if ll_new >= ll - 1e-10 or t < 1e-4:
                break
            t *= 0.5
        theta, ll_old, ll = cand, ll, ll_new
        if np.max(np.abs(t * step)) < cfg.tol or abs(ll - ll_old) < cfg.tol:
            break

    rho = 0.0
    if fit_rho:
        eta = X @ theta
        lam_all = np.exp(eta[:m])
        nu_all = np.exp(eta[m:])
        low = (hg <= 1) & (ag <= 1)
        if low.any():
            x, yy = hg[low], ag[low]
            lam, nu, ww = lam_all[low], nu_all[low], weights[low]

            def neg(rh):
                t_ = tau(x, yy, lam, nu, rh)
                return -float(np.sum(ww * np.log(np.clip(t_, 1e-9, None))))

            res = minimize_scalar(neg, bounds=(-0.3, 0.3), method="bounded", options={"xatol": 1e-4})
            rho = float(res.x)
    if return_cov:
        eta = X @ theta
        H = (X * (w * np.exp(eta))[:, None]).T @ X
        H[np.diag_indices(p)] += pen
        try:
            cov = np.linalg.inv(H)
        except np.linalg.LinAlgError:
            cov = np.linalg.pinv(H)
        return theta, rho, cov
    return theta, rho


class DCTracker:
    """Bir ligin maçlarını biriktirir ve istenen tarihte modeli (yeniden) kurar."""

    def __init__(self, cfg: DCConfig | None = None, fit_rho: bool = True, keep_cov: bool = False):
        self.cfg = cfg or DCConfig()
        self.fit_rho = fit_rho
        self.keep_cov = keep_cov
        self._days: list[int] = []
        self._home: list[str] = []
        self._away: list[str] = []
        self._hg: list[int] = []
        self._ag: list[int] = []
        self._last_theta: dict[str, float] = {}
        self.model: DCModel | None = None
        self.fit_day: int | None = None

    def add(self, day: int, home: str, away: str, hg: int, ag: int) -> None:
        self._days.append(day)
        self._home.append(home)
        self._away.append(away)
        self._hg.append(hg)
        self._ag.append(ag)

    def n_matches(self) -> int:
        return len(self._days)

    def fit(self, day: int, new_teams: set[str] | None = None) -> DCModel | None:
        """`day` gününden önce oynanmış maçlarla modeli kurar."""
        cfg = self.cfg
        days = np.asarray(self._days)
        if len(days) == 0:
            return None
        sel = (days < day) & (days >= day - cfg.window_days)
        if sel.sum() < cfg.min_matches:
            return self.model
        idx = np.nonzero(sel)[0]
        home = [self._home[i] for i in idx]
        away = [self._away[i] for i in idx]
        teams = sorted(set(home) | set(away))
        tix = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        hi = np.fromiter((tix[t] for t in home), dtype=int, count=len(idx))
        ai = np.fromiter((tix[t] for t in away), dtype=int, count=len(idx))
        hg = np.asarray(self._hg)[idx]
        ag = np.asarray(self._ag)[idx]
        w = np.exp(-cfg.xi * (day - days[idx]))
        new_teams = new_teams or set()
        pa = np.array([cfg.promoted_attack if t in new_teams else 0.0 for t in teams])
        pd_ = np.array([cfg.promoted_defense if t in new_teams else 0.0 for t in teams])
        init = None
        if self._last_theta:
            lt = self._last_theta
            init = np.concatenate([
                [lt.get("__mu__", 0.3), lt.get("__home__", 0.25)],
                [lt.get("a:" + t, pa[i]) for i, t in enumerate(teams)],
                [lt.get("d:" + t, pd_[i]) for i, t in enumerate(teams)],
            ])
        res = fit_dixon_coles(hi, ai, hg, ag, w, n, pa, pd_, cfg, init=init, fit_rho=self.fit_rho,
                              return_cov=self.keep_cov)
        theta, rho = res[0], res[1]
        cov = res[2] if self.keep_cov else None
        self._last_theta = {"__mu__": theta[0], "__home__": theta[1]}
        self._last_theta.update({"a:" + t: theta[2 + i] for i, t in enumerate(teams)})
        self._last_theta.update({"d:" + t: theta[2 + n + i] for i, t in enumerate(teams)})
        self.model = DCModel(
            teams=teams,
            attack=theta[2:2 + n].copy(),
            defense=theta[2 + n:].copy(),
            mu=float(theta[0]),
            home_adv=float(theta[1]),
            rho=rho,
            new_attack=cfg.promoted_attack,
            new_defense=cfg.promoted_defense,
            cov=cov,
            ridge=cfg.ridge,
        )
        self.fit_day = day
        return self.model


class MarketRatingTracker:
    """Geçmiş maç oranlarından takımların "piyasa gücü" reytingleri.

    Marjı temizlenmiş oranlardan iki hedef çıkarılır:
      z = log(P(ev) / P(deplasman))      ->  z ≈ h + r_ev − r_dep
      t = log(beklenen toplam gol)       ->  t ≈ c + s_ev + s_dep  (Alt/Üst 2.5 oranından)
    Her ikisi de zaman ağırlıklı ridge regresyonla çözülür.
    """

    def __init__(self, xi: float = 0.02, ridge: float = 0.1, window_days: int = 365, min_matches: int = 60):
        self.xi = xi
        self.ridge = ridge
        self.window_days = window_days
        self.min_matches = min_matches
        self._days: list[int] = []
        self._home: list[str] = []
        self._away: list[str] = []
        self._z: list[float] = []
        self._t: list[float] = []
        self.teams: dict[str, int] = {}
        self.r: np.ndarray | None = None
        self.s: np.ndarray | None = None
        self.h = 0.0
        self.c = float(np.log(2.6))
        self.r_new = 0.0
        self.s_new = 0.0
        self.fit_day: int | None = None

    def add(self, day: int, home: str, away: str, z: float, t: float) -> None:
        if not np.isfinite(z) and not np.isfinite(t):
            return
        self._days.append(day)
        self._home.append(home)
        self._away.append(away)
        self._z.append(z)
        self._t.append(t)

    @staticmethod
    def _solve(hi, ai, target, w, n, ridge, sign_away):
        m = len(target)
        X = np.zeros((m, n + 1))
        r = np.arange(m)
        X[:, 0] = 1.0
        X[r, 1 + hi] += 1.0
        X[r, 1 + ai] += sign_away
        A = (X * w[:, None]).T @ X
        A[np.diag_indices(n + 1)] += np.r_[1e-6, np.full(n, ridge)]
        b = (X * w[:, None]).T @ target
        return np.linalg.solve(A, b)

    def fit(self, day: int, new_teams: set[str] | None = None) -> bool:
        days = np.asarray(self._days)
        if len(days) == 0:
            return False
        sel = (days < day) & (days >= day - self.window_days)
        if sel.sum() < self.min_matches:
            return self.r is not None
        idx = np.nonzero(sel)[0]
        home = [self._home[i] for i in idx]
        away = [self._away[i] for i in idx]
        names = sorted(set(home) | set(away))
        tix = {t: i for i, t in enumerate(names)}
        n = len(names)
        hi = np.array([tix[t] for t in home])
        ai = np.array([tix[t] for t in away])
        w = np.exp(-self.xi * (day - days[idx]))
        z = np.asarray(self._z)[idx]
        t = np.asarray(self._t)[idx]
        r = np.zeros(n)
        s = np.zeros(n)
        okz = np.isfinite(z)
        if okz.sum() >= self.min_matches:
            th = self._solve(hi[okz], ai[okz], z[okz], w[okz], n, self.ridge, -1.0)
            self.h, r = float(th[0]), th[1:]
        okt = np.isfinite(t)
        if okt.sum() >= self.min_matches:
            th = self._solve(hi[okt], ai[okt], t[okt], w[okt], n, self.ridge, 1.0)
            self.c, s = float(th[0]), th[1:]
        self.teams, self.r, self.s = tix, r, s
        # Yeni (yükselen) takımlar için: geçerli takımların alt çeyreği
        self.r_new = float(np.quantile(r, 0.2)) if n else 0.0
        self.s_new = float(np.median(s)) if n else 0.0
        self.fit_day = day
        return True

    def predict(self, home: str, away: str) -> tuple[float, float]:
        """(z, t) tahmini; model kurulmadıysa NaN."""
        if self.r is None:
            return float("nan"), float("nan")
        ih, ia = self.teams.get(home), self.teams.get(away)
        rh = self.r[ih] if ih is not None else self.r_new
        ra = self.r[ia] if ia is not None else self.r_new
        sh = self.s[ih] if ih is not None else self.s_new
        sa = self.s[ia] if ia is not None else self.s_new
        return float(self.h + rh - ra), float(self.c + sh + sa)

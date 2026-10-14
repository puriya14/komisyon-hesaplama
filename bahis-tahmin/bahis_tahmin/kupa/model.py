"""Ligler arası ortak gol modeli (KUPA-01).

Bütün lig ve kupa maçları tek bir zaman ağırlıklı Poisson modelinde çözülür:

    log λ_ev  = μ + H + (A[L_ev] + a_ev) − (D[L_dep] + d_dep)
    log λ_dep = μ     + (A[L_dep] + a_dep) − (D[L_ev] + d_ev)

* ``a``, ``d``: takımın hücum ve savunma gücü (lig ortalamasına göre); ``A``, ``D``: ligin hücum ve savunma gücü.
  Lig maçlarında iki takımın ligi aynıdır; ligler arasındaki fark yalnızca kupa maçlarından (ve lig değiştiren
  takımlardan: küme düşme/yükselme) öğrenilir. Ligi veride olmayan takımlar ülkelerinin sahte ligine (``X:ülke``)
  bağlanır; bu liglerin gücü yalnızca kupa maçlarından gelir ve daha güçlü cezalandırılır.
* ``H``: iç saha avantajı. Lig maçlarında lige özgü, kupalarda turnuva grubuna özgü (``U``/``Q``/``C``/``K``);
  tarafsız sahada (final, süper kupa) sıfır.
* L2 cezası (ridge) takım ve lig parametrelerini sıfıra (ortalamaya) çeker; eski maçların ağırlığı exp(−ξ·gün).

Parametreler (ξ, pencere, cezalar) KUPA-01 ölçümünde geliştirme döneminde (2018/19–2021/22 kupa maçları) seçildi ve
2022/23–2025/26 test döneminde doğrulandı (docs/KUPA_01.md). Çözüm Newton yöntemiyle (seyrek doğrusal sistem) yapılır.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

EPOCH = pd.Timestamp("2000-01-01")
HOME_GROUPS = ("U", "Q", "C", "K")


@dataclass(frozen=True)
class ModelConfig:
    xi: float = 0.0019  # günlük zaman sönümü (yarı ömür ≈ 1 yıl)
    window_days: int = 1095
    r_team: float = 12.0  # takım parametreleri cezası
    r_league: float = 0.5  # lig parametreleri cezası
    r_outside: float = 4.0  # ligi veride olmayan ülkelerin sahte lig cezası
    r_home: float = 1.0  # iç saha parametrelerinin önsel değere (0.25) çekilmesi
    home_prior: float = 0.25
    max_iter: int = 30
    tol: float = 1e-7
    min_matches: int = 200


@dataclass
class ModelData:
    """Modelin bütün maçları (lig + kupa), zaman sırasında ve sayısal kodlarla."""
    day: np.ndarray
    home: np.ndarray  # takım dizini
    away: np.ndarray
    hlg: np.ndarray  # ev sahibinin ligi (dizin)
    alg: np.ndarray
    hgrp: np.ndarray  # iç saha parametresi dizini: lig maçında lig, kupada grup; -1 = tarafsız
    hg: np.ndarray
    ag: np.ndarray
    cup: np.ndarray  # bool
    teams: list
    leagues: list  # lig kodları + "X:ülke" sahte ligler
    homes: list  # iç saha parametre adları ("lig:E0", "grup:U")
    team_index: dict = field(default_factory=dict)
    league_index: dict = field(default_factory=dict)

    def __post_init__(self):
        self.team_index = {t: i for i, t in enumerate(self.teams)}
        self.league_index = {lg: i for i, lg in enumerate(self.leagues)}


@dataclass
class Params:
    fit_day: int
    teams: list
    attack: np.ndarray
    defense: np.ndarray
    leagues: list
    lg_attack: np.ndarray
    lg_defense: np.ndarray
    homes: dict  # ad -> değer
    mu: float
    n_matches: int
    team_index: dict = field(default_factory=dict)
    league_index: dict = field(default_factory=dict)
    # Yalnızca son çözümde (``fit(..., hessian=True)``): cezalı negatif log-olabilirliğin seyrek Hessian'ı ve parametre
    # bloklarının başlangıçları (μ=0, iç saha, lig hücum, lig savunma, takım hücum, takım savunma). Belirsizlik aralığı
    # (KUPA-GOL-02) için; tahmini değiştirmez.
    hess: object = None
    offsets: tuple | None = None

    def __post_init__(self):
        self.team_index = {t: i for i, t in enumerate(self.teams)}
        self.league_index = {lg: i for i, lg in enumerate(self.leagues)}

    def _home_key(self, group: str | None) -> str | None:
        key = f"grup:{group}"
        return key if key in self.homes else ("grup:U" if "grup:U" in self.homes else None)

    def log_rate_cov(self, home: str, away: str, hlg: str | None, alg: str | None, group: str | None,
                     neutral: bool) -> np.ndarray | None:
        """(log λ, log ν) ham gol beklentilerinin yaklaşık kovaryansı (Laplace yaklaşımı: cezalı olabilirliğin ters
        Hessian'ı, ``rates`` ile aynı parametreler). Hessian yoksa veya takım modelde yoksa None."""
        if self.hess is None or self.offsets is None:
            return None
        i, j = self.team_index.get(home), self.team_index.get(away)
        if i is None or j is None:
            return None
        o_H, o_A, o_D, o_a, o_d = self.offsets
        g = np.zeros((self.hess.shape[0], 2))
        g[0, :] = 1.0
        hk = None if neutral else self._home_key(group)
        if hk is not None:
            g[o_H + list(self.homes).index(hk), 0] += 1.0
        lh = self.league_index.get(hlg) if hlg is not None else None
        la = self.league_index.get(alg) if alg is not None else None
        if lh is not None:
            g[o_A + lh, 0] += 1.0
            g[o_D + lh, 1] -= 1.0
        if la is not None:
            g[o_D + la, 0] -= 1.0
            g[o_A + la, 1] += 1.0
        g[o_a + i, 0] += 1.0
        g[o_d + j, 0] -= 1.0
        g[o_a + j, 1] += 1.0
        g[o_d + i, 1] -= 1.0
        x = np.asarray(spsolve(self.hess, g)).reshape(g.shape)
        cov = g.T @ x
        return 0.5 * (cov + cov.T)

    def as_dict(self) -> dict:
        """Isınma başlangıcı (sonraki çözüm için): ad -> değer."""
        out = {"mu": self.mu}
        out.update({f"h:{k}": v for k, v in self.homes.items()})
        out.update({f"A:{lg}": float(v) for lg, v in zip(self.leagues, self.lg_attack)})
        out.update({f"D:{lg}": float(v) for lg, v in zip(self.leagues, self.lg_defense)})
        out.update({f"a:{t}": float(v) for t, v in zip(self.teams, self.attack)})
        out.update({f"d:{t}": float(v) for t, v in zip(self.teams, self.defense)})
        return out

    def team_strength(self, team: str, league: str | None) -> tuple[float, float] | None:
        """(hücum, savunma) log-gol ölçeğinde, lig gücü dahil; takım modelde yoksa None."""
        i = self.team_index.get(team)
        if i is None:
            return None
        j = self.league_index.get(league) if league is not None else None
        la = float(self.lg_attack[j]) if j is not None else 0.0
        ld = float(self.lg_defense[j]) if j is not None else 0.0
        return la + float(self.attack[i]), ld + float(self.defense[i])

    def rates(self, home: str, away: str, hlg: str | None, alg: str | None, group: str | None,
              neutral: bool) -> tuple[float, float] | None:
        """Ham (kalibrasyonsuz) gol beklentileri; takımlardan biri modelde yoksa None."""
        h = self.team_strength(home, hlg)
        a = self.team_strength(away, alg)
        if h is None or a is None:
            return None
        hk = None if neutral else self._home_key(group)
        hv = 0.0 if neutral else (float(self.homes[hk]) if hk is not None else 0.25)
        lam = float(np.exp(self.mu + hv + h[0] - a[1]))
        nu = float(np.exp(self.mu + a[0] - h[1]))
        return lam, nu


# ------------------------------------------------------------------------------------------------ veri hazırlığı


def day_number(ts) -> np.ndarray:
    return ((pd.to_datetime(ts) - EPOCH).dt.days).to_numpy(dtype=int) if isinstance(ts, pd.Series) else \
        int((pd.Timestamp(ts) - EPOCH).days)


class LeagueTimeline:
    """Takımın belirli bir tarihteki ligi: aynı sezondaki en yakın lig maçının ligi (önce geçmiş; 400 gün içinde)."""

    def __init__(self, domestic: pd.DataFrame, key_of):
        rows = []
        for side in ("home", "away"):
            rows.append(pd.DataFrame({"k": [key_of(lg, t) for lg, t in zip(domestic["league"], domestic[side])],
                                      "day": day_number(domestic["date"]), "lg": domestic["league"].astype(str)}))
        tl = pd.concat(rows, ignore_index=True).sort_values(["k", "day"], kind="mergesort") if rows else None
        self._by: dict = {}
        if tl is not None:
            for k, g in tl.groupby("k", sort=False):
                self._by[k] = (g["day"].to_numpy(), g["lg"].to_numpy())

    def has(self, key: str) -> bool:
        return key in self._by

    def league_at(self, key: str, day: int) -> str | None:
        hit = self._by.get(key)
        if hit is None:
            return None
        days, lgs = hit
        i = int(np.searchsorted(days, day))
        cand = []
        if i > 0 and day - days[i - 1] <= 400:
            cand.append((day - days[i - 1], lgs[i - 1]))
        if i < len(days) and days[i] - day <= 120:
            cand.append((days[i] - day, lgs[i]))
        if not cand:
            return None
        return min(cand, key=lambda x: x[0])[1]

    def last_league(self, key: str) -> str | None:
        hit = self._by.get(key)
        return None if hit is None else str(hit[1][-1])


def outside_league(country: str) -> str:
    return f"X:{country or '?'}"


def build_data(domestic: pd.DataFrame, cups: pd.DataFrame, key_of, group_of) -> tuple[ModelData, LeagueTimeline]:
    """Lig maçları (depo) + kupa maçları -> ``ModelData``. ``key_of(lig, takım)``: lig takımının anahtarı;
    ``group_of(turnuva)``: kupa grubu."""
    tl = LeagueTimeline(domestic, key_of)
    d_day = day_number(domestic["date"])
    d_h = [key_of(lg, t) for lg, t in zip(domestic["league"], domestic["home"])]
    d_a = [key_of(lg, t) for lg, t in zip(domestic["league"], domestic["away"])]
    d_lg = domestic["league"].astype(str).tolist()
    c_day = day_number(cups["date"]) if len(cups) else np.zeros(0, dtype=int)
    c_h = cups["home_key"].astype(str).tolist() if len(cups) else []
    c_a = cups["away_key"].astype(str).tolist() if len(cups) else []
    c_hl, c_al = [], []
    for k, ctry, d in zip(c_h, cups["home_country"].astype(str).tolist() if len(cups) else [], c_day):
        c_hl.append(tl.league_at(k, int(d)) or outside_league(ctry))
    for k, ctry, d in zip(c_a, cups["away_country"].astype(str).tolist() if len(cups) else [], c_day):
        c_al.append(tl.league_at(k, int(d)) or outside_league(ctry))
    teams = sorted(set(d_h) | set(d_a) | set(c_h) | set(c_a))
    leagues = sorted(set(d_lg) | set(c_hl) | set(c_al))
    homes = [f"lig:{lg}" for lg in sorted(set(d_lg))] + [f"grup:{g}" for g in HOME_GROUPS]
    ti = {t: i for i, t in enumerate(teams)}
    li = {lg: i for i, lg in enumerate(leagues)}
    hi = {h: i for i, h in enumerate(homes)}
    neutral = cups["neutral"].astype(bool).to_numpy() if len(cups) else np.zeros(0, bool)
    grp = [group_of(c) for c in cups["comp"]] if len(cups) else []
    day = np.concatenate([d_day, c_day]).astype(int)
    order = np.argsort(day, kind="mergesort")
    arr = lambda xs: np.asarray(xs)[order]  # noqa: E731
    data = ModelData(
        day=day[order],
        home=arr([ti[k] for k in d_h + c_h]), away=arr([ti[k] for k in d_a + c_a]),
        hlg=arr([li[x] for x in d_lg + c_hl]), alg=arr([li[x] for x in d_lg + c_al]),
        hgrp=arr([hi[f"lig:{x}"] for x in d_lg] + [(-1 if n else hi[f"grup:{g}"]) for n, g in zip(neutral, grp)]),
        hg=arr(list(domestic["fthg"].astype(int)) + (list(cups["fthg"].astype(int)) if len(cups) else [])),
        ag=arr(list(domestic["ftag"].astype(int)) + (list(cups["ftag"].astype(int)) if len(cups) else [])),
        cup=arr([False] * len(d_h) + [True] * len(c_h)).astype(bool),
        teams=teams, leagues=leagues, homes=homes)
    return data, tl


# ----------------------------------------------------------------------------------------------------- çözüm


def fit(data: ModelData, day: int, cfg: ModelConfig = ModelConfig(), init: dict | None = None,
        hessian: bool = False) -> Params | None:
    """``day`` gününden ÖNCE oynanmış ve pencere içindeki maçlarla parametreler (yeterli maç yoksa None).
    ``hessian``: çözümdeki Hessian'ı da sakla (belirsizlik aralığı için; yalnızca son çözümde)."""
    sel = np.nonzero((data.day < day) & (data.day >= day - cfg.window_days))[0]
    if len(sel) < cfg.min_matches:
        return None
    h, a = data.home[sel], data.away[sel]
    hl, al = data.hlg[sel], data.alg[sel]
    hg_idx = data.hgrp[sel]
    tu, h_t = np.unique(np.concatenate([h, a]), return_inverse=True)
    h_t, a_t = h_t[:len(sel)], h_t[len(sel):]
    lu, l_t = np.unique(np.concatenate([hl, al]), return_inverse=True)
    hl_t, al_t = l_t[:len(sel)], l_t[len(sel):]
    nT, nL, nH = len(tu), len(lu), len(data.homes)
    o_H, o_A = 1, 1 + nH
    o_D = o_A + nL
    o_a = o_D + nL
    o_d = o_a + nT
    p = o_d + nT
    m = len(sel)
    r = np.arange(m)
    w = np.exp(-cfg.xi * (day - data.day[sel]))
    rows, cols, vals = [], [], []

    def add(rr, cc, v=1.0):
        rows.append(rr)
        cols.append(cc)
        vals.append(np.full(len(rr), float(v)))

    add(r, np.zeros(m, int))
    add(m + r, np.zeros(m, int))
    hm = hg_idx >= 0
    add(r[hm], o_H + hg_idx[hm])
    add(r, o_A + hl_t)
    add(r, o_D + al_t, -1.0)
    add(m + r, o_A + al_t)
    add(m + r, o_D + hl_t, -1.0)
    add(r, o_a + h_t)
    add(r, o_d + a_t, -1.0)
    add(m + r, o_a + a_t)
    add(m + r, o_d + h_t, -1.0)
    X = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(2 * m, p))
    y = np.concatenate([data.hg[sel], data.ag[sel]]).astype(float)
    ww = np.concatenate([w, w])
    pen = np.zeros(p)
    prior = np.zeros(p)
    pen[o_H:o_A] = cfg.r_home
    prior[o_H:o_A] = cfg.home_prior
    names_L = [data.leagues[j] for j in lu]
    for j, lg in enumerate(names_L):
        rr = cfg.r_outside if lg.startswith("X:") else cfg.r_league
        pen[o_A + j] = pen[o_D + j] = rr
    pen[o_a:] = cfg.r_team
    th = prior.copy()
    th[0] = float(np.log(max(np.average(y, weights=ww), 0.1)))
    if init:
        th[0] = init.get("mu", th[0])
        for k, hn in enumerate(data.homes):
            th[o_H + k] = init.get(f"h:{hn}", th[o_H + k])
        for j, lg in enumerate(names_L):
            th[o_A + j] = init.get(f"A:{lg}", 0.0)
            th[o_D + j] = init.get(f"D:{lg}", 0.0)
        for i, t in enumerate(tu):
            tn = data.teams[t]
            th[o_a + i] = init.get(f"a:{tn}", 0.0)
            th[o_d + i] = init.get(f"d:{tn}", 0.0)
    Xt = X.T.tocsr()

    def objective(t):
        eta = X @ t
        return float(np.sum(ww * (y * eta - np.exp(eta))) - 0.5 * np.sum(pen * (t - prior) ** 2))

    obj = objective(th)
    for _ in range(cfg.max_iter):
        eta = X @ th
        rate = np.exp(eta)
        g = Xt @ (ww * (y - rate)) - pen * (th - prior)
        H = (Xt @ sp.diags(ww * rate) @ X).tocsc()
        H = H + sp.diags(pen + 1e-9)
        step = spsolve(H, g)
        if not np.all(np.isfinite(step)):
            break
        t = 1.0
        while True:
            cand = th + t * step
            new = objective(cand)
            if new >= obj - 1e-9 or t < 1e-4:
                break
            t *= 0.5
        th, obj_old, obj = cand, obj, new
        if np.max(np.abs(t * step)) < cfg.tol or abs(obj - obj_old) < cfg.tol:
            break
    teams = [data.teams[t] for t in tu]
    hess = None
    if hessian:
        rate = np.exp(X @ th)
        hess = ((Xt @ sp.diags(ww * rate) @ X) + sp.diags(pen + 1e-9)).tocsc()
    return Params(fit_day=int(day), teams=teams, attack=th[o_a:o_d].copy(), defense=th[o_d:].copy(), leagues=names_L,
                  lg_attack=th[o_A:o_D].copy(), lg_defense=th[o_D:o_a].copy(),
                  homes={hn: float(th[o_H + k]) for k, hn in enumerate(data.homes)}, mu=float(th[0]), n_matches=m,
                  hess=hess, offsets=(o_H, o_A, o_D, o_a, o_d) if hessian else None)


# ------------------------------------------------------------------------------------------------ kalibrasyon


def calibrate_rates(lam, nu, theta, neutral=None) -> tuple[np.ndarray, np.ndarray]:
    """Toplam gol ve güç farkı kalibrasyonu: log(λ+ν) ve log(λ/ν) doğrusal olarak yeniden ölçeklenir.

    θ = (a, b, δ, γ): T = exp(a + b·log(λ+ν)), q = σ(δ + γ·log(λ/ν)); λ' = T·q, ν' = T·(1−q). Kimlik dönüşümü
    (0, 1, 0, 1)'dir. Kupa maçlarında ham model toplam golü fazla yayar (eğim b ≈ 0,4). δ iç saha avantajının
    düzeltmesidir: tarafsız sahada (``neutral``) uygulanmaz, böylece takımların yeri değişince tahmin de simetrik
    değişir."""
    lam = np.asarray(lam, dtype=float)
    nu = np.asarray(nu, dtype=float)
    a, b, dlt, gam = theta
    home = 1.0 if neutral is None else 1.0 - np.asarray(neutral, dtype=float)
    T = np.exp(a + b * np.log(lam + nu))
    q = 1.0 / (1.0 + np.exp(-(dlt * home + gam * np.log(lam / nu))))
    return T * q, T * (1.0 - q)


def fit_calibration(lam, nu, hg, ag, neutral=None) -> tuple[float, float, float, float]:
    """Kalibrasyon parametreleri: bağımsız Poisson olabilirliğinin en büyüklenmesi (önceki dönemin örneklem dışı
    tahminleri üzerinde)."""
    from scipy.optimize import minimize

    lam = np.asarray(lam, dtype=float)
    nu = np.asarray(nu, dtype=float)
    hg = np.asarray(hg, dtype=float)
    ag = np.asarray(ag, dtype=float)
    neutral = None if neutral is None else np.asarray(neutral, dtype=bool)
    if len(lam) < 50:
        return (0.0, 1.0, 0.0, 1.0)

    def nll(th):
        lx, nx = calibrate_rates(lam, nu, th, neutral)
        return -float(np.mean(hg * np.log(lx) - lx + ag * np.log(nx) - nx))

    res = minimize(nll, [0.0, 1.0, 0.0, 1.0], method="Nelder-Mead",
                   options={"xatol": 1e-5, "fatol": 1e-9, "maxiter": 4000})
    th = tuple(float(x) for x in res.x)
    # Makul aralık dışındaki çözüm (az veri) kullanılmaz
    if not (0.0 < th[1] < 2.0 and 0.3 < th[3] < 2.0 and abs(th[0]) < 2.0 and abs(th[2]) < 1.0):
        return (0.0, 1.0, 0.0, 1.0)
    return th

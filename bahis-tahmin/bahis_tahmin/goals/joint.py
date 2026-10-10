"""İlk yarı / ikinci yarı ortak gol dağılımından tutarlı pazar olasılıkları.

Model yapısı (maç öncesi bilgiyle, gerçek ilk yarı skoru KULLANILMADAN):

    P(İY skoru a-b) = Poisson(a; g·k1·λ1h) · Poisson(b; g·k1·λ1a) · τ(a, b; ρ1)
    P(2Y golleri | İY skoru) = Poisson(g·k2·λ2h·m_h[c]) × Poisson(g·k2·λ2a·m_a[c])

    c = İY skor durumu (her takım için 0 / 1 / 2+ → 9 durum), m = durum çarpanları (geçmişten öğrenilir)
    g = maç temposu için ortak gama kırılganlığı (ortalama 1, varyans φ); φ=0 ise yok.

Üç ana pazar ve diğerleri aynı dağılımdan türetilir; bu yüzden P(A) ≤ P(B), P(A) ≤ P(C)
kendiliğinden sağlanır. İY ızgarası her takım için 0..GMAX ile sınırlıdır; dışarıda kalan
olasılık kütlesi (kuyruk) ölçülür: B ve C için tam olarak hesaba katılır (kuyruktaki tüm skorlar
≥ GMAX+1 gol içerir), A ve diğer pazarlar için hata sınırı olarak raporlanır.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import gamma as gamma_dist

GMAX = 10
_G = np.arange(GMAX + 1)
_FACT = np.array([math.factorial(k) for k in range(GMAX + 1)], dtype=float)
_I, _J = np.meshgrid(_G, _G, indexing="ij")
STATE = (np.minimum(_I, 2) * 3 + np.minimum(_J, 2)).ravel()  # 9 İY durumu
N_STATES = 9
FLAT_I = _I.ravel()
FLAT_J = _J.ravel()
TOTAL_H1 = FLAT_I + FLAT_J

OUTPUT_KEYS = (
    "A", "B", "C", "BC",
    "h1_home", "h1_away", "h2_home", "h2_away",  # dört koşulun her birinin gerçekleşme olasılığı
    "FT_BTTS", "FH_BTTS", "SH_O15", "FT_O25", "FT_O45",
    "tail",
)


def _poisson_grid(lam: np.ndarray) -> np.ndarray:
    lam = np.asarray(lam, dtype=float)[:, None]
    return np.exp(-lam) * lam ** _G / _FACT


def _nb_grid(mu: np.ndarray, alpha: float, kmax: int = GMAX) -> np.ndarray:
    """Negatif binom olasılıkları P(0..kmax); ortalama mu, varyans mu + alpha·mu² (alpha=0 → Poisson)."""
    mu = np.asarray(mu, dtype=float)
    if alpha <= 1e-8:
        out = np.empty(mu.shape + (kmax + 1,))
        term = np.exp(-mu)
        for k in range(kmax + 1):
            out[..., k] = term
            term = term * mu / (k + 1)
        return out
    size = 1.0 / alpha
    pr = size / (size + mu)
    out = np.empty(mu.shape + (kmax + 1,))
    term = pr ** size
    q = mu / (size + mu)
    for k in range(kmax + 1):
        out[..., k] = term
        term = term * (k + size) / (k + 1) * q
    return out


def _survival(mu: np.ndarray, k: np.ndarray) -> np.ndarray:
    """P(Poisson(mu) ≥ k), k tamsayı dizisi (k ≤ 0 → 1)."""
    out = np.ones_like(mu)
    kmax = int(np.max(k)) if np.size(k) else 0
    if kmax <= 0:
        return out
    term = np.exp(-mu)
    cdf = np.zeros_like(mu)
    for j in range(kmax):
        cdf = cdf + term
        out = np.where(k == j + 1, 1.0 - cdf, out)
        term = term * mu / (j + 1)
    return np.clip(out, 0.0, 1.0)


def frailty_nodes(phi: float, n: int = 24) -> tuple[np.ndarray, np.ndarray]:
    """Gama(ortalama 1, varyans φ) için kareleme noktaları ve ağırlıkları.

    Eşit olasılıklı kantil orta noktaları kullanılır (küçük φ'de genelleştirilmiş Laguerre
    ağırlıkları taşabildiği için). Noktalar ortalaması tam 1 olacak şekilde ölçeklenir.
    """
    if phi is None or not np.isfinite(phi) or phi <= 1e-6:
        return np.array([1.0]), np.array([1.0])
    u = (np.arange(n) + 0.5) / n
    g = gamma_dist.ppf(u, a=1.0 / phi, scale=phi)
    g = g / g.mean()
    return g, np.full(n, 1.0 / n)


def joint_probs(
    l1h, l1a, l2h, l2a, rho1=None,
    mult_h=None, mult_a=None, phi: float = 0.0, k1: float = 1.0, k2: float = 1.0,
    chunk: int = 20000, alpha1: float = 0.0, alpha2: float = 0.0,
) -> dict[str, np.ndarray]:
    """Vektörel pazar olasılıkları (her maç için).

    alpha1/alpha2 > 0 ise yarı-takım golleri Poisson yerine negatif binom dağılır (fazla dağılım).
    """
    if alpha1 > 1e-8 or alpha2 > 1e-8:
        return _joint_nb(l1h, l1a, l2h, l2a, mult_h, mult_a, alpha1, alpha2, chunk)
    l1h = np.asarray(l1h, dtype=float)
    l1a = np.asarray(l1a, dtype=float)
    l2h = np.asarray(l2h, dtype=float)
    l2a = np.asarray(l2a, dtype=float)
    n = len(l1h)
    rho1 = np.zeros(n) if rho1 is None else np.nan_to_num(np.asarray(rho1, dtype=float), nan=0.0)
    mh = np.ones(N_STATES) if mult_h is None else np.asarray(mult_h, dtype=float)
    ma = np.ones(N_STATES) if mult_a is None else np.asarray(mult_a, dtype=float)
    nodes, weights = frailty_nodes(phi)
    out = {k: np.zeros(n) for k in OUTPUT_KEYS}
    mh_cell = mh[STATE]
    ma_cell = ma[STATE]
    for s in range(0, n, chunk):
        e = min(n, s + chunk)
        acc = {k: np.zeros(e - s) for k in OUTPUT_KEYS}
        for g, w in zip(nodes, weights):
            a1 = g * k1 * l1h[s:e]
            b1 = g * k1 * l1a[s:e]
            r = rho1[s:e]
            P = (_poisson_grid(a1)[:, :, None] * _poisson_grid(b1)[:, None, :]).reshape(e - s, -1)
            # Dixon-Coles düşük skor düzeltmesi (marjinalleri korur)
            P[:, 0] *= np.maximum(1 - a1 * b1 * r, 1e-9)
            P[:, 1] *= np.maximum(1 + a1 * r, 1e-9)
            P[:, GMAX + 1] *= np.maximum(1 + b1 * r, 1e-9)
            P[:, GMAX + 2] *= np.maximum(1 - r, 1e-9)
            tail = np.clip(1.0 - P.sum(axis=1), 0.0, 1.0)
            r2h = (g * k2 * l2h[s:e])[:, None] * mh_cell[None, :]
            r2a = (g * k2 * l2a[s:e])[:, None] * ma_cell[None, :]
            qh = 1.0 - np.exp(-r2h)
            qa = 1.0 - np.exp(-r2a)
            mu2 = r2h + r2a
            both1 = (FLAT_I >= 1) & (FLAT_J >= 1)
            res = {
                "A": (P * both1 * qh * qa).sum(axis=1),
                "B": (P * _survival(mu2, np.broadcast_to(4 - TOTAL_H1, mu2.shape))).sum(axis=1) + tail,
                "C": 1.0 - (P[:, 0] + P[:, 1] + P[:, GMAX + 1]),
                "BC": (P * (TOTAL_H1 >= 2) * _survival(mu2, np.broadcast_to(4 - TOTAL_H1, mu2.shape))).sum(axis=1) + tail,
                "h1_home": 1.0 - np.exp(-a1),
                "h1_away": 1.0 - np.exp(-b1),
                "h2_home": (P * qh).sum(axis=1) + tail,
                "h2_away": (P * qa).sum(axis=1) + tail,
                "FT_BTTS": (P * np.where(FLAT_I >= 1, 1.0, qh) * np.where(FLAT_J >= 1, 1.0, qa)).sum(axis=1) + tail,
                "FH_BTTS": (P * both1).sum(axis=1),
                "SH_O15": (P * _survival(mu2, np.full(mu2.shape, 2))).sum(axis=1) + tail,
                "FT_O25": (P * _survival(mu2, np.broadcast_to(3 - TOTAL_H1, mu2.shape))).sum(axis=1) + tail,
                "FT_O45": (P * _survival(mu2, np.broadcast_to(5 - TOTAL_H1, mu2.shape))).sum(axis=1) + tail,
                "tail": tail,
            }
            for k in OUTPUT_KEYS:
                acc[k] += w * res[k]
        for k in OUTPUT_KEYS:
            out[k][s:e] = acc[k]
    # Not: A ≤ B∩C ≤ min(B, C) ilişkisi yapı gereği (aynı dağılımdan) sağlanır; burada kırpma/min()
    # ile düzeltme YAPILMAZ. Yalnızca kayan nokta gürültüsü için [0, 1] sınırı uygulanır.
    for k in OUTPUT_KEYS:
        if k != "tail":
            out[k] = np.clip(out[k], 0.0, 1.0)
    return out


def loglik_params(h1h, h1a, h2h, h2a, l1h, l1a, l2h, l2a, mult_h, mult_a, k1, k2, phi) -> float:
    """Gözlenen yarı skorlarının ortak (gama-Poisson) log-olabilirliği (τ düzeltmesi hariç).

    Gama ortak kırılganlık altında kapalı form (negatif multinomial):
      Σ x_i log λ_i − Σ log x_i! + log Γ(X + r) − log Γ(r) + X log φ − (X + r) log(1 + φΛ)
    """
    from scipy.special import gammaln

    c = np.minimum(h1h, 2) * 3 + np.minimum(h1a, 2)
    lam = np.column_stack([k1 * l1h, k1 * l1a, k2 * l2h * mult_h[c], k2 * l2a * mult_a[c]])
    x = np.column_stack([h1h, h1a, h2h, h2a]).astype(float)
    lam = np.clip(lam, 1e-9, None)
    base = (x * np.log(lam)).sum(axis=1) - gammaln(x + 1).sum(axis=1)
    X = x.sum(axis=1)
    L = lam.sum(axis=1)
    if phi <= 1e-8:
        return float((base - L).sum())
    r = 1.0 / phi
    mix = gammaln(X + r) - gammaln(r) + X * np.log(phi) - (X + r) * np.log1p(phi * L)
    return float((base + mix).sum())


def loglik_rates(x: np.ndarray, lam: np.ndarray, phi: float) -> np.ndarray:
    """Satır başına ortak gama-Poisson log-olabilirliği; x ve lam (n, 4): İY ev, İY dep, 2Y ev, 2Y dep."""
    from scipy.special import gammaln

    lam = np.clip(lam, 1e-9, None)
    base = (x * np.log(lam)).sum(axis=1) - gammaln(x + 1).sum(axis=1)
    X = x.sum(axis=1)
    L = lam.sum(axis=1)
    if phi <= 1e-8:
        return base - L
    r = 1.0 / phi
    return base + gammaln(X + r) - gammaln(r) + X * np.log(phi) - (X + r) * np.log1p(phi * L)


def _joint_nb(l1h, l1a, l2h, l2a, mult_h, mult_a, alpha1, alpha2, chunk=20000) -> dict[str, np.ndarray]:
    """Negatif binom yarı-takım gollü ortak dağılım (ortak kırılganlık ve τ yok)."""
    l1h, l1a, l2h, l2a = (np.asarray(v, dtype=float) for v in (l1h, l1a, l2h, l2a))
    n = len(l1h)
    mh = np.ones(N_STATES) if mult_h is None else np.asarray(mult_h, dtype=float)
    ma = np.ones(N_STATES) if mult_a is None else np.asarray(mult_a, dtype=float)
    mh_cell, ma_cell = mh[STATE], ma[STATE]
    out = {k: np.zeros(n) for k in OUTPUT_KEYS}
    K = 5  # 2. yarı toplamı için 0..4 yeterli (en fazla "≥5" eşiği)
    both1 = (FLAT_I >= 1) & (FLAT_J >= 1)
    for s in range(0, n, chunk):
        e = min(n, s + chunk)
        gh = _nb_grid(l1h[s:e], alpha1)
        ga = _nb_grid(l1a[s:e], alpha1)
        P = (gh[:, :, None] * ga[:, None, :]).reshape(e - s, -1)
        tail = np.clip(1.0 - P.sum(axis=1), 0.0, 1.0)
        r2h = l2h[s:e, None] * mh_cell[None, :]
        r2a = l2a[s:e, None] * ma_cell[None, :]
        ph = _nb_grid(r2h, alpha2, K - 1)  # (n, 121, 5)
        pa = _nb_grid(r2a, alpha2, K - 1)
        qh = 1.0 - ph[..., 0]
        qa = 1.0 - pa[..., 0]
        # 2. yarı toplam golünün 0..4 olasılıkları (konvolüsyon)
        tot = np.zeros(ph.shape)
        for i in range(K):
            for j in range(K - i):
                tot[..., i + j] += ph[..., i] * pa[..., j]
        cdf = np.cumsum(tot, axis=-1)  # P(toplam ≤ m), m = 0..4

        def surv(kneed):
            kneed = np.broadcast_to(kneed, cdf.shape[:-1])
            idx = np.clip(kneed - 1, 0, K - 1)
            val = 1.0 - np.take_along_axis(cdf, idx[..., None], axis=-1)[..., 0]
            return np.where(kneed <= 0, 1.0, val)

        s4 = surv(4 - TOTAL_H1)
        res = {
            "A": (P * both1 * qh * qa).sum(axis=1),
            "B": (P * s4).sum(axis=1) + tail,
            "C": 1.0 - (gh[:, 0] * ga[:, 0] + gh[:, 1] * ga[:, 0] + gh[:, 0] * ga[:, 1]),
            "BC": (P * (TOTAL_H1 >= 2) * s4).sum(axis=1) + tail,
            "h1_home": 1.0 - gh[:, 0],
            "h1_away": 1.0 - ga[:, 0],
            "h2_home": (P * qh).sum(axis=1) + tail,
            "h2_away": (P * qa).sum(axis=1) + tail,
            "FT_BTTS": (P * np.where(FLAT_I >= 1, 1.0, qh) * np.where(FLAT_J >= 1, 1.0, qa)).sum(axis=1) + tail,
            "FH_BTTS": (P * both1).sum(axis=1),
            "SH_O15": (P * surv(np.full(TOTAL_H1.shape, 2))).sum(axis=1) + tail,
            "FT_O25": (P * surv(3 - TOTAL_H1)).sum(axis=1) + tail,
            "FT_O45": (P * surv(5 - TOTAL_H1)).sum(axis=1) + tail,
            "tail": tail,
        }
        for k in OUTPUT_KEYS:
            out[k][s:e] = res[k]
    for k in OUTPUT_KEYS:
        if k != "tail":
            out[k] = np.clip(out[k], 0.0, 1.0)
    return out


def loglik_nb(x: np.ndarray, lam: np.ndarray, alpha1: float, alpha2: float) -> np.ndarray:
    """Dört bağımsız negatif binom sayımın satır başına log-olabilirliği (İY: alpha1, 2Y: alpha2)."""
    from scipy.special import gammaln

    lam = np.clip(lam, 1e-9, None)
    out = np.zeros(len(x))
    for j, a in ((0, alpha1), (1, alpha1), (2, alpha2), (3, alpha2)):
        k, mu = x[:, j], lam[:, j]
        if a <= 1e-8:
            out += k * np.log(mu) - mu - gammaln(k + 1)
        else:
            sz = 1.0 / a
            out += (gammaln(k + sz) - gammaln(sz) - gammaln(k + 1)
                    + sz * np.log(sz / (sz + mu)) + k * np.log(mu / (sz + mu)))
    return out


# ----------------------------------------------------------------------------
# Bölge kütleleri ve marjinal hedeflere üstel eğim (IPF / I-projeksiyon)
# ----------------------------------------------------------------------------

REGIONS = ("BC", "BnC", "nBC", "nn")  # B∧C, B∧¬C, ¬B∧C, ¬B∧¬C
COND_KEYS = ("h1_home", "h1_away", "h2_home", "h2_away")


def joint_regions(l1h, l1a, l2h, l2a, mult_h=None, mult_a=None, phi: float = 0.0, chunk: int = 20000) -> dict:
    """B/C bölgelerinin olasılık kütleleri ve A ile dört koşulun bölgelere dağılımı (Poisson yapı).

    Dönen sözlük: "BC","BnC","nBC","nn","A" ve her koşul için "<koşul>:<bölge>" kütleleri, "tail".
    """
    l1h, l1a, l2h, l2a = (np.asarray(v, dtype=float) for v in (l1h, l1a, l2h, l2a))
    n = len(l1h)
    mh = np.ones(N_STATES) if mult_h is None else np.asarray(mult_h, dtype=float)
    ma = np.ones(N_STATES) if mult_a is None else np.asarray(mult_a, dtype=float)
    mh_cell, ma_cell = mh[STATE], ma[STATE]
    keys = list(REGIONS) + ["A", "tail"] + [f"{c}:{r}" for c in COND_KEYS for r in REGIONS]
    out = {k: np.zeros(n) for k in keys}
    nodes, weights = frailty_nodes(phi)
    c_cell = TOTAL_H1 >= 2
    both1 = (FLAT_I >= 1) & (FLAT_J >= 1)
    kneed = 4 - TOTAL_H1
    for s in range(0, n, chunk):
        e = min(n, s + chunk)
        for g, w in zip(nodes, weights):
            a1, b1 = g * l1h[s:e], g * l1a[s:e]
            P = (_poisson_grid(a1)[:, :, None] * _poisson_grid(b1)[:, None, :]).reshape(e - s, -1)
            tail = np.clip(1.0 - P.sum(axis=1), 0.0, 1.0)
            r2h = (g * l2h[s:e])[:, None] * mh_cell[None, :]
            r2a = (g * l2a[s:e])[:, None] * ma_cell[None, :]
            kk = np.broadcast_to(kneed, r2h.shape)
            S = _survival(r2h + r2a, kk)  # P(2Y toplam ≥ 4 − İY toplam)
            qh, qa = 1.0 - np.exp(-r2h), 1.0 - np.exp(-r2a)
            # P(2Y ev ≥1 ∧ 2Y toplam ≥ k) = S(k; μ) − P(2Y ev = 0)·S(k; ν_dep)
            h2h_and = np.where(kk <= 0, qh, S - np.exp(-r2h) * _survival(r2a, kk))
            h2a_and = np.where(kk <= 0, qa, S - np.exp(-r2a) * _survival(r2h, kk))
            reg = {
                "BC": (P * c_cell * S).sum(axis=1) + tail,
                "BnC": (P * ~c_cell * S).sum(axis=1),
                "nBC": (P * c_cell * (1 - S)).sum(axis=1),
                "nn": (P * ~c_cell * (1 - S)).sum(axis=1),
                "A": (P * both1 * qh * qa).sum(axis=1),
                "tail": tail,
            }
            for cond, ind_and_B, ind_total in (
                ("h1_home", (FLAT_I >= 1) * S, (FLAT_I >= 1) * np.ones_like(S)),
                ("h1_away", (FLAT_J >= 1) * S, (FLAT_J >= 1) * np.ones_like(S)),
                ("h2_home", h2h_and, qh),
                ("h2_away", h2a_and, qa),
            ):
                andB = P * ind_and_B
                notB = P * (ind_total - ind_and_B)
                reg[f"{cond}:BC"] = (andB * c_cell).sum(axis=1) + tail
                reg[f"{cond}:BnC"] = (andB * ~c_cell).sum(axis=1)
                reg[f"{cond}:nBC"] = (notB * c_cell).sum(axis=1)
                reg[f"{cond}:nn"] = (notB * ~c_cell).sum(axis=1)
            for k in keys:
                out[k][s:e] += w * reg[k]
    return out


def tilt_to_targets(reg: dict, t_b, t_c, iters: int = 200, tol: float = 1e-12) -> dict:
    """Ortak dağılımı, B ve C marjinalleri hedeflere eşit olacak şekilde üstel eğimle yeniden ağırlıklandırır.

    Aynı bölgedeki tüm skor senaryoları aynı çarpanı alır (IPF / en küçük bilgi kaybı projeksiyonu);
    dağılım geçerli kalır, bu yüzden A ⊆ B∩C ilişkisi korunur. Kırpma veya min() kullanılmaz.
    """
    t_b = np.asarray(t_b, dtype=float)
    t_c = np.asarray(t_c, dtype=float)
    m = {r: np.maximum(reg[r], 1e-300).copy() for r in REGIONS}
    for _ in range(iters):
        b = m["BC"] + m["BnC"]
        f, gq = t_b / b, (1 - t_b) / (m["nBC"] + m["nn"])
        m["BC"] *= f
        m["BnC"] *= f
        m["nBC"] *= gq
        m["nn"] *= gq
        c = m["BC"] + m["nBC"]
        f, gq = t_c / c, (1 - t_c) / (m["BnC"] + m["nn"])
        m["BC"] *= f
        m["nBC"] *= f
        m["BnC"] *= gq
        m["nn"] *= gq
        dev = np.nanmax(np.abs(m["BC"] + m["BnC"] - t_b))
        if dev < tol:
            break
    w = {r: m[r] / np.maximum(reg[r], 1e-300) for r in REGIONS}
    out = {"B": m["BC"] + m["BnC"], "C": m["BC"] + m["nBC"], "BC": m["BC"], "A": reg["A"] * w["BC"]}
    for cond in COND_KEYS:
        out[cond] = sum(reg[f"{cond}:{r}"] * w[r] for r in REGIONS)
    out["weights"] = w
    return out


# ----------------------------------------------------------------------------
# İY/MS (ilk yarı / maç sonu sonucu) — aynı ortak dağılımdan
# ----------------------------------------------------------------------------

HTFT_REGIONS = ("A", "BCnA", "BnC", "nBC", "nn")  # A, (B∧C)∖A, B∧¬C, ¬B∧C, ¬B∧¬C
_HT_IDX = np.where(FLAT_I > FLAT_J, 0, np.where(FLAT_I == FLAT_J, 1, 2))  # İY sonucu: 0='1', 1='X', 2='2'
_C_CELL = TOTAL_H1 >= 2
_A_CELL = (FLAT_I >= 1) & (FLAT_J >= 1)
_SMALL = [(x, y) for x in range(4) for y in range(4) if x + y <= 3]


def _pois_k(mu: np.ndarray, kmax: int) -> np.ndarray:
    out = np.empty(mu.shape + (kmax + 1,))
    t = np.exp(-mu)
    for k in range(kmax + 1):
        out[..., k] = t
        t = t * mu / (k + 1)
    return out


def htft_regions(l1h, l1a, l2h, l2a, mult_h=None, mult_a=None, phi: float = 0.0, chunk: int = 4000,
                 kmax2: int = 20) -> np.ndarray:
    """İY sonucu × MS sonucu × B/C/A bölgesi olasılık kütleleri, şekil (n, 3, 3, 5).

    Eksenler: İY sonucu (1, X, 2), MS sonucu (1, X, 2), bölge ``HTFT_REGIONS``. Yapı ``joint_regions`` ile
    aynıdır (İY ızgarası × İY durumuna koşullu 2Y Poisson'ları × gama kırılganlığı); bölge toplamları
    ``joint_regions`` ile birebir uyuşur. İY ızgarası dışındaki kuyruk kütlesi (``joint_regions['tail']``)
    bu diziye DAHİL DEĞİLDİR: toplam = 1 − kuyruk. 2Y gol farkı dağılımı takım başına ``kmax2`` gole kadar
    hesaplanır (kesme hatası ihmal edilebilir düzeydedir).
    """
    l1h, l1a, l2h, l2a = (np.asarray(v, dtype=float) for v in (l1h, l1a, l2h, l2a))
    n = len(l1h)
    mh = np.ones(N_STATES) if mult_h is None else np.asarray(mult_h, dtype=float)
    ma = np.ones(N_STATES) if mult_a is None else np.asarray(mult_a, dtype=float)
    out = np.zeros((n, 3, 3, 5))
    nodes, weights = frailty_nodes(phi)
    K = kmax2
    d = FLAT_I - FLAT_J
    idx0 = K - d  # P(X−Y = −d) dizini
    for s in range(0, n, chunk):
        e = min(n, s + chunk)
        m = e - s
        for g, wg in zip(nodes, weights):
            P = (_poisson_grid(g * l1h[s:e])[:, :, None] * _poisson_grid(g * l1a[s:e])[:, None, :]).reshape(m, -1)
            ph = _pois_k((g * l2h[s:e])[:, None] * mh[None, :], K)  # (m, 9, K+1)
            pa = _pois_k((g * l2a[s:e])[:, None] * ma[None, :], K)
            D = np.zeros((m, N_STATES, 2 * K + 1))  # P(X − Y = j − K)
            for j in range(-K, K + 1):
                if j >= 0:
                    D[..., j + K] = (ph[..., j:] * pa[..., :K + 1 - j]).sum(-1)
                else:
                    D[..., j + K] = (ph[..., :K + 1 + j] * pa[..., -j:]).sum(-1)
            F = np.cumsum(D, axis=-1)
            pX = D[:, STATE, idx0]
            p2 = F[:, STATE, idx0 - 1]
            p1 = 1.0 - F[:, STATE, idx0]
            ft = np.stack([p1, pX, p2], axis=-1)  # (m, 121, 3) P(MS = k | İY hücresi)
            phc, pac = ph[:, STATE, :], pa[:, STATE, :]
            notb = np.zeros_like(ft)  # 2Y toplamı ≤ 3 − İY toplamı (B gerçekleşmez)
            for x, y in _SMALL:
                ok = (x + y) <= (3 - TOTAL_H1)
                if not ok.any():
                    continue
                fd = d + x - y
                kk = np.where(fd > 0, 0, np.where(fd == 0, 1, 2))
                pr = phc[:, :, x] * pac[:, :, y] * ok
                for k in range(3):
                    notb[:, :, k] += pr * (kk == k)
            withb = ft - notb
            # A hücreleri (İY'de iki takım da gol attı): P(MS = k ∧ 2Y ev ≥ 1 ∧ 2Y dep ≥ 1), içerme-dışlama
            cy, cx = np.cumsum(pac, axis=-1), np.cumsum(phc, axis=-1)

            def cdf(c, t):
                t = np.broadcast_to(t, d.shape)
                idx = np.broadcast_to(np.clip(t, 0, K)[None, :, None], (c.shape[0], d.size, 1))
                v = np.take_along_axis(c, idx, axis=-1)[..., 0]
                return np.where(t[None, :] < 0, 0.0, v)

            e_h, e_a = phc[:, :, 0], pac[:, :, 0]
            y_dm1, y_d = cdf(cy, d - 1), cdf(cy, d)
            x0 = np.stack([y_dm1, y_d - y_dm1, 1.0 - y_d], -1) * e_h[..., None]  # 2Y ev golü yok
            x_md, x_mdm1 = cdf(cx, -d), cdf(cx, -d - 1)
            y0 = np.stack([1.0 - x_md, x_md - x_mdm1, x_mdm1], -1) * e_a[..., None]  # 2Y dep golü yok
            s0 = np.stack([d > 0, d == 0, d < 0], -1)[None].astype(float) * (e_h * e_a)[..., None]
            apart = (ft - x0 - y0 + s0) * _A_CELL[None, :, None]
            reg5 = np.stack([
                apart * _C_CELL[None, :, None],
                (withb - apart) * _C_CELL[None, :, None],
                withb * ~_C_CELL[None, :, None],
                notb * _C_CELL[None, :, None],
                notb * ~_C_CELL[None, :, None],
            ], axis=-1)  # (m, 121, 3, 5)
            contrib = (wg * P)[:, :, None, None] * reg5
            for h in range(3):
                out[s:e, h] += contrib[:, _HT_IDX == h].sum(axis=1)
    return out

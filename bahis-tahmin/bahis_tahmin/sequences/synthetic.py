"""YALNIZCA TEST/DEMO: bilinen olasılıklarla sentetik çok ligli maç verisi ve araştırma çerçevesi.

Gerçek veri yerine geçmez; arayüzde veya raporlarda gerçek sonuç gibi gösterilmez. Gerçek İY/MS olasılıkları
(üretici model) kesin bilindiği için referans sürecin ve çoklu test kontrolünün kalibrasyonu sınanabilir.
İsteğe bağlı ``comeback_boost``: takımın bir önceki maçı "İY geride → MS galip" ise o takımın ikinci yarı gol
yoğunluğu çarpılır (bilinen bir dizi etkisi — güç testi için).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import poisson

from ..goals.markets import HTFT_KEYS

SYNTH_SOURCE = "SENTETIK-TEST"
_G = np.arange(11)


def _htft_exact(l1h, l1a, l2h, l2a) -> np.ndarray:
    """Bağımsız yarı Poisson'ları için 9 İY/MS hücresinin kesin olasılıkları (HTFT_KEYS sırası)."""
    p1h, p1a, p2h, p2a = (poisson.pmf(_G, v) for v in (l1h, l1a, l2h, l2a))
    H1 = np.outer(p1h, p1a)
    H2 = np.outer(p2h, p2a)
    d1 = np.subtract.outer(_G, _G)  # İY farkı
    d2 = np.subtract.outer(_G, _G)
    # 2Y fark dağılımı
    dist2 = {}
    for dv in range(-10, 11):
        dist2[dv] = H2[d2 == dv].sum()
    out = np.zeros((3, 3))
    for dv1 in range(-10, 11):
        p1 = H1[d1 == dv1].sum()
        hi = 0 if dv1 > 0 else (1 if dv1 == 0 else 2)
        for dv2, p2 in dist2.items():
            ft = dv1 + dv2
            fi = 0 if ft > 0 else (1 if ft == 0 else 2)
            out[hi, fi] += p1 * p2
    out /= out.sum()
    return out.ravel()


def _double_round_robin(n: int, rng) -> list[tuple[int, int, int]]:
    """Çember yöntemiyle çift devreli fikstür: (tur, ev, deplasman); her takım her turda tam bir maç oynar."""
    order = list(rng.permutation(n))
    rounds = []
    for r in range(n - 1):
        pairs = [(order[k], order[n - 1 - k]) for k in range(n // 2)]
        pairs = [(a, b) if (r + k) % 2 == 0 else (b, a) for k, (a, b) in enumerate(pairs)]
        rounds.append(pairs)
        order = [order[0]] + [order[-1]] + order[1:-1]
    out = []
    for r, pairs in enumerate(rounds):
        out += [(r, a, b) for a, b in pairs]
    for r, pairs in enumerate(rounds):
        out += [(r + n - 1, b, a) for a, b in pairs]
    return out


def synthetic_matches(n_leagues: int = 2, n_seasons: int = 26, n_teams: int = 10, start_year: int = 2000, seed: int = 0,
                      comeback_boost: float = 1.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(maçlar, kesin_olasılıklar) — olasılık tablosu: event_id-uyumlu anahtarlar + 9 hücre (EV perspektifi).

    ``comeback_boost`` ≠ 1 ise kesin olasılıklar o etkiyi İÇERMEZ (temel model etkiyi bilmez); bu, gerçek bir
    dizi etkisinin "S0'a ek bilgi" olarak bulunup bulunamadığını sınamak içindir.
    """
    from ..data.leagues import season_label
    from ..goals.ledger import event_id

    rng = np.random.default_rng(seed)
    codes = ["T1", "N1", "E0", "D1"][:n_leagues]
    rows, probs = [], []
    for lg in codes:
        teams = [f"{lg}-Takım {chr(65 + i)}" for i in range(n_teams)]
        att = rng.normal(0, 0.25, n_teams)
        dfn = rng.normal(0, 0.25, n_teams)
        last_comeback = {t: False for t in teams}
        for s in range(n_seasons):
            year = start_year + s
            date0 = pd.Timestamp(year, 8, 10)
            att += rng.normal(0, 0.05, n_teams)  # güçler yavaşça değişir
            for rnd, i, j in _double_round_robin(n_teams, rng):
                d = date0 + pd.Timedelta(days=7 * rnd)
                lam = np.exp(0.3 + 0.15 + att[i] - dfn[j])
                nu = np.exp(0.3 + att[j] - dfn[i])
                l1h, l1a, l2h, l2a = 0.45 * lam, 0.45 * nu, 0.55 * lam, 0.55 * nu
                p = _htft_exact(l1h, l1a, l2h, l2a)
                b_h = comeback_boost if last_comeback[teams[i]] else 1.0
                b_a = comeback_boost if last_comeback[teams[j]] else 1.0
                hh, ha = rng.poisson(l1h), rng.poisson(l1a)
                fh, fa = hh + rng.poisson(l2h * b_h), ha + rng.poisson(l2a * b_a)
                last_comeback[teams[i]] = bool(hh < ha and fh > fa)
                last_comeback[teams[j]] = bool(ha < hh and fa > fh)
                rows.append({"league": lg, "season": season_label(year), "date": d, "time": "", "home": teams[i],
                             "away": teams[j], "fthg": fh, "ftag": fa, "hthg": float(hh), "htag": float(ha),
                             "source": SYNTH_SOURCE})
                probs.append({"event_id": event_id(lg, d, teams[i], teams[j]), **dict(zip(HTFT_KEYS, p))})
    m = pd.DataFrame(rows)
    from ..data.parsers import MATCH_COLUMNS

    for c in MATCH_COLUMNS:
        if c not in m.columns:
            m[c] = np.nan
    m = m[MATCH_COLUMNS].sort_values("date", kind="mergesort").reset_index(drop=True)
    return m, pd.DataFrame(probs)


def synthetic_frame(seed: int = 0, comeback_boost: float = 1.0, **kw):
    """Sentetik maçlardan araştırma çerçevesi; S0 yerine üretici modelin kesin olasılıkları kullanılır."""
    from .frame import build_frame
    from .timeline import build_team_matches

    m, probs = synthetic_matches(seed=seed, comeback_boost=comeback_boost, **kw)
    tm = build_team_matches(m)
    fr = build_frame(tm, probs)
    fr.meta["synthetic"] = True
    return fr, m, probs

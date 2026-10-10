"""Referans süreç (§7), Westfall–Young adım adım azalan maxT, Benjamini–Yekutieli (tanımlayıcı) ve plasebo (§9 F7).

Referans süreç: değerlendirilen dönemdeki her maç için kalibre 9 İY/MS hücresinden TEK sonuç çekilir (iki takım
satırı tutarlı); diğer bütün maçlar gerçek sonuçlarını korur (gerçek geçmişe koşullu); gerçekte bilinmeyen
satırlar çekimden sonra yeniden "bilinmiyor" yapılır (İY yok → İY −1; MS yok/hükmen olabilir → ikisi −1).
Güç, ev/deplasman, lig, sezon, takvim ve beklenen puan (``fr.exp_points``) aynen kalır. Dizi atomları, hedefler
ve destek filtresi her tekrarda simüle kodlardan yeniden hesaplanır; arama sürecinin tamamı yeniden çalışır.
Gol sütunları (gf_*/ga_*) hiç okunmaz.

Sınır: referans S0'ın doğru olduğunu varsayar; S0'ın takım-sezon düzeyi hataları referansta yoktur (gerçek
veride CR1 varyans bunu hesaba katar).
"""

from __future__ import annotations

from typing import Callable

import numpy as np
from scipy.stats import beta, norm

from . import config as C
from . import patterns as P
from .features import history_atoms, outcome_codes
from .frame import target_outcomes
from .timeline import RAW_TO_TEAM_CELL

_HOME_MAP = np.array([RAW_TO_TEAM_CELL[i][0] for i in range(9)], dtype=np.int8)
_AWAY_MAP = np.array([RAW_TO_TEAM_CELL[i][1] for i in range(9)], dtype=np.int8)
PLACEBO_DECILES = getattr(C, "PLACEBO_DECILES", 10)  # §9 F7: S0 güç ondalığı


# ----------------------------------------------------------------------------
# Simülasyon
# ----------------------------------------------------------------------------

def simulation_pairs(fr, mask) -> np.ndarray:
    """Değerlendirilen dönemin maçları (pair_id üzerinde bool): maske satırlarının sezon yıllarındaki tüm maçlar."""
    tm = fr.tm
    pair = tm["pair_id"].to_numpy()
    years = np.unique(tm["season_year"].to_numpy()[np.asarray(mask, dtype=bool)])
    in_period = np.isin(tm["season_year"].to_numpy(), years)
    out = np.zeros(int(pair.max()) + 1, dtype=bool)
    out[pair[in_period]] = True
    return out


class _Sim:
    """Simülasyon için sabit yapılar (maç → satırlar, birikimli olasılıklar, gerçek bilinmeyen deseni)."""

    def __init__(self, fr, sim_mask_pairs: np.ndarray, real_codes: tuple[np.ndarray, np.ndarray] | None = None):
        tm = fr.tm
        pair = tm["pair_id"].to_numpy().astype(np.int64)
        home = tm["is_home"].to_numpy().astype(bool)
        n_pairs = int(pair.max()) + 1
        home_row = np.full(n_pairs, -1, dtype=np.int64)
        away_row = np.full(n_pairs, -1, dtype=np.int64)
        home_row[pair[home]] = np.where(home)[0]
        away_row[pair[~home]] = np.where(~home)[0]
        sim = np.zeros(n_pairs, dtype=bool)
        sm = np.asarray(sim_mask_pairs, dtype=bool)
        sim[:len(sm)] = sm[:n_pairs]
        sim &= (home_row >= 0) & (away_row >= 0)
        probs = np.asarray(fr.raw_probs, dtype=float)[np.where(sim, home_row, 0)]
        tot = probs.sum(axis=1)
        sim &= np.isfinite(probs).all(axis=1) & (tot > 0)  # S0 yoksa gerçek sonuç kalır
        ids = np.where(sim)[0]
        pr = np.clip(probs[ids], 0.0, None)
        cum = np.cumsum(pr / pr.sum(axis=1, keepdims=True), axis=1)
        cum[:, -1] = 1.0
        self.cum = cum
        self.home_rows = home_row[ids]
        self.away_rows = away_row[ids]
        ht, ft = outcome_codes(tm) if real_codes is None else real_codes
        self.real_ht, self.real_ft = ht.astype(np.int8), ft.astype(np.int8)
        rows = np.r_[self.home_rows, self.away_rows]
        self.ht_unknown = rows[(self.real_ht[rows] < 0) | (self.real_ft[rows] < 0)]
        self.ft_unknown = rows[self.real_ft[rows] < 0]
        self.n_sim = len(ids)

    def draw(self, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        u = rng.random(self.n_sim)
        raw = (self.cum < u[:, None]).sum(axis=1)
        raw = np.minimum(raw, 8)
        hc, ac = _HOME_MAP[raw], _AWAY_MAP[raw]
        ht, ft = self.real_ht.copy(), self.real_ft.copy()
        ht[self.home_rows], ft[self.home_rows] = hc // 3, hc % 3
        ht[self.away_rows], ft[self.away_rows] = ac // 3, ac % 3
        ht[self.ht_unknown] = -1
        ft[self.ft_unknown] = -1
        return ht, ft


def simulate_codes(fr, sim_mask_pairs: np.ndarray, rng: np.random.Generator,
                   real_codes: tuple[np.ndarray, np.ndarray] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Simüle takım İY ve MS kodları (tm'ye hizalı; 0=G, 1=B, 2=M, −1 bilinmiyor).

    ``sim_mask_pairs``: pair_id üzerinde bool (``simulation_pairs``). Seçili maçlar için ``fr.raw_probs``
    (yeniden normalize) üzerinden tek ham hücre; iki satır ``RAW_TO_TEAM_CELL`` ile türetilir. Diğer maçlar gerçek.
    """
    return _Sim(fr, sim_mask_pairs, real_codes).draw(rng)


def _seed_seq(seed) -> np.random.SeedSequence:
    """Taze SeedSequence: verilen nesne kopyalanır (``spawn`` nesneyi değiştirir; aynı nesneyle iki çağrı farklı
    tekrarlar üretmesin — aynı tohum birebir aynı sonuç)."""
    if isinstance(seed, np.random.SeedSequence):
        return np.random.SeedSequence(seed.entropy, spawn_key=seed.spawn_key, pool_size=seed.pool_size)
    return np.random.SeedSequence(int(seed))


# ----------------------------------------------------------------------------
# Sorgu 1 referans dağılımı
# ----------------------------------------------------------------------------

def _rep_indices(R: int, reps) -> list[int]:
    """Çalıştırılacak tekrar indeksleri (paralel parçalar için alt küme); 0 ≤ r < R."""
    if reps is None:
        return list(range(int(R)))
    out = [int(r) for r in reps]
    if any(r < 0 or r >= R for r in out):
        raise ValueError(f"tekrar indeksi 0..{R - 1} dışında")
    return out


def run_null(fr, mask, R: int = C.N_NULL, seed=C.SEED, conditions=None, targets=C.TARGETS_Q1,
             prep: P.Prep | None = None, hyp_ids: list[str] | None = None,
             atoms_fn: Callable = history_atoms, progress: Callable | None = None, min_n: float = C.MIN_N,
             min_e: float = C.MIN_E, sim_pairs: np.ndarray | None = None, reps=None) -> dict:
    """R tekrar: simüle kodlardan dizi atomları (sabit ``fr.exp_points``) ve hedefler, aynı katman/küme ve destek
    filtresiyle tam arama. Dönüş: ``z``, ``supported``, ``T`` (len(reps) × H; ``reps`` yoksa R × H), ``hyp_ids``.

    Tekrar r'nin rastgele akışı ``SeedSequence(seed).spawn(R)[r]`` → aynı tohum birebir aynı sonuç.
    ``reps`` (ör. ``range(a, b)``): yalnızca bu tekrarlar çalışır, satırlar ``reps`` sırasındadır; parçaların
    birleşimi tek çalıştırmayla birebir aynıdır (paralel işçi sayısından bağımsız).
    ``atoms_fn(si, ht, ft, exp_points)`` dizi atomlarını döndürür (plasebo için bağış eşlemeli sürüm).
    """
    if prep is None:
        prep = P.prepare(fr, mask, conditions, targets)
    else:
        P.check_prep_mask(prep, mask)  # simülasyon dönemi maskeden; prep başka maskeyle kurulmuşsa uyuşmaz
    all_ids = prep.hyp_ids
    if hyp_ids is None:
        cols = np.arange(len(all_ids))
        hyp_ids = all_ids
    else:
        where = {h: j for j, h in enumerate(all_ids)}
        cols = np.array([where[h] for h in hyp_ids], dtype=np.int64)
    sim = _Sim(fr, simulation_pairs(fr, mask) if sim_pairs is None else sim_pairs)
    fixed = {k: v for k, v in fr.atoms.items() if k in C.CONTEXT_ATOMS}
    children = _seed_seq(seed).spawn(R)
    run = _rep_indices(R, reps)
    H = len(cols)
    Z = np.full((len(run), H), np.nan)
    S = np.zeros((len(run), H), dtype=bool)
    T = np.full((len(run), H), np.nan)
    for k, r in enumerate(run):
        ht, ft = sim.draw(np.random.default_rng(children[r]))
        atoms = dict(fixed)
        atoms.update(atoms_fn(fr.seq, ht, ft, fr.exp_points))
        X, N = P.atom_matrices(prep, atoms)
        ys = target_outcomes(fr.tm, ht[prep.idx], ft[prep.idx])
        res = P._core(prep, X, N, ys, min_n, min_e)
        Z[k], S[k], T[k] = res["z"][cols], res["supported"][cols], res["T"][cols]
        if progress is not None:
            progress(k + 1, len(run))
    return {"z": Z, "supported": S, "T": T, "hyp_ids": list(hyp_ids), "R": R, "reps": run}


# ----------------------------------------------------------------------------
# Çoklu test
# ----------------------------------------------------------------------------

def clopper_pearson(k: np.ndarray, n: int, level: float = C.MC_CI_LEVEL) -> tuple[np.ndarray, np.ndarray]:
    k = np.asarray(k, dtype=float)
    a = 1.0 - level
    lo = np.where(k > 0, beta.ppf(a / 2, np.maximum(k, 1e-300), n - k + 1), 0.0)
    hi = np.where(k < n, beta.ppf(1 - a / 2, k + 1, np.maximum(n - k, 1e-300)), 1.0)
    return lo, hi


def westfall_young_stepdown(z_obs, supported_obs, z_null, supported_null,
                            include_unsupported_obs: bool = True) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Adım adım azalan maxT (|z|) ile FWER düzeltilmiş p ve Monte Carlo Clopper–Pearson aralığı.

    Aile = gözlenen veride desteklenen hipotezler; |z| azalan sırada h_(1..m). Tekrar r'de adım j'nin eşiği
    max{|z*_r,h| : h ∈ {h_(j..m)} ve tekrarda desteklenen}. Tekrarda desteklenmeyen hipotez o tekrarın maksimumuna
    girmez. ``include_unsupported_obs`` (varsayılan): gözlenen veride desteklenmeyen ama tekrarda desteklenen
    hipotezler de her adımın maksimumuna girer (tekrarın kendi tam araması; reddedilemedikleri için hep kalanlar
    kümesindedir — muhafazakâr). p_j = (c_j + 1)/(R + 1), c_j = #{r: eşik ≥ |z_(j)|}; monotonluk c'de kümülatif
    maksimumla sağlanır. Aralık: c/R için Clopper–Pearson (``config.MC_CI_LEVEL``). Aile dışı hipotezler NaN.
    """
    z_obs = np.asarray(z_obs, dtype=float)
    fam = np.asarray(supported_obs, dtype=bool) & np.isfinite(z_obs)
    Zn = np.asarray(z_null, dtype=float)
    Sn = np.asarray(supported_null, dtype=bool) & np.isfinite(Zn)
    R = Zn.shape[0]
    A = np.where(Sn, np.abs(Zn), -np.inf)
    p_adj = np.full(len(z_obs), np.nan)
    lo = np.full(len(z_obs), np.nan)
    hi = np.full(len(z_obs), np.nan)
    fam_idx = np.where(fam)[0]
    if len(fam_idx) == 0 or R == 0:
        return p_adj, lo, hi
    order = fam_idx[np.argsort(-np.abs(z_obs[fam_idx]), kind="mergesort")]
    q = np.maximum.accumulate(A[:, order][:, ::-1], axis=1)[:, ::-1]  # R × m ardışık maksimumlar
    if include_unsupported_obs and (~fam).any():
        extra = A[:, ~fam].max(axis=1)
        q = np.maximum(q, extra[:, None])
    counts = (q >= np.abs(z_obs[order])[None, :]).sum(axis=0)
    counts = np.maximum.accumulate(counts)
    p_adj[order] = (counts + 1.0) / (R + 1.0)
    l, h = clopper_pearson(counts, R)
    lo[order], hi[order] = l, h
    return p_adj, lo, hi


def by_descriptive(z) -> np.ndarray:
    """Benjamini–Yekutieli düzeltilmiş p (iki yönlü normal p'ler üzerinden; YALNIZCA tanımlayıcı)."""
    z = np.asarray(z, dtype=float)
    p = 2.0 * norm.sf(np.abs(z))
    out = np.full(len(z), np.nan)
    fin = np.where(np.isfinite(p))[0]
    m = len(fin)
    if m == 0:
        return out
    cm = float(np.sum(1.0 / np.arange(1, m + 1)))
    order = fin[np.argsort(p[fin], kind="mergesort")]
    raw = p[order] * m * cm / np.arange(1, m + 1)
    adj = np.minimum.accumulate(raw[::-1])[::-1]
    out[order] = np.minimum(adj, 1.0)
    return out


# ----------------------------------------------------------------------------
# Sorgu 2 referans dağılımı
# ----------------------------------------------------------------------------

def run_null_q2(fr, mask, R: int = C.N_NULL, seed=C.SEED, progress: Callable | None = None,
                sim_pairs: np.ndarray | None = None, reps=None) -> dict:
    """Sorgu 2'nin 6 hipotezi için aynı referans süreç (olaylar ve sonuçlar simüle kodlardan yeniden).

    ``reps``: ``run_null`` ile aynı anlam (tekrar r → ``SeedSequence(seed).spawn(R)[r]``)."""
    prep = P.q2_prepare(fr, mask)
    sim = _Sim(fr, simulation_pairs(fr, mask) if sim_pairs is None else sim_pairs)
    children = _seed_seq(seed).spawn(R)
    run = _rep_indices(R, reps)
    Z = np.full((len(run), len(P.Q2_HYP_IDS)), np.nan)
    S = np.zeros((len(run), len(P.Q2_HYP_IDS)), dtype=bool)
    for k, r in enumerate(run):
        ht, ft = sim.draw(np.random.default_rng(children[r]))
        res = P._q2_core(fr, prep, ht, ft)
        Z[k] = [d["z"] for d in res]
        S[k] = [d["supported"] for d in res]
        if progress is not None:
            progress(k + 1, len(run))
    return {"z": Z, "supported": S, "hyp_ids": list(P.Q2_HYP_IDS), "R": R, "reps": run}


# ----------------------------------------------------------------------------
# Plasebo negatif kontrol (F7)
# ----------------------------------------------------------------------------

def placebo_donors(fr, rng: np.random.Generator, deciles: int = PLACEBO_DECILES) -> np.ndarray:
    """Her satır için bağışçı satır: aynı lig-sezon, farklı takım ve rakip olmayan; en yakın S0 galibiyet ondalığı,
    sonra en yakın tarih; kalan eşitlikler rastgele (tohuma bağlı). Bağışçısı olmayan satır −1.

    Zaman güvenliği (§4): bağışçının tarihi satırın tarihinden SONRA olamaz. Daha sonraki bir bağışçının atomları
    satırın maç gününü ve sonrasını içerir; özellikle bağışçının rakibi satırın takımı veya rakibiyse ``RAKIP_*``
    atomları satırın kendi hedef sonucunu taşır. Aynı gün bağışçısı güvenlidir (atomlar önceki günlerden; aynı gün
    bağışçının rakibi satırın takımı veya rakibi olamaz)."""
    tm = fr.tm
    n = len(tm)
    pw = np.asarray(fr.p_win, dtype=float)
    ok = np.isfinite(pw)
    dec = P._bins(np.nan_to_num(pw), ok, deciles)
    days = ((tm["date"] - tm["date"].min()).dt.days).to_numpy().astype(np.int64)
    names = np.r_[tm["team"].astype(str).to_numpy(), tm["opponent"].astype(str).to_numpy()]
    codes, _ = P._codes(names)
    team, opp = codes[:n], codes[n:]
    cl, _ = P._codes(np.asarray(fr.cluster))
    donor = np.full(n, -1, dtype=np.int64)
    order = np.argsort(cl, kind="mergesort")
    bounds = np.r_[0, np.cumsum(np.bincount(cl))]
    big = float(days.max() + 10) if n else 1.0
    for g in range(len(bounds) - 1):  # lig-sezonlar üzerinde döngü (kurulum; sıcak yol değil)
        rows = order[bounds[g]:bounds[g + 1]]
        rows = rows[ok[rows]]
        if len(rows) < 2:
            continue
        prio = rng.random(len(rows)) * 0.5
        dist = (np.abs(dec[rows][:, None] - dec[rows][None, :]) * big
                + np.abs(days[rows][:, None] - days[rows][None, :]) + prio[None, :])
        bad = (team[rows][None, :] == team[rows][:, None]) | (team[rows][None, :] == opp[rows][:, None])
        bad |= days[rows][None, :] > days[rows][:, None]  # bağışçı satırdan sonra oynanamaz
        dist[bad] = np.inf
        j = np.argmin(dist, axis=1)
        good = np.isfinite(dist[np.arange(len(rows)), j])
        donor[rows[good]] = rows[j[good]]
    return donor


def _map_atoms(atoms: dict, donor: np.ndarray) -> dict:
    out = {}
    for k, v in atoms.items():
        x = np.asarray(v, dtype=float)[np.clip(donor, 0, None)]
        x[donor < 0] = np.nan
        out[k] = x
    return out


def placebo_atoms(fr, rng: np.random.Generator) -> tuple[dict, np.ndarray]:
    """(plasebo atomları, bağışçı dizisi): dizi atomları bağışçının atomlarıyla değiştirilir; bağlam atomları kendi."""
    donor = placebo_donors(fr, rng)
    atoms = _map_atoms({k: fr.atoms[k] for k in C.HISTORY_ATOMS}, donor)
    atoms.update({k: fr.atoms[k] for k in C.CONTEXT_ATOMS if k in fr.atoms})
    return atoms, donor


def run_placebo(fr, mask, seeds=None, R: int = C.N_NULL_PLACEBO, conditions=None, targets=C.TARGETS_Q1,
                hyp_ids: list[str] | None = None, min_n: float = C.MIN_N, min_e: float = C.MIN_E,
                progress: Callable | None = None) -> dict:
    """Plasebo: gerçek sonuçlar + gerçek S0, bağışçı atomlarıyla tam arama + WY (her tohumda R tekrar).

    Referans tekrarlarında bağışçıların atomları simüle kodlardan yeniden hesaplanır (aynı bağış eşlemesi).
    Geçme kuralı: keşif çıkan tohum sayısı ≤ ``config.PLACEBO_MAX_DISCOVERIES``.
    """
    if seeds is None:
        seeds = [C.SEED + 1000 + k for k in range(C.N_PLACEBO_SEEDS)]
    prep = P.prepare(fr, mask, conditions, targets)
    all_ids = prep.hyp_ids
    ids = all_ids if hyp_ids is None else list(hyp_ids)
    cols = np.array([all_ids.index(h) for h in ids], dtype=np.int64)
    sim_pairs = simulation_pairs(fr, mask)
    out = []
    for k, seed in enumerate(seeds):
        ss_donor, ss_null = np.random.SeedSequence(int(seed)).spawn(2)
        atoms, donor = placebo_atoms(fr, np.random.default_rng(ss_donor))
        X, N = P.atom_matrices(prep, atoms)
        ys = {t: np.asarray(fr.y[t], dtype=float)[prep.idx] for t in prep.targets}
        obs = P._core(prep, X, N, ys, min_n, min_e)

        def atoms_fn(si, ht, ft, ep, _d=donor):
            return _map_atoms(history_atoms(si, ht, ft, ep), _d)

        null = run_null(fr, mask, R, ss_null, prep=prep, hyp_ids=ids, atoms_fn=atoms_fn, min_n=min_n, min_e=min_e,
                        sim_pairs=sim_pairs)
        p_adj, lo, hi = westfall_young_stepdown(obs["z"][cols], obs["supported"][cols], null["z"], null["supported"])
        disc = np.nan_to_num(p_adj, nan=1.0) < C.ALPHA
        strict = disc & (np.nan_to_num(hi, nan=1.0) < C.ALPHA)
        out.append({"seed": int(seed), "n_supported": int(obs["supported"][cols].sum()),
                    "n_discoveries": int(disc.sum()), "n_discoveries_strict": int(strict.sum()),
                    "discoveries": [ids[j] for j in np.where(disc)[0]],
                    "min_p_adj": float(np.nanmin(p_adj)) if np.isfinite(p_adj).any() else float("nan")})
        if progress is not None:
            progress(k + 1, len(seeds))
    n_with = sum(1 for d in out if d["n_discoveries"] > 0)
    return {"seeds": out, "R": R, "n_seeds": len(out), "n_seeds_with_discovery": n_with,
            "passed": n_with <= C.PLACEBO_MAX_DISCOVERIES,
            "not": f"Plasebo başına R = {R} referans tekrarı; keşif = WY p_adj < {C.ALPHA}."}

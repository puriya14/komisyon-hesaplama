"""Sorgu 1 örüntü motoru (§7), Mod B (§7a), yanlışlama listesi (§7b) ve Sorgu 2 (§7c).

Katmanlı istatistik (S0'a göre; sözleşme §7):
  katman s = taraf (ev/dep) × lig × hedefe özgü kalibre p0 beşlisi (değerlendirilen maske içinde).
  Geçerli küme (hipotez başına) = maskede, hedefi bilinen ve koşul atomları tanımlı satırlar; tanımsız atomlu
  satırlar koşulun hem içinden hem tümleyeninden çıkar. r_s = O_s/E_s (geçerli küme), E_adj = Σ_{i∈c} p_i·r_s,
  T = O − E_adj. Katmanlar sezonlar üzerinden birleştiği için kümelerin (lig-sezon) içinde yuvalanmaz; bu yüzden
  varyans T'nin TAM etki fonksiyonuyla hesaplanır: ψ_i = (1[i∈c] − E_cs/E_s)·(y_i − p_i·r_s), Σ_i ψ_i = T.
  V = G/(G−1)·Σ_g (Σ_{i∈g} ψ_i)² (CR1, lig-sezon kümeleri), z = T/√V.

Vektörleştirme: (küme × katman) hücreleri için atom çiftlerinin ağırlıklı Gram matrisleri tek bir seyrek çarpımla
alınır (hücre × atom yerleşim matrisi · ağırlıklı atom göstergeleri); her hipotezin hücre toplamları bu
matrisin (a, b) elemanıdır. Hipotez veya satır üzerinde Python döngüsü yoktur. Geçerlilik toplamları
"tanımsız" göstergelerinin (seyrek) Gram'ından içerme-dışlama ile bulunur. ``Prep`` nesnesi katman/küme
yapılarını saklar; referans süreç her tekrarda yalnızca atomları ve hedefleri değiştirir.
"""

from __future__ import annotations

import hashlib
import math
import warnings
from dataclasses import dataclass, field
from itertools import combinations, product
from typing import Sequence

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.stats import norm

from . import config as C
from .features import B as _B
from .features import G as _G
from .features import M as _M
from .features import outcome_codes
from .frame import TARGET_TEAM_CELLS
from .timeline import RAW_TO_TEAM_CELL

Q1_LABEL = "Sorgu 1 (maç öncesi)"
Q2_LABEL = "Sorgu 2 (olay sonrası)"
Q2_HYP_IDS: tuple[str, ...] = tuple(f"Q2|{ev}|{t}" for ev in C.Q2_EVENTS for t in C.Q2_TARGETS)
ATOM_NAMES: tuple[str, ...] = tuple(C.HISTORY_ATOMS) + tuple(C.CONTEXT_ATOMS)
PAIR_SEP = " & "
KIND_SINGLE, KIND_HH, KIND_HC = "tek", "dizi×dizi", "dizi×bağlam"

# Sözleşmede sayısı yazılı fakat config.py'de henüz bulunmayan sabitler: config'e eklenirse oradan okunur.
Z95 = getattr(C, "Z_95", 1.96)  # §7: oran ± 1,96·√V/E_c
TOP_DROP_SHARE = getattr(C, "FALSIFY_TOP_SHARE", 0.01)  # §7b.2
SEASON_SAME_DIR_SHARE = getattr(C, "FALSIFY_SEASON_SHARE", 0.60)  # §7b.3
MATCH_DECILES = getattr(C, "MATCH_DECILES", 10)  # §7: eşleştirilmiş karşılaştırma S0 ondalığı
N_COUNTER = getattr(C, "N_COUNTER_EXAMPLES", 20)  # §7a/§7b.6

_CARD_COLS = ("row_id", "event_id", "date", "league", "season", "team", "opponent", "is_home", "htft")


# ----------------------------------------------------------------------------
# Koşullar ve hipotezler
# ----------------------------------------------------------------------------

def build_conditions() -> list[tuple[str, tuple[str, ...]]]:
    """200 koşul (deterministik sıra): 16 tek dizi atomu, 120 dizi×dizi, 64 dizi×bağlam. Bağlam tek başına yok."""
    out = [(a, (a,)) for a in C.HISTORY_ATOMS]
    out += [(f"{a}{PAIR_SEP}{b}", (a, b)) for a, b in combinations(C.HISTORY_ATOMS, 2)]
    out += [(f"{a}{PAIR_SEP}{b}", (a, b)) for a, b in product(C.HISTORY_ATOMS, C.CONTEXT_ATOMS)]
    return out


def context_reference_conditions() -> list[tuple[str, tuple[str, ...]]]:
    """Yalnızca aday seçimindeki 'tek atomdan güçlü' karşılaştırması için bağlam atomlarının tek başına oranları.

    Bunlar hipotez ailesine GİRMEZ (bağlam tek başına koşul değildir; §7).
    """
    return [(a, (a,)) for a in C.CONTEXT_ATOMS]


def condition_kind(atoms: Sequence[str]) -> str:
    if len(atoms) == 1:
        return KIND_SINGLE
    return KIND_HC if any(a in C.CONTEXT_ATOMS for a in atoms) else KIND_HH


def hyp_id(target: str, condition: str) -> str:
    return f"{target}|{condition}"


def hypothesis_table(conditions=None, targets=C.TARGETS_Q1) -> pd.DataFrame:
    """Hipotez sırası (hedef-öncelikli): her hedef için koşullar ``build_conditions`` sırasında."""
    conditions = list(conditions or build_conditions())
    rows = [{"hyp_id": hyp_id(t, name), "target": t, "condition": name, "atoms": atoms,
             "kind": condition_kind(atoms)} for t in targets for name, atoms in conditions]
    return pd.DataFrame(rows)


def resolve_condition(condition) -> tuple[str, tuple[str, ...]]:
    """Koşul adı (``A & B``), atom demeti (``("A", "B")``) veya ``build_conditions`` öğesi (``(ad, atomlar)``)
    → (ad, atomlar)."""
    if isinstance(condition, str):
        atoms = tuple(a.strip() for a in condition.split(PAIR_SEP.strip()))
        return condition, atoms
    cond = tuple(condition)
    if len(cond) == 2 and isinstance(cond[0], str) and isinstance(cond[1], (tuple, list)):
        return cond[0], tuple(cond[1])
    if not all(isinstance(a, str) for a in cond):
        raise TypeError(f"Koşul anlaşılamadı: {condition!r}")
    return PAIR_SEP.join(cond), cond


# ----------------------------------------------------------------------------
# Katman/küme ön hesabı
# ----------------------------------------------------------------------------

def _bins(p: np.ndarray, ok: np.ndarray, nq: int) -> np.ndarray:
    """``ok`` satırlarındaki dağılıma göre nq eşit sıklık dilimi (0..nq−1); kesim noktası üst dilime gider."""
    q = np.zeros(len(p), dtype=np.int64)
    if ok.any():
        cuts = np.quantile(p[ok], np.arange(1, nq) / nq)
        q[ok] = np.searchsorted(cuts, p[ok], side="right")
    return q


def _codes(values) -> tuple[np.ndarray, np.ndarray]:
    codes, labels = pd.factorize(pd.Series(values).astype(str), sort=True)
    return codes.astype(np.int64), np.asarray(labels)


@dataclass
class TargetPrep:
    target: str
    p: np.ndarray  # maske satırlarında p0 (NaN → 0; ``ok`` dışında ağırlık 0)
    ok: np.ndarray
    stratum: np.ndarray  # satır → katman
    cell: np.ndarray  # satır → (küme × katman) hücresi
    K: int
    S: int
    cell_s: np.ndarray  # hücre → katman
    cell_g: np.ndarray  # hücre → küme
    agg_s: sparse.csr_matrix  # (S × K)
    agg_g: sparse.csr_matrix  # (G × K)


@dataclass
class Prep:
    """Değerlendirme maskesi için sabit yapılar (atom ve hedef değerlerinden bağımsız)."""

    idx: np.ndarray
    targets: tuple
    conditions: list
    atom_names: tuple
    a_idx: np.ndarray
    b_idx: np.ndarray
    cluster: np.ndarray
    cluster_labels: np.ndarray
    side: np.ndarray
    league: np.ndarray
    tp: dict = field(default_factory=dict)

    @property
    def hyp_ids(self) -> list[str]:
        return [hyp_id(t, name) for t in self.targets for name, _ in self.conditions]

    @property
    def n_hyp(self) -> int:
        return len(self.targets) * len(self.conditions)


def _target_prep(target: str, p_full: np.ndarray, idx: np.ndarray, cluster: np.ndarray, side: np.ndarray,
                 league: np.ndarray, n_clusters: int) -> TargetPrep:
    p = np.asarray(p_full, dtype=float)[idx]
    ok = np.isfinite(p)
    q = _bins(p, ok, C.N_QUINTILES)
    nq = C.N_QUINTILES
    s_key = np.where(ok, (league * 2 + side) * nq + q, -1)
    _, stratum = np.unique(s_key, return_inverse=True)
    stratum = stratum.astype(np.int64)
    # hücre = (küme, katman) çifti: kümeler ligde yuvalanmasa da (ör. duyarlılık kümeleri) hücre → katman tektir
    c_key = cluster.astype(np.int64) * (int(stratum.max()) + 1 if len(stratum) else 1) + stratum
    _, cell = np.unique(c_key, return_inverse=True)
    cell = cell.astype(np.int64)
    K, S = int(cell.max()) + 1 if len(cell) else 0, int(stratum.max()) + 1 if len(stratum) else 0
    cell_s = np.zeros(K, dtype=np.int64)
    cell_g = np.zeros(K, dtype=np.int64)
    cell_s[cell] = stratum
    cell_g[cell] = cluster
    ones = np.ones(K)
    agg_s = sparse.csr_matrix((ones, (cell_s, np.arange(K))), shape=(S, K))
    agg_g = sparse.csr_matrix((ones, (cell_g, np.arange(K))), shape=(n_clusters, K))
    return TargetPrep(target, np.where(ok, p, 0.0), ok, stratum, cell, K, S, cell_s, cell_g, agg_s, agg_g)


def prepare(fr, mask, conditions=None, targets=C.TARGETS_Q1, p0: dict | None = None) -> Prep:
    """Katman (taraf × lig × p0 beşlisi) ve küme (lig-sezon) yapıları; tekrar eden değerlendirmelerde
    yeniden kullanılır."""
    mask = np.asarray(mask, dtype=bool)
    idx = np.where(mask)[0]
    conditions = list(conditions or build_conditions())
    used = {a for _, atoms in conditions for a in atoms}
    names = tuple(a for a in ATOM_NAMES if a in used) + tuple(sorted(used - set(ATOM_NAMES)))
    pos = {a: j for j, a in enumerate(names)}
    a_idx = np.array([pos[atoms[0]] for _, atoms in conditions], dtype=np.int64)
    b_idx = np.array([pos[atoms[-1]] for _, atoms in conditions], dtype=np.int64)
    if any(len(atoms) > 2 for _, atoms in conditions):
        raise ValueError("Koşul uzunluğu en fazla 2 olabilir (§7)")
    cluster, cl_labels = _codes(np.asarray(fr.cluster)[idx])
    side = fr.tm["is_home"].to_numpy()[idx].astype(np.int64)
    league, _ = _codes(fr.tm["league"].to_numpy()[idx])
    prep = Prep(idx, tuple(targets), conditions, names, a_idx, b_idx, cluster, cl_labels, side, league)
    p0 = fr.p0 if p0 is None else p0
    for t in prep.targets:
        prep.tp[t] = _target_prep(t, p0[t], idx, cluster, side, league, len(cl_labels))
    return prep


def check_prep_mask(prep: Prep, mask) -> None:
    """Verilen ``prep`` başka bir maskeyle kurulmuşsa hata (sessizce yanlış dönemde değerlendirmeyi önler)."""
    if mask is None:
        return
    if not np.array_equal(np.flatnonzero(np.asarray(mask, dtype=bool)), prep.idx):
        raise ValueError("prep farklı bir değerlendirme maskesiyle kurulmuş")


def atom_matrices(prep: Prep, atoms: dict) -> tuple[np.ndarray, np.ndarray]:
    """(X, N): maske satırları × kullanılan atomlar; X = atom 1, N = atom tanımsız (NaN)."""
    n, m = len(prep.idx), len(prep.atom_names)
    X = np.zeros((n, m), dtype=bool)
    N = np.zeros((n, m), dtype=bool)
    for j, name in enumerate(prep.atom_names):  # atomlar üzerinde (≤ 20) döngü
        a = np.asarray(atoms[name], dtype=float)[prep.idx]
        X[:, j] = a == 1
        N[:, j] = ~np.isfinite(a)
    return X, N


# ----------------------------------------------------------------------------
# Vektörleştirilmiş çekirdek
# ----------------------------------------------------------------------------

def _cell_gram(cell: np.ndarray, K: int, M: np.ndarray, r: np.ndarray, a: np.ndarray, W: np.ndarray) -> np.ndarray:
    """G[k, a, w, b] = Σ_{i∈k} M_ia · W_iw · M_ib (tek seyrek çarpım)."""
    n, m = M.shape
    q = W.shape[1]
    P = sparse.csr_matrix((np.ones(len(r)), (cell[r] * m + a, r)), shape=(K * m, n))
    D = np.empty((n, q * m))
    Mf = M.astype(float)
    for w in range(q):
        np.multiply(Mf, W[:, w:w + 1], out=D[:, w * m:(w + 1) * m])
    return np.asarray(P @ D).reshape(K, m, q, m)


def _core(prep: Prep, X: np.ndarray, N: np.ndarray, ys: dict, min_n: float = C.MIN_N,
          min_e: float = C.MIN_E) -> dict[str, np.ndarray]:
    """Tüm hipotezler için katmanlı O, E, T, CR1 V, z (hedef-öncelikli sıra). ``ys``: maske satırlarına hizalı."""
    rX, aX = np.nonzero(X)
    rN, aN = np.nonzero(N)
    a, b = prep.a_idx, prep.b_idx
    keys = ("n", "O", "E_raw", "E_adj", "T", "V", "z", "n_valid", "G", "comparable_rate")
    out: dict[str, list] = {k: [] for k in keys}
    for t in prep.targets:
        tp = prep.tp[t]
        y = np.asarray(ys[t], dtype=float)
        yf = np.isfinite(y) & tp.ok
        W = np.column_stack([yf.astype(float), np.where(yf, y, 0.0), np.where(yf, tp.p, 0.0)])
        GX = _cell_gram(tp.cell, tp.K, X, rX, aX, W)
        GN = _cell_gram(tp.cell, tp.K, N, rN, aN, W)
        tot = np.column_stack([np.bincount(tp.cell, weights=W[:, w], minlength=tp.K) for w in range(3)])
        met = GX[:, a, :, b]  # (H, K, 3)
        val = tot[None, :, :] - GN[:, a, :, a] - GN[:, b, :, b] + GN[:, a, :, b]
        nc, Ac, Bc = (met[:, :, w].T for w in range(3))  # (K, H)
        nv, Ov, Ev = (val[:, :, w].T for w in range(3))
        S_ = tp.agg_s
        Os, Es, Ocs, Ecs, ncs, ns = (np.asarray(S_ @ v) for v in (Ov, Ev, Ac, Bc, nc, nv))
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.where(Es > 0, Os / np.where(Es > 0, Es, 1.0), 0.0)
            frac = np.where(Es > 0, Ecs / np.where(Es > 0, Es, 1.0), 0.0)
            rate = np.where(ns > 0, Os / np.where(ns > 0, ns, 1.0), 0.0)
        O = Ocs.sum(axis=0)
        n = ncs.sum(axis=0)
        E_raw = Ecs.sum(axis=0)
        E_adj = (Ecs * r).sum(axis=0)
        T = O - E_adj
        rc, fc = r[tp.cell_s], frac[tp.cell_s]
        psi = Ac - rc * Bc - fc * (Ov - rc * Ev)  # hücre toplamı Σ ψ_i
        U = np.asarray(tp.agg_g @ psi)
        Gh = (np.asarray(tp.agg_g @ nv) > 0).sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            V = np.where(Gh > 1, Gh / np.maximum(Gh - 1, 1) * (U ** 2).sum(axis=0), np.nan)
            z = np.where(V > 0, T / np.sqrt(np.where(V > 0, V, 1.0)), np.nan)
            comp = np.where(n > 0, (ncs * rate).sum(axis=0) / np.where(n > 0, n, 1.0), np.nan)
        for k, v in zip(keys, (n, O, E_raw, E_adj, T, V, z, nv.sum(axis=0), Gh, comp)):
            out[k].append(v)
    res = {k: np.concatenate(v) if v else np.zeros(0) for k, v in out.items()}
    res["supported"] = (res["n"] >= min_n) & (res["E_raw"] >= min_e) & np.isfinite(res["z"])
    return res


def evaluate(fr, mask, atoms: dict | None = None, y: dict | None = None, conditions=None,
             targets=C.TARGETS_Q1, prep: Prep | None = None, min_n: float = C.MIN_N, min_e: float = C.MIN_E,
             p0: dict | None = None) -> pd.DataFrame:
    """Her (hedef, koşul) için bir satır: katmanlı O/E, CR1 aralığı, z, destek ve tanılama oranları."""
    if prep is None:
        prep = prepare(fr, mask, conditions, targets, p0)
    else:
        check_prep_mask(prep, mask)
        if conditions is not None and list(conditions) != prep.conditions:
            raise ValueError("prep farklı bir koşul listesiyle kurulmuş")
    atoms = fr.atoms if atoms is None else atoms
    y = fr.y if y is None else y
    X, N = atom_matrices(prep, atoms)
    ys = {t: np.asarray(y[t], dtype=float)[prep.idx] for t in prep.targets}
    r = _core(prep, X, N, ys, min_n, min_e)
    df = hypothesis_table(prep.conditions, prep.targets)
    for k in ("n", "O", "E_raw", "E_adj", "T", "V", "z", "n_valid", "G", "comparable_rate", "supported"):
        df[k] = r[k]
    with np.errstate(divide="ignore", invalid="ignore"):
        se = np.sqrt(df["V"].to_numpy()) / df["E_adj"].to_numpy()
        lift = df["O"].to_numpy() / df["E_adj"].to_numpy()
        df["lift"] = lift
        df["lift_lo"] = np.clip(lift - Z95 * se, 0.0, None)
        df["lift_hi"] = lift + Z95 * se
        df["abs_diff"] = (df["O"] - df["E_adj"]) / df["n"]
        df["raw_rate"] = df["O"] / df["n"]
        df["oe_raw"] = df["O"] / df["E_raw"]
    df["p_norm"] = 2.0 * norm.sf(np.abs(df["z"].to_numpy()))
    df["n"] = df["n"].round().astype(np.int64)
    df["n_valid"] = df["n_valid"].round().astype(np.int64)
    df["sorgu"] = Q1_LABEL
    return df


# ----------------------------------------------------------------------------
# Tek hipotez yardımcıları (yanlışlama, Mod B)
# ----------------------------------------------------------------------------

def _strat_single(p, y, c, v, stratum, cluster) -> dict:
    """Tek hipotez için katmanlı istatistik (bincount; ``v`` geçerli küme, ``c`` koşul ⊂ v)."""
    v = v & np.isfinite(p) & np.isfinite(y)
    c = c & v
    S = int(stratum.max()) + 1 if len(stratum) else 1
    yv, pv = np.where(v, y, 0.0), np.where(v, p, 0.0)
    Os = np.bincount(stratum, weights=yv, minlength=S)
    Es = np.bincount(stratum, weights=pv, minlength=S)
    Ecs = np.bincount(stratum, weights=np.where(c, pv, 0.0), minlength=S)
    r = np.divide(Os, Es, out=np.zeros(S), where=Es > 0)
    frac = np.divide(Ecs, Es, out=np.zeros(S), where=Es > 0)
    O = float(yv[c].sum())
    n = int(c.sum())
    E_raw = float(pv[c].sum())
    E_adj = float((Ecs * r).sum())
    T = O - E_adj
    psi = np.where(v, (c.astype(float) - frac[stratum]) * (yv - pv * r[stratum]), 0.0)
    G = int(cluster.max()) + 1 if len(cluster) else 1
    U = np.bincount(cluster, weights=psi, minlength=G)
    Gh = int((np.bincount(cluster, weights=v.astype(float), minlength=G) > 0).sum())
    V = Gh / (Gh - 1) * float((U ** 2).sum()) if Gh > 1 else float("nan")
    z = T / math.sqrt(V) if V > 0 else float("nan")
    lift = O / E_adj if E_adj > 0 else float("nan")
    se = math.sqrt(V) / E_adj if (E_adj > 0 and V >= 0) else float("nan")
    return {"n": n, "O": O, "E_raw": E_raw, "E_adj": E_adj, "T": T, "V": V, "z": z, "lift": lift,
            "lift_lo": max(lift - Z95 * se, 0.0) if np.isfinite(se) else float("nan"),
            "lift_hi": lift + Z95 * se if np.isfinite(se) else float("nan"), "r_row": r[stratum], "G": Gh}


@dataclass
class _Single:
    """Tek hipotezin maske satırlarındaki dizileri."""

    idx: np.ndarray
    p: np.ndarray
    y: np.ndarray
    c: np.ndarray
    v: np.ndarray
    stratum: np.ndarray
    cluster: np.ndarray
    target: str
    name: str
    atoms: tuple


def _single(fr, target, condition, mask, atoms=None, y=None, p0=None) -> _Single:
    name, at = resolve_condition(condition)
    prep = prepare(fr, mask, [(name, at)], (target,), None if p0 is None else {target: p0})
    atoms = fr.atoms if atoms is None else atoms
    yy = np.asarray((fr.y if y is None else y)[target], dtype=float)[prep.idx]
    tp = prep.tp[target]
    X, N = atom_matrices(prep, atoms)
    met = X.all(axis=1) if X.shape[1] else np.zeros(len(prep.idx), dtype=bool)
    v = ~N.any(axis=1) & np.isfinite(yy) & tp.ok
    p = np.where(tp.ok, tp.p, np.nan)
    return _Single(prep.idx, p, yy, met & v, v, tp.stratum, prep.cluster, target, name, at)


def _stats(s: _Single, keep: np.ndarray | None = None, p: np.ndarray | None = None) -> dict:
    keep = np.ones(len(s.idx), dtype=bool) if keep is None else keep
    return _strat_single(s.p if p is None else p, s.y, s.c & keep, s.v & keep, s.stratum, s.cluster)


def _records(fr, rows: np.ndarray, p: np.ndarray, y: np.ndarray) -> list[dict]:
    tm = fr.tm
    out = []
    for r, pi, yi in zip(rows, p, y):
        rec = {k: tm[k].iat[int(r)] for k in _CARD_COLS if k in tm.columns}
        rec["date"] = str(pd.Timestamp(rec["date"]).date()) if "date" in rec else None
        rec["is_home"] = bool(rec.get("is_home"))
        rec["row_id"] = int(rec.get("row_id", r))
        rec["p0"] = float(pi)
        rec["y"] = float(yi)
        out.append(rec)
    return out


def _counter_examples(fr, s: _Single, direction: int, k: int = N_COUNTER) -> list[dict]:
    """Koşul var ama yön tersine sonuç: (+) olay yok ve en yüksek p0; (−) olay var ve en düşük p0."""
    if direction >= 0:
        sel = np.where(s.c & (s.y == 0))[0]
        order = sel[np.lexsort((s.idx[sel], -s.p[sel]))]
    else:
        sel = np.where(s.c & (s.y == 1))[0]
        order = sel[np.lexsort((s.idx[sel], s.p[sel]))]
    top = order[:k]
    return _records(fr, s.idx[top], s.p[top], s.y[top])


def _hit_examples(fr, s: _Single, direction: int, k: int = N_COUNTER) -> list[dict]:
    """Yönü destekleyen örnekler: (+) koşul ∧ olay, en düşük p0 (en şaşırtıcı başarılar)."""
    if direction >= 0:
        sel = np.where(s.c & (s.y == 1))[0]
        order = sel[np.lexsort((s.idx[sel], s.p[sel]))]
    else:
        sel = np.where(s.c & (s.y == 0))[0]
        order = sel[np.lexsort((s.idx[sel], -s.p[sel]))]
    top = order[:k]
    return _records(fr, s.idx[top], s.p[top], s.y[top])


def _matched(fr, s: _Single) -> dict:
    """Eşleştirilmiş ampirik karşılaştırma: koşulsuz geçerli satırlar, aynı lig-sezon × taraf × S0 ondalığı."""
    dec = _bins(np.nan_to_num(s.p), np.isfinite(s.p), MATCH_DECILES)
    side = fr.tm["is_home"].to_numpy()[s.idx].astype(np.int64)
    key = (s.cluster * 2 + side) * MATCH_DECILES + dec
    _, cell = np.unique(key, return_inverse=True)
    K = int(cell.max()) + 1 if len(cell) else 1
    comp = s.v & ~s.c
    n_comp = np.bincount(cell, weights=comp.astype(float), minlength=K)
    y_comp = np.bincount(cell, weights=np.where(comp, s.y, 0.0), minlength=K)
    has = s.c & (n_comp[cell] > 0)
    if not has.any():
        return {"n_matched": 0, "rate_with": float("nan"), "matched_base_rate": float("nan"), "diff": float("nan")}
    base = float((y_comp[cell] / np.maximum(n_comp[cell], 1))[has].mean())
    rate = float(s.y[has].mean())
    return {"n_matched": int(has.sum()), "rate_with": rate, "matched_base_rate": base, "diff": rate - base}


def _loo_lifts(s: _Single, memberships: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Birim çıkarıldığında oran (vektörleştirilmiş). ``memberships``: satır → birim kodu (−1 yok) dizileri."""
    v, c = s.v, s.c
    S = int(s.stratum.max()) + 1
    U = int(max(int(m.max()) for m in memberships)) + 1
    yv, pv = np.where(v, s.y, 0.0), np.where(v, s.p, 0.0)

    def per(weights):
        full = np.bincount(s.stratum, weights=weights, minlength=S)
        unit = np.zeros(U * S)
        for mem in memberships:
            ok = mem >= 0
            unit += np.bincount(mem[ok] * S + s.stratum[ok], weights=weights[ok], minlength=U * S)
        return full, unit.reshape(U, S)

    Os, Osu = per(yv)
    Es, Esu = per(pv)
    Ocs, Ocsu = per(np.where(c, yv, 0.0))
    Ecs, Ecsu = per(np.where(c, pv, 0.0))
    ncs, ncsu = per(c.astype(float))
    Es_r, Os_r = Es[None, :] - Esu, Os[None, :] - Osu
    r = np.divide(Os_r, Es_r, out=np.zeros_like(Es_r), where=Es_r > 1e-12)
    E_adj = ((Ecs[None, :] - Ecsu) * r).sum(axis=1)
    O = (Ocs[None, :] - Ocsu).sum(axis=1)
    n_left = (ncs[None, :] - ncsu).sum(axis=1)
    lift = np.divide(O, E_adj, out=np.full(U, np.nan), where=E_adj > 0)
    touched = ncsu.sum(axis=1) + np.abs(Esu).sum(axis=1) > 0
    return lift, n_left, touched


# ----------------------------------------------------------------------------
# Yanlışlama listesi (§7b) ve Mod B (§7a)
# ----------------------------------------------------------------------------

def falsification(fr, target: str, condition, mask, p0_market: np.ndarray | None = None, atoms: dict | None = None,
                  y: dict | None = None) -> dict:
    """Yanlışlama kontrolleri 1–5 ve en büyük 20 karşı örnek (6). ``p0_market``: S0p hedef olasılığı (tm'ye hizalı)."""
    s = _single(fr, target, condition, mask, atoms, y)
    full = _stats(s)
    lift = full["lift"]
    direction = 1 if lift > 1 else (-1 if lift < 1 else 0)
    out: dict = {"hedef": target, "kosul": s.name, "atomlar": list(s.atoms), "yon": direction, "sorgu": Q1_LABEL,
                 "lift": lift, "lift_lo": full["lift_lo"], "lift_hi": full["lift_hi"], "z": full["z"],
                 "n": full["n"], "checks": {}}

    def same_side(x):
        return np.sign(np.asarray(x, dtype=float) - 1.0) == direction

    # 1) bir takım / bir lig çıkarıldığında oran 1'in öbür yanına geçmemeli
    tm = fr.tm
    teams = pd.Series(np.r_[tm["team"].to_numpy()[s.idx], tm["opponent"].to_numpy()[s.idx]]).astype(str)
    tcodes, tlabels = pd.factorize(teams, sort=True)
    n = len(s.idx)
    team_mem, opp_mem = tcodes[:n].astype(np.int64), tcodes[n:].astype(np.int64)
    league_mem, l_labels = _codes(tm["league"].to_numpy()[s.idx])
    chk1 = {}
    for nm, mems, labels in (("takim", [team_mem, opp_mem], np.asarray(tlabels)), ("lig", [league_mem], l_labels)):
        lifts, n_left, touched = _loo_lifts(s, mems)
        rel = touched & (n_left > 0) & np.isfinite(lifts)
        flips = rel & ~same_side(lifts)
        worst = None
        if rel.any() and direction != 0:
            # en zayıf = etki yönünde en küçük log oran (yön değişmişse negatif; 1'e en yakın olan değil)
            dev = np.where(rel, direction * np.log(np.clip(lifts, 1e-12, None)), np.inf)
            j = int(np.argmin(dev))
            # kulüp adı yazılmaz (takım bazında etiket/sıralama yok); lig kodu yazılabilir
            worst = {"birim": str(labels[j]) if nm == "lig" else None, "lift": float(lifts[j])}
        chk1[nm] = {"n_birim": int(rel.sum()), "n_yon_degisen": int(flips.sum()),
                    "min_lift": float(np.nanmin(np.where(rel, lifts, np.nan))) if rel.any() else float("nan"),
                    "max_lift": float(np.nanmax(np.where(rel, lifts, np.nan))) if rel.any() else float("nan"),
                    "en_zayif": worst, "passed": bool(direction != 0 and rel.any() and not flips.any())}
    out["checks"]["1_birim_cikarma"] = {**chk1, "passed": bool(chk1["takim"]["passed"] and chk1["lig"]["passed"])}

    # 2) O − E'ye en çok katkı veren %1 satır çıkarılınca aynı yön ve aralık 1'i dışlamalı
    contrib = np.where(s.c, s.y - s.p * full["r_row"], np.nan) * (direction if direction != 0 else 1)
    k = max(1, int(math.ceil(TOP_DROP_SHARE * full["n"])))
    cand = np.where(s.c)[0]
    drop = cand[np.lexsort((s.idx[cand], -contrib[cand]))][:k]
    keep = np.ones(n, dtype=bool)
    keep[drop] = False
    st2 = _stats(s, keep)
    ok2 = direction != 0 and ((st2["lift_lo"] > 1) if direction > 0 else (st2["lift_hi"] < 1))
    out["checks"]["2_ust_yuzde1_cikarma"] = {"n_cikarilan": int(k), "lift": st2["lift"], "lift_lo": st2["lift_lo"],
                                             "lift_hi": st2["lift_hi"], "passed": bool(ok2)}

    # 3) sezonların en az %60'ında aynı yön (tam dönem r_s ile sezon O/E)
    seasons, s_labels = _codes(tm["season"].to_numpy()[s.idx])
    ns = len(s_labels)
    O_se = np.bincount(seasons, weights=np.where(s.c, s.y, 0.0), minlength=ns)
    E_se = np.bincount(seasons, weights=np.where(s.c, s.p * full["r_row"], 0.0), minlength=ns)
    n_se = np.bincount(seasons, weights=s.c.astype(float), minlength=ns)
    has = n_se > 0
    same = has & (np.sign(O_se - E_se) == direction)
    share = float(same.sum() / has.sum()) if has.any() else float("nan")
    out["checks"]["3_sezon_yonu"] = {"n_sezon": int(has.sum()), "ayni_yon": int(same.sum()), "pay": share,
                                     "esik": SEASON_SAME_DIR_SHARE,
                                     "passed": bool(direction != 0 and has.any() and share >= SEASON_SAME_DIR_SHARE)}

    # 4) eşleştirilmiş ampirik karşılaştırma aynı yönde
    mt = _matched(fr, s)
    out["checks"]["4_eslestirilmis"] = {**mt, "passed": bool(direction != 0 and np.sign(mt["diff"]) == direction)}

    # 5) S0p (piyasa) offsetiyle etki sürmeli
    if p0_market is None:
        out["checks"]["5_piyasa"] = {"durum": "not_run", "passed": None,
                                     "not": "S0p olasılıkları verilmedi; OUT_OF_SAMPLE_SUPPORTED için gerekli"}
    else:
        sm = _single(fr, target, s.atoms, mask, atoms, y, p0=np.asarray(p0_market, dtype=float))
        st5 = _stats(sm)
        ok5 = direction != 0 and ((st5["lift_lo"] > 1) if direction > 0 else (st5["lift_hi"] < 1))
        out["checks"]["5_piyasa"] = {"durum": "run", "n": st5["n"], "lift": st5["lift"], "lift_lo": st5["lift_lo"],
                                     "lift_hi": st5["lift_hi"], "z": st5["z"], "passed": bool(ok5),
                                     "sonuc": None if ok5 else "NO_ADDED_VALUE"}

    # 6) en büyük 20 karşı örnek
    out["counter_examples"] = _counter_examples(fr, s, direction)
    flags = [out["checks"][k]["passed"] for k in
             ("1_birim_cikarma", "2_ust_yuzde1_cikarma", "3_sezon_yonu", "4_eslestirilmis")]
    out["passed_1_4"] = bool(all(flags))
    out["passed_all"] = bool(all(flags) and out["checks"]["5_piyasa"]["passed"] is True)
    return out


def mode_b_card(fr, target: str, condition, mask, atoms: dict | None = None, y: dict | None = None) -> dict:
    """Mod B (koşuldan başlayan doğrulama) kart alanları; statülerin tek kaynağı."""
    s = _single(fr, target, condition, mask, atoms, y)
    st = _stats(s)
    direction = 1 if st["lift"] > 1 else (-1 if st["lift"] < 1 else 0)
    comp = s.v & ~s.c
    hits = int((s.c & (s.y == 1)).sum())
    misses = int((s.c & (s.y == 0)).sum())
    ev_wo = int((comp & (s.y == 1)).sum())
    n_wo = int(comp.sum())
    mt = _matched(fr, s)
    seasons, labels = _codes(fr.tm["season"].to_numpy()[s.idx])
    table = []
    for j, lab in enumerate(labels):
        sel = s.c & (seasons == j)
        if not sel.any():
            continue
        o, e_raw, e_adj = float(s.y[sel].sum()), float(s.p[sel].sum()), float((s.p * st["r_row"])[sel].sum())
        table.append({"sezon": str(lab), "n": int(sel.sum()), "O": o, "E_s0": e_raw, "E_adj": e_adj,
                      "oe": o / e_adj if e_adj > 0 else float("nan")})
    n_c = int(s.c.sum())
    return {
        "sorgu": Q1_LABEL, "hedef": target, "kosul": s.name, "atomlar": list(s.atoms),
        "n_cond": n_c, "hits": hits, "misses": misses, "events_without_cond": ev_wo, "n_without_cond": n_wo,
        "rate_with": hits / n_c if n_c else float("nan"), "rate_without": ev_wo / n_wo if n_wo else float("nan"),
        "matched_base_rate": mt["matched_base_rate"], "matched_n": mt["n_matched"],
        "E_s0": st["E_raw"], "E_adj": st["E_adj"], "O": st["O"],
        "abs_diff": (st["O"] - st["E_adj"]) / n_c if n_c else float("nan"),
        "lift": st["lift"], "relative_increase": st["lift"] - 1.0, "lift_lo": st["lift_lo"], "lift_hi": st["lift_hi"],
        "z": st["z"], "V": st["V"], "G": st["G"], "season_table": table,
        "hit_examples": _hit_examples(fr, s, direction), "counter_examples": _counter_examples(fr, s, direction),
        "not": "Bulunan ilişki nedensellik veya manipülasyon kanıtı değildir.",
    }


# ----------------------------------------------------------------------------
# Tekilleştirme, kalibrasyon kapısı, aday seçimi, Holm
# ----------------------------------------------------------------------------

def _target_raw_bits(target: str) -> tuple[int, int]:
    """Hedefi oluşturan ham İY/MS hücrelerinin bit maskesi (ev satırı, deplasman satırı perspektifi)."""
    cells = set(TARGET_TEAM_CELLS[target])
    home = sum(1 << i for i in range(9) if RAW_TO_TEAM_CELL[i][0] in cells)
    away = sum(1 << i for i in range(9) if RAW_TO_TEAM_CELL[i][1] in cells)
    return home, away


def pair_symmetric(fr, mask) -> np.ndarray:
    """Maskeyi ikiz satırlara göre simetrik yapar (maçın iki satırı birlikte maskede ya da ikisi de dışında)."""
    mask = np.asarray(mask, dtype=bool)
    return mask & mask[fr.tm["mirror_row"].to_numpy()]


def dedupe(fr, mask, hyps: Sequence[str] | None = None, atoms: dict | None = None, y: dict | None = None,
           conditions=None, targets=C.TARGETS_Q1, pair_symmetric_mask: bool = False) -> dict:
    """Olay düzeyi imzayla ikiz denk hipotezlerin tekilleştirilmesi.

    İmza = nitelikli satırların (maskede, koşul var, hedef biliniyor) sıralı (pair_id, o satır perspektifinde hedefi
    oluşturan ham İY/MS hücre kümesi) listesi. Aynı imza = aynı maç-olay kümesi (ör. ``RAKIP_SON3_MAGLUBIYET ×
    GALIBIYET`` ≡ ``SON3_MAGLUBIYET × MAGLUBIYET``). Boş imzalı hipotezler birleştirilmez (test edilemez).
    Not: uygunluk satır bazlıdır (ör. lig değişikliği dışlaması takıma özgü); ikizlerden yalnızca biri maskede ise
    ayna hipotezlerin imzaları birkaç maçla ayrışır ve birleşmez. ``pair_symmetric_mask=True`` imzaları
    ``pair_symmetric(fr, mask)`` üzerinde hesaplar (değerlendirme maskesi de aynı olmalıdır).
    """
    if pair_symmetric_mask:
        mask = pair_symmetric(fr, mask)
    prep = prepare(fr, mask, conditions, targets)
    table = hypothesis_table(prep.conditions, prep.targets)
    ids = list(table["hyp_id"]) if hyps is None else list(hyps)
    lookup = table.set_index("hyp_id")
    atoms = fr.atoms if atoms is None else atoms
    y = fr.y if y is None else y
    X, _ = atom_matrices(prep, atoms)
    pos = {a: j for j, a in enumerate(prep.atom_names)}
    pair = fr.tm["pair_id"].to_numpy()[prep.idx].astype(np.int64)
    home = fr.tm["is_home"].to_numpy()[prep.idx].astype(bool)
    seen: dict[bytes, str] = {}
    unique, dup_of, empty = [], {}, []
    for h in ids:
        t, at = lookup.at[h, "target"], lookup.at[h, "atoms"]
        hb, ab = _target_raw_bits(t)
        q = np.isfinite(np.asarray(y[t], dtype=float)[prep.idx])
        for a in at:
            q &= X[:, pos[a]]
        if not q.any():
            empty.append(h)
            unique.append(h)
            continue
        key = np.sort(pair[q] * 512 + np.where(home[q], hb, ab))
        sig = hashlib.sha256(key.tobytes()).digest()
        if sig in seen:
            dup_of[h] = seen[sig]
        else:
            seen[sig] = h
            unique.append(h)
    return {"unique": unique, "duplicate_of": dup_of, "empty": empty, "n_raw": len(ids), "n_unique": len(unique),
            "n_duplicates": len(dup_of)}


def calibration_gate(fr, mask, targets=C.TARGETS_Q1) -> pd.DataFrame:
    """Arama öncesi kapı: her hedef × taraf için katmanlanmamış O/E ve %95 CR1 aralığı; aralık 1'i içermeli.

    ``df.attrs['passed']``: tüm satırlar geçti mi.
    """
    mask = np.asarray(mask, dtype=bool)
    is_home = fr.tm["is_home"].to_numpy().astype(bool)
    rows = []
    for t in targets:
        p = np.asarray(fr.p0[t], dtype=float)
        yy = np.asarray(fr.y[t], dtype=float)
        for side, nm in ((True, "ev"), (False, "deplasman")):
            sel = mask & (is_home == side) & np.isfinite(p) & np.isfinite(yy)
            cl, _ = _codes(np.asarray(fr.cluster)[sel])
            O, E = float(yy[sel].sum()), float(p[sel].sum())
            G = int(cl.max()) + 1 if sel.any() else 0
            U = np.bincount(cl, weights=yy[sel] - p[sel], minlength=max(G, 1))
            V = G / (G - 1) * float((U ** 2).sum()) if G > 1 else float("nan")
            oe = O / E if E > 0 else float("nan")
            half = Z95 * math.sqrt(V) / E if (E > 0 and np.isfinite(V)) else float("nan")
            lo, hi = oe - half, oe + half
            rows.append({"target": t, "side": nm, "n": int(sel.sum()), "O": O, "E": E, "oe": oe, "lo": lo, "hi": hi,
                         "z": (O - E) / math.sqrt(V) if V and V > 0 else float("nan"), "G": G,
                         "passed": bool(np.isfinite(half) and lo <= 1.0 <= hi)})
    df = pd.DataFrame(rows)
    df.attrs["passed"] = bool(len(df) and df["passed"].all())
    return df


def _lcb_abs_log_lift(lift, lo, hi) -> np.ndarray:
    lift, lo, hi = (np.asarray(v, dtype=float) for v in (lift, lo, hi))
    with np.errstate(divide="ignore", invalid="ignore"):
        up = np.where(lo > 0, np.log(np.where(lo > 0, lo, 1.0)), -np.inf)
        down = np.where(hi > 0, -np.log(np.where(hi > 0, hi, 1.0)), np.inf)
    return np.where(lift >= 1, up, down)


def select_candidates(results: pd.DataFrame, reference: pd.DataFrame | None = None,
                      max_candidates: int = C.MAX_CANDIDATES, alpha: float = C.ALPHA) -> pd.DataFrame:
    """Aday seçimi (§7): WY-anlamlı (p_adj < α ve MC aralığı α'yı içermiyor) + desteklenen hipotezler.

    Çiftler yalnızca |log oran|'ı her iki tek atomunkinden büyük ve aynı yöndeyse (tek atomun oranı tam 1 ise yön
    kısıtı yok). Bağlam atomlarının tek başına oranları ``reference`` ile verilir (aileye girmez;
    ``evaluate(..., conditions=context_reference_conditions())``). WY-anlamlı bir çiftin tek atomlarından birinin
    oranı ne ``results`` ne ``reference`` içinde yoksa kural doğrulanamaz → çift ELENİR (muhafazakâr; sessizce
    geçirilmez), ``UserWarning`` verilir ve ``attrs['cift_kurali_dogrulanamadi']`` listelenir. Ör. yalnızca tekil
    hipotezler verilirse ayna kopyası olarak çıkarılan tek atomlar (``MAGLUBIYET|SON3_MAGLUBIYET``) eksik kalır;
    bu yüzden ``reference`` tam değerlendirme tablosunu (+ bağlam referansını) içermelidir. Tek atom oranı sonlu
    değilse (O = 0 vb.) çift aşılamaz sayılır. Sıra: |log oran| alt güven sınırı; en fazla ``max_candidates``;
    her hedefte aynı atomu paylaşanlardan en fazla biri. Ön-kayıtlı yön ``direction`` (+1/−1).
    """
    df = results.copy()
    need = {"p_adj", "lift", "lift_lo", "lift_hi", "atoms", "target", "supported"}
    missing = need - set(df.columns)
    if missing:
        raise KeyError(f"Eksik sütun(lar): {sorted(missing)}")
    ci_hi = df["ci_hi"] if "ci_hi" in df.columns else df["p_adj"]
    sig = df["supported"].astype(bool) & (df["p_adj"] < alpha) & (ci_hi < alpha)
    with np.errstate(divide="ignore", invalid="ignore"):
        df["log_lift"] = np.log(df["lift"].astype(float))
    singles: dict[tuple[str, str], float] = {}
    for src in (df, reference) if reference is not None else (df,):
        with np.errstate(divide="ignore", invalid="ignore"):
            logs = np.log(src["lift"].astype(float))
        for t, at, ll in zip(src["target"], src["atoms"], logs):
            if len(at) == 1:
                singles.setdefault((t, at[0]), float(ll))
    keep, unverifiable = [], []
    for i, (t, at, ll) in enumerate(zip(df["target"], df["atoms"], df["log_lift"])):
        if not sig.iat[i] or not np.isfinite(ll):
            keep.append(False)
            continue
        if len(at) == 1:
            keep.append(True)
            continue
        ok = True
        for a in at:
            s = singles.get((t, a))
            if s is None:  # tek atom oranı yok → kural doğrulanamaz → çift elenir
                unverifiable.append(df["hyp_id"].iat[i] if "hyp_id" in df.columns else f"{t}|{PAIR_SEP.join(at)}")
                ok = False
                break
            if not (np.isfinite(s) and abs(ll) > abs(s) and (s == 0 or np.sign(s) == np.sign(ll))):
                ok = False
        keep.append(ok)
    if unverifiable:
        warnings.warn(f"Çift kuralı doğrulanamadı (tek atom oranı yok), elendi: {unverifiable}. "
                      "reference = tam değerlendirme tablosu + context_reference_conditions sonucu verin.",
                      UserWarning, stacklevel=2)
    cand = df[np.array(keep, dtype=bool)].copy()
    cand["lcb_abs_log_lift"] = _lcb_abs_log_lift(cand["lift"], cand["lift_lo"], cand["lift_hi"])
    cand["direction"] = np.where(cand["lift"] >= 1, 1, -1)
    sort_key = ["lcb_abs_log_lift"] + (["hyp_id"] if "hyp_id" in cand.columns else [])
    cand = cand.sort_values(sort_key, ascending=[False] + [True] * (len(sort_key) - 1), kind="mergesort")
    chosen, used = [], set()
    for i, (t, at) in enumerate(zip(cand["target"], cand["atoms"])):
        if len(chosen) >= max_candidates:
            break
        if any((t, a) in used for a in at):
            continue
        chosen.append(i)
        used.update((t, a) for a in at)
    out = cand.iloc[chosen].copy()
    out["rank"] = np.arange(1, len(out) + 1)
    out = out.reset_index(drop=True)
    out.attrs["cift_kurali_dogrulanamadi"] = unverifiable
    return out


def holm_one_sided(z, direction=None, alpha: float = C.ALPHA) -> dict[str, np.ndarray]:
    """Ön-kayıtlı yönde tek yönlü normal p ve Holm düzeltmesi (parametre/test aşaması)."""
    z = np.asarray(z, dtype=float)
    d = np.ones_like(z) if direction is None else np.asarray(direction, dtype=float)
    p = norm.sf(z * d)
    m = int(np.isfinite(p).sum())
    adj = np.full_like(p, np.nan)
    fin = np.where(np.isfinite(p))[0]
    if m:
        order = fin[np.argsort(p[fin], kind="mergesort")]
        stepped = np.minimum(1.0, (m - np.arange(m)) * p[order])
        adj[order] = np.maximum.accumulate(stepped)
    return {"p_one": p, "p_holm": adj, "reject": np.nan_to_num(adj, nan=1.0) < alpha}


# ----------------------------------------------------------------------------
# Sorgu 2 (§7c): olay sonrası sonraki maç(lar)
# ----------------------------------------------------------------------------

def _event_code(ht: np.ndarray, ft: np.ndarray, event: str) -> np.ndarray:
    if event == "IY_GERIDE_MS_GALIP":
        return (ht == _M) & (ft == _G)
    if event == "IY_ONDE_MS_MAGLUP":
        return (ht == _G) & (ft == _M)
    raise KeyError(event)


@dataclass
class Q2Prep:
    """Yapısal olarak uygun olay konumları (sonuçtan bağımsız): olay e, ufuk e+1..e+H aynı dilimde, sezonlar tam,
    sezon atlaması yok ve ufuktaki tüm satırlar maskede."""

    cand: np.ndarray  # dizi konumu e
    team: np.ndarray
    rows: np.ndarray  # (len, H) tm satırları e+1..e+H
    event_row: np.ndarray
    cluster: np.ndarray  # örnek (e+1) satırının küme kodu


def q2_prepare(fr, mask) -> Q2Prep:
    si = fr.seq
    H = C.Q2_HORIZON
    mask = np.asarray(mask, dtype=bool)
    if si.n <= H:
        z = np.zeros(0, dtype=np.int64)
        return Q2Prep(z, z, np.zeros((0, H), dtype=np.int64), z, z)
    e = np.arange(si.n - H)
    wok = si.window_ok(H)[e + H]
    m_seq = mask[si.rows].astype(np.int64)
    cm = np.r_[0, np.cumsum(m_seq)]
    in_mask = (cm[e + H + 1] - cm[e + 1]) == H
    cand = e[wok & in_mask]
    rows = si.rows[cand[:, None] + np.arange(1, H + 1)[None, :]]
    team, _ = _codes(fr.tm["team"].to_numpy()[si.rows[cand]]) if len(cand) else (np.zeros(0, np.int64), None)
    cl_all, _ = _codes(np.asarray(fr.cluster))
    return Q2Prep(cand, team, rows, si.rows[cand], cl_all[rows[:, 0]] if len(cand) else np.zeros(0, np.int64))


def _greedy_nonoverlap(pos: np.ndarray, team: np.ndarray, horizon: int) -> np.ndarray:
    """Takım başına her ufukta ilk olay (seçilen olayların sonuç pencereleri çakışmaz)."""
    keep = np.zeros(len(pos), dtype=bool)
    last_t, last_p = None, -(10 ** 12)
    for k, (p, t) in enumerate(zip(pos.tolist(), team.tolist())):
        if t != last_t or p >= last_p + horizon:
            keep[k] = True
            last_t, last_p = t, p
    return keep


def q2_instances(fr, mask, ht: np.ndarray | None = None, ft: np.ndarray | None = None,
                 prep: Q2Prep | None = None) -> pd.DataFrame:
    """Çakışmayan olay örnekleri: olay satırı, örnek satırı (olaydan sonraki maç), takım, olay türü."""
    prep = q2_prepare(fr, mask) if prep is None else prep
    if ht is None:
        ht, ft = outcome_codes(fr.tm)
    parts = []
    for ev in C.Q2_EVENTS:
        er = prep.event_row
        hit = _event_code(ht[er], ft[er], ev) & (ht[er] >= 0) & (ft[er] >= 0)
        sel = np.where(hit)[0]
        keep = sel[_greedy_nonoverlap(prep.cand[sel], prep.team[sel], C.Q2_HORIZON)]
        parts.append(pd.DataFrame({"event": ev, "k": keep, "event_row": er[keep], "row": prep.rows[keep, 0],
                                   "cluster": prep.cluster[keep]}))
    return pd.concat(parts, ignore_index=True)


def _q2_core(fr, prep: Q2Prep, ht: np.ndarray, ft: np.ndarray) -> list[dict]:
    """6 hipotez için O, E, T, CR1 V, z."""
    inst = q2_instances(fr, None, ht, ft, prep)
    res = []
    G_all = int(prep.cluster.max()) + 1 if len(prep.cluster) else 1
    for ev in C.Q2_EVENTS:
        k = inst.loc[inst["event"] == ev, "k"].to_numpy()
        rows = prep.rows[k]
        cl = prep.cluster[k]
        h, f = ht[rows], ft[rows]
        fk = f >= 0
        bk = fk & (h >= 0)
        p_ev = np.asarray(fr.p0[ev], dtype=float)[rows]
        y_win = np.where(fk[:, 0], (f[:, 0] == _G).astype(float), np.nan)
        e_win = np.asarray(fr.p_win, dtype=float)[rows[:, 0]]
        y3 = np.where(bk[:, :3].all(axis=1), _event_code(h[:, :3], f[:, :3], ev).any(axis=1).astype(float), np.nan)
        e3 = 1.0 - np.prod(1.0 - p_ev[:, :3], axis=1)
        pts = np.where(f == _G, 3.0, np.where(f == _B, 1.0, 0.0))
        y5 = np.where(fk.all(axis=1), pts.sum(axis=1), np.nan)
        e5 = np.asarray(fr.exp_points, dtype=float)[rows].sum(axis=1)
        series = {"SONRAKI_GALIBIYET": (y_win, e_win), "SONRAKI3_AYNI_OLAY": (y3, e3), "SONRAKI5_PUAN": (y5, e5)}
        for tgt in C.Q2_TARGETS:  # sıra = Q2_HYP_IDS
            yy, ee = series[tgt]
            v = np.isfinite(yy) & np.isfinite(ee)
            O, E = float(yy[v].sum()), float(ee[v].sum())
            U = np.bincount(cl[v], weights=(yy - ee)[v], minlength=G_all)
            Gh = int((np.bincount(cl[v], minlength=G_all) > 0).sum())
            V = Gh / (Gh - 1) * float((U ** 2).sum()) if Gh > 1 else float("nan")
            z = (O - E) / math.sqrt(V) if V > 0 else float("nan")
            res.append({"hyp_id": f"Q2|{ev}|{tgt}", "event": ev, "target": tgt, "n": int(v.sum()), "O": O, "E": E,
                        "T": O - E, "V": V, "z": z, "G": Gh, "supported": bool(v.sum() > 0 and np.isfinite(z))})
    return res


def q2_evaluate(fr, mask, ht: np.ndarray | None = None, ft: np.ndarray | None = None,
                prep: Q2Prep | None = None) -> pd.DataFrame:
    """Sorgu 2'nin 6 hipotezi (ayrı aile): sonraki maçta galibiyet (p0), sonraki 3 maçta aynı olay
    (1 − Π(1 − p0)), sonraki 5 maçta puan (Σ beklenen puan); CR1 z. Etiket: 'Sorgu 2 (olay sonrası)'."""
    prep = q2_prepare(fr, mask) if prep is None else prep
    if ht is None:
        ht, ft = outcome_codes(fr.tm)
    df = pd.DataFrame(_q2_core(fr, prep, ht, ft))
    with np.errstate(divide="ignore", invalid="ignore"):
        se = np.sqrt(df["V"]) / df["E"]
        df["ratio"] = df["O"] / df["E"]
        df["ratio_lo"] = np.clip(df["ratio"] - Z95 * se, 0.0, None)
        df["ratio_hi"] = df["ratio"] + Z95 * se
        df["abs_diff"] = (df["O"] - df["E"]) / df["n"]
    df["p_norm"] = 2.0 * norm.sf(np.abs(df["z"].to_numpy(dtype=float)))
    df["sorgu"] = Q2_LABEL
    return df

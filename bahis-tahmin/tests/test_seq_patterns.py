"""Sorgu 1/2 örüntü motoru, referans süreç, WY ve plasebo testleri (yalnızca sentetik veri)."""

from __future__ import annotations

import dataclasses
import math
from collections import defaultdict
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from bahis_tahmin.sequences import config as C
from bahis_tahmin.sequences import null as NL
from bahis_tahmin.sequences import patterns as P
from bahis_tahmin.sequences.features import outcome_codes
from bahis_tahmin.sequences.synthetic import synthetic_frame
from bahis_tahmin.sequences.timeline import RAW_TO_TEAM_CELL

EVAL_PERIODS = ["kesif", "parametre", "test"]
SMALL = {"min_n": 100, "min_e": 5.0}  # küçük sentetik çerçeve için destek eşikleri (gerçek: config.MIN_N/MIN_E)


def _mask(fr, periods=EVAL_PERIODS):
    return fr.eligible & np.isin(fr.period.astype(str), periods)


@pytest.fixture(scope="module")
def fr0():
    fr, _, _ = synthetic_frame(0)
    return fr


@pytest.fixture(scope="module")
def null0(fr0):
    mask = _mask(fr0)
    prep = P.prepare(fr0, mask)
    obs = P.evaluate(fr0, mask, prep=prep, **SMALL)
    nul = NL.run_null(fr0, mask, 30, 3, prep=prep, **SMALL)
    return obs, nul


@pytest.fixture(scope="module")
def planted():
    fr, _, _ = synthetic_frame(5, comeback_boost=3.0, n_leagues=4)
    return fr


# ----------------------------------------------------------------------------
# Koşullar ve tekilleştirme
# ----------------------------------------------------------------------------

def test_conditions_structure():
    conds = P.build_conditions()
    assert len(conds) == 200
    assert conds == P.build_conditions()  # deterministik
    names = [n for n, _ in conds]
    assert len(set(names)) == 200
    kinds = pd.Series([P.condition_kind(a) for _, a in conds]).value_counts().to_dict()
    assert kinds == {P.KIND_SINGLE: 16, P.KIND_HH: 120, P.KIND_HC: 64}
    singles = [a for _, a in conds if len(a) == 1]
    assert all(a[0] in C.HISTORY_ATOMS for a in singles)  # bağlam tek başına koşul değil
    for _, a in conds:
        assert len(a) <= 2
        if len(a) == 2:
            assert a[0] in C.HISTORY_ATOMS
    assert len(P.hypothesis_table()) == 800


def test_dedupe_finds_mirror_duplicate(fr0):
    mask = _mask(fr0, ["kesif"])
    # bir satırın ikizini maskeden çıkar: ayna imzalar ayrışır; pair_symmetric_mask ile yeniden birleşir
    mirror = fr0.tm["mirror_row"].to_numpy()
    a_rows = np.where(mask & (fr0.atoms["RAKIP_SON3_MAGLUBIYET"] == 1) & np.isfinite(fr0.y["GALIBIYET"]))[0]
    asym = mask.copy()
    asym[mirror[a_rows[0]]] = False
    d_asym = P.dedupe(fr0, asym)
    assert "MAGLUBIYET|SON3_MAGLUBIYET" not in d_asym["duplicate_of"]
    d_sym = P.dedupe(fr0, asym, pair_symmetric_mask=True)
    assert d_sym["duplicate_of"].get("MAGLUBIYET|SON3_MAGLUBIYET") == "GALIBIYET|RAKIP_SON3_MAGLUBIYET"
    mask = P.pair_symmetric(fr0, mask)  # iki ikiz satır birlikte
    d = P.dedupe(fr0, mask)
    assert d["n_raw"] == 800
    assert d["n_unique"] + d["n_duplicates"] == 800 and d["n_duplicates"] > 0
    a = "GALIBIYET|RAKIP_SON3_MAGLUBIYET"
    b = "MAGLUBIYET|SON3_MAGLUBIYET"
    assert d["duplicate_of"].get(b) == a
    assert a in d["unique"] and b not in d["unique"]
    # farklı olay kümesi birleşmez
    assert "GALIBIYET|SON3_MAGLUBIYET" in d["unique"]
    # ikiz-simetrik maskede ayna kopyaları istatistik olarak da özdeş (katmanlar, kümeler ve tümleyen dahil)
    ev = P.evaluate(fr0, mask, min_n=0, min_e=0).set_index("hyp_id")
    for dup_id, rep in d["duplicate_of"].items():
        for k in ("n", "O", "E_raw", "E_adj", "V", "z"):
            assert ev.at[dup_id, k] == pytest.approx(ev.at[rep, k], rel=1e-9, abs=1e-9), (dup_id, rep, k)


# ----------------------------------------------------------------------------
# Katmanlı istatistik ve CR1
# ----------------------------------------------------------------------------

def _brute(fr, mask, target, atoms):
    """Satır döngüsüyle katmanlı O/E, ψ ve CR1 (bağımsız referans)."""
    idx = np.where(mask)[0]
    p = np.asarray(fr.p0[target], dtype=float)[idx]
    ok = np.isfinite(p)
    cuts = np.quantile(p[ok], np.arange(1, C.N_QUINTILES) / C.N_QUINTILES)
    rows = []
    for k, i in enumerate(idx):
        yi = float(fr.y[target][i])
        vals = [float(fr.atoms[a][i]) for a in atoms]
        if not ok[k] or not math.isfinite(yi) or not all(math.isfinite(v) for v in vals):
            continue
        q = int(np.searchsorted(cuts, p[k], side="right"))
        s = (str(fr.tm["league"].iat[i]), bool(fr.tm["is_home"].iat[i]), q)
        rows.append((s, str(fr.cluster[i]), p[k], yi, all(v == 1 for v in vals)))
    Os, Es, Ecs, ns = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(int)
    for s, g, pi, yi, c in rows:
        Os[s] += yi
        Es[s] += pi
        ns[s] += 1
        if c:
            Ecs[s] += pi
    r = {s: Os[s] / Es[s] for s in Es}
    O = sum(yi for s, g, pi, yi, c in rows if c)
    n = sum(1 for row in rows if row[4])
    E_raw = sum(pi for s, g, pi, yi, c in rows if c)
    E_adj = sum(pi * r[s] for s, g, pi, yi, c in rows if c)
    U = defaultdict(float)
    for s, g, pi, yi, c in rows:
        U[g] += ((1.0 if c else 0.0) - Ecs[s] / Es[s]) * (yi - pi * r[s])
    G = len(U)
    V = G / (G - 1) * sum(u * u for u in U.values())
    comp = sum(Os[s] / ns[s] for s, g, pi, yi, c in rows if c) / n if n else float("nan")
    return {"n": n, "O": O, "E_raw": E_raw, "E_adj": E_adj, "T": O - E_adj, "V": V, "z": (O - E_adj) / math.sqrt(V),
            "comparable_rate": comp, "G": G}


def test_stratified_stats_match_brute_force(fr0):
    # iki lig × üç sezon: katmanlar (lig × taraf × beşli) sezonlar üzerinden birleşir, kümelerde yuvalanmaz
    mask = fr0.eligible & np.isin(fr0.tm["season_year"].to_numpy(), [2007, 2008, 2009])
    assert fr0.tm["league"][mask].nunique() == 2
    assert 400 < mask.sum() < 1200
    # NaN atomları, NaN p0 ve NaN hedefler de sınanır
    atoms = dict(fr0.atoms)
    a = atoms["SON5_IY_ONDE_EN_AZ_3"].copy()
    a[::7] = np.nan
    atoms["SON5_IY_ONDE_EN_AZ_3"] = a
    p0 = {k: v.copy() for k, v in fr0.p0.items()}
    p0["GALIBIYET"][np.flatnonzero(mask)[::13]] = np.nan
    y = {k: v.copy() for k, v in fr0.y.items()}
    y["MAGLUBIYET"][np.flatnonzero(mask)[::11]] = np.nan
    fr = dataclasses.replace(fr0, atoms=atoms, p0=p0, y=y)
    conds = [("SON5_IY_GERIDE_EN_AZ_2", ("SON5_IY_GERIDE_EN_AZ_2",)),
             ("SON5_IY_ONDE_EN_AZ_3", ("SON5_IY_ONDE_EN_AZ_3",)),
             ("SON20_IY_GERIDE_MS_GALIP_YOK", ("SON20_IY_GERIDE_MS_GALIP_YOK",)),
             ("SON5_IY_GERIDE_EN_AZ_2 & SON5_IY_ONDE_EN_AZ_3", ("SON5_IY_GERIDE_EN_AZ_2", "SON5_IY_ONDE_EN_AZ_3")),
             ("SON20_IY_GERIDE_MS_GALIP_YOK & FAVORI", ("SON20_IY_GERIDE_MS_GALIP_YOK", "FAVORI")),
             ("SON5_IY_ONDE_EN_AZ_3 & EV_SAHIBI", ("SON5_IY_ONDE_EN_AZ_3", "EV_SAHIBI"))]
    df = P.evaluate(fr, mask, conditions=conds, min_n=0, min_e=0)
    assert len(df) == len(conds) * 4
    for _, row in df.iterrows():
        b = _brute(fr, mask, row["target"], row["atoms"])
        assert row["n"] == b["n"]
        assert row["G"] == b["G"]
        for k in ("O", "E_raw", "E_adj", "T", "V", "z", "comparable_rate"):
            assert row[k] == pytest.approx(b[k], rel=1e-9, abs=1e-9), (row["hyp_id"], k)
        assert row["lift"] == pytest.approx(b["O"] / b["E_adj"])
        half = 1.96 * math.sqrt(b["V"]) / b["E_adj"]
        assert row["lift_hi"] == pytest.approx(row["lift"] + half)
        assert row["oe_raw"] == pytest.approx(b["O"] / b["E_raw"])
    # Mod B ve yanlışlama aynı tek hipotez istatistiğini kullanır (NaN p0 satırları dahil)
    for t in ("GALIBIYET", "MAGLUBIYET"):
        card = P.mode_b_card(fr, t, "SON5_IY_GERIDE_EN_AZ_2 & SON5_IY_ONDE_EN_AZ_3", mask)
        ref = df.set_index("hyp_id").loc[f"{t}|SON5_IY_GERIDE_EN_AZ_2 & SON5_IY_ONDE_EN_AZ_3"]
        assert card["z"] == pytest.approx(ref["z"]) and card["E_adj"] == pytest.approx(ref["E_adj"])
        assert card["n_cond"] == ref["n"]
    # başka maskeyle kurulmuş prep sessizce kullanılmaz
    prep = P.prepare(fr, mask, conds)
    other = mask.copy()
    other[np.flatnonzero(mask)[0]] = False
    with pytest.raises(ValueError):
        P.evaluate(fr, other, prep=prep)
    with pytest.raises(ValueError):
        NL.run_null(fr, other, 1, 0, prep=prep)


def _fake_frame(dup: int = 1, seed: int = 0, nested: bool = True):
    """Lig-sezon kümeli küçük çerçeve (p0 beş eşit sıklıklı düzey → beşli sınırları çoğaltmada değişmez).

    ``nested=False``: iki lig aynı küme etiketlerini paylaşır (ör. hafta kümeleri duyarlılığı) → kümeler ligde
    yuvalanmaz; hücre (küme × katman) eşlemesi yine doğru olmalı.
    """
    rng = np.random.default_rng(seed)
    n_cl, per = 12, 200
    n = n_cl * per
    cluster = np.repeat([f"L|{2006 + k}" for k in range(n_cl)], per)
    league = np.full(n, "L") if nested else np.where(np.arange(n) % 3 == 0, "L1", "L2")
    shock = np.repeat(rng.normal(0, 0.25, n_cl), per)
    p = np.array([0.1, 0.2, 0.3, 0.4, 0.5])[np.arange(n) % 5]
    lg_eff = np.where(league == "L1", 1.3, 1.0)  # ligler arası taban farkı (katmanlama bunu ayırmalı)
    y = (rng.random(n) < np.clip(p * np.exp(shock) * lg_eff, 0, 1)).astype(float)
    A = (rng.random(n) < np.clip(0.3 + shock, 0.05, 0.95)).astype(float)
    Bt = (rng.random(n) < 0.4).astype(float)
    Bt[rng.random(n) < 0.1] = np.nan
    arrays = {"cluster": cluster, "is_home": (np.arange(n) // 5) % 2 == 0, "p": p, "y": y, "A": A, "B": Bt,
              "league": league}
    arrays = {k: np.repeat(v, dup) for k, v in arrays.items()}  # her satır aynı kümede dup kez
    tm = pd.DataFrame({"is_home": arrays["is_home"], "league": arrays["league"]})
    return SimpleNamespace(tm=tm, cluster=arrays["cluster"], p0={"T": arrays["p"]}, y={"T": arrays["y"]},
                           atoms={"A": arrays["A"], "B": arrays["B"]})


FAKE_CONDS = [("A", ("A",)), ("A & B", ("A", "B"))]


@pytest.mark.parametrize("nested", [True, False])
def test_cr1_matches_manual_computation(nested):
    fr = _fake_frame(nested=nested)
    mask = np.ones(len(fr.cluster), dtype=bool)
    df = P.evaluate(fr, mask, conditions=FAKE_CONDS, targets=("T",), min_n=0, min_e=0).set_index("condition")
    for name, atoms in FAKE_CONDS:
        d = pd.DataFrame({"g": fr.cluster, "p": fr.p0["T"], "y": fr.y["T"], "home": fr.tm["is_home"],
                          "lg": fr.tm["league"]})
        vals = np.column_stack([fr.atoms[a] for a in atoms])
        d = d[np.isfinite(vals).all(axis=1)].copy()
        d["c"] = (vals[np.isfinite(vals).all(axis=1)] == 1).all(axis=1).astype(float)
        cuts = np.quantile(fr.p0["T"], [0.2, 0.4, 0.6, 0.8])
        d["s"] = (d["lg"] + "|" + d["home"].astype(int).astype(str) + "|"
                  + np.searchsorted(cuts, d["p"], side="right").astype(str))
        st = d.groupby("s").agg(O=("y", "sum"), E=("p", "sum"))
        st["Ec"] = d[d["c"] == 1].groupby("s")["p"].sum()
        st = st.fillna(0.0)
        st["r"] = st["O"] / st["E"]
        d = d.join(st[["r", "E", "Ec"]], on="s")
        d["psi"] = (d["c"] - d["Ec"] / d["E"]) * (d["y"] - d["p"] * d["r"])
        U = d.groupby("g")["psi"].sum()
        G = len(U)
        V = G / (G - 1) * float((U ** 2).sum())
        T = float((d["c"] * d["y"]).sum() - (d["c"] * d["p"] * d["r"]).sum())
        assert float(d["psi"].sum()) == pytest.approx(T)  # ψ toplamı = T (tam ayrışım)
        assert df.at[name, "V"] == pytest.approx(V, rel=1e-10)
        assert df.at[name, "T"] == pytest.approx(T, rel=1e-10)
        assert df.at[name, "z"] == pytest.approx(T / math.sqrt(V), rel=1e-10)


def test_duplicated_rows_do_not_inflate_evidence():
    """Çakışan pencereler gibi aynı kümede tekrarlanan satırlar: CR1 z değişmez; naif binom z √2 büyür."""
    base, dup = _fake_frame(1), _fake_frame(2)
    out = []
    for fr in (base, dup):
        mask = np.ones(len(fr.cluster), dtype=bool)
        df = P.evaluate(fr, mask, conditions=FAKE_CONDS, targets=("T",), min_n=0, min_e=0)
        a = np.asarray(fr.atoms["A"]) == 1
        q = np.asarray(fr.p0["T"])
        naive = df["T"].iat[0] / math.sqrt(float((q[a] * (1 - q[a])).sum()))
        out.append((df, naive))
    (d1, n1), (d2, n2) = out
    np.testing.assert_allclose(d2["T"], 2 * d1["T"], rtol=1e-10)
    np.testing.assert_allclose(d2["V"], 4 * d1["V"], rtol=1e-10)
    np.testing.assert_allclose(d2["z"], d1["z"], rtol=1e-10)
    assert n2 / n1 == pytest.approx(math.sqrt(2), rel=1e-6)


def test_calibration_gate(fr0):
    mask = _mask(fr0, ["kesif"])
    gate = P.calibration_gate(fr0, mask)
    assert len(gate) == 8 and set(gate["side"]) == {"ev", "deplasman"}
    assert (gate["passed"] == ((gate["lo"] <= 1) & (gate["hi"] >= 1))).all()
    assert gate.attrs["passed"] == bool(gate["passed"].all())
    bad = dataclasses.replace(fr0, p0={k: v * 1.3 for k, v in fr0.p0.items()})
    g2 = P.calibration_gate(bad, mask)
    assert not g2.attrs["passed"]
    assert (g2.loc[g2["target"] == "GALIBIYET", "hi"] < 1).all()


# ----------------------------------------------------------------------------
# Referans süreç
# ----------------------------------------------------------------------------

def test_simulate_codes_consistency_and_remask(fr0):
    tm = fr0.tm.copy()
    ht_res, ft_res = tm["ht_res"].to_numpy().copy(), tm["ft_res"].to_numpy().copy()
    mask = _mask(fr0, ["kesif"])
    sim_pairs = NL.simulation_pairs(fr0, mask)
    pair = tm["pair_id"].to_numpy()
    in_sim = sim_pairs[pair]
    cand = np.unique(pair[in_sim])
    p_ht, p_ft = cand[3], cand[11]  # bir maçta İY yok, birinde MS yok (hükmen olabilir)
    ht_res[pair == p_ht] = None
    ht_res[pair == p_ft] = None
    ft_res[pair == p_ft] = None
    tm["ht_res"], tm["ft_res"] = ht_res, ft_res
    fr = dataclasses.replace(fr0, tm=tm)
    ht, ft = NL.simulate_codes(fr, sim_pairs, np.random.default_rng(1))
    rht, rft = outcome_codes(tm)
    assert (ht[pair == p_ht] == -1).all() and (ft[pair == p_ht] >= 0).all()
    assert (ht[pair == p_ft] == -1).all() and (ft[pair == p_ft] == -1).all()
    # dönem dışı satırlar gerçek kodlarını korur
    assert np.array_equal(ht[~in_sim], rht[~in_sim]) and np.array_equal(ft[~in_sim], rft[~in_sim])
    # ikiz satırlar tutarlı (aynı ham hücre)
    mirror = tm["mirror_row"].to_numpy()
    both = in_sim & (ht >= 0) & (ft >= 0)
    assert np.array_equal(ft[both], 2 - ft[mirror][both]) and np.array_equal(ht[both], 2 - ht[mirror][both])
    assert not np.array_equal(ht[in_sim], rht[in_sim])  # gerçekten yeniden çekildi
    # ham hücre → takım hücresi eşlemesi sözleşmedeki tabloyla uyumlu
    assert all(RAW_TO_TEAM_CELL[i][0] + RAW_TO_TEAM_CELL[i][1] == 8 for i in range(9))


def test_null_reproducible(fr0):
    mask = _mask(fr0, ["kesif"])
    prep = P.prepare(fr0, mask)
    a = NL.run_null(fr0, mask, 3, 7, prep=prep, **SMALL)
    b = NL.run_null(fr0, mask, 3, 7, prep=prep, **SMALL)
    c = NL.run_null(fr0, mask, 3, 8, prep=prep, **SMALL)
    np.testing.assert_array_equal(a["z"], b["z"])
    np.testing.assert_array_equal(a["supported"], b["supported"])
    assert not np.allclose(np.nan_to_num(a["z"]), np.nan_to_num(c["z"]))
    assert a["z"].shape == (3, 800)
    # aynı SeedSequence nesnesi iki kez verilse de sonuç aynı (spawn nesneyi değiştirmemeli)
    ss = np.random.SeedSequence(7)
    d1 = NL.run_null(fr0, mask, 2, ss, prep=prep, **SMALL)
    d2 = NL.run_null(fr0, mask, 2, ss, prep=prep, **SMALL)
    np.testing.assert_array_equal(d1["z"], d2["z"])
    np.testing.assert_array_equal(d1["z"], a["z"][:2])  # int tohum ile aynı akış
    # paralel parçalar (reps) birleşince tek çalıştırmayla birebir aynı
    parts = [NL.run_null(fr0, mask, 3, 7, prep=prep, reps=r, **SMALL) for r in (range(0, 1), range(1, 3))]
    np.testing.assert_array_equal(np.vstack([p["z"] for p in parts]), a["z"])
    np.testing.assert_array_equal(np.vstack([p["T"] for p in parts]), a["T"])
    with pytest.raises(ValueError):
        NL.run_null(fr0, mask, 3, 7, prep=prep, reps=[3], **SMALL)


def test_null_never_reads_goal_columns(fr0):
    mask = _mask(fr0, ["kesif"])
    tm = fr0.tm.copy()
    for col in ("gf_ht", "ga_ht", "gf_ft", "ga_ft", "gf_2h", "ga_2h"):
        tm[col] = np.nan
    fr_nan = dataclasses.replace(fr0, tm=tm)
    a = NL.run_null(fr0, mask, 2, 11, **SMALL)
    b = NL.run_null(fr_nan, mask, 2, 11, **SMALL)
    np.testing.assert_array_equal(a["z"], b["z"])
    np.testing.assert_array_equal(a["T"], b["T"])
    np.testing.assert_array_equal(a["supported"], b["supported"])


def test_null_centred(null0):
    obs, nul = null0
    T, R = nul["T"], nul["T"].shape[0]
    sup = obs["supported"].to_numpy() & (np.nanstd(T, axis=0) > 0)
    assert sup.sum() > 100
    t = T[:, sup].mean(axis=0) / (T[:, sup].std(axis=0, ddof=1) / math.sqrt(R))
    assert np.mean(np.abs(t) > 4) <= 0.02
    pooled = T[:, sup].sum(axis=1)
    assert abs(pooled.mean() / (pooled.std(ddof=1) / math.sqrt(R))) < 4
    # simüle hedeflerin ortalaması S0 beklentisine yakın (taban oran korunur)
    assert np.nanmean(nul["z"][:, sup]) == pytest.approx(0.0, abs=0.5)


# ----------------------------------------------------------------------------
# Çoklu test
# ----------------------------------------------------------------------------

def _wy_brute(z_obs, sup_obs, z_null, sup_null, include_unsupported_obs=True):
    R, H = z_null.shape
    fam = [h for h in range(H) if sup_obs[h] and np.isfinite(z_obs[h])]
    order = sorted(fam, key=lambda h: (-abs(z_obs[h]), h))
    out = np.full(H, np.nan)
    prev = -1
    for j, h in enumerate(order):
        remaining = set(order[j:])
        if include_unsupported_obs:
            remaining |= {k for k in range(H) if k not in fam}
        cnt = 0
        for r in range(R):
            vals = [abs(z_null[r, k]) for k in remaining if sup_null[r, k] and np.isfinite(z_null[r, k])]
            if vals and max(vals) >= abs(z_obs[h]):
                cnt += 1
        prev = max(prev, cnt)
        out[h] = (prev + 1) / (R + 1)
    return out


def test_westfall_young_matches_brute_force_and_is_monotone():
    rng = np.random.default_rng(0)
    R, H = 60, 12
    z_null = rng.normal(size=(R, H))
    sup_null = rng.random((R, H)) > 0.15
    z_obs = rng.normal(size=H) * 1.5
    z_obs[0], z_obs[1] = 3.5, -2.9
    sup_obs = np.ones(H, dtype=bool)
    sup_obs[[4, 9]] = False
    for inc in (True, False):
        p, lo, hi = NL.westfall_young_stepdown(z_obs, sup_obs, z_null, sup_null, include_unsupported_obs=inc)
        ref = _wy_brute(z_obs, sup_obs, z_null, sup_null, inc)
        np.testing.assert_allclose(p, ref, equal_nan=True)
        assert np.isnan(p[[4, 9]]).all()
        order = np.argsort(-np.abs(np.where(sup_obs, z_obs, 0)))
        order = [h for h in order if sup_obs[h]]
        assert np.all(np.diff(p[order]) >= 0)  # |z| azaldıkça düzeltilmiş p azalmaz (monotonluk)
        assert np.all(lo[order] <= (p[order] * (R + 1) - 1) / R + 1e-12)
        assert np.all(hi[order] >= (p[order] * (R + 1) - 1) / R - 1e-12)
    # tekrarda desteklenmeyen hipotez o tekrarın maksimumuna girmez
    zn = np.array([[10.0, 0.1], [0.2, 0.1]])
    p, _, _ = NL.westfall_young_stepdown(np.array([1.0, 0.5]), np.array([True, True]), zn,
                                         np.array([[False, True], [True, True]]))
    assert p[0] == pytest.approx(1 / 3)


def test_by_and_holm():
    z = np.array([4.0, 2.5, 1.0, np.nan, -3.0])
    by = NL.by_descriptive(z)
    assert np.isnan(by[3]) and np.all(by[np.isfinite(z)] <= 1)
    p = 2 * (1 - pd.Series(np.abs(z)).apply(lambda v: 0.5 * (1 + math.erf(v / math.sqrt(2))))).to_numpy()
    cm = sum(1 / i for i in range(1, 5))
    assert by[0] == pytest.approx(min(1.0, p[0] * 4 * cm / 1, p[4] * 4 * cm / 2), rel=1e-6)
    h = P.holm_one_sided(np.array([3.0, 2.0, -1.0]), np.array([1, 1, -1]))
    ps = h["p_one"]
    srt = np.sort(ps)
    manual = np.maximum.accumulate(np.minimum(1, (3 - np.arange(3)) * srt))
    np.testing.assert_allclose(np.sort(h["p_holm"]), manual)
    assert h["reject"][0] and not h["reject"][2]


def test_select_candidates_rules():
    def row(t, atoms, lift, sig=True, ci_hi=0.01, half=0.1):
        return {"hyp_id": f"{t}|{' & '.join(atoms)}", "target": t, "atoms": tuple(atoms), "lift": lift,
                "lift_lo": lift - half, "lift_hi": lift + half, "p_adj": 0.01 if sig else 0.5,
                "ci_hi": ci_hi, "supported": True}

    rows = [row("G", ["A"], 1.2), row("G", ["B"], 1.1), row("G", ["A", "B"], 1.5), row("G", ["A", "C"], 1.15),
            row("G", ["C"], 1.0, sig=False), row("G", ["B", "D"], 0.7), row("G", ["D"], 1.05, sig=False),
            row("G", ["E"], 1.3, ci_hi=0.06), row("G", ["F"], 0.6), row("M", ["A"], 1.25),
            row("G", ["A", "EV_SAHIBI"], 1.3)]
    res = pd.DataFrame(rows)
    ref = pd.DataFrame([row("G", ["EV_SAHIBI"], 1.4, sig=False)])
    out = P.select_candidates(res, reference=ref)
    ids = list(out["hyp_id"])
    assert "G|A & B" in ids  # iki tek atomdan da güçlü, aynı yön
    assert "G|A & C" not in ids  # A'dan zayıf
    assert "G|B & D" not in ids  # B ile ters yön
    assert "G|E" not in ids  # MC aralığı α'yı içeriyor
    assert "G|A & EV_SAHIBI" not in ids  # bağlam tek başına daha güçlü
    assert "G|A" not in ids and "G|B" not in ids  # aynı hedefte atom paylaşımı (A & B seçildi)
    assert "M|A" in ids and "G|F" in ids  # farklı hedef atom paylaşabilir
    assert list(out["rank"]) == list(range(1, len(out) + 1))
    assert out.set_index("hyp_id").at["G|F", "direction"] == -1
    lcb = out["lcb_abs_log_lift"].to_numpy()
    assert np.all(np.diff(lcb) <= 1e-12)
    many = pd.DataFrame([row("G", [f"X{i}"], 1.1 + 0.05 * i) for i in range(9)])
    sel = P.select_candidates(many)
    assert len(sel) == C.MAX_CANDIDATES and sel["hyp_id"].iat[0] == "G|X8"
    assert out.attrs["cift_kurali_dogrulanamadi"] == []
    # bağlam atomunun (veya ayna kopyası olarak çıkarılmış tek atomun) oranı yoksa çift kuralı doğrulanamaz →
    # çift elenir ve uyarılır (sessizce geçirilmez, uzun koşuyu da düşürmez)
    big = pd.DataFrame([row("G", ["A"], 1.2), row("G", ["A", "EV_SAHIBI"], 1.6)])
    with pytest.warns(UserWarning, match="doğrulanamadı"):
        out2 = P.select_candidates(big)
    assert "G|A & EV_SAHIBI" not in list(out2["hyp_id"])
    assert out2.attrs["cift_kurali_dogrulanamadi"] == ["G|A & EV_SAHIBI"]
    ok_ref = P.select_candidates(big, reference=pd.DataFrame([row("G", ["EV_SAHIBI"], 1.1, sig=False)]))
    assert ok_ref["hyp_id"].iat[0] == "G|A & EV_SAHIBI"
    # tek atom oranı sonlu değilse (O = 0) çift aşılamaz
    zero = pd.DataFrame([row("G", ["A"], 0.0, sig=False), row("G", ["B"], 1.1), row("G", ["A", "B"], 1.5)])
    assert "G|A & B" not in list(P.select_candidates(zero)["hyp_id"])


# ----------------------------------------------------------------------------
# Mod B, yanlışlama, Sorgu 2, plasebo
# ----------------------------------------------------------------------------

def test_mode_b_counts(fr0):
    mask = _mask(fr0)
    target, cond = "GALIBIYET", "SON5_GALIBIYET_EN_AZ_4"
    card = P.mode_b_card(fr0, target, cond, mask)
    assert card["sorgu"] == "Sorgu 1 (maç öncesi)"
    assert card["hits"] + card["misses"] == card["n_cond"]
    a = fr0.atoms[cond]
    y = fr0.y[target]
    valid = mask & np.isfinite(a) & np.isfinite(y)
    assert card["n_cond"] == int((valid & (a == 1)).sum())
    assert card["events_without_cond"] == int((valid & (a == 0) & (y == 1)).sum())
    assert card["n_without_cond"] == int((valid & (a == 0)).sum())
    assert card["rate_with"] == pytest.approx(card["hits"] / card["n_cond"])
    direction = 1 if card["lift"] > 1 else -1
    hits, counters = card["hit_examples"], card["counter_examples"]
    assert 0 < len(hits) <= 20 and 0 < len(counters) <= 20
    assert all(r["y"] == (1.0 if direction > 0 else 0.0) for r in hits)
    assert all(r["y"] == (0.0 if direction > 0 else 1.0) for r in counters)
    if direction > 0:
        assert [r["p0"] for r in counters] == sorted([r["p0"] for r in counters], reverse=True)
    assert sum(r["n"] for r in card["season_table"]) == card["n_cond"]
    assert card["E_s0"] > 0 and np.isfinite(card["matched_base_rate"])


def test_falsification_structure(fr0):
    mask = _mask(fr0)
    out = P.falsification(fr0, "GALIBIYET", "SON5_GALIBIYET_EN_AZ_4", mask)
    assert set(out["checks"]) == {"1_birim_cikarma", "2_ust_yuzde1_cikarma", "3_sezon_yonu", "4_eslestirilmis",
                                  "5_piyasa"}
    assert out["checks"]["5_piyasa"]["durum"] == "not_run" and out["passed_all"] is False
    assert len(out["counter_examples"]) <= 20
    out2 = P.falsification(fr0, "GALIBIYET", "SON5_GALIBIYET_EN_AZ_4", mask, p0_market=fr0.p0["GALIBIYET"])
    assert out2["checks"]["5_piyasa"]["durum"] == "run"
    assert out2["checks"]["5_piyasa"]["lift"] == pytest.approx(out2["lift"])
    # koşul üç biçimde verilebilir: ad, atom demeti, build_conditions öğesi (ad, atomlar)
    name, atoms = "SON5_GALIBIYET_EN_AZ_4 & EV_SAHIBI", ("SON5_GALIBIYET_EN_AZ_4", "EV_SAHIBI")
    cards = [P.mode_b_card(fr0, "GALIBIYET", c, mask) for c in (name, atoms, (name, atoms))]
    assert all(c["kosul"] == name and c["atomlar"] == list(atoms) and c["z"] == cards[0]["z"] for c in cards)
    with pytest.raises(TypeError):
        P.resolve_condition(("A", 3))


def test_falsification_checks_match_refit(fr0):
    """Kontrol 1–3 bağımsız yeniden hesapla aynı: birim çıkarılıp (aynı katmanlarla) yeniden değerlendirme."""
    mask = _mask(fr0)
    target, cond = "GALIBIYET", "SON5_GALIBIYET_EN_AZ_4 & EV_SAHIBI"
    out = P.falsification(fr0, target, cond, mask)
    s = P._single(fr0, target, cond, mask)
    d = out["yon"]
    assert d in (1, -1)
    tm = fr0.tm
    lg = tm["league"].to_numpy()[s.idx]
    team, opp = tm["team"].to_numpy()[s.idx], tm["opponent"].to_numpy()[s.idx]
    units = {"lig": [lg != L for L in np.unique(lg)],
             "takim": [(team != T) & (opp != T) for T in np.unique(np.r_[team, opp])]}
    for nm, keeps in units.items():
        lifts = np.array([P._stats(s, k)["lift"] for k in keeps])
        c1 = out["checks"]["1_birim_cikarma"][nm]
        assert c1["n_birim"] == len(lifts)
        assert c1["min_lift"] == pytest.approx(lifts.min()) and c1["max_lift"] == pytest.approx(lifts.max())
        assert c1["n_yon_degisen"] == int((np.sign(lifts - 1) != d).sum())
        # "en zayıf" birim etki yönünde en olumsuz olandır (1'e en yakın olan değil)
        assert c1["en_zayif"]["lift"] == pytest.approx(lifts.min() if d > 0 else lifts.max())
        assert c1["passed"] == (c1["n_yon_degisen"] == 0)
    assert out["checks"]["1_birim_cikarma"]["takim"]["en_zayif"]["birim"] is None  # kulüp adı yazılmaz
    # 2) O − E'ye en çok katkı veren %1 koşul satırı çıkarılınca
    full = P._stats(s)
    contrib = np.where(s.c, (s.y - s.p * full["r_row"]) * d, -np.inf)
    k = math.ceil(0.01 * full["n"])
    keep = np.ones(len(s.idx), dtype=bool)
    keep[np.argsort(-contrib, kind="mergesort")[:k]] = False
    st2 = P._stats(s, keep)
    c2 = out["checks"]["2_ust_yuzde1_cikarma"]
    assert c2["n_cikarilan"] == k and c2["lift"] == pytest.approx(st2["lift"])
    # 3) sezon yönü: tam dönem r_s ile sezon başına O − E
    seasons = tm["season"].to_numpy()[s.idx]
    same = [np.sign((s.y - s.p * full["r_row"])[s.c & (seasons == se)].sum()) == d
            for se in np.unique(seasons[s.c])]
    assert out["checks"]["3_sezon_yonu"]["pay"] == pytest.approx(np.mean(same))


def test_query2(fr0):
    mask = _mask(fr0)
    df = P.q2_evaluate(fr0, mask)
    assert len(df) == 6 and set(df["sorgu"]) == {"Sorgu 2 (olay sonrası)"}
    assert set(df["target"]) == set(C.Q2_TARGETS) and set(df["event"]) == set(C.Q2_EVENTS)
    inst = P.q2_instances(fr0, mask)
    si = fr0.seq
    pos = si.pos_of_tm[inst["event_row"].to_numpy()]
    teams = fr0.tm["team"].to_numpy()[inst["event_row"].to_numpy()]
    for ev in C.Q2_EVENTS:
        sel = (inst["event"] == ev).to_numpy()
        d = pd.DataFrame({"t": teams[sel], "p": pos[sel]}).sort_values(["t", "p"])
        gaps = d.groupby("t")["p"].diff().dropna()
        assert (gaps >= C.Q2_HORIZON).all()  # çakışmayan pencereler
    assert (si.pos_of_tm[inst["row"].to_numpy()] == pos + 1).all()  # örnek = olaydan sonraki maç
    assert mask[inst["row"].to_numpy()].all()
    nq = NL.run_null_q2(fr0, mask, 3, 1)
    assert nq["z"].shape == (3, 6) and nq["hyp_ids"] == list(df["hyp_id"]) == list(P.Q2_HYP_IDS)
    part = NL.run_null_q2(fr0, mask, 3, 1, reps=range(1, 3))
    np.testing.assert_array_equal(part["z"], nq["z"][1:])
    assert NL.run_null_q2(fr0, mask, 0, 1)["hyp_ids"] == list(P.Q2_HYP_IDS)


def test_query2_matches_brute_force(fr0):
    """Örnek seçimi ve 6 hipotezin O, E, CR1 V'si takım dizisi üzerinde satır döngüsüyle aynı."""
    mask = _mask(fr0, ["kesif", "parametre"])
    df = P.q2_evaluate(fr0, mask).set_index("hyp_id")
    tm = fr0.tm
    ht, ft = outcome_codes(tm)
    H = C.Q2_HORIZON
    spell, complete = tm["spell_id"].to_numpy(), tm["season_complete"].to_numpy()
    skip = tm["season_skip"].to_numpy()
    seq = tm[tm["in_seq"]]
    for ev, (eh, ef) in (("IY_GERIDE_MS_GALIP", (2, 0)), ("IY_ONDE_MS_MAGLUP", (0, 2))):
        acc = defaultdict(list)
        for _, g in seq.groupby("team", sort=False):
            rows = g["row_id"].to_numpy()
            last = -(10 ** 9)
            for j in range(len(rows) - H):
                e, w = rows[j], rows[j + 1: j + 1 + H]
                if not (ht[e] == eh and ft[e] == ef):
                    continue
                if (spell[w] != spell[e]).any() or not complete[np.r_[e, w]].all() or skip[w].any():
                    continue
                if not mask[w].all() or j < last + H:  # ufuk maskede ve önceki seçilen örnekle çakışmıyor
                    continue
                last = j
                g0 = fr0.cluster[w[0]]
                if ft[w[0]] >= 0:
                    acc["SONRAKI_GALIBIYET"].append((g0, float(ft[w[0]] == 0), fr0.p_win[w[0]]))
                w3 = w[:3]
                if (ht[w3] >= 0).all() and (ft[w3] >= 0).all():
                    acc["SONRAKI3_AYNI_OLAY"].append((g0, float(((ht[w3] == eh) & (ft[w3] == ef)).any()),
                                                      1.0 - np.prod(1.0 - fr0.p0[ev][w3])))
                if (ft[w] >= 0).all():
                    pts = float(np.where(ft[w] == 0, 3, np.where(ft[w] == 1, 1, 0)).sum())
                    acc["SONRAKI5_PUAN"].append((g0, pts, fr0.exp_points[w].sum()))
        for tgt in C.Q2_TARGETS:
            d = pd.DataFrame(acc[tgt], columns=["g", "y", "e"])
            U = (d["y"] - d["e"]).groupby(d["g"]).sum()
            V = len(U) / (len(U) - 1) * float((U ** 2).sum())
            r = df.loc[f"Q2|{ev}|{tgt}"]
            assert r["n"] == len(d) > 20
            assert r["O"] == pytest.approx(d["y"].sum()) and r["E"] == pytest.approx(d["e"].sum())
            assert r["V"] == pytest.approx(V) and r["G"] == len(U)


def test_placebo_donors_and_run(fr0):
    rng = np.random.default_rng(4)
    atoms, donor = NL.placebo_atoms(fr0, rng)
    tm = fr0.tm
    ok = donor >= 0
    assert ok.mean() > 0.95
    assert (fr0.cluster[donor[ok]] == fr0.cluster[ok]).all()
    assert (tm["team"].to_numpy()[donor[ok]] != tm["team"].to_numpy()[ok]).all()
    assert (tm["team"].to_numpy()[donor[ok]] != tm["opponent"].to_numpy()[ok]).all()
    # zaman güvenliği: bağışçı satırdan sonra oynanmamış; böylece bağışçının RAKIP_* atomları satırın kendi
    # maçını (hedefini) içeremez
    dates = tm["date"].to_numpy()
    assert (dates[donor[ok]] <= dates[ok]).all()
    d_opp = tm["opponent"].to_numpy()[donor[ok]]
    same_day = dates[donor[ok]] == dates[ok]
    assert not ((d_opp == tm["team"].to_numpy()[ok]) | (d_opp == tm["opponent"].to_numpy()[ok]))[same_day].any()
    assert same_day.mean() > 0.5  # en yakın tarih çoğunlukla aynı tur
    k = "SON5_IY_GERIDE_EN_AZ_2"
    np.testing.assert_array_equal(atoms[k][ok], fr0.atoms[k][donor[ok]])
    np.testing.assert_array_equal(atoms["EV_SAHIBI"], fr0.atoms["EV_SAHIBI"])
    mask = _mask(fr0, ["kesif"])
    res = NL.run_placebo(fr0, mask, seeds=[1, 2], R=4, **SMALL)
    assert res["n_seeds"] == 2 and res["R"] == 4
    assert {"seed", "n_discoveries", "discoveries", "n_supported"} <= set(res["seeds"][0])
    assert res["passed"] == (res["n_seeds_with_discovery"] <= C.PLACEBO_MAX_DISCOVERIES)


# ----------------------------------------------------------------------------
# Uçtan uca: rastgele hedef (etki yok) ve yerleştirilmiş etki
# ----------------------------------------------------------------------------

def test_random_target_no_wy_discovery_most_seeds(fr0, null0):
    """S0 = gerçek, dizi etkisi yok: WY keşfi 3 tohumun en az 2'sinde çıkmamalı (olasılıksal; FWER ≈ %5)."""
    no_disc = 0
    for seed in (0, 1, 2):
        if seed == 0:
            obs, nul = null0
        else:
            fr, _, _ = synthetic_frame(seed)
            mask = _mask(fr)
            prep = P.prepare(fr, mask)
            obs = P.evaluate(fr, mask, prep=prep, **SMALL)
            nul = NL.run_null(fr, mask, 30, 3, prep=prep, **SMALL)
        p_adj, _, _ = NL.westfall_young_stepdown(obs["z"].to_numpy(), obs["supported"].to_numpy(), nul["z"],
                                                 nul["supported"])
        assert obs["supported"].sum() > 100
        no_disc += int(not (np.nan_to_num(p_adj, nan=1.0) < C.ALPHA).any())
    assert no_disc >= 2


def test_planted_effect_detected(planted):
    fr = planted
    mask = _mask(fr)
    support = {"min_n": 300, "min_e": 10.0}
    prep = P.prepare(fr, mask)
    obs = P.evaluate(fr, mask, prep=prep, **support).set_index("hyp_id", drop=False)
    h = "IY_GERIDE_MS_GALIP|SON_MAC_IY_GERIDE_MS_GALIP"
    r = obs.loc[h]
    assert r["supported"] and r["z"] > 4 and r["lift_lo"] > 1.5
    nul = NL.run_null(fr, mask, 20, 3, prep=prep, **support)
    p_adj, lo, hi = NL.westfall_young_stepdown(obs["z"].to_numpy(), obs["supported"].to_numpy(), nul["z"],
                                               nul["supported"])
    obs["p_adj"], obs["ci_lo"], obs["ci_hi"] = p_adj, lo, hi
    assert obs.at[h, "p_adj"] < C.ALPHA  # R = 20 ile ulaşılabilecek en küçük p = 1/21
    fa = P.falsification(fr, "IY_GERIDE_MS_GALIP", "SON_MAC_IY_GERIDE_MS_GALIP", mask)
    assert fa["yon"] == 1 and fa["passed_1_4"]
    ce = fa["counter_examples"]
    assert len(ce) == 20 and all(c["y"] == 0.0 for c in ce)
    assert [c["p0"] for c in ce] == sorted([c["p0"] for c in ce], reverse=True)

"""Dizi modülü temel katmanı: takım-maç tablosu, kimlik eşlemesi, kapsam, pencereler, atomlar, çerçeve, S0 kalibrasyonu.

Yalnızca sentetik (açıkça test amaçlı) veri ve geçici dizinler kullanılır.
"""

import numpy as np
import pandas as pd
import pytest

from bahis_tahmin.goals.markets import HTFT_KEYS
from bahis_tahmin.sequences import config as C
from bahis_tahmin.sequences.aliases import AliasMap, detect_intra_season_splits
from bahis_tahmin.sequences.features import SeqIndex, history_atoms, outcome_codes
from bahis_tahmin.sequences.frame import build_frame, team_cell_probs
from bahis_tahmin.sequences.s0 import calibrated_cells
from bahis_tahmin.sequences.synthetic import synthetic_frame, synthetic_matches
from bahis_tahmin.sequences.timeline import (
    build_team_matches,
    coverage_report,
    event_card,
    possible_awarded,
    team_events,
    window_rows,
)


@pytest.fixture(scope="module")
def synth():
    m, probs = synthetic_matches(n_leagues=2, n_seasons=26, n_teams=10, seed=3)
    return m, probs


@pytest.fixture(scope="module")
def tm(synth):
    return build_team_matches(synth[0])


def _atoms(tm, probs):
    fr = build_frame(tm, probs, with_s1=True)
    return fr


def test_two_rows_per_match_with_mirror_consistency(tm):
    assert len(tm) == 2 * tm["pair_id"].nunique()
    mr = tm["mirror_row"].to_numpy()
    assert (tm["pair_id"].to_numpy()[mr] == tm["pair_id"].to_numpy()).all()
    assert (tm["is_home"].to_numpy()[mr] != tm["is_home"].to_numpy()).all()
    # İkiz satırlar aynı tarih, sezon yılı ve küme → bölmelerde ayrılamaz
    for c in ("date", "season_year", "league", "season"):
        assert (tm[c].to_numpy()[mr] == tm[c].to_numpy()).all()
    # Ev 2/1 ↔ deplasman 'İY önde MS mağlup'
    h21 = tm["is_home"] & (tm["htft"] == "HTFT_2_1")
    assert (tm.loc[h21, "IY_GERIDE_MS_GALIP"] == 1).all()
    assert (tm.iloc[mr[h21.to_numpy()]]["IY_ONDE_MS_MAGLUP"] == 1).all()


def test_post_event_data_never_enters_pre_event_features(synth):
    m, probs = synth
    tm0 = build_team_matches(m)
    fr0 = _atoms(tm0, probs)
    row = int(tm0.index[(tm0["season_year"] == 2010) & tm0["in_seq"]][100])
    d0 = tm0.loc[row, "date"]
    # t0 maçının ve sonraki tüm maçların sonucunu değiştir
    m2 = m.copy()
    later = m2["date"] >= d0
    m2.loc[later, ["hthg", "htag", "fthg", "ftag"]] = [3.0, 0.0, 3, 5]
    tm1 = build_team_matches(m2)
    fr1 = _atoms(tm1, probs)
    upto = tm0["date"] <= d0
    for k, v in fr0.atoms.items():
        a, b = v[upto.to_numpy()], fr1.atoms[k][upto.to_numpy()]
        assert np.allclose(np.nan_to_num(a, nan=-1), np.nan_to_num(b, nan=-1)), k
    s1a = fr0.s1[upto.to_numpy()].to_numpy(dtype=float)
    s1b = fr1.s1[upto.to_numpy()].to_numpy(dtype=float)
    assert np.allclose(np.nan_to_num(s1a, nan=-9), np.nan_to_num(s1b, nan=-9))


def test_adding_future_matches_does_not_change_past_features(synth):
    m, probs = synth
    cut = pd.Timestamp("2015-07-01")
    past = m[m["date"] < cut]
    fr_past = _atoms(build_team_matches(past), probs)
    fr_all = _atoms(build_team_matches(m), probs)
    key = ["event_id", "is_home"]
    a = fr_past.tm[key].assign(**{k: v for k, v in fr_past.atoms.items()})
    b = fr_all.tm[key].assign(**{k: v for k, v in fr_all.atoms.items()})
    j = a.merge(b, on=key, suffixes=("_p", "_a"))
    assert len(j) == len(a)
    for k in fr_past.atoms:
        assert np.allclose(np.nan_to_num(j[f"{k}_p"], nan=-1), np.nan_to_num(j[f"{k}_a"], nan=-1)), k


def test_unplayed_next_matches_are_censored_not_filled(tm):
    team = tm["team"].iloc[0]
    last = int(tm.index[tm["team"] == team][-1])
    w, state = window_rows(tm, last, 3, forward=True)
    assert len(w) == 0 and state == "RIGHT_CENSORED"
    card = event_card(tm, last)
    assert card["POST_EVENT"]["sonraki_5"]["maclar"] == []
    assert card["POST_EVENT"]["sonraki_5"]["durum"] == "RIGHT_CENSORED"


def test_open_intervals_are_kept(tm):
    team = tm["team"].iloc[0]
    ev = team_events(tm, team, target="IY_GERIDE_MS_GALIP")
    tail = ev.attrs["censored_tail"]
    assert tail["acik_aralik_mac"] >= 0 and tail["bitis_nedeni"] == "RIGHT_CENSORED"
    assert "olmayacak" in tail["not"]


def test_intra_season_split_detection_and_manual_aliases():
    m, _ = synthetic_matches(n_leagues=1, n_seasons=3, n_teams=8, seed=5)
    # sezon ortasında bir takımın kaynak adı değişsin
    s = m["season"] == m["season"].iloc[-1]
    dates = m.loc[s, "date"]
    mid = dates.min() + (dates.max() - dates.min()) / 2
    old = m["home"].iloc[0]
    rename = s & (m["date"] > mid)
    m.loc[rename & (m["home"] == old), "home"] = old + " FC"
    m.loc[rename & (m["away"] == old), "away"] = old + " FC"
    splits = detect_intra_season_splits(m)
    assert list(splits.values()) == [old]
    am = AliasMap(splits)
    tm = build_team_matches(m, am)
    assert (tm["team"] == old + " FC").sum() == 0 and (tm["team_raw"] == old + " FC").sum() > 0
    assert am.canonical("Roda", "Hollanda") == "Roda JC"  # katman 2
    assert am.canonical("AFC Wimbledon", "İngiltere") == "AFC Wimbledon"  # ardıl kulüp eşlenmez


def test_scottish_format_and_upper_rounds():
    rows = []
    teams = [f"T{i}" for i in range(4)]
    d = pd.Timestamp("2010-08-01")
    # 4 takım, SC1 formatı: takım başına 36 normal maç beklenir → 2(n−1)=6 değil
    k = 0
    for rnd in range(12):
        for a, b in ((0, 1), (2, 3)) if rnd % 2 == 0 else ((1, 2), (3, 0)):
            rows.append({"league": "SC1", "season": "2010/11", "date": d + pd.Timedelta(days=7 * k), "time": "",
                         "home": teams[a], "away": teams[b], "fthg": 1, "ftag": 0, "hthg": 0.0, "htag": 0.0, "source": "SENTETIK-TEST"})
        k += 1
    # veri sonu çok daha ileride olsun (bu sezon "devam eden sezon" sayılmasın)
    rows.append({"league": "E0", "season": "2012/13", "date": pd.Timestamp("2013-01-05"), "time": "", "home": "X",
                 "away": "Y", "fthg": 1, "ftag": 1, "hthg": 0.0, "htag": 0.0, "source": "SENTETIK-TEST"})
    from bahis_tahmin.data.parsers import MATCH_COLUMNS
    m = pd.DataFrame(rows)
    for c in MATCH_COLUMNS:
        if c not in m.columns:
            m[c] = np.nan
    tm = build_team_matches(m[MATCH_COLUMNS])
    sc = tm[tm["league"] == "SC1"]
    assert (sc["regular_len"] == 36).all()
    assert not sc["ust_tur"].any()
    cov = coverage_report(tm).set_index("league")
    assert not cov.loc["SC1", "tam"]  # 12/36 maç → eksik sezon


def test_possible_awarded_rows_have_unknown_result(tm, synth):
    m = synth[0].copy()
    i = 50
    m.loc[i, ["hthg", "htag", "fthg", "ftag"]] = [np.nan, np.nan, 3, 0]
    assert possible_awarded(m)[i]
    t2 = build_team_matches(m)
    rows = t2[t2["event_id"] == t2["event_id"][t2["awarded"]].iloc[0]]
    assert rows["ft_res"].isna().all() and rows["GALIBIYET"].isna().all() and (rows["cell"] == -1).all()


def test_eligibility_excludes_first_matches_after_league_change(synth):
    m, probs = synth
    fr = build_frame(build_team_matches(m), probs, with_s1=False)
    tm = fr.tm
    early = tm["since_league_change"] < C.LEAGUE_CHANGE_EXCLUDE
    assert not fr.eligible[early.to_numpy()].any()


def test_team_cell_mapping_and_probabilities_sum_to_one(synth):
    m, probs = synth
    fr = build_frame(build_team_matches(m), probs, with_s1=False)
    ok = np.isfinite(fr.raw_probs).all(axis=1)
    assert np.allclose(fr.team_probs[ok].sum(axis=1), 1.0)
    assert np.allclose(fr.p0["GALIBIYET"][ok] + fr.p0["BERABERLIK"][ok] + fr.p0["MAGLUBIYET"][ok], 1.0)
    # ev satırında ham 2/1 = takım (M, G)
    raw = np.eye(9)[[HTFT_KEYS.index("HTFT_2_1")]]
    tp_home = team_cell_probs(raw, np.array([True]))
    tp_away = team_cell_probs(raw, np.array([False]))
    from bahis_tahmin.sequences.timeline import CELL_INDEX
    assert tp_home[0, CELL_INDEX[("M", "G")]] == 1 and tp_away[0, CELL_INDEX[("G", "M")]] == 1


def test_atoms_only_use_outcome_codes(synth):
    m, probs = synth
    tm = build_team_matches(m)
    fr = build_frame(tm, probs, with_s1=False)
    ht, ft = outcome_codes(tm)
    tm2 = tm.copy()
    tm2[["gf_ht", "ga_ht", "gf_ft", "ga_ft", "gf_2h", "ga_2h"]] = np.nan  # gol sütunları okunmamalı
    a2 = history_atoms(SeqIndex(tm2), ht, ft, fr.exp_points)
    for k, v in fr.atoms.items():
        if k in a2:
            assert np.allclose(np.nan_to_num(v, nan=-1), np.nan_to_num(a2[k], nan=-1)), k


def test_calibration_is_identity_until_enough_history_and_uses_only_past():
    rng = np.random.default_rng(0)
    n = 30000
    P = rng.dirichlet(np.ones(9) * 3, size=n)
    folds = np.repeat(np.arange(2002, 2008), n // 6)
    y = np.array([rng.choice(9, p=p) for p in P])
    s0 = pd.DataFrame(P, columns=list(HTFT_KEYS))
    s0.insert(0, "event_id", [f"e{i}" for i in range(n)])
    s0["fold"] = folds
    q, params = calibrated_cells(s0, pd.Series(y))
    assert params[2002] == [0.0] * 9  # önceki örneklem dışı sezon yok → özdeşlik
    first = folds == 2002
    assert np.allclose(q.loc[first, list(HTFT_KEYS)].to_numpy(), P[first])
    # gelecekteki sonuçlar değişince geçmiş sezonun kalibrasyonu değişmez
    y2 = y.copy()
    y2[folds == 2007] = 0
    q2, params2 = calibrated_cells(s0, pd.Series(y2))
    assert params2[2005] == params[2005]
    assert np.allclose(q2[list(HTFT_KEYS)].to_numpy()[folds < 2007], q[list(HTFT_KEYS)].to_numpy()[folds < 2007])

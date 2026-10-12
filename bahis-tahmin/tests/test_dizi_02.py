"""DIZI-02: "Takım-maç tablosu kurulamadı: Aynı takımın aynı gün birden fazla maçı var" düzeltmesi.

Gerçek veride (yedek veri seti, 38 lig) ham veride aynı gün çakışması yoktu; çakışmayı katman 1 kimlik kuralının
yanlış pozitifleri üretiyordu: sezon sınırında düşen ve çıkan iki farklı kulüp "sezon ortası ad değişikliği" sanılıp
birleştiriliyor, eşleme bütün sezonlara uygulanınca aynı kulübe aynı gün iki maç yazılıyordu. Yalnızca SENTETİK veri.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bahis_tahmin.data.parsers import MATCH_COLUMNS
from bahis_tahmin.sequences.aliases import AliasMap, detect_intra_season_splits
from bahis_tahmin.sequences.timeline import build_team_matches

START = pd.Timestamp("2018-08-04")


def _rounds(teams: list[str], n_rounds: int):
    """Basit dönüşümlü fikstür (çember yöntemi); her turda her takım bir kez oynar."""
    t = list(teams)
    for r in range(n_rounds):
        half = len(t) // 2
        yield [(t[i], t[-1 - i]) if r % 2 == 0 else (t[-1 - i], t[i]) for i in range(half)]
        t = [t[0]] + [t[-1]] + t[1:-1]


def _frame(rows) -> pd.DataFrame:
    m = pd.DataFrame(rows)
    m["fthg"], m["ftag"], m["hthg"], m["htag"] = 1, 0, 0.0, 0.0
    m["time"], m["source"] = "", "SENTETIK-TEST"
    for c in MATCH_COLUMNS:
        if c not in m.columns:
            m[c] = np.nan
    return m[MATCH_COLUMNS]


def _season(league, season, teams, start, n_rounds, slot=None):
    """``slot``: (yer tutucu, ilk_ad, sonraki_ad, geçiş_turu) — sezon ortasında adı değişen tek takım."""
    rows = []
    for r, games in enumerate(_rounds(teams, n_rounds)):
        d = start + pd.Timedelta(days=7 * r)
        for h, a in games:
            if slot:
                ph, first, then, at = slot
                h = (first if r < at else then) if h == ph else h
                a = (first if r < at else then) if a == ph else a
            rows.append({"league": league, "season": season, "date": d, "home": h, "away": a})
    return rows


def test_genuine_mid_season_rename_is_still_detected():
    rows = _season("E0", "2018/19", ["A", "B", "C", "SLOT"], START, 20, ("SLOT", "Eski Ad", "Yeni Ad", 10))
    m = _frame(rows)
    assert detect_intra_season_splits(m) == {("İngiltere", "Yeni Ad"): "Eski Ad"}
    tm = build_team_matches(m)
    assert set(tm["team"]) == {"A", "B", "C", "Eski Ad"}


def test_season_boundary_is_not_a_rename():
    """Sezon etiketi iki gerçek sezonu kapsıyor: E ve F düşüyor, G ve H çıkıyor (birlikte ayrılıp katılıyorlar)."""
    first = _season("POL", "2018", ["A", "B", "C", "D", "E", "F"], START, 10)
    second = _season("POL", "2018", ["A", "B", "C", "D", "G", "H"], START + pd.Timedelta(days=7 * 10 + 30), 10)
    later = _season("POL", "2019", ["A", "B", "E", "G"], START + pd.Timedelta(days=400), 6)  # iki kulüp birlikte
    m = _frame(first + second + later)
    rejected: list = []
    assert detect_intra_season_splits(m, rejected) == {}
    assert rejected and all("sezon sınırı" in r[3] for r in rejected)
    tm = build_team_matches(m)  # eskiden: "Aynı takımın aynı gün birden fazla maçı var"
    assert {"E", "F", "G", "H"} <= set(tm["team"])
    assert tm.attrs["rejected_splits"]


def test_candidate_that_shares_a_match_day_elsewhere_is_rejected():
    """Tek lig-sezonda ad değişikliğine benzeyen iki ad, aynı ülkenin başka liginde aynı gün maç oynamış: aynı kulüp
    olamaz; birleştirilmez ve tablo kurulur."""
    rename_like = _season("E0", "2018/19", ["A", "B", "C", "SLOT"], START, 20, ("SLOT", "X", "Y", 10))
    elsewhere = [{"league": "E1", "season": "2019/20", "date": START + pd.Timedelta(days=400), "home": "X", "away": "P"},
                 {"league": "E1", "season": "2019/20", "date": START + pd.Timedelta(days=400), "home": "Q", "away": "Y"}]
    m = _frame(rename_like + elsewhere)
    rejected: list = []
    assert detect_intra_season_splits(m, rejected) == {}
    assert rejected[0][:3] == ("İngiltere", "Y", "X") and "aynı gün" in rejected[0][3]
    tm = build_team_matches(m)
    assert not tm.duplicated(["team", "date"]).any() and {"X", "Y"} <= set(tm["team"])
    am = AliasMap.from_matches(m)
    assert am.splits == {} and am.rejected_splits


def test_same_name_in_two_countries_is_kept_apart():
    rows = [{"league": "E0", "season": "2018/19", "date": START, "home": "Nacional", "away": "A"},
            {"league": "P1", "season": "2018/19", "date": START, "home": "B", "away": "Nacional"},
            {"league": "E0", "season": "2018/19", "date": START + pd.Timedelta(days=7), "home": "A", "away": "Nacional"}]
    tm = build_team_matches(_frame(rows))
    assert {"Nacional (İngiltere)", "Nacional (Portekiz)"} <= set(tm["team"])
    assert (tm["team"] == "Nacional (İngiltere)").sum() == 2 and tm.attrs["country_scoped_names"] == ["Nacional"]
    assert set(tm.loc[tm["team"] == "Nacional (Portekiz)", "team_raw"]) == {"Nacional"}


def test_real_same_day_duplicate_names_examples():
    rows = [{"league": "E0", "season": "2018/19", "date": START, "home": "A", "away": "B"},
            {"league": "E0", "season": "2018/19", "date": START, "home": "A", "away": "C"}]
    with pytest.raises(ValueError, match="Örnekler: A \\(E0 2018-08-04\\)"):
        build_team_matches(_frame(rows))

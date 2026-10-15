"""KUPA-GOL-06: kupa gol düzeyi izleme aracı (``tools/research/kupa_gol_duzey.py``). Elle kurulmuş satırlar; ağ yok."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("kupa_gol_duzey", ROOT / "tools" / "research" / "kupa_gol_duzey.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _frame(weeks=12, per_week=4, groups=("UEFA", "YURTICI")):
    """Haftalık maçlar; her maçta tahmin λ' + ν' = 2,8 ve gerçekleşen 3 gol (testler skorları değiştirir)."""
    rows = []
    for g in groups:
        for w in range(weeks):
            wk = 8000 + 7 * w
            for j in range(per_week):
                rows.append({"vgroup": g, "season": "2023/24" if w < weeks // 2 else "2024/25", "week": wk,
                             "date": pd.Timestamp("2000-01-01") + pd.Timedelta(days=wk + 1 + j % 3),
                             "lam_c": 1.6, "nu_c": 1.2, "hg": 2, "ag": 1})
    return pd.DataFrame(rows)


def test_level_is_one_without_history_and_with_perfect_forecasts(tool):
    df = _frame()
    r = tool.level_series(df)
    first = df.groupby("vgroup")["week"].transform("min") == df["week"]
    assert np.all(r[first.to_numpy()] == 1.0)  # geçmiş yoksa önbilgi: 1
    exact = df.assign(hg=1, ag=0, lam_c=0.6, nu_c=0.4)  # gerçekleşen = tahmin (1 gol)
    np.testing.assert_allclose(tool.level_series(exact), 1.0, rtol=1e-12)


def test_level_moves_toward_the_ratio_and_matches_the_formula(tool):
    df = _frame()
    df["hg"], df["ag"] = 3, 1  # gerçekleşen 4, tahmin 2,8 → oran 4 / 2,8
    r = tool.level_series(df)
    g = df["vgroup"] == "YURTICI"
    rv = pd.Series(r[g.to_numpy()]).groupby(df.loc[g, "week"].to_numpy()).first().to_numpy()
    assert np.all(np.diff(rv) > 0) and rv[-1] < 4 / 2.8  # veri biriktikçe orana yaklaşır, önbilgi yüzünden aşmaz
    # Elle hesap: son haftanın R'si
    wk = df["week"].max()
    past = df[g & (df["week"] < wk)]
    day = (pd.to_datetime(past["date"]) - pd.Timestamp("2000-01-01")).dt.days.to_numpy()
    w = 0.5 ** ((wk - day) / tool.HALF_LIFE)
    expect = (np.sum(w * 4.0) + tool.TAU) / (np.sum(w * 2.8) + tool.TAU)
    assert abs(rv[-1] - expect) < 1e-12


def test_level_uses_only_earlier_weeks_and_its_own_group(tool):
    df = _frame()
    base = tool.level_series(df)
    wk = sorted(df["week"].unique())[5]
    alt = df.copy()
    sel = (alt["week"] == wk) & (alt["vgroup"] == "YURTICI")
    alt.loc[sel, "hg"] = 9  # o haftanın sonuçları değişir
    r = tool.level_series(alt)
    yur = (df["vgroup"] == "YURTICI").to_numpy()
    same = ((df["week"] <= wk).to_numpy() & yur) | ~yur  # o hafta ve öncesi + öbür grup değişmez
    np.testing.assert_allclose(r[same], base[same], rtol=1e-12)
    later = (df["week"] > wk).to_numpy() & yur
    assert np.all(r[later] > base[later])


def test_season_table(tool):
    df = _frame()
    df["hg"], df["ag"] = 3, 1
    t = tool.season_table(df)
    assert set(t["grup"]) == {"UEFA", "YURTICI"} and set(t["sezon"]) == {"2023/24", "2024/25"}
    assert (t["maç"] == 24).all()
    np.testing.assert_allclose(t["fark"], 4 - 2.8)
    assert (t["z"] > 0).all() and np.allclose(t["gol"], 4.0) and np.allclose(t["tahmin"], 2.8)

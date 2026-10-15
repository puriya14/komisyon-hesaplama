"""KUPA-ROV-06: iki ayaklı eşleşmelerde rövanş sınama aracı (``tools/research/kupa_rovans.py``). Elle kurulmuş satırlar;
ağ yok."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
D = pd.Timestamp


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("kupa_rovans", ROOT / "tools" / "research" / "kupa_rovans.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cups(rows):
    return (pd.DataFrame([dict(zip(("comp", "season", "stage", "date", "home_key", "away_key", "fthg", "ftag"), r))
                          for r in rows]).sort_values("date", kind="mergesort").reset_index(drop=True))


def test_tie_detection_rules(tool):
    c = _cups([
        ("UCL", "2023/24", "Round of 16", D("2024-02-13"), "A", "B", 2, 0),
        ("UCL", "2023/24", "Round of 16", D("2024-03-05"), "B", "A", 1, 1),  # rövanş: B ilk maçta 0-2 kaybetti
        ("UCL", "2023/24", "Group A", D("2023-10-01"), "C", "D", 1, 0),
        ("UCL", "2023/24", "Group A", D("2023-10-20"), "D", "C", 1, 0),  # grup: hariç
        ("FAC", "2023/24", "Round 3", D("2024-01-06"), "E", "F", 1, 1),
        ("FAC", "2023/24", "Round 3", D("2024-01-16"), "F", "E", 2, 1),  # FA Cup tekrar maçı: hariç
        ("UEL", "2023/24", "Playoffs", D("2024-02-15"), "G", "H", 0, 3),
        ("UEL", "2023/24", "Playoffs", D("2024-02-16"), "H", "G", 1, 0),  # 1 gün: aralık dışı
        ("UEL", "2022/23", "Playoffs", D("2023-02-16"), "I", "J", 1, 0),
        ("UEL", "2023/24", "Playoffs", D("2023-08-20"), "J", "I", 1, 0),  # farklı sezon: hariç
    ])
    t = tool.ties(c)
    assert len(t) == 1
    r = t.iloc[0]
    assert c.loc[r["i2"], "home_key"] == "B" and c.loc[r["i1"], "home_key"] == "A" and r["d"] == -2


def test_tie_uses_nearest_previous_and_each_match_once(tool):
    c = _cups([
        ("UCLQ", "2023/24", "Round 1", D("2023-07-01"), "A", "B", 1, 0),
        ("UCLQ", "2023/24", "Round 1", D("2023-07-08"), "A", "B", 3, 1),
        ("UCLQ", "2023/24", "Round 1", D("2023-07-15"), "B", "A", 0, 0),
        ("UCLQ", "2023/24", "Round 2", D("2023-07-22"), "A", "B", 2, 2),  # B-A ikinci maç olamaz: önceki ilk maç
    ])
    t = tool.ties(c)
    assert len(t) == 1
    assert c.loc[t.iloc[0]["i1"], "date"] == D("2023-07-08") and t.iloc[0]["d"] == 1 - 3  # en yakın önceki maç
    assert tool.ties(c.iloc[:0]).empty


def test_design_and_rates(tool):
    d = pd.DataFrame({"d": [-5.0, -1.0, 0.0, 2.0, 3.0], "lam_c": 1.0, "nu_c": 1.0})
    xh, xa = tool.design(d, "V1")
    assert xh[:, 0].tolist() == [3, 1, 0, -2, -3] and xa[:, 0].tolist() == [-3, -1, 0, 2, 3]  # kırpma ±3
    xh, xa = tool.design(d, "V2")
    assert xh[:, 0].tolist() == [1, 0, 0, 0, 1] and (xa == xh).all()
    xh, xa = tool.design(d, "V3")
    assert xh.shape == (5, 2)
    lam, nu = tool.rates(d, "V1", [0.1])
    assert lam[1] == pytest.approx(np.exp(0.1)) and nu[1] == pytest.approx(np.exp(-0.1))  # geride olan ev sahibi artar
    with pytest.raises(KeyError):
        tool.design(d, "V9")


def _sim(tool, beta=0.0, gamma=0.0, n=5000, seed=5):
    rng = np.random.default_rng(seed)
    d = pd.DataFrame({"d": rng.integers(-4, 5, n).astype(float), "lam_c": rng.uniform(0.7, 2.4, n),
                      "nu_c": rng.uniform(0.5, 2.0, n), "week_b": np.arange(n) // 8})
    xh, xa = tool.design(d, "V3")
    t = np.array([beta, gamma])
    d["hg"] = rng.poisson(d["lam_c"] * np.exp(xh @ t))
    d["ag"] = rng.poisson(d["nu_c"] * np.exp(xa @ t))
    return d


def test_fit_selection_and_acceptance(tool):
    d = _sim(tool, beta=0.15)
    assert tool.fit(d, "V1")[0] == pytest.approx(0.15, abs=0.03)
    best, res = tool.select(d)
    assert best in ("V1", "V3") and res["V1"]["daic"] == pytest.approx(2 - 2 * res["V1"]["dll"])
    assert res["V3"]["daic"] == pytest.approx(4 - 2 * res["V3"]["dll"])
    r = tool.compare(d, "V1", res["V1"]["theta"])
    assert r["skor"]["ust"] < 0 and tool.accept(r)
    flat = _sim(tool, seed=11)
    best0, res0 = tool.select(flat)
    assert best0 == "V0" and all(x["daic"] >= 0 for x in res0.values())
    g = _sim(tool, gamma=-0.3, seed=2)
    assert tool.fit(g, "V2")[0] == pytest.approx(-0.3, abs=0.08)


def test_second_legs_join_oos_rows(tool):
    c = _cups([
        ("UCL", "2023/24", "Round of 16", D("2024-02-13"), "A", "B", 2, 0),
        ("UCL", "2023/24", "Round of 16", D("2024-03-05"), "B", "A", 1, 1),
        ("UCL", "2023/24", "Round of 16", D("2024-02-14"), "C", "D", 1, 1),
    ])
    oos = pd.DataFrame({"i": [0, 1, 2], "date": c["date"], "lam_c": 1.2, "nu_c": 1.0, "hg": c["fthg"],
                        "ag": c["ftag"]})
    d = tool.second_legs(oos, c)
    assert len(d) == 1 and d.iloc[0]["i"] == c.index[c["home_key"] == "B"][0] and d.iloc[0]["fold"] == 2023
    tab = tool.residual_table(d.assign(d=-2.0))
    assert tab.index.tolist() == [-2] and tab["n"].iloc[0] == 1

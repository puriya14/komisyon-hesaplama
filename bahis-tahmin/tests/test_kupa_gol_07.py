"""KUPA-GOL-07: kupa motorunda dinamik gol düzeyi (kullanıcı kararıyla uygulandı; KUPA-GOL-06'da kuralı geçmedi).

R = (Σ w·gerçekleşen + τ) / (Σ w·tahmin + τ); aynı doğrulama grubundan, o haftadan önceki haftaların örneklem dışı
maçları; w = 0,5^(gün / 180), τ = 150. Yalnızca SENTETİK veri (``kupa_yardim``) ve elle kurulmuş satırlar; ağ yok."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from kupa_yardim import CUP_DAY, world

HK, AK = "İngiltere|Arsenal", "Türkiye|Galatasaray"
EPOCH = pd.Timestamp("2000-01-01")


@pytest.fixture(scope="module")
def w():
    return world()


@pytest.fixture(scope="module")
def engines(w):
    from bahis_tahmin.kupa.motor import CupEngine

    on, off = CupEngine(), CupEngine(dynamic_level=False)
    on.train(*w)
    off.train(*w)
    return on, off


def _brute_level(ev: pd.DataFrame, i: int, half=180.0, tau=150.0) -> float:
    """Bağımsız yeniden hesap: tek satırın R'si, satır satır döngüyle."""
    row = ev.iloc[i]
    num = den = 0.0
    for _, r in ev.iterrows():
        if r["vgroup"] != row["vgroup"] or not r["week"] < row["week"]:
            continue
        wgt = 0.5 ** ((row["week"] - (pd.Timestamp(r["date"]) - EPOCH).days) / half)
        num += wgt * (r["hg"] + r["ag"])
        den += wgt * (r["lam_c0"] + r["nu_c0"])
    return (num + tau) / (den + tau)


def test_training_rows_are_scaled_by_the_past_level(engines):
    on, off = engines
    ev = on.oos
    for i in (0, 1, len(ev) // 3, len(ev) // 2, len(ev) - 1):
        assert abs(ev["duzey"].iloc[i] - _brute_level(ev, i)) < 1e-12
    first = ev["week"] == ev["week"].min()
    assert np.all(ev.loc[first, "duzey"] == 1.0) and ev["duzey"].std() > 0
    np.testing.assert_allclose(ev["lam_c"], ev["lam_c0"] * ev["duzey"], rtol=1e-12)
    np.testing.assert_allclose(ev["nu_c"], ev["nu_c0"] * ev["duzey"], rtol=1e-12)
    # Düzeysiz motorla aynı ham ve düzeysiz kalibre beklentiler; düzey kapalıyken R = 1
    b = off.oos.set_index("i")
    a = ev.set_index("i")
    np.testing.assert_allclose(a["lam_c0"], b.loc[a.index, "lam_c"], rtol=1e-12)
    assert np.all(off.oos["duzey"] == 1.0) and off.level_rows == {}


def test_measurement_uses_scaled_expectations(engines, w):
    """1X2 ve gol pazarı ölçümü düzeyli beklentilerden (bağımsız yeniden hesap)."""
    from bahis_tahmin.kupa.gol import first_half_share, ht_mask, market_probs
    from bahis_tahmin.kupa.motor import probs_from_rates

    on, _ = engines
    ev = on.oos
    P, _, _ = probs_from_rates(ev["lam_c0"] * ev["duzey"], ev["nu_c0"] * ev["duzey"])
    np.testing.assert_allclose(ev[["ph", "pd", "pa"]].to_numpy(), P, rtol=1e-12)
    _, cups = w
    cups = cups.sort_values("date", kind="mergesort").reset_index(drop=True)
    g = on.goal.oos
    ok = ht_mask(cups)
    for season, rows in g.groupby("season"):
        s = first_half_share(cups[ok & (pd.to_datetime(cups["date"]) < rows["date"].min()).to_numpy()])
        pr = market_probs(rows["lam_c0"] * rows["duzey"], rows["nu_c0"] * rows["duzey"], s)
        for k in "ABC":
            np.testing.assert_allclose(rows[f"p{k}"], pr[k], rtol=1e-12)


def test_prediction_uses_the_level_at_the_match_date(engines):
    from bahis_tahmin.kupa.model import calibrate_rates
    from bahis_tahmin.kupa.motor import _week_start

    on, off = engines
    day = int((pd.Timestamp(CUP_DAY) - EPOCH).days)
    ev = on.oos[on.oos["vgroup"] == "UEFA"]
    wk = _week_start(day)
    d = (pd.to_datetime(ev["date"]) - EPOCH).dt.days.to_numpy()
    m = ev["week"].to_numpy() < wk
    wgt = 0.5 ** ((wk - d[m]) / 180.0)
    expect = (np.sum(wgt * (ev["hg"] + ev["ag"]).to_numpy()[m]) + 150) / (
        np.sum(wgt * (ev["lam_c0"] + ev["nu_c0"]).to_numpy()[m]) + 150)
    assert abs(on.level_at("UEFA", day) - expect) < 1e-12 and on.level_at("KITA", day) == 1.0
    r = on.rates(HK, AK, "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "UCL", False)
    lc, nc = calibrate_rates([r["lam_raw"]], [r["nu_raw"]], on.calib, [False])
    assert abs(r["gol_duzeyi"] - expect) < 1e-12
    assert abs(r["lam"] - lc[0] * expect) < 1e-12 and abs(r["nu"] - nc[0] * expect) < 1e-12
    p = on.predict("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "21:00")
    assert p.info["gol_duzeyi"] == r["gol_duzeyi"] and abs(p.info["lam"] - r["lam"]) < 1e-12
    gp = on.predict_goals("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY),
                          "21:00", False, "espn")
    assert gp.info["gol_duzeyi"] == r["gol_duzeyi"]
    ro = off.rates(HK, AK, "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "UCL", False)
    assert ro["gol_duzeyi"] == 1.0
    # Düzey modele ve olasılıklara gerçekten girer: düzeysiz motordan farklı (aynı ham beklenti)
    assert abs(ro["lam_raw"] - r["lam_raw"]) < 1e-12 and abs(expect - 1.0) > 1e-4
    assert on.digest != off.digest


def test_level_never_uses_the_week_it_scores(w, engines):
    """Bir haftadan itibaren kupa sonuçları değişse de o haftanın ve öncekilerin düzeyi ve beklentileri aynı."""
    from bahis_tahmin.kupa.motor import CupEngine

    on, _ = engines
    dom, cups = w
    cut = pd.Timestamp("2025-02-03")  # pazartesi
    alt = cups.copy()
    late = alt["date"] >= cut
    alt.loc[late, ["fthg", "ftag"]] = alt.loc[late, ["ftag", "fthg"]].to_numpy() + 2
    e2 = CupEngine()
    e2.train(dom, alt)
    upto = on.oos["date"] < cut + pd.Timedelta(days=7)
    a = on.oos[upto].set_index("i")
    b = e2.oos[e2.oos["date"] < cut + pd.Timedelta(days=7)].set_index("i")
    assert len(a) > 50 and a.index.equals(b.index) and (a["date"] >= cut).any()
    for col in ("duzey", "lam_c", "nu_c"):
        np.testing.assert_allclose(a[col], b[col], rtol=1e-12)
    later = on.oos["date"] >= cut + pd.Timedelta(days=7)
    assert not np.allclose(on.oos.loc[later, "duzey"].to_numpy(), e2.oos.loc[later.to_numpy(), "duzey"].to_numpy())


def test_groups_are_separate():
    from bahis_tahmin.kupa.motor import level_series

    rows = []
    for g in ("UEFA", "YURTICI"):
        for k in range(10):
            wk = 9000 + 7 * k
            for j in range(3):
                rows.append({"vgroup": g, "week": wk, "date": EPOCH + pd.Timedelta(days=wk + j), "hg": 2, "ag": 1,
                             "lam_c0": 1.5, "nu_c0": 1.1})
    df = pd.DataFrame(rows)
    base = level_series(df)
    alt = df.copy()
    alt.loc[alt["vgroup"] == "YURTICI", "hg"] = 6
    r = level_series(alt)
    u = (df["vgroup"] == "UEFA").to_numpy()
    np.testing.assert_allclose(r[u], base[u], rtol=1e-12)
    assert np.all(r[~u][3:] > base[~u][3:]) and np.all(r[~u][:3] == 1.0)


def test_roundtrip_versions_and_visibility(engines, tmp_path):
    from bahis_tahmin.kupa.gorunum import goal_model_card, level_line
    from bahis_tahmin.kupa.motor import CUP_ENGINE_VERSION, MODEL_VERSION, CupEngine

    on, off = engines
    assert CUP_ENGINE_VERSION == 6 and MODEL_VERSION == "kupa-model-v3"
    path = tmp_path / "kupa.joblib"
    on.save(path)
    e2 = CupEngine.load(path)
    day = int((pd.Timestamp(CUP_DAY) - EPOCH).days)
    assert e2.dynamic_level and e2.level_at("UEFA", day) == on.level_at("UEFA", day)
    args = ("UCL", HK, AK, "Arsenal", "Galatasaray", "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "21:00", False,
            "espn")
    assert e2.predict_goals(*args).probs == on.predict_goals(*args).probs
    line = level_line(on)
    assert "UEFA" in line and "kullanıcı kararıyla" in line and level_line(off) == "" and level_line(None) == ""
    card = goal_model_card(on.predict_goals(*args), on)
    assert "gol düzeyi ×" in card["version"] and "dinamik gol düzeyi" in card["inputs"]


def test_prediction_level_equals_training_level_in_the_same_week(engines):
    """Tahmin anındaki düzey, aynı haftadaki eğitim satırlarının düzeyiyle aynı (o haftanın sonuçları sayılmaz)."""
    on, _ = engines
    ev = on.oos
    for i in (5, len(ev) // 4, len(ev) // 2, len(ev) - 1):
        r = ev.iloc[i]
        day = int((pd.Timestamp(r["date"]) - EPOCH).days)
        assert abs(on.level_at(r["vgroup"], day) - r["duzey"]) < 1e-12


def test_rates_use_the_level_of_the_competitions_group(engines):
    """Yurt içi kupa maçı yurt içi grubunun, UEFA maçı UEFA grubunun düzeyini kullanır."""
    import copy

    on, _ = engines
    e = copy.copy(on)
    week, d, tot, mu = on.level_rows["UEFA"]
    e.level_rows = {"UEFA": on.level_rows["UEFA"], "YURTICI": (week, d, tot * 1.5, mu)}
    day = int((pd.Timestamp(CUP_DAY) - EPOCH).days)
    assert e.level_at("YURTICI", day) > e.level_at("UEFA", day) + 0.05
    uefa = e.rates(HK, AK, "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "UCL", False)
    cup = e.rates(HK, AK, "İngiltere", "Türkiye", pd.Timestamp(CUP_DAY), "FAC", False)
    assert uefa["gol_duzeyi"] == e.level_at("UEFA", day) and cup["gol_duzeyi"] == e.level_at("YURTICI", day)


def test_level_line_needs_measurements(engines):
    import copy

    from bahis_tahmin.kupa.gorunum import level_line

    on, _ = engines
    e = copy.copy(on)
    e.level_rows = {}
    assert level_line(e) == "" and level_line(on) != ""

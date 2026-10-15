"""KUPA-GOL-05: kupa gol pazarı model seçimi aracı (``tools/research/kupa_gol_secim.py``).

Araç KUPA-GOL-02'nin altı adayını (SK0 = uygulamadaki model) ileriye dönük yeniden kurar. Testler: maç sonu modeli
ve SK0 uygulamanın ölçümüyle birebir aynı; adaylar tutarlı; seçim kuralı yazıldığı gibi; sızıntı yok; 0-0 maçlarda
devre skoru yazılmasa da sonuç aynı. Yalnızca SENTETİK veri (``kupa_yardim``); ağ isteği yok."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kupa_yardim import world

ROOT = Path(__file__).resolve().parents[1]
NAN = float("nan")


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("kupa_gol_secim", ROOT / "tools" / "research" / "kupa_gol_secim.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def w():
    return world()


@pytest.fixture(scope="module")
def engine(w):
    """KUPA-GOL-05 seçiminin temeli dinamik gol düzeysiz modeldir (KUPA-GOL-07 düzeyi bunun üzerine uygular)."""
    from bahis_tahmin.kupa.motor import CupEngine

    eng = CupEngine(dynamic_level=False)
    eng.train(*w)
    return eng


@pytest.fixture(scope="module")
def run(tool, w):
    dom, cups = w
    oos = tool.walk_forward(dom, cups, progress=None)
    return oos, tool.evaluate(oos, cups)


def test_full_time_model_is_the_engines_walk_forward(run, engine):
    oos, _ = run
    a = oos.set_index("i")
    b = engine.oos.set_index("i")
    assert set(b.index) <= set(a.index) and len(b) > 300
    np.testing.assert_allclose(a.loc[b.index, "lam"], b["lam"], rtol=1e-12)
    np.testing.assert_allclose(a.loc[b.index, "nu"], b["nu"], rtol=1e-12)
    assert oos[["r1h", "r1a", "r2h", "r2a"]].notna().all().all()  # yarı modelleri de her hafta kurulur


def test_half_models_are_fit_on_half_scores(run, w):
    """İlk yarı / ikinci yarı modelleri, skorları yarı skorlarıyla değiştirilmiş veriden bağımsız kurulan modelle aynı
    (ısınma başlangıcı farkı dışında)."""
    from bahis_tahmin.kupa.gol import ht_scores
    from bahis_tahmin.kupa.model import EPOCH, ModelConfig, build_data, fit
    from bahis_tahmin.kupa.motor import CupEngine, group_of, key_of

    dom, cups = w
    oos, _ = run
    cups = cups.sort_values("date", kind="mergesort").reset_index(drop=True)

    def halves(df, second):
        h, a = ht_scores(df)
        out = df.copy()
        out["fthg"] = (df["fthg"].to_numpy() - h) if second else h
        out["ftag"] = (df["ftag"].to_numpy() - a) if second else a
        return out.astype({"fthg": int, "ftag": int})

    eng = CupEngine()
    for second, cols in ((False, ("r1h", "r1a")), (True, ("r2h", "r2a"))):
        data, tl = build_data(halves(dom, second), halves(cups, second), key_of, group_of)
        eng.timeline = tl
        for idx in (0, len(oos) // 2, len(oos) - 1):
            r = oos.iloc[idx]
            c = cups.iloc[int(r["i"])]
            day = int((pd.Timestamp(c["date"]) - EPOCH).days)
            par = fit(data, int(r["week"]), ModelConfig(), None)
            got = par.rates(c["home_key"], c["away_key"], eng.league_for(c["home_key"], c["home_country"], day),
                            eng.league_for(c["away_key"], c["away_country"], day), group_of(c["comp"]),
                            bool(c["neutral"]))
            np.testing.assert_allclose([r[cols[0]], r[cols[1]]], got, rtol=1e-4)
    share = (oos["r1h"] + oos["r1a"]).sum() / (oos["lam"] + oos["nu"]).sum()
    assert 0.40 < share < 0.50  # sentetik dünyada ilk yarı payı %45


def test_sk0_is_the_application_measurement(run, engine, tool):
    _, ev = run
    chk = tool.engine_check(ev, engine)
    assert chk["ortak"] == chk["motor"] == chk["prototip"] == int(ev["measured"].sum())
    assert max(chk["en_buyuk_fark"].values()) < 1e-12


def test_candidates_are_coherent_and_distinct(run, tool):
    _, ev = run
    m = ev["measured"]
    res = ev["res"]
    assert set(res) == set(tool.ORDER)
    for v, r in res.items():
        a, b, c = r["A"][m], r["B"][m], r["C"][m]
        assert np.all((a > 0) & (a < 1) & (b > 0) & (b < 1) & (c > 0) & (c < 1)), v
        assert np.all(a <= b + 1e-12) and np.all(a <= c + 1e-12), v  # A ⊆ B ∩ C (aynı ortak dağılım)
        if v != "SK0":
            assert np.max(np.abs(r["B"][m] - res["SK0"]["B"][m])) > 1e-4 or \
                np.max(np.abs(r["C"][m] - res["SK0"]["C"][m])) > 1e-4, v
    for k in "ABC":
        np.testing.assert_allclose(res["MIX"][k], 0.5 * res["SK1"][k] + 0.5 * res["K1"][k])
    # SK1 durum çarpanları yalnızca ikinci yarıya etki eder: İY 1,5 Üst SK0 ile aynı
    np.testing.assert_allclose(res["SK1"]["C"][m], res["SK0"]["C"][m], rtol=1e-12)


def test_candidates_are_calibrated_in_the_large(run, tool):
    """Sentetik dünyada (ikinci yarı skor durumundan bağımsız) her adayın ortalama tahmini gerçekleşen orana yakın ve
    durum çarpanları SK1'i SK0'dan ancak az ayırır: çarpanlar ikinci yarı golleriyle (maç sonu − ilk yarı) öğrenilir."""
    _, ev = run
    m = ev["measured"]
    o = ev["o"]
    for v in tool.ORDER:
        for k in "ABC":
            assert abs(ev["res"][v][k][m].mean() - o.loc[m, f"y{k}"].mean()) < 0.06, (v, k)
    assert abs(ev["res"]["SK1"]["B"][m] - ev["res"]["SK0"]["B"][m]).mean() < 0.02


def _dev(totals: dict[str, dict[str, float]]) -> pd.DataFrame:
    return pd.DataFrame([{"grup": g, "aday": v, "toplam": t} for g, d in totals.items() for v, t in d.items()])


def _tot(sk0=1.5, sk1=1.5, s2=1.5, k1=1.5, mix=1.5, h2=1.5):
    return {"SK0": sk0, "SK1": sk1, "S2": s2, "K1": k1, "MIX": mix, "H2": h2}


def test_selection_rule(tool):
    sel = tool.select
    # Eşdeğerler içinde sadelikte ilk: SK0
    r = sel(_dev({"TÜMÜ": _tot(mix=1.4995), "UEFA": _tot(), "YURTICI": _tot()}))
    assert r["secilen"] == "SK0" and r["en_iyi"] == "MIX" and r["esdeger"] == ["SK0", "SK1", "S2", "K1", "MIX", "H2"]
    # Sınır dahil (≤ 0,001): SK0 hâlâ eşdeğer
    assert sel(_dev({"TÜMÜ": _tot(mix=1.499), "UEFA": _tot(), "YURTICI": _tot()}))["secilen"] == "SK0"
    # SK0 dışarıda; eşdeğerlerin en sadesi grup korumasını geçerse seçilir
    r = sel(_dev({"TÜMÜ": _tot(sk1=1.4975, mix=1.497, s2=1.51, k1=1.51, h2=1.51), "UEFA": _tot(sk1=1.4995),
                  "YURTICI": _tot(sk1=1.5005)}))
    assert r["secilen"] == "SK1" and r["esdeger"] == ["SK1", "MIX"]
    # Grup koruması: SK1 bir grupta SK0'dan 0,001'den fazla kötü → sıradaki eşdeğer (MIX)
    r = sel(_dev({"TÜMÜ": _tot(sk1=1.4975, mix=1.497, s2=1.51, k1=1.51, h2=1.51), "UEFA": _tot(sk1=1.49),
                  "YURTICI": _tot(sk1=1.5015)}))
    assert r["secilen"] == "MIX" and "SK1: grup koruması geçmedi" in r["notlar"][0]
    # Hiçbir eşdeğer korumayı geçmezse SK0
    r = sel(_dev({"TÜMÜ": _tot(k1=1.49), "UEFA": _tot(k1=1.47), "YURTICI": _tot(k1=1.502)}))
    assert r["esdeger"] == ["K1"] and r["secilen"] == "SK0"


def test_no_leakage_into_earlier_seasons(tool, w, run):
    """Son sezonun maç sonu ve devre skorları değişse de önceki sezonların bütün aday olasılıkları ve tabanları aynı."""
    dom, cups = w
    _, ev1 = run
    alt = cups.copy()
    last = alt["season"] == "2025/26"
    alt.loc[last, ["fthg", "ftag"]] = alt.loc[last, ["ftag", "fthg"]].to_numpy() + 2
    alt.loc[last, ["hthg", "htag"]] = alt.loc[last, ["htag", "hthg"]].to_numpy() + 1
    ev2 = tool.evaluate(tool.walk_forward(dom, alt, progress=None), alt)
    o1, o2 = ev1["o"], ev2["o"]
    early1 = (o1["season"] < "2025/26").to_numpy() & ev1["measured"]
    early2 = (o2["season"] < "2025/26").to_numpy() & ev2["measured"]
    assert early1.sum() > 100 and np.array_equal(o1.loc[early1, "i"].to_numpy(), o2.loc[early2, "i"].to_numpy())
    for v in tool.ORDER:
        for k in "ABC":
            np.testing.assert_allclose(ev1["res"][v][k][early1], ev2["res"][v][k][early2], rtol=1e-12, err_msg=v + k)
    for k in "ABC":
        np.testing.assert_allclose(ev1["base"][k][early1], ev2["base"][k][early2], rtol=1e-12)
    late = (o1["season"] == "2025/26").to_numpy() & ev1["measured"]
    assert late.any()


def test_calibrations_come_only_from_before_the_season(tool, w, run):
    """Ham beklentiler aynıyken bir sezonun sonuçları değişirse o sezonun ve öncekilerin aday olasılıkları ve tabanları
    değişmez: kalibrasyon, durum çarpanı, Platt, ilk yarı payı ve taban sezon başından önceki maçlardan."""
    _, cups = w
    oos1, ev1 = run
    season = "2024/25"
    oos2, cups2 = oos1.copy(), cups.copy()
    for df in (oos2, cups2):
        cur = df["season"] == season
        df.loc[cur, ["fthg", "ftag"]] = df.loc[cur, ["ftag", "fthg"]].to_numpy() + 1
        df.loc[cur, ["hthg", "htag"]] = df.loc[cur, ["htag", "hthg"]].to_numpy()
    ev2 = tool.evaluate(oos2, cups2)
    o = ev1["o"]
    upto = (o["season"] <= season).to_numpy() & ev1["measured"]
    later = (o["season"] > season).to_numpy() & ev1["measured"]
    assert (o.loc[upto, "season"] == season).sum() > 50 and later.any()
    for v in tool.ORDER:
        for k in "ABC":
            np.testing.assert_allclose(ev1["res"][v][k][upto], ev2["res"][v][k][upto], rtol=1e-12, err_msg=v + k)
    for k in "ABC":
        np.testing.assert_allclose(ev1["base"][k][upto], ev2["base"][k][upto], rtol=1e-12)
    assert not np.allclose(ev1["res"]["S2"]["B"][later], ev2["res"]["S2"]["B"][later])  # sonraki sezon öğrenir


def test_blank_goalless_half_time_gives_the_same_result(tool, w, run):
    """openfootball gibi 0-0 maçlarda devre skoru yazılmasa da yarı modelleri ve bütün adaylar aynı (ht_scores)."""
    dom, cups = w
    oos1, ev1 = run
    blank = cups.copy()
    nil = (blank["fthg"] == 0) & (blank["ftag"] == 0)
    assert nil.sum() > 50
    blank.loc[nil, ["hthg", "htag"]] = NAN
    oos2 = tool.walk_forward(dom, blank, progress=None)
    for c in ("lam", "nu", "r1h", "r1a", "r2h", "r2a"):
        np.testing.assert_allclose(oos1[c], oos2[c], rtol=1e-12, err_msg=c)
    ev2 = tool.evaluate(oos2, blank)
    assert np.array_equal(ev1["measured"], ev2["measured"])
    for v in tool.ORDER:
        for k in "ABC":
            np.testing.assert_allclose(ev1["res"][v][k], ev2["res"][v][k], rtol=1e-12, err_msg=v + k)


def test_table_totals(run, tool):
    _, ev = run
    t = tool.table(ev, tool.DEV + tool.TEST, "tümü")
    assert set(t["aday"]) == set(tool.ORDER) | {"taban"}
    np.testing.assert_allclose(t["toplam"], t["llA"] + t["llB"] + t["llC"])
    g = t.set_index(["grup", "aday"])
    assert g.loc[("TÜMÜ", "SK0"), "n"] == int(ev["measured"].sum())
    sel = tool.select(t)
    assert sel["secilen"] in tool.ORDER and sel["en_iyi"] in sel["esdeger"]

"""Üç ana pazar (iki yarıda KG, 3,5 Üst, İY 1,5 Üst) için altın regresyon testi.

Beklenen değerler (tests/fixtures/golden_primary.json), İY/MS ve dizi modülü eklenmeden ÖNCEKİ kodla
(commit b78a992) sentetik veride üretildi. Mevcut kodun aynı tahminleri, aralıkları ve etiketleri vermesi gerekir;
ana pazarlarda herhangi bir davranış değişikliği bu testi kırar.
"""

import json
import warnings

import numpy as np
import pytest

from tests.conftest import FIXTURES

from bahis_tahmin.goals.decision import NUMERIC_TOLERANCE

# Aynı makinede eski (b78a992) ve yeni kod birebir aynı sonuç verdi (en büyük fark 0). Farklı işlemci/BLAS ve numpy SIMD
# yolunda L-BFGS uyumunun sonlanma noktası oynar: S2-KABUL-01 denetiminde CI farkı (A 1,54e-6; aralık 4,07e-6) bit
# düzeyinde yeniden üretildi; testin karşılaştırdığı tüm anahtarlarda en büyük fark 9,5e-6 (29 yapılandırmada 1,38e-5).
# Tolerans mutlak ve karar motorunun sayısal eşik-yakını işaretiyle aynı kaynaktan gelir. Etiketler birebir
# karşılaştırılır. Bu tolerans içindeki farkın karar etkisi test_decisions_unchanged_outside_numeric_band ile sınanır.
TOL = NUMERIC_TOLERANCE


@pytest.fixture(scope="module")
def current():
    from bahis_tahmin.goals.features import build_goal_features
    from bahis_tahmin.goals.markets import MARKETS, PRIMARY_YES, label_frame
    from bahis_tahmin.goals.model import GoalModel
    from bahis_tahmin.selftest import synthetic_matches

    warnings.filterwarnings("ignore")
    m = synthetic_matches(n_seasons=8, n_teams=16, seed=1, half_time=True)
    feat, _ = build_goal_features(m)
    tr, te = feat[feat["date"] < "2026-08-01"], feat[feat["date"] >= "2026-08-01"]
    mod = GoalModel("M10_ipf_kosullu").fit(tr)
    sample = te.iloc[:60]
    return {
        "predict": mod.predict(sample),
        "interval": mod.interval(sample.iloc[:20], draws=50),
        "labels": label_frame(m.iloc[:300], PRIMARY_YES),
        "markets": sorted(MARKETS),
    }


def _arr(v):
    return np.array([np.nan if x is None else x for x in np.ravel(v)], dtype=float)


def test_primary_predictions_unchanged(current):
    gold = json.loads((FIXTURES / "golden_primary.json").read_text(encoding="utf-8"))
    diffs = {}
    for k, v in gold["predict"].items():
        got, want = _arr(current["predict"][k]), _arr(v)
        assert np.array_equal(np.isnan(got), np.isnan(want)), k
        diffs[k] = float(np.nanmax(np.abs(got - want)))
    assert max(diffs.values()) <= TOL, diffs  # tüm anahtarların farkı tek iletide
    # 'tail' çok küçük büyüklükte: mutlak TOL anlamsız olduğundan ayrıca göreli ölçüt
    got, want = _arr(current["predict"]["tail"]), _arr(gold["predict"]["tail"])
    assert np.all(np.abs(got - want) <= 1e-11 + 1e-2 * np.abs(want)), "tail"


def test_primary_intervals_and_labels_unchanged(current):
    gold = json.loads((FIXTURES / "golden_primary.json").read_text(encoding="utf-8"))
    for k, v in gold["interval"].items():
        lo, hi = current["interval"][k]
        got, want = np.column_stack([lo, hi]).ravel(), _arr(v)
        assert np.array_equal(np.isnan(got), np.isnan(want)), k
        assert np.nanmax(np.abs(got - want)) <= TOL, k
    for k, v in gold["labels"].items():
        got, want = current["labels"][k].to_numpy(dtype=float), _arr(v)
        assert np.array_equal(np.isnan(got), np.isnan(want)) and np.nanmax(np.abs(got - want)) == 0, k
    assert current["markets"] == gold["markets"]  # iki seçenekli pazar kaydı değişmedi


def test_primary_structural_order_exact(current):
    """A ⊂ B∩C: A ≤ BC ≤ min(B, C) toleranssız (M10 yolunda kayan noktada kesin)."""
    pr = current["predict"]
    a, bc, b, c = (_arr(pr[k]) for k in ("A", "BC", "B", "C"))
    assert np.all(a <= bc) and np.all(bc <= np.minimum(b, c))


@pytest.mark.parametrize("shift", [None, +NUMERIC_TOLERANCE, -NUMERIC_TOLERANCE])
def test_decisions_unchanged_outside_numeric_band(current, shift):
    """Toleranstaki olasılık farkı kararı yalnızca SAYISAL_ESIK_YAKINI işaretli durumlarda değiştirebilir.

    Altın ve güncel olasılıklar/aralıklar, aynı sentetik oran ızgarasıyla (0,01 adım) karar motoruna verilir; işaretsiz
    her durumda karar (durum ve EV işareti) birebir aynı olmalı. Eşikler ve politika değiştirilmez."""
    import datetime as dt

    from bahis_tahmin.goals.decision import NEAR_THRESHOLD, Assessment, decide
    from bahis_tahmin.goals.markets import MARKETS
    from bahis_tahmin.goals.value import OddsQuote

    gold = json.loads((FIXTURES / "golden_primary.json").read_text(encoding="utf-8"))
    t = dt.datetime(2026, 9, 1, 12, tzinfo=dt.timezone.utc)
    keys = {"A": "BTTS_BOTH_HALVES_YES", "B": "FT_OVER_3_5", "C": "FH_OVER_1_5"}
    grid = np.round(np.arange(1.01, 12.0, 0.01), 2)
    changed = flagged = 0
    for short, mk in keys.items():
        m = MARKETS[mk]
        lo_c, hi_c = current["interval"][mk]
        iv_g = _arr(gold["interval"][mk]).reshape(-1, 2)
        for i in range(len(iv_g)):
            src = {"altin": (_arr(gold["predict"][short])[i], iv_g[i, 0], iv_g[i, 1]),
                   "guncel": (_arr(current["predict"][short])[i], float(lo_c[i]), float(hi_c[i]))}
            if shift is not None:  # duyarlılık: toleransın tamamı kadar (en kötü durum) kaydırılmış olasılıklar
                pg, lg, hg = src["altin"]
                src["guncel"] = (pg + shift, lg + shift, hg + shift)
            for d in grid:
                q = OddsQuote("E", mk, m.period, m.line, m.selection, "test", "test", float(d),
                              t - dt.timedelta(minutes=5), t - dt.timedelta(minutes=5))
                out = {}
                for name, (p, lo, hi) in src.items():
                    a = Assessment("E", "T1", "Ev", "Dep", mk, float(p), float(lo), float(hi), model_validated=True,
                                   quote=q, kickoff=t + dt.timedelta(days=1))
                    out[name] = decide(a, t)
                g, c = out["altin"], out["guncel"]
                near = any(r.startswith(NEAR_THRESHOLD) for r in g.reasons + c.reasons)
                same = g.status == c.status and np.sign(g.ev) == np.sign(c.ev)
                flagged += near
                if not same:
                    changed += 1
                    assert near, (mk, i, d, g.status, c.status, g.ev, c.ev)
    assert flagged >= changed
    if shift is not None:
        assert changed > 0  # kaydırma gerçekten bazı kararları değiştiriyor; hepsi işaretli

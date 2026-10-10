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

TOL = 1e-7


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
    for k, v in gold["predict"].items():
        got, want = _arr(current["predict"][k]), _arr(v)
        assert np.array_equal(np.isnan(got), np.isnan(want)), k
        assert np.nanmax(np.abs(got - want)) <= TOL, k


def test_primary_intervals_and_labels_unchanged(current):
    gold = json.loads((FIXTURES / "golden_primary.json").read_text(encoding="utf-8"))
    for k, v in gold["interval"].items():
        lo, hi = current["interval"][k]
        got = np.column_stack([lo, hi]).ravel()
        assert np.nanmax(np.abs(got - _arr(v))) <= TOL, k
    for k, v in gold["labels"].items():
        got, want = current["labels"][k].to_numpy(dtype=float), _arr(v)
        assert np.array_equal(np.isnan(got), np.isnan(want)) and np.nanmax(np.abs(got - want)) == 0, k
    assert current["markets"] == gold["markets"]  # iki seçenekli pazar kaydı değişmedi

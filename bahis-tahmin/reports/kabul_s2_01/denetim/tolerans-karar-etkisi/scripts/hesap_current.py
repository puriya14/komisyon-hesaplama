"""tests/test_primary_regression.py::current fikstürünün (01b7e9f) birebir kopyası; yalnızca sentetik veri.

Kullanım: python hesap_current.py <kod_kökü(bahis-tahmin)> <çıktı.json> <etiket>
Kodu DEĞİŞTİRMEZ; sadece içe aktarır ve sonuçları tam duyarlıkla JSON'a yazar, altın değerlerle karşılaştırır.
"""
import json, os, sys, time, warnings
import numpy as np

root, out_path, tag = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
t0 = time.time()
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
cur = {
    "predict": mod.predict(sample),
    "interval": mod.interval(sample.iloc[:20], draws=50),
    "labels": label_frame(m.iloc[:300], PRIMARY_YES),
    "markets": sorted(MARKETS),
}
elapsed = time.time() - t0

def _arr(v):
    return np.array([np.nan if x is None else x for x in np.ravel(v)], dtype=float)

gold_path = sys.argv[4] if len(sys.argv) > 4 else os.path.join(root, "tests/fixtures/golden_primary.json")
gold = json.loads(open(gold_path, encoding="utf-8").read())
res = {"tag": tag, "elapsed_s": round(elapsed, 2),
       "env": {k: os.environ.get(k) for k in ("OPENBLAS_CORETYPE", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
                                              "NPY_DISABLE_CPU_FEATURES", "MKL_NUM_THREADS")},
       "qcal": list(mod.qcal) if mod.qcal else None,
       "base_coef": [float(x) for x in mod.base.coef], "base_phi": mod.base.phi,
       "predict_maxabs": {}, "predict_nanmask_equal": {}, "interval_maxabs": {}, "interval_nan_mismatch": {},
       "labels_identical": {}, "markets_identical": cur["markets"] == gold["markets"], "values": {}}
for k, v in gold["predict"].items():
    got, want = _arr(cur["predict"][k]), _arr(v)
    res["predict_nanmask_equal"][k] = bool(np.array_equal(np.isnan(got), np.isnan(want)))
    d = np.abs(got - want)
    res["predict_maxabs"][k] = float(np.nanmax(d)) if np.isfinite(d).any() else None
    res["values"][f"predict.{k}"] = [None if not np.isfinite(x) else float(x) for x in got]
for k, v in gold["interval"].items():
    lo, hi = cur["interval"][k]
    got = np.column_stack([lo, hi]).ravel()
    want = _arr(v)
    res["interval_nan_mismatch"][k] = int((np.isnan(got) != np.isnan(want)).sum())
    res["interval_maxabs"][k] = float(np.nanmax(np.abs(got - want)))
    res["values"][f"interval.{k}"] = [None if not np.isfinite(x) else float(x) for x in got]
for k, v in gold["labels"].items():
    got, want = cur["labels"][k].to_numpy(dtype=float), _arr(v)
    res["labels_identical"][k] = bool(np.array_equal(np.isnan(got), np.isnan(want)) and np.nanmax(np.abs(got - want)) == 0)
# Testin kendi iddiaları (ilk başarısız anahtar dahil), TOL=1e-7 ve 5e-5 için
for tol in (1e-7, 5e-5):
    first_fail_pred = next((k for k, d in res["predict_maxabs"].items() if not (d is not None and d <= tol) or not res["predict_nanmask_equal"][k]), None)
    first_fail_int = next((k for k, d in res["interval_maxabs"].items() if not d <= tol), None)
    res[f"test_pass_tol_{tol:g}"] = {"predict_first_fail": first_fail_pred, "interval_first_fail": first_fail_int}
try:
    from threadpoolctl import threadpool_info
    res["threadpool_info"] = [{k: i.get(k) for k in ("internal_api", "version", "num_threads", "architecture", "filepath")} for i in threadpool_info()]
except Exception as e:  # noqa
    res["threadpool_info"] = str(e)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
print(tag, "elapsed", res["elapsed_s"], "pred_max", max(v for v in res["predict_maxabs"].values() if v is not None),
      "int_max", max(res["interval_maxabs"].values()), "labels", all(res["labels_identical"].values()))

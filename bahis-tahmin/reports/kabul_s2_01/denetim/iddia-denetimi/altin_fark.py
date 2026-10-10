"""Altın regresyon testi: mevcut koddaki (01b7e9f) sentetik tahminlerin altın değerlerden en büyük farkı (bu konteyner)."""
import json, sys, warnings
from pathlib import Path
import numpy as np
root = Path(sys.argv[1]); sys.path.insert(0, str(root))
warnings.filterwarnings("ignore")
from bahis_tahmin.goals.features import build_goal_features
from bahis_tahmin.goals.markets import MARKETS, PRIMARY_YES, label_frame
from bahis_tahmin.goals.model import GoalModel
from bahis_tahmin.selftest import synthetic_matches
m = synthetic_matches(n_seasons=8, n_teams=16, seed=1, half_time=True)
feat, _ = build_goal_features(m)
tr, te = feat[feat["date"] < "2026-08-01"], feat[feat["date"] >= "2026-08-01"]
mod = GoalModel("M10_ipf_kosullu").fit(tr)
sample = te.iloc[:60]
pred = mod.predict(sample); itv = mod.interval(sample.iloc[:20], draws=50); lab = label_frame(m.iloc[:300], PRIMARY_YES)
gold = json.loads((root / "tests/fixtures/golden_primary.json").read_text(encoding="utf-8"))
arr = lambda v: np.array([np.nan if x is None else x for x in np.ravel(v)], dtype=float)
out = {"predict": {}, "interval": {}, "labels": {}}
for k, v in gold["predict"].items():
    out["predict"][k] = float(np.nanmax(np.abs(arr(pred[k]) - arr(v))))
for k, v in gold["interval"].items():
    lo, hi = itv[k]; out["interval"][k] = float(np.nanmax(np.abs(np.column_stack([lo, hi]).ravel() - arr(v))))
for k, v in gold["labels"].items():
    out["labels"][k] = float(np.nanmax(np.abs(lab[k].to_numpy(dtype=float) - arr(v))))
out["predict_anahtarlari"] = sorted(gold["predict"].keys()); out["interval_anahtarlari"] = sorted(gold["interval"].keys())
print(json.dumps(out, indent=1))

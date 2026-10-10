"""Mekanizma denemesi (kod DEĞİŞTİRİLMEZ; yalnızca bu süreçte model modülündeki `minimize` adı sarmalanır):
L-BFGS-B'ye çok sıkı durma ölçütleri verilirse, iki farklı hesap yolu (varsayılan vs CI benzeri) arasındaki fark
küçülüyor mu? Küçülüyorsa farkın kaynağı, ULP düzeyindeki ara-sonuç farklarının optimizasyonun DURMA NOKTASINDA
büyümesidir (model değişikliği değil). Kullanım: python ... <kod_kökü> <çıktı.json> <etiket> <mod: varsayilan|siki>
"""
import json, os, sys, warnings
import numpy as np
root, out_path, tag, mode = sys.argv[1:5]
sys.path.insert(0, root)
import bahis_tahmin.goals.model as M
from scipy.optimize import minimize as _min
calls = []
def wrapped(fun, x0, *a, **k):
    if mode == "siki" and k.get("method") == "L-BFGS-B":
        opts = dict(k.get("options") or {}); opts.update(ftol=1e-15, gtol=1e-11, maxiter=20000, maxfun=40000)
        k["options"] = opts
    r = _min(fun, x0, *a, **k)
    calls.append({"nit": int(getattr(r, "nit", -1)), "nfev": int(getattr(r, "nfev", -1)), "msg": str(r.message)[:60], "x0": float(r.x[0])})
    return r
M.minimize = wrapped
from bahis_tahmin.goals.features import build_goal_features
from bahis_tahmin.selftest import synthetic_matches
warnings.filterwarnings("ignore")
m = synthetic_matches(n_seasons=8, n_teams=16, seed=1, half_time=True)
feat, _ = build_goal_features(m)
tr, te = feat[feat["date"] < "2026-08-01"], feat[feat["date"] >= "2026-08-01"]
mod = M.GoalModel("M10_ipf_kosullu").fit(tr)
sample = te.iloc[:60]
p = mod.predict(sample)
iv = mod.interval(sample.iloc[:20], draws=50)
out = {"tag": tag, "mode": mode, "calls": calls, "base_coef": [float(x) for x in mod.base.coef], "qcal": list(mod.qcal),
       "predict": {k: [float(x) for x in np.ravel(v)] for k, v in p.items()},
       "interval": {k: [float(x) for x in np.column_stack(iv[k]).ravel()] for k in ("BTTS_BOTH_HALVES_YES", "FT_OVER_3_5", "FH_OVER_1_5")}}
json.dump(out, open(out_path, "w"), indent=1)
print(tag, mode, [(c["nit"], c["msg"][:30]) for c in calls])

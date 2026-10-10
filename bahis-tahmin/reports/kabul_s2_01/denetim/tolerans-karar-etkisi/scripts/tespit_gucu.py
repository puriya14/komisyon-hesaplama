"""TOL=5e-5'in tespit gücü: küçük ama GERÇEK model/kod değişikliklerinin altın değerlerden sapması (sentetik veri).
Kod dosyaları DEĞİŞTİRİLMEZ; değişiklikler yalnızca bu süreçte parametre/sarmalama ile uygulanır.
Kullanım: python tespit_gucu.py <kod_kökü> <altın.json> <çıktı.csv>"""
import json, sys, warnings
import numpy as np, pandas as pd
root, gpath, out = sys.argv[1:4]
sys.path.insert(0, root)
warnings.filterwarnings("ignore")
import bahis_tahmin.goals.model as M
import bahis_tahmin.goals.joint as J
from bahis_tahmin.goals.features import build_goal_features
from bahis_tahmin.selftest import synthetic_matches
gold = json.load(open(gpath))
m = synthetic_matches(n_seasons=8, n_teams=16, seed=1, half_time=True)
feat, _ = build_goal_features(m)
tr0, te = feat[feat["date"] < "2026-08-01"], feat[feat["date"] >= "2026-08-01"]
sample = te.iloc[:60]
arr = lambda v: np.array([np.nan if x is None else x for x in np.ravel(np.array(v, dtype=object))], dtype=float)
orig_LR, orig_tilt, orig_min = M.ChallengerLR, M.tilt_to_targets, M.minimize

def run(name, shrink=30.0, tr=tr0, lr_C=None, tilt_tol=None, ftol=None, seed=20261010):
    M.ChallengerLR = (lambda f=None: orig_LR(f, C=lr_C)) if lr_C else orig_LR
    M.tilt_to_targets = (lambda reg, b, c: orig_tilt(reg, b, c, tol=tilt_tol)) if tilt_tol else orig_tilt
    def mn(*a, **k):
        if ftol and k.get("method") == "L-BFGS-B":
            k["options"] = {**(k.get("options") or {}), "ftol": ftol}
        return orig_min(*a, **k)
    M.minimize = mn
    mod = M.GoalModel("M10_ipf_kosullu", shrink=shrink).fit(tr)
    p = mod.predict(sample)
    iv = mod.interval(sample.iloc[:20], draws=50, seed=seed)
    r = {"degisiklik": name}
    for s in ("A", "B", "C"):
        r[f"predict_{s}_max"] = float(np.nanmax(np.abs(arr(p[s]) - arr(gold["predict"][s]))))
    r["predict_tum_anahtarlar_max"] = max(float(np.nanmax(np.abs(arr(p[k]) - arr(gold["predict"][k])))) for k in gold["predict"])
    for k in gold["interval"]:
        r[f"interval_{k}_max"] = float(np.nanmax(np.abs(np.column_stack(iv[k]).ravel() - arr(gold["interval"][k]))))
    r["TOL_5e-5_yakalar"] = max(v for kk, v in r.items() if kk.endswith("_max")) > 5e-5
    print(r, flush=True)
    return r

rows = [run("referans (değişiklik yok)"),
        run("durum çarpanı küçültmesi shrink 30→31", shrink=31.0),
        run("eğitimden son 1 maç çıkarıldı", tr=tr0.iloc[:-1]),
        run("kalibratör LR C 0.1→0.11", lr_C=0.11),
        run("IPF eğim toleransı 1e-12→1e-9", tilt_tol=1e-9),
        run("L-BFGS-B ftol varsayılan→1e-12 (sayısal)", ftol=1e-12),
        run("aralık tohumu 20261010→20261011", seed=20261011)]
pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6g")

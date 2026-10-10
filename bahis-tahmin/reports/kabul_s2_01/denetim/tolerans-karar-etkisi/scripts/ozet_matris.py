"""run_*.json dosyalarından anahtar başına en büyük mutlak farkı CSV'ye döker; CI örnek değerleriyle eşleşmeyi denetler."""
import glob, json, os, sys
import numpy as np
O = sys.argv[1]
rows = []
for p in sorted(glob.glob(os.path.join(O, "cikti", "run_*.json"))):
    d = json.load(open(p))
    r = {"config": d["tag"], "elapsed_s": d["elapsed_s"],
         "openblas_arch": ";".join(sorted({i["architecture"] or "" for i in d["threadpool_info"] if i["internal_api"] == "openblas"})),
         "labels_identical_all": all(d["labels_identical"].values()), "markets_identical": d["markets_identical"],
         "predict_nanmask_equal_all": all(d["predict_nanmask_equal"].values()),
         "interval_nan_mismatch_total": sum(d["interval_nan_mismatch"].values())}
    for k, v in d["predict_maxabs"].items():
        r[f"predict.{k}"] = v
    for k, v in d["interval_maxabs"].items():
        r[f"interval.{k}"] = v
    pm = [v for v in d["predict_maxabs"].values() if v is not None]
    r["predict_max_all"] = max(pm); r["interval_max_all"] = max(d["interval_maxabs"].values())
    r["pass_tol_1e-7"] = d["test_pass_tol_1e-07"]["predict_first_fail"] is None and d["test_pass_tol_1e-07"]["interval_first_fail"] is None
    r["first_fail_1e-7"] = f'{d["test_pass_tol_1e-07"]["predict_first_fail"]}|{d["test_pass_tol_1e-07"]["interval_first_fail"]}'
    r["pass_tol_5e-5"] = d["test_pass_tol_5e-05"]["predict_first_fail"] is None and d["test_pass_tol_5e-05"]["interval_first_fail"] is None
    rows.append(r)
import pandas as pd
df = pd.DataFrame(rows)
df.to_csv(os.path.join(O, "cikti", "matris_ozet.csv"), index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 50)
print(df[["config", "openblas_arch", "predict.A", "interval.BTTS_BOTH_HALVES_YES", "predict_max_all", "interval_max_all", "labels_identical_all", "markets_identical", "first_fail_1e-7", "pass_tol_5e-5"]].to_string())
# CI örnekleri: A ilk 3 + 8. değer (got) ve BTTS aralığı
ci_A = {0: 0.04025403, 1: 0.14520174, 2: 0.22256236}
for p in sorted(glob.glob(os.path.join(O, "cikti", "run_*.json"))):
    d = json.load(open(p))
    a = d["values"]["predict.A"]; bt = d["values"]["interval.BTTS_BOTH_HALVES_YES"]
    ok = all(round(a[i], 8) == v for i, v in ci_A.items()) and (0.20594797 in [round(x, 8) for x in a])
    okb = (0.03180467 in [round(x, 8) for x in bt if x is not None]) and (0.28056686 in [round(x, 8) for x in bt if x is not None])
    if d["predict_maxabs"]["A"] == 1.5351364150983926e-06 or ok or okb:
        print("CI_ESLESME", d["tag"], "A_max", repr(d["predict_maxabs"]["A"]), "BTTS_int_max", repr(d["interval_maxabs"]["BTTS_BOTH_HALVES_YES"]), "A_ornek_ok", ok, "BTTS_ornek_ok", okb)

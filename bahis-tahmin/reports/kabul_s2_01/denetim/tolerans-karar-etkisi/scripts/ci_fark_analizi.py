"""Madde 2: CI farklarının anahtar bazında mutlak/göreli büyüklüğü (altın değerlere göre).

Girdi: altın (01b7e9f tests/fixtures/golden_primary.json kopyası), CI'yi bit düzeyinde yeniden üreten koşu
(run_ct-Haswell_th-4_npy-nov4.json) ve tüm matris koşuları. Çıktı: ci_fark_anahtar_bazinda.csv, ci_ornek_degerler.csv
"""
import glob, json, os, sys
import numpy as np, pandas as pd
O = sys.argv[1]
gold = json.load(open(f"{O}/cikti/golden_primary_01b7e9f.json"))
ci = json.load(open(f"{O}/cikti/run_ct-Haswell_th-4_npy-nov4.json"))
runs = [json.load(open(p)) for p in sorted(glob.glob(f"{O}/cikti/run_*.json"))]
arr = lambda v: np.array([np.nan if x is None else x for x in np.ravel(np.array(v, dtype=object))], dtype=float)
rows = []
for grp, keys in (("predict", gold["predict"].keys()), ("interval", gold["interval"].keys())):
    for k in keys:
        want = arr(gold[grp][k]); got = arr(ci["values"][f"{grp}.{k}"])
        d = np.abs(got - want); rel = d / np.abs(want)
        fin = np.isfinite(want)
        r = {"grup": grp, "anahtar": k, "n": int(fin.sum()), "altin_min": np.nanmin(want), "altin_medyan": np.nanmedian(want),
             "altin_max": np.nanmax(want), "ci_max_mutlak": np.nanmax(d), "ci_argmax_altin_degeri": want[np.nanargmax(d)],
             "ci_argmax_goreli": rel[np.nanargmax(d)], "ci_max_goreli": np.nanmax(rel),
             "ci_max_goreli_altin>=0.01": np.nanmax(np.where(want >= 0.01, rel, np.nan)) if (want >= 0.01).any() else np.nan,
             "ci_max_goreli_altin>=0.05": np.nanmax(np.where(want >= 0.05, rel, np.nan)) if (want >= 0.05).any() else np.nan,
             "ci_medyan_mutlak": np.nanmedian(d),
             "matris29_max_mutlak": max((max(np.nanmax(np.abs(arr(rr["values"][f"{grp}.{k}"]) - want)), 0.0)) for rr in runs),
             }
        rows.append(r)
df = pd.DataFrame(rows)
df.to_csv(f"{O}/cikti/ci_fark_anahtar_bazinda.csv", index=False, float_format="%.6g")
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
print(df.to_string(float_format=lambda x: f"{x:.3g}"))
# CI günlüğündeki örnek değerler: hem yuvarlanmış CI metninden hem yeniden üretilen tam duyarlıklı değerden göreli fark
samples = [("predict.A", 0.04025403, 0.04025424), ("predict.A", 0.14520174, 0.14520134), ("predict.A", 0.22256236, 0.22256271),
           ("predict.A", 0.20594797, 0.20594951), ("interval.BTTS_BOTH_HALVES_YES", 0.03180467, 0.03180501),
           ("interval.BTTS_BOTH_HALVES_YES", 0.28056686, 0.28056832)]
srows = []
for key, g, w in samples:
    grp, k = key.split(".", 1)
    want = arr(gold[grp][k]); got = arr(ci["values"][key])
    idx = int(np.nanargmin(np.abs(want - w)))
    srows.append({"anahtar": key, "indeks": idx, "ci_got_metin": g, "ci_want_metin": w, "metin_mutlak": abs(g - w), "metin_goreli": abs(g - w) / w,
                  "altin_tam": want[idx], "yeniden_uretilen_tam": got[idx], "yeniden_uretilen_8hane_eslesir": round(got[idx], 8) == g,
                  "tam_mutlak": abs(got[idx] - want[idx]), "tam_goreli": abs(got[idx] - want[idx]) / want[idx]})
sdf = pd.DataFrame(srows); sdf.to_csv(f"{O}/cikti/ci_ornek_degerler.csv", index=False, float_format="%.10g")
print(sdf.to_string(float_format=lambda x: f"{x:.6g}"))

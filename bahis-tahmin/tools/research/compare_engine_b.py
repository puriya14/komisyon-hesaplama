"""Final testte 3,5 Üst (B) için gol modeli ile mevcut uygulama maç motorunun karşılaştırması.

Kullanım: python -I compare_engine_b.py <goal_test_pred.pkl> <engine_oos_b.pkl> <cikti.json>
Yalnızca iki tahminin de bulunduğu (lig, tarih, ev, deplasman) eşleşen maçlar kullanılır.
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np, pandas as pd
from bahis_tahmin.goals.validation import block_bootstrap_diff, calibration_bins, calibration_slope

g = pd.read_pickle(sys.argv[1])
e = pd.read_pickle(sys.argv[2])
key = ["league", "date", "home", "away"]
g = g[g["FT_OVER_3_5"].notna() & g["usable"]]
m = g.merge(e[key + ["pmk_O3.5"]], on=key, how="inner")
m = m[np.isfinite(m["pmk_O3.5"]) & np.isfinite(m["M10_ipf_kosullu:B"]) & np.isfinite(m["M0_taban:B"])]
y = m["FT_OVER_3_5"].to_numpy(float)
wk = pd.to_datetime(m["date"]).dt.strftime("%G-%V").to_numpy()

def ll(p):
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))

out = {"n": int(len(m)), "pozitif": int(y.sum()), "taban_oran": float(y.mean()), "modeller": {}}
cols = {"M0_taban": "M0_taban:B", "M10_ipf_kosullu": "M10_ipf_kosullu:B", "C1_lojistik": "C1_lojistik:B",
        "mevcut_mac_motoru": "pmk_O3.5"}
base = ll(m["M0_taban:B"].to_numpy(float))
eng = ll(m["pmk_O3.5"].to_numpy(float))
for name, c in cols.items():
    if c not in m:
        continue
    p = m[c].to_numpy(float)
    l = ll(p)
    d, lo, hi = block_bootstrap_diff(l, base, wk)
    de, loe, hie = block_bootstrap_diff(l, eng, wk)
    slope, icpt = calibration_slope(y, p)
    bins = calibration_bins(y, p)
    ece = float(np.sum([b["n"] * abs(b["tahmin"] - b["gercek"]) for b in bins]) / len(y))
    out["modeller"][name] = {"log_loss": float(l.mean()), "fark_taban": [d, lo, hi], "fark_mevcut_motor": [de, loe, hie],
                             "kal_egim": slope, "ece": ece, "ort": float(p.mean())}
Path(sys.argv[3]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=1))

"""A ≤ BC ≤ min(B, C) ve aralık uçlarında A ≤ B, A ≤ C: altın değerlerde ve 29+2 koşunun hepsinde KESİN (toleranssız) denetim."""
import glob, json, sys
import numpy as np
O = sys.argv[1]
arr = lambda v: np.array([np.nan if x is None else x for x in np.ravel(np.array(v, dtype=object))], dtype=float)
srcs = {"altin": {f"predict.{k}": arr(v) for k, v in json.load(open(f"{O}/cikti/golden_primary_01b7e9f.json"))["predict"].items()}}
g = json.load(open(f"{O}/cikti/golden_primary_01b7e9f.json"))
srcs["altin"].update({f"interval.{k}": arr(v) for k, v in g["interval"].items()})
for p in sorted(glob.glob(f"{O}/cikti/run_*.json")) + sorted(glob.glob(f"{O}/cikti/b78a992_*.json")):
    d = json.load(open(p)); srcs[d["tag"]] = {k: arr(v) for k, v in d["values"].items()}
viol = {}
for name, v in srcs.items():
    A, B, C, BC = v["predict.A"], v["predict.B"], v["predict.C"], v["predict.BC"]
    iA, iB, iC = v["interval.BTTS_BOTH_HALVES_YES"], v["interval.FT_OVER_3_5"], v["interval.FH_OVER_1_5"]
    checks = {"A<=BC": int((A > BC).sum()), "BC<=B": int((BC > B).sum()), "BC<=C": int((BC > C).sum()),
              "A<=B": int((A > B).sum()), "A<=C": int((A > C).sum()),
              "iv_lo/hi_A<=B": int((iA > iB).sum()), "iv_lo/hi_A<=C": int((iA > iC).sum()),
              "min_gap_B-A": float(np.nanmin(B - A)), "min_gap_C-A": float(np.nanmin(C - A)), "min_gap_BC-A": float(np.nanmin(BC - A)),
              "min_gap_iv_B-A": float(np.nanmin(iB - iA)), "min_gap_iv_C-A": float(np.nanmin(iC - iA))}
    viol[name] = checks
tot = {k: sum(c[k] for c in viol.values()) for k in viol["altin"] if not k.startswith("min_gap")}
mins = {k: min(c[k] for c in viol.values()) for k in viol["altin"] if k.startswith("min_gap")}
print("kaynak sayısı:", len(viol)); print("ihlal toplamları:", tot); print("en küçük paylar:", mins)
json.dump({"kaynaklar": viol, "ihlal_toplam": tot, "en_kucuk_pay": mins}, open(f"{O}/cikti/yapi_esitsizlik.json", "w"), indent=1)

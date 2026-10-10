"""Gol pazarları doğrulaması: stage=dev (model seçimi) veya stage=test (kapalı final test).

Kullanım: python -I goal_validate.py <dev|test> <feat.pkl> <matches.pkl> <rapor_klasoru> ['{"not": "...", "varyantlar": [...], "etiket": "_x", "rakipler": true}']
"""
import sys, json, time, warnings
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
warnings.filterwarnings("ignore")
from bahis_tahmin.goals import validation as V
from bahis_tahmin.goals.model import VARIANTS

stage, feat_path, matches_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
extra = json.loads(sys.argv[5]) if len(sys.argv) > 5 else {}
variants = tuple(extra.pop("varyantlar", VARIANTS))
tag = extra.pop("etiket", "")
use_ch = extra.pop("rakipler", True)
feat = pd.read_pickle(feat_path)
matches = pd.read_pickle(matches_path)
years = V.DEV_YEARS if stage == "dev" else tuple(range(V.TEST_FIRST, 2027))
t = time.time()
pred, params = V.walk_forward(feat, years, variants, V.default_challengers() if use_ch else {}, progress=lambda y: print("fold", y, round(time.time()-t), flush=True))
models = list(variants[1:]) + (["C1_lojistik", "C1_lojistik+H2H"] if use_ch else [])
res = V.evaluate(pred, ["M0_taban"] + models)
cons = V.consistency(pred, list(variants[1:]) + (["C1_lojistik"] if use_ch else []))
out = {"stage": stage, "years": [int(y) for y in years], "data": V.data_manifest(matches), "results": res,
       "consistency": cons, "params_last": [p for p in params if p["fold"] == max(pp["fold"] for pp in params)],
       "seconds": round(time.time() - t), **extra}
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / f"goal_{stage}{tag}_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
pred.to_pickle(Path(sys.argv[2]).with_name(f"goal_{stage}{tag}_pred.pkl"))
V.log_experiment(out_dir / "experiments.jsonl", {
    "asama": stage, "test_yillari": [int(y) for y in years], "veri_sha256": out["data"]["sha256"],
    "egitim_kurali": f"her sezon Y için: {V.BURN_IN_LAST + 1} ≤ sezon < Y", "karar_zamani": "maç günü 00:00 (yalnızca tarih)",
    "ozet": {k: {m: round(v["log_loss"], 5) for m, v in r["modeller"].items()} for k, r in res.items()}, **extra})
for key, r in res.items():
    print(f"\n== {key}: n={r['n']} pozitif={r['pozitif']} taban={r['taban_oran']:.4f}")
    for m, v in r["modeller"].items():
        print(f"  {m:18s} LL={v['log_loss']:.5f} Δ={v['ll_fark_ref']:+.5f} [{v['ll_fark_alt']:+.5f},{v['ll_fark_ust']:+.5f}] BSS={v['brier_skill']:+.4f} AP={v['ap']:.4f} eğim={v['kal_egim']:.3f} ECE={v['ece']:.4f} ort={v['ort_tahmin']:.4f}")
print("\ntutarlilik", cons)
print("params(last fold)", [ (p["variant"], round(p["k1"],3), round(p["k2"],3), round(p["phi"],4)) for p in out["params_last"]])

"""UST_TUR kuralının (timeline.py:180-181, çift satırdan biri season_ord > reg → maç üst tur) karışık sınıflama
yaptığı maçlar: üst tur sayılan ama iki takımdan biri için hâlâ normal sezon sırası ≤ reg olan maçlar."""
import json
import numpy as np, pandas as pd
from ortak import OUT, build_tm
m, tm = build_tm()
u = tm[tm["ust_tur"]]
g = u.groupby("pair_id").agg(league=("league", "first"), season=("season", "first"), mn=("season_ord", "min"), reg=("regular_len", "first"))
mixed = g[g["mn"] <= g["reg"]]
out = {"ust_tur_mac": int(len(g)), "karisik_siniflanan_mac": int(len(mixed)),
       "lig_sezon": mixed.groupby(["league", "season"]).size().rename("n").reset_index().to_dict("records")}
json.dump(out, open(f"{OUT}/s2b_ust_tur.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False))

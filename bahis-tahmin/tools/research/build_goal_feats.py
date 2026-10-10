"""Gol pazarları özelliklerini üretir. Kullanım: python -I build_goal_feats.py <matches.pkl> <cikti_feat.pkl>"""
import sys, time, pandas as pd
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from bahis_tahmin.goals.features import build_goal_features
m = pd.read_pickle(sys.argv[1])
t = time.time()
feat, states = build_goal_features(m, progress=lambda f, lg: print(f"{f:.2f} {lg} {time.time()-t:.0f}s", flush=True))
print("done", feat.shape, round(time.time() - t), "s", flush=True)
feat.to_pickle(sys.argv[2])

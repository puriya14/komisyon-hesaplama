"""Araştırma S0 soy kaydını üretir (kanonik takım adlarıyla özellikler + sezon başına walk-forward M10 + 9 İY/MS hücresi).

Kullanım: python -I build_s0.py <matches.pkl> <cikti_s0.pkl> [<cikti_feat.pkl>]
"""
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
warnings.filterwarnings("ignore")
import pandas as pd

from bahis_tahmin.goals.features import build_goal_features
from bahis_tahmin.sequences.aliases import AliasMap
from bahis_tahmin.sequences.s0 import build_s0, canonical_matches

t = time.time()
m = pd.read_pickle(sys.argv[1])
am = AliasMap.from_matches(m)
cm = canonical_matches(m, am)
feat, _ = build_goal_features(cm.drop(columns=["home_raw", "away_raw"]), progress=lambda f, lg: print(f"feat {f:.2f} {lg} {time.time() - t:.0f}s", flush=True) if lg else None)
if len(sys.argv) > 3:
    feat.to_pickle(sys.argv[3])
s0 = build_s0(m, feat=feat, alias_map=am, progress=lambda s: print(s, f"{time.time() - t:.0f}s", flush=True))
s0.to_pickle(sys.argv[2])
print("done", len(s0), "alias_sha", am.sha256(), round(time.time() - t), "s", flush=True)

"""Ortak yardımcılar: baseline (01b7e9f) kodunu içe aktar, CSV'yi oku.

load(): manifest SHA-256'sını (6ca929a2…) birebir veren okuma: time sütunu str ve NaN → "" (parser `_clean_time`
boş saati "" olarak yazar). Yalnızca parse_dates ile okumak SHA'yı değiştirir (aff287d6…), içerik aynıdır.
"""
import os, sys, time as _time
OUT = "/tmp/claude-0/-home-user-komisyon-hesaplama/bd37f391-ef82-5701-bf64-cae5433e5dc0/scratchpad/kabul_s2_01/denetim/veri-kapsami-sureklilik"
KOD = os.path.join(OUT, "kod", "bahis-tahmin")
CSV = "/tmp/claude-0/-home-user-komisyon-hesaplama/bd37f391-ef82-5701-bf64-cae5433e5dc0/scratchpad/kabul_s2_01/girdi/maclar_yeniden_kurulan.csv.gz"
if KOD not in sys.path:
    sys.path.insert(0, KOD)
import pandas as pd

def load():
    m = pd.read_csv(CSV, parse_dates=["date"], dtype={"time": str}, low_memory=False)
    m["time"] = m["time"].fillna("")
    return m

def build_tm(m=None):
    from bahis_tahmin.sequences.timeline import build_team_matches
    m = load() if m is None else m
    t = _time.time()
    tm = build_team_matches(m)
    print(f"build_team_matches: {time_s(t)} sn, {len(tm)} satır", file=sys.stderr)
    return m, tm

def time_s(t):
    return round(_time.time() - t, 1)

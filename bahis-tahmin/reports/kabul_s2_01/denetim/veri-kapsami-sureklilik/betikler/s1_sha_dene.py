"""CSV'den baseline data_sha256'yı yeniden üretme denemeleri (dtype varyantları)."""
import numpy as np, pandas as pd
from ortak import CSV
from bahis_tahmin.sequences.research import data_sha256
TARGET = "6ca929a2c62fb0aa304bb672339d290347db416e1c8bbfea758f6a46b53b4bc2"
base = pd.read_csv(CSV, parse_dates=["date"], dtype={"time": str}, keep_default_na=True, low_memory=False)
def variants():
    m = base.copy(); yield "varsayilan(time str)", m
    m = base.copy(); m["time"] = m["time"].fillna(""); yield "time fillna ''", m
    for unit in ("ns", "us"):
        m = base.copy(); m["time"] = m["time"].fillna("")
        for c in ("league", "season", "time", "home", "away", "source"):
            m[c] = m[c].astype(object)
        m["date"] = m["date"].astype(f"datetime64[{unit}]")
        yield f"object str + date {unit}", m
for name, m in variants():
    s = data_sha256(m); print(name, s[:16], s == TARGET)

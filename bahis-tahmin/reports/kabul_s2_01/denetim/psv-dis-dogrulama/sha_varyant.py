"""Icerik SHA'sinin hangi okuma bicimiyle manifestle eslestigini dener (yalnizca hash; sonuc analizi yok)."""
import sys
import pandas as pd
sys.path.insert(0, sys.argv[2])
from bahis_tahmin.sequences.research import data_sha256
p = sys.argv[1]
HEDEF = "6ca929a2c62fb0aa304bb672339d290347db416e1c8bbfea758f6a46b53b4bc2"
vs = {
 "varsayilan(parse_dates=['date'])": dict(parse_dates=["date"]),
 "low_memory=False": dict(parse_dates=["date"], low_memory=False),
 "time=str": dict(parse_dates=["date"], dtype={"time": str}),
 "time=object,low_memory=False": dict(parse_dates=["date"], dtype={"time": object}, low_memory=False),
}
for k, kw in vs.items():
    d = pd.read_csv(p, **kw)
    h = data_sha256(d)
    print(k, h, h == HEDEF, d["time"].dtype, d["hthg"].dtype, d["date"].dtype)
d = pd.read_csv(p, parse_dates=["date"])
d2 = d.copy(); d2["date"] = d2["date"].astype("datetime64[ns]")
h = data_sha256(d2); print("date->datetime64[ns]", h, h == HEDEF)
print(d.dtypes.to_dict())

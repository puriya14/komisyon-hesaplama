"""data_sha256'nın CSV okuma biçimine duyarlılığı (salt-okunur)."""
import sys
import pandas as pd
sys.path.insert(0, sys.argv[1])
from bahis_tahmin.sequences.research import data_sha256
p = sys.argv[2]
a = pd.read_csv(p, parse_dates=["date"])
print("varsayilan read_csv:", data_sha256(a), a["date"].dtype, a["time"].dtype)
b = pd.read_csv(p, parse_dates=["date"], low_memory=False)
print("low_memory=False:", data_sha256(b), b["date"].dtype, b["time"].dtype)
c = a.copy(); c["date"] = c["date"].astype("datetime64[ns]")
print("varsayilan + date ns:", data_sha256(c))
d = b.copy(); d["date"] = d["date"].astype("datetime64[ns]")
print("low_memory=False + date ns:", data_sha256(d))

"""data_sha256'nın CSV okuma biçimine duyarlılığı (yalnızca özet; sonuç analizi yok)."""
import sys, json
from pathlib import Path
import pandas as pd
KOD, CSV = Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, str(KOD))
from bahis_tahmin.sequences.research import data_sha256
m = pd.read_csv(CSV, parse_dates=["date"], low_memory=False)
print("dtypes", {c: str(t) for c, t in m.dtypes.items() if str(t) not in ("float64",)})
print("time na", int(m["time"].isna().sum()) if "time" in m else None)
out = {"duz": data_sha256(m)}
m2 = m.copy(); m2["time"] = m2["time"].fillna("")
out["time_bos"] = data_sha256(m2)
m3 = pd.read_csv(CSV, parse_dates=["date"], keep_default_na=False, na_values={c: [""] for c in m.columns if c not in ("time",)}, low_memory=False)
out["time_str"] = data_sha256(m3)
for c in ("time", "season", "home", "away", "league", "source"):
    if c in m2: m2[c] = m2[c].astype(object)
out["obj"] = data_sha256(m2)
m4 = m2.copy()
for c in ("time", "season", "home", "away", "league", "source"):
    if c in m4: m4[c] = m4[c].astype("str")
out["strdtype"] = data_sha256(m4)
m4["date"] = m4["date"].astype("datetime64[us]")
out["strdtype_us"] = data_sha256(m4)
print(json.dumps(out))

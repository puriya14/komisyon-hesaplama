"""Girdi CSV'nin data_sha256 değerini farklı okuma biçimleriyle hesaplar (manifest: 6ca929a2...)."""
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent / "kod" / "bahis-tahmin"))
from bahis_tahmin.sequences.research import data_sha256
CSV = sys.argv[1]
for label, kw in (("varsayilan", {}), ("low_memory=False", {"low_memory": False}),
                  ("time=str", {"dtype": {"time": str}}), ("time=object low_memory=False", {"dtype": {"time": object}, "low_memory": False})):
    m = pd.read_csv(CSV, parse_dates=["date"], **kw)
    print(label, data_sha256(m), m["time"].map(type).value_counts().to_dict())
# pandas 3: parse_dates mikro saniye çözünürlüğü verir; özgün tablo nanosaniye olabilir
m = pd.read_csv(CSV, parse_dates=["date"], low_memory=False)
m["date"] = m["date"].astype("datetime64[ns]")
print("date→datetime64[ns]", data_sha256(m))
import itertools
base = pd.read_csv(CSV, parse_dates=["date"], low_memory=False)
strc = [c for c in base.columns if str(base[c].dtype) == "str"]
for dres, sobj, ftf in itertools.product(("us", "ns"), (False, True), (False, True)):
    m = base.copy()
    m["date"] = m["date"].astype(f"datetime64[{dres}]")
    if sobj:
        for c in strc:
            m[c] = m[c].astype(object)
    if ftf:
        m["fthg"] = m["fthg"].astype(float); m["ftag"] = m["ftag"].astype(float)
    h = data_sha256(m)
    print(f"date={dres} str→object={sobj} fthg/ftag→float={ftf}", h, "ESIT" if h.startswith("6ca929a2") else "")

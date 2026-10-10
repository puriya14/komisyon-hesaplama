"""CSV'den parser dtype'larına geri dönüşle data_sha256 (time boş metin, fthg/ftag float, date ns) denemesi."""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, sys.argv[1])
from bahis_tahmin.sequences.research import data_sha256
p = sys.argv[2]
a = pd.read_csv(p, parse_dates=["date"], low_memory=False, keep_default_na=True)
for date_unit in ("us", "ns"):
    for ft_float in (False, True):
        for time_obj in (False, True):
            c = a.copy()
            c["date"] = c["date"].astype(f"datetime64[{date_unit}]")
            if ft_float:
                c["fthg"] = c["fthg"].astype(float); c["ftag"] = c["ftag"].astype(float)
            if time_obj:
                c["time"] = c["time"].fillna("").astype(object)
                for col in ("league", "season", "home", "away", "source"):
                    c[col] = c[col].astype(object)
            print(date_unit, "ft_float" if ft_float else "ft_int", "time_obj" if time_obj else "time_str", data_sha256(c))

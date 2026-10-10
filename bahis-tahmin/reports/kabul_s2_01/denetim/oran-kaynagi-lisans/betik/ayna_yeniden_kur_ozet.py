"""Ham ayna CSV'den store.update'in ayna yolunu (22 lig, years_back=26, bugün=2026-10-10) bellekte yeniden kurar,
data_sha256'yı manifestle ve yeniden kurulan CSV'nin oran sütunlarıyla karşılaştırır. Pickle YÜKLENMEZ, dosya yazılmaz
(yalnızca stdout)."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAW, REBUILT, KOD, META = map(Path, sys.argv[1:5])
sys.path.insert(0, str(KOD))
from bahis_tahmin.data.leagues import LEAGUES, recent_season_starts  # noqa: E402
from bahis_tahmin.data.parsers import normalize_mirror  # noqa: E402
from bahis_tahmin.data.store import DataStore  # noqa: E402
from bahis_tahmin.sequences.research import data_sha256  # noqa: E402
import datetime as dt  # noqa: E402

meta = json.loads(META.read_text())
leagues = meta["leagues"]
starts = recent_season_starts(meta["years_back"], dt.date(2026, 10, 10))
raw = pd.read_csv(RAW, low_memory=False)
mdf = normalize_mirror(raw, leagues)
frames = []
for code in leagues:
    lg = LEAGUES[code]
    cutoff = pd.Timestamp(starts[0], 1 if lg.calendar_year else 7, 1)
    part = mdf[(mdf["league"] == code) & (mdf["date"] >= cutoff)]
    if not part.empty:
        frames.append(part)
mt = DataStore._clean_matches(pd.concat(frames, ignore_index=True)).reset_index(drop=True)
print("satir", len(mt), "data_sha256", data_sha256(mt))
reb = pd.read_csv(REBUILT, parse_dates=["date"], low_memory=False)
cols = ["o_h", "o_d", "o_a", "omax_h", "omax_d", "omax_a", "b365_h", "b365_d", "b365_a", "ps_h", "ps_d", "ps_a",
        "oc_h", "oc_d", "oc_a", "o_o25", "o_u25", "omax_o25", "omax_u25"]
same_keys = bool((mt[["league", "home", "away"]].astype(str).values == reb[["league", "home", "away"]].astype(str).values).all()
                 and (mt["date"].values.astype("datetime64[D]") == reb["date"].values.astype("datetime64[D]")).all())
print("anahtar_sirasi_ayni", same_keys)
for c in cols:
    a, b = mt[c].to_numpy(float), reb[c].to_numpy(float)
    ok = np.array_equal(np.isnan(a), np.isnan(b)) and np.array_equal(a[~np.isnan(a)], b[~np.isnan(b)])
    print(c, "ayni" if ok else "FARKLI")
print("dtypes_bellek", dict(mt.dtypes.astype(str)))

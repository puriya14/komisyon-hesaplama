"""Sol kesik (ilk olay öncesi) sınıflaması: lig kapsam başı vs sonradan giriş; window_rows'un geriye pencere durum
etiketi (timeline.py:266-269) için takımların ilk dilimlerinin 'DATA_START' mı 'GAP_GT_400D' mı etiketlendiği."""
import json
import numpy as np, pandas as pd
from ortak import OUT, build_tm
from bahis_tahmin.sequences.frame import target_outcomes
from bahis_tahmin.sequences import config as C
m, tm = build_tm()
s = tm[tm["in_seq"]]
lg_start = pd.to_datetime(m.groupby("league")["date"].min())
first = s.groupby("team").agg(d=("date", "min"), lg=("league", "first"))
first["lig_bas"] = first["lg"].map(lg_start)
first["lig_kapsam_basi"] = pd.to_datetime(first["d"]) <= first["lig_bas"] + pd.Timedelta(days=45)
first["global_veri_basi"] = pd.to_datetime(first["d"]) <= pd.Timestamp(tm["date"].min()) + pd.Timedelta(days=45)
out = {"takim": int(len(first)), "ilk_dilim_global_veri_basinda": int(first["global_veri_basi"].sum()),
       "ilk_dilim_lig_kapsam_basinda": int(first["lig_kapsam_basi"].sum()),
       "lig_kapsam_basinda_ama_window_rows_GAP_GT_400D_etiketli": int((first["lig_kapsam_basi"] & ~first["global_veri_basi"]).sum()),
       "sonradan_giris": int((~first["lig_kapsam_basi"]).sum()),
       "lig_baslangiclari": {k: str(v.date()) for k, v in lg_start.items()}}
y = target_outcomes(tm)
for ev in C.HAZARD_EVENTS:
    yy = np.asarray(y[ev])[s.index.to_numpy()] if False else s[ev].to_numpy(dtype=float)
    hit = s[yy == 1]
    fe = hit.groupby("team")["date"].min()
    ff = first.loc[fe.index]
    out[ev] = {"ilk_olayli_takim": int(len(fe)), "sol_kesik_lig_kapsam_basi": int(ff["lig_kapsam_basi"].sum()),
               "sol_kesik_sonradan_giris": int((~ff["lig_kapsam_basi"]).sum())}
json.dump(out, open(f"{OUT}/s5c_sol_kesik.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))

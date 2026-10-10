"""Adım 5 ek: S1 penceresi eksik lig-sezona uzanan 'uygun' (S0 koşulu hariç) satırların dönem/lig-sezon dağılımı;
F4 Kaplan–Meier medyanının (29) yeniden üretimi (tanımlayıcı)."""
import json, types
import numpy as np, pandas as pd
from ortak import OUT, build_tm
from bahis_tahmin.sequences.features import SeqIndex
from bahis_tahmin.sequences.frame import target_outcomes
from bahis_tahmin.sequences import hazard as H
from bahis_tahmin.sequences import config as C

m, tm = build_tm()
si = SeqIndex(tm)
seq = tm.iloc[si.rows]
bad = ~seq["season_complete"].to_numpy()
cb = np.r_[0, np.cumsum(bad)]
j = np.arange(si.n); pos = si.pos_in_spell
since_lc = np.nan_to_num(seq["since_league_change"].to_numpy(dtype=float), nan=-1)
elig = seq["season_complete"].to_numpy() & (since_lc >= C.LEAGUE_CHANGE_EXCLUDE)
out = {}
for k in (5, 10):
    lo = j - np.minimum(pos, k)
    touch = elig & (np.minimum(pos, k) > 0) & ((cb[j] - cb[lo]) > 0)
    per = np.array([C.period_of(int(y)) for y in seq["season_year"]], dtype=object)
    d = pd.DataFrame({"donem": per[touch], "ls": (seq["league"] + " " + seq["season"]).to_numpy()[touch]})
    out[k] = {"donem": d["donem"].fillna("donem_disi").value_counts().to_dict(),
              "en_cok_lig_sezon": d["ls"].value_counts().head(15).to_dict()}
y = target_outcomes(tm)
fr = types.SimpleNamespace(tm=tm, y=y)
km = {}
for ev in C.HAZARD_EVENTS:
    g = H.event_gaps(fr, ev)
    s = H.km_survival(g)
    med = s.loc[s["survival"] <= 0.5, "t"]
    km[ev] = int(med.iloc[0]) if len(med) else None
out["F4_KM_medyan_yeniden"] = km
json.dump(out, open(f"{OUT}/s5b_donem.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))

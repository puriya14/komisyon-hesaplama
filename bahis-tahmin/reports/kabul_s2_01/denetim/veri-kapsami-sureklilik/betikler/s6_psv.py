"""Adım 6: PSV Eindhoven Mod A sayılarının yeniden üretimi ve kapsam/boşluk kontrolü (baseline kod, tanımlayıcı)."""
import json
import numpy as np, pandas as pd
from ortak import OUT, build_tm
from bahis_tahmin.sequences.timeline import team_events, coverage_report
from bahis_tahmin.goals.markets import htft_frame

m, tm = build_tm()
T = "PSV Eindhoven"
R = {}
pm = m[(m["home"] == T) | (m["away"] == T)].copy()
pm["htft"] = htft_frame(pm).to_numpy()
R["mac_sayisi"] = int(len(pm)); R["ligler"] = pm["league"].value_counts().to_dict()
R["tarih_araligi"] = [str(pm["date"].min().date()), str(pm["date"].max().date())]
R["iy_eksik"] = int(pm[["hthg", "htag"]].isna().any(axis=1).sum())
e21 = pm[pm["htft"] == "HTFT_2_1"].sort_values("date")
R["ham_HTFT_2_1"] = int(len(e21))
R["ham_2_1_psv_ev"] = int((e21["home"] == T).sum()); R["ham_2_1_psv_dep"] = int((e21["away"] == T).sum())
R["ilk_2_1"] = e21.iloc[0][["date", "home", "away", "hthg", "htag", "fthg", "ftag"]].astype(str).to_dict()
R["son_2_1"] = e21.iloc[-1][["date", "home", "away", "hthg", "htag", "fthg", "ftag"]].astype(str).to_dict()
ev = team_events(tm, T, htft_key="HTFT_2_1")
R["ModA_ham_2_1_olay"] = int(len(ev)); R["ModA_ham_2_1_censored_tail"] = ev.attrs["censored_tail"]
R["ModA_ham_2_1_aralik_mac"] = ev["onceki_olaydan_mac"].dropna().astype(int).tolist()
for tg in ("IY_GERIDE_MS_GALIP", "IY_ONDE_MS_MAGLUP"):
    e = team_events(tm, T, target=tg)
    R[f"ModA_{tg}"] = {"olay": int(len(e)), "medyan_aralik_mac": float(e["onceki_olaydan_mac"].median()) if len(e) > 1 else None,
                       "censored_tail": e.attrs["censored_tail"]}
# PSV sezonları ve kapsam
cov = coverage_report(tm).set_index(["league", "season"])
x = tm[tm["team"] == T]
ps = x.groupby("season").agg(mac=("row_id", "size"), in_seq=("in_seq", "sum"), ilk=("date", "min"), son=("date", "max")).reset_index()
ps["lig_sezon_tam"] = [bool(cov.loc[("N1", s), "tam"]) for s in ps["season"]]
ps["pay"] = [float(cov.loc[("N1", s), "pay"]) for s in ps["season"]]
ps["kisaltilmis"] = [bool(cov.loc[("N1", s), "kisaltilmis"]) for s in ps["season"]]
ps["devam_ediyor"] = [bool(cov.loc[("N1", s), "devam_ediyor"]) for s in ps["season"]]
ps["normal_sezon_kurali"] = [int(cov.loc[("N1", s), "normal_sezon_mac"]) for s in ps["season"]]
ps.to_csv(f"{OUT}/psv_sezonlar.csv", index=False)
R["sezon_sayisi"] = int(len(ps)); R["tam_olmayan_sezonlar"] = ps.loc[~ps["lig_sezon_tam"], ["season", "mac", "pay"]].to_dict("records")
R["kisaltilmis"] = ps.loc[ps["kisaltilmis"], "season"].tolist(); R["devam_eden"] = ps.loc[ps["devam_ediyor"], "season"].tolist()
R["takim_mac_kuraldan_az_sezonlar"] = ps.loc[(ps["mac"] < ps["normal_sezon_kurali"]), ["season", "mac", "normal_sezon_kurali", "lig_sezon_tam"]].to_dict("records")
R["dilim_sayisi"] = int(x["spell_id"].nunique()); R["lig_degisimi"] = int(x["league_changed"].sum()); R["season_skip"] = int(x["season_skip"].sum())
R["ust_tur"] = int(x["ust_tur"].sum())
# her aralık için boşluk kontrolü
t = x[x["in_seq"]].reset_index(drop=True)
def gap_check(ev_dates):
    out = []
    idx = [int(t.index[pd.to_datetime(t["date"]) == pd.Timestamp(d)][0]) for d in ev_dates]
    for a, b in zip(idx[:-1], idx[1:]):
        seg = t.iloc[a:b + 1]
        out.append({"bas": str(pd.Timestamp(t.loc[a, "date"]).date()), "son": str(pd.Timestamp(t.loc[b, "date"]).date()),
                    "mac": b - a, "eksik_sezon": sorted(seg.loc[~seg["season_complete"], "season"].unique().tolist()),
                    "dilim_degisir": bool(seg["spell_id"].nunique() > 1)})
    return out
g21 = gap_check(ev["date"].tolist())
R["ham_2_1_bosluk_asan_aralik"] = [g for g in g21 if g["eksik_sezon"] or g["dilim_degisir"]]
# sol kesik: ilk olaydan önceki dönem
R["ham_2_1_ilk_olay_oncesi_mac"] = int(ev.iloc[0]["seq_no"]) if len(ev) else None
R["ham_2_1_ilk_olay_oncesi_eksik_sezon"] = sorted(t.iloc[: int(ev.iloc[0]["seq_no"]) + 1].loc[lambda d: ~d["season_complete"], "season"].unique().tolist())
for tg in ("IY_GERIDE_MS_GALIP", "IY_ONDE_MS_MAGLUP"):
    e = team_events(tm, T, target=tg)
    gg = gap_check(e["date"].tolist())
    R[f"{tg}_bosluk_asan_aralik"] = [g for g in gg if g["eksik_sezon"] or g["dilim_degisir"]]
    R[f"{tg}_bosluk_asan_sayi"] = len(R[f"{tg}_bosluk_asan_aralik"])
# açık aralık maçları
last_ev = pd.Timestamp(ev.iloc[-1]["date"])
tail = t[pd.to_datetime(t["date"]) > last_ev][["date", "season", "opponent", "is_home", "gf_ht", "ga_ht", "gf_ft", "ga_ft", "season_complete"]]
R["acik_aralik_maclari"] = [{**{k: str(v) for k, v in r.items()}} for r in tail.to_dict("records")]
json.dump(R, open(f"{OUT}/s6_psv.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(R, ensure_ascii=False, indent=1, default=str))
print(ps.to_string())

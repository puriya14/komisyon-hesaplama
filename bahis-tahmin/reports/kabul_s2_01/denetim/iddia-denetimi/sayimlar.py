"""Belgelerdeki basit veri sayımlarını yeniden kurulmuş CSV'den doğrular (salt-okunur; hipotez testi/model uyumu yok).

Kullanım: python -I sayimlar.py <kod_kok> <maclar.csv.gz> <cikti.json>
Yalnızca tanımlayıcı sayımlar: satır/lig/tarih, oran/İY/kırmızı kart/saat kapsamı, dizi-kapsam (veri boşluğu, hükmen
olabilir) ve belgede zaten yayımlanmış PSV olay sayıları (dizi-olay komutunun kullandığı team_events ile).
"""
import json
import sys

import numpy as np
import pandas as pd

kok, csv, cikti = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, kok)
from bahis_tahmin.sequences.research import data_sha256  # noqa: E402
from bahis_tahmin.sequences.timeline import build_team_matches, coverage_report, team_events  # noqa: E402

m = pd.read_csv(csv, parse_dates=["date"], low_memory=False)
out = {}
out["veri_sha256"] = data_sha256(m)
out["mac_sayisi"] = int(len(m))
out["lig_sayisi"] = int(m["league"].nunique())
out["ligler"] = sorted(m["league"].unique().tolist())
out["tarih_min"], out["tarih_max"] = str(m["date"].min().date()), str(m["date"].max().date())
out["kaynak"] = m["source"].value_counts().to_dict()
odds = np.isfinite(m[["o_h", "o_d", "o_a"]].to_numpy(dtype=float)).all(axis=1)
out["oran_1x2_kapsam_payi"] = float(odds.mean())
out["oran_1x2_eksik_satir"] = int((~odds).sum())
out["b365_esit_o"] = bool(np.allclose(m[["o_h", "o_d", "o_a"]].to_numpy(dtype=float),
                                      m[["b365_h", "b365_d", "b365_a"]].to_numpy(dtype=float), equal_nan=True))
out["ps_dolu_satir"] = int(m[["ps_h"]].notna().sum().iloc[0])
out["oc_dolu_satir"] = int(m[["oc_h"]].notna().sum().iloc[0])
ht = m["hthg"].notna() & m["htag"].notna()
out["iy_skor_kapsam_payi"] = float(ht.mean())
sy = np.where(m["date"].dt.month >= 7, m["date"].dt.year, m["date"].dt.year - 1)
red = m["h_red"].notna() & m["a_red"].notna()
t = m["time"].astype(str).str.match(r"^\d{1,2}:\d{2}$")
by = pd.DataFrame({"sy": sy, "red": red, "time": t, "odds": odds}).groupby("sy").mean().round(4)
out["sezon_yili_kapsam"] = {int(k): v for k, v in by.to_dict(orient="index").items()}

tm = build_team_matches(m)
cov = coverage_report(tm)
out["lig_sezon_sayisi"] = int(len(cov))
out["veri_boslugu_lig_sezon"] = int((~cov["tam"]).sum())
out["hukmen_olabilir"] = int(tm.attrs.get("n_awarded"))

team = "PSV Eindhoven"
p = tm[tm["team"] == team]
out["psv"] = {"satir": int(len(p)), "ligler": p["league"].value_counts().to_dict(),
              "ilk": str(pd.Timestamp(p["date"].min()).date()), "son": str(pd.Timestamp(p["date"].max()).date()),
              "iy_skor_eksik": int(p["htft"].isna().sum() + (p["htft"] == "").sum()) if "htft" in p else None}
ev = team_events(tm, team, htft_key="HTFT_2_1")
out["psv"]["ham_2_1"] = {"n": int(len(ev)), "ev_sahibi": int(ev["is_home"].sum()),
                         "deplasman": int((~ev["is_home"].astype(bool)).sum()),
                         "ilk": str(pd.Timestamp(ev["date"].min()).date()),
                         "son": str(pd.Timestamp(ev["date"].max()).date()),
                         "son_rakip": str(ev.iloc[-1]["opponent"]),
                         "son_iy": [float(ev.iloc[-1]["gf_ht"]), float(ev.iloc[-1]["ga_ht"])],
                         "son_ms": [float(ev.iloc[-1]["gf_ft"]), float(ev.iloc[-1]["ga_ft"])],
                         "acik_aralik": ev.attrs.get("censored_tail")}
for tgt in ("IY_GERIDE_MS_GALIP", "IY_ONDE_MS_MAGLUP"):
    e = team_events(tm, team, target=tgt)
    gaps = e["onceki_olaydan_mac"].dropna()
    out["psv"][tgt] = {"n": int(len(e)), "medyan_aralik_mac": float(gaps.median()) if len(gaps) else None,
                       "aralik_sayisi": int(len(gaps)), "acik_aralik": e.attrs.get("censored_tail")}
with open(cikti, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=str)
print(json.dumps({k: v for k, v in out.items() if k != "sezon_yili_kapsam"}, ensure_ascii=False, indent=1, default=str))
print("sezon_yili_kapsam:")
print(by.to_string())

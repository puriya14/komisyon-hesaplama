"""Adım 1: 22 lig / 184.378 maç / tarih aralığı / veri SHA-256 (baseline research.data_sha256)."""
import json
import pandas as pd
from ortak import load, OUT
from bahis_tahmin.sequences.research import data_sha256
m = load()
res = {
    "satir": int(len(m)), "sutunlar": list(m.columns), "lig_sayisi": int(m["league"].nunique()),
    "ligler": sorted(m["league"].unique().tolist()),
    "tarih_min": str(m["date"].min().date()), "tarih_max": str(m["date"].max().date()),
    "sha256": data_sha256(m),
    "sha256_yalniz_parse_dates_okuma": data_sha256(pd.read_csv(__import__("ortak").CSV, parse_dates=["date"], low_memory=False)),
    "dtypes": {c: str(t) for c, t in m.dtypes.items()},
    "tekrar_lig_tarih_ev_dep": int(m.duplicated(["league", "date", "home", "away"]).sum()),
    "sezon_etiketleri": sorted(m["season"].astype(str).unique().tolist()),
}
man = json.load(open(f"{OUT}/dizi_sonuclar_01b7e9f.json"))["manifest"]
res["manifest"] = {k: man[k] for k in ("mac_sayisi", "veri_tarih_araligi", "veri_sha256", "veri_etiketi")}
res["sha_eslesir"] = res["sha256"] == man["veri_sha256"]
json.dump(res, open(f"{OUT}/s1_temel.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))

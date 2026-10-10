"""Resmi çalıştırmanın yerel anomaliler.json dosyasından YALNIZCA toplu sayımlar (takım/maç adı yazılmaz)."""
import json, sys
from collections import Counter
import numpy as np
a = json.load(open(sys.argv[1], encoding="utf-8"))
out = {"kayit": len(a)}
flags = Counter(f for r in a for f in r["flags"])
out["bayrak_sayilari"] = dict(flags)
out["iki_bayrakli"] = sum(1 for r in a if len(r["flags"]) > 1)
out["status"] = dict(Counter(r["status"] for r in a))
expl = Counter(e for r in a for e in (r.get("explained_by") or []))
out["aciklayan_kontrol_kayit_sayisi"] = dict(expl)
# kırmızı kart verisi yok
nored = 0; ran = Counter(); 
for r in a:
    for c in r["checklist"]:
        if c.get("calistirildi"):
            ran[c["kontrol"]] += 1
        if "kırmızı" in c["kontrol"] and ("veri yok" in str(c.get("sonuc", "")) or c.get("calistirildi") is False):
            nored += 1
out["kontrol_calistirildi_kayit"] = dict(ran)
out["kirmizi_kart_veri_yok_kayit"] = nored
kirmizi_sonuc = Counter(str(c.get("sonuc"))[:60] for r in a for c in r["checklist"] if "kırmızı" in c["kontrol"])
out["kirmizi_kart_sonuc_dagilimi"] = dict(kirmizi_sonuc)
sur_unexpl = [r for r in a if r.get("status_by_flag", {}).get("UNEXPLAINED_ANOMALY") == "UNEXPLAINED_ANOMALY"]
out["surpriz_aciklanamayan"] = len(sur_unexpl)
out["surpriz_aciklanamayan_htft"] = dict(Counter(r["htft"] for r in sur_unexpl).most_common(5))
out["surpriz_aciklanamayan_medyan_s0_p"] = float(np.median([r["s0_p_gerceklesen"] for r in sur_unexpl]))
sur_all = [r for r in a if "UNEXPLAINED_ANOMALY" in r["flags"]]
out["surpriz_tum_htft"] = dict(Counter(r["htft"] for r in sur_all).most_common(5))
out["status_by_flag_dagilimi"] = dict(Counter((f, s) for r in a for f, s in r["status_by_flag"].items()))
out["status_by_flag_dagilimi"] = {f"{k[0]}->{k[1]}": v for k, v in out["status_by_flag_dagilimi"].items()}
print(json.dumps(out, ensure_ascii=False, indent=1))

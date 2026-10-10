"""Ek sayımlar: kayıtların sezon yılı aralığı, S0'sız olabilecek ilk sezonların maç sayısı, ≤100 havuzların nedeni."""
import json, sys
from pathlib import Path
import pandas as pd
OUT = Path(__file__).resolve().parent
SEQ = Path(sys.argv[1])
recs = json.loads((SEQ / "anomaliler.json").read_text(encoding="utf-8"))
d = pd.to_datetime(pd.Series([r["date"] for r in recs]))
print("kayıt tarih aralığı:", d.min().date(), d.max().date())
print("kayıt sezonları (isinma):", sorted({r["season"] for r in recs if r["period"] == "isinma"}))
k = pd.read_csv(OUT / "evren_kume.csv")
early = k[k.sezon.isin(["2000/01", "2001/02"])]
print("2000/01+2001/02 küme:", len(early), "maç:", int(early.mac.sum()), "S kayıtlı küme:", int((early.S_kayit > 0).sum()))
print("toplam maç:", int(k.mac.sum()), " manifest has_s0 satır/2 =", 343856 // 2, " fark =", int(k.mac.sum()) - 343856 // 2)
le = k[k.iyms_bilinen <= 100]
print("≤100 İY/MS-bilinen maçlı küme:", len(le), "neden:", le.S_kayit_yok_nedeni.value_counts().to_dict(), "S kayıtlı:", int((le.S_kayit > 0).sum()))
pn = k[k.period.isna()]
print("period None küme sezonları:", pn.sezon.value_counts().to_dict())
inc = k[(k.S_kayit_yok_nedeni.fillna('').str.startswith('lig-sezon tam'))]
print("tam olmayan küme sayısı:", len(inc), "sezonlar (ilk 10):", inc.sezon.value_counts().head(10).to_dict())
print("kırmızı kart verisi eksik 1600 kayıt içinde yıl aralığı ve kırmızı kart çalışan kayıtların en erken yılı:")
kk = pd.DataFrame([{"y": int(r["date"][:4]), "ok": next(c for c in r["checklist"] if c["kontrol"] == "kırmızı kart")["calistirildi"]} for r in recs])
print("  NA yıl:", kk[~kk.ok].y.min(), "-", kk[~kk.ok].y.max(), "; çalışan en erken yıl:", kk[kk.ok].y.min(), "; 2018+ NA:", int((~kk.ok & (kk.y >= 2018)).sum()))

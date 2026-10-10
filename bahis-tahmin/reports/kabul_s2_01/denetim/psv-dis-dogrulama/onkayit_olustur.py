"""Adim 1: PSV ham IY/MS 2/1 (HTFT_2_1) mac listesi + orneklem on-kaydi.

WEB ERISIMINDEN ONCE calistirilir. Yalnizca listeleme/sayim yapar (desen aramasi, test, model yok).
Kullanim: python -I onkayit_olustur.py <csv.gz> <cikti_dizini> <kod_kok>
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

csv_path, out_dir, kod_kok = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, kod_kok)
from bahis_tahmin.sequences.research import data_sha256  # noqa: E402  (01b7e9f'den disari aktarilan kod)

TEAM = "PSV Eindhoven"
SEED = 20261010

file_sha = hashlib.sha256(Path(csv_path).read_bytes()).hexdigest()
df = pd.read_csv(csv_path, parse_dates=["date"])
icerik_sha = data_sha256(df)

psv = df[(df["home"] == TEAM) | (df["away"] == TEAM)].copy()
n_psv = len(psv)
n_psv_ht = int(psv[["hthg", "htag"]].notna().all(axis=1).sum())
mask = psv[["hthg", "htag"]].notna().all(axis=1) & (psv["hthg"] < psv["htag"]) & (psv["fthg"] > psv["ftag"])
ev = psv[mask].sort_values(["date", "home", "away"], kind="mergesort").reset_index()  # 'index' = CSV satir indeksi
ev["psv_rolu"] = np.where(ev["home"] == TEAM, "ev", "deplasman")


def kayit(r):
    return {
        "csv_satir_indeksi": int(r["index"]),
        "lig": r["league"], "sezon": r["season"], "tarih": r["date"].strftime("%Y-%m-%d"),
        "ev": r["home"], "deplasman": r["away"], "psv_rolu": r["psv_rolu"],
        "iy": f"{int(r['hthg'])}-{int(r['htag'])}", "ms": f"{int(r['fthg'])}-{int(r['ftag'])}",
        "kaynak_sutunu": r["source"],
    }


tum = [kayit(r) for _, r in ev.iterrows()]
used = set()
secim = []

i_last = len(ev) - 1
secim.append({"kural": "(i) en son HTFT_2_1 maci", "sira_no": i_last, **tum[i_last]}); used.add(i_last)
i_first = 0
secim.append({"kural": "(ii) en eski HTFT_2_1 maci", "sira_no": i_first, **tum[i_first]}); used.add(i_first)
dep = [k for k in range(len(ev)) if ev.loc[k, "psv_rolu"] == "deplasman"]
i_dep = max(dep)
if i_dep in used:
    raise SystemExit("(iii) zaten secili; kural belirsiz")
secim.append({"kural": "(iii) PSV'nin DEPLASMAN oldugu en son HTFT_2_1 maci", "sira_no": i_dep, **tum[i_dep]}); used.add(i_dep)
kalan = [k for k in range(len(ev)) if k not in used]
rng = np.random.default_rng(SEED)
cek = rng.choice(np.array(kalan), size=2, replace=False)
for j, k in enumerate(cek.tolist()):
    secim.append({"kural": f"({'iv' if j == 0 else 'v'}) rastgele cekilis", "sira_no": int(k), **tum[int(k)]})

onkayit = {
    "amac": "PSV Eindhoven ham IY/MS 2/1 (HTFT_2_1) maclarinin sinirli dis capraz kontrolu icin orneklem on-kaydi",
    "olusturma_zamani_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "not": "Bu dosya herhangi bir web erisiminden ONCE yazildi; dogrulama sonrasi degistirilmez (sha256 sonuclar dosyasina yazilir).",
    "veri": {
        "dosya": csv_path, "dosya_bayt_sha256": file_sha,
        "icerik_sha256_data_sha256": icerik_sha,
        "manifest_veri_sha256 (reports/dizi_sonuclar.json@01b7e9f)": "6ca929a2c62fb0aa304bb672339d290347db416e1c8bbfea758f6a46b53b4bc2",
        "eslesiyor": icerik_sha == "6ca929a2c62fb0aa304bb672339d290347db416e1c8bbfea758f6a46b53b4bc2",
        "okuma": "pd.read_csv(path, parse_dates=['date'])",
    },
    "olay_tanimi": "ham IY/MS 2/1: hthg<htag ve fthg>ftag (ev sahibi IY geride, MS galip); PSV ev VEYA deplasman; hthg/htag NaN olan satirlar haric",
    "siralama": "date, home, away artan (mergesort); sira_no bu siradaki 0-tabanli konum",
    "kural": {
        "i": "en son HTFT_2_1 maci (sira_no = n-1)",
        "ii": "en eski HTFT_2_1 maci (sira_no = 0)",
        "iii": "PSV'nin deplasman oldugu en son HTFT_2_1 maci (PSV IY onde, MS maglup)",
        "iv_v": f"kalan maclarin sira_no listesinden numpy.random.default_rng({SEED}).choice(kalan, size=2, replace=False)",
    },
    "sayimlar": {
        "psv_mac_sayisi": n_psv, "psv_iy_skoru_olan": n_psv_ht,
        "psv_ligleri": psv["league"].value_counts().to_dict(),
        "psv_tarih_araligi": [psv["date"].min().strftime("%Y-%m-%d"), psv["date"].max().strftime("%Y-%m-%d")],
        "htft_2_1_toplam": len(ev),
        "htft_2_1_psv_ev": int((ev["psv_rolu"] == "ev").sum()),
        "htft_2_1_psv_deplasman": int((ev["psv_rolu"] == "deplasman").sum()),
    },
    "rng": {"tohum": SEED, "kalan_sira_no": kalan, "cekilen_sira_no": [int(x) for x in cek], "numpy": np.__version__},
    "orneklem": secim,
    "tam_liste": tum,
}
out_dir.mkdir(parents=True, exist_ok=True)
p = out_dir / "orneklem_onkayit.json"
if p.exists():
    raise SystemExit("on-kayit zaten var; uzerine yazilmaz")
p.write_text(json.dumps(onkayit, ensure_ascii=False, indent=2), encoding="utf-8")
pd.DataFrame(tum).to_csv(out_dir / "psv_htft21_liste.csv", index=False)
print(json.dumps({k: onkayit[k] for k in ("olusturma_zamani_utc", "veri", "sayimlar", "rng")}, ensure_ascii=False, indent=1))
for s in secim:
    print(s["kural"], "|", s["tarih"], s["ev"], "-", s["deplasman"], "IY", s["iy"], "MS", s["ms"], s["psv_rolu"])
print("sha256(orneklem_onkayit.json) =", hashlib.sha256(p.read_bytes()).hexdigest())

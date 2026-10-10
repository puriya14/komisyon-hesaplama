"""Anomali sayımlarının maç (pair_id) düzeyinde uzlaştırılması — YALNIZCA mevcut kayıtlar okunur.

Girdi: seq/research_out/anomaliler.json (resmi çalıştırmanın yerel tekil kayıtları),
       seq/research_out/sonuclar_tam.json ve 01b7e9f:reports/dizi_sonuclar.json (anomali_ozeti).
Yeni örüntü araması / model uyumu YOK; yalnızca kümeler, kesişimler ve sayımlar.
Çıktılar: sayim_uzlastirma.csv, aciklayan_kontrol_kesisim.csv, havuz_bayrak.csv, a_ozet.json (bu klasöre).
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
SEQ = Path(sys.argv[1])  # .../scratchpad/seq/research_out
BASE_JSON = Path(sys.argv[2])  # git show 01b7e9f:bahis-tahmin/reports/dizi_sonuclar.json çıktısı

S_T, M_T = "UNEXPLAINED_ANOMALY", "MODEL_PIYASA_FARKI"
EXPL = "açıklanabilir"

recs = json.loads((SEQ / "anomaliler.json").read_text(encoding="utf-8"))
oz_tam = json.loads((SEQ / "sonuclar_tam.json").read_text(encoding="utf-8"))["anomali_ozeti"]
oz_repo = json.loads(BASE_JSON.read_text(encoding="utf-8"))["anomali_ozeti"]

rows = []
for r in recs:
    ck = {c["kontrol"]: c for c in r["checklist"]}
    rows.append({
        "pair_id": r["pair_id"], "event_id": r["event_id"], "date": r["date"], "cluster": r["cluster"],
        "period": r["period"], "htft": r["htft"], "p_real": r["s0_p_gerceklesen"], "bits": r["surprise_bits"],
        "s_share": r["surprise_top_share"], "s_n": r["surprise_pool_n"], "gap": r["model_market_gap"],
        "m_share": r["gap_top_share"], "m_n": r["gap_pool_n"],
        "S": S_T in r["flags"], "M": M_T in r["flags"], "type": r["type"], "status": r["status"],
        "st_S": r["status_by_flag"].get(S_T), "st_M": r["status_by_flag"].get(M_T),
        "explained_by": "|".join(r["explained_by"]),
        **{f"aciklar::{k}": bool(v["aciklar"]) for k, v in ck.items()},
        **{f"calisti::{k}": bool(v["calistirildi"]) for k, v in ck.items()},
        **{f"sonuc::{k}": v["sonuc"] for k, v in ck.items()},
        **{f"kapsam::{k}": "|".join(v["kapsam"]) for k, v in ck.items()},
    })
df = pd.DataFrame(rows)
# Maçı tanımlayabilecek alanlar (event_id, pair_id, tarih, lig-sezon) yazılmaz; yalnızca sayım için gereken sütunlar.
df.to_csv(OUT / "kayit_tablosu_kimliksiz.csv", index=False,
          columns=[c for c in df.columns if c not in ("event_id", "pair_id", "date", "cluster")
                   and not c.startswith("sonuc::")])

n = len(df)
S = set(df.loc[df.S, "pair_id"])
M = set(df.loc[df.M, "pair_id"])
U = S | M
I = S & M
assert df.pair_id.is_unique and df.event_id.is_unique

# Bayrak başına durum (status_by_flag) — anomaly.py:254-257
s_unexp = df.S & (df.st_S == S_T)
s_exp = df.S & (df.st_S == EXPL)
m_unexp = df.M & (df.st_M == M_T)
m_exp = df.M & (df.st_M == EXPL)
assert (s_unexp | s_exp)[df.S].all() and (m_unexp | m_exp)[df.M].all()

# Kayıt düzeyi "durum" (status = status_by_flag[flags[0]]; S varsa S'nin durumu) — anomaly.py:270
dur = Counter(df.status)
only_m = df.M & ~df.S
both = df.S & df.M

PER = ["isinma", "kesif", "parametre", "test"]


def per(mask) -> dict:
    c = Counter(df.loc[mask, "period"])
    return {p: int(c.get(p, 0)) for p in PER}


def chk(name):
    return df[f"aciklar::{name}"]


lig = chk("lig değişikliği sonrası ilk maçlar")
kk = chk("kırmızı kart")
kk_na = ~df["calisti::kırmızı kart"]
hk = chk("hükmen olabilir")
vd = chk("veri doğrulama")
ta = chk("takım adı kopukluğu")
ta_na = ~df["calisti::takım adı kopukluğu"]
lig_na = ~df["calisti::lig değişikliği sonrası ilk maçlar"]

table = []


def add(kod, iddia, birim, evren, sayi, rapor, durum, kaynak, not_=""):
    table.append({"kod": kod, "raporlanan_iddia": iddia, "raporlanan_sayi": rapor, "hesaplanan": sayi,
                  "sayim_birimi": birim, "evren": evren, "donem_dagilimi": None, "durum": durum,
                  "kaynak": kaynak, "not": not_})


EVREN = ("lig-sezon referans havuzu = lig-sezonun S0 + bilinen İY/MS (sürpriz) veya S0 + piyasa oranı (fark) olan TÜM "
         "maçları (dönem/uygunluk fark etmez); raporlanan = iki satırından en az biri (uygun ∧ dönem≠None) olan maçlar "
         "(research.py:892, anomaly.py:111,247)")

add("N_kayit", "toplam 1.600 kayıt", "maç (pair_id; ev satırı temsilci)", EVREN, n, 1600,
    "DOGRULANDI" if n == 1600 else "DUZELTILDI", "anomaliler.json len; anomali_ozeti.toplam",
    f"pair_id tekil={df.pair_id.is_unique}; event_id tekil={df.event_id.is_unique}; |S∪M|={len(U)}")
table[-1]["donem_dagilimi"] = json.dumps(per(df.S | df.M))
add("S", "sürpriz 845", "maç-bayrağı (UNEXPLAINED_ANOMALY bayrağı taşıyan maç)", EVREN, len(S), 845,
    "DOGRULANDI" if len(S) == 845 else "DUZELTILDI", "flags içinde UNEXPLAINED_ANOMALY; anomali_ozeti.tur",
    "İSİM UYARISI: bayrak adı UNEXPLAINED_ANOMALY olduğu halde 210'u 'açıklanabilir' durumda")
table[-1]["donem_dagilimi"] = json.dumps(per(df.S))
add("M", "piyasa farkı 761", "maç-bayrağı (MODEL_PIYASA_FARKI)", EVREN, len(M), 761,
    "DOGRULANDI" if len(M) == 761 else "DUZELTILDI", "flags içinde MODEL_PIYASA_FARKI; anomali_ozeti.tur")
table[-1]["donem_dagilimi"] = json.dumps(per(df.M))
add("S∩M", "(raporlanmadı) iki bayrak birlikte", "maç", EVREN, len(I), None, "BILGI",
    "küme kesişimi", "845 + 761 = 1.606 bayrak; 1.600 maç → 6 maç iki bayraklı")
table[-1]["donem_dagilimi"] = json.dumps(per(df.S & df.M))
add("S∪M", "toplam 1.600", "maç", EVREN, len(U), 1600, "DOGRULANDI" if len(U) == 1600 else "DUZELTILDI",
    "küme birleşimi")
add("S_aciklanamayan", "845 sürpriz işaretinden 635'i açıklanamadı", "maç-bayrağı (S, status_by_flag[S]=S)",
    "S kümesi", int(s_unexp.sum()), 635, "DOGRULANDI" if s_unexp.sum() == 635 else "DUZELTILDI",
    "status_by_flag; anomali_ozeti.tur_durum_donem.UNEXPLAINED_ANOMALY.UNEXPLAINED_ANOMALY")
table[-1]["donem_dagilimi"] = json.dumps(per(s_unexp))
add("S_aciklanabilir", "210 (= 845 − 635)", "maç-bayrağı (S, status_by_flag[S]=açıklanabilir)", "S kümesi",
    int(s_exp.sum()), 210, "DOGRULANDI" if s_exp.sum() == 210 else "DUZELTILDI",
    "anomali_ozeti.tur_durum_donem.UNEXPLAINED_ANOMALY.açıklanabilir")
table[-1]["donem_dagilimi"] = json.dumps(per(s_exp))
add("M_aciklanamayan", "(özette tur_durum_donem içinde) M bayrağı açıklanamayan", "maç-bayrağı (M)", "M kümesi",
    int(m_unexp.sum()), None, "BILGI", "status_by_flag[MODEL_PIYASA_FARKI]",
    "493 ile KARIŞTIRILMAMALI: bayrak düzeyinde 497")
table[-1]["donem_dagilimi"] = json.dumps(per(m_unexp))
add("M_aciklanabilir", "M bayrağı açıklanabilir", "maç-bayrağı (M)", "M kümesi", int(m_exp.sum()), None, "BILGI",
    "status_by_flag[MODEL_PIYASA_FARKI]")
table[-1]["donem_dagilimi"] = json.dumps(per(m_exp))
add("durum_MPF", "493 MODEL_PIYASA_FARKI", "KAYIT (maç) durumu = status_by_flag[flags[0]]",
    "yalnızca-M kayıtları (S bayrağı olmayan 755 maç)", int(dur.get(M_T, 0)), 493,
    "DARALTILDI" if dur.get(M_T, 0) == 493 else "DUZELTILDI", "anomali_ozeti.durum; anomaly.py:270,289-290",
    "493 = yalnızca-M ve açıklanamayan kayıt; M bayrağı açıklanamayan sayısı 497 (4'ü S∩M kayıtlarında S durumu "
    "altında gizli)")
table[-1]["donem_dagilimi"] = json.dumps(per(only_m & m_unexp))
add("durum_UA", "635 açıklanamayan (durum)", "KAYIT durumu", "S kümesi (S varsa durum S'ninkidir)",
    int(dur.get(S_T, 0)), 635, "DOGRULANDI" if dur.get(S_T, 0) == 635 else "DUZELTILDI", "anomali_ozeti.durum")
add("durum_acik", "472 açıklanabilir", "KAYIT durumu (iki bayrak türü karışık)",
    "S-açıklanabilir (210) + yalnızca-M açıklanabilir", int(dur.get(EXPL, 0)), 472,
    "DARALTILDI" if dur.get(EXPL, 0) == 472 else "DUZELTILDI", "anomali_ozeti.durum",
    f"= {int(s_exp.sum())} sürpriz kaydı + {int((only_m & m_exp).sum())} yalnızca-piyasa-farkı kaydı; tek bir bayrak "
    "türünün 'açıklanan' sayısı değildir")
table[-1]["donem_dagilimi"] = json.dumps(per(df.status == EXPL))

# 353 / 121 / 429 — hangi havuz?
for kod, name, mask, rap in (("lig_353", "lig değişikliği sonrası ilk maçlar (aciklar=True)", lig, 353),
                             ("kk_121", "kırmızı kart (aciklar=True)", kk, 121),
                             ("kk_na_429", "kırmızı kart çalıştırılamadı (değerlendirilemedi)", kk_na, 429)):
    c_all = int(mask.sum())
    c_s = int((mask & df.S).sum())
    c_m = int((mask & df.M).sum())
    c_mo = int((mask & only_m).sum())
    c_sexp = int((mask & s_exp).sum())
    add(kod, name, "KAYIT (maç)", "1.600 kaydın tümü (S∪M)", c_all, rap,
        "BILGI", "checklist[kontrol].aciklar / calistirildi",
        f"S içinde {c_s}; M içinde {c_m}; yalnızca-M {c_mo}; S∩M {int((mask & both).sum())}; "
        f"S-açıklanabilir 210 içinde {c_sexp}")
    table[-1]["donem_dagilimi"] = json.dumps(per(mask))

tab = pd.DataFrame(table)

# 210 açıklanan sürpriz kaydının açıklayan kontrollere göre dağılımı (S kapsamlı açıklayan kontroller)
CHK = ["veri doğrulama", "hükmen olabilir", "takım adı kopukluğu", "lig değişikliği sonrası ilk maçlar", "kırmızı kart"]


def s_explainers(i):
    return tuple(c for c in CHK if df.at[i, f"aciklar::{c}"] and S_T in df.at[i, f"kapsam::{c}"].split("|"))


def m_explainers(i):
    return tuple(c for c in CHK if df.at[i, f"aciklar::{c}"] and M_T in df.at[i, f"kapsam::{c}"].split("|"))


combo_s = Counter(s_explainers(i) for i in df.index[s_exp])
combo_m = Counter(m_explainers(i) for i in df.index[m_exp])
# tutarlılık: S-açıklayan yok ⇔ S açıklanamayan
assert all(len(s_explainers(i)) == 0 for i in df.index[s_unexp])
assert all(len(m_explainers(i)) == 0 for i in df.index[m_unexp])
crow = []
for flag, cc in (("S", combo_s), ("M", combo_m)):
    for k, v in sorted(cc.items(), key=lambda kv: -kv[1]):
        crow.append({"bayrak": flag, "aciklayan_kontrol_birlesimi": " + ".join(k), "kayit": v,
                     "kontrol_sayisi": len(k)})
cdf = pd.DataFrame(crow)
cdf.to_csv(OUT / "aciklayan_kontrol_kesisim.csv", index=False)
marg_s = {c: int(sum(v for k, v in combo_s.items() if c in k)) for c in CHK}
marg_m = {c: int(sum(v for k, v in combo_m.items() if c in k)) for c in CHK}

# Kırmızı kart değerlendirilemeyen kayıtların dönemi/yılı
df["year"] = df.date.str[:4].astype(int)
kk_na_years = df.loc[kk_na].groupby("year").size().to_dict()
kk_na_S = int((kk_na & df.S).sum())
kk_na_S_unexp = int((kk_na & s_unexp).sum())

# İY/MS dağılımı (635 açıklanamayan sürpriz) — belgede "1/2 (619) ve 2/1 (218)" iddiası
ht_unexp = Counter(df.loc[s_unexp, "htft"].fillna("None"))
ht_S = Counter(df.loc[df.S, "htft"].fillna("None"))
ht_all = Counter(df.htft.fillna("None"))
med_p_unexp = float(df.loc[s_unexp, "p_real"].median())
med_p_S = float(df.loc[df.S, "p_real"].median())

# ---- Seçim kuralı: orta-sıra pay ve havuz büyüklüğü ----
# Üst pay = (2·büyük + eşit)/(2n); bayrak ⇔ 2·üst·n·200 < 2n·1 (anomaly.py:91-95), 1-q = 1/200


def n_flags_no_ties(nn: int) -> int:
    # k. büyük (eşitsiz): twice = 2k − 1; bayrak ⇔ (2k−1)·200 < 2·nn  ⇔ 2k − 1 < nn/100
    return sum(1 for k in range(1, nn + 1) if (2 * k - 1) * 200 < 2 * nn)


def twice_val(share, nn):
    return share * 2 * nn


chk_rule = []
for flag, sh, nn in (("S", "s_share", "s_n"), ("M", "m_share", "m_n")):
    sub = df[df[flag]]
    tw = (sub[sh] * 2 * sub[nn]).round(6)
    odd_int = ((tw - tw.round()).abs() < 1e-6) & (tw.round() % 2 == 1)
    chk_rule.append({"bayrak": flag, "kayit": len(sub), "pay_max": float(sub[sh].max()),
                     "hepsi_pay<0.005": bool((sub[sh] < 0.005).all()), "havuz_min": int(sub[nn].min()),
                     "havuz<=100_bayrak": int((sub[nn] <= 100).sum()),
                     "esitlik_yok(2·pay·n tek tam sayı)": bool(odd_int.all()),
                     "sira_k_max": int(((tw.round() + 1) // 2).max())})
    # bayraksız tarafın payı ≥ 0.005 olmalı
other = []
for flag, sh in (("S", "s_share"), ("M", "m_share")):
    sub = df[~df[flag]]
    other.append({"bayrak_yok": flag, "kayit": len(sub), "pay_min": float(sub[sh].min()) if sub[sh].notna().any() else None,
                  "hepsi_pay>=0.005_veya_NaN": bool(((sub[sh] >= 0.005) | sub[sh].isna()).all()),
                  "NaN_pay": int(sub[sh].isna().sum())})

# Havuz başına: kayıtlı bayrak sayısı vs kuralın zorladığı sayı
pool_rows = []
for flag, nn in (("S", "s_n"), ("M", "m_n")):
    g = df[df[flag]].groupby("cluster").agg(havuz_n=(nn, "first"), havuz_n_sabit=(nn, "nunique"),
                                            kayitli_bayrak=("pair_id", "size"))
    assert (g.havuz_n_sabit == 1).all()
    g["kural_bayrak"] = g.havuz_n.map(n_flags_no_ties)
    g["fark"] = g.kural_bayrak - g.kayitli_bayrak
    g["bayrak"] = flag
    pool_rows.append(g.reset_index())
pool = pd.concat(pool_rows, ignore_index=True)
# Lig kimliği yazılmaz (lig bazında anomali sayımı üretmemek için): yalnızca sezon + anonim küme kodu
import hashlib
_codes = {c: "K" + hashlib.sha256(c.encode()).hexdigest()[:6] for c in set(pool["cluster"])}  # b_evren_kontrol.py ile aynı kod
pool_out = pool.assign(sezon=pool["cluster"].str.split("|").str[1], kume_kodu=pool["cluster"].map(_codes)).drop(columns=["cluster"])
pool_out.to_csv(OUT / "havuz_bayrak.csv", index=False)

# havuz büyüklüğü sınıflarına göre özet
bins = [100, 150, 250, 350, 450, 650, 10**6]
labels = ["101-150", "151-250", "251-350", "351-450", "451-650", ">650"]
pool["sinif"] = pd.cut(pool.havuz_n, bins=bins, labels=labels, right=True)
pool_sum = (pool.groupby(["bayrak", "sinif"], observed=True)
            .agg(havuz_sayisi=("cluster", "size"), havuz_n_min=("havuz_n", "min"), havuz_n_max=("havuz_n", "max"),
                 kural_bayrak_toplam=("kural_bayrak", "sum"), kayitli_bayrak_toplam=("kayitli_bayrak", "sum"),
                 mac_toplam=("havuz_n", "sum")).reset_index())
pool_sum["kayitli_oran_%"] = (100 * pool_sum.kayitli_bayrak_toplam / pool_sum.mac_toplam).round(3)
pool_sum.to_csv(OUT / "havuz_sinif_ozet.csv", index=False)

# eşik tablosu: n → kural bayrak sayısı
thr = []
prev = None
for nn in range(1, 1201):
    f = n_flags_no_ties(nn)
    if f != prev:
        thr.append({"havuz_n_baslangic": nn, "bayrak_sayisi": f})
        prev = f
pd.DataFrame(thr).to_csv(OUT / "kural_esik_tablosu.csv", index=False)

res = {
    "n_kayit": n, "S": len(S), "M": len(M), "S∩M": len(I), "S∪M": len(U), "yalnizca_S": len(S - M),
    "yalnizca_M": len(M - S),
    "S_aciklanamayan": int(s_unexp.sum()), "S_aciklanabilir": int(s_exp.sum()),
    "M_aciklanamayan": int(m_unexp.sum()), "M_aciklanabilir": int(m_exp.sum()),
    "durum_sayim": dict(dur),
    "yalnizca_M_aciklanamayan": int((only_m & m_unexp).sum()), "yalnizca_M_aciklanabilir": int((only_m & m_exp).sum()),
    "SM_kesisim_detay": df.loc[both, ["period", "st_S", "st_M", "status", "explained_by"]].to_dict("records"),
    "donem": {"S∪M": per(df.S | df.M), "S": per(df.S), "M": per(df.M), "S_aciklanamayan": per(s_unexp),
              "S_aciklanabilir": per(s_exp), "M_aciklanamayan": per(m_unexp), "M_aciklanabilir": per(m_exp),
              "durum_MPF": per(only_m & m_unexp), "durum_acik": per(df.status == EXPL)},
    "ozet_esit_tam_repo": oz_tam == oz_repo,
    "aciklayan_S_birlesim": {" + ".join(k): v for k, v in combo_s.items()},
    "aciklayan_S_marjinal": marg_s,
    "aciklayan_M_birlesim": {" + ".join(k): v for k, v in combo_m.items()},
    "aciklayan_M_marjinal": marg_m,
    "kontrol_sayim_tum_kayit": {c: {"aciklar": int(chk(c).sum()), "calistirilamadi": int((~df[f"calisti::{c}"]).sum())}
                                for c in CHK},
    "lig_353": {"tum": int(lig.sum()), "S": int((lig & df.S).sum()), "M": int((lig & df.M).sum()),
                "yalnizca_M": int((lig & only_m).sum()), "S∩M": int((lig & both).sum())},
    "kk_121": {"tum": int(kk.sum()), "S": int((kk & df.S).sum()), "M": int((kk & df.M).sum()),
               "yalnizca_M": int((kk & only_m).sum()), "S∩M": int((kk & both).sum())},
    "kk_na_429": {"tum": int(kk_na.sum()), "S": kk_na_S, "S_aciklanamayan": kk_na_S_unexp,
                  "M": int((kk_na & df.M).sum()), "yalnizca_M": int((kk_na & only_m).sum()),
                  "yil": {int(k): int(v) for k, v in kk_na_years.items()}},
    "kk_calisti_S": int((~kk_na & df.S).sum()),
    "hukmen_aciklar_tum": int(hk.sum()), "veri_dogrulama_aciklar_tum": int(vd.sum()),
    "takim_adi_aciklar_tum": int(ta.sum()), "takim_adi_calistirilamadi": int(ta_na.sum()),
    "lig_calistirilamadi": int(lig_na.sum()),
    "htft_S_aciklanamayan": dict(ht_unexp), "htft_S_tum": dict(ht_S), "htft_tum_kayit": dict(ht_all),
    "medyan_p_S_aciklanamayan": med_p_unexp, "medyan_p_S_tum": med_p_S,
    "kural_kontrol": chk_rule, "bayraksiz_taraf": other,
    "havuz_sayisi": {f: int((pool.bayrak == f).sum()) for f in ("S", "M")},
    "havuz_fark_toplam": {f: int(pool.loc[pool.bayrak == f, "fark"].sum()) for f in ("S", "M")},
    "havuz_fark_dagilim": {f: {int(k): int(v) for k, v in pool.loc[pool.bayrak == f, "fark"].value_counts().items()}
                           for f in ("S", "M")},
    "havuz_n_ozet": {f: pool.loc[pool.bayrak == f, "havuz_n"].describe().round(1).to_dict() for f in ("S", "M")},
    "kayit_orani_%": {f: round(100 * pool.loc[pool.bayrak == f, "kayitli_bayrak"].sum()
                               / pool.loc[pool.bayrak == f, "havuz_n"].sum(), 4) for f in ("S", "M")},
    "kural_orani_%": {f: round(100 * pool.loc[pool.bayrak == f, "kural_bayrak"].sum()
                               / pool.loc[pool.bayrak == f, "havuz_n"].sum(), 4) for f in ("S", "M")},
    "sonsuz_bit": int((df.bits == float("inf")).sum()) if df.bits.notna().any() else 0,
    "bits_None_S": int(df.loc[df.S, "bits"].isna().sum()),
}
tab.to_csv(OUT / "sayim_uzlastirma.csv", index=False)
(OUT / "a_ozet.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
print(pool_sum.to_string())

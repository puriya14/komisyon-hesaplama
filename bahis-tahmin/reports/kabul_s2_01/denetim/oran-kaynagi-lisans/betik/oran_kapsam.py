"""Oran kaynağı/kapsam denetimi (yalnızca oran sütunları; sonuç/etiket analizi YOK).

Girdi: ham ayna CSV (salt-okunur), yeniden kurulan maç CSV'si, 01b7e9f kodunun dışa aktarılmış kopyası.
Çıktı: oran_kapsam.csv (lig-sezon), oran_kapsam_donem.csv, oran_kapsam_ozet.json, ham_sutunlar.txt
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(sys.argv[1])
RAW = Path(sys.argv[2])
REBUILT = Path(sys.argv[3])
KOD = Path(sys.argv[4])
sys.path.insert(0, str(KOD))

from bahis_tahmin.data.parsers import _odds, normalize_mirror  # noqa: E402
from bahis_tahmin.data.store import DataStore  # noqa: E402
from bahis_tahmin.data.leagues import MIRROR_TO_CODE  # noqa: E402
from bahis_tahmin.sequences import config as C  # noqa: E402
from bahis_tahmin.sequences.research import data_sha256  # noqa: E402

ozet = {}
raw = pd.read_csv(RAW, low_memory=False)
cols = list(raw.columns)
(OUT / "ham_sutunlar.txt").write_text("\n".join(cols) + "\n", encoding="utf-8")
ozet["ham_satir"] = int(len(raw))
ozet["ham_sutun_sayisi"] = len(cols)
ozet["ham_sutunlar"] = cols
# A/B/C (iki yarıda KG, 3,5 Üst, İY 1,5 Üst) ve İY/MS oran sütunu var mı? (ad taraması)
pat = r"(?i)btts|both|bts|gg|ng|3\.?5|35|1\.?5|15|ht.?ft|htft|half|iy|fh|1h|2h|corr|cs_"
ozet["abc_htft_aday_sutunlar"] = [c for c in cols if pd.Series([c]).str.contains(pat).iloc[0]
                                  and c not in ("HTHome", "HTAway", "HTResult")]

# --- 1) Ayna normalize + temizlik (baseline kodu) ve yeniden kurulan CSV ile eşitlik
norm = DataStore._clean_matches(normalize_mirror(raw))
reb = pd.read_csv(REBUILT, parse_dates=["date"], low_memory=False)
ozet["yeniden_kurulan_satir"] = int(len(reb))
ozet["baseline_parser_satir"] = int(len(norm))
try:
    ozet["yeniden_kurulan_data_sha256"] = data_sha256(reb)
    ozet["baseline_parser_data_sha256"] = data_sha256(norm)
except Exception as e:  # noqa: BLE001
    ozet["data_sha256_hata"] = repr(e)
odds_cols = ["o_h", "o_d", "o_a", "omax_h", "omax_d", "omax_a", "b365_h", "b365_d", "b365_a",
             "ps_h", "ps_d", "ps_a", "oc_h", "oc_d", "oc_a", "o_o25", "o_u25", "omax_o25", "omax_u25"]
if len(norm) == len(reb):
    eq = {}
    for c in odds_cols:
        a, b = norm[c].to_numpy(float), reb[c].to_numpy(float)
        eq[c] = bool(np.array_equal(np.isnan(a), np.isnan(b)) and np.allclose(a[~np.isnan(a)], b[~np.isnan(b)], rtol=0, atol=1e-12))
    ozet["oran_sutunlari_baseline_ile_ayni"] = eq

# --- 2) Ham sütun -> araştırma sütunu eşlemesinin satır düzeyinde doğrulanması ve doldurma sayıları
r = raw.copy()
r["league"] = r["Division"].astype(str).map(MIRROR_TO_CODE)
r = r[r["league"].notna()].copy()
r["date"] = pd.to_datetime(r["MatchDate"], errors="coerce").dt.normalize()
r["home"] = r["HomeTeam"].astype(str).str.strip()
r["away"] = r["AwayTeam"].astype(str).str.strip()
for side, c, mc in (("h", "OddHome", "MaxHome"), ("d", "OddDraw", "MaxDraw"), ("a", "OddAway", "MaxAway")):
    r[f"raw_odd_{side}"] = _odds(pd.to_numeric(r[c], errors="coerce"))
    r[f"raw_max_{side}"] = _odds(pd.to_numeric(r[mc], errors="coerce"))
    r[f"raw_odd_present_{side}"] = pd.to_numeric(r[c], errors="coerce").notna()
r["raw_o25"] = _odds(pd.to_numeric(r["Over25"], errors="coerce"))
r["raw_u25"] = _odds(pd.to_numeric(r["Under25"], errors="coerce"))
r["raw_mo25"] = _odds(pd.to_numeric(r["MaxOver25"], errors="coerce"))
r["raw_mu25"] = _odds(pd.to_numeric(r["MaxUnder25"], errors="coerce"))
key = ["league", "date", "home", "away"]
r = r.drop_duplicates(subset=key, keep="first")
m = reb.merge(r[key + [c for c in r.columns if c.startswith("raw_")]], on=key, how="left", validate="one_to_one")
ozet["eslesen_satir"] = int(m["raw_odd_h"].notna().sum() + (m["raw_odd_h"].isna() & m["raw_max_h"].notna()).sum()
                            + (m["raw_odd_h"].isna() & m["raw_max_h"].isna()).sum())
chk = {}
for side in "hda":
    a = m[f"o_{side}"].to_numpy(float)
    b = m[f"raw_odd_{side}"].to_numpy(float)
    chk[f"o_{side}==_odds(Odd*)"] = bool(np.array_equal(np.isnan(a), np.isnan(b)) and np.allclose(a[~np.isnan(a)], b[~np.isnan(b)]))
    a2 = m[f"b365_{side}"].to_numpy(float)
    chk[f"b365_{side}==o_{side}"] = bool(np.array_equal(np.isnan(a2), np.isnan(a)) and np.allclose(a2[~np.isnan(a2)], a[~np.isnan(a)]))
    exp = m[f"raw_max_{side}"].fillna(m[f"raw_odd_{side}"]).to_numpy(float)
    om = m[f"omax_{side}"].to_numpy(float)
    chk[f"omax_{side}==Max*.fillna(Odd*)"] = bool(np.array_equal(np.isnan(om), np.isnan(exp)) and np.allclose(om[~np.isnan(om)], exp[~np.isnan(exp)]))
for s, rc, mc in (("o25", "raw_o25", "raw_mo25"), ("u25", "raw_u25", "raw_mu25")):
    a = m[f"o_{s}"].to_numpy(float); b = m[rc].to_numpy(float)
    chk[f"o_{s}==_odds(raw)"] = bool(np.array_equal(np.isnan(a), np.isnan(b)) and np.allclose(a[~np.isnan(a)], b[~np.isnan(b)]))
    exp = m[mc].fillna(m[rc]).to_numpy(float); om = m[f"omax_{s}"].to_numpy(float)
    chk[f"omax_{s}==Max.fillna(raw)"] = bool(np.array_equal(np.isnan(om), np.isnan(exp)) and np.allclose(om[~np.isnan(om)], exp[~np.isnan(exp)]))
ozet["esleme_kontrolleri"] = chk

n = len(m)
one = m[["o_h", "o_d", "o_a"]].notna().all(axis=1)
anyo = m[["o_h", "o_d", "o_a"]].notna().any(axis=1)
mx_raw = m[["raw_max_h", "raw_max_d", "raw_max_a"]].notna().all(axis=1)
mx = m[["omax_h", "omax_d", "omax_a"]].notna().all(axis=1)
mx_fill = m[[f"raw_max_{s}" for s in "hda"]].isna().any(axis=1) & m[["omax_h", "omax_d", "omax_a"]].notna().any(axis=1)
ou = m[["o_o25", "o_u25"]].notna().all(axis=1)
ou_mx_raw = m[["raw_mo25", "raw_mu25"]].notna().all(axis=1)
ou_fill = (m["raw_mo25"].isna() & m["omax_o25"].notna()) | (m["raw_mu25"].isna() & m["omax_u25"].notna())
odd_invalid = (m[[f"raw_odd_present_{s}" for s in "hda"]].to_numpy() & m[[f"raw_odd_{s}" for s in "hda"]].isna().to_numpy()).any(axis=1)
ozet["genel"] = {
    "n_mac": int(n),
    "1x2_uc_oran_tam": int(one.sum()), "1x2_uc_oran_tam_pay": float(one.mean()),
    "1x2_en_az_bir_oran": int(anyo.sum()),
    "1x2_ham_var_ama_gecersiz_(<=1_veya_>=1000)_satir": int(odd_invalid.sum()),
    "max_ham_uc_oran_tam": int(mx_raw.sum()), "max_ham_uc_oran_tam_pay": float(mx_raw.mean()),
    "omax_uc_oran_tam_(doldurma_sonrasi)": int(mx.sum()),
    "omax_en_az_bir_taraf_Odd_ile_doldurulmus_satir": int(mx_fill.sum()),
    "ou25_iki_oran_tam": int(ou.sum()), "ou25_iki_oran_tam_pay": float(ou.mean()),
    "ou25_max_ham_tam": int(ou_mx_raw.sum()),
    "omax_ou25_ham_Over/Under_ile_doldurulmus_satir": int(ou_fill.sum()),
    "ps_oc_dolu_satir": int(m[["ps_h", "oc_h"]].notna().any(axis=1).sum()),
}
# Odd <= Max tutarlılığı (Max'ın Bet365'i içerip içermediğine dair dolaylı, yalnızca oran kontrolü)
both = m[[f"raw_odd_{s}" for s in "hda"] + [f"raw_max_{s}" for s in "hda"]].notna().all(axis=1)
viol = np.zeros(n, dtype=bool)
for s in "hda":
    viol |= (m[f"raw_odd_{s}"] > m[f"raw_max_{s}"] + 1e-9).to_numpy() & both.to_numpy()
ozet["odd_gt_max_satir"] = {"iki_taraf_da_var": int(both.sum()), "Odd>Max_en_az_bir_secim": int(viol.sum())}

# --- 3) lig-sezon ve dönem kapsamı
sy = np.where(m["date"].dt.month >= 7, m["date"].dt.year, m["date"].dt.year - 1)
m["season_year"] = sy
m["donem"] = [C.period_of(int(y)) or "donem_disi" for y in sy]
m["_1x2"] = one; m["_maxraw"] = mx_raw; m["_maxfill"] = mx_fill; m["_ou"] = ou; m["_ouraw"] = ou_mx_raw
m["_marj"] = 1 / m["o_h"] + 1 / m["o_d"] + 1 / m["o_a"]


def agg(g):
    return pd.Series({
        "n_mac": len(g), "ilk_tarih": g["date"].min().date().isoformat(), "son_tarih": g["date"].max().date().isoformat(),
        "n_1x2_tam": int(g["_1x2"].sum()), "pay_1x2_tam": round(float(g["_1x2"].mean()), 6),
        "n_max_ham_tam": int(g["_maxraw"].sum()), "pay_max_ham_tam": round(float(g["_maxraw"].mean()), 6),
        "n_omax_Odd_ile_doldurulan": int(g["_maxfill"].sum()),
        "n_ou25_tam": int(g["_ou"].sum()), "pay_ou25_tam": round(float(g["_ou"].mean()), 6),
        "n_ou25_max_ham_tam": int(g["_ouraw"].sum()),
        "medyan_1x2_marj": round(float(g["_marj"].median()), 4) if g["_marj"].notna().any() else np.nan,
    })


ls = m.groupby(["league", "season"], sort=True).apply(agg, include_groups=False).reset_index()
ls.to_csv(OUT / "oran_kapsam.csv", index=False)
dn = m.groupby("donem").apply(agg, include_groups=False).reset_index()
dn.to_csv(OUT / "oran_kapsam_donem.csv", index=False)
sy_t = m.groupby("season_year").apply(agg, include_groups=False).reset_index()
sy_t.to_csv(OUT / "oran_kapsam_sezon_yili.csv", index=False)
ozet["donem"] = dn.set_index("donem")[["n_mac", "n_1x2_tam", "pay_1x2_tam", "n_max_ham_tam", "pay_max_ham_tam",
                                         "n_omax_Odd_ile_doldurulan", "n_ou25_tam", "pay_ou25_tam"]].to_dict(orient="index")
ozet["lig_sezon_sayisi"] = int(len(ls))
ozet["lig_sezon_1x2_pay_lt_0.95"] = ls.loc[ls["pay_1x2_tam"] < 0.95, ["league", "season", "n_mac", "pay_1x2_tam"]].to_dict(orient="records")
ozet["lig_sezon_1x2_sifir"] = int((ls["n_1x2_tam"] == 0).sum())
ozet["lig_sezon_ou25_sifir"] = int((ls["n_ou25_tam"] == 0).sum())
ozet["lig_sezon_maxham_sifir"] = int((ls["n_max_ham_tam"] == 0).sum())
ozet["max_ham_ilk_sezon_yili"] = int(m.loc[m["_maxraw"], "season_year"].min())
ozet["ou25_ilk_sezon_yili"] = int(m.loc[m["_ou"], "season_year"].min())
ozet["1x2_ilk_sezon_yili"] = int(m.loc[m["_1x2"], "season_year"].min())
(OUT / "oran_kapsam_ozet.json").write_text(json.dumps(ozet, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: v for k, v in ozet.items() if k not in ("ham_sutunlar", "lig_sezon_1x2_pay_lt_0.95")}, ensure_ascii=False, indent=1, default=str))
print("pay<0.95 lig-sezon:", len(ozet["lig_sezon_1x2_pay_lt_0.95"]))

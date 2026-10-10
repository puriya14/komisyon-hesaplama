"""Adım 2–3: lig_sezon_kapsam.csv (lig-sezon başına kapsam) + lig_ozet.csv (lig başına tam sezon sayısı).

Beklenen maç sayısı PROJENİN KENDİ TÜRETİLMİŞ format kuralıdır (timeline._coverage_flags, satır 177-196):
takım başına normal sezon = REGULAR_LEN_OVERRIDE.get(lig, 2(n−1)); lig-sezon toplam = n × reg / 2
(çift devre için n(n−1)). Resmî fikstür listesi DEĞİLDİR.
"""
import json
import numpy as np, pandas as pd
from ortak import OUT, build_tm
from bahis_tahmin.sequences import timeline as T
from bahis_tahmin.goals.markets import frame_issues

m, tm = build_tm()
cov = T.coverage_report(tm).set_index(["league", "season"])

# --- maç düzeyi bayraklar (ham tablo) ---
hh, ha, fh, fa = (m[c].to_numpy(dtype=float) for c in ("hthg", "htag", "fthg", "ftag"))
ht_any_missing = np.isnan(hh) | np.isnan(ha)
ht_partial = np.isnan(hh) ^ np.isnan(ha)
neg = (hh < 0) | (ha < 0) | (fh < 0) | (fa < 0)
nonint = ((~np.isnan(hh)) & (hh % 1 != 0)) | ((~np.isnan(ha)) & (ha % 1 != 0))
ht_gt_ft = (~ht_any_missing) & ((hh > fh) | (ha > fa))
contradictory = ht_gt_ft | neg | nonint
valid_ht = (~ht_any_missing) & ~contradictory
issues = frame_issues(m)
aw = T.possible_awarded(m)
aw_s = T.possible_awarded(m, sensitive=True)
m = m.assign(_valid_ht=valid_ht, _ht_missing=ht_any_missing, _ht_partial=ht_partial, _contra=contradictory,
             _ht_gt_ft=ht_gt_ft, _neg=neg, _aw=aw, _aw_s=aw_s, _issue=(issues != "").to_numpy(),
             _sy=T.season_year(m["date"]))
m["_label_sy"] = pd.to_numeric(m["season"].astype(str).str[:4])
m["_dup"] = m.duplicated(["league", "date", "home", "away"])

# --- takım-maç tablosundan lig-sezon başına: kanonik takım, normal sezon maçları, takım başı min/max ---
reg_rows = tm[~tm["ust_tur"]]
per_team = reg_rows.groupby(["league", "season", "team"]).size()
tmin = per_team.groupby(["league", "season"]).min()
tmax = per_team.groupby(["league", "season"]).max()
ust_pairs = tm[tm["ust_tur"]].groupby(["league", "season"])["pair_id"].nunique()
reg_pairs = reg_rows.groupby(["league", "season"])["pair_id"].nunique()
n_raw = pd.concat([m[["league", "season", "home"]].rename(columns={"home": "t"}),
                   m[["league", "season", "away"]].rename(columns={"away": "t"})]).groupby(["league", "season"])["t"].nunique()

# --- format uyarıları (proje kuralının dayanağı / şüpheli durumlar) ---
SHORT = T.SHORTENED_SEASONS

def kaynak(lg, n):
    if lg == "SC0":
        return "türetilmiş kural: REGULAR_LEN_OVERRIDE SC0=33 maç/takım (12 takım × 3 devre; 33. haftadan sonraki bölünme turu UST_TUR)"
    if lg in ("SC1", "SC2", "SC3"):
        return f"türetilmiş kural: REGULAR_LEN_OVERRIDE {lg}=36 maç/takım (10 takım × 4 devre varsayımı; n'den bağımsız)"
    return "türetilmiş kural: çift devre, takım başı 2(n−1), toplam n(n−1)"

rows = []
for (lg, se), g in m.groupby(["league", "season"], sort=True):
    c = cov.loc[(lg, se)]
    n = int(c["takim"]); reg = float(c["normal_sezon_mac"])
    exp = n * reg / 2
    uy = []
    if lg == "SC0":
        uy.append("SPLIT: 33 maç sonra üst/alt grup (5 maç) — kural yalnızca normal sezonu sayar")
    if lg in ("SC1", "SC2", "SC3") and n != 10:
        uy.append(f"KURAL_SUPHELI: {lg} sabit 36 maç/takım ama kanonik takım sayısı {n}≠10")
    if lg in ("SC1", "SC2", "SC3"):
        uy.append("4 devreli lig: kural 10 takım varsayar")
    if lg in ("B1", "G1"):
        uy.append("PLAYOFF/GRUP TURU olan lig: normal sezonu aşan maçlar UST_TUR; normal sezon uzunluğu 2(n−1) varsayımı")
    if int(ust_pairs.get((lg, se), 0)) > 0:
        uy.append(f"UST_TUR maç {int(ust_pairs.get((lg, se), 0))}")
    if n % 2 == 1:
        uy.append(f"tek sayıda kanonik takım (n={n}): bay haftası veya ad/eşleme sorunu olabilir")
    if n != int(n_raw.get((lg, se))):
        uy.append(f"ham ad sayısı {int(n_raw.get((lg, se)))} ≠ kanonik {n} (sezon ortası ad ayrılması eşlendi)")
    if (lg, se) in SHORT:
        uy.append("SHORTENED_SEASONS (COVID) listesinde: tamlık eşiği %60")
    mn, mx = int(tmin.get((lg, se), 0)), int(tmax.get((lg, se), 0))
    if bool(c["tam"]) and not bool(c["devam_ediyor"]) and mx - mn > 0:
        uy.append(f"tam sayılan sezonda takım başı normal maç {mn}–{mx} (eşit değil)")
    if mx > reg:
        uy.append("takım başı maç > kural (imkânsız; kontrol)")
    if bool(c["devam_ediyor"]):
        durum = "DEVAM_EDEN_TAM" if bool(c["tam"]) else "DEVAM_EDEN_KISMI"
    elif bool(c["kisaltilmis"]):
        durum = "KISALTILMIS_TAM" if bool(c["tam"]) else "KISALTILMIS_KISMI"
    else:
        durum = "TAM" if bool(c["tam"]) else "KISMI"
    rows.append({
        "league": lg, "season": se, "season_year_etiket": int(g["_label_sy"].iloc[0]),
        "season_year_tarih_min": int(g["_sy"].min()), "season_year_tarih_max": int(g["_sy"].max()),
        "takim_kanonik_n": n, "takim_ham_n": int(n_raw.get((lg, se))),
        "kural_takim_basi_normal_mac": int(reg), "beklenen_normal_sezon_mac": exp,
        "beklenen_kaynagi": kaynak(lg, n) + " — RESMÎ FİKSTÜR LİSTESİ DEĞİL",
        "format_uyarisi": " | ".join(uy),
        "bulunan_mac_tekil": int((~g["_dup"]).sum()), "ham_satir": int(len(g)),
        "bulunan_normal_sezon_mac": int(reg_pairs.get((lg, se), 0)), "ust_tur_mac": int(ust_pairs.get((lg, se), 0)),
        "gecerli_iy": int(g["_valid_ht"].sum()), "eksik_iy": int(g["_ht_missing"].sum()),
        "eksik_iy_tek_taraf": int(g["_ht_partial"].sum()),
        "celiskili": int(g["_contra"].sum()), "celiskili_iy_gt_ms": int(g["_ht_gt_ft"].sum()), "negatif": int(g["_neg"].sum()),
        "frame_issues_dolu": int(g["_issue"].sum()),
        "hukmen_olabilir": int(g["_aw"].sum()), "hukmen_olabilir_duyarli": int(g["_aw_s"].sum()),
        "ilk_tarih": str(g["date"].min().date()), "son_tarih": str(g["date"].max().date()),
        "takim_basi_normal_min": mn, "takim_basi_normal_max": mx,
        "pay_season_share": round(float(c["pay"]), 4), "tam_season_complete": bool(c["tam"]),
        "devam_ediyor": bool(c["devam_ediyor"]), "kisaltilmis": bool(c["kisaltilmis"]),
        "eksik_normal_mac_kurala_gore": exp - int(reg_pairs.get((lg, se), 0)),
        "durum": durum,
    })
df = pd.DataFrame(rows)
# Denetçi notları (veriden türetilmiş; dış resmî kaynakla doğrulanmadı)
NOTES = {
    ("SC1", "2004/05"): "Eşleme kaçağı: 'Raith' (1 maç, 2004-11-23 Ross County–Raith) 'Raith Rvs' ile birleşmedi → kanonik n=11; 10 takımla beklenen 180, bulunan 164 (pay 0.911, yine KISMI).",
    ("EC", "2020/21"): "Dover Athletic 15 maç, diğerleri 42–43: sezon içi çekilme/ihraç olasılığı; n(n−1) kuralı bu sezonda şüpheli (dış kaynakla doğrulanmadı).",
    ("G1", "2024/25"): "Veri 2024-11-22'de başlıyor; hiçbir takım 26'yı aşmadığı için olası play-off maçları normal sezon sayıldı (UST_TUR=0).",
    ("EC", "2024/25"): "Veri 2024-10-23'te bitiyor (takım başı 15 maç).",
    ("SC0", "2007/08"): "228/228 maç mevcut; takım-sezon 'eksiği' UST_TUR karışık sınıflamasından (erteleme) — gerçek veri boşluğu değil.",
    ("SC0", "2010/11"): "228/228 maç mevcut; takım-sezon 'eksiği' UST_TUR karışık sınıflamasından — gerçek veri boşluğu değil.",
    ("SC0", "2014/15"): "228/228 maç mevcut; takım-sezon 'eksiği' UST_TUR karışık sınıflamasından — gerçek veri boşluğu değil.",
    ("SC0", "2024/25"): "Toplam 200 maç (beklenen 228): bölünme turunun büyük kısmı yok; kural UST_TUR tamlığını denetlemediği için TAM sayıldı.",
    ("T1", "2022/23"): "29 hükmen olabilir satır (İY yok, 3-0/0-3).",
    ("G1", "2014/15"): "22 hükmen olabilir satır (İY yok, 3-0/0-3).",
    ("SP2", "2018/19"): "21 satırda İY eksik (hükmen skoru değil).",
}
def _note(r):
    n = NOTES.get((r["league"], r["season"]), "")
    if r["league"] == "B1" and r["ust_tur_mac"] == 0 and 2009 <= r["season_year_etiket"] <= 2025:
        n = (n + " " if n else "") + "Play-off/üst tur maçı veride yok (UST_TUR=0); normal sezon olarak değerlendirildi (dış kaynakla doğrulanmadı)."
    if r["league"] == "G1" and r["ust_tur_mac"] == 0 and r["season"] not in ("2024/25", "2026/27"):
        n = (n + " " if n else "") + "Üst tur maçı veride yok (UST_TUR=0); dış kaynakla doğrulanmadı."
    return n
df["denetci_notu"] = df.apply(_note, axis=1)
df.to_csv(f"{OUT}/lig_sezon_kapsam.csv", index=False)

# --- Adım 3: lig başına özet ---
lo = []
for lg, g in df.groupby("league"):
    g = g.sort_values("season")
    full_hist = g[(g["season_year_etiket"] <= 2025)]
    lo.append({"league": lg, "ilk_sezon": g["season"].iloc[0], "son_sezon": g["season"].iloc[-1],
               "sezon_etiketi_sayisi": len(g),
               "sezon_2000_01_2025_26_mevcut": int(len(full_hist)),
               "tam_2000_01_2025_26": int(full_hist["tam_season_complete"].sum()),
               "kismi_2000_01_2025_26": int((~full_hist["tam_season_complete"]).sum()),
               "kisaltilmis_tam": int((full_hist["durum"] == "KISALTILMIS_TAM").sum()),
               "eksik_sezon_etiketi_2000_01_2025_26": 26 - int(len(full_hist)),
               "kismi_sezonlar": ",".join(full_hist.loc[~full_hist["tam_season_complete"], "season"]),
               "eksik_etiketler": ",".join(sorted(set(f"{y}/{(y + 1) % 100:02d}" for y in range(2000, 2026)) - set(full_hist["season"]))),
               "sezon_2026_27": (g.loc[g["season"] == "2026/27", "durum"].iloc[0] if (g["season"] == "2026/27").any() else "YOK"),
               "toplam_mac": int(g["bulunan_mac_tekil"].sum())})
lo = pd.DataFrame(lo)
lo.to_csv(f"{OUT}/lig_ozet.csv", index=False)

ozet = {
    "lig_sezon": int(len(df)), "tam_degil": int((~df["tam_season_complete"]).sum()),
    "durum_sayilari": df["durum"].value_counts().to_dict(),
    "hukmen_olabilir_toplam": int(df["hukmen_olabilir"].sum()), "tm_attrs_n_awarded": int(tm.attrs["n_awarded"]),
    "hukmen_olabilir_duyarli_toplam": int(df["hukmen_olabilir_duyarli"].sum()),
    "eksik_iy_toplam": int(df["eksik_iy"].sum()), "eksik_iy_tek_taraf": int(df["eksik_iy_tek_taraf"].sum()),
    "celiskili_toplam": int(df["celiskili"].sum()), "gecerli_iy_toplam": int(df["gecerli_iy"].sum()),
    "frame_issues_dolu_toplam": int(df["frame_issues_dolu"].sum()),
    "tekil_mac_toplam": int(df["bulunan_mac_tekil"].sum()), "ust_tur_mac_toplam": int(df["ust_tur_mac"].sum()),
    "etiket_tarih_sezon_uyumsuz_satir": int((m["_label_sy"] != m["_sy"]).sum()),
    "tam_sezon_toplam_2000_2025": int(lo["tam_2000_01_2025_26"].sum()),
    "olasi_lig_sezon_2000_2025": 22 * 26,
    "mevcut_lig_sezon_2000_2025": int(lo["sezon_2000_01_2025_26_mevcut"].sum()),
    "2026_27": df.loc[df["season"] == "2026/27", "durum"].value_counts().to_dict(),
    "tum_ligler_tam_sezon_dagilimi": lo.set_index("league")["tam_2000_01_2025_26"].to_dict(),
    "intra_season_splits": tm.attrs["intra_season_splits"],
}
json.dump(ozet, open(f"{OUT}/s2_ozet.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(ozet, ensure_ascii=False, indent=1))
print(lo.to_string())

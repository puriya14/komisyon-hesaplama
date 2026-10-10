"""uzlastirma.py çıktılarından okunabilir Markdown tabloları (adaylar.md, yeniden_ornekleme.md, mde_hedef_ozet.md)
ve iddia_kontrolleri.csv üretir. Yalnızca <OUT> içindeki CSV/JSON'u ve 01b7e9f arşivindeki yayımlanmış raporları okur.

Çalıştırma:  PYTHONDONTWRITEBYTECODE=1 /home/user/venv-bahis/bin/python -I tablolar_md.py <OUT>
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(sys.argv[1])
K = OUT / "kod" / "bahis-tahmin"
J = json.loads((K / "reports" / "dizi_sonuclar.json").read_text(encoding="utf-8"))
NUM = json.loads((OUT / "hesap_ciktisi.json").read_text(encoding="utf-8"))
AD = pd.read_csv(OUT / "adaylar.csv")
SEL = pd.read_csv(OUT / "aday_secimi_yeniden.csv")
MT = pd.read_csv(OUT / "coklu_test_dll.csv")
MAG = pd.read_csv(OUT / "buyukluk.csv")
MS = pd.read_csv(OUT / "mde_hedef_ozet.csv")
ZC = pd.read_csv(OUT / "zcrit.csv")
RM = pd.read_csv(OUT / "yeniden_ornekleme.csv")
CP = pd.read_csv(OUT / "cp_esikler.csv")


def f(x, nd=3, sign=False):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if not math.isfinite(v):
        return "–"
    s = f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"
    return s.replace("-", "−").replace(".", ",")


def hid(h: str) -> str:
    """Tablo hücresinde hipotez kimliği (GFM: hücre içindeki | kaçışlanır)."""
    return "`" + h.replace("|", "\\|") + "`"


def e(x, nd=6):
    return f(x, nd, sign=True)


L = []
L.append("# F1 adayları ve EXPLORATORY WY-anlamlı hipotezler — sayısal uzlaştırma (taban 01b7e9f)\n")
L.append("Kaynak: `reports/dizi_sonuclar.json` (aileler.F1.adaylar, aileler.F1.baglam_tanilama), "
         "`reports/dizi_f1_hipotezler.csv`; girdi SHA-256: "
         + ", ".join(f"`{k}` {v[:12]}…" for k, v in NUM["girdi_sha256"].items())
         + ". Üretim: `uzlastirma.py` + `tablolar_md.py` (yalnızca yayımlanmış sayılar üzerinde aritmetik; maç verisi "
           "açılmadı). Tam sütunlar: `adaylar.csv`.\n")
L.append("## Tanımlar (koddan)\n")
L.append("- **Referans / beklenen:** E_adj = Σ_{i∈koşul} p0_i · r_s, r_s = O_s/E_s; katman s = taraf × lig × hedefe özgü "
         "kalibre S0 p0 beşlisi, değerlendirilen dönem maskesi içinde (patterns.py:3-9, 279). O/E = O/E_adj; %95 aralık "
         "O/E ± 1,96·√V/E_adj (patterns.py:315-319); V = CR1 lig-sezon kümeli (patterns.py:283-286); z = (O−E_adj)/√V. "
         "\"E ham S0\" = Σ p0_i (katman yeniden kalibrasyonu yok).")
L.append("- **Çoklu test:** keşifte Westfall–Young adım adım azalan maxT (|z|, iki yönlü), R = 1000, "
         "p_adj = (c+1)/(R+1), Monte Carlo %99 Clopper–Pearson aralığı c/R üzerinde (null.py:181-214); keşif kuralı "
         "destekli ∧ p_adj < 0,05 ∧ MC üst < 0,05 (research.py:479). Parametre ve testte ön-kayıtlı yönde tek yönlü normal "
         "p ve Holm, k = 4 (patterns.py:784-796; research.py:499, 508).")
L.append("- **ΔLL işareti:** ΔLL = aday_log_kayıp − referans_log_kayıp = ortalama[LL(S0 + sabit + gösterge)] − "
         "ortalama[LL(S0 + sabit)]; **negatif = aday daha iyi**. İki model de S0 logit offset'li lojistik; aynı eğitim "
         "satırlarında (keşif ∪ parametre maskesi ∧ atomlar tanımlı ∧ hedef ve p0 sonlu ∧ maç günü + 1 < 2019-07-01; "
         "son eğitim tarihi 2019-06-09) uyumlanır; gösterge modeli λ = 0 (cezasız), referans λ = ∞ (yalnız offset + "
         "sabit). Değerlendirme: test maskesinde atomların tanımlı olduğu TÜM satırlar (yalnız koşul satırları değil), "
         "nats/satır (research.py:386-419; models.py:168-188). Gösterge ham 0/1 (ortalama 0, std 1 → β doğrudan "
         "log-odds). Aralık: lig-sezon kümeli yüzdelik bootstrap, 1000 tekrar, tohum 20261010; p_tek = Φ(ΔLL/se_boot); "
         "duyarlılık: ISO-hafta kümeleri; ayrıca ham S0'a göre fark.")
L.append("- **Statü sırası (research.py:555-574):** parametre Holm → test Holm → test ΔLL üst sınır < 0 → (parametre: "
         "7b/1–4, 7b/5) → (test: 7b/1–4, 7b/5). Kayıtlı gerekçe İLK başarısız kontroldür; aşağıda tüm başarısızlar da "
         "listelenir.\n")

L.append("## Tablo A — sekiz WY-anlamlı tekil hipotez (keşif 2006/07–2012/13)\n")
L.append("| # | Hipotez (hedef \\| koşul) | Rol | Düz anlatım | n | O (olay) | E_adj | E ham S0 | O/E [%95] | z | "
         "WY p_adj (c/1000) [MC %99] | Statü |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
for i, r in AD.iterrows():
    L.append(f"| {i + 1} | {hid(r['hyp_id'])} | {r['rol']} | {r['tanim']} | {int(r['kesif_n'])} | {int(r['kesif_olay_O'])} | "
             f"{f(r['kesif_E_adj'], 1)} | {f(r['kesif_E_ham_S0'], 1)} | {f(r['kesif_OE'])} [{f(r['kesif_OE_lo95'])}; "
             f"{f(r['kesif_OE_hi95'])}] | {f(r['kesif_z'], 2, True)} | {f(r['wy_p_adj'], 4)} ({int(r['wy_c_sayim'])}) "
             f"[{f(r['wy_mc99_lo'], 4)}; {f(r['wy_mc99_hi'], 4)}] | {r['statu']} |")
L.append("\nAtom tanımlarının kod satırları: " + "; ".join(sorted({x for t in AD["tanim_kod"] for x in t.split("; ")}))
         + ".\n")
L.append("EXPLORATORY dört hipotez için parametre/test dönemi n, olay sayısı, ΔLL ve 7b kayıtları **yayımlanmış "
         "kayıtlarda yok** (örneklem dışı değerlendirilmediler; research.py:496-519 yalnızca adaylara uygulanır). "
         "Bu değerler maç verisi açılmadan üretilemez → DOGRULANAMADI/uygulanmadı.\n")

L.append("## Tablo B — dört aday: dönem başına sayım, etki ve çoklu test\n")
L.append("| Aday | Dönem | n | O (olay) | E_adj | O/E [%95] | z | p_tek (yön) | p_Holm (k=4) | Holm geçti | "
         "7b 1–5 (G=geçti, K=kaldı) | 7b/2 O/E [%95] | 7b/3 aynı yön | 7b/5 S0p O/E [%95] |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for _, r in AD.iloc[:4].iterrows():
    L.append(f"| {hid(r['hyp_id'])} | keşif | {int(r['kesif_n'])} | {int(r['kesif_olay_O'])} | {f(r['kesif_E_adj'], 1)} | "
             f"{f(r['kesif_OE'])} [{f(r['kesif_OE_lo95'])}; {f(r['kesif_OE_hi95'])}] | {f(r['kesif_z'], 2, True)} | "
             f"WY {f(r['wy_p_adj'], 4)} | – | – | – | – | – | – |")
    for per in ("parametre", "test"):
        L.append(f"| | {per} | {int(float(r[per + '_n']))} | {int(float(r[per + '_olay_O']))} | {f(r[per + '_E_adj'], 1)} | "
                 f"{f(r[per + '_OE'])} [{f(r[per + '_OE_lo95'])}; {f(r[per + '_OE_hi95'])}] | {f(r[per + '_z'], 2, True)} | "
                 f"{f(r[per + '_p_tek'], 5)} | {f(r[per + '_p_holm_k4'], 5)} | {'evet' if r[per + '_holm_gecti'] else 'hayır'} | "
                 f"{r['7b_' + per]} | {r['7b2_' + per + '_OE_aralik'].replace('.', ',')} | {r['7b3_' + per + '_pay']} | "
                 f"{r['7b5_' + per + '_S0p_OE_aralik'].replace('.', ',')} |")
L.append("")
L.append("Keşif→test log(O/E) oranı (küçülme; aritmetik): "
         + "; ".join(f"`{r['hyp_id']}` {f(math.log(r['test_OE']) / math.log(r['kesif_OE']), 2)}" for _, r in AD.iloc[:4].iterrows())
         + " (1 = küçülme yok). Seçilen etkiler keşif MDE'sine yakın olduğundan (bkz. `hesap_ciktisi.json` "
           "aday_gozlenen_vs_mde80) örneklem dışı küçülme beklenir.\n")

L.append("## Tablo C — test dönemi ΔLL (S0 + sabit + gösterge − S0 + sabit), 2019/20–2025/26\n")
L.append("| Aday | β gösterge (log-odds) | sabit (gösterge / ref) | n eğitim | n test (koşul) | LL S0+sabit | "
         "ΔLL [boot %95] | p_tek | p_boot | ISO-hafta [%95] (p_tek) | ham S0'a göre ΔLL [%95] | Holm k=4 (p_tek) | "
         "Bonferroni k=4 |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
mt = MT[MT["p_turu"].str.startswith("p_tek_normal")].set_index("hyp_id")
for _, r in AD.iloc[:4].iterrows():
    h = r["hyp_id"]
    L.append(f"| {hid(h)} | {f(r['beta_gosterge_logodds'], 4, True)} | {f(r['sabit_gosterge_modeli'], 4, True)} / "
             f"{f(r['sabit_S0_sabit_modeli'], 4, True)} | {int(r['ll_egitim_n'])} | {int(r['ll_test_n'])} "
             f"({int(r['ll_test_kosul_n'])}) | {f(r['ll_S0_sabit'], 6)} | {e(r['dLL_aday_eksi_ref'])} "
             f"[{e(r['dLL_boot95_lo'])}; {e(r['dLL_boot95_hi'])}] | {f(r['dLL_p_tek_normal'], 4)} | "
             f"{f(r['dLL_p_boot'], 4)} | [{e(r['dLL_isohafta95_lo'])}; {e(r['dLL_isohafta95_hi'])}] "
             f"({f(r['dLL_isohafta_p_tek'], 4)}) | {e(r['dLL_hamS0_fark'])} [{e(r['dLL_hamS0_lo'])}; "
             f"{e(r['dLL_hamS0_hi'])}] | {f(mt.at[h, 'holm_k4'], 4)} | {f(mt.at[h, 'bonferroni_k4'], 4)} |")
d = NUM["dLL"]
L.append(f"\nÖzet: ΔLL ortalama {e(d['ortalama'])}, ortanca {e(d['ortanca'])}, aralık [{e(d['min'])}; {e(d['max'])}]; "
         f"sıfırı içeren bootstrap aralığı {d['ci_sifiri_iceren']}/4 (ilk üç aday). Göreli iyileşme "
         + ", ".join(f(x, 4) for x in d["goreli_iyilesme_yuzde"]) + " % (−ΔLL / LL(S0+sabit)). "
         "Yalnız `GALIBIYET|RAKIP_SON5_IY_ONDE_EN_AZ_3` aralığı sıfırı dışlar; bu aralık aday başına (çoklu "
         "düzeltmesiz) bootstrap'tır; 4 test adayı üzerinde Holm/Bonferroni p = "
         f"{f(mt.at['GALIBIYET|RAKIP_SON5_IY_ONDE_EN_AZ_3', 'holm_k4'], 4)} (> 0,05; p_boot ile 0,0719, ISO-hafta ile 0,0648, "
         "ham S0'a göre 0,0962).\n")

L.append("## Tablo D — statü ve neden\n")
L.append("| Hipotez | Statü | Kayıtlı gerekçe (ilk başarısız) | Tüm başarısız kontroller / aday seçimi |")
L.append("|---|---|---|---|")
for _, r in AD.iterrows():
    extra = r["tum_basarisiz_kontroller"] if r["rol"].startswith("ADAY") else str(r["aday_secimi"]).replace("|", "\\|")
    L.append(f"| {hid(r['hyp_id'])} | {r['statu']} | {r['gerekce_kayitli_ilk_basarisiz']} | {extra} |")
L.append("")
L.append("## Tablo E — aday seçiminin yayımlanmış sayılarla yeniden kurulumu (patterns.select_candidates)\n")
L.append("| LCB sırası | Hipotez | LCB(\\|log O/E\\|) | Çift kuralı | Ayrıntı | Sonuç |")
L.append("|---|---|---|---|---|---|")
for _, r in SEL.iterrows():
    r = r.copy()
    r["secim_sonucu"] = str(r["secim_sonucu"]).replace("|", "\\|")
    L.append(f"| {r['lcb_sira']} | {hid(r['hyp_id'])} | {f(r['lcb'], 4)} | {'geçti' if r['pair_ok'] else 'kaldı'} | "
             f"{str(r['pair_note']).replace('.', ',').replace('-0', '−0')} | {r['secim_sonucu']} |")
L.append("\nNot: `EV_SAHIBI` tek başına O/E'si katmanlama (taraf) nedeniyle tam 1,000'dır (baglam_tanilama); "
         "çift kuralı `s == 0` dalında koşulsuz geçilir (patterns.py:757). Yeniden kurulan seçim yayımlanan sıra "
         "1–4 ile birebir aynı; EXPLORATORY dördünün hepsi çift kuralını geçiyor ve **aynı hedefte ortak atom** kuralıyla "
         "(5'lik sınır değil) elendi.\n")
(OUT / "adaylar.md").write_text("\n".join(L), encoding="utf-8")

# ----------------------------------------------------------------------------
R2 = ["# Yeniden örnekleme sayıları ve p-değeri formülü (taban 01b7e9f)\n",
      "| Kavram | Değer | Kod (dosya:satır) | Manifest / sonuç alanı | Not |", "|---|---|---|---|---|"]
for _, r in RM.iterrows():
    r = r.map(lambda v: v.replace("|", "\\|") if isinstance(v, str) else v)
    R2.append(f"| {r['kavram']} | {r['deger']} | {r['kod']} | {r['manifest']} | {'' if pd.isna(r['not']) else r['not']} |")
R2.append("\n## Clopper–Pearson eşikleri (cp_esikler.csv)\n")
R2.append("| R | en büyük c (CP %99 üst < 0,05) | CP üst(c) | CP üst(c+1) | karşılık gelen p_adj | en büyük c (p_adj < 0,05) "
          "| en küçük p_adj |")
R2.append("|---|---|---|---|---|---|---|")
for _, r in CP.iterrows():
    R2.append(f"| {int(r['R'])} | {int(r['en_buyuk_c_CP99_ust<0,05'])} | {f(r['CP99_ust(cmax)'], 4)} | "
              f"{f(r['CP99_ust(cmax+1)'], 4)} | {f(r['p_adj(cmax)=(c+1)/(R+1)'], 5)} | {int(r['en_buyuk_c_p_adj<0,05'])} | "
              f"{f(r['min_p_adj=1/(R+1)'], 6)} |")
(OUT / "yeniden_ornekleme.md").write_text("\n".join(R2) + "\n", encoding="utf-8")

# ----------------------------------------------------------------------------
zc = float(ZC.iloc[0]["z_crit"])
M3 = [f"# Keşif dönemi MDE (desteklenen tekil F1 hipotezleri, n = 430)\n",
      f"MDE = 1 ± (z_crit + z_güç)·√V/E_adj; z_crit = {f(zc, 4)} (WY p_adj = 0,05 geçişi; sıra 8 |z| 4,2034 / p 0,02298 "
      f"ile sıra 9 |z| 3,8226 / p 0,08891 arasında log p doğrusal ara değer); z_güç = 0 (%50), 0,8416 (%80). "
      "V ve E_adj gözlenen keşif değerleridir (alternatif altındaki varyans değil). **Ön-kayıtlı bir pratik önem eşiği "
      "yoktur**; aşağıdaki sayılar yalnızca tespit edilebilirlik sınırıdır.\n",
      "| Hedef | tekil / destekli | E_adj ortanca | gözlenen en büyük \\|z\\| | %50 güç: min / ortanca / max göreli MDE | "
      "%80 güç: min / ortanca / max göreli MDE | %80 ortanca O/E sınırları | %80'de alt yön tespit edilemez |",
      "|---|---|---|---|---|---|---|---|"]
for _, r in MS.iterrows():
    M3.append(f"| {r['hedef']} | {int(r['tekil'])} / {int(r['desteklenen'])} | {f(r['E_adj_ortanca'], 1)} | "
              f"{f(r['max_abs_z_gozlenen'], 2)} | %{f(r['g50_min_%'], 1)} / %{f(r['g50_ortanca_%'], 1)} / %{f(r['g50_max_%'], 1)} | "
              f"%{f(r['g80_min_%'], 1)} / %{f(r['g80_ortanca_%'], 1)} / %{f(r['g80_max_%'], 1)} | "
              f"≤ {f(r['g80_OE_alt_ortanca'], 2)} veya ≥ {f(r['g80_OE_ust_ortanca'], 2)} | "
              f"{int(r['g80_alt_tarafta_tespit_edilemez_(mde>=1)'])} |")
M3.append("\nz_crit duyarlılığı (zcrit.csv): " + "; ".join(f"{r['yontem']}: {f(r['z_crit'], 4)}" for _, r in ZC.iterrows()
                                                          if math.isfinite(r['z_crit'])) + ".")
(OUT / "mde_hedef_ozet.md").write_text("\n".join(M3) + "\n", encoding="utf-8")
print("ok")

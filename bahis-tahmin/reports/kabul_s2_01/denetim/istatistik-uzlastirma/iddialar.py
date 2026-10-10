"""Önceki rapor ve sonuç belgesindeki istatistik iddialarını yayımlanmış kayıtlarla eşleştirir → iddia_kontrolleri.csv.

Yalnızca <OUT>/kod/bahis-tahmin/reports/* ve uzlastirma.py çıktısı (hesap_ciktisi.json) okunur.
Çalıştırma:  PYTHONDONTWRITEBYTECODE=1 /home/user/venv-bahis/bin/python -I iddialar.py <OUT>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

OUT = Path(sys.argv[1])
K = OUT / "kod" / "bahis-tahmin"
J = json.loads((K / "reports" / "dizi_sonuclar.json").read_text(encoding="utf-8"))
N = json.loads((OUT / "hesap_ciktisi.json").read_text(encoding="utf-8"))
F1, F4, F6, F7 = (J["aileler"][k] for k in ("F1", "F4", "F6", "F7"))
MAN = J["manifest"]
C = sorted(F1["adaylar"], key=lambda c: c["sira"])
c1 = C[0]
roi = [v["roi"] for per in ("parametre", "test") for t in ("GALIBIYET", "MAGLUBIYET")
       for s, v in F6[per]["hedefler"][t]["kaynaklar"].items() if s in ("S0", "S1", "S2")]
s0p_bets = [F6[per]["hedefler"][t]["kaynaklar"][s]["n_bahis"] for per in ("parametre", "test")
            for t in ("GALIBIYET", "MAGLUBIYET") for s in ("S0p", "Bet365_marjsiz")]
d = N["dLL"]
rows = [
    ("onceki_rapor.md madde 7", "Hiçbiri OUT_OF_SAMPLE_SUPPORTED almadı.", "DOGRULANDI",
     f"dizi_sonuclar.json aileler.F1.statu_sayilari={F1['statu_sayilari']}; adaylar[*].statu="
     f"{[c['statu'] for c in C]}"),
    ("onceki_rapor.md madde 7; SONUCLARI.md:8-9", "Keşifte 8 hipotez aile düzeltmesini geçti.", "DOGRULANDI",
     f"F1.wy_anlamli={F1['wy_anlamli']}; c (WY sayımı) = {sorted(N['wy_yeniden_uretim']['c_8_hipotez'].values())} ≤ 22 "
     f"(p_adj ≤ 0,02298); katı kural c ≤ 32 (cp_esikler.csv) → 8'i de katı anlamlı"),
    ("onceki_rapor.md madde 7; SONUCLARI.md:9", "4 adayın yönü parametre ve testte tekrar etti.", "DOGRULANDI",
     "tek yönlü Holm k=4: parametre p_holm=" + str([round(c['parametre']['p_holm'], 5) for c in C]) +
     "; test p_holm=" + str([round(c['test']['p_holm'], 5) for c in C]) + "; hepsi gecti=True"),
    ("onceki_rapor.md madde 7; SONUCLARI.md:9-10", "Dördünde de etki piyasa kontrolüne (S0p) girince kayboldu.",
     "DARALTILDI",
     "7b/5 dört adayda iki dönemde de passed=False (S0p offset O/E aralığı 1'i içeriyor: test "
     + str([round(c['yanlislama']['test']['checks']['5_piyasa']['lift'], 3) for c in C]) +
     "). Ancak kayıtlı statü gerekçesi İLK başarısız kontroldür (research.py:555-574): 3 adayda 'test ΔLL', "
     "1 adayda 'parametre 7b/1–4 (7b/2)'; hiçbirinin kayıtlı gerekçesi 7b/5 değil"),
    ("onceki_rapor.md madde 7; SONUCLARI.md:10-11", "Log-kayıp katkısı yaklaşık −0,00005.", "DARALTILDI",
     f"adaylar[*].gosterge.fark.diff = {[round(x, 7) for x in d['degerler']]}; ortalama {d['ortalama']:.3e}, ortanca "
     f"{d['ortanca']:.3e}, aralık [{d['min']:.3e}; {d['max']:.3e}]; −0,00005 yalnızca ortanca/üç aralığı sıfırı içeren "
     f"adayın ortalamasına ({d['ci_sifiri_icerenlerin_ortalamasi']:.3e}) yakın"),
    ("onceki_rapor.md madde 7; SONUCLARI.md:11", "Dördünden üçünde güven aralığı sıfırı içeriyor.", "DOGRULANDI",
     "fark.ci_lo/ci_hi: " + "; ".join(f"{c['hyp_id']} [{c['gosterge']['fark']['ci_lo']:.2e}; {c['gosterge']['fark']['ci_hi']:.2e}]"
                                      for c in C) + ". Dördüncü (GALIBIYET|RAKIP_SON5_IY_ONDE_EN_AZ_3) sıfırı dışlıyor; "
     "aday başına aralık, 4 aday üzerinde Holm p=0,0717"),
    ("onceki_rapor.md madde 9; SONUCLARI.md:65-67",
     "Son 5'te ≥4 galibiyet + favori: test 3.110 maçın 346'sı (%11,1) kayıp; S0 beklentisi ≈ %12,7.", "DARALTILDI",
     f"mod_b.test n_cond={c1['mod_b']['test']['n_cond']}, hits={c1['mod_b']['test']['hits']}, misses="
     f"{c1['mod_b']['test']['misses']}; 346/3110={346/3110:.4f}; E_adj/n={c1['test']['E_adj']/3110:.4f} (katman-yeniden "
     f"kalibre S0); ham S0 E_raw/n={c1['test']['E_raw']/3110:.4f}. %12,7 = E_adj; ham S0 beklentisi %13,0"),
    ("onceki_rapor.md madde 5", "Plasebo 20 tohum tam arama.", "DOGRULANDI",
     f"F7.n_seeds={F7['n_seeds']}, F7.R={F7['R']}; manifest.plasebo={MAN['plasebo']}"),
    ("onceki_rapor.md madde 14; SONUCLARI.md:35-36", "Plasebo 0/20 (geçti); en küçük düzeltilmiş p 0,17.", "DOGRULANDI",
     f"F7.n_seeds_with_discovery={F7['n_seeds_with_discovery']}, passed={F7['passed']}; min(min_p_adj)="
     f"{N['plasebo']['min_p_adj_en_kucuk']:.5f} (=34/201). Sınırlar plasebo_sinirlar.csv'de"),
    ("onceki_rapor.md madde 10; SONUCLARI.md:94-95", "Süre etkisi yok: p = 0,87 ve 0,98; medyan aralık 29 lig maçı.",
     "DOGRULANDI",
     f"F4.events.*.p_wald={[round(v['p_wald'], 4) for v in F4['events'].values()]}; km_summary.median_matches="
     f"{[v['km_summary']['median_matches'] for v in F4['events'].values()]}"),
    ("onceki_rapor.md madde 11; SONUCLARI.md:108-111",
     "1X2'de varsayımsal ROI −%6 ile −%13; piyasa kontrollü modeller eşiği geçen bahis bulmadı.", "DOGRULANDI",
     f"F6 S0/S1/S2 roi aralığı [{min(roi):.4f}; {max(roi):.4f}]; S0p ve Bet365_marjsiz n_bahis={sorted(set(s0p_bets))}"),
    ("SONUCLARI.md:29; research.py:15", "R = 1000 · 20 tohum × 200 · bootstrap 1000; tohum 20261010.", "DOGRULANDI",
     f"manifest.R={MAN['R']}, plasebo={MAN['plasebo']}, bootstrap={MAN['bootstrap']}, tohum={MAN['tohum']}; "
     "kod satırları yeniden_ornekleme.csv"),
    ("SONUCLARI.md:3", "Çalıştırma 37,5 dk, 3 işçi.", "DOGRULANDI",
     f"manifest.sure_sn={MAN['sure_sn']} (= {MAN['sure_sn'] / 60:.2f} dk), isci={MAN['isci']}"),
    ("SONUCLARI.md:40", "Kalibrasyon kapısı geçti (8 hedef × taraf hücresi).", "DOGRULANDI",
     f"F1.kalibrasyon_kapisi.gecti={F1['kalibrasyon_kapisi']['gecti']}; tablo satırı="
     f"{len(F1['kalibrasyon_kapisi']['tablo'])}, hepsi passed"),
    ("SONUCLARI.md:40-41", "780 tekil hipotezin 430'u asgari desteği sağladı.", "DOGRULANDI",
     f"F1.hipotez_tekil={F1['hipotez_tekil']}, desteklenen_tekil={F1['desteklenen_tekil']}"),
    ("SONUCLARI.md:41-42",
     "İY/MS geçiş hedeflerinde en büyük |z| 2,6 (referans süreçte rastgele en büyük |z|'nin medyanı 3,1).", "DARALTILDI",
     f"desteklenen (aile içi) tekil hipotezlerde max |z|: {N['iy_hedefleri_max_abs_z_desteklenen']}; desteklenmeyen "
     f"(aile dışı, O=0 küçük hücreler) dahil: {N['iy_hedefleri_max_abs_z_tum_tekil']}; ortanca 3,138 tüm F1 ailesinin "
     f"(4 hedef) tekrar başına max |z| ortancasıdır (F1.referans_ozeti); karar eşiği z_crit≈3,98 (zcrit.csv)"),
    ("SONUCLARI.md:46-53", "Sekiz WY-anlamlı hipotezin keşif O/E [%95], FWER p, statü tablosu.", "DOGRULANDI",
     "dizi_f1_hipotezler.csv lift/lift_lo/lift_hi/p_adj/statu ile yuvarlama düzeyinde birebir (adaylar.md Tablo A)"),
    ("SONUCLARI.md:55",
     "EXPLORATORY dördü aday kuralı nedeniyle (her hedefte aynı atomu paylaşanlardan yalnızca biri) sınanmadı.",
     "DOGRULANDI",
     "select_candidates yayımlanmış lift/aralıklarla yeniden kuruldu (aday_secimi_yeniden.csv): seçilen sıra yayımlananla "
     "aynı; 4 EXPLORATORY çift kuralını geçiyor, ortak-atom kuralıyla eleniyor; 5'lik sınıra ulaşılmadı (4 aday)"),
    ("dizi_f1_hipotezler.csv gerekce (EXPLORATORY satırları)",
     "'aday sınırı/çift kuralı nedeniyle örneklem dışı sınanmadı'", "DARALTILDI",
     "gerçek neden 'aynı hedefte ortak atom' kuralı (patterns.py:770-776); çift kuralı ve 5'lik sınır bağlayıcı değil"),
    ("SONUCLARI.md:60-63", "Aday dördünün örneklem dışı tablosu (O/E, Holm, ΔLL [aralık], S0p O/E, neden).",
     "DOGRULANDI",
     "adaylar.md Tablo B–D ile yuvarlama düzeyinde aynı (ör. ΔLL −0,00010 [−0,00020; −0,00001])"),
    ("SONUCLARI.md:9-11", "Log-kayıp katkısı ihmal edilebilir düzeyde.", "DARALTILDI",
     f"ön-kayıtlı bir 'ihmal edilebilir' eşiği yok; göreli iyileşme {[round(x, 4) for x in d['goreli_iyilesme_yuzde']]} % "
     "(−ΔLL/LL(S0+sabit)); ifade yargıdır, ölçüt değildir"),
    ("DIZI_ARASTIRMA_SOZLESMESI.md §9 OUT_OF_SAMPLE_SUPPORTED satırı",
     "Testte S0 + gösterge log-kaybı S0'dan anlamlı düşük.", "BILGI",
     "kod S0 + sabit ile karşılaştırır (research.py:563; RUN_DECISIONS['aday_test'] ön-kayıtlı); ham S0'a göre fark da "
     "raporlanır (fark_ham_s0). İki karşılaştırma 4 adayda aynı sonucu verir (yalnız 4. adayda ikisi de sıfırı dışlar)"),
    ("onceki_rapor.md kısa cevap; SONUCLARI.md:12-13",
     "İY/MS 2/1 tipi geri dönüşler (ve önde kapatıp kaybetme) için anlamlı bir öncü koşul çıkmadı.", "DARALTILDI",
     "doğru (desteklenen max |z| " + str({k: round(v, 3) for k, v in N['iy_hedefleri_max_abs_z_desteklenen'].items()}) +
     " < z_crit≈3,98) fakat güç düşük: %80 güçte ortanca göreli MDE " +
     str({r['hedef']: round(r['g80_ortanca_%'], 1) for r in N['mde_ozet'][:2]}) +
     " % (O/E ≈ ≤0,48 veya ≥1,52); destekli hipotez 99/200 ve 84/190. Daha küçük etkiler dışlanmış değildir"),
    ("reports/experiments.jsonl dizi-arastirma F1–F7 kayıtları", "Aile kayıtları sonuç dosyasıyla aynı.", "DOGRULANDI",
     "7 aile kaydında ozet ve statu_sayilari dizi_sonuclar.json ile birebir; veri_sha256 ve kod_sha256 manifestle aynı; "
     "git 398b60b kirli=False. Not: F7 kaydındaki 'R': 1000 genel R'dir; plasebo R=200 yalnız ozet metninde"),
]
df = pd.DataFrame(rows, columns=["kaynak", "iddia", "durum", "kanit"])
df.to_csv(OUT / "iddia_kontrolleri.csv", index=False)
print(df[["kaynak", "durum"]].to_string())

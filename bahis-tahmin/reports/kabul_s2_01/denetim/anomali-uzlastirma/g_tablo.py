"""Uzlaştırma tablosu (sayim_uzlastirma.csv / .md) — değerler a_ozet.json ve b_ozet.json'dan programla okunur."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
a = json.loads((OUT / "a_ozet.json").read_text(encoding="utf-8"))
b = json.loads((OUT / "b_ozet.json").read_text(encoding="utf-8"))
D = a["donem"]


K = pd.read_csv(OUT / "kayit_tablosu_kimliksiz.csv")


def pdd(mask):
    c = K.loc[mask, "period"].value_counts()
    return "/".join(str(int(c.get(p, 0))) for p in ("isinma", "kesif", "parametre", "test"))


def dd(d):
    return f"{d['isinma']}/{d['kesif']}/{d['parametre']}/{d['test']}"


KAYIT = "anomaliler.json (1.600 kayıt; sha256 c2f39ce9…)"
OZET = "sonuclar_tam.json ve 01b7e9f:reports/dizi_sonuclar.json → anomali_ozeti (birebir aynı)"
rows = [
    dict(kod="N", iddia="toplam 1.600 kayıt (SONUCLAR.md:120-121; anomali_ozeti.toplam)", rapor=1600, hesap=a["n_kayit"],
         birim="maç (pair_id başına 1 kayıt; ev satırı temsilci; anomaly.py:99-139,247)",
         evren="en az bir takım satırı (uygun ∧ dönem≠None) olan maçlar (research.py:892 + anomaly.py:111); dönemler isinma 2002/03–2005/06 dahil",
         donem=dd(D["S∪M"]), durum="DOGRULANDI",
         oneri="1.600 maç (845 sürpriz + 761 model–piyasa farkı bayrağı; 6 maç iki bayraklı)",
         kanit=f"{KAYIT}: pair_id ve event_id tekil; |S∪M|={a['S∪M']}"),
    dict(kod="S", iddia="sürpriz 845", rapor=845, hesap=a["S"], birim="maç-bayrağı (flags ∋ UNEXPLAINED_ANOMALY)",
         evren="S kümesi", donem=dd(D["S"]), durum="DOGRULANDI",
         oneri="845 maçta sonuç sürprizi lig-sezonunun üst %0,5 sırasında (bayrak adı 'UNEXPLAINED_ANOMALY' olsa da 210'u alternatif açıklamayla uyumlu)",
         kanit=f"{KAYIT}; {OZET}.tur"),
    dict(kod="M", iddia="piyasa farkı 761", rapor=761, hesap=a["M"], birim="maç-bayrağı (flags ∋ MODEL_PIYASA_FARKI)",
         evren="M kümesi", donem=dd(D["M"]), durum="DOGRULANDI", oneri="", kanit=f"{KAYIT}; {OZET}.tur"),
    dict(kod="S∩M", iddia="(raporlanmadı)", rapor=None, hesap=a["S∩M"], birim="maç", evren="S∩M",
         donem="1/1/4/0", durum="BILGI",
         oneri="845 + 761 = 1.606 bayrak, 1.600 maç; 6 maç iki bayraklı. Yalnızca-S 839, yalnızca-M 755",
         kanit="küme kesişimi (a_kayit_uzlastirma.py)"),
    dict(kod="S_acik_degil", iddia="845 sürpriz işaretinden 635'i açıklanamadı", rapor=635, hesap=a["S_aciklanamayan"],
         birim="maç-bayrağı (status_by_flag[S] = UNEXPLAINED_ANOMALY)", evren="S kümesi",
         donem=dd(D["S_aciklanamayan"]), durum="DOGRULANDI",
         oneri="635 sürpriz bayrağında çalıştırılabilen kontrollerden hiçbiri koşulunu sağlamadı (208'inde kırmızı kart verisi yok; 5 kontrol hiç çalıştırılamadı) — 'açıklanamadı' değil",
         kanit=f"{OZET}.tur_durum_donem.UNEXPLAINED_ANOMALY.UNEXPLAINED_ANOMALY"),
    dict(kod="S_acik", iddia="210 (= 845 − 635)", rapor=210, hesap=a["S_aciklanabilir"],
         birim="maç-bayrağı (status_by_flag[S] = açıklanabilir)", evren="S kümesi", donem=dd(D["S_aciklanabilir"]),
         durum="DOGRULANDI",
         oneri="210 sürpriz bayrağı alternatif açıklamayla uyumlu: yalnız kırmızı kart 109, yalnız lig değişikliği 83, lig+kırmızı 11, yalnız takım adı 6, takım adı+kırmızı 1 (marjinal: kırmızı 121, lig 94, takım adı 7; veri doğrulama 0, hükmen 0)",
         kanit="aciklayan_kontrol_kesisim.csv; anomali_ozeti.tur_durum_donem.UNEXPLAINED_ANOMALY.açıklanabilir"),
    dict(kod="M_acik_degil", iddia="(özette yalnızca tur_durum_donem içinde)", rapor=None, hesap=a["M_aciklanamayan"],
         birim="maç-bayrağı (status_by_flag[M] = MODEL_PIYASA_FARKI)", evren="M kümesi", donem=dd(D["M_aciklanamayan"]),
         durum="BILGI", oneri="M bayrağı düzeyinde açıklama bulunmayan 497 (493 değil)",
         kanit=f"{OZET}.tur_durum_donem.MODEL_PIYASA_FARKI.MODEL_PIYASA_FARKI (43+148+162+144)"),
    dict(kod="M_acik", iddia="(özette yalnızca tur_durum_donem içinde)", rapor=None, hesap=a["M_aciklanabilir"],
         birim="maç-bayrağı (status_by_flag[M] = açıklanabilir)", evren="M kümesi", donem=dd(D["M_aciklanabilir"]),
         durum="BILGI", oneri="264 M bayrağı alternatif açıklamayla uyumlu: yalnız lig değişikliği 260, yalnız takım adı 3, ikisi 1",
         kanit="aciklayan_kontrol_kesisim.csv"),
    dict(kod="durum_MPF", iddia="493 MODEL_PIYASA_FARKI (anomali_ozeti.durum; CLI çıktısı cli.py:388)", rapor=493,
         hesap=a["durum_sayim"]["MODEL_PIYASA_FARKI"],
         birim="KAYIT durumu = status_by_flag[flags[0]] (anomaly.py:270) — S varsa S'nin durumu",
         evren="yalnızca-M 755 kayıt", donem=dd(D["durum_MPF"]), durum="DARALTILDI",
         oneri="493 = sürpriz bayrağı olmayan ve model–piyasa farkı için alternatif açıklama bulunmayan maç; M bayrağı düzeyinde sayı 497 (4'ü iki bayraklı kayıtlarda sürpriz durumunun altında görünmüyor)",
         kanit=f"{OZET}.durum; a_ozet.json yalnizca_M_aciklanamayan={a['yalnizca_M_aciklanamayan']}"),
    dict(kod="durum_acik", iddia="472 açıklanabilir (anomali_ozeti.durum)", rapor=472, hesap=a["durum_sayim"]["açıklanabilir"],
         birim="KAYIT durumu (iki bayrak türü karışık)", evren="S-açıklanabilir 210 + yalnızca-M açıklanabilir 262",
         donem=dd(D["durum_acik"]), durum="DARALTILDI",
         oneri="472 kayıt = 210 sürpriz + 262 yalnızca-piyasa-farkı kaydı; bayrak düzeyinde S 210, M 264 (2 iki-bayraklı kayıt bir kez sayılır)",
         kanit=f"{OZET}.durum; a_ozet.json yalnizca_M_aciklanabilir={a['yalnizca_M_aciklanabilir']}"),
    dict(kod="lig_353", iddia="lig değişikliği sonrası ilk maçlar (353 kaydı açıkladı) (SONUCLAR.md:122; önceki rapor m.12)",
         rapor=353, hesap=a["lig_353"]["tum"], birim="KAYIT (maç)",
         evren="1.600 kaydın tümü (S∪M); kontrol kapsamı iki bayrak", donem=pdd(K["aciklar::lig değişikliği sonrası ilk maçlar"]),
         durum="DARALTILDI",
         oneri="1.600 kaydın 353'ünde takımlardan biri lig değişikliği/dilim başından sonraki ilk 8 maçında (S0 soğuk başlangıcıyla uyumlu): sürpriz bayraklı 94, piyasa farkı bayraklı 261 (2 maç iki bayraklı). Bu 353 maçın her birinde tam olarak bir takım satırı 'uygun' değil (since_league_change < 8) → Sorgu 1/2 maskelerinin dışındadır",
         kanit=f"checklist aciklar; evren_kayit_satir.csv: tek taraf uygun {b['kayit_tek_taraf_uygun']} = lig açıklar 353 (çapraz tablo birebir)"),
    dict(kod="kk_121", iddia="kırmızı kart (121 kaydı açıkladı)", rapor=121, hesap=a["aciklayan_S_marjinal"]["kırmızı kart"],
         birim="KAYIT (maç)", evren="yalnızca S kümesi (kontrol kapsamı yalnız sürpriz; anomaly.py:214-221)",
         donem=pdd(K["aciklar::kırmızı kart"] & K["S"]), durum="DARALTILDI",
         oneri="845 sürpriz bayraklı maçın 121'inde maçta kırmızı kart var (alternatif açıklamayla uyumlu; nedensellik sınanmadı). 1.600 kaydın tümünde kırmızı kart olan maç 212'dir (91'i yalnızca-M; M'yi açıklamaz)",
         kanit=f"a_ozet.json kk_121 = {a['kk_121']}"),
    dict(kod="kk_na_429", iddia="kırmızı kart: 429 kayıtta veri yok", rapor=429, hesap=a["kk_na_429"]["tum"],
         birim="KAYIT (maç)", evren="1.600 kaydın tümü (S∪M) — 121 ile AYNI havuz değil", donem=pdd(~K["calisti::kırmızı kart"]), durum="DARALTILDI",
         oneri="Kırmızı kart kontrolü (yalnız sürprize uygulanır) 845 sürpriz kaydının 229'unda veri olmadığı için çalışmadı (208'i 'açıklanamayan' 635 içinde); 616'sında çalıştı, 121'inde kırmızı kart var. 429 = 1.600 kaydın tümü (200'ü yalnızca-M, kontrol kapsamı dışında). Verisiz kayıtların tamamı 2002–2017",
         kanit=f"a_ozet.json kk_na_429 = {a['kk_na_429']['S']} (S) / {a['kk_na_429']['yalnizca_M']} (yalnızca-M); kaynakta h_red/a_red NaN: {b['kk_na_kaynakta_red_NaN']}"),
    dict(kod="htft_619_218", iddia="Açıklanamayan 635 sürpriz kaydının çoğu ham İY/MS 1/2 (619) ve 2/1 (218)", rapor="619/218",
         hesap=f"{a['htft_S_aciklanamayan'].get('HTFT_1_2')}/{a['htft_S_aciklanamayan'].get('HTFT_2_1')}",
         birim="KAYIT (maç)", evren="619/218 aslında 845 S kaydının tümüne ait", donem="-", durum="DUZELTILDI",
         oneri="Açıklama bulunmayan 635 sürpriz kaydının 476'sı ham İY/MS 1/2, 153'ü 2/1 (toplam 629, %99,1). 619 ve 218 tüm 845 sürpriz kaydının sayılarıdır (619+218=837 > 635)",
         kanit="htft alanı; a_ozet.json htft_S_aciklanamayan / htft_S_tum"),
    dict(kod="medyan_p", iddia="medyan S0 olasılığı %1,4", rapor="1,4%", hesap=f"{a['medyan_p_S_aciklanamayan']*100:.3f}%",
         birim="kayıt", evren="635 açıklama bulunmayan S kaydı", donem="-", durum="DOGRULANDI",
         oneri="(tüm 845 S kaydında %1,384)", kanit="s0_p_gerceklesen medyanı"),
    dict(kod="kural_pay", iddia="her lig-sezonda en üst %0,5 / 'kural her lig-sezonda sabit pay işaretliyor'", rapor="%0,5",
         hesap="havuz başına 0/1/2/3 bayrak (n≤100 / 101–300 / 301–500 / 501–700); kayıtlı havuzlarda kural oranı %0,341–%0,909 (ort. %0,549)",
         birim="maç-bayrağı / havuz", evren="449 (S) ve 431 (M) kayıtlı lig-sezon havuzu", donem="-", durum="DARALTILDI",
         oneri="Kural her lig-sezonda havuz büyüklüğüyle belirlenen sabit SAYIDA maçı işaretler: max(0, ⌈(n−100)/200⌉). 845 ve 761 bu kuralın ve havuz sayılarının sonucudur; sıklık/yaygınlık tahmini değildir",
         kanit="anomaly.py:73-96; kural_esik_tablosu.csv; havuz_bayrak.csv; havuz_sinif_ozet.csv; sentetik_kural.csv (gerçek anomali olmayan sentetik veride de her kümede aynı sayıda bayrak)"),
    dict(kod="kucuk_havuz", iddia="≤ 100 maçlık havuzlar işaretlenmez", rapor="0", hesap="0 (en küçük bayraklı havuz 110)",
         birim="havuz", evren="tüm kayıtlar", donem="-", durum="DOGRULANDI",
         oneri="Bu çalıştırmada ≤100 olan 30 havuzun hepsi zaten rapor evreni dışındaydı (22'si 2026/27 dönemsiz, 8'i tam olmayan sezon); kural sayıları değiştirmedi",
         kanit="anomaly.py:95 (twice·200 < 2n); a_ozet.json kural_kontrol; b_ozet.json kume_mac_le100 + d_cikti.txt"),
    dict(kod="evren_uygun", iddia="RUN_DECISIONS['anomali']: 'tüm dönemlerin uygun maçlarında'", rapor=None,
         hesap=f"iki taraf uygun {b['kayit_iki_taraf_uygun']}, tek taraf uygun {b['kayit_tek_taraf_uygun']}, hiçbiri {b['kayit_hic_uygun_degil']}",
         birim="maç", evren="kayıtlar", donem="-", durum="DARALTILDI",
         oneri="'iki takım satırından EN AZ BİRİ uygun olan (dönemi isinma/keşif/parametre/test) maçlarda'; referans havuz ise lig-sezonun S0'lı TÜM maçlarıdır (uygun olmayanlar dahil; 449 kümenin 370'inde havuz > seçilebilir maç, toplam fazla 2.491)",
         kanit="research.py:892; anomaly.py:111,137-138,247; b_ozet.json"),
    dict(kod="raporlanmayan_bayrak", iddia="(raporlanmadı)", rapor=None,
         hesap=f"S en az {b['S_kural_eksi_kayit']}, M en az {b['M_kural_eksi_kayit']} (+ S kaydı olup M kaydı olmayan 20 tam oranlı kümede tahmini ≈26)",
         birim="maç-bayrağı", evren="kayıtlı havuzlarda kuralın ürettiği ama maskeye girmeyen bayraklar", donem="-",
         durum="BILGI",
         oneri="Kural bayrağı alan ama iki satırı da uygun olmayan maçlar raporlanmaz; bunlar çoğunlukla iki tarafı da soğuk başlangıçta olan (yani lig kontrolüyle 'uyumlu' olacak) maçlardır → raporlanan 'açıklanabilir' payı aşağı yanlıdır",
         kanit="havuz_bayrak.csv (fark sütunu); f_cikti.txt; S0 yüklenmeden kesin sayı DOGRULANAMADI"),
]
def _md_table(t):
    out = ["| " + " | ".join(map(str, t.columns)) + " |", "|" + "---|" * len(t.columns)]
    out += ["| " + " | ".join(map(str, r)) + " |" for r in t.itertuples(index=False)]
    return out


df = pd.DataFrame(rows)
df.columns = ["kod", "raporlanan_iddia", "raporlanan_sayi", "hesaplanan", "sayim_birimi", "evren_havuz",
              "donem_isinma/kesif/parametre/test", "durum", "onerilen_ifade", "kanit"]
df.to_csv(OUT / "sayim_uzlastirma.csv", index=False)

md = ["# Anomali sayımlarının maç düzeyinde uzlaştırılması (01b7e9f; resmi çalıştırma 398b60b, 2026-10-10T10:08–10:45 UTC)",
      "",
      "Kaynak kayıtlar: `seq/research_out/anomaliler.json` (sha256 c2f39ce97f0f…); özet: `sonuclar_tam.json` ve "
      "`01b7e9f:reports/dizi_sonuclar.json` → `anomali_ozeti` (ikisi birebir aynı). Kod: anomaly.py/research.py "
      "398b60b ile 01b7e9f arasında anomali yolunda değişmedi (`git diff 398b60b 01b7e9f -- bahis_tahmin/sequences/` "
      "yalnızca prematch.py ayna eşlemesi ve research.py TEST_OPENED/ayna değişiklikleri).",
      "",
      "## Küme cebiri",
      "",
      f"|S| = {a['S']}, |M| = {a['M']}, |S∩M| = {a['S∩M']}, |S∪M| = {a['S∪M']} = kayıt sayısı; yalnızca-S {a['yalnizca_S']}, yalnızca-M {a['yalnizca_M']}.",
      "",
      "| | S (sürpriz) | M (model–piyasa) | kayıt durumu (status = flags[0]'ın durumu) |",
      "|---|---|---|---|",
      f"| açıklama bulunmayan | {a['S_aciklanamayan']} | {a['M_aciklanamayan']} | UNEXPLAINED_ANOMALY {a['durum_sayim']['UNEXPLAINED_ANOMALY']}, MODEL_PIYASA_FARKI {a['durum_sayim']['MODEL_PIYASA_FARKI']} |",
      f"| alternatif açıklamayla uyumlu | {a['S_aciklanabilir']} | {a['M_aciklanabilir']} | açıklanabilir {a['durum_sayim']['açıklanabilir']} |",
      f"| toplam | {a['S']} | {a['M']} | {a['n_kayit']} |",
      "",
      "S∩M'deki 6 maç: 2'si iki bayrakta da lig değişikliğiyle uyumlu (isinma, keşif), 3'ü iki bayrakta da açıklamasız "
      "(parametre), 1'i S kırmızı kartla uyumlu / M açıklamasız (parametre). Bu yüzden 497 − 4 = 493 ve 210 + 264 − 2 = 472.",
      "",
      "## Uzlaştırma tablosu",
      "",
      "| kod | iddia | rapor | hesap | birim | evren | dönem (ıs/keş/par/test) | durum | önerilen ifade |",
      "|---|---|---|---|---|---|---|---|---|"]
for r in df.itertuples(index=False):
    md.append("| " + " | ".join(str(x).replace("|", "/") if x is not None else "-" for x in
                                  (r.kod, r.raporlanan_iddia, r.raporlanan_sayi, r.hesaplanan, r.sayim_birimi,
                                   r.evren_havuz, r[6], r.durum, r.onerilen_ifade)) + " |")
md += ["", "Kanıt sütunu için `sayim_uzlastirma.csv`'ye bakın.", "",
       "## 210 açıklamalı sürpriz kaydının açıklayan kontrollere göre dağılımı (kesişimli)", "",
       "| birleşim | kayıt |", "|---|---|"]
for k, v in sorted(a["aciklayan_S_birlesim"].items(), key=lambda kv: -kv[1]):
    md.append(f"| {k} | {v} |")
md += ["", f"Marjinal: {a['aciklayan_S_marjinal']}", "",
       "M (264): " + ", ".join(f"{k}: {v}" for k, v in a["aciklayan_M_birlesim"].items()), "",
       "## Havuz büyüklüğüne göre bayrak (kural: bayrak ⇔ (2·büyük + eşit)·200 < 2n; anomaly.py:91-95)", "",
       "| havuz n | bayrak sayısı | pay aralığı |", "|---|---|---|",
       "| ≤ 100 | 0 | 0 |", "| 101–300 | 1 | %0,33–%0,99 |", "| 301–500 | 2 | %0,40–%0,66 |",
       "| 501–700 | 3 | %0,43–%0,60 |", "",
       *_md_table(pd.read_csv(OUT / "havuz_sinif_ozet.csv")), "",
       f"Kayıtlı havuzlarda kuralın zorladığı toplam: S {a['S'] + b['S_kural_eksi_kayit']}, M {a['M'] + b['M_kural_eksi_kayit']}; "
       f"raporlanan S {a['S']}, M {a['M']} (fark = maskeye girmeyen bayraklı maç). Sentetik gösterim (gerçek anomali yok): "
       "`sentetik_kural.csv` — her kümede S ve M bayrak sayısı kuralla birebir."]
(OUT / "sayim_uzlastirma.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))

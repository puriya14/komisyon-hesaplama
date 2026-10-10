# Anomali sayımlarının maç düzeyinde uzlaştırılması (01b7e9f; resmi çalıştırma 398b60b, 2026-10-10T10:08–10:45 UTC)

Kaynak kayıtlar: `seq/research_out/anomaliler.json` (sha256 c2f39ce97f0f…); özet: `sonuclar_tam.json` ve `01b7e9f:reports/dizi_sonuclar.json` → `anomali_ozeti` (ikisi birebir aynı). Kod: anomaly.py/research.py 398b60b ile 01b7e9f arasında anomali yolunda değişmedi (`git diff 398b60b 01b7e9f -- bahis_tahmin/sequences/` yalnızca prematch.py ayna eşlemesi ve research.py TEST_OPENED/ayna değişiklikleri).

## Küme cebiri

|S| = 845, |M| = 761, |S∩M| = 6, |S∪M| = 1600 = kayıt sayısı; yalnızca-S 839, yalnızca-M 755.

| | S (sürpriz) | M (model–piyasa) | kayıt durumu (status = flags[0]'ın durumu) |
|---|---|---|---|
| açıklama bulunmayan | 635 | 497 | UNEXPLAINED_ANOMALY 635, MODEL_PIYASA_FARKI 493 |
| alternatif açıklamayla uyumlu | 210 | 264 | açıklanabilir 472 |
| toplam | 845 | 761 | 1600 |

S∩M'deki 6 maç: 2'si iki bayrakta da lig değişikliğiyle uyumlu (isinma, keşif), 3'ü iki bayrakta da açıklamasız (parametre), 1'i S kırmızı kartla uyumlu / M açıklamasız (parametre). Bu yüzden 497 − 4 = 493 ve 210 + 264 − 2 = 472.

## Uzlaştırma tablosu

| kod | iddia | rapor | hesap | birim | evren | dönem (ıs/keş/par/test) | durum | önerilen ifade |
|---|---|---|---|---|---|---|---|---|
| N | toplam 1.600 kayıt (SONUCLAR.md:120-121; anomali_ozeti.toplam) | 1600 | 1600 | maç (pair_id başına 1 kayıt; ev satırı temsilci; anomaly.py:99-139,247) | en az bir takım satırı (uygun ∧ dönem≠None) olan maçlar (research.py:892 + anomaly.py:111); dönemler isinma 2002/03–2005/06 dahil | 135/465/483/517 | DOGRULANDI | 1.600 maç (845 sürpriz + 761 model–piyasa farkı bayrağı; 6 maç iki bayraklı) |
| S | sürpriz 845 | 845 | 845 | maç-bayrağı (flags ∋ UNEXPLAINED_ANOMALY) | S kümesi | 72/252/249/272 | DOGRULANDI | 845 maçta sonuç sürprizi lig-sezonunun üst %0,5 sırasında (bayrak adı 'UNEXPLAINED_ANOMALY' olsa da 210'u alternatif açıklamayla uyumlu) |
| M | piyasa farkı 761 | 761 | 761 | maç-bayrağı (flags ∋ MODEL_PIYASA_FARKI) | M kümesi | 64/214/238/245 | DOGRULANDI |  |
| S∩M | (raporlanmadı) | - | 6 | maç | S∩M | 1/1/4/0 | BILGI | 845 + 761 = 1.606 bayrak, 1.600 maç; 6 maç iki bayraklı. Yalnızca-S 839, yalnızca-M 755 |
| S_acik_degil | 845 sürpriz işaretinden 635'i açıklanamadı | 635 | 635 | maç-bayrağı (status_by_flag[S] = UNEXPLAINED_ANOMALY) | S kümesi | 58/202/185/190 | DOGRULANDI | 635 sürpriz bayrağında çalıştırılabilen kontrollerden hiçbiri koşulunu sağlamadı (208'inde kırmızı kart verisi yok; 5 kontrol hiç çalıştırılamadı) — 'açıklanamadı' değil |
| S_acik | 210 (= 845 − 635) | 210 | 210 | maç-bayrağı (status_by_flag[S] = açıklanabilir) | S kümesi | 14/50/64/82 | DOGRULANDI | 210 sürpriz bayrağı alternatif açıklamayla uyumlu: yalnız kırmızı kart 109, yalnız lig değişikliği 83, lig+kırmızı 11, yalnız takım adı 6, takım adı+kırmızı 1 (marjinal: kırmızı 121, lig 94, takım adı 7; veri doğrulama 0, hükmen 0) |
| M_acik_degil | (özette yalnızca tur_durum_donem içinde) | - | 497 | maç-bayrağı (status_by_flag[M] = MODEL_PIYASA_FARKI) | M kümesi | 43/148/162/144 | BILGI | M bayrağı düzeyinde açıklama bulunmayan 497 (493 değil) |
| M_acik | (özette yalnızca tur_durum_donem içinde) | - | 264 | maç-bayrağı (status_by_flag[M] = açıklanabilir) | M kümesi | 21/66/76/101 | BILGI | 264 M bayrağı alternatif açıklamayla uyumlu: yalnız lig değişikliği 260, yalnız takım adı 3, ikisi 1 |
| durum_MPF | 493 MODEL_PIYASA_FARKI (anomali_ozeti.durum; CLI çıktısı cli.py:388) | 493 | 493 | KAYIT durumu = status_by_flag[flags[0]] (anomaly.py:270) — S varsa S'nin durumu | yalnızca-M 755 kayıt | 43/148/158/144 | DARALTILDI | 493 = sürpriz bayrağı olmayan ve model–piyasa farkı için alternatif açıklama bulunmayan maç; M bayrağı düzeyinde sayı 497 (4'ü iki bayraklı kayıtlarda sürpriz durumunun altında görünmüyor) |
| durum_acik | 472 açıklanabilir (anomali_ozeti.durum) | 472 | 472 | KAYIT durumu (iki bayrak türü karışık) | S-açıklanabilir 210 + yalnızca-M açıklanabilir 262 | 34/115/140/183 | DARALTILDI | 472 kayıt = 210 sürpriz + 262 yalnızca-piyasa-farkı kaydı; bayrak düzeyinde S 210, M 264 (2 iki-bayraklı kayıt bir kez sayılır) |
| lig_353 | lig değişikliği sonrası ilk maçlar (353 kaydı açıkladı) (SONUCLAR.md:122; önceki rapor m.12) | 353 | 353 | KAYIT (maç) | 1.600 kaydın tümü (S∪M); kontrol kapsamı iki bayrak | 28/89/99/137 | DARALTILDI | 1.600 kaydın 353'ünde takımlardan biri lig değişikliği/dilim başından sonraki ilk 8 maçında (S0 soğuk başlangıcıyla uyumlu): sürpriz bayraklı 94, piyasa farkı bayraklı 261 (2 maç iki bayraklı). Bu 353 maçın her birinde tam olarak bir takım satırı 'uygun' değil (since_league_change < 8) → Sorgu 1/2 maskelerinin dışındadır |
| kk_121 | kırmızı kart (121 kaydı açıkladı) | 121 | 121 | KAYIT (maç) | yalnızca S kümesi (kontrol kapsamı yalnız sürpriz; anomaly.py:214-221) | 7/26/40/48 | DARALTILDI | 845 sürpriz bayraklı maçın 121'inde maçta kırmızı kart var (alternatif açıklamayla uyumlu; nedensellik sınanmadı). 1.600 kaydın tümünde kırmızı kart olan maç 212'dir (91'i yalnızca-M; M'yi açıklamaz) |
| kk_na_429 | kırmızı kart: 429 kayıtta veri yok | 429 | 429 | KAYIT (maç) | 1.600 kaydın tümü (S∪M) — 121 ile AYNI havuz değil | 82/203/144/0 | DARALTILDI | Kırmızı kart kontrolü (yalnız sürprize uygulanır) 845 sürpriz kaydının 229'unda veri olmadığı için çalışmadı (208'i 'açıklanamayan' 635 içinde); 616'sında çalıştı, 121'inde kırmızı kart var. 429 = 1.600 kaydın tümü (200'ü yalnızca-M, kontrol kapsamı dışında). Verisiz kayıtların tamamı 2002–2017 |
| htft_619_218 | Açıklanamayan 635 sürpriz kaydının çoğu ham İY/MS 1/2 (619) ve 2/1 (218) | 619/218 | 476/153 | KAYIT (maç) | 619/218 aslında 845 S kaydının tümüne ait | - | DUZELTILDI | Açıklama bulunmayan 635 sürpriz kaydının 476'sı ham İY/MS 1/2, 153'ü 2/1 (toplam 629, %99,1). 619 ve 218 tüm 845 sürpriz kaydının sayılarıdır (619+218=837 > 635) |
| medyan_p | medyan S0 olasılığı %1,4 | 1,4% | 1.401% | kayıt | 635 açıklama bulunmayan S kaydı | - | DOGRULANDI | (tüm 845 S kaydında %1,384) |
| kural_pay | her lig-sezonda en üst %0,5 / 'kural her lig-sezonda sabit pay işaretliyor' | %0,5 | havuz başına 0/1/2/3 bayrak (n≤100 / 101–300 / 301–500 / 501–700); kayıtlı havuzlarda kural oranı %0,341–%0,909 (ort. %0,549) | maç-bayrağı / havuz | 449 (S) ve 431 (M) kayıtlı lig-sezon havuzu | - | DARALTILDI | Kural her lig-sezonda havuz büyüklüğüyle belirlenen sabit SAYIDA maçı işaretler: max(0, ⌈(n−100)/200⌉). 845 ve 761 bu kuralın ve havuz sayılarının sonucudur; sıklık/yaygınlık tahmini değildir |
| kucuk_havuz | ≤ 100 maçlık havuzlar işaretlenmez | 0 | 0 (en küçük bayraklı havuz 110) | havuz | tüm kayıtlar | - | DOGRULANDI | Bu çalıştırmada ≤100 olan 30 havuzun hepsi zaten rapor evreni dışındaydı (22'si 2026/27 dönemsiz, 8'i tam olmayan sezon); kural sayıları değiştirmedi |
| evren_uygun | RUN_DECISIONS['anomali']: 'tüm dönemlerin uygun maçlarında' | - | iki taraf uygun 1247, tek taraf uygun 353, hiçbiri 0 | maç | kayıtlar | - | DARALTILDI | 'iki takım satırından EN AZ BİRİ uygun olan (dönemi isinma/keşif/parametre/test) maçlarda'; referans havuz ise lig-sezonun S0'lı TÜM maçlarıdır (uygun olmayanlar dahil; 449 kümenin 370'inde havuz > seçilebilir maç, toplam fazla 2.491) |
| raporlanmayan_bayrak | (raporlanmadı) | - | S en az 11, M en az 69 (+ S kaydı olup M kaydı olmayan 20 tam oranlı kümede tahmini ≈26) | maç-bayrağı | kayıtlı havuzlarda kuralın ürettiği ama maskeye girmeyen bayraklar | - | BILGI | Kural bayrağı alan ama iki satırı da uygun olmayan maçlar raporlanmaz; bunlar çoğunlukla iki tarafı da soğuk başlangıçta olan (yani lig kontrolüyle 'uyumlu' olacak) maçlardır → raporlanan 'açıklanabilir' payı aşağı yanlıdır |

Kanıt sütunu için `sayim_uzlastirma.csv`'ye bakın.

## 210 açıklamalı sürpriz kaydının açıklayan kontrollere göre dağılımı (kesişimli)

| birleşim | kayıt |
|---|---|
| kırmızı kart | 109 |
| lig değişikliği sonrası ilk maçlar | 83 |
| lig değişikliği sonrası ilk maçlar + kırmızı kart | 11 |
| takım adı kopukluğu | 6 |
| takım adı kopukluğu + kırmızı kart | 1 |

Marjinal: {'veri doğrulama': 0, 'hükmen olabilir': 0, 'takım adı kopukluğu': 7, 'lig değişikliği sonrası ilk maçlar': 94, 'kırmızı kart': 121}

M (264): lig değişikliği sonrası ilk maçlar: 260, takım adı kopukluğu: 3, takım adı kopukluğu + lig değişikliği sonrası ilk maçlar: 1

## Havuz büyüklüğüne göre bayrak (kural: bayrak ⇔ (2·büyük + eşit)·200 < 2n; anomaly.py:91-95)

| havuz n | bayrak sayısı | pay aralığı |
|---|---|---|
| ≤ 100 | 0 | 0 |
| 101–300 | 1 | %0,33–%0,99 |
| 301–500 | 2 | %0,40–%0,66 |
| 501–700 | 3 | %0,43–%0,60 |

| bayrak | sinif | havuz_sayisi | havuz_n_min | havuz_n_max | kural_bayrak_toplam | kayitli_bayrak_toplam | mac_toplam | kayitli_oran_% |
|---|---|---|---|---|---|---|---|---|
| M | 101-150 | 6 | 110 | 139 | 6 | 6 | 768 | 0.781 |
| M | 151-250 | 92 | 169 | 240 | 92 | 92 | 18878 | 0.487 |
| M | 251-350 | 114 | 274 | 342 | 223 | 208 | 34782 | 0.598 |
| M | 351-450 | 117 | 374 | 446 | 234 | 216 | 44771 | 0.482 |
| M | 451-650 | 102 | 451 | 552 | 275 | 239 | 53402 | 0.448 |
| S | 101-150 | 6 | 110 | 139 | 6 | 6 | 768 | 0.781 |
| S | 151-250 | 106 | 177 | 240 | 106 | 106 | 21705 | 0.488 |
| S | 251-350 | 116 | 279 | 341 | 229 | 225 | 35465 | 0.634 |
| S | 351-450 | 114 | 379 | 441 | 228 | 223 | 43491 | 0.513 |
| S | 451-650 | 107 | 451 | 552 | 287 | 285 | 55956 | 0.509 |

Kayıtlı havuzlarda kuralın zorladığı toplam: S 856, M 830; raporlanan S 845, M 761 (fark = maskeye girmeyen bayraklı maç). Sentetik gösterim (gerçek anomali yok): `sentetik_kural.csv` — her kümede S ve M bayrak sayısı kuralla birebir.

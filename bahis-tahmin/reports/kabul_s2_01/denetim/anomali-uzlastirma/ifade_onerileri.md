# Anomali bölümü: ifade önerileri ve "suç puanı gibi okunabilecek etiket" taraması (01b7e9f)

Yeni bir puan veya skor ÖNERİLMEZ. Öneriler yalnızca mevcut alanların adını ve cümleleri değiştirir.

## 1. "Açıkladı / açıklanamadı" yerine

| Yer | Bugünkü ifade | Önerilen ifade | Gerekçe |
|---|---|---|---|
| docs/DIZI_ARASTIRMA_SONUCLARI.md:122; önceki rapor m.12 | "lig değişikliği sonrası ilk maçlar (353 kaydı açıkladı)" | "1.600 kaydın 353'ünde takımlardan biri lig değişikliğinden/dilim başından sonraki ilk 8 maçında (S0 soğuk başlangıcıyla **uyumlu alternatif açıklama**; sürpriz bayraklı 94, model–piyasa farkı bayraklı 261, 2 maç iki bayraklı)" | Kontrol bir koşulun sağlandığını gösterir; sürprizin nedeni olduğunu göstermez. 353 iki bayrağın birleşimidir (sayim_uzlastirma.csv: lig_353) |
| aynı satır | "kırmızı kart (121 kaydı açıkladı; 429 kayıtta veri yok)" | "kırmızı kart (yalnızca sonuç sürprizine uygulanır): 845 sürpriz kaydının 616'sında çalıştı, 121'inde maçta kırmızı kart var (**alternatif açıklamayla uyumlu**); 229'unda veri yok (2002–2017)" | 121 S havuzunda, 429 ise S∪M havuzunda sayılmış; aynı cümlede iki havuz (kk_121, kk_na_429) |
| SONUCLAR.md:124 | "Açıklanamayan 635 sürpriz kaydının çoğu ham İY/MS 1/2 (619) ve 2/1 (218)" | "Çalıştırılabilen kontrollerin hiçbirine uymayan 635 sürpriz kaydının 476'sı ham İY/MS 1/2, 153'ü 2/1" | 619/218 tüm 845 S kaydına aittir (htft_619_218) |
| önceki rapor m.12 | "845 sürpriz işaretinden 635'i açıklanamadı" | "845 sürpriz işaretinin 635'inde çalıştırılabilen beş kontrolden hiçbiri uymadı (208'inde kırmızı kart verisi yoktu; eski oran, likidite, kadro, maç içi bilgi ve sağlayıcı gecikmesi kontrolleri veri olmadığı için hiç çalıştırılamadı)" | "Açıklanamadı" kontrol kapsamının dar olduğunu gizler |
| anomaly.py:32 `EXPLAINED = "açıklanabilir"` (durum değeri) | "açıklanabilir" | "alternatif açıklamayla uyumlu" | "Açıklandı" anlamına kayıyor |
| anomaly.py:29 `TYPE_SURPRISE = "UNEXPLAINED_ANOMALY"` (tür alanı) | 845 kaydın TÜRÜ "UNEXPLAINED_ANOMALY" (210'u açıklamayla uyumlu) | tür adı örn. "SONUC_SURPRIZI_UST_PAY" (lig-sezon içi en yüksek sürpriz sırası); "açıklama bulunamadı" yalnızca durum değeri olsun | Sözleşme §11 (DIZI_ARASTIRMA_SOZLESMESI.md:271-273) UNEXPLAINED_ANOMALY'yi "üst %0,5 **ve** açıklanamıyor" diye tanımlar; `anomali_ozeti.tur.UNEXPLAINED_ANOMALY = 845` bu tanımla çelişir (doğrusu 635) |
| anomaly.py:35 ANOMALY_NOTE, ui/pages/sequences.py:393, sözleşme:278 | "Anomali puanı ..." | "Sürpriz değeri (bit) ..." | "Puan/skor" sözcüğü bir değerlendirme puanı gibi okunabilir; alan zaten `surprise_bits` |
| SONUCLAR.md:121 ve önceki rapor m.12 | "Kural her lig-sezonda sabit pay işaretliyor" / "en üst %0,5" | "Kural her lig-sezonda havuz büyüklüğüne bağlı sabit **sayıda** maç işaretler: ≤100 maç 0; 101–300 maç 1; 301–500 maç 2; 501–700 maç 3 (havuz başına %0,33–%0,99). 845 ve 761 kuralın ve havuz sayısının sonucudur; sıklık veya yaygınlık tahmini değildir" | anomaly.py:73-96; havuz_bayrak.csv; sentetik_kural.csv |
| research.py:120 RUN_DECISIONS['anomali'] | "Anomali taraması tüm dönemlerin uygun maçlarında" | "... iki takım satırından en az biri uygun olan (dönemi ısınma/keşif/parametre/test) maçlarda; referans havuz lig-sezonun S0'lı tüm maçlarıdır" | 353 kaydın tam olarak bir satırı uygun değil (evren_kayit_satir.csv). NOT: RUN_DECISIONS metni sha256 ile ön-kayıtlı; değiştirmek yerine sonuç belgesinde açıklama notu düşülmesi önerilir |
| anomali_ozeti.durum (CLI cli.py:388 ve UI an_text) | `{'MODEL_PIYASA_FARKI': 493, 'UNEXPLAINED_ANOMALY': 635, 'açıklanabilir': 472}` | Bayrak başına tablo: sürpriz 635 açıklamasız / 210 uyumlu; model–piyasa 497 / 264 (6 maç iki bayraklı) | Kayıt durumu flags[0]'a göre (anomaly.py:270); 493 ve 472 iki bayrak türünü karıştırır |

## 2. Arayüz/rapor etiketlerinde "suç puanı" gibi okunabilecek ifade taraması

Grep: `grep -rn -i -E "şüpheli|supheli|şike|suç|manipül|hile|risk skoru|risk puanı|anomali puanı|anomali skoru|UNEXPLAINED|açıklanamayan|açıklandı|açıklanabilir|açıkladı" bahis_tahmin docs README.md tools` (01b7e9f arşivi).

- "şike/suç olasılığı" üreten bir alan YOK: kayıt anahtarları sabit listededir (anomaly.py:260-276); "şike/suç" yalnızca olumsuzlama notlarında geçer (anomaly.py:35, ui/pages/sequences.py:393, sözleşme:278). Bu durum DOGRULANDI.
- Risk 1 (orta): UI anomali tablosu `ui_summary` alanlarını HAM sütun adlarıyla gösterir (ui/pages/sequences.py:513-517; research.py:705-707): `type` ve `status` sütunlarında İngilizce "UNEXPLAINED_ANOMALY" değeri görünür. Türkçe başlık eşlemesi (`headers`) ve nötr değerler önerilir: "Sonuç sürprizi (üst sıra)", "Model–piyasa farkı (üst sıra)", "alternatif açıklamayla uyumlu", "kontrollerle açıklama bulunamadı (kapsam dar)".
- Risk 2 (düşük): Özet metni Python sözlüğü olarak basılır (`f"... {summ}"`, ui/pages/sequences.py:516) — 493/472 karışık kayıt durumları bağlamsız görünür.
- Risk 3 (düşük): "Anomali puanı" ifadesi (banner ve not) — "sürpriz değeri (bit)" önerilir.
- Bilgi: tablo `make_table(..., sortable=True)` varsayılanıyla sıralanabilir (ui/widgets.py:179-194) ve `league`, `season` sütunlarını içerir; toplam/sayım gösterilmez, ama kullanıcı lig sütununa göre sıralayarak gözle lig bazında yığılma görebilir. Sözleşme "lig bazında toplama ve sıralama yapılmaz" der; satır sıralaması toplama değildir, ancak bu sütunlarda sıralamanın kapatılması düşünülebilir. Yeni skor önerilmez.
- Bilgi: `prematch_view` (prematch.py:85-113) `son_sonuclar.json` sözlüğünü bütün olarak alır ama yalnızca `oruntuler` ve `ayna_kopyalari` anahtarlarını okur; `anomaliler`/`anomali_ozeti` okunmaz.

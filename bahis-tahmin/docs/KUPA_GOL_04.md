# KUPA-GOL-04: Yurt içi kupalarda gol modeli

İstek: "yurt içi gol modelini düzelt".

**Önceki durum (KUPA-IY-03).** Yurt içi kupalarda üç gol pazarının üçü de (A: iki yarıda KG, B: 3,5 Üst, C: İY 1,5 Üst)
"doğrulanmadı" idi. Teşhis, modelin bu maçlarda golü düşük tahmin ettiğini söylüyordu: maç başına beklenen 2,92 gol,
gerçekleşen 3,15.

## Kısa sonuç

Sorunun asıl nedeni model değil, **ölçüm örneklemiydi**. openfootball dosyaları 0-0 biten maçlarda devre skorunu
neredeyse hiç yazmıyor. Gol pazarı ölçümü "ilk yarı skoru yok" diye bu maçların hepsini dışarıda bırakıyordu. Ölçülen
örneklem böylece gol yönünde seçilmiş oluyordu. Maç sonu 0-0 ise ilk yarı da zorunlu olarak 0-0'dır. Bu kural eklendi
ve seçim baştan yapıldı. Önceden kaydedilmiş kurala göre mevcut model korundu.

Gerçek veride model değişmeden:

- Yurt içi **3,5 Üst** ve **İY 1,5 Üst** artık doğrulanıyor.
- UEFA İY 1,5 Üst de doğrulanıyor.
- İki grupta da "iki yarıda KG" doğrulanmıyor: gerçekleşen örnek 200'den az.

Yurt içi kupalarda son dört sezonda model golü hâlâ biraz düşük tahmin ediyor. Bu açık bir sınırlılık olarak duruyor;
aşağıda anlatılıyor.

## 1. İlk tur: model varyantları (yanlı örneklemle)

İlk teşhis, yurt içi kupalarda iki şey gösteriyordu:

- Ligi veride olmayan (alt lig, amatör) takımlı maçlarda gol düşük tahmin ediliyordu (2,97'ye karşı 3,04) ve
  dağılım fazla yayvandı (Pearson oranı 1,16; iki takımı da depodaki liglerden olan maçlarda 0,98).
- 2023/24'ten sonra güç farkı büyük maçlar artmıştı (ör. Kral Kupası 2023/24'te 1-12, 0-12, 0-10).

Sonuçlar görülmeden şu seçim kuralı yazıldı (`variants.py` başlığı):

- **Ana ölçüt:** yurt içi kupaların geliştirme dönemi (2019/20–2021/22) A, B, C ortalama log-kaybı.
- **Koşul 1:** UEFA'nın aynı dönemdeki A, B, C ortalaması V0'dan 0,0005'ten fazla kötü olamaz.
- **Koşul 2:** iki grubun 1X2 log-kaybı da V0'dan 0,001'den fazla kötü olamaz.
- **Seçim:** koşulları geçenler içinde ana ölçütte en iyisi seçilir. En iyiye 0,0005'ten yakın daha sade bir varyant
  varsa o seçilir. Sadelik sırası: V0 < V2 < V1 < V5 < V3 < V4.
- **Test dönemi** (2022/23–2025/26) seçimden sonra raporlanır.

Varyantlar:

| Varyant | Kalibrasyon |
|---|---|
| V0 | Mevcut: bütün kupalar için ortak 4 parametre |
| V1 | Doğrulama grubuna özgü 4 parametre |
| V2 | Ortak + güç farkı terimi |
| V3 | Gruba özgü + güç farkı terimi |
| V4 | V3 + yakın dönem ağırlığı (yarı ömür 1 yıl) |
| V5 | V1 + yakın dönem ağırlığı |

İlk turda V0 seçildi. Teşhisten sonra bir aday daha eklendi; bu sonradan eklenmiş bir adaydır:

- **F1:** gol pazarı olasılıklarını takım gücü belirsizliği üzerinden ortalamak (Laplace kovaryansı, 5×5
  Gauss–Hermite).

F1 yanlı örneklemde yurt içi ana ölçütte V0'dan 0,000552 iyiydi. Eşik 0,0005'ti, yani kıl payı seçiliyordu. F1 motora
uygulandı ve sınandı. Rapor hazırlanırken asıl neden bulundu (bölüm 2). Bu yüzden F1 kullanılmadı (bölüm 4).

## 2. Asıl neden: 0-0 maçlar ölçümden düşüyordu

Ölçülen örneklem dışı maçlar ile gol pazarı ölçümüne giren maçlar karşılaştırıldı. İlk yarı skoru "eksik" olan
satırların **hepsi** 0-0 bitmişti: UEFA'da 175, yurt içi kupalarda 164 maç.

Depodaki bütün kupa maçlarına bakıldı (7.227 maç):

| | Maç | 0-0 biten | 0-0 ve devre skoru yazılmamış | 0-0 olmayan, devre skoru yok |
|---|---:|---:|---:|---:|
| UEFA | 3.615 | 221 | 221 | 0 |
| Yurt içi | 3.612 | 220 | 219 | 31 |

Football.TXT dosyalarında 0-0 maç çoğunlukla parantezsiz yazılıyor (`Genoa 0-0 Modena`). Okuyucu doğru davranıyordu:
kaynakta olmayan devre skorunu uydurmuyordu. Lig verisinde bu sorun yok: 4.161 lig maçı 0-0 bitmiş, hepsinde devre
skoru var.

**Etkisi.** Bu maçlar düşünce gerçekleşme oranları yapay olarak yükseliyordu:

| Grup | Ölçüm | Maç başına gol | A | B | C |
|---|---|---:|---:|---:|---:|
| UEFA | eski (0-0'lar hariç) | 3,10 | %6,3 | %35,5 | %39,9 |
| UEFA | düzeltilmiş | 2,92 | %5,9 | %33,3 | %37,5 |
| Yurt içi | eski (0-0'lar hariç) | 3,15 | %5,6 | %38,1 | %39,7 |
| Yurt içi | düzeltilmiş | 2,96 | %5,3 | %35,8 | %37,3 |

Gol sütunu ölçülen örneklem dışı maçlardır. Oran sütunları depodaki bütün kupa maçlarıdır.

Taban oranı da aynı yanlı örneklemden hesaplandığı için karşılaştırma kendi içinde tutarlıydı. Ama örneklem temsili
değildi. Model bütün maçlara göre kalibre edildiği için bu örneklemde "golü düşük tahmin ediyor" görünüyordu.
KUPA-IY-03'teki "2,92'ye karşı 3,15" farkının büyük kısmı buydu. Düzeltilmiş örneklemde fark 2,92'ye karşı 2,96.

## 3. Düzeltme

`kupa.gol.ht_scores`: maç sonu (normal süre) 0-0 ise ve kaynak iki devre skorunu da yazmamışsa ilk yarı 0-0 sayılır.
Bu bir tahmin değil, mantıksal zorunluluk. Kupa satırlarında `fthg/ftag` her zaman normal süre skorudur (KUPA-01).

Lig sonuç okuyucusu aynı kuralı S4-PILOT'tan beri uyguluyor (`data/parsers.py` v2, `iy_mantiksal` işareti). Lig
verisinde bu yüzden sorun yok. Kupa tarafında bu kural eksikti.

Kural yalnızca şu durumda uygulanır:

- Golü olan maçta eksik devre skoru yine **tahmin edilmez**.
- Devre skorunun tek tarafı yazılmışsa kayıt tamamlanmaz.

Kuralın kullanıldığı yerler:

- **Gol pazarı ölçümü:** geçerli satır maskesi, A/B/C gerçekleşmeleri, taban oranları, turnuva İY skoru oranı (veri
  kapsamı sekmesi ve `LIG_IY_ORANI_DUSUK` notu).
- **İlk yarı payı:** 0-0 maçlar payı değiştirmez (0/0). Bu yüzden tahminler aynı kalır.
- **Sanal takip sonuçlandırması (`goals.service.settle_pending`):** 0-0 biten kupa maçında A ve C artık
  sonuçlanıyor. Daha önce `UNKNOWN` yazılmış bir kayıt, gerekçe notuyla ("sonuç verisi tamamlandı (önceki sonuç:
  UNKNOWN)") güncellenir. Eski olay silinmez, zincir bozulmaz.

Sonuçlandırmada ayrıca bir hata bulundu ve düzeltildi. Kayıt defteri, önceki sonucu değiştiren kaydı gerekçesiz kabul
etmiyor. Bu yüzden önceki sonucu `UNKNOWN` olan bir kayıt, skor tamamlanınca sonuçlandırmayı `ValueError` ile
durduruyordu. Bu düzeltmeyle 0-0 kupa maçlarında bu durum kesin oluşacaktı. İlk yarı skoru sonradan gelen her maçta da
oluşabilirdi.

Depodaki ham satırlar ve köken kayıtları değişmez.

**Sürümler:**

- Doğrulama kuralı `kupa-gol-dogrulama-v3`: eşikler v2 ile aynı; 0-0 maçlar örneklemde.
- Kayıtlı kupa modelinin dosya sürümü 5. Eski statüler yanlı örneklemle ölçüldüğü için yeniden eğitim gerekir.
- Model `kupa-gol-v2` değişmedi.

## 4. Seçim, düzeltilmiş örneklemle yeniden

Aynı ön kayıtlı kural ve aynı adaylar (V0–V5 ve F1) düzeltilmiş örneklemde yeniden çalıştırıldı.

**Geliştirme dönemi (2019/20–2021/22).** UEFA 813 maç, yurt içi 1.060 maç. Tablodaki değerler A, B, C ortalama
log-kaybıdır.

| Varyant | UEFA | Yurt içi (ana ölçüt) | Koşul 1 | Koşul 2 |
|---|---:|---:|:---:|:---:|
| V0 | 0,53447 | 0,49006 | ✓ | ✓ |
| V1 | 0,5344 | 0,49030 | ✓ | ✓ |
| V2 | 0,5351 | 0,48984 | ✗ | ✗ |
| V3 | 0,5350 | 0,49034 | ✗ | ✓ |
| V4 | 0,5353 | 0,49063 | ✗ | ✓ |
| V5 | 0,5345 | 0,49064 | ✓ | ✗ |
| F1 (sonradan eklenen aday) | 0,53406 | 0,49016 | ✓ | ✓ (1X2 değişmez) |

Koşulları geçen V0, V1 ve F1 içinde yurt içi ana ölçütte en iyisi V0. F1 artık V0'dan 0,000105 **kötü**; yanlı
örneklemde 0,000552 iyiydi. **V0 seçildi.** F1'in uygulaması geri alındı (kod, sürüm ve eğitim süresi KUPA-IY-03'teki
gibi).

F1'in yanlı örneklemdeki küçük üstünlüğü büyük olasılıkla o örneklemin gol yönündeki eğiliminden geliyordu. Belirsizlik
ortalaması tahmin edilen golü biraz artırır. 0-0'lar çıkarılınca bu, gerçekleşmeye yaklaşmak gibi görünüyordu.

**Test dönemi (2022/23–2025/26, seçimden sonra).** UEFA 2.236 maç, yurt içi 1.614 maç. Değerler model ve taban
log-kaybıdır.

| Grup | A model / taban | B model / taban | C model / taban |
|---|---|---|---|
| UEFA | 0,2102 / 0,2133 | 0,6257 / 0,6368 | 0,6523 / 0,6563 |
| Yurt içi | 0,2151 / 0,2175 | 0,6493 / 0,6584 | 0,6652 / 0,6699 |

**Açıklama:**

- Adaylar ve kural ilk çalıştırmadan önce yazıldı.
- F1 sonradan eklenmiş bir adaydı; artık kullanılmıyor.
- Test dönemi ilk turda yanlı örneklemle görülmüştü. Düzeltilmiş test sonuçları seçimi etkilemedi: seçim yalnızca
  geliştirme dönemine göre yapıldı.

## 5. Gerçek veri sonuçları (`kupa-gol-dogrulama-v3`)

7.227 kupa maçı ve 55.604 lig maçıyla. Eğitim 42 saniye sürdü. 1X2 sonuçları değişmedi: UEFA 3.049 maç, 0,951 / 1,047;
yurt içi 2.674 maç, 0,969 / 1,077; ikisi de doğrulandı.

| Grup / pazar | Maç | Pozitif | LL model | LL taban | Δ üst | Eğim | ECE | Eşik | Statü (önceki) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| UEFA · A | 3.049 | 193 | 0,2335 | 0,2371 | −0,0009 | 0,99 | 0,014 | 0,020 | DOĞRULANMADI: pozitif 193 < 200 (aynı) |
| UEFA · B | 3.049 | 1.026 | 0,6296 | 0,6391 | −0,0053 | 1,03 | 0,021 | 0,030 | **doğrulandı** (doğrulandı) |
| UEFA · C | 3.049 | 1.129 | 0,6559 | 0,6603 | −0,0009 | 0,88 | 0,023 | 0,030 | **doğrulandı** (doğrulanmadı) |
| Yurt içi · A | 2.674 | 144 | 0,2080 | 0,2104 | +0,0002 | 0,94 | 0,006 | 0,020 | DOĞRULANMADI: log-kayıp, pozitif 144 < 200 (aynı) |
| Yurt içi · B | 2.674 | 940 | 0,6400 | 0,6497 | −0,0037 | 1,07 | 0,028 | 0,033 | **doğrulandı** (doğrulanmadı) |
| Yurt içi · C | 2.674 | 1.004 | 0,6580 | 0,6624 | −0,0013 | 1,04 | 0,023 | 0,033 | **doğrulandı** (doğrulanmadı) |

Ölçülen maç sayısı artık örneklem dışı kupa maçlarının tamamı (önceden UEFA 2.874, yurt içi 2.510).

**Geçerli ilk yarı skoru oranı (veri kapsamı):**

- UEFA: %93,9'dan %100'e.
- Yurt içi: %93,1'den %99,1'e. Kalan 31 maçta gol var ve devre skoru yok: Türkiye Kupası 23, Kral Kupası 8.
- Türkiye Kupası %79,6'dan %84,4'e çıktı ve %80 eşiğini geçti. Bu turnuvanın gol pazarı tahminleri artık
  `LIG_IY_ORANI_DUSUK` nedeniyle bahis adayı dışında kalmıyor; diğer uygunluk kontrolleri geçerli.

"Doğrulandı", ileriye dönük ölçümde önceden tanımlı kuralın geçildiği anlamına gelir. Pazar sanal takibe alınır. Kâr
kanıtı değildir; bahis adayı olmak için sizin girdiğiniz gerçek oran gerekir.

## 6. Kalan sınırlılıklar

- **Yurt içi kupalarda son sezonlar.** Geliştirme döneminde model golü biraz yüksek tahmin ediyor: 2,91'e karşı 2,83.
  Test döneminde ise düşük: 2,92'ye karşı 3,04; B'de %33,5'e karşı %36,7. 2024/25'te yeni turnuvalar eklendi
  (Türkiye, Fransa, Hollanda, Portekiz, Belçika kupaları) ve güç farkı büyük maçlar arttı. Gruba özgü kalibrasyon (V1)
  ve yakın dönem ağırlığı (V5) test döneminde yurt içi B'de biraz daha iyiydi (0,6476–0,6483'e karşı 0,6493). Ön
  kayıtlı kurala göre seçilmediler; geliştirme döneminde iyi değillerdi. İleriye dönük izlenmeli (sanal takip).
- **A (iki yarıda KG)** iki grupta da az gerçekleşiyor (144 ve 193 maç). Kuraldaki en az 200 pozitif şartı karşılanana
  kadar doğrulanamaz.
- **KUPA-GOL-02'deki model seçimi** de 0-0'ların düştüğü örneklemde yapılmıştı. Ayrı ilk yarı / ikinci yarı güçleri,
  skor durumu çarpanları ve pazar kalibrasyonu adayları orada birbirine 0,001'den yakındı; bu iş kapsamında yeniden
  çalıştırılmadı.

## 7. Testler

`tests/test_kupa_gol_04.py` 7 test içerir ve yalnızca sentetik veri kullanır:

- **Kural:** yalnızca 0-0 ve iki tarafı da boş devre skoru doldurulur. Golü olan maç, tek tarafı yazılmış kayıt ve
  çelişkili kayıt dokunulmadan kalır. Ham satır değişmez. 0-0 maçlar ilk yarı payını değiştirmez.
- **Okuyucu:** kaynağı olduğu gibi okur (0-0'da devre skoru yok); ölçüm İY 0-0 kullanır.
- **Eşdeğerlik:** sentetik kupa dünyasında 0-0 maçların devre skoru silindiğinde de ölçüm aynı kalır. Taban oranları,
  statüler, ilk yarı payı, turnuva İY oranı ve tahminler devre skoru yazılmış haliyle aynıdır.
- **Seçilim etkisi:** eski maske her pazarın gerçekleşme oranını yükseltir.
- **Sonuçlandırma:**
  - 0-0 biten kupa maçında A, C, İY 1,5 Alt ve B sonuçlanır.
  - Önceki `UNKNOWN` sonuç gerekçesiyle güncellenir.
  - Golü olan veya devre skoru eksik yazılmış maçta ilk yarı pazarları belirsiz kalır.
  - İkinci çalıştırma yeni sonuç eklemez; zincir doğrulanır.
- **Sürümler.**

**Mutasyon denetimi:** kodu kasıtlı bozan 13 değişiklik denendi:

- 2 değişiklik eşdeğerdi: A/B/C gerçekleşmesi ve ilk yarı payı ham sütunlarla da aynı sonucu veriyor. NaN
  karşılaştırması yanlış, NaN toplamı atlanıyor.
- İlk turda biri yakalanmadı: yalnızca ev sahibi golsüzse doldurmak. Teste 0-2 biten, devre skoru olmayan satır
  eklendi.
- Son durumda eşdeğer olmayan 11 değişikliğin hepsi en az bir testi kırıyor.

## 8. Kullanım

Kayıtlı kupa modeli dosya sürümü 4 olduğu için yüklenmez. Veri sayfasında **Kaydet, Güncelle ve Eğit** ile veya
`python -m bahis_tahmin kupa-egit` ile yeniden eğitin. Gol Pazarları sayfası ve `kupa-rapor` yeni statüleri gösterir.

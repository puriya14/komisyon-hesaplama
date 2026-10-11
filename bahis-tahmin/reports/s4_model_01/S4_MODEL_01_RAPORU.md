# S4-MODEL-01 — Negatif kalibrasyon ve taban modele yenilginin kök nedeni

**Soru:** Negatif kalibrasyon ve taban modele yenilgi, hangi kanıtla hangi aşamaya bağlandı?

**Kısa cevap.** Bu sorun bir yazılım hatasından ya da ölçüm hatasından kaynaklanmıyor.
- Ölçüm bağımsız olarak birebir yeniden üretildi. Satır ve etiket eşleşmesi ham kaynaktan 1190/1190 doğrulandı. M0'da
  sızıntı yok.
- Toplu örneklemde M0'a göre %95 aralığı sıfırı dışlayan ilk aşama, M10'un B ve C hedeflerini üreten lojistik katman
  (S2):
  - B'de S1 (yapısal) +0,0019 [−0,0074; +0,0112] iken S2 +0,0174 [+0,0074; +0,0286].
  - C'de +0,0017'den +0,0087'ye [+0,0006; +0,0168] çıkıyor.
  - Eşleştirilmiş S2−S1 farkı (sonradan hesaplandı) B'de +0,0155 [+0,0042; +0,0283], C'de +0,0071 [−0,0010; +0,0150].
    C'deki atama bu yüzden sınırda.
  - M10'un nihai B/C olasılığı S2 çıktısıyla aynı (en büyük fark 7,7e-13).
- A'daki kayıp tek bir aşamada oluşmuyor. S2'nin B/C hedeflerine eğme (S3) ve q kalibrasyonu (S4) adımlarında birikiyor;
  q kalibrasyonu örneklem içinde öğreniliyor.
  - M0'a göre aralığı sıfırı dışlayan ilk A aşaması S3: +0,0052 [+0,0013; +0,0091].
  - Tekil adımların hiçbiri tek başına anlamlı değil: S3−S1 +0,0032 [−0,0010; +0,0079], S4−S3 +0,0010 [−0,0013; +0,0036].
  - A'da yalnızca 77 pozitif var; kanıt zayıf.
- Mekanizma sezon düzeyinde:
  - Gollerin rekor kırdığı 2023/24'te B gerçekleşmesi 0,437 (eğitim oranı 0,303). S2 bu sezonun ortalamasını 0,275'e
    indiriyor. B'deki S1→S2 kaybının %127'si bu sezondan geliyor.
  - S2'nin sezon ortalamasındaki salınımın %73–87'si lig düzeyi özelliklerden (bA, bB, bC, s1) geliyor. Bu özellikler
    tek ligde yalnızca zamanla değişiyor. Gürültü düzeyindeki ve kattan kata işaret değiştiren katsayılar, eğitim
    ortalamasından 2–3 sd uzaktaki test değerlerinde kaldıraç gibi etki ediyor.
  - B'de sezon içi eğimler pozitif (+0,14 ile +0,45 arası); toplu negatif eğim sezonlar arası karışmadan doğuyor.
  - "Negatif" eğimler 0'dan ayrışmıyor (standart hata 0,17–0,42) ama 1'den belirgin biçimde uzak. Asıl eksik sezon içi
    ayırt etme gücü: en iyi aşamada bile sezon içi AUC yaklaşık 0,53.
- Bu atama tek bir aykırı sezona dayanıyor. 2023/24 dışarıda bırakılınca (sonradan yapılmış analiz) fark anlamlı değil.
  Sezon kümeli testte de, yalnızca 4 sezonla, hiçbir aşama farkı anlamlı değil.
- Bulunan veri işleme kusuru (MS 0-0 maçların ilk yarısının "bilinmiyor" sayılması) düzeltildi. Ölçülen etkisi S1'in
  B'deki düzey yanlılığını gidermek oldu (0,377 → 0,340; gerçekleşme 0,354). M0'a yenilgiyi değiştirmedi.

| Boyut | Sonuç |
|---|---|
| MEASUREMENT | **VERIFIED** — S4 ölçütleri bağımsız olarak yeniden üretildi; işaret, hedef sınıf ve dönüşüm doğru. Eğim fonksiyonundaki gizli kusurlar düzeltildi (G). |
| MODEL | **BELOW_BASELINE** — düzeltmeden önce de sonra da: S4 − M0, B +0,0185, C +0,0110, A +0,0062; aralıkların hepsi sıfırın üstünde. |
| FORECAST_OPERATION | **SOURCE_BLOCKED** — kaynak güncelliği ve bağımsız katılımcı referansı değişmedi. |

Bu dosya yalnızca toplu sayılar içerir. Gerçek maç satırları, tahmin listeleri, ham veri ve model dosyaları yoktur.
Bu hesaplar, sonuçları daha önce görülmüş sezonlar üzerinde yapılmış tanılamadır; temiz bir final test değildir.

## A. Doğrulanan başlangıç

- Dal `claude/bahis-tahmin`, başlangıç HEAD'i `7588a1fc3e859e697c62c55ad7ce150d972970aa`; uzak dal ile aynıydı ve
  çalışma ağacı temizdi.
- Kaynak: openfootball/football.json, commit `e6744429ee395bc86f247348c6184bb08d4eb361`. 11 sezon dosyası 2016-17'den
  2026-27'ye uzanıyor.
- Referans eğitim kimlik düzeltmesinden sonraki eğitim (pilot klasörü `ev2`):
  - veri özeti `3aa6e5c81c901ab310507b914f6ccba412284e0d4378e14a0871c745c321eb0c`;
  - model dosyası SHA-256 `aedf185e8044721612119e99b5d35301911f72681ca87fd8591b4d2de53f29ab`;
  - varyant `goal-joint-1.0/M10_ipf_kosullu`, doğrulama sezonları 2023–2026.
  Kimlik hatalı ilk model (`12adc927…`) kullanılmadı.
- Model dosyası yüklenmeden önce manifest özeti, manifestteki veri özeti ve pilot model bilgisi doğrulandı. Pilot verisi
  köken doğrulamasından geçti.
- Analiz planı gerçek veriye dokunmadan önce kaydedildi (2026-10-10T23:52:42Z). Plan: hafta blok bootstrap, 1000 tekrar,
  tohum 20261011, aşama listesi, örneklem maskesi ve tekrar bütçesi.
- Kayıtlı tam değerler model dosyasındaki doğrulama kaydından alındı:
  - A: n=1131, pozitif=77, ll_fark_ref 0,0062302614869502275, kal_egim −0,7167841081508455.
  - B: n=1190, pozitif=421, ll_fark_ref 0,0173873943959378, kal_egim −0,19097405260532138.
  - C: n=1131, pozitif=444, ll_fark_ref 0,008698166094729967, kal_egim −0,26782297249105025.
- Yeniden üretim **bit düzeyinde aynı** çıktı (`ayni_deney: true`, en büyük fark 0,0). Pilot dosyalarının 19 SHA-256
  değeri her çalıştırmadan önce ve sonra aynıydı.

## B. Metrik doğruluğu

- Log-kayıp, Brier, ΔLL = LL(model) − LL(M0) ve hafta blok aralığı, ürün kodu kullanılmadan bağımsız formüllerle
  hesaplandı. Kayıtlı değerlerden farkı 0 ile 7e-17 arasında. Pozitif ΔLL modelin aleyhine; işaret doğru.
- Kalibrasyon eğimi üç ayrı yöntemle hesaplandı: elle Newton-IRLS, scipy BFGS ve sıkı toleranslı sklearn. Üçü
  1e-11 içinde uyuşuyor.
  - Ürünün kayıtlı eğimi kesin en çok olabilirlik değeri değildi. sklearn lbfgs, varsayılan `tol=1e-4` ile erken durmuş.
  - Fark A'da 0,0022, B'de 8e-5, C'de 2,4e-4; işareti ve sonucu değiştirmiyor.
  - Düzeltilmiş fonksiyon kesin değeri veriyor: A −0,71462, B −0,19105, C −0,26759.
- Eğimlerin belirsizliği:
  - Standart hatalar A 0,423, B 0,174, C 0,277. Eğimler 0'dan ayrışmıyor (z = −1,69 / −1,10 / −0,96) ama 1'den belirgin
    biçimde uzak (z = −4,05 / −6,84 / −4,57).
  - Doğru yorum ters sıralama değil, ayırt etme gücünün yokluğu.
  - M0'ın eğimi (−2,7 / −1,9 / −2,7) anlamsız: M0 tahminleri neredeyse sabit (sezon içi sd 0,0007–0,013).
- Sentetik denetimlerde yöntem şu durumlarda doğru davrandı: kalibre tahmin, ters sıralı tahmin (eğim işaret değiştirir,
  AUC 1−AUC olur), sabit tahmin, dar aralık, tek sınıf, geçersiz olasılık ve eksik hedef.

## C. Satır ve etiket doğruluğu

- Ham kaynak JSON'u ürün ayrıştırıcısı kullanılmadan ayrıştırıldı ve olay kimliğiyle birleştirildi. 1190/1190 satır
  eşleşti. Skor, takım yönü, tarih, sezon, kat ve A/B/C etiketlerinde uyuşmazlık sıfır.
- Pozitif sınıf YES/OVER koşulu (Y=1). Lojistik katmanın sınıf sırası [0, 1] ve `predict_proba[:, 1]` Y=1'e ait.
  Etiketler ters olsaydı pozitif sayıları 1054/769/687 olurdu.
- Satır sırası kaymıyor:
  - S0_M0 her tarih içinde sabit ve bağımsız hesapla aynı.
  - S1, satırın kendi özellikleri ve kayıtlı katsayılarla satır bazında 1,4e-15 farkla yeniden üretildi.
  - Bir satır kaydırılınca fark 0,23'e çıkıyor; test kaymayı yakalıyor.
- Pandas indeksi ile NumPy pozisyonunun karıştığı bir yer bulunmadı. Tekil olmayan indeks sessizce kaymıyor, hata
  veriyor.
- B'de n=1190, A ve C'de n=1131. Fark, doğrulama sezonlarındaki 59 MS 0-0 maçtan geliyor (2023/24: 11, 2024/25: 16,
  2025/26: 27, 2026/27: 5). v1 ayrıştırıcıda bu maçların İY'si "bilinmiyor" (NaN) sayılıyordu; bkz. G.
- Karantinadaki kayıtlar doğrulama satırlarına girmiyor.
- 2019/20'deki 66 `TARIH_SEZON_DISI` kaydı:
  - **(A) kaynakta gerçekten yanlış yıl var.** Ham tarihler 2019-07-01 ile 2019-07-26 arasında, turlar 32–38. Bu tarihler
    1. turdan (2019-08-09) önce; 380 tarihin hepsi "ay ≥ 7 ise 2019" kalıbına uyuyor.
  - (B) değil: ayrıştırıcının sezon penceresi ham metne göre doğru karar veriyor.
  - (C) bugünkü veride uyuşmazlık 0. Ancak kaynak düzeltilirse, Temmuz 2020 maçlarının 2019/20 sezonuna ait olmasına
    karşın `season_year` kuralı (ay ≥ 7 ise o yıl) onları 2020 katına atar. Bu gizli bir tasarım sınırı; doğrulama
    katlarına (2023–2026) etkisi yok.
  - Eğitimdeki payı %1,7–2,5. Doğrulama özelliklerine katkısı yok (Dixon-Coles penceresi dışında). M0 log-kaybına etkisi
    en çok 6,5e-5. Kayıt yıl tahmin edilerek düzeltilmedi; karantinada bırakıldı.

## D. Aşama tablosu (özgün yeniden üretim; v1 verisi)

Aşamalar aynı M10 modelinin kendi bileşenleridir: S0 M0_taban → S1 yapısal dağılım (M10'un M5 tabanı) → S2 B/C
lojistik hedefleri → S3 IPF (q öncesi) → S4 nihai.
- Her pazarda bütün aşamalar aynı maç kümesinde ölçüldü.
- Aralıklar önceden kaydedilen yöntemle hesaplandı: ISO hafta blok bootstrap, 1000 tekrar, tohum 20261011.
- Sezon satırlarında aralık yok; sezon başına aralık önceden kaydedilmedi.
- Aşama ilişkileri bütün satırlarda tutuyor: A ≤ B∩C ≤ min(B, C), aralık dışı değer 0.
- S3'teki B/C değerleri hedeflerle en çok 7,7e-13 farklı. S3→S4 arasında B/C değişmiyor. Kırpma yok, NaN hedef yok,
  0,5 varsayılan değeri kullanılmamış.

**A: iki yarıda KG** (n=1131, pozitif=77)

| Aşama | Log-kayıp | ΔLL (M0'a göre) [%95] | Brier | Eğim [%95] | Kesişim | AUC | AP | Ort. tahmin | sd | aralık |
|---|---|---|---|---|---|---|---|---|---|---|
| S0 M0_taban | 0,2498 | +0,0000 | 0,0636 | -2,71 | -10,07 | 0,453 | 0,060 | 0,060 | 0,003 | 0,052–0,065 |
| S1 yapısal (M10.base/M5) | 0,2519 | +0,0020 [-0,0027, +0,0067] | 0,0639 | -0,02 [-0,71, +0,70] | -2,67 | 0,493 | 0,069 | 0,072 | 0,020 | 0,021–0,145 |
| S2 lojistik (A: bilgi; M10 A yolunda kullanılmaz) | 0,2630 | +0,0132 [+0,0059, +0,0210] | 0,0648 | -0,29 [-0,65, +0,10] | -3,51 | 0,456 | 0,060 | 0,052 | 0,024 | 0,009–0,222 |
| S3 IPF (q öncesi) | 0,2550 | +0,0052 [+0,0013, +0,0091] | 0,0642 | -0,47 [-1,14, +0,19] | -3,93 | 0,447 | 0,062 | 0,062 | 0,018 | 0,022–0,128 |
| S4 nihai M10 | 0,2561 | +0,0062 [+0,0019, +0,0110] | 0,0642 | -0,71 [-1,49, +0,05] | -4,70 | 0,438 | 0,059 | 0,054 | 0,014 | 0,022–0,104 |

| Sezon | n | Gerçekleşme | S0 ort. | S1 ort. | S2 ort. | S4 ort. | S1 ΔLL | S2 ΔLL | S4 ΔLL | S1 AUC | S2 AUC | S4 AUC | S1 eğim | S2 eğim | S4 eğim |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023/24 | 369 | 0,084 | 0,059 | 0,068 | 0,043 | 0,044 | -0,0018 | +0,0227 | +0,0137 | 0,526 | 0,504 | 0,467 | +0,29 | -0,07 | -0,29 |
| 2024/25 | 364 | 0,047 | 0,062 | 0,077 | 0,063 | 0,065 | +0,0085 | +0,0087 | +0,0037 | 0,433 | 0,400 | 0,394 | -0,54 | -0,62 | -1,23 |
| 2025/26 | 353 | 0,065 | 0,059 | 0,073 | 0,049 | 0,055 | +0,0011 | +0,0066 | +0,0004 | 0,530 | 0,510 | 0,520 | +0,22 | +0,02 | +0,40 |
| 2026/27 (kısmi) | 45 | 0,133 | 0,063 | 0,065 | 0,051 | 0,053 | -0,0125 | +0,0218 | +0,0114 | 0,598 | 0,479 | 0,547 | +1,17 | +0,18 | +0,83 |

Sezon sabit etkili eğim (yalnızca tanılama): S0 -2,05, S1 +0,17, S2 -0,14, S3 -0,06, S4 -0,27

**B: MS 3,5 Üst** (n=1190, pozitif=421)

| Aşama | Log-kayıp | ΔLL (M0'a göre) [%95] | Brier | Eğim [%95] | Kesişim | AUC | AP | Ort. tahmin | sd | aralık |
|---|---|---|---|---|---|---|---|---|---|---|
| S0 M0_taban | 0,6521 | +0,0000 | 0,2297 | -1,89 | -1,88 | 0,471 | 0,334 | 0,337 | 0,012 | 0,306–0,356 |
| S1 yapısal (M10.base/M5) | 0,6540 | +0,0019 [-0,0074, +0,0112] | 0,2306 | +0,37 [+0,02, +0,75] | -0,42 | 0,531 | 0,379 | 0,377 | 0,074 | 0,150–0,629 |
| S2 B/C lojistik | 0,6695 | +0,0174 [+0,0074, +0,0286] | 0,2371 | -0,19 [-0,61, +0,20] | -0,74 | 0,477 | 0,347 | 0,336 | 0,076 | 0,156–0,560 |
| S3 IPF (q öncesi) | 0,6695 | +0,0174 [+0,0074, +0,0286] | 0,2371 | -0,19 [-0,61, +0,20] | -0,74 | 0,477 | 0,347 | 0,336 | 0,076 | 0,156–0,560 |
| S4 nihai M10 | 0,6695 | +0,0174 [+0,0074, +0,0286] | 0,2371 | -0,19 [-0,61, +0,20] | -0,74 | 0,477 | 0,347 | 0,336 | 0,076 | 0,156–0,560 |

| Sezon | n | Gerçekleşme | S0 ort. | S1 ort. | S2 ort. | S4 ort. | S1 ΔLL | S2 ΔLL | S4 ΔLL | S1 AUC | S2 AUC | S4 AUC | S1 eğim | S2 eğim | S4 eğim |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023/24 | 380 | 0,437 | 0,326 | 0,371 | 0,275 | 0,275 | -0,0204 | +0,0413 | +0,0413 | 0,566 | 0,515 | 0,515 | +0,63 | +0,25 | +0,25 |
| 2024/25 | 380 | 0,342 | 0,349 | 0,395 | 0,406 | 0,406 | +0,0114 | +0,0130 | +0,0130 | 0,508 | 0,512 | 0,512 | +0,18 | +0,14 | +0,14 |
| 2025/26 | 380 | 0,284 | 0,337 | 0,370 | 0,330 | 0,330 | +0,0144 | -0,0001 | -0,0001 | 0,523 | 0,520 | 0,520 | +0,25 | +0,26 | +0,26 |
| 2026/27 (kısmi) | 50 | 0,340 | 0,328 | 0,347 | 0,308 | 0,308 | +0,0031 | +0,0021 | +0,0021 | 0,565 | 0,535 | 0,535 | +0,33 | +0,45 | +0,45 |

Sezon sabit etkili eğim (yalnızca tanılama): S0 +0,34, S1 +0,39, S2 +0,22, S3 +0,22, S4 +0,22

**C: İY 1,5 Üst** (n=1131, pozitif=444)

| Aşama | Log-kayıp | ΔLL (M0'a göre) [%95] | Brier | Eğim [%95] | Kesişim | AUC | AP | Ort. tahmin | sd | aralık |
|---|---|---|---|---|---|---|---|---|---|---|
| S0 M0_taban | 0,6704 | +0,0000 | 0,2387 | -2,73 | -1,61 | 0,463 | 0,365 | 0,394 | 0,006 | 0,385–0,405 |
| S1 yapısal (M10.base/M5) | 0,6721 | +0,0017 [-0,0047, +0,0085] | 0,2395 | +0,36 [-0,18, +0,89] | -0,30 | 0,526 | 0,416 | 0,409 | 0,054 | 0,230–0,583 |
| S2 B/C lojistik | 0,6791 | +0,0087 [+0,0006, +0,0168] | 0,2426 | -0,27 [-0,94, +0,42] | -0,57 | 0,482 | 0,399 | 0,378 | 0,051 | 0,216–0,542 |
| S3 IPF (q öncesi) | 0,6791 | +0,0087 [+0,0006, +0,0168] | 0,2426 | -0,27 [-0,94, +0,42] | -0,57 | 0,482 | 0,399 | 0,378 | 0,051 | 0,216–0,542 |
| S4 nihai M10 | 0,6791 | +0,0087 [+0,0006, +0,0168] | 0,2426 | -0,27 [-0,94, +0,42] | -0,57 | 0,482 | 0,399 | 0,378 | 0,051 | 0,216–0,542 |

| Sezon | n | Gerçekleşme | S0 ort. | S1 ort. | S2 ort. | S4 ort. | S1 ΔLL | S2 ΔLL | S4 ΔLL | S1 AUC | S2 AUC | S4 AUC | S1 eğim | S2 eğim | S4 eğim |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023/24 | 369 | 0,431 | 0,393 | 0,408 | 0,353 | 0,353 | -0,0001 | +0,0233 | +0,0233 | 0,533 | 0,461 | 0,461 | +0,37 | -0,50 | -0,50 |
| 2024/25 | 364 | 0,382 | 0,401 | 0,420 | 0,391 | 0,391 | +0,0045 | +0,0019 | +0,0019 | 0,518 | 0,513 | 0,513 | +0,23 | +0,22 | +0,22 |
| 2025/26 | 353 | 0,360 | 0,389 | 0,401 | 0,390 | 0,390 | +0,0019 | +0,0016 | +0,0016 | 0,525 | 0,508 | 0,508 | +0,41 | +0,13 | +0,13 |
| 2026/27 (kısmi) | 45 | 0,422 | 0,387 | 0,384 | 0,391 | 0,391 | -0,0085 | -0,0004 | -0,0004 | 0,587 | 0,540 | 0,540 | +1,24 | +0,42 | +0,42 |

Sezon sabit etkili eğim (yalnızca tanılama): S0 -10,17, S1 +0,38, S2 -0,10, S3 -0,10, S4 -0,10

Ek tanılama (önceden kayıtlı): üç pazarın ortak kümesinde (n=1131) S4 − M0: A +0,0062, B +0,0188, C +0,0087. S1 − M0:
A +0,0020, B −0,0001, C +0,0017.

## E. Sezon ayrımı

- **Kaybın kaynağı tek sezon.** S1→S2 kaybının B'de %127'si, C'de %109'u 2023/24'ten geliyor; diğer sezonlarda fark
  sıfıra yakın ya da ters yönde.
  - 2023/24'te S1 M0'dan iyi: B ΔLL −0,0204 [−0,0363; −0,0038].
  - 2025/26'da B'de S2, S1'den belirgin biçimde iyi.
- **2023 hariç (sonradan yapılmış duyarlılık analizi).**
  - S4 − M0: B +0,0062 [−0,0025; +0,0159], C +0,0016, A +0,0026; hiçbiri anlamlı değil.
  - B'de M0'a göre ilk anlamlı kayıp S1'de: +0,0123 [+0,0024; +0,0227].
- **Toplu eğim ile sezon içi eğim (B).**
  - Toplu −0,191 (SE 0,174); sezon sabit etkili +0,221 (SE 0,242).
  - Sezonlar arası bileşen (Mundlak) −0,634. Sezon içi eğimler +0,25 / +0,14 / +0,26 / +0,45.
  - Sezon ortalaması hatası giderilince (sonradan, yalnızca tanılama) S1→S2 kaybının %89'u kayboluyor.
- **C'de sezon açıklaması kısmi.** Sezon sabit etkili eğim −0,10 (SE 0,30). 2023/24'te sezon içi eğim −0,50
  (SE 0,45), AUC 0,461. Kaybın yalnızca yaklaşık 1/3'ü sezon düzeyinde.
- **A'da sezon payı yüksek ama kanıt zayıf.** Sezon sabit etkili S4 eğimi −0,27 (SE 0,55), Mundlak arası bileşen −1,38
  (SE 0,68); yalnızca 77 pozitif var.
- **Sezon içi (katmanlı) AUC her aşamada düşük.** B: S0 0,482, S1 0,534, S2 0,516. S2 − S1 farkının aralıkları sıfırı
  içeriyor (B −0,018, C −0,033).
- **Sezon ortalaması ile gerçekleşme ilişkisi.** Korelasyon S2'de negatif: A −0,97, B −0,54, C −0,95. Ancak yalnızca 3
  tam sezon var ve S1'de de benzer korelasyonlar görülüyor; aşamaları ayırt etmiyor.
- **Hafta blok aralıkları iyimser olabilir.** Lojistik katman kat başına bir kez eğitildiği için hatası bir sezonun bütün
  haftalarına ortak bir kayma olarak yansır. Sezon kümeli t-testinde (G=4) hiçbir fark anlamlı değil: B S2 t=1,57,
  C t=1,32.
- **Yöntem notu.** Sezon ayrımı yalnızca tanılamadır. Test sezonundan öğrenilen bir düzeltme geçmiş tahminlere
  uygulanmadı ve kullanılabilir model olarak sunulmadı.

**S2'nin lig düzeyi özellikleri.**
- Bu özellikler (bA, bB, bC, s1, season_n) tek ligde aynı günün bütün maçlarında eşit.
- Test değerleri 2023 ve 2024 katlarında eğitim ortalamasının +1,9 ile +3,0 sd üstünde (bB: +1,85 ve +2,96). 2024'te
  test satırlarının %41,3'ünde bB eğitim maksimumunun üstünde. 2025 ve 2026'da z 0,5–1,5 arasında.
- Bu grubun B ortalama logit katkısı: 2023 −0,172 ± 0,142, 2024 +0,290 ± 0,156.
- S2'nin sezon ortalaması salınımındaki payı: B %73–87, A %63–99. C'de payı %160'ın üstünde; form grubu bunu ters yönde
  dengeliyor.
- Katsayılar kararsız ve gürültü düzeyinde (B'de tek tek |t| < 1,3), kattan kata işaret değiştiriyor:
  - B modelinde bB −0,098, +0,016, −0,054, −0,110; bA −0,037'den +0,035'e.
  - C modelinde bC −0,113 ile −0,181 arasında.
- 2023→2024 salınımının büyük kısmı özelliklerin kaymasından değil, yeniden eğitimde değişen katsayılardan geliyor:
  B'de +0,604'ün +0,610'u model, −0,006'sı veri kaynaklı.
- Eğitim döneminde sezon başı bB ile o sezonun B gerçekleşmesi arasındaki korelasyon 2017–2022'de −0,35. Öğrenilebilecek
  kararlı bir ilişki yok.
- Bu bir mekanizma açıklamasıdır, nedensel kanıt değildir. Özellik çıkarma (ablasyon) denemesi bu görevde yapılmadı.

## F. Optimizasyon

- **Katlar.**
  - 2023: eğitim 2016-08-13 → 2023-05-28, test 2023-08-11 → 2024-05-19.
  - 2024: eğitim → 2024-05-19, test 2024-08-16 → 2025-05-25.
  - 2025: eğitim → 2025-05-25, test 2025-08-15 → 2026-05-24.
  - 2026: eğitim → 2026-05-24, test 2026-08-21 → 2026-09-20.
  - Eğitim satırları 2594 / 2974 / 3354 / 3734; usable 2528 / 2908 / 3288 / 3668. M5'in kullandığı İY'li satırlar (v1)
    2355 / 2724 / 3088 / 3441.
- **Lojistik katman.**
  - 27 özellik, C=0,1. Medyan doldurma ve ölçekleme yalnızca eğitim satırlarında öğreniliyor; test eksik oranları çok
    düşük.
  - Yakınsama: A 16–19, B 22–27, C 23–27 iterasyon (sınır 2000); hepsi yakınsadı.
  - Katsayılar küçük (en büyük |β| ≈ 0,25); işaret değiştiren özellik sayısı A 7, B 8, C 9 (27'de).
  - Eğitimdeki kazanç gürültü beklentisinin 1,6–2,8 katı; permütasyon testi bunun gerçek bir yapı olduğunu gösteriyor.
    Ancak bu kazanç örneklem dışına taşınmıyor: B'de dört katın dördünde, C'de üçünde S2, M0'dan kötü.
  - İyimserlik (örneklem dışı − örneklem içi fark) yalnızca S2'ye özgü değil; S1'de de 2024–2025 katlarında büyük.
    "Aşırı uyum S2'de başlıyor" ifadesi bu yüzden kullanılmadı.
- **M5.**
  - 8 L-BFGS-B çağrısının hepsi başarılı ve göreli amaç ölçütüyle durdu. Bağımsız hesaplanan amaç ve gradyan optimuma çok
    yakın: satır başına gradyan ≤ 2,5e-5, koşul sayısı 67–70.
  - `sinirda [8]` = log φ alt sınırı. Bu bir hata değil, Poisson sınır çözümü (KKT sağlanıyor). Eğitim kümesi Poisson'a
    göre az dağılımlı: z −4,4 ile −6,0 arası.
  - 0-0 maçlar İY 0-0 olarak eklenince aynı parametrelerle aşırı dağılım skoru +2,9 ile +3,9'a çıkıyor. Yani v1'deki 0-0
    dışlaması φ'yi de etkiliyor.
- **q kalibrasyonu.**
  - Kodda gerçekten örneklem içi tahminlerle eğitiliyor; q_ham = A/BC yalnızca M5 yapısına bağlı.
  - Katsayılar (a, b) ≈ (−0,6…−0,76; 0,43…0,56); b ≈ 0,5 q'nun yayılımını yarıya indiriyor.
  - Örneklem içi kazanç k/n düzeyinde. Örneklem dışında, B ve C'nin gerçekleştiği 298 satırda q_kal q_ham'dan kötü:
    0,57244'e karşı 0,57117. A'da S3→S4 farkı +0,0010.
- Uyarıların bastırılması başarı sayılmadı; durum `OptimizeResult` ve iterasyon kayıtlarından okundu.

## G. Kanıtlanan hata ve düzeltme

Kök neden olarak bir yazılım hatası gösterilemedi. Bulunan kusurlar aşağıda; her biri önce başarısız bir testle
belgelendi, en küçük düzeltme yapıldı ve testler korundu.

1. **Kalibrasyon eğimi fonksiyonu (`validation.calibration_slope`).** Bu bir ölçüm kusuruydu.
   - Sabit tahminde sahte eğim veriyordu (p=0,3'te +0,41, p=0,6'da −0,29).
   - Tam ayrışmada keyfî bir büyük eğim veriyordu (313,9).
   - Neredeyse sabit tahminde, ölçeksiz tasarım ve varsayılan tolerans yüzünden veriden bağımsız yaklaşık 0,93 eğim
     veriyordu. Bu değer doğrulama kuralının 0,8–1,25 aralığına düşebiliyordu; en çok olabilirlik değeri −5,4'tü.
   - [0,1] dışındaki olasılığı kırpıp sayı döndürüyordu.
   - Tanılamadaki IRLS neredeyse sabit girdide `LinAlgError` veriyordu.

   **Düzeltme:** tanımsız durumlarda NaN dönüyor. Tasarım merkezlenip ölçekleniyor ve sıkı tolerans kullanılıyor;
   böylece kesin en çok olabilirlik değeri bulunuyor. NaN eğim doğrulamayı geçemez. Eşik ve toleranslar değişmedi.

   **Eski/yeni etki (aynı kayıtlı tahminler):** yalnızca kal_egim ve kal_kesisim değişiyor (A −0,716784 → −0,714623,
   B −0,190974 → −0,191054, C −0,267823 → −0,267587). Diğer bütün alanlar bit düzeyinde aynı; doğrulama statüleri
   değişmedi. Kayıtlı model dosyası değiştirilmedi.

2. **MS 0-0 maçlarda ilk yarı (veri işleme kusuru).**
   - Kaynak, MS 0-0 maçlarda İY alanını hiç yazmıyor. 236 MS 0-0 maçın hepsinde İY yok; diğer 3614 maçın hepsinde var.
   - v1 ayrıştırıcı bunları "İY bilinmiyor" sayıyordu. Oysa 0 ≤ İY ≤ MS = 0 olduğundan İY zorunlu olarak 0-0'dır ve A ile
     C mantıksal olarak 0'dır.
   - Sonuç: bütün 0-0 maçlar şunlardan sonuca bağlı olarak dışlanıyordu: A/C etiketleri, ilk ve ikinci yarı güç
     izleyicileri, s1, bA/bC taban oranları, M5 eğitimi ve q kalibrasyonu. Bu rastgele olmayan bir seçimdir (MNAR).
     Etkisi: M5'in gördüğü B oranı yaklaşık +0,022 şişiyordu.
   - **S4-PILOT-01 raporuna düzeltme notu:** o raporda "İY eksik" diye sayılan 234 maçın (karantina dışı) hepsi MS 0-0.
     Kaynakta MS 0-0 olmayan ve İY'si eksik maç yok. Eski rapor değiştirilmedi; bu not onu düzeltir.

   **Düzeltme:** ayrıştırıcı sürümü `openfootball-sonuc-v2`.
   - Yalnızca MS 0-0 ve İY yok ise İY 0-0 kaydediliyor ve `iy_mantiksal` ile işaretleniyor.
   - MS 0-0 olmayan maçta eksik İY eksik kalıyor; MS'den tahmin edilmiyor.
   - v1 kayıtları v1 ile doğrulanabilir kalıyor; eski pilot verisi ve modeli korunuyor.
   - S4-PILOT-01'deki "eksikleri 0-0 yapma" kuralı belirsiz İY'yi uydurmayı yasaklıyordu. Burada değer belirsiz değil,
     mantıksal olarak zorunlu. Bu ayrım bilinçli bir karardır; v1 yeniden seçilebilir.

   **Eski/yeni etki (izinli tek düzeltilmiş karşılaştırmalı tekrar; aynı 3784 maç, aynı MS, 234 maçın İY'si değişti):**
   - S1'in B ortalaması 0,377'den 0,340'a indi (gerçekleşme 0,354); S1'in B'deki düzey yanlılığı giderildi. S1 − M0:
     B +0,0020 [−0,0063; +0,0104].
   - M5 eğitim satırları her katta 179–233 arttı.
   - S2/S4 kaybı sürüyor:
     - B S4 − M0 +0,0185 [+0,0083; +0,0300].
     - C (n=1190) +0,0110 [+0,0022; +0,0217].
     - A (n=1190) +0,0062 [+0,0023; +0,0106]; eğim −0,83 [−1,61; −0,04].
     - Eski değerlendirme kümesinde (aynı satırlar) B +0,0185, C +0,0135, A +0,0067.
   - Yani düzeltme MODEL sonucunu değiştirmiyor (IMPROVED_POST_FIX değil). Bu tekrar temiz bir yeni final test değildir.

   Düzeltilmiş tekrarın aşama tablosu (v2, yeni tam örneklem):

**A** (n=1190, pozitif=77)

| Aşama | Log-kayıp | ΔLL (M0'a göre) [%95] | Eğim [%95] | AUC | Ort. tahmin |
|---|---|---|---|---|---|
| S0 M0_taban | 0,2410 | +0,0000 | -2,82 | 0,450 | 0,057 |
| S1 yapısal | 0,2428 | +0,0019 [-0,0024, +0,0058] | -0,01 [-0,62, +0,65] | 0,494 | 0,065 |
| S2 lojistik (bilgi; M10 A yolunda kullanılmaz) | 0,2545 | +0,0135 [+0,0063, +0,0219] | -0,22 [-0,61, +0,15] | 0,464 | 0,047 |
| S3 IPF | 0,2465 | +0,0056 [+0,0018, +0,0096] | -0,56 [-1,20, +0,10] | 0,443 | 0,060 |
| S4 nihai | 0,2471 | +0,0062 [+0,0023, +0,0106] | -0,83 [-1,61, -0,04] | 0,436 | 0,053 |

**B** (n=1190, pozitif=421)

| Aşama | Log-kayıp | ΔLL (M0'a göre) [%95] | Eğim [%95] | AUC | Ort. tahmin |
|---|---|---|---|---|---|
| S0 M0_taban | 0,6521 | +0,0000 | -1,89 | 0,471 | 0,337 |
| S1 yapısal | 0,6541 | +0,0020 [-0,0063, +0,0104] | +0,34 [-0,00, +0,71] | 0,530 | 0,340 |
| S2 lojistik | 0,6706 | +0,0185 [+0,0083, +0,0300] | -0,21 [-0,63, +0,16] | 0,474 | 0,337 |
| S3 IPF | 0,6706 | +0,0185 [+0,0083, +0,0300] | -0,21 [-0,63, +0,16] | 0,474 | 0,337 |
| S4 nihai | 0,6706 | +0,0185 [+0,0083, +0,0300] | -0,21 [-0,63, +0,16] | 0,474 | 0,337 |

**C** (n=1190, pozitif=444)

| Aşama | Log-kayıp | ΔLL (M0'a göre) [%95] | Eğim [%95] | AUC | Ort. tahmin |
|---|---|---|---|---|---|
| S0 M0_taban | 0,6611 | +0,0000 | -2,21 | 0,472 | 0,373 |
| S1 yapısal | 0,6616 | +0,0005 [-0,0057, +0,0069] | +0,42 [-0,12, +0,95] | 0,532 | 0,378 |
| S2 lojistik | 0,6721 | +0,0110 [+0,0022, +0,0217] | -0,29 [-0,96, +0,33] | 0,483 | 0,346 |
| S3 IPF | 0,6721 | +0,0110 [+0,0022, +0,0217] | -0,29 [-0,96, +0,33] | 0,483 | 0,346 |
| S4 nihai | 0,6721 | +0,0110 [+0,0022, +0,0217] | -0,29 [-0,96, +0,33] | 0,483 | 0,346 |

## H. Değişmeyen engeller

- Kaynak güncelliği: commit 2026-09-22; 2026-10-10 tarihli 6 maçın sonucu yok.
- Bağımsız katılımcı referansı yok; resmî lig sitesi bu ortamın ağ politikasınca engelli.
- Gerçek oran yok; EV, ROI ve bahis adayı yok, stake 0.
- Pilot defterindeki 42 `TAHMIN_YOK` kaydı gerçek tahmin veya test örneklemi sayılmadı. Bu görev kayıt koşullarını
  esnetmedi.
- 2023–2026 doğrulama sezonlarının sonuçları artık görüldü. Bu sezonlar üzerindeki her yeni hesap tanılamadır, temiz test
  değildir.
- Yeni ayrıştırıcı (v2) varsayılan oldu. Mevcut `ev2` pilotu v1 verisiyle eğitilmiş modelini korur; v2 verisi için
  pilotun ayrı bir klasöre yeniden hazırlanması gerekir.

## I. Çalıştırılan testler ve deney bütçesi

- **Gerçek veride yalnızca iki çalıştırma yapıldı:**
  1. Özgün walk-forward tekrarı (`pilot-tani`): kayıtlı doğrulamanın birebir yeniden üretimi.
  2. Düzeltilmiş karşılaştırmalı tekrar (`pilot-tani --ayristirici openfootball-sonuc-v2`): izinli tek tekrar.

  Başka model eğitimi, seed araması, sezon kombinasyonu veya varyant denemesi yapılmadı.
- **Bağımsız denetimler** (39 ajan) yalnızca kayıtlı çıktılar, kayıtlı parametreler ve özellik hesabı üzerinde çalıştı.
  168 denetim betiği tarandı; hiçbirinde model eğitimi yok.
- **Önceden kaydedilmemiş ek analizler sonradan yapıldı ve öyle işaretlendi:** 2023 hariç duyarlılık, eşleştirilmiş
  aşama farkı aralıkları (ajan tohumu 777, 2000 tekrar), sezon ortalaması kehanet düzeltmesi, sezon kümeli t.
- **Sentetik testler:** `tests/test_s4_model.py` içinde 27 test. Kapsadıkları:
  - bağımsız ölçütlerin kütüphanelerle uyumu;
  - ters, sabit, dar ve ayrışmalı tahminler; geçersiz olasılık ve eksik hedef;
  - sezon kaymasının toplu eğimi negatife çevirebilmesi;
  - A/B/C etiketleri ve pozitif sınıf yönü;
  - aşama çalıştırmasının ürün walk-forward'ıyla bit düzeyinde aynı olması;
  - aşama ilişkileri ve satır sırasından bağımsızlık;
  - gelecek bilgisi sızıntısı;
  - aracın girdi kökeni ve çıktı klasörü reddi;
  - pilot dosyalarının korunması;
  - karşılaştırmalı tekrar;
  - v1/v2 köken doğrulaması;
  - MS 0-0 İY'sinin etiket ve özelliklere etkisi.

  `tests/test_s4_pilot.py` içindeki 0-0 testi v1 ve v2 beklentileriyle genişletildi; assertion kaldırılmadı. Yeni skip,
  xfail veya tolerans genişletmesi yok.
- Yerel tam paketin ve CI'ın gerçek sonuçları oturum yanıtındadır; bu dosya kendi commit'inin sonucunu iddia etmez.

## J. Commit, uzak SHA ve CI

- Kod commit'i `469261eaf8a942875c1d70ea4e009836525c1cc4`: tanılama aracı ve sabit tahmin düzeltmesi. Ubuntu CI
  (run 38097808123) başarılı.
- İkinci commit: kalan eğim düzeltmeleri, ayrıştırıcı v2, karşılaştırmalı tekrar ve bu rapor. SHA ve Linux/Windows CI
  durumu oturum yanıtında verilir.
- Gerçek veri, model ve ayrıntılı tanılama çıktıları (`asamalar.csv`, `tani.json`, denetim betikleri) yalnızca oturumun
  geçici çalışma alanında. Kalıcı bir hedefe aktarılmadı; kod push'u bu dosyaların yedeği değildir.

## Tek sonraki adım

Kanıt, M0'a göre kaybın S2 lojistik katmanında, lig düzeyi zaman özelliklerinin sezon düzeyindeki kaldıraç etkisiyle
oluştuğunu gösteriyor. M10'un yapısal katmanı (S1) ise M0 ile karşılaştırılabilir.

**Önerilen adım:** ayrı ve önceden kaydedilmiş tek bir model kararı. Tek lig pilotunda S2'nin B/C hedef katmanı, yalnızca
zamanla değişen lig düzeyi özellikleri (bA, bB, bC, s1, season_n) kullanmasın.
- Başarı ölçütü ve karşılaştırma (M0 ve mevcut M10) kayıt altına alınmadan önce tanımlanmalı.
- Değerlendirme yalnızca bu görevde görülmemiş ileriye dönük maçlarla yapılmalı, v2 verisiyle yeniden hazırlanmış ayrı bir
  pilotta.
- Beklenti en fazla M0 ile karşılaştırılabilir olmaktır: sezon içi ayırt etme gücü bütün aşamalarda yaklaşık 0,53. Bu adım
  avantaj vaat etmez ve FORECAST_OPERATION engelini kaldırmaz.

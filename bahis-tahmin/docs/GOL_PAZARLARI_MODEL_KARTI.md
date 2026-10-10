# Model kartı — gol pazarları (`goal-joint-1.0` / `M10_ipf_kosullu`)

| | |
|---|---|
| Model sürümü | `goal-joint-1.0`, özellik sürümü `goal-feat-1.0`, motor sürümü 1, sonuçlandırma kuralı `std-v1` |
| Seçilen varyant | `M10_ipf_kosullu` |
| Pazarlar | A: iki yarıda da karşılıklı gol – Evet · B: maç sonu 3,5 Üst · C: ilk yarı 1,5 Üst (ve tümleyenleri) |
| Amaç | Maç öncesi olasılık tahmini ve sanal (paper) takip. **Gerçek bahis önerisi veya kâr iddiası değildir.** |
| Olasılık üreticisi | Yalnızca istatistiksel model; dil modeli (LLM) kullanılmaz |
| Kod | `bahis_tahmin/goals/` (joint, features, model, validation, engine, decision, value, ledger, service) |

## 1. Yapı

1. **Özellikler (yalnızca maç gününden önceki veriler):** her lig için ilk yarı, ikinci yarı ve maç sonu
   ayrı zaman ağırlıklı Poisson takım güçleri (atak/savunma, ev avantajı; ilk yarıda düşük skor düzeltmesi),
   bunların standart hataları, ligin zaman ağırlıklı ilk yarı gol payı ve A/B/C taban oranları, takımların
   yakın dönem yarı bazlı gol atma/yeme sıklıkları, dinlenme günleri, sezon içi maç sayısı.
2. **Yapısal ortak dağılım (M5):** dört yarı-takım gol yoğunluğu, yarıya özel ve maç sonu güç tahminlerinin
   log-doğrusal karışımıdır (katsayılar ortak olabilirlikle öğrenilir). İkinci yarı, ilk yarı skor durumuna
   (9 durum) bağlı çarpanlarla koşulludur; ortak tempo için gama kırılganlığı (φ) vardır. Tüm pazarlar bu
   tek ızgaradan hesaplanır.
3. **Marjinal kalibrasyon (M9 adımı):** B ve C için pazar başına düzenlileştirilmiş lojistik regresyon
   olasılıkları hedef alınır; ortak dağılım B/C 2×2 bölgelerinde üstel eğimle (IPF) bu hedeflere eşitlenir.
4. **Koşullu pay kalibrasyonu (M10):** A = P(B∩C) · q, q = P(A | B∩C); q iki parametreli lojistikle yalnızca
   B ve C'nin birlikte gerçekleştiği eğitim maçlarında kalibre edilir.

Sonuç: her maç için A ≤ P(B∩C) ≤ min(B, C) yapısal olarak sağlanır; kırpma kullanılmaz. Ek çıktılar: P(B∩C),
P(A | B∩C), dört koşulun (ev/deplasman × 1./2. yarı gol) olasılıkları, araştırma pazarları (maç sonu KG,
İY KG, 2. yarı 1,5 Üst, 2,5/4,5 Üst) — son grup öneri motoruna kapalıdır.

## 2. Veri

| | |
|---|---|
| Geliştirme/test verisi | 22 lig (İngiltere 5, İskoçya 4, Almanya 2, İtalya 2, İspanya 2, Fransa 2, Hollanda, Belçika, Portekiz, Türkiye, Yunanistan), **184.378 maç**, 28.07.2000 – 03.09.2026 |
| Kaynak | GitHub yedek veri seti (football-data.co.uk kaynaklı). football-data.co.uk bu ortamdan erişilemedi (vekil sunucu 403) |
| Sezon kapsamı | çoğu ligde 26–27 sezon (2000/01–2026/27); EC 16, G1 19 sezon. **30 sezon hedefi karşılanamadı** (`DATA_BLOCKED`) |
| İlk yarı skoru | 184.378 maçın 102'sinde eksik; karantina (çelişkili kayıt) 0 |
| Gerçek oran | A/B/C için **0** maç; 2,5 Alt/Üst için 156.685 maç (kullanılmadı) |
| Veri özeti (SHA-256) | `reports/goal_test_results.json` → `data.sha256` |

## 3. Eğitim, kalibrasyon ve test tarihleri

| Aşama | Dönem |
|---|---|
| Isınma (yalnızca güçlerin oturması) | 2000/01 – 2002/03 |
| Eğitim | her test sezonu Y için 2003/04 ≤ sezon < Y (genişleyen pencere) |
| Geliştirme / model seçimi | 2008/09 – 2018/19 (82.991–83.048 değerlendirilebilir maç) |
| Kalibrasyon | eğitim penceresinin içinde (lojistik hedefler ve q-kalibrasyonu yalnızca eğitim satırlarıyla) |
| Kapalı final test (tek sefer) | 2019/20 – 2026/27 (52.902–52.940 maç; 2026/27 veri sonuna kadar kısmi) |
| Ön-kayıt | seçim ve kural, test çalıştırılmadan önce `reports/experiments.jsonl` dosyasına yazıldı |

## 4. Sonuçlar — kapalı final test (2019/20 – 2026/27)

Referans: M0 = ligin zaman ağırlıklı geçmiş taban oranı. Δ = log-kayıp farkı (negatif = daha iyi),
köşeli parantez: ISO hafta blok bootstrap %95 aralığı.

| Pazar | n | Gerçekleşen | Taban oran | Δ LL (M10 − M0) | Brier becerisi | Kal. eğimi | ECE | Kural v1 |
|---|---|---|---|---|---|---|---|---|
| A: iki yarıda KG | 52.902 | 2.701 | %5,11 | −0,00084 [−0,00132, −0,00041] | +%0,16 | **0,788** | 0,0028 | **Geçmedi** (eğim < 0,80) |
| B: 3,5 Üst | 52.940 | 14.984 | %28,30 | −0,00569 [−0,00658, −0,00488] | +%1,18 | 1,048 | 0,0062 | Geçti |
| C: İY 1,5 Üst | 52.902 | 17.771 | %33,59 | −0,00331 [−0,00397, −0,00273] | +%0,67 | 1,048 | 0,0081 | Geçti |

Diğer modeller (aynı test): M5 yapısal model B'de Δ −0,00263 (eğim 0,77), C'de −0,00186 (eğim 0,79),
A'da −0,00025 [−0,00096, +0,00042] (anlamsız). Ayrı lojistik C1, B ve C'de M10 ile aynı (M10 bu marjinallere
eşitlenir), A'da Δ −0,00079, eğim 0,89 — ancak C1 pazarlar arası tutarlılığı garanti etmez. Tutarlılık
ihlali (A>B, A>C, [0,1] dışı): tüm modellerde 0.

**Yorum:** Model taban orandan istatistiksel olarak anlamlı biçimde daha iyi, ancak fark **küçüktür**
(Brier becerisi %0,2–1,2). Olasılıklar çoğunlukla taban oran civarında kalır; maçlar arasında ayırt etme
gücü sınırlıdır (A için ortalama kesinlik 0,063'e karşı taban 0,057). Bu düzeyde bir olasılık iyileşmesinin
bahis piyasasına karşı kâra dönüşüp dönüşmediği **bilinmiyor**: bu pazarlar için gerçek oran verisi yoktur.

### Mevcut uygulama maç motoru ile karşılaştırma (yalnızca B)

Mevcut maç motorunun örneklem dışı 3,5 Üst olasılığı (`pmk_O3.5`: Dixon-Coles skor matrisi, model ve
**maç öncesi 1X2 + 2,5 Alt/Üst piyasa oranlarıyla** karıştırılmış 1X2/2,5/KG marjinallerine uyarlanmış),
aynı genişleyen pencere kuralıyla 2016/17'den itibaren yeniden üretildi
(`tools/research/engine_oos_b.py`, karşılaştırma `tools/research/compare_engine_b.py`,
sonuç `reports/goal_test_vs_engine_b.json`). Final testin 52.940 maçının tamamı eşleşti.

| Model | Log-kayıp | Δ taban orana göre [%95] | Δ mevcut motora göre [%95] | Kal. eğimi | ECE |
|---|---|---|---|---|---|
| M0 taban oran | 0,59045 | — | +0,00855 [+0,00734, +0,00990] | 0,969 | 0,0068 |
| **M10 (gol modeli)** | 0,58476 | −0,00569 [−0,00658, −0,00488] | **+0,00286 [+0,00213, +0,00347]** | 1,048 | 0,0062 |
| **Mevcut maç motoru** | **0,58190** | −0,00855 [−0,00990, −0,00734] | — | 0,906 | 0,0074 |

**Sonuç: 3,5 Üst için mevcut maç motoru final testte gol modelinden anlamlı biçimde daha iyidir.**
Muhtemel neden, mevcut motorun piyasa oranlarını (özellikle 2,5 Alt/Üst) kullanması; gol modeli hiçbir
oran kullanmaz. Ön-kayıt gereği model bu sonuca bakılarak değiştirilmedi. A ve C için mevcut motorda
karşılık yoktur (ilk yarı modeli yoktu). Önerilen sonraki adım: 2,5 Alt/Üst piyasa olasılığını
kalibratöre ekleyen bir varyantın geliştirme döneminde denenmesi ve **yeni** bir bekletme döneminde
(ör. ileriye dönük sanal takip) değerlendirilmesi — mevcut final test artık "görülmüş" sayılır.

## 5. Doğrulama statüsü

| Pazar | Final test (kural v1) | Statü |
|---|---|---|
| A | eğim 0,788 < 0,80 | `MODEL_NOT_VALIDATED` — öneri motoru bu pazarda aday üretmez |
| B | tüm koşullar sağlandı (taban orana göre); **mevcut maç motoru daha iyi** (bkz. §4) | `VALIDATED_FOR_PAPER_TRADING` (yalnızca olasılık kalitesi, taban orana göre) |
| C | tüm koşullar sağlandı | `VALIDATED_FOR_PAPER_TRADING` (yalnızca olasılık kalitesi) |

Uygulama, kullanıcının kendi verisiyle her eğitimde aynı kuralı **son 3 sezon + güncel sezon** üzerinde
yeniden uygular ve statüyü buna göre belirler (veri değişirse statü değişebilir).

**Uygulama içi eğitim denemesi** (aynı 184.378 maç, geçici dizinde; `GoalEngine.train`): süre ~466 sn
(4 çekirdekli Linux, başka işlerle eşzamanlı), iç doğrulama sezonları 2023/24–2026/27:

| Pazar | n | Δ LL [%95] | Eğim | ECE | Statü |
|---|---|---|---|---|---|
| A | 22.975 | −0,00090 [−0,00160, −0,00023] | 0,752 | 0,0039 | `MODEL_NOT_VALIDATED` |
| B | 22.977 | −0,00750 [−0,00890, −0,00613] | 1,060 | 0,0119 | `VALIDATED_FOR_PAPER_TRADING` |
| C | 22.975 | −0,00465 [−0,00563, −0,00359] | 1,068 | 0,0121 | `VALIDATED_FOR_PAPER_TRADING` |

Bu sezonlar final test döneminin alt kümesidir (bağımsız ikinci bir test değildir); amaç, uygulamanın
statü hesaplamasının final testle tutarlı olduğunu göstermektir.

## 6. Belirsizlik

%80 aralık: takım gücü standart hatalarından log-normal Monte Carlo (200 çekiliş, tohum 20261010).
İlk ve ikinci yarı hataları bağımsız; maç sonu hatası yarı hatalarının yoğunluk ağırlıklı birleşimi
(λ_MS ≈ λ_İY + λ_2Y), kendi standart hatasına ölçeklenir. Kalibratör katsayı belirsizliği yok sayılır.
2026/27'nin ilk 200 maçında medyan genişlik: A 0,036 · B 0,132 · C 0,104 (B'de maçların %9,5'i 0,25
sınırını aşar → `HIGH_UNCERTAINTY`). İlk sürümdeki bağımsız bozma B için medyan 0,30 veriyordu; düzeltme
final testten sonra yapıldı ve olasılıkları/test ölçütlerini değiştirmez (`reports/experiments.jsonl`). Karar motoru alt sınırı (p_safe) kullanır;
aralık genişliği > 0,25 ise öneri yok.

## 7. Sınırlamalar

- Kadro, sakatlık, xG, hava durumu, motivasyon verisi yok (doğrulanmış ücretsiz kaynak bulunamadı).
- Geçmiş verinin yayımlanma zamanı doğrulanamaz; geçmiş testte karar anı "maç günü 00:00" varsayılır.
- Geliştirme döneminde çok sayıda varyant denendi; final test ayrı tutuldu ancak çoklu karşılaştırma
  düzeltmesi yapılmadı.
- Kupa maçları, uzatmalar ve hükmen sonuçlar veri setinde ayrıca işaretli değildir; `fthg/ftag` normal süre
  kabul edilir.
- Ligler arası farklar: düşük veri hacimli liglerde (EC, G1) takım güçleri daha belirsizdir.
- **Gerçek oranlı ROI/CLV hesaplanamadı** (bkz. `LISANS_DENETIMI.md`).

## 8. Kullanım dışı

Kesin sonuç iddiası, gerçek para yönetimi, otomatik bahis, kombine kupon olasılığının bağımsız çarpımla
hesaplanması (aynı maçtaki A, B, C güçlü biçimde bağımlıdır).

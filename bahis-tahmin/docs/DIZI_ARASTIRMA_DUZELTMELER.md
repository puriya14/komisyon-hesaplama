# Dizi araştırması — düzeltme ve daraltma kaydı (S2-KABUL-01)

Belge sürümü **1.1** (10.10.2026). Kapsam: [`DIZI_ARASTIRMA_SONUCLARI.md`](DIZI_ARASTIRMA_SONUCLARI.md) sürüm 1.0
(commit `01b7e9f`) ve aynı görevin son raporu. Önceki metinler **değiştirilmedi**; her düzeltme burada kimliği,
eski ifadesi, durumu, yeni ifadesi ve kanıtıyla kayıtlıdır. Sonuç belgesinin başına yalnızca bu kayda işaret eden bir
not eklendi. Temizlenmiş kanıt özetleri: [`reports/kabul_s2_01/`](../reports/kabul_s2_01/). Ham denetim kanıtları paylaşım kapsamı dışında, yalnızca yerel ortamda tutulmaktadır. Public depo temizlenmiş özetleri içerir.

Durumlar: **DOĞRULANDI** (iddia kanıtla tutarlı), **DARALTILDI** (iddia daha dar koşullarda doğru),
**DÜZELTİLDİ** (iddia yanlıştı), **DOĞRULANAMADI** (gerekli kanıt yok veya erişilemedi). Raporun varlığı içindeki
sonucun doğrulandığı anlamına gelmez; negatif araştırma sonucu yazılım hatası değildir.

## 1. Özet cümleleri

| # | Eski ifade (yer) | Durum | Yeni ifade |
|---|---|---|---|
| D-01 | "log-kayıp katkısı ihmal edilebilir düzeyde (yaklaşık −0,00005; üçünde güven aralığı 0'ı içeriyor)" (SONUÇLAR özet) | DARALTILDI | Test döneminde (2019/20–2025/26) gösterge eklenmesi log-kaybı S0 + sabit modeline göre −0,000042 ile −0,000102 nats/satır değiştirdi (ortanca −0,000055, ortalama −0,000064; göreli %0,007–%0,017). ΔLL = aday_model − referans; negatif aday lehinedir. Üç adayda lig-sezon kümeli %95 aralık 0'ı içeriyor. GALIBIYET \| RAKIP_SON5_IY_ONDE_EN_AZ_3 adayında aralık [−0,000197; −0,000010] 0'ı dışlıyor; bu aday başına ve **çoklu karşılaştırma düzeltmesiz** bir aralıktır (dört aday üzerinde Holm tek yönlü p = 0,072). Ekonomik önemi değerlendirilemez (oran zamanı doğrulanamaz; aday sonuçlardan sonra seçildi, en fazla EXPLORATORY). |
| D-02 | "dördü de piyasa kontrolünde (S0p) kayboldu … bahis piyasası bunu zaten fiyatlıyor" (SONUÇLAR özet, F1) | DARALTILDI | Dört adayın hiçbiri örneklem dışında ek değer göstermedi. Statüyü belirleyen, kayıtlı ilk başarısız kontroldür: üç adayda test ΔLL aralığının 0'ı içermesi, birinde parametre döneminde 7b/2. 7b/5 (piyasa kontrolü) dört adayda iki dönemde de geçmedi; ancak 7b/5 çıkarılınca da statüler aynı kalır. Piyasa kontrolü zamanı doğrulanmamış tarihsel oranlarla (`HISTORICAL_REFERENCE_ONLY`) ve sonuçlardan sonra değişen S0p tanımıyla (D-20) yapıldı. "Piyasa bunu zaten fiyatlıyor" bu veriyle kanıtlanmış bir genel ifade değildir; yalnızca "geçmiş tek bahisçi oranlarına göre kurulan S0p kontrolünde etki 1'i dışlamadı" denebilir. |
| D-03 | "İY/MS 2/1 tipi … hedeflerde hiçbir koşul anlamlı değil" (SONUÇLAR özet ve F1) | DARALTILDI | Desteklenen hipotezlerde en büyük \|z\| 2,63 (İY geride→MS galip) ve 2,35 (İY önde→MS mağlup); aile düzeyinde anlamlılık eşiği yaklaşık \|z\| 3,98 (WY, R = 1000). Keşif tasarımı %80 güçte bu hedeflerde ancak yaklaşık ±%50'lik göreli sapmaları (ortanca) saptayabilirdi; daha küçük etkilerin yokluğu gösterilmedi. Önceden tanımlanmış pratik önem eşiği yoktur. Sentetik pozitif kontrolde (bölüm 4) büyük ekili etki 3 tohumun 2'sinde, ×1,3'lük etki hiç yakalanmadı. |
| D-04 | "en büyük \|z\| 2,6 (referans süreçte rastgele en büyük \|z\|'nin medyanı 3,1)" (F1) | DARALTILDI | 2,6 yalnızca desteklenen hipotezler içindir (desteklenmeyen küçük hücrelerde \|z\| 7,2'ye çıkar); 3,1 tüm F1 ailesinin (dört hedef) tekrar başına en büyük \|z\| ortancasıdır; karar eşiği ≈ 3,98. |
| D-05 | "Tekrar eden ilişki … temel gol modelinin formu geç yansıtması" (F3) | DARALTILDI | Bu bir yorumdur; F3 önceden görülmüş ailedir (en fazla EXPLORATORY) ve S1/GALIBIYET'in statüsü yalnızca sonradan değişen S0p'ye dayanır (D-20). |
| D-06 | "%12,7 S0 beklentisi" (F1 okuma notu) | DARALTILDI | Test döneminde 3.110 maçın 346'sı (%11,1) mağlubiyet; katman içinde yeniden kalibre S0 beklentisi %12,7 (E_adj), ham S0 beklentisi %13,0. |
| D-07 | "Referans süreç güvenilir kabul edildi" (F7, 0/20) | DARALTILDI | 0/20: tohumlar bağımsız sayılırsa tohum başına keşif olasılığı için %95 üst sınır tek yönlü 0,139, iki yönlü 0,168. Tohumlar aynı sonuçları ve S0'ı paylaştığı için bu sınır iyimserdir (etkin n = 5 için 0,451). Kural (en fazla 1 keşif) kalibre bir süreçte 0,736 olasılıkla geçilir. Plasebo keşif kuralı (p_adj < 0,05) F1'in katı kuralından gevşektir (kontrol bu yönde muhafazakâr). |

## 2. Veri kapsamı ve süreklilik

| # | Eski ifade | Durum | Yeni ifade |
|---|---|---|---|
| D-08 | "22 lig, 184.378 maç, 28.07.2000–03.09.2026" | DOĞRULANDI | Aynı. İçerik özeti `6ca929a2…` CSV'den yalnızca `time` metin olarak okunup boşlar "" yapıldığında yeniden üretilir; düz okuma `aff287d6…` verir (içerik aynı, temsil farkı). Bellekte ham dosyadan kurulan tablo doğrudan `6ca929a2…` verir. |
| D-09 | "59 lig-sezonda veri boşluğu" | DARALTILDI | Verideki 567 lig-sezon etiketinin 59'u kısmi (proje kuralına göre planlanan normal sezon maçlarının %97'sinden azı). Ayrıca 2000/01–2025/26'da 27 lig-sezon veride hiç yok; "tam" sayılan 13 lig-sezonda 41 takım-sezon eksiği var. Beklenen maç sayısı projenin türettiği format kuralıdır, resmî fikstür değildir. |
| D-10 | (sezon sayısı) | DARALTILDI | 2000/01–2025/26 arasında 572 olası lig-sezonun 545'i veride, 486'sı tam; ligine göre 13–24 tam sezon; hiçbir ligde 26 tam sezon yok; 2026/27 devam ediyor. "30 sezon" iddiası yayımlanmış belgelerde yok (model kartı hedefin karşılanmadığını yazıyor). |
| D-11 | Mod A "olaylar arası maç" (PSV örneği dahil) | DÜZELTİLDİ (kod) | Aralık veride **gözlenen** lig maçı sayısıdır; aradaki eksik maçlar sayılmaz, bilinmeyen sonuçlar olaysız sayılır. Gerçek veride tamamlanmış aralıkların yaklaşık %16'sı (1.215/7.690 ve 1.245/7.652) bir veri boşluğundan geçer. Mod A artık her aralığa boşluk işareti ekler (`aralik_durumu`); ≥%97 tam sezonlardaki tekil eksikler fikstür listesi olmadan işaretlenemez. |
| D-12 | "Pencere, dokunduğu lig-sezon tam değilse tanımsızdır" | DÜZELTİLDİ (ifade); kod açık | Bu kural yalnızca 5/10'luk tarih atomları için geçerlidir ve planlanan maçların ≥%97'si bulunan sezonlardaki eksikleri ve üst tur maçlarını bayraksız atlar. S1/S2 sürekli özellik pencereleri eksik lig-sezonları hiç kesmez (S0 koşulu hariç uygun satırların k=10 için 5.317/320.809'u; keşif 752, test 894). Kodu düzeltmek araştırma yöntemini test açıldıktan sonra değiştirir; bu görevde yapılmadı, yeni sürümde ele alınmalı. |
| D-13 | PSV: "850 maç; 25 ham 2/1 (19/6); ilki 08.02.2004; son 04.04.2026; 9 maçlık açık aralık; resmî kaynakla çapraz kontrol yapılmadı" | DARALTILDI | Sayılar kaynak veriyle yeniden üretildi. PSV'nin N1 sezonlarında 30 maç eksik (2002/03 14/34, 2004/05 26/34, 2007/08 32/34); 25 bu veri için geçerlidir (gerçek sayı en az 25), 24 aralıktan 3'ü bu boşluklardan geçer; 9 maçlık açık aralık boşluksuzdur. Önceden kaydedilmiş 5 maçlık örneklemde 4 maç dış kaynakla eşleşti (biri resmî kulüp sitesi, üçü ikincil kaynak; yalnızca arama özetleri, sayfalar açılamadı), 1 maçın (08.02.2004) İY skoru bulunamadı. |

## 3. Oranlar, zaman ve haklar

| # | Eski ifade | Durum | Yeni ifade |
|---|---|---|---|
| D-14 | "Bet365 kapanış oranlarının yayımlanma zamanı doğrulanamadığı için" (F6) | DÜZELTİLDİ | Ayna README'sine göre Bet365 olan 1X2 oranlarının açılış/kapanış niteliği ve alınma zamanı belirtilmemiştir; maç başına zaman damgası yoktur. Statü: `HISTORICAL_REFERENCE_ONLY` (artık piyasa kontrolü çıktılarında ve manifestte yazılıdır). |
| D-15 | "Bet365 1X2 oranları (satırların yaklaşık %99,8'inde)" | DARALTILDI | 1X2 oranı tüm veride maçların %98,35'inde, araştırma dönemlerinde (2006/07–2025/26) %99,8–99,9'unda, 2000/01–2005/06'da %92'sinde var. A/B/C ve İY/MS oranı yoktur; 1X2'den türetilmez. |
| D-16 | "S0p / marjsız Bet365: bahis yok" (F6) | DARALTILDI | Marjsız Bet365 referansı tanımı gereği hiç bahis üretemez (en küçük marj 1,0102 ⇒ EV < 0); S0p'nin 0 bahsi ampiriktir. |
| D-17 | Ana uygulama: "Piyasa ortalaması" | DÜZELTİLDİ (arayüz) | Yedek (GitHub) veri setinde "ortalama" oran tek bahisçinin (README'ye göre Bet365) oranıdır; etiket ve açıklama buna göre değiştirildi. |
| D-18 | Veri hakları | DOĞRULANAMADI | football-data.co.uk belgelerine erişilemedi; erişim, otomatik indirme, model eğitimi ve yeniden dağıtım hakları belgeyle doğrulanamadı. Ayna deposunun MIT lisansı yalnızca xgabora'nın katkısını kapsar; verinin kaynağı football-data/ClubElo'dur. openfootball CC0 1.0'dır ancak madde 4(c) gereği üçüncü taraf hakları temizlenmemiştir. Araştırma verisi, uygulamanın kullanıcı onay kapısı çalıştırılmadan geliştirici betiğiyle yüklendi; diskte onay kaydı yok. |
| D-19 | Ham dosyanın alınma zamanı ("05:18 UTC") | DÜZELTİLDİ | Ham ayna dosyası ~03:33:36 UTC'de indirildi; 05:18 UTC araştırma deposunun kurulma (kopyalama) zamanıdır. Yukarı akış commit'i kaydedilmedi. |

## 4. Test bağımsızlığı ve ön-kayıt

| # | Eski ifade | Durum | Yeni ifade |
|---|---|---|---|
| D-20 | `RUN_DECISIONS['s0p_tanimi']`: S0p değişikliği "models gözden geçirmesinde sentetik veride gösterilen zayıflık nedeniyle" | DÜZELTİLDİ | S0p'ye S0 sıcaklığı 09:46:11 UTC'de eklendi. Bundan önce bir inceleme alt ajanı gerçek veride F3 parametre/test sonuçlarını gördü (eski S0p ile S1/GALIBIYET destekli ve 7b/5 geçmişti) ve sıcaklıklı alternatifi gerçek veride (test dönemi dahil) karşılaştırdı; sentetik gösterim bundan sonra yapıldı. Değişiklik muhafazakâr yöndeydi ve F1 7b/5'e, 10:01:59'da da F4 7b/5'e yayıldı (önceki beyandaki "09:4x" saati yanlış). F1 ve F4 statülerini belirlemedi; F3 S1/GALIBIYET'in statüsü yalnızca bu değişikliğe bağlıdır. Ek kayıt `reports/experiments.jsonl` sonuna eklendi; özgün kayıt değişmedi. |
| D-21 | "Test dönemi temiz mi: F1, F2, F4, F7: evet" | DARALTILDI | F1/F2/F4/F7 istatistikleri gerçek S0'a göre ilk kez resmî çalıştırmada hesaplandı (keşifte sahte S0 ile F1/F2 türü çıktılar önceden görüldü). F7 ve F2'nin statüleri yalnızca keşif döneminde belirlenir. F1 ve F4'ün test iddiaları koşulludur: S0'ın İY/MS kalibrasyonu 2019+ döneminde görüldü (07:21 UTC) ve 9 hücreli kalibratör biçimi bu bulguyu da gerekçe gösteren bir öneriyle seçildi; 7b/5 tanımı F3'ün gerçek test sonuçlarından sonra değişti. |
| D-22 | Ön-görülme beyanı (09:37:02) ve "toplu frekanslar, PSV listesi, 2019+ kalibrasyon görüldü" | DARALTILDI | Beyan dışında kalanlar: S0p değişikliği ve yeni F3 sayıları; anomali sayılarının (845/761/635) resmî çalıştırmadan önce görülmesi ve seçim kuralının gerçek veride görülen aşırı işaretlemeden sonra sözleşme tanımına uydurulması; piyasa ondalığına göre İY/MS oranları ve takım/lig geri dönüş oranları; sahte S0 keşif çıktılarının orkestratörce okunması. |
| D-23 | "Yeni çalıştırma farklı kodla yapılırsa otomatik temiz test değil" | DARALTILDI → DÜZELTİLDİ (kod) | Eski mekanizma yalnızca `sequences` kodu, parametre özeti ve uygulama kararlarındaki değişikliği yakalıyordu; aynı kodla sonradan yapılan tekrar "temiz" görünüyordu. Artık test açılışından (10:36:06 UTC) sonra başlayan her gerçek veri çalıştırması "yeniden üretim" olarak temiz değildir. Veri ve S0 değişikliği hâlâ ayrıca karşılaştırılmıyor; erişim geçmişi manifesti önerisi hazırlandı (oturum referansları içerdiği için yalnızca yerelde). |
| D-24 | `TEST_OPENED.zaman_utc` 10:36:06 | DARALTILDI | 10:36:06 F1'in resmî kaydıdır; test dönemiyle ilk temas daha önce gerçekleşti (07:21 toplu S0 kalibrasyonu; 09:01 F3). |
| D-25 | Ara commit `d57eea7` | BİLGİ | Mutasyon testi sürerken alındı ve `hazard.py`'nin geçici mutantını içerir; resmî çalıştırmayı (`398b60b`) etkilemedi. |

## 5. Anomali incelemesi

| # | Eski ifade | Durum | Yeni ifade |
|---|---|---|---|
| D-26 | "toplam 1.600 kayıt (sürpriz 845, piyasa farkı 761)" | DOĞRULANDI + DARALTILDI | 1.600 maç = 845 sürpriz + 761 model–piyasa farkı bayrağı; 6 maç iki bayraklı. Seçim kuralı her lig-sezonda havuz büyüklüğüne bağlı **sabit sayıda** maç işaretler (101–300 maç: 1; 301–500: 2; 501–700: 3); 845 ve 761 bir yaygınlık tahmini değildir. Uygun maskeye girmediği için raporlanmayan bayraklı maçlar var (en az 11 sürpriz, 69 piyasa farkı). |
| D-27 | "lig değişikliği sonrası ilk maçlar (353 kaydı açıkladı), kırmızı kart (121 kaydı açıkladı; 429 kayıtta veri yok)" | DARALTILDI | Sayılar farklı havuzlara aittir: 353, 1.600 kaydın tümünde (sürpriz 94, piyasa farkı 261) takımlardan birinin lig değişikliğinden sonraki ilk 8 maçında olmasıdır; 121, 845 sürpriz kaydında maçta kırmızı kart bulunmasıdır; kırmızı kart kontrolü 845 sürpriz kaydının 616'sında çalıştı, 229'unda veri yoktu (429, tüm kayıtlardaki sayıdır). "Açıkladı" yerine: **alternatif açıklamayla uyumlu (nedensellik sınanmadı)**. 210 = 109 yalnız kırmızı kart + 83 yalnız lig değişikliği + 11 ikisi + 6 takım adı + 1 takım adı ve kırmızı kart. |
| D-28 | "Açıklanamayan 635 sürpriz kaydının çoğu ham İY/MS 1/2 (619) ve 2/1 (218)" | DÜZELTİLDİ | 619 ve 218, 845 sürpriz kaydının tamamına aittir. Çalıştırılabilen kontrollerin hiçbirine uymayan 635 kaydın 476'sı ham 1/2, 153'ü 2/1'dir. |
| D-29 | Tür adı `UNEXPLAINED_ANOMALY` | DARALTILDI | Tür adı açıklama durumundan bağımsız olarak her sürpriz adayına verilir (sözleşme §11 anlamında açıklanamayan 635'tir). Kayıtlı değerler değiştirilmedi; arayüzde nötr Türkçe etiketler gösterilir ("Sonuç sürprizi (lig-sezon üst sırası)", "Sürpriz değeri (bit)"). Anomali çıktısını okuyan maç öncesi/tahmin yolu yoktur (artık testle korunuyor); eşikler sezonun sonraki maçlarını da kullandığı için görünüm geriye dönüktür. |

## 6. Yazılım ve süreç

| # | Eski ifade | Durum | Yeni ifade |
|---|---|---|---|
| D-30 | "İlk CI'da altın test 1e-7 toleransını ~1e-6 farkla aştı" / test yorumu "CI'da gözlenen en büyük fark 4,1e-6" | DÜZELTİLDİ | İlk CI'da fark A'da 1,54e-6, A aralığında 4,07e-6 idi; aynı hesaplama yolunda testin karşılaştırdığı tüm anahtarlarda en büyük fark 9,5e-6'dır (29 yapılandırmada 1,38e-5). Fark model değişikliğinden değil, hesaplama yolundan (OpenBLAS çekirdeği + numpy SIMD) gelir; yerelde bit düzeyinde yeniden üretildi. Etiketler ve sonuçlandırma birebir. |
| D-31 | "Ana modele dokunuldu mu: Hayır; altın regresyon testiyle korunuyor" | DARALTILDI | Ana model sentetik altın senaryoda davranış olarak değişmedi (aynı makinede fark 0). Altın test 5e-5'ten büyük sapmayı yakalar; daha küçük model değişikliklerini yakalamaz. 5e-5'lik fark gerçekçi oran ızgarasında bazı kararları (çoğu iki yarıda KG pazarında) değiştirebilir; bu durumlar artık karar gerekçesinde `SAYISAL_ESIK_YAKINI` olarak işaretlenir (durum ve eşikler değişmedi). |
| D-32 | Geri alma: "`dizi_arastirma` klasörünü silin" (KULLANIM, README) | DÜZELTİLDİ | Klasör önbellek dışında yeniden üretilemeyen deney geçmişi ve değişmez defter içerir; silmek geri alma yöntemi değildir. Dosya sınıfları ve güvenli geri alma KULLANIM belgesinde. Gol pazarları defteri (`gol_pazarlari.sqlite`) için de silme önerisi kaldırıldı. |
| D-33 | Windows doğrulaması | DOĞRULANAMADI | Bu ortamda Windows yok; Linux ekransız (offscreen) testler Windows doğrulaması sayılmaz. Yalnızca elle tetiklenen, derleme/paket üretmeyen bir Windows test işi CI'a eklendi (çalıştırılmadı). |

## 7. Diğer iddialar (önceki son rapor ve belgeler; 79 iddianın tamamı `reports/kabul_s2_01/denetim/iddia-denetimi/`)

Dağılım: 40 DOĞRULANDI, 26 DARALTILDI, 9 DÜZELTİLDİ, 3 DOĞRULANAMADI, 1 BİLGİ. Yukarıda olmayanlar:

| # | Eski ifade | Durum | Yeni ifade |
|---|---|---|---|
| D-34 | Geri alma: "kod için `e671c8f..01b7e9f` git revert" | DÜZELTİLDİ | Bu aralık `e671c8f`'yi (İY/MS ve dizi temel katmanı) dışarıda bırakır, CI tolerans düzeltmesini (`7437549`) geri alır ve `reports/experiments.jsonl`'den 9 ön-kayıt/aile satırını çalışma ağacından kaldırır. Doğrusu: önce `git log` ile aralığı inceleyin; gerekiyorsa `e671c8f^..01b7e9f`, `reports/` ve deney kayıtları korunarak, commit'ler tek tek. |
| D-35 | "İleriye dönük sanal takip için ayrı bir defter (`dizi_arastirma.sqlite`) kullanılır"; "resmî karar kaydı eklendi" | DÜZELTİLDİ | Sınıflar var ve sentetik testlerle sınanıyor; arayüze/CLI'ye bağlı bir akış yok, dosyalar oluşturulmuyor. İleriye dönük ölçüm artık gol pazarları defterinde `FORECAST_RECORD` ile yapılır (ikinci kayıt sistemi kurulmadı). |
| D-36 | F7: atomlar "daha önceki tarihli" başka bir takımdan | DÜZELTİLDİ | Aynı gün **veya** daha önceki tarihli (keşifte aynı gün payı 0,63). |
| D-37 | "Bir alt ajan F3/F5/F6'yı önceden hesapladı" | DARALTILDI | İki alt ajan gerçek veride (test dahil) hesapladı (08:47–09:02 ve 09:42–09:51); ikincisinin bulgusu üzerine S0p ve F3 statü kuralı değişti. `experiments.jsonl`'deki F3/F5/F6 kayıtlarındaki `temiz_test=true` bu aileler için geçerli değildir (kod bunları zaten en fazla EXPLORATORY'ye indirir). |
| D-38 | "Kalibrasyon kapısı geçti; 8 hücrenin hepsinde O/E aralığı 1'i içeriyor" | DARALTILDI | Kapı yalnızca keşif döneminde uygulandı; ayna simetrisi nedeniyle 8 hücrede 4 bağımsız değer var. Parametre ve test dönemleri için kapı uygulanmadı. |
| D-39 | "yaklaşık 110 yeni test" | DÜZELTİLDİ | Önceki görev boyunca 92 → 242 test (150 yeni; 135 yeni test fonksiyonu). |
| D-40 | "Kırmızı kart 2018 sonrası tam" | DARALTILDI | 2017/18'den itibaren %99,6+ dolu; 2000–2016 arası %35–59. |
| D-41 | "Ana modele/verilere dokunulmadı; mevcut tahminler değişmedi" | DARALTILDI | 1X2 motoru (`models/`) kodu değişmedi; A/B/C tahminleri sentetik altın testte bu ortamda birebir aynı, CI toleransı 5e-5 (bkz. D-31). Altın test 1X2 motorunu kapsamaz. |
| D-42 | "Gerçek veri yalnızca okundu" | DARALTILDI | Kullanıcının kendi uygulama klasörü bu ortamda yoktur; gerçek verinin ortamdaki kopyaları dosya zamanlarına göre değişmedi. |
| D-43 | "CI yeşil (241 geçti, 1 atlandı)" | DARALTILDI | `01b7e9f`'te yalnızca Ubuntu test işi yeşil (aktarılan günlük + yerel yeniden çalıştırma); Windows işi hiç çalışmadı; `e671c8f`'teki ilk CI kırmızıydı. |
| D-44 | Maç öncesi görünüm "yaklaşan maç için" | DARALTILDI | Önceki görevde yalnızca varsayımsal fikstürle denendi. Bu görevde gerçek openfootball fikstürü izole klasörde uygunluk ve kayıt zincirinden geçirildi (veri güncel olmadığı için tahmin yok); dizi maç öncesi görünümü gerçek fikstürle çalıştırılmadı. |
| D-45 | "Aynı veri, kod, manifest ve tohumla sonuçlar birebir tekrarlanır" | DOĞRULANAMADI | Sentetik veride tekrarlanabilirlik testi geçiyor; gerçek veride birebir tekrar `398b60b` kodu ve aynı S0 soy kaydıyla yapılmalıdır (bu denetimde yapılmadı; ayrıca artık yeniden üretim sayılır, D-23). |
| D-46 | Uygulama kararları "ilk sonuçtan önce" kayıtlı | DARALTILDI | F1/F2/F4/F7'nin resmî sonuçlarından önce kaydedildi; F3/F5/F6 ve S0p'ye ilişkin gerçek veri sonuçları bu kayıttan önce görülmüştü. |

Görev metnindeki ifadeler için kısa karşılıklar: "Piyasa bilgiyi zaten içeriyor" → D-02; "Ek değer yok" → "Bu veri
ve deney koşullarında, ön-kayıtlı aileler içinde ek katkı gösterilemedi" (D-02, D-03); "Kalibrasyon kapısı geçti" →
D-38; "Temiz test" → D-21, D-23, D-37; "30 sezon incelendi" → D-10; "Anomaliler açıklandı" → D-27; "Mevcut tahminler
değişmedi" → D-31, D-41.

## 8. Sürüm

- 1.0 — `01b7e9f` (sonuç belgesi).
- 1.1 — bu kayıt (S2-KABUL-01). Sonuç belgesinin gövdesi değişmedi.

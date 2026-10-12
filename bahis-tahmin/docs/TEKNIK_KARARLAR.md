# Teknik kararlar (gol pazarları analiz katmanı)

Her karar: bağlam → karar → sonuç/gerekçe. Tarih: 2026-10-10.

## K1. Mevcut uygulama yeniden yazılmadı; ayrı bir paket eklendi
Maç sonucu motoru (Elo + Dixon-Coles + LR/HGB + piyasa karıştırma), arayüz ve veri katmanı korundu.
Gol pazarları `bahis_tahmin/goals/` altında bağımsız, test edilebilir modüller olarak eklendi; arayüze
tek sayfa (`ui/pages/goals.py`) ve denetleyiciye ayrı model/defter alanları eklendi. Framework,
mikroservis veya veritabanı sunucusu eklenmedi.

## K2. Tek ortak gol dağılımı; pazarlar birbirinden türetilir
A ⊆ B ∩ C ilişkisi nedeniyle pazarlar ayrı modellerle tahmin edilirse P(A) > P(B) gibi tutarsızlıklar
oluşabilir ve bağımsız çarpım yanlış olur. Karar: ilk yarı skor ızgarası × ilk yarı durumuna koşullu
ikinci yarı dağılımından A, B, C, B∩C ve dört koşul aynı olasılık kütlesinden hesaplanır (`goals/joint.py`).
`min()`/kırpma ile "düzeltme" yapılmaz; ilişkiler yapısal olarak sağlanır ve testlerle doğrulanır.

## K3. Marjinal kalibrasyon I-projeksiyon (IPF) ile; A'nın koşullu payı ayrıca kalibre
Geliştirme döneminde yapısal modeller (M1–M8) aşırı güvenliydi (eğim 0,4–0,77); ayrı lojistik modeller
B ve C için iyi kalibreydi ama tutarlılık garantisi vermez. Seçilen M10: ortak dağılım B/C bölgelerinin
2×2 bölümlemesi üzerinde üstel eğimle (IPF) lojistik B ve C marjinallerine eşitlenir; A = P(B∩C)·q,
q = P(A | B∩C) iki parametreli lojistikle (yalnızca B∩C gerçekleşmiş eğitim maçlarında) kalibre edilir.
Böylece A ≤ P(B∩C) ≤ min(B, C) korunur.

## K4. Türetilmiş oran yok
3,5 Üst oranı 2,5'ten, iki yarıda KG oranı maç sonu KG'den, çifte şans 1X2'den türetilmez. Mevcut maç
motorunun "piyasa oranı" matrisi de bu yüzden yalnızca gerçek 1X2 ve 2,5 oranlarını içerecek şekilde
daraltıldı (`models/engine.py: market_odds_matrix`). Gerçek oran yoksa EV/ROI/CLV "hesaplanamıyor"dur.

## K5. "Avantaj yok" geçerli bir sonuç; öneri yalnızca tüm kontroller geçerse
Karar motoru (`goals/decision.py`) sabit öncelikli engelleyicilerle çalışır: pazar desteklenmiyor/maç
başlamış → sonuçlandırma kuralı belirsiz → veri yetersiz → model doğrulanmadı → oran yok → eski oran →
yüksek belirsizlik → olağandışı avantaj (karantina). Beklenen değer, belirsizlik aralığının alt sınırıyla
(p_safe) hesaplanır; eşik %3. Aynı maçtan yalnızca bir aday, günlük/lig başı sınır vardır.

## K6. "En olası" ve "avantaj adayı" ayrı görünümler
Yüksek olasılıklı seçimler genellikle düşük oranlıdır ve avantaj anlamına gelmez. Eski "Banko" sayfası
"En Olası Seçimler" olarak yeniden adlandırıldı; kesinlik iması taşıyan ifadeler kaldırıldı.

## K7. Veri kaynakları açık onayla
Kullanım hakkı belirsiz kaynaklar (football-data.co.uk ve ondan türetilmiş GitHub veri seti) kullanıcı
onayı olmadan indirilmez (`data/source_registry.py`, `ui/consent.py`, `DataStore.update(allowed=...)`).
Açılışta otomatik güncelleme varsayılan olarak kapalıdır; sayfa açmak yeniden eğitim tetiklemez.
VERI-01: model eğitimi ve tahmin için indirme onayından ayrı, açık bir kişisel (ticari olmayan) kullanım beyanı
istenir. Veri denetimi varsayılanı "standart"tır: yalnızca kanıt eksikliği tahmini engellemez, bilinen eksik veri
yalnızca bahis adayını engeller. "Sıkı" mod v2 kurallarını aynen uygular (bkz. `docs/VERI_01.md`).

## K8. Sanal takip: SQLite, yalnızca ekleme, hash zinciri
Kayıtlar karar anında değişmez biçimde yazılır (`goals/ledger.py`). UPDATE/DELETE tetikleyicilerle
engellenir; sonuçlar ayrı olay olarak eklenir; düzeltme gerekçe ister; zincir doğrulanabilir. Dosya
uygulama veri klasöründe ilk kullanımda oluşturulur (mevcut bir veritabanı taşınmaz). Gerçek bahis,
para transferi veya bahis hesabı entegrasyonu yoktur. Kelly yalnızca sanal ve üst sınırlı (çeyrek, %2).

## K9. Model dosyası manifesti
Model dosyaları SHA-256, tür/sürüm, bağımlılık sürümleri, veri manifesti ve doğrulama sonuçlarını içeren
manifestle kaydedilir; uyumsuz/kurcalanmış/manifestsiz dosya yüklenmez (`models/artifacts.py`).
Bu, `joblib` (pickle) yüklemesinin yalnızca uygulamanın kendi ürettiği dosyalarla yapılmasını da sağlar.

## K10. LLM olasılık üretmez
Uygulama hiçbir dil modeli çağırmaz; tüm olasılıklar istatistiksel modellerden gelir.

## K11. Zaman dilimi
Saatler UTC tutulur, Europe/Istanbul gösterilir. Windows'ta `tzdata` paketi gerekir (requirements'ta
yalnızca Windows için); yoksa İstanbul sabit UTC+3 yedeğine düşülür (2016'dan beri yaz saati yok).

## K12. Performans
Yarı bazlı Poisson güçleri günlük yeniden kestirimle hesaplanır; BLAS iş parçacığı sayısı 1'e sınırlandı
(aksi halde küçük matrislerde aşırı abonelik 10× yavaşlatıyordu). Kalibre modelin olabilirliği analitik
gradyanla en büyüklenir. Belirsizlik Monte Carlo'su tek bir vektörleştirilmiş çağrıda yapılır.

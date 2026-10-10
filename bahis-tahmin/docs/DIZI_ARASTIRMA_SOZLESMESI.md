# Araştırma sözleşmesi (ön-kayıt) — maç dizileri, olay öncesi/sonrası, tekrarlama ve anomali

Sürüm: `dizi-sozlesme-v2` · Tarih: 2026-10-10 · Kod: `bahis_tahmin/sequences/` (sayısal parametreler
`bahis_tahmin/sequences/config.py` içinde; bu belgeyle aynıdır, özeti manifestte).

**Süreç:** v1 taslağı, gerçek veride hiçbir sonuç hesaplanmadan dört bağımsız şüpheci incelemeden geçti
(zaman güvenliği, istatistik, şartname kapsamı, veri anlamı); bulguları bu sürüme işlendi
(`reports/dizi_sozlesme_kirmizi_takim.json`). Sözleşmenin ve parametrelerin özeti, gerçek veride **ilk
örüntü sonucu hesaplanmadan önce** `reports/experiments.jsonl` dosyasına yazılır. Sonraki her değişiklik
yeni bir deney kaydıdır; etkilediği dönem "temiz test" sayılmaz ve kartlarda öyle gösterilir.

## 0. İlke

Başlangıç varsayımı "gizli algoritma" değildir. Amaç ölçülebilir hipotez üretmek, yanlışlamaya çalışmak ve
yalnızca zaman sıralı, kullanılmamış dönemde doğrulanan **ek** tahmin katkısını raporlamaktır. Bir ilişkinin
bulunması nedensellik veya manipülasyon kanıtı değildir; bulunamaması manipülasyon olmadığını kanıtlamaz.
Dil modeli sayısal sinyal üretmez; tüm hesaplar koddadır ve tekrarlanabilir.

## 1. Veri ve kapsam (incelemede doğrulandı)

- 22 ulusal lig, 184.378 maç, 28.07.2000–03.09.2026, tek kaynak (GitHub yedek / football-data türevi).
  Sonuçlar yalnızca skorlardan türetilir (`hthg/htag/fthg/ftag`); kaynak sonuç kodları (H/D/A) yalnızca
  tutarlılık kontrolüdür.
- **Yalnızca lig maçları.** Kupa, Avrupa ve millî maç yok → "tüm resmî maçlar" görünümü,
  "tüm resmî maç sayısı" aralığı ve kupa kaynaklı fikstür yoğunluğu: `DATA_QUALITY_BLOCKED`.
  Lig maçları arasındaki gün sayısı `LIG_ARASI_GUN` olarak adlandırılır (dinlenme değil).
- Dakika bazlı gol yok → "maç içinde geriye düşüp kazanma" (`MAC_ICI_GERIDEN_DONUS`): `DATA_QUALITY_BLOCKED`.
  Ölçülen hedef "ilk yarıyı geride kapatıp kazanma"dır.
- İY/MS oranı yok → İY/MS ve İY-MS geçiş hedefleri: `ROI_UNAVAILABLE`. 1X2 oranı (Bet365; yayımlanma zamanı
  doğrulanamaz) yalnızca galibiyet/mağlubiyet hedeflerinde **varsayımsal** getiri için kullanılır.
- xG, kadro, teknik direktör/kadro dönemleri, bahis hacmi, hakem: veri yok → `DATA_QUALITY_BLOCKED`.
  İsabetli şut ve kırmızı kart (2018 sonrası tam, öncesi kısmi) dizi özelliği olarak **kullanılmaz**
  (dondurulmuş karar); yalnızca olay kartında ve anomali kontrol listesinde gösterilir.
- Başlama saati yalnızca 2019/20'den itibaren; saat dilimi kaynak için doğrulanmadı (kartta belirtilir).
- **Hükmen olabilir satırlar (`POSSIBLE_AWARDED`):** İY skoru yok ve MS ∈ {3-0, 0-3, 5-0, 0-5} (78 maç).
  Karar anında sonucu bilinmeyen maç kabul edilir: hiçbir pencerede sonuç olarak sayılmaz, etiket değildir;
  fikstür sırası ve `LIG_ARASI_GUN` için sayılır. Duyarlılık: ayrıca İY 0-0, MS 3-0/0-3 ve istatistiksiz satırlar.
- **Takım kimliği:** `sequences/aliases.py` (iki katman). Katman 1: aynı lig-sezonda tarih aralıkları
  çakışmayan ve hiç karşılaşmayan iki adın sezon ortası ayrılması (deterministik kural; 3 vaka). Katman 2:
  elle incelenmiş sezonlar arası ad değişiklikleri (4 vaka). Yeniden kurulmuş/ardıl kulüpler eşlenmez
  (varsayılan "farklı kimlik"). Tablo yalnızca adlar, ligler ve tarih aralıklarından kurulur (sonuçlardan
  değil); ilk sonuçtan önce dondurulur; SHA-256'sı manifestte.

## 2. Tanımlar

**Pazar perspektifi (İY/MS, 9 sonuç):** `HTFT_<iy>_<ms>`, kodlar `1/X/2`. Sağlayıcı gösterimleri (`H/D/A`,
`0`, `D`, `X`, `2/1`, `0/1`, `D/H`) merkezi olarak normalize edilir (`goals/markets.py: parse_htft`); `0/0`
İY/MS gösterimidir ve 0-0 skoru değildir. Normal süre (uzatma, penaltı hariç). İY skoru eksik veya kayıt
çelişkili (herhangi bir tarafta İY golü > MS golü) ise **UNKNOWN**. Merkezi kayıt `HTFT_MARKETS` iki
seçenekli `MARKETS` kaydından ayrıdır (9 sonuçlu pazarda tümleyen yoktur).

**Takım perspektifi:** her maç iki satırdır (aynı `event_id`, `pair_id`). Takımın İY ve MS sonucu `G/B/M`.

| Hedef (kod) | Tanım | Ev satırında ham kod | Deplasman satırında ham kod |
|---|---|---|---|
| `IY_GERIDE_MS_GALIP` | İlk yarıyı geride kapatıp kazanma | `HTFT_2_1` | `HTFT_1_2` |
| `IY_ONDE_MS_MAGLUP` | İlk yarıyı önde kapatıp kaybetme | `HTFT_1_2` | `HTFT_2_1` |
| `IY_BERABERE_MS_GALIP` | Beraberlikten kazanma | `HTFT_X_1` | `HTFT_X_2` |
| `IY_ONDE_MS_BERABERE` | Önde kapatıp berabere | `HTFT_1_X` | `HTFT_2_X` |
| diğer 5 geçiş | `IY_GERIDE_MS_BERABERE`, `IY_BERABERE_MS_MAGLUP`, `IY_ONDE_MS_GALIP`, `IY_BERABERE_MS_BERABERE`, `IY_GERIDE_MS_MAGLUP` | | |
| `GALIBIYET`, `MAGLUBIYET` | MS sonucu | `*_1` / `*_2` | `*_2` / `*_1` |

İY/MS 2/1 otomatik olarak 3,5 Üst veya İY 1,5 Üst değildir (İY 0-1, MS 2-1: `HTFT_2_1` doğru; B, C yanlış).

## 3. Olay kartı ve pencereler

- `t0` incelenen maç. Pencereler: öncesi **5 ve 10**, sonrası **1, 3 ve 5** takım lig maçı; gerçek oynanma
  sırası (tarih). Araştırma ayarıdır; döngü iddiası değildir; sonuçlara bakılarak pencere eklenmez.
- Pencereler kanonik takım kimliğiyle kapsanan ligler arasında devam eder; "önceki maçtan beri lig değişti"
  bayrağı taşınır.
- **Pencere durumu** (her blok için): `COMPLETE`, `DATA_START` (veri başlangıcı), `COVERAGE_EXIT` (takım
  kapsanan liglerden çıktı), `GAP_GT_400D`, `RIGHT_CENSORED` (veri sonu: 03.09.2026), `INCOMPLETE_SEASON`
  (pencerenin dokunduğu lig-sezonda planlanan maçların < %97'si var), `SEASON_SKIP` (takımın sezon etiketleri
  ardışık değil), `HT_MISSING`, `POSSIBLE_AWARDED`.
- Planlanan maç sayısı format tablosundan: takım başına normal sezon = 2(n−1); istisnalar SC0 = 33, SC1–SC3 = 36.
  Takımın normal sezon sayısını aşan maçları (B1, G1, SC0 sonrası grup turları) `UST_TUR` işaretlenir ve
  pencerelerden ve hedeflerden **tüm sezonlarda** çıkarılır.
- Oynanmamış sonraki maçlar "bilinmiyor/sansürlü" kalır; başarısızlık veya sıfır gol sayılmaz.
- **Kart şeması:** başlık (event_id, pair_id, takım, rakip, ev/deplasman, lig, sezon, tarih, İY ve MS skoru
  hem ev-dep hem takım perspektifinden, ham İY/MS anahtarı, takım sonucu); `PRE_EVENT`, `EVENT_OUTCOME`,
  `POST_EVENT` ve `RAKIP_PRE_EVENT` blokları; her maç satırında maç kimliği, önceki/sonraki maç kimliği,
  ev/deplasman, yarı skorları, o maç öncesi S0 gücü (takım ve rakip), alan kapsamı (İY / oran / istatistik
  var mı), kaynak, veri güncelleme zamanı, başlama saati ("saat dilimi doğrulanmadı").
- "Tüm resmî maçlar" sekmesi her zaman gösterilir ve `DATA_QUALITY_BLOCKED` yazar.

## 4. Zaman kuralları

- `decision_time` = maç günü 00:00 (yerel). Özellikler yalnızca **daha önceki günlerin** maçlarından;
  aynı gün oynanan hiçbir maç kullanılmaz.
- **S0 soy kaydı:** her maçın tek bir saklı S0 tahmini vardır; eğitimi o maçın sezonundan önce biten fold
  tarafından üretilir (event_id, fold, eğitim son tarihi, model özeti). Beklenen puan, kalibrasyon, referans
  süreç, S2 ve `FAVORI` yalnızca bu tablodan okur.
- `label_known_at` = hedefin bilindiği günün ertesi 00:00 (aynı maç hedefi: maç günü + 1; "sonraki k maç":
  k'ncı sonraki maç günü + 1). Kesim zamanı T olan her model uyumunda eğitim satırları `label_known_at < T`.
- S1/S2/tehlike protokolü: keşifte uyum, parametre döneminde seçim, keşif+parametre üzerinde (arındırılmış)
  yeniden uyum, test için **dondurma** (test içinde yeniden uyum yok). S0 kalibrasyonu sezon başına genişleyen
  pencereyle yenilenir (yalnızca önceki sezonların saklı tahminleri).
- S2 komşuları yalnızca `label_known_at < decision_time` satırlardan; sorgu maçı, ikiz satırı ve aynı gün
  satırları dışlanır; ölçekleme yalnızca keşif döneminden öğrenilir.
- Resmî kararlar karar tarihinden önce hiçbir hesaba giremez.
- Bölme/fold sınırları tarih (1 Temmuz) ile; sezon içi sıra ve sezon sonu aşaması kaynağın `season`
  etiketiyle (2019/20'nin Temmuz–Ağustos 2020 maçları 2019/20'de kalır).

## 5. Dönemler

| Dönem | Aralık (tarihe göre sezon) | Kullanım |
|---|---|---|
| Isınma | 2000/01 – 2005/06 | 2000/01 güç ısınması; S0 2001/02'den eğitilir, 2002/03–2005/06 S0 örneklem dışı tahminleri yalnızca kalibrasyon ve beklenen puan için üretilir; hipotez değerlendirilmez |
| Keşif | 2006/07 – 2012/13 | Örüntü araması, referans süreç, kalibrasyon kapısı |
| Parametre | 2013/14 – 2018/19 | S1 düzenlileştirme, S2 k ve κ seçimi, adayların ilk teyidi, A/B/C ek kontrolü |
| Test | 2019/20 – 2025/26 | Tek seferlik değerlendirme; tanımlar test açıldıktan sonra değiştirilmez |
| İleriye dönük | sözleşme tarihinden (2026-10-10) sonra oynanan ve tahmini maç öncesinde kayda geçmiş maçlar | `PAPER_TRADING` |

**Dürüstlük notu:** (1) S0'ın (M10) varyant ve hiperparametreleri 2008–2018 geliştirme döneminde seçildi
(keşif ve parametre dönemleriyle örtüşür). (2) 2019–2026 önceki görevde üç ana pazarın final testi olarak
kullanıldı. (3) Bu görevin incelemesinde tüm dönemin toplu İY/MS frekansları, PSV olay listesi ve S0'ın İY/MS
türetiminin 2019 sonrası satırlarda (örneklem içi) kalibrasyon karşılaştırması görüldü. Eğilmiş + q-kalibre
türetim, kullanıcının "A/B/C ile aynı dağılım" şartından gelir; o karşılaştırmaya göre seçilmedi ve dondurulmuştur.
Test bu yüzden "koşullu örüntüler için ön-kayıtlı; S0 İY/MS kalibrasyonu test döneminde görülmüş" olarak
etiketlenir. Tamamen temiz kanıt yalnızca ileriye dönük dönemdir; her `OUT_OF_SAMPLE_SUPPORTED` kartında yazılır.

## 6. Modeller (kodda `S0/S0p/S1/S2`)

- **S0 (görevdeki M0):** M10 ortak gol dağılımı, kanonik takım kimlikleriyle araştırma için yeniden kurulan
  özelliklerden, her sezon Y için `2001 ≤ sezon < Y` ile eğitilir; 9 İY/MS hücresi A/B/C ile aynı dağılımdan
  (`GoalModel.htft_probs`). Izgara kuyruğu (≤ 3e-6) ham S0'da ayrı raporlanır.
- **Tek 9 hücreli kalibrasyon:** çok sınıflı lojistik (log S0 hücre olasılıkları × sıcaklık + 8 serbest
  hücre sabiti), sezon Y için yalnızca önceki sezonların saklı S0 tahminleriyle; en az bir tam örneklem dışı
  sezon oluşana kadar özdeşlik. Bütün takım hedefleri (her iki perspektif) bu dağılımdan türetilir → ikiz
  satırlar tutarlıdır. Beklenen değer ve referans süreç **aynı** dağılımı kullanır.
- **S0p (piyasa kontrolü):** kalibre S0 + Bet365 1X2 marjsız olasılıkları (sıcaklık + 2 sabit; MS sonucu
  hücre gruplarına çarpan olarak). Satırların ~%2'sinde oran yoktur.
- **S1 (M1):** S0 logiti sabit (offset) + standartlaştırılmış dizi özellikleri (ölçek keşiften), sabit terim
  cezasız, L2 ceza λ ∈ {1e-4, 1e-3, 1e-2, 1e-1} ve λ=∞ (yalnız offset+sabit) — offset destekli L-BFGS.
  Özellikler (takım ve rakip ayrı): son 5'te İY geride / İY önde sayısı, son 10'da `IY_GERIDE_MS_GALIP` ve
  `IY_ONDE_MS_MAGLUP` sayısı, son 5 puan ortalaması, son 10'da puan − S0 beklenen puan, son 10'da 2. yarı
  gol farkı, son 10'da İY→MS iyileşme sayısı, son 10 maçta ev oranı, son 10 maçta rakip S0 gücü ortalaması,
  son 10 maçta piyasa sürprizi (puan − marjsız 1X2 beklenen puan; oran varsa), son olaydan beri maç (log),
  `LIG_ARASI_GUN` (log), mevcut maç sayısı ve eksik göstergeleri. Eksik pencereli satırlar **kalır**
  (mevcut maçlar üzerinden hesap + gösterge).
- **S2 (M2):** S1 özellikleri + takım/rakip S0 gücü; keşiften standart ölçek; Öklid uzaklığı; k ∈ {200, 500,
  1000} × κ ∈ {5, 20, 80} parametre döneminde seçilir; komşular takım-sezon başına en fazla 1;
  `logit p = logit p0 + [logit((O + κ·p̄)/(n + κ)) − logit((E + κ·p̄)/(n + κ))]`, p̄ = E/n.
  Ham benzerlik yüzdesi olasılık değildir. Etkili örnek sayısı = farklı takım-sezon (ve farklı takım, maç).
- **Ortak değerlendirme kümesi:** S0, S0p, S1, S2 aynı satırlarda (kesişim) değerlendirilir; satır kimliği
  özeti manifestte; dışlanan küme ayrıca raporlanır.

## 7. Sorgu 1 — maç öncesi koşul araması (aynı maç hedefi)

- **Hedefler (4):** `IY_GERIDE_MS_GALIP`, `IY_ONDE_MS_MAGLUP`, `GALIBIYET`, `MAGLUBIYET`.
- **Dizi atomları (16; hepsi İY/MS hücrelerinden türetilir):** `SON_MAC_IY_GERIDE_MS_GALIP`,
  `SON_MAC_IY_ONDE_MS_MAGLUP`, `SON5_IY_GERIDE_EN_AZ_2`, `SON5_IY_ONDE_EN_AZ_3`, `SON5_GALIBIYET_EN_AZ_4`,
  `SON5_GALIBIYETSIZ`, `SON3_MAGLUBIYET`, `SON10_IY_GERIDE_MS_GALIP_EN_AZ_2`, `SON10_IY_SONRASI_IYILESME_EN_AZ_4`,
  `SON20_IY_GERIDE_MS_GALIP_YOK`, `SON3_IY_GERIDE_MS_GALIP_VAR`, `FORM_BEKLENTI_USTU` (son 10'da puan −
  kalibre S0 beklenen ≥ +4), `FORM_BEKLENTI_ALTI` (≤ −4), `RAKIP_SON5_IY_ONDE_EN_AZ_3`,
  `RAKIP_SON10_IY_ONDE_MS_MAGLUP_EN_AZ_2`, `RAKIP_SON3_MAGLUBIYET`.
  Tanımlılık: İY gerektiren sayımlar penceredeki her maçın İY'si biliniyorsa; MS sayımları her maçın sonucu
  biliniyorsa; pencere durumu `COMPLETE` değilse atom tanımsızdır (satır o koşulun hem içinden hem
  tümleyeninden çıkar). Beklenen puanlı atomlar için penceredeki 10 maçın da S0 tahmini olmalıdır.
- **Bağlam (tek başına koşul değildir):** `EV_SAHIBI`, `FAVORI` (kalibre S0 galibiyet ≥ 0,55),
  `LIG_YOGUN_KISA_ARA` (`LIG_ARASI_GUN` ≤ 3), `SEZON_SONU` (sezon içi sıra / planlanan normal sezon uzunluğu
  ≥ 0,8; uzunluk format tablosundan; kapsamı < %97 sezonlarda tanımsız). Yalnızca bir dizi atomuyla birlikte
  kısıt olarak kullanılır. Ayrıca bağlam bazlı O/E tablosu yalnızca "S0 kalibrasyon tanılaması" olarak raporlanır.
- **Koşullar:** 16 tek atom + 120 dizi×dizi çifti + 64 dizi×bağlam çifti = 200 koşul × 4 hedef = **800 ham
  hipotez**. Uzunluk > 2 yok. İkiz denk hipotezler (aynı maç-olay kümesi; ör. `RAKIP_SON3_MAGLUBIYET × GALIBIYET`
  ≡ `SON3_MAGLUBIYET × MAGLUBIYET`) olay düzeyi imzayla tekilleştirilir; ham ve tekil sayı raporlanır.
- **Dışlamalar:** takımın lig değişikliğinden sonraki ilk 8 maçı (S0 terfi/düşme önselleri) aramadan ve testten
  çıkarılır; `UST_TUR` maçları hedef değildir; sayılar raporlanır.
- **İstatistik (katmanlı, S0'a göre):** katman s = taraf (ev/dep) × lig × hedefe özgü kalibre p0 beşlisi
  (dönem içinde). r_s = O_s/E_s (geçerli satırlar); koşullu beklenen E_c = Σ_{i∈c} p_i·r_s;
  T = Σ_s (O_cs − E_cs·r_s). Varyans: lig-sezon kümeli (CR1, G/(G−1)) — ikiz satırlar, takım-sezon ve hafta
  bağımlılığı aynı kümededir; katman katkıları küme toplamlarına cebirsel olarak tam ayrışır. z = T/√V.
  Etki: oran O_c/E_c, mutlak fark (O_c − E_c)/n_c, göreli artış; aralık oran ± 1,96·√V/E_c. Ayrıca katmanlanmamış
  S0 O/E ve ham taban oran (S0'ın zaten bildiğini ayırt etmek için) ve eşleştirilmiş ampirik karşılaştırma
  (koşulsuz satırlar, aynı lig-sezon × taraf × S0 ondalığı) raporlanır.
- **Asgari destek:** n_c ≥ 500 ve Σ_{i∈c} p_i ≥ 25 (keşifte; her referans tekrarında yeniden uygulanır).
- **Kalibrasyon kapısı (arama öncesi):** keşifte her hedef × taraf için toplam O/E %95 aralığı 1'i içermeli;
  içermezse arama yapılmaz, S0 kalibrasyon sorunu raporlanır.
- **Referans süreç:** keşif dönemindeki her maç için kalibre 9 hücreden **tek** bir İY/MS sonucu çekilir (iki
  satır tutarlı); keşif öncesi satırlar gerçek sonuçlarını korur (gerçek geçmişe koşullu); gerçekte bilinmeyen
  satırlar (İY eksik, hükmen olabilir) çekimden sonra yeniden "bilinmiyor" yapılır; güç, ev/deplasman, lig,
  sezon ve takvim aynen korunur; tüm dizi atomları ve destek filtresi çekimden **yeniden hesaplanır**; arama
  sürecinin **tamamı** her tekrarda yeniden çalışır. **R = 1000.** Seçim kapısı: Westfall–Young adım adım
  azalan maxT (FWER 0,05); her düzeltilmiş p için Monte Carlo %99 aralığı; aralık 0,05'i içeriyorsa
  `INSUFFICIENT_EVIDENCE`. Benjamini–Yekutieli yalnızca normal yaklaşımlı p'lerle **tanımlayıcı** raporlanır.
  Sınır: referans S0'ın doğru olduğunu varsayar; S0'ın takım-sezon düzeyi hataları referansta yoktur (CR1
  varyans bunu gerçek veride hesaba katar).
- **Seçim ve durdurma:** tek arama geçişi. WY-anlamlı hipotezlerden, çiftler yalnızca her iki tek atomundan
  aynı yönde daha büyük |log oran| veriyorsa; |log oran| alt güven sınırına göre en fazla **5** aday, her
  hedefte aynı atomu paylaşanlardan en fazla biri. Parametre döneminde tek yönlü (ön-kayıtlı yön) Holm
  düzeltmeli p < 0,05 olanlar teste taşınır. Ek arama, yeni atom veya eşik yoktur.
- **Gösterge katsayısı:** S0 offsetli lojistikte adayın log-odds katsayısı keşif+parametre ile öğrenilir ve
  teste aynen uygulanır.

## 7a. Mod A ve Mod B

- **Mod A (olaydan başlayan tarihsel inceleme):** seçilen takım ve hedef/İY-MS kodu için tüm olaylar,
  olay kartları, olaylar arası gün/maç/sezon geçişi, açık (sansürlü) son aralık; olay öncesi özelliklerin
  aynı takımın tüm maçlarıyla karşılaştırması. **Yalnızca tanımlayıcıdır** ("olay seçimli, tahmin değil"),
  her dönemde çalışabilir, statü üretmez, atom eklemez.
- **Mod B (koşuldan başlayan doğrulama):** kart alanları: n_koşul, isabet (koşul ∧ olay), ıska (koşul ∧ olay
  yok), koşulsuz olay (olay ∧ koşul yok), koşullu/koşulsuz olay oranı, eşleştirilmiş ampirik taban, S0
  beklenen, mutlak fark, göreli artış, CR1 aralığı, sonraki her yıl için sezon bazlı O/E, en büyük 20 karşı
  örnek. Statülerin **tek** kaynağı Mod B'dir.

## 7b. Yanlışlama listesi (parametre ve test dönemlerinde her adaya)

1. Bir takım veya bir lig çıkarıldığında oran 1'in öbür yanına geçmemeli / yön değişmemeli.
2. O − E'ye en çok katkı veren %1 satır çıkarıldığında aynı yön ve aralık 1'i dışlamalı.
3. Sezonların en az %60'ında aynı yön.
4. Eşleştirilmiş ampirik karşılaştırma aynı yönde.
5. S0p (piyasa) offsetiyle etki sürmeli (aralık 1'i dışlar); sürmezse `NO_ADDED_VALUE` — "piyasa/temel model bilgisi".
6. En büyük 20 karşı örnek kartta listelenir.
Her kontrolün sonucu deney kaydına yazılır. `OUT_OF_SAMPLE_SUPPORTED` için 1–5 geçmelidir.

## 7c. Sorgu 2 — olay sonrası (sonraki maç/lar)

Olay türleri: son maçta `IY_GERIDE_MS_GALIP`, son maçta `IY_ONDE_MS_MAGLUP`. Hedefler: sonraki maçta
`GALIBIYET` (S0'a göre), sonraki 3 maçta en az bir aynı olay (S0'a göre 1 − Π(1−p)), sonraki 5 maçta puan
(S0 beklenen puana göre). 2 × 3 = **6 hipotez**, ayrı aile; çakışmayan olay örnekleri (takım başına her 5 maçlık
ufukta ilk olay); aynı referans süreçle WY. "Sonraki 3 maçta en az bir" ile "sonraki maçta" ayrı tutulur.
Arayüz ve raporlar her sonucu "Sorgu 1 (maç öncesi)" veya "Sorgu 2 (olay sonrası)" diye etiketler.

## 8. Olaylar arası süre ve tehlike modeli

- Her takım için olaylar (`IY_GERIDE_MS_GALIP`, `IY_ONDE_MS_MAGLUP`) arası gün, lig maçı sayısı, sezon geçişi;
  tamamlanmış aralıklar ve sansürlü dilimler (veri sonu, kapsamdan çıkış, 400 gün, eksik sezon) birlikte saklanır.
- Risk altı süre her dilimde **ilk gözlenen olaydan** başlar (sol kesik); öncesi dışlanır ve sayılır.
- Ayrık zamanlı tehlike: olay olasılığı = kalibre S0 logit (offset) + takım kırılganlık ortak değişkeni (önceki iki
  sezondaki küçültülmüş kendi olay oranı; zaman güvenli) + "son olaydan beri maç" kategorileri {1–3, 4–10, 11–20,
  21–40, 41+}. Keşifte takım kümeli sağlam Wald testi; parametre/testte örneklem dışı log-kayıp. "Uzun süredir
  olmadı, olmak zorunda" kuralı kurulmaz; frekans/döngü taraması yapılmaz.

## 9. Doğrulama ölçütleri, aileler ve statüler

**Deney aileleri (tam liste; her biri sonuç ne olursa olsun kaydedilir):** F1 Sorgu 1 araması (WY) · F2 Sorgu 2
(WY) · F3 S1 ve S2'nin S0'a katkısı, 4 hedef × 2 model (Holm) · F4 tehlike, 2 olay türü (Holm) · F5 A/B/C ek
kontrolü, 3 pazar (Holm; keşifte uyum, parametre döneminde değerlendirme; 2019+ yalnızca `EXPLORATORY`) ·
F6 ekonomik değer (tanımlayıcı) · F7 plasebo negatif kontrol.

Raporlanan: Brier, log-kayıp, kalibrasyon (eğim, ECE), taban sıklık, örnek sayısı, mutlak ve göreli iyileşme,
lig-sezon kümeli bootstrap aralıkları (ISO hafta blokları duyarlılık), sezon kararlılığı, S0'a göre ek katkı.

| Statü | Kural |
|---|---|
| `EXPLORATORY` | Keşifte bulundu, örneklem dışı değerlendirilmedi (veya yalnızca görülmüş dönemde değerlendirildi) |
| `INSUFFICIENT_EVIDENCE` | Destek yetersiz, WY anlamsız veya Monte Carlo aralığı 0,05'i içeriyor |
| `NO_ADDED_VALUE` | Örneklem dışında tek yönlü Holm testi geçmedi, log-kayıp katkısı yok veya piyasa kontrolünde kayboldu |
| `OUT_OF_SAMPLE_SUPPORTED` | Parametre + test dönemlerinde ayrı ayrı tek yönlü Holm (1−0,05/k) geçti, testte S0 + gösterge log-kaybı S0'dan anlamlı düşük (lig-sezon kümeli bootstrap üst sınır < 0) ve 7b/1–5 geçti |
| `PAPER_TRADING` | `OUT_OF_SAMPLE_SUPPORTED` + ileriye dönük takipte; değerlendirme noktası ≥ 300 nitelikli takım satırı veya 2 sezon (önce gelen); aynı kural; başarısızsa `NO_ADDED_VALUE`, uzatma yok |
| `DATA_QUALITY_BLOCKED` | Gerekli veri yok |

Bu statüler **örüntü** statüleridir; şike, kulüp, oyuncu veya hakem statüsü değildir.

**Plasebo negatif kontrol (F7):** gerçek sonuçlar ve gerçek S0 ile; her satırın dizi atomları, aynı lig-sezonda
S0 güç ondalığı ve tarihe en yakın başka bir takımın atomlarıyla değiştirilir; tüm süreç (arama + WY) en az
20 tohumla çalışır (plasebo başına R = 200, belirtilerek). Geçme kuralı: 20 tohumdan en fazla 1'inde WY keşfi.
Aşılırsa referans süreç güvenilmez sayılır ve gerçek keşifler dondurulur. S0'dan sentetik hedefle çalıştırma
yalnızca kod testi olarak kalır (red oranı ≈ %5).

## 10. Ekonomik değer

İY/MS ve İY-MS geçiş hedefleri: `ROI_UNAVAILABLE` (doğru pazarın zaman damgalı gerçek oranı yok; 1X2'den İY/MS
oranı türetilmez). Galibiyet hedefleri: araştırmaya özel 1X2 sonuçlandırma ve EV (`goals/value.expected_value`
yeniden kullanılır; `decide()` ve ana kayıt değişmez); maç başına seçim başına tek bahis; S0, S1/S2 ve
marjsız Bet365 aynı maç kümesinde, aynı eşik (EV ≥ 0,05), komisyon 0, sabit birim; lig-sezon kümeli aralık.
Oran zamanı doğrulanamadığı için **varsayımsal**. Benzerlik puanı olasılığa eklenmez. Takip sanal.

## 11. Anomali incelemesi (tahminden ayrı)

- `PREDICTIVE_PATTERN` = Mod B sonucu (statülü). `UNEXPLAINED_ANOMALY` = tek maç: gerçekleşen İY/MS sonucunun
  kalibre S0'a göre sürprizi (−log₂ p) kendi lig-sezonunun **en üst %0,5'inde** ve çalıştırılabilen kontrollerle
  açıklanamıyor. İkincisi birincisini güçlendirmez.
- Kontrol listesi: veri hatası (doğrulama kuralları), hükmen olabilir, yanlış eşleşme/ad kopukluğu, lig
  değişikliği sonrası ilk maçlar (S0 soğuk başlangıç), kırmızı kart ("açıklanabilir: kırmızı kart", veri varsa),
  eski oran / düşük likidite / kadro haberi / maç içi bilgi / sağlayıcı gecikmesi (veri yok → "değerlendirilemedi").
  Birden fazla sitede aynı hareket bağımsız kanıt sayılmaz (ortak kaynak olasılığı).
- Anomali puanı suç veya şike olasılığı değildir; kulüp/oyuncu/hakem etiketlenmez; **takım, lig veya hakem
  bazında toplama ve sıralama yapılmaz** (arayüz ve raporlarda; testle korunur); karar motoruna, sanal takibe
  veya örüntü statüsüne bağlanmaz.
- Resmî kararlar ayrı kayıtta: kaynak, karar tarihi, kapsam (maç/olay), itiraz/kesinleşme durumu; karar
  tarihinden önce hiçbir hesapta kullanılmaz; kaydın olmaması "temiz" anlamına gelmez. Şu an kayıt yoktur.

## 12. Tekrarlanabilirlik ve regresyon

Manifest: veri SHA-256, git commit, sözleşme ve parametre özeti, eşleme tablosu özeti, ortak değerlendirme
satır kümesi özeti, tohum, saat dilimli zaman, ham/tekil hipotez sayısı, S0 model özetleri. Aynı manifest ve
tohumla sonuçlar birebir tekrarlanır. Olumlu, olumsuz ve sonuçsuz bütün deneyler `reports/` altında saklanır.
Üç ana pazarın tahmin ve etiketleri için altın regresyon testi (`tests/test_primary_regression.py`).

## 13. Arayüz kuralları

- **Geçmiş inceleme ekranı** (olay zaman çizgisi, Mod A): PRE/EVENT/POST blokları; "olay seçimli, tahmin değil"
  etiketi; olay sonrası bilgi içerebilir.
- **Maç öncesi ekranı** (benzer diziler, Sorgu 1): yalnızca `decision_time` öncesi veriler ve
  `label_known_at < decision_time` komşular; `POST_EVENT` alanı yoktur (testle korunur); statü yalnızca dondurulmuş
  deney kaydından; `EXPLORATORY` ve `INSUFFICIENT_EVIDENCE` örüntüler soluk gösterilir ve olasılığı değiştirmez.
- **Örüntü doğrulama kartı:** tanım, keşif ve doğrulama dönemi, denenen alternatif sayısı, Mod B alanları,
  yanlışlama sonuçları, belirsizlik, gerçek oranlı test durumu, ileriye dönük takip.
- **Anomali sayfası:** ayrı; karar motoruna, sanal takibe ve örüntü statüsüne bağlantı yoktur.

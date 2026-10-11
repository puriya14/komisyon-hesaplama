# S5-GITHUB-01 — GitHub veri profili ve tarihsel arşiv

Bu belge, uygulamanın yalnızca kullanıcının seçtiği dört public GitHub deposundan veri alması ve bu verilerle
geçmiş maçları incelemesi için eklenen yolları anlatır. football-data.org bu yolun parçası değildir; hesap,
API anahtarı veya ücretli servis gerekmez.

| Depo | Kayıt anahtarı | Asıl köken |
|---|---|---|
| `openfootball/football.json` | `openfootball-sonuc` | openfootball topluluk derlemesi (CC0) |
| `datasets/football-datasets` | `football-datasets` | football-data.co.uk (deponun kendi derleme betiği asıl siteden okur) |
| `xgabora/Club-Football-Match-Data-2000-2025` | `github-mirror` | football-data.co.uk (maçlar) + ClubElo (Elo) |
| `hudl/open-data` | `statsbomb-acik` | StatsBomb (Hudl) olay verisi |

Başka depo, çatal (fork) veya site kullanılmaz. Depoların kendi güncelleme betikleri (ör. `scripts/process.py`)
**çalıştırılmaz**, çünkü bu betikler GitHub dışındaki asıl sitelere istek gönderebilir.

## 1. Veri profili (`varsayilan` / `github`)

- **Arayüz:** Veri sayfası → "Veri profili" listesi. Seçiminiz yalnızca ayarlara kaydedilir; indirmeyi
  "Kaydet, Güncelle ve Eğit" düğmesi başlatır.
- **Komut satırı:** `python -m bahis_tahmin update --profil github` (bu seçim de ayarlara kaydedilir).

`github` profili seçiliyken güncelleme şöyle çalışır:

- football-data adreslerine istek gönderilmez; bu, sonuç ve fikstür dosyalarının ikisi için de geçerlidir.
  İndirici yalnızca `github.com`, `raw.githubusercontent.com` ve `api.github.com` adreslerine izin verir.
  Başka bir adres önbellekten de okunmaz.
- Yönlendirmeler elle izlenir. GitHub dışına çıkan bir yönlendirme isteği durdurur
  (`YONLENDIRME_DISARI`).
- Geçmiş sonuçlar GitHub yedek veri setinden (xgabora), fikstürler openfootball'dan alınır. Her iki depo
  için dal ucu bir kez çözülür (git `info/refs`; API kotası gerekmez) ve dosyalar o commit'ten indirilir.
  Önbellek anahtarı depo + commit + yoldur. Özeti kayıtla uyuşmayan bir dosya kullanılmaz.
- Uç çözülemezse veya dosya alınamazsa, daha önce doğrulanmış bir kopya varsa kullanılır ve raporda
  açıkça "ESKİ kopya" olarak işaretlenir (`UpdateReport.stale`, `data_meta.json` → `eski_kopya_dosyalari`).
  Hiç kopya yoksa o kaynak atlanır. Başka bir siteye geçilmez ve sınırsız yeniden deneme yapılmaz.
- Bu profilde yalnızca GitHub yedek veri setinin kullanım koşulu onayı aranır
  (`update --profil github --accept-terms github-mirror`). Onay yalnızca **erişimi** kapsar. Model
  eğitimi ve tahmin, mevcut uygunluk ve hak kurallarına bağlı kalır; bu görevde hiçbir hak değiştirilmedi.

`varsayilan` profilinde de değişen tek şey şudur: indirme başarısız olup önbellekteki eski kopya
kullanıldığında bu durum artık ayrıca sayılır ve raporda gösterilir.

## 2. Tarihsel arşiv

Arşiv, uygulama veri klasöründen **ayrı** bir klasördür:

- Windows varsayılanı: `%LOCALAPPDATA%\BahisTahmin-Arsiv`
- Linux varsayılanı: `~/.local/share/BahisTahmin-Arsiv`
- `BAHIS_TAHMIN_ARSIV` ortam değişkeni veya `--ev` ile başka bir klasör verilebilir.

Uygulama klasörünün kendisi, alt klasörü veya onu içeren bir klasör reddedilir. Boş olmayan ve arşiv
işareti (`arsiv.json`) taşımayan bir klasöre de yazılmaz. Kullanıcı veri deposu, pilot, model ve defter
değişmez. Eğitim yapılmaz; olasılık, tahmin veya bahis adayı üretilmez.

### Üç ayrı işlem

| İşlem | Komut / düğme | Ne yapar |
|---|---|---|
| **Arşivi açmak, incelemek** (salt okunur) | `arsiv-katalog`, `arsiv-maclar`, `arsiv-ozet`, `arsiv-kart`; arayüzde "Arşivi aç" | Ağ isteği yapmaz, hiçbir dosyaya yazmaz; arşivdeki dosyaların kökenini yeniden doğrular. |
| **Arşivi hazırlamak, güncellemek** | `arsiv-hazirla`; arayüzde "Arşivi hazırla / güncelle" | Seçili GitHub depolarını sabit commit'ten indirir ve yalnızca arşiv klasörüne yazar (katalog ve analiz tablosu yeniden yazılır; ham dosyalar commit bazında korunur). Ana uygulamanın verisine, modeline ve ayarlarına dokunmaz. |
| **Ana uygulamanın güncellemesi** | `update`; Veri sayfasında "Kaydet, Güncelle ve Eğit" | Arşivi kullanmak için **gerekmez** ve arşivle ilgisi yoktur. Ana uygulamanın veri deposunu ve ayarlarını değiştirir (`--profil`, `--accept-terms`, lig ve yıl seçimi ayarlara kaydedilir); "Kaydet, Güncelle ve Eğit" düğmesi modeli de eğitebilir. |

"Arşivi aç" ile "Kaydet, Güncelle ve Eğit" farklı işlemlerdir: birincisi yalnızca okur, ikincisi ana uygulamanın
verisini günceller.

### Komutlar

Linux / macOS — arşivi hazırlamak (indirir, yalnızca arşiv klasörüne yazar):

```
python -m bahis_tahmin arsiv-hazirla --ev <ARSIV>                              # dört kaynak (onay gerekenler hariç)
python -m bahis_tahmin arsiv-hazirla --ev <ARSIV> --erisim-onayi datasets,xgabora
python -m bahis_tahmin arsiv-hazirla --ev <ARSIV> --kaynak openfootball,hudl
python -m bahis_tahmin arsiv-hazirla --ev <ARSIV> --pilot <PILOT_KLASORU>     # openfootball dosyalarını pilottan kopyala
python -m bahis_tahmin arsiv-hazirla --ev <ARSIV> --cevrimdisi                 # ağ yok; yalnızca arşivdeki kopyalar
```

Linux / macOS — arşivi incelemek (salt okunur):

```
python -m bahis_tahmin arsiv-katalog --ev <ARSIV>
python -m bahis_tahmin arsiv-maclar  --ev <ARSIV> --kaynak openfootball --sezon 2024/25 --limit 50   # tek kaynak
python -m bahis_tahmin arsiv-maclar  --ev <ARSIV> --sezon 2015/16                                   # birleştirilmiş
python -m bahis_tahmin arsiv-maclar  --ev <ARSIV> --kaynak openfootball --takim "Arsenal FC" --yer ev --bas 2020-08-01 --son 2025-06-01
python -m bahis_tahmin arsiv-ozet    --ev <ARSIV> --kaynak openfootball --sezon 2024/25
python -m bahis_tahmin arsiv-kart    --ev <ARSIV> --kaynak openfootball --mac "E0|2024-08-17|Arsenal FC|Wolverhampton Wanderers FC" --takim "Arsenal FC" --sezon 2024/25
```

Windows (kaynak koddan; `baslat.bat` sanal ortamı `.venv` klasörüne kurar):

```
.venv\Scripts\python -m bahis_tahmin arsiv-hazirla --ev "%LOCALAPPDATA%\BahisTahmin-Arsiv" --erisim-onayi datasets,xgabora
.venv\Scripts\python -m bahis_tahmin arsiv-katalog --ev "%LOCALAPPDATA%\BahisTahmin-Arsiv"
.venv\Scripts\python -m bahis_tahmin arsiv-maclar  --ev "%LOCALAPPDATA%\BahisTahmin-Arsiv" --kaynak openfootball --sezon 2024/25
.venv\Scripts\python -m bahis_tahmin arsiv-ozet    --ev "%LOCALAPPDATA%\BahisTahmin-Arsiv" --kaynak openfootball --sezon 2024/25
```

Ana uygulamayı GitHub profiliyle güncellemek ayrı bir işlemdir (bkz. bölüm 1) ve arşiv için gerekmez:
`.venv\Scripts\python -m bahis_tahmin update --profil github --accept-terms github-mirror` — bu komut ana
uygulamanın veri deposunu ve ayarlarını değiştirir.

### Görünümler: tek kaynak ve birleştirilmiş

`--kaynak` (arayüzde "Görünüm" listesi) iki farklı görünümden birini seçer:

- **Tek kaynak** (`--kaynak openfootball|datasets|xgabora|hudl` veya kayıt anahtarı; kısa ad ile kayıt anahtarı aynı
  sonucu verir): kaynak filtresi birleştirmeden **önce** uygulanır. Kimlik eşleme, tekilleştirme ve pazar
  etiketleri yalnızca o kaynağın kayıtlarıyla yapılır. Başka kaynaktan İY, xG, şut, saat, sağlayıcı kimliği veya
  başka bir alan taşınmaz; eksik alan eksik kalır (sıfırla doldurulmaz). Başka kaynakla çelişen ama kendi içinde
  tutarlı bir kayıt bu görünümde engellenmez; kaynağın kendi içindeki çelişki kuralları çalışmaya devam eder.
  Takım adları kaynağın kendi adlarıdır (ör. StatsBomb'da "Arsenal", openfootball'da "Arsenal FC"). Tarihsel
  analizi kapalı kaynak (datasets, xgabora) seçilirse görünüm boştur ve başka kaynaktan veri gösterilmez.
- **Birleştirilmiş** (`--kaynak` verilmez veya `--kaynak birlesik`; arayüzde "Birleştirilmiş görünüm (tek kaynak
  değil)"): tarihsel analizi açık bütün kaynaklar birleşir. Aynı gerçek maç bir kez sayılır ve kaynaklar satırda
  yazılır. Bu görünüm **kaynaklar arası alan birleştirmesi içerir**: bir maçın İY'si, saati veya xG/şut değeri,
  MS'yi veren kaynaktan farklı bir kaynaktan gelebilir. Her satırın alan kökeni (`ms_kaynaklari`,
  `iy_kaynaklari`, `saat_kaynagi`, `xg_kaynagi`, `sut_kaynagi`) yazılır ve listede "alan kökeni" sütununda
  gösterilir. Çelişkili skorlar çoğunluk oyuyla veya son commit seçilerek çözülmez.

CLI ve arayüz her listenin başında hangi görünümün kullanıldığını yazar. Hiçbir görünüm model eğitimi veya
tahmin gösterimi izni değildir.

Olay kartı (`arsiv-kart`, arayüzde "Seçili maçın olay kartı") listeyle **aynı görünümde** açılır: tek kaynak
listesinden açılan kart başka kaynakları birleştirmez. Önce/sonra pencereleri aynı görünümün aynı ligindeki
doğrulanmış maçlarından alınır; seçili listenin sezon, takım ve tarih filtresiyle sınırlı değildir ve önceki
sezona taşabilir. Kart bunu açıkça yazar: pencere maçlarının sezonları, tarih aralığı ve listenin filtresi dışında
kalan pencere maçı sayısı. CLI'da listenin filtresi `--sezon`, `--bas`, `--son`, `--liste-takim` ile verilir.

### Sayaçlar ve birimleri

Listedeki maçlar, geçerli maç sayısı, A/B/C gerçekleşme sayıları ve paydaları, İY/MS dağılımı, çelişkili maçlar,
tarih uyuşmazlıkları ve kimlik incelemesi **aynı görünüm ve aynı filtreden** (kaynak, lig, sezon, takım,
ev/deplasman, tarih aralığı) üretilir. Başka sezonun çelişkisi seçili sezonun sayacına, başka takımın inceleme
kaydı seçili takımın sayacına girmez.

| Alan | Birim |
|---|---|
| `mac` | benzersiz maç (tarih uyuşmazlığındaki iki aday satır tek eşleşme sayılır) |
| `liste_satiri` | listede görünen satır |
| `kaynak_satiri` | kaynak kaydı (bir maçın birden çok kaynak kaydı olabilir) |
| `blok_sayisi` | kaynak dosyası / lig-sezon bloğu |
| `celiskili` / `celiski_kaynak_satiri` | çelişkili benzersiz maç / bu maçların kaynak kayıtları (ör. 1 maç, 2 kaynak kaydı) |
| `incelemede` / `incelemede_liste_satiri` | tarih uyuşmazlığındaki eşleşme / liste satırı |
| `kimlik_incelemesi_kaynak_satiri` | takım kimliği kesinleşmeyen ve filtreye uyan kaynak kaydı |
| `kimlik_incelemesi_takima_indirgenemeyen` | takım filtresinde, ilgili tarafı çözülemediği için seçili takıma ait olup olmadığı bilinemeyen kaynak kaydı (ayrı gösterilir; takım filtresi yoksa boş) |

Dosya düzeyinde tutulan sayılar takım veya tarih filtresine indirgenemez ve öyle gösterilmez:
`kaynak_karantinasi` "seçili kaynak/lig/sezon dosyalarındaki toplam karantina" olarak, dosya düzeyi açıklamasıyla
verilir (`kaynak_karantinasi_kapsami`). Bütün arşivin sağlık sayıları (blok sayısı, analiz satırı, kökeni
doğrulanamayan blok) yalnızca ayrı bir **Genel arşiv durumu** bölümünde yer alır (`genel_arsiv_durumu`). Özetler
önbelleğe alınmaz; filtre değişince yeniden hesaplanır.

Arayüzdeki bölümler:

- **A · Kaynak kapsamı:** lig/sezon, commit, önbellek durumu, son geçerli maç, MS/İY kapsamı, işaretli
  mantıksal İY 0-0, tam/kısmi kapsam, kullanım durumu ve olay/xG/gerçek oran alanlarının varlığı.
- **B · Maç tarayıcı:** görünüm, lig, sezon, takım, ev/deplasman ve tarih aralığı filtreleri. Her satırda
  maç kimliği, İY ve MS, A/B/C etiketleri, İY/MS sonucu, veri kalitesi, kaynaklar ve (birleştirilmiş görünümde)
  alan kökeni görünür. StatsBomb xG'si yalnızca maç sonrası açıklama olarak gösterilir.
- **C · Toplu özet:** merkezi pazar kaydından (`goals.markets`) gelen A/B/C ve İY/MS sayıları, her biri
  geçerli örnek sayısıyla; yukarıdaki sayaçlar ve birimleri. Seçili maç için mevcut dizi olay kartı (önce/sonra)
  da buradan açılır.

> Buradaki oranlar tarihsel gerçekleşme oranıdır. Bugünkü bir maç için olasılık, model güveni veya bahis
> avantajı değildir. Tahmin ekranı kendi uygunluk kurallarını uygular; arşiv bu kuralları atlatmaz.

### Önbellek ve köken

- Dosyalar `<ARSIV>/github/<sahip__depo>/<commit>/<yol>` altında, yanlarında bir `.kaynak.json` kaydıyla
  saklanır. Kayıt depo, commit, yol, SHA-256, boyut, alım anı ve yöntemi tutar. Dal ucu geçmişi
  `<ARSIV>/github/uclar.json` dosyasındadır.
- Her dosya şu durumlardan biriyle işaretlenir: `KAYNAKTAN_ALINDI`, `DOGRULANMIS_ONBELLEK`,
  `PILOT_ONBELLEGINDEN_KOPYALANDI` (özet doğrulanmış) veya `GUNCELLEME_BASARISIZ_ESKI_KOPYA`.
- Katalogda (`katalog.json`) şunlar ayrı ayrı görülür: yeni commit ("uç değişti a → b"), aynı uç ("uç
  değişmedi") ve bugün alınan dosya (`alinma_utc`). Yeni commit eski commit'in dosyalarını ezmez.
- Arşiv yüklenirken her analiz bloğunun ham dosyası ve satır özeti yeniden doğrulanır. Ham dosya
  değiştirilmişse, satır etiketi değiştirilmişse veya analizi kapalı bir kaynağın satırı izinli kaynak gibi
  gösterilmişse o blok kullanılmaz (`KOKEN_DOGRULANAMADI`).
- Güncel sezon durumu `VERIFIED_AVAILABLE` / `STALE` / `UNAVAILABLE` değerlerinden biridir.
  `VERIFIED_AVAILABLE` için iki koşul gerekir: dal ucu bugün çözülmüş olmalı ve tarihi geçmiş ama sonucu
  olmayan maç bulunmamalı. Bu durum tahmin uygunluğunu geçirmez; tarihsel görünümü de kapatmaz.

### Çoğaltma ve çelişki kuralları

- Ham veri kaynak bazında ayrı kalır. Birleştirilmiş görünümde aynı gerçek maç bir kez sayılır. Eşleme, aynı
  lig-sezon bağlamında kesin takım kimliği ve aynı tarihle yapılır (`data.teams` sözleşmesi; yaş ve
  kategori, örneğin U21 veya kadın takımı, farklı takımdır).
- Tarih toleransı uygulanmaz. Aynı eşleşme farklı tarihlerde görünürse incelemeye ayrılır
  (`TARIH_UYUSMAZ`). Kesin kimliği bulunamayan ad da incelemeye ayrılır.
- Skor çelişkisi çoğunluk oyuyla veya en yeni commit seçilerek çözülmez. Maç `CELISKI` olarak özetlerden
  çıkarılır ve kaynaklarıyla birlikte listelenir.
- datasets ile xgabora aynı asıl kökenden (football-data.co.uk) beslenir. Bu yüzden ikisinin uyuşması
  bağımsız doğrulama sayılmaz (`bagimsiz_kaynak`).
- Farklı tanımlı metrikler birleştirilmez. xG yalnızca StatsBomb'dandır.

## 3. Kaynak bazında okuyucular

- **openfootball:** mevcut sonuç okuyucusu (`openfootball-sonuc-v2`) kullanılır. Eksik İY eksik kalır;
  tek istisna MS 0-0 maçıdır, burada İY mantıksal olarak 0-0 kaydedilir ve işaretlenir. Tarihi sezon
  dışında kalan kayıt, yılı tahmin edilip düzeltilmez; karantinaya alınır.
- **datasets:** `datapackage.json` dosyasından kaynak listesi okunur. Her sezon CSV'si için geçerli maç, MS,
  İY, birebir tekrar, karantina nedenleri ve alan bazında kapsam sayılır. Depo oran sütunlarını attığı
  için oran üretilmez.
- **xgabora:** büyük `Matches.csv` bir kez önbelleğe alınır ve alt kümeler yerelde süzülür (uygulama
  açılışında yüklenmez). Ham skor ve istatistik sütunları ayrı tutulur. Elo, form ve küme sütunları
  türetilmiş alanlardır; oran sütunları piyasa alanıdır. Bunlar model girdisi yapılmaz. README'ye göre
  Elo kökeni 2025-06-15'ten sonra değişmiştir; bu not kaynak kaydındadır.
- **Hudl/StatsBomb:** önce `competitions.json` ve maç listeleri okunur. Kapsam olduğu gibi gösterilir:
  tam sezon mu, seçili takımın maçları mı. Olay okuyucusu en çok 12 maçlık, önceden tanımlı bir örneklemle
  doğrulanır: tarih, sonra maç kimliği sırasıyla ilk N maç; sonuçlara bakılmaz. 360 verisi indirilmez.
  Olaylardan skor şöyle çıkarılır: 1. ve 2. devre normal süredir, 3. ve 4. devre uzatmadır, 5. devre
  penaltı atışlarıdır ve skora girmez. Kendi kalesine gol olayı tek sayılır ve çifti denetlenir. Sonuç
  maç meta verisiyle uzlaştırılır; uyuşmazsa skor üretilmez.

## 4. Kullanım kapsamı (işlem bazında)

`source_registry.ARCHIVE_SCOPES`, kaynak × işlem tablosudur. Kayıtta olmayan bir kaynak veya işlem
`DOGRULANAMADI` sayılır.

| İşlem | openfootball | datasets | xgabora | Hudl/StatsBomb |
|---|---|---|---|---|
| belge inceleme | izinli | izinli | izinli | izinli |
| alma / saklama | izinli | izinli (erişim onayıyla) | izinli (erişim onayıyla) | izinli |
| envanter | izinli | izinli | izinli | izinli |
| tarihsel analiz | izinli | **doğrulanamadı** | **doğrulanamadı** | izinli (araştırma) |
| model eğitimi | izinli | doğrulanamadı | doğrulanamadı | doğrulanamadı |
| tahmin gösterimi | izinli | doğrulanamadı | doğrulanamadı | doğrulanamadı |
| ticari kullanım | izinli | doğrulanamadı | doğrulanamadı | **yasak (belgeli)** |
| yeniden dağıtım | izinli | izin varsayılmaz | izin varsayılmaz | **yasak (belgeli)** |

datasets ve xgabora için deponun lisansı tek başına yeterli değildir: asıl kaynağın (football-data.co.uk)
koşulları bu kullanım için doğrulanmadı. Bu yüzden bu iki kaynağın satırları analiz tablosuna girmez;
katalogda yalnızca envanter sayıları görünür. Onay kutusu veya etiket değişikliği bu kapsamı açmaz.

# Tek ligde gerçek veri pilotu (S4-PILOT-01)

openfootball/football.json maç sonuçlarıyla (CC0) İngiltere Premier League (`E0`) için uçtan uca akış:

kaynak (sabit commit) → sonuç ayrıştırma ve karantina → kaynak kökeni → takım kimliği → takvim kapsamı → mevcut gol
motoruyla ayrı pilot eğitimi → ortak veri uygunluk kontrolü → ayrı pilot defterine A/B/C kaydı.

Yeni tahmin motoru, yeni pazar veya yeni eşik yoktur: mevcut `GoalEngine` (`MIN_TRAIN_ROWS = 500`, pazar doğrulaması
için en az 200 pozitif ve mevcut kalibrasyon kuralları), `eligibility` (politika `veri-uygunluk-v2`) ve
`forecast_log` (protokol `ileriye-donuk-olcum-v3`) kullanılır. Gerçek oran yoktur: EV/ROI hesaplanmaz, bahis adayı
üretilmez, `stake_units = 0`.

## Yalıtım

- Bütün yazmalar **yalnızca** `--ev` ile verilen pilot klasörüne yapılır; `--ev` zorunludur (varsayılan yol yoktur).
- Pilot klasörü uygulama veri klasörüyle (`%LOCALAPPDATA%\BahisTahmin`, Linux `~/.local/share/BahisTahmin` veya
  `BAHIS_TAHMIN_HOME`) aynı olamaz, onun içinde olamaz ve onu içeremez; boş olmayan ve pilot işareti (`pilot.json`)
  taşımayan klasöre yazılmaz. Pilot komutları uygulama veri klasörünü oluşturmaz, okumaz ve değiştirmez (mevcut veri
  deposu, defter, model ve ayarlar).
- Salt okunur: `pilot-kapsam` ve `pilot-tahmin` (bayraksız; kuru çalıştırma). Yazan: `pilot-hazirla`, `pilot-egit`,
  `pilot-tahmin --uygula`.
- Otomatik güncelleme veya zamanlayıcı yoktur; her adım elle çalıştırılır.

## Komutlar

`<PILOT_KLASORU>`: sizin seçeceğiniz, uygulama veri klasörünün dışında yeni ve boş bir klasör. `<COMMIT>`:
openfootball/football.json deposunun 40 karakterlik commit özeti. Güncel ucu şöyle görebilirsiniz (git kuruluysa):

```bash
git ls-remote https://github.com/openfootball/football.json refs/heads/master
```

`--ref` verilmezse program ucu GitHub API'sinden çözmeye çalışır; çözemezse indirme yapmaz ve `--ref` ister
(sabitlenmemiş dala karşı indirme yapılmaz).

Linux / macOS (proje klasöründe, sanal ortam etkin):

```bash
python -m bahis_tahmin pilot-hazirla --ev <PILOT_KLASORU> --ref <COMMIT> --sezon 10
python -m bahis_tahmin pilot-kapsam  --ev <PILOT_KLASORU>
python -m bahis_tahmin pilot-egit    --ev <PILOT_KLASORU>
python -m bahis_tahmin pilot-tahmin  --ev <PILOT_KLASORU>            # kuru çalıştırma, yazmaz
python -m bahis_tahmin pilot-tahmin  --ev <PILOT_KLASORU> --uygula   # pilot defterine değişmez kayıt
```

Windows (Komut İstemi, proje klasöründe):

```bat
.venv\Scripts\python -m bahis_tahmin pilot-hazirla --ev "<PILOT_KLASORU>" --ref <COMMIT> --sezon 10
.venv\Scripts\python -m bahis_tahmin pilot-kapsam  --ev "<PILOT_KLASORU>"
.venv\Scripts\python -m bahis_tahmin pilot-egit    --ev "<PILOT_KLASORU>"
.venv\Scripts\python -m bahis_tahmin pilot-tahmin  --ev "<PILOT_KLASORU>"
.venv\Scripts\python -m bahis_tahmin pilot-tahmin  --ev "<PILOT_KLASORU>" --uygula
```

Bağımsız katılımcı referansı eklemek için `pilot-hazirla ... --katilimci <DOSYA.json>` (aşağıda). Komutlar JSON
özet yazar (yalnızca sayılar ve kimlikler; maç satırı yok). Pilot hatasında çıkış kodu 3'tür.

- `--sezon N`: içinde bulunulan sezon + önceki N tamamlanmış sezon (varsayılan 10; devam eden dahil en çok 17 dosya).
- `--gun N`: fikstür penceresi (gün, varsayılan 10).
- Aynı commit ve aynı dosya özetiyle tekrar çalıştırmada dosyalar yeniden indirilmez; depo aynı satırlarla yeniden
  kurulur (idempotent). Yeni commit verilirse dosyalar yeni geçici yola indirilir; başarısız indirmede eski
  commit'in dosyası kullanılmaz.

## Kaynak kökeni

Her sezon dosyası için veri deposunun `data_meta.json → kaynak_kokeni` kaydında depo (`openfootball/football.json`),
dosya yolu, sabit commit, alınma anı (dosyanın alındığı gerçek an; içindeki skorların güncelliği **değil**), dosya
SHA-256, ayrıştırıcı sürümü (`openfootball-sonuc-v2`; eski pilotlar `-v1`) ve satır özeti tutulur. Doğrulama her
kaydı kendi sürümüyle yeniden üretir; sürümler birbirinin yerine geçmez. Eğitim ve tahmin öncesinde önbellekteki
dosya yeniden ayrıştırılır; depodaki satırlar birebir aynı değilse `KAYNAK_KOKENI_DOGRULANAMADI` (eğitim ve tahmin
engeli). Etiketi `openfootball-sonuc` yapılmış başka kaynak satırları bu kontrolü geçemez.

## Sonuç adaptörü

`data/parsers.parse_openfootball_results`:

- `score: {"ft": [a, b], "ht": [c, d]}` → maç sonu ve ilk yarı. `ht` yoksa ilk yarı **eksik** kalır; 0-0 yapılmaz,
  MS'den tahmin edilmez.
- Tek istisna MS 0-0 maçlardır: kaynak bu maçlarda `ht` alanını hiç yazmaz. 0 ≤ İY ≤ MS = 0 olduğundan İY zorunlu olarak
  0-0'dır; bu bir tahmin değil, mantıksal sonuçtur. v2 bu maçlarda İY'yi 0-0 kaydeder ve `iy_mantiksal` ile işaretler.
  v1 (S4-PILOT-01) bu maçları "İY bilinmiyor" sayıyordu: bütün MS 0-0 maçlar A/C etiketlerinden, ilk yarı güç
  izleyicilerinden, bA/bC taban oranlarından ve M5 eğitiminden dışlanıyordu (rastgele olmayan seçim; S4-MODEL-01).
- `score: [a, b]` → yalnızca maç sonu (ilk yarı sayılmaz). Skorsuz maç oynanmamıştır.
- Karantina (kayda alınmaz, nedenle sayılır): negatif/kesirli/boolean/30'dan büyük skor (`SKOR_GECERSIZ`), bilinmeyen
  alan veya biçim (`BICIM_BILINMIYOR`), uzatma/penaltı alanı (`UZATMA_ALANI`), İY > MS (`IY_MS_CELISKI`), skorlu
  ama durumu belirtilmiş maç (`DURUM_BELIRSIZ`), geçersiz tarih/takım, sezon penceresi dışı tarih
  (`TARIH_SEZON_DISI`; yıl tahmin edilip düzeltilmez), aynı maçın farklı içerikli kayıtları (`CAKISAN_KAYIT`, ikisi
  de) ve aynı gün iki maç oynayan takım (`AYNI_GUN_IKI_MAC`). Birebir tekrar sayımı artırmaz.
- Fikstür adaptörü (`parse_openfootball`) değişmedi; fikstür etiketi `openfootball`, sonuç etiketi
  `openfootball-sonuc`.

## Takım kimliği

football.json eski sezonlarda kulüp adlarını "FC"siz (ör. "Manchester City"), 2020/21'den itibaren "FC"li yazar.
Mevcut kimlik sözleşmesi bunları otomatik birleştirmez. Pilot, yalnızca sağlayıcının kendi kulüp kaydında
(openfootball/clubs, commit ae3800227c44, `europe/england/eng.clubs.txt`, CC0) **o kulübün alternatif adı olarak
listelenen** ve pilot verisinde görülen 16 adı kayıttaki kanonik ada çevirir (`OPENFOOTBALL_CLUB_ALIASES["E0"]`).
Kayıtta olmayan kısaltmalar veya benzer adlar birleştirilmez. Eşleme ayrıştırıcının parçasıdır; köken doğrulaması
aynı eşlemeyle yeniden üretir.

## Bağımsız katılımcı referansı

Takvim tamlığı ve 365 günlük pencere, kaynak takviminin **bağımsız** bir katılımcı listesiyle doğrulanmasını ister.
Sonuçlar ve takvim aynı dosyadan (aynı veri zinciri) geldiği için kaynak kendini doğrulayamaz; referans verilmezse
uygunluk `KAYNAK_KAPSAMI_KISMI` döner ve tahmin üretilmez. Referansı ilgili sezonların resmî kaynağından (ör. ligin
resmî kulüp listesi) kendiniz hazırlarsınız; program bu bilgiyi uydurmaz ve bugünkü katılımcıları eski sezonlara
uygulamaz:

```json
{"lig": "E0", "kaynak": "https://...resmi-kaynak...", "alinma_utc": "2026-10-11T08:00:00+00:00",
 "sezonlar": {"2026/27": ["...20 kulüp..."], "2025/26": ["...20 kulüp..."]}}
```

Adlar pilot deposundaki adlarla **kesin** eşleşmelidir. Eşleşmeyen veya belirsiz ad o sezonu geçersiz kılar;
`pilot-kapsam` çıktısında `eslesmeyen_adlar` yalnızca yazımı düzeltmek için öneri gösterir (öneri kimlik kanıtı
değildir). Dosyanın kopyası ve özeti pilot klasörüne kaydedilir; kopya değişirse referans kullanılmaz.

## Tahmin kaydı

`pilot-tahmin`, kaynaktaki gerçek yaklaşan fikstürler için her maçta üç pazar (A, B, C) kaydı hazırlar. Gerçek sistem
saati kullanılır; karar hedefi maç günü 00:00 (İstanbul) olup geçmişse `PENCERE_KACIRILDI`; yazma anında saat yeniden
denetlenir. Uygunluk geçmeyen maç nedenli `TAHMIN_YOK` olur. Aynı maç/pazar/protokol/model kohortu ikinci kez
yazılmaz. Çıktıdaki `model_dogrulama`, modelin pazar başına doğrulama etiketini (`MODEL_NOT_VALIDATED` /
`VALIDATED_FOR_PAPER_TRADING`) gösterir; bu olasılık kalitesi etiketidir, bahis avantajı değildir.

## Model aşama tanılaması (S4-MODEL-01)

`pilot-tani`, eğitilmiş pilot modelinin iç zaman sıralı doğrulamasını aynı veri ve aynı bölmeyle **bir kez** yeniden
üretir. Her doğrulama katında tek bir M10 eğitilir; aşamalar bu aynı modelin kendi bileşenlerinden okunur:
S0 M0_taban → S1 yapısal ortak dağılım (M10'un M5 tabanı) → S2 B/C lojistik hedefleri → S3 IPF (q öncesi) → S4 nihai.

```bash
python -m bahis_tahmin pilot-tani --ev <PILOT_KLASORU> --cikti <TANI_KLASORU>
```

```bat
.venv\Scripts\python -m bahis_tahmin pilot-tani --ev "<PILOT_KLASORU>" --cikti "<TANI_KLASORU>"
```

- Pilot dosyaları değişmez. Çıktı klasörü zorunludur; pilot klasörüyle veya uygulama veri klasörüyle çakışamaz.
- Model dosyası yüklenmeden önce şu kontroller yapılır: pilot verisinin kökeni, manifestteki veri özeti ve pilot model
  bilgisi aynı veriyi göstermeli. Model dosyasının özeti manifestle eşleşmezse dosya yüklenmez.
- Yeniden hesaplanan doğrulama kayıtlı doğrulamayla bit düzeyinde uyuşmazsa `ayni_deney: false` yazılır.
- Ölçütler ürün koduna bağımlı olmadan hesaplanır:
  - log-kayıp doğrudan formülle;
  - kalibrasyon eğimi cezasız Newton-IRLS ile; sabit tahmin, tek sınıf ve ayrışmada eğim tanımsız döner;
  - AUC sıra formülüyle.
- Güven aralıkları ISO hafta blok bootstrap ile hesaplanır (1000 tekrar, tohum 20261011, önceden sabit). Lojistik katman
  kat başına bir kez eğitildiği için hatası bir sezonun bütün haftalarına ortak bir kayma olarak yansır; hafta blokları
  bu bağımlılığı yakalamaz, aralıklar iyimser olabilir. Sezon sayısı az olduğundan sezon kümeli bir aralık da güçsüzdür.
- `asamalar.csv` gerçek maç satırları içerir ve yalnızca yerel çıktı klasöründe kalır.
- `--ayristirici openfootball-sonuc-v2` karşılaştırmalı tekrar yapar: aynı kaynak dosyaları o sürümle yeniden ayrıştırılır
  (aynı maç kümesi) ve aynı bölmeyle bir walk-forward çalışır. Sonuç kayıtlı doğrulamanın tekrarı değildir
  (`ayni_deney: false`). Pilot verisi ve modeli değişmez, yeni model dosyası yazılmaz.

```bash
python -m bahis_tahmin pilot-tani --ev <PILOT_KLASORU> --cikti <TANI_KLASORU_2> --ayristirici openfootball-sonuc-v2
```

## Saklama

Pilot dosyaları (ham sezon dosyaları, veri deposu, model, defter) yalnızca pilot klasöründedir; depoya veya
dağıtıma konmaz. Bulut/geçici bir ortamda üretilen pilot klasörü o ortamla birlikte silinir; kalıcı saklama sizin
bilgisayarınızda bu komutları çalıştırmanızla olur.

## Bilinen sınırlar

- Kaynak güncelliği: commit tarihi ve dosyadaki son skorlu maç ayrı ölçülür (`son_tamamlanan`,
  `bilgi_kesiminden_once_sonucsuz`). Tarihi geçmiş ama skoru olmayan maçlar, bağımsız referansla kapsam doğrulandığında
  `KAYNAK_DURUMU_BELIRSIZ` / `LIG_DURUMU_BELIRSIZ` üretir; kaynak güncellenmeden tahmin açılmaz.
- Lige yeni katılan ve son 365 günde ligde 10 maçtan az oynayan takım `TAKIM_GECMISI_YETERSIZ` kalır (eşik
  düşürülmez).
- Tek lig ve on sezon, mevcut doğrulama kurallarını geçmek için çoğu pazarda yetersiz olabilir; sonuç
  `MODEL_NOT_VALIDATED` olarak açıkça gösterilir.

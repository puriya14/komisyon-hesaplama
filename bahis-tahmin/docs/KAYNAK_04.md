# KAYNAK-04 — Serie B, La Liga 2 ve Ligue 2 için ESPN (onaylı kaynak)

> **KAYNAK-05 eki.** Süper Lig (`tur.1`) ve 2. Bundesliga (`ger.2`) da ESPN liglerine eklendi. Bu iki ligin
> openfootball metin dosyalarında 11 Eylül'den sonra sonuç yok (FIKSTUR-03).
>
> Kural: Ligin verisi football-data'dan gelmiyorsa ve ESPN onaylıysa önce ESPN denenir. ESPN'den veri gelen ligde o
> güncellemede openfootball'un sonuçları, fikstürleri ve takvimi kullanılmaz; aynı sezon için ESPN takvimi varsa
> uygunluk kontrolü openfootball takvimini okumaz. Böylece geride kalmış bir takvim yanlış "son maç sonucu
> bilinmiyor" uyarısı üretmez ve aynı maç iki farklı tarihte listelenmez.
>
> ESPN'e ulaşılamazsa veya onay geri alınırsa openfootball yedeği eskisi gibi çalışır. Bu durumda eski ESPN takvimleri
> silinir ve ESPN satırları bir sonraki güncellemede veriden kalkar. Testler: `tests/test_kaynak_05.py`.

## Neden

football-data.co.uk erişilemediğinde bu üç ligin yaklaşan maçı yoktu ve verisi GitHub yedeğinde 30–31 Ağustos'ta
kalıyordu. Açık lisanslı, güncel bir kaynak arandı:

- **GitHub'daki açık kaynaklarda 2026-27 verisi yok.** openfootball (italy, espana, europe/france),
  oritzio/football-database, datasets/football-datasets, footballcsv ve worldfootballR_data (FBref) kontrol edildi.
- **football-data.org.** Ücretsiz katmanı bu ligleri içermiyor.
- **API-Football.** Ücretsiz planının güncel sezonu vermediği bildiriliyor ve anahtar gerekiyor.
- **TheSportsDB.** Ücretsiz anahtar sorgu başına az maç veriyor.

Kullanıcı, ESPN'in herkese açık skor tablosu uç noktasını **onayla açılan bir kaynak** olarak eklemeyi seçti.

## Kullanım koşulları

`site.api.espn.com` uç noktası belgelenmemiştir ve açık bir lisans metni yoktur. Bu yüzden:

- **İndirme onayı.** Kaynak yalnızca kullanıcının indirme onayıyla kullanılır. Onay yoksa hiç istek gönderilmez.
- **Kişisel kullanım beyanı.** Sonuçlar model eğitimi ve tahminde yalnızca bu beyanla kullanılır (VERI-01 ile aynı
  kural). Beyan ticari kullanım veya yeniden dağıtım hakkı vermez.
- **GitHub veri profili.** Bu profilde ESPN kullanılmaz.
- **Ne zaman kullanılır.** Yalnızca ligin verisi football-data'dan gelmiyorsa. KAYNAK-05'ten beri ESPN'den veri gelen
  ligde openfootball kullanılmaz (yukarıdaki ek).

Onay penceresinin sürümü 3'e çıktı (`CONSENT_SCHEMA`). Mevcut kullanıcılara pencere bir kez yeniden gösterilir ve ESPN
için iki kutu (indirme onayı, kişisel kullanım beyanı) çıkar. Komut satırında:

```
python -m bahis_tahmin update --accept-terms espn --kisisel-kullanim espn
```

## Ne alınır

Kod: `data/espn.py`, `DataStore._from_espn`.

Lig başına, bir önceki sezonun başından fikstür penceresinin sonuna kadar aylık istek atılır. Ay bittikten sonra alınan
yanıt önbellekte kalır; diğerleri saatlik yenilenir.

1. **Fikstür.** Oynanmamış maçlar yerel saatle eklenir. Saat kesin değilse boş kalır ve arayüz "saat bilinmiyor"
   gösterir.
2. **Eksik dönem sonuçları.** Veri deposunun ligdeki son maç gününden sonra normal sürede bitmiş ve depoda olmayan
   maçlar eklenir. Etiketleri `espn` olur ve her güncellemede yeniden kurulur. Oran ve istatistik yoktur. İlk yarı
   skoru yalnızca devre skorları tutarlıysa alınır.
3. **Sezon takvimi.** `raw/espn/<sezon>/<lig>.json` dosyasına yazılır ve uygunluk kontrolü okur. ESPN'de oynanmış
   görünüp veri deposunda olmayan maç "veride eksik maç" olarak işaretlenir. ESPN fikstürü bu takvimde aynı adlarla
   yeniden doğrulanır.

Okunmayanlar: uzatma, penaltı ve hükmen gibi normal süre dışı sonuçlar; biçimi tanınmayan kayıtlar. Ertelenen veya
iptal edilen maçlar fikstür ya da sonuç sayılmaz. Atlanan kayıtlar nedenleriyle rapora yazılır.

## Takım adları

ESPN adları ("Cosenza 1914", "FC Südtirol Bolzano" gibi) veri deposu adlarından farklı olabilir. Bu ortamdan ESPN'e
erişilemediği için takma adlar önceden türetilemedi. Eşleme her güncellemede kullanıcının bilgisayarında, VERI-01 ve
FIKSTUR-03 ile aynı kanıt kuralıyla yapılır:

1. **Aynı ad.** Yazım farkı yok sayılır.
2. **Maç kanıtı.** Aynı lig, tarih ±1 gün, aynı MS skoru (ikisinde de varsa aynı İY skoru) ve tek aday. En az 3 tekil
   maç, oyların en az %90'ı tek takımda ve ev ile deplasman oyları aynı takımda olmalı.
3. **Sezon kadrosu kısıtı.** Lige yeni çıkan takımlar için kullanılır:
   - İki kaynağın güncel sezon kadrosu aynı büyüklükte olmalı.
   - Kalan her ad, bütün oylarıyla kalan takımlardan tekine işaret etmeli.
   - Tek ad tek takım kalmışsa eleme ile eşlenir.

Güvenlik kuralları:

- Aynı ad kanıtla çelişirse eşleme yapılmaz.
- İki ad aynı takıma düşerse ikisi de eşlenmez.
- Benzerlikle eşleme yapılmaz.

Eşleşmeyen adın fikstürü nedenli "tahmin yok" olur ve sonucu eklenmez. Rapor bu adları yazar. Kararlar ve kanıtlar
veri deposunda `espn_eslesme` kaydında saklanır.

## Doğrulama

`tests/test_kaynak_04.py`, sentetik ESPN yanıtlarıyla şunları denetler:

- ayrıştırıcı ve "tahmin yapmama" kuralları
- maç kanıtı, kadro kısıtı ve çelişki durumları
- onaysız istek gönderilmemesi
- onay ile beyanın eğitim hakkına etkisi
- fikstürün takvimde yeniden doğrulanması ve bilinen eksiğin görünmesi
- eşleşmeyen adın nedenli "tahmin yok" olması

Bu ortamda gerçek veriyle güncelleme denendi. ESPN'e erişilemedi; uygulama bunu "ESPN'den veri alınamadı" diye
raporladı ve diğer kaynaklarla sonuç değişmedi.

## Bilinen sınırlar

- **İlk gerçek çalıştırma.** Uç nokta bu ortamdan denenemedi; yanıt biçimi bilinen yapısına göre okunur. İlk
  gerçek çalıştırma kullanıcının bilgisayarında olur. Biçim farklıysa kayıtlar atlanır ve rapora yazılır; maç
  uydurulmaz.
- **Belgelenmemiş uç nokta.** ESPN uç noktayı haber vermeden değiştirebilir.
- **Eşleşmeyen rakip.** Bir takımın eşleşmeyen bir rakiple oynadığı maç takvimde o takıma bağlanamaz. Bu maç eksikse
  "veride eksik maç" görünmez. Raporda eşleşmeyen adlar yazar.

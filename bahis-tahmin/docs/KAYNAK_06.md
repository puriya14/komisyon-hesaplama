# KAYNAK-06 — Bütün ligler için ESPN

İstek: "diğer ligler için de espn ekle". KAYNAK-04 (Serie B, La Liga 2, Ligue 2) ve KAYNAK-05 (Süper Lig,
2. Bundesliga) ESPN'i beş ligde açmıştı. Bu değişiklik uygulamanın kalan bütün liglerini de ekler.

Kullanım koşulları değişmedi: ESPN yalnızca indirme onayıyla istenir ve sonuçları yalnızca kişisel kullanım beyanıyla
model eğitimi ve tahminde kullanılır (bkz. [`KAYNAK_04.md`](KAYNAK_04.md)).

## Kural

Kural KAYNAK-05 ile aynıdır:

- Ligin verisi football-data.co.uk'tan geliyorsa ESPN kullanılmaz.
- Gelmiyorsa ve ESPN onaylıysa önce ESPN denenir.
- ESPN'den veri gelen ligde o güncellemede openfootball'un sonuçları, fikstürleri ve takvimi kullanılmaz.
- ESPN'den veri gelmezse, takım adları yeterince eşlenemezse veya onay geri alınırsa openfootball yedeği çalışır.

## Lig kodları

Kod: `espn.ESPN_LEAGUES`.

Uygulamanın 38 liginin hepsinin bir ESPN kodu var. Kodlar, ESPN lig listesinin topluluk derlemesinden doğrulandı
(`pseudo-r/Public-ESPN-API`, `docs/sports/soccer.md`). Örnekler: İngiltere `eng.1`–`eng.5`, İskoçya `sco.1`–`sco.4`,
`ned.1`, `bel.1`, `por.1`, `gre.1`, `usa.1`, `mex.1`, `arg.1`, `bra.1`, `jpn.1`, `chn.1`.

Almanya'nın küme düşme ve yükselme play-off'ları ESPN'de ayrı kodlardadır (`ger.playoff.relegation`,
`ger.2.promotion.relegation`), bu yüzden lig verisine karışmaz.

**Doğrulanamayan dört kod** (`espn.UNVERIFIED`): İsviçre `sui.1`, Finlandiya `fin.1`, Polonya `pol.1`, Romanya
`rou.1`. Bu ligler listede yok; kodlar ESPN'in ülke.kademe düzenine göre yazıldı. ESPN bu ligi vermezse:

- Hiç maç alınamamışken art arda 3 aylık istek başarısız olursa lig bırakılır, kalan aylar istenmez.
- Rapor "ESPN'de bu lig bulunamadı; 'sui.1' lig kodu önceden doğrulanamamıştı" yazar.

## Yeni güvenlik önlemleri

### 1. Önceki sezonun lig dışı maçları takvime girmez

**Sorun.** Uygunluk kontrolü ESPN takviminde oynanmış görünüp veride olmayan maçı "veride eksik maç" sayar
(`DEPODA_EKSIK_MAC`). Bu gerekçe bahis adaylığını engeller.

football-data ana liglerde sezon sonu play-off maçlarını tutmaz. Veride gözlenen maç sayıları:

| Lig | 2025/26 maç sayısı | Play-off veya ikinci aşama |
|---|---|---|
| Championship | 552 (24 × 23) | yok |
| Eredivisie | 306 | yok |
| Serie B | 380 | yok |
| La Liga 2 | 462 | yok |
| Belçika | 311 | var |
| Yunanistan | 236 | var |

ESPN bir play-off maçını lig koduyla verirse, o maç önceki sezonun takviminde kalıcı olarak "veride eksik" görünürdü.
Önceki sezon tamamlanmadığı için bu maçlar hiçbir zaman eklenmez.

**Düzeltme** (`DataStore._from_espn`). Deponun bitmiş saydığı bir sezon için ESPN takvimi, deponun o sezondaki son maç
gününde (+1 gün) kesilir. Bitmiş sezon, depoda kendisinden sonra başka sezonu olan sezondur. Kesilen maç sayısı
`espn_eslesme.<lig>.sezon_sonu_disarida` kaydına yazılır.

Belçika ve Yunanistan'da ikinci aşama depoda olduğu için kesim tarihi o aşamanın son günüdür ve aşama korunur.

### 2. Ad eşlemesi yetersizse ESPN kullanılmaz

Ortak dönemdeki ESPN adlarının yarısından azı eşlenirse lig için ESPN kullanılmaz ve openfootball yedeği çalışır.
Ortak dönem, deponun son maçına kadar olan dönemdir. Bu, yanlış lig kodu veya başka bir yarışmanın verisi gibi durumlara
karşı korur. Rapor eşlenen ad sayısını yazar.

### 3. Toplu uyarı

ESPN'e hiç ulaşılamıyorsa her lig için ayrı satır yazılmaz. Rapor tek satır yazar: "ESPN'den 16 lig için veri
alınamadı (bağlantı kurulamadı): T1, E0, …".

## Veri deposu geride kaldığında (ek ligler)

GitHub yedek veri seti ek liglerde (Arjantin, ABD, Brezilya vb.) Aralık 2024'te bitiyor.

- **İstek penceresi.** Normalde istekler bir önceki sezonun başından başlar. Bu ligde ortak dönem olmaz ve takım
  adları maç kanıtıyla eşlenemezdi. Depo bir önceki sezonun başından da gerideyse istekler deponun son maçından
  120 gün önce başlar (en fazla 3 yıl geriye).
- **Eksik dönem.** Deponun son maçından sonraki bütün ESPN sonuçları eklenir, yalnızca güncel sezon değil. Ana liglerde
  sonuç değişmez, çünkü depo güncel sezonda.
- **Lige sonradan katılan takım** (`espn` kural 4). Bu kural yalnızca depo güncel sezona hiç ulaşmıyorsa uygulanır.
  Deponun son maçından sonra lige katılan bir takımın depoda maçı olamaz. Sıra:
  1. Aynı ülkenin bütün depo adlarında aynı ad aranır.
  2. Bulunmazsa takım ESPN adıyla yeni takım olarak eklenir.

  Ad bir depo adıyla çakışıyorsa takım eklenmez. Rapor eklenen takımları yazar.

## Ad eşlemesi iyileştirmeleri

Bu üç kural, aşağıdaki ESPN benzetiminde görülen eşleşmeme durumları için eklendi.

1. **Ad değişikliği.** İki ESPN adı aynı depo takımına düşüyorsa (ör. "Aberdeen FC" ve "Aberdeen") iki ad da eşlenmiş
   kalır. Koşul: iki adın kullanıldığı dönemler hiç çakışmamalı. Aynı dönemde iki ad aynı takıma düşüyorsa hangisinin o
   takım olduğu bilinemez ve ikisi de eşlenmez (eski kural).
2. **Ligler arası kanıt** (`espn.share_mappings`). ESPN adı ligden bağımsızdır. Bir ligde kanıtla eşlenmiş ad, aynı
   ülkenin başka bir liginde kanıtı olmayan veya yeni takım sayılmış aynı ad için kullanılır. Örnek: lige yükselen
   takım, alt ligdeki geçen sezon maçlarıyla eşlenir. Kanıt kullanılmaz:
   - hedef takım o ligde başka bir ada verilmişse;
   - diğer ligler farklı takımlar gösteriyorsa;
   - lig başka bir ülkedeyse.
3. **Kadro elemesi.** Kadro kısıtında oy alan adlar seçildikten sonra geriye tek ad ve tek takım kalırsa ad o takıma
   eşlenir. Adın oyu varsa hepsi o takımda olmalıdır.

## İstek sayısı

- **İlk güncelleme.** Lig başına bir önceki sezonun başından fikstür penceresine kadar aylık istek atılır: Avrupa
  takvimli liglerde yaklaşık 16, deposu geride olan ek liglerde yaklaşık 27.
- **Sonraki güncellemeler.** Tamamlanmış ayların yanıtları önbellekte kalır. Lig başına 1–2 istek atılır.
- **ESPN'e ulaşılamıyorsa.** Lig başına tek istek denenir. İndirici iki başarısız denemeden sonra sunucuyu "ulaşılamıyor"
  sayar ve kalan istekler hemen düşer.

Güncelleme sırasında ilerleme çubuğu "ESPN verileri alınıyor: <lig> (i/n)" gösterir.

## Doğrulama

**Testler** (`tests/test_kaynak_06.py`, 10 test):

- bütün liglerin kodu ve doğrulanamayan dört kod;
- Championship: önceki sezonun play-off maçları takvime girmez;
  - karşı olgu: takvime eklenirlerse `DEPODA_EKSIK_MAC` çıkar;
- eski sezon takvimi dosyasının silinmesi ve lig başına ilerleme mesajı;
- ABD (depo Kasım 2024'te kalmış):
  - istekler Ağustos 2024'ten başlar;
  - adlar ortak dönemden eşlenir;
  - 2025 ve 2026 sonuçları eklenir;
  - lige sonradan katılan takım ESPN adıyla eklenir;
  - uygunlukta eşleme ve eksik maç engeli yoktur;
- yeni takım kuralı yalnızca depo güncel sezona ulaşmıyorsa uygulanır;
- ad değişikliği (dönemler çakışıyorsa eşleme yok);
- ligler arası kanıt kuralları;
- kadro elemesi;
- uçtan uca: yaz arasında Bundesliga'ya çıkan takımın 2. Bundesliga kanıtıyla eşlenmesi;
- eşlemesi yetersiz lig için ESPN kullanılmaması;
- ESPN'de bulunmayan doğrulanamamış kodda 3 istekten sonra durulması.

**Bozma denetimi.** Sezon sonu kesimi, yeni takım kuralı ve ligler arası kanıt teker teker kapatıldığında ilgili
testler başarısız oluyor.

**ESPN benzetimi (gerçek veri).** Bu ortamdan ESPN'e ulaşılamıyor. Bu yüzden openfootball'un gerçek 2025-26 ve
2026-27 maçları, uzun kulüp adlarıyla ESPN yanıt biçiminde verildi (ör. "Manchester United FC", "SC Paderborn 07").
16 varsayılan lig için güncelleme çalıştırıldı. Eşlemeler, doğrulanmış openfootball takma adlarıyla karşılaştırıldı:

| Sonuç | Sayı |
|---|---|
| Doğru eşleme | 329 |
| Ad değişikliği eşlemesi (hepsi doğru, ör. "Aberdeen FC" / "Aberdeen") | 26 |
| Yanlış eşleme | 0 |
| Eşleşmeyen | 4 (Belçika) |

Belçika'daki 4 eşleşmeyen adın nedeni benzetim kaynağıdır: openfootball aynı kulübe iki sezonda tamamen farklı ad
veriyor ("Sint-Truidense VV" / "STVV"). ESPN'in adları sabittir. Üç iyileştirmeden önce eşleşmeyen sayısı 44'tü.

Diğer benzetim sonuçları:

- 121 yaklaşan maçın hepsi ESPN'den geldi. Yalnızca openfootball ile de 121 maç geliyor.
- Championship'te openfootball 2025-26 dosyasındaki 5 play-off maçı takvim dışında kaldı.
- Uygunluk kontrolünde hiçbir maçta "veride eksik maç" çıkmadı ve standart modda yeni bir bahis engeli eklenmedi.
- Süper Lig ve 2. Bundesliga'daki "son maç sonucu bilinmiyor" engeli kalktı.

**Gerçek veriyle güncelleme (bu ortam).** ESPN'e ulaşılamadı. Rapor 16 ligi tek satırda yazdı ve openfootball yedeği
öncekiyle aynı sonucu verdi (121 yaklaşan maç).

## Bilinen sınırlar

- **İlk gerçek çalıştırma** kullanıcının bilgisayarında olur. Yanıt biçimi farklıysa kayıtlar atlanır ve rapora
  yazılır; maç uydurulmaz.
- **Yeni takımın eski maçları.** Ek liglerde ESPN adıyla eklenen takımın depodaki eski maçlarıyla bağlantısı
  kurulamaz. Önce aynı ülkenin depo adlarında aynı ad aranır.
- **Güncel sezonun play-off'ları.** Güncel sezonun sonundaki play-off maçları ESPN'den eklenir (football-data'da
  olmasa da). Bunlar gerçek maçlardır.
  - Yaz arasında veri deposu yeni sezona geçmemişse, önceki sezonun son maçından sonraki ESPN maçları da eksik dönem
    sayılır. ESPN play-off'u lig koduyla veriyorsa bu maçlar o sezonun lig maçı olarak eklenir.
  - ESPN yanıtındaki aşama bilgisi doğrulanamadığı için bunlar normal sezonun eksik maçlarından ayrılamaz.
  - Depo yeni sezona geçince o sezon kapanır: takvim kesilir ve bu maçlar artık eklenmez.
- **Sıkı mod.** ESPN takvimi tur bilgisi içermediği için sıkı modda "tam sezon takvimi" kanıtlanamaz (KAYNAK-04 ile
  aynı). Standart modda bu bir engel değildir.

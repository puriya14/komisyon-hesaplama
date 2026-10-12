# FIKSTUR-03 — Diğer liglerin fikstürleri

## Belirti

football-data.co.uk erişilemediğinde Tahminler sayfasında yalnızca 8 ligin yaklaşan maçları görünüyordu: E0, E1,
D1, SP1, I1, F1, N1, P1. Süper Lig, İskoçya, Yunanistan, 2. Bundesliga ve Belçika için hiç maç yoktu.

## Neden

Yaklaşan maçlar normalde football-data'nın `fixtures.csv` dosyasından gelir. Bu dosyaya erişilemediğinde yedek kaynak
openfootball/football.json'dur. Bu depoda 2026-27 için yalnızca yukarıdaki 8 ligin dosyası var.

football.json, openfootball topluluğunun ulusal metin depolarından derlenir. Bu depolarda Football.TXT biçiminde daha
çok lig bulunur (ör. `openfootball/europe/turkey/2026-27_tr1.txt`). Uygulama bu biçimi okuyamıyordu.

## Düzeltme

### 1. Football.TXT dönüştürücüsü

Kod: `data/football_txt.py`.

Dosya football.json biçimine çevrilir. Böylece fikstür, uygunluk kontrolünün takvim kanıtı ve eksik dönemin
tamamlanması (VERI-02) aynı kodla çalışır.

Dönüştürücü dar tutuldu ve tahmin yapmaz:

- Okuduğu satırlar: tur başlığı, tarih satırı, maç satırı ve gol satırları. Gol satırları atlanır. İki yazım düzeni
  de okunur: europe deposu ("Ev  2-1 (1-0)  Deplasman") ve openligadb/Brezilya ("Ev v Deplasman 2-1 (1-0)").
- Tanımadığı satırı atlar, nedeniyle sayar ve güncelleme raporuna yazar. Maç uydurulmaz.
- Yılı yazılmayan tarihin yılı önceki tarihe en yakın yıl olarak alınır. Haftanın günü yazılmışsa tarihle uyuşmalıdır.
  Sezon penceresi dışındaki tarih okunmaz.
- Tarihi olmayan maç ("TBC", tarihsiz tur) okunmaz. Önceki turun tarihi taşınmaz.
- "[awarded]", "[postponed]" gibi notlu satırlar ve uzatma/penaltı skorları okunmaz. Bunların normal süre sonucu
  olduğu kanıtlanamaz.
- Saat yazılmayan maç, aynı günün önceki saatini alır. Hiç oynanmamış bir turun bütün maçları aynı gün ve aynı
  saatteyse bu saat yer tutucudur (ör. openligadb). Bu durumda saat boş bırakılır ve arayüz "saat bilinmiyor"
  gösterir.

### 2. Kaynak sırası

Kod: `DataStore._openfootball_file`.

1. Önce football.json denenir.
2. Dosya yoksa ligin metin dosyası denenir (`football_txt.TXT_FILES`).

Dönüştürülen takvim `raw/openfootball/<sezon>/<kod>.txt.json` dosyasına yazılır ve uygunluk kontrolü onu okur
(`eligibility.cached_coverages`). football.json dosyası sonradan çıkarsa o kullanılır ve eski dönüşüm silinir.

GitHub veri profilinde metin dosyası da tek seferde çözülen sabit commit'ten alınır (`github_kaynak.TXT_REPO_SPECS`).
Bu depolar tarihsel arşive girmez.

### 3. Köken (eksik dönemin tamamlanması)

Metin dosyasından eklenen sonuçlar da `openfootball-tamamlama` etiketini alır. Köken kaydı şunları içerir:

- ASIL metin dosyasının birebir kopyası
- `bicim: football.txt`
- dönüştürücü sürümü (`football-txt-v1`)
- dosya yolu

Doğrulama, saklanan dosyayı aynı dönüştürücüyle yeniden çevirir ve aynı satırları üretmeyi şart koşar. Dosya,
dönüştürücü sürümü veya depodaki skor değişirse satırlar hak kazanamaz.

### 4. Takım adları

Metin dosyalarındaki adlardan 12'si eşleşmiyordu. Hepsi kanıtla eşlendi (`teams._TXT_ALIASES`):

| Ülke | Kaynak adı → veri deposu adı | Kanıt |
|---|---|---|
| Türkiye | Atiker Konyaspor → Konyaspor, BB Erzurumspor → Erzurumspor | 3/3 maç |
| Türkiye | Amed → Amedspor, Aytemiz Alanyaspor → Alanyaspor | 2/2 ve 1/1 maç + sezon kadrosu |
| Yunanistan | Aris Thessaloniki → Aris, Iraklis 1908 → Iraklis, OFI → OFI Crete, Volos → Volos NFC | 1–2 maç + sezon kadrosu |
| İskoçya | Saint Johnstone FC → St Johnstone | 3/3 maç |
| Almanya | DSC Arminia Bielefeld → Bielefeld | 42/42 maç |
| Almanya | Energie Cottbus → Cottbus | 3/3 maç |

Maç kanıtının kuralı VERI-01 ile aynıdır: aynı lig, tarih ±1 gün, aynı MS (ve varsa İY) skoru, tek aday.

Yedek veri seti güncel sezonda yalnızca 2–3 tur içerdiği için bazı adların 1–2 maçı vardı. Bunlar için sezon kadrosu
kısıtı da kullanıldı:

- İki kaynağın 2026/27 kadrosu aynı büyüklükte olmalı (T1 18, G1 14).
- Diğer bütün adlar kanıtla eşleşmiş olmalı.
- Kalan her ad, bütün oylarıyla kalan takımlardan tekine işaret etmeli ve eşleme birebir olmalı.

Kanıtı olmayan adlar eklenmedi. Örnek: Belçika "OH Leuven" ve "STVV". Benzerlikle eşleme yapılmadı.

### 5. Tur etiketleri

Yeni dosyalardaki "Regular Season - 7" ve İskoçya'nın bölünme öncesi "1st Phase - 7" etiketleri numaralı normal
sezon turu sayılır (`eligibility.round_number`). "Championship Round - 1" gibi aşama etiketleri sayılmaz.

### 6. Uyarılar

- Kaynak gerideyse rapora yazılır. Koşul: bilgi kesiminden 4 günden önce oynanması gereken en az 3 maçın sonucu ne
  kaynakta ne veride olmalı. Bu durumda yaklaşan maç tarihleri de kesin olmayabilir.
- Saati olmayan yaklaşan maçlar da rapora yazılır.

## Doğrulama

**Dönüştürücü ile football.json karşılaştırması.** Aynı topluluk verisinden üretilmiş 21 dosya çiftinde (2024-25 –
2026-27; E0, E1, D1, SP1, I1, F1, N1, P1, T1, SC0, G1, D2, B1, I2, SP2, F2, E2, E3, BRA) yaklaşık 8.000 ortak maçta
0 skor farkı çıktı. Farklar yalnızca iki türden:

- Dönüştürücünün bilinçli olarak atladığı ertelenmiş veya hükmen maçlar.
- football.json'un 2025-26 League One dosyasında 1 Ocak maçlarına yanlış yıl yazması. Dönüştürücü doğru yılı
  (2026) verir.

**Uygulamanın liglerine ait 83 metin dosyası (2023–2026).** Okunmayan satırlar:

- 15 not işareti ([awarded], [postponed])
- 1 uzatmalı skor
- 244 tarihsiz maç (Belçika 2026-27)

## Sonuç (bu ortamda gerçek veri, 12 Ekim 2026)

Koşullar: football-data erişilemedi; GitHub yedek veri seti ve openfootball kullanıldı.

| Lig | Metin dosyası | Yaklaşan maç | Eksik dönemden eklenen |
|---|---|---|---|
| T1 Süper Lig | europe `turkey/2026-27_tr1.txt` | 0 → 9 (hepsi "Uyarılı": kaynakta 11 Eylül'den beri sonuç yok) | 9 |
| SC0 Premiership | europe `scotland/2026-27_sco1.txt` | 0 → 6 (5 Kullanılabilir) | 17 |
| G1 Super League | europe `greece/2026-27_gr1.txt` | 0 → 8 (5 Kullanılabilir; 1'i bugün oynandı) | 22 |
| D2 2. Bundesliga | deutschland `openliga/2026-27_de.2.txt` | 0 → 9 (hepsi "Uyarılı": kaynakta 11 Eylül'den beri sonuç yok) | 9 |
| B1 Pro League | belgium `2026-27/be1.txt` | 0 → 0 (8. haftadan sonra tarih yok) | 0 |

Toplam yaklaşan maç 88'den 120'ye çıktı; "Kullanılabilir" 59'dan 66'ya. Takım adı eşleşmeyen yaklaşan maç yok.

T1 ve D2'deki "Uyarılı" doğru sonuçtur. Kaynak dosyalarında 5–7. haftaların sonucu girilmemiş, model bu sonuçları
bilmiyor. Tahmin gösterilir ama bahis adayı olmaz. Kaynak güncellenince uyarı kendiliğinden kalkar.

## Bilinen sınırlar

- **2026-27 dosyası olmayan ligler.** openfootball'da I2, SP2, F2, E2, E3, EC ve SC1–SC3 için 2026-27 dosyası yok.
  Bu liglerde yaklaşan maç yalnızca football-data'dan gelir. Dosya eklenirse uygulama kendiliğinden kullanır
  (`TXT_FILES`).
- **Geride kalan kaynak.** Türkiye ve 2. Bundesliga dosyaları geride. Türkiye'de 7. hafta "11 Ekim" tarihli
  görünüyor ama oynanmamış; 8. hafta 18 Ekim'de saatsiz listeleniyor. Gerçek maç günü farklı olabilir; güncelleme
  raporu bunu yazar.
- **Belçika.** Dosya elle tutuluyor ve 8. haftadan sonra tarih içermiyor.
- **Avusturya ve İsviçre.** GitHub yedek veri seti 2025'te kalmış. Bu ligler için takma ad türetilmedi; eşleşmeyen
  adlar nedenli "tahmin yok" olarak gösterilir.

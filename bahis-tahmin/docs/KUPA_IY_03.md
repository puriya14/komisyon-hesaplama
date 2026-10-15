# KUPA-IY-03: Yurt içi kupalar için ilk yarı skorları

İstek: "yurt içi kupalar için de ilk yarı skorlarını ekle".

**Önceki durum.** Yurt içi kupalar (Türkiye Kupası, FA Cup, Kral Kupası, DFB-Pokal...) yalnızca ESPN'den, içinde
bulunulan ve bir önceki sezon için geliyordu. İlk yarı skoru yalnızca ESPN yanıtında iki devre skoru varsa alınıyordu.
Gerçek veri ortamında yurt içi kupalar için ilk yarı skorlu ölçüm yoktu. Gol Pazarlarının üç pazarı da (A: iki yarıda
KG, B: 3,5 Üst, C: İY 1,5 Üst) bu yüzden "doğrulanmadı" görünüyordu.

## Kaynak: openfootball ülke depoları (CC0)

openfootball, UEFA dosyalarının yanında ülke depolarında yurt içi kupaları da Football.TXT biçiminde ve ilk yarı
skorlarıyla tutuyor. Lisans dosyaları KUPA-01'deki CC0 1.0 metniyle aynı git nesnesi (`670154e3538863b2`):
deutschland `c34532ab6950`, england `9ee7a0c35180`, espana `80035a93dd49`, italy `48954d163c31`, europe
`63df627f3c87`, belgium `1166d3c9c572` (2026-10-15). Onay gerekmez. Satırlar, UEFA satırları gibi, yalnızca saklanan
kopyadan aynı okuyucuyla yeniden üretilebiliyorsa hak kazanır (köken doğrulaması).

| Turnuva | Depo / dosya | Sezonlar | Maç | Geçerli İY skoru | Oran |
|---|---|---|---:|---:|---:|
| Almanya Kupası (DFB-Pokal) | deutschland `{sezon}/cup.txt` | 2018/19–2025/26 | 488 | 473 | %96,9 |
| FA Cup | england `{sezon}/facup.txt` | 2018/19–2024/25 | 981 | 923 | %94,1 |
| Lig Kupası (EFL) | england `{sezon}/eflcup.txt` | 2018/19–2024/25 | 646 | 605 | %93,7 |
| Kral Kupası | espana `{sezon}/cup.txt` | 2020/21–2024/25 | 630 | 568 | %90,2 |
| İtalya Kupası | italy `{sezon}/cup.txt` | 2020/21–2024/25 | 255 | 234 | %91,8 |
| Türkiye Kupası | europe `turkey/{sezon}_trcup.txt` | 2024/25 | 147 | 117 | %79,6 |
| Fransa Kupası | europe `france/{sezon}_frcup.txt` | 2024/25 | 197 | 185 | %93,9 |
| Hollanda Kupası | europe `netherlands/{sezon}_nlcup.txt` | 2024/25 | 109 | 105 | %96,3 |
| Portekiz Kupası | europe `portugal/{sezon}_ptcup.txt` | 2024/25 | 110 | 104 | %94,5 |
| Belçika Kupası | belgium `{sezon}/becup.txt` | 2024/25 | 49 | 48 | %98,0 |
| **Toplam** | | | **3.612** | **3.362** | **%93,1** |

Türkiye Kupası'nın oranı %80 eşiğinin altında kalıyor: gol pazarlarında `LIG_IY_ORANI_DUSUK` koduyla bahis adayı
olmaz. İskoçya ve Yunanistan kupaları ile süper kupaların openfootball dosyası yok; bunlar ESPN'den gelmeye devam eder.

**ESPN.** Bu çalışmanın bulut ortamında ESPN'e erişim ağ politikasıyla engelliydi (HTTP 403). ESPN yanıtlarında yurt
içi kupalar için devre skoru olup olmadığı burada doğrulanamadı. Okuyucu değişmedi: devre skoru varsa ve toplamı maç
skoruyla tutarlıysa alınır. Sizin bilgisayarınızda ESPN içinde bulunulan sezonu ve bir önceki sezonu vermeye devam
eder.

## Okuyucu (`kupa-football-txt-v2`)

Yurt içi dosyalarda UEFA dosyalarından farklı üç biçim var; okuyucu bunları da okur:

- **Skor ortada** (deutschland, espana, italy): `1. FC Saarbrücken   2-1 (0-0)  Karlsruher SC`. Uzatma, penaltı ve
  hükmen notlu biçimleriyle.
- **Uzatmasız penaltı** (EFL Kupası, Fransa): `10-9 pen. (1-1, 0-1)`. Normal süre 1-1, ilk yarı 0-1. Tek parantezde
  (`3-1 pen. (0-0)`) parantez normal süredir; ilk yarı bilinmiyor kalır.
- **Ülke kodu yok:** takımın ülkesi turnuvadan gelir (`default_cc`, ör. FA Cup → ENG).

Diğer kurallar:

- Normal süre skoru yazılmamış uzatmalı/penaltılı maç atlanır (`2-4 a.e.t.`, `4-3 pen.`).
- Normal sürenin berabere bitmesi aranmaz. İki ayaklı eşleşmede uzatmaya toplam skor götürür: ilk maç 1-0, rövanş 1-0
  biterse rövanşta uzatma oynanır. Bu denetim ilk denemede eklenmişti. Kayıtlı 25 UEFA dosyasında eski okuyucuyla
  karşılaştırınca 91 geçerli maçı attığı görüldü ve kaldırıldı.
- FA Cup yarı finalleri Wembley'de oynandığı için tarafsız sahada sayılır (`of_neutral`); finaller her turnuvada
  tarafsızdır.
- **Geriye uyumluluk:** yeni okuyucu, kayıtlı 25 UEFA dosyasında eskisiyle birebir aynı satırları üretiyor (3.615 maç).
  Bu yüzden KUPA-01 köken kayıtları (`kupa-football-txt-v1`) güncellemeden önce de doğrulanmaya devam eder.

## Veri akışı

- Her turnuvanın openfootball deposu, dosya yolu ve ilk dosya sezonu `kupa.turnuvalar` içinde tanımlı
  (`of_repo`, `of_path`, `of_first`). İlk sezondan önceki dosyalar istenmez.
- **Bağlam etiketi** depo adını içerir (`openfootball/deutschland:2024-25/cup.txt`). Üç ülkenin dosya adı aynı
  olduğundan ("2024-25/cup.txt") etiketler başka türlü çakışırdı.
- **Köken kaydı:** depo, dosya yolu ve sezon klasörü saklanır. Doğrulama turnuvanın kendi deposunu ve yolunu bekler;
  başka depodan gelen kayıt kabul edilmez.
- **Kaynak seçimi:** bitmiş sezonda openfootball dosyası varsa o kullanılır. Yeni kural: dosya eksikse (oynanmış maç
  sayısı ESPN'dekinin %90'ından az) o sezon ESPN'den alınır ve güncelleme özetinde yazılır. Örnek: 2025/26 DFB-Pokal
  dosyası 48 maçla finalsiz; ESPN erişilebilirse o sezon ESPN'den gelir. Bu ortamda ESPN olmadığı için openfootball'un
  48 maçı kullanıldı.
- **Saat dilimi:** openfootball yurt içi dosyalarındaki saatler ülkenin yerel saatidir, UEFA dosyalarınınki Orta Avrupa
  saati.

## Takım kimliği

Ad, turnuvanın ülkesindeki depo takımları arasında aranır (KUPA-01 kuralı). Yurt içi dosyalarda depoda olmayan alt
lig ve amatör kulüpler çoktur. Ad normalleştirmesi kulüp türü eklerini attığı için farklı kulüpler aynı anahtara
düşebilir. Bu yüzden iki koruma eklendi (`kupa-kimlik-v2`); yalnızca yurt içi dosyalarında uygulanır:

1. **Ters çakışma:** aynı dosyada birden çok ad aynı depo takımına düşerse yalnızca doğrulanmış takma adla eşleşenler
   bağlanır. Örnek: Portekiz Kupası'nda "SL Benfica" takma adla Benfica'dır; amatör "CF Benfica" bağlanmaz.
2. **Kulüp türü eki çelişkisi:** normal adla eşleşmede iki adın da kulüp türü eki varsa ve ortak eki yoksa eşleşme
   reddedilir. Örnek: 2022'de kurulan "CD Extremadura", 2020'de dağılan "Extremadura UD" değildir.

Gerçek veride bu iki koruma yalnızca bu iki adı değiştirdi.

Bir "sezon kadrosu" koruması da denendi: takım kupa sezonunda veya komşu sezonlarda depo liglerinde oynamış olmalıydı.
Bu koruma 207 adı değiştirdi; aralarında 3. kademeye düşmüş Bolton, Portsmouth, Lincoln gibi aynı kulüpler vardı. Bu
yüzden kullanılmadı.

**Yeni doğrulanmış takma adlar (11).** Kupa sezonunda ülkenin depo kadrosunda tek kulübe karşılık gelenler:

- "AD Alcorcón", "CE Sabadell", "MSV Duisburg", "Chievo Verona"
- "L.R. Vicenza Virtus"/"L.R. Vicenza", "Reggina 1914", "SPAL 2013 Ferrara", "US Alessandria 1912"
- "Havre AC", "Estrela Amadora"

Aynı sezonda depoda olmayan kulüpler (Niort, Bordeaux, Eupen gibi) ve farklı kulüpler (Viktoria Köln, Stuttgarter
Kickers gibi) eklenmedi.

**Eşleşme oranı.** Dosya bağlamı başına sayıldığında 1.785 ad depo kulübüne bağlandı, 1.709 ad bağlanmadı. Bağlanmayanlar çoğunlukla
depodaki liglerde oynamayan alt lig ve amatör kulüpler (ör. FA Cup'ta National League, Kral Kupası'nda bölgesel lig
takımları). Bunlar ülke kapsamlı ayrı bir kimlikle modele girer ("ligi veride yok"). Tahminleri yapılır ama bahis adayı
olmazlar.

## Ölçüm kuralları: taban ve ilk yarı payı doğrulama grubundan

Yurt içi kupalar eklenince bir tasarım sorunu ortaya çıktı. 1X2 tabanı (KUPA-01), gol pazarı tabanları ve ilk yarı payı
(KUPA-GOL-02) bütün kupalardan birlikte hesaplanıyordu. Kupa verisinin tamamı UEFA'dan gelirken bu fark etmiyordu.
Gruplar ise farklı:

| Grup | Maç | Ev / Beraberlik / Deplasman | Gol/maç | İlk yarı payı | A / B / C oranı |
|---|---:|---|---:|---:|---|
| UEFA | 3.615 | %47,1 / %21,2 / %31,7 | 2,92 | 0,4436 | %6,3 / %35,5 / %39,9 |
| Yurt içi | 3.612 | %36,1 / %23,0 / %41,0 | 2,99 | 0,4418 | %5,6 / %38,1 / %39,7 |

Ortak taban yurt içi kupalarda grupların farkını modele üstünlük diye yazardı. Ayrıca doğrulanmış UEFA gol modelini
kendiliğinden değiştirirdi.

Bu yüzden taban ve ilk yarı payı artık **aynı doğrulama grubunun** önceki sezonlarından hesaplanıyor. Grupta önceki
maç 30'dan azsa taban için bütün kupalar kullanılıyor; ilk yarı payı lig önbilgisiyle yumuşatılıyor.

Yeni sürümler: `kupa-dogrulama-v2`, `kupa-gol-v2`, `kupa-gol-dogrulama-v2`; kayıtlı kupa modelinin dosya sürümü 4.
UEFA için sonuç bu işten önceki kuralla aynıdır: UEFA'nın 1X2 tabanı yine 1,047. Testler, yurt içi kupa eklenince
UEFA tabanlarının değişmediğini denetler.

## Gerçek veri sonuçları

7.227 kupa maçı (3.615 UEFA + 3.612 yurt içi) ve 55.604 lig maçıyla. Eğitim 44 saniye sürdü.

**1X2 (`kupa-dogrulama-v2`):**

| Grup | Maç | Log-kayıp | Taban | Fark üst sınırı | İsabet | Statü |
|---|---:|---:|---:|---:|---:|---|
| UEFA turnuvaları | 3.049 | 0,951 | 1,047 | −0,078 | %56,0 | doğrulandı |
| **Yurt içi kupalar** | **2.674** | **0,969** | **1,077** | **−0,090** | **%54,3** | **doğrulandı (yeni)** |

Turnuva bazında yurt içi (log-kayıp / taban):

| Turnuva | Maç | Log-kayıp / taban |
|---|---:|---|
| FA Cup | 769 | 0,992 / 1,086 |
| Lig Kupası | 551 | 0,989 / 1,083 |
| Kral Kupası | 449 | 0,949 / 1,052 |
| Almanya Kupası | 340 | 0,955 / 1,069 |
| İtalya Kupası | 230 | 0,988 / 1,117 |
| Fransa Kupası | 106 | 0,979 / 1,078 |
| Türkiye Kupası | 73 | 0,844 / 1,054 |
| Portekiz Kupası | 64 | 0,826 / 1,024 |
| Hollanda Kupası | 59 | 1,031 / 1,075 |
| Belçika Kupası | 33 | 0,794 / 1,085 |

**Bunun sonucu:** yurt içi kupa maçlarında 1X2 tahmini artık "doğrulandı". İki takım da depodaki liglerdeyse ve diğer
veri uygunluk kontrolleri geçilirse 1X2 bahis adayı olabilir. Sizin girdiğiniz gerçek oran yine gerekir. Amatör veya
alt lig takımlı maçlar "ligi veride yok" olarak bahis adayı olmaz.

**Gol pazarları (`kupa-gol-dogrulama-v2`):**

> **Düzeltme (KUPA-GOL-04).** Bu tablo ve aşağıdaki teşhis, 0-0 biten maçlar ölçümden düşmüş haliyle hesaplandı:
> openfootball 0-0 maçlarda devre skorunu neredeyse hiç yazmıyor. Maç sonu 0-0 ise İY 0-0 sayılınca model değişmeden
> yurt içi B ve C doğrulandı; "golü düşük tahmin" farkı 2,92'ye karşı 3,15'ten 2,92'ye karşı 2,96'ya indi. Geçerli İY
> skoru oranları da yükseldi (yurt içi %93,1'den %99,1'e; Türkiye Kupası %79,6'dan %84,4'e). Ayrıntılar:
> [`KUPA_GOL_04.md`](KUPA_GOL_04.md).

| Grup / pazar | Maç | Pozitif | LL model | LL taban | Δ üst | Eğim | ECE | Eşik | Statü |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| UEFA · A | 2.874 | 193 | 0,2441 | 0,2475 | −0,0004 | 0,96 | 0,015 | 0,020 | DOĞRULANMADI (pozitif 193 < 200) |
| UEFA · B | 2.874 | 1.026 | 0,6439 | 0,6522 | −0,0039 | 0,98 | 0,028 | 0,032 | **doğrulandı** |
| UEFA · C | 2.874 | 1.129 | 0,6682 | 0,6716 | +0,0011 | 0,78 | 0,025 | 0,032 | DOĞRULANMADI (log-kayıp, eğim) |
| Yurt içi · A | 2.510 | 144 | 0,2179 | 0,2204 | +0,0001 | 0,93 | 0,007 | 0,020 | DOĞRULANMADI (log-kayıp, pozitif 144 < 200) |
| Yurt içi · B | 2.510 | 940 | 0,6563 | 0,6622 | +0,0004 | 1,01 | 0,039 | 0,033 | DOĞRULANMADI (log-kayıp, ECE) |
| Yurt içi · C | 2.510 | 1.004 | 0,6727 | 0,6739 | +0,0022 | 0,91 | 0,040 | 0,034 | DOĞRULANMADI (log-kayıp, ECE) |

Yurt içi kupalarda ilk yarı skoru artık var ve ölçülüyor. Ancak üç pazar da önceden tanımlı kuralı geçemedi; bu
geçerli bir sonuçtur. Tahminler gösterilir, bahis adayı olmaz.

**Teşhis.** Model yurt içi kupalarda maç başına golü düşük tahmin ediyor: beklenen 2,92, gerçekleşen 3,15. B'nin
ortalama tahmini %33,5, gerçekleşen %37,5. Fark özellikle güç farkı büyük maçlarda belirgin: profesyonel–amatör
eşleşmelerinin uç beşte birlik dilimlerinde maç başına 0,35–0,42 gol eksik. UEFA'da da hafif bir eksik var (2,94'e
karşı 3,10).

Bunun nedeni modelin yapısı; ilk yarı verisiyle ilgisi yok. Düzeltmek ayrı bir model işidir, örneğin gruba özgü
kalibrasyon ya da büyük güç farkı terimi. Seçimin yeniden bir geliştirme/test dönemi protokolüyle yapılması gerekir.
Bu işte model değiştirilmedi.

## Testler

`tests/test_kupa_iy_03.py` 9 test içerir ve yalnızca sentetik veri kullanır: `kupa_yardim` dünyası ve deplasman ağırlıklı
sentetik FA Cup. Denetlenenler:

- **Okuyucu:** yurt içi biçimler (skor ortada, uzatmasız penaltı, tek parantez, hükmen, tanınmayan satır, iki ayaklı
  uzatma, ülke kodu, tarafsız tur) ve UEFA biçiminin değişmediği.
- **Katalog:** etiketlerin tekilliği, ülke kodları, saat dilimi.
- **Kimlik korumaları:** ters çakışma, tür eki ve yeni takma adlar.
- **Güncelleme:** ilk yarı skorlu yurt içi satırlar, kimlik, ülke deposundan istek, ilk sezon sınırı, güncelleme
  akışında ters çakışma, köken kaydı, kurcalama ve yanlış depo tespiti, KUPA-01 kayıtlarıyla uyumluluk.
- **Skor-ortada dosyalar ve FA Cup yarı finalinin tarafsızlığı.**
- **Tamlık kuralı:** dosya tamsa openfootball, eksikse ESPN ve güncelleme özetinde uyarı.
- **Ölçüm:** gruba özgü 1X2 ve gol pazarı tabanları, yurt içi kupa eklenince UEFA tabanlarının değişmemesi, gruba
  özgü ilk yarı payının tahminde kullanılması.

**Mutasyon denetimi:** kodu kasıtlı bozan 20 değişiklik denendi. İlk turda biri yakalanmadı: turnuvanın ilk dosya
sezonu sınırı, çünkü test 6 sezon geriye bakıyordu. Test güçlendirildi; son durumda 20 değişikliğin hepsi en az bir
testi kırıyor. KUPA-01 ve KUPA-GOL-02 testleri sürüm adlarını artık sabitlerden okuyor.

## Değişen dosyalar

- `bahis_tahmin/kupa/openfootball.py`: okuyucu v2.
- `bahis_tahmin/kupa/turnuvalar.py`: depo, yol, ilk sezon, tarafsız turlar, `default_cc`, `COUNTRY_CC`.
- `bahis_tahmin/kupa/veri.py`: `OfSpec`/`of_spec`/`parse_of`, ülke depolarından alım, tamlık kuralı, köken kaydı ve
  doğrulama.
- `bahis_tahmin/kupa/kimlik.py`: yurt içi korumaları.
- `bahis_tahmin/data/teams.py`: 11 takma ad.
- `bahis_tahmin/kupa/motor.py`: gruba özgü 1X2 tabanı, grup payı, saat dilimi, sürüm 4.
- `bahis_tahmin/kupa/gol.py`: gruba özgü pay ve taban, `kupa-gol-v2`.
- `bahis_tahmin/data/store.py`: güncelleme özetinde eksik dosya satırı.
- Belgeler: bu belge, `KUPA_01.md`, `KUPA_GOL_02.md`, README, Hakkında.

# VERI-02 — Bütün maçların "Uyarılı · bahis adayı değil (DEPODA_EKSIK_MAC)" görünmesi

## Belirti

VERI-01'den sonra tahminler gösteriliyordu, ancak Tahminler sayfasındaki bütün maçlar "Uyarılı · bahis adayı değil
(DEPODA_EKSIK_MAC)" etiketini taşıyordu.

## Neden

football-data.co.uk erişilemediğinde geçmiş veri GitHub yedek veri setinden gelir. Güncelleme özetinde bu durum "GitHub
yedek veri seti kullanıldı" diye yazar. Bu set güncel sezonda haftalarca geride kalabilir; 12 Ekim 2026'da son maç günü
3 Eylül'dü.

Fikstürleri sağlayan openfootball dosyası ise sonraki haftaların oynanmış maçlarını gösteriyordu. Uygunluk kontrolü bu
farkı doğru tespit etti: veride eksik maç vardı ve model bu sonuçları bilmiyordu.

## Düzeltme 1: eksik dönemin openfootball sonuçlarıyla tamamlanması

Kod: `data/completion.py`; çağrıldığı yer `DataStore.update`.

Uygulama her güncellemede, fikstür için zaten indirdiği openfootball sezon dosyasından (CC0) oynanmış maç sonuçlarını
alır. Bir maç şu koşulların hepsi sağlanırsa veriye eklenir:

- Ligin veride kalan son maç gününden sonra ve güncelleme gününden önce oynanmış.
- Veride ±3 gün içinde aynı eşleşme yok. Var olan satırlar değiştirilmez.
- İki takımın adı da kesin kimlikle eşleşiyor: aynı ad ya da maç düzeyinde kanıtlanmış takma ad (VERI-01).
  Eşleşmeyen adlı maç eklenmez.

Sonuçlar S4 pilotunun sonuç ayrıştırıcısıyla okunur. Belirsiz veya çelişkili kayıtlar karantinaya gider; skor tahmin
edilmez. Oran ve maç istatistikleri openfootball'da olmadığı için boş kalır.

**Köken.** Eklenen satırların etiketi `openfootball-tamamlama` olur. Hak kaydında bu etiket `openfootball-sonuc` (CC0)
kaynağına bağlıdır, ancak satırlar yalnızca kökenleri doğrulanırsa hak kazanır. Bunun için uygulama şunları yapar:

- Kullanılan dosyanın birebir kopyasını önbellekte saklar.
- Veri deposuna bir köken kaydı (`tamamlama_kokeni`) yazar: dosya özeti, ayrıştırıcı sürümü, eşleme sürümü, seçim
  tarihleri, ad eşlemesi ve satır özeti.
- Doğrulamada aynı dosyadan aynı kuralla aynı satırların yeniden üretilmesini şart koşar.

Skoru değiştirilen bir satır, etiketi değiştirilmiş bir yedek veri satırı ya da değişmiş bir dosya doğrulamadan geçmez
(`KAYNAK_KOKENI_DOGRULANAMADI`).

Tamamlama her güncellemede yeniden üretilir. Yedek veri yetişirse tamamlama satırları kendiliğinden kalkar.

## Düzeltme 2: son sonuçların yayın gecikmesi (yalnızca standart mod)

openfootball son hafta sonunun sonuçlarını genellikle birkaç gün içinde ekler. Bilgi kesiminden önceki son 4 gün içinde
oynanması beklenen ama sonucu henüz hiçbir yerde olmayan maçlar artık "belirsiz" sayılmaz. Bu maçlar yeni
`SON_SONUC_BEKLENIYOR` koduyla işaretlenir: bilgi düzeyindedir, tahmini ve bahsi engellemez, açıklamada yazar.

Daha eski bilinmeyen sonuçlar eskisi gibi bahis adayını engeller (`KAYNAK_DURUMU_BELIRSIZ`). Sıkı mod değişmedi.

## Düzeltme 3: anlaşılır etiketler

Etiket artık kodun yanında kısa bir Türkçe neden yazar (`eligibility.SHORT_TEXT`). Örnekler:

- "Uyarılı · bahis adayı değil: takımın bu ligde az maçı var (TAKIM_GECMISI_YETERSIZ)"
- "Uygun değil · model eğitilmedi (MODEL_YOK)"

## Sonuç (bu ortamda gerçek veri, 12 Ekim 2026)

Koşullar: football-data erişilemedi; GitHub yedek veri seti ve openfootball kullanıldı.

| | Önce | Sonra |
|---|---|---|
| Veriye eklenen maç | — | 257 (E0 30, E1 47, SP1 38, I1 30, D1 27, F1 26, N1 30, P1 29) |
| Veri sonu (bu 8 lig) | 30 Ağustos – 3 Eylül | 20 Eylül (openfootball'daki son sonuç) |
| Kullanılabilir | 0 / 88 | 59 / 88 |
| Uyarılı | 88 (DEPODA_EKSIK_MAC) | 29 (TAKIM_GECMISI_YETERSIZ) |

Kalan 29 "Uyarılı" maç, takımın bu ligde son 365 günde 10'dan az maçı olduğu maçlardır: lige yeni çıkan veya düşen
takımlar. Tahmin gösterilir, ama sezon başında bu takımların belirsizliği yüksek olduğu için bahis adayı olmaz. Takım bu
ligde 10 maça ulaşınca uyarı kendiliğinden kalkar.

## Bilinen sınırlar

- Tamamlama yalnızca openfootball dosyası olan liglerde yapılır. 2026-27 için football.json'daki ligler: E0, E1, D1,
  SP1, I1, F1, N1, P1. FIKSTUR-03'ten sonra openfootball metin depolarındaki T1, SC0, G1, D2 (ve dosya çıkarsa
  diğerleri) de kullanılır ([`FIKSTUR_03.md`](FIKSTUR_03.md)).
- openfootball'un kendisi de bir iki gün geride olabilir; bu durum notta yazılır.
- Tamamlanan maçlarda bahis oranı yoktur. Model bu maçları sonuç olarak kullanır, piyasa bilgisi olarak kullanmaz.

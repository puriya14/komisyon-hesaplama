# KUPA-GOL-05: Kupa gol modelinin seçimi, 0-0 düzeltmesiyle yeniden

İstek: "kupa gol modelinin ilk seçimini de yeniden çalıştır".

**Neden.** Kupa maçlarında gol pazarı modeli KUPA-GOL-02'de altı aday arasından seçilmişti. O ölçümde 0-0 biten maçlar
yoktu: openfootball bu maçlarda devre skorunu yazmıyor ve ölçüm onları "İY skoru yok" diye dışarıda bırakıyordu
([`KUPA_GOL_04.md`](KUPA_GOL_04.md)). Aynı maçlar ilk yarı ve ikinci yarı modellerinin eğitim verisinden de düşüyordu.
Seçim bu yüzden yeniden yapıldı.

## Sonuç

- Kural yine **SK0'ı seçti**. SK0 uygulamadaki `kupa-gol-v2` modelidir: kalibre maç sonu beklentisi, ilk yarı payıyla
  yarılara bölünüyor. Uygulamada değişiklik yok, yeniden eğitim gerekmiyor.
- Eşdeğer üçlü ilk seçimdekiyle aynı: SK0, SK1, MIX. Aralarındaki farklar her iki dönemde de istatistiksel gürültü
  düzeyinde.
- Test döneminde, seçimden sonra, bütün kupa maçları birlikte en iyi sonucu yine SK0 veriyor.
- Bir duyarlılık noktası var. Kural yalnızca UEFA maçlarına uygulansaydı (ilk seçimin o günkü örneklemi) SK0 eşdeğerlik
  sınırının 0,00023 dışında kalır, SK1 seçilirdi. UEFA'nın test döneminde ise SK1, SK0'dan kötü. Ayrıntı aşağıda.

## Ön kayıtlı seçim kuralı

Kural, betik ilk kez çalıştırılmadan ve hiçbir sonuç görülmeden yazıldı. Metni `tools/research/kupa_gol_secim.py`
başlığındadır. Çalıştırmadan önce alınan betik özeti (SHA-256, 2026-10-15 19:10 UTC): `5e26ea36…422f251b`.

- **Adaylar** (KUPA-GOL-02 ile aynı):

  | Kod | Kurgu |
  |---|---|
  | SK0 | Kalibre maç sonu beklentisi + ilk yarı payı s ile bölme (uygulamadaki model) |
  | SK1 | SK0 + ikinci yarı skor durumu çarpanları |
  | S2 | Kalibrasyonsuz maç sonu beklentisi + s ile bölme + durum çarpanları + pazar kalibrasyonu (Platt + IPF) |
  | K1 | Ayrı ilk yarı / ikinci yarı ligler arası takım güçleri + her yarıya ayrı kalibrasyon + durum çarpanları |
  | MIX | SK1 ile K1'in yarı yarıya karışımı |
  | H2 | Ayrı yarı güçleri (kalibrasyonsuz) + durum çarpanları + Platt + IPF |

- **Ana ölçüt:** geliştirme döneminde (2019/20–2021/22) bütün kupa maçlarında A, B ve C ortalama log-kayıplarının
  toplamı. KUPA-GOL-02 tablosundaki "Toplam" satırıyla aynı tanım.
- **Eşdeğerlik:** en iyiye 0,001'den yakın adaylar eşdeğer sayılır. Eşdeğerler içinde sadelik sırasındaki ilk aday
  seçilir. Sadelik sırası: SK0 < SK1 < S2 < K1 < MIX < H2.
- **Grup koruması (yeni):** KUPA-GOL-02'de tek grup (UEFA) vardı; şimdi yurt içi kupalar da var. SK0 dışındaki bir aday,
  UEFA'nın ve yurt içi kupaların geliştirme toplamlarının her birinde SK0'dan en fazla 0,001 kötüyse seçilebilir.
- ECE ve kalibrasyon eğimi raporlanır, seçimde kullanılmaz.
- Test dönemi (2022/23–2025/26) seçimden sonra raporlanır ve seçimi değiştirmez.

## Hat

Her adayın hattı uygulamadaki ölçümle aynıdır:

- **İlk yarı skoru:** `ht_scores` ile okunur (maç sonu 0-0 ise İY 0-0).
- **İlk yarı payı ve taban oranları:** sezon başından önceki, aynı doğrulama grubundaki kupa maçlarından (KUPA-IY-03).
- **SK kalibrasyonu:** sezon başından önceki bütün örneklem dışı maçlardan, motordaki gibi. Eski prototip yalnızca devre
  skorlu maçları kullanıyordu; 0-0'lar düştüğü için bu da gol yönünde eğilimliydi.
- **Durum çarpanları, Platt ve yarı kalibrasyonları:** sezon başından önceki, devre skoru geçerli örneklem dışı
  maçlardan.
- **Ligler arası modeller:** maç sonu, ilk yarı ve ikinci yarı modelleri her hafta yalnızca o haftadan önceki maçlarla
  kurulur. 0-0 kupa maçları artık ilk yarı ve ikinci yarı modellerinin eğitiminde.

**Denetimler:**

- SK0'ın olasılıkları ve taban oranları, uygulamanın ölçtüğüyle **birebir aynı**: 5.710 ortak maçta en büyük fark
  4·10⁻¹⁶. KUPA-GOL-02'de prototip ile uygulama arasında küçük farklar vardı; artık yok.
- Ölçülen 5.710 maç, uygulamanın ölçtüğü 5.723 maçın içinde. Kalan 13 maçta takımlardan birinin daha önce devre skoru
  yazılmış maçı yok, bu yüzden yarı modeli kurulamıyor. Hepsi amatör takımlı ilk tur maçları: Kral Kupası 2020/21'de 8,
  Türkiye Kupası 2024/25'te 5.
- Depodaki araç, geçici çalışma betiğiyle aynı sayıları veriyor (bütün tablolarda fark 0).

## Geliştirme dönemi (seçim)

Değerler A + B + C log-kaybı toplamıdır; düşük daha iyi.

| Aday | Bütün kupalar (1.865) | UEFA (813) | Yurt içi (1.052) |
|---|---:|---:|---:|
| **SK0** | **1,52866** | 1,60342 | 1,47089 |
| SK1 | 1,52860 | 1,60316 | 1,47098 |
| S2 | 1,53182 | 1,60399 | 1,47604 |
| K1 | 1,52996 | 1,60399 | 1,47275 |
| MIX | 1,52808 | 1,60218 | 1,47081 |
| H2 | 1,53096 | 1,60564 | 1,47324 |
| taban | 1,54545 | 1,61971 | 1,48806 |

Bütün kupalarda pazar bazında log-kayıp; parantez içinde ECE:

| Aday | A | B | C |
|---|---|---|---|
| **SK0** | 0,2416 (0,014) | 0,6319 (0,016) | 0,6552 (0,035) |
| SK1 | 0,2414 (0,010) | 0,6320 (0,021) | 0,6552 (0,035) |
| S2 | 0,2415 (0,013) | 0,6328 (0,026) | 0,6575 (0,030) |
| K1 | 0,2423 (0,012) | 0,6312 (0,028) | 0,6565 (0,031) |
| MIX | 0,2417 (0,012) | 0,6312 (0,019) | 0,6552 (0,033) |
| H2 | 0,2421 (0,015) | 0,6313 (0,020) | 0,6576 (0,035) |
| taban | 0,2452 | 0,6404 | 0,6599 |

**Kuralın uygulanışı:**

- En iyi aday MIX: 1,52808.
- 0,001 içindekiler, sadelik sırasıyla: SK0, SK1, MIX.
- Sadelikte ilk aday SK0, grup korumasına gerek kalmadı. **Seçilen: SK0.**

İlk seçimle karşılaştırma: KUPA-GOL-02'de (0-0'lar hariç, 767 UEFA maçı) sıralama MIX 1,6379, SK0 1,6381, SK1 1,6387,
K1 1,6405, S2 1,6436, H2 1,6494 idi. Aynı üçlü eşdeğerdi ve aynı aday seçilmişti. 0-0'ların eklenmesi log-kayıpların
düzeyini düşürdü (0-0 maçlarda üç pazar da kolay tahmin edilir), sıralamayı değiştirmedi.

## Test dönemi (seçimden sonra)

| Aday | Bütün kupalar (3.845) | UEFA (2.236) | Yurt içi (1.609) |
|---|---:|---:|---:|
| **SK0** | **1,50557** | **1,48824** | 1,52965 |
| SK1 | 1,50568 | 1,48864 | 1,52936 |
| S2 | 1,50635 | 1,48937 | 1,52995 |
| K1 | 1,50750 | 1,48933 | 1,53274 |
| MIX | 1,50600 | 1,48830 | 1,53060 |
| H2 | 1,50627 | 1,48863 | 1,53079 |
| taban | 1,52305 | 1,50638 | 1,54622 |

## Farklar gürültüden büyük mü?

Hafta bloklu bootstrap ile toplam log-kayıp farkı (aday − SK0) ve %95 aralığı, bütün kupalar:

| Aday | Geliştirme | Test |
|---|---|---|
| SK1 | −0,00006 [−0,00057; +0,00047] | +0,00011 [−0,00046; +0,00065] |
| MIX | −0,00058 [−0,00371; +0,00264] | +0,00043 [−0,00111; +0,00198] |
| K1 | +0,00130 [−0,00522; +0,00833] | +0,00193 [−0,00104; +0,00501] |
| S2 | +0,00316 [+0,00005; +0,00620] | +0,00078 [+0,00005; +0,00145] |
| H2 | +0,00230 [−0,00327; +0,00814] | +0,00070 [−0,00178; +0,00307] |

SK1, MIX, K1 ve H2'nin SK0'dan farkı iki dönemde de sıfırdan ayırt edilemiyor. S2, iki dönemde de SK0'dan anlamlı
biçimde kötü.

## Duyarlılık: kural tek bir gruba uygulansaydı

Kural seçimden önce "bütün kupa maçları" üzerinden tanımlandı; KUPA-GOL-02'deki tanım buydu ve o gün bütün kupa maçları
UEFA maçlarıydı. Seçimden sonra, bilgi amaçlı olarak, kural tek gruba da uygulandı:

- **Yalnızca UEFA:** en iyi MIX (1,60218). SK0 0,00123 geride, sınırın 0,00023 dışında. Eşdeğerler SK1 ve MIX olur,
  **SK1 seçilirdi**. UEFA geliştirme döneminde SK1 − SK0 farkı −0,00026 [−0,00100; +0,00057], MIX − SK0 farkı −0,00123
  [−0,00500; +0,00335]; ikisi de gürültü düzeyinde. UEFA'nın test döneminde SK0 hepsinden iyi: SK1 +0,00040, MIX
  +0,00006.
- **Yalnızca yurt içi:** en iyi MIX (1,47081), SK0 0,00008 geride. Eşdeğerler SK0, SK1, MIX; SK0 seçilirdi.

Bu duyarlılık seçimi değiştirmez. Kural önceden yazıldığı gibi uygulandı, test dönemi de SK0'ı destekliyor. UEFA'da
SK1'in geliştirme dönemindeki küçük üstünlüğü test döneminde tersine dönüyor.

## Tekrar çalıştırma

```
python -I tools/research/kupa_gol_secim.py <çıktı_klasörü>          # geliştirme dönemi ve seçim
python -I tools/research/kupa_gol_secim.py <çıktı_klasörü> --test   # test dönemi de (seçimden sonra)
```

- Veri uygulamanın veri klasöründen okunur (`BAHIS_TAHMIN_HOME`); ağ isteği yoktur.
- Haftalık hat yaklaşık 100 saniye sürer; sonucu `<çıktı_klasörü>/oos.pkl` olarak saklanır ve sonraki çalıştırmada
  yeniden kullanılır.
- Kayıtlı kupa modeli varsa SK0 = uygulama denetimi de yazdırılır.

## Testler

`tests/test_kupa_gol_05.py` 10 test içerir ve yalnızca sentetik veri kullanır:

- Maç sonu modeli, kupa motorunun ileriye dönük döngüsüyle birebir aynı.
- İlk yarı ve ikinci yarı modelleri, skorları yarı skorlarıyla değiştirilmiş veriden bağımsız kurulan modelle aynı.
- SK0'ın olasılıkları ve tabanları uygulamanın ölçümüyle aynı.
- Adaylar tutarlı (A ⊆ B ∩ C) ve birbirinden farklı. MIX tanımına uygun. SK1 ilk yarı pazarını değiştirmiyor. Her adayın
  ortalama tahmini gerçekleşen orana yakın.
- **Seçim kuralı:** sınır dahil eşdeğerlik, sadelik sırası, grup koruması ve hiçbir aday korumayı geçmezse SK0.
- **Sızıntı:**
  - Son sezonun sonuçları değişse de önceki sezonların bütün aday olasılıkları ve tabanları aynı kalır.
  - Ham beklentiler aynıyken bir sezonun sonuçları değişirse o sezonun ve öncekilerin tahminleri değişmez: bütün
    kalibrasyonlar sezon başından öncesinden.
- 0-0 maçlarda devre skoru yazılmasa da yarı modelleri ve bütün adaylar aynı.

**Mutasyon denetimi:** aracı kasıtlı bozan 18 değişiklik denendi.

- İlk turda ikisi yakalanmadı: ilk yarı modeline yanlış hedef vermek ve ikinci yarı golü yerine maç sonu golünü
  kullanmak. İki test eklendi: bağımsız yarı modeli ve ortalama kalibrasyon. Son durumda 18'inin hepsi en az bir testi
  kırıyor.
- Sentetik dünyada tek doğrulama grubu (UEFA) olduğu için grup ayrımı testle sınanamıyor. Bu ayrım gerçek veride, SK0'ın
  uygulamanın ölçümüyle birebir aynı çıkmasıyla denetlendi; tabanlar dahil, iki grupta da.

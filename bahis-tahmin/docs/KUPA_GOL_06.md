# KUPA-GOL-06: Yurt içi kupalarda son sezonlardaki düşük gol tahmini

İstek: "yurt içi kupalarda son sezonlardaki düşük gol tahminini düzelt".

## Kısa sonuç

- Model **değişmedi**. Mekanizmaya dayalı iki düzeltme, sonuç görülmeden yazılmış kurallarla sınandı; ikisi de
  kuralları geçemedi:
  - Sahte lig düzeyi (C1, C2): neredeyse hiç etki etmedi.
  - Dinamik gol düzeyi (D1): son sezonları biraz iyileştirdi ama eski sezonları bozdu ve iyileşme anlamlı değil.
- **Neden:** 2023/24 ve 2024/25'te yurt içi kupalarda gol düzeyi yükseldi. Aynı sezonlarda liglerde de gol arttı;
  Premier Lig 2023/24'te 3,28 gol/maç ile rekor kırdı. Model bu ani kaymayı ancak gecikmeyle izleyebiliyor. Önceki
  sezonlarda kayma ters yöndeydi; düzeyi hızlı izleyen bir kural orada gürültüyü kovalıyor.
- **Kazanç sınırlı:** her sezonun düzeyini sonuçları bilerek mükemmel düzeltmek bile son dönemde A+B+C log-kaybını
  yalnızca 0,0045 iyileştirirdi. Gerçekçi bir düzeltme bunun ancak bir kısmını alabilir.
- **Pratik risk:** son dönemde yurt içi kupalarda 3,5 Üst ortalama %33,5 tahmin edildi, gerçekleşen %36,7. Yani 3,5 Alt
  yaklaşık 3 puan fazla görünüyor. 3,5 Alt karar motorunda bahis adayı olabilen bir seçim; bu kayma sürerken orada
  sahte "değer" görülebilir.
- **Bugün:** yurt içi kupalarda son 180 günün dinamik düzeyi R = 1,03. Gerçekleşen gol tahminden yaklaşık %3 fazla.
  Yurt içi veri 2025-10-29'da bitiyor; 2025/26'dan yalnızca Almanya Kupası'nın ilk turları var (37 maç).
- Kaymayı yeni veri geldikçe izlemek için salt okunur bir araç eklendi: `tools/research/kupa_gol_duzey.py`.

## 1. Teşhis (mevcut model, ileriye dönük tahminler)

**Sezon bazında gerçekleşen ve tahmin edilen gol** (fark = gerçekleşen − tahmin; z aşırı yayılım düzeltmeli):

| Sezon | Yurt içi maç | Gol | Tahmin | Fark | z | UEFA fark |
|---|---:|---:|---:|---:|---:|---:|
| 2019/20 | 281 | 2,92 | 3,00 | −0,08 | −0,8 | +0,04 |
| 2020/21 | 379 | 2,75 | 2,91 | −0,16 | −1,8 | −0,05 |
| 2021/22 | 400 | 2,85 | 2,86 | −0,01 | −0,1 | −0,04 |
| 2022/23 | 419 | 2,85 | 2,85 | −0,00 | −0,0 | −0,09 |
| **2023/24** | 425 | 3,14 | 2,87 | **+0,27** | **+3,2** | +0,02 |
| **2024/25** | 733 | 3,11 | 2,98 | **+0,13** | **+2,0** | −0,01 |
| 2025/26 | 37 | 2,81 | 3,16 | −0,35 | −1,1 | +0,05 |

UEFA'da kayma yok. Yurt içinde iki sezon üst üste anlamlı bir açık var; daha önceki sezonlarda işaret tersti.

**Nerede birikiyor:**

- **Güç farkı büyük maçlar.** En büyük beşte birlikte +0,19, en küçükte −0,10.
- **Önceki maçı az takımlar.** En az bir takımın son üç yılda en fazla 2 maçı olan maçlarda +0,19.
- **Amatör–profesyonel maçlarında eksik tahmin edilen, profesyonel takımın golü.** Test döneminde +0,20; amatörün
  önceki maçı en fazla 2 ise +0,39; 2023/24'te +0,59. Amatörün golü doğru, hatta biraz fazla tahmin ediliyor.
- **Turnuva bazında (2022/23 sonrası):**

  | Turnuva | Fark | Maç |
  |---|---:|---:|
  | Türkiye Kupası | +0,45 | 73 |
  | Belçika Kupası | +0,29 | 33 |
  | Hollanda Kupası | +0,25 | 59 |
  | FA Cup | +0,16 | 387 |
  | Portekiz Kupası | +0,16 | 64 |
  | İtalya Kupası | +0,12 | 129 |
  | Almanya Kupası | +0,11 | 192 |
  | Kral Kupası | +0,08 | 292 |
  | Fransa Kupası | +0,03 | 106 |
  | Lig Kupası | +0,02 | 279 |

  İlk dördünden üçü 2024/25'te ilk kez eklenen turnuvalar.

**Liglerde de gol arttı (depodaki veri, maç başına):**

| Lig | 2022/23 | 2023/24 | 2024/25 |
|---|---:|---:|---:|
| Premier Lig | 2,85 | 3,28 | 2,93 |
| Championship | 2,43 | 2,68 | 2,45 |
| 2. Bundesliga | 2,94 | 3,09 | 3,02 |
| Eredivisie | 3,06 | 3,24 | 2,99 |
| Portekiz | 2,49 | 2,87 | 2,57 |
| La Liga | 2,51 | 2,64 | 2,62 |

2023/24'te İngiltere'de uzatma süreleri belirgin biçimde uzadı. Ligler arası model gol düzeyini bir yıl yarı ömürle
izlediği için böyle bir kaymaya gecikmeyle uyum sağlıyor.

**Üst sınır.** Son dönemde (2022/23–2025/26) her sezonun yurt içi λ, ν'si o sezonun gerçekleşen/tahmin oranıyla
ölçeklenseydi A+B+C log-kaybı 1,52955'ten 1,52508'e inerdi (−0,0045). Bu ölçekleme sonuçları kullanıyor, yani
ulaşılamaz bir kahin sınırıdır.

## 2. Birinci tur: sahte lig düzeyi

**Hipotez.** Ligi depoda olmayan takımlar ülke bazlı bir sahte lige (`X:ülke`) bağlanıyor. Bu ligin gücü 0'a, yani
depodaki liglerin ortalamasına çekiliyor. Verisi az amatör takım bu yüzden fazla güçlü başlıyor olabilir.

**Adaylar:**

- **C1:** sahte ligler, modelin birlikte öğrendiği tek ortak düzeye çekilir.
- **C2:** iki ayrı düzey. Ülkesinin ligi veride olan alt lig takımları bir düzeyde, ligi veride olmayan ülkeler ayrı
  düzeyde.

Cezalar ve diğer ayarlar aynı.

**Kural.** Hiçbir aday çalıştırılmadan yazıldı (2026-10-15 19:59 UTC, SHA-256 `f793aa83…8c6f`).

- **Ana ölçüt:** yurt içi son dönem A+B+C toplamı.
- **K1:** son dönemin iki yarısında da C0'dan kötü değil.
- **K2:** geliştirme dönemi en fazla +0,001.
- **K3:** UEFA en fazla +0,0015.
- **K4:** iki grubun 1X2'si en fazla +0,001.
- **K5:** son dönem farkının hafta bloklu %95 üst sınırı < 0.

Her aday için motor baştan eğitildi. C0, kayıtlı modelle birebir aynı çıktı.

| Aday | Yurt içi son dönem | 2022/23–23/24 | 2024/25–25/26 | Yurt içi gel. | UEFA | 1X2 UEFA | 1X2 yurt içi |
|---|---:|---:|---:|---:|---:|---:|---:|
| C0 | 1,52952 | 1,52829 | 1,53086 | 1,47017 | 1,51895 | 0,95112 | 0,96904 |
| C1 | 1,52951 | 1,52832 | 1,53081 | 1,47021 | 1,51882 | 0,95046 | 0,96909 |
| C2 | 1,52938 | 1,52856 | 1,53029 | 1,46971 | 1,51891 | 0,95213 | 0,96760 |

- **C1:** K1 ✗, K2 ✓, K3 ✓, K4 ✓, K5 ✗. Fark −0,00001 [−0,00008; +0,00007].
- **C2:** K1 ✗, K2 ✓, K3 ✓, K4 ✗, K5 ✗. Fark −0,00013 [−0,00069; +0,00031].
- **Sonuç:** C0 kaldı.

**Neden etki etmedi.** Öğrenilen düzeyler belirgin biçimde negatifti: C1'de hücum −0,42, savunma −0,39. Önbilgi yanlıştı.
Ama sahte liglerin gücü zaten veriden öğreniliyor. Amatör–profesyonel maçlarında profesyonel takımın ham beklentisi
2,194'ten yalnızca 2,199'a çıktı. Hipotez teşhiste görünse de açığın ana kaynağı değil.

**Ayrıca gözlendi.** C2 yurt içi 1X2'yi 0,0014 iyileştirdi ama UEFA 1X2'yi 0,0010 kötüleştirdi. Bu iş gol pazarı içindi;
1X2 için ayrıca incelenebilir.

## 3. İkinci tur: dinamik gol düzeyi

**Hipotez.** Ortak bir gol düzeyi kayması var. Aday **D1:** mevcut modelin kalibre beklentileri, grup bazlı bir R
çarpanıyla çarpılır:

    R = (Σ w·gerçekleşen + 150) / (Σ w·tahmin + 150)

- Toplam aynı gruptan, o haftadan **önceki** haftaların maçları üzerindendir.
- w = 0,5^(gün / 180).
- Ayarlar sonuç görülmeden sabitlendi.

**Kural.** Aynı beş koşul; çalıştırmadan önce yazıldı (2026-10-15 20:06 UTC, SHA-256 `73c0bf0a…eb0f`).

| Aday | Yurt içi son dönem | 2022/23–23/24 | 2024/25–25/26 | Yurt içi gel. | UEFA | 1X2 UEFA | 1X2 yurt içi |
|---|---:|---:|---:|---:|---:|---:|---:|
| C0 | 1,52952 | 1,52829 | 1,53086 | 1,47017 | 1,51895 | 0,95112 | 0,96904 |
| D1 | 1,52861 | 1,52854 | 1,52870 | 1,47307 | 1,51981 | 0,95134 | 0,96903 |

- K1 ✗: son dönemin ilk yarısında +0,00025.
- K2 ✗: geliştirme döneminde +0,0029.
- K3 ✓, K4 ✓.
- K5 ✗: fark −0,00090 [−0,00499; +0,00334].
- **Sonuç:** C0 kaldı.

D1, 2024/25'te kaymayı yakalıyor ama 2020/21 gibi ters yönlü sezonlarda gürültüyü kovalıyor. Toplamda iyileşme
anlamlı değil.

**Açıklama.** Son dönem önceki işlerde görüldü ve sorun orada bulundu. İki tur yapıldı; bu, çoklu deneme riskini
artırır. Kurallar bu yüzden tek mekanizma, sabit ayarlar, alt dönemlerde tutarlılık, başka yerde zarar yok ve anlamlılık
şartı koydu. Gerçek ileriye dönük sınav 2026/27 sezonudur.

## 4. İzleme aracı

```
python -I tools/research/kupa_gol_duzey.py
```

Kayıtlı kupa modelinden şunları yazar:

- grup × sezon gerçekleşen ve tahmin edilen gol, fark ve z,
- grup başına bugünkü dinamik düzey R.

Modeli değiştirmez, ağ isteği yapmaz. Bugünkü çıktı: yurt içi R = 1,032 (son maç 2025-10-29), UEFA R = 1,021.
Yeni sezonun yurt içi kupa sonuçları geldikçe ("Kaydet, Güncelle ve Eğit" sonrası) yeniden çalıştırılabilir.

## 5. Testler

`tests/test_kupa_gol_06.py` 4 test içerir (elle kurulmuş satırlar):

- Geçmiş yokken ve tahmin kusursuzken R = 1.
- R veri biriktikçe gerçekleşen/tahmin oranına yaklaşır ve formülle birebir aynıdır.
- R yalnızca önceki haftaları ve kendi grubunu kullanır (sızıntı yok).
- Sezon tablosu doğrudur.

Aracı kasıtlı bozan 6 değişikliğin hepsi en az bir testi kırıyor.

Reddedilen sahte lig düzeyi seçeneği koda alınmadı; uygulama değişmedi ve yeniden eğitim gerekmiyor.

# KUPA-GOL-07: Dinamik gol düzeyi (kullanıcı kararıyla uygulandı)

İstek: "Haftalık gol düzeyini yine de uygula".

**Karar.** KUPA-GOL-06'nın ikinci turundaki D1 adayı, ön kayıtlı kuralı geçmemişti ([`KUPA_GOL_06.md`](KUPA_GOL_06.md)).
Kullanıcı, bilinen bedelleriyle birlikte uygulanmasına karar verdi. Bu belge neyin uygulandığını, gerçek veride neyin
değiştiğini ve bedelini yazar.

## Ne uygulandı

Kupa motorunun kalibre gol beklentileri λ', ν', doğrulama grubu (UEFA, yurt içi, diğer kıtalar) başına bir R çarpanıyla
çarpılır:

    R = (Σ w·gerçekleşen gol + 150) / (Σ w·tahmin edilen gol + 150),   w = 0,5^(gün farkı / 180)

- **Eğitim ve ölçüm:** her örneklem dışı maçın R'si, aynı gruptan ve o haftadan **önceki** haftaların maçlarından
  hesaplanır. O haftanın sonuçları kullanılmaz. Tahmin edilen gol, düzeysiz kalibre beklentidir. 1X2 ve gol pazarı
  ölçümleri (doğrulama statüleri dahil) düzeyli beklentilerle yapılır. KUPA-GOL-06'da değerlendirilen D1 ile birebir
  aynıdır: gerçek veride gol pazarı olasılıklarında, R'de ve 1X2'de fark 0.
- **Tahmin:** aynı formül, maç tarihinin haftasından önceki örneklem dışı maçlarla hesaplanır. Yeni sonuç gelmedikçe
  ağırlıklar azalır ve R yavaşça 1'e döner. Belirsizlik aralığındaki her çekiliş de aynı R ile çarpılır.
- **Görünürlük:**
  - Gol Pazarları → Model doğrulama (masaüstü ve web) ve `kupa-rapor` grup başına bugünkü R'yi gösterir.
  - Maç analizindeki model kartı maçın R'sini gösterir ("gol düzeyi ×1,017").
  - Tahmin bilgisinde `gol_duzeyi` alanı var.
- **Sürümler:** kupa modeli `kupa-model-v3`, kayıtlı motor dosya sürümü 6. Eski kayıtlı motor yüklenmez; "Kaydet,
  Güncelle ve Eğit" ya da `kupa-egit` yeniden eğitir. `CupEngine(dynamic_level=False)` eski davranışı verir (araştırma
  ve testler için).

## Gerçek veride ne değişti

**Kalan fark** (gerçekleşen − tahmin, maç başına gol):

| Sezon | Yurt içi önce | Yurt içi şimdi | UEFA önce | UEFA şimdi |
|---|---:|---:|---:|---:|
| 2019/20 | −0,08 | −0,07 | +0,04 | +0,06 |
| 2020/21 | −0,16 | −0,09 | −0,05 | −0,10 |
| 2021/22 | −0,01 | +0,06 | −0,04 | −0,03 |
| 2022/23 | −0,00 | +0,01 | −0,09 | −0,05 |
| 2023/24 | **+0,27** | **+0,15** | +0,02 | +0,05 |
| 2024/25 | **+0,13** | **+0,00** | −0,01 | +0,03 |
| 2025/26 | −0,35 (37 maç) | −0,46 | +0,05 | +0,06 |

**3,5 Üst ortalama tahmini** (gerçekleşenle):

| Grup / dönem | Önce | Şimdi | Gerçekleşen |
|---|---:|---:|---:|
| Yurt içi 2022/23–2025/26 | %33,5 | %35,5 | %36,7 |
| Yurt içi 2019/20–2021/22 | %33,4 | %32,1 | %32,8 |
| UEFA 2022/23–2025/26 | %33,3 | %32,6 | %33,3 |
| UEFA 2019/20–2021/22 | %35,1 | %35,3 | %34,7 |

Yurt içi son dönemde 3,5 Alt'ın fazla görünmesi 3,2 puandan 1,2 puana indi.

**Doğrulama (`kupa-gol-dogrulama-v3`).** Statülerin hepsi aynı kaldı:

| Grup / pazar | Δ üst önce → şimdi | Eğim önce → şimdi | ECE önce → şimdi | Statü |
|---|---|---|---|---|
| UEFA · A | −0,0009 → −0,0010 | 0,99 → 1,00 | 0,014 → 0,011 | doğrulanmadı (pozitif 193 < 200) |
| UEFA · B | −0,0053 → −0,0048 | 1,03 → 0,96 | 0,021 → 0,015 | doğrulandı |
| UEFA · C | −0,0009 → **−0,0004** | 0,88 → **0,82** | 0,023 → 0,026 | doğrulandı |
| Yurt içi · A | +0,0002 → +0,0007 | 0,94 → 0,82 | 0,006 → 0,013 | doğrulanmadı |
| Yurt içi · B | −0,0037 → −0,0034 | 1,07 → 0,96 | 0,028 → **0,020** | doğrulandı |
| Yurt içi · C | −0,0013 → **−0,0006** | 1,04 → **0,86** | 0,023 → 0,020 | doğrulandı |

1X2 statüleri aynı: UEFA 0,9511 → 0,9513, yurt içi 0,9690 → 0,9690; ikisi de doğrulandı.

## Bedeli (açıkça)

- **Ön kayıtlı kuralı geçmedi** (KUPA-GOL-06):
  - Yurt içi geliştirme döneminde A+B+C toplamı +0,0029 kötü.
  - Son dönemin ilk yarısında (2022/23–2023/24) +0,00025 kötü.
  - Son dönemdeki toplam iyileşme (−0,0009) istatistiksel olarak anlamlı değil: [−0,0050; +0,0033].
- **UEFA'da küçük zarar:** gol pazarlarında A+B+C +0,0009, 1X2'de +0,0002.
- **İY 1,5 Üst (C) daha kırılgan:** iki grupta da log-kayıp üst sınırı sıfıra, kalibrasyon eğimi alt sınıra (0,80)
  yaklaştı. Bir sonraki eğitimde C'nin statüsü "doğrulanmadı"ya dönebilir.
- **Gecikme ve gürültü:** düzey geçmişten öğrenildiği için yeni bir kaymayı birkaç ay gecikmeyle yakalar. Ters yönlü bir
  sezonda (2020/21 gibi) gürültüyü kovalar. 2025/26'da yurt içi veri yalnızca 37 maç (Almanya Kupası ilk turları). Bu
  sezonda model zaten fazla gol tahmin ediyordu; düzey bunu büyüttü (−0,35 → −0,46).

## İzleme

`python -I tools/research/kupa_gol_duzey.py` şunları yazar:

- düzeysiz modelin ve uygulamadaki (düzeyli) modelin sezon bazında kalan farkı,
- grup başına R'yi ve tahminde kullanılan değeri.

Bugün (2026-10-15) tahminde kullanılan düzey: UEFA ×1,018, yurt içi ×1,016. Gerçek sınav, 2026/27 sezonunun sanal takip
kayıtlarıdır. Kayıtlarda `kupa-model-v3` sürümüyle ayrılırlar.

## Testler

`tests/test_kupa_gol_07.py` 9 test içerir; yalnızca sentetik veri kullanır:

- **Eğitim satırları:** R satır satır bağımsız yeniden hesapla aynı. Düzeysiz motorla aynı ham beklentiler. Düzey
  kapalıyken R = 1.
- **Ölçüm:** 1X2 ve gol pazarı ölçümü düzeyli beklentilerden; bağımsız yeniden hesapla aynı.
- **Tahmin:** maç tarihindeki R formülle aynı, kalibre beklentiye uygulanıyor. 1X2, gol pazarları ve model kartı aynı R'yi
  taşıyor.
- **Tutarlılık:** tahmin anındaki R, aynı haftadaki eğitim satırlarının R'siyle aynı.
- **Sızıntı:** bir haftadan sonraki sonuçlar değişse de o haftanın ve öncekilerin düzeyi ve beklentileri aynı.
- **Gruplar ayrı:** yurt içi maç yurt içi düzeyini, UEFA maçı UEFA düzeyini kullanıyor.
- **Kayıt / yükleme, sürümler ve bilgi satırı.**

`test_kupa_gol_02` aralık testi düzeyi her çekilişe uyguluyor. KUPA-GOL-05 aracının SK0 = uygulama denetimi artık
düzeysiz motorla yapılıyor.

**Mutasyon denetimi:** kodu kasıtlı bozan 12 değişiklik denendi. İlk turda üçü yakalanmadı:

- tahmin anında o haftanın maçlarını da saymak,
- grubu yanlış seçmek (sentetik dünyada yalnız UEFA var),
- ölçüm yokken bilgi satırı yazmak.

Üçü için test eklendi; son durumda 12'sinin hepsi en az bir testi kırıyor.

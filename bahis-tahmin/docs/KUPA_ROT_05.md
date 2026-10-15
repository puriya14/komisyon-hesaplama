# KUPA-ROT-05: Kupada rotasyon

İstek: "4, 5 ve 6'yı da sırayla yap" — 5. fikir: büyük kulüpler erken kupa turlarında yedek oynatıyor; model tam kadro
varsayıyor. Fikstür yoğunluğundan ya da turdan bir rotasyon göstergesi kurulabilir mi?

**Kısa sonuç:**

- Ön kayıtlı iki gösterge de kupa modelinin tahminlerinde ölçülebilir bir hata bırakmadı.
- Geliştirme döneminde ikisi de AIC'yi iyileştirmedi; kural gereği model **değişmedi**.
- Test dönemi de etkisiz.
- Sonradan yapılan bir betimleme, erken turlarda çok güçlü favorilerin tahminden az kazandığını düşündürüyor. Bu bir
  hipotezdir; aynı veriyle temiz sınanamaz, izlenecek.

## Ön kayıtlı sınama

Kural aracın başındaki açıklamadadır (`tools/research/kupa_rotasyon.py`). Kural ilk çalıştırmadan, sonuç görülmeden
yazıldı. Parmak izi: 2026-10-15 23:54:00 UTC, sha256 `26991f3d54a01438ec41a5e5817de1216fcbe0c29f76a0a293b015e161f76260`.

**Veri:**

- Kayıtlı kupa modelinin örneklem dışı tahminleri (her hafta yalnızca önceki maçlarla; kalibre ve dinamik gol düzeyli
  λ', ν'). 2019/20–2025/26 arası 5 723 kupa maçı.
- Maçın turu kupa kaydından; takım takvimleri depodaki lig ve kupa maçlarından.

**Tanımlar:**

- **Güçlü taraf:** gol beklentisi büyük olan.
- **Erken tur:** yurt içi kupa, çeyrek final / yarı final / final değil.
- **Takvimi bilinen takım:** maçtan ±60 gün içinde depoda lig maçı olan.
- **Yoğun fikstür:** takvimi bilinen takımın önceki ya da sonraki maçına en fazla 3 gün.

**Adaylar** (log gol beklentisine ek terim; katsayılar geliştirme döneminde Poisson en çok olabilirlikle):

- **R1 (erken tur favorisi):** erken turda güçlü tarafın gol beklentisi × e^a, zayıf tarafınki × e^b.
- **R2 (yoğun fikstür):** yoğun fikstürlü takımın gol beklentisi × e^a, rakibininki × e^b.

**Seçim:** geliştirme dönemi 2019/20–2021/22. ΔAIC = 2·2 − 2·Δℓ; en küçük ΔAIC < 0 olan aday seçilir, yoksa model
değişmez.

**Test:** 2022/23–2025/26. KABUL için iki koşul gerekir: skor log-kaybı farkının %95 üst sınırı < 0 ve 1X2'nin anlamlı
kötüleşmemesi.

## Sonuçlar

**Geliştirme dönemi** (1 873 maç):

- Erken tur oranı %42. Yoğun fikstürlü ev sahibi %36, yoğun fikstürlü deplasman %38.
- Takvimi bilinen ev sahibi %52, deplasman %59.

| Aday | e^a | e^b | Δℓ | ΔAIC |
|---|---:|---:|---:|---:|
| R1 (erken tur favorisi) | 1,004 | 0,989 | +0,07 | +3,85 |
| R2 (yoğun fikstür) | 1,002 | 0,980 | +0,38 | +3,23 |

Etkiler %1–2 düzeyinde, kestirim gürültüsünün içinde. Seçilen aday R0, yani model değişmedi.

**Test dönemi** (bilgi için; 3 850 maç):

| Aday | Skor log-kaybı farkı [%95] | 1X2 log-kaybı farkı [%95] |
|---|---|---|
| R1 | −0,00007 [−0,00035; +0,00021] | +0,00007 [−0,00015; +0,00031] |
| R2 | −0,00005 [−0,00054; +0,00052] | −0,00011 [−0,00037; +0,00017] |

Yurt içi grupta da farklar sıfırdan ayırt edilemiyor (R1: skor −0,00017 [−0,00086; +0,00054]).

## Sonradan betimleme (karara girmez)

Güç oranına göre, bütün sezonlar (geliştirme + test). Güç oranı = büyük gol beklentisi / küçük gol beklentisi.

| Yurt içi erken tur, güç oranı | Maç | Favorinin golü (tahmin → gerçek) | Rakibin golü (tahmin → gerçek) | Favori kazanır (tahmin → gerçek) |
|---|---:|---|---|---|
| 1–1,5 | 1 078 | 1,57 → 1,50 | 1,29 → 1,27 | %43,9 → %41,7 |
| 1,5–2,5 | 802 | 1,90 → 2,04 | 1,01 → 0,96 | %57,9 → %59,4 |
| 2,5–4 | 330 | 2,34 → 2,47 | 0,76 → 0,80 | **%72,4 → %65,8** |
| ≥ 4 | 201 | 2,90 → 2,89 | **0,55 → 0,66** | %84,3 → %79,6 |

**Gözlem:** UEFA'da aynı kovalarda böyle bir sapma yok (2,5–4: %71,9 → %74,9). Yurt içi erken turlarda çok güçlü
favoriler tahminden 5–7 puan az kazanıyor. Golleri azalmıyor ama rakipleri biraz daha çok gol atıyor. Bu, kısmi
rotasyonla uyumlu.

**Neden uygulanmadı:**

- Bu tablo **test dönemi de görüldükten sonra** ve birden çok kova ve grup incelenerek çıkarıldı.
- 2,5–4 kovasındaki fark yaklaşık 2,7 standart hata. Çoklu bakış düşünüldüğünde güçlü kanıt değil.
- Aynı veriyle yeni bir kural sınamak temiz olmaz.

**Öneri:**

- 2026/27 sezonunun yurt içi kupa maçları biriktikçe aynı tabloyu izlemek. Bunun için araç yeniden çalıştırılabilir.
- O sırada yeni, önceden yazılmış bir kuralla (ör. "erken tur ve güç oranı ≥ 2,5: favorinin kazanma olasılığı
  düşürülür") sınamak.
- Bu arada pratik bir uyarı: yurt içi erken turlarda çok güçlü favorinin 1X2 olasılığı biraz iyimser olabilir.

## Testler

`tests/test_kupa_rot_05.py` (6 test), elle kurulmuş verilerle:

- **Takvim hesabı:** önceki ve sonraki maç; aynı gün sayılmaz; takvimi bilinen takım; lig ve kupa takvimlerinin
  birleşmesi.
- **Erken tur tanımı.**
- **Tasarım matrisleri:** güçlü/zayıf taraf; iki takım birden yoğun.
- **Kestirim:** benzetimde bilinen etkinin geri kazanılması.
- **AIC ile seçim:** etkisiz veride model değişmez.
- **Karşılaştırma ve kabul kuralı.**

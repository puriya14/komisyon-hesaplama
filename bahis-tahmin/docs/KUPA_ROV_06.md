# KUPA-ROV-06: İki ayaklı eşleşmelerde rövanş

> **Sonradan:** kullanıcı 2. seçeneği seçti; V1 kupa motoruna kullanıcı kararıyla eklendi (KUPA-ROV-07). Ne
> uygulandığı, gerçek veride ne değiştiği ve bedeli: [`KUPA_ROV_07.md`](KUPA_ROV_07.md).

İstek: "4, 5 ve 6'yı da sırayla yap" — 6. fikir: ilk maçın skoru rövanşta takımların oyununu değiştirir (önde olan
savunur, geride olan saldırır); model bunu bilmiyor.

**Kısa sonuç:**

- Ön kayıtlı kuralda geliştirme dönemi yalnızca 181 rövanş içeriyordu. Hiçbir aday AIC'yi iyileştirmedi; kural gereği
  model **değişmedi**.
- Test dönemi (590 rövanş) ve bütün verideki sonradan kestirim ise ölçüsü küçük ama tutarlı bir "motivasyon" etkisi
  gösteriyor: ilk maçta önde olan takım rövanşta biraz daha az, geride olan biraz daha çok gol atıyor (gol farkı başına
  yaklaşık %2,7, p ≈ 0,03).
- Bu bir hipotezdir; 2026/27 rövanşlarıyla yeniden sınanmalı. İsterseniz kullanıcı kararıyla uygulanabilir (aşağıda).

## Ön kayıtlı sınama

Kural aracın başındaki açıklamadadır (`tools/research/kupa_rovans.py`). Kural ilk çalıştırmadan, sonuç görülmeden
yazıldı. Parmak izi: 2026-10-15 23:57:49 UTC, sha256 `dec465bf381989a0a640f547d5d0a74fb6197cbf74fe873cd682204cb5b071f2`.

**Eşleşme (iki ayaklı tur) tanımı:**

- **Ters eşleşme:** aynı turnuva ve sezon; rövanşın ev sahibi ilk maçın deplasmanı; rövanş ilk maçtan 3–70 gün sonra.
- **Hariç tutulanlar:**
  - grup ve lig aşaması,
  - FA Cup (oradaki ters eşleşmeler tekrar maçıdır, toplam skorlu tur değildir).
- **Tekillik:** her maç en fazla bir eşleşmede yer alır; ilk maç olarak en yakın önceki maç sayılır.
- **d:** rövanşın ev sahibinin ilk maçtaki gol farkı. Skorlar 90 dakikanın skorlarıdır; kupa kaydında uzatma golleri
  yoktur.

**Veri:**

- Kayıtlı kupa modelinin örneklem dışı tahminlerindeki 771 rövanş.
- Turnuvalara göre: UEFA ön eleme 427, UCL 104, UEL 117, UECL 88, yurt içi kupalar 35.

**Adaylar** (log gol beklentisine ek terim; Poisson en çok olabilirlik):

- **V1 (motivasyon):** rövanşın ev sahibinin gol beklentisi × e^(−β·d), deplasmanınki × e^(+β·d). d, [−3, 3]
  aralığına kırpılır.
- **V2 (kopmuş eşleşme):** |d| ≥ 3 ise iki takımın gol beklentisi de × e^γ.
- **V3:** V1 + V2.

**Dönemler:** geliştirme 2019/20–2022/23 (181 rövanş), test 2023/24–2025/26 (590 rövanş). Rövanş sayısı az olduğu için
geliştirme dönemi diğer kupa çalışmalarından bir sezon uzun tutuldu.

**Seçim:** geliştirme döneminde ΔAIC < 0 olan en küçük ΔAIC'li aday; yoksa model değişmez.

**Test:** KABUL için iki koşul gerekir: skor log-kaybı farkının %95 üst sınırı < 0 ve 1X2'nin anlamlı kötüleşmemesi.

## Sonuçlar

**Geliştirme dönemi** (181 rövanş):

| Aday | Katsayı | Δℓ | ΔAIC |
|---|---|---:|---:|
| V1 | β = 0,009 | +0,05 | +1,90 |
| V2 | γ = 0,030 | +0,03 | +1,94 |
| V3 | β = 0,010, γ = 0,037 | +0,09 | +3,82 |

Seçilen aday V0: model değişmedi. Karar: **RED**.

**Test dönemi** (bilgi için; katsayılar geliştirme döneminden; 590 rövanş):

| Aday | Skor log-kaybı farkı [%95] | 1X2 log-kaybı farkı [%95] |
|---|---|---|
| V1 | −0,00207 [−0,00523; +0,00079] | **−0,00259 [−0,00491; −0,00033]** |
| V2 | +0,00029 [−0,00076; +0,00126] | +0,00006 [−0,00026; +0,00035] |
| V3 | −0,00204 [−0,00622; +0,00139] | −0,00289 [−0,00546; −0,00045] |

**İlk maç farkına göre rövanş golleri** (bütün dönem, rövanşın ev sahibi açısından; tahmin → gerçek):

| d | Rövanş | Ev sahibi golü | Deplasman golü |
|---:|---:|---|---|
| −3 ve altı | 85 | 1,23 → 1,28 | 1,70 → 1,62 |
| −2 | 80 | 1,32 → 1,29 | 1,47 → 1,19 |
| −1 | 179 | 1,53 → 1,69 | 1,24 → 0,96 |
| 0 | 175 | 1,61 → 1,58 | 1,17 → 1,24 |
| +1 | 134 | 1,82 → 1,85 | 1,05 → 1,13 |
| +2 | 65 | 1,98 → 2,08 | 1,02 → 0,80 |
| +3 ve üstü | 53 | 2,28 → 2,15 | 0,89 → 1,09 |

En belirgin durum d = −1: ilk maçı 1 farkla kaybeden ev sahibi tahminden 0,16 gol fazla atıyor; önde olan deplasman
0,28 gol az atıyor. Diğer satırlar daha gürültülü ve tek yönlü değil.

**Sonradan kestirim** (V1'in β'sı; karara girmez):

| Dönem | Rövanş | β | Standart hata | Olabilirlik oranı p |
|---|---:|---:|---:|---:|
| Geliştirme | 181 | 0,009 | 0,029 | 0,75 |
| Test | 590 | 0,031 | 0,014 | 0,026 |
| Tümü | 771 | 0,027 | 0,013 | 0,033 |

## Değerlendirme

- **Ön kayıt sonucu:** model değişmedi. Geliştirme dönemi etkiyi görmeye yetmeyecek kadar küçüktü. Standart hata
  0,029 iken beklenen etki ~0,03.
- **Test dönemi:** V1 1X2'yi anlamlı iyileştiriyor; ancak kurala göre karar geliştirme döneminde verilir.
- **Sonradan kestirim:** etki küçük. 1 gol önde olan takımın gol beklentisi %2,7 düşer, rakibininki %2,7 artar; 2 gol
  farkta yaklaşık %5,5. Kanıt zayıf (p ≈ 0,03, tek bir kestirim).
- **Deplasman golü kuralı:** UEFA bu kuralı 2021/22'de kaldırdı; rövanşların çoğu (688/736 UEFA rövanşı) kural
  sonrası. Kural öncesi örnek (48) ayrı inceleme için çok az.

**Öneri ve seçenekler:**

1. **Bekle ve yeniden sına.** Kuralı, test dönemi verisiyle değil, 2026/27 rövanşlarıyla (~250 maç) önceden yazılmış
   haliyle yeniden çalıştırmak. Araç aynen kullanılabilir; yalnızca dönemler değişir.
2. **Kullanıcı kararıyla uygulamak** (KUPA-GOL-07'deki gibi). V1, β = 0,027 ile kupa motorunun rövanş tahminlerine
   eklenebilir. Bedeli: geliştirme döneminde sınanmamış bir katsayı ve küçük etki. İsterseniz söyleyin, uygularım.

## Testler

`tests/test_kupa_rov_06.py` (5 test), elle kurulmuş verilerle:

- **Eşleşme kuralları:** grup, FA Cup tekrar maçı, gün aralığı ve sezon dışarıda; rövanş ev sahibinin d'si.
- **En yakın ilk maç:** her maç tek eşleşmede.
- **Tasarım:** ±3 kırpma ve işaretler.
- **Kestirim:** benzetimde bilinen β ve γ'nın geri kazanılması.
- **Seçim ve kabul:** AIC ile seçim, etkisiz veride model değişmez, kabul kuralı.
- **Birleştirme:** örneklem dışı tabloyla birleştirme ve kalıntı tablosu.

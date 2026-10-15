# ORAN-04: Piyasa oranını gol düzeyine katmak

İstek: "4, 5 ve 6'yı da sırayla yap" — 4. fikir: maçın 2,5 Üst/Alt oranından beklenen gol düzeyini çıkarıp Gol Pazarları
modeline katmak. Oranlar gol düzeyi kaymalarını (ör. 2023/24) anında fiyatlar; model bunları aylar sonra yakalar.

**Kısa sonuç:**

- Ön kayıtlı sınamada kabul edildi.
- 2,5 Üst/Alt oranı olan maçlarda tahmin piyasanın gol düzeyine ölçeklenir. Bu, üç pazarın toplam log-kaybını test
  döneminde **−0,0050** iyileştirdi [%95: −0,0068; −0,0031]. 3,5 Üst ve İY 1,5 Üst belirgin iyileşti; iki yarıda KG
  değişmedi.
- Uygulamada oran kaynağı ya kullanıcının girdiği 2,5 Üst/Alt oranıdır ya da football-data fikstür dosyasındaki
  ortalama orandır.
- Kupa maçlarında aynı yöntem kullanılır ama geçmiş oran olmadığı için orada **sınanmadı**.

## Ön kayıtlı sınama

Kural aracın başındaki açıklamadadır (`tools/research/piyasa_duzey.py`). Kural ilk çalıştırmadan, sonuç görülmeden
yazıldı. Parmak izi: 2026-10-15 23:04:44 UTC, sha256 `5c44669a662cb236d5ca1c85ff021f78c0e4939f2731162cd8ac6a3c4f83b2c7`.
Araç sonra değiştirilmedi.

**Kurulum:**

- **Veri:** depodaki 16 lig.
- **Eğitim:** model (`M10_ipf_kosullu`) her sezon yalnızca önceki sezonlarla eğitildi.
- **Piyasa olasılığı p_m:** ortalama 2,5 Üst/Alt oranından, marjı orantılı olarak çıkarılmış olasılık.
- **Ölçüt:** maç başına A, B ve C log-kayıplarının toplamı. Aralıklar hafta bloklu bootstrap ile.

**Adaylar:**

- **P0:** mevcut model.
- **P1 (ölçek):** bütün takım gücü girdileri (ilk yarı, ikinci yarı ve maç sonu, iki takım için) tek bir s ile çarpılır.
  s, modelin 2,5 Üst olasılığı p_m'ye eşit olacak biçimde bulunur. Tahmin hattının tamamı (ayarlayıcı, ortak dağılım,
  IPF, A kalibrasyonu) ölçeklenmiş girdilerle yeniden çalışır.
- **P2 (öğrenilmiş kaydırma):** B ve C, logit ölçekte piyasa farkıyla kaydırılır; katsayılar eğitim sezonlarında
  öğrenilir.

**Seçim kuralı (geliştirme dönemi 2017/18–2020/21):**

- Bir aday, P0'a göre farkın %95 üst sınırı < 0 ise uygundur.
- Uygun adaylar arasından en düşük toplam kayıp seçilir.

**Test kuralı (2021/22 ve sonrası):** KABUL için iki koşul gerekir:

- toplam farkın %95 üst sınırı < 0,
- hiçbir pazarda farkın %95 alt sınırı > 0 olmaması (yani hiçbir pazarın anlamlı kötüleşmemesi).

**Sonuçlar** (P0'a göre log-kayıp farkı; negatif = daha iyi):

| Dönem · aday | Toplam | A (iki yarıda KG) | B (3,5 Üst) | C (İY 1,5 Üst) |
|---|---|---|---|---|
| Geliştirme · P1 (21 983 maç) | −0,00683 [−0,00903; −0,00479] | −0,00057 [−0,00117; −0,00001] | −0,00408 [−0,00532; −0,00286] | −0,00218 [−0,00302; −0,00134] |
| Geliştirme · P2 | −0,00672 [−0,00836; −0,00521] | −0,00062 [−0,00103; −0,00024] | −0,00404 [−0,00499; −0,00311] | −0,00206 [−0,00269; −0,00144] |
| **Test · P1 (27 619 maç)** | **−0,00496 [−0,00678; −0,00309]** | −0,00011 [−0,00066; +0,00043] | **−0,00305 [−0,00403; −0,00203]** | **−0,00180 [−0,00263; −0,00099]** |
| Test · P2 (bilgi) | −0,00478 [−0,00628; −0,00324] | −0,00024 [−0,00063; +0,00015] | −0,00294 [−0,00381; −0,00205] | −0,00160 [−0,00226; −0,00097] |

- **Seçim ve karar:** iki aday da uygun çıktı. P1 seçildi (geliştirme döneminde ortalama kaybı en düşük). Test kararı
  **KABUL**.
- **Sezon bazında:** test döneminin her sezonunda iyileşme var (−0,0027 ile −0,0102 arası).
- **Kalibrasyon (test):**

  | Pazar | Eğim P0 → P1 | ECE P0 → P1 |
  |---|---|---|
  | B (3,5 Üst) | 0,99 → 1,01 | 0,0068 → 0,0064 |
  | C (İY 1,5 Üst) | 1,01 → 1,02 | 0,0101 → 0,0084 |
  | A (iki yarıda KG) | 0,81 → 0,79 | 0,0045 → 0,0030 |

  A'nın eğimi ikisinde de düşüktür.
- **s'nin sezon ortalaması:** 1,00–1,035; en yüksek 2023/24. Piyasa son sezonlarda modelden fazla gol bekliyor.
  Yurt içi kupalarda gördüğümüz düzey kayması liglerde de var ve piyasa bunu biliyor.

## Uygulamada ne değişti

**Lig maçları (Gol Pazarları motoru)**

- **Oran kaynağı (öncelik sırasıyla):**
  1. Kullanıcının karar anından önce kaydettiği 2,5 Üst **ve** 2,5 Alt oranı. Aynı şirketten, en fazla 10 dakika
     arayla girilmiş olmalı.
  2. football-data fikstür dosyasındaki ortalama 2,5 Üst/Alt oranı (onaylı football-data kaynağıyla gelen
     fikstürlerde).
- **Yöntem:** P1'in aynısı (`bahis_tahmin/goals/piyasa.py`; araçla aynı sınırlar ve adım sayısı, testte
  karşılaştırılır). Belirsizlik aralığı da ölçeklenmiş girdilerle hesaplanır.
- **Doğrulama:** eğitim artık her doğrulama sezonunda aynı modellerin piyasa düzeyli tahminlerini de ölçer (oranı olan
  maçlar). Piyasa düzeyli bir tahminin doğrulama statüsü bu ölçümden gelir; modelin kendi statüsünden değil.
  - Gerçek veride son dört sezonun sonuçları:

    | Pazar | Model | Piyasa düzeyli |
    |---|---|---|
    | 3,5 Üst | 0,5977 · doğrulandı | 0,5939 · doğrulandı |
    | İY 1,5 Üst | 0,6391 · doğrulandı | 0,6370 · doğrulandı |
    | İki yarıda KG | 0,2160 · doğrulanmadı | 0,2154 · doğrulanmadı |

  - **Eski kayıtlı motor:** bu ölçüm olmadan kaydedilmiş bir motorda piyasa düzeyli tahminler "doğrulanmadı"
    sayılır. Modeli yeniden eğitmek gerekir: "Gol modelini eğit" ya da `gol-egit`.
  - **Eğitim süresi:** gerçek veride yaklaşık 2,5 dakika.
- **Sürüm ve kayıt:**
  - Piyasa düzeyli tahminin model sürümü `goal-joint-1.0/M10_ipf_kosullu+piyasa-duzey-v1`.
  - Sanal takip kayıtları `piyasa_duzeyi` alanını taşır: kullanılan oranlar, olasılık, ölçek ve kaynak.
- **İleriye dönük ölçüm protokolü** (`gol-olcum-kaydet`) bilerek **değişmedi**. Temel modelin tahminlerini ölçer;
  fikstür oranları oraya girmez.

**Kupa maçları**

- Girilen 2,5 Üst/Alt oranıyla kalibre gol beklentileri λ', ν' aynı k ile çarpılır. k, toplam golün Poisson
  dağılımında P(≥ 3) = p_m olacak biçimde bulunur.
- Kupa maçlarında geçmiş oran olmadığı için bu uyarlama **sınanmadı**. Model kartı bunu açıkça yazar. Doğrulama
  statüsü grubun piyasasız ölçümünden gelir.

**Arayüz**

- **Maç analizi (masaüstü ve web):** "Gerçek oranlar" kutusunda **2,5 Üst (gol düzeyi)** ve **2,5 Alt (gol düzeyi)**
  alanları var. İkisi birlikte kaydedilince kartlar, karar tablosu ve model kartı piyasa düzeyli tahmine geçer. 2,5
  için karar üretilmez.
- **Model kartı:** hangi oranın ve hangi ölçeğin kullanıldığını yazar, ör. "piyasa gol düzeyi ×1,042 (2,5 Üst %58,2;
  oranlar 1,70 / 2,20; girilen oran, Şirket)".
- **Tarama tablosu:** "Piyasa gol düzeyi" sütunu.
- **Durum satırı ve Model doğrulama sekmesi:** piyasa düzeyli tahminlerin statüsü ve ölçümü ayrı satırlarda.
- **CLI:**
  - `gol-tahmin`: satır sonunda "[piyasa gol düzeyi ×…]".
  - `gol-egit`: piyasa düzeyli doğrulama satırları.

## Sınırlar

- **Değer bulma değişti.** Piyasa düzeyli tahmin, gol düzeyini zaten piyasadan alır. Modelin 3,5 Üst olasılığı ile
  3,5 Üst oranı arasındaki fark artık yalnızca dağılımın biçiminden gelir (2,5 ile 3,5 çizgisi arasındaki ilişki).
  Bu, özellikle düzeyin yanlış tahmin edildiği maçlarda yanlış "değer" sinyalini azaltır. Kazanç garantisi değildir.
- **Ortalama oran ile tek şirket oranı farklıdır.** Sınamada ortalama oranlar kullanıldı. Kullanıcının girdiği tek
  şirket oranının marjı ve doğruluğu farklı olabilir.
- **İki yarıda KG:** iyileşme anlamlı değil, kalibrasyon eğimi düşük kaldı.

## Testler

`tests/test_oran_04.py` (14 test) ve `test_ui.py`, `test_web.py` içindeki akış testleri. Sınananlar:

- **Kaynaklar:**
  - iki taraf, aynı şirket ve 10 dakika kuralı,
  - karar anından sonraki oranın kullanılmaması.
- **Ölçek:**
  - s'nin kök bulucuyla bağımsız yeniden hesaplanması,
  - sınırda kırpma.
- **Motor:**
  - 2,5 Üst'ün piyasaya eşitlenmesi ve olasılıkların ölçeklenmiş girdilerle bağımsız yeniden hesaplanması,
  - yön (yüksek gol düzeyi → yüksek B, C),
  - piyasa düzeyli tahminin kendi doğrulama statüsü; eski motorda "doğrulanmadı",
  - fikstür oranının yalnızca kendi satırına uygulanması.
- **Servis ve kayıt:**
  - kayıtlı oranla yeniden tahmin; veri kodu değişirse tahminin değişmemesi,
  - kayıtlarda sürüm ve `piyasa_duzeyi`.
- **Eğitim ve doğrulama hattı:**
  - eğitimde ayrı ölçüm; iki statünün kendi ölçümünden hesaplanması,
  - doğrulama hattındaki piyasa sütunlarının bağımsız yeniden hesapla aynı olması,
  - araç ile uygulamanın aynı yöntemi kullanması.
- **İleriye dönük protokol:** fikstür oranlarının ölçüm protokolüne girmemesi.
- **Kupa:** Poisson ölçeği, model kartı uyarısı.
- **Arayüz:** masaüstü ve web'de 2,5 oranı girişi, tarama sütunu, kayıt ve doğrulama sekmesi.

**Mutasyon denetimi:** kodu kasıtlı bozan 19 değişiklik denendi. İlk turda ikisi yakalanmadı:

- kupa belirsizlik aralığının piyasa ölçeğini almaması,
- piyasa düzeyli statünün modelin statüsünden kopyalanması (sentetik veride iki statü de aynıydı).

İkisi için test eklendi. Statü hesabı küçük bir yönteme ayrıldı (`apply_validation_rule`). Son durumda 19'unun hepsi en
az bir testi kırıyor.

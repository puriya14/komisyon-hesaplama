# KUPA-ROV-07: Rövanş etkisi (kullanıcı kararıyla uygulandı)

İstek: "7'yi de yap ve rövanş etkisini uygula".

**Karar.** KUPA-ROV-06'daki V1 ("motivasyon") adayı ön kayıtlı kuralı geçmemişti. Geliştirme dönemi yalnızca 181
rövanş içeriyordu ([`KUPA_ROV_06.md`](KUPA_ROV_06.md)). Kullanıcı, bilinen bedeliyle birlikte etkinin uygulanmasına karar
verdi (KUPA-ROV-06'daki 2. seçenek). Bu belge neyin uygulandığını, gerçek veride neyin değiştiğini ve bedelini yazar.

## Ne uygulandı

Maç iki ayaklı bir eşleşmenin rövanşıysa kupa motorunun gol beklentileri ilk maçın skoruna göre çarpılır:

    ev sahibi × e^(−β·x),   deplasman × e^(+β·x),   x = d'nin [−3, 3] aralığına kırpılmış hali

- **d:** rövanşın ev sahibinin ilk maçtaki gol farkı (attığı − yediği; ilk maçta deplasmandaydı).
- **β > 0:** ilk maçta önde olan takım rövanşta daha az, geride olan daha çok gol atar.
- **Eşleşme tanımı** KUPA-ROV-06 ile aynı (testte araştırma aracıyla karşılaştırılır):
  - aynı turnuva ve sezon, ters takımlar, iki maç arasında 3–70 gün;
  - grup ve lig aşaması dışarıda, FA Cup tekrar maçları dışarıda;
  - skorlar normal süre (90 dk) skorlarıdır.
- **β'nın kestirimi:** Poisson en çok olabilirlik. Girdiler kalibre ve dinamik gol düzeyli (KUPA-GOL-07) örneklem dışı
  beklentiler; kod `bahis_tahmin/kupa/rovans.py`.
  - **Eğitim ve ölçüm:** her rövanşın β'sı yalnızca o haftadan **önceki** haftaların rövanşlarından kestirilir. Önceki
    rövanş sayısı 200'den azsa β = 0. O haftanın sonuçları kullanılmaz. 1X2 ve gol pazarı ölçümleri (doğrulama
    statüleri dahil) çarpanlı beklentilerle yapılır.
  - **Tahmin:** bütün örneklem dışı rövanşlardan. Gerçek veride β **0,027**, standart hata 0,013, 771 rövanş.
    İlk maçta 1 gol önde olan takımın rövanştaki gol beklentisi ×0,973, rakibininki ×1,027. 3 ve daha fazla gol
    farkında ×0,922 / ×1,085.
- **Tahminde ilk maçın bulunması:**
  - İlk maç, kayıtlı kupa sonuçlarında aynı eşleşme kuralıyla aranır. Yalnızca maç gününden önceki sonuçlar kullanılır.
  - Fikstürden gelen maçta tur ve sezon fikstürden alınır.
  - Elle seçilen maçta sezon tarihten bulunur. Tur bilinmediği için ilk maçın grup ya da lig aşaması maçı olmaması
    istenir.
  - Gerçek veride 2025/26'nın 237 rövanşının tamamında aynı ilk maç bulundu: hem tur/sezonla hem onlarsız.
- **Etkilenenler:** 1X2, üç gol pazarı, belirsizlik aralığının her çekilişi ve piyasa düzeyli yeniden tahmin (ORAN-04).
- **Görünürlük:**
  - Maç analizindeki notlar: "Bu maç bir eşleşmenin rövanşı — ilk maç 2026-02-10 2-0 …; gol beklentisi ev ×…,
    deplasman ×…".
  - Gol modeli kartının sürüm satırı da aynı bilgiyi taşır.
  - Gol Pazarları → Model doğrulama (masaüstü ve web) ve `kupa-rapor`: kullanılan β ve standart hatası.
  - Tahmin bilgisinde `rovans` alanı (d, ilk maç tarihi ve skoru, β, iki çarpan).
- **Sürümler:** kupa modeli `kupa-model-v4`, kayıtlı motor dosya sürümü 7. Eski kayıtlı motor yüklenmez; "Kaydet,
  Güncelle ve Eğit" ya da `kupa-egit` yeniden eğitir. `CupEngine(rovans=False)` eski davranışı verir (araştırma ve
  testler için).

## Gerçek veride ne değişti

Örneklem dışı 5723 kupa maçının 771'i rövanş: 736'sı UEFA (çoğu eleme turları), 35'i yurt içi.

- Ölçümdeki ilk 201 rövanşta β = 0 (önceki rövanş sayısı 200'den az). β ilk kez 2024-03-05 haftasında devreye girdi.
- Ölçümde kullanılan β ortalama 0,020, en yüksek 0,045.

**Log-kayıp (eski motor `kupa-model-v3` → yeni):**

| Maçlar | Sayı | 1X2 önce | 1X2 şimdi | Gol (Poisson) önce | Gol şimdi |
|---|---:|---:|---:|---:|---:|
| Rövanşlar | 771 | 0,99613 | **0,99329** | 3,01307 | 3,01267 |
| Diğerleri | 4952 | 0,95392 | 0,95392 | 3,02217 | 3,02217 |
| Hepsi | 5723 | 0,95961 | 0,95922 | 3,02094 | 3,02089 |

Rövanşlardaki farkın hafta bloklu bootstrap %95 aralığı (53 hafta):

- 1X2: −0,00284 [−0,00866; +0,00291]
- gol: −0,00040 [−0,00820; +0,00755]

**İkisi de sıfırı içeriyor:** iyileşme istatistiksel olarak anlamlı değil.

İlk maç farkına göre (1X2 / gol log-kaybı farkı):

| \|x\| | Rövanş | 1X2 | Gol |
|---:|---:|---:|---:|
| 0 | 175 | 0 | 0 |
| 1 | 313 | −0,0051 | −0,0048 |
| 2 | 145 | −0,0004 | +0,0070 |
| 3 | 138 | −0,0040 | +0,0013 |

**Doğrulama statüleri:** hepsi aynı kaldı.

- 1X2: UEFA 0,9513 → 0,9506, yurt içi 0,9690 → 0,9690; ikisi de doğrulandı.
- Gol pazarları (`kupa-gol-dogrulama-v3`):

| Grup / pazar | Log-kayıp önce → şimdi | Δ üst önce → şimdi | Eğim önce → şimdi | ECE önce → şimdi | Statü |
|---|---|---|---|---|---|
| UEFA · İki yarıda KG | 0,2334 → 0,2334 | −0,0010 → −0,0009 | 1,00 → 0,99 | 0,011 → 0,011 | doğrulanmadı (pozitif 193 < 200) |
| UEFA · 3,5 Üst | 0,6302 → **0,6306** | −0,0048 → −0,0043 | 0,96 → 0,94 | 0,015 → 0,016 | doğrulandı |
| UEFA · İY 1,5 Üst | 0,6562 → 0,6563 | −0,0004 → −0,0004 | 0,82 → 0,81 | 0,026 → 0,026 | doğrulandı |
| Yurt içi · İki yarıda KG | 0,2083 → 0,2083 | +0,0007 → +0,0007 | 0,82 → 0,82 | 0,013 → 0,013 | doğrulanmadı |
| Yurt içi · 3,5 Üst | 0,6399 → 0,6399 | −0,0034 → −0,0033 | 0,96 → 0,96 | 0,020 → 0,022 | doğrulandı |
| Yurt içi · İY 1,5 Üst | 0,6584 → 0,6584 | −0,0006 → −0,0006 | 0,86 → 0,86 | 0,020 → 0,020 | doğrulandı |

## Bedeli (açıkça)

- **Ön kayıtlı kuralı geçmedi** (KUPA-ROV-06): β geliştirme döneminde sınanmadı.
- **Anlamlı değil:** ileriye dönük ölçümdeki iyileşmenin %95 aralıkları sıfırı içeriyor.
- **UEFA 3,5 Üst'te küçük zarar:** log-kayıp +0,0004; kalibrasyon eğimi 0,96'dan 0,94'e indi.
  - Etki ev ve deplasmanı ters yönde değiştirdiği için toplam gol üzerindeki etkisi küçüktür.
  - Fark büyüdükçe (|x| = 2) gol log-kaybı kötüleşiyor.
- **Ölçüm büyük ölçüde UEFA eleme turlarından.** Yurt içi kupalarda iki ayaklı tur azdır (35 rövanş); oradaki etki ayrıca
  sınanmadı.
- **Bilinmeyenler:** uzatma ya da penaltıya kalan rövanşlarda yalnızca 90 dakikanın skoru kullanılır.
  - İlk maç verisi yoksa (kaynakta eksikse) çarpan uygulanmaz ve maç sıradan maç gibi tahmin edilir.
  - Turnuva kuralı değişiklikleri (ör. 2021'de deplasman golü kuralının kalkması) ayrıca modellenmedi.

## İzleme

KUPA-ROV-06'daki 1. seçenek hâlâ geçerli: 2026/27 rövanşları birikince (~250 maç) önceden yazılmış kural araç
(`tools/research/kupa_rovans.py`) ile yeniden çalıştırılabilir. Etki tutmazsa geri almak için kupa motorunu
`rovans=False` ile kurmak yeterli; motor dosya sürümü artırılır.

## Testler

`tests/test_kupa_rov_07.py` (8 test). Sentetik dünyadaki rastlantısal eşleşmelerle; eşik testte 20'ye indirilir:

- **Eşleşme tanımı:** paket ile araştırma aracının `ties` sonuçları aynı (tur adları ve FA Cup karışık veride de).
- **β kestirimi:** bilinen β = 0,1 geri bulunur. Araştırma aracının V1 kestirimiyle aynı. Standart hata, sayısal ikinci
  türevle aynı.
- **Çarpanlar:** kırpma; d NaN ise 1.
- **Sızıntı yok:** β yalnızca önceki haftalardan, eşiğin altında 0. Bir haftadan sonraki sonuçlar değişince o haftanın
  ve öncekilerin β'sı değişmez.
- **İlk maç kuralları:** aynı yön, gün aralığı, grup aşaması, tur bilinmeyen maç, FA Cup, başka sezon. Tahmin
  gününden sonraki maçlar kullanılmaz.
- **Motor ölçümü:** λ = rövanşsız λ × çarpan (rövanş olmayanlarda birebir aynı). 1X2 çarpanlı beklentilerden. Tahmin
  β'sı bütün rövanşlardan. `rovans=False` motorunda çarpan yok.
- **Tahmin:** ilk maç (3-0) bulunur; λ ve ν doğru yönde çarpılır. Tur/sezon verilmeden de bulunur, ters yöndeki maçta
  bulunmaz. 1X2, gol pazarları, aralık (büyük β ile nokta tahmin aralığın içinde) ve piyasa düzeyli tahmin aynı çarpanı
  taşır.
- **Kart, notlar, sürüm, kaydet/yükle, özet (digest).**

Mutasyon denetimi: 27 değişiklikten 25'i yakalandı. Kalan ikisi eşdeğer: eşleşme kuralı sezonu ve grup aşamasını zaten
ayrıca eliyor; ilk maç aramasındaki ön süzgeç yalnızca hız için.

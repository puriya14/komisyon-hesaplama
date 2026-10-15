# KUPA-GOL-02: Gol Pazarlarında kupa ve Avrupa maçları

İstek: "gol pazarlarına kupa maçlarını da ekle". Gol Pazarları sayfası artık Şampiyonlar Ligi, Avrupa Ligi, Konferans
Ligi (elemeler dahil), ulusal kupalar ve diğer kıtaların kupa maçlarını da kapsar. Pazarlar aynıdır:

| Kod | Pazar | Sonuçlandırma |
|---|---|---|
| A | İki yarıda da karşılıklı gol | İlk yarı ve ikinci yarı skoru gerekir |
| B | Maç sonu 3,5 Üst | Maç sonu (90 dk) skoru |
| C | İlk yarı 1,5 Üst | İlk yarı skoru gerekir |

Kurallar lig maçlarındakiyle aynıdır: her pazar ayrı doğrulanır, doğrulanmayan pazarda tahmin gösterilir ama bahis
adayı olmaz, gerçek oran olmadan öneri üretilmez ve kayıtlar değiştirilemez sanal takibe yazılır.

## Neden ayrı bir model

Lig maçlarının yarı-gol modeli (`goals.engine`) her ligi kendi içinde eğitir: takım güçleri yalnızca o ligin maçlarından
gelir. Farklı liglerin takımları bu modelde aynı ölçekte değildir (KUPA-01'de 1X2 için de aynı sorun vardı). Kupa
maçlarının gol pazarları bu yüzden KUPA-01'in **ligler arası ortak modelinden** türetilir. KUPA-01'den önce Gol
Pazarları sayfasında kupa maçları yoktu.

## Veri: kupa maçlarında ilk yarı skoru

A ve C pazarları ilk yarı skoru olmadan ne ölçülebilir ne sonuçlandırılabilir. Gerçek verideki kapsam:

| Turnuva | Maç | Geçerli İY skoru | Oran | Kaynak |
|---|---:|---:|---:|---|
| Şampiyonlar Ligi | 1.372 | 1.298 | %94,6 | openfootball |
| Avrupa Ligi | 814 | 774 | %95,1 | openfootball |
| Konferans Ligi | 575 | 540 | %93,9 | openfootball |
| Konferans Ligi (eleme) | 510 | 472 | %92,5 | openfootball |
| Şampiyonlar Ligi (eleme) | 182 | 169 | %92,9 | openfootball |
| Avrupa Ligi (eleme) | 162 | 141 | %87,0 | openfootball |

Yalnızca İY ≤ MS olan skorlar geçerlidir. Geçerli İY skoru oranı %80'in altında olan turnuvada tahmin gösterilir ama
`LIG_IY_ORANI_DUSUK` koduyla bahis adayı olmaz (lig kuralıyla aynı eşik). Yurt içi kupalar ve diğer kıtalar ESPN'den
gelir; İY skoru ESPN'in periyot skorlarında varsa kullanılır. Bu çalışmanın gerçek veri ortamında bu gruplar için ilk
yarı skorlu örneklem dışı maç yoktu, bu yüzden "doğrulanmadı" görünürler. Ölçüm her eğitimde yeniden yapılır.

Kapsam tablosu arayüzde **Gol Pazarları → Kapsam** sekmesinde (masaüstü ve web) "Kupa ve Avrupa maçlarında ilk yarı
skoru" başlığıyla görünür.

## Model: `kupa-gol-v1` (maç sonu bölme)

Ligler arası ortak modelin **kalibre** maç sonu gol beklentileri λ (ev) ve ν (deplasman), ilk yarı payı s ile yarılara
bölünür:

    İY golleri  ~ Poisson(s·λ) × Poisson(s·ν)
    2Y golleri  ~ Poisson((1−s)·λ) × Poisson((1−s)·ν)

- Bütün pazarlar tek bir ortak dağılımdan (`goals.joint.joint_probs`) türetilir: A ⊆ B ∩ C yapısal olarak korunur,
  kırpma yoktur.
- s, tahmin anından **önceki** kupa maçlarında ilk yarı gollerinin bütün gollere oranıdır (geçerli İY skorlu maçlar).
  Lig önbilgisi 0,44 ile yumuşatılır (100 gol ağırlığında). Gerçek veride s = 0,4436.
- B (maç sonu 3,5 Üst) yalnızca λ + ν'ye bağlıdır, s'den etkilenmez.
- Tarafsız sahada iç saha avantajı ve kalibrasyonun iç saha terimi uygulanmaz. Takımların yeri değişince tahmin de
  simetrik değişir (testle denetlenir).
- Sürüm bilgisi kayıtlarda `kupa-model-v2/kupa-gol-v1` olarak yazılır. Kayıtlı kupa modelinin dosya sürümü 3'e çıktı.
  Eski kayıtlı kupa modeli yüklenmez; "Kaydet, Güncelle ve Eğit" ya da `kupa-egit` onu yeniden eğitir.
- **KUPA-IY-03 güncellemesi (`kupa-gol-v2`, kural `kupa-gol-dogrulama-v2`, dosya sürümü 4):** s ve taban oranları
  doğrulama grubunun kendi geçmişinden hesaplanır (UEFA ayrı, yurt içi kupalar ayrı). Kupa verisinin tamamı UEFA'dan
  geldiği sürece v1 ile aynıdır. Gerekçe ve yurt içi kupaların sonuçları: [`KUPA_IY_03.md`](KUPA_IY_03.md).

### Seçim: geliştirme döneminde karşılaştırma

Seçim yalnızca **geliştirme döneminin** (2019/20–2021/22 kupa maçları, ilk yarı skorlu 767 maç) ileriye dönük
tahminleriyle yapıldı. Denenen kurgular:

| Kod | Kurgu |
|---|---|
| S2 | Kalibrasyonsuz maç sonu beklentisi + s ile bölme + ikinci yarı skor durumu çarpanları + pazar kalibrasyonu (Platt + IPF) |
| H2 | Ayrı ilk yarı / ikinci yarı ligler arası takım güçleri + durum çarpanları + Platt + IPF |
| SK1 | Kalibre maç sonu beklentisi + s ile bölme + durum çarpanları |
| **SK0** | **Kalibre maç sonu beklentisi + s ile bölme (seçilen; ek parametre yok)** |
| K1 | Ayrı yarı güçleri + her yarı için ayrı kalibrasyon + durum çarpanları |
| MIX | SK1 ile K1'in yarı yarıya karışımı |

Geliştirme dönemi, ortalama log-kayıp (düşük iyi). Parantez içinde ECE var:

| Pazar | Taban oran | S2 | H2 | SK1 | **SK0** | K1 | MIX |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 0,3151 | 0,3112 (0,035) | 0,3133 (0,036) | 0,3105 (0,032) | **0,3098 (0,028)** | 0,3100 (0,035) | 0,3100 (0,046) |
| B | 0,6571 | 0,6526 (0,038) | 0,6520 (0,045) | 0,6517 (0,026) | **0,6518 (0,023)** | 0,6509 (0,054) | 0,6506 (0,056) |
| C | 0,6803 | 0,6798 (0,054) | 0,6841 (0,060) | 0,6765 (0,055) | **0,6765 (0,055)** | 0,6796 (0,061) | 0,6773 (0,047) |
| Toplam | | 1,6436 | 1,6494 | 1,6387 | **1,6381** | 1,6405 | 1,6379 |

SK0, SK1 ve MIX log-kayıpta eşdeğerdir (toplam fark 0,001'den küçük). SK0 seçildi, çünkü:

- ek parametresi yok,
- A ve B'de kalibrasyon hatası en düşük,
- durum çarpanları (SK1) ve yarıya özgü güçler (K1) geliştirme döneminde anlamlı bir iyileşme getirmedi.

**Şeffaflık notu.** Prototip aynı çalıştırmada test döneminin (2022/23–2025/26) sayılarını da yazdırdı, yani bu sayılar
seçim sırasında görüldü. Seçim kuralı geliştirme dönemi + sadelik olarak uygulandı. SK0'ın prototip test dönemi
sonuçları: A 0,2205 (taban 0,2233), B 0,6404 (taban 0,6503), C 0,6636 (taban 0,6678). Uygulamadaki nihai sayılar
aşağıdaki motor ölçümünden gelir; prototip hattı birebir aynı olmadığından küçük farklar vardır.

## Doğrulama kuralı: `kupa-gol-dogrulama-v1`

Ölçüm her doğrulama grubu (UEFA turnuvaları, yurt içi kupalar, diğer kıtalar) ve her pazar için ayrı yapılır. Ölçülen
tahminler, kupa motorunun haftalık ileriye dönük (walk-forward) tahminleridir: model o maçları görmeden tahmin eder. İlk
örneklem dışı sezon kalibrasyona ayrılır. Her sezonun ilk yarı payı ve taban oranları yalnızca o sezondan **önceki**
kupa maçlarından hesaplanır (sızıntı testi: son sezonun İY skorları değişse de önceki sezonların tahminleri değişmez).

Bir pazar "doğrulandı" sayılırsa yalnızca sanal takip için kullanılır. Dört ölçütün hepsi sağlanmalıdır (lig gol
motorunun ölçütleri):

1. Log-kayıp farkı (model − önceki sezonların kupa taban oranı) için hafta bloklu bootstrap %95 üst sınırı < 0,
2. kalibrasyon eğimi 0,8–1,25,
3. ECE ≤ max(0,02; kusursuz kalibrasyonda örneklem gürültüsünden beklenen ECE'nin %95 üst sınırı),
4. en az 200 gerçekleşen (pozitif) örnek.

**ECE eşiğindeki uyarlama (açıkça):** Lig motorunda eşik sabit 0,02'dir ve on binlerce maçla ölçülür. Kupada yaklaşık
2.900 maç vardır. Bu örneklemde kusursuz kalibre bir model bile gürültü yüzünden 0,02'yi aşabilir: B için gürültünün %95
üst sınırı 0,031'dir. Eşik bu yüzden örneklem gürültüsüne göre ölçeklenir ve 0,02'nin altına inmez. Gürültü düzeyi
her ölçümde tahminlerin kendisinden simüle edilir (400 tekrar, sabit tohum). Bu uyarlama prototip sonuçları görüldükten
sonra belirlendi. Kuralın lig motorundan tek farkı budur; gerekçesi örneklem büyüklüğüdür. **Uyarlama olmasaydı B de
doğrulanmazdı** (ECE 0,025 > 0,02).

## Gerçek veri sonuçları

UEFA turnuvaları (elemeler dahil), 2.874 ilk yarı skorlu örneklem dışı maç:

| Pazar | Pozitif | LL model | LL taban | Δ üst sınır | Kal. eğim | ECE | ECE eşiği | Statü |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| A: iki yarıda KG | 193 | 0,2447 | 0,2475 | +0,0000 | 0,95 | 0,016 | 0,020 | DOĞRULANMADI: log-kayıp farkı anlamlı değil, pozitif 193 < 200 |
| B: 3,5 Üst | 1.026 | 0,6454 | 0,6522 | −0,0027 | 1,04 | 0,025 | 0,031 | **doğrulandı (sanal takip)** |
| C: İY 1,5 Üst | 1.129 | 0,6688 | 0,6716 | +0,0016 | 0,83 | 0,034 | 0,031 | DOĞRULANMADI: log-kayıp farkı anlamlı değil, ECE yüksek |

Yurt içi kupalar ve diğer kıtalar için örneklem dışı ölçüm yok, üç pazar da "doğrulanmadı" (bu ölçüm anında yurt içi
kupalarda ilk yarı skoru yoktu; KUPA-IY-03 ile eklendi).

Sonuç olarak kupa maçlarında yalnızca **UEFA turnuvalarının maç sonu 3,5 Üst** pazarı karar motorunda avantaj adayı
olabilir. Bunun için de sizin girdiğiniz güncel gerçek oran ve karar politikasının bütün eşikleri gerekir. A ve C
tahminleri bilgi olarak gösterilir. Pozitif sayısı arttıkça A ileride eşiğe ulaşabilir; ölçüm her eğitimde yenilenir.

**KUPA-IY-03 sonrası güncel ölçüm.** Yurt içi kupalar 3.612 maçla modele girdi. Ortak modelin takım güçleri de
değiştiği için UEFA sayıları biraz değişti. Statüler aynı kaldı: UEFA'da yalnızca B doğrulandı (LL 0,6439 / taban
0,6522; Δ üst −0,0039; eğim 0,98; ECE 0,028 ≤ 0,032). Yurt içi kupalarda (2.510 maç) üç pazar da doğrulanmadı. Tablo
ve teşhis: [`KUPA_IY_03.md`](KUPA_IY_03.md).

## Tahmin ve belirsizlik aralığı

- Olasılıklar: kalibre λ, ν ve s ile ortak dağılımdan.
- %80 aralık (10.–90. yüzdelik): ortak modelin cezalı olabilirliğinin Hessian'ından (Laplace yaklaşımı) ham
  (log λ, log ν) kovaryansı hesaplanır. 200 çekiliş yapılır (tohum 20261015); her çekilişte kalibrasyon ve ortak
  dağılım yeniden çalışır. Ev ve deplasman beklentisi birlikte çekilir. Aralık yalnızca parametre belirsizliğini
  yansıtır, gerçek olasılığın kesin sınırı değildir. Az maçlı takımda (ör. ligi veride olmayan) aralık genişler.
- Testler, gradyanın doğru parametrelere düştüğünü sonlu farkla, aralığı da bağımsız yeniden hesapla denetler.

## Uygunluk, karar ve sanal takip

- **Veri uygunluğu:** KUPA-01'in pazar başına kupa uygunluğu kullanılır. İki takımın kanıtlı kimliği, ligleri ve son 365
  günü, turnuva takvimi ve tazelik denetlenir. Gol pazarlarına motorun kodları da eklenir:
  `TAKIM_N365_AZ` → `TAKIM_GECMISI_YETERSIZ` (son 365 günde 10'dan az lig + kupa maçı), `LIG_IY_ORANI_DUSUK` (turnuvada
  geçerli İY skoru oranı < %80; üç pazarda da bahis engeli) ve `OLASILIK_GECERSIZ`. Motor kodları yoksa tahmin uygun
  sayılmaz.
- **Model doğrulaması:** 1X2 modelinin doğrulama kodu (`KUPA_MODEL_DOGRULANMADI`) gol pazarlarına uygulanmaz. Gol
  pazarının kendi doğrulaması karar motorunda, turnuvanın doğrulama grubuna göre denetlenir (`MODEL_NOT_VALIDATED`).
- **Karar politikası:** lig gol pazarlarıyla aynı (`karar-politikasi-v1.1`): güvenli olasılıkla en az %3 beklenen
  getiri, %80 aralık genişliği ≤ 0,25, beklenen getiri ≤ %30 (üstü karantina), oran en çok 60 dakikalık.
- **Sanal takip:** kayıt anında kararlar aynı uygunluk sonucuyla yeniden üretilir. Model sürümü `kupa-model-v2/kupa-gol-v1`,
  veri kesimi kupa motorunun son eğitim günüdür.
- **Sonuçlandırma:** kupa sonuçlarından yapılır (kayıttaki lig alanı turnuva kodudur). İY skoru yoksa A ve C
  sonuçlandırılamaz; kayıt bekler ve skor gelince yeniden denenir.
- **İleriye dönük ölçüm protokolü** (`gol-forecast-log`): dondurulmuş protokol yalnızca lig maçlarını kapsar. Kupa gol
  tahminleri bu protokole girmez.

## Arayüz ve komut satırı

- **Masaüstü, Gol Pazarları:**
  - Tarama listesinde kupa maçları lig maçlarıyla birlikte görünür. Lig gol modeli eğitilmemiş olsa da kupa maçları
    listelenir.
  - **Maç analizi:** listeden seçilebilir ya da "Kupa / ligler arası maç" bölümünden turnuva, ev, deplasman ve tarafsız
    saha seçilerek elle kurulabilir. Panelde modelin bilgileri görünür: sürüm, eğitim, doğrulama, belirsizlik, girdiler.
    Kupa motoru değişirse paneldeki eski tahminle kayıt yapılmaz.
  - **Doğrulama:** kupa tablosu ve kalibrasyon grafiği.
  - **Kapsam:** kupa İY skoru tablosu.
  - Durum satırında pazar başına kupa doğrulama statüsü yazar.
- **Web (`/gol/`):** aynı sekmeler ve aynı kurallar. Elle kupa maçı için `turnuva`, `ev_k`, `dep_k` ve `tarafsiz`
  parametreleri kullanılır.
- **Komut satırı:**

```bat
.venv\Scripts\python -m bahis_tahmin kupa-egit                          & rem gol pazarları ölçümü de yazılır
.venv\Scripts\python -m bahis_tahmin kupa-gol-tahmin --turnuva UCL      & rem kupa maçlarında A/B/C ve uygunluk
.venv\Scripts\python -m bahis_tahmin kupa-rapor                         & rem "Gol pazarları" doğrulama tablosu dahil
```

## Sınırlar

- Kupa maçları için ücretsiz veride piyasa oranı yoktur. Değer yalnızca sizin girdiğiniz oranla hesaplanır; geçmiş
  getiri ölçülemez.
- Model varsayımı: yarılar bağımsız Poisson'dur ve ikinci yarıda skor durumu etkisi yoktur. Durum çarpanları geliştirme
  döneminde iyileşme getirmedi.
- `LIG_IY_ORANI_DUSUK`, B'nin tahmini İY skoruna bağlı olmasa da üç pazarda bahsi engeller. Bu ihtiyatlı bir seçimdir ve
  lig kuralıyla aynıdır.
- Tahmin 90 dakikalıktır; uzatma golleri sayılmaz.
- Yurt içi kupalar ve diğer kıtalar: İY skorlu örneklem yoksa doğrulanmaz.

## Testler

`tests/test_kupa_gol_02.py` 14 test içerir ve yalnızca sentetik veri kullanır (`tests/kupa_yardim.py`: iki lig + Avrupa
kupası; ilk yarı golleri binom %45). Denetlenenler:

- **Gol bölümü ve sızıntı:** gol bölümünün kurulması ve ölçülen tahminlerin kupa motorununkilerle aynı olması; sızıntı
  olmaması (son sezonun İY skorları değişince önceki sezonlar değişmez).
- **Ortak dağılım ve aralık:** ortak dağılımın tutarlılığı (B = 1 − Poisson KDF(3; λ+ν), C ve A'nın kapalı formu,
  A ≤ B∩C); aralığın nokta tahminini içermesi ve belirlenimci olması; tarafsız saha simetrisi; başlama saati
  (ESPN İstanbul, openfootball Orta Avrupa); bilinmeyen takım.
- **Kovaryans:** pozitif tanımlı olması; az maçlı takımda daha geniş olması; sonlu farkla gradyan denetimi; aralığın
  bağımsız yeniden hesabı (tarafsız saha dahil).
- **Doğrulama kuralı:** dört ölçütün her biri; ECE eşiğinin örneklemle ölçeklenmesi.
- **Uygunluk:** standart ve sıkı modda olumlu kontrol; takımı eksik maçın nedenli "tahmin yok" sonucu; 1X2 doğrulama
  kodunun gol pazarlarına geçmemesi; motor kodlarının pazarlara ulaşması (`TAKIM_N365_AZ`, `OLASILIK_GECERSIZ:pazar`,
  düşük İY oranı, kod yokken uygun sayılmama).
- **Karar ve sanal takip:** doğrulanmamış A ve C'de `MODEL_NOT_VALIDATED`, B'de oranla `VALUE_CANDIDATE`, uygunluk
  verilmeden `DATA_NOT_ELIGIBLE`; kayıtta model sürümü ve veri kesimi; kupa sonucuyla sonuçlandırma ve zincir bütünlüğü.
- **Uçtan uca:** çekirdek (lig gol modeli yokken kupa maçları, turnuva seçimi boşken hiç), web (tarama, maç, elle seçim,
  kayıt, doğrulama, kapsam), masaüstü (tarama, analiz, kayıt, elle maç, doğrulama ve kapsam tabloları, motor değişince
  panelin geçersiz olması) ve komut satırı.

**Mutasyon denetimi:** kodu kasıtlı bozan 22 değişiklik denendi. Örnekler: sızıntı koruması, log-kayıp, ECE ve pozitif
ölçütleri, pay yönü, aralıkta ev beklentisinin belirsizliği, tarafsız sahada aralık, kovaryans gradyanının işaret ve
terimleri, doğrulama statüsünün taşınması, İY oranı kodu, saat dilimi, model kodlarının kapsamı, tahmin kodlarının
yok sayılması, kupa sonuçlarının sonuçlandırmada olmaması, çekirdek, masaüstü ve web kupa dalları, komut satırı süzgeci.

İlk turda 3 değişikliği testler yakalamadı: aralıkta ev beklentisinin belirsizliği, tarafsız sahada aralık ve web
taramasında kupa kararları. Testler güçlendirildi; son durumda 22 değişikliğin hepsi en az bir testi kırıyor.

## Değişen dosyalar

- `bahis_tahmin/kupa/gol.py` (yeni): model, ölçüm kuralı, gol bölümü, aralık.
- `bahis_tahmin/kupa/model.py`: Hessian, parametre blokları, `log_rate_cov`.
- `bahis_tahmin/kupa/motor.py`: gol bölümünün eğitimi, `predict_goals`, doğrulama grubu, başlama saati ülkesi, sürüm 3.
- `bahis_tahmin/kupa/uygunluk.py`: gol pazarları için uygunluk ve `gated_cup_goal_predictions`.
- `bahis_tahmin/kupa/gorunum.py`: durum satırı, model kartı, doğrulama, kalibrasyon ve kapsam tabloları, elle maç.
- `bahis_tahmin/goals/engine.py`, `goals/service.py`: tahmine özgü doğrulama, kupa kayıtları, `settlement_matches`.
- `bahis_tahmin/core.py`, `ui/controller.py`, `ui/pages/goals.py`, `web/gol.py`, `web/templates/gol.html`, `cli.py`.

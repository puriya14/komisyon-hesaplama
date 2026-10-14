# KUPA-01 — Kupa ve Avrupa maçları

İstek: "Bizim bu tahmin uygulamamızda Şampiyonlar Ligi, Konferans Ligi, Avrupa Ligi maçları vs yok. Neden yok?
Eksiksiz olması lazım."

## Neden yoktu?

1. **Veri.** Uygulamanın bütün kaynakları (football-data.co.uk, onun GitHub kopyası, openfootball lig dosyaları, ESPN
   lig uçları) yalnızca **ulusal lig** maçlarını veriyordu. Kupa ve Avrupa maçlarının ne sonuçları ne fikstürleri
   indiriliyordu. Bu yüzden listede hiç görünmüyorlardı.
2. **Model.** Maç sonucu modeli (Elo + Dixon-Coles + makine öğrenmesi) her ligi **kendi içinde** ölçer. Premier
   League'de 1600 Elo ile Süper Lig'de 1600 Elo aynı güç değildir. Farklı liglerden iki takımı karşılaştıracak ortak
   bir ölçek yoktu. Lig modeliyle Avrupa maçı tahmin etmek yanlış sonuç verirdi: Süper Lig'in lideri ile Premier
   League'in orta sıradaki bir takımı eşit görünürdü.
3. **Uygunluk kuralları** her maçı tek bir ligin takvimine göre denetliyordu. Kupa maçında iki takımın ligi farklıdır.

Üçü de eklendi: kupa verisi, **ligler arası ortak model** ve iki takımın ayrı liglerine göre çalışan uygunluk kontrolü.

## Kapsam

Veri sayfasındaki "Kupalar ve Avrupa maçları" bölümünden seçilir (komut satırı: `update --kupalar`).

| Grup | Turnuvalar | Varsayılan |
|---|---|---|
| UEFA | Şampiyonlar Ligi, Avrupa Ligi, Konferans Ligi (üçü de eleme turlarıyla ayrı), UEFA Süper Kupa | her zaman |
| Yurt içi | Türkiye Kupası, FA Cup, Lig Kupası (İngiltere), Community Shield, Kral Kupası, İspanya/Almanya/İtalya/Fransa Süper Kupası, Almanya/İtalya/Fransa/Hollanda/Portekiz/İskoçya/Belçika/Yunanistan Kupası, Johan Cruyff Kalkanı, İskoçya Lig Kupası | ülkesinin ligi seçiliyse |
| Diğer kıtalar | Copa Libertadores, Copa Sudamericana, CONCACAF Şampiyonlar Kupası, Leagues Cup, AFC Şampiyonlar Ligi, Arjantin/Brezilya Kupası, ABD Açık Kupası | o kıtanın bir ligi seçiliyse |

"Doğrulanmadı" işaretli üç kod (Türkiye, Belçika, Yunanistan kupası) ESPN'in herkese açık listesinde bulunamadı. ESPN
bunlara veri vermezse güncelleme raporu bunu açıkça yazar; tahmin uydurulmaz.

## Veri kaynakları

| Kaynak | Ne verir | Koşul |
|---|---|---|
| [openfootball/champions-league](https://github.com/openfootball/champions-league) (CC0) | UEFA turnuvalarının geçmiş sezonları (Şampiyonlar Ligi 2011'den, Avrupa Ligi ve Konferans Ligi dosyası olan sezonlar, eleme turları) | onay gerekmez |
| ESPN skor tablosu (resmi olmayan uç) | Bütün turnuvaların içinde bulunulan ve önceki sezonu: fikstür, sonuç, tarafsız saha, takım numarası | onay + kişisel kullanım beyanı; "Yalnızca GitHub" profilinde kullanılmaz |

Kurallar:

- **Bir turnuvanın bir sezonu tek kaynaktan alınır.** Bitmiş sezonda openfootball dosyası varsa o, yoksa ESPN.
  İçinde bulunulan sezonda ESPN (yoksa openfootball). Kaynaklar birbirine karıştırılmaz.
- **Skor her zaman 90 dakikadır.** openfootball'da "1-1 a.e.t. (1-1, 0-1)" satırında normal süre parantezdeki ilk
  skordur. Normal süre skoru yazılmamış uzatmalı maç atlanır. ESPN'de uzatmaya/penaltıya giden maçın normal süre
  skoru yalnızca dönem skorları maç skoruyla tutarlıysa okunur, değilse maç atlanır. Penaltılar sonuç sayılmaz.
- Hükmen, iptal ve ertelenen maçlar sonuç sayılmaz. Tanınmayan satır nedeniyle sayılır ve raporda görünür.
- Final ve süper kupa maçları tarafsız sahadadır (openfootball: turun adı "Final"; ESPN: `neutralSite`).
- **Köken.** openfootball dosyasının kullanılan baytları özetiyle (`raw/kupa_koken/`) saklanır. Kupa satırları ancak
  bu kopyadan aynı okuyucuyla yeniden üretilebiliyor **ve** kayıttaki satır özeti tutuyorsa hak kazanır (VERI-02
  ilkesi). Bozulan kopya, değiştirilen skor veya uydurulan özet yakalanır.
- Lig maçlarının verisine dokunulmaz. Kupa verisi ayrı dosyalarda tutulur (`cup_matches.pkl`, `cup_fixtures.pkl`).

## Takım kimliği

Kupa kaynaklarındaki adlar depodaki adlardan farklıdır ("Manchester City FC (ENG)", ESPN "Manchester City"; depoda
"Man City"). Kimlik yalnızca kanıtla kurulur, benzerlikle eşleme yapılmaz.

- **openfootball:** Adın yanındaki ülke kodu ülkeyi verir. Ad yalnızca **o ülkenin** depo takımları arasında aranır
  (aynı ad, normal ad veya o ülkenin doğrulanmış takma adı). İspanyol bir "Arsenal" İngiliz Arsenal'le birleşmez.
  Bulunamayan ad hiçbir takıma bağlanmaz ve raporda gösterilir.
- **ESPN:** Takım numarası iki yoldan bağlanır: (1) aynı takımın ESPN'deki **lig** maçları depodaki lig maçlarıyla
  maç kanıtıyla eşleşir (KAYNAK-04 kuralı), (2) ESPN kupa maçları openfootball kupa maçlarıyla aynı turnuvada, tarih
  ±1 gün ve aynı skorla tek adaylı eşleşir (en az 2 maç, oyların hepsi aynı takımda). İki kanıt çelişirse numara
  bağlanmaz.
- **Ligi veride olmayan takımlar** (ör. Slavia Praha, Qarabağ) kendi kupa geçmişleriyle ayrı bir kimlik alır. Tahmin
  edilebilirler ama bahis adayı olmazlar.

## Ligler arası ortak model

Bütün lig ve kupa maçları tek bir zaman ağırlıklı Poisson modelinde çözülür:

    log λ_ev  = μ + H + (A[ligi_ev] + a_ev) − (D[ligi_dep] + d_dep)
    log λ_dep = μ     + (A[ligi_dep] + a_dep) − (D[ligi_ev] + d_ev)

- `a`, `d` takımın lig ortalamasına göre hücum ve savunma gücü; `A`, `D` ligin gücü. Lig maçında iki takımın ligi
  aynıdır, bu yüzden ligler arasındaki fark **kupa maçlarından** (ve küme düşen/çıkan takımlardan) öğrenilir.
- `H` iç saha avantajı: lig maçlarında lige, kupalarda turnuva grubuna özgüdür. Tarafsız sahada sıfırdır.
- Ridge cezaları (takım 12, lig 0,5, ligi veride olmayan ülke 4), zaman sönümü ξ = 0,0019/gün (yarı ömür ≈ 1 yıl),
  pencere 3 yıl. Parametreler geliştirme döneminde (2018/19–2021/22 kupa maçları) seçildi, 2022/23–2025/26 test
  döneminde **bir kez** sınandı: test log-kaybı 0,958, taban 1,044.
- **Kalibrasyon:** toplam gol ve güç farkı yeniden ölçeklenir (`T = exp(a + b·log(λ+ν))`, `q = σ(δ + γ·log(λ/ν))`).
  Her sezon yalnızca **önceki** sezonların örneklem dışı tahminleriyle kalibre edilir. δ iç saha düzeltmesidir ve
  tarafsız sahada uygulanmaz (takımların yeri değişince tahmin simetrik değişir; model sürümü `kupa-model-v2`).
- Piyasa oranıyla karıştırma yoktur: ücretsiz veride kupa maçlarının oranı yok.

## İleriye dönük doğrulama ve statü

Kupa maçı olan her hafta model yalnızca o haftanın başından **önceki** maçlarla kurulur ve o haftanın kupa maçları
tahmin edilir (model o maçları görmez). İlk örneklem dışı sezon yalnızca kalibrasyon içindir, ölçüme girmez.

Önceden tanımlı kural (`kupa-dogrulama-v1`), doğrulama grubu başına (UEFA / yurt içi / diğer kıtalar): en az 300
örneklem dışı maç **ve** 1X2 log-kayıp farkının (model − önceki sezonların kupa sonuç oranları) hafta bloklu bootstrap
%95 üst sınırı sıfırın altında → **doğrulandı**. Doğrulanmayan grubun tahmini gösterilir ama bahis adayı olmaz.

Gerçek veriyle (16 varsayılan lig, 10 yıl; UEFA turnuvaları openfootball'dan; eğitim 17 sn):

| Grup / turnuva | Maç | Log-kayıp | Taban | İsabet | Statü |
|---|---:|---:|---:|---:|---|
| **UEFA turnuvaları (elemeler dahil)** | 3049 | 0,953 | 1,047 | %56,1 | doğrulandı (fark üst sınırı −0,076) |
| Şampiyonlar Ligi | 984 | 0,901 | 1,037 | %59,2 | |
| Şampiyonlar Ligi (eleme) | 163 | 0,953 | 1,036 | %54,6 | |
| Avrupa Ligi | 790 | 0,969 | 1,055 | %56,3 | |
| Avrupa Ligi (eleme) | 147 | 0,962 | 1,057 | %55,8 | |
| Konferans Ligi | 542 | 0,979 | 1,051 | %53,7 | |
| Konferans Ligi (eleme) | 423 | 1,008 | 1,050 | %51,8 | |

Her sezon (2019/20–2025/26) model tabandan iyidir (log-kayıp 0,90–0,96, taban 1,03–1,07). 2,5 Üst için de tabandan
biraz iyidir (0,682 / 0,689), karşılıklı golde fark çok küçüktür (0,691 / 0,693).

Ortak ölçekte lig gücü (gol farkı: ortalama takıma karşı tarafsız sahada, 90 dk): Premier League +2,22, Ligue 1 +1,62,
Bundesliga +1,51, La Liga +1,49, Serie A +1,37, Liga Portugal +0,76, Eredivisie +0,75, Pro League +0,68, Süper Lig
+0,41, Premiership (İskoçya) +0,34, Super League (Yunanistan) +0,30; ikinci ligler −0,1 ile −0,2 arasında.

## Veri uygunluğu (kupa maçı)

Lig maçlarındaki ortak kural iki takımın **ayrı ligleri** üzerinden uygulanır ve sonuç aynı `Eligibility` nesnesidir.

| Kod | Ne zaman | Etki |
|---|---|---|
| `KUPA_TAKIM_VERISI_YOK` | takımın son 365 günde lig + kupa maçı 5'ten az | tahmin yok |
| `TAKIM_GECMISI_YETERSIZ` | 10'dan az | bahis adayı değil |
| `KUPA_TAKIM_LIGI_VERIDE_YOK` | takımın ligi uygulamada yok (ör. Çekya) veya alt lig | bahis adayı değil; sıkı modda tahmin de yok |
| `KUPA_MODEL_DOGRULANMADI` | turnuvanın doğrulama grubu doğrulanmadı | bahis adayı değil |
| `KUPA_TAKVIMI_YOK` | turnuvanın ESPN takvimi yok | sıkı modda tahmin yok; standart modda not |
| `TAKIM_ESLESMESI_DOGRULANAMADI` | ESPN fikstürünün numarası/takımları takvimde yeniden bulunamadı | tahmin yok |
| `DEPODA_EKSIK_MAC`, `KAYNAK_DURUMU_BELIRSIZ`, `SON_SONUC_BEKLENIYOR` | takımın kupa maçı kaynakta oynanmış görünüyor ama depoda yok / sonucu bilinmiyor | lig kuralıyla aynı |

Bunların yanında her takımın **kendi liginde** lig maçlarıyla aynı kaynak takvimi denetimleri (eksik maç, kapsam,
güncellik), haklar, model durumu ve zaman denetimleri çalışır. Güncellik kanıtı ancak iki takımın lig takvimi ve
turnuvanın takvimi varsa oluşur.

## Arayüz (masaüstü ve web)

- **Tahminler:** kupa maçları lig maçlarıyla aynı listede. "Lig / turnuva" seçiminde "Yalnızca kupa ve Avrupa
  maçları" ve tek tek turnuvalar var.
- **Maç ayrıntısı:** modelin doğrulama satırı, ortak ölçekte takım karşılaştırması (ligi, gücü, beklenen gol, son 365
  günde maç), iki takımın lig + kupa son maçları ve aralarındaki maçlar.
- **Maç Analizi → Ligler arası / kupa maçı:** farklı liglerden iki takım, turnuva, tarih, tarafsız saha ve isteğe bağlı
  kendi oranlarınız. Sonuç aynı uygunluk kontrolünden geçer.
- **Güç Sıralaması → Avrupa (ligler arası ortak ölçek):** liglerin ve en güçlü 60 takımın ortak ölçekteki gücü.
- **Veri:** turnuva seçimi, kupa verisi özeti, yaklaşan kupa maçı sayısı ve doğrulama raporu.
- **En Olası Seçimler:** uygun kupa maçları da listelenir. Kartlar lig modelinin geçmişidir; kupa modelinin aynı
  eşikteki örneklem dışı geçmişi (yalnızca doğrulanmış gruplar) ayrı bir satırda yazılır.
- **Gol Pazarları:** KUPA-01'de kupa maçları bu sayfada yoktu. KUPA-GOL-02 ile eklendi: ligler arası ortak modelin
  kalibre gol beklentileri ilk yarı payıyla yarılara bölünür; her doğrulama grubu ve pazar ayrı ölçülür. Ayrıntılar ve
  gerçek veri sonuçları: [`KUPA_GOL_02.md`](KUPA_GOL_02.md).

## Komut satırı

```bat
.venv\Scripts\python -m bahis_tahmin update --kupalar varsayilan        & rem veya UCL,UEL,UECL / hepsi / yok
.venv\Scripts\python -m bahis_tahmin kupa-turnuvalar                    & rem kodlar ve seçim durumu
.venv\Scripts\python -m bahis_tahmin kupa-egit                          & rem ortak model + ileriye dönük doğrulama
.venv\Scripts\python -m bahis_tahmin kupa-tahmin --turnuva UCL
.venv\Scripts\python -m bahis_tahmin kupa-rapor                         & rem kupa verisi ve doğrulama raporu
```

Arayüzde "Kaydet, Güncelle ve Eğit" kupa verisini de günceller ve kupa modelini (veri değiştiyse) eğitir. Turnuva
seçimi boşaltılırsa kupa verisi ve kayıtlı kupa modeli kaldırılır.

## Sınırlar

- **Oran yok:** kupa maçları için ücretsiz veride piyasa oranı yoktur. "Değer" yalnızca Maç Analizi'nde kendi
  oranınızı girerseniz hesaplanır; geçmiş getiri hesaplanamaz.
- **Yurt içi kupalar ve diğer kıtalar:** geçmişleri yalnızca ESPN'den (iki sezon) gelir. İlk örneklem dışı sezon
  kalibrasyona ayrıldığı için 300 maçlık doğrulama eşiğine ulaşmayabilirler. Bu durumda tahmin gösterilir ama
  "doğrulanmadı" olarak bahis adayı olmaz. Doğrulama gerçek verinizle her eğitimde yeniden ölçülür.
- **Alt lig takımları** (ör. FA Cup'ta National League takımları, Türkiye Kupası'nda 2. Lig takımları) uygulamanın
  liglerinde yoksa "ligi veride yok" olur, bahis adayı olmaz.
- Tahmin 90 dakikalık sonuçtur. Uzatma, penaltı ve "tur atlama" olasılığı tahmin edilmez.
- Dizi Araştırması ve GitHub tarihsel arşivi yalnızca lig maçlarını kapsar.

## Testler

`tests/test_kupa_01.py` (30 test, yalnızca sentetik veri: iki lig + Avrupa kupası dünyası, `tests/kupa_yardim.py`):
openfootball okuyucusu (90 dk, uzatma, penaltı, hükmen/iptal, tarih denetimleri), ESPN uzatmalı maç okuma, ülke
kapsamlı kimlik, ESPN numara kanıtı ve çelişki, openfootball + ESPN birlikte çevrimdışı güncelleme (kaynak seçimi,
kimlikler, takvimler), köken (kopya, özet, satır yeniden üretimi), onaysız ESPN isteği olmaması, veri deposu, modelin
ligler arası farkı öğrenmesi, ileriye dönük doğrulamada sızıntı olmaması (aynı haftanın sonuçları değişse de tahmini
değişmez), az veride doğrulanmama, tarafsız saha simetrisi, kayıt/yükleme, tam uygun olumlu kontrol ve her uygunluk
denetiminin tek tek bozulması, ayarlar, web sayfaları, komut satırı ve masaüstü sayfaları.

Testlerin hata yakaladığı 14 kasıtlı bozmayla (sızıntı, kodların kaldırılması, eşikler, köken denetimleri, onay,
ülke kapsamı, tarafsız saha) ayrı ayrı denetlendi: hepsinde en az bir test kırıldı.

Bu iş sırasında testlerin bulduğu iki hata düzeltildi: ESPN ↔ openfootball kupa kanıtı var olmayan bir sütun adını
okuyordu (ESPN kupa verisi geldiğinde güncelleme çökecekti); kalibrasyonun iç saha terimi tarafsız sahada da
uygulanıyordu.

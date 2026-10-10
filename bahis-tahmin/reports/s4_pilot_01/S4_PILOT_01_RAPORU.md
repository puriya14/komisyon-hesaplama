# S4-PILOT-01 — openfootball sonuçlarıyla tek ligde (E0) gerçek A/B/C pilotu

**Sonuç durumu: `SOURCE_COVERAGE_BLOCKED`**

Veri hattı uçtan uca çalıştı: kaynak (sabit commit), sonuç adaptörü, köken doğrulaması, kimlik, ayrı pilot
eğitimi, uygunluk kontrolü ve pilot defterine kayıt. Ancak gerçek yaklaşan maçlar için hiçbir olasılık kaydı (TAHMIN)
oluşmadı. Kaynağın takvim kapsamı bağımsız bir katılımcı listesiyle doğrulanamadı (resmî lig sitesi bu ortamın ağ
politikasınca engelli). Kaynak 2026-09-22'den beri güncellenmediği için tarihi geçmiş 6 maçın sonucu da bilinmiyor.
Model eğitildi; üç pazar da `MODEL_NOT_VALIDATED`.

Bu dosya yalnızca toplu sayılar içerir: gerçek maç satırı, tahmin listesi, ham veri veya model dosyası yoktur. Gerçek
veri pilotunun sonuçları sentetik test sonuçlarından ayrıdır (bölüm 13). Tarihler UTC; bilgi kesimi İstanbul günü.

## 1. Kaynak erişimi ve doğrulanan lisans/kapsam

| Kaynak | Erişim | Sabit ref | Lisans |
|---|---|---|---|
| openfootball/football.json | `git ls-remote` + kısmi klon (`--filter=blob:none --depth 1`, tüm depo indirilmedi); sezon dosyaları raw.githubusercontent.com'dan **sabit commit** adresiyle | `e6744429ee395bc86f247348c6184bb08d4eb361` (commit tarihi 2026-09-22T09:33:49Z, "auto-update week 39") | `LICENSE.md` git nesnesi `670154e3538863b2…`: CC0 1.0 Universal |
| openfootball/clubs (yalnızca kulüp alternatif adı kanıtı) | kısmi klon, tek dosya: `europe/england/eng.clubs.txt` (git nesnesi `685470b0704b…`, SHA-256 `272bf00c7cc8…`) | `ae3800227c449447b3a337fc0aac79a8f02f4c8b` (2025-01-03) | aynı CC0 1.0 metni (aynı git nesnesi) |

- CC0, derleyicinin telif ve veritabanı haklarından feragatidir. Verinin doğruluğunu garanti etmez ve üçüncü kişi
  haklarını temizlemez (madde 4). Sınırsız garanti olarak sunulmadı.
- İndirilen sezon dosyaları git nesneleriyle bayt bayt aynıdır. 11 dosya 2026-10-10T22:10:55Z–22:11:06Z arasında
  tek tek ve sırayla alındı; sonraki çalıştırmalar önbellekten okundu, yeniden indirme olmadı.
- İlk inceleme önce devam eden (2026-27) ve son tamamlanan (2025-26) sezonla yapıldı. Ardından 10 tamamlanmış sezon
  ve devam eden sezona genişletildi (11 dosya; üst sınır 17).
- `openfootball/england` (Football.TXT) aynı veri zincirindedir (son commit 2026-09-21). Bağımsız çapraz kontrol
  sayılmadı.
- Erişilemeyenler: www.premierleague.com ve footballapi.pulselive.com (ağ vekili 403), en.wikipedia.org (ulaşılamadı),
  api.github.com commit uç noktası (403; bu yüzden `--ref` verildi), `LICENSE.md` raw adresi bir kez 429 (kullanılmadı;
  lisans git nesnesinden okundu). Yeni vekil, hesap veya atlatma yöntemi kurulmadı.

## 2. Kullanılan lig, gerçek sezonlar ve veri kesim tarihi

- Lig: İngiltere Premier League (`E0`). 10 tamamlanmış sezon (2016/17–2025/26) ve devam eden 2026/27.
- Gerçek tarih aralığı: 2016-08-13 – 2026-09-20 (son skorlu maç). Kaynak commit'i 2026-09-22, alım 2026-10-10.
  Alım anı skorların güncelliği değildir.
- Bilgi kesimi (kayıt anı): 2026-10-11 (İstanbul). Pilot hazırlama 2026-10-10T22:27:43Z. Model veri kesimi
  2026-09-20.

## 3. Sezon bazında FT/HT doluluk ve eksiklik sayıları

| Sezon | Kayıt | Geçerli MS | Geçerli İY | Yalnız MS (İY eksik) | Oynanmamış | Karantina | Son skorlu maç | Kesimden önce sonuçsuz |
|---|---|---|---|---|---|---|---|---|
| 2016/17 | 380 | 380 | 353 | 27 | 0 | 0 | 2017-05-21 | 0 |
| 2017/18 | 380 | 380 | 348 | 32 | 0 | 0 | 2018-05-13 | 0 |
| 2018/19 | 380 | 380 | 358 | 22 | 0 | 0 | 2019-05-12 | 0 |
| 2019/20 | 380 | 314 | 295 | 19 | 0 | 66 (`TARIH_SEZON_DISI`) | 2020-06-30 | 0 |
| 2020/21 | 380 | 380 | 350 | 30 | 0 | 0 | 2021-05-23 | 0 |
| 2021/22 | 380 | 380 | 358 | 22 | 0 | 0 | 2022-05-22 | 0 |
| 2022/23 | 380 | 380 | 357 | 23 | 0 | 0 | 2023-05-28 | 0 |
| 2023/24 | 380 | 380 | 369 | 11 | 0 | 0 | 2024-05-19 | 0 |
| 2024/25 | 380 | 380 | 364 | 16 | 0 | 0 | 2025-05-25 | 0 |
| 2025/26 | 380 | 380 | 353 | 27 | 0 | 0 | 2026-05-24 | 0 |
| 2026/27 | 380 | 50 | 45 | 5 | 330 | 0 | 2026-09-20 | **6** |
| **Toplam** | 4180 | **3784** | **3550** | 234 | 330 | 66 | | 6 |

- Yineleme ve çakışan kayıt yok. Uzatma/penaltı alanı, geçersiz skor, İY > MS ve durum belirsizliği de yok.
- 2019/20: 66 maç kaynakta sezon penceresi dışındaki bir tarihle (2019 Temmuz) yazılı. Yıl tahmin edilip
  düzeltilmedi, başka kaynaktan doldurulmadı; karantinada.
- Eksik İY skorları eksik kaldı (0-0 yapılmadı, MS'den türetilmedi).
- 2026/27'de 2026-10-10 tarihli 6 maç bilgi kesiminden önce, ama kaynakta sonuçları yok (kaynak bayat).

## 4. Eşleşmeyen takım ve takvim engelleri

- Fikstür: 14 gerçek yaklaşan maç (2026-10-11 – 2026-10-19). Eşleşmeyen takım adı 0.
- **Kimlik düzeltmesi:** football.json kulüp adlarını 2016/17–2019/20'de çoğunlukla "FC"siz, 2020/21'den itibaren
  "FC"li yazıyor. 14 kulüp iki adla geçiyordu (toplam 49 ad), mevcut sözleşme bunları birleştirmiyordu. Sağlayıcının
  kendi kulüp kaydında **yalnızca o kulübün alternatif adı** olarak listelenen ve pilot verisinde görülen 16 ad,
  kayıttaki kanonik ada eşlendi (ör. "Manchester City" → "Manchester City FC"). Benzerlik veya ek silme ile otomatik
  birleştirme yapılmadı. Sonuç: 35 benzersiz kulüp; normalleştirilmiş ad çakışması 0; her sezon 20 takım.
- **Takvim/kapsam engeli:** Sonuçlar ve takvim aynı dosyadan geldiği için kaynak kendini doğrulayamaz. Bağımsız
  katılımcı referansı (resmî lig kulüp listesi) bu ortamdan alınamadı, kullanıcıdan da gelmedi. Bu yüzden
  2024/25–2026/27 takvimleri `KAYNAK_KAPSAMI_KISMI` kaldı ve 365 günlük pencere kanıtlanamadı. Bugünkü katılımcılar
  eski sezonlara uygulanmadı.
- **Bayatlık:** son skorlu maç 2026-09-20, kaynak commit'i 2026-09-22. 2026-10-10 tarihli 6 maçın sonucu yok.

## 5. Mevcut modele girebilen gerçek özellik-tamam satır sayısı

**3486** satır: İY skoru geçerli ve takım güçleri hesaplanabilir (`usable_rows & ht_rows`). Ham geçerli maç 3784,
İY'si geçerli 3550. Eşik `MIN_TRAIN_ROWS = 500` değişmedi.

## 6. Hangi adaptör ve kod değişiklikleri yapıldı?

- `data/parsers.py`: `parse_openfootball_results` (ayrıştırıcı `openfootball-sonuc-v1`, etiket
  `openfootball-sonuc`):
  - `score.ft`/`score.ht` sözlüğü, yalnızca MS içeren liste, skorsuz (oynanmamış) maç ve eski `score1/score2`.
  - Durum, tur, saat ve kimlik alanları.
  - Skor doğrulaması ve karantina kodları; birebir tekrarın sayılmaması; çakışan kaydın üzerine yazılmaması.
  - Sezon penceresi dışı tarih karantinası.
  - Sağlayıcı kaydından kulüp kanonik adı (`OPENFOOTBALL_CLUB_ALIASES`).
  - Fikstür adaptörü (`parse_openfootball`) değişmedi.
- `data/provenance.py` (yeni): köken kaydı (`SourceFile`) ve doğrulama. Önbellekteki dosya özeti kontrol edilir,
  dosya yeniden ayrıştırılır ve depodaki satırlarla birebir karşılaştırılır. Satır özeti de tutulur.
- `data/source_registry.py`: `openfootball-sonuc` kaydı eklendi (CC0 belgeli, `saglar=("sonuc",)`,
  `koken_dogrulamasi=True`). Eski kaynakların hakları değişmedi. Fikstür etiketi `openfootball` sonuç hakkı kazanmadı.
- `eligibility.py`:
  - Yeni neden kodu `KAYNAK_KOKENI_DOGRULANAMADI` (tahmin ve eğitim engeli).
  - `rights_from_registry`, `training_rights_codes` ve `EligibilityContext` doğrulanmış etiketleri alıyor.
  - `build_context(participants=...)`: aynı kaynak zincirinden gelen satırlar bağımsız katılımcı sayılmıyor.
- `pilot.py` (yeni): yalıtılmış pilot klasörü (kullanıcı klasörüyle aynı, içinde veya onu içeren klasör reddedilir).
  Ayrıca sabit commit ile indirme/önbellek, bağımsız katılımcı referansı, hazırlama, salt okunur özet, mevcut
  `GoalEngine` ile ayrı eğitim ve mevcut `forecast_log` ile kayıt.
- `cli.py`: `pilot-kapsam` (salt okunur), `pilot-hazirla`, `pilot-egit`, `pilot-tahmin [--uygula]` eklendi. `--ev`
  zorunlu. Eğitim hakkı kontrolü köken doğrulamasını kullanıyor.
- `config.py`: `app_home_path()` klasör oluşturmadan yolu verir. `ui/controller.py`: eğitim hakkı kontrolü köken
  doğrulamasıyla. `ui/pages/goals.py`: kaynak tablosunda yeni kayıt "Yalnızca S4 pilotu (köken doğrulaması
  zorunlu)" olarak görünür. Ana uygulama bu kaynaktan sonuç okumaz.
- Belgeler: `docs/S4_PILOT.md` (yeni), `docs/VERI_UYGUNLUK.md`, `docs/LISANS_DENETIMI.md`, `README.md`.
- Sentetik testler: `tests/test_s4_pilot.py` (38 test).

## 7. Pilot modeli gerçekten eğitildi mi?

Evet. Mevcut `GoalEngine` ve mevcut varyant (`goal-joint-1.0/M10_ipf_kosullu`, özellik `goal-feat-1.0`) kullanıldı.
İç zaman sıralı doğrulama 2023–2026 sezonlarında yapıldı. Eşik, varyant ve sezon değiştirilmedi. Eski modelden
ağırlık, kalibratör veya durum taşınmadı. Model yalnızca pilot klasörüne yazıldı.

- **İlk eğitim (geçersiz sayıldı):** 2026-10-10T22:12:34Z, veri özeti `12adc927…`. Eğitimden sonra bölüm 4'teki
  kimlik hatası fark edildi: aynı kulüp sezon sınırında iki ayrı takım sayılıyordu. Bu eğitim sonuçlarına bakılarak
  değil, girdi verisindeki kimlik hatası nedeniyle geçersiz sayıldı. Kimlik düzeltilmiş veriyle **tek** yeniden
  eğitim yapılacağına ve sonucunun ne olursa olsun kabul edileceğine, yeni sonuç görülmeden karar verildi.
- **Kesin eğitim:** 2026-10-10T22:28:09Z, veri özeti `3aa6e5c81c90…`, eğitim satırı 3486. Kaynak etiketi yalnızca
  `openfootball-sonuc`, köken doğrulandı.
- İki eğitimde de üç pazar `MODEL_NOT_VALIDATED`; ölçütler birbirine çok yakın (ilk eğitim Δ LL 0,0058 / 0,0169 /
  0,0076).
- Pilot özetindeki Δ LL nokta değeri yanlış anahtardan okunuyordu (`None`); düzeltildi. Kesin modelin bilgi dosyası,
  yeniden eğitim yapılmadan kayıtlı modelin kendi doğrulama sonuçlarından güncellendi; model dosyası özeti değişmedi.

## 8. Her pazarın gerçek doğrulama statüsü

İç zaman sıralı doğrulama (geçmiş veri). İleriye dönük başarı değildir; kaynağın tarihsel yayın zamanları bilinmiyor.
Kural: Δ LL üst sınırı < 0, kalibrasyon eğimi 0,8–1,25, ECE ≤ 0,02, pozitif ≥ 200.

| Pazar | Test maçı | Pozitif | Δ LL (model − taban) [%95] | Kal. eğimi | ECE | Statü |
|---|---|---|---|---|---|---|
| A: iki yarıda KG | 1131 | 77 | +0,0062 [+0,0020, +0,0109] | −0,72 | 0,029 | `MODEL_NOT_VALIDATED` |
| B: MS 3,5 Üst | 1190 | 421 | +0,0174 [+0,0080, +0,0283] | −0,19 | 0,089 | `MODEL_NOT_VALIDATED` |
| C: İY 1,5 Üst | 1131 | 444 | +0,0087 [+0,0012, +0,0163] | −0,27 | 0,062 | `MODEL_NOT_VALIDATED` |

- Bu tek lig verisinde model, taban orana göre daha kötü log-kayıp veriyor (aralıklar sıfırın üstünde). A pazarında
  pozitif sayısı da 200'ün altında.
- Negatif kalibrasyon eğimi, tek ligde ve küçük test kümesinde bu ölçütün kararsız olabileceğini gösterir. Neden
  araştırılmak üzere açık bırakıldı. Sonuca bakılarak hiçbir şey değiştirilmedi.
- Veri tutarlılık denetimi temiz: ev sahibi gol ortalaması deplasmandan yüksek, 2020/21 seyircisiz sezon farkı
  görünüyor, İY > MS kaydı 0, tarihler sıralı.

## 9. Gerçek gelecek maç için olasılık kaydı oluştu mu?

**Hayır.** Akış gerçek sistem saatiyle (2026-10-10T22:30:00Z = 2026-10-11 01:30 İstanbul) çalıştı. 14 gerçek
fikstür × 3 pazar = **42 kayıt** pilot defterine yazıldı; **hepsi `TAHMIN_YOK`** (gerekçeli). TAHMIN 0, olasılık 0,
`stake_units` toplamı 0, bahis adayı 0, zamanı doğrulanmış oran 0. Defter karma zinciri doğrulandı. Model doğrulama
etiketi çıktıda gösterildi (`MODEL_NOT_VALIDATED`). Sahte maç eklenmedi; geçmiş maç ileriye dönük kayda girmedi;
saat veya protokol başlangıcı geri çekilmedi.

## 10. Oluşmadıysa tam neden ve gereken eksik veri

Birincil nedenler (42 kayıt):

| Neden | Kayıt | Maç | Açıklama |
|---|---|---|---|
| `PENCERE_KACIRILDI` | 9 | 3 | 2026-10-11 maçları; karar hedefi (maç günü 00:00 İstanbul) kayıt anında geçmişti |
| `KAYNAK_KAPSAMI_KISMI` | 33 | 11 | Takvim tamlığı bağımsız katılımcı listesiyle doğrulanamadı |

İkincil neden: `TAKIM_GECMISI_YETERSIZ` 12 kayıt (4 maç). 2026/27'de lige katılan 3 kulübün son 365 günde ligde
yalnızca 5'er maçı var. Eşik (10) düşürülmedi.

Gerçek bir TAHMIN kaydı için gerekenler:

1. **Bağımsız katılımcı referansı.** 2025/26 ve 2026/27 için resmî kaynaktan alınmış kulüp listesi. Kullanıcı
   hazırlar ve `pilot-hazirla --katilimci` ile verir (biçim `docs/S4_PILOT.md`). Bu ortamda resmî site engelli.
   Ortam ayarlarından ağ erişimi açılırsa okunabilir.
2. **Güncel kaynak.** 2026-10-10 maçlarının skorlarını içeren yeni bir football.json commit'i gerekir. Mevcut kurala
   göre referans verilse bile bu 6 sonuçsuz maç tahmini engeller: o gün oynayan takımlarda
   `KAYNAK_DURUMU_BELIRSIZ`, 2026/27 sezonunda %5 sınırını aştığı için `LIG_DURUMU_BELIRSIZ`. Bu engel gerçek
   veride çalıştırılmadı; sentetik testte doğrulandı.
3. Kaydın maç günü 00:00 (İstanbul) öncesinde yapılması. 2026-10-17 maçları için bu sınır 2026-10-16T21:00Z.
4. Lige yeni katılan kulüpler, 10 maçlık geçmiş birikene kadar uygun olmayacak.

Model doğrulaması ayrı bir konudur: `MODEL_NOT_VALIDATED` olasılık kaydını engellemez, açıkça etiketlenir. Bahis
adayı ise gerçek oran olmadan oluşmaz.

## 11. Pilot dosyalarının kalıcı/geçici saklama durumu

Bütün pilot dosyaları (ham sezon dosyaları, veri deposu, iki model, iki pilot defteri) bu oturumun **geçici**
kapsayıcısındaki çalışma alanında. Kalıcı bir hedefe aktarılmadı, depoya veya artifact'a konmadı. Kapsayıcı
kapanınca silinecekler. Kod push'u veri yedeği değildir. Sürekli ileriye dönük izleme başlatılmadı; zamanlayıcı yok.
İlk (geçersiz) eğitimin klasörü ayrı tutuldu (42 `TAHMIN_YOK`, kohort `7033dc6f42e17fac`). Kesin klasörde 42
`TAHMIN_YOK`, kohort `b43ac064a07510ef`.

## 12. Mevcut kullanıcı verilerinin değişmediği kontrolü

- Uygulama veri klasörü (`~/.local/share/BahisTahmin`; `BAHIS_TAHMIN_HOME`/`XDG_DATA_HOME` tanımsız) pilottan önce
  yoktu ve pilottan sonra da yok. Pilot komutları bu klasörü oluşturmadı.
- Önceki görevlerin yerel kopyalarında S4 başladıktan sonra değişen dosya yok (son değişiklik 2026-10-10T14:17:43Z).
- Pilot klasörü kullanıcı klasörüyle çakışırsa komutlar reddediyor (sentetik testlerle doğrulandı). Migration, seed,
  backfill, reset veya eski modele yazma yapılmadı.

## 13. Yerel ve CI test sonuçları

- Sentetik testler `tests/test_s4_pilot.py` (38 test; ağ yok, sahte commit, `example.invalid` referansı) şunları
  kapsar:
  - Adaptör: ht/ft sözlüğü; yalnız MS listesinin İY sayılmaması; 0-0 ile eksik skorun ayrılması; geçersiz ve
    çelişkili kaydın karantinası; tekrarın idempotent olması; kanonik ad eşlemesinin yalnızca kayıttaki adlarla
    yapılması; fikstür adaptörünün değişmemesi.
  - Köken ve haklar: etiketi değiştirilmiş eski satırın köken kontrolünü aşamaması; belirsiz adın kesinleşmemesi.
  - Uygunluk: önceki sezon referansı yoksa pencerenin geçilmemesi; bağımsız referans yokken kapsamın
    kanıtlanmaması; bayat kaynağın engellemesi.
  - Yalıtım ve kayıt: modelin yalnızca pilot yoluna yazılması; oran yokken TAHMIN kaydı ile bahis adayının
    ayrılması; doğrulanmadı etiketinin korunması; kaçırılmış pencerenin doldurulmaması; kullanıcı dosyalarının
    değişmemesi; komut yardımı ve reddetme yolları; ham verisiz temiz kopya.
- Sentetik uçtan uca akışta bağımsız sentetik referansla 24/24 TAHMIN kaydı oluştu: olasılıklı, stake 0, bahis adayı
  yok, `MODEL_NOT_VALIDATED` etiketli. Bu yalnızca kod yolunun kanıtıdır, gerçek veri sonucu değildir.
- Yerel tam paket (temiz kopya, ham veri yok): bkz. oturum yanıtı. Ubuntu ve Windows CI sonuçları bu commit'ten
  sonra çalışır; commit SHA'sıyla oturum yanıtında bildirilir. Bu dosyada başarı iddia edilmez.
- Mevcut testlerde skip, xfail, assertion silme veya tolerans genişletme yok. Yeni kaynak kaydı nedeniyle iki mevcut
  test gerekçesiyle güncellendi:
  - `test_s3_gate_02.py`: `openfootball-sonuc` artık kayıtlı. Kökeni doğrulanmamışken `KAYNAK_KOKENI_DOGRULANAMADI`
    ile engelli olduğu ve doğrulanınca açıldığı ayrıca sınanıyor. Etiket sahteciliği listesi kayıtsız bir etiketle
    sürdürüldü; negatif kontrol korundu.
  - `test_ui.py`: kaynak tablosu 4 yerine 5 satır gösteriyor; yeni satırın "Yalnızca S4 pilotu" durumu da sınanıyor.

## 14. Commit, uzak SHA ve Linux/Windows durumu

Bu raporun commit'i ve CI sonuçları oturum yanıtında verilir (dosya kendi commit SHA'sını içeremez).

## 15. Kullanıcının bilgisayarında aynı pilotu çalıştıracak gerçek komutlar

`<PILOT_KLASORU>`, uygulama veri klasörünün dışında yeni bir klasördür. `<COMMIT>`, `git ls-remote
https://github.com/openfootball/football.json refs/heads/master` ile görülen 40 karakterlik özettir. Bu oturumda
`e6744429ee395bc86f247348c6184bb08d4eb361` kullanıldı; daha yeni bir commit güncel sonuçları içerebilir.

Linux/macOS:

```bash
python -m bahis_tahmin pilot-hazirla --ev <PILOT_KLASORU> --ref <COMMIT> --sezon 10 [--katilimci <REFERANS.json>]
python -m bahis_tahmin pilot-kapsam  --ev <PILOT_KLASORU>
python -m bahis_tahmin pilot-egit    --ev <PILOT_KLASORU>
python -m bahis_tahmin pilot-tahmin  --ev <PILOT_KLASORU>
python -m bahis_tahmin pilot-tahmin  --ev <PILOT_KLASORU> --uygula
```

Windows:

```bat
.venv\Scripts\python -m bahis_tahmin pilot-hazirla --ev "<PILOT_KLASORU>" --ref <COMMIT> --sezon 10
.venv\Scripts\python -m bahis_tahmin pilot-kapsam  --ev "<PILOT_KLASORU>"
.venv\Scripts\python -m bahis_tahmin pilot-egit    --ev "<PILOT_KLASORU>"
.venv\Scripts\python -m bahis_tahmin pilot-tahmin  --ev "<PILOT_KLASORU>"
.venv\Scripts\python -m bahis_tahmin pilot-tahmin  --ev "<PILOT_KLASORU>" --uygula
```

Linux komutları bu oturumda gerçek veriyle çalıştırıldı. Windows komutları aynı CLI'dır; Windows'ta gerçek veriyle
denenmedi, CLI yolları Windows test işinde sentetik testlerle sınanır.

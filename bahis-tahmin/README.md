# Bahis Tahmin

Windows 11 için Türkçe, ücretsiz verilere dayalı futbol analiz uygulaması (PySide6 masaüstü + tarayıcı arayüzü +
komut satırı).

> **18+ · Sorumlu kullanım.** Bu uygulama istatistiksel analiz aracıdır; kazanç garantisi vermez, gerçek
> bahis oynatmaz ve bahis hesabına bağlanmaz. Olasılıklar belirsizlik içerir; geçmiş performans geleceği
> garanti etmez. Bahis bağımlılığı için destek: YEDAM 115.

## Neler var?

| Bölüm | Açıklama |
|---|---|
| Maç sonucu motoru | Elo + zaman ağırlıklı Dixon-Coles + lojistik/gradyan artırma modeli + piyasa oranlarıyla karıştırma; 1X2, çifte şans, alt/üst, KG olasılıkları |
| En Olası Seçimler | Model olasılığı yüksek seçimler ve geçmişte gerçekleşme oranları (avantaj listesi **değildir**) |
| Geriye dönük test | Gerçek 1X2 ve 2,5 Alt/Üst oranlarıyla geçmiş simülasyon |
| **Gol Pazarları** | İki yarıda da karşılıklı gol (A), maç sonu 3,5 Üst (B), ilk yarı 1,5 Üst (C): ortak yarı-gol modeli, belirsizlik aralıkları, kapsam matrisi, doğrulama, karar motoru ve değiştirilemez sanal takip |
| **Dizi Araştırması** | Maç dizileri, olay öncesi/sonrası ve tekrarlar (ör. İY/MS 2/1): geçmiş inceleme, maç öncesi benzer diziler, ön-kayıtlı örüntü doğrulama (çoklu test, yanlışlama, zaman sıralı doğrulama) ve tahminden ayrı anomali incelemesi. **Araştırma statüsündedir**; ana modelleri değiştirmez |

Gol pazarlarının ayrıntıları: [`docs/GOL_PAZARLARI_MODEL_KARTI.md`](docs/GOL_PAZARLARI_MODEL_KARTI.md).
Dizi araştırması: [`docs/DIZI_ARASTIRMA_KULLANIM.md`](docs/DIZI_ARASTIRMA_KULLANIM.md) ve ön-kayıtlı [`docs/DIZI_ARASTIRMA_SOZLESMESI.md`](docs/DIZI_ARASTIRMA_SOZLESMESI.md).
İlk resmi çalıştırmanın sonucu ([`docs/DIZI_ARASTIRMA_SONUCLARI.md`](docs/DIZI_ARASTIRMA_SONUCLARI.md)): örneklem dışında temel modele ve piyasaya ek değer katan bir dizi örüntüsü **bulunamadı**; tekrar eden "iyi form" etkileri piyasa oranlarında zaten yer alıyor, İY/MS 2/1 tipi geri dönüşler için anlamlı öncü koşul yok.

## Kurulum (Windows 11)

1. [Python 3.12+](https://www.python.org/downloads/) kurun ("Add to PATH" işaretli).
2. Bu klasörde `baslat.bat` dosyasını çalıştırın (ilk seferde sanal ortam ve paketler kurulur).
3. Güncellemeden sonra paketleri yenilemek için: `.venv\Scripts\python -m pip install -r requirements.txt`

İsteğe bağlı .exe derlemesi: `exe_olustur.bat` (çıktı: `dist\BahisTahmin\BahisTahmin.exe`).

### Web sürümü (tarayıcıdan)

- `web_baslat.bat`: tarayıcıda `http://127.0.0.1:8765` açılır. Yalnızca bu bilgisayardan erişilir.
- `web_paylas.bat`: aynı ev ağındaki telefon veya tablet için. Açılışta bir giriş parolası sorulur. Ekranda yazan
  `http://192.168…:8765` adresini telefonda açın.

Web arayüzü masaüstüyle aynı verileri, ayarları, modeli ve kuralları kullanır. GitHub arşivi, Dizi Araştırması ve
Araştırma Çalışma Alanı yalnızca masaüstündedir. Ayrıntılar: [`docs/WEB_01.md`](docs/WEB_01.md).

## Veri ve kullanım koşulları

Geçmiş maç verisi football-data.co.uk'tan (erişilemezse ondan türetilmiş GitHub veri setinden) indirilir.
Bu kaynakların yeniden kullanım koşulları açıkça doğrulanamadığı için **ilk indirmeden önce onayınız
istenir**; onay vermediğiniz kaynaktan veri indirilmez. Aynı pencerede, kaynak başına ayrı bir **kişisel kullanım
beyanı** kutusu da vardır. Bu kutuyla verileri yalnızca kişisel ve ticari olmayan amaçla kullanacağınızı beyan
edersiniz: kendi analiziniz, bu bilgisayarda model eğitimi ve tahmin. **Beyan olmadan model eğitilmez ve maçlarda
olasılık gösterilmez** ("veri bulunamadı / MODEL_YOK"). Ayrıntılar:
[`docs/LISANS_DENETIMI.md`](docs/LISANS_DENETIMI.md), [`docs/VERI_01.md`](docs/VERI_01.md).

Veriler, modeller ve sanal takip dosyası yalnızca bilgisayarınızda tutulur:
`%LOCALAPPDATA%\BahisTahmin` (Linux/macOS: `~/.local/share/BahisTahmin`).

## Komut satırı

```bat
.venv\Scripts\python -m bahis_tahmin update --leagues E0,T1 --years 10 --accept-terms football-data --kisisel-kullanim football-data
.venv\Scripts\python -m bahis_tahmin train
.venv\Scripts\python -m bahis_tahmin predict --league T1
.venv\Scripts\python -m bahis_tahmin gol-egit
.venv\Scripts\python -m bahis_tahmin gol-tahmin --league E0
.venv\Scripts\python -m bahis_tahmin gol-kapsam --csv kapsam.csv
.venv\Scripts\python -m bahis_tahmin gol-oran-ice-aktar --csv oranlar.csv            & rem yalnızca doğrular
.venv\Scripts\python -m bahis_tahmin gol-oran-ice-aktar --csv oranlar.csv --uygula   & rem doğrulananları ekler
.venv\Scripts\python -m bahis_tahmin gol-sanal
.venv\Scripts\python -m bahis_tahmin dizi-olay --takim "PSV Eindhoven" --iyms 2/1
.venv\Scripts\python -m bahis_tahmin dizi-arastir --isci 3
.venv\Scripts\python -m bahis_tahmin dizi-benzer --takim "PSV Eindhoven"
.venv\Scripts\python -m bahis_tahmin self-test
```

Tek ligde gerçek veri pilotu (S4; openfootball sonuçları, İngiltere Premier League; bütün yazmalar yalnızca `--ev`
ile verilen ayrı pilot klasörüne): `pilot-hazirla`, `pilot-kapsam` (salt okunur), `pilot-egit`, `pilot-tahmin`
(varsayılan kuru çalıştırma; `--uygula` pilot defterine yazar), `pilot-tani` (M10 aşama tanılaması; ayrı çıktı
klasörü). Ayrıntılar: [`docs/S4_PILOT.md`](docs/S4_PILOT.md).

GitHub veri profili ve tarihsel arşiv (S5): `update --profil github` bütün güncellemeleri yalnızca seçili GitHub
depolarından yapar (football-data adreslerine istek gönderilmez). `arsiv-hazirla`, `arsiv-katalog`, `arsiv-maclar`,
`arsiv-ozet` ve `arsiv-kart` komutları openfootball, datasets, xgabora ve Hudl/StatsBomb depolarını sabit commit'ten
ayrı bir arşiv klasörüne alır; geçmiş maçları kaynak, kapsam ve kullanım hakkıyla birlikte listeler. Arayüzde: Veri
sayfası → "GitHub Veri ve Arşiv". Ayrıntılar: [`docs/S5_GITHUB.md`](docs/S5_GITHUB.md).

Kayıtlı araştırmalar (S6; betimleyici, ayrı çalışma alanı): `calisma-olustur`, `calisma-revize`, `calisma-calistir`,
`calisma-karsilastir`, `calisma-not` ve salt okunur `calisma-liste`, `calisma-oku`, `calisma-calistirma-oku`,
`calisma-dogrula`, `calisma-not-kart`. İki maç grubunun A/B/C ve İY/MS gerçekleşmelerini aynı arşiv sürümünde
karşılaştırır; çalıştırmaları veri ve kod sürümüyle saklar. Ayrıntılar: [`docs/S6_CALISMA.md`](docs/S6_CALISMA.md).
Salt okunur `calisma-olay-karsilastir`, aynı takımın birden çok geçmiş olayının önce/sonra pencerelerini yan yana
gösterir. Olaylar saklı bir çalıştırma grubundan veya açık bir listeden gelir. Ayrıntılar: [`docs/S6_OLAY.md`](docs/S6_OLAY.md).
Arayüzde (S7): "Araştırma Çalışma Alanı" sayfası araştırma oluşturma/revizyon, önizleme, çalıştırma ve saklı sonuç,
grup karşılaştırması, olay matrisi ve notları terminal olmadan sunar. Ayrıntılar: [`docs/S7_UI.md`](docs/S7_UI.md).

## Gol pazarları kısaca

- Üç pazar tek bir ortak gol dağılımından hesaplanır; A ⊆ B ∩ C olduğundan P(A) ≤ P(B), P(A) ≤ P(C)
  her zaman sağlanır. Olasılıklar bağımsız çarpılmaz.
- Bu pazarların **gerçek oranları ücretsiz veride yoktur**. Uygulama oran türetmez; kendi gördüğünüz oranı
  (bahis şirketi ve zamanıyla) girmeniz gerekir. Bu yüzden geçmiş getiri (ROI/CLV) **hesaplanamaz**.
- "Avantaj adayı" yalnızca model o pazar için zaman sıralı testte doğrulanmışsa, güncel gerçek oran
  varsa ve belirsizlik dahil beklenen değer eşiği geçiyorsa oluşur. Çoğu durumda doğru sonuç "aday yok"tur.
- "Sanal takibe kaydet" kararları değiştirilemez biçimde saklar; gerçek para kullanılmaz.
- Bütün tahmin ve karar yolları ortak **veri uygunluk kontrolünden** geçer: güncelliği kanıtla doğrulanamayan veya
  eksikliği bilinen veriyle, kesin kimliği kurulamayan takımla ya da kullanım kapsamı (sonuç kullanımı, model eğitimi,
  model kullanımı) belgelenmemiş kaynakla olasılık gösterilmez, avantaj adayı ve sanal stake üretilmez; neden, veri
  kesimi ve gereken düzeltme yazılır ([`docs/VERI_UYGUNLUK.md`](docs/VERI_UYGUNLUK.md)). Kullanım kapsamı
  doğrulanmamış gerçek veriyle model eğitimi de yapılmaz; kaynak onayı yalnızca indirmeyi kapsar, eğitim ve tahmin
  için kişisel kullanım beyanı gerekir. Varsayılan **standart** veri denetiminde (Ayarlar › Veri denetimi):
  - yalnızca güncelliği bağımsız takvimle kanıtlanamayan maçın tahmini gösterilir ve açıklamada yazılır;
  - bilinen eksik veri veya az geçmiş varsa tahmin "Uyarılı" gösterilir, avantaj adayı olmaz;
  - "Sıkı" mod eski (v2) davranıştır.

## Testler

```bash
python -m pip install -r requirements.txt pytest
QT_QPA_PLATFORM=offscreen python -m pytest -q        # Windows'ta: python -m pytest -q
python -m pytest -q --network                        # gerçek kaynaklara bağlanan testler dahil
```

Testler yalnızca geçici klasörler ve sentetik (açıkça test amaçlı) veri kullanır; uygulama veri klasörünüze
dokunmaz (`tests/conftest.py`: `BAHIS_TAHMIN_HOME` geçici dizine yönlendirilir).

## Belgeler

- [`docs/GOL_PAZARLARI_MODEL_KARTI.md`](docs/GOL_PAZARLARI_MODEL_KARTI.md) — model kartı ve doğrulama sonuçları
- [`docs/DOGRULAMA_YONTEMI.md`](docs/DOGRULAMA_YONTEMI.md) — zaman sıralı doğrulama ve ölçütler
- [`docs/VERI_SOZLESMESI.md`](docs/VERI_SOZLESMESI.md) — veri alanları, pazar kuralları, zaman güvenceleri
- [`docs/LISANS_DENETIMI.md`](docs/LISANS_DENETIMI.md) — veri kaynakları ve kullanım koşulları
- [`docs/TEKNIK_KARARLAR.md`](docs/TEKNIK_KARARLAR.md) — mimari kararlar
- [`docs/DIZI_ARASTIRMA_SOZLESMESI.md`](docs/DIZI_ARASTIRMA_SOZLESMESI.md) — dizi araştırması ön-kayıtlı sözleşmesi
- [`docs/DIZI_ARASTIRMA_KULLANIM.md`](docs/DIZI_ARASTIRMA_KULLANIM.md) — dizi araştırması kullanımı ve dosyaları
- [`docs/DIZI_ARASTIRMA_SONUCLARI.md`](docs/DIZI_ARASTIRMA_SONUCLARI.md) — dizi araştırması sonuçları ve zorunlu test eşlemesi
- [`docs/DIZI_ARASTIRMA_DUZELTMELER.md`](docs/DIZI_ARASTIRMA_DUZELTMELER.md) — sonuç belgesinin kanıt denetimi: düzeltme ve daraltma kaydı (S2-KABUL-01)
- [`docs/ILERIYE_DONUK_OLCUM.md`](docs/ILERIYE_DONUK_OLCUM.md) — A/B/C için ileriye dönük ölçüm protokolü ve elle günlük akış
- [`docs/WEB_01.md`](docs/WEB_01.md) — web sürümü: açma, telefondan parolalı erişim, sayfalar, masaüstüyle ortak çekirdek, güvenlik önlemleri
- [`docs/KAYNAK_06.md`](docs/KAYNAK_06.md) — bütün ligler için ESPN: lig kodları, önceki sezonun play-off maçlarını takvim dışında tutma, geride kalan veri deposu (ek ligler), ad değişikliği, ligler arası kanıt, ESPN benzetimi
- [`docs/KAYNAK_04.md`](docs/KAYNAK_04.md) — Serie B, La Liga 2, Ligue 2, Süper Lig ve 2. Bundesliga için ESPN (onay + kişisel kullanım beyanıyla açılan kaynak): fikstür, eksik dönem, sezon takvimi, maç kanıtlı ad eşlemesi; KAYNAK-05: ESPN'in openfootball'a önceliği
- [`docs/FIKSTUR_03.md`](docs/FIKSTUR_03.md) — diğer liglerin fikstürleri: openfootball Football.TXT metin depoları, dönüştürücü, köken ve kanıtlı takma adlar
- [`docs/VERI_02.md`](docs/VERI_02.md) — eksik dönemin openfootball sonuçlarıyla tamamlanması (köken doğrulamalı), son sonuçların yayın gecikmesi ve Türkçe nedenli etiketler
- [`docs/VERI_01.md`](docs/VERI_01.md) — "birçok maçta veri bulunamadı" düzeltmesi: kişisel kullanım beyanı, doğrulanmış takım takma adları, standart/sıkı veri denetimi
- [`docs/DIZI_02.md`](docs/DIZI_02.md) — dizi araştırması takım-maç tablosu: "aynı gün iki maç" hatası ve kimlik kuralı doğrulaması
- [`docs/VERI_UYGUNLUK.md`](docs/VERI_UYGUNLUK.md) — ortak veri uygunluk kontrolü (güncellik, kapsam, takım kimliği, zaman, işlem kapsamlı haklar; politika v2, S3-GATE-02)
- [`docs/S4_PILOT.md`](docs/S4_PILOT.md) — tek ligde gerçek veri pilotu: komutlar, yalıtım, kaynak kökeni, katılımcı referansı
- [`docs/S5_GITHUB.md`](docs/S5_GITHUB.md) — GitHub veri profili, sürümlü önbellek, tarihsel arşiv ve kaynak/işlem bazında kullanım kapsamı
- [`docs/S6_CALISMA.md`](docs/S6_CALISMA.md) — kayıtlı araştırmalar, revizyon/çalıştırma/not sözleşmesi, iki grup karşılaştırması ve arayüz servis sözleşmesi
- [`docs/S6_OLAY.md`](docs/S6_OLAY.md) — çoklu olay öncesi/sonrası karşılaştırması: giriş yolları, pencere ve sayma kuralları, servis imzası
- [`docs/S6_PERF.md`](docs/S6_PERF.md) — arşiv görünümü hızlandırması: değişen ve değişmeyen davranış, eşdeğerlik kanıtı, ölçüm aracı (`tools/perf_arsiv.py`)
- `reports/s5_github_01/` — S5-GITHUB-01 toplu sonuç raporu (yalnızca sayılar; maç satırı yok)
- `reports/s4_pilot_01/` — S4-PILOT-01 toplu sonuç raporu (yalnızca sayılar; maç satırı ve tahmin listesi yok)
- `reports/s3_gate_02/` — S3-GATE-02 raporu ve dondurulmuş ileriye dönük ölçüm protokolü v3
- `reports/s3_gate_01/` — S3-GATE-01 raporu ve dondurulmuş ileriye dönük ölçüm protokolü v2
- `reports/kabul_s2_01/` — S2-KABUL-01 kabul raporu, denetim kanıtları, kontroller ve dondurulmuş protokol
- `reports/` — deney günlüğü (`experiments.jsonl`) ve doğrulama sonuçları (JSON)

## Kaldırma / geri alma

- Uygulamayı tamamen kaldırmak: `%LOCALAPPDATA%\BahisTahmin` klasörü veriler, modeller, sanal takip defterleri ve
  araştırma geçmişini içerir. Kaldırmadan önce klasörü yedekleyin; defterler (`*.sqlite`) ve `deneyler.jsonl`
  yeniden üretilemez.
- Yalnızca gol pazarları modeli: `goal_engine.joblib` ve `goal_engine.manifest.json` yeniden eğitilebilir model
  dosyalarıdır (yedekleyip taşıyabilirsiniz). `gol_pazarlari.sqlite` sanal takip ve ileriye dönük ölçüm defteridir;
  geri alma için silinmez.
- Dizi araştırması: klasör silinmez; dosya sınıfları ve güvenli geri alma için
  [`docs/DIZI_ARASTIRMA_KULLANIM.md`](docs/DIZI_ARASTIRMA_KULLANIM.md#geri-alma-ve-veri-koruma) (düzeltme:
  S2-KABUL-01).
- Kod değişikliği: önce commit aralığını inceleyin, ilgili commit'leri tek tek `git revert` ile geri alın.

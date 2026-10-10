# Bahis Tahmin

Windows 11 için Türkçe, ücretsiz verilere dayalı futbol analiz uygulaması (PySide6 masaüstü + komut satırı).

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

Gol pazarlarının ayrıntıları: [`docs/GOL_PAZARLARI_MODEL_KARTI.md`](docs/GOL_PAZARLARI_MODEL_KARTI.md).

## Kurulum (Windows 11)

1. [Python 3.12+](https://www.python.org/downloads/) kurun ("Add to PATH" işaretli).
2. Bu klasörde `baslat.bat` dosyasını çalıştırın (ilk seferde sanal ortam ve paketler kurulur).
3. Güncellemeden sonra paketleri yenilemek için: `.venv\Scripts\python -m pip install -r requirements.txt`

İsteğe bağlı .exe derlemesi: `exe_olustur.bat` (çıktı: `dist\BahisTahmin\BahisTahmin.exe`).

## Veri ve kullanım koşulları

Geçmiş maç verisi football-data.co.uk'tan (erişilemezse ondan türetilmiş GitHub veri setinden) indirilir.
Bu kaynakların yeniden kullanım koşulları açıkça doğrulanamadığı için **ilk indirmeden önce onayınız
istenir**; onay vermediğiniz kaynaktan veri indirilmez. Ayrıntılar: [`docs/LISANS_DENETIMI.md`](docs/LISANS_DENETIMI.md).

Veriler, modeller ve sanal takip dosyası yalnızca bilgisayarınızda tutulur:
`%LOCALAPPDATA%\BahisTahmin` (Linux/macOS: `~/.local/share/BahisTahmin`).

## Komut satırı

```bat
.venv\Scripts\python -m bahis_tahmin update --leagues E0,T1 --years 10 --accept-terms football-data
.venv\Scripts\python -m bahis_tahmin train
.venv\Scripts\python -m bahis_tahmin predict --league T1
.venv\Scripts\python -m bahis_tahmin gol-egit
.venv\Scripts\python -m bahis_tahmin gol-tahmin --league E0
.venv\Scripts\python -m bahis_tahmin gol-kapsam --csv kapsam.csv
.venv\Scripts\python -m bahis_tahmin gol-oran-ice-aktar --csv oranlar.csv            & rem yalnızca doğrular
.venv\Scripts\python -m bahis_tahmin gol-oran-ice-aktar --csv oranlar.csv --uygula   & rem doğrulananları ekler
.venv\Scripts\python -m bahis_tahmin gol-sanal
.venv\Scripts\python -m bahis_tahmin self-test
```

## Gol pazarları kısaca

- Üç pazar tek bir ortak gol dağılımından hesaplanır; A ⊆ B ∩ C olduğundan P(A) ≤ P(B), P(A) ≤ P(C)
  her zaman sağlanır. Olasılıklar bağımsız çarpılmaz.
- Bu pazarların **gerçek oranları ücretsiz veride yoktur**. Uygulama oran türetmez; kendi gördüğünüz oranı
  (bahis şirketi ve zamanıyla) girmeniz gerekir. Bu yüzden geçmiş getiri (ROI/CLV) **hesaplanamaz**.
- "Avantaj adayı" yalnızca model o pazar için zaman sıralı testte doğrulanmışsa, güncel gerçek oran
  varsa ve belirsizlik dahil beklenen değer eşiği geçiyorsa oluşur. Çoğu durumda doğru sonuç "aday yok"tur.
- "Sanal takibe kaydet" kararları değiştirilemez biçimde saklar; gerçek para kullanılmaz.

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
- `reports/` — deney günlüğü (`experiments.jsonl`) ve doğrulama sonuçları (JSON)

## Kaldırma / geri alma

- Uygulama verisini silmek: `%LOCALAPPDATA%\BahisTahmin` klasörünü silin (veriler, modeller, sanal takip).
- Yalnızca gol pazarları: `goal_engine.joblib`, `goal_engine.manifest.json`, `gol_pazarlari.sqlite` dosyalarını silin.
- Kod değişikliği: ilgili git commit'ini `git revert` ile geri alın.

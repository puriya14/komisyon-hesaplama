# Veri koruyan geri alma planı (taslak)

Genel yöntem olarak klasör silinmez. Dosya sınıfları ve kaynak satırlar: `uygulama_dosya_envanteri.csv`.

## Mevcut talimatlar neden yetersiz
- README.md:93-95: "`%LOCALAPPDATA%\BahisTahmin` klasörünü silin", "`gol_pazarlari.sqlite` … silin", "`dizi_arastirma` klasörünü silin".
  docs/DIZI_ARASTIRMA_KULLANIM.md:84 ve önceki rapor madde 17 aynı şeyi söylüyor. Bunlar şunları geri dönüşsüz siler:
  değiştirilemez sanal tahmin ve sonuç kayıtları (`gol_pazarlari.sqlite`), elle girilen oranlar, deney geçmişi
  (`dizi_arastirma/deneyler.jsonl`; `clean_test_status` girdisi: research.py:211-235) ve kaynak onay zamanları (`settings.json`).
- Önceki rapordaki `git revert e671c8f..01b7e9f`, `e671c8f` commit'ini KAPSAMAZ (aralık gösterimi başlangıcı dışlar). Ayrıca
  `7437549` commit'ini (altın test toleransı; CI'yı yeşile döndüren düzeltme) geri alır ve depodaki deney geçmişinden
  (`reports/experiments.jsonl`) 9 satırı çalışma ağacından kaldırır (01b7e9f'de 20 satır; e671c8f öncesinde 10 satır;
  satırlar: e671c8f +1, 289854e +1, 398b60b +1, 01b7e9f +7 — `git show --numstat`).

## Adımlar
0. **Uygulamayı kapat ve bekle.** İptal düğmesi yok; kapanışta uzun bir iş varsa pencere gizlenip iş bitene kadar süreç
   yaşar (main_window.py:140-156). Görev Yöneticisi'nde `pythonw.exe`/`BahisTahmin.exe` kalmadığını doğrula.
1. **Durumu kaydet (salt okuma).** `.venv\Scripts\python -m bahis_tahmin gol-sanal > durum_once.txt` (zincir + özet;
   Windows'ta yönlendirmede kodlama hatası riski için önce `set PYTHONUTF8=1`).
   PowerShell: `Get-ChildItem -Recurse $env:LOCALAPPDATA\BahisTahmin | Get-FileHash -Algorithm SHA256 | Export-Csv yedek_ozet.csv`.
2. **Tam yedek (kopya).** `robocopy "%LOCALAPPDATA%\BahisTahmin" "%LOCALAPPDATA%\BahisTahmin_yedek_<YYYYMMDD-HHMMSS>" /E /COPY:DAT`
   → özetleri yeniden hesapla, birebir eşleşmeli. Yedek klasörü salt-okunur yap.
3. **Kodu geri al — geçmişi yeniden yazmadan.** Tercih: eski sürümü yan klasörde çalıştır
   (`git worktree add ..\bahis-tahmin-eski <commit>`). Depoda geri alma gerekiyorsa:
   `git revert --no-commit e671c8f^..01b7e9f` → `git checkout HEAD -- bahis-tahmin/reports bahis-tahmin/tests/test_primary_regression.py`
   (deney geçmişi ve tolerans düzeltmesi korunur) → ayrı commit. Geri alma gerekçesi `reports/experiments.jsonl`'e YENİ satır
   olarak eklenir (satır silinmez).
4. **Sınıf bazında işlem (silme yok, yalnızca taşıma/arşiv):**
   - Tahmin/sonuç kayıtları (`gol_pazarlari.sqlite`; ileride `dizi_arastirma/dizi_arastirma.sqlite`): YERİNDE bırak.
     Eski kod şema v1'i okur; şema değişikliği yapılacaksa geri uyumlu olmalı (ek JSON alanları ve ek dizin eski kodu bozmaz).
     Eski kodun okuyamadığı bir durumda eski kod bir KOPYA üzerinde çalıştırılır.
   - Deney geçmişi (`dizi_arastirma/deneyler.jsonl`, `reports/experiments.jsonl`): yerinde bırak; yalnızca ekleme.
   - Araştırma manifesti/sonuçları (`sonuclar_tam.json, manifest.json, son_sonuclar.json, anomaliler.json, f1_hipotezler.csv`):
     `dizi_arastirma\arsiv\<manifest.zaman_utc>\` altına TAŞI (arayüz sonuç göstermesin isteniyorsa).
   - Yeniden üretilebilir önbellek (`matches.pkl, fixtures.pkl, data_meta.json, engine.*, s0_soy.*, s0_kalibre.pkl`):
     `arsiv\onbellek_<tarih>\` altına taşı; uygulama yeniden üretir. `goal_engine.*` arşivde tutulur (kayıtlar bu modelle üretildi).
   - Ham indirme önbelleği (`raw\`): yerinde bırak (kaynak sonradan değişebilir).
   - Kullanıcı girdisi (`settings.json`): yerinde bırak.
   - Günlükler (`logs\`): yerinde bırak / arşivle.
5. **Önce kopyada dene.** `set BAHIS_TAHMIN_HOME=<yedek kopyasının bir kopyası>` ile eski kodu çalıştır; açılış, veri yükleme,
   `gol-sanal` zinciri doğrulanınca gerçek klasöre geç.
6. **Sonrası.** `gol-sanal` çıktısı 1. adımla aynı kayıt sayısını ve "Zincir doğrulandı"yı vermeli; özet CSV'si korunan dosyalar
   için değişmemiş olmalı.
7. **İleri alma.** Arşivdeki dosyalar yeniden adlandırılarak geri konur; önbellekler yeniden üretilebilir.

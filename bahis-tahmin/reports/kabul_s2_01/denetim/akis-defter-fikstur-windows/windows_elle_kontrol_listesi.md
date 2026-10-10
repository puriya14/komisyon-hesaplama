# Windows elle kontrol listesi (bu ortamda Windows çalıştırılamadı; hiçbiri doğrulanmadı)

Gerçek kullanıcı verisiyle değil, kopya bir uygulama klasörüyle yapın: `set BAHIS_TAHMIN_HOME=C:\Deneme Klasörü ğüşİ\BahisTahmin`.

| # | Kontrol | Nasıl | Beklenen / bilinen risk (kaynak) |
|---|---|---|---|
| W1 | baslat.bat, Türkçe karakterli ve boşluklu klasörde | Kodu `C:\Users\<ad>\Masaüstü\Bahis Tahmin Ğ\bahis-tahmin` altına koyup çift tıkla; ikinci kez çalıştır | İlk çalıştırmada .venv + paketler; ikinci çalıştırmada doğrudan açılış. `cd /d "%~dp0"` tırnaklı (baslat.bat:3) |
| W2 | Yarım kurulum | İlk kurulumda ağı kes, sonra tekrar çalıştır | baslat.bat yalnızca `.venv` var mı diye bakar (satır 4) ve pip hatasını denetlemez (12-13): yarım kurulumda uygulama pythonw ile sessizce açılmaz. Çözüm: `.venv` klasörünü (kod klasörü, kullanıcı verisi değil) silip yeniden çalıştırmak |
| W3 | Python sürümü | `py -0p`; Python 3.11 ile dene | baslat.bat:2 "3.11+", README.md:25 "3.12+" diyor; CI yalnızca 3.13'ü sınıyor |
| W4 | pythonw ile görünmez hata | Uygulama açılmazsa `%LOCALAPPDATA%\BahisTahmin\logs\bahis_tahmin.log` | Konsol yok; tek iz günlük |
| W5 | CLI konsolda ve yönlendirmede | `.venv\Scripts\python -m bahis_tahmin self-test` (konsol) ve `... self-test > out.txt` (cmd ve PowerShell) | Konsolda sorun beklenmez. Yönlendirmede ANSI kod sayfası cp1252 ise `UnicodeEncodeError` (benzetim: cikti/cli_kodlama_dinamik.txt); cp1254'te yalnızca ≥ → Δ içeren satırlar (cli.py:113, 146, 192, 194). Geçici çözüm `set PYTHONUTF8=1` |
| W6 | Veri ve gol komutları | `update --accept-terms football-data`, `gol-egit`, `gol-tahmin`, `dizi-kapsam`, `dizi-benzer --takim "PSV Eindhoven"` | Boşluklu takım adı tırnakla geçmeli |
| W7 | Dizi Araştırması sayfası | Sayfayı aç → olay listesi (PSV) → "Benzer diziler" → "Yaklaşan maçları hazırla" | Tablo arka planda kurulur (kritik olmayan iş). Gerçek fikstürle çalıştır; veri kesimi ile fikstür arasındaki boşluk için UYARI GÖSTERİLMEZ (bilinen boşluk; sentetik: cikti/defter_tazelik_sentetik.json) |
| W8 | Gerçek maç öncesi görünüm | Veri güncelledikten sonra Eredivisie fikstürleri | openfootball "NEC" adı veri adı "Nijmegen"e eşleşmez → NEC maçları listede olmaz, yalnızca güncelleme özetinde sayı uyarısı (cikti/openfootball_takim_eslesme.csv) |
| W9 | İş iptali ve kapanış (kritik iş) | "Verileri Güncelle" başlarken pencereyi kapat → "Bir işlem sürüyor…" → Evet | İptal yok: pencere gizlenir, iş bitene kadar süreç yaşar (main_window.py:145-156). Görev Yöneticisi'nde süreci izle; bu sırada uygulamayı yeniden açmak İKİ ÖRNEK çalıştırır (tek örnek kilidi yok) |
| W10 | Kapanış (kritik olmayan iş) | "Dizi araştırması hazırlanıyor" sürerken kapat | Soru sorulmaz, gizlenip beklenir (main_window.py:141-144) |
| W11 | Zorla sonlandırma | Kopya klasörde güncelleme kaydı sırasında süreci Görev Yöneticisi'nden sonlandır | matches.pkl/fixtures.pkl atomik yazılmaz (store.py:99-104) → sonraki açılışta "veri yok" olabilir; ham önbellekten yeniden güncelleme ile düzelmeli |
| W12 | Sanal takip | Kararları iki kez kaydet; "Kayıt zincirini doğrula"; CSV'yi Türkçe/boşluklu yola dışa aktar, Excel'de aç | Çift kayıt bugün kabul edilir (sentetik: 6 → 12 satır). CSV utf-8-sig (goals.py:679) → Excel'de Türkçe karakterler doğru görünmeli |
| W13 | Kullanıcı adında Türkçe karakter | `%LOCALAPPDATA%` Türkçe karakterli bir kullanıcıda ilk açılış | Linux'ta eşdeğer yol denemesi geçti (cikti/yol_kontrol.json); Windows'ta SQLite/joblib/Qt eklenti yolu ayrıca görülmeli |
| W14 | OneDrive / kilitli dosya | Uygulama klasörü veya kod klasörü OneDrive altında | `settings.tmp → settings.json` ve `*.tmp → *.joblib` değiştirmesi (config.py:105-107, artifacts.py:51-53) kilitte PermissionError verebilir |
| W15 | Europe/Istanbul gösterimi | `python -c "import bahis_tahmin.timeutil as t; print(t._TZ_OK)"` → True; Windows saat dilimini UTC yapıp aynı maça bak | E0 15:00 Londra (BST, 25.10.2026'ya kadar) → 17:00 İstanbul; 25.10.2026 sonrası GMT → 18:00. tzdata yoksa Londra UTC sayılır (timeutil.py:16-19) |
| W16 | Satır sonu | Depoyu Git for Windows ile klonla (`git config core.autocrlf`); `certutil -hashfile docs\DIZI_ARASTIRMA_SOZLESMESI.md SHA256` | LF'de 4599ddb2… (ön-kayıt); CRLF'de 7373470b… → araştırma manifestinde "sozlesme ön-kayıttan farklı" (research.py:174-176 ham bayt özeti) |
| W17 | Antivirüs / ilk açılış | İlk kurulum ve ilk açılış süresi | Defender taraması yavaşlatabilir; işlevsel değil |

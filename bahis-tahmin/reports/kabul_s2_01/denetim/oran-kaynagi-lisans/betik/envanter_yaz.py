"""Denetim tablolarını CSV olarak yazar (elle doğrulanmış satırlar; kaynak satırları 01b7e9f dışa aktarımından)."""
import csv
import sys
from pathlib import Path

OUT = Path(sys.argv[1])

ifade = [
    # dosya, satır, ifade (kısaltılmış), durum, gerekçe/düzeltme
    ("docs/DIZI_ARASTIRMA_SONUCLARI.md", 114, "Bet365 kapanış oranlarının yayımlanma zamanı doğrulanamadığı için",
     "DUZELTILDI", "'kapanış' dayanaksız: ayna README'si OddHome/OddDraw/OddAway'i yalnızca \"Bet365's ... Odd\" ve veri setini \"pre-match odds\" olarak tanımlar; açılış/kapanış/toplama zamanı belirtilmez; football-data notes.txt erişilemedi. Önerilen: 'Bet365 1X2 oranları (ayna README'sine göre; açılış/kapanış ve yayımlanma zamanı belirtilmemiş, doğrulanamaz)'."),
    ("docs/DIZI_ARASTIRMA_SONUCLARI.md", 106, "S0p / marjsız Bet365 (F6 tablo başlığı)", "DARALTILDI",
     "Bet365 etiketi yalnızca ayna README'sine dayanır; marjsız Bet365 için 'bahis yok' yapısaldır (marj > 0 olduğundan p_marjsız·oran − 1 = 1/marj − 1 ≤ −0,0101 < 0,05)."),
    ("docs/DIZI_ARASTIRMA_SONUCLARI.md", 144, "Bet365 oranlarının zamanı doğrulanamaz; piyasa kontrolü ve ROI bu nedenle varsayımsaldır.",
     "DOGRULANDI", "Zaman damgası yok (ham 48 sütunda quoted_at/fetched_at yok). 'Bet365' yalnızca README dayanaklı (DARALTILDI)."),
    ("docs/DIZI_ARASTIRMA_SOZLESMESI.md", 29, "1X2 oranı (Bet365; yayımlanma zamanı doğrulanamaz) ... varsayımsal getiri",
     "DARALTILDI", "Bet365 = ayna README beyanı (OddHome: \"Bet365's Home Team Win Odd\"); football-data özgün sütunuyla (B365H mi B365CH mi) çapraz doğrulanamadı."),
    ("docs/DIZI_ARASTIRMA_SOZLESMESI.md", 131, "S0p: kalibre S0 + Bet365 1X2 marjsız olasılıkları ... Satırların ~%2'sinde oran yoktur.",
     "DARALTILDI", "~%2 tüm veri için doğru (3.038/184.378 = %1,65 maçta tam 1X2 yok); araştırma dönemlerinde eksik pay %0,11–%0,21, F3 uygun satırlarında %0,05–%0,17."),
    ("docs/DIZI_ARASTIRMA_SOZLESMESI.md", 266, "S0, S1/S2 ve marjsız Bet365 aynı maç kümesinde", "DARALTILDI", "Bet365 = README beyanı."),
    ("docs/DIZI_ARASTIRMA_SOZLESMESI.md", 267, "Oran zamanı doğrulanamadığı için varsayımsal", "DOGRULANDI", "Zaman damgası yok."),
    ("bahis_tahmin/sequences/frame.py", 11, "mkt_win/draw/loss, mkt_points : marjsız Bet365 1X2 (oran yoksa NaN; zamanı doğrulanamaz)", "DARALTILDI", "Bet365 = README beyanı; zaman uyarısı mevcut."),
    ("bahis_tahmin/sequences/hazard.py", 311, "MKT_COLS (marjsız Bet365 galip/mağlup logiti ...)", "DARALTILDI", "Bet365 = README; zaman uyarısı YOK."),
    ("bahis_tahmin/sequences/hazard.py", 616, "7b/5: piyasa (marjsız Bet365 1X2 logitleri)", "DARALTILDI", "Zaman uyarısı YOK."),
    ("bahis_tahmin/sequences/hazard.py", 825, "F4 notu: 5 piyasa (marjsız Bet365 1X2 logitleri) kontrolü", "DARALTILDI", "JSON'a aynen yazılır (reports/dizi_sonuclar.json satır 52478); zaman uyarısı YOK."),
    ("bahis_tahmin/sequences/models.py", 15, "S0p ... (takım perspektifi, marjsız Bet365)", "DARALTILDI", "Bet365 = README."),
    ("bahis_tahmin/sequences/models.py", 667, "p0_market docstring: marjsız Bet365; zamanı doğrulanamaz", "DARALTILDI", "Zaman uyarısı mevcut."),
    ("bahis_tahmin/sequences/models.py", 1128, "economic_eval: Bet365 oranları, zamanı doğrulanamaz → varsayımsal", "DARALTILDI", "Zaman uyarısı mevcut."),
    ("bahis_tahmin/sequences/models.py", 1176, "not: Bet365 1X2 oranlarının yayımlanma zamanı doğrulanamaz; sonuçlar varsayımsaldır.", "DARALTILDI", "JSON'da 4 kez (52980, 53040, 53162, 53222)."),
    ("bahis_tahmin/sequences/models.py", 1209, "preds['Bet365_marjsiz']", "DARALTILDI", "JSON anahtarı 4 kez (52974, 53034, 53156, 53216); 0 bahis yapısal."),
    ("reports/dizi_sonuclar.json", 52478, "F4 notes: marjsız Bet365 1X2 logitleri", "DARALTILDI", "Zaman uyarısı yok."),
    ("girdi/onceki_rapor.md", 10, "Bet365 1X2 oranları (satırların yaklaşık %99,8'inde)", "DARALTILDI",
     "Tüm veri (184.378 maç): %98,35 (181.340). Keşif %99,79, parametre %99,79, test %99,89 (maç); F3 uygun takım-satırları %99,83–%99,95. 2000–2005 ısınma: %92,03."),
    ("girdi/onceki_rapor.md", 21, "Bet365 oran zamanı doğrulanamıyor", "DOGRULANDI", "Zaman damgası yok; README zaman belirtmez."),
    ("girdi/onceki_rapor.md", 13, "Dördünde de etki piyasa kontrolüne (S0p) girince kayboldu", "DARALTILDI",
     "5_piyasa her 4 adayda iki dönemde de geçmedi (betimsel doğru), fakat kayıtlı statü gerekçesi 3 adayda test ΔLL, 1 adayda parametre 7b/1–4; piyasa kontrolü belirleyici değildi."),
    ("girdi/onceki_rapor.md", 17, "Piyasa kontrollü modeller eşiği geçen bahis bulmadı", "DARALTILDI",
     "S0p için ampirik (0 bahis); Bet365_marjsiz için matematiksel olarak kaçınılmaz (min marj 1,0102)."),
    ("bahis_tahmin/models/engine.py", 48, "ODDS_TYPE_LABELS 'avg': 'Piyasa ortalaması'", "DUZELTILDI",
     "Ayna kaynaklı veride o_h/o_d/o_a = OddHome/OddDraw/OddAway = README'ye göre Bet365 (tek bahisçi), ortalama değil. football-data yolunda (normalize_main) o_* = Avg/BbAv olduğundan etiket yalnız o yolda doğru."),
    ("bahis_tahmin/models/engine.py", 49, "ODDS_TYPE_LABELS 'max': 'En yüksek oran (varsayımsal)'", "DARALTILDI",
     "Ayna verisinde 2000/01–2004/05'te ham Max yok; omax = Bet365 ile dolduruldu (24.749 satır; 24.701'i ısınma döneminde)."),
    ("bahis_tahmin/ui/pages/settings.py", 72, "'Piyasa ortalaması' tipik bir bahis şirketini temsil eder", "DUZELTILDI", "Ayna verisinde tek bahisçi (Bet365, README)."),
    ("bahis_tahmin/ui/pages/likely.py", 61, "1X2 ve 2.5 Alt/Üst, piyasa ortalaması", "DUZELTILDI", "Ayna verisinde o_o25/o_u25 = Over25/Under25 = README'ye göre Bet365."),
]
with open(OUT / "ifade_envanteri.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["dosya", "satir_01b7e9f", "ifade", "durum", "gerekce_veya_duzeltme"])
    w.writerows(ifade)

kullanim = [
    ("timeline.build_team_matches has_odds", "bahis_tahmin/sequences/timeline.py:104", "o_h,o_d,o_a", "betimsel sütun (UI 'Oran var')", "yok", "-"),
    ("frame.mkt / mkt_points (devig_1x2)", "bahis_tahmin/sequences/frame.py:109", "o_h,o_d,o_a (o maçın kendisi)", "S0p, F4 7b/5, F6, anomali, mkt10", "docstring: 'zamanı doğrulanamaz'", "-"),
    ("S1/S2 özelliği mkt10 (son 10 maçta puan − marjsız beklenen puan)", "bahis_tahmin/sequences/features.py:193", "geçmiş maçların o_* (window_sum yalnız önceki konumlar)", "F3 S1/S2, F6 S1/S2 olasılıkları, S2 kNN uzayı", "sözleşme §6 satır 138 tanımlar; zaman uyarısı yok", "sızıntı yok (yalnız önceki maçlar); geçmiş oran özellik olarak eğitimde"),
    ("F1 7b/5 piyasa kontrolü (S0p offset)", "bahis_tahmin/sequences/patterns.py:555-572; research.py:516,570-571", "S0p (o maçın oranı)", "4 adayın 5_piyasa sonucu; statü belirleyici DEĞİL (3 aday ΔLL, 1 aday 7b/1–4 parametre)", "JSON 5_piyasa kaydında zaman/HISTORICAL etiketi YOK", "sonuç oransız da aynı (NO_ADDED_VALUE)"),
    ("F3 S0p karşılaştırması + S1/S2 7b/5", "bahis_tahmin/sequences/models.py:664-736", "S0p", "GALIBIYET-S1 statüsü YALNIZCA 7b/5 ile NO_ADDED_VALUE (7b/1–3 iki dönemde geçti); MAGLUBIYET-S1 7b/5 + test 7b/2", "gerekce metninde zaman etiketi YOK", "1/8 F3 statüsü yalnız tarihsel orana dayanıyor"),
    ("F4 tehlike 7b/5", "bahis_tahmin/sequences/hazard.py:616-", "MKT_COLS (marjsız logit)", "belirleyici değil (diğer 7b maddeleri ve test ΔLL)", "notta 'marjsız Bet365', zaman uyarısı YOK", "-"),
    ("F6 ekonomik değer", "bahis_tahmin/sequences/models.py:1127-1214", "o_h/o_a (ödeme) + S0p + Bet365_marjsiz", "varsayımsal ROI −%6,1 … −%12,7", "etiket: 'varsayımsal (oran zamanı doğrulanamaz)' VAR", "Bet365_marjsiz 0 bahis yapısal"),
    ("Anomali MODEL_PIYASA_FARKI", "bahis_tahmin/sequences/anomaly.py:117-120", "fr.mkt", "761 bayrak (anomali_ozeti.tur)", "zaman uyarısı YOK", "tanımlayıcı"),
    ("Ana motor piyasa özellikleri / harmanlama", "bahis_tahmin/models/features.py:255; models/engine.py:72-80", "o_h..o_a, o_o25/o_u25", "ana 1X2 motoru (araştırma dışı)", "'Piyasa ortalaması' (ayna verisinde yanlış)", "-"),
    ("Ana backtest", "bahis_tahmin/betting/backtest.py:12-17", "avg/max/b365/pinnacle setleri", "ana uygulama geriye dönük test (araştırma dışı)", "etiketler engine.ODDS_TYPE_LABELS", "ayna verisinde avg=b365, ps_* boş"),
    ("Karar defteri (goals) odds tablosu", "bahis_tahmin/goals/ledger.py:182-203; service.py:28-29", "yalnız manuel giriş (ui/pages/goals.py:395, quoted_at=now) veya kullanıcı CSV'si (cli.py:288, value.py:163)", "A/B/C kararları", "quoted_at/fetched_at zorunlu, TZ zorunlu, ≤60 dk", "tarihsel CSV oranlarını deftere yazan kod yolu YOK"),
    ("Araştırma defteri (sequences)", "bahis_tahmin/sequences/research_ledger.py:180-195", "oran alanı yok", "ileriye dönük sanal kayıt (stake 0)", "-", "oran yazmaz"),
]
with open(OUT / "oran_kullanim_envanteri.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["kullanim", "kod_konumu_01b7e9f", "girdi", "etkiledigi_sonuc", "etiket_durumu", "not"])
    w.writerows(kullanim)

haklar = [
    ("football-data.co.uk", "Aynanın asıl kaynağı (README satır 5, 53); projede doğrudan indirici var (normalize_main) ama araştırma verisinde kullanılmadı (data_meta.sources tümü 'GitHub yedek veri seti')",
     "DOGRULANAMADI", "DOGRULANAMADI", "DOGRULANAMADI", "DOGRULANAMADI (proje politikası: dağıtılmaz)",
     "Hiçbir belge elde edilemedi: WebFetch www.football-data.co.uk/notes.txt ve football-data.co.uk/notes.txt -> getaddrinfo ENOTFOUND; LISANS_DENETIMI.md satır 5-6 da erişilemediğini söylüyor. source_registry'deki 'ücretsiz', 'All Rights Reserved', 'Football DataCo hak iddia eder' ifadeleri bu denetimde belgelenemedi."),
    ("xgabora/Club-Football-Match-Data-2000-2025 (ayna)", "Araştırmadaki tüm maç ve oran verisinin fiilî kaynağı (Matches.csv, sha256 ef224cf2…)",
     "Teknik erişim: herkese açık GitHub raw (izin belgesi değil)", "DOGRULANAMADI (GitHub kullanım koşulları alınmadı; LICENSE otomatik indirme hakkını ayrıca düzenlemez)",
     "DARALTILDI: MIT, xgabora'nın kendi katkısı için 'use, copy, modify, merge, publish, distribute, sublicense' izni verir; README verinin football-data ve ClubElo'dan derlendiğini söyler -> üçüncü taraf hakları MIT ile devredilemez; model eğitimi için asıl kaynak izni DOGRULANAMADI",
     "DARALTILDI: MIT bildirimiyle yalnız xgabora katkısı; asıl kaynak verisi için DOGRULANAMADI",
     "indirilen/xgabora_LICENSE.txt (MIT, 'Copyright (c) 2025 xgabora', 'the Software and associated documentation files'; veri açıkça anılmaz), indirilen/xgabora_README.md satır 5 ve 53 (kaynak football-data/ClubElo); README'de veri lisansı veya football-data izni yok"),
    ("openfootball/football.json", "Yalnızca yedek fikstür (parse_openfootball); oran yok; araştırmada kullanılmadı",
     "İzinli (CC0 feragati)", "İzinli (CC0 feragati, Affirmer'ın hakları için)", "İzinli (Affirmer'ın hakları için)", "İzinli (Affirmer'ın hakları için)",
     "indirilen/openfootball_LICENSE.md: CC0 1.0 Universal, madde 2 feragat (veritabanı hakları dahil); madde 4(c): üçüncü kişilerin haklarını temizleme sorumluluğu reddedilir -> 'tamamen serbest' DARALTILDI"),
    ("ClubElo (aynadaki HomeElo/AwayElo ve EloRatings)", "Ham Matches.csv içinde mevcut (sütun 6-7) fakat normalize_mirror okumaz; araştırma/model kullanmaz",
     "DOGRULANAMADI", "Uygulanmaz (doğrudan indirilmiyor)", "Uygulanmaz (kullanılmıyor)", "DOGRULANAMADI (ham dosya diskte saklanıyor)",
     "Belge alınmadı (bütçe; kullanılmadığı için öncelik düşük). README satır 5, 42: Elo ClubElo'dan, 15.06.2025 sonrası 'provisional continuation'."),
    ("The Odds API", "Entegre değil (source_registry.IMPLEMENTED dışında)", "-", "-", "-", "-", "Kullanılmadığı için denetlenmedi."),
]
with open(OUT / "haklar_tablosu.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["kaynak", "projede_kullanim", "erisim_izni", "otomatik_indirme", "model_egitimi", "yeniden_dagitim", "kanit_belgesi"])
    w.writerows(haklar)
print("yazıldı")

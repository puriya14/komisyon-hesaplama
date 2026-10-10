# Test dönemi temas ve bağımlılık denetimi (S2-KABUL-01 / test-bagimsizligi)

Temel: `01b7e9f` (salt-okunur). Kanıt: `git show`, `reports/experiments.jsonl` (EXP:n, 0 tabanlı), `reports/dizi_sonuclar.json`,
ana oturum dökümü ve üç iş akışının alt ajan dökümleri (düzleştirme: `dokum_duzlestir.py`, `ana_dokum_duzlestir.py`;
arama: `ara.py`). Zamanlar UTC, 2026-10-10. Pickle/joblib yüklenmedi; gerçek sonuçlarla yeni test/uyum yapılmadı.

## Özet

1. **F1/F2/F4/F7 için gerçek S0'a göre istatistik resmi çalıştırmadan önce hesaplanmadı** (tüm dökümlerde
   gerçek veri + istatistik çağrısı taraması: `f1f2f4_on_temas_taramasi.txt`). review:patterns'in gerçek S0 ile
   yaptığı işler yapısal (bağışçı kapsamı) ve simüle sonuçlu referans süreç süresiydi. impl:patterns gerçek sonuçları
   **sahte S0** ile ve **yalnızca keşif** maskesinde kullandı (kapı, yanlışlama, Mod B, Sorgu 2 z, 427 destekli z).
2. **S0p tanımı sonuca bakılarak değişti.** review:models 09:43:37'de eski S0p ile gerçek F3'te S1/GALIBIYET'i
   `OUT_OF_SAMPLE_SUPPORTED` (7b/5 dahil) gördü, 09:45:12'de sıcaklıklı alternatifi gerçek veride (test dahil)
   karşılaştırdı, 09:45:53'te sentetik gösterim yaptı, 09:46:11'de kodu değiştirdi. RUN_DECISIONS `s0p_tanimi`
   (EXP:12) yalnızca "sentetik veride gösterilen zayıflık" diyor → kayıt eksik/yanıltıcı. Değişiklik muhafazakâr
   yönde (F3'te destek → NO_ADDED_VALUE) ama F1 7b/5'e ve (10:01:59'da orkestratörle) F4 7b/5'e yayıldı.
3. **Statüler bu değişiklikten bağımsız:** yayımlanmış kontrollerle statü kuralları 7b/5 çıkarılarak yeniden
   uygulandı (`piyasa_kontrolu_duyarlilik.csv`): F1'in 4 adayı ve F4'ün 2 olayı aynı statüyü alır (karar veren
   kural: 3 adayda ΔLL üst sınırı > 0, 1 adayda parametre 7b/2; F4'te test Holm p = 1,0 / parametre 0,73). Tek
   değişen F3 S1/GALIBIYET (→ OUT_OF_SAMPLE_SUPPORTED, önceden görülmüş aile kuralıyla en fazla EXPLORATORY).
   Dolayısıyla "dördü de piyasa kontrolünde (S0p) kayboldu" ifadesi **doğru ama karar veren neden değil** ve
   sonuçtan sonra seçilen S0p tanımına bağlı.
4. **S0 İY/MS kalibrasyonu test döneminde görüldü ve 9 hücreli kalibratörün biçimi kısmen bu bulguyla
   gerekçelendirildi** (map:joint 07:21:00, 52.902 satırlık 2019+ örneklem içi karşılaştırma; kırmızı takım
   önerisi "dönüş hücreleri %7-12 düşük, ~4 SE" bulgusunu andı). Kalibratörün kendisi zaman güvenli (fold < Y).
5. **Temiz test mekanizması** yalnızca "test açıldıktan sonra `sequences/*.py`, parametre ve uygulama kararı
   özeti değişti mi" sorusunu yanıtlar. Aynı kodla yeniden çalıştırma `temiz: true` döner (test zaten açılmış
   olsa da), veri özeti ve S0 (goals/ kodu, pickle) karşılaştırılmaz (`temiz_test_davranisi_cikti.json`
   senaryo A, B, E). HEAD (`01b7e9f`) kodu özeti `36ca6d11…` ≠ `8ca41041…` olduğundan HEAD ile yeniden çalıştırma
   otomatik "temiz değil" sayılır (senaryo C).

## Bulgular (öncelik sırasıyla)

| # | Konu | Durum | Kanıt | Önerilen ifade / düzeltme |
|---|---|---|---|---|
| 1 | RUN_DECISIONS `s0p_tanimi` gerekçesi | DUZELTILDI | WF3 review:models satır 183-215 (09:42:54–09:47:03); JRN review:models remaining_risks ("the S0p temperature fix came out of the reviewer's real-data inspection of F3") | "S0p'ye S0 sıcaklığı, review:models'in gerçek veride F3 parametre/test sonuçlarını (eski S0p ile S1/GALIBIYET destekli) ve sıcaklıklı alternatifi gerçek veride karşılaştırmasından sonra eklendi; sentetik gösterim sonradan yapıldı." Yeni deney kaydı olarak eklenmeli; S1|S0p ve τ sayıları dahil. |
| 2 | "F1, F2, F4, F7: test dönemi temiz: evet" (SONUCLARI.md:30) | DARALTILDI | EXP:12; T08, T25, T28 (`temas_siniflandirma.csv`) | "F1/F2/F4/F7 istatistikleri gerçek S0'a göre resmi çalıştırmadan önce hesaplanmadı (koşullu örüntüler için ön-kayıtlı). Ancak S0 İY/MS kalibrasyonu test döneminde görüldü ve kalibratör biçimi bu bulguyu anan öneriyle seçildi; F1 ve F4'ün 7b/5 piyasa kontrol tanımı F3'ün gerçek test sonuçlarından sonra değişti (statüyü belirlemedi)." F2 ve F7 statüleri yalnızca keşifte belirlenir. |
| 3 | "Dördünde de etki piyasa kontrolüne (S0p) girince kayboldu" (önceki rapor md. 7; SONUCLARI.md:9) | DARALTILDI | `piyasa_kontrolu_duyarlilik.csv`; research.py `_candidate_status` sırası | "Dört adayın hiçbiri örneklem dışı ek değer göstermedi: üçünde test ΔLL güven aralığı 0'ı içeriyor, birinde parametre döneminde 7b/2 geçmedi. Ayrıca dördü de (sonuçtan sonra tanımlanan) S0p kontrolünde 1'i dışlamadı." |
| 4 | S0 9 hücre kalibrasyonu ve 2019+ | DARALTILDI | WF1 map:joint 107; WF2 redteam:stats 34, redteam:data 70; sözleşme v1 (07:51) → v2 (08:08) | Sözleşme §5 notuna ek: "9 hücreli kalibrasyon biçimi, 2019+ örneklem içi karşılaştırmada görülen dönüş hücresi eksik tahminini anan kırmızı takım önerisiyle seçildi (gerekçe ayrıca yapısal: ikiz tutarlılığı ve referans süreç)." |
| 5 | EXP:10 `durust_not`: "gerçek veride hiçbir koşullu örüntü istatistiği hesaplanmadı" | DARALTILDI | WF1 map:engine 134 (İY/MS oranları piyasa ondalığına göre), map:data (lig/takım P(galibiyet\|İY geride), PSV aralıkları) | "Dizi (maç öncesi koşul) örüntüsü hesaplanmadı; maç içi koşullu oranlar (İY geride → galibiyet), piyasa ondalığına göre İY/MS oranları ve PSV olaylar arası aralıkları görüldü." |
| 6 | Hazard 7b/5 değişikliği zamanı | DUZELTILDI | ANA satır 4157 (10:01:59), 4125 (10:01:20) | 09:4x değil 10:01:59; tetikleyici review:models önerisi; F4 sonucu görülmeden. |
| 7 | Ön-görülme beyanı (EXP:11) kapsamı | DARALTILDI | EXP:11 09:37:02 < review:models bitişi 10:00:50; review:anomaly 09:29:52 | Beyan S0p değişikliğini, anomali sayılarının (845/761/635) resmi öncesi görüldüğünü ve impl:anomaly çalıştırmasını içermiyor; yeni bir ek kayıt gerekir. |
| 8 | Anomali | DARALTILDI | WF3 impl:anomaly 93 (08:54:31), review:anomaly 102 (09:29:52) | Tanımlayıcı; sayılar resmi öncesi görüldü; kural gerçek veride tespit edilen aşırı işaretleme sonrası sözleşme tanımına uyduruldu. |
| 9 | Commit d57eea7'deki hazard.py | BILGI | review:hazard mutasyon testi 09:28:48 başladı (WF3 review:hazard 224), commit 09:28:51; d57eea7 hazard.py:115 `prev = np.where(same, cm, -1)` (mutant "since_leak"); 289854e:116 düzeltilmiş | Ara commit mutant içeriyor; resmi çalıştırma 398b60b (kod özeti 8ca41041… = 289854e) etkilenmedi. Çalışma ağacı ajanlar dosya değiştirirken commit edilmemeli. |
| 10 | Veri sürümü | BILGI | `veri_surumu_cikti.json`, `veri_surumu_varyant_cikti.txt` | CSV düz okunduğunda data_sha256 = aff287d6… (131.438 boş `time` → NaN); `time` boş dizgi yapılınca 6ca929a2… (manifestle aynı). Önceki görev özeti (data_manifest) 281e3ea2… aynı tabloda yeniden üretildi. |
| 11 | TEST_OPENED zamanı | DARALTILDI | research.py:64-70; EXP:14 | 10:36:06 F1'in resmi kaydıdır; test dönemiyle ilk sonuç teması 07:21:00 (toplu S0 İY/MS), ilk test dönemi model değerlendirmesi 09:01:27 (F3). |

## Temiz test mekanizması: ne kanıtlar, ne kanıtlamaz

Kanıtlar: resmi çalıştırmanın (398b60b) sözleşme/parametre/eşleme özetlerinin ön-kayıtla aynı olduğu
(JSON manifest `on_kayitla_uyum` üçü true), `sequences/*.py` kod özetinin `8ca41041…` olduğu ve bu üçlüden
farklı bir sonraki çalıştırmanın otomatik "temiz değil" etiketleneceği (senaryo C).

Kanıtlamaz: (a) kimin neyi ne zaman gördüğünü — erişim kaydı yoktur; F3/F5/F6 elle `SEEN_FAMILIES` ile kodlandı,
S0p ve kalibratör kararlarının görülmüş sonuçlarla bağı hiçbir yerde temsil edilmez; (b) veri değişikliğini
(`veri_sha256` karşılaştırılmıyor, senaryo B); (c) S0'ı (goals/ kodu, `s0_v1.pkl`, senaryo E); (d) aynı kodla
yeniden çalıştırmanın görülmüş sonuçları görülmemiş yapmadığını — senaryo A `temiz: true` döner ve yalnızca
"tanım değişmedi" anlamına gelir. Öneri: `erisim_gecmisi_manifesti_onerisi.json` (ekleme-yalnız, zincirli olay
kaydı; aile başına `ilk_gorulme`; bağımlılık grafiğiyle yayılım; kod özetine goals/ ve tools/research dahil;
S0 pickle bayt özeti; veri özeti okuma biçimi sabit).

## Dosyalar

- `bagimlilik_tablosu.csv/.md` — model/kalibratör/aile başına dönemler, ilk görülme, ön-kayıt, resmi çalıştırma, veri, kod.
- `temas_siniflandirma.csv` — 31 temas, beş sınıf.
- `aile_kanit_statusu.csv` — aile başına bağımlılıklar ve kanıt statüsü.
- `piyasa_kontrolu_duyarlilik.csv` (+ `piyasa_kontrolu_duyarlilik.py`) — 7b/5 çıkarılınca statüler.
- `beyan_dogrulama.csv` (+ `.py`) — orkestratör beyanı satır satır.
- `temiz_test_davranisi.py`, `temiz_test_davranisi_cikti.json` — clean_test_status senaryoları (yapay manifest).
- `kod_ozeti.py`, `kod_ozeti_cikti.txt` — code_sha256 commit başına.
- `veri_surumu*.py`, `veri_surumu*_cikti.*` — veri özetleri.
- `gercek_veri_temaslari.csv` (+ `.py`), `f1f2f4_on_temas_taramasi.txt` — döküm taramaları.
- `erisim_gecmisi_manifesti_onerisi.json` — önerilen erişim kaydı şeması.
- Yardımcı: `dokum_duzlestir.py`, `ana_dokum_duzlestir.py`, `ara.py`, `tablolari_yaz.py`, `olaylar*.jsonl`,
  `journal_sonuclar.txt`, `sozlesme_v1_075125_dokumden.md`, `sozlesme_v2_080837_dokumden.md` (ana dökümdeki Write çağrılarından sözleşme v1 ve v2 metni), `kod/` (01b7e9f arşivi),
  `dizi_sonuclar_01b7e9f.json`.

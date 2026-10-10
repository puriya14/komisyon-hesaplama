# S2-KABUL-01 — Dizi araştırması kanıt denetimi, sayısal uzlaştırma ve gerçek maç öncesi ölçüm

Tarih: 10.10.2026 · Dal: `claude/bahis-tahmin` · Başlangıç: `01b7e9f` · Bu görevin commit'leri yalnızca **yerel**
(uzak depoya push yapılmadı; görev kuralı). Düzeltme kaydı: [`docs/DIZI_ARASTIRMA_DUZELTMELER.md`](../../docs/DIZI_ARASTIRMA_DUZELTMELER.md).
Kanıtlar: bu klasördeki temizlenmiş özetler (`denetim/<denetçi>/`, `kontroller/`, `fikstur_zinciri*.json`). Ham denetim kanıtları paylaşım kapsamı dışında, yalnızca yerel ortamda tutulmaktadır. Public depo temizlenmiş özetleri içerir. Satır düzeyinde gerçek maç verisi (PSV dış doğrulama listeleri ve örneklemi), oturum günlükleri ve denetçi ham çıktıları (S2-KORUMA-02) depoya dahil değildir.

Kanıt statüleri ayrı tutulur: kod/birim · entegrasyon · Windows · veri kapsamı · veri kullanım hakkı · tarihsel zaman
uygunluğu · istatistiksel doğrulama · gerçek oranla ekonomik doğrulama · ileriye dönük ölçüm. Bir raporun varlığı
içindeki sonucun doğrulandığı anlamına gelmez; eksik kanıt başarılı doğrulama değildir.

## A. Doğrulanan başlangıç

| Öğe | Durum | Kanıt |
|---|---|---|
| Dal / HEAD | `claude/bahis-tahmin`, HEAD `01b7e9f` (ilerlememiş), çalışma ağacı temiz | `git log`, `git status` |
| Testler | Yerelde 241 geçti, 1 atlandı (ağ testi) | `testler/taban_01b7e9f.log`; iddia denetçisi bağımsız tekrar etti |
| CI | Ubuntu test işi `01b7e9f`'te yeşil (ikincil kanıt: aktarılan günlük; ham günlük okunamadı). Windows işi hiç çalışmadı. İlk CI (`e671c8f`) kırmızıydı | `girdi/ci_kanit.md`, D-43 |
| Model / çaba | Gerçek oturum bilgisi (`get_session`): yapılandırılmış ve son sunulan model `claude-opus-5-5`; `effort_level` = `xhigh`; bayrak `effortLevel` = `ultracode` | oturum meta verisi |
| Ortam | Linux kapsayıcı; Python 3.13.16, numpy 2.5.3, pandas 3.0.6, scipy 1.18.1, scikit-learn 1.9.1, PySide6 6.12.0. Windows yok | |
| Ağ | `raw.githubusercontent.com` erişilebilir; football-data.co.uk, github.com, psv.nl, eredivisie.nl erişilemedi (DNS) | denetçi ağ günlükleri |
| CLAUDE.md / AGENTS.md | Depoda yok (arandı) | |
| Veri kökeni | Ham `Matches.csv` sha256 `ef224cf2…` → çevrimdışı yeniden kurulum → içerik özeti `6ca929a2…` = manifest (bellek içi; ağ isteği 0) | `tools/research/veri_kokeni_dogrula.py`, `testler/veri_kokeni.log` |
| Kullanıcı değişikliği | Başlangıçta commit'lenmemiş değişiklik yoktu | |

## B. Önceki rapor denetimi

9 bağımsız salt-okunur denetçi (veri kapsamı, PSV dış doğrulama, oran kaynağı/lisans, istatistik uzlaştırma,
anomali uzlaştırma, tolerans/karar etkisi, test bağımsızlığı, akış/defter/fikstür/Windows, iddia denetimi). Alt
ajanlara pickle yükleme, gerçek sonuçlarla yeni test ve depoya yazma yasaktı; yalnızca kendi işlerine gereken veri
bölümleri verildi. İddia denetiminde 79 iddia: **40 DOĞRULANDI, 26 DARALTILDI, 9 DÜZELTİLDİ, 3 DOĞRULANAMADI, 1 BİLGİ.**
Toplam 46 düzeltme kaydı (D-01 … D-46). En önemlileri:

- **DÜZELTİLDİ:** S0p (piyasa kontrolü) tanımı, bir inceleme alt ajanı gerçek veride F3 parametre/test sonuçlarını
  gördükten sonra değiştirildi; ön-kayıttaki gerekçe ("sentetik veride gösterilen zayıflık") eksikti (D-20). Statüleri
  belirlemedi (7b/5 çıkarılınca F1/F4 statüleri aynı), ancak F1/F4 test iddiaları artık "koşullu".
- **DÜZELTİLDİ:** "Bet365 kapanış" → açılış/kapanış niteliği ve zamanı bilinmeyen, README beyanına dayanan 1X2 oranı;
  `HISTORICAL_REFERENCE_ONLY` (D-14). Anomali: "635'in çoğu 1/2 (619) ve 2/1 (218)" → 476 ve 153 (D-28). Geri alma
  önerileri (klasör silme; `e671c8f..01b7e9f` revert) yanlıştı (D-32, D-34). Tolerans anlatımı (D-30).
- **DARALTILDI:** "≈ −0,00005" (D-01), "piyasa bilgiyi zaten içeriyor / ek değer yok" (D-02), "İY/MS'de anlamlı koşul
  yok" (güç sınırlı, D-03), "temiz test" (D-21, D-23, D-37), "kalibrasyon kapısı geçti" (yalnız keşif, D-38),
  "59 boşluk" (D-09), sezon sayısı (D-10), PSV (veride 30 PSV maçı eksik, D-13), "anomaliler açıklandı" (D-27),
  "mevcut tahminler değişmedi" (D-31, D-41).
- **DOĞRULANAMADI:** veri kullanım hakları (D-18), gerçek veride birebir yeniden üretim (D-45), Windows (D-33).

Önceki rapor ve sonuç belgesi sessizce yeniden yazılmadı: sonuç belgesinin gövdesi aynen duruyor, başına yalnızca
düzeltme kaydına işaret eden bir not eklendi; `reports/experiments.jsonl` sonuna bir düzeltme kaydı eklendi (önceki
satırlar değişmedi).

## C. Sayısal uzlaştırma

**Dört F1 adayı** (ΔLL = aday_model_log_loss − referans_log_loss; referans = S0 + sabit; negatif aday lehine; test
2019/20–2025/26; lig-sezon kümeli bootstrap %95; aday başına, çoklu düzeltmesiz):

| Aday | Keşif O/E [%95], WY p (c) | Test n / O / E_adj (O/E) | Test Holm p | ΔLL [%95] | 7b/5 test O/E [%95] | Statüyü belirleyen |
|---|---|---|---|---|---|---|
| MAĞ \| SON5_GAL≥4 & FAVORİ | 0,788 [0,690; 0,887], 0,022 (21) | 3.110 / 346 / 393,8 (0,879) | 0,0017 | −0,000042 [−0,000142; +0,000060] | 0,980 [0,900; 1,060] | test ΔLL |
| MAĞ \| SON5_İY_ÖNDE≥3 & FORM_ÜSTÜ | 0,884 [0,842; 0,926], 0,002 (1) | 5.049 / 1.379 / 1.488,1 (0,927) | 0,0009 | −0,000062 [−0,000175; +0,000053] | 0,993 [0,954; 1,033] | test ΔLL |
| GAL \| SON5_İY_ÖNDE≥3 & FORM_ÜSTÜ | 1,061 [1,033; 1,089], 0,021 (20) | 5.049 / 2.389 / 2.303,4 (1,037) | 0,0049 | −0,000048 [−0,000137; +0,000031] | 0,986 [0,963; 1,010] | test ΔLL |
| GAL \| RAKİP_SON5_İY_ÖNDE≥3 | 0,954 [0,932; 0,975], 0,023 (22) | 15.453 / 4.557 / 4.768,7 (0,956) | 0,0002 | −0,000102 [−0,000197; −0,000010] | 0,986 [0,966; 1,007] | parametre 7b/2 |

- "≈ −0,00005": dört adayın ortancası −0,000055, ortalaması −0,000064 (göreli %0,007–%0,017).
- Aralığı 0'ı dışlayan tek aday (4.): yön −1 (takım S0'ın beklediğinden az kazanıyor), pazar 1X2 "takım kazanır",
  dönem test. Düzeltmesiz; dört aday üzerinde Holm tek yönlü p = 0,072 (ISO-hafta 0,065). Büyüklük: S0'a göre ≈ −1,6
  yüzde puan, S0p sonrası ≈ −0,4 yp (aralık 0'ı içeriyor); tipik 1X2 marj yükünün (≈ 1–5 yp) altında. Ekonomik değer
  **değerlendirilemez** (oran zamanı yok; aday sonuçlardan sonra seçildi). Sonradan eşik konmadı.
- **Güç/MDE** (keşif, %80 güç, ortanca göreli): İY geride→MS galip %52,3; İY önde→MS mağlup %53,3; galibiyet %12,0;
  mağlubiyet %14,0. Aile eşiği \|z\| ≈ 3,98. Ön-kayıtlı pratik önem eşiği yok.
- **Yeniden örnekleme:** F1/F2 R_inner = 1000 (CLI varsayılanı `--R 1000` aynı); plasebo R_outer = 20 tohum × iç R = 200;
  bootstrap 1000. p = (c+1)/(R+1), en küçük p 1/1001. Katı kural (p_adj < 0,05 **ve** MC %99 Clopper–Pearson üst
  < 0,05): R = 1000'de c ≤ 32; R = 200'de c ≤ 2; R = 20'de hiç ulaşılamaz; c = 0 için R ≥ 104 gerekir
  (`tests/test_kabul_s2_01.py::test_strict_rule_reachability`). Sekiz WY-anlamlı hipotezde c = 1,1,1,2,15,20,21,22
  (hepsi katı). Plasebo 0/20: %95 üst sınır tek yönlü 0,139, iki yönlü 0,168 (tohumlar bağımsız sayılırsa; değil →
  iyimser). Bütçe ve durdurma sonuçlardan önce sabitti; "geçene kadar tekrar" yapılmadı.
- **Pozitif/negatif kontrol** (yalnızca sentetik; plan sonuçlardan önce yazıldı: `kontroller/kontroller_plan.json`,
  sha256 `7d29031d…`, 11:50:15 UTC; sonuç 11:56:00 UTC). Aynı tam F1 akışı (WY R = 200 + aday + Holm + ΔLL + 7b +
  piyasa), 3 tohum, örneklem 4 lig × 20 takım × 27 sezon (gerçeğin ≈ %22'si), maç öncesi erişilebilir ekili etki
  (önceki maç "İY geride→MS galip" ise ikinci yarı gol yoğunluğu ×2), piyasa etkiyi bilmiyor:
  - Pozitif (×2): **2/3** tohumda WY-anlamlı ve OUT_OF_SAMPLE_SUPPORTED → önceden yazılan "3/3" ölçütü **GEÇMEDİ**.
  - Negatif (×1): 0/3 OUT_OF_SAMPLE_SUPPORTED, 0 WY-anlamlı → **GEÇTİ**.
  - Duyarlılık (×1,3; ölçütsüz): 0/3.
  - Yakalanan gerçek (ekili) etkilerde bile gösterge ΔLL yalnızca −0,0006 ile −0,0010 arasında.
  - Sonuç: akış yanlış keşif üretmiyor, ancak gücü sınırlı; gerçek veride örüntü bulunmaması küçük etkilerin yokluğunu
    göstermez. Sentetik sonuç gerçek futbol avantajı değildir.
- **Anomali uzlaştırma** (maç düzeyi): 1.600 maç = 845 sürpriz + 761 model–piyasa farkı (6 maç iki bayraklı); 635 + 210
  = 845; 210 = 109 kırmızı kart + 83 lig değişikliği + 11 ikisi + 6 takım adı + 1 takım adı+kırmızı kart. 353 (tüm
  1.600 havuzu; sürpriz 94, piyasa farkı 261), 121 (845 sürpriz havuzu), 429 (tüm havuz; sürprizde 229). Seçim kuralı
  havuz büyüklüğüne bağlı sabit sayı işaretler (101–300: 1; 301–500: 2; 501–700: 3). Maç öncesi yolda anomali tüketicisi
  yok (artık testle korunuyor). Yeni skor üretilmedi; takım/lig/hakem sıralaması yapılmadı.
- **Tolerans 1e-7 → 5e-5:** saf mutlak (atol), maks-norm; rtol yok. CI farkı (A 1,535e-6; A aralığı 4,072e-6) yerelde
  bit düzeyinde yeniden üretildi (OpenBLAS Haswell/Zen çekirdeği + numpy AVX-512 kapalı): model değil hesaplama yolu.
  Aynı yolda tüm anahtarlarda en büyük fark 9,5e-6; 29 yapılandırmada 1,38e-5. Yalnız A (iki yarıda KG) etkileniyor; B ve
  C ULP düzeyinde aynı; etiketler/sonuçlandırma birebir. Karar etkisi: ΔEV = oran·Δp; gerçekçi 0,01 ızgarada 4,1e-6'lık
  fark VALUE↔NO_VALUE geçişi üretmedi, 5e-5'lik fark 618 bin vakada 12–20 geçiş üretti (çoğu A'da). Eşikler
  değiştirilmedi; altın değerler güncellenmedi.

## D. Test bağımsızlığı

| Zaman (UTC) | Olay | Sınıf |
|---|---|---|
| 07:14–08:24 | İnceleme: toplu İY/MS frekansları, piyasa ondalığına göre İY/MS, takım/lig geri dönüş oranları, PSV olayları; 07:21 S0 İY/MS örneklem içi kalibrasyon (2019+) | veriye erişim + inceleme (test dönemi dahil) |
| 08:24:47 | Ön-kayıt (sözleşme `4599ddb2…`, parametre `fc12e491…`, eşleme `69f7a695…`) | — |
| 08:47–09:02 | impl:models gerçek veride F3/F5/F6 (parametre+test) | fit + inceleme |
| 09:37:02 | Ön-görülme beyanı (kapsamı eksik, D-22) | — |
| 09:42–09:51 | review:models F3/F5/F6 yeniden; 09:43:37 eski S0p ile S1/GALİBİYET destekli | fit + inceleme |
| 09:46:11 | S0p'ye sıcaklık (gerçek veri karşılaştırmasından sonra) | yöntem değişikliği (inceleme sonrası) |
| 10:01:59 | Hazard 7b/5'e aynı yaklaşım | yöntem değişikliği |
| 10:07:59 | Uygulama kararları ön-kaydı | — |
| 10:08:10–10:45:40 | Resmî çalıştırma; F1/F2/F4/F7 gerçek S0'a göre ilk kez burada | — |
| 10:36:06 | `TEST_OPENED` (F1 kaydı) | — |

Aile kanıt statüsü: F7 ve F2 ön-kayıtlı, temiz (statü yalnız keşifte); F1 koşullu; F4 ön-kayıtlı, koşullu; F3/F5/F6
keşifsel; anomali tanımlayıcı, önceden görülmüş. Kod özeti tek başına bağımsızlığı kanıtlamaz: eski temiz-test
mekanizması aynı kodla sonradan yapılan tekrarı "temiz" sayıyordu; artık test açılışından sonra başlayan her gerçek veri
çalıştırması yeniden üretimdir (D-23). Erişim geçmişi manifesti önerisi hazırlandı; oturum referansları içerdiği için yalnızca yerelde tutulur.

## E. Değişiklikler (yerel commit'ler; push yok)

- **Yeni:** `bahis_tahmin/goals/forecast_log.py` (FORECAST_RECORD / TAHMIN_YOK / geçersiz ilan / değerlendirme; protokol
  `ileriye-donuk-olcum-v1` 11:52:58Z'de donduruldu), `bahis_tahmin/sequences/odds_status.py`, CLI `gol-olcum-kaydet`
  (varsayılan kuru çalıştırma) ve `gol-olcum-degerlendir`, `tools/research/{veri_kokeni_dogrula, kontrol_pozitif_negatif,
  fikstur_zinciri_kontrol}.py`, belgeler `docs/DIZI_ARASTIRMA_DUZELTMELER.md`, `docs/ILERIYE_DONUK_OLCUM.md`.
- **Sınırlı düzeltmeler:** karar kayıtlarında `BET_CANDIDATE_RECORD`/`KARAR_KAYDI` ayrımı; Mod A aralıklarına veri
  boşluğu işareti (arayüz + CLI); piyasa kontrolü çıktılarına `HISTORICAL_REFERENCE_ONLY` (ön-kayıtlı parametre özeti
  değişmedi; testle korunuyor); temiz-test kuralı (yeniden üretim); sözleşme özeti satır sonundan bağımsız (LF'de aynı
  özet); karar motorunda `SAYISAL_ESIK_YAKINI` gerekçesi (durum ve eşikler aynı; politika sürüm metni v1.1); altın test
  güçlendirildi (toplu fark raporu, aralık NaN maskesi, `tail` göreli ölçütü, A ≤ BC ≤ min(B, C), karar etkisi ve ±tolerans
  duyarlılığı) — altın değerler değişmedi; anomali arayüz etiketleri nötr; yedek veri setindeki "piyasa ortalaması"
  etiketi; openfootball takım adı eşlemeleri (NEC, Rennes, Benfica, Sporting); Windows'ta yönlendirilmiş CLI çıktısı UTF-8;
  oran zaman doğrulamasında `fetched_at` de karar anından önce olmalı; geri alma belgeleri (silme önerisi kaldırıldı);
  CI'a yalnızca elle tetiklenen Windows test işi (derleme/paket yok; çalıştırılmadı).

## F. İleriye dönük ölçüm hazırlığı

- Protokol donduruldu (gerçek sistem saati 2026-10-10T11:52:58Z; gövde sha256 `3946a6e2…`; kopya
  `ileriye_donuk_protokol_v1.json`, test kopyayla kodun eşitliğini denetler). Pencere: maç günü 00:00 İstanbul; 22 lig,
  sonuçlara göre lig seçimi yok; model sürümü = kohort; referans: son 3 tamamlanmış sezon lig oranı; ölçütler log-kayıp,
  Brier, ΔLL (model − referans), kalibrasyon; asgari 300 sonuç + 50 pozitif; birincil değerlendirme 2027-07-01; ara
  raporlar tanımlayıcı; durdurma yalnız bütünlük nedeniyle; zamanlayıcı yok, elle akış (`docs/ILERIYE_DONUK_OLCUM.md`).
- **Henüz hiçbir ileriye dönük tahmin kaydı yok:** bu ortamdaki veri 03.09.2026'da bitiyor ve güncelleme kaynakları
  erişilemiyor. Dondurma anından önceki bir tarih "ileriye dönük başlangıç" diye yazılmadı; sonucu bilinen maç eklenmedi.

## G. Gerçek fikstür ve entegrasyon zinciri (izole klasör)

| Adım | Durum | Kanıt |
|---|---|---|
| Kaynak (openfootball CC0) | 18 ligden 8'inde 2026-27 dosyası var (18 istek) | `fikstur_zinciri.json` |
| Kimlik eşleme | İlk çalıştırmada 148/153 (5 eşleşmedi); eşleme düzeltmesinden sonra 153/153 | `fikstur_zinciri_2_eslesme_sonrasi.json` |
| Zaman doğrulama | 41 maç (bugün) `PENCERE_KACIRILDI`; başlama saati 153/153'te var | aynı |
| Özellik → A/B/C (teknik yol) | Motor 153 maçın hepsinde sonlu olasılık üretti; değerler kaydedilmedi/raporlanmadı | aynı |
| Uygunluk | 112 maç `VERI_GUNCEL_DEGIL` (ligde son kayıtlı maçtan sonra 26–47 oynanmış maç veride yok) | aynı |
| İzole kayıt | 459 `FORECAST_RECORD`/`TAHMIN_YOK`; ikinci çalıştırmada 444 mükerrer atlandı; zincir doğrulandı | aynı |
| Arayüz | Linux ekransız: Gol Pazarları defter tablosu 459 satır, kayıt türü ve neden görünür (**Windows doğrulaması değil**) | `arayuz_offscreen_kontrol.txt` |
| Windows | **NOT_RUN** | — |

Zincirin bütünü **PASS değildir**: teknik adımlar çalışıyor, ancak veri güncel olmadığından tahmin üretilemiyor
(engelli). Kullanılan motor bu görevde, kaynağı bilinen CSV'den yeniden eğitildi (`goal_engine.joblib`, kendi
ürünümüz); başka hiçbir pickle/joblib dosyası yüklenmedi.

## H. Testler

Tam takım (Linux, ekransız Qt): **266 geçti, 1 atlandı (ağ testi; 4 dk 39 sn)** (başlangıç 241 geçti / 1 atlandı). Yeni/değişen testler:
`tests/test_forecast_log.py` (11: aday yokken tahmin kaydı, gerekçeli tahmin-yok, geçmiş/bilinen/dondurma öncesi maç
ileriye dönük sayılmaz, yazma anında saat denetimi, değişmezlik/mükerrer/geçersiz ilan, sonuçlandırma ve kohort ayrımı,
zamanı doğrulanmamış oranın ekonomik sayılmaması ve `fetched_at`, aday/karar kaydı ayrımı, protokol dondurma),
`tests/test_kabul_s2_01.py` (katı kural ulaşılabilirliği, aynı akışta pozitif/negatif kontrol, `HISTORICAL_REFERENCE_ONLY`
etiketi, ön-kayıt özeti, anomali ters-yön koruması, nötr etiketler, takım eşlemeleri, CRLF sözleşme özeti, cp1252
yönlendirilmiş CLI), `tests/test_primary_regression.py` (+4), `tests/test_seq_timeline.py` (Mod A boşluk işaretleri),
`tests/test_seq_research.py` (yeniden üretim temiz değil).

## I. Yetki ve güvenlik

- Uzak depoya push, PR, force-push, reset, toplu revert: **yapılmadı.** İki yerel commit var; kapsayıcı geçici olduğu için
  push edilmezse kaybolabilirler.
- Production veritabanına yazma, migration/seed/backfill, deployment, ZIP/.exe, zamanlayıcı, gerçek bahis/para işlemi,
  model otomatik etkinleştirme: **yok.** Ücretli API yok.
- Ağ: openfootball fikstür dosyaları (CC0; 18 istek), denetçilerin belge/lisans indirmeleri ve PSV için web aramaları
  (15 çağrı). Kazıma yok.
- Silme: mevcut hiçbir veri, defter, araştırma geçmişi veya klasör silinmedi. `reports/experiments.jsonl` sonuna bir
  düzeltme kaydı **eklendi** (önceki satırlar aynı; isterseniz bu ekleme commit'iyle birlikte geri alınabilir).
- Yeni çıktılar yalnızca bu görevin klasörlerine yazıldı (`reports/kabul_s2_01/`, geçici çalışma alanı).
- Önceki görev için dürüstlük notu: araştırma verisi uygulamanın kullanıcı onay kapısı çalıştırılmadan geliştirici
  betiğiyle yüklenmişti (D-18).

## J. Açık engeller ve riskler

1. **Veri güncel değil** (03.09.2026): ileriye dönük ölçüm tahmin üretemez; güncelleme kullanıcı onaylı kaynakla
   kullanıcının makinesinde yapılmalı (bu ortamda football-data.co.uk ve GitHub yedeği erişilemiyor).
2. **Veri kullanım hakları** (football-data.co.uk, yedek veri seti, model eğitimi) belgeyle doğrulanmadı.
3. **Windows** hiç çalıştırılmadı; elle kontrol listesi `denetim/akis-defter-fikstur-windows/windows_elle_kontrol_listesi.md`.
4. Ana uygulamanın karar motoru veri bayatlığını işaretlemiyor (eski veriyle VALUE_CANDIDATE mümkün); öneri:
   fikstür başına son kayıtlı maç ve gün farkı → `INSUFFICIENT_DATA`.
5. S1/S2 pencereleri eksik sezonları kesmiyor (yöntem; yeni sürümde).
6. Defter: sondan silme ve oran tablosu zincir dışı; grup yazımı atomik değil; dış çapa yok.
7. `s0_soy.pkl`/`s0_kalibre.pkl` özet doğrulamasız `pd.read_pickle` ile yükleniyor.
8. Temiz-test denetimi veri ve S0 değişikliğini hâlâ karşılaştırmıyor.
9. EXPLORATORY dört hipotezin parametre/test sayımları kayıtlı değil; gerçek veride birebir tekrar yapılmadı.
10. Pozitif kontrol ölçütü geçmedi: akışın gücü sınırlı.
11. Eşleşmeyen takımlı fikstürler `TAHMIN_YOK` olarak deftere girmiyor (fikstür katmanında eleniyor).
12. Yoğunlaşma (günlük aday sınırı) için sayısal eşik-yakını işareti uygulanmadı.

## K. Tek sonraki adım

Bu görevin iki yerel commit'inin `claude/bahis-tahmin` dalına **push edilmesine açık onay vermeniz** (kapsayıcı geçici;
onay olmadan değişiklikler sizin makinenize ve CI'a ulaşmaz). Onaydan sonra sırası: elle `windows_test` CI işi →
kendi makinenizde onaylı veri güncellemesi → bir sonraki maç gününden önce `gol-olcum-kaydet` (kuru) ve `--uygula`.

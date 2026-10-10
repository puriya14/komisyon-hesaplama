# İleriye dönük ölçüm (A/B/C) — kullanım

Amaç: iki yarıda KG (A), 3,5 Üst (B) ve İY 1,5 Üst (C) için model olasılıklarını **maç oynanmadan önce**, bahis
adayı olsun olmasın, değişmez deftere kaydetmek ve sonuçlandıktan sonra değerlendirmek. Bu bir bahis önerisi veya
getiri iddiası değildir; gerçek para kullanılmaz.

## Protokol

- **Etkin sürüm `ileriye-donuk-olcum-v3`** (S3-GATE-02): veri uygunluğu ortak kontrolden gelir
  ([`VERI_UYGUNLUK.md`](VERI_UYGUNLUK.md), politika `veri-uygunluk-v2`: kesin takım kimliği `takim-eslesme-v2`,
  bağımsız katılımcılarla doğrulanan takvim aralığı, "yerel analiz" istisnası olmadan işlem kapsamlı kaynak hakları).
  Dondurma anı ve gövde SHA-256: [`reports/s3_gate_02/ileriye_donuk_protokol_v3.json`](../reports/s3_gate_02/ileriye_donuk_protokol_v3.json)
  (kodda `PROTOCOL_V3_FROZEN`; ikisinin eşitliği testle denetlenir).
- Önceki sürümler **değiştirilmedi**: `ileriye-donuk-olcum-v2` (S3-GATE-01; 2026-10-10T16:28:32Z, gövde SHA-256
  `56c41f57c2a49610f072f0016e653a33ca70f98d1212fb5effdb6fee7d333063`,
  [`reports/s3_gate_01/ileriye_donuk_protokol_v2.json`](../reports/s3_gate_01/ileriye_donuk_protokol_v2.json)) ve
  `ileriye-donuk-olcum-v1` (2026-10-10T11:52:58Z, gövde SHA-256
  `3946a6e2865f4ea5386156e20cb5ccb7ccd8a4c1520c3dc65fdd4e2a6814fddf`,
  [`reports/kabul_s2_01/ileriye_donuk_protokol_v1.json`](../reports/kabul_s2_01/ileriye_donuk_protokol_v1.json)).
  Sürümlerin kayıtları değerlendirmede ayrı raporlanır ve birleştirilmez
  (`python -m bahis_tahmin gol-olcum-degerlendir --protokol` belgeleri yazdırır). Kod: `bahis_tahmin/goals/forecast_log.py`.
- Hedef karar anı: **maç günü 00:00 Europe/Istanbul**. Kayıt anı (defterin `created_at`'i) bundan önce olmalı; değilse
  olasılık yazılmaz (`PENCERE_KACIRILDI`). Kaçırılan pencere sonradan doldurulmaz.
- Dondurma gününden önceki veya sonucu bilinen maçlar ileriye dönük örnekleme girmez.
- Model değişikliği (yeniden eğitim dahil) yeni bir **kohort**tur; kohortlar birleştirilmez.
- Referans: ligin karar anından önceki son 3 tamamlanmış sezondaki gerçekleşme oranı. ΔLL = model − referans
  (negatif model lehine), maç günü kümeli bootstrap.
- Resmî değerlendirme: kohort × pazar başına en az 300 sonuçlanmış tahmin ve 50 pozitif olay; birincil tarih
  2027-07-01. Eşik karşılanmazsa "yetersiz örneklem" olarak açıklanır, süre uzatılmaz. Ara raporlar yalnızca
  tanımlayıcıdır; sonuca göre durdurma yoktur.
- Ekonomik değerlendirme yalnızca hem geçerlilik anı (`quoted_at`) hem sisteme alınma anı (`fetched_at`) karar
  anından önce olan gerçek oranla yapılır; aksi halde `ROI_UNAVAILABLE`.

## Kayıt türleri (mevcut değişmez defter: `gol_pazarlari.sqlite`)

| Tür | Ne zaman |
|---|---|
| `FORECAST_RECORD` + `TAHMIN` | Uygunluk koşulları sağlandı; olasılık, aralık, referans ve oran bilgisi yazılır (stake 0) |
| `FORECAST_RECORD` + `TAHMIN_YOK` | Aday maç uygun değil; olasılık yazılmaz, neden kodu yazılır |
| `BET_CANDIDATE_RECORD` | Karar motorunun `VALUE_CANDIDATE` dediği, zamanı doğrulanmış gerçek oranlı aday (Maç analizi ekranından kayıt) |
| `KARAR_KAYDI` | Karar motorunun diğer kararları |
| `FORECAST_GECERSIZ_ILAN` | Bir tahmini gerekçeyle geçersiz ilan eden ayrı kayıt (orijinal değişmez; değerlendirme dahil/hariç iki sayım verir) |

Neden kodları (v2/v3): zaman kodları `PENCERE_KACIRILDI`, `MAC_SONUCU_BILINIYOR`, `PROTOKOLDEN_ONCE` ve ortak
uygunluk kontrolünün kodları (birincil neden `reasons[0]`; tamamı `veri_uygunlugu.nedenler`), ör. `DEPODA_EKSIK_MAC`,
`DURUM_DEPODAN_GERIDE`, `KAYNAK_KAPSAMI_YOK`, `TAKIM_ESLESMEDI`, `GEREKLI_ALAN_EKSIK`, `TAKIM_GECMISI_YETERSIZ`,
`OLASILIK_GECERSIZ`; v3'te ayrıca `TAKIM_ESLESMESI_DOGRULANAMADI`, `KAYNAK_DEPO_CELISKISI`,
`KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI`, `KAYNAK_EGITIM_HAKKI_DOGRULANAMADI`, `KAYNAK_MODEL_KULLANIMI_DOGRULANAMADI`,
`MODEL_EGITIM_KOKENI_YOK` (bunlar artık olasılıksız `TAHMIN_YOK` kaydına yol açar). Takım adı kesin olarak eşleşmeyen
(bulunamadı, belirsiz veya yalnızca benzer) fikstür, aday kimlikle (`aday:…`, `kanonik_kimlik: false`) üç pazar için
`TAKIM_ESLESMEDI` kaydı alır. v1'in `VERI_GUNCEL_DEGIL` kuralı (son kayıtlı lig maçından sonra oynanmış maç veya 21 gün)
yalnızca eski kayıtların anlamı için belgede kalır. Kayıtlarda ayrıca `hesaplama_ani`, `bilgi_kesimi` ve
`veri_uygunlugu` (güncellik, tahmin/bahis uygunluğu, nedenler, veri kesimi, durum özeti) alanları vardır.

## Elle günlük akış (otomatik zamanlayıcı yok)

1. Verileri güncelleyin (uygulamada **Veri güncelle** veya `python -m bahis_tahmin update`). Kaynak kullanım
   koşullarının onayı uygulama içinden verilir; onay olmadan güncelleme çalışmaz.
2. Gol modelini gerekiyorsa eğitin (`gol-egit`). Yeni eğitim yeni kohort başlatır.
3. Maç gününden önceki gün (en geç İstanbul saatiyle gece yarısından önce) kuru çalıştırma:
   `python -m bahis_tahmin gol-olcum-kaydet` — her maç için "uygun" veya neden kodu listelenir, hiçbir şey yazılmaz.
4. Yazmak için: `python -m bahis_tahmin gol-olcum-kaydet --uygula`. Aynı (maç, pazar, protokol, kohort) ikinci kez
   yazılmaz; yazma anında saat yeniden denetlenir.
5. Maçlar oynandıktan ve veriler güncellendikten sonra: Gol Pazarları → Sanal takip → **Sonuçlandır** (sonuç ayrı
   olay olarak eklenir; tahmin kaydı değişmez).
6. Değerlendirme (yazma yapmaz): `python -m bahis_tahmin gol-olcum-degerlendir` — kapsam (neden dağılımı), kohort ×
   pazar log-kayıp, Brier, ΔLL ve aralığı, zincir doğrulaması.

## Bilinen sınırlar

- Fikstür kaynağı olmayan liglerde aday maç oluşmaz (openfootball 2026-27'de 22 ligin 8'i için dosya var); tam sezon
  takvimi olmayan liglerde güncellik doğrulanamaz (`KAYNAK_KAPSAMI_YOK`) ve tahmin yazılmaz.
- Takım adı eşleşmeyen fikstür v2'de aday kimlikli `TAHMIN_YOK` kaydı alır (v1'de deftere girmiyordu).
- Başlama saati olmayan fikstürlerde karar anı yine maç günü 00:00 İstanbul'dur.
- Model eğitim verisinin (football-data.co.uk / GitHub yedeği) sonuç kullanımı, model eğitimi ve model kullanımı
  hakları belgeyle doğrulanmadı. v3'te "kişisel analiz" istisnası yoktur: bu veriyle eğitilmiş modelden olasılık
  kaydedilmez (nedenli `TAHMIN_YOK`), gerçek veriyle yeni eğitim de yapılmaz.
- Bu ortamda (10.10.2026) veri 03.09.2026'da bittiği için gerçek fikstürlerin hepsi `VERI_GUNCEL_DEGIL` ya da
  `PENCERE_KACIRILDI` oldu; bu nedenle henüz hiçbir ileriye dönük tahmin kaydı yoktur (bkz. `reports/kabul_s2_01/`).

# İleriye dönük ölçüm (A/B/C) — kullanım

Amaç: iki yarıda KG (A), 3,5 Üst (B) ve İY 1,5 Üst (C) için model olasılıklarını **maç oynanmadan önce**, bahis
adayı olsun olmasın, değişmez deftere kaydetmek ve sonuçlandıktan sonra değerlendirmek. Bu bir bahis önerisi veya
getiri iddiası değildir; gerçek para kullanılmaz.

## Protokol

- Sürüm `ileriye-donuk-olcum-v1`; gerçek sistem saatinde **2026-10-10T11:52:58Z** donduruldu; gövde SHA-256
  `3946a6e2865f4ea5386156e20cb5ccb7ccd8a4c1520c3dc65fdd4e2a6814fddf`. Tam metin:
  [`reports/kabul_s2_01/ileriye_donuk_protokol_v1.json`](../reports/kabul_s2_01/ileriye_donuk_protokol_v1.json)
  (`python -m bahis_tahmin gol-olcum-degerlendir --protokol` aynı belgeyi yazdırır). Kod: `bahis_tahmin/goals/forecast_log.py`.
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

Neden kodları: `PENCERE_KACIRILDI`, `MAC_SONUCU_BILINIYOR`, `PROTOKOLDEN_ONCE`, `MODEL_YOK`,
`LIG_MODEL_KAPSAMI_DISI`, `VERI_GUNCEL_DEGIL`, `TAKIM_GECMISI_YETERSIZ`, `OLASILIK_GECERSIZ`.
`VERI_GUNCEL_DEGIL`: fikstür kaynağı (openfootball) ligde veri deposundaki son maçtan sonra oynanmış maç listeliyorsa
veya bu doğrulanamıyor ve ligin son kayıtlı maçı 21 günden eskiyse.

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

- Fikstür kaynağı olmayan liglerde aday maç oluşmaz (openfootball 2026-27'de 22 ligin 8'i için dosya var).
- Takım adı eşleşmeyen fikstür deftere girmez; sayısı güncelleme uyarısında görünür.
- Başlama saati olmayan fikstürlerde karar anı yine maç günü 00:00 İstanbul'dur.
- Model eğitim verisinin (football-data.co.uk / GitHub yedeği) kullanım hakları belgeyle doğrulanmadı; ölçüm kişisel
  analiz kapsamındadır.
- Bu ortamda (10.10.2026) veri 03.09.2026'da bittiği için gerçek fikstürlerin hepsi `VERI_GUNCEL_DEGIL` ya da
  `PENCERE_KACIRILDI` oldu; bu nedenle henüz hiçbir ileriye dönük tahmin kaydı yoktur (bkz. `reports/kabul_s2_01/`).

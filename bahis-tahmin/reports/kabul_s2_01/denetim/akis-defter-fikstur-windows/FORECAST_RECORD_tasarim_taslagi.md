# FORECAST_RECORD — en küçük tasarım taslağı (mevcut `goals/ledger.py` Ledger'ı yeniden kullanır)

Taslaktır; depoya yazılmadı. Dayanak: 01b7e9f kodu. Kanıtlar `cikti/` altındaki sentetik denemeler.

## 1. Bugün ne kaydediliyor? (temel kod)

| Akış | Ne zaman | Ne yazılır | Kanıt |
|---|---|---|---|
| Arayüz "Gol Pazarları → Maç analizi → Bu kararları sanal takibe kaydet" | Yalnızca kullanıcı tıklayınca, tek maç | O maçın 6 seçimi için 6 `predictions` satırı; aday olsun olmasın (stake yalnızca VALUE_CANDIDATE'te 1) | ui/pages/goals.py:402-408, goals/service.py:43-58 |
| Arayüz "Oranları şimdi geçerli olarak kaydet" | Tıklayınca | `odds` satırları; quoted_at = fetched_at = şimdi | ui/pages/goals.py:386-400 |
| CLI `gol-oran-ice-aktar --uygula` | Komutla | CSV'deki oranlar (quoted_at/fetched_at CSV'den) | cli.py:268-291 |
| Arayüz "Sonuçları veriden güncelle" | Tıklayınca | `outcomes` olayı (WIN/LOSS/VOID/UNKNOWN) | goals/service.py:61-80 |
| CLI tahmin komutları (`gol-tahmin`, `predict`) | — | HİÇBİR ŞEY kaydedilmez (yalnızca ekrana yazar) | cli.py:117-134, 210-230 |
| `ResearchLedger.record_forecast` | — | Hiçbir kullanıcı akışına bağlı değil (yalnızca testler) | grep: tests/test_seq_anomaly.py dışında çağrı yok |

Saklanan alanlar (sentetik kayıttan okundu, `cikti/defter_tazelik_sentetik.json` → `kaydedilen_alanlar`):
`id, created_at, event_id, league, home, away, kickoff, market_key, decision_time, model_version, feature_version,
data_cutoff, p, p_low, odds, decision_status, reasons, ev, ev_safe, stake_units, strategy_version, policy_version`.

Zamanlar: `decision_time` = ekranda kararların hesaplandığı an (`now_utc()`, goals.py:373); `created_at` = tıklama anı
(ledger.py:112). İkisi arasında üst sınır veya başlama saati kontrolü yok.

## 2. Boşluk analizi (istenen FORECAST_RECORD alanlarına karşı)

| İstenen | Bugün | Durum |
|---|---|---|
| maç kimliği | `event_id = lig|tarih|ev|deplasman` (ledger.py:81-83) | VAR; erteleme/ad değişince sonuçlandırma eşleşmez (sentetik: 6 kayıt BEKLEYEN kaldı) |
| pazar | `market_key` | VAR |
| tahmin zamanı | `decision_time` + `created_at` | VAR ama aralarında kural yok |
| o anda bilinen başlama saati | `kickoff` (bilinmiyorsa yalnızca tarih) | VAR; kaynağı (fikstür sağlayıcısı, alındığı an) yok |
| veri kesimi | `data_cutoff` = eğitim verisindeki son maç tarihi (engine.py:138) | VAR; takım bazında son maç ve aradaki boşluk yok |
| model/özellik sürümü | `model_version`, `feature_version` | VAR; artefakt SHA'sı (goal_engine.manifest.json) ve kod sürümü yok |
| olasılık + belirsizlik | `p`, `p_low` | KISMEN: `p_high`, yöntem/çekiliş/tohum yok |
| mevcut oranlar + quoted_at/fetched_at | yalnızca `odds` (sayı) | EKSİK: hangi teklif, sağlayıcı, bahis şirketi, quoted_at, fetched_at kaydedilmez; `odds` tablosu zincir dışında |
| veri kalitesi durumu | `reasons` içine karışık metin | KISMEN: ayrı alan/kod yok; veri tazeliği hiç denetlenmez |
| uygunluk nedeni | `decision_status` + `reasons` | KISMEN: makine okunur neden kodu yok |
| tahmin üretilemeyen maçlar için kayıt | yok: `predict_fixtures` tanımsız ligi sessizce atlar (engine.py:172-174); eşleşmeyen takım fikstürü yalnızca sayıyla uyarılır (store.py:291-296) | YOK |
| sonuçlandırma ayrı olay | `outcomes` tablosu | VAR |
| sürümlü düzeltme | sonuçta `note` zorunlu + `correction_of` (ledger.py:120-138) | KISMEN: tahmin kaydının kendisi için düzeltme/iptal olayı yok |
| ayrı BET_CANDIDATE_RECORD | aynı satırda `decision_status`/`stake_units` | YOK |
| değişmezlik | UPDATE/DELETE tetikleyicileri + özet zinciri | KISMEN: tetikleyici düşürülüp sondan silme `verify_chain`'den geçti (sentetik); iki yazar zinciri çatallayabilir |
| çift kayıt engeli | yok | YOK: aynı kararlar iki kez → 12 satır; aday iki kez → `sanal_bahis` 1 → 2 |
| grup bütünlüğü | satır başına işlem | YOK: 4. satırda hata → 6 satırdan 3'ü kaldı |
| geç kayıt engeli | yok (`ResearchLedger`'da var) | YOK: başlama saatinden ~47 gün sonra 6 kayıt kabul edildi |

## 3. En küçük tasarım (ikinci kayıt sistemi YOK)

Aynı `Ledger` sınıfı ve aynı tablolar (`predictions`, `outcomes`, `odds`, `meta`). Yeni tablo gerekmez; ayrım payload'daki
`record_kind` alanıyla yapılır. `SCHEMA_VERSION` 1 → 2: ek olarak bir kısmi benzersizlik dizini ve `meta` anahtarları.

### 3.1 Kayıt türleri (`predictions.payload.record_kind`)
- `FORECAST`: bir protokol çalıştırmasında, protokol kapsamındaki HER fikstür ve pazar ailesi (A/B/C evet tarafı) için.
  Oran veya aday olmasa da yazılır.
- `NO_FORECAST`: kapsamda olup tahmin üretilemeyen her fikstür için; neden kodlarıyla.
- `BET_CANDIDATE`: yalnızca karar motoru VALUE_CANDIDATE verdiğinde; `forecast_id` ile FORECAST'a bağlanır, stake yalnızca burada.
- `RUN_SUMMARY`: çalıştırma başına bir satır (kapsam sayısı = FORECAST + NO_FORECAST; son özet).
- Eski satırlar (`record_kind` yok) `LEGACY_DECISION` olarak okunur; özet hesabı değişmez.

### 3.2 FORECAST alanları
`record_kind, schema_version=2, run_id, protocol_id, protocol_sha256, protocol_frozen_at (UTC)`,
`event_id, league, home, away, fixture_source, fixture_fetched_at, raw_home, raw_away, team_mapping_method`,
`kickoff_utc (nullable), kickoff_source, match_date_local (Europe/Istanbul), target_decision_time (UTC)`,
`data_cutoff, data_sha256, data_fetched_at (tz'li), home_last_match_date, away_last_match_date, staleness_days`,
`model_version, feature_version, variant, artifact_sha256, trained_at (UTC), code_version`,
`market_key, p, p_low, p_high, interval_method, interval_draws, interval_seed, base_rate, model_validated`,
`odds_snapshot: [{provider, bookmaker, selection, decimal_odds, quoted_at, fetched_at}]` (yalnızca fetched_at ≤ created_at),
`data_quality: {status: OK|WARN|BLOCKED, codes: [...], notes: [...]}`,
`eligibility: {status: ELIGIBLE|INELIGIBLE, codes: [DATA_STALE, TEAM_UNMATCHED, KICKOFF_UNKNOWN, AFTER_DECISION_TIME, LEAGUE_NOT_MODELLED, MODEL_NOT_VALIDATED, ODDS_UNAVAILABLE]}`.
`created_at` ve `id`'yi Ledger koyar (mevcut davranış).

`NO_FORECAST`: `run_id, protocol_id, raw fikstür kimliği (lig, tarih, ham adlar, kaynak), target_decision_time, reason_codes`.
`BET_CANDIDATE`: `forecast_id, decision_status, reasons, policy_version, quote {provider, bookmaker, quoted_at, fetched_at, decimal_odds}, ev, ev_safe, stake_units, strategy_version`.

### 3.3 Olaylar (`outcomes` tablosu, mevcut)
- `SETTLEMENT` (mevcut `record_outcome`): `prediction_id` = FORECAST id (aday sonucu FORECAST'tan türetilir); `source` +
  `source_data_sha256` + `source_fetched_at` eklenir.
- `CORRECTION`: mevcut kural (önceki sonucu değiştiren kayıt `note` ister, `correction_of` taşır).
- `VOID_FORECAST`: yanlış eşleme vb. için tahmini değerlendirmeden çıkarır; tahmin satırı silinmez/değişmez. Yerine yazılan
  yeni FORECAST `supersedes` taşır; `created_at ≥ target_decision_time` ise değerlendirmeye girmez.
- Ertelenen maç: N gün (ör. 7) eşleşme olmazsa `VOID` (gerekçe: "maç oynanmadı/ertelendi") — bugün sonsuza dek BEKLEYEN kalır.

### 3.4 Değişmezler (yazma anında zorunlu; ihlal → ValueError)
1. `created_at < target_decision_time ≤ kickoff_utc` (kickoff biliniyorsa); zaman dilimsiz zaman reddedilir. (ResearchLedger
   kuralları — research_ledger.py:160-175 — tek doğrulayıcıya taşınıp iki akışta da kullanılır.)
2. `protocol_frozen_at < created_at` ve `protocol_sha256` deney kaydındaki (reports/experiments.jsonl veya
   dizi_arastirma/deneyler.jsonl) dondurulmuş protokolle aynı; farklıysa satır yazılmaz.
3. Yalnızca ekleme: mevcut tetikleyiciler + her çalıştırma sonunda `(run_id, satır sayısı, son hash)` deney kaydına
   eklenir (dış çapa) → sondan silme yakalanır.
4. Benzersizlik: `(protocol_id, event_id, market_key, record_kind='FORECAST')` tektir (Python kontrolü + kısmi dizin
   `json_extract` ile). Çift tıklama aday sayısını ikiye katlayamaz.
5. Oran zamanı: anlık görüntüdeki her teklif için `fetched_at ≤ created_at` ve `quoted_at ≤ target_decision_time`
   (`latest_quote` bugün yalnızca quoted_at'e bakıyor: ledger.py:193-203).
6. Grup bütünlüğü: bir çalıştırmanın tüm satırları tek SQLite işleminde (`BEGIN IMMEDIATE` … `COMMIT`); `_last_hash`
   okuması aynı işlemin içinde (iki yazar çatallanması önlenir).
7. Kapsam tamlığı: kapsamdaki her fikstür × pazar ailesi için tam bir FORECAST veya NO_FORECAST; RUN_SUMMARY sayıları tutar.
8. Veri tazeliği: `staleness_days` eşiği (ör. sezon içinde > 10 gün) aşılırsa `data_quality=BLOCKED`, `eligibility=INELIGIBLE(DATA_STALE)`;
   FORECAST yine yazılır (olasılık + neden), BET_CANDIDATE yazılmaz.

## 4. Gerekli testler (sentetik veri, geçici klasör)
1. Oran yokken FORECAST yazılır (stake 0, `odds_snapshot=[]`, ODDS_UNAVAILABLE).
2. NO_FORECAST: tanımsız lig, eşleşmeyen takım (NEC benzeri), başlamış maç, bayat veri → doğru neden kodu; kapsam = FORECAST + NO_FORECAST.
3. Geç kayıt: saat enjeksiyonuyla `created_at ≥ target_decision_time` ve `target_decision_time > kickoff` reddedilir; tz'siz zaman reddedilir.
4. Çift kayıt reddedilir; `summary()` aynı adayı bir kez sayar.
5. Toplu yazımda yapay hata → sıfır yeni satır.
6. `fetched_at > created_at` olan teklif anlık görüntüye ve karara girmez.
7. Sonuçlandırma ayrı olay; düzeltme gerekçe ister; ertelenen maç N gün sonra VOID; tahmin satırı değişmez.
8. Dış çapa: tetikleyici düşürülüp son satır silinirse doğrulama BOZUK der.
9. İki bağlantı aynı anda yazar → zincir geçerli kalır.
10. Protokol özeti farklı → yazım reddedilir; donma zamanı ilk tahminden önce olmalı.
11. Bayat veri (fikstür, takımın son kayıtlı maçından 45 gün sonra) → BLOCKED/DATA_STALE.
12. Şema v1 dosyası v2 kodla açılır, `verify_chain` ve eski özet değişmez; v1 kod v2 dosyayı okuyabilir (geri alma güvenliği).

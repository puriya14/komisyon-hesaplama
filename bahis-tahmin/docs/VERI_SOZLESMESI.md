# Veri sözleşmesi — gol pazarları katmanı

Bu belge, gol pazarları motorunun okuduğu ve yazdığı verilerin biçimini, kurallarını ve
zaman (point-in-time) güvencelerini tanımlar. Kod karşılıkları parantez içinde verilmiştir.

## 1. Katmanlar

| Katman | İçerik | Nerede | Not |
|---|---|---|---|
| Sonuç | maç sonu skoru (`fthg`, `ftag`), ilk yarı skoru (`hthg`, `htag`), tarih, saat, takımlar | `matches.pkl` (uygulama veri klasörü) | Kaynağı `source` sütununda |
| Zenginleştirilmiş | isabetli şut (`h_sot`, `a_sot`) | aynı tablo | Gol modeli şut verisini kullanmaz; kapsam matrisinde ayrı sayılır |
| Oran | 1X2 ve 2,5 Alt/Üst (football-data); A/B/C için yalnızca kullanıcının girdiği gerçek oranlar | maç tablosu / `gol_pazarlari.sqlite` → `odds` | 3,5 Üst oranı 2,5'ten, iki yarıda KG oranı maç sonu KG'den TÜRETİLMEZ |

## 2. Maç kaydı (sonuç katmanı)

| Alan | Tür | Kural |
|---|---|---|
| `league` | metin | uygulama lig kodu (ör. `E0`, `T1`) |
| `season` | metin | `YYYY/YY`; kaynakta yanlışsa tarih boşluklarından yeniden atanır (`assign_seasons`) |
| `date` | tarih | maç günü (yerel takvim günü) |
| `time` | metin `SS:DD` veya boş | football-data saatleri İngiltere saatidir; diğer kaynaklarda ülke saat dilimi (`timeutil.kickoff_utc`) |
| `home`, `away` | metin | kaynak adı; fikstür eşleştirmesi bulanık ad eşleştirmesiyle |
| `fthg`, `ftag` | tam sayı ≥ 0 | **normal süre** sonu (uzatmalar ve penaltılar hariç) |
| `hthg`, `htag` | tam sayı ≥ 0 veya boş | ilk yarı sonu (ilk yarı uzatma dakikaları dahil) |
| `source` | metin | veri kaynağı (provenans) |

### Doğrulama ve karantina (`goals/markets.py: validate`, `frame_issues`; `goals/coverage.py: quarantine`)

- `GECERSIZ_DEGER:<alan>` — negatif, kesirli veya sayı olmayan gol değeri.
- `ILK_YARI_MAC_SONUNU_ASIYOR` — `hthg > fthg` veya `htag > ftag`.
- `UZATMA_SKORU_NORMAL_SUREDEN_KUCUK` — uzatmalı skor normal süreden küçük.

Sorunlu kayıt **silinmez veya düzeltilmez**; karantinaya alınır, hiçbir pazar etiketlenmez (UNKNOWN)
ve model güncellemelerinde kullanılmaz. İlk yarı skoru eksik maç, ilk yarı gerektiren pazarlarda
UNKNOWN olur (FALSE değil).

## 3. Pazar tanımları (kural sürümü `std-v1`, `goals/markets.py`)

| Kod | Ad | Koşul (Evet/Üst tarafı) | Gerekli alanlar |
|---|---|---|---|
| `BTTS_BOTH_HALVES_YES` (A) | İki yarıda da karşılıklı gol – Evet | `hthg≥1 ∧ htag≥1 ∧ (fthg−hthg)≥1 ∧ (ftag−htag)≥1` | İY + MS |
| `FT_OVER_3_5` (B) | Maç sonu 3,5 Üst | `fthg+ftag ≥ 4` | MS |
| `FH_OVER_1_5` (C) | İlk yarı 1,5 Üst | `hthg+htag ≥ 2` | İY |

Her pazarın tümleyeni (`_NO`, `_UNDER_`) ayrı kayıttır. Araştırma pazarları (maç sonu KG, İY KG,
2. yarı 1,5, 2,5 ve 4,5 Alt/Üst) tanımlıdır ancak öneri motoruna kapalıdır.

**Mantıksal ilişki:** A gerçekleşirse ilk yarıda en az 2 gol (C) ve maçta en az 4 gol (B) vardır:
A ⊆ B ∩ C. Model bu ilişkiyi tek ortak dağılımdan türettiği için yapısal olarak korur.

### Etiket ve bahis sonucu ayrımı

- **Etiket** (`label`): `TRUE / FALSE / UNKNOWN` — maç bitmemişse, kayıt çelişkiliyse veya gerekli alan
  eksikse UNKNOWN.
- **Bahis sonucu** (`settle`): `WIN / LOSS / VOID / PENDING / UNKNOWN`
  - başlamamış / oynanıyor → PENDING
  - ertelendi / iptal / yarıda kaldı / hükmen → VOID
  - bitti → etikete göre WIN/LOSS; etiket bilinmiyorsa UNKNOWN (otomatik kayıp yazılmaz)
  - bilinmeyen kural sürümü → hata (sessizce uygulanmaz)

## 4. Oran kaydı (`goals/value.py: OddsQuote`)

| Alan | Kural |
|---|---|
| `event_id` | `lig|YYYY-AA-GG|ev|deplasman` (`goals/ledger.py: event_id`) |
| `market_key`, `period`, `line`, `selection` | pazar tanımıyla birebir uyumlu olmalı (aksi halde `DONEM_UYUSMAZ`, `CIZGI_UYUSMAZ`, `SECIM_UYUSMAZ`) |
| `provider`, `bookmaker` | zorunlu; marjsız olasılık yalnızca iki taraf aynı sağlayıcı/bahis şirketi ve ≤10 dk farkla ise |
| `decimal_odds` | > 1,0 |
| `quoted_at`, `fetched_at` | **zaman dilimi zorunlu** (`ZAMAN_DILIMI_YOK`), UTC olarak saklanır |
| `status` | `OPEN` dışındaki kayıtlar kullanılmaz |
| `settlement_rule_version` | `std-v1` değilse karar `SETTLEMENT_AMBIGUOUS` |

CSV içe aktarma (`gol-oran-ice-aktar`): en fazla 5 MB, sütun şeması zorunlu, hatalı satırlar karantina
listesine düşer, aynı kayıt ikinci kez eklenmez. Varsayılan kuru çalıştırmadır; yazma yalnızca `--uygula` ile.

## 5. Zaman güvenceleri

- **Özellikler:** bir maçın özellikleri yalnızca o maçın **gününden önceki** günlerde oynanmış maçlardan
  hesaplanır; aynı gün oynanan diğer maçlar dahil edilmez (ihtiyatlı aynı gün kuralı). Takım güçleri
  zaman ağırlıklı yeniden kestirimle güncellenir. Test: `tests/test_goal_engine.py::test_goal_features_do_not_leak_future_or_same_day`.
- **Geçmiş veride yayımlanma zamanı:** football-data dosyaları sonradan derlenmiştir; o anda yayımlanmış
  olduğu doğrulanamaz. Kapsam matrisinde `zaman_dogrulama` alanı bunu belirtir.
- **Karar anı:** her karar `decision_time` (UTC) taşır. Karar anından **sonra** girilmiş oran kullanılamaz;
  60 dakikadan eski oran `STALE_ODDS`; başlama saatinden sonra alınmış oran veya maç başladıktan sonra
  istenen karar reddedilir; başlama saati bilinmiyorsa maç günü (İstanbul) ve sonrasında karar üretilmez.
- **Gösterim:** kullanıcıya tüm saatler Europe/Istanbul olarak gösterilir.

## 6. Sanal takip veritabanı (`gol_pazarlari.sqlite`, `goals/ledger.py`)

- Uygulama veri klasöründe, **ilk sanal kayıtta** oluşturulan yeni bir dosyadır; mevcut bir veritabanının
  geçişi (migration) değildir.
- Tablolar: `predictions`, `outcomes`, `odds`, `meta`. `predictions` ve `outcomes` hash zinciriyle bağlıdır.
- Tetikleyiciler `predictions`, `outcomes` ve `odds` tablolarında UPDATE/DELETE işlemlerini engeller.
- Sonuç düzeltmesi yeni bir `outcomes` kaydı olarak eklenir ve gerekçe (`note`) zorunludur.
- Özet: VOID/PENDING/UNKNOWN kayıtlar getiri paydasına girmez; geçmiş testten ayrı gösterilir.

## 7. Model dosyası (`models/artifacts.py`)

`goal_engine.joblib` + `goal_engine.manifest.json`: tür (`goal-engine`), sürüm, oluşturma zamanı, SHA-256,
bağımlılık sürümleri, model/özellik sürümü, varyant, eğitim zamanı, veri kesimi, veri manifesti (maç sayısı,
ligler, tarih aralığı, kaynaklar, veri SHA-256), özellik şeması, doğrulama kuralı ve sonuçları.
Manifesti olmayan, özeti tutmayan, türü/sürümü uyuşmayan veya scikit-learn/numpy ana-alt sürümü değişmiş
model dosyası **yüklenmez**; kullanıcıdan yeniden eğitim istenir.

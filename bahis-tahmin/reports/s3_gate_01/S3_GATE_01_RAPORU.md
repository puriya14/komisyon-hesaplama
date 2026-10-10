# S3-GATE-01 — Ana tahmin ve karar akışlarında ortak veri uygunluk kontrolü

Tarih: 2026-10-10. Başlangıç: `claude/bahis-tahmin` @ `3c80b6244f226df4d03aa286d8335482a48df683`.
Politika: `veri-uygunluk-v1` ([`docs/VERI_UYGUNLUK.md`](../../docs/VERI_UYGUNLUK.md)). Protokol: `ileriye-donuk-olcum-v2`
([`ileriye_donuk_protokol_v2.json`](ileriye_donuk_protokol_v2.json)); `ileriye-donuk-olcum-v1` değiştirilmedi.

Bu çalışma bir model geliştirme, örüntü araması veya getiri iddiası değildir. Testler yalnızca açıkça sentetik veriyle
ve geçici dizinlerde çalışır; sentetik başarı gerçek maç başarısı sayılmaz. **Bu ortamda güncel gerçek veri yoktur.**

## Bulunan geçiş yolları (değişiklikten önce)

| Kullanıcı akışı | Atlanan kontrol |
|---|---|
| Gol ekranı taraması, maç analizi, elle maç seçimi | Tazelik kontrolü yoktu; eğitimde donmuş model durumu kullanılıyordu; yalnızca metin notları |
| A/B/C kararları ve tamamlayıcı Alt/Hayır (`decide`, `decisions_for`) | Veri güncelliği hiç denetlenmiyordu; bağlamsız çağrı `VALUE_CANDIDATE` üretebiliyordu |
| Sanal takip kaydı (`record_decisions`) | NaN olasılık yazılabiliyordu; stake yalnızca karar durumuna bağlıydı |
| CLI `gol-tahmin`, `predict`, `en-olasi` | Güncellik denetimi yoktu; 1X2 "DEĞER" ve Kelly stake'i her koşulda |
| 1X2 tahmin listesi, en olası, gösterge paneli, maç ayrıntısı/analizi | Güncellik denetimi yoktu |
| İleriye dönük ölçüm (v1) | Yalnızca lig son tarihi sonrası eksik maç sayısı / 21 gün; takım içi ara eksikler, model durumu ↔ depo farkı ve boş/kısmi kaynak yakalanmıyordu |
| Fikstür katmanı | Takım adı eşleşmeyen fikstürler sessizce düşüyordu; modelde olmayan lig sessizce atlanıyordu |
| Kaynak hakları | Kayıtta metin olarak vardı; karar açısından kullanılmıyordu |

## Sonuç

- Tek merkezi kontrol (`bahis_tahmin/eligibility.py`); bütün kullanıcı yolları aynı sonucu kullanır (tablo:
  `docs/VERI_UYGUNLUK.md` → "Kullanıldığı yollar").
- `VERIFIED_CURRENT` yalnızca kanıtla: kaynak tam sezon takvimi ↔ veri deposu ↔ tahminde kullanılan model durumu,
  takım düzeyinde ve bilgi kesimiyle sınırlı. `UNKNOWN` ve bağlamsız çağrı uygun değildir.
- Tahmin uygunluğu (`forecast_ok`) ile bahis uygunluğu (`bet_ok`) ayrıdır; model doğrulaması, oran ve diğer karar
  kontrolleri değişmeden çalışır. Karar motoruna `DATA_NOT_ELIGIBLE` durumu eklendi; eşikler değişmedi.
- Belgelenmemiş sonuç kullanımı / model eğitimi hakkı bahis adayını engeller (politika kararı, kullanıcı onayına açık).
- Modelin olasılık matematiği değişmedi (altın regresyon testi aynı tolerans ve altın değerlerle geçti).
- Eğitimde her lig durumunun kurulduğu maç kümesinin kimliği (`row_digest`) modele yazılır; köken bilgisi olmayan eski
  model dosyalarıyla tahmin gösterilmez (`DURUM_KOKENI_YOK`; yeniden eğitim gerekir, dosya değiştirilmez).

## Çekişmeli inceleme

Değişiklikler 7 bağımsız ajanla (atlatma yolu, mantık, uyumluluk + boyut başına çekişmeli doğrulama + tamamlayıcı
eleştirmen) incelendi. Doğrulanan bulgular düzeltildi ve her biri için test eklendi; başlıcaları: gün değişince önceki
günün sonucunun gösterimde yeniden kullanılması; engelli tahminde güvenli olasılık/gereken oranın sızması; önceden
hesaplanmış kararın kayıt anında yeniden doğrulanmadan aday kaydı olması; yalnızca eşleşmeyen fikstür varken 1X2
listesinin boş kalması; durum ↔ depo kontrolünün ara dönemi görmemesi (→ satır özeti); lig düzeyi eşiğin sezonlar
arası seyreltilmesi (→ sezon başına); önceki sezonun takım düzeyinde iç tutarlılıkla kapsanması (→ sezon düzeyinde);
karantinadaki kaydın "var" sayılması; önbellek anahtarı; karar anından sonra değerlendirilen sonucun kabulü; tarih
toleransının sınırda uygulanmaması; araştırma aracının yeni API ile çökmesi; değerlendirme JSON'unda NaN (önceden
vardı). Düzeltmeler ikinci bir doğrulama turundan (2 ajan) geçti; bu tur ek olarak şunları buldu ve düzeltildi:
fikstürsüz gün değişiminde gol taramasında sonsuz yeniden değerlendirme; model/veri değişince maç analizi panelinin
eski tahminle kayıt yazabilmesi; model yokken kayıt düğmesinde istisna; gün değişiminin yalnızca yeniden çizimde
denetlenmesi (→ dakikalık denetim ve sayfa geçişi); split/play-off'lu liglerde depo-içi sezon kanıtının eksik sezonu
tam sayması (→ yalnızca kesin çift devreli sezon); satır özetinin skor değişikliğini görmemesi; kaynak takvimi
yokken karantinanın görülmemesi; küçük örneklemde tek maçın bütün ligi engellemesi. İki turda seçilmiş 13 düzeltme
geri alınarak (mutasyon) ilgili testlerin düştüğü doğrulandı.

## Test sonucu

Linux (Python 3.13), çalışma ağacının yalnızca izlenen/izlenebilir dosyalarından oluşan temiz kopyada (yerelde tutulan
ham denetim dosyaları yok): `QT_QPA_PLATFORM=offscreen python -m pytest -q` → **311 geçti, 1 atlandı** (ağ testi).
Başlangıç (3c80b62): 266 geçti, 1 atlandı. Altın regresyon değerleri ve sayısal tolerans değiştirilmedi. Windows'ta
çalıştırılmadı (**NOT_RUN**).

## Zorunlu senaryoların test karşılıkları

| # | Senaryo | Test |
|---|---|---|
| 1 | Bilinen eksik tamamlanmış maç → hiçbir yolda VALUE_CANDIDATE yok | `test_eligibility.py::test_t01_*` (karar + tamamlayıcılar, kayıt, ölçüm kaydı, CLI `gol-tahmin`/`predict`/`en-olasi`/`gol-olcum-kaydet`) + `test_ui.py::test_goals_page` (ana ekran, kayıt anı) |
| 2 | Ligde yeni kayıt var, takımın eski maçı eksik | `test_t02_*`, `test_quarantined_record_is_not_counted_as_present`, `test_league_share_*` |
| 3 | Kapsam doğrulanamıyor → UNKNOWN | `test_t03_*` |
| 4 | Kaynak boş/kısmi → "eksik maç yok" değil | `test_t04_*` |
| 5 | Doğrulanmış sezon arası → yanlış KNOWN_STALE yok | `test_t05_*`, `test_previous_season_store_evidence_must_be_complete_for_the_whole_league` |
| 6 | Ertelenen/iptal/oynanmamış maç eksik sayılmaz | `test_t06_*` |
| 7 | Depo güncel, kullanılan durum eski | `test_t07_*`, `test_state_built_from_different_rows_is_caught` |
| 8 | Eski eğitim tarihi tek başına engel değil | `test_t08_*` |
| 9 | Gelecek sonuç geçmiş as-of sonucunu değiştirmez | `test_t09_*` |
| 10 | Aynı gün, yayın saati bilinmeyen sonuç | `test_t10_*`, `test_pair_tolerance_applies_at_the_cutoff_boundary`, `test_eligibility_evaluated_after_decision_time_is_rejected` |
| 11 | Gerekli alan: pazar ve gerçek model bağımlılığı | `test_t11_*`, `test_team_history_rule_is_enforced` |
| 12 | Eşleşmeyen takım → nedenli aday sonuç | `test_t12_*`, `test_match_paths_keep_unmatched_and_unmodelled_fixtures`, `test_ui.py::test_unmatched_only_fixtures_are_listed_with_reasons`, `test_store.py` (güncelle → kaydet → yükle), `test_forecast_log.py::test_unmatched_fixtures_get_candidate_id_records` |
| 13 | Veri uygun, oran yok | `test_t13_*` |
| 14 | Veri uygun, model doğrulanmamış | `test_t14_*`, `test_recorded_candidate_is_revalidated_at_record_time` |
| 15 | Bağlamsız karar servisi | `test_t15_*`, `test_goal_value.py::test_decision_without_eligibility_is_never_a_candidate` |
| 16 | Kaynak hakkı bilinmiyor; onay/bayrak doğrulamaz | `test_t16_*`, `test_unverified_rights_block_every_bet_path_but_keep_forecast` |
| 17 | Geçerli sentetik uçtan uca | `test_t17_*`, `test_ui.py::test_goals_page` |
| 18 | Geçersiz olasılık kamuya açık JSON/CSV'ye girmez | `test_t18_*` |
| 19 | A ⇒ B, C ilişkisi | `test_t19_*`, `test_goal_engine.py` |
| 20 | Mevcut kayıtlar okunur ve değişmez | `test_t20_*`, `test_forecast_log.py::test_protocol_v2_is_frozen_separately_and_v1_is_unchanged` |
| 21 | Önbellek geçersizleşmesi | `test_t21_*` (bağlam ve arayüz denetleyicisi), `test_cache_key_respects_source_availability_within_the_day`, `test_day_change_never_reuses_previous_days_result` |
| 22 | Temiz kod dışa aktarımı | `test_t22_*` + `git archive` dışa aktarımında tam paket |

## Gerçek veri durumu

Bu ortamda güncel gerçek veri yoktur. S2-KABUL-01'den kalan yerel (yayımlanmayan) eski kopya üzerinde kapı salt-okunur
çalıştırıldı: kaynak takvimi olan 8 ligdeki 160 yaklaşan maçın tamamı `KNOWN_STALE` (`DEPODA_EKSIK_MAC`; depo
03.09.2026'da bitiyor; eski model dosyası için ayrıca `DURUM_KOKENI_YOK`); tahmin ve bahis adayı üretilmedi. Diğer 14 ligde tam takvim kaynağı olmadığından güncellik
doğrulanamaz. Maç satırları bu rapora alınmadı.

## Açık kalanlar

- Windows: bu ortamda Windows yok; Windows testleri **NOT_RUN** (Linux testi Windows doğrulaması sayılmaz).
- Veri hakları: football-data.co.uk / GitHub yedeği için sonuç kullanımı ve model eğitimi hakkı belgelenmedi.
- Defter bütünlüğü: sondan kayıt silme tespiti, dış bütünlük çapası, oran tablosunun zincire bağlanması ve grup
  yazımının atomikliği bu görevde çözülmedi; defter "değiştirilemez" olarak tanıtılmamalıdır.
- Eski public geçmiş: 01b7e9f'deki örnek maç satırları (EXISTING_PUBLIC_EXPOSURE_UNRESOLVED) ayrı açık olarak kalır.
- Takım adı eşleyicisi (`data/teams.py`) tek harfli ad parçalarında önek kuralıyla yanlış eşleşme üretebilir
  (sentetik örnek: "Foo FC" → "Takim F"); bu görevde değiştirilmedi.
- Kaynak kapsamı: tam sezon takvimi yalnızca openfootball'un sunduğu liglerde; önceki sezon dosyası önbelleğe
  alınmıyor (önceki sezonun kapsamı depodaki sezon tamlığından gelir).
- S1/S2 araştırma pencerelerindeki süreklilik sorunları ve araştırma gücü bu görevde yeniden ele alınmadı.

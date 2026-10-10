# Dizi araştırması — sonuçlar (ilk resmi çalıştırma)

> **Düzeltme notu (S2-KABUL-01, 10.10.2026).** Bu belgenin gövdesi sürüm 1.0 (`01b7e9f`) olarak değiştirilmeden
> bırakıldı. Sonradan yapılan kanıt denetiminde bazı ifadeler daraltıldı veya düzeltildi (ör. ΔLL özeti, piyasa
> kontrolü yorumu, oranların "kapanış" niteliği, anomali sayılarının havuzları, PSV veri boşlukları, S0p tanım
> değişikliğinin zamanı, geri alma önerisi). Okumadan önce
> [`DIZI_ARASTIRMA_DUZELTMELER.md`](DIZI_ARASTIRMA_DUZELTMELER.md) kaydına bakın.

Sözleşme `dizi-sozlesme-v2` · çalıştırma 10.10.2026 10:08–10:45 UTC (37,5 dk, 3 işçi) · kod `398b60b` (temiz çalışma
ağacı) · ayrıntılı çıktı: [`reports/dizi_sonuclar.json`](../reports/dizi_sonuclar.json), başarısızlar dahil bütün
hipotezler: [`reports/dizi_f1_hipotezler.csv`](../reports/dizi_f1_hipotezler.csv), aile kayıtları:
[`reports/experiments.jsonl`](../reports/experiments.jsonl).

> **Kısa sonuç.** Ön-kayıtlı 800 ham (780 tekil) koşul hipotezinden 8'i keşif döneminde aile bazlı hata kontrolünü
> geçti; seçilen 4 adayın yönü parametre ve test dönemlerinde de tekrar etti. Ancak dördü de **piyasa kontrolünde
> (S0p) kayboldu** ve temel modele eklenen gösterge katsayısının log-kayıp katkısı ihmal edilebilir düzeyde kaldı
> (yaklaşık −0,00005; üçünde güven aralığı 0'ı içeriyor). Tekrar eden ilişki "yakın formu iyi olan takımı temel gol
> modeli biraz küçümsüyor" türündendir ve bahis piyasası bunu zaten fiyatlıyor. **İlk yarıyı geride kapatıp kazanma
> (İY/MS 2/1 tipi) ve önde kapatıp kaybetme hedeflerinde hiçbir koşul anlamlı değil; olay sonrası (Sorgu 2) ve olaylar
> arası süre (tehlike modeli) ek bilgi sağlamadı.** Örneklem dışında desteklenen (`OUT_OF_SAMPLE_SUPPORTED`) örüntü
> yoktur; sanal takibe alınacak aday da yoktur.

Bir ilişkinin bulunması nedensellik veya manipülasyon kanıtı değildir; bulunamaması da manipülasyon olmadığını
kanıtlamaz. Hiçbir kulüp, oyuncu veya hakem için etiket ya da olasılık üretilmedi.

## Manifest

| Alan | Değer |
|---|---|
| Veri | 184.378 lig maçı, 22 lig, 28.07.2000–03.09.2026; içerik SHA-256 `6ca929a2…` |
| Sözleşme / parametre / eşleme özeti | `4599ddb2…` / `fc12e491…` / `69f7a695…` (üçü de ön-kayıtla aynı) |
| Uygulama kararları | `a85fa19e…` (`398b60b`'de, ilk sonuçtan önce kayıtlı) |
| `sequences` kod özeti | `8ca41041…` |
| Değerlendirme satırları (ikiz-simetrik) | keşif 87.854 · parametre 85.944 · test 92.216 |
| Referans süreç / plasebo / bootstrap | R = 1000 · 20 tohum × 200 · 1000; tohum 20261010 |
| Test dönemi temiz mi | F1, F2, F4, F7: evet. F3, F5, F6: hayır — geliştirme sırasında bir alt ajan bu aileleri gerçek veride hesapladı (resmi çalıştırmadan önce beyan edildi); bu ailelerde statü en fazla `EXPLORATORY` olabilir |

## F7 — plasebo negatif kontrol (önce çalıştırıldı)

Her satırın dizi atomları aynı lig-sezondan, benzer güçte ve daha önceki tarihli başka bir takımın atomlarıyla
değiştirildi; gerçek sonuçlar ve gerçek S0 ile tam arama + Westfall–Young. **20 tohumun hiçbirinde keşif yok**
(sınır: en fazla 1; en küçük düzeltilmiş p 0,17). Referans süreç güvenilir kabul edildi.

## F1 — Sorgu 1 (maç öncesi koşul araması)

Kalibrasyon kapısı geçti (8 hedef × taraf hücresinin hepsinde S0 O/E %95 aralığı 1'i içeriyor). 780 tekil hipotezin
430'u asgari desteği (n ≥ 500, beklenen ≥ 25) sağladı. İlk yarı/maç sonu geçiş hedeflerinde en büyük |z| 2,6
(referans süreçte rastgele en büyük |z|'nin medyanı 3,1) — **anlamlı koşul yok**.

| Hipotez (hedef \| koşul) | Keşif O/E [%95] | FWER düz. p | Statü |
|---|---|---|---|
| MAGLUBIYET \| SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU | 0,884 [0,842; 0,926] | 0,002 | NO_ADDED_VALUE |
| MAGLUBIYET \| SON5_GALIBIYET_EN_AZ_4 | 0,917 [0,884; 0,950] | 0,002 | EXPLORATORY |
| MAGLUBIYET \| SON5_GALIBIYET_EN_AZ_4 & EV_SAHIBI | 0,855 [0,800; 0,911] | 0,002 | EXPLORATORY |
| MAGLUBIYET \| SON5_IY_ONDE_EN_AZ_3 & SON5_GALIBIYET_EN_AZ_4 | 0,891 [0,847; 0,934] | 0,003 | EXPLORATORY |
| MAGLUBIYET \| SON5_GALIBIYET_EN_AZ_4 & FORM_BEKLENTI_USTU | 0,906 [0,863; 0,948] | 0,016 | EXPLORATORY |
| GALIBIYET \| SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU | 1,061 [1,033; 1,089] | 0,021 | NO_ADDED_VALUE |
| MAGLUBIYET \| SON5_GALIBIYET_EN_AZ_4 & FAVORI | 0,788 [0,690; 0,887] | 0,022 | NO_ADDED_VALUE |
| GALIBIYET \| RAKIP_SON5_IY_ONDE_EN_AZ_3 | 0,954 [0,932; 0,975] | 0,023 | NO_ADDED_VALUE |

`EXPLORATORY` dördü aday kuralı nedeniyle (her hedefte aynı atomu paylaşanlardan yalnızca biri) örneklem dışında
sınanmadı; hepsi aynı "iyi form" ailesindendir. Aday dördünün örneklem dışı seyri:

| Aday | Parametre O/E (Holm) | Test O/E (Holm) | Test ΔLL (S0+gösterge − S0+sabit) | Piyasa (S0p) kontrolünde O/E | Neden elendi |
|---|---|---|---|---|---|
| MAGLUBIYET \| SON5_GALIBIYET_EN_AZ_4 & FAVORI | 0,867 (geçti) | 0,879 (geçti) | −0,00004 [−0,00014; +0,00006] | 0,93 → 0,98 (aralık 1'i içeriyor) | ΔLL anlamsız; piyasada kayboldu |
| MAGLUBIYET \| SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU | 0,911 (geçti) | 0,927 (geçti) | −0,00006 [−0,00018; +0,00005] | 0,97 → 0,99 | ΔLL anlamsız; piyasada kayboldu |
| GALIBIYET \| SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU | 1,037 (geçti) | 1,037 (geçti) | −0,00005 [−0,00014; +0,00003] | 0,99 → 0,99 | ΔLL anlamsız; en etkili %1 çıkarılınca aralık 1'i içeriyor; piyasada kayboldu |
| GALIBIYET \| RAKIP_SON5_IY_ONDE_EN_AZ_3 | 0,962 (geçti) | 0,956 (geçti) | −0,00010 [−0,00020; −0,00001] | 0,99 → 0,99 | parametre döneminde 7b/2 geçmedi; piyasada kayboldu |

Okuma: "son 5 maçta en az 4 galibiyet + favori" koşulunda takım test döneminde %11,1 kaybetti; S0'ın beklediği oran
yaklaşık %12,7 idi (3.110 maç; 346 mağlubiyet, 2.764 mağlup olmama). Fark tutarlı ama küçük ve piyasa oranları zaten
bu farkı içeriyor.

## F2 — Sorgu 2 (olay sonrası)

| Olay → hedef | n (çakışmayan) | O/E [%95] | FWER düz. p |
|---|---|---|---|
| İY geride→MS galip → sonraki maçta galibiyet | 1.534 | 0,999 [0,940; 1,058] | 0,998 |
| İY geride→MS galip → sonraki 3 maçta yine aynı olay | 1.534 | 0,993 [0,811; 1,174] | 0,998 |
| İY geride→MS galip → sonraki 5 maçta puan | 1.534 | 1,014 [0,996; 1,032] | 0,549 |
| İY önde→MS mağlup → sonraki maçta galibiyet | 1.498 | 1,016 [0,955; 1,077] | 0,974 |
| İY önde→MS mağlup → sonraki 3 maçta yine aynı olay | 1.498 | 1,012 [0,830; 1,193] | 0,998 |
| İY önde→MS mağlup → sonraki 5 maçta puan | 1.496 | 0,986 [0,966; 1,005] | 0,575 |

Bir geri dönüşün (veya önde olup kaybetmenin) ardından sonraki maçlar S0'ın beklediğinden farklı değil.

## F3 — S1 (dizi özellikli lojistik) ve S2 (benzer diziler, kNN) — önceden görülmüş aile

8 hücrenin hepsi `NO_ADDED_VALUE`. İY/MS geçiş hedeflerinde S1 ve S2 S0'ı geçemedi (S2 test ΔLL +0,0008/+0,0011).
GALIBIYET/MAGLUBIYET'te S1 S0'ı belirgin geçiyor (test ΔLL −0,0034/−0,0031) ama aynı satırlarda piyasa kontrolü S0p
çok daha iyi (GALIBIYET test log-kayıp: S0 0,6076 · S1 0,6041 · S0p 0,5941) ve S1'in katkısı S0p üzerine eklenince
kayboluyor; piyasa kontrolünde S0'ın ağırlığı ≈ 0 (sıcaklık −0,03). Yani 1X2'de dizi özelliklerinin yararı, temel gol
modelinin piyasanın zaten bildiği formu geç yansıtmasından geliyor.

## F4 — olaylar arası süre (tehlike modeli)

| Olay | Aralık (tamamlanan / sansürlü) | Medyan aralık | Keşif Wald p ("son olaydan beri maç") | Test ΔLL [%95] | Statü |
|---|---|---|---|---|---|
| İY geride → MS galip | 6.475 / 1.275 (+1.673 sol kesik) | 29 lig maçı | 0,87 | +0,00003 [−0,00003; +0,00010] | NO_ADDED_VALUE |
| İY önde → MS mağlup | 6.407 / 1.343 (+1.673 sol kesik) | 29 lig maçı | 0,98 | +0,00002 [−0,00001; +0,00004] | NO_ADDED_VALUE |

"Uzun süredir olmadı, sıra geldi" türü bir süre etkisi yok; parametre döneminde görülen küçük iyileşme (İY geride →
MS galip, −0,00003) testte tekrarlanmadı. Süre birimi lig maçıdır; tüm resmî maçlar `DATA_QUALITY_BLOCKED`.

## F5 — A/B/C (iki yarıda KG, 3,5 Üst, İY 1,5 Üst) ek kontrolü — önceden görülmüş aile

Dizi özellikleri üç pazara da katkı sağlamadı (parametre ΔLL +0,00014 / +0,00014 / +0,00009; Holm p = 1).

## F6 — ekonomik değer (varsayımsal; önceden görülmüş aile)

| Hedef | Dönem | S0 | S1 | S2 | S0p / marjsız Bet365 |
|---|---|---|---|---|---|
| GALIBIYET | parametre | −%8,3 | −%7,0 | −%8,1 | bahis yok (ROI_UNAVAILABLE) |
| GALIBIYET | test | −%12,3 | −%12,7 | −%11,3 | bahis yok |
| MAGLUBIYET | parametre | −%8,5 | −%6,1 | −%9,0 | bahis yok |
| MAGLUBIYET | test | −%12,7 | −%12,6 | −%12,4 | bahis yok |
| İY/MS geçiş hedefleri | her iki dönem | ROI_UNAVAILABLE | | | gerçek İY/MS oranı yok; 1X2'den türetilmez |

EV ≥ 0,05 eşiği, maç başına tek bahis, sabit birim, komisyon 0; Bet365 kapanış oranlarının yayımlanma zamanı
doğrulanamadığı için sonuçlar varsayımsaldır. Hiçbir model ekonomik avantaj göstermedi.

## Anomali incelemesi (tahminden ayrı)

Her lig-sezonda gerçekleşen İY/MS sonucunun S0'a göre sürprizi en üst %0,5'te olan maçlar ve ayrıca model–piyasa
farkı en üst %0,5'te olan maçlar işaretlendi (orta sıra kuralı; ≤ 100 maçlık havuzlar işaretlenmez): toplam 1.600 kayıt
(sürpriz 845, piyasa farkı 761). Çalıştırılabilen kontroller: veri doğrulama, hükmen olabilir, takım adı kopukluğu,
lig değişikliği sonrası ilk maçlar (353 kaydı açıkladı), kırmızı kart (121 kaydı açıkladı; 429 kayıtta veri yok).
Çalıştırılamayanlar (veri yok): eski oran, düşük likidite, kadro haberi, maç içi bilgi, sağlayıcı gecikmesi.
Açıklanamayan 635 sürpriz kaydının çoğu ham İY/MS 1/2 (619) ve 2/1 (218) sonucudur (medyan S0 olasılığı %1,4);
seçim kuralı gereği her lig-sezonda sabit bir pay işaretlendiği için bu sayı tek başına bir bulgu değildir. Takım,
lig veya hakem bazında toplama/sıralama yapılmadı; tekil maç kayıtları yalnızca yerel uygulama klasöründe tutulur.
Resmî karar kaydı boştur (veri kaynağı bağlı değil); kaydın olmaması "temiz" anlamına gelmez.

## Mod A örneği: PSV Eindhoven (tanımlayıcı, olay seçimli)

Veri setinde PSV'nin 850 Eredivisie maçı var (19.08.2000–30.08.2026, hepsinde İY skoru mevcut). Ham İY/MS 2/1:
25 maç (19'unda PSV ev sahibi ve ilk yarıyı geride kapatıp kazandı; 6'sında deplasmanda ilk yarıyı önde kapatıp
kaybetti), ilki 08.02.2004, sonuncusu 04.04.2026 (Utrecht, İY 1-2, MS 4-3). Takım perspektifinde "İY geride → MS
galip" 35 kez (medyan aralık 18,5 maç), "İY önde → MS mağlup" 8 kez. Son olaydan bu yana 9 maçlık açık (sansürlü)
aralık var — "olmayacak" veya "sırası geldi" anlamına gelmez. Bu sayılar kaynak verideki skorlarla doğrulandı;
resmî kaynakla çapraz kontrol yapılmadı. Ön-kayıtlı araştırmada bu tür olaylar için anlamlı bir öncü koşul
bulunmadı (yukarıdaki F1, F2, F4).

## Sınırlar

- Yalnızca lig maçları; kupa/Avrupa maçı, dakika bazlı gol, kadro, xG, hakem, bahis hacmi ve İY/MS oranı yok.
- Test dönemi koşullu örüntüler için ön-kayıtlıdır; S0'ın İY/MS kalibrasyonu test döneminde görülmüştür (sözleşme §5).
  Tamamen temiz kanıt yalnızca ileriye dönük takipten gelebilir; şu an takibe alınacak aday yoktur.
- Bet365 oranlarının zamanı doğrulanamaz; piyasa kontrolü ve ROI bu nedenle varsayımsaldır.
- S0p sözleşmedeki 9 hücreli çarpan biçimi yerine hedef başına, S0'a serbest sıcaklık veren biçimde uygulandı (ilk
  sonuçtan önce kayda geçirilen uygulama kararı).

## Zorunlu testler ve karşılıkları

Hepsi yalnızca sentetik (açıkça test amaçlı) veri ve geçici klasörlerle çalışır.

| # | Zorunlu test | Test fonksiyon(lar)ı |
|---|---|---|
| 1 | HT 0-1, FT 2-1 → `HTFT_2_1` | `test_htft.py::test_ht01_ft21_is_htft_2_1_and_not_over35_or_fh15` |
| 2 | Aynı örnek 3,5 Üst / İY 1,5 Üst sayılmaz | aynı test (B ve C etiketleri 0) |
| 3 | HT 1-0, FT 1-2 → `HTFT_1_2` | `test_htft.py::test_ht10_ft12_is_htft_1_2` |
| 4 | Ev/deplasman perspektifinde geri dönüş anlamı korunur | `test_htft.py::test_team_perspective_flips_with_home_away`, `test_seq_timeline.py::test_two_rows_per_match_with_mirror_consistency` |
| 5 | İY skoru eksikse İY/MS bilinmiyor | `test_htft.py::test_missing_halftime_is_unknown_not_false`, `test_seq_timeline.py::test_possible_awarded_rows_have_unknown_result` |
| 6 | Uzatma normal süre sonucuna katılmaz | `test_htft.py::test_extra_time_not_used_for_full_time_result` |
| 7 | Dokuz İY/MS olasılığının toplamı 1 | `test_htft.py::test_nine_htft_probabilities_sum_to_one`, `test_seq_timeline.py::test_team_cell_mapping_and_probabilities_sum_to_one` |
| 8 | Olay sonrası veri maç öncesi özelliğe giremez | `test_seq_timeline.py::test_post_event_data_never_enters_pre_event_features`, `test_seq_research.py::test_prematch_view_has_no_post_event_and_keeps_failures`, `test_ui.py::test_sequences_prematch_view_has_no_post_event` |
| 9 | Gelecek maç eklenmesi geçmiş karar anı tahminini değiştirmez | `test_seq_timeline.py::test_adding_future_matches_does_not_change_past_features`, `test_seq_research.py::test_prematch_atoms_equal_full_data_atoms_for_next_match`, `test_seq_timeline.py::test_calibration_is_identity_until_enough_history_and_uses_only_past`, `test_seq_hazard.py::test_frailty_unaffected_by_future_seasons` |
| 10 | Benzer örnek araması başarısız örnekleri dışlamaz | `test_seq_research.py::test_prematch_view_has_no_post_event_and_keeps_failures`, `test_ui.py::test_sequences_prematch_view_has_no_post_event`, `test_seq_patterns.py::test_mode_b_counts` |
| 11 | Ham benzerlik yüzdesi olasılık olarak kullanılmaz | `test_seq_models.py::test_s2_adjust_formula_hand_example`, `test_seq_research.py::test_prematch_view_has_no_post_event_and_keeps_failures` |
| 12 | Örtüşen pencereler bağımsız kanıt sayısını büyütmez | `test_seq_patterns.py::test_duplicated_rows_do_not_inflate_evidence`, `test_seq_patterns.py::test_cr1_matches_manual_computation`, `test_seq_patterns.py::test_query2_matches_brute_force` |
| 13 | Tek maç iki takım üzerinden eğitim/test arasında sızmaz | `test_seq_timeline.py::test_two_rows_per_match_with_mirror_consistency`, `test_seq_research.py::test_pair_symmetric_masks_keep_twin_rows_together`, `test_seq_models.py::test_s2_neighbors_exclusions_cap_and_exactness` |
| 14 | Tekrarlanmamış ve gözlem süresi bitmiş aralıklar kaybolmaz | `test_seq_timeline.py::test_open_intervals_are_kept`, `test_seq_timeline.py::test_unplayed_next_matches_are_censored_not_filled`, `test_seq_hazard.py::test_km_on_gaps_keeps_all_censored_intervals`, `test_seq_hazard.py::test_km_hand_example_keeps_censored` |
| 15 | Test açıldıktan sonra değişen örüntü "temiz test" sayılmaz | `test_seq_research.py::test_changed_definition_after_test_opened_is_not_clean`, `test_seq_research.py::test_previously_seen_families_cannot_be_supported` |
| 16 | Yanlış pazarın oranı ROI hesabına girmez | `test_htft.py::test_htft_quote_validation_detects_wrong_market`, `test_seq_models.py::test_economic_htft_targets_roi_unavailable`, `test_seq_models.py::test_economic_loss_target_uses_opponent_win_odds_and_settles` |
| 17 | Oran yoksa ROI sıfır değil, hesaplanamıyor | `test_seq_models.py::test_economic_same_event_set_and_missing_odds`, `test_seq_research.py::test_economic_family_never_reports_zero_roi_for_unavailable_markets` |
| 18 | Anomali skoru şike olasılığına dönüştürülmez | `test_seq_anomaly.py::test_records_carry_bits_and_no_wrongdoing_probability`, `test_seq_anomaly.py::test_module_has_no_group_aggregation_or_links`, `test_seq_research.py::test_outputs_keep_anomalies_local_and_unaggregated` |
| 19 | Resmî kararın olmaması "temiz" etiketi oluşturmaz | `test_seq_anomaly.py::test_official_absence_is_kayit_yok` |
| 20 | Gelecekteki resmî karar geçmiş tahmine sızmaz | `test_seq_anomaly.py::test_official_decision_invisible_before_its_date` |
| 21 | Aynı manifest ve tohumla sonuçlar tekrarlanır | `test_seq_research.py::test_rerun_with_same_manifest_and_seed_is_identical`, `test_seq_research.py::test_parallel_reference_process_equals_serial`, `test_seq_patterns.py::test_null_reproducible`, `test_seq_anomaly.py::test_anomaly_outputs_reproducible`, `test_seq_models.py::test_cluster_bootstrap_reproducible_with_seed` |
| 22 | Önceki üç ana pazarda regresyon yok | `test_primary_regression.py` (2 test; altın değerler İY/MS eklenmeden önceki koddan) ve mevcut gol pazarı testleri |
| + | Rastgele hedefte sürekli "güçlü örüntü" ilan edilmez | `test_seq_patterns.py::test_random_target_no_wy_discovery_most_seeds`, `test_seq_research.py::test_null_synthetic_data_does_not_declare_supported_patterns`, `test_seq_hazard.py::test_wald_does_not_reject_without_duration_dependence`; gerçek veride F7 plasebo (0/20) |
| + | Gerçek etki varsa bulunur (güç) | `test_seq_patterns.py::test_planted_effect_detected`, `test_seq_hazard.py::test_wald_rejects_injected_duration_effect` |

## Yeniden üretme

```bash
python -I tools/research/run_dizi.py <matches.pkl> <s0_soy.pkl> <cikti_klasoru> --isci 3          # rapor üretimi
python -m bahis_tahmin dizi-arastir --isci 3                                                       # uygulama klasörüne
```

Aynı veri, kod, manifest ve tohumla sonuçlar birebir tekrarlanır (referans tekrarları işçi sayısından bağımsızdır).

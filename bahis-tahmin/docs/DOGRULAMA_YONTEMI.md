# Doğrulama yöntemi — gol pazarları

Kod: `bahis_tahmin/goals/validation.py`, araştırma betiği çıktıları `reports/`.

## 1. Zaman bölmesi

Sezon yılı Temmuz başında değişir (`season_year`).

| Dönem | Sezonlar | Kullanım |
|---|---|---|
| Isınma | veri başı – 2002/03 | yalnızca takım güçlerinin oturması; eğitime girmez |
| Geliştirme | 2008/09 – 2018/19 (11 sezon) | model/parametre seçimi; istenildiği kadar deneme |
| Kapalı final test | 2019/20 – 2026/27 (son sezon veri sonuna kadar kısmi) | **tek sefer**; seçim kararlarında kullanılmadı |

Her test sezonu `Y` için model yalnızca `2003 ≤ sezon < Y` satırlarıyla eğitilir (genişleyen pencere,
`walk_forward`). Özellikler de zaman sıralıdır: maç günü öncesi bilgiler (bkz. `VERI_SOZLESMESI.md` §5).
Karar anı geçmiş testte "maç günü 00:00" kabul edilir; oran kullanılmadığından oran zamanlaması burada
geçerli değildir.

Uygulama içindeki eğitim (`GoalEngine.train`), aynı yöntemi verinin **son 3 sezonu + güncel sezon** için
tekrarlar ve doğrulama statüsünü buna göre belirler; nihai model ardından tüm verilerle eğitilir.

## 2. Ölçütler (her pazar ayrı, ortak örneklemde)

- **Log-kayıp** (birincil) ve referansa göre fark `Δ = LL_model − LL_taban` (negatif = daha iyi).
- **%95 aralık:** ISO hafta blokları korunarak 1.000 tekrarlı blok bootstrap (aynı haftanın maçları
  birlikte örneklenir; tohum 7).
- **Brier skoru** ve **Brier becerisi** `1 − Brier/Brier_taban`.
- **Ortalama kesinlik (AP):** nadir pazar A için sıralama gücü.
- **Kalibrasyon eğimi/kesişimi:** `logit(y) ≈ a + b·logit(p)`; `b≈1` iyi, `b<1` aşırı güven.
- **ECE:** eşit örnekli 10 bölmede |tahmin − gerçekleşme| ağırlıklı ortalaması; bölmeler için Wilson %95 aralığı.
- **Tutarlılık:** A>B, A>C ve [0,1] dışı olasılık sayısı (hepsi 0 olmalı).
- Referanslar: **M0** (ligin zaman ağırlıklı taban oranı), **C1** (pazar başına ayrı lojistik regresyon;
  tutarlılık garantisi yok), final testte ayrıca **mevcut uygulama maç motoru** (yalnızca B, eşleşen maçlarda).

## 3. Seçim ve ön-kayıt

Geliştirme turlarının tamamı (başarısızlar dahil) `reports/experiments.jsonl` dosyasına eklenir;
kayıt silinmez. Final testten önce seçilen model (`M10_ipf_kosullu`), karşılaştırma listesi ve doğrulama
kuralı aynı dosyaya **ön-kayıt** olarak yazıldı; test sonucu ne olursa olsun model değiştirilmedi.

## 4. Doğrulama kuralı (`dogrulama-kurali-v1`)

Bir pazar `VALIDATED_FOR_PAPER_TRADING` sayılır ancak:

1. `Δ` log-kayıp %95 üst sınırı < 0 (taban orandan anlamlı biçimde iyi),
2. kalibrasyon eğimi 0,8–1,25 ve ECE ≤ 0,02,
3. en az 200 gerçekleşen (pozitif) örnek.

Aksi halde `MODEL_NOT_VALIDATED` ve öneri motoru o pazarda avantaj adayı üretmez. Bu statü yalnızca
**olasılık kalitesini** belgeler; geçmiş gerçek oran olmadığından **kârlılık doğrulanmış değildir**.

## 5. Belirsizlik

Maç başına %80 aralık: takım gücü log-yoğunluklarının standart hataları (Poisson modellerinin ters
Hessian'ı) ile log-normal Monte Carlo (200 çekiliş, sabit tohum), tüm tahmin hattı yeniden çalıştırılır.
İlk/ikinci yarı hataları bağımsız, maç sonu hatası bunların yoğunluk ağırlıklı birleşimidir (kendi
standart hatasına ölçeklenir). Kalibratör katsayı belirsizliği yok sayılır; aralık gerçek olasılığın kesin
sınırı değildir. Karar motoru, aralığın alt sınırıyla (p_safe) hesaplanan beklenen değeri kullanır ve
aralık 0,25'ten genişse öneri üretmez.

## 6. Çoklu deneme uyarısı

Geliştirme döneminde 10+ varyant denendi; seçim geliştirme verisiyle yapıldığı için geliştirme sonuçları
iyimser olabilir. Final test bu yüzden ayrı ve tek seferliktir. Çoklu karşılaştırma için ayrıca bir
düzeltme uygulanmadı.

## 7. Yeniden üretme

Araştırma betikleri `tools/research/` altındadır (maç verisi `matches.pkl`, uygulama veri klasöründen):

```bash
python -I tools/research/build_goal_feats.py <matches.pkl> feat.pkl
python -I tools/research/goal_validate.py dev  feat.pkl <matches.pkl> reports '{"not": "...", "varyantlar": ["M0_taban", "M10_ipf_kosullu"], "etiket": "_x"}'
python -I tools/research/goal_validate.py test feat.pkl <matches.pkl> reports '{"varyantlar": ["M0_taban", "M5_kalibre", "M9_ipf", "M10_ipf_kosullu"]}'
python -I tools/research/engine_oos_b.py <matches.pkl> engine_oos_b.pkl
python -I tools/research/compare_engine_b.py goal_test_pred.pkl engine_oos_b.pkl reports/goal_test_vs_engine_b.json
```

Uygulama içinden: `python -m bahis_tahmin gol-egit` (son sezonlar için aynı doğrulamayı yapar ve statüyü yazar).

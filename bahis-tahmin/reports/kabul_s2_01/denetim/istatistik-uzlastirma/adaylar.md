# F1 adayları ve EXPLORATORY WY-anlamlı hipotezler — sayısal uzlaştırma (taban 01b7e9f)

Kaynak: `reports/dizi_sonuclar.json` (aileler.F1.adaylar, aileler.F1.baglam_tanilama), `reports/dizi_f1_hipotezler.csv`; girdi SHA-256: `dizi_sonuclar.json` 82b35decd7c6…, `dizi_f1_hipotezler.csv` 09dc70b676ba…, `experiments.jsonl` 0f9868507016…. Üretim: `uzlastirma.py` + `tablolar_md.py` (yalnızca yayımlanmış sayılar üzerinde aritmetik; maç verisi açılmadı). Tam sütunlar: `adaylar.csv`.

## Tanımlar (koddan)

- **Referans / beklenen:** E_adj = Σ_{i∈koşul} p0_i · r_s, r_s = O_s/E_s; katman s = taraf × lig × hedefe özgü kalibre S0 p0 beşlisi, değerlendirilen dönem maskesi içinde (patterns.py:3-9, 279). O/E = O/E_adj; %95 aralık O/E ± 1,96·√V/E_adj (patterns.py:315-319); V = CR1 lig-sezon kümeli (patterns.py:283-286); z = (O−E_adj)/√V. "E ham S0" = Σ p0_i (katman yeniden kalibrasyonu yok).
- **Çoklu test:** keşifte Westfall–Young adım adım azalan maxT (|z|, iki yönlü), R = 1000, p_adj = (c+1)/(R+1), Monte Carlo %99 Clopper–Pearson aralığı c/R üzerinde (null.py:181-214); keşif kuralı destekli ∧ p_adj < 0,05 ∧ MC üst < 0,05 (research.py:479). Parametre ve testte ön-kayıtlı yönde tek yönlü normal p ve Holm, k = 4 (patterns.py:784-796; research.py:499, 508).
- **ΔLL işareti:** ΔLL = aday_log_kayıp − referans_log_kayıp = ortalama[LL(S0 + sabit + gösterge)] − ortalama[LL(S0 + sabit)]; **negatif = aday daha iyi**. İki model de S0 logit offset'li lojistik; aynı eğitim satırlarında (keşif ∪ parametre maskesi ∧ atomlar tanımlı ∧ hedef ve p0 sonlu ∧ maç günü + 1 < 2019-07-01; son eğitim tarihi 2019-06-09) uyumlanır; gösterge modeli λ = 0 (cezasız), referans λ = ∞ (yalnız offset + sabit). Değerlendirme: test maskesinde atomların tanımlı olduğu TÜM satırlar (yalnız koşul satırları değil), nats/satır (research.py:386-419; models.py:168-188). Gösterge ham 0/1 (ortalama 0, std 1 → β doğrudan log-odds). Aralık: lig-sezon kümeli yüzdelik bootstrap, 1000 tekrar, tohum 20261010; p_tek = Φ(ΔLL/se_boot); duyarlılık: ISO-hafta kümeleri; ayrıca ham S0'a göre fark.
- **Statü sırası (research.py:555-574):** parametre Holm → test Holm → test ΔLL üst sınır < 0 → (parametre: 7b/1–4, 7b/5) → (test: 7b/1–4, 7b/5). Kayıtlı gerekçe İLK başarısız kontroldür; aşağıda tüm başarısızlar da listelenir.

## Tablo A — sekiz WY-anlamlı tekil hipotez (keşif 2006/07–2012/13)

| # | Hipotez (hedef \| koşul) | Rol | Düz anlatım | n | O (olay) | E_adj | E ham S0 | O/E [%95] | z | WY p_adj (c/1000) [MC %99] | Statü |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FAVORI` | ADAY (sıra 1) | Hedef: takım maçı kaybeder (MS M). Koşul: takımın aynı dilimdeki son 5 lig maçının en az 4'ünü kazanmış olması (5 maçın MS sonucu bilinmeli, pencere tam) VE bağlam: kalibre S0 galibiyet olasılığı ≥ 0,55. | 2275 | 221 | 280,4 | 297,5 | 0,788 [0,690; 0,887] | −4,21 | 0,0220 (21) [0,0111; 0,0357] | NO_ADDED_VALUE |
| 2 | `MAGLUBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU` | ADAY (sıra 2) | Hedef: takım maçı kaybeder (MS M). Koşul: takımın son 5 lig maçının en az 3'ünde ilk yarıyı önde kapatmış olması (5 maçın İY sonucu bilinmeli) VE son 10 maçta Σ(puan − kalibre S0 beklenen puan) ≥ +4 (FORM_DIFF=4; 10 maçın MS'si ve S0 beklenen puanı mevcut olmalı). | 4759 | 1262 | 1427,5 | 1427,0 | 0,884 [0,842; 0,926] | −5,41 | 0,0020 (1) [0,0000; 0,0074] | NO_ADDED_VALUE |
| 3 | `GALIBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU` | ADAY (sıra 3) | Hedef: takım maçı kazanır (MS G). Koşul: takımın son 5 lig maçının en az 3'ünde ilk yarıyı önde kapatmış olması (5 maçın İY sonucu bilinmeli) VE son 10 maçta Σ(puan − kalibre S0 beklenen puan) ≥ +4 (FORM_DIFF=4; 10 maçın MS'si ve S0 beklenen puanı mevcut olmalı). | 4759 | 2253 | 2124,2 | 2092,1 | 1,061 [1,033; 1,089] | +4,24 | 0,0210 (20) [0,0104; 0,0344] | NO_ADDED_VALUE |
| 4 | `GALIBIYET\|RAKIP_SON5_IY_ONDE_EN_AZ_3` | ADAY (sıra 4) | Hedef: takım maçı kazanır (MS G). Koşul: RAKİBİN kendi son 5 lig maçının en az 3'ünde ilk yarıyı önde kapatmış olması (rakip satırının SON5_IY_ONDE_EN_AZ_3 değeri). | 13719 | 4140 | 4340,9 | 4338,7 | 0,954 [0,932; 0,975] | −4,20 | 0,0230 (22) [0,0118; 0,0369] | NO_ADDED_VALUE |
| 5 | `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4` | EXPLORATORY (aday değil) | Hedef: takım maçı kaybeder (MS M). Koşul: takımın aynı dilimdeki son 5 lig maçının en az 4'ünü kazanmış olması (5 maçın MS sonucu bilinmeli, pencere tam). | 7654 | 1960 | 2138,5 | 2142,9 | 0,917 [0,884; 0,950] | −4,96 | 0,0020 (1) [0,0000; 0,0074] | EXPLORATORY |
| 6 | `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & EV_SAHIBI` | EXPLORATORY (aday değil) | Hedef: takım maçı kaybeder (MS M). Koşul: takımın aynı dilimdeki son 5 lig maçının en az 4'ünü kazanmış olması (5 maçın MS sonucu bilinmeli, pencere tam) VE bağlam: takım ev sahibi. | 3598 | 619 | 723,6 | 727,3 | 0,855 [0,800; 0,911] | −5,07 | 0,0020 (1) [0,0000; 0,0074] | EXPLORATORY |
| 7 | `MAGLUBIYET\|SON5_IY_ONDE_EN_AZ_3 & SON5_GALIBIYET_EN_AZ_4` | EXPLORATORY (aday değil) | Hedef: takım maçı kaybeder (MS M). Koşul: takımın son 5 lig maçının en az 3'ünde ilk yarıyı önde kapatmış olması (5 maçın İY sonucu bilinmeli) VE takımın aynı dilimdeki son 5 lig maçının en az 4'ünü kazanmış olması (5 maçın MS sonucu bilinmeli, pencere tam). | 4298 | 1024 | 1149,7 | 1155,6 | 0,891 [0,847; 0,934] | −4,95 | 0,0030 (2) [0,0001; 0,0092] | EXPLORATORY |
| 8 | `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FORM_BEKLENTI_USTU` | EXPLORATORY (aday değil) | Hedef: takım maçı kaybeder (MS M). Koşul: takımın aynı dilimdeki son 5 lig maçının en az 4'ünü kazanmış olması (5 maçın MS sonucu bilinmeli, pencere tam) VE son 10 maçta Σ(puan − kalibre S0 beklenen puan) ≥ +4 (FORM_DIFF=4; 10 maçın MS'si ve S0 beklenen puanı mevcut olmalı). | 4903 | 1258 | 1389,1 | 1389,1 | 0,906 [0,863; 0,948] | −4,34 | 0,0160 (15) [0,0069; 0,0280] | EXPLORATORY |

Atom tanımlarının kod satırları: bahis_tahmin/sequences/features.py:116; bahis_tahmin/sequences/features.py:117; bahis_tahmin/sequences/features.py:125; bahis_tahmin/sequences/features.py:132; bahis_tahmin/sequences/features.py:144; bahis_tahmin/sequences/features.py:145; bahis_tahmin/sequences/frame.py:95.

EXPLORATORY dört hipotez için parametre/test dönemi n, olay sayısı, ΔLL ve 7b kayıtları **yayımlanmış kayıtlarda yok** (örneklem dışı değerlendirilmediler; research.py:496-519 yalnızca adaylara uygulanır). Bu değerler maç verisi açılmadan üretilemez → DOGRULANAMADI/uygulanmadı.

## Tablo B — dört aday: dönem başına sayım, etki ve çoklu test

| Aday | Dönem | n | O (olay) | E_adj | O/E [%95] | z | p_tek (yön) | p_Holm (k=4) | Holm geçti | 7b 1–5 (G=geçti, K=kaldı) | 7b/2 O/E [%95] | 7b/3 aynı yön | 7b/5 S0p O/E [%95] |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FAVORI` | keşif | 2275 | 221 | 280,4 | 0,788 [0,690; 0,887] | −4,21 | WY 0,0220 | – | – | – | – | – | – |
| | parametre | 2804 | 287 | 331,2 | 0,867 [0,771; 0,962] | −2,75 | 0,00299 | 0,00598 | evet | 1:G 2:G 3:G 4:G 5:K | 0,8841 [0,7875; 0,9806] | 6/6 | 0,9325 [0,8333; 1,0316] |
| | test | 3110 | 346 | 393,8 | 0,879 [0,803; 0,954] | −3,14 | 0,00084 | 0,00168 | evet | 1:G 2:G 3:G 4:G 5:K | 0,8943 [0,8189; 0,9697] | 6/7 | 0,9801 [0,9004; 1,0598] |
| `MAGLUBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU` | keşif | 4759 | 1262 | 1427,5 | 0,884 [0,842; 0,926] | −5,41 | WY 0,0020 | – | – | – | – | – | – |
| | parametre | 4631 | 1265 | 1387,9 | 0,911 [0,865; 0,958] | −3,73 | 0,00010 | 0,00039 | evet | 1:G 2:G 3:G 4:G 5:K | 0,9325 [0,8859; 0,9792] | 5/6 | 0,9683 [0,9237; 1,0129] |
| | test | 5049 | 1379 | 1488,1 | 0,927 [0,885; 0,968] | −3,45 | 0,00028 | 0,00085 | evet | 1:G 2:G 3:G 4:G 5:K | 0,9482 [0,9070; 0,9894] | 6/7 | 0,9935 [0,9543; 1,0327] |
| `GALIBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU` | keşif | 4759 | 2253 | 2124,2 | 1,061 [1,033; 1,089] | +4,24 | WY 0,0210 | – | – | – | – | – | – |
| | parametre | 4631 | 2172 | 2094,7 | 1,037 [1,008; 1,066] | +2,53 | 0,00575 | 0,00598 | evet | 1:G 2:K 3:G 4:G 5:K | 1,0186 [0,9908; 1,0464] | 4/6 | 0,9905 [0,9642; 1,0168] |
| | test | 5049 | 2389 | 2303,4 | 1,037 [1,009; 1,065] | +2,58 | 0,00490 | 0,00490 | evet | 1:G 2:K 3:G 4:G 5:K | 1,0192 [0,9919; 1,0464] | 5/7 | 0,9864 [0,9628; 1,0100] |
| `GALIBIYET\|RAKIP_SON5_IY_ONDE_EN_AZ_3` | keşif | 13719 | 4140 | 4340,9 | 0,954 [0,932; 0,975] | −4,20 | WY 0,0230 | – | – | – | – | – | – |
| | parametre | 13623 | 4082 | 4241,6 | 0,962 [0,939; 0,986] | −3,17 | 0,00075 | 0,00226 | evet | 1:G 2:K 3:G 4:G 5:K | 0,9825 [0,9600; 1,0050] | 6/6 | 0,9906 [0,9688; 1,0124] |
| | test | 15453 | 4557 | 4768,7 | 0,956 [0,934; 0,978] | −3,96 | 0,00004 | 0,00015 | evet | 1:G 2:G 3:G 4:G 5:K | 0,9753 [0,9540; 0,9967] | 7/7 | 0,9863 [0,9660; 1,0067] |

Keşif→test log(O/E) oranı (küçülme; aritmetik): `MAGLUBIYET|SON5_GALIBIYET_EN_AZ_4 & FAVORI` 0,54; `MAGLUBIYET|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU` 0,62; `GALIBIYET|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU` 0,62; `GALIBIYET|RAKIP_SON5_IY_ONDE_EN_AZ_3` 0,96 (1 = küçülme yok). Seçilen etkiler keşif MDE'sine yakın olduğundan (bkz. `hesap_ciktisi.json` aday_gozlenen_vs_mde80) örneklem dışı küçülme beklenir.

## Tablo C — test dönemi ΔLL (S0 + sabit + gösterge − S0 + sabit), 2019/20–2025/26

| Aday | β gösterge (log-odds) | sabit (gösterge / ref) | n eğitim | n test (koşul) | LL S0+sabit | ΔLL [boot %95] | p_tek | p_boot | ISO-hafta [%95] (p_tek) | ham S0'a göre ΔLL [%95] | Holm k=4 (p_tek) | Bonferroni k=4 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FAVORI` | −0,2862 | +0,0109 / +0,0070 | 173242 | 91585 (3110) | 0,605772 | −0,000042 [−0,000142; +0,000060] | 0,2097 | 0,1918 | [−0,000155; +0,000075] (0,2312) | −0,000038 [−0,000143; +0,000065] | 0,4314 | 0,8390 |
| `MAGLUBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU` | −0,1799 | +0,0154 / +0,0068 | 171593 | 90637 (5049) | 0,605621 | −0,000062 [−0,000175; +0,000053] | 0,1484 | 0,1528 | [−0,000178; +0,000056] (0,1582) | −0,000058 [−0,000177; +0,000061] | 0,4314 | 0,5937 |
| `GALIBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU` | +0,1299 | −0,0004 / +0,0071 | 171593 | 90637 (5049) | 0,605954 | −0,000048 [−0,000137; +0,000031] | 0,1438 | 0,1528 | [−0,000139; +0,000049] (0,1598) | −0,000043 [−0,000135; +0,000040] | 0,4314 | 0,5752 |
| `GALIBIYET\|RAKIP_SON5_IY_ONDE_EN_AZ_3` | −0,0855 | +0,0192 / +0,0069 | 173130 | 91577 (15453) | 0,605760 | −0,000102 [−0,000197; −0,000010] | 0,0179 | 0,0180 | [−0,000187; −0,000005] (0,0162) | −0,000098 [−0,000195; −0,000004] | 0,0717 | 0,0717 |

Özet: ΔLL ortalama −0,000064, ortanca −0,000055, aralık [−0,000102; −0,000042]; sıfırı içeren bootstrap aralığı 3/4 (ilk üç aday). Göreli iyileşme 0,0070, 0,0102, 0,0079, 0,0169 % (−ΔLL / LL(S0+sabit)). Yalnız `GALIBIYET|RAKIP_SON5_IY_ONDE_EN_AZ_3` aralığı sıfırı dışlar; bu aralık aday başına (çoklu düzeltmesiz) bootstrap'tır; 4 test adayı üzerinde Holm/Bonferroni p = 0,0717 (> 0,05; p_boot ile 0,0719, ISO-hafta ile 0,0648, ham S0'a göre 0,0962).

## Tablo D — statü ve neden

| Hipotez | Statü | Kayıtlı gerekçe (ilk başarısız) | Tüm başarısız kontroller / aday seçimi |
|---|---|---|---|
| `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FAVORI` | NO_ADDED_VALUE | Testte S0 + gösterge log-kaybı S0 + sabitten anlamlı düşük değil. | test ΔLL üst sınır ≥ 0; 7b/5 parametre; 7b/5 test |
| `MAGLUBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU` | NO_ADDED_VALUE | Testte S0 + gösterge log-kaybı S0 + sabitten anlamlı düşük değil. | test ΔLL üst sınır ≥ 0; 7b/5 parametre; 7b/5 test |
| `GALIBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU` | NO_ADDED_VALUE | Testte S0 + gösterge log-kaybı S0 + sabitten anlamlı düşük değil. | test ΔLL üst sınır ≥ 0; 7b/2 parametre; 7b/5 parametre; 7b/2 test; 7b/5 test |
| `GALIBIYET\|RAKIP_SON5_IY_ONDE_EN_AZ_3` | NO_ADDED_VALUE | Yanlışlama listesi (7b/1–4) parametre döneminde geçmedi. | 7b/2 parametre; 7b/5 parametre; 7b/5 test |
| `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4` | EXPLORATORY | Keşifte aile düzeltmesinden geçti; aday sınırı/çift kuralı nedeniyle örneklem dışı sınanmadı. | aynı hedefte ortak atom (SON5_GALIBIYET_EN_AZ_4) — daha yüksek LCB'li seçilmiş aday(lar): MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FAVORI |
| `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & EV_SAHIBI` | EXPLORATORY | Keşifte aile düzeltmesinden geçti; aday sınırı/çift kuralı nedeniyle örneklem dışı sınanmadı. | aynı hedefte ortak atom (SON5_GALIBIYET_EN_AZ_4) — daha yüksek LCB'li seçilmiş aday(lar): MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FAVORI |
| `MAGLUBIYET\|SON5_IY_ONDE_EN_AZ_3 & SON5_GALIBIYET_EN_AZ_4` | EXPLORATORY | Keşifte aile düzeltmesinden geçti; aday sınırı/çift kuralı nedeniyle örneklem dışı sınanmadı. | aynı hedefte ortak atom (SON5_IY_ONDE_EN_AZ_3, SON5_GALIBIYET_EN_AZ_4) — daha yüksek LCB'li seçilmiş aday(lar): MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FAVORI + MAGLUBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU |
| `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FORM_BEKLENTI_USTU` | EXPLORATORY | Keşifte aile düzeltmesinden geçti; aday sınırı/çift kuralı nedeniyle örneklem dışı sınanmadı. | aynı hedefte ortak atom (SON5_GALIBIYET_EN_AZ_4, FORM_BEKLENTI_USTU) — daha yüksek LCB'li seçilmiş aday(lar): MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FAVORI + MAGLUBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU |

## Tablo E — aday seçiminin yayımlanmış sayılarla yeniden kurulumu (patterns.select_candidates)

| LCB sırası | Hipotez | LCB(\|log O/E\|) | Çift kuralı | Ayrıntı | Sonuç |
|---|---|---|---|---|---|
| 1 | `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FAVORI` | 0,1201 | geçti | çift log O/E −0,2379 vs SON5_GALIBIYET_EN_AZ_4: log O/E −0,0872, FAVORI: log O/E −0,0145 | ADAY sıra 1 |
| 2 | `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & EV_SAHIBI` | 0,0928 | geçti | çift log O/E −0,1561 vs SON5_GALIBIYET_EN_AZ_4: log O/E −0,0872, EV_SAHIBI: log O/E +0,0000 | aynı hedefte ortak atom (SON5_GALIBIYET_EN_AZ_4) — daha yüksek LCB'li seçilmiş aday(lar): MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FAVORI |
| 3 | `MAGLUBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU` | 0,0768 | geçti | çift log O/E −0,1233 vs SON5_IY_ONDE_EN_AZ_3: log O/E −0,0474, FORM_BEKLENTI_USTU: log O/E −0,0420 | ADAY sıra 2 |
| 4 | `MAGLUBIYET\|SON5_IY_ONDE_EN_AZ_3 & SON5_GALIBIYET_EN_AZ_4` | 0,0683 | geçti | çift log O/E −0,1158 vs SON5_IY_ONDE_EN_AZ_3: log O/E −0,0474, SON5_GALIBIYET_EN_AZ_4: log O/E −0,0872 | aynı hedefte ortak atom (SON5_IY_ONDE_EN_AZ_3, SON5_GALIBIYET_EN_AZ_4) — daha yüksek LCB'li seçilmiş aday(lar): MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FAVORI + MAGLUBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU |
| 5 | `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FORM_BEKLENTI_USTU` | 0,0532 | geçti | çift log O/E −0,0991 vs SON5_GALIBIYET_EN_AZ_4: log O/E −0,0872, FORM_BEKLENTI_USTU: log O/E −0,0420 | aynı hedefte ortak atom (SON5_GALIBIYET_EN_AZ_4, FORM_BEKLENTI_USTU) — daha yüksek LCB'li seçilmiş aday(lar): MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FAVORI + MAGLUBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU |
| 6 | `MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4` | 0,0518 | geçti | tek atom (çift kuralı uygulanmaz) | aynı hedefte ortak atom (SON5_GALIBIYET_EN_AZ_4) — daha yüksek LCB'li seçilmiş aday(lar): MAGLUBIYET\|SON5_GALIBIYET_EN_AZ_4 & FAVORI |
| 7 | `GALIBIYET\|SON5_IY_ONDE_EN_AZ_3 & FORM_BEKLENTI_USTU` | 0,0321 | geçti | çift log O/E +0,0588 vs SON5_IY_ONDE_EN_AZ_3: log O/E +0,0221, FORM_BEKLENTI_USTU: log O/E +0,0293 | ADAY sıra 3 |
| 8 | `GALIBIYET\|RAKIP_SON5_IY_ONDE_EN_AZ_3` | 0,0250 | geçti | tek atom (çift kuralı uygulanmaz) | ADAY sıra 4 |

Not: `EV_SAHIBI` tek başına O/E'si katmanlama (taraf) nedeniyle tam 1,000'dır (baglam_tanilama); çift kuralı `s == 0` dalında koşulsuz geçilir (patterns.py:757). Yeniden kurulan seçim yayımlanan sıra 1–4 ile birebir aynı; EXPLORATORY dördünün hepsi çift kuralını geçiyor ve **aynı hedefte ortak atom** kuralıyla (5'lik sınır değil) elendi.

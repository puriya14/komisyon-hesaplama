# Yeniden örnekleme sayıları ve p-değeri formülü (taban 01b7e9f)

| Kavram | Değer | Kod (dosya:satır) | Manifest / sonuç alanı | Not |
|---|---|---|---|---|
| R_inner (F1 WY ailesi başına referans tekrarı) | 1000 | bahis_tahmin/sequences/config.py:46; bahis_tahmin/cli.py:484; tools/research/run_dizi.py:32; bahis_tahmin/sequences/research.py:794; bahis_tahmin/sequences/research.py:457; bahis_tahmin/sequences/null.py:125 | manifest.R=1000; F1.R=1000 | CLI varsayılanı sabit 1000 (config'e bağlı değil); run_dizi.py config.N_NULL'u okur; tohum 20261010 |
| R_inner (F2 Sorgu 2 WY ailesi) | 1000 | bahis_tahmin/sequences/research.py:584 | F2.R=1000 | aynı R, tohum seed+2 |
| R_outer (plasebo tohum sayısı) | 20 | bahis_tahmin/sequences/config.py:48; bahis_tahmin/cli.py:485; tools/research/run_dizi.py:33; bahis_tahmin/sequences/research.py:795; bahis_tahmin/sequences/research.py:862 | manifest.plasebo.tohum_sayisi=20; F7.n_seeds=20 | tohumlar 20262010…20262029 (seed+1000+k) |
| plasebo iç R (tohum başına referans tekrarı) | 200 | bahis_tahmin/sequences/config.py:47; bahis_tahmin/cli.py:486; tools/research/run_dizi.py:34; bahis_tahmin/sequences/research.py:795; bahis_tahmin/sequences/null.py:319 | manifest.plasebo.R=200; F7.R=200 | toplam plasebo tam araması 20 × 200 = 4000 (+20 gözlenen) |
| plasebo geçme sınırı | 1 | bahis_tahmin/sequences/config.py:49; bahis_tahmin/sequences/research.py:367 | F7.passed=True; n_seeds_with_discovery=0 |  |
| bootstrap tekrarı (ΔLL; lig-sezon ve ISO-hafta kümeli) | 1000 | bahis_tahmin/sequences/models.py:62; bahis_tahmin/sequences/models.py:157; bahis_tahmin/sequences/research.py:797; bahis_tahmin/sequences/research.py:386; bahis_tahmin/sequences/research.py:407 | manifest.bootstrap=1000; adaylar.gosterge.fark.reps=[1000] | CLI'da bootstrap bayrağı yok (run_research varsayılanı); her aday için aynı tohum 20261010 |
| MC aralık düzeyi (WY p_adj için Clopper–Pearson) | 0.99 | bahis_tahmin/sequences/config.py:52; bahis_tahmin/sequences/null.py:173 | - | c/R üzerinde iki yönlü %99 |
| WY p formülü | (c+1)/(R+1) | bahis_tahmin/sequences/null.py:209; bahis_tahmin/sequences/null.py:210; bahis_tahmin/sequences/null.py:211; bahis_tahmin/sequences/null.py:212 | - | \|z\| maxT (iki yönlü), adım adım azalan; gözlenen-desteklenmeyen ama tekrarda desteklenen hipotezler her adımın maksimumuna girer (muhafazakâr) |
| F1 keşif kuralı (katı) | supported ∧ p_adj<0,05 ∧ MC99_üst<0,05 | bahis_tahmin/sequences/research.py:479 | F1.wy_anlamli=8 |  |
| F7 keşif kuralı (gevşek) | p_adj<0,05 (MC üst sınırı ŞART DEĞİL) | bahis_tahmin/sequences/null.py:348; bahis_tahmin/sequences/null.py:349 | F7.seeds[*].n_discoveries / n_discoveries_strict | katı sayı yalnızca raporlanır; geçme kuralı gevşek sayıyı kullanır (plasebo için daha zor ölçüt) |

## Clopper–Pearson eşikleri (cp_esikler.csv)

| R | en büyük c (CP %99 üst < 0,05) | CP üst(c) | CP üst(c+1) | karşılık gelen p_adj | en büyük c (p_adj < 0,05) | en küçük p_adj |
|---|---|---|---|---|---|---|
| 1000 | 32 | 0,0492 | 0,0504 | 0,03297 | 49 | 0,000999 |
| 200 | 2 | 0,0455 | 0,0538 | 0,01493 | 9 | 0,004975 |

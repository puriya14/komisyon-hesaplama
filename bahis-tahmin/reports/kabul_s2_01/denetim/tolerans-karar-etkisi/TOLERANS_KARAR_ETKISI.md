# Altın regresyon toleransı (1e-7 → 5e-5) ve karar etkisi: denetim

Kapsam: `tests/test_primary_regression.py` (e671c8f → 7437549; 01b7e9f ile aynı), `goals.decision`, `goals.value`.
Kod 01b7e9f'den (ve karşılaştırma için b78a992'den) `git archive` ile `kod/`, `kod_b78a992/` altına çıkarıldı. Depoda hiçbir şey değiştirilmedi.
Yalnızca sentetik veri kullanıldı (`selftest.synthetic_matches(n_seasons=8, n_teams=16, seed=1, half_time=True)` + sentetik oranlar).
Gerçek maç verisi (maclar_yeniden_kurulan.csv.gz) bu görevde KULLANILMADI. Pickle/joblib yüklenmedi. Ağ kullanılmadı.
Python: /home/user/venv-bahis/bin/python 3.13.16, numpy 2.5.3, scipy 1.18.1, pandas 3.0.6, scikit-learn 1.9.1, threadpoolctl 3.7.0;
CPU: Intel Xeon @2.10GHz (AVX-512 FP16 dahil), 4 çekirdek; OpenBLAS otomatik çekirdek = SkylakeX (threadpoolctl).

## 1. Eski ve yeni tolerans (git show e671c8f / 7437549)

- Tek fark `TOL = 1e-7` → `TOL = 5e-5` (+3 satır yorum). `git diff e671c8f 7437549 -- tests/test_primary_regression.py`. 01b7e9f'de dosya 7437549 ile aynı.
- TOL **saf mutlak** toleranstır; rtol yoktur. Ölçüt: anahtar başına `np.nanmax(np.abs(got - want)) <= TOL` (maks-norm).
- predict: 17 anahtar (A, B, C, BC, h1_home, h1_away, h2_home, h2_away, FT_BTTS, FH_BTTS, SH_O15, FT_O25, FT_O45, tail, structural_A/B/C) × 60 satır; NaN maskesi eşitliği AYRICA denetlenir.
- interval: 3 anahtar × 20 satır × [alt, üst] (draws=50, seed=20261010 varsayılan); **NaN maskesi denetlenmez** (aşağıda zayıflık).
- labels: 3 birincil pazar × 300 maç, birebir (maske eşit ve maks fark == 0). markets: `sorted(MARKETS)` listesi birebir (16 anahtar).
- Döngüdeki `assert` ilk başarısız anahtarda durur; CI günlüğü yalnız ilk anahtarı gösterir.

## 2. CI farkları (ci_kanit.md) ve yerel yeniden üretim

- CI başarısız koşu (e671c8f): predict A maks 1.5351364150983926e-06; interval BTTS_BOTH_HALVES_YES maks 4.0720293013052355e-06.
- **Bit düzeyinde yeniden üretildi**: `OPENBLAS_CORETYPE=Haswell` (veya `Zen`) + `NPY_DISABLE_CPU_FEATURES=X86_V4` (AVX-512 dağıtımı kapalı), 1 veya 4 iş parçacığı →
  A = 1.5351364150983926e-06, BTTS aralık = 4.0720293013052355e-06; günlükteki 6 örnek değerin 6'sı 8 haneye kadar aynı (`cikti/ci_ornek_degerler.csv`).
- Aynı (CI) yolda TÜM anahtarlar (`cikti/ci_fark_anahtar_bazinda.csv`): A 1.54e-6, B 5.6e-16, C 7.8e-16, BC 3.8e-7; ikincil anahtarlar 4.7e-6–9.47e-6 (en büyük FT_O45 9.47e-6, structural_B 9.47e-6); aralık: BTTS 4.07e-6, FT_OVER_3_5 ve FH_OVER_1_5 5.6e-16.
  → Etkilenen birincil pazar yalnız **A (BTTS_BOTH_HALVES)**; B ve C ULP düzeyinde aynı.
- Göreli farklar (CI yolu): A en çok 1.14e-5 (altın ≥ 0,05'te 8.95e-6); BTTS aralık 1.53e-5; ikincillerde en çok 3.9e-5 (FT_O45).
- "En büyük fark 4,1e-6" (commit mesajı/yorum) yalnız testin durmadan önce gördüğü iki anahtarın maksimumudur; testin karşılaştırdığı tüm anahtarlarda CI yolunun maksimumu **9.47e-6**.

## 3. Ortam: hesaplama yolu (model değişikliği değil)

- b78a992 (altının üretildiği kod) ve 01b7e9f yerelde varsayılan yolda altınla **birebir** (fark 0); CI benzeri yolda ikisi de bit-aynı sonuç verir (`cikti/b78a992_*.json`).
  e671c8f..01b7e9f arasında goals/, selftest.py, data/, timeutil.py, requirements.txt değişmedi (`git diff --stat`).
- 29 yapılandırmalı matris (`cikti/matris_ozet.csv`; 7 OpenBLAS çekirdeği × {1,4} iş parçacığı × numpy AVX-512 açık/kapalı + varsayılan):
  etiketler 29/29 aynı, pazar listesi 29/29 aynı, TOL=5e-5 29/29 geçer, TOL=1e-7 yalnız 5/29 (yerel varsayılan yol) geçer.
  En büyük farklar: A 2.06e-6, A aralık 5.58e-6, B ≤ 1.3e-15, C ≤ 3.3e-15, tüm predict anahtarları 1.38e-5.
- Kaynak yalnız BLAS değil: numpy'nin kendi SIMD dağıtımı (AVX-512'ye karşı AVX2 exp/log/log1p/expm1/power) da ULP farkı üretir (2M rastgele girdide exp 92 418, log1p 92 575, expm1 180 435, power 104 665, sqrt 0 fark; `cikti/simd_farki.txt`).
  CI sayılarını yeniden üretmek için İKİSİ birlikte gerekti → AVX-512'siz (ör. AMD EPYC/Zen) bir koşucu ile tutarlı; CI işlemci modeli kanıtta yok.
- Mekanizma (sıkı durma ölçütü denemesi, `cikti/mekanizma_ozet.txt`): L-BFGS-B (M5 `_fit_calibrated` + `_fit_qcal`) sıkı ölçütle koşulunca
  yollar arası fark A'da 1.5e-6 → 3.4e-8, tüm anahtarlarda 9.5e-6 → 3.3e-7. ULP farkları optimizasyonun durma noktasında büyüyor.
  Yan bulgu: varsayılan durma ölçütünün kendisi A'yı 1.67e-4, ikincilleri 2.28e-3'e kadar (sıkı çözüme göre) yaklaşık bırakıyor.

## 4. Karar etkisi (sentetik oranlar; `scripts/karar_etkisi.py`)

- EV = p·d − 1 (komisyon 0) ⇒ ΔEV = d·Δp; ölçülen sapma ≤ 6.1e-16. 207 360 eşik-bitişik vakada (F1) tüm geçişler |EV − eşik| ≤ d·|Δp| bandında (bant dışı geçiş 0).
- Gerçekçi 0,01 kotasyon ızgarası (F2, 77 246 oran × 8 işaret deseni): δ=4.1e-6 → durum değişimi 16 (yalnız A) / 20 (ABC) / 617 968; VALUE↔NO_VALUE 0; EV işareti 20/24.
  δ=5e-5 → 216/256 durum, VALUE↔NO_VALUE 12/20, EV işareti 152/180. Değişimlerin çoğu BTTS_BOTH_HALVES_YES'te (düşük p, yüksek oran).
- Gösterim: adil oran (2 hane) 360'ın 11'i (4.1e-6) / 41–49'u (5e-5); min. oran (2 hane) 120'nin 3–5'i / 14–22'si; en büyük göreli adil oran değişimi 2.9e-4 / 3.56e-3.
- Sıralama (F4, 1000 olay × 8 desen): tam sıralama 10–16 (4.1e-6) / 188–222 (5e-5) değişti; yoğunlaşma sonrası kazanan aday 2–4 / 8 değişti.
- Genişlik eşiği (0.25): altın genişliklerin eşiğe en yakın payı 0.00126 ≫ 2·5e-5 → HIGH_UNCERTAINTY geçişi mümkün değil.
- A ≤ BC ≤ min(B, C): M10 (qcal var) yolunda kayan noktada KESİN (A = BC·q, q = 1/(1+e^-x) ≤ 1; B = BC + BnC). 32 kaynakta (altın + 31 koşu) 0 ihlal;
  stres testinde M10 0 ihlal. qcal=None (M9 ya da <200 B∩C eğitim maçı) yolunda A, BC'yi 1.1e-16'ya kadar aşabilir (200 000 yapay vakada 475).

### Önerilen bayrak: SAYISAL_ESIK_YAKINI (durum ve ekonomik eşik değişmez; yalnız gerekçe/uyarı)
δ_num = altın regresyon testinin TOL'u (tek kaynaktan içe aktarılır; bugün 5e-5). Herhangi biri doğruysa bayrak:
1. |ev_safe − min_edge_safe| ≤ d·δ_num  (eşdeğeri: d ∈ [(1+m)/(p_safe+δ_num), (1+m)/(p_safe−δ_num)])
2. |ev − max_plausible_ev| ≤ d·δ_num
3. |ev| ≤ d·δ_num  (EV işareti/rengi)
4. |(p_high − p_low) − max_interval_width| ≤ 2·δ_num
5. Yoğunlaşma: ilk iki VALUE adayı için |ev_safe₁ − ev_safe₂| ≤ (d₁ + d₂)·δ_num (gün/lig-gün sınırındaki son kabul–ilk ret çifti için de).
Gerekçe: test, |Δp| ≤ TOL farkını "aynı model" sayar; bu farkla değişebilen her karar sayısal olarak belirsizdir. Sonuç: δ ≤ δ_num için bayraksız karar değişimi
F1'de 0, F2'de 0, F4'te 0. δ_num = 4.1e-6 seçilseydi δ=5e-5'te 332/392 değişim kaçardı. Maliyet: ızgara oranlarının %0.29'u (226/77 246), olayların %1.4'ü (14/1000).

## 5. Önerilen testler
- Etiket/sonuçlandırma/pazar kaydı birebir (mevcut) + `settle()` sonuçları altın skorlarda birebir; aralıklarda da NaN maskesi eşitliği.
- Olasılıklar: anahtar başına mutlak TOL=5e-5 (en kötü gözlenen 1.38e-5'in 3.6 katı; A için 9 kat) + küçük büyüklüklü `tail` için göreli ölçüt;
  tüm anahtarların farkları toplanıp tek iletide raporlansın; altın dosyasına üretim commit'i, sürümler, OpenBLAS çekirdeği ve numpy SIMD hedefleri yazılsın,
  aynı parmak izinde birebir (0) eşitlik istensin. Tespit gücü: shrink 30→31 A'yı yalnız 2.05e-5 (aralık 4.53e-5) oynatıyor, TOL'u yalnız ikincil anahtarlar (8.1e-5) aşıyor.
- Yapısal: A ≤ BC ≤ min(B, C) toleranssız; p_NO = 1 − p_YES.
- Karar etkisi: altın p/aralıklardan sentetik oran ızgarası; bayrak dışındaki her vakada güncel çıktıyla altın çıktının kararı (durum, EV işareti, kazanan aday) birebir;
  ΔEV = d·Δp özdeşliği; bayrağın δ_num'u testin TOL'undan içe aktarılır.

## Dosyalar
scripts/: hesap_current.py, matris.sh, ozet_matris.py, ci_fark_analizi.py, mekanizma_siki_tolerans.py, yapi_esitsizlik.py, yapi_fp_stres.py, karar_etkisi.py, tespit_gucu.py, test_zayifliklari.py, simd_farki.py
cikti/: matris_ozet.csv, run_*.json (29+1), b78a992_*.json, ci_fark_anahtar_bazinda.csv, ci_ornek_degerler.csv, mek_*.json, mekanizma_ozet.txt,
yapi_esitsizlik.json, yapi_fp_stres.json, karar_*.csv, karar_etkisi_ozet.json, karar_etkisi_konsol.txt, tespit_gucu.csv, test_zayifliklari.json, simd_farki.txt

"""Denetim tablolarını yazar (elle derlenmiş kanıt satırları; her satır kaynak gösterir).

Kısaltmalar (kanıt alanında):
  EXP:n      = git show 01b7e9f:bahis-tahmin/reports/experiments.jsonl, 0 tabanlı satır n
  JSON:...   = git show 01b7e9f:bahis-tahmin/reports/dizi_sonuclar.json alan yolu
  ANA:s      = /root/.claude/projects/-home-user-komisyon-hesaplama/bd37f391-ef82-5701-bf64-cae5433e5dc0.jsonl satır s
  WF3:ajan:s = .../subagents/workflows/wf_ee64b9c7-3e4/agent-<ajan>.jsonl satır s
  WF1:ajan:s = .../subagents/workflows/wf_852a73d7-2d0/agent-<ajan>.jsonl satır s (inceleme haritaları)
  WF2:ajan:s = .../subagents/workflows/wf_c4cae70c-7e9/agent-<ajan>.jsonl satır s (kırmızı takım)
  JRN        = .../wf_ee64b9c7-3e4/journal.jsonl
  (satır numaraları dokum_duzlestir.py / ana_dokum_duzlestir.py çıktısındaki 'satir' alanıdır; zamanlar JSONL timestamp)
"""
import csv
import os

O = os.path.dirname(os.path.abspath(__file__))

AJ = {"impl:patterns": "a363b3a7cc28a5e08", "impl:hazard": "af502104277989788", "impl:models": "a58b9d1c82fa2ce81",
      "impl:anomaly": "af0020055103a70e0", "review:hazard": "a2ea2325f3543961f", "review:patterns": "ab803ae9b14027c91",
      "review:anomaly": "a0b9105a06dda0652", "review:models": "a0d0195ca5ffc05a8", "map:joint": "a2310bd460fbf2bcc",
      "map:engine": "ad6aaadf98359ae9a", "map:data": "afe0dd7d7d29d743f", "redteam:stats": "a1121b50b1fa56be0",
      "redteam:data": "a0c8cc68246ea7e67"}

# ---------------------------------------------------------------------------------------------------------------
# 1) Bağımlılık tablosu
# ---------------------------------------------------------------------------------------------------------------
BAG = [
    dict(nesne="S0 varyant seçimi (M10_ipf_kosullu; önceki görev)",
         egitim="her fold Y: 2003 ≤ sezon < Y (EXP:0-7 egitim_kurali)",
         kalibrasyon="model içi (M5 çarpanları, C1 IPF, q-kal) her fold eğitiminde",
         parametre_secimi="varyant: geliştirme 2008/09–2018/19 (EXP:6 secim_gerekcesi; EXP:0-5 test_yillari 2008–2018). "
                          "DC xi=0.0019 başlangıç uygulamasından (0a243af, models/dixon_coles.py:22), ridge=3.0 HALF_CFG "
                          "b78a992'de; bu ikisinin seçim dönemi kayıtlı değil",
         ilk_gercek_sonuc="geliştirme 05:28:05–06:12:46 (orkestratör; EXP:0-5); 2019/20+ A/B/C final testi 06:30:28 "
                          "(orkestratör; EXP:7); motor B karşılaştırması 06:46:58 (EXP:9)",
         on_kayit="06:14:54 (EXP:6)", resmi_calistirma="06:20:39 başlatma → 06:30:28 kayıt (ANA ~06:20:39; EXP:7)",
         veri="data_manifest sha 281e3ea2… (EXP:0-9) = yeniden kurulan CSV (veri_surumu_cikti.json)",
         kod="çalışma ağacı; commit b78a992 06:48:10 (testten sonra; aralık yöntemi değişikliği EXP:8 dahil) — "
             "bit düzeyinde DOGRULANAMADI"),
    dict(nesne="S0 soy kaydı (seq/s0_v1.pkl; dizi)",
         egitim="fold Y (tarih bazlı sezon yılı): 2001 ≤ fold < Y (s0.py:30,75-77); fold 2002–2026; 172.061 satır",
         kalibrasyon="M10 iç kalibratörleri her fold içinde",
         parametre_secimi="yeni seçim yok (varyant/hiperparametre önceki görevden)",
         ilk_gercek_sonuc="kurulum günlüğü 08:32:40 (yalnızca satır/süre; ANA:3191); S0 ile ilk performans: impl:models "
                          "09:01:27 (F3)",
         on_kayit="sözleşme v2 08:24:47 (EXP:10) — kurulum 08:13:52'de ÖN-KAYITTAN ÖNCE başladı (ANA:2939), "
                  "~08:32:31'de bitti",
         resmi_calistirma="10:08:09'da run_dizi.py'ye hazır pickle olarak verildi, yeniden kurulmadı (ANA:4211)",
         veri="home30/matches.pkl; eşleme 69f7a695… (kurulum günlüğü); tüketen çalıştırma veri sha 6ca929a2…",
         kod="08:13 çalışma ağacı; s0.py/goals değişikliği 08:13→e671c8f arası dökümde yok; git diff e671c8f..398b60b "
             "boş. Pickle içeriği DOGRULANAMADI (pickle yüklenmedi; manifestte yalnızca model_hash listesi)"),
    dict(nesne="S0 İY/MS 9 hücre kalibrasyonu",
         egitim="sezon Y için yalnızca fold < Y saklı S0 tahminleri, en az 5000 satır; 2002–2003 özdeşlik "
                "(s0.py:136-154; ANA:3202)",
         kalibrasyon="çok sınıflı lojistik: log S0 × sıcaklık + 8 hücre sabiti, ridge 1e-3 (s0.py:102-134)",
         parametre_secimi="biçim sözleşme v2'de (08:08:37) seçildi; kırmızı takım önerisi 2019+ örneklem içi "
                          "kalibrasyon bulgusunu (dönüş hücreleri %7-12 düşük, ~4 SE) gerekçede kullandı "
                          "(WF2:redteam:stats:34; WF2:redteam:data:70)",
         ilk_gercek_sonuc="2019-07+ 52.902 satırda örneklem içi İY/MS kalibrasyonu: map:joint 07:21:00 (WF1:map:joint:107); "
                          "orkestratör 07:45:58/07:59:16'da okudu; fold sıcaklıkları 08:33:09 (ANA:3202; 2019: 1,29)",
         on_kayit="08:24:47 (sözleşme v2 §6 tanımlıyor)", resmi_calistirma="çalıştırma içinde yeniden hesaplandı "
                                                                      "(JSON:s0_kalibrasyon)",
         veri="6ca929a2…", kod="s0.py e671c8f = 398b60b"),
    dict(nesne="S0p (piyasa kontrolü)",
         egitim="parametre değerlendirmesi: keşif uyumu; test: keşif+parametre (arındırılmış, dondurulmuş) "
                "(models.s0p_predict; JSON:aileler.F3.hedefler.*.secim.S0p egitim_son_tarih 2013-06-09/2019-06-09)",
         kalibrasyon="hedef başına cezasız lojistik; v1: logit p0 offset + 2 piyasa logit; v2: + S0 sıcaklığı",
         parametre_secimi="v1 tanımı orkestratör brifinde (08:18:43/08:21:09); v2'ye geçiş 09:46:11 review:models "
                          "(WF3:review:models:209) — gerçek veride F3 test sonuçları görüldükten SONRA",
         ilk_gercek_sonuc="impl:models 09:01:46 (S0p dLL parametre/test; WF3:impl:models:284); review:models 09:43:37 "
                          "(eski S0p ile S1/GALIBIYET OUT_OF_SAMPLE_SUPPORTED), 09:45:12 (sıcaklıklı alternatif gerçek "
                          "veride, test dahil), 09:47:03 (yeni S0p ile NO_ADDED_VALUE)",
         on_kayit="RUN_DECISIONS s0p_tanimi 10:07:59 (EXP:12) — gerekçe yalnızca 'sentetik veride gösterilen zayıflık'",
         resmi_calistirma="10:08–10:45 (F1 7b/5, F3, F6)", veri="6ca929a2…", kod="models.py 289854e = 398b60b"),
    dict(nesne="S1 (offsetli L2 lojistik)",
         egitim="keşif uyumu; λ parametrede seçilir; keşif+parametre yeniden uyum, test dondurulmuş",
         kalibrasyon="S0 logit offset", parametre_secimi="λ ∈ {1e-4…1e-1, ∞} parametre döneminde",
         ilk_gercek_sonuc="impl:models 09:01:12 (λ seçimleri), 09:01:27 (F3 statüleri, test dahil)",
         on_kayit="08:24:47 (ızgara config'te)", resmi_calistirma="F3 kaydı 10:45:23 (EXP:16)",
         veri="6ca929a2…", kod="398b60b"),
    dict(nesne="S2 (kNN)", egitim="kütüphane: parametre için keşif, test için keşif+parametre",
         kalibrasyon="S0'a göre O/E düzeltmesi", parametre_secimi="(k, κ) parametre döneminde",
         ilk_gercek_sonuc="impl:models 09:01:12 ((1000,80)/(500,80)); 09:01:27 F3",
         on_kayit="08:24:47", resmi_calistirma="10:45:23 (EXP:16)", veri="6ca929a2…", kod="398b60b"),
    dict(nesne="Tehlike modeli (F4)", egitim="keşifte Wald; parametre/test için dondurulmuş örneklem dışı uyum",
         kalibrasyon="kalibre S0 logit offset + kırılganlık (önceki 2 sezon)",
         parametre_secimi="yok (kategoriler sözleşmede); 7b/5'e S0 sıcaklığı 10:01:59 (ANA:4157) orkestratör",
         ilk_gercek_sonuc="resmi çalıştırma 10:45:35 (EXP:17); öncesi yalnızca yapısal (08:33:10 WF3:impl:hazard:97; "
                          "09:03:16 WF3:review:hazard:59) ve simüle sonuç (09:32:51 WF3:review:hazard:230)",
         on_kayit="08:24:47 + RUN_DECISIONS f3_yanlislama 10:07:59", resmi_calistirma="10:45:35",
         veri="6ca929a2…", kod="hazard.py 289854e = 398b60b (d57eea7'deki sürüm mutant, aşağıya bakın)"),
    dict(nesne="F1 Sorgu 1 (800 hipotez, WY)", egitim="keşif 2006/07–2012/13 arama + referans süreç",
         kalibrasyon="kalibre S0; gösterge katsayısı keşif+parametre (arındırılmış, <2019-07-01; JSON egitim_son_tarih "
                     "2019-06-09)",
         parametre_secimi="aday ≤5 kural tabanlı; parametre Holm; 7b/5 için S0p v2",
         ilk_gercek_sonuc="gerçek S0'a göre: resmi 10:36:06 (EXP:14). Öncesi: impl:patterns SAHTE S0 + gerçek sonuç, "
                          "yalnızca keşif maskesi 08:34:13 ve 08:40:23 (WF3:impl:patterns:69,101); orkestratör bu "
                          "çıktıları 09:36:20'de okudu (ANA:4045)",
         on_kayit="08:24:47 (EXP:10) + 10:07:59 (EXP:12)", resmi_calistirma="10:31–10:36:06",
         veri="6ca929a2…", kod="398b60b / kod sha 8ca41041…"),
    dict(nesne="F2 Sorgu 2 (6 hipotez)", egitim="keşif WY; parametre/test Holm yalnızca WY-anlamlılar için",
         kalibrasyon="kalibre S0", parametre_secimi="yok",
         ilk_gercek_sonuc="gerçek S0'a göre: resmi 10:36:11 (EXP:15). Öncesi: impl:patterns sahte S0 ile q2_evaluate "
                          "(keşif) 08:40:23",
         on_kayit="08:24:47 + 10:07:59", resmi_calistirma="10:36:11", veri="6ca929a2…", kod="398b60b"),
    dict(nesne="F3 S1/S2 vs S0", egitim="yukarıdaki S1/S2", kalibrasyon="S0, S0p",
         parametre_secimi="λ, (k,κ) parametrede; 7b uyarlaması 09:41–09:42 review:models",
         ilk_gercek_sonuc="impl:models 09:01:27 (test dahil statüler); orkestratör 09:04:11 kısmi not "
                          "(ANA:3303), 10:01:20 tam sayılar (ANA:4125)",
         on_kayit="08:24:47; önceden görülme beyanı 09:37:02 (EXP:11)", resmi_calistirma="10:45:23",
         veri="6ca929a2…", kod="398b60b"),
    dict(nesne="F5 A/B/C ek kontrolü", egitim="keşif uyumu, λ=0", kalibrasyon="M10 A/B/C offset (s0_v1)",
         parametre_secimi="yok",
         ilk_gercek_sonuc="impl:models 09:02:46 (WF3:impl:models:296); orkestratör 09:35:58 (ANA:4032); ayrıca 2019+ "
                          "A/B/C önceki görevin final testi (06:30:28)",
         on_kayit="08:24:47; beyan 09:37:02", resmi_calistirma="10:45:37 (EXP:18)", veri="6ca929a2…", kod="398b60b"),
    dict(nesne="F6 ekonomik değer", egitim="S0/S0p/S1/S2 tahminleri", kalibrasyon="—", parametre_secimi="EV eşiği config",
         ilk_gercek_sonuc="impl:models 09:01:46 (test ROI −10…−13%)", on_kayit="08:24:47; beyan 09:37:02",
         resmi_calistirma="10:45:39 (EXP:19)", veri="6ca929a2…", kod="398b60b"),
    dict(nesne="F7 plasebo", egitim="yalnızca keşif maskesi (research.py run_research: disc = masks['kesif'])",
         kalibrasyon="gerçek kalibre S0", parametre_secimi="yok",
         ilk_gercek_sonuc="resmi 10:31:12 (EXP:13); öncesi yalnızca bağışçı kapsamı (yapısal, 09:12:40) ve sahte S0 "
                          "ile duman testi",
         on_kayit="08:24:47 + 10:07:59", resmi_calistirma="10:08–10:31:12", veri="6ca929a2…", kod="398b60b"),
    dict(nesne="Anomali incelemesi", egitim="—", kalibrasyon="kalibre S0 sürprizi + model-piyasa farkı",
         parametre_secimi="üst %0,5 kuralı; orta-sıra kuralı ve referans havuzu 09:26–09:30 review:anomaly değişikliği",
         ilk_gercek_sonuc="impl:anomaly 08:54:31 (2118 kayıt; test 629; WF3:impl:anomaly:93); review:anomaly 09:29:52 "
                          "(araştırma maskesi: 845/761, açıklanamayan 635 = resmi sayılarla aynı; WF3:review:anomaly:102)",
         on_kayit="sözleşme §11 08:24:47", resmi_calistirma="10:45:39 sonrası (JSON:anomali_ozeti)",
         veri="6ca929a2…", kod="398b60b"),
]
cols = ["nesne", "egitim", "kalibrasyon", "parametre_secimi", "ilk_gercek_sonuc", "on_kayit", "resmi_calistirma",
        "veri", "kod"]
with open(os.path.join(O, "bagimlilik_tablosu.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=cols)
    w.writeheader()
    w.writerows(BAG)
with open(os.path.join(O, "bagimlilik_tablosu.md"), "w", encoding="utf-8") as fh:
    fh.write("# Bağımlılık tablosu (model / kalibratör / aile)\n\nTüm zamanlar UTC, 2026-10-10. Kanıt kısaltmaları "
             "tablolari_yaz.py başındadır.\n\n")
    hdr = ["Nesne", "Eğitim", "Kalibrasyon", "Parametre seçimi", "Gerçek sonucun ilk görülmesi (kim)", "Ön-kayıt",
           "Resmi çalıştırma", "Veri", "Kod"]
    fh.write("| " + " | ".join(hdr) + " |\n|" + "---|" * len(hdr) + "\n")
    for r in BAG:
        fh.write("| " + " | ".join(str(r[c]).replace("|", "\\|") for c in cols) + " |\n")

# ---------------------------------------------------------------------------------------------------------------
# 2) Temas sınıflandırması
# ---------------------------------------------------------------------------------------------------------------
S_ER, S_FIT, S_INC, S_YD, S_HD = ("veriye erişim", "veride fit", "sonuçların incelenmesi",
                                 "sonuca bakarak yöntem değişikliği", "sonuçtan bağımsız hata düzeltmesi")
TEM = [
    ("T01", "06:30:28", "orkestratör (önceki görev)", "S0/M10, F5 dolaylı", "test 2019/20–2026/27",
     "A/B/C kapalı final testi; B,C kural v1 geçti, A geçmedi (eğim 0,788)", S_INC, "EXP:7; goal_test_results.json"),
    ("T02", "06:45:49", "orkestratör (önceki görev)", "S0 aralık yöntemi", "2026/27 ilk 200 maç",
     "final test sonrası aralık yöntemi değişti (olasılıklar değişmez)", S_YD + " (yalnızca aralık; S0 olasılığı etkilenmez)",
     "EXP:8"),
    ("T03", "07:20:06–07:21:00", "map:joint", "S0 İY/MS türetimi", "2019-07+ 52.902 satır (test)",
     "örneklem içi İY/MS hücre kalibrasyonu, çok sınıflı log-kayıp; dönüş hücreleri %7-12 düşük", S_INC,
     "WF1:map:joint:103-107,126"),
    ("T04", "07:33:38", "map:engine", "S0p/piyasa ile ilişkili", "tüm dönem (test dahil)",
     "piyasa ev galibiyeti ondalığına göre İY/MS 2/1, 1/2, X/1, 1/1 oranları", S_INC, "WF1:map:engine:133-134"),
    ("T05", "07:34:50–07:36:56", "map:data", "F4/tanımlayıcı", "tüm dönem",
     "toplu 9 hücre frekansları (genel/lig/takım perspektifi), lig bazında P(galibiyet|İY geride), takım bazında "
     "geri dönüş sayıları, PSV olay listeleri ve olaylar arası maç aralıkları (sansürlü son aralık dahil)", S_INC,
     "WF1:map:data (07:34:50, 07:35:10, 07:36:56); bxp8jirc8 çıktısı"),
    ("T06", "07:45:51–07:45:58", "orkestratör", "inceleme", "tüm dönem", "veri haritası ve eleştirmen çıktısını okudu",
     S_INC, "ANA:2566-2576"),
    ("T07", "07:52–08:05", "kırmızı takım (4 ajan)", "sözleşme v1", "tüm dönem (yapısal)",
     "hükmen skorlar, sezon etiketi uyuşmazlığı, kapsam; T03 bulgusunu gerekçede kullanarak 9 hücreli kalibrasyon önerdi",
     S_ER, "WF2:redteam:leakage:52, redteam:data:41-70, redteam:stats:34"),
    ("T08", "08:08:37", "orkestratör", "S0 kalibrasyonu; dönemler", "—",
     "sözleşme v2: hedef başına 2 parametreli yeniden kalibrasyon → tek 9 hücreli kalibrasyon; test 2018/19→2019/20",
     S_YD + " (karışık: ikiz/referans süreç tutarlılığı yapısal, büyüklük gerekçesi T03'ten)",
     "ANA Write 07:51:25 vs 08:08:37 (sozlesme_v1_075125_dokumden.md, sozlesme_v2_080837_dokumden.md)"),
    ("T09", "08:02:53–08:15:49", "orkestratör", "takım-maç tablosu", "tüm dönem",
     "kapsam, PSV olayları, atom yaygınlığı (sonuç koşulsuz)", S_ER, "ANA:2800-2968"),
    ("T10", "08:13:52–08:32:31", "orkestratör", "S0 soy kaydı", "2001–2026 walk-forward",
     "M10 sezon başına eğitim (1119 sn)", S_FIT, "ANA:2939, 3191"),
    ("T11", "08:32:55–08:33:09", "orkestratör", "9 hücre kalibrasyonu", "fold < Y",
     "kalibrasyon uyumu; fold sıcaklıkları yazdırıldı (2019: 1,29)", S_FIT, "ANA:3197-3202"),
    ("T12", "08:33:08–08:33:19", "impl:hazard", "F4", "tüm dönem", "blok/aralık değişmezleri, kırılganlık süresi",
     S_ER, "WF3:impl:hazard:96-101"),
    ("T13", "08:34:01–08:40:52", "impl:patterns", "F1/F2/F7", "yalnızca keşif",
     "gerçek sonuç + SAHTE S0: 427 destekli, z dağılımı, kalibrasyon kapısı (sahte), GALIBIYET|SON5_GALIBIYET_EN_AZ_4 "
     "yanlışlaması (eşleştirilmiş oran 0,492 vs 0,351), Mod B kartı, Sorgu 2 z (SONRAKI5_PUAN 4,80/−3,87); ikiz "
     "asimetrisi 3.340 satır", S_INC + " (keşif, sahte temel) + yapısal bulgu → ikiz-simetrik maske kararı",
     "WF3:impl:patterns:69,101,106"),
    ("T14", "08:47:53–09:02:46", "impl:models", "F3/F5/F6, S0p", "parametre + test",
     "S1/S2 uyumları; F3 statüleri (S1 GALIBIYET/MAGLUBIYET OUT_OF_SAMPLE_SUPPORTED, test ΔLL −0,00344/−0,00306); "
     "S0p dLL; F6 test ROI; F5 A/B/C", S_FIT + " + " + S_INC + " (test dahil)", "WF3:impl:models:99-296"),
    ("T15", "08:54:20–08:56:45", "impl:anomaly", "anomali", "tüm dönem (test 629 kayıt)",
     "flag_anomalies gerçek veride: 2118 kayıt, dönem dağılımı", S_INC + " (tanımlayıcı)", "WF3:impl:anomaly:93-127"),
    ("T16", "09:04:11", "orkestratör", "F3", "test", "uygulayıcı raporu: 'S1 kazancı ≈ S0p kazancı (dLL ≈ −0,0031)' notu",
     S_INC, "ANA:3303"),
    ("T17", "09:08:17–09:21:18", "review:patterns", "F1/F2/F7", "keşif",
     "S0 tablosu yapısı, bağışçı kapsamı (yapısal), referans süreç süresi (simüle sonuç); gözlenen istatistik YOK",
     S_ER, "WF3:review:patterns:64,123,321"),
    ("T18", "09:20:49–09:21:13", "orkestratör", "F1", "keşif", "gerçek çerçeve + simüle referans tekrarı süresi",
     S_ER, "ANA:3813-3818"),
    ("T19", "09:22:46", "orkestratör", "Mod A (PSV)", "tüm dönem", "PSV olay sayıları/aralıkları (tanımlayıcı)", S_INC,
     "ANA:3897-3898"),
    ("T20", "09:26:23–09:29:52", "review:anomaly", "anomali", "tüm dönem",
     "gerçek işaret oranı %0,62 (hedef %0,5), küçük havuz maksimumları → orta-sıra kuralı ve referans havuzu "
     "değişikliği; düzeltme sonrası sayılar resmi sayılarla aynı (845/761/635)",
     S_HD + " (kural sözleşmedeki %0,5 tanımına uyduruldu; gerçek veride tespit edildi) + " + S_INC,
     "WF3:review:anomaly:64,102; JRN review:anomaly"),
    ("T21", "09:32:36–09:32:51", "review:hazard", "F4", "tüm dönem", "gerçek yapı + SİMÜLE sonuç ile aile süresi",
     S_ER, "WF3:review:hazard:229-230"),
    ("T22", "09:35:51–09:36:20", "orkestratör", "F3/F5, F1 (sahte)", "test / keşif",
     "impl:models dökümünden F5 çıktısı, impl:patterns sahte-S0 çıktıları okundu", S_INC, "ANA:4027-4045"),
    ("T23", "09:42:54–09:44:28", "review:models", "F3, S0p", "parametre + test",
     "eski S0p ile 7b: S1/GALIBIYET OUT_OF_SAMPLE_SUPPORTED, 7b/5 geçti (test fark −0,0024)", S_INC,
     "WF3:review:models:183-192"),
    ("T24", "09:45:01–09:45:12", "review:models", "S0p", "parametre + test",
     "gerçek veride offset S0p vs serbest sıcaklıklı kontrol; S1|S0pT−S0pT test −0,000061 (üst +0,000064)", S_INC,
     "WF3:review:models:195-196"),
    ("T25", "09:46:11", "review:models", "S0p (F1 7b/5, F3, F6)", "—", "S0p'ye S0 sıcaklığı eklendi",
     S_YD + " (sentetik gösterim 09:45:52 sonradan; gerçek veri karşılaştırması 09:45:12 önce)",
     "WF3:review:models:205-210"),
    ("T26", "09:46:21–09:57:09", "review:models", "F3/F5/F6", "parametre + test",
     "yeni S0p ile F3 yeniden: tüm hücreler NO_ADDED_VALUE; F5, F6", S_INC, "WF3:review:models:214-215,291"),
    ("T27", "10:01:20", "orkestratör", "F3, S0p", "test", "review:models sonucu (tam sayılar + süreç notu)", S_INC,
     "ANA:4125"),
    ("T28", "10:01:59", "orkestratör", "F4 7b/5", "—",
     "hazard 7b/5'e S0 sıcaklığı (review:models'in F3 gerçek veri incelemesinden doğan önerisi); F4 sonucu görülmedi",
     S_YD + " (dolaylı; F4 sonucu görülmeden)", "ANA:4157; git show 289854e -- hazard.py"),
    ("T29", "10:07:59", "orkestratör", "RUN_DECISIONS", "—",
     "uygulama kararları ön-kaydı; s0p_tanimi gerekçesi yalnızca 'sentetik veride gösterilen zayıflık'", "kayıt",
     "EXP:12; ANA:4203"),
    ("T30", "10:08:10–10:45:40", "orkestratör (resmi)", "F7,F1,F2,F3,F4,F5,F6, anomali", "tüm dönemler",
     "resmi çalıştırma", "resmi değerlendirme", "EXP:13-19; JSON:manifest"),
    ("T31", "10:51:42–10:56:18", "orkestratör", "prematch/ui_summary, TEST_OPENED", "—",
     "sonuçtan sonra ayna kopyası statü eşlemesi ve test açılış sabiti (istatistik değişmez; kod sha değişti)",
     S_HD + " (gösterim)", "git diff 398b60b 01b7e9f -- sequences/"),
]
with open(os.path.join(O, "temas_siniflandirma.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["no", "zaman_utc", "aktor", "aile_nesne", "donem_kapsami", "ne_goruldu_yapildi", "sinif", "kanit"])
    w.writerows(TEM)

# ---------------------------------------------------------------------------------------------------------------
# 3) Aile kanıt statüsü
# ---------------------------------------------------------------------------------------------------------------
AIL = [
    ("F7", "S0 soy kaydı, 9 hücre kalibrasyonu (bağışçı S0 ondalığı, referans süreç)",
     "test dönemi kullanılmaz (yalnızca keşif)", "ön-kayıtlı, temiz (keşif)",
     "0/20 tohum; gerçek sonuçla ilk hesap resmi çalıştırmada"),
    ("F1", "S0 soy kaydı; 9 hücre kalibrasyonu (E, referans süreç, FAVORI/FORM_BEKLENTI atomları, kapı); S0p v2 (7b/5); "
           "gösterge ΔLL S0 offset",
     "4 adayın test aşaması", "koşullu",
     "keşif WY ön-kayıtlı ve gerçek S0'a göre önceden hesaplanmadı; ancak (a) 9 hücreli kalibrasyon biçimi 2019+ "
     "örneklem içi bulguyu anan önerilerle seçildi, (b) 7b/5'in S0p tanımı F3'ün gerçek test sonuçları görüldükten sonra "
     "değişti. Statüler 7b/5'ten bağımsız (piyasa_kontrolu_duyarlilik.csv); 'dördü de piyasa kontrolünde kayboldu' "
     "ifadesi S0p v2'ye bağlı ve karar veren kural değil"),
    ("F2", "S0 soy kaydı; 9 hücre kalibrasyonu", "statüler keşifte belirlendi (WY anlamsız); test sayıları bilgi amaçlı",
     "ön-kayıtlı, temiz (keşif); test iddiası yok", "impl:patterns sahte S0 ile keşifte Sorgu 2 z gördü"),
    ("F3", "S0, kalibrasyon, S0p v2, S1/S2", "test dahil önceden hesaplandı (09:01:27)", "keşifsel",
     "SEEN_FAMILIES → en fazla EXPLORATORY; S1/GALIBIYET'in NO_ADDED_VALUE nedeni (7b/5) sonuç görüldükten sonra "
     "seçilen S0p'ye bağlı; 7b/5 çıkarılırsa OUT_OF_SAMPLE_SUPPORTED→(EXPLORATORY) olurdu"),
    ("F4", "kalibre S0 offset; 7b/5'te S0 sıcaklığı + piyasa", "test", "ön-kayıtlı, koşullu",
     "gerçek sonuç resmi çalıştırmada ilk kez; 7b/5 yöntemi F3 kaynaklı öneriyle değişti ama karar veren kural değil "
     "(test Holm p=1,0 / 0,73 parametre)"),
    ("F5", "s0_v1 M10 A/B/C offset", "2019+ önceki görevin final testi; impl:models 09:02:46", "keşifsel",
     "sözleşme zaten 2019+ için EXPLORATORY diyor; parametre dönemi statüsü NO_ADDED_VALUE"),
    ("F6", "S0/S0p/S1/S2", "test ROI 09:01:46'da görüldü", "keşifsel (tanımlayıcı)", "statü üretmez"),
    ("Anomali", "kalibre S0 sürprizi, model-piyasa farkı", "sayılar 09:29:52'de görüldü", "tanımlayıcı, önceden görülmüş",
     "kural gerçek veride görülen işaret oranından sonra düzeltildi (sözleşme tanımına uyum)"),
]
with open(os.path.join(O, "aile_kanit_statusu.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["aile", "bagimliliklar", "test_donemi_durumu", "kanit_statusu", "not"])
    w.writerows(AIL)
print("yazildi")

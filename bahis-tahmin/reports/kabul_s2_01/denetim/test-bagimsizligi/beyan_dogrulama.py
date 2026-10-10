"""orkestrator_beyani.md satır satır doğrulama tablosu (beyan_dogrulama.csv). Kanıt kısaltmaları tablolari_yaz.py'de."""
import csv
import os

O = os.path.dirname(os.path.abspath(__file__))
R = [
    ("B1", "Önceki görev: M10 varyantı ve hiperparametreleri 2008/09–2018/19'da seçildi; 2019/20+ A/B/C kapalı final testi; "
           "B, C kural v1'i geçti; A geçmedi.",
     "DARALTILDI",
     "Varyant seçimi geliştirme 2008–2018'de (EXP:0-6; EXP:6 secim_gerekcesi). Final test 06:30:28 (EXP:7). Kural v1 "
     "(EXP:6 dogrulama_kurali): A eğim 0,788 < 0,80 → geçmedi; B 1,048 ve C 1,048, ECE 0,0062/0,0081, LL üst sınır <0 → "
     "geçti (goal_test_results.json results.*.modeller.M10_ipf_kosullu; GOL_PAZARLARI_MODEL_KARTI.md:60-62). Ancak "
     "DC zaman sönümü xi=0.0019 başlangıç uygulamasından (0a243af) gelir ve ridge=3.0'ın seçim dönemi kayıtlı değil "
     "(EXP:0 notu 'HALF_CFG xi=0.0019 ridge=3' ilk turdan sabit).",
     "Varyant seçimi 2008/09–2018/19 geliştirme döneminde yapıldı; DC hiperparametreleri (xi, ridge) önceden sabitti ve "
     "seçim dönemi belgelenmemiş."),
    ("B2", "İnceleme (≈07:30–08:20): toplu İY/MS frekansları, PSV olay listesi ve S0 İY/MS türetiminin 2019+ örneklem içi "
           "kalibrasyon karşılaştırması görüldü.",
     "DARALTILDI",
     "İnceleme iş akışı 07:14:29'da başladı (ANA Workflow); 2019+ örneklem içi kalibrasyon 07:21:00 (WF1:map:joint:107), "
     "yani 07:30'dan önce. Görülenler ayrıca: piyasa ev-galibiyeti ondalığına göre İY/MS oranları (07:33:41, "
     "WF1:map:engine:134), lig bazında P(galibiyet|İY geride), takım bazında geri dönüş sayıları ve PSV olaylar arası "
     "maç aralığı istatistikleri (map:data 07:35:10, 07:36:56). Kırmızı takım bu kalibrasyon bulgusunu 9 hücreli "
     "kalibrasyon önerisinde gerekçe olarak kullandı (WF2:redteam:stats:34, redteam:data:70).",
     "07:14–08:24 incelemede tüm dönemin toplu İY/MS frekansları, piyasa ondalığına göre İY/MS oranları, takım/lig "
     "bazında geri dönüş oranları, PSV olay listesi ve aralıkları ile S0 İY/MS türetiminin 2019+ örneklem içi kalibrasyonu "
     "görüldü; 9 hücreli kalibrasyon önerisi bu bulguyu da gerekçe gösterdi."),
    ("B3", "08:24:47 ön-kayıt (sözleşme v2 sha 4599ddb2…, parametre fc12e491…, eşleme 69f7a695…).", "DOGRULANDI",
     "EXP:10 zaman_utc 08:24:47, üç özet aynı; sözleşme dosyası sha256 e671c8f…01b7e9f'te 4599ddb2… (sha256sum). "
     "Not: kayıt anında sözleşme commit edilmemişti (EXP:10 not_commit; git_head b78a992).", ""),
    ("B4", "S0 soy kaydı build_s0.py ile (~1119 sn); her sezon Y için 2001≤sezon<Y; 9 hücre kalibrasyonu genişleyen pencere "
           "(yalnızca önceki sezonlar).",
     "DOGRULANDI",
     "Günlük 'done 172061 alias_sha 69f7a695… 1119 s' (ANA:3191); s0.py:30,75-77 (fold ≥ 2001, fold < Y; fold = tarih "
     "bazlı sezon yılı); s0.py:148-154 (fold < Y, ≥5000 satır, yoksa özdeşlik). Ek: kurulum 08:13:52'de ön-kayıttan "
     "önce başladı (ANA:2939). Pickle içeriği bu denetimde yüklenmedi (kural) → bit düzeyi DOGRULANAMADI.", ""),
    ("B5", "08:21–09:03 impl:models (a58b9d1c82fa2ce81) gerçek veride F3, F5, F6 hesapladı ve sonuçları gördü.",
     "DARALTILDI",
     "Ajan 08:35:13–09:03:22 çalıştı (döküm zaman damgaları; 08:21 iş akışı başlangıcı). Gerçek veri: çerçeve 08:47:53, "
     "F3 statüleri 09:01:27 (S1 GALIBIYET/MAGLUBIYET OUT_OF_SAMPLE_SUPPORTED), F6 09:01:46, F5 09:02:46 "
     "(WF3:impl:models:99-296).",
     "impl:models 08:35–09:03 arasında çalıştı; gerçek veride F3 (09:01:27), F6 (09:01:46) ve F5'i (09:02:46) parametre "
     "ve test dönemlerinde hesaplayıp gördü."),
    ("B6", "impl:patterns gerçek sonuçları SAHTE S0 ile keşif maskesinde hız/yapı ölçümü için kullandı (kalibrasyon kapısı "
           "tablosu ve bir yanlışlama çıktısı görüldü).",
     "DARALTILDI",
     "Doğru, yalnızca keşif maskesi ve sahte S0 (WF3:impl:patterns:68-106). Ayrıca görülen: 427 destekli hipotezin z "
     "dağılımı, Mod B kartı (n_koşul 895, isabet 29), Sorgu 2'nin 6 hipotezi için z (SONRAKI5_PUAN 4,80/−3,87), "
     "yanlışlamada gerçek koşullu oran (0,492 vs eşleştirilmiş 0,351). Gerçek S0 hiç kullanılmadı.",
     "impl:patterns yalnızca keşif döneminde gerçek sonuçları sahte S0 ile kullandı; kalibrasyon kapısı, bir yanlışlama, "
     "Mod B kartı, Sorgu 2 z değerleri ve destekli z dağılımı görüldü."),
    ("B7", "review:hazard (a2ea2325f3543961f) gerçek yapı + SİMÜLE sonuçlarla performans ölçtü.", "DOGRULANDI",
     "09:32:36–09:32:51, y yerine p0'dan simülasyon (WF3:review:hazard:229-230); ayrıca 09:03:14 sonuç-koşulsuz yapısal "
     "kontrol (satır 58-59).", ""),
    ("B8", "review:anomaly (a0b9105a06dda0652?) gerçek veride anomali işaretlerini hesapladı (tanımlayıcı).",
     "DARALTILDI",
     "Kimlik meta dosyasıyla doğrulandı. Ek: gerçek veride görülen işaret oranından (%0,62) sonra kural değiştirildi; "
     "düzeltme sonrası araştırma maskesi sayıları (845/761, açıklanamayan 635) resmi sonuçla aynı (09:29:52, "
     "WF3:review:anomaly:102). impl:anomaly de 08:54:31'de gerçek veride çalıştırmıştı (beyanda yok).",
     "review:anomaly ve impl:anomaly gerçek veride anomali işaretlerini hesapladı; resmi sayılar (845/761/635) "
     "09:29:52'de görüldü; kural gerçek veride tespit edilen aşırı işaretlemeden sonra düzeltildi."),
    ("B9", "review:models (a0d0195ca5ffc05a8?) gerçek veride F3/F5/F6'yı yeniden hesapladı; S0p tanımını bu inceleme sırasında "
           "değiştirdi (≈09:35–09:58).",
     "DARALTILDI",
     "Kimlik doğrulandı. Sıra: 09:43:37 eski S0p ile gerçek F3 (S1/GALIBIYET OUT_OF_SAMPLE_SUPPORTED, 7b/5 geçti), "
     "09:45:12 gerçek veride sıcaklıklı kontrol karşılaştırması (test dahil), 09:45:53 sentetik gösterim, 09:46:11 kod "
     "değişikliği, 09:47:03 yeni S0p ile NO_ADDED_VALUE, 09:57:09 tam F3/F5/F6 (WF3:review:models:183-291). Yani "
     "değişiklik gerçek test sonuçları görüldükten sonra ve gerçek veri karşılaştırmasıyla seçildi.",
     "review:models S0p'ye S0 sıcaklığını 09:46:11'de, gerçek veride F3 test sonuçlarını (eski S0p ile destekli) ve "
     "alternatifi gerçek veride karşılaştırdıktan sonra ekledi."),
    ("B10", "09:37:02 ön-görülme beyanı (experiments.jsonl).", "DOGRULANDI",
     "EXP:11 zaman_utc 09:37:02. İçerik notu: beyan review:models bitmeden yazıldı; S0p değişikliği, anomali sayılarının "
     "görülmesi, inceleme dışındaki map:engine tablosu kapsamda değil.", ""),
    ("B11", "Orkestratör 09:4x'te hazard 7b/5 piyasa kontrolüne S0 sıcaklığı ekledi (F4 gerçek sonucu görülmeden).",
     "DUZELTILDI",
     "Değişiklik 10:01:59 (ANA:4157 'Add S0 temperature to hazard market check'), review:models sonucunun okunmasından "
     "(10:01:20, ANA:4125) sonra; öneri review:models'in gerçek F3 incelemesinden doğdu (JRN remaining_risks). F4'ün "
     "gerçek sonucu bu anda hiçbir ajanca hesaplanmamıştı (yalnızca yapısal/simüle) → 'F4 görülmeden' kısmı doğru.",
     "Orkestratör 10:01:59'da, review:models'in (gerçek F3 test incelemesinden doğan) önerisi üzerine hazard 7b/5'e S0 "
     "sıcaklığı ekledi; F4 gerçek sonucu o sırada görülmemişti."),
    ("B12", "10:07:59 uygulama kararları ön-kaydı (sha a85fa19e…), commit 398b60b.", "DOGRULANDI",
     "EXP:12 zaman 10:07:59, kararlar_sha256 a85fa19e…; commit 398b60b 10:07:59 (git show). Kayıt içindeki git alanı "
     "289854e (kayıt yazılırken HEAD).", ""),
    ("B13", "10:08:10–10:45:40 resmi çalıştırma (F7→F1→F2→F3→F4→F5→F6→anomali). F1/F2/F4/F7 sonuçları ilk kez burada "
            "görüldü (orkestratör açısından).",
     "DARALTILDI",
     "Zaman ve sıra: JSON manifest zaman_utc 10:08:10, bitis_utc 10:45:40; EXP:13-19 sırası. Gerçek S0'a göre F1/F2/F4/F7 "
     "istatistiği öncesinde hesaplanmadı (f1f2f4_on_temas_taramasi.txt). Ancak orkestratör 09:36:20'de impl:patterns'in "
     "sahte-S0 keşif çıktılarını (kapı, yanlışlama) okudu (ANA:4045).",
     "F1/F2/F4/F7'nin gerçek S0'a göre istatistikleri ilk kez resmi çalıştırmada hesaplandı; keşif döneminde sahte S0 "
     "ile F1/F2 türü çıktılar daha önce görülmüştü."),
    ("B14", "10:56 commit 01b7e9f: sonuçlar + TEST_OPENED sabiti + ayna eşlemesi.", "DOGRULANDI",
     "git show 01b7e9f: 10:56:18; research.py TEST_OPENED, prematch.py/ui_summary ayna eşlemesi. Not: bu değişiklikler "
     "kod özetini 8ca41041…→36ca6d11… yaptı (kod_ozeti_cikti.txt); HEAD ile yeniden çalıştırma 'temiz değil' sayılır.", ""),
]
with open(os.path.join(O, "beyan_dogrulama.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["no", "beyan", "durum", "kanit", "onerilen_ifade"])
    w.writerows(R)
print(len(R))

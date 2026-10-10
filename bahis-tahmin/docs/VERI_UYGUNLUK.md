# Ortak veri uygunluk kontrolü (`veri-uygunluk-v2`, S3-GATE-02)

Sürüm geçmişi: `veri-uygunluk-v1` (S3-GATE-01) → `veri-uygunluk-v2` (S3-GATE-02: kesin takım kimliği, bağımsız
katılımcılarla doğrulanan takvim aralığı, "yerel analiz" istisnası olmadan işlem kapsamlı kaynak hakları). v1
sonuçları karar denetiminde v2 ile eşleşmez (`BAGLAM_UYUSMUYOR`); eski kayıtlar olduğu gibi okunur.

Amaç: güncel olmayan, eksikliği bilinen veya uygunluğu doğrulanamayan verinin uygulamanın **hiçbir kullanıcıya
dönük yolunda** güvenilir tahmin veya bahis adayı gibi sunulmasını engellemek. Kod: `bahis_tahmin/eligibility.py`
(tek merkezi kontrol; ekranlar ve CLI kendi kopyalarını kurmaz). Bu kontrol olasılık hesaplamaz ve modelin
matematiğini değiştirmez.

## İki ayrı soru

| Alan | Soru |
|---|---|
| `forecast_ok` | Bu maç/pazar için veri ve zaman açısından tahmin üretilebilir ve gösterilebilir mi? |
| `bet_ok` | Veri ve kaynak hakları açısından bahis adayına engel kalmadı mı? |

`bet_ok` yalnızca **veri** koşulunun geçildiğini söyler. Model doğrulaması (`MODEL_NOT_VALIDATED`), gerçek ve zamanı
doğrulanmış oran, belirsizlik, sonuçlandırma kuralı ve yoğunlaşma sınırları karar motorunda ayrıca uygulanır.
Örnek: veri uygun ama oran yok → tahmin gösterilir/ölçüm kaydı yazılabilir, karar `ODDS_UNAVAILABLE`; veri uygun ama
model doğrulanmamış → deneysel kayıt (stake 0), karar `MODEL_NOT_VALIDATED`.

## Sonuç sözleşmesi (`Eligibility`)

Aday/maç kimliği (`candidate_id`, `canonical_id`), pazar, gerçek değerlendirme anı (`evaluated_at`), bilgi kesimi
(`info_cutoff`), veri kesimi (`data_cutoff`), veri kapsamı ve özeti (`data_scope`: lig maç sayısı, kaynaklar, kapsam
kanıtları, kontrol edilen takım/dönem, ayrıntı), kullanılan model durumunun kapsamı ve sürümü (`state_scope`: özellik
sürümü, model eğitim kesimi, lig ve takım durumunun son maçı, durum özeti, eğitim kaynakları), güncellik
(`freshness`), süreklilik (`continuity`), takım eşleme (`team_mapping`), gerekli alanlar (`required_fields`), kaynak
kullanım durumu (`source_use`), bütün neden kodları (`reasons`), birincil açıklama ve gereken düzeltme
(`primary_text`, `fix_text`), politika sürümü (`policy_version`) ve parmak izi (`fingerprint`).

## Güncellik

- `VERIFIED_CURRENT`: ilgili kapsamın güncelliği kanıtla doğrulandı.
- `KNOWN_STALE`: tamamlanmış ve erişilebilir olması beklenen maçların eksik olduğu biliniyor.
- `UNKNOWN`: doğrulamaya yeterli kanıt yok. **UNKNOWN hiçbir zaman uygun değildir.** Kontrol çağrılmamışsa veya
  bağlam verilmemişse sonuç `BAGLAM_YOK` (uygun değil) olur; karar motoru bağlamsız çağrıda `DATA_NOT_ELIGIBLE` döner.

Kararlar yalnızca yapılandırılmış neden kodlarından türetilir; açıklama metinlerinde ifade aranmaz (motor, veri
notlarının yanında `GoalPrediction.data_codes` üretir).

## Gerekli kanıtlar

1. **Model durumu ↔ veri deposu** (kontrol edilen veri, KULLANILAN veriye bağlanır). Tahmin, modelin eğitimde donan
   lig/takım durumundan üretilir. Motor eğitimde her lig durumunun kurulduğu maç kümesinin kimliğini (sayı + SHA-256;
   `row_digest`; gün, takımlar ve motorun tükettiği skor/oran alanları — skor düzeltmesi de fark yaratır) durum
   nesnesine yazar. Kontrol, depoda modelin işleyeceği aynı dönemin satırlarıyla bunu **birebir**
   karşılaştırır: depoda daha fazla satır varsa `DURUM_DEPODAN_GERIDE` (KNOWN_STALE; ör. eski sezon eklenip model
   yeniden eğitilmedi), farklı küme varsa `DURUM_VERIYLE_UYUSMUYOR` (UNKNOWN). Durumun son gününden sonraki ve takım
   pencerelerindeki eksikler de ayrıca sayılır. Bu köken bilgisi olmayan **eski model dosyaları** için bilgi
   uydurulmaz ve dosya güncellenmez: `DURUM_KOKENI_YOK` (UNKNOWN) — modelin yeniden eğitilmesi gerekir. Gol modeli
   karantinadaki kayıtları işlemediği için karşılaştırmada da sayılmaz. Model parametrelerinin eğitim tarihi tek başına
   engel değildir. Karar ve gösterim anında tahmin ile uygunluk sonucunun **aynı durumdan** geldiği durum özetiyle
   doğrulanır (`BAGLAM_UYUSMUYOR`).
2. **Veri deposu ↔ kaynak takvimi.** Ligin sezon takvimi (openfootball, CC0; veri güncellemesinin önbelleğe aldığı
   içinde bulunulan ve önceki iki sezon dosyaları; yeni indirme yok) ile takımların geçmiş maçları takım düzeyinde
   karşılaştırılır. Kontrol
   depodaki son tarihle sınırlı değildir: ligin yeni maçları depoda olsa bile takımın daha eski bir maçı eksikse
   `DEPODA_EKSIK_MAC` (KNOWN_STALE). Ertelenen/iptal edilen maçlar eksik sayılmaz; geçmiş tarihli ama sonucu ne
   kaynakta ne depoda olan maç `KAYNAK_DURUMU_BELIRSIZ` (UNKNOWN). Kaynaktaki ad eşleşmezse "eksik" değil
   `KAYNAK_ESLESME_BELIRSIZ` (UNKNOWN). Tamlığı kanıtlanmamış (kısmi) takvim de kaynakta tamamlanmış görünüp depoda
   olmayan maçı `DEPODA_EKSIK_MAC` olarak bildirir, ama "eksik yok" iddiası üretmez. Ters yön: doğrulanmış takvim
   aralığında depoda olup kaynakta olmayan maç iki sağlayıcının çeliştiğini gösterir (`KAYNAK_DEPO_CELISKISI`,
   UNKNOWN). Depoda kaydı olan ama skoru geçersiz olduğu için karantinada kalan (modelin
   kullanmadığı) maç, kaynak takvimi olsun olmasın, son 365 gün içindeyse `DEPODA_GECERSIZ_SKOR` (KNOWN_STALE). Başka takımlara ait eksikler yalnızca paylaşılan lig durumu
   gerçekten etkileniyorsa engeldir: oran **her kaynak sezonu için ayrı** ve yalnızca son 365 gün içinde hesaplanır;
   herhangi bir sezonda eksik sayısı max(1, %5 × maç) sınırını aşarsa `LIG_DURUMU_EKSIK`, aşmazsa bilgi kodu
   `LIG_DURUMU_KISMEN_EKSIK` (ek sezon kanıtı eşiği seyreltemez; sezon başındaki küçük örneklemde tek maç bütün ligi
   engellemez). İlgisiz bir ligdeki eksik başka ligi etkilemez.
3. **Kapsam (v2: A ve B ayrı).** Kaynak dosyasının kendi takım sayısı kendi tamlığının kanıtı değildir (v1 bunu
   dosyadan çıkarıyordu: daha büyük ligin 4 takımlık, kendi içinde kusursuz alt kümesi "tam" görünürdü).
   - **Bağımsız katılımcı listesi:** aynı sezonun veri deposundaki takımları (başka sağlayıcı). Kaynak adlarının
     tamamı kesin kimlikle eşlenmeli ve bu listeye birebir eşit olmalıdır; liste yoksa (ör. yeni sezonun ilk maçı
     depoda değilse) tamlık kanıtlanmaz.
   - **Tekilleştirme:** kaynak maç kimliği varsa onunla, yoksa (tur etiketi, tarih, ev, deplasman) anahtarıyla.
     Birebir tekrar sayımı artırmaz; aynı anahtarla farklı içerik çakışmadır, birleştirilmez ve o turu doğrulanmamış
     yapar. Farklı turlardaki aynı eşleşme (ikinci devre) ayrı maçtır.
   - **B — gerekli geçmiş aralığın tamlığı:** 1. turdan başlayıp ardışık her numaralı turun ("Matchday 7" vb.)
     katılımcıların tam eşleşmesi olduğu (her takım turda bir kez; ertelenen/iptal kaydı, yenisi varsa sayılmaz)
     turlardan kurulur. Eksik turdan sonrası, numarasız aşamalar (play-off, split) ve doğrulanmamış bir maçın tarihi
     aralığa girmez. Gelecek fikstürlerin yayımlanmamış olması B'yi tek başına reddetmez.
   - **A — tam sezon takvimi:** B'ye ek olarak bütün listelenen maçlar doğrulanmış, tur sayısı lig formatına (takım
     başına `expected_per_team`; split'li liglerde normal sezon sonrası aşama da listelenmiş) ve eşleşme yapısına
     (her ikili beklenen sayıda; çift devrede her yön bir kez) uyuyor. Format bağımsız katılımcı sayısıyla tutarsızsa
     (ör. bugünkü 12 takım/33 tur formatı 10 takımlı eski sezona) A kurulmaz; bugünkü format geçmiş sezonlara
     zorlanmaz. Takım başına sayı tek başına rakip/iç-dış saha dağılımını kanıtlamaz. Normal sezondan sonra
     split/play-off aşaması olan liglerde (`POST_STAGE_LEAGUES`: SC0, B1, G1, AUT, DNK, SWZ; bugünkü format, yalnızca
     daha sıkı sonuç verir) listelenen takvim sezon sonunu kanıtlamaz: A kurulmaz, sezonlar arası köprü yoktur.
   - **Pencere:** takımın gerekli penceresi (bilgi kesiminden önceki 365 gün; süre kısaltılmadı ve depodaki ilk maç
     pencereyi kısaltamaz — önceki sezonları eksik depo daha "uygun" görünmez; ligde yeni takımın önceki dönemi,
     takımın yer almadığı doğrulanmış lig takvimiyle kapsanır) B aralıklarıyla kapsanmalıdır. Ardışık iki sezon
     arasındaki ara yalnızca önceki sezonun listelenen takvimi sonuna kadar doğrulandıysa (A) ve arada (bilgi
     kesiminden önce) ne depoda ne kaynakta maç yoksa
     kapsanır; yeni sezonun takviminde bilgi kesiminden önce maç yoksa (sezon başlamadı, 1. tur var) ara bilgi
     kesimine kadar kapsanır. Takvimde maç olmayan aralık (millî maç arası) veri hatası sayılmaz.
   - **Depo-içi kanıt kaldırıldı:** v1'deki "depoda tam çift devreli kapanmış sezon" kanıtı takım sayısını depodan
     çıkardığı için (eksik takım/alt küme görünmez) artık kabul edilmez; önceki sezon için de kaynak takvimi gerekir.
   Kaynak yoksa (`KAYNAK_KAPSAMI_YOK`), boş/bozuk/kısmî veya bağımsız katılımcıyla doğrulanamıyorsa
   (`KAYNAK_KAPSAMI_KISMI`) ya da pencere kapsanmıyorsa (`KAYNAK_ARALIK_DISI`) sonuç UNKNOWN'dır; "eksik maç yok"
   iddiası (`data_scope.kontrol`) yalnızca doğrulanmış takvimle üretilir. `data_scope.kapsam_kanitlari` A (`tam`) ve
   B (`gecmis_aralik_kaniti`) sonuçlarını ve bağımsız katılımcı sayısını ayrı gösterir. Mevcut 21 günlük eşik (v1)
   yalnızca yaş göstergesi olarak kalır; tek başına eksiksizlik kanıtı değildir.
4. **Gerekli alanlar (gerçek model bağımlılığı).** Gol modeli üç pazarı da yarı bazlı takım güçlerinden üretir
   (`goals.model.REQUIRED`); bu yüzden ilk yarı verisi eksikse 3,5 Üst de tahmin edilemez (`GEREKLI_ALAN_EKSIK`),
   oysa 3,5 Üst'ün sonucu yalnızca maç sonu skoruyla etiketlenebilir. 1X2 motoru ilk yarı verisine bağlı değildir.
   Son 365 günde ligde 10 maçtan az geçmiş `TAKIM_GECMISI_YETERSIZ`; ligde düşük ilk yarı skoru kapsamı
   (`LIG_IY_ORANI_DUSUK`) yalnızca bahis adayını engeller. Geçersiz olasılık (NaN/sonsuz/[0,1] dışı) yalnızca ilgili
   pazarı engeller (`OLASILIK_GECERSIZ`).

5. **Takım kimliği (v2, `data/teams.py`, `takim-eslesme-v2`).** Kesin kimlik yalnızca bağlamda (ligin son iki
   sezonundaki takımlar) normalleştirilmiş adı **benzersiz** tam ad veya kapsamı (kaynak openfootball + lig ülkesi)
   tutan doğrulanmış takma adla kurulur. Aynı normalleştirilmiş ada sahip birden çok aday ya da aynı dosyada aynı
   takıma düşen birden çok farklı ad (doğrulanmış takma adlar hariç) **belirsizdir**; son/alfabetik/sıradaki aday
   seçilmez. Önek ve benzerlik yalnızca öneridir. Boş ad ve tek harfli parça kimlik kanıtı değildir; rezerv/II/B,
   U21/U19, kadın takımı ayrımları korunur (öneri de olmaz). Unicode/Türkçe harfler (ı, İ, ş, ğ, ø, ß…) ASCII'ye
   kayıpsız indirgenir. Ev sahibi ve deplasman aynı takıma eşlenmez. Eşleşmeyen fikstür düşmez: ham adlar,
   eşleme durumu (`BULUNAMADI`/`BELIRSIZ`/`AYNI_TAKIM`), eşleme sürümü, öneriler ve (varsa) kaynak maç kimliği
   `data_meta.json → eslesmeyen_fikstur` içinde saklanır; eşlenen openfootball fikstürü `raw_home`, `raw_away`,
   `eslesme` (sürüm + dayanak) sütunlarını taşır. Uygunluk anında başka kaynaktan eşlenmiş fikstürün kimliği aynı
   kaynak dosyasında güncel eşleyiciyle yeniden kurulur; kurulamıyorsa (eski eşleyicinin kaydı, dosya yok)
   `TAKIM_ESLESMESI_DOGRULANAMADI` (UNKNOWN) — eski kayıtlar yeni eşleyiciden geçmiş sayılmaz, toplu yeniden
   yazılmaz. Sezon bazlı takma ad yoktur: aynı adı taşıyan yeniden kurulmuş kulüp addan ayırt edilemez (sınır).

## Zaman kuralı

- Ayrı alanlar: tahminin/uygunluğun fiilen hesaplandığı an (`evaluated_at` / `hesaplama_ani`), kaydın yazıldığı an
  (defterin `created_at`'i), hedef karar anı (maç günü 00:00 İstanbul; değiştirilmedi), o anda bilinen başlama zamanı
  ve bilgi kesimi.
- Bilgi kesimi: değerlendirme anının İstanbul tarihi `D`. Yalnızca `D`'den ÖNCEKİ günlerin sonuçları erişilebilir
  sayılır; bitiş/yayın saati bilinmediği için aynı günün sonuçları beklenmez. Model durumu `D` veya sonrasına
  tarihli maç içeriyorsa ve durumun değerlendirme anından önce var olduğu bilinmiyorsa (`state_available_since`:
  eğitim anı; dosyadan yüklenen modelde dosyadaki değer kullanılmaz, yükleme anıyla değiştirilir)
  `DURUM_KARAR_ANINDAN_SONRA`. Kaynak ile depo arasındaki ±3 günlük tarih toleransı bilgi kesimi sınırında da
  uygulanır (aynı maçın yerel tarih farkı "eksik" sayılmaz).
- Uygunluk sonucu yalnızca değerlendirildiği **gün** (bilgi kesimi), maç, pazar ve model durumu için geçerlidir. Karar
  motoru ve ekranlar bunu her kullanımda denetler: gün değişince önceki günün "uygun" sonucu ne olasılık göstermek ne
  de karar için kullanılır (`BAGLAM_UYUSMUYOR`). Uygulama açıkken dakikalık denetim ve sayfa geçişleri gün değişimini
  yakalayıp uygunluğu yeniden değerlendirir; değerlendirme bitene kadar önceki günün sonucu gösterilmez. Model veya
  veri değişince maç analizi paneli sıfırlanır; kayıt yalnızca güncel motorun aynı lig durumundan gelen tahminle ve
  kararlar kayıt anında yeniden üretilerek yapılır. Karar anından SONRA
  değerlendirilmiş bir sonuç o kararın kanıtı olamaz.
- Kaynak dosyası değerlendirme anından sonra alınmışsa o anın kanıtı olamaz (`KAYNAK_KARAR_ANINDAN_SONRA`). Kaynakta
  "tamamlandı" görünmesi, ancak alınma anı itibarıyla kanıttır; eski bir dosya son günlerin maçlarını doğrulayamaz.
- Bütün karşılaştırmalar bilgi kesimiyle sınırlandığından depoya sonradan eklenen sonuçlar geçmiş bir as-of
  değerlendirmesini değiştirmez.

## Kaynak hakları (v2: işlem kapsamları, "yerel analiz" istisnası yok)

`data/source_registry.py` içindeki `USE_RIGHTS` kayıt metinlerinin yapılandırılmış hâlidir (yeni hak verilmedi).
Ayrı alanlar: kullanıcı indirme onayı (ayarlar), kaynak erişim koşulları (`erisim_kosullari`), sonuç verisinin
analizde kullanımı (`sonuc_kullanimi`), model eğitimi (`model_egitimi`), mevcut modelin kullanımı (`model_kullanimi`),
ticari kullanım (`ticari_kullanim`), yeniden dağıtım (`yeniden_dagitim`) ve kaynağın uygulamada sağladığı veri türleri
(`saglar`). İşlemlerin gerektirdiği kapsam (`eligibility.OPERATION_SCOPES`):

| İşlem | Gerekli | Gerekmeyen (engel değil) |
|---|---|---|
| Kullanıcıya tahmin/olasılık gösterme, FORECAST_RECORD | erişim onayı; sonuç verisinde `sonuc_kullanimi`; modelin eğitim verisinde `model_egitimi` + `model_kullanimi`; modelin eğitim kaynağı kökeni kayıtlı | ticari kullanım, yeniden dağıtım |
| Bahis adayı / sanal stake | tahminle aynı (ek: model doğrulaması, oran vb. karar motorunda) | ticari kullanım, yeniden dağıtım |
| Gerçek veriyle model eğitimi (CLI `train`/`gol-egit`/`dizi-arastir`, arayüz eğitimi ve güncelleme sonrası otomatik eğitim) | erişim onayı; eğitim verisinin her satırının kaynağı kayıtlı; `sonuc_kullanimi` + `model_egitimi` (eğitilen modelin *kullanımı* tahmin anında ayrıca `model_kullanimi` ister) | ticari kullanım, yeniden dağıtım |
| İndirme | kullanıcı onayı (değişmedi) | — |

- v1'deki **"yerel analiz" istisnası kaldırıldı**: belgelenmemiş sonuç kullanımı/model eğitimi/model kullanımı artık
  tahmini de engeller (`KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI`, `KAYNAK_EGITIM_HAKKI_DOGRULANAMADI`,
  `KAYNAK_MODEL_KULLANIMI_DOGRULANAMADI`; hepsi "tahmin" engeli). Eğitim kaynağı kökeni olmayan model
  `MODEL_EGITIM_KOKENI_YOK` (eski dosyaya köken uydurulmaz; boş köken listesi de bilinmeyen köken sayılır). Kaynak
  etiketi olmayan veri satırı `KAYNAK_HAKKI_BILINMIYOR`; motorlar etiketsiz eğitim satırını kökende açıkça
  `etiketsiz` olarak kaydeder. Engel varken nedenli, olasılıksız kayıt ve kaynak kapsamı
  açıklaması gösterilir; tahmin/olasılık, bahis adayı, stake ve gerçek veriyle eğitim yoktur. Mevcut dosyalar ve
  kayıtlar silinmez.
- Kullanıcının onayı (arayüz kutusu, `update --accept-terms`) yalnızca indirmeyi (erişimi) kapsar. Onay kutusu,
  bayrak veya etiket bu kontrolü aşamaz: kayıtlı olmayan etiket `KAYNAK_HAKKI_BILINMIYOR`; bir kaynağın hakkı yalnızca
  o kaynağın uygulamada gerçekten sağladığı veri türü için geçerlidir (yalnızca fikstür sağlayan CC0 kaynağın
  etiketini taşıyan sonuç satırı `KAYNAK_ETIKETI_UYUMSUZ`). GitHub yedeğinin depo lisansı (MIT) asıl kaynağın
  haklarını kanıtlamaz.
- football-data.co.uk belgeleri (`data.php`, `contact.php`) 2026-10-10'da bu ortamdan açılamadı (ad çözümlenemedi);
  belge okunamadığı için hiçbir alan izinli sayılmadı. Engeli kaldırmanın tek yolu kaynağın lisans/izin belgesinin
  kayda (`belge` alanıyla) eklenmesidir. Bu bir hukuki ihlal tespiti değildir.

## Kullanıldığı yollar

| Yol | Nasıl |
|---|---|
| Toplu fikstür (gol) | `goals.service.gated_goal_predictions` → arayüz taraması, CLI `gol-tahmin` |
| Tek maç / elle seçim (gol) | `goals.service.gated_goal_match` → Maç analizi sekmesi |
| A/B/C ve tamamlayıcı Alt/Hayır kararları | `decisions_for(..., eligibility=...)` → `decide()` (`DATA_NOT_ELIGIBLE`) |
| BET_CANDIDATE_RECORD / KARAR_KAYDI | `record_decisions`: aday kaydı ve sanal stake yalnızca veri uygunsa ve karar kayıt anında hâlâ geçerliyse (aynı gün, maç başlamadan); arayüz kararları kayıt anında yeniden üretir; olasılık yalnızca tahmin uygunsa |
| FORECAST_RECORD | `forecast_log.build_forecast_records(ctx=...)` (protokol `ileriye-donuk-olcum-v3`) |
| Gerçek veriyle eğitim | `eligibility.training_rights_codes` → CLI `train`/`gol-egit`/`dizi-arastir` (çıkış 3), arayüz yeniden eğitimi ve güncelleme sonrası otomatik eğitim |
| 1X2 tahmin listesi, en olası, gösterge paneli, maç ayrıntısı, maç analizi | `eligibility.gated_match_predictions` / `gate_match_prediction`; `MatchPrediction.value_rows` uygunluk olmadan değer/stake üretmez |
| CLI `predict`, `en-olasi` | aynı bağlayıcı |
| Sanal takip CSV dışa aktarımı | `goals.service.ledger_rows` / `ledger_csv` (NaN/sonsuz boş hücre; uygunluk sütunu) |

Uygunluk engelliyse: olasılık ve ondan türetilen değerler (belirsizlik aralığı, güvenli olasılık, gereken en düşük
oran) gösterilmez (boş; **sıfır değil**), değer önerisi ve sanal stake yoktur, liste
sıralamasında en sona düşer, durum metinle yazılır (Kullanılabilir / Doğrulanamıyor / Eksik veri / Uygun değil) ve
somut neden, veri kesimi ile gereken düzeltme gösterilir. Eşleşmeyen takımlı fikstürler düşürülmez: veri deposu ham
adları saklar (`data_meta.json` → `eslesmeyen_fikstur`); kaynak, lig, tarih ve ham adlardan kararlı bir **aday
kimlik** (`aday:…`, kanonik maç kimliği değildir) ile üç pazar için `TAKIM_ESLESMEDI` sonucu üretilir.

## Önbellek

`EligibilityContext.fingerprint` veri deposu, model durumu, kaynak dosyaları (özet, alınma anı, eşleme sürümü,
doğrulanmış aralıklar, bağımsız katılımcı sayısı), haklar, politika ve eşleme sürümünden türetilir; sonuçlar bu parmak
izi + eşleme sürümü + maç + pazar + kaynak etiketi + bilgi kesimi + o anda kullanılabilir kaynak dosyaları ile
önbelleklenir. Arayüz denetleyicisi bağlamı veri
deposu, motor, kaynak dosyalarının değişiklik zamanı/boyutu, onaylar ve gün değişince yeniden kurar.

## Bilinen sınırlar

- openfootball 2026-27'de 22 ligin yalnızca 8'i için dosya sunar; diğer liglerde güncellik **doğrulanamaz**
  (`KAYNAK_KAPSAMI_YOK`) ve tahmin gösterilmez. Başka bir tam takvim kaynağı eklenmeden bu ligler açılmaz.
- Önceki sezon dosyası önbellekte yoksa (veri güncellemesi yalnızca içinde bulunulan sezonu indirir; yeni toplu
  indirme eklenmedi) 365 günlük pencere kanıtlanamaz: UNKNOWN (`KAYNAK_ARALIK_DISI`).
- Hem kaynakta hem depoda bulunmayan sezon sonu aşamaları (play-off) tespit edilemez; köprü yalnızca ikisinin de
  ara dönemde maç göstermediği durumda kurulur.
- Maç bitiş saatleri bilinmediği için aynı günün sonuçları kullanılmaz; gece eğitilen bir model, durum o gün
  içindeki maçları içeriyorsa ve geçmiş bir an için değerlendiriliyorsa engellenir.
- Kesin kimlik kuralı gerçek openfootball adlarının bir kısmını (ör. "X City FC" ↔ "X") yalnızca öneriye düşürür;
  bunlar için doğrulanmış takma ad gerekir (öneri kimlik kanıtı değildir).
- S3-GATE-01'den önce eğitilmiş model dosyalarında durum köken bilgisi yoktur (`DURUM_KOKENI_YOK`); bu modellerle
  tahmin gösterilmez, yeniden eğitim gerekir (otomatik eğitim başlatılmaz).
- S1/S2 dizi araştırması ve geriye dönük test ekranları geçmiş veri üzerinde araştırmadır; bu kontrolle yeniden
  etiketlenmedi.

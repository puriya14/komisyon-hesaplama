# Ortak veri uygunluk kontrolü (`veri-uygunluk-v1`, S3-GATE-01)

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
2. **Veri deposu ↔ kaynak takvimi.** Ligin tam sezon takvimi (openfootball, CC0; veri güncellemesinin önbelleğe aldığı
   içinde bulunulan ve önceki sezon dosyaları) ile takımların geçmiş maçları takım düzeyinde karşılaştırılır. Kontrol
   depodaki son tarihle sınırlı değildir: ligin yeni maçları depoda olsa bile takımın daha eski bir maçı eksikse
   `DEPODA_EKSIK_MAC` (KNOWN_STALE). Ertelenen/iptal edilen maçlar eksik sayılmaz; geçmiş tarihli ama sonucu ne
   kaynakta ne depoda olan maç `KAYNAK_DURUMU_BELIRSIZ` (UNKNOWN). Kaynaktaki ad eşleşmezse "eksik" değil
   `KAYNAK_ESLESME_BELIRSIZ` (UNKNOWN). Depoda kaydı olan ama skoru geçersiz olduğu için karantinada kalan (modelin
   kullanmadığı) maç, kaynak takvimi olsun olmasın, son 365 gün içindeyse `DEPODA_GECERSIZ_SKOR` (KNOWN_STALE). Başka takımlara ait eksikler yalnızca paylaşılan lig durumu
   gerçekten etkileniyorsa engeldir: oran **her kaynak sezonu için ayrı** ve yalnızca son 365 gün içinde hesaplanır;
   herhangi bir sezonda eksik sayısı max(1, %5 × maç) sınırını aşarsa `LIG_DURUMU_EKSIK`, aşmazsa bilgi kodu
   `LIG_DURUMU_KISMEN_EKSIK` (ek sezon kanıtı eşiği seyreltemez; sezon başındaki küçük örneklemde tek maç bütün ligi
   engellemez). İlgisiz bir ligdeki eksik başka ligi etkilemez.
3. **Kapsam.** Takımın gerekli penceresi (bilgi kesiminden önceki 365 gün, ligdeki ilk maçından erken değil) kanıtla
   kapsanmalıdır: tam kaynak sezon takvimi veya depoda **sezon düzeyinde** tam kapanmış, yapısı kesin bilinen düz çift
   devreli sezon (her eşleşme tam bir kez iç saha, her takım tam 2·(n−1) maç; daha zayıf, iç tutarlılık kanıtı).
   Split/play-off'lu liglerde (`sequences.timeline.REGULAR_LEN_OVERRIDE`) toplam maç sayısı depodan bilinemediği için
   depo-içi kanıt kabul edilmez; kaynak takvimi gerekir. Ardışık iki kapsanmış sezon arasındaki ara (sezon arası) ve takvimde maç olmayan
   aralık (millî maç arası) veri hatası sayılmaz. Kaynak yoksa (`KAYNAK_KAPSAMI_YOK`), boş/bozuk/kısmîyse
   (`KAYNAK_KAPSAMI_KISMI`) veya pencere kapsanmıyorsa (`KAYNAK_ARALIK_DISI`) sonuç UNKNOWN'dır; "eksik maç yok"
   iddiası (`data_scope.kontrol`) yalnızca tam takvimle üretilir. Mevcut 21 günlük eşik (v1) yalnızca yaş göstergesi
   olarak kalır; tek başına eksiksizlik kanıtı değildir.
4. **Gerekli alanlar (gerçek model bağımlılığı).** Gol modeli üç pazarı da yarı bazlı takım güçlerinden üretir
   (`goals.model.REQUIRED`); bu yüzden ilk yarı verisi eksikse 3,5 Üst de tahmin edilemez (`GEREKLI_ALAN_EKSIK`),
   oysa 3,5 Üst'ün sonucu yalnızca maç sonu skoruyla etiketlenebilir. 1X2 motoru ilk yarı verisine bağlı değildir.
   Son 365 günde ligde 10 maçtan az geçmiş `TAKIM_GECMISI_YETERSIZ`; ligde düşük ilk yarı skoru kapsamı
   (`LIG_IY_ORANI_DUSUK`) yalnızca bahis adayını engeller. Geçersiz olasılık (NaN/sonsuz/[0,1] dışı) yalnızca ilgili
   pazarı engeller (`OLASILIK_GECERSIZ`).

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

## Kaynak hakları

`data/source_registry.py` içindeki `USE_RIGHTS`, mevcut kayıt metinlerinin yapılandırılmış hâlidir (yeni hak verilmedi):
erişim (kullanıcı onayı), sonuç verisini kullanma, model eğitimi ve yeniden dağıtım ayrı alanlardır.

- Tahmin (yerel, kişisel analiz; dağıtılmaz) için kaynağa **erişim izni** gerekir (`KAYNAK_ERISIM_IZNI_YOK`);
  kayıtlı olmayan kaynak `KAYNAK_HAKKI_BILINMIYOR`.
- Bahis adayı için **sonuç kullanımı** ve **model eğitimi** haklarının belgeyle doğrulanması gerekir
  (`KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI`, `KAYNAK_EGITIM_HAKKI_DOGRULANAMADI`). Model eğitim kaynakları model
  dosyasının manifestinden okunur; yoksa depodaki bütün kaynaklar varsayılır.
- Kullanıcının uygulamadaki onayı veya `update --accept-terms` yalnızca erişimi açar; bu alanları doğrulanmış
  yapmaz. Komut satırında uygunluğu atlatan bir bayrak yoktur.
- **Politika kararı (kullanıcı onayına açık):** football-data.co.uk ve GitHub yedeği için sonuç kullanımı ve model
  eğitimi hakkı belgelenmediğinden, bu verilerle eğitilen modellerden **bahis adayı üretilmez**; tahminler yerel
  analiz olarak (stake 0) gösterilebilir. Engeli kaldırmak için kaynağın lisans/izin belgesi `USE_RIGHTS`'a
  (`belge` alanıyla) eklenmelidir. Bu bir hukuki ihlal tespiti değildir.

## Kullanıldığı yollar

| Yol | Nasıl |
|---|---|
| Toplu fikstür (gol) | `goals.service.gated_goal_predictions` → arayüz taraması, CLI `gol-tahmin` |
| Tek maç / elle seçim (gol) | `goals.service.gated_goal_match` → Maç analizi sekmesi |
| A/B/C ve tamamlayıcı Alt/Hayır kararları | `decisions_for(..., eligibility=...)` → `decide()` (`DATA_NOT_ELIGIBLE`) |
| BET_CANDIDATE_RECORD / KARAR_KAYDI | `record_decisions`: aday kaydı ve sanal stake yalnızca veri uygunsa ve karar kayıt anında hâlâ geçerliyse (aynı gün, maç başlamadan); arayüz kararları kayıt anında yeniden üretir; olasılık yalnızca tahmin uygunsa |
| FORECAST_RECORD | `forecast_log.build_forecast_records(ctx=...)` (protokol `ileriye-donuk-olcum-v2`) |
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

`EligibilityContext.fingerprint` veri deposu, model durumu, kaynak dosyaları (özet ve alınma anı) ve haklardan
türetilir; sonuçlar bu parmak izi + maç + pazar + bilgi kesimi + o anda kullanılabilir kaynak dosyaları ile
önbelleklenir. Arayüz denetleyicisi bağlamı veri
deposu, motor, kaynak dosyalarının değişiklik zamanı/boyutu, onaylar ve gün değişince yeniden kurar.

## Bilinen sınırlar

- openfootball 2026-27'de 22 ligin yalnızca 8'i için dosya sunar; diğer liglerde güncellik **doğrulanamaz**
  (`KAYNAK_KAPSAMI_YOK`) ve tahmin gösterilmez. Başka bir tam takvim kaynağı eklenmeden bu ligler açılmaz.
- Önceki sezon dosyası önbellekte yoksa önceki sezonun kapsamı depodaki sezonun tamlığından (iç tutarlılık) gelir.
- Maç bitiş saatleri bilinmediği için aynı günün sonuçları kullanılmaz; gece eğitilen bir model, durum o gün
  içindeki maçları içeriyorsa ve geçmiş bir an için değerlendiriliyorsa engellenir.
- Takım adı eşleyicisi (`data/teams.py`) bulanık eşleme yapar; yanlış eşleşme bu kontrolün dışındadır (bkz. rapor).
- S3-GATE-01'den önce eğitilmiş model dosyalarında durum köken bilgisi yoktur (`DURUM_KOKENI_YOK`); bu modellerle
  tahmin gösterilmez, yeniden eğitim gerekir (otomatik eğitim başlatılmaz).
- S1/S2 dizi araştırması ve geriye dönük test ekranları geçmiş veri üzerinde araştırmadır; bu kontrolle yeniden
  etiketlenmedi.

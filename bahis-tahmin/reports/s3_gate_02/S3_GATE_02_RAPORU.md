# S3-GATE-02 — Takım kimliği, kullanım kapsamı ve kaynak tamlığı düzeltmesi

Tarih: 2026-10-10. Başlangıç: `claude/bahis-tahmin` @ `6b1197f242feb70ae62ff98c545c5f7a49f63685` (yerel HEAD = uzak dal
ucu; çalışma ağacı temiz; `data/teams.py` blob `131fb4fbbdb669046d476703c254fc2894a57594`).
Politika: `veri-uygunluk-v2` ([`docs/VERI_UYGUNLUK.md`](../../docs/VERI_UYGUNLUK.md)). Eşleme sözleşmesi:
`takim-eslesme-v2` (`bahis_tahmin/data/teams.py`). Protokol: `ileriye-donuk-olcum-v3`
([`ileriye_donuk_protokol_v3.json`](ileriye_donuk_protokol_v3.json)); v1 ve v2 değiştirilmedi.

Bu çalışma model geliştirme, örüntü araması veya getiri iddiası değildir. Testler yalnızca açıkça sentetik veriyle ve
geçici dizinlerde çalışır. **Bu ortamda güncel gerçek veri yoktur**; gerçek veri güncellenmedi, model eğitilmedi,
defter bütünlüğü çözülmedi, kazanç kanıtı yoktur.

## İncelenen çağrı yolları

Eşleyici: `data/store.py::_update_fixtures` (openfootball fikstürü → depo adları) ve
`eligibility.coverage_from_openfootball` (kaynak takvimi → depo adları); başka çağıran yok (araştırma aracı dolaylı).
Kapsam: `cached_coverages` → `build_context` (CLI `_eligibility_ctx`, arayüz `eligibility_context`) →
`EligibilityContext.evaluate` (gol taraması, maç analizi, elle seçim, 1X2 listeleri, CLI `gol-tahmin`/`predict`/
`en-olasi`/`gol-olcum-kaydet`, karar ve kayıt yolları). Haklar: `source_registry.USE_RIGHTS` → `rights_from_registry`
→ `RightsStatus.codes`. Eğitim: CLI `train`, `gol-egit`, `dizi-arastir` (S0 modeli), arayüz `update_and_train`
(otomatik), `retrain`, `train_goal_engine`.

## Yeniden üretilen yanlış eşleşmeler (6b1197f)

| Çağrı | Önceki sonuç | Neden | Şimdi |
|---|---|---|---|
| `match_team("Foo FC", ["Takim F"])` | `"Takim F"` | tek harfli parça ("f") önek kanıtı sayıldı | `None` (öneri de yok) |
| `match_team("City", ["City FC", "City SC"])` | `"City SC"` | normalleştirilmiş anahtar çakışmasında sözlüğe son yazılan aday | `None`, `BELIRSIZ` (iki aday) |
| `match_team("City", ["City SC", "City FC"])` | `"City FC"` | aynı çakışma; sonuç aday sırasına bağlı | `None`, `BELIRSIZ` |
| `match_team("City", ["City U21"])` | `"City U21"` | önek kuralı yaş grubunu geçti | `None` (öneri de yok) |
| ek: `("City", ["City Women"])`, `("Galatasaray", ["Galatasaray II"])`, `("Real Madrid", ["Real Madrid Castilla"])` | ikinci takım | aynı önek kuralı | `None` |

Kapsam tarafında yeniden üretilen sorunlar (sentetik): 4 takımlık kusursuz çift devre alt küme "tam sezon" sayılıyordu
(takım sayısı dosyadan); depodaki tam çift devreli kapanmış sezon da takım sayısını depodan çıkararak kanıt
sayılıyordu; yinelenen kayıt eksik maçın yerini doldurabiliyordu; tur yapısı ve play-off/split ayrımı yoktu.

## Yeni sözleşmeler (özet; ayrıntı `docs/VERI_UYGUNLUK.md`)

- **Kimlik:** kesin kimlik = bağlamda benzersiz normalleştirilmiş tam ad veya kapsamı (kaynak + lig ülkesi) tutan
  doğrulanmış takma ad. Çakışma ve ters çakışma belirsizdir (doğrulanmış takma adlar hariç); önek/benzerlik yalnızca
  öneri; boş ad/tek harf kanıt değil; kategori (II/B, U19/U21, kadın) ayrı; Türkçe ı/İ ve ø/ß/ł kayıpsız; ev ≠
  deplasman. `match_team` imzası korunur (yalnızca kesin kimlik döner); `resolve_team`/`resolve_teams` ayrıntıyı verir.
- **Eşleme güveni uygunlukta:** eşleşmeyen fikstür ham adları, eşleme durumu/sürümü, önerileri ve (varsa) kaynak maç
  kimliğiyle saklanır; eşlenen openfootball fikstürü ham ad ve eşleme dayanağı taşır. Uygunluk anında başka kaynaktan
  eşlenmiş fikstür kimliği aynı kaynak dosyasında güncel eşleyiciyle yeniden kurulur; kurulamazsa
  `TAKIM_ESLESMESI_DOGRULANAMADI` (eski kayıtlar yeni eşleyiciden geçmiş sayılmaz, toplu yeniden yazılmaz). Eşleme
  sürümü önbellek anahtarı ve bağlam parmak izinde.
- **Takvim A/B:** bağımsız katılımcı = aynı sezonun depo takımları; tekilleştirme (kaynak kimliği, yoksa tur+tarih+
  takımlar; çakışma birleştirilmez); B = 1. turdan ardışık, katılımcıların tam eşleşmesi olan numaralı turlar;
  A = B + format tur sayısı + eşleşme yapısı (iç/dış saha dahil) + split/play-off'lu lig değil. Pencere her zaman 365
  gün (depodaki ilk maç pencereyi kısaltamaz). Sezonlar arası köprü yalnızca önceki sezonun sonu doğrulanmışsa ve ara
  boşsa; sezon başlamadıysa ara bilgi kesimine kadar. Depo-içi tamlık kanıtı kaldırıldı. Ters yön denetimi:
  `KAYNAK_DEPO_CELISKISI`.
- **Haklar:** "yerel analiz" istisnası kaldırıldı (`KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI` ve
  `KAYNAK_EGITIM_HAKKI_DOGRULANAMADI` artık "tahmin" engeli; yeni `KAYNAK_MODEL_KULLANIMI_DOGRULANAMADI`,
  `MODEL_EGITIM_KOKENI_YOK`, `KAYNAK_ETIKETI_UYUMSUZ`). İşlem kapsamları `OPERATION_SCOPES`; yeniden dağıtım ve
  ticari kullanım bu yerel işlemler için gerekmez. Gerçek veriyle eğitim aynı kayıttan denetlenir (çıkış 3 / arayüz
  uyarısı; onay kutusu veya bayrak aşamaz). Etiketsiz kaynak satırı ve boş eğitim kökeni kapalı başarısız olur.

## Sürümler

`veri-uygunluk-v1` → `veri-uygunluk-v2`; `takim-eslesme-v2` (yeni sabit; önceki önek/benzerlik eşleyicisi v1 sayılır);
`ileriye-donuk-olcum-v3` gerçek sistem saatinde donduruldu (zaman ve gövde özeti
`ileriye_donuk_protokol_v3.json` ve kodda `PROTOCOL_V3_FROZEN`; eşitlik testle denetlenir). v1/v2 gövdeleri, özetleri
ve dondurma anları değişmedi (testle denetlenir). Model matematiği, karar eşikleri, sayısal toleranslar ve altın
regresyon değerleri değişmedi.

## Eski politikayı bekleyen ve güncellenen testler

| Test | Neden |
|---|---|
| `test_eligibility.py::test_t16_*` | Onaylı football-data verisi v1'de tahmine izinliydi (yalnızca bahis engelli); v2'de tahmin de engelli. İzin verme durumu (belgeli sentetik kaynak) eklendi. |
| `test_unverified_rights_block_every_bet_path_but_keep_forecast` → `..._block_forecast_and_every_bet_path` | Aynı politika değişikliği; olasılıksız/stake 0 kayıt ve belgeli kaynakla aday üretimi ayrıca sınanır. |
| `test_previous_season_store_evidence_must_be_complete_for_the_whole_league` → `test_previous_season_needs_independent_calendar_not_store_self_consistency` | Depo-içi tamlık kanıtı kaldırıldı; bağımsız takvimle izin verme durumu sınanır. |
| `test_store_only_season_evidence_requires_exact_double_round_robin` → `test_store_only_season_is_never_completeness_evidence` | Kaldırılan fonksiyonun birim testiydi; 4 takımlık kusursuz alt küme karşı örneğiyle yeniden yazıldı. |
| `test_models.py::test_team_name_matching` ("Coventry City FC" → "Coventry") | Önek eşleşmesi artık yalnızca öneri; öneri ayrıca doğrulanır. |
| `test_cli.py` (`gol-egit`) | Belgeli hakkı olmayan veriyle eğitim engellenir (çıkış 3); testte açıkça sentetik kaynak kaydıyla izin verme durumu. |
| `test_forecast_log.py` (etkin protokol v2) | Etkin protokol v3; v1/v2'nin değişmediği ayrıca sınanır. |

Hiçbir assertion silinmedi veya test atlanmadı; değişen her testte engelleme ve izin verme durumu birlikte var.

## Bağımsız inceleme

Tek bağımsız inceleyici (zincir yok) değişiklikleri sentetik yeniden üretimlerle inceledi. Doğrulanan ve düzeltilen
bulgular: (M1) pencere başının depodaki ilk maçtan alınması — önceki sezonları eksik depo daha "uygun" görünüyordu;
(M2) kaynak etiketi olmayan satırlar ve boş eğitim kökeni hak kontrolünden geçiyordu; (M3) `dizi-arastir` S0 modelini
gerçek veriyle eğitim kapısı olmadan eğitiyordu; önbellekte üçüncü sezon dosyası okunmadığı için sezon öncesi yol
uygulamada hiç çalışmıyordu; split/play-off'lu liglerde "33 tur + bir split turu" tam sezon sayılıyordu; bozuk tarih
alanı kapsam okumasını çökertebiliyordu; güncelleme sonrası otomatik eğitim kapısı ve 1X2 yeniden doğrulaması testsizdi.
Her biri için test eklendi. Düzeltmeler geri alınarak (mutasyon) 23 durumda ilgili testlerin düştüğü doğrulandı.
Bilinçli olarak değiştirilmeyenler: eğitim kapsamı `model_kullanimi` istemez (eğitilen modelin kullanımı tahmin anında
ayrıca denetlenir); `backtest` ve `en-olasi` başlığı eski modelin saklı örneklem dışı geçmiş sonuçlarını gösterir
(yeni tahmin değil); `dizi-benzer` geçmiş olay sıklıklarını gösterir ("olasılığa etki: yok").

## Test sonucu

Linux (Python 3.13), çalışma ağacının yalnızca izlenen/izlenebilir dosyalarından oluşan temiz kopyada:
`QT_QPA_PLATFORM=offscreen python -m pytest -q` → **367 geçti, 1 atlandı** (ağ testi). Başlangıç (6b1197f, aynı
yöntem): 311 geçti, 1 atlandı; önceden bulunan hata yoktu. Yeni testler: `tests/test_s3_gate_02.py` (55),
`tests/test_forecast_log.py::test_protocol_v3_*` (1) ve güncellenen testler. `ruff --select F,E9`: yalnızca
değiştirilmemiş dosyalardaki önceden var olan 4 F401. Windows'ta bu commit anında çalıştırılmadı (Linux sonucu Windows
doğrulaması değildir).

## Gerçek veri durumu (salt-okunur, yayımlanmayan yerel eski kopya)

- Eşleme: 8 ligin openfootball 2026-27 dosyalarındaki 156 adın tamamı eski eşleyicide eşleşiyordu; yeni sözleşmede
  115'i kesin, 41'i yalnızca öneri (ör. "X City FC" ↔ "X" biçimi). Kesin eşleşenlerin hiçbiri eski eşleyiciden farklı
  takıma gitmedi. Bu 41 ad için doğrulanmış takma ad eklenmedi (öneri kimlik kanıtı değildir).
- Uygunluk: 160 yaklaşan maçın tamamı `KNOWN_STALE` (`DEPODA_EKSIK_MAC`; depo 03.09.2026'da bitiyor); ayrıca
  `KAYNAK_KAPSAMI_KISMI` (eşleşmeyen adlar yüzünden katılımcı listesi doğrulanamıyor), `DURUM_KOKENI_YOK` ve üç hak
  kodu. Tahmin uygun: 0; bahis verisi uygun: 0. Maç satırları rapora alınmadı.

## Açık kalanlar

- **Kullanım hakları:** football-data.co.uk belgelerine (`data.php`, `contact.php`) bu ortamdan erişilemedi (ad
  çözümlenemedi); sonuç kullanımı, model eğitimi ve model kullanımı belgelenmedi → bu verilerle tahmin gösterilmez,
  bahis adayı ve gerçek veriyle eğitim yoktur. GitHub yedeği (MIT depo lisansı) asıl kaynak hakkını kanıtlamaz.
- **Takvim:** önceki sezon dosyası yalnızca uygulama o sezon kullanıldıysa önbellekte olur (yeni indirme eklenmedi);
  yoksa 365 günlük pencere kanıtlanamaz (UNKNOWN). openfootball 22 ligin yalnızca 8'ini sunar. Split/play-off'lu
  liglerde sezon sonu doğrulanamaz (doğrulanmış format kaydı gerekir). Hem kaynakta hem depoda olmayan sezon sonu
  aşamaları tespit edilemez.
- **Kimlik:** 41 gerçek ad için doğrulanmış takma ad süreci (ör. iki sağlayıcının sonuç uyumuyla) gerekir; sezon bazlı
  takma ad yok (aynı adlı yeniden kurulmuş kulüp ayırt edilemez).
- Windows testi ve defter bütünlüğü: ayrı başlıklar; eski public maruziyet (01b7e9f) bu görevin kapsamı değildir ve
  temizlenmedi.

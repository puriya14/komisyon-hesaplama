# S4-KAYNAK-03 — football-data.org değerlendirmesi ve katılımcı referansı zaman kontrolü

**football-data.org bu pilot için gerçek ve izinli güncel veri yolu olabilir mi?** Bu oturumda **belirlenemedi**.
- `www.football-data.org`, `docs.football-data.org` ve `api.football-data.org` adreslerinin üçü de bu ortamın ağ
  politikasınca bağlantı aşamasında reddedildi (CONNECT 403). Resmî belgelerin hiçbiri okunamadı.
- Uygulamaya tanımlı bir API anahtarı ya da anahtar mekanizması da yok.
- Plan, alan dolululuğu, gecikme ve kullanım hakları doğrulanmadı. Hiçbir kapı gevşetilmedi.

**Katılımcı referansının zaman kontrolü kapandı mı?** Evet.
- Önce başarısız sentetik testlerle açık yeniden üretildi, sonra en küçük düzeltme yapıldı.
- Referans, değerlendirme anında henüz bu sistemde erişilebilir değilse artık o anın kapsam kanıtı sayılmıyor.

| Boyut | Durum |
|---|---|
| SOURCE_CAPABILITY | **INSUFFICIENT**: kanıt yetersiz (belge okunamadı, API çağrılmadı). Sağlayıcının yetersiz olduğu kanıtlanmadı. |
| SOURCE_RIGHTS | **NEEDS_CLARIFICATION**: kullanım koşulları okunamadı. |
| SOURCE_ACCESS | **NETWORK_BLOCKED**: ağ açılsa bile anahtar yok (API_ACCESS_REQUIRED). |
| REFERENCE_TIME_CHECK | **FIXED_AND_TESTED** |
| MODEL | **BELOW_BASELINE**: bu görevde değiştirilmedi. |

Bu dosya ham API yanıtı, maç satırı, tahmin, anahtar veya oturum günlüğü içermez.

## A. Sağlayıcı kapsamı

**Belgeyle doğrulanan:** yok. Altı resmî adresin hiçbiri okunamadı (2026-10-11T13:57Z, her biri tek istek, CONNECT
403):
- `/coverage`
- `/pricing`
- `/about`
- `/documentation/faq`
- `docs …/v4/match.html`
- `docs …/v4/policies.html`

**Gerçek API ile doğrulanan:** yok. Anahtar olmadığı için veri ucu çağrılmadı.

**Belirsiz kalanlar.** Hepsi resmî belgeden ve plana uygun gerçek yanıttan doğrulanmalı:
- Premier League hangi planda; güncel sezona erişim var mı?
- İlk yarı ve normal süre skorları o planda bütün maçlarda dolu mu?
- Sonuçların gecikmesi ne kadar?
- Maç ve takım kimlikleri kalıcı mı?
- Maç durumları (`FINISHED`, `POSTPONED`, `CANCELLED`, `SUSPENDED`, `AWARDED` vb.) ne anlama geliyor? Hükmen
  sonuçlar nasıl gösteriliyor?
- `fullTime` uzatma veya penaltıyı içerebiliyor mu? `score.duration`, `regularTime` gibi alanlar var mı?
- Kaynağın güncelleme bilgisi (`lastUpdated`) var mı?
- Kota ve aşım ücreti ne?
- Hangi alanlar null olabilir?

Bu alan adları önbilgidir; bu oturumda belgeden okunmadı ve kanıt sayılmadı.

**Teknik karar (mevcut yapıya göre; uygulanmadı).** Sağlayıcı ileride uygun bulunursa:
- `source_registry` içinde **ayrı** bir kaynak anahtarı ve etiketle eklenir. football-data.co.uk kaydı ve hakları
  taşınmaz.
- Mevcut sonuç adaptörü desenine uyar: `MATCH_COLUMNS` ve sağlayıcı kimliği.
- Köken kaydı mevcut `data/provenance.py` desenine uyar: istek anı, yanıt özeti, uç, plan.
- Aynı yalıtılmış pilot `DataStore`'unda kalır. İkinci veritabanı veya servis gerekmez.

Kural kısıtları:
- Eksik ilk yarı 0-0 yapılmaz. Mantıksal İY 0-0 yalnızca gerçek normal süre 0-0 için ve işaretli kalır (v2 kuralı).
- Uzatma veya hükmen sonuç normal süre skoru sayılmaz.
- Belirsiz takım kimliği kesinleşmez (`takim-eslesme-v2`).

## B. Kullanım koşulları

Hiçbir işlem için izin belgesi okunamadı; aşağıdakilerin hepsi açıklama gerektiriyor:
- ücretsiz veya ücretli API erişimi;
- yerel saklama ve önbellek;
- openfootball (CC0) geçmişiyle birlikte kullanım;
- yeni maçlardan takım özelliği üretme;
- model eğitimi;
- eğitilmiş modelin sonradan kullanımı;
- uygulamada tahmin gösterme;
- abonelik bitince veri ve modelin kullanımı.

Ham veriyi yeniden dağıtma uygulamanın yaptığı bir işlem değil, istenmiyor da. Bir paket adı ("ML Pack" gibi) veya
"ücretsiz API" ifadesi tek başına bu işlemlerin izni sayılmadı.

**Sağlayıcıya iletilecek soru taslağı.** Kullanıcı gönderir; bu görevde gönderilmedi.

> Hello, I am evaluating football-data.org API v4 for a small private project that predicts English Premier League
> goal markets with a statistical model (no betting service, no redistribution of your data). Before creating a key or
> subscribing, could you confirm, for the plan that covers the Premier League current season:
> (1) whether full-time (regular-time) and half-time scores are available for all matches, how soon after the final
> whistle they appear, whether `fullTime` can include extra time or penalties, and how AWARDED / POSTPONED /
> CANCELLED / SUSPENDED matches are represented;
> (2) whether we may (a) store retrieved results locally as a private cache, (b) combine them with CC0 historical
> data, (c) derive team features and train a model on them, (d) keep using the stored results and the trained model
> after the subscription ends, and (e) show the model's own probabilities (not your raw data) in a private
> application;
> (3) which rate limit applies and whether any overage charges can occur. Thank you.

## C. Erişim

- **Anahtar:** uygulamada API anahtarı ya da gizli ayar mekanizması yok. `config.Settings` yalnızca düz ayarları
  tutuyor. Ortamda bu amaçla adlandırılmış bir değişken de yok; yalnızca adlarına bakıldı.
- **Arama sınırı:** git geçmişi, e-posta, başka uygulamalar ve ilgisiz gizli dosyalar aranmadı.
- **Güvenli tanımlama:** bulut ortamında anahtar, ortam ayarlarında gizli değişken olarak tanımlanır (ör.
  `FOOTBALL_DATA_ORG_TOKEN`); yeni oturum onu görür. Anahtar sohbete veya depoya yazılmamalı. Yerel uygulamada
  ileride okunacaksa yalnızca çağrı anında ortam değişkeninden okunmalı; ayar dosyasına, loga ve hata mesajına
  yazılmamalı.
- **İstekler:** 7 bağlantı denemesi yapıldı (6 belge, 1 API kök adresi; veri ucu ve anahtar yok). Hepsi ağ
  geçidinde reddedildi; **sağlayıcıya ulaşan istek 0**. Ücret oluşmadı.

## D. Gerçek veri

Okunmadı. 2026-10-10 tarihli 6 maçın durumu ve İY/MS kapsamı bilinmiyor. Uydurulmadı ve 0-0 yapılmadı.

## E. Zaman düzeltmesi

**Kök neden:**
- `load_participants`, `alinma_utc` alanının yalnızca boş olmadığını denetliyordu; tarih ayrıştırılmıyor, zaman
  dilimi aranmıyordu.
- Katılımcı kümesi kapsam kanıtına zamansız bir `frozenset` olarak giriyordu.
- Değerlendirmede yalnızca kaynak dosyasının `retrieved_at <= as_of` kuralı vardı. Önbellek anahtarı da referansın o
  andaki erişilebilirliğini içermiyordu.

Bu yüzden Python API'sine (`forecast(now=...)`, `build_context`) geçmiş bir an verildiğinde, sonradan alınmış bir
referans o anın takvimini "tam" gösterebiliyordu. Aynı gün içindeki daha erken bir an için önbellekteki "doğrulandı"
sonucu da yeniden kullanılabiliyordu.

**Düzeltme:**
- `alinma_utc` zaman dilimli ISO 8601 olmalı.
- Erişilebilirlik = `max(alinma_utc, dosyanın bu sistemdeki değiştirilme zamanı)`; dosyadaki tarih daha erken
  erişilebilirlik kanıtı değildir. Sınır kuralı kaynak dosyasıyla aynı: `<=`, yani aynı an kullanılabilir.
- Küme bu anı taşıyor (`ParticipantSet.available_since`).
- `EligibilityContext.coverages_at(league, as_of)` erişilebilir olmayan referansa dayanan takvimi kısmi sayıyor.
  Sonuç `KAYNAK_KAPSAMI_KISMI` ve UNKNOWN.
- Önbellek anahtarı bu durumu içeriyor.
- Kayıtlı kopyada geçersiz tarih varsa referans kullanılmıyor (`GECERSIZ_REFERANS`).
- Depodan türetilen katılımcılar (başka sağlayıcı) eski davranışla kalıyor.

**Değişen dosyalar:**
- `bahis_tahmin/eligibility.py`
- `bahis_tahmin/pilot.py`
- `docs/S4_PILOT.md`
- `tests/test_s4_kaynak_03.py` (yeni)
- `tests/test_s4_pilot.py`

**Regresyon testleri:**
- `test_s4_kaynak_03.py`: 15 test. Düzeltmeden önce 10'u başarısızdı.
- `test_s4_pilot.py`: 2 yeni test; eski kodla ikisi de başarısız.

Kapsanan durumlar:
1. Alım değerlendirmeden önce: geçer.
2. Aynı an: geçer.
3. Alım sonra: engellenir.
4. Eksik, bozuk, zaman dilimsiz, sayısal veya geçersiz tarih: reddedilir.
5. UTC ve +03:00 ile verilen aynı an aynı sonucu verir.
6. Kayıtlı kopya yolu kontrolü atlayamaz; pilot, model ve defter değişmez.
7. Daha erken bir an için önbellek kullanılmaz.
8. 20 kulüplük referans alındıktan sonra çalışmaya devam eder.
9. Dosyadaki tarih erişilebilirliği öne çekemez.

**Test verisi değişikliği:** `test_s4_pilot.py` fikstüründeki sentetik referans alınma anını 2030 olarak beyan
ediyordu (değerlendirme anından sonra). Yeni kural bunu doğru biçimde engellediği için tarih değerlendirme anından
önceye alındı. Assertion kaldırılmadı; skip veya xfail eklenmedi.

## F. Korunanlar

- Gerçek E0 pilotu (ev2: veri, model, 42 kayıtlı defter), eski pilot ve tanılama çıktıları değişmedi.
- Uygulama veri klasörü oluşmadı.
- openfootball geçmişi, köken kayıtları ve katılımcı referansının `alinma_utc` değeri değişmedi.
- Protokoller ve eşikler değişmedi.
- football-data.co.uk kaydı değişmedi.

Gerçek 20 kulüplük referansla yerel ve salt okunur bir kontrol yapıldı:
- Referans alındıktan sonraki bir anda 2025/26 ve 2026/27 kapsamı doğrulanıyor.
- Dosyadaki `alinma_utc`'den sonraki ama dosyanın bu sisteme gelmesinden önceki bir anda doğrulanmıyor.

## G. Test ve koruma

Gerçek test sonuçları, commit, uzak SHA ve Linux/Windows CI durumu oturum yanıtındadır. Bu dosya kendi commit'inin
sonucunu iddia etmez.

## H. Tek gerekli dış adım

Bu ortamın ağ politikasında `www.football-data.org`, `docs.football-data.org` ve `api.football-data.org` adreslerinin
izinli alan olarak eklenmesi. Bu yapılmadan belge ve koşullar okunamaz; anahtar verilse bile API'ye ulaşılamaz.

"""Veri kaynakları ve kullanım koşulları kaydı.

Bir verinin internette bulunması kullanım hakkı anlamına gelmez. Kullanım koşulları
açıkça doğrulanamayan kaynaklar, kullanıcı koşulları okuyup onaylamadan otomatik
indirilmez ve model eğitimine sokulmaz. Bu tablo 2026-10-10 tarihli denetime dayanır;
koşullar değişebilir, kullanıcı kaynak sayfalarını kendisi kontrol etmelidir.
"""

from __future__ import annotations

from dataclasses import dataclass

AUDIT_DATE = "2026-10-10"


@dataclass(frozen=True)
class SourceInfo:
    key: str
    name: str
    url: str
    terms_url: str
    license_summary: str
    commercial_use: str
    automated_download: str
    model_training: str
    redistribution: str
    coverage: str
    cost: str
    requires_consent: bool


SOURCES: dict[str, SourceInfo] = {
    "football-data": SourceInfo(
        key="football-data",
        name="football-data.co.uk",
        url="https://www.football-data.co.uk/data.php",
        terms_url="https://www.football-data.co.uk/disclaimer.php",
        license_summary=(
            "Site, CSV dosyalarının ücretsiz indirilebildiğini belirtiyor; sayfa altbilgisi 'All Rights Reserved'. "
            "Yeniden kullanım, model eğitimi veya yeniden dağıtım için açık bir lisans metni bulunamadı "
            "(denetim ortamından siteye doğrudan erişilemedi)."
        ),
        commercial_use="Doğrulanamadı (açık izin yok). İngiltere/İskoçya resmi lig verisi üzerinde Football DataCo hak iddia eder.",
        automated_download="Doğrulanamadı; nazik, önbellekli ve seyrek indirme yapılır.",
        model_training="Doğrulanamadı.",
        redistribution="İzin varsayılmaz: veriler yalnızca kullanıcının bilgisayarında tutulur, uygulama ile dağıtılmaz.",
        coverage=("Ana ligler 1993/94'ten itibaren (ligden lige değişir); ilk yarı skorları çoğu ligde 2000/01'den, "
                  "İngiltere'de daha erken. Oranlar: 1X2, 2.5 Alt/Üst, Asya handikabı. 3.5 Üst, İY 1.5 Üst ve "
                  "iki yarıda KG oranı YOK."),
        cost="Ücretsiz",
        requires_consent=True,
    ),
    "github-mirror": SourceInfo(
        key="github-mirror",
        name="Club Football Match Data (GitHub, xgabora)",
        url="https://github.com/xgabora/Club-Football-Match-Data-2000-2025",
        terms_url="https://github.com/xgabora/Club-Football-Match-Data-2000-2025/blob/main/LICENSE",
        license_summary=(
            "Depo MIT lisanslı; ancak maç verileri football-data.co.uk'tan, Elo verileri ClubElo'dan derlenmiştir. "
            "Depo sahibi kaynak verinin haklarını devredemeyeceği için asıl kaynakların koşulları geçerlidir. "
            "README (commit 25882a58a736): Elo 1 Haziran 2025'e kadar ClubElo'dan; 15 Haziran 2025'ten sonrası yazarın "
            "son ClubElo görüntüsünden yeni sonuçlarla ürettiği geçici devam serisidir (aynı yöntem sayılmaz). Elo, "
            "form, küme olasılıkları ve oranlar türetilmiş/piyasa alanlarıdır; model girdisi yapılmaz."
        ),
        commercial_use="Asıl kaynağa bağlı (doğrulanamadı).",
        automated_download="GitHub üzerinden tek dosya indirme.",
        model_training="Asıl kaynağa bağlı (doğrulanamadı).",
        redistribution="İzin varsayılmaz.",
        coverage="38 lig kodu, 2000/01–2026 (ana ligler); ilk yarı skorları yalnızca Avrupa ana liglerinde.",
        cost="Ücretsiz",
        requires_consent=True,
    ),
    "openfootball": SourceInfo(
        key="openfootball",
        name="openfootball/football.json",
        url="https://github.com/openfootball/football.json",
        terms_url="https://github.com/openfootball/football.json/blob/master/LICENSE.md",
        license_summary="CC0 1.0 (kamu malı): ticari kullanım dahil serbest.",
        commercial_use="İzinli (CC0).",
        automated_download="İzinli (CC0).",
        model_training="İzinli (CC0).",
        redistribution="İzinli (CC0).",
        coverage=("Fikstür ve sonuçlar (yalnızca yedek fikstür kaynağı olarak kullanılır). Oran yok. FIKSTUR-03: "
                  "football.json'da güncel sezon dosyası olmayan liglerde aynı topluluğun ulusal Football.TXT "
                  "depoları (europe, belgium, austria, deutschland, england, espana, italy, south-america; aynı CC0 "
                  "lisans dosyası) okunur."),
        cost="Ücretsiz",
        requires_consent=False,
    ),
    "openfootball-sonuc": SourceInfo(
        key="openfootball-sonuc",
        name="openfootball/football.json (maç sonuçları; S4 pilotu)",
        url="https://github.com/openfootball/football.json",
        terms_url="https://github.com/openfootball/football.json/blob/master/LICENSE.md",
        license_summary=(
            "CC0 1.0: derleyici kendi telif ve veritabanı haklarından feragat eder. CC0 veri doğruluğunu garanti "
            "etmez ve üçüncü kişilerin olası haklarını (ör. lig fikstür listeleri üzerindeki talepler) temizlemez "
            "(CC0 madde 4). Yalnızca pilot sonuç adaptörüyle okunan ve kökeni doğrulanan satırlar için geçerlidir."
        ),
        commercial_use="CC0 (derleyicinin hakları açısından izinli; üçüncü kişi hakları temizlenmez).",
        automated_download="Sabit commit üzerinden, önbellekli ve seyrek (tek lig).",
        model_training="CC0 (derleyicinin hakları açısından izinli).",
        redistribution="CC0 (derleyicinin hakları açısından izinli); uygulama ham veriyi dağıtmaz.",
        coverage=("Sezon dosyalarında normal süre sonucu (score.ft / liste) ve çoğu maçta ilk yarı (score.ht). "
                  "S4 pilotunda tam sezon; ana uygulamada (VERI-02) yalnızca veri deposunun geride kaldığı güncel "
                  "dönemin tamamlanması (etiket openfootball-tamamlama; köken doğrulamalı)."),
        cost="Ücretsiz",
        requires_consent=False,
    ),
    "football-datasets": SourceInfo(
        key="football-datasets",
        name="datasets/football-datasets (GitHub; Premier League sezon CSV'leri)",
        url="https://github.com/datasets/football-datasets",
        terms_url="https://github.com/datasets/football-datasets/blob/main/README.md",
        license_summary=(
            "README: lig veri setleri ODC-PDDL 1.0 ile yayımlanır; veri football-data.co.uk'tan alınır (depodaki "
            "scripts/process.py asıl siteden indirir; uygulama bu betiği çalıştırmaz). premier-league/README: 'yalnızca "
            "eğitim ve araştırma amaçlı; ötesi için Football Data UK koşullarını inceleyin'. Depo lisansı asıl kaynağın "
            "haklarını kanıtlamaz; asıl kaynağın koşulları doğrulanamadı (football-data kaydıyla aynı)."
        ),
        commercial_use="Asıl kaynağa bağlı (doğrulanamadı).",
        automated_download="GitHub raw, sabit commit; yalnızca depodaki dosyalar okunur.",
        model_training="Asıl kaynağa bağlı (doğrulanamadı).",
        redistribution="İzin varsayılmaz (uygulama veri dağıtmaz).",
        coverage=("Premier League 1993/94–2025/26 sezon dosyaları (commit 436a51f15258): MS her sezonda; İY 1995/96'dan; "
                  "hakem/şut/faul/korner/kart 2000/01'den. Oran sütunu yok."),
        cost="Ücretsiz",
        requires_consent=True,
    ),
    "statsbomb-acik": SourceInfo(
        key="statsbomb-acik",
        name="StatsBomb açık verisi (hudl/open-data)",
        url="https://github.com/hudl/open-data",
        terms_url="https://github.com/hudl/open-data/blob/master/LICENSE.pdf",
        license_summary=(
            "StatsBomb Public Data User Agreement (LICENSE.pdf, son güncelleme 8 Eylül 2023; commit 4b73468fc5b0'da "
            "okundu): 1.1 analiz ve araştırma için erişim; 1.2.1 veriyi düzenleme, çoğaltma, dağıtma ve üçüncü kişiye "
            "verme yasak; 1.2.2 veriyi veya türetilen analizi ticari kullanma yasak; 1.4 yayımlanan analizde StatsBomb "
            "atfı/logosu; 2.2 kullanıcılardan web sitesinde kayıt isteniyor (uygulama kullanıcı adına kayıt yapmaz)."
        ),
        commercial_use="Yasak (madde 1.2.2).",
        automated_download="GitHub raw, sabit commit; yalnızca seçili dosyalar (360 dosyaları indirilmez).",
        model_training="Bahis amaçlı kullanım ticari kullanım sayılabilir; belgeyle doğrulanmadı (kapalı).",
        redistribution="Yasak (madde 1.2.1); uygulama ham veriyi dağıtmaz.",
        coverage=("Olay verisi seçili yarışmalar: Premier League 2015/16 tam sezon (380 maç) ve 2003/04 yalnızca "
                  "Arsenal maçları (38); her maç için olay, kadro; seçili maçlarda 360."),
        cost="Ücretsiz",
        requires_consent=False,
    ),
    "espn": SourceInfo(
        key="espn",
        name="ESPN skor tablosu (resmi olmayan uç nokta)",
        url="https://www.espn.com/soccer/",
        terms_url="https://www.espn.com/",
        license_summary=(
            "site.api.espn.com skor tablosu uç noktası belgelenmemiştir; açık bir lisans veya veri kullanım metni "
            "bulunamadı (2026-10-12 denetimi; uç noktaya bu ortamdan erişilemedi). Sitenin genel kullanım koşulları "
            "espn.com sayfa altındaki 'Terms of Use' bağlantısındadır. Yalnızca Serie B, La Liga 2, Ligue 2, Süper Lig "
            "ve 2. Bundesliga için, verileri football-data.co.uk'tan alınamadığında fikstür, sonuç ve sezon takvimi "
            "alınır."
        ),
        commercial_use="Doğrulanamadı (açık izin yok).",
        automated_download="Doğrulanamadı; lig başına aylık, önbellekli ve seyrek istek.",
        model_training="Doğrulanamadı.",
        redistribution="İzin varsayılmaz: veriler yalnızca kullanıcının bilgisayarında tutulur.",
        coverage=("Serie B, La Liga 2, Ligue 2, Süper Lig, 2. Bundesliga: fikstür, normal süre sonucu, varsa devre "
                  "skorları; oran ve istatistik yok. Takım adları yalnızca maç kanıtıyla eşlenir."),
        cost="Ücretsiz (anahtar gerekmez)",
        requires_consent=True,
    ),
    "the-odds-api": SourceInfo(
        key="the-odds-api",
        name="The Odds API",
        url="https://the-odds-api.com/",
        terms_url="https://the-odds-api.com/terms-and-conditions.html",
        license_summary=(
            "Entegre EDİLMEDİ. Resmi siteye denetim ortamından erişilemedi; üçüncü taraf kaynaklara göre tarihsel "
            "oranlar ücretli planlarda ve 2020 ortasından itibaren 5-10 dk aralıklı. Pazar kapsamı (3.5 Üst, İY "
            "1.5 Üst, iki yarıda KG) resmi dokümandan doğrulanamadı."
        ),
        commercial_use="Plan koşullarına bağlı.",
        automated_download="API anahtarı ve kota ile.",
        model_training="Doğrulanamadı.",
        redistribution="Doğrulanamadı.",
        coverage="Doğrulanamadı.",
        cost="Ücretli (tarihsel oranlar); kullanıcı ücretsiz kaynak istediği için etkinleştirilmedi.",
        requires_consent=True,
    ),
}

# Uygulamanın gerçekten kullandığı (adaptörü olan) kaynaklar
IMPLEMENTED = ("football-data", "github-mirror", "openfootball", "espn")

# Veri deposundaki ``source`` etiketi -> kaynak anahtarı
SOURCE_LABELS = {"football-data.co.uk": "football-data", "github-yedek": "github-mirror", "openfootball": "openfootball",
                 "openfootball-sonuc": "openfootball-sonuc", "football-datasets": "football-datasets",
                 "statsbomb-acik": "statsbomb-acik",
                 # VERI-02: güncel sezonun openfootball ile tamamlanan satırları; aynı kaynak ve lisans (CC0), hak
                 # yalnızca köken doğrulanırsa (data/completion.py)
                 "openfootball-tamamlama": "openfootball-sonuc",
                 # KAYNAK-04: ESPN sonuç ve fikstür satırları (onay + kişisel kullanım beyanı)
                 "espn": "espn"}

# Kullanım kapsamının yapılandırılmış hâli (veri uygunluk kontrolü bunu okur; S3-GATE-01, kapsamlar S3-GATE-02).
# Değerler yukarıdaki SOURCES metinlerinin aynısıdır, YENİ HAK VERMEZ: belge yoksa "DOGRULANAMADI" kalır. Ayrı alanlar:
# kullanıcı indirme onayı (ayarlar; burada değil), kaynak erişim koşulları, sonuç verisinin analizde kullanımı, model
# eğitimi, bu veriyle eğitilmiş mevcut modelin kullanımı, ticari kullanım ve yeniden dağıtım. Kullanıcının
# uygulamadaki onayı yalnızca indirmeyi (erişimi) kapsar; diğer alanları doğrulanmış yapmaz ve "yerel/kişisel analiz"
# gerekçesiyle otomatik izin verilmez (S3-GATE-02). VERI-01: kullanıcı, onay verdiği kaynak için ayrıca açık bir
# "kişisel kullanım beyanı" verebilir (``kisisel_beyan`` alanları; ayarlarda ``kisisel_kullanim``). Beyan, yalnızca
# DOGRULANAMADI olan bu alanları kullanıcının kendi sorumluluğunda "KULLANICI_BEYANI" yapar (kişisel, ticari olmayan
# analiz, bu bilgisayarda model eğitimi ve tahmin). Kayıttaki belge durumu değişmez; ticari kullanım ve yeniden dağıtım
# beyanla açılmaz; IZIN_VARSAYILMAZ/YASAK alanlar hiçbir zaman açılmaz. Hangi işlemin hangi alanları gerektirdiği:
# ``eligibility.OPERATION_SCOPES``. ``saglar``: kaynağın uygulamada GERÇEKTEN sağladığı veri türleri; bir etiketin
# hakkı yalnızca bu türler için geçerlidir (ör. yalnızca fikstür sağlayan kaynağın etiketiyle sonuç verisi hak
# kazanamaz). GitHub yedeğinin depo lisansı (MIT) asıl kaynağın haklarını kanıtlamaz.
#   IZINLI_BELGELI   : lisans belgesi kayıtlı (``belge``)
#   DOGRULANAMADI    : açık izin belgesi bulunamadı veya belgeye erişilemedi
#   IZIN_VARSAYILMAZ : izin varsayılmıyor (uygulama bu kullanımı yapmaz)
USE_RIGHTS: dict[str, dict] = {
    "football-data": {"erisim_kosullari": "DOGRULANAMADI", "sonuc_kullanimi": "DOGRULANAMADI",
                      "model_egitimi": "DOGRULANAMADI", "model_kullanimi": "DOGRULANAMADI",
                      "ticari_kullanim": "DOGRULANAMADI", "yeniden_dagitim": "IZIN_VARSAYILMAZ", "belge": "",
                      "saglar": ("sonuc", "fikstur"),
                      "kisisel_beyan": ("sonuc_kullanimi", "model_egitimi", "model_kullanimi"),
                      "belge_denetimi": ("2026-10-10 (S3-GATE-02): data.php ve contact.php bu ortamdan açılamadı (ad "
                                         "çözümlenemedi); koşul metni okunamadığı için hiçbir alan izinli sayılmadı.")},
    "github-mirror": {"erisim_kosullari": "DOGRULANAMADI", "sonuc_kullanimi": "DOGRULANAMADI",
                      "model_egitimi": "DOGRULANAMADI", "model_kullanimi": "DOGRULANAMADI",
                      "ticari_kullanim": "DOGRULANAMADI", "yeniden_dagitim": "IZIN_VARSAYILMAZ", "belge": "",
                      "saglar": ("sonuc",),
                      "kisisel_beyan": ("sonuc_kullanimi", "model_egitimi", "model_kullanimi"),
                      "belge_denetimi": "Depo lisansı (MIT) asıl kaynağın (football-data.co.uk) haklarını kanıtlamaz."},
    "openfootball": {"erisim_kosullari": "IZINLI_BELGELI", "sonuc_kullanimi": "IZINLI_BELGELI",
                     "model_egitimi": "IZINLI_BELGELI", "model_kullanimi": "IZINLI_BELGELI",
                     "ticari_kullanim": "IZINLI_BELGELI", "yeniden_dagitim": "IZINLI_BELGELI",
                     "belge": SOURCES["openfootball"].terms_url, "saglar": ("fikstur", "takvim"),
                     "belge_denetimi": "CC0 1.0 lisans dosyası (S2 denetimi)."},
    # Sonuç verisi (S4-PILOT-01): "sonuc" türü yalnızca gerçek sonuç adaptörüyle okunan ve kökeni doğrulanan satırlara
    # tanınır (``koken_dogrulamasi``); etiket tek başına hak vermez (data/provenance.py).
    "openfootball-sonuc": {"erisim_kosullari": "IZINLI_BELGELI", "sonuc_kullanimi": "IZINLI_BELGELI",
                           "model_egitimi": "IZINLI_BELGELI", "model_kullanimi": "IZINLI_BELGELI",
                           "ticari_kullanim": "IZINLI_BELGELI", "yeniden_dagitim": "IZINLI_BELGELI",
                           "belge": "https://github.com/openfootball/football.json/blob/master/LICENSE.md",
                           "saglar": ("sonuc",), "koken_dogrulamasi": True,
                           "belge_denetimi": ("2026-10-10 (S4-PILOT-01): LICENSE.md, commit e6744429ee39 git nesnesi "
                                              "670154e3538863b2 — CC0 1.0 Universal metni okundu. 2026-10-12 "
                                              "(FIKSTUR-03): openfootball/europe 0bf83f88e8fe, belgium 1166d3c9c572, "
                                              "austria 627ba1b3ebdd, deutschland c34532ab6950, england b17e8f01707d, "
                                              "espana 09afd6cd836e, italy 48954d163c31, south-america 119fa1724b20 "
                                              "LICENSE.md dosyaları aynı git nesnesi (670154e3538863b2)."),
                           "sinirlar": ("CC0 doğruluk garantisi vermez ve üçüncü kişi haklarını temizlemez (madde 4); "
                                        "uygulama ham veriyi dağıtmaz.")},
    # KAYNAK-04: koşul metni yok; hiçbir alan izinli sayılmaz. Kullanıcının onayı erişimi, kişisel kullanım beyanı
    # (VERI-01) yalnızca kişisel analiz, bu bilgisayarda eğitim ve tahmin alanlarını açar.
    "espn": {"erisim_kosullari": "DOGRULANAMADI", "sonuc_kullanimi": "DOGRULANAMADI",
             "model_egitimi": "DOGRULANAMADI", "model_kullanimi": "DOGRULANAMADI",
             "ticari_kullanim": "DOGRULANAMADI", "yeniden_dagitim": "IZIN_VARSAYILMAZ", "belge": "",
             "saglar": ("sonuc", "fikstur", "takvim"),
             "kisisel_beyan": ("sonuc_kullanimi", "model_egitimi", "model_kullanimi"),
             "belge_denetimi": ("2026-10-12 (KAYNAK-04): uç nokta belgelenmemiş; açık lisans veya veri kullanım metni "
                                "bulunamadı ve uç noktaya bu ortamdan erişilemedi. Kullanıcı kaynağı onayla açmayı "
                                "seçti.")},
    # S5-GITHUB-01: depo lisansı (PDDL) asıl kaynağın (football-data.co.uk) haklarını kanıtlamaz; etiket değiştirmek
    # football-data kaydının doğrulanamayan kapsamını aşmaz.
    "football-datasets": {"erisim_kosullari": "DOGRULANAMADI", "sonuc_kullanimi": "DOGRULANAMADI",
                          "model_egitimi": "DOGRULANAMADI", "model_kullanimi": "DOGRULANAMADI",
                          "ticari_kullanim": "DOGRULANAMADI", "yeniden_dagitim": "IZIN_VARSAYILMAZ", "belge": "",
                          "saglar": ("sonuc",),
                          "belge_denetimi": ("2026-10-11 (S5-GITHUB-01): README ve premier-league/README okundu "
                                             "(commit 436a51f15258). Depo PDDL; veri football-data.co.uk'tan; asıl "
                                             "kaynağın koşulları okunamadı.")},
    "statsbomb-acik": {"erisim_kosullari": "IZINLI_BELGELI", "sonuc_kullanimi": "IZINLI_BELGELI",
                       "model_egitimi": "DOGRULANAMADI", "model_kullanimi": "DOGRULANAMADI",
                       "ticari_kullanim": "IZIN_VARSAYILMAZ", "yeniden_dagitim": "IZIN_VARSAYILMAZ",
                       "belge": "https://github.com/hudl/open-data/blob/master/LICENSE.pdf", "saglar": ("olay",),
                       "belge_denetimi": ("2026-10-11 (S5-GITHUB-01): LICENSE.pdf (StatsBomb Public Data User "
                                          "Agreement, 8 Eylül 2023) commit 4b73468fc5b0'da okundu."),
                       "sinirlar": ("Yalnızca ticari olmayan analiz/araştırma (1.1, 1.2.2); dağıtım yok (1.2.1); "
                                    "yayımlanan analizde StatsBomb atfı (1.4). Bahis amaçlı model eğitimi ve tahmin "
                                    "gösterimi bu kapsama otomatik genişletilmez.")},
}

# GitHub arşivi (S5-GITHUB-01) işlemleri. Her kaynak için ayrı değerlendirilir; bir kaynağın belirsizliği diğerlerini
# durdurmaz. Değerler: IZINLI_BELGELI / DOGRULANAMADI / IZIN_VARSAYILMAZ (uygulama yapmaz) / YASAK_BELGELI.
#   belge_inceleme   : README/lisans/şema okuma
#   alma_saklama     : dosyayı sabit commit'ten alıp YEREL, özel önbellekte saklama (dağıtım yok)
#   envanter         : yapısal sayımlar (maç, MS/İY alan kapsamı, eksik/çelişkili kayıt) — sonuç oranı değil
#   tarihsel_analiz  : geçmiş maç listesi ve gerçekleşme özetleri (betimleyici)
#   model_egitimi, tahmin_gosterimi, ticari_kullanim, yeniden_dagitim
ARCHIVE_OPERATIONS = ("belge_inceleme", "alma_saklama", "envanter", "tarihsel_analiz", "model_egitimi",
                      "tahmin_gosterimi", "ticari_kullanim", "yeniden_dagitim")
ARCHIVE_SCOPES: dict[str, dict[str, str]] = {
    "openfootball-sonuc": {"belge_inceleme": "IZINLI_BELGELI", "alma_saklama": "IZINLI_BELGELI",
                           "envanter": "IZINLI_BELGELI", "tarihsel_analiz": "IZINLI_BELGELI",
                           "model_egitimi": "IZINLI_BELGELI", "tahmin_gosterimi": "IZINLI_BELGELI",
                           "ticari_kullanim": "IZINLI_BELGELI", "yeniden_dagitim": "IZINLI_BELGELI",
                           "not": "CC0 1.0 (LICENSE.md); doğruluk garantisi yok."},
    "football-datasets": {"belge_inceleme": "IZINLI_BELGELI", "alma_saklama": "IZINLI_BELGELI",
                          "envanter": "IZINLI_BELGELI", "tarihsel_analiz": "DOGRULANAMADI",
                          "model_egitimi": "DOGRULANAMADI", "tahmin_gosterimi": "DOGRULANAMADI",
                          "ticari_kullanim": "DOGRULANAMADI", "yeniden_dagitim": "IZIN_VARSAYILMAZ",
                          "not": ("Depo ODC-PDDL; veri football-data.co.uk'tan. Asıl kaynağın koşulları okunamadığı için "
                                  "betimleyici analiz ve eğitim kapalı; yalnızca yerel envanter.")},
    "github-mirror": {"belge_inceleme": "IZINLI_BELGELI", "alma_saklama": "IZINLI_BELGELI",
                      "envanter": "IZINLI_BELGELI", "tarihsel_analiz": "DOGRULANAMADI",
                      "model_egitimi": "DOGRULANAMADI", "tahmin_gosterimi": "DOGRULANAMADI",
                      "ticari_kullanim": "DOGRULANAMADI", "yeniden_dagitim": "IZIN_VARSAYILMAZ",
                      "not": ("Depo MIT; maçlar football-data.co.uk, Elo ClubElo (2025-06-15 sonrası geçici devam "
                              "serisi). Asıl kaynağın koşulları okunamadığı için betimleyici analiz ve eğitim kapalı.")},
    "statsbomb-acik": {"belge_inceleme": "IZINLI_BELGELI", "alma_saklama": "IZINLI_BELGELI",
                       "envanter": "IZINLI_BELGELI", "tarihsel_analiz": "IZINLI_BELGELI",
                       "model_egitimi": "DOGRULANAMADI", "tahmin_gosterimi": "DOGRULANAMADI",
                       "ticari_kullanim": "YASAK_BELGELI", "yeniden_dagitim": "YASAK_BELGELI",
                       "not": ("StatsBomb Public Data User Agreement: ticari olmayan analiz/araştırma; dağıtım ve ticari "
                               "kullanım yasak; yayımlanan analizde StatsBomb atfı. Seçili maçlar; tam lig değil.")},
}


def archive_scope(key: str) -> dict[str, str]:
    """Arşiv işlemleri için kapsam; kayıtta olmayan kaynak hiçbir işlem hakkı kazanmaz."""
    base = {op: "DOGRULANAMADI" for op in ARCHIVE_OPERATIONS}
    return {**base, **ARCHIVE_SCOPES.get(key, {})}


def archive_allowed(key: str, operation: str) -> bool:
    if operation not in ARCHIVE_OPERATIONS:
        raise KeyError(operation)
    return archive_scope(key).get(operation) == "IZINLI_BELGELI"


# Kişisel kullanım beyanı verilebilen kaynaklar (uygulamanın sonuç verisi aldığı, onay gerektiren kaynaklar)
DECLARABLE = tuple(k for k in IMPLEMENTED if USE_RIGHTS.get(k, {}).get("kisisel_beyan"))
# Onay penceresinin sürümü: ayarlardaki ``onay_surumu`` bundan küçükse pencere bir kez yeniden gösterilir (VERI-01'de
# kişisel kullanım beyanı eklendi; eski indirme onayı beyan sayılmaz. 3: KAYNAK-04'te ESPN eklendi).
CONSENT_SCHEMA = 3


def effective_declarations(consent: dict | None, declarations: dict | None) -> set[str]:
    """Geçerli beyanlar: beyan verilebilen ve indirme onayı da olan kaynaklar (onay geri alınırsa beyan da geçmez)."""
    consent = consent or {}
    return {k for k in (declarations or {}) if k in DECLARABLE and k in consent}


def missing_declarations(labels, consent: dict | None, declarations: dict | None) -> list[str]:
    """Verideki sonuç etiketlerinden, beyan verilebilen ama geçerli kişisel kullanım beyanı olmayan kaynaklar (yalnızca
    kullanıcıya gösterilecek ipucu için; hak kararı ``eligibility`` içindedir)."""
    keys = {SOURCE_LABELS.get(str(lb)) for lb in labels}
    have = effective_declarations(consent, declarations)
    return sorted(k for k in keys if k in DECLARABLE and k not in have)


def allowed_sources(consent: dict[str, str] | None) -> set[str]:
    """Kullanılmasına izin verilen kaynaklar: onay gerektirmeyenler + kullanıcının onayladıkları."""
    consent = consent or {}
    return {k for k in IMPLEMENTED if not SOURCES[k].requires_consent or k in consent}

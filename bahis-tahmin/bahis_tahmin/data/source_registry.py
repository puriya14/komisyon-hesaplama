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
            "Depo sahibi kaynak verinin haklarını devredemeyeceği için asıl kaynakların koşulları geçerlidir."
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
        coverage="Fikstür ve sonuçlar (yalnızca yedek fikstür kaynağı olarak kullanılır). Oran yok.",
        cost="Ücretsiz",
        requires_consent=False,
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
IMPLEMENTED = ("football-data", "github-mirror", "openfootball")

# Veri deposundaki ``source`` etiketi -> kaynak anahtarı
SOURCE_LABELS = {"football-data.co.uk": "football-data", "github-yedek": "github-mirror", "openfootball": "openfootball"}

# Kullanım kapsamının yapılandırılmış hâli (veri uygunluk kontrolü bunu okur; S3-GATE-01, kapsamlar S3-GATE-02).
# Değerler yukarıdaki SOURCES metinlerinin aynısıdır, YENİ HAK VERMEZ: belge yoksa "DOGRULANAMADI" kalır. Ayrı alanlar:
# kullanıcı indirme onayı (ayarlar; burada değil), kaynak erişim koşulları, sonuç verisinin analizde kullanımı, model
# eğitimi, bu veriyle eğitilmiş mevcut modelin kullanımı, ticari kullanım ve yeniden dağıtım. Kullanıcının
# uygulamadaki onayı yalnızca indirmeyi (erişimi) kapsar; diğer alanları doğrulanmış yapmaz ve "yerel/kişisel analiz"
# gerekçesiyle otomatik izin verilmez (S3-GATE-02). Hangi işlemin hangi alanları gerektirdiği:
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
                      "belge_denetimi": ("2026-10-10 (S3-GATE-02): data.php ve contact.php bu ortamdan açılamadı (ad "
                                         "çözümlenemedi); koşul metni okunamadığı için hiçbir alan izinli sayılmadı.")},
    "github-mirror": {"erisim_kosullari": "DOGRULANAMADI", "sonuc_kullanimi": "DOGRULANAMADI",
                      "model_egitimi": "DOGRULANAMADI", "model_kullanimi": "DOGRULANAMADI",
                      "ticari_kullanim": "DOGRULANAMADI", "yeniden_dagitim": "IZIN_VARSAYILMAZ", "belge": "",
                      "saglar": ("sonuc",),
                      "belge_denetimi": "Depo lisansı (MIT) asıl kaynağın (football-data.co.uk) haklarını kanıtlamaz."},
    "openfootball": {"erisim_kosullari": "IZINLI_BELGELI", "sonuc_kullanimi": "IZINLI_BELGELI",
                     "model_egitimi": "IZINLI_BELGELI", "model_kullanimi": "IZINLI_BELGELI",
                     "ticari_kullanim": "IZINLI_BELGELI", "yeniden_dagitim": "IZINLI_BELGELI",
                     "belge": SOURCES["openfootball"].terms_url, "saglar": ("fikstur", "takvim"),
                     "belge_denetimi": "CC0 1.0 lisans dosyası (S2 denetimi)."},
}


def allowed_sources(consent: dict[str, str] | None) -> set[str]:
    """Kullanılmasına izin verilen kaynaklar: onay gerektirmeyenler + kullanıcının onayladıkları."""
    consent = consent or {}
    return {k for k in IMPLEMENTED if not SOURCES[k].requires_consent or k in consent}

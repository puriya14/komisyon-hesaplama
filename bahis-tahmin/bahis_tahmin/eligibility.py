"""Ortak veri uygunluk kontrolü (politika ``veri-uygunluk-v1``, S3-GATE-01).

Kullanıcıya dönük bütün tahmin ve karar yolları (gol pazarları taraması, maç analizi, elle maç seçimi, 1X2 tahmin
listeleri, CLI, ileriye dönük ölçüm kaydı, sanal takip kaydı) bu modülün sonucunu kullanır. İki soru ayrıdır:

* ``forecast_ok`` — Bu maç/pazar için veri ve zaman açısından tahmin üretilebilir mi?
* ``bet_ok`` — Veri ve kaynak hakları açısından bahis adayına engel kalmadı mı? Model doğrulaması, gerçek oran,
  belirsizlik, sonuçlandırma ve diğer karar kontrolleri karar motorunda AYRICA uygulanır; ``bet_ok`` yalnızca veri
  koşulunun geçildiğini gösterir.

Güncellik (``freshness``):

* ``VERIFIED_CURRENT`` — İlgili kapsamın güncelliği kanıtla doğrulandı.
* ``KNOWN_STALE`` — Tamamlanmış ve erişilebilir olması beklenen maçların eksik olduğu biliniyor.
* ``UNKNOWN`` — Doğrulamaya yeterli kanıt yok. UNKNOWN hiçbir zaman uygun sayılmaz; kontrol çağrılmadıysa veya bağlam
  verilmediyse sonuç uygun değildir (``BAGLAM_YOK``).

Kanıt zinciri (kontrol edilen veri, tahminde KULLANILAN veriye bağlanır):

1. **Model durumu ↔ veri deposu.** Tahminler modelin bellekteki lig/takım durumundan (state) üretilir ve bu durum
   eğitim anında donar. Depoda, durumun içermediği ve bilgi kesiminden önce tamamlanmış (modelin işleyeceği) maç
   varsa ``DURUM_DEPODAN_GERIDE`` (KNOWN_STALE). Model parametrelerinin eğitim kesimi tek başına engel değildir;
   karşılaştırma tahminde kullanılan lig/takım durumunun kapsamı üzerinden yapılır.
2. **Veri deposu ↔ fikstür/sonuç kaynağı.** Kaynağın tam sezon takvimi (ör. openfootball, CC0) ile takımın geçmiş
   maçları karşılaştırılır. Kaynakta tamamlanmış görünen ama depoda olmayan maç ``DEPODA_EKSIK_MAC`` (KNOWN_STALE).
   Kontrol depodaki son tarihle sınırlı değildir: ligin yeni maçları depoda olsa bile takımın daha eski bir maçı
   eksikse yakalanır. Ertelenen/iptal edilen maçlar eksik sayılmaz; geçmiş tarihli, sonucu kaynakta da depoda da
   olmayan maç ``KAYNAK_DURUMU_BELIRSIZ`` (UNKNOWN) olur.
3. **Kapsam.** Gerekli pencere (bilgi kesiminden önceki 365 gün, takımın bu ligdeki ilk maçından erken değil) kanıtla
   kapsanmalıdır: tam bir kaynak sezon takvimi veya depoda takım başına beklenen maç sayısına ulaşmış KAPANMIŞ bir
   sezon (daha zayıf, iç tutarlılık kanıtı). Ardışık iki kapsanmış sezon arasındaki ara (sezon arası) kapsanmış
   sayılır; takvim bir aralıkta maç göstermiyorsa (millî maç arası) uzun süre maç oynanmaması veri hatası sayılmaz.
   Kaynak yoksa, boşsa veya kısmîyse "eksik maç yok" sonucu çıkmaz: UNKNOWN.

Zaman kuralı (muhafazakâr, maç bitiş/yayın saati bilinmediği için): değerlendirme anının İstanbul takvim günü ``D``
ise yalnızca tarihi ``D``'den ÖNCE olan maç sonuçları erişilebilir sayılır; aynı günün sonuçları beklenmez. Kaynak
takviminde bir maçın "tamamlandı" görünmesi yalnızca değerlendirme anından ÖNCE alınmış kaynak dosyası için kanıttır
(``KAYNAK_KARAR_ANINDAN_SONRA``); geçmiş bir an, bugünkü tam sezon dosyasıyla "o gün veri tamdı" diye doğrulanamaz.
Model durumu ``D`` veya sonrasına tarihli maç içeriyorsa ve durumun değerlendirme anından önce var olduğu
bilinmiyorsa ``DURUM_KARAR_ANINDAN_SONRA``. Depoya sonradan eklenen sonuçlar geçmiş bir değerlendirmenin sonucunu
değiştirmez (bütün karşılaştırmalar bilgi kesimiyle sınırlıdır).

Kaynak hakları (``data.source_registry.USE_RIGHTS``): erişim (kullanıcı onayı), sonuç verisini kullanma, model
eğitimi ve yeniden dağıtım ayrı alanlardır. Tahmin (yerel, kişisel analiz; dağıtılmaz) için erişim izni gerekir.
Bahis adayı için sonuç kullanımı ve model eğitimi haklarının belgeyle doğrulanmış olması gerekir; doğrulanmamışsa
``KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI`` / ``KAYNAK_EGITIM_HAKKI_DOGRULANAMADI`` görünür engel olur. Kullanıcı onayı
yalnızca erişimi kapsar; arayüz onayı veya komut satırı bayrağı bu alanları doğrulanmış yapamaz.

Bu modül olasılık hesaplamaz ve modelin matematiğini değiştirmez.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .timeutil import ISTANBUL

POLICY_VERSION = "veri-uygunluk-v1"

VERIFIED_CURRENT = "VERIFIED_CURRENT"
KNOWN_STALE = "KNOWN_STALE"
UNKNOWN = "UNKNOWN"

EPOCH = pd.Timestamp("2000-01-01")  # goals.features / models.features ile aynı gün numarası
LOOKBACK_DAYS = 365  # takım özelliklerinin (form, n365, zamanla azalan güçler) bağlı olduğu pencere
MIN_TEAM_MATCHES = 10  # karar politikasıyla aynı: son 365 günde bu ligde en az maç
LEAGUE_MISSING_SHARE = 0.05  # lig düzeyinde eksik/belirsiz maç payı bunu aşarsa paylaşılan lig durumu güvenilmez
PAIR_DAY_TOLERANCE = 3  # kaynak ile depo arasında aynı eşleşme için tarih farkı toleransı (yerel tarih farkları)
NOT_PLAYED_STATUSES = frozenset({"POSTPONED", "CANCELLED", "ABANDONED", "SUSPENDED"})
FINISHED = "FINISHED"
SCHEDULED_OR_UNKNOWN = "SCHEDULED_OR_UNKNOWN"

# ----------------------------------------------------------------------------
# Neden kodları
# ----------------------------------------------------------------------------
# blocks: "tahmin" = tahmini ve bahis adayını engeller; "bahis" = yalnızca bahis adayını engeller; "yok" = bilgi.
# freshness: bu nedenin güncellik sonucuna etkisi (None = güncellikle ilgisiz).


@dataclass(frozen=True)
class Reason:
    text: str
    blocks: str
    freshness: str | None
    fix: str


REASONS: dict[str, Reason] = {
    "BAGLAM_YOK": Reason("Veri uygunluk kontrolü yapılmadı veya gerekli bağlam verilmedi.", "tahmin", UNKNOWN,
                         "Tahmini uygulamanın veya CLI'nin uygunluk kontrollü yolundan üretin."),
    "BAGLAM_UYUSMUYOR": Reason("Uygunluk sonucu bu maç, pazar, karar günü veya model durumu için değil.", "tahmin",
                               UNKNOWN, "Uygunluğu bu karar anı ve bu model için yeniden değerlendirin."),
    "MAC_GECMISTE": Reason("Maç günü değerlendirme gününden önce; maç öncesi tahmin değildir.", "tahmin", None,
                           "Yalnızca oynanmamış maçlar için tahmin üretilir."),
    "MODEL_YOK": Reason("Eğitilmiş model yok.", "tahmin", None, "Modeli eğitin."),
    "LIG_MODEL_KAPSAMI_DISI": Reason("Lig modelin durumunda yok.", "tahmin", None,
                                     "Bu ligin verisini indirip modeli yeniden eğitin."),
    "TAKIM_ESLESMEDI": Reason("Fikstürdeki takım adı veri deposundaki bir takımla eşleştirilemedi.", "tahmin", None,
                              "Takım adı eşlemesini (data/teams.py ALIASES) düzeltin."),
    "TAKIM_DURUMDA_YOK": Reason("Takım modelin lig durumunda yok (geçmişi olmayan veya eğitimden sonra gelen takım).",
                                "tahmin", None, "Takımın bu ligdeki geçmiş verisi ve güncel model gerekir."),
    "DURUM_KARAR_ANINDAN_SONRA": Reason(
        "Model durumu değerlendirme gününde veya sonrasında oynanan maçları içeriyor (bilgi kesimi aşılmış olabilir).",
        "tahmin", None, "Bu an için, o andan önce oluşturulmuş bir model durumu gerekir."),
    "DURUM_DEPODAN_GERIDE": Reason(
        "Modelin kullandığı takım/lig durumu, depodaki tamamlanmış maçları içermiyor (model durumu veriden eski).",
        "tahmin", KNOWN_STALE, "Modeli güncel veriyle yeniden eğitin."),
    "DEPODA_EKSIK_MAC": Reason("Kaynakta tamamlanmış görünen maç(lar) veri deposunda yok.", "tahmin", KNOWN_STALE,
                               "Verileri güncelleyin."),
    "DEPODA_GECERSIZ_SKOR": Reason(
        "Kaynakta tamamlanmış görünen maçın depodaki kaydı geçersiz skorlu (karantinada); model bu maçı kullanmıyor.",
        "tahmin", KNOWN_STALE, "Maçın skorunu kaynakta düzeltip verileri güncelleyin."),
    "DURUM_KOKENI_YOK": Reason(
        "Model dosyasında lig durumunun hangi maçlardan kurulduğu bilgisi yok (eski model); kullanılan durum veriyle "
        "doğrulanamıyor.", "tahmin", UNKNOWN, "Modeli yeniden eğitin (eski model dosyası değiştirilmez)."),
    "DURUM_VERIYLE_UYUSMUYOR": Reason(
        "Modelin lig durumu, depodaki aynı dönemin maçlarıyla birebir uyuşmuyor (farklı veriyle kurulmuş).", "tahmin",
        UNKNOWN, "Modeli güncel veriyle yeniden eğitin."),
    "LIG_DURUMU_EKSIK": Reason(
        f"Ligde tamamlanmış maçların %{100 * LEAGUE_MISSING_SHARE:.0f}'inden fazlası depoda yok "
        "(paylaşılan lig durumu güvenilmez).", "tahmin", KNOWN_STALE, "Verileri güncelleyin."),
    "LIG_DURUMU_KISMEN_EKSIK": Reason("Ligde başka takımlara ait az sayıda tamamlanmış maç depoda yok.", "yok", None,
                                      "Verileri güncelleyin."),
    "LIG_DURUMU_BELIRSIZ": Reason(
        f"Ligde geçmiş tarihli maçların %{100 * LEAGUE_MISSING_SHARE:.0f}'inden fazlasının sonucu doğrulanamıyor.",
        "tahmin", UNKNOWN, "Kaynak dosyası ve veriler güncellendikten sonra yeniden deneyin."),
    "KAYNAK_KAPSAMI_YOK": Reason("Bu lig için güncelliği doğrulayacak fikstür/sonuç kaynağı (tam sezon takvimi) yok.",
                                 "tahmin", UNKNOWN,
                                 "Ligin openfootball sezon dosyası (veya başka tam takvim kaynağı) gerekir."),
    "KAYNAK_KAPSAMI_KISMI": Reason("Kaynak dosyası boş, okunamadı veya sezon takvimi eksik.", "tahmin", UNKNOWN,
                                   "Tam sezon takvimi içeren kaynak dosyası gerekir."),
    "KAYNAK_KARAR_ANINDAN_SONRA": Reason("Kaynak dosyası değerlendirme anından sonra alınmış; o anın kanıtı olamaz.",
                                         "tahmin", UNKNOWN, "Geçmiş an için o anda alınmış kaynak gerekir."),
    "KAYNAK_ARALIK_DISI": Reason("Takımın gerekli geçmiş pencere aralığı kaynak veya tam sezon kanıtıyla kapsanmıyor.",
                                 "tahmin", UNKNOWN, "Önceki sezonun tam verisi veya sezon takvimi gerekir."),
    "KAYNAK_DURUMU_BELIRSIZ": Reason(
        "Takımın geçmiş tarihli bir maçının sonucu ne kaynakta ne depoda var (oynandı mı bilinmiyor).",
        "tahmin", UNKNOWN, "Kaynak ve veriler güncellendikten sonra yeniden deneyin."),
    "KAYNAK_ESLESME_BELIRSIZ": Reason("Takımın maçları kaynak takviminde güvenilir biçimde eşleştirilemedi.", "tahmin",
                                      UNKNOWN, "Takım adı eşlemesini düzeltin."),
    "KAYNAK_ESLESMEMIS_ADLAR": Reason("Kaynak takviminde eşleşmeyen takım adları var (lig düzeyi bilgi).", "yok", None,
                                      "Takım adı eşlemesini düzeltin."),
    "GEREKLI_ALAN_EKSIK": Reason("Modelin bu pazar için gerektirdiği girdiler (yarı bazlı takım güçleri) yok.",
                                 "tahmin", None, "İlk yarı skorlu yeterli geçmiş veri gerekir."),
    "TAKIM_GECMISI_YETERSIZ": Reason(f"Takımın son 365 günde bu ligde {MIN_TEAM_MATCHES} maçtan az geçmişi var.",
                                     "tahmin", None, "Daha fazla maç verisi gerekir."),
    "LIG_IY_ORANI_DUSUK": Reason("Bu ligde geçerli ilk yarı skoru oranı düşük.", "bahis", None,
                                 "İlk yarı skoru kapsamı yüksek veri gerekir."),
    "KAYNAK_ERISIM_IZNI_YOK": Reason("Kullanılan verinin kaynağı için kullanıcı erişim onayı yok.", "tahmin", None,
                                     "Kaynak kullanım koşullarını uygulamada onaylayın."),
    "KAYNAK_HAKKI_BILINMIYOR": Reason("Kullanılan verinin kaynağı kayıtlı değil; kullanım hakkı bilinmiyor.", "tahmin",
                                      None, "Kaynağı belgeleriyle kaynak kaydına (source_registry) ekleyin."),
    "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI": Reason(
        "Sonuç verisinin kaynağında kullanım hakkı belgeyle doğrulanmadı; bahis adayı üretilmez.", "bahis", None,
        "Kaynağın lisans/izin belgesini kaynak kaydına ekleyin (uygulamadaki onay yeterli değildir)."),
    "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI": Reason(
        "Modelin eğitildiği verinin kaynağında model eğitimi hakkı belgeyle doğrulanmadı; bahis adayı üretilmez.",
        "bahis", None, "Kaynağın lisans/izin belgesini kaynak kaydına ekleyin (uygulamadaki onay yeterli değildir)."),
    "OLASILIK_GECERSIZ": Reason("Model olasılığı geçersiz (NaN, sonsuz veya [0,1] dışı).", "tahmin", None,
                                "Model ve girdi verisi denetlenmeli."),
}

# Kullanıcıya gösterilecek birincil nedenin sırası: önce bağlam ve yapısal engeller (tahmin hiç kurulamaz), sonra
# bilinen eksik veri, sonra doğrulanamayan kapsam, sonra gerekli alanlar ve haklar; en son yalnızca bahsi engelleyenler.
LEAD_ORDER = (
    "BAGLAM_YOK", "BAGLAM_UYUSMUYOR", "TAKIM_ESLESMEDI", "MAC_GECMISTE", "MODEL_YOK", "LIG_MODEL_KAPSAMI_DISI",
    "TAKIM_DURUMDA_YOK", "DURUM_KARAR_ANINDAN_SONRA", "DEPODA_EKSIK_MAC", "DEPODA_GECERSIZ_SKOR",
    "DURUM_DEPODAN_GERIDE", "LIG_DURUMU_EKSIK", "DURUM_KOKENI_YOK", "DURUM_VERIYLE_UYUSMUYOR", "KAYNAK_KAPSAMI_YOK", "KAYNAK_KAPSAMI_KISMI", "KAYNAK_KARAR_ANINDAN_SONRA", "KAYNAK_ESLESME_BELIRSIZ",
    "KAYNAK_DURUMU_BELIRSIZ", "KAYNAK_ARALIK_DISI", "LIG_DURUMU_BELIRSIZ", "OLASILIK_GECERSIZ", "GEREKLI_ALAN_EKSIK",
    "TAKIM_GECMISI_YETERSIZ", "KAYNAK_ERISIM_IZNI_YOK", "KAYNAK_HAKKI_BILINMIYOR",
    "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI", "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI", "LIG_IY_ORANI_DUSUK",
)


def lead_reason(codes) -> str | None:
    """Engelleyen kodlardan kullanıcıya gösterilecek birincil neden (bilgi kodları hariç)."""
    blocking = [c for c in codes if REASONS[c].blocks != "yok"]
    if not blocking:
        return None
    return min(blocking, key=lambda c: (LEAD_ORDER.index(c) if c in LEAD_ORDER else len(LEAD_ORDER), c))


STATUS_TEXT = {"UYGUN": "Kullanılabilir", KNOWN_STALE: "Eksik veri", UNKNOWN: "Doğrulanamıyor",
               "ENGELLI": "Uygun değil"}

# Pazarın gerçek model bağımlılığı (skor etiketlenebilirliğinden AYRI): gol modeli (M10) üç pazarı da yarı bazlı
# takım güçlerinden (goals.model.REQUIRED) üretir; 3,5 Üst'ün sonuçlandırması yalnızca maç sonu skoru gerektirse de
# tahmini ilk yarı verisine bağlıdır. 1X2 motoru yalnızca maç sonu skorlarını kullanır.
MODEL_INPUTS = {
    "gol": {"BTTS_BOTH_HALVES_YES": ("ilk_yari", "mac_sonu"), "FT_OVER_3_5": ("ilk_yari", "mac_sonu"),
            "FH_OVER_1_5": ("ilk_yari", "mac_sonu")},
    "mac": {"1X2": ("mac_sonu",)},
}
GOAL_MARKETS = ("BTTS_BOTH_HALVES_YES", "FT_OVER_3_5", "FH_OVER_1_5")
MATCH_MARKETS = ("1X2",)
# Motorun yapılandırılmış tahmin kodları -> (neden kodu, gerektirdiği girdi; None = her pazar)
PREDICTION_CODE_MAP = {"TAKIM_GUCU_YOK": ("GEREKLI_ALAN_EKSIK", "ilk_yari"),
                       "TAKIM_N365_AZ": ("TAKIM_GECMISI_YETERSIZ", None),
                       "LIG_IY_ORANI_DUSUK": ("LIG_IY_ORANI_DUSUK", "ilk_yari"),
                       "OLASILIK_GECERSIZ": ("OLASILIK_GECERSIZ", None)}


def day_number(d) -> int:
    return int((pd.Timestamp(d).normalize() - EPOCH).days)


def day_to_date(day: int) -> dt.date:
    return (EPOCH + pd.Timedelta(days=int(day))).date()


def info_cutoff(as_of: dt.datetime) -> dt.date:
    """Bilgi kesimi: değerlendirme anının İstanbul tarihi. Bu günden ÖNCEKİ sonuçlar erişilebilir sayılır."""
    if as_of.tzinfo is None:
        raise ValueError("Değerlendirme anı zaman dilimi bilgisi içermeli")
    return as_of.astimezone(ISTANBUL).date()


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# Durum özetine giren alanlar: motorun o satırdan gerçekten TÜKETTİĞİ değerler (skor düzeltmesi de fark yaratır)
DIGEST_COLUMNS = {"gol": ("fthg", "ftag", "hthg", "htag"),
                  "mac": ("fthg", "ftag", "h_sot", "a_sot", "o_h", "o_d", "o_a", "o_o25", "o_u25")}


def _cell(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return f"{f:.6f}" if math.isfinite(f) else ""


def rows_digest(df: pd.DataFrame, kind: str) -> tuple[int, str]:
    """Bir lig durumunun kurulduğu maç kümesinin kimliği: (sayı, SHA-256). Gün, takımlar ve motorun tükettiği değerler
    (``DIGEST_COLUMNS``) girer. Motorlar eğitimde işledikleri satırlar için hesaplayıp durum nesnesine yazar
    (``row_digest``); uygunluk kontrolü depodaki aynı dönemle birebir karşılaştırır."""
    days = ((pd.to_datetime(df["date"]).dt.normalize() - EPOCH).dt.days).to_numpy()
    cols = [df[c].to_numpy() if c in df else np.full(len(df), np.nan) for c in DIGEST_COLUMNS[kind]]
    keys = sorted("|".join([str(int(d)), str(h), str(a)] + [_cell(c[i]) for c in cols])
                  for i, (d, h, a) in enumerate(zip(days, df["home"], df["away"])))
    return len(keys), hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------
# Kaynak kapsamı (tam sezon takvimi)
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class ScheduledMatch:
    date: dt.date
    raw_home: str
    raw_away: str
    home: str | None
    away: str | None
    status: str  # FINISHED / POSTPONED / CANCELLED / ABANDONED / SUSPENDED / SCHEDULED_OR_UNKNOWN


@dataclass(frozen=True)
class SourceCoverage:
    """Bir lig-sezon için kaynağın takvim kanıtı. ``complete``: takvim sezonun tamamını içeriyor."""
    league: str
    source: str
    season: str
    retrieved_at: dt.datetime
    matches: tuple[ScheduledMatch, ...]
    complete: bool
    detail: str
    sha256: str
    unmapped_names: tuple[str, ...] = ()

    @property
    def window(self) -> tuple[int, int] | None:
        if not self.matches:
            return None
        days = [day_number(m.date) for m in self.matches]
        return min(days), max(days)


def expected_per_team(league: str, n_teams: int) -> int:
    """Takım başına normal sezon maç sayısı (dizi araştırmasıyla aynı tek kaynak)."""
    from .sequences.timeline import REGULAR_LEN_OVERRIDE

    return int(REGULAR_LEN_OVERRIDE.get(league, 2 * (n_teams - 1)))


def _status_of(m: dict) -> str:
    st = str(m.get("status") or "").strip().upper()
    if st in ("POSTPONED", "CANCELLED", "CANCELED", "ABANDONED", "SUSPENDED"):
        return "CANCELLED" if st == "CANCELED" else st
    score = m.get("score")
    if isinstance(score, dict):
        score = score.get("ft")
    if isinstance(score, (list, tuple)) and len(score) >= 2 and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in score[:2]):
        return FINISHED
    if isinstance(m.get("score1"), int) and isinstance(m.get("score2"), int):
        return FINISHED
    return SCHEDULED_OR_UNKNOWN


def coverage_from_openfootball(data: bytes, league: str, season: str, retrieved_at: dt.datetime,
                               known_teams) -> SourceCoverage:
    """openfootball/football.json sezon dosyasından kapsam kanıtı (ağ isteği yapmaz)."""
    from .data.teams import match_team

    raw_bytes = data if isinstance(data, bytes) else str(data).encode("utf-8")
    sha = hashlib.sha256(raw_bytes).hexdigest()
    try:
        obj = json.loads(raw_bytes.decode("utf-8-sig"))
        raw = obj.get("matches", []) if isinstance(obj, dict) else []
        if not isinstance(raw, list):
            raw = []
    except (ValueError, UnicodeDecodeError):
        return SourceCoverage(league, "openfootball", season, retrieved_at, (), False, "dosya okunamadı", sha)
    known = sorted(set(known_teams))
    cache: dict[str, str | None] = {}

    def mapped(name: str) -> str | None:
        if name not in cache:
            cache[name] = match_team(name, known) if known else None
        return cache[name]

    out = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        t1, t2 = m.get("team1"), m.get("team2")
        t1 = t1.get("name") if isinstance(t1, dict) else t1
        t2 = t2.get("name") if isinstance(t2, dict) else t2
        d = pd.to_datetime(m.get("date"), errors="coerce")
        if not t1 or not t2 or pd.isna(d):
            continue
        out.append(ScheduledMatch(d.date(), str(t1), str(t2), mapped(str(t1)), mapped(str(t2)), _status_of(m)))
    unmapped = tuple(sorted(n for n, v in cache.items() if v is None))
    if not out:
        return SourceCoverage(league, "openfootball", season, retrieved_at, (), False, "dosyada maç yok", sha, unmapped)
    teams = sorted({m.raw_home for m in out} | {m.raw_away for m in out})
    need = expected_per_team(league, len(teams))
    per = dict.fromkeys(teams, 0)
    for m in out:
        per[m.raw_home] += 1
        per[m.raw_away] += 1
    short = [t for t, n in per.items() if n < need]
    complete = not short and len(teams) >= 4
    detail = (f"{len(out)} maç, {len(teams)} takım, takım başına beklenen ≥ {need}"
              + ("" if complete else f"; takvimi eksik takım: {len(short)}"))
    return SourceCoverage(league, "openfootball", season, retrieved_at, tuple(out), complete, detail, sha, unmapped)


# ----------------------------------------------------------------------------
# Model durumu görünümü (tahminde KULLANILAN durumun kapsamı)
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class LeagueStateView:
    last_day: int | None
    team_last: dict
    team_days: dict  # takım -> durumun bildiği maç günleri
    team_days_from: dict  # takım -> bu günden itibaren team_days tam (None = baştan beri tam)
    digest: str
    rows: tuple | None = None  # (sayı, sha) — durumun kurulduğu maçlar; eski model dosyalarında yok (None)


def league_state_digest(st) -> str:
    """Bir lig durumunun özeti (tahmin ile uygunluk sonucunun AYNI durumdan geldiğini bağlamak için)."""
    if st is None:
        return ""
    rows = getattr(st, "row_digest", None)
    if hasattr(st, "dates"):  # gol durumu
        body = ["gol", st.last_match_day, sorted((t, int(d)) for t, d in st.last_day.items()), st.season,
                st.season_n, rows]
    else:  # 1X2 durumu
        body = ["mac", st.last_day, sorted((t, f.last_day) for t, f in st.forms.items()), st.season, rows]
    return _digest(body)


@dataclass(frozen=True)
class StateView:
    kind: str  # "gol" | "mac"
    feature_version: str
    model_cutoff: str  # model parametrelerinin eğitim verisi kesimi (dinamik durumdan ayrı)
    leagues: dict
    available_since: dt.datetime | None  # durumun (ve içindeki bilginin) en geç bu anda var olduğu biliniyor
    train_sources: tuple[str, ...] | None  # modelin eğitildiği verinin kaynak etiketleri (biliniyorsa)
    fingerprint: str

    def scope(self, league: str, teams: tuple[str, ...]) -> dict:
        lv = self.leagues.get(league)
        out = {"tur": self.kind, "ozellik_surumu": self.feature_version, "model_egitim_kesimi": self.model_cutoff,
               "egitim_kaynaklari": list(self.train_sources) if self.train_sources is not None else None}
        if lv is None:
            return out
        out.update({
            "lig_durum_son_mac": str(day_to_date(lv.last_day)) if lv.last_day is not None else None,
            "takim_durum_son_mac": {t: (str(day_to_date(lv.team_last[t])) if t in lv.team_last else None)
                                    for t in teams},
            "durum_ozeti": lv.digest,
        })
        return out


def state_view(engine) -> StateView | None:
    """Gol motoru (GoalEngine) veya 1X2 motoru (PredictionEngine) durumunun kapsam görünümü."""
    if engine is None or not getattr(engine, "trained", False):
        return None
    kind = "gol" if hasattr(engine, "validated") else "mac"
    leagues = {}
    for lg, st in (getattr(engine, "states", None) or {}).items():
        team_last, team_days, team_from = {}, {}, {}
        if hasattr(st, "dates"):  # gol durumu: takım başına son 60 maç günü
            for t, dq in st.dates.items():
                days = [int(d) for d in dq]
                team_days[t] = frozenset(days)
                team_from[t] = days[0] if dq.maxlen is not None and len(days) >= dq.maxlen else None
            team_last = {t: int(d) for t, d in st.last_day.items()}
            last = st.last_match_day
        else:  # 1X2 durumu: takım başına son 6 maç
            for t, f in st.forms.items():
                days = [int(r[0]) for r in f.all]
                team_days[t] = frozenset(days)
                team_from[t] = min(days) if (days and f.all.maxlen is not None and len(days) >= f.all.maxlen) else None
                if f.last_day is not None:
                    team_last[t] = int(f.last_day)
            last = st.last_day
        rows = getattr(st, "row_digest", None)
        leagues[lg] = LeagueStateView(None if last is None else int(last), team_last, team_days, team_from,
                                      league_state_digest(st), tuple(rows) if rows is not None else None)
    if kind == "gol":
        from .goals.model import FEATURE_VERSION as fv

        cutoff = str(getattr(engine, "data_cutoff", "") or "")
        srcs = (getattr(engine, "manifest", None) or {}).get("sources")
    else:
        from .models.features import FEATURES

        fv = "mac-ozellik:" + hashlib.sha256(",".join(FEATURES).encode()).hexdigest()[:8]
        lmd = getattr(engine, "last_match_date", None)
        cutoff = str(pd.Timestamp(lmd).date()) if lmd is not None else ""
        srcs = getattr(engine, "train_sources", None)
    avail = getattr(engine, "state_available_since", None)
    if not (isinstance(avail, dt.datetime) and avail.tzinfo is not None):
        avail = None  # köken bilgisi yoksa uydurulmaz
    fp = _digest([kind, fv, cutoff, sorted((lg, v.digest) for lg, v in leagues.items())])
    return StateView(kind, fv, cutoff, leagues, avail, tuple(sorted(srcs)) if srcs is not None else None, fp)


# ----------------------------------------------------------------------------
# Kaynak hakları
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceUse:
    label: str
    key: str | None
    erisim: str  # IZINLI / ONAY_VAR / ONAY_YOK / BILINMIYOR
    sonuc_kullanimi: str  # IZINLI_BELGELI / DOGRULANAMADI / BILINMIYOR
    model_egitimi: str
    yeniden_dagitim: str


@dataclass(frozen=True)
class RightsStatus:
    by_label: dict  # etiket -> SourceUse

    def codes(self, data_labels, train_labels) -> list[str]:
        data_labels, train_labels = set(data_labels), set(train_labels)
        out = []
        for lb in data_labels | train_labels:
            u = self.by_label.get(lb)
            if u is None or u.key is None:
                out.append("KAYNAK_HAKKI_BILINMIYOR")
                continue
            if u.erisim not in ("IZINLI", "ONAY_VAR"):
                out.append("KAYNAK_ERISIM_IZNI_YOK")
            if lb in data_labels and u.sonuc_kullanimi != "IZINLI_BELGELI":
                out.append("KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI")
            if lb in train_labels and u.model_egitimi != "IZINLI_BELGELI":
                out.append("KAYNAK_EGITIM_HAKKI_DOGRULANAMADI")
        return sorted(set(out))

    def summary(self, labels) -> dict:
        return {lb: (asdict(self.by_label[lb]) if lb in self.by_label else None) for lb in sorted(set(labels))}


def rights_from_registry(labels, consent: dict | None) -> RightsStatus:
    """Kaynak kaydındaki BELGELİ kullanım kapsamı + kullanıcı onayı (onay yalnızca erişimi etkiler)."""
    from .data.source_registry import SOURCE_LABELS, SOURCES, USE_RIGHTS

    consent = consent or {}
    out = {}
    for lb in set(labels):
        key = SOURCE_LABELS.get(lb)
        if key is None or key not in USE_RIGHTS or key not in SOURCES:
            out[lb] = SourceUse(lb, None, "BILINMIYOR", "BILINMIYOR", "BILINMIYOR", "BILINMIYOR")
            continue
        r = USE_RIGHTS[key]
        erisim = "IZINLI" if not SOURCES[key].requires_consent else ("ONAY_VAR" if key in consent else "ONAY_YOK")
        out[lb] = SourceUse(lb, key, erisim, r["sonuc_kullanimi"], r["model_egitimi"], r["yeniden_dagitim"])
    return RightsStatus(out)


# ----------------------------------------------------------------------------
# Sonuç
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Eligibility:
    candidate_id: str  # kanonik maç kimliği veya (eşleşmeyen fikstür için) aday kimliği
    canonical_id: bool  # False: yalnızca kayıt takibi için aday kimliği; kanonik maç kimliği DEĞİLDİR
    league: str
    home: str
    away: str
    match_date: str
    market: str
    evaluated_at: str  # gerçek değerlendirme anı (UTC, ISO)
    info_cutoff: str  # bu günden ÖNCEKİ sonuçlar erişilebilir sayıldı (İstanbul tarihi)
    data_cutoff: str | None  # depoda bilgi kesiminden önceki son lig maçı
    data_scope: dict
    state_scope: dict
    freshness: str
    continuity: str  # TAM / EKSIK / BILINMIYOR
    team_mapping: str  # ESLESTI / ESLESMEDI / KONTROL_EDILMEDI
    required_fields: str  # YETERLI / EKSIK / KONTROL_EDILMEDI
    source_use: dict
    reasons: tuple[str, ...]
    forecast_ok: bool
    bet_ok: bool
    primary_text: str
    fix_text: str
    policy_version: str = POLICY_VERSION
    fingerprint: str = ""

    @property
    def status_key(self) -> str:
        if self.forecast_ok:
            return "UYGUN"
        if self.freshness in (KNOWN_STALE, UNKNOWN):
            return self.freshness
        return "ENGELLI"

    @property
    def status_label(self) -> str:
        """Renkten bağımsız okunabilir durum: Kullanılabilir / Eksik veri / Doğrulanamıyor / Uygun değil."""
        return STATUS_TEXT[self.status_key]

    @property
    def as_of_day(self) -> dt.date:
        return dt.date.fromisoformat(self.info_cutoff)

    @property
    def state_digest(self) -> str:
        return str(self.state_scope.get("durum_ozeti", "") or "")

    @property
    def lead_code(self) -> str | None:
        return lead_reason(self.reasons)

    def short_text(self) -> str:
        """Tek satır: durum, somut neden, veri kesimi ve gereken düzeltme."""
        cut = self.data_cutoff or "-"
        if self.forecast_ok and self.bet_ok:
            return f"{self.status_label} (veri kesimi {cut})"
        if self.forecast_ok:
            return (f"{self.status_label}; bahis adayı değil: {self.primary_text} [{self.lead_code}] — "
                    f"veri kesimi {cut}; gereken: {self.fix_text}")
        return (f"{self.status_label}: {self.primary_text} [{self.lead_code}] — veri kesimi {cut}; "
                f"gereken: {self.fix_text}")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reasons"] = list(self.reasons)
        d["status_label"] = self.status_label
        return d

    def compact(self) -> dict:
        """Kayıtlara geriye uyumlu ek alan olarak yazılan özet."""
        return {"politika": self.policy_version, "guncellik": self.freshness, "tahmin_uygun": self.forecast_ok,
                "bahis_veri_uygun": self.bet_ok, "nedenler": list(self.reasons), "bilgi_kesimi": self.info_cutoff,
                "veri_kesimi": self.data_cutoff, "degerlendirme_ani": self.evaluated_at,
                "aday_kimlik": self.candidate_id, "kanonik_kimlik": self.canonical_id,
                "durum_ozeti": self.state_digest[:16], "ozet": self.fingerprint[:16]}


def candidate_id(source: str, league: str, date, raw_home: str, raw_away: str) -> str:
    """Eşleşmeyen fikstür için kararlı aday kimliği (kanonik maç kimliği DEĞİLDİR)."""
    key = "|".join([str(source or ""), str(league), str(pd.Timestamp(date).date()), str(raw_home), str(raw_away)])
    return "aday:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _finalize(base: dict, codes, markets, per_market: dict, evidence_checked: bool,
              required_checked: bool) -> dict:
    out = {}
    for mk in markets:
        cs = tuple(sorted(set(codes) | set(per_market.get(mk, ()))))
        stale = any(REASONS[c].freshness == KNOWN_STALE for c in cs)
        unknown = any(REASONS[c].freshness == UNKNOWN for c in cs) or not evidence_checked
        freshness = KNOWN_STALE if stale else (UNKNOWN if unknown else VERIFIED_CURRENT)
        forecast_ok = (freshness == VERIFIED_CURRENT and required_checked
                       and not any(REASONS[c].blocks == "tahmin" for c in cs))
        bet_ok = forecast_ok and not any(REASONS[c].blocks == "bahis" for c in cs)
        blocking = [c for c in cs if REASONS[c].blocks != "yok"]
        if not blocking and not forecast_ok:
            blocking = ["BAGLAM_YOK"]
            cs = tuple(sorted(set(cs) | {"BAGLAM_YOK"}))
        lead = lead_reason(blocking)
        primary, fix = (REASONS[lead].text, REASONS[lead].fix) if lead else ("Veri uygunluğu doğrulandı.", "-")
        continuity = "EKSIK" if stale else ("BILINMIYOR" if unknown else "TAM")
        if any(c in ("GEREKLI_ALAN_EKSIK", "TAKIM_GECMISI_YETERSIZ") for c in cs):
            req = "EKSIK"
        else:
            req = "YETERLI" if required_checked else "KONTROL_EDILMEDI"
        e = dict(base, market=mk, freshness=freshness, continuity=continuity, required_fields=req, reasons=cs,
                 forecast_ok=forecast_ok, bet_ok=bet_ok, primary_text=primary, fix_text=fix)
        fp = _digest({k: v for k, v in e.items() if k != "evaluated_at"})
        out[mk] = Eligibility(**e, fingerprint=fp)
    return out


# ----------------------------------------------------------------------------
# Bağlam
# ----------------------------------------------------------------------------

class EligibilityContext:
    """Veri deposu + kullanılan model durumu + kaynak kapsamı + haklar.

    Bağlamın parmak izi bunlardan herhangi biri değişince değişir; önbellek parmak izine bağlıdır (eski "uygun"
    sonucu yeni veri/durum/kapsamla kullanılmaz)."""

    def __init__(self, matches: pd.DataFrame | None, state: StateView | None,
                 coverages: dict | None = None, rights: RightsStatus | None = None,
                 consent: dict | None = None):
        self.state = state
        self.coverages = {lg: tuple(v) for lg, v in (coverages or {}).items()}
        need = ("league", "date", "home", "away", "fthg", "ftag")
        m = matches
        if m is None or m.empty or not all(c in m for c in need):
            m = pd.DataFrame({c: pd.Series(dtype=object) for c in need + ("season", "hthg", "htag", "source")})
        m = m[pd.to_numeric(m["fthg"], errors="coerce").notna() & pd.to_numeric(m["ftag"], errors="coerce").notna()]
        # Modelin bu satırı işleyip işlemediği: gol durumu karantinadaki (geçersiz skorlu) kayıtları atlar.
        if state is not None and state.kind == "gol" and len(m) and "hthg" in m and "htag" in m:
            from .goals.markets import frame_issues

            ingest = (frame_issues(m) == "").to_numpy()
        else:
            ingest = np.ones(len(m), dtype=bool)
        keep = DIGEST_COLUMNS.get(state.kind, ()) if state is not None else ()
        cols = [c for c in ("league", "season", "date", "home", "away", "source") + tuple(keep) if c in m]
        m = m[cols].copy()
        m["date"] = pd.to_datetime(m["date"]).dt.normalize()
        m["day"] = ((m["date"] - EPOCH).dt.days).astype(int)
        m["ingest"] = ingest
        for c in ("source", "season"):
            if c not in m:
                m[c] = None
        self.matches = m
        self._by_league = {lg: g.sort_values("day", kind="mergesort") for lg, g in m.groupby("league", sort=False)}
        labels = set(m["source"].dropna().astype(str))
        train = set(state.train_sources) if (state is not None and state.train_sources is not None) else labels
        self.rights = rights if rights is not None else rights_from_registry(labels | train, consent)
        h = hashlib.sha256()
        h.update(pd.util.hash_pandas_object(m[["league", "day", "home", "away", "source", "ingest"]].astype(str),
                                            index=False).values.tobytes() if len(m) else b"bos")
        h.update((state.fingerprint if state else "durum-yok").encode())
        if state is not None:
            h.update(str(state.available_since).encode())
        for lg in sorted(self.coverages):
            for c in self.coverages[lg]:
                h.update(f"{lg}|{c.season}|{c.sha256}|{c.retrieved_at.isoformat()}".encode())
        h.update(_digest({k: asdict(v) for k, v in self.rights.by_label.items()}).encode())
        self.fingerprint = h.hexdigest()
        self._cache: dict = {}
        self._rows_cache: dict = {}

    def league_matches(self, league: str) -> pd.DataFrame:
        return self._by_league.get(league, self.matches.iloc[0:0])

    def _rows(self, league: str, last_day: int) -> tuple[int, str]:
        """Depoda modelin işleyeceği, ``last_day``e kadarki lig satırlarının kimliği (önbellekli)."""
        key = (league, int(last_day))
        hit = self._rows_cache.get(key)
        if hit is None:
            g = self.league_matches(league)
            g = g[g["ingest"] & (g["day"] <= last_day)]
            hit = rows_digest(g, self.state.kind)
            self._rows_cache[key] = hit
        return hit

    def recent_teams(self, league: str, seasons: int = 2) -> list[str]:
        g = self.league_matches(league)
        if g.empty:
            return []
        recent = sorted(g["season"].dropna().astype(str).unique())[-seasons:]
        g = g[g["season"].astype(str).isin(recent)] if recent else g
        return sorted(set(g["home"]) | set(g["away"]))

    # ------------------------------------------------------------------ değerlendirme
    def evaluate(self, *, league: str, date, home: str, away: str, as_of: dt.datetime, markets,
                 source: str = "", mapped: bool = True, raw_home: str | None = None, raw_away: str | None = None,
                 prediction_codes=None, event_id: str | None = None) -> dict:
        """Bir fikstür için pazar başına uygunluk (önbellekli; bağlam parmak izi değişince yeniden hesaplanır).

        ``prediction_codes``: motorun yapılandırılmış veri kodları (``GoalPrediction.data_codes``); None ise gerekli
        alan yeterliliği "KONTROL_EDILMEDI" olur ve tahmin uygun sayılmaz."""
        markets = tuple(markets)
        cut = info_cutoff(as_of)
        pcodes = None if prediction_codes is None else tuple(sorted(prediction_codes))
        live = self._live(as_of)
        usable = tuple(sorted(c.sha256 for c in self.coverages.get(league, ()) if c.retrieved_at <= as_of))
        key = (self.fingerprint, league, str(pd.Timestamp(date).date()), home, away, bool(mapped), raw_home,
               raw_away, source, pcodes, markets, cut, live, usable, event_id)
        hit = self._cache.get(key)
        if hit is None:
            hit = self._evaluate(league, date, home, away, as_of, cut, live, markets, source, mapped, raw_home,
                                 raw_away, pcodes, event_id)
            self._cache[key] = hit
        stamp = as_of.astimezone(dt.timezone.utc).isoformat()
        return {mk: _restamp(e, stamp) for mk, e in hit.items()}

    def _live(self, as_of: dt.datetime) -> bool:
        """Durumun değerlendirme anından önce var olduğu biliniyor mu (o zaman içindeki bilgi o anda vardı)."""
        av = self.state.available_since if self.state is not None else None
        return av is not None and as_of >= av

    def _evaluate(self, league, date, home, away, as_of, cut, live, markets, source, mapped, raw_home, raw_away,
                  pcodes, eid):
        from .goals.ledger import event_id as make_event_id

        cut_day = day_number(cut)
        fx_day = day_number(date)
        kind = self.state.kind if self.state else None
        codes: list[str] = []
        detail: dict = {}
        if eid is None:
            eid = (make_event_id(league, pd.Timestamp(date).date(), home, away) if mapped
                   else candidate_id(source, league, date, raw_home or home, raw_away or away))
        g_all = self.league_matches(league)
        g = g_all[g_all["day"] < cut_day]  # bilgi kesiminden ÖNCE erişilebilir sonuçlar
        labels = sorted(set(g["source"].dropna().astype(str)))
        # Model eğitim verisinin kaynakları: model dosyasında kayıtlıysa o; değilse (ör. 1X2 motoru) depodaki bütün
        # kaynaklar (model tüm liglerle eğitildiği için ihtiyatlı varsayım; köken bilgisi uydurulmaz)
        train = (sorted(self.state.train_sources) if (self.state is not None and self.state.train_sources is not None)
                 else sorted(set(self.matches["source"].dropna().astype(str))))
        base = dict(candidate_id=eid, canonical_id=bool(mapped), league=league, home=home, away=away,
                    match_date=str(pd.Timestamp(date).date()), evaluated_at="", info_cutoff=str(cut),
                    team_mapping="ESLESTI" if mapped else "ESLESMEDI",
                    data_cutoff=str(day_to_date(int(g["day"].max()))) if len(g) else None,
                    data_scope={"lig_mac_sayisi": int(len(g)), "kaynaklar": labels, "kapsam_kanitlari": [],
                                "depo_ozeti": _digest(g[["day", "home", "away"]].astype(str).values.tolist())[:16]},
                    state_scope=self.state.scope(league, (home, away)) if self.state else {"tur": None},
                    source_use=self.rights.summary(set(labels) | set(train)))
        if fx_day < cut_day:
            codes.append("MAC_GECMISTE")
        if not mapped:
            codes.append("TAKIM_ESLESMEDI")
            return _finalize(base, codes, markets, {}, evidence_checked=False, required_checked=False)
        codes += self.rights.codes(labels, train)
        # 1) Model durumu ↔ depo (yalnızca modelin işlediği satırlar)
        gi = g[g["ingest"]]
        if self.state is None:
            codes.append("MODEL_YOK")
        else:
            lv = self.state.leagues.get(league)
            if lv is None:
                codes.append("LIG_MODEL_KAPSAMI_DISI")
            else:
                if any(t not in lv.team_last for t in (home, away)):
                    codes.append("TAKIM_DURUMDA_YOK")
                if lv.last_day is not None and lv.last_day >= cut_day and not live:
                    codes.append("DURUM_KARAR_ANINDAN_SONRA")
                behind = int((gi["day"] > (lv.last_day if lv.last_day is not None else -10 ** 9)).sum())
                team_gaps = {}
                for t in (home, away):
                    tg = gi[(gi["home"] == t) | (gi["away"] == t)]
                    known = lv.team_days.get(t, frozenset())
                    since = lv.team_days_from.get(t)
                    days = [int(d) for d in tg["day"] if since is None or int(d) >= since]
                    miss = sorted(d for d in days if d not in known)
                    if miss:
                        team_gaps[t] = [str(day_to_date(d)) for d in miss[-5:]]
                # Durumun kurulduğu maç kümesi ↔ depodaki aynı dönem (modelin işlediği satırlar), birebir
                stale_rows = mismatch = False
                if lv.rows is None:
                    codes.append("DURUM_KOKENI_YOK")
                elif lv.last_day is not None:
                    n_store, sha_store = self._rows(league, lv.last_day)
                    if (n_store, sha_store) != tuple(lv.rows):
                        stale_rows = n_store > lv.rows[0]
                        mismatch = not stale_rows
                        detail["durum_satirlari"] = {"durum": int(lv.rows[0]), "depo": int(n_store)}
                if behind or team_gaps or stale_rows:
                    codes.append("DURUM_DEPODAN_GERIDE")
                    detail["durum_depodan_geride"] = {"lig_mac": behind, "takim": team_gaps}
                if mismatch:
                    codes.append("DURUM_VERIYLE_UYUSMUYOR")
        # Takımın pencere içinde karantinada (modelin kullanmadığı) kaydı: kaynak takviminden bağımsız bilinen eksik
        qg = g[~g["ingest"] & (g["day"] >= cut_day - LOOKBACK_DAYS)]
        bad = {t: [str(day_to_date(int(d))) for d in qg[(qg["home"] == t) | (qg["away"] == t)]["day"]]
               for t in (home, away)}
        bad = {t: v for t, v in bad.items() if v}
        if bad:
            codes.append("DEPODA_GECERSIZ_SKOR")
            detail["gecersiz_skorlu_depo"] = bad
        # Takım geçmişi (depodan; modelden bağımsız yapısal ölçü)
        for t in (home, away):
            n = int((((g["home"] == t) | (g["away"] == t)) & (g["day"] >= cut_day - LOOKBACK_DAYS)).sum())
            if n < MIN_TEAM_MATCHES:
                codes.append("TAKIM_GECMISI_YETERSIZ")
                detail.setdefault("takim_mac_365", {})[t] = n
        # 2) Depo ↔ kaynak takvimi ve kapsam
        covs = self.coverages.get(league, ())
        usable = [c for c in covs if c.retrieved_at <= as_of]
        complete = [c for c in usable if c.complete]
        evidence_checked = bool(complete)
        if not covs:
            codes.append("KAYNAK_KAPSAMI_YOK")
        elif not usable:
            codes.append("KAYNAK_KARAR_ANINDAN_SONRA")
        elif not complete:
            codes.append("KAYNAK_KAPSAMI_KISMI")
        for c in usable:
            base["data_scope"]["kapsam_kanitlari"].append({
                "kaynak": c.source, "sezon": c.season, "alinma": c.retrieved_at.isoformat(), "tam": c.complete,
                "aciklama": c.detail, "ozet": c.sha256[:16]})
        if complete:
            near = g_all[g_all["day"] < cut_day + PAIR_DAY_TOLERANCE]  # aynı maçın yerel tarih farkı (sınırda da)
            self._check_against_source(home, away, near[near["ingest"]], near, complete, cut_day, codes, detail, base)
            for t in (home, away):
                if not any(t in (m.home, m.away) for c in complete for m in c.matches):
                    codes.append("KAYNAK_ESLESME_BELIRSIZ")
                elif not self._window_covered(league, t, gi, complete, cut_day):  # modelin işlediği satırlar
                    codes.append("KAYNAK_ARALIK_DISI")
        # 3) Modelin gerçek girdi bağımlılığı (motorun yapılandırılmış kodlarından; metin aranmaz)
        per_market: dict[str, tuple] = {}
        for mk in markets:
            inputs = MODEL_INPUTS.get(kind or "", {}).get(mk, ("mac_sonu",))
            req = []
            for pc in pcodes or ():
                code, _, only = pc.partition(":")  # "KOD:PAZAR" yalnızca o pazara uygulanır
                if only and only != mk:
                    continue
                hit = PREDICTION_CODE_MAP.get(code)
                if hit and (hit[1] is None or hit[1] in inputs):
                    req.append(hit[0])
            per_market[mk] = tuple(req)
        base["data_scope"]["ayrinti"] = detail
        return _finalize(base, codes, markets, per_market, evidence_checked, required_checked=pcodes is not None)

    @staticmethod
    def _check_against_source(home, away, g_pair, g_any, complete, cut_day, codes, detail, base) -> None:
        """Kaynakta beklenen maçlar ↔ depodaki maçlar (takım düzeyi ve paylaşılan lig durumu).

        ``g_pair``: modelin işlediği depo satırları (eşleştirme; bilgi kesimi + tarih toleransı); ``g_any``: aynı aralıkta
        karantinadakiler dahil bütün satırlar (geçersiz skorlu kaydı "yok" yerine ayrıca adlandırmak için)."""
        def pairs(df):
            out: dict[tuple, list[int]] = {}
            for h, a, d in zip(df["home"], df["away"], df["day"]):
                out.setdefault((h, a), []).append(int(d))
            return out

        ok_days, any_days = pairs(g_pair), pairs(g_any)

        def found(idx, m: ScheduledMatch) -> bool:
            md = day_number(m.date)
            return any(abs(d - md) <= PAIR_DAY_TOLERANCE for d in idx.get((m.home, m.away), ()))

        team_missing: dict[str, list[str]] = {}
        team_invalid: dict[str, list[str]] = {}
        team_unknown: dict[str, list[str]] = {}
        team_unmapped: dict[str, list[str]] = {}
        league: dict[str, dict[str, int]] = {}  # sezon -> pencere içindeki diğer-takım sayımları
        unmapped: set[str] = set()
        checked = {"takimlar": [home, away], "donem_sonu": str(day_to_date(cut_day - 1)), "kaynak_sezonlari": []}
        for c in complete:
            unmapped |= set(c.unmapped_names)
            checked["kaynak_sezonlari"].append(c.season)
            cnt = league.setdefault(c.season, {"gecmis": 0, "eksik": 0, "belirsiz": 0})
            for m in c.matches:
                md = day_number(m.date)
                if md >= cut_day or m.status in NOT_PLAYED_STATUSES:
                    continue  # aynı gün / gelecek veya ertelenen-iptal edilen: eksik tamamlanmış maç sayılmaz
                ours = [t for t in (home, away) if t in (m.home, m.away)]
                in_window = md >= cut_day - LOOKBACK_DAYS  # paylaşılan lig durumu için ilgili dönem
                if not ours and in_window:
                    cnt["gecmis"] += 1
                if m.home is None or m.away is None:
                    # Kaynaktaki takım adı eşleşmedi: depoda olup olmadığı güvenilir biçimde bilinemez (UNKNOWN;
                    # yanlışlıkla "eksik" sayılmaz)
                    for t in ours:
                        team_unmapped.setdefault(t, []).append(str(m.date))
                    if not ours and in_window:
                        cnt["belirsiz"] += 1
                    continue
                if found(ok_days, m):
                    continue
                if m.status == FINISHED:
                    bucket = team_invalid if found(any_days, m) else team_missing
                    for t in ours:
                        bucket.setdefault(t, []).append(str(m.date))
                    if not ours and in_window:
                        cnt["eksik"] += 1
                else:
                    for t in ours:
                        team_unknown.setdefault(t, []).append(str(m.date))
                    if not ours and in_window:
                        cnt["belirsiz"] += 1
        checked.update({"eksik_tamamlanmis": {t: len(v) for t, v in team_missing.items()},
                        "gecersiz_skorlu": {t: len(v) for t, v in team_invalid.items()},
                        "sonucu_belirsiz": {t: len(v) for t, v in team_unknown.items()}})
        base["data_scope"]["kontrol"] = checked
        if team_missing:
            codes.append("DEPODA_EKSIK_MAC")
            detail["depoda_eksik"] = {t: v[-5:] for t, v in team_missing.items()}
        if team_invalid:
            codes.append("DEPODA_GECERSIZ_SKOR")
            detail["gecersiz_skorlu"] = {t: v[-5:] for t, v in team_invalid.items()}
        if team_unknown:
            codes.append("KAYNAK_DURUMU_BELIRSIZ")
            detail["sonucu_belirsiz"] = {t: v[-5:] for t, v in team_unknown.items()}
        if team_unmapped:
            codes.append("KAYNAK_ESLESME_BELIRSIZ")
            detail["rakip_adi_eslesmeyen"] = {t: v[-5:] for t, v in team_unmapped.items()}
        # Lig düzeyi: oran her kaynak sezonu için AYRI ve yalnızca son 365 gün içinde hesaplanır; ek sezon kanıtı
        # yalnızca engel ekleyebilir, mevcut engeli seyreltemez.
        # Küçük paydada (sezon başı, pencere kuyruğu) tek maç bütün ligi engellemesin: sınır en az 1 maç.
        partial = False
        for cnt in league.values():
            if not cnt["gecmis"]:
                continue
            limit = max(1.0, LEAGUE_MISSING_SHARE * cnt["gecmis"])
            if cnt["eksik"] > limit:
                codes.append("LIG_DURUMU_EKSIK")
            elif cnt["eksik"]:
                partial = True
            if cnt["belirsiz"] > limit:
                codes.append("LIG_DURUMU_BELIRSIZ")
        if partial and "LIG_DURUMU_EKSIK" not in codes:
            codes.append("LIG_DURUMU_KISMEN_EKSIK")
        detail["lig_duzeyi"] = league
        if unmapped:
            codes.append("KAYNAK_ESLESMEMIS_ADLAR")
            detail["eslesmeyen_kaynak_adi_sayisi"] = len(unmapped)

    @staticmethod
    def _store_season_complete(league: str, sg: pd.DataFrame) -> bool:
        """Depodaki kapanmış bir sezon, kaynak takvimi olmadan SEZON düzeyinde tam sayılabilir mi?

        Yalnızca yapısı kesin bilinen düz çift devreli sezon kabul edilir: her eşleşme tam iki kez (birer kez iç ve
        dış saha), her takım tam 2·(n−1) maç. Split/play-off'lu liglerde (``REGULAR_LEN_OVERRIDE``) toplam maç sayısı
        depodan bilinemediği için depo-içi kanıt kabul edilmez (kaynak takvimi gerekir). Yalnızca hedef takımın tamlığı
        paylaşılan lig durumunu kanıtlamaz."""
        from .sequences.timeline import REGULAR_LEN_OVERRIDE

        if league in REGULAR_LEN_OVERRIDE:
            return False
        teams = pd.concat([sg["home"], sg["away"]]).value_counts()
        n = len(teams)
        if n < 4 or not (teams == 2 * (n - 1)).all() or len(sg) != n * (n - 1):
            return False
        return not sg.duplicated(subset=["home", "away"]).any()

    @classmethod
    def _window_covered(cls, league: str, team: str, g: pd.DataFrame, complete: list, cut_day: int) -> bool:
        """Takımın gerekli pencere aralığı kanıtla kapsanıyor mu?"""
        tg = g[(g["home"] == team) | (g["away"] == team)]
        first = int(tg["day"].min()) if len(tg) else cut_day
        w0 = max(cut_day - LOOKBACK_DAYS, first)
        w1 = cut_day - 1
        if w0 > w1:
            return True
        intervals: list[tuple[int, int, str]] = []
        for c in complete:
            if c.window is not None:
                intervals.append((c.window[0], c.window[1], c.season))
        cov_seasons = {c.season for c in complete}
        for season, sg in g.groupby(g["season"].astype(str)):
            if season in cov_seasons or season in ("None", "nan"):
                continue
            if int(sg["day"].max()) >= cut_day - 1:
                continue  # süren sezon yalnızca kaynak takvimiyle doğrulanır
            if cls._store_season_complete(league, sg):  # kapanmış sezon depoda sezon düzeyinde tam (iç tutarlılık)
                intervals.append((int(sg["day"].min()), int(sg["day"].max()), season))
        if not intervals:
            return False
        intervals.sort()
        merged = [list(intervals[0])]
        for s, e, season in intervals[1:]:
            ps, pe, pseason = merged[-1]
            if s <= pe + 1 or _next_season(pseason) == season:  # bitişik veya ardışık sezon (sezon arası)
                merged[-1] = [ps, max(pe, e), season]
            else:
                merged.append([s, e, season])
        return any(s <= w0 and e >= w1 for s, e, _ in merged)


def _next_season(season: str) -> str:
    s = str(season)
    try:
        if "/" in s:
            y = int(s.split("/")[0]) + 1
            return f"{y}/{(y + 1) % 100:02d}"
        if "-" in s:
            y = int(s.split("-")[0]) + 1
            return f"{y}/{(y + 1) % 100:02d}"
        if s.isdigit():
            return str(int(s) + 1)
    except ValueError:
        return ""
    return ""


def _restamp(e: Eligibility, stamp: str) -> Eligibility:
    """Önbellekten gelen sonuca gerçek değerlendirme anını yazar (aynı gün, aynı parmak izi)."""
    d = asdict(e)
    d["evaluated_at"] = stamp
    d["reasons"] = tuple(d["reasons"])
    return Eligibility(**d)


def not_evaluated(event_id: str, market: str, as_of: dt.datetime | None = None,
                  canonical: bool | None = None) -> Eligibility:
    """Bağlam verilmediğinde kullanılan sonuç: uygun değil (``BAGLAM_YOK``)."""
    now = as_of or dt.datetime.now(dt.timezone.utc)
    canonical = (not str(event_id).startswith("aday:")) if canonical is None else bool(canonical)
    base = dict(candidate_id=event_id, canonical_id=canonical, league="", home="", away="", match_date="",
                evaluated_at=now.astimezone(dt.timezone.utc).isoformat(), info_cutoff=str(info_cutoff(now)),
                data_cutoff=None, data_scope={}, state_scope={}, source_use={}, team_mapping="KONTROL_EDILMEDI")
    return _finalize(base, ["BAGLAM_YOK"], (market,), {}, evidence_checked=False, required_checked=False)[market]


def _context_mismatch(e, event_id: str, market: str, at: dt.datetime, state_digest: str | None) -> list[str]:
    """Sonuç bu maç, pazar, gün, politika ve model durumu için mi (ve ``at`` anından önce mi) üretildi?"""
    if not isinstance(e, Eligibility) or "BAGLAM_YOK" in e.reasons:
        return ["BAGLAM_YOK"]
    if (e.candidate_id != event_id or e.market != market or e.policy_version != POLICY_VERSION
            or e.as_of_day != info_cutoff(at)):
        return ["BAGLAM_UYUSMUYOR"]
    try:  # o andan SONRA değerlendirilmiş sonuç o anın kanıtı olamaz
        if dt.datetime.fromisoformat(e.evaluated_at) > at + dt.timedelta(seconds=1):
            return ["BAGLAM_UYUSMUYOR"]
    except (TypeError, ValueError):
        return ["BAGLAM_UYUSMUYOR"]
    if state_digest is not None and e.state_digest != state_digest:
        return ["BAGLAM_UYUSMUYOR"]
    return []


def check_for_decision(e, event_id: str, market: str, decision_time: dt.datetime,
                       state_digest: str | None = None) -> list[str]:
    """Karar motorunun denetimi. Boş liste = veri açısından bahis adayına engel yok. Bağlam yoksa, başka maça/
    pazara/güne/model durumuna aitse ya da veri bahis için uygun değilse engel kodları döner."""
    mismatch = _context_mismatch(e, event_id, market, decision_time, state_digest)
    if mismatch:
        return mismatch
    if not e.bet_ok:
        return [c for c in e.reasons if REASONS[c].blocks != "yok"] or ["BAGLAM_YOK"]
    return []


def check_for_display(e, event_id: str, market: str, now: dt.datetime, state_digest: str | None = None) -> list[str]:
    """Gösterim denetimi: olasılık ancak sonuç BUGÜN (bilgi kesimi günü), bu maç/pazar ve bu model durumu için
    üretilmiş ve tahmine izin veriyorsa gösterilir. Boş liste = gösterilebilir. Gün değişince eski sonuç kullanılmaz."""
    mismatch = _context_mismatch(e, event_id, market, now, state_digest)
    if mismatch:
        return mismatch
    if not e.forecast_ok:
        return [c for c in e.reasons if REASONS[c].blocks == "tahmin"] or ["BAGLAM_YOK"]
    return []


def display_label(e, codes) -> tuple[str, str]:
    """(kısa durum, ayrıntı metni). Renkten bağımsız: Kullanılabilir / Doğrulanamıyor / Eksik veri / Uygun değil."""
    if e is None or (codes and codes[0] in ("BAGLAM_YOK", "BAGLAM_UYUSMUYOR")):
        code = codes[0] if codes else "BAGLAM_YOK"
        return f"Doğrulanamıyor · {code}", f"{REASONS[code].text} [{code}] Gereken: {REASONS[code].fix}"
    if codes:
        return f"{e.status_label} · {e.lead_code}", e.short_text()
    if not e.bet_ok:
        return f"{e.status_label} · bahis adayı değil ({e.lead_code})", e.short_text()
    return e.status_label, e.short_text()


def valid_probability(p) -> bool:
    if p is None or isinstance(p, bool):
        return False
    try:
        f = float(p)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and 0.0 <= f <= 1.0


def finite_or_none(v):
    """Kamuya açık JSON/CSV için: NaN/sonsuz değerler None olur (sıfır olarak doldurulmaz)."""
    if v is None or isinstance(v, bool):
        return v
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def reason_texts(codes) -> str:
    return "; ".join(f"{c}: {REASONS[c].text}" for c in codes if c in REASONS)


# ----------------------------------------------------------------------------
# Uygulama ve CLI için: önbellekteki kaynak dosyalarından kapsam (ağ isteği yok)
# ----------------------------------------------------------------------------

def cached_coverages(raw_dir, leagues, today: dt.date, known_teams_by_league: dict) -> dict:
    """Veri güncellemesinin önbelleğe aldığı openfootball sezon dosyaları (içinde bulunulan ve önceki sezon).

    Alınma anı dosyanın değiştirilme zamanıdır (güncellemenin dosyayı yazdığı an)."""
    from pathlib import Path

    from .data.leagues import LEAGUES, openfootball_season

    out: dict[str, list[SourceCoverage]] = {}
    for code in leagues:
        lg = LEAGUES.get(code)
        if lg is None or not lg.openfootball:
            continue
        prev = today - dt.timedelta(days=365)
        for season in sorted({openfootball_season(today, lg.calendar_year),
                              openfootball_season(prev, lg.calendar_year)}):
            path = Path(raw_dir) / "openfootball" / season / f"{lg.openfootball}.json"
            if not path.is_file():
                continue
            at = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
            out.setdefault(code, []).append(coverage_from_openfootball(
                path.read_bytes(), code, _norm_season(season, lg.calendar_year), at,
                known_teams_by_league.get(code, ())))
    return out


def _norm_season(season: str, calendar_year: bool) -> str:
    """openfootball "2026-27" -> depo etiketi "2026/27" (takvim yılı ligleri aynen)."""
    if calendar_year or "-" not in season:
        return season
    y = int(season.split("-")[0])
    return f"{y}/{(y + 1) % 100:02d}"


def build_context(store, engine, consent: dict | None, today: dt.date | None = None) -> EligibilityContext:
    """Uygulama/CLI için bağlam: veri deposu + motorun durumu + önbellekteki kaynak takvimleri + kayıtlı haklar."""
    today = today or dt.datetime.now(ISTANBUL).date()
    matches = getattr(store, "matches", None)
    sv = state_view(engine)
    leagues = sorted(set(matches["league"].unique())) if matches is not None and not matches.empty else []
    tmp = EligibilityContext(matches, None, rights=RightsStatus({}))
    known = {lg: tmp.recent_teams(lg) for lg in leagues}
    covs = cached_coverages(getattr(store, "raw_dir", "."), leagues, today, known)
    return EligibilityContext(matches, sv, covs, consent=consent)


@dataclass
class FixtureVerdict:
    """Bir fikstürün pazar başına uygunluğu ve (varsa) tahmini — kullanıcı yollarında ortak kullanım."""
    league: str
    date: pd.Timestamp
    time: str
    home: str
    away: str
    candidate_id: str
    canonical_id: bool
    by_market: dict = field(default_factory=dict)
    prediction: object | None = None

    def get(self, market: str) -> Eligibility | None:
        return self.by_market.get(market)

    @property
    def forecast_ok(self) -> bool:
        return bool(self.by_market) and all(e.forecast_ok for e in self.by_market.values())

    @property
    def any_forecast_ok(self) -> bool:
        return any(e.forecast_ok for e in self.by_market.values())

    def display_codes(self, market: str, now: dt.datetime) -> list[str]:
        """Gösterim engeli (boş = bu anda gösterilebilir): gün, kimlik ve model durumu eşleşmesi dahil."""
        if self.prediction is None:
            e = self.by_market.get(market)
            return ([c for c in e.reasons if REASONS[c].blocks == "tahmin"] or ["BAGLAM_YOK"]) if e else ["BAGLAM_YOK"]
        digest = getattr(self.prediction, "state_digest", None) or None
        return check_for_display(self.by_market.get(market), self.candidate_id, market, now, digest)

    def usable(self, market: str, now: dt.datetime) -> bool:
        return self.prediction is not None and not self.display_codes(market, now)

    def any_usable(self, now: dt.datetime) -> bool:
        return any(self.usable(mk, now) for mk in self.by_market)

    def all_usable(self, now: dt.datetime) -> bool:
        return bool(self.by_market) and all(self.usable(mk, now) for mk in self.by_market)

    def first(self) -> Eligibility | None:
        return next(iter(self.by_market.values()), None)


# ----------------------------------------------------------------------------
# 1X2 (maç sonucu) motoru için ince bağlayıcı: aynı merkezi değerlendirme
# ----------------------------------------------------------------------------

def gate_match_prediction(ctx: EligibilityContext | None, pred, as_of: dt.datetime) -> Eligibility:
    """1X2 tahminine uygunluk sonucunu bağlar (``pred.eligibility``) ve döndürür."""
    eid = pred.event_id
    if ctx is None:
        e = not_evaluated(eid, "1X2", as_of, canonical=True)
    else:
        ok = bool(np.all(np.isfinite(np.asarray(pred.p_final, dtype=float))))
        codes = () if ok else ("OLASILIK_GECERSIZ:1X2",)
        e = ctx.evaluate(league=pred.league, date=pred.date, home=pred.home, away=pred.away, as_of=as_of,
                         markets=MATCH_MARKETS, source=pred.source or "", prediction_codes=codes, event_id=eid)["1X2"]
    pred.eligibility = e
    return e


def gated_match_predictions(engine, ctx: EligibilityContext | None, fixtures: pd.DataFrame | None,
                            as_of: dt.datetime, odds_type: str = "avg", unmatched: pd.DataFrame | None = None):
    """Toplu 1X2 tahmini: (uygunluğu bağlanmış tahminler, tahmini olmayan fikstürlerin nedenli sonuçları)."""
    from .goals.ledger import event_id

    fx = fixtures if fixtures is not None else pd.DataFrame()
    preds = engine.predict_fixtures(fx, odds_type) if (engine is not None and engine.trained and not fx.empty) else []
    for p in preds:
        gate_match_prediction(ctx, p, as_of)
    have = {p.event_id for p in preds}
    missing: list[FixtureVerdict] = []
    rows = [(r, True) for r in fx.itertuples(index=False)]
    rows += [(r, False) for r in (unmatched if unmatched is not None else pd.DataFrame()).itertuples(index=False)]
    for r, mapped in rows:
        home = r.home if mapped else r.raw_home
        away = r.away if mapped else r.raw_away
        src = getattr(r, "source", "") or ""
        eid = event_id(r.league, r.date, home, away) if mapped else candidate_id(src, r.league, r.date, home, away)
        if mapped and eid in have:
            continue
        if ctx is None:
            by = {"1X2": not_evaluated(eid, "1X2", as_of, canonical=mapped)}
        else:
            by = ctx.evaluate(league=r.league, date=r.date, home=home, away=away, as_of=as_of, markets=MATCH_MARKETS,
                              source=src, mapped=mapped, raw_home=None if mapped else home,
                              raw_away=None if mapped else away, prediction_codes=None, event_id=eid)
        missing.append(FixtureVerdict(league=r.league, date=pd.Timestamp(r.date), time=getattr(r, "time", "") or "",
                                      home=home, away=away, candidate_id=eid, canonical_id=mapped, by_market=by))
    return preds, missing

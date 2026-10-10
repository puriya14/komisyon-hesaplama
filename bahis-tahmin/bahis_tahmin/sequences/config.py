"""Araştırma sözleşmesi ``dizi-sozlesme-v2`` sayısal parametreleri (docs/DIZI_ARASTIRMA_SOZLESMESI.md ile aynı).

Bu değerler gerçek veride ilk örüntü sonucu hesaplanmadan önce dondurulur; özeti (``config_hash``) her çalışma
manifestine ve ön-kayda yazılır. Değişiklik = yeni deney; etkilenen dönem "temiz test" sayılmaz.
"""

from __future__ import annotations

import hashlib
import json
import math

CONTRACT_VERSION = "dizi-sozlesme-v2"
CONTRACT_DATE = "2026-10-10"

PERIODS = {  # tarihe göre sezon yılı (1 Temmuz), kapalı aralıklar
    "isinma": (2000, 2005),
    "kesif": (2006, 2012),
    "parametre": (2013, 2018),
    "test": (2019, 2025),
}
FORWARD_FROM = "2026-10-10"  # bu tarihten sonra oynanan ve tahmini maç öncesinde kaydedilen maçlar

PRE_WINDOWS = (5, 10)
POST_WINDOWS = (1, 3, 5)

TARGETS_Q1 = ("IY_GERIDE_MS_GALIP", "IY_ONDE_MS_MAGLUP", "GALIBIYET", "MAGLUBIYET")
HISTORY_ATOMS = (
    "SON_MAC_IY_GERIDE_MS_GALIP", "SON_MAC_IY_ONDE_MS_MAGLUP", "SON5_IY_GERIDE_EN_AZ_2", "SON5_IY_ONDE_EN_AZ_3",
    "SON5_GALIBIYET_EN_AZ_4", "SON5_GALIBIYETSIZ", "SON3_MAGLUBIYET", "SON10_IY_GERIDE_MS_GALIP_EN_AZ_2",
    "SON10_IY_SONRASI_IYILESME_EN_AZ_4", "SON20_IY_GERIDE_MS_GALIP_YOK", "SON3_IY_GERIDE_MS_GALIP_VAR",
    "FORM_BEKLENTI_USTU", "FORM_BEKLENTI_ALTI", "RAKIP_SON5_IY_ONDE_EN_AZ_3", "RAKIP_SON10_IY_ONDE_MS_MAGLUP_EN_AZ_2",
    "RAKIP_SON3_MAGLUBIYET",
)
CONTEXT_ATOMS = ("EV_SAHIBI", "FAVORI", "LIG_YOGUN_KISA_ARA", "SEZON_SONU")
FAVORI_THRESHOLD = 0.55
SHORT_GAP_DAYS = 3
SEASON_END_SHARE = 0.8
FORM_DIFF = 4.0
LEAGUE_CHANGE_EXCLUDE = 8  # lig değişikliğinden sonraki ilk 8 maç aramadan/testten çıkar

MIN_N = 500
MIN_E = 25.0
N_QUINTILES = 5
ALPHA = 0.05
N_NULL = 1000
N_NULL_PLACEBO = 200
N_PLACEBO_SEEDS = 20
PLACEBO_MAX_DISCOVERIES = 1
MAX_CANDIDATES = 5
SEED = 20261010
MC_CI_LEVEL = 0.99

Q2_EVENTS = ("IY_GERIDE_MS_GALIP", "IY_ONDE_MS_MAGLUP")
Q2_TARGETS = ("SONRAKI_GALIBIYET", "SONRAKI3_AYNI_OLAY", "SONRAKI5_PUAN")
Q2_HORIZON = 5

HAZARD_EVENTS = ("IY_GERIDE_MS_GALIP", "IY_ONDE_MS_MAGLUP")
HAZARD_BINS = ((1, 3), (4, 10), (11, 20), (21, 40), (41, math.inf))

S1_LAMBDAS = (1e-4, 1e-3, 1e-2, 1e-1, math.inf)
S2_K = (200, 500, 1000)
S2_KAPPA = (5.0, 20.0, 80.0)

EV_THRESHOLD = 0.05
ANOMALY_QUANTILE = 0.995
PAPER_MIN_ROWS = 300
PAPER_MAX_SEASONS = 2

STATUSES = ("EXPLORATORY", "INSUFFICIENT_EVIDENCE", "NO_ADDED_VALUE", "OUT_OF_SAMPLE_SUPPORTED", "PAPER_TRADING",
            "DATA_QUALITY_BLOCKED")
STATUS_TR = {
    "EXPLORATORY": "Keşif aşamasında (örneklem dışı doğrulanmadı)",
    "INSUFFICIENT_EVIDENCE": "Kanıt yetersiz",
    "NO_ADDED_VALUE": "Temel modele ek katkı yok",
    "OUT_OF_SAMPLE_SUPPORTED": "Örneklem dışında destekleniyor",
    "PAPER_TRADING": "İleriye dönük sanal takipte",
    "DATA_QUALITY_BLOCKED": "Veri kalitesi/kapsamı nedeniyle incelenemiyor",
}
ROI_UNAVAILABLE = "ROI_UNAVAILABLE"
DATA_QUALITY_BLOCKED_ITEMS = {
    "TUM_RESMI_MACLAR": "Kupa, Avrupa ve millî maç verisi yok (yalnızca lig maçları).",
    "MAC_ICI_GERIDEN_DONUS": "Dakika bazlı gol verisi yok; yalnızca 'ilk yarıyı geride kapatıp kazanma' ölçülür.",
    "TEKNIK_DIREKTOR_KADRO_DONEMI": "Teknik direktör/kadro verisi yok.",
    "XG_KADRO": "Geçerli ücretsiz xG/kadro kaynağı yok.",
    "IYMS_ORANI": "İY/MS oranı yok → ROI_UNAVAILABLE.",
    "BAHIS_HACMI": "Bahis hacmi/hesap verisi yok; anomali yalnızca sonuç ve oranlardan.",
    "KUPA_FIKSTUR_YOGUNLUGU": "Kupa maçları olmadığı için gerçek dinlenme süresi ölçülemez (LIG_ARASI_GUN kullanılır).",
}


def config_dict() -> dict:
    g = globals()
    keys = [k for k in g if k.isupper() and not k.startswith("_")]
    out = {}
    for k in sorted(keys):
        v = g[k]
        if isinstance(v, (str, int, float, bool, tuple, list, dict)):
            out[k] = v
    return json.loads(json.dumps(out, default=lambda x: "inf" if x == math.inf else str(x)))


def config_hash() -> str:
    return hashlib.sha256(json.dumps(config_dict(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def period_of(season_year: int) -> str | None:
    for name, (a, b) in PERIODS.items():
        if a <= season_year <= b:
            return name
    return None

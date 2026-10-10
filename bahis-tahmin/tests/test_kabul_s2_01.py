"""S2-KABUL-01: referans sürecin ulaşılabilir eşikleri ve sentetik pozitif/negatif kontrol (katı kural ile).

Yalnızca sentetik veri. Sentetik kontrol sonucu gerçek futbol avantajı değildir.
"""

import numpy as np
import pytest

from bahis_tahmin.sequences import config as C
from bahis_tahmin.sequences import null as NL
from bahis_tahmin.sequences import patterns as P
from bahis_tahmin.sequences.synthetic import synthetic_frame

SUPPORT = {"min_n": 300, "min_e": 10.0}
PLANTED = "IY_GERIDE_MS_GALIP|SON_MAC_IY_GERIDE_MS_GALIP"
R_STRICT = 104  # c = 0 iken MC %99 Clopper–Pearson üst sınırının 0,05'in altına indiği en küçük R


def _strict(c: int, R: int) -> tuple[float, float]:
    _, hi = NL.clopper_pearson(np.array([c]), R)
    return (c + 1) / (R + 1), float(hi[0])


def test_strict_rule_reachability():
    """Katı kural (p_adj < 0,05 VE MC üst sınır < 0,05): R = 20 ile hiçbir hipotez geçemez; c = 0 için R ≥ 104 gerekir."""
    assert C.MC_CI_LEVEL == 0.99
    p20, hi20 = _strict(0, 20)
    assert p20 == pytest.approx(1 / 21) and hi20 > 0.2  # p < 0,05 olsa da üst sınır geçmez
    assert _strict(0, R_STRICT - 1)[1] >= C.ALPHA and _strict(0, R_STRICT)[1] < C.ALPHA
    # Resmî R = 1000: en çok c = 32 aşımda geçer (p_adj = 33/1001 ≈ 0,033); R = 200 için c ≤ 2
    reach = {R: max([c for c in range(80) if (lambda p, h: p < C.ALPHA and h < C.ALPHA)(*_strict(c, R))], default=None)
             for R in (20, R_STRICT, 200, C.N_NULL)}
    assert C.N_NULL == 1000 and reach == {20: None, R_STRICT: 0, 200: 2, 1000: 32}


@pytest.fixture(scope="module")
def frames():
    pos, _, _ = synthetic_frame(5, comeback_boost=3.0, n_leagues=4)
    neg, _, _ = synthetic_frame(5, comeback_boost=1.0, n_leagues=4)
    return pos, neg


def _wy(fr, R):
    # Mevcut ekili etki testiyle aynı satırlar (üç dönem birlikte; makine testi, protokol dönemi değil)
    mask = fr.eligible & np.isin(fr.period.astype(str), ["kesif", "parametre", "test"])
    prep = P.prepare(fr, mask)
    obs = P.evaluate(fr, mask, prep=prep, **SUPPORT).set_index("hyp_id", drop=False)
    nul = NL.run_null(fr, mask, R, 3, prep=prep, **SUPPORT)
    p, lo, hi = NL.westfall_young_stepdown(obs["z"].to_numpy(), obs["supported"].to_numpy(), nul["z"], nul["supported"])
    obs["p_adj"], obs["ci_hi"] = p, hi
    return obs[obs["supported"] & (obs["p_adj"] < C.ALPHA) & (obs["ci_hi"] < C.ALPHA)]


def test_positive_and_negative_control_under_strict_rule(frames):
    """Aynı akış, aynı R: ekili güçlü etki katı kuralla yakalanır; etkisiz veride katı kuralı geçen hipotez yok."""
    pos, neg = frames
    hits = _wy(pos, 200)
    assert PLANTED in hits.index
    assert _wy(neg, 200).empty


def test_market_checks_are_labelled_historical_reference_only(frames):
    """Piyasa kontrolü (7b/5) çıktısı oranın zamanı doğrulanmamış tarihsel referans olduğunu taşır."""
    from bahis_tahmin.sequences.odds_status import ODDS_STATUS

    pos, _ = frames
    mask = pos.eligible & np.isin(pos.period.astype(str), ["kesif"])
    fa = P.falsification(pos, "IY_GERIDE_MS_GALIP", "SON_MAC_IY_GERIDE_MS_GALIP", mask,
                         p0_market=np.full(len(pos.tm), 0.3))
    assert ODDS_STATUS == "HISTORICAL_REFERENCE_ONLY" and fa["checks"]["5_piyasa"]["oran_statusu"] == ODDS_STATUS


def test_odds_label_does_not_change_preregistered_parameters():
    from bahis_tahmin.sequences.research import PREREGISTERED

    assert C.config_hash() == PREREGISTERED["parametre_ozeti"]

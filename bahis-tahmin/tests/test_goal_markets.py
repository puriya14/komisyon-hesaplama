"""Zorunlu test matrisi: pazar etiketleri ve sonuçlandırma (settlement)."""

import itertools

import numpy as np
import pandas as pd
import pytest

from bahis_tahmin.goals.markets import (
    MARKETS,
    PRIMARY_YES,
    Label,
    MatchStatus,
    PeriodScore,
    Settlement,
    label,
    label_all,
    label_frame,
    settle,
    validate,
)

A, B, C = PRIMARY_YES
T, F, U = Label.TRUE, Label.FALSE, Label.UNKNOWN


def labels(ht, ft, **kw):
    ps = PeriodScore(fthg=ft[0], ftag=ft[1], hthg=None if ht is None else ht[0],
                     htag=None if ht is None else ht[1], **kw)
    return label(A, ps), label(B, ps), label(C, ps)


@pytest.mark.parametrize("ht, ft, expected", [
    ((1, 1), (2, 2), (T, T, T)),   # 1
    ((2, 0), (2, 2), (F, T, T)),   # 2
    ((1, 0), (3, 1), (F, T, F)),   # 3
    ((1, 1), (1, 1), (F, F, T)),   # 4
    ((0, 0), (4, 0), (F, T, F)),   # 5
    (None, (3, 1), (U, T, U)),     # 6: ilk yarı yok → yalnız B hesaplanır
])
def test_mandatory_label_cases(ht, ft, expected):
    assert labels(ht, ft) == expected


def test_case7_ht_exceeds_ft_is_caught():
    ps = PeriodScore(fthg=1, ftag=0, hthg=2, htag=0)
    assert "ILK_YARI_MAC_SONUNU_ASIYOR" in validate(ps)
    # Çelişkili kayıtta negatif ikinci yarı golü üretilmez; tüm pazarlar UNKNOWN
    assert labels((2, 0), (1, 0)) == (U, U, U)
    lf = label_frame(pd.DataFrame({"fthg": [1], "ftag": [0], "hthg": [2], "htag": [0]}))
    assert lf["issues"].iloc[0] == "ILK_YARI_MAC_SONUNU_ASIYOR"
    assert lf[[A, B, C]].isna().all(axis=None)


def test_case8_extra_time_not_used():
    ps = PeriodScore(fthg=1, ftag=1, hthg=0, htag=1, status=MatchStatus.FINISHED_AET, aet_home=3, aet_away=2)
    assert label(B, ps) == F  # 3-2 değil, normal süre 1-1 kullanılır
    assert label(C, ps) == F
    assert settle(B, ps) == Settlement.LOSS


@pytest.mark.parametrize("status", [MatchStatus.ABANDONED, MatchStatus.AWARDED,
                                    MatchStatus.POSTPONED, MatchStatus.CANCELLED])
def test_case9_abandoned_or_awarded_is_void_not_loss(status):
    ps = PeriodScore(fthg=3, ftag=0, hthg=3, htag=0, status=status)
    for key in PRIMARY_YES:
        assert settle(key, ps) == Settlement.VOID
        assert label(key, ps) == U


def test_pending_and_unknown_settlement():
    assert settle(A, PeriodScore(status=MatchStatus.SCHEDULED)) == Settlement.PENDING
    assert settle(A, PeriodScore(status=MatchStatus.IN_PLAY, fthg=1, ftag=1, hthg=1, htag=1)) == Settlement.PENDING
    assert settle(A, PeriodScore(fthg=3, ftag=1)) == Settlement.UNKNOWN  # ilk yarı yok → kayıp yazılmaz
    assert settle(B, PeriodScore(fthg=3, ftag=1)) == Settlement.WIN
    with pytest.raises(ValueError):
        settle(B, PeriodScore(fthg=3, ftag=1), rule_version="baska-kural")


def test_complement_sides():
    ps = PeriodScore(fthg=2, ftag=1, hthg=1, htag=0)
    for key, m in MARKETS.items():
        a, b = label(key, ps), label(m.complement, ps)
        assert {a, b} == {T, F}
        assert MARKETS[m.complement].complement == key


def test_invalid_values_rejected():
    assert "GECERSIZ_DEGER:fthg" in validate(PeriodScore(fthg=-1, ftag=0))
    assert "GECERSIZ_DEGER:hthg" in validate(PeriodScore(fthg=1, ftag=0, hthg=0.5, htag=0))
    assert labels((0.5, 0), (1, 0)) == (U, U, U)


def test_logical_relations_on_all_scores():
    """A ⇒ B ve A ⇒ C; B∧C, A'yı gerektirmez."""
    seen_bc_not_a = False
    for hh, ha, sh, sa in itertools.product(range(5), repeat=4):
        ps = PeriodScore(fthg=hh + sh, ftag=ha + sa, hthg=hh, htag=ha)
        la = label_all(ps, PRIMARY_YES)
        if la[A] == T:
            assert la[B] == T and la[C] == T
        if la[B] == T and la[C] == T and la[A] == F:
            seen_bc_not_a = True
    assert seen_bc_not_a


def test_label_frame_matches_scalar_labels():
    rng = np.random.default_rng(0)
    n = 400
    hh, ha = rng.integers(0, 3, n), rng.integers(0, 3, n)
    fh, fa = hh + rng.integers(0, 3, n), ha + rng.integers(0, 3, n)
    df = pd.DataFrame({"fthg": fh, "ftag": fa, "hthg": hh.astype(float), "htag": ha.astype(float)})
    df.loc[::17, ["hthg", "htag"]] = np.nan
    keys = list(MARKETS)
    lf = label_frame(df, keys)
    for i in range(n):
        r = df.iloc[i]
        ps = PeriodScore(fthg=r.fthg, ftag=r.ftag,
                         hthg=None if np.isnan(r.hthg) else r.hthg, htag=None if np.isnan(r.htag) else r.htag)
        for key in keys:
            s = label(key, ps)
            v = lf[key].iloc[i]
            assert (s == U and np.isnan(v)) or (s == T and v == 1.0) or (s == F and v == 0.0), (i, key)

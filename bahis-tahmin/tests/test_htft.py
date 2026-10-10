"""İY/MS (9 sonuçlu) pazar ailesi: etiket, takım perspektifi, normalizasyon, sonuçlandırma ve ortak dağılım."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from bahis_tahmin.goals.markets import (
    HTFT_KEYS,
    HTFT_MARKETS,
    MARKETS,
    Label,
    MatchStatus,
    PeriodScore,
    Settlement,
    get_market,
    htft_frame,
    htft_key_for_team,
    htft_outcome,
    label,
    label_frame,
    normalize_result_code,
    parse_htft,
    settle,
    team_htft,
)
from bahis_tahmin.goals.value import OddsQuote, validate_quote

UTC = dt.timezone.utc


def ps(ht, ft, **kw):
    return PeriodScore(fthg=ft[0], ftag=ft[1], hthg=ht[0], htag=ht[1], **kw)


def test_ht01_ft21_is_htft_2_1_and_not_over35_or_fh15():
    s = ps((0, 1), (2, 1))
    assert htft_outcome(s) == "HTFT_2_1"
    assert label("HTFT_2_1", s) == Label.TRUE
    assert label("HTFT_1_1", s) == Label.FALSE
    assert label("FT_OVER_3_5", s) == Label.FALSE
    assert label("FH_OVER_1_5", s) == Label.FALSE


def test_ht10_ft12_is_htft_1_2():
    assert htft_outcome(ps((1, 0), (1, 2))) == "HTFT_1_2"


def test_team_perspective_flips_with_home_away():
    # Aynı ham 2/1: ev sahibi için İY geride MS galip, deplasman için İY önde MS mağlup
    assert team_htft("HTFT_2_1", True) == ("M", "G")
    assert team_htft("HTFT_2_1", False) == ("G", "M")
    assert team_htft("HTFT_1_2", False) == ("M", "G")
    assert htft_key_for_team("IY_GERIDE_MS_GALIP", True) == "HTFT_2_1"
    assert htft_key_for_team("IY_GERIDE_MS_GALIP", False) == "HTFT_1_2"
    assert htft_key_for_team("IY_ONDE_MS_MAGLUP", True) == "HTFT_1_2"
    assert team_htft(None, True) is None


def test_missing_halftime_is_unknown_not_false():
    s = PeriodScore(fthg=2, ftag=1, hthg=None, htag=None)
    assert htft_outcome(s) is None
    assert all(label(k, s) == Label.UNKNOWN for k in HTFT_KEYS)
    assert settle("HTFT_2_1", s) == Settlement.UNKNOWN


def test_extra_time_not_used_for_full_time_result():
    s = ps((0, 1), (1, 1), status=MatchStatus.FINISHED_AET, aet_home=2, aet_away=1)
    assert htft_outcome(s) == "HTFT_2_X"  # normal süre 1-1; uzatmadaki 2-1 sayılmaz


def test_xx_is_not_nil_nil():
    s = ps((1, 1), (2, 2))
    assert htft_outcome(s) == "HTFT_X_X"
    assert label("FT_OVER_3_5", s) == Label.TRUE  # 0-0 değil
    assert parse_htft("0/0") == "HTFT_X_X"  # İY/MS gösterimi: ilk yarı berabere / maç berabere


@pytest.mark.parametrize("raw,key", [
    ("2/1", "HTFT_2_1"), ("2-1", "HTFT_2_1"), ("21", "HTFT_2_1"), ("A/H", "HTFT_2_1"),
    ("0/1", "HTFT_X_1"), ("X/1", "HTFT_X_1"), ("D/H", "HTFT_X_1"), ("x-2", "HTFT_X_2"), ("HTFT_1_X", "HTFT_1_X"),
    ("3/1", None), ("", None), (None, None),
])
def test_draw_code_normalisation(raw, key):
    assert parse_htft(raw) == key


def test_result_code_aliases():
    assert [normalize_result_code(c) for c in ("H", "D", "A", "0", "X", "1", "2", "?")] == ["1", "X", "2", "X", "X", "1", "2", None]


def test_settlement_void_pending_and_win_loss():
    s = ps((0, 1), (2, 1))
    assert settle("HTFT_2_1", s) == Settlement.WIN
    assert settle("HTFT_X_1", s) == Settlement.LOSS
    assert settle("HTFT_2_1", ps((0, 1), (2, 1), status=MatchStatus.ABANDONED)) == Settlement.VOID
    assert settle("HTFT_2_1", PeriodScore(status=MatchStatus.SCHEDULED)) == Settlement.PENDING


def test_registry_is_separate_from_binary_markets():
    assert set(HTFT_MARKETS) == set(HTFT_KEYS) and len(HTFT_KEYS) == 9
    assert not set(HTFT_MARKETS) & set(MARKETS)  # iki seçenekli kayıt değişmedi
    assert get_market("HTFT_2_1").selection == "2/1" and get_market("FT_OVER_3_5") is MARKETS["FT_OVER_3_5"]


def test_frame_labels_match_scalar_labels():
    df = pd.DataFrame({
        "hthg": [0, 1, 1, np.nan, 2], "htag": [1, 0, 1, np.nan, 3],  # son satır: İY > MS → çelişkili
        "fthg": [2, 1, 2, 2, 2], "ftag": [1, 2, 2, 1, 1],
    })
    codes = htft_frame(df)
    assert list(codes) == ["HTFT_2_1", "HTFT_1_2", "HTFT_X_X", None, None]
    lab = label_frame(df, HTFT_KEYS)
    for i, row in df.iterrows():
        sc = PeriodScore(*(None if pd.isna(row[c]) else row[c] for c in ("fthg", "ftag", "hthg", "htag")))
        for k in HTFT_KEYS:
            want = {Label.TRUE: 1.0, Label.FALSE: 0.0}.get(label(k, sc), np.nan)
            got = lab.loc[i, k]
            assert (np.isnan(want) and np.isnan(got)) or want == got
    known = lab[list(HTFT_KEYS)].dropna()
    assert (known.sum(axis=1) == 1).all()  # 9 sonuç birbirini dışlar


def _q(market, selection, period="HTFT", odds=5.0):
    now = dt.datetime(2026, 10, 1, 12, tzinfo=UTC)
    return OddsQuote("E0|2026-10-02|A|B", market, period, None, selection, "manuel", "test", odds, now, now)


def test_htft_quote_validation_detects_wrong_market():
    assert validate_quote(_q("HTFT_2_1", "2/1")) == []
    assert validate_quote(_q("HTFT_2_1", "0/1")) != []  # yanlış seçim
    assert validate_quote(_q("HTFT_X_1", "0/1")) == []  # beraberlik gösterimi normalize edilir
    assert any(e.startswith("DONEM_UYUSMAZ") for e in validate_quote(_q("HTFT_2_1", "2/1", period="FT")))


# ------------------------------------------------------------- ortak dağılım
@pytest.fixture(scope="module")
def fitted():
    from bahis_tahmin.goals.features import build_goal_features
    from bahis_tahmin.goals.model import GoalModel
    from bahis_tahmin.selftest import synthetic_matches

    m = synthetic_matches(n_seasons=8, n_teams=16, seed=1, half_time=True)
    feat, _ = build_goal_features(m)
    tr, te = feat[feat["date"] < "2026-08-01"], feat[feat["date"] >= "2026-08-01"]
    return GoalModel("M10_ipf_kosullu").fit(tr), te


def test_nine_htft_probabilities_sum_to_one(fitted):
    model, te = fitted
    h = model.htft_probs(te)
    cells = np.column_stack([h[k] for k in HTFT_KEYS])
    ok = np.isfinite(cells).all(axis=1)
    assert ok.any() and (cells[ok] >= 0).all()
    total = cells[ok].sum(axis=1) + h["HTFT_KUYRUK"][ok]
    assert np.allclose(total, 1.0, atol=1e-9)
    assert (h["HTFT_KUYRUK"][ok] < 1e-4).all()


def test_htft_consistent_with_abc_from_same_distribution(fitted):
    from bahis_tahmin.goals import joint as J

    model, te = fitted
    p = model.predict(te)
    lam, bad = model.structural_rates(te)
    b = model.base
    R = J.htft_regions(lam[:, 0], lam[:, 1], lam[:, 2], lam[:, 3], b.mult_h, b.mult_a, b.phi)
    reg = J.joint_regions(lam[:, 0], lam[:, 1], lam[:, 2], lam[:, 3], b.mult_h, b.mult_a, b.phi)
    # Yapısal (eğilmemiş) bölge toplamları joint_regions ile birebir
    assert np.allclose(R[..., 0].sum((1, 2)), reg["A"], atol=1e-12)
    assert np.allclose(R[..., 2].sum((1, 2)), reg["BnC"], atol=1e-12)
    # Eğilmiş + q-kalibre dağılım: İY/MS hücrelerinden geri kurulan A ve 1X2, predict ile tutarlı
    h = model.htft_probs(te)
    ok = np.isfinite(p["A"]) & np.isfinite(h["HTFT_1_1"])
    home_ft = h["HTFT_1_1"] + h["HTFT_X_1"] + h["HTFT_2_1"]
    away_ft = h["HTFT_1_2"] + h["HTFT_X_2"] + h["HTFT_2_2"]
    assert ((home_ft + away_ft)[ok] < 1).all()
    # A, B, C'nin İY/MS ayrıştırması: bölge ağırlıklarıyla toplam predict'e eşit
    cal = model.calibrator.predict(te)
    til = J.tilt_to_targets(reg, np.clip(np.nan_to_num(cal["B"], nan=.5), 1e-4, 1 - 1e-4),
                            np.clip(np.nan_to_num(cal["C"], nan=.5), 1e-4, 1 - 1e-4))
    w = til["weights"]
    q = reg["A"] / reg["BC"]
    qc = model._q_cal(til["A"], til["BC"])
    a_from_cells = (R[..., 0].sum((1, 2))) * w["BC"] * qc / q
    assert np.allclose(a_from_cells[ok], p["A"][ok], atol=1e-10)
    b_from_cells = (R[..., 0].sum((1, 2)) * w["BC"] * qc / q + (R[..., 1].sum((1, 2)) + reg["tail"]) * w["BC"] * (1 - qc) / (1 - q)
                    + R[..., 2].sum((1, 2)) * w["BnC"])
    assert np.allclose(b_from_cells[ok], p["B"][ok], atol=1e-9)

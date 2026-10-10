import json

import numpy as np
import pandas as pd
import pytest
from conftest import fixture_bytes

from bahis_tahmin.data.leagues import recent_season_starts, season_code, season_for_date, season_label
from bahis_tahmin.data.parsers import (
    MATCH_COLUMNS,
    assign_seasons,
    normalize_extra,
    normalize_fixtures,
    normalize_main,
    parse_dates,
    parse_openfootball,
    read_csv_robust,
)


def test_season_helpers():
    import datetime as dt

    assert season_code(2025) == "2526"
    assert season_code(1999) == "9900"
    assert season_label(2025) == "2025/26"
    assert season_label(2025, calendar_year=True) == "2025"
    assert season_for_date(dt.date(2026, 3, 1), False) == "2025/26"
    assert season_for_date(dt.date(2026, 8, 1), False) == "2026/27"
    starts = recent_season_starts(10, dt.date(2026, 10, 10))
    assert starts[0] == 2016 and starts[-1] == 2026 and len(starts) == 11


def test_parse_dates_mixed_formats():
    s = pd.Series(["16/08/2024", "19/08/16", "2024-08-17", None])
    d = parse_dates(s)
    assert d.iloc[0] == pd.Timestamp("2024-08-16")
    assert d.iloc[1] == pd.Timestamp("2016-08-19")
    assert d.iloc[2] == pd.Timestamp("2024-08-17")
    assert pd.isna(d.iloc[3])


def test_read_csv_robust_handles_extra_fields():
    raw = b"A,B,C\n1,2,3\n4,5,6,,,\n7,8\n"
    df = read_csv_robust(raw)
    assert list(df.columns) == ["A", "B", "C"]
    assert len(df) == 3
    assert df.iloc[2]["C"] is np.nan or pd.isna(df.iloc[2]["C"])


def test_normalize_main_new_format():
    df = normalize_main(read_csv_robust(fixture_bytes("E0_2425.csv")), "E0", "2024/25")
    assert list(df.columns) == MATCH_COLUMNS
    assert len(df) == 4  # oynanmamış maç (skor yok) atılır
    r = df.iloc[0]
    assert r["home"] == "Man United" and r["away"] == "Fulham"
    assert (r["fthg"], r["ftag"]) == (1, 0)
    assert r["date"] == pd.Timestamp("2024-08-16")
    assert r["time"] == "20:00"
    assert r["o_h"] == pytest.approx(1.63) and r["omax_h"] == pytest.approx(1.70)
    assert r["ps_h"] == pytest.approx(1.65) and r["b365_h"] == pytest.approx(1.60)
    assert r["oc_h"] == pytest.approx(1.60)
    assert r["o_o25"] == pytest.approx(1.64) and r["omax_u25"] == pytest.approx(2.40)
    assert r["h_sot"] == 5 and r["a_corners"] == 8


def test_normalize_main_old_betbrain_format():
    df = normalize_main(read_csv_robust(fixture_bytes("T1_1617.csv")), "T1", "2016/17")
    assert len(df) == 3
    r = df.iloc[0]
    assert r["date"] == pd.Timestamp("2016-08-19")
    assert r["o_h"] == pytest.approx(1.26)  # BbAvH
    assert r["omax_d"] == pytest.approx(6.40)  # BbMxD
    assert r["o_o25"] == pytest.approx(1.47)  # BbAv>2.5
    assert r["time"] == ""


def test_normalize_extra_league():
    df = normalize_extra(read_csv_robust(fixture_bytes("BRA.csv")), "BRA")
    assert len(df) == 3
    assert set(df["season"]) == {"2024", "2023"}
    r = df[df["home"] == "Flamengo"].iloc[0]
    assert r["o_h"] == pytest.approx(1.73)  # yalnızca kapanış ortalaması var
    assert r["ps_h"] == pytest.approx(1.75)


def test_normalize_fixtures_filters_unknown_leagues():
    fx = normalize_fixtures(read_csv_robust(fixture_bytes("fixtures.csv")))
    assert set(fx["league"]) == {"T1", "E0"}
    gs = fx[fx["home"] == "Galatasaray"].iloc[0]
    assert gs["o_h"] == pytest.approx(1.70) and gs["omax_h"] == pytest.approx(1.78)
    assert gs["date"] == pd.Timestamp("2026-10-17")


def test_assign_seasons_handles_covid_restart_and_data_gaps():
    dates = (
        list(pd.date_range("2019-08-10", "2020-03-08", freq="7D"))
        + list(pd.date_range("2020-06-17", "2020-07-26", freq="7D"))  # COVID sonrası devam
        + list(pd.date_range("2020-09-12", "2021-05-20", freq="7D"))
        + list(pd.date_range("2024-11-22", "2025-05-18", freq="7D"))  # uzun veri boşluğu
    )
    df = pd.DataFrame({"league": "E0", "date": dates})
    s = assign_seasons(df)
    by = dict(zip(df["date"], s))
    assert by[pd.Timestamp("2020-07-22")] == "2019/20"
    assert by[pd.Timestamp("2020-09-12")] == "2020/21"
    assert by[pd.Timestamp("2024-11-22")] == "2024/25"


def test_parse_openfootball_skips_played():
    fx = parse_openfootball(fixture_bytes("openfootball_en1.json"), "E0")
    assert len(fx) == 3
    assert "Arsenal FC" in set(fx["away"])
    played = json.loads(fixture_bytes("openfootball_en1.json"))["matches"][0]
    assert played["team1"] not in set(fx["home"]) or len(fx[fx["date"] == pd.Timestamp(played["date"])]) == 0

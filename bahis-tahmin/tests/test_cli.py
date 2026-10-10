"""Komut satırı gol pazarları komutları (geçici uygulama dizininde, sentetik veriyle)."""

import pandas as pd

from bahis_tahmin.cli import main
from bahis_tahmin.data.store import DataStore
from bahis_tahmin.selftest import synthetic_matches


def test_goal_cli_commands(tmp_home, capsys):
    st = DataStore(tmp_home)
    m = synthetic_matches(n_seasons=8, n_teams=16, seed=1, half_time=True)
    st.matches = m
    fx = m.tail(3)[["league", "date", "time", "home", "away", "source"]].copy()
    fx["date"] = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
    st.fixtures = fx.reindex(columns=st.fixtures.columns)
    st.save()
    assert main(["gol-sanal"]) == 0  # kayıt yokken dosya oluşturmaz
    assert not (tmp_home / "gol_pazarlari.sqlite").exists()
    assert main(["gol-egit"]) == 0
    out = capsys.readouterr().out
    assert "M10_ipf_kosullu" in out and "MODEL_NOT_VALIDATED" in out
    assert (tmp_home / "goal_engine.joblib").exists() and (tmp_home / "goal_engine.manifest.json").exists()
    assert main(["gol-tahmin"]) == 0
    out = capsys.readouterr().out
    assert "DOĞRULANMADI" in out and out.count(" - ") >= 3
    csv = tmp_home / "kapsam.csv"
    assert main(["gol-kapsam", "--csv", str(csv)]) == 0
    assert csv.exists() and len(pd.read_csv(csv)) == 8


def test_goal_train_without_halftime_fails_cleanly(tmp_home, capsys):
    st = DataStore(tmp_home)
    st.matches = synthetic_matches(n_seasons=5, n_teams=14, seed=1)
    st.save()
    assert main(["gol-egit"]) == 2
    assert "ilk yarı" in capsys.readouterr().err
    assert not (tmp_home / "goal_engine.joblib").exists()


def test_odds_import_is_dry_run_by_default(tmp_home, tmp_path, capsys):
    from bahis_tahmin.goals.value import ODDS_CSV_FIELDS

    rows = [
        ",".join(ODDS_CSV_FIELDS),
        "E0|2026-10-12|A|B,FT_OVER_3_5,FT,3.5,OVER,manuel,test,2.40,2026-10-11T10:00:00+00:00,2026-10-11T10:00:05+00:00,OPEN,std-v1",
        "E0|2026-10-12|A|B,FT_OVER_3_5,FT,3.5,OVER,manuel,test,0.90,2026-10-11T10:00:00+00:00,2026-10-11T10:00:05+00:00,OPEN,std-v1",
        "E0|2026-10-12|A|B,FT_OVER_3_5,FT,3.5,OVER,manuel,test,2.40,2026-10-11T10:00:00,2026-10-11T10:00:05,OPEN,std-v1",
    ]
    f = tmp_path / "oranlar.csv"
    f.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert main(["gol-oran-ice-aktar", "--csv", str(f)]) == 0
    out = capsys.readouterr().out
    assert "Geçerli oran kaydı: 1" in out and "karantina: 2" in out and "Kuru çalıştırma" in out
    assert not (tmp_home / "gol_pazarlari.sqlite").exists()
    assert main(["gol-oran-ice-aktar", "--csv", str(f), "--uygula"]) == 0
    assert main(["gol-oran-ice-aktar", "--csv", str(f), "--uygula"]) == 0
    out = capsys.readouterr().out
    assert "1 yeni oran kaydı" in out and "0 yeni oran kaydı" in out

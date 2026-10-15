"""ORAN-03: sanal takipte kapanış oranı ve CLV. Elle kurulmuş kayıtlar; ağ yok."""

from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3

import pytest

from bahis_tahmin.goals.clv import (
    closing_candidates,
    closing_from_quotes,
    clv,
    clv_summary,
    record_clv,
    summary_line,
    timing,
)
from bahis_tahmin.goals.ledger import Ledger
from bahis_tahmin.goals.markets import MARKETS
from bahis_tahmin.goals.service import ledger_csv, ledger_rows
from bahis_tahmin.goals.value import OddsQuote

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 10, 17, 9, 0, tzinfo=UTC)  # karar anı
KICK = dt.datetime(2026, 10, 17, 18, 0, tzinfo=UTC)  # maç saati
EV1 = "E0|2026-10-17|Arsenal|Chelsea"
EV2 = "E0|2026-10-17|Everton|Fulham"


def _rec(event=EV1, market="FT_OVER_3_5", odds=2.5, stake=1.0, decided=T0, kickoff=KICK, status="VALUE_CANDIDATE"):
    return {"kayit_turu": "BAHIS_ADAYI" if stake else "KARAR_KAYDI", "event_id": event, "league": "E0",
            "home": event.split("|")[2], "away": event.split("|")[3],
            "kickoff": kickoff.isoformat() if kickoff else "2026-10-17", "market_key": market,
            "decision_time": decided.isoformat(), "model_version": "t", "feature_version": "t", "data_cutoff": "t",
            "p": 0.45, "odds": odds, "decision_status": status, "reasons": [], "stake_units": stake,
            "strategy_version": "t"}


@pytest.fixture
def led(tmp_path):
    lg = Ledger(tmp_path / "l.sqlite")
    yield lg
    lg.close()


# ------------------------------------------------------------------------------------------- hesap
def test_clv_math():
    raw, fair = clv(2.2, 2.0)
    assert raw == pytest.approx(0.1) and fair is None
    raw, fair = clv(2.2, 2.0, 1.8)
    p = (1 / 2.0) / (1 / 2.0 + 1 / 1.8)
    assert raw == pytest.approx(0.1) and fair == pytest.approx(2.2 * p - 1)
    assert fair < raw  # kapanış oranı marj içerdiği için ham CLV iyimser


def test_timing_labels():
    rec = _rec()
    seen = lambda t: {"observed_at": t.isoformat()}  # noqa: E731
    assert timing(rec, seen(T0 - dt.timedelta(minutes=1))) == (False, "kapanış oranı karar anından önce "
                                                                       "(karşılaştırılmaz)")
    ok, lab = timing(rec, seen(KICK - dt.timedelta(minutes=20)))
    assert ok and lab == "maçtan 20 dk önce"
    ok, lab = timing(rec, seen(KICK - dt.timedelta(minutes=61)))
    assert ok and "erken" in lab
    ok, lab = timing(rec, seen(KICK - dt.timedelta(minutes=60)))
    assert ok and "erken" not in lab
    assert timing(rec, seen(KICK + dt.timedelta(hours=2))) == (True, "maç başladıktan sonra girildi")
    assert timing(rec, seen(KICK + dt.timedelta(minutes=1))) == (True, "maç başladıktan sonra girildi")
    assert timing(_rec(kickoff=None), seen(KICK)) == (True, "maç saati bilinmiyor")
    assert timing(rec, {"observed_at": "2026-10-17T18:00:00"})[0] is False  # zaman dilimi yok


# ------------------------------------------------------------------------------------------- kayıt
def test_closing_record_is_immutable_chained_and_corrections_need_a_note(led):
    assert led.record_closing(EV1, "FT_OVER_3_5", 2.3, KICK, "B1", "manuel", 1.7)
    assert not led.record_closing(EV1, "FT_OVER_3_5", 2.3, KICK, "B1", "manuel", 1.7)  # aynı: eklenmez
    assert led.closing_count() == 1
    with pytest.raises(ValueError, match="gerekçe"):
        led.record_closing(EV1, "FT_OVER_3_5", 2.4, KICK, "B1", "manuel", 1.7)
    with pytest.raises(ValueError, match="gerekçe"):  # yalnızca karşı taraf değişse de düzeltmedir
        led.record_closing(EV1, "FT_OVER_3_5", 2.3, KICK, "B1", "manuel", None)
    with pytest.raises(ValueError, match="gerekçe"):
        led.record_closing(EV1, "FT_OVER_3_5", 2.3, KICK, "B1", "manuel", 1.8)
    with pytest.raises(ValueError, match="gerekçe"):  # başka şirketin oranı da önceki kaydı değiştirir
        led.record_closing(EV1, "FT_OVER_3_5", 2.3, KICK, "B2", "manuel", 1.7)
    assert led.record_closing(EV1, "FT_OVER_3_5", 2.4, KICK, "B1", "manuel", 1.65, note="yanlış yazılmış")
    c = led.closing(EV1, "FT_OVER_3_5")
    assert c["odds"] == 2.4 and c["opposite_odds"] == 1.65 and c["correction_of"] is not None
    assert c["observed_at"] == KICK.isoformat()
    for sql in ("UPDATE closing_odds SET payload='x'", "DELETE FROM closing_odds"):
        with pytest.raises(sqlite3.DatabaseError):
            led.conn.execute(sql)
    assert led.verify_chain()[0]
    # Sessiz ekleme (zinciri bozan satır) tespit edilir
    led.conn.execute("INSERT INTO closing_odds (event_id, market_key, recorded_at, payload, prev_hash, hash) "
                     "VALUES ('x','FT_OVER_3_5','t','{}','0','0')")
    ok, msg = led.verify_chain()
    assert not ok and "closing_odds" in msg


def test_closing_validation(led):
    with pytest.raises(ValueError):  # yalnızca kayıtlı iki seçenekli pazarlar
        led.record_closing(EV1, "YOK", 2.0, KICK, "B", "manuel")
    for bad in (1.0, 0.5, float("nan"), float("inf"), 1001.0):
        with pytest.raises(ValueError):
            led.record_closing(EV1, "FT_OVER_3_5", bad, KICK, "B", "manuel")
    with pytest.raises(ValueError):
        led.record_closing(EV1, "FT_OVER_3_5", 2.0, KICK, "B", "manuel", opposite_odds=1.0)
    with pytest.raises(ValueError):
        led.record_closing(EV1, "FT_OVER_3_5", 2.0, KICK.replace(tzinfo=None), "B", "manuel")
    assert led.closing_count() == 0


def test_closing_is_oriented_to_the_asked_market(led):
    assert led.closing(EV1, "FT_UNDER_3_5") is None
    led.record_closing(EV1, "FT_OVER_3_5", 2.3, KICK, "B", "manuel", 1.7)
    c = led.closing(EV1, "FT_UNDER_3_5")  # karşı tarafın kaydı yer değiştirerek kullanılır
    assert c["market_key"] == "FT_UNDER_3_5" and c["odds"] == 1.7 and c["opposite_odds"] == 2.3
    # Karşı tarafsız yeni kayıt (önceki değerden farklı: düzeltme): kendi pazarı için o; diğer taraf için önceki
    # kullanılabilir kayıt
    with pytest.raises(ValueError, match="gerekçe"):
        led.record_closing(EV1, "FT_UNDER_3_5", 1.75, KICK, "B", "manuel")
    led.record_closing(EV1, "FT_UNDER_3_5", 1.75, KICK, "B", "manuel", note="son an")
    assert led.closing(EV1, "FT_UNDER_3_5")["odds"] == 1.75
    assert led.closing(EV1, "FT_OVER_3_5")["odds"] == 2.3
    led.record_closing(EV1, "FT_OVER_3_5", 2.2, KICK, "B", "manuel", note="yeni")
    assert led.closing(EV1, "FT_OVER_3_5")["odds"] == 2.2 and led.closing(EV1, "FT_UNDER_3_5")["odds"] == 1.75
    assert led.closing(EV2, "FT_OVER_3_5") is None


def test_old_ledger_file_is_migrated_without_touching_records(tmp_path):
    from bahis_tahmin.goals import ledger as L

    path = tmp_path / "eski.sqlite"
    old_schema = L.SCHEMA.split("CREATE TABLE IF NOT EXISTS closing_odds")[0]
    con = sqlite3.connect(path)
    con.executescript(old_schema)
    con.execute("INSERT INTO meta VALUES ('schema_version', '1')")
    con.commit()
    con.close()
    old = Ledger.__new__(Ledger)  # eski dosyaya eski kodla yazılmış gibi: tahmin kaydı
    old.path, old.conn = path, sqlite3.connect(path)
    pid = old.record_prediction(_rec())
    before = old.conn.execute("SELECT payload, hash FROM predictions").fetchall()
    old.conn.close()
    led = Ledger(path)
    assert led.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"
    assert led.conn.execute("SELECT payload, hash FROM predictions").fetchall() == before
    assert led.verify_chain()[0] and led.closing_count() == 0
    led.record_closing(EV1, "FT_OVER_3_5", 2.3, KICK, "B", "manuel")
    assert led.predictions()[0]["id"] == pid and led.verify_chain()[0]
    led.close()


# ------------------------------------------------------------------------------------- özet ve satırlar
def test_clv_summary_counts_only_bets_and_compares_valid_closings(led):
    led.record_prediction(_rec(EV1, "FT_OVER_3_5", odds=2.5))  # bahis, kapanış 2,3/1,7
    led.record_prediction(_rec(EV2, "FH_OVER_1_5", odds=2.0))  # bahis, kapanış 2,1 (karşı yok)
    led.record_prediction(_rec("E0|2026-10-17|A|B", "FT_OVER_3_5", odds=3.0))  # bahis, kapanış yok
    led.record_prediction(_rec("E0|2026-10-17|C|D", "FT_OVER_3_5", odds=3.0))  # bahis, kapanış karardan önce
    led.record_prediction(_rec(EV1, "FT_UNDER_3_5", odds=1.6, stake=0.0, status="NO_VALUE"))  # bahis değil
    led.record_closing(EV1, "FT_OVER_3_5", 2.3, KICK - dt.timedelta(minutes=5), "B", "manuel", 1.7)
    led.record_closing(EV2, "FH_OVER_1_5", 2.1, KICK - dt.timedelta(hours=3), "B", "manuel")
    led.record_closing("E0|2026-10-17|C|D", "FT_OVER_3_5", 2.8, T0 - dt.timedelta(hours=1), "B", "manuel")
    s = clv_summary(led)
    assert (s["sanal_bahis"], s["kapanisli"], s["karsilastirilan"], s["erken"]) == (4, 3, 2, 1)
    r1, f1 = clv(2.5, 2.3, 1.7)
    r2, _ = clv(2.0, 2.1)
    assert s["ham_ort"] == pytest.approx((r1 + r2) / 2) and s["kapanisi_gecen_payi"] == pytest.approx(0.5)
    assert s["marjsiz_n"] == 1 and s["marjsiz_ort"] == pytest.approx(f1) and s["marjsiz_alt"] is None
    line = summary_line(s)
    assert "2/4 bahis" in line and "marjsız CLV ort." in line and "1 kapanış oranı maçtan 1 saatten erken" in line
    # Bahis olmayan kayıtta da satır bazında karşılaştırma görünür
    under = next(r for r in led.predictions() if r["market_key"] == "FT_UNDER_3_5")
    c = record_clv(led, under)
    assert c["kapanis"] == 1.7 and c["ham"] == pytest.approx(1.6 / 1.7 - 1)


def test_summary_interval_and_empty_cases(led):
    assert summary_line(clv_summary(led)) == "Kapanış oranı (CLV): henüz sanal bahis yok."
    led.record_prediction(_rec(EV1, odds=2.5))
    assert "karşılaştırılabilen yok" in summary_line(clv_summary(led))
    led.record_prediction(_rec(EV2, odds=2.0))
    led.record_closing(EV1, "FT_OVER_3_5", 2.3, KICK, "B", "manuel", 1.7)
    led.record_closing(EV2, "FT_OVER_3_5", 2.2, KICK, "B", "manuel", 1.65)
    s = clv_summary(led)
    xs = [clv(2.5, 2.3, 1.7)[1], clv(2.0, 2.2, 1.65)[1]]
    m = sum(xs) / 2
    h = 1.96 * math.sqrt(sum((x - m) ** 2 for x in xs)) / math.sqrt(2)
    assert s["marjsiz_alt"] == pytest.approx(m - h) and s["marjsiz_ust"] == pytest.approx(m + h)
    assert "%95:" in summary_line(s)


def test_ledger_rows_and_csv_carry_closing_columns(led):
    led.record_prediction(_rec(EV1, odds=2.5))
    led.record_prediction(_rec(EV2, odds=None, stake=0.0, status="NO_ODDS"))
    led.record_closing(EV1, "FT_OVER_3_5", 2.3, KICK - dt.timedelta(minutes=10), "B", "manuel", 1.7)
    rows = ledger_rows(led)
    r1, r2 = rows
    raw, fair = clv(2.5, 2.3, 1.7)
    assert r1["Kapanış oranı"] == 2.3 and r1["CLV (ham)"] == pytest.approx(raw)
    assert r1["CLV (marjsız)"] == pytest.approx(fair) and r1["Kapanış zamanlaması"] == "maçtan 10 dk önce"
    assert r2["Kapanış oranı"] is None and r2["CLV (ham)"] is None and r2["Kapanış zamanlaması"] == ""
    text = ledger_csv(rows)
    assert "Kapanış oranı" in text and "nan" not in text.lower()


def test_candidates_list_only_records_with_odds(led):
    assert closing_candidates(led) == []
    led.record_prediction(_rec(EV1, odds=2.5))
    led.record_prediction(_rec(EV2, "FH_OVER_1_5", odds=None, stake=0.0, status="NO_ODDS"))
    led.record_prediction(_rec(EV1, "FT_UNDER_3_5", odds=1.6, stake=0.0, status="NO_VALUE"))
    c = closing_candidates(led)
    assert {(e, m) for e, m, _ in c} == {(EV1, "FT_OVER_3_5"), (EV1, "FT_UNDER_3_5")}
    assert all("kapanış" not in lab for _, _, lab in c)
    led.record_closing(EV1, "FT_OVER_3_5", 2.3, KICK, "B", "manuel", 1.7)
    labels = dict(((e, m), lab) for e, m, lab in closing_candidates(led))
    assert "kapanış 2.30" in labels[(EV1, "FT_OVER_3_5")] and "kapanış 1.70" in labels[(EV1, "FT_UNDER_3_5")]


def _q(event, key, odds, t, book="B1", prov="csv"):
    m = MARKETS[key]
    return OddsQuote(event, key, m.period, m.line, m.selection, prov, book, odds, t, t)


def test_closing_from_csv_quotes_pairs_complements(led):
    qs = [_q(EV1, "FT_OVER_3_5", 2.3, KICK), _q(EV1, "FT_UNDER_3_5", 1.7, KICK + dt.timedelta(minutes=5)),
          _q(EV2, "FT_OVER_3_5", 2.0, KICK), _q(EV2, "FT_UNDER_3_5", 1.9, KICK + dt.timedelta(minutes=30)),
          _q(EV2, "BTTS_BOTH_HALVES_YES", 9.0, KICK, book="B2")]
    n, skipped = closing_from_quotes(led, qs)
    assert n == 4 and not skipped  # EV1 tek kayıt (eşli); EV2 iki ayrı kayıt (30 dk ara); BTTS bir kayıt
    c = led.closing(EV1, "FT_UNDER_3_5")
    assert c["odds"] == 1.7 and c["opposite_odds"] == 2.3 and c["observed_at"] == KICK.isoformat()
    assert led.closing(EV2, "FT_OVER_3_5")["opposite_odds"] is None
    assert led.closing(EV2, "FT_UNDER_3_5")["odds"] == 1.9
    assert closing_from_quotes(led, qs) == (0, [])  # tekrar içe aktarma eklemez
    n, skipped = closing_from_quotes(led, [_q(EV1, "FT_OVER_3_5", 2.6, KICK)])
    assert n == 0 and "gerekçe" in skipped[0]
    assert led.odds_count() == 0  # karar oranı tablosuna yazılmaz


# ------------------------------------------------------------------------------------------------- CLI
def test_cli_closing_commands(tmp_home, tmp_path, capsys):
    from bahis_tahmin.cli import main
    from bahis_tahmin.goals.value import ODDS_CSV_FIELDS

    assert main(["gol-kapanis-ekle"]) == 0 and "Henüz sanal takip kaydı yok" in capsys.readouterr().out
    lg = Ledger(tmp_home / "gol_pazarlari.sqlite")
    lg.record_prediction(_rec(EV1, odds=2.5, decided=dt.datetime(2026, 1, 1, tzinfo=UTC),
                              kickoff=dt.datetime(2026, 1, 2, tzinfo=UTC)))
    lg.close()
    assert main(["gol-kapanis-ekle"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{EV1}\tFT_OVER_3_5\t")
    args = ["gol-kapanis-ekle", "--olay", EV1, "--pazar", "FT_OVER_3_5", "--oran", "2.3", "--karsi", "1.7",
            "--sirket", "B1"]
    assert main(args) == 0 and "kaydedildi" in capsys.readouterr().out
    assert main(args) == 0 and "zaten kayıtlı" in capsys.readouterr().out
    assert main(args[:6] + ["2.4"]) == 2 and "gerekçe" in capsys.readouterr().err
    assert main(["gol-kapanis-ekle", "--olay", EV1]) == 2
    assert main(["gol-sanal"]) == 0
    out = capsys.readouterr().out
    assert "Kapanış oranı (CLV): 1/1 bahis karşılaştırıldı" in out
    # CSV'den kapanış oranı: yalnızca --uygula ile ve kapanış tablosuna
    f = tmp_path / "kapanis.csv"
    f.write_text(",".join(ODDS_CSV_FIELDS) + "\n"
                 f"{EV2},FT_OVER_3_5,FT,3.5,OVER,csv,B1,2.10,2026-01-02T17:55:00+00:00,2026-01-02T18:30:00+00:00,"
                 "OPEN,std-v1\n", encoding="utf-8")
    assert main(["gol-oran-ice-aktar", "--csv", str(f), "--kapanis"]) == 0
    assert "Kuru çalıştırma" in capsys.readouterr().out
    assert main(["gol-oran-ice-aktar", "--csv", str(f), "--kapanis", "--uygula"]) == 0
    assert "1 yeni kapanış oranı" in capsys.readouterr().out
    lg = Ledger(tmp_home / "gol_pazarlari.sqlite")
    assert lg.closing(EV2, "FT_OVER_3_5")["odds"] == 2.1 and lg.odds_count() == 0
    assert json.loads(lg.conn.execute("SELECT payload FROM closing_odds ORDER BY seq DESC").fetchone()[0])[
        "source"] == "csv"
    lg.close()

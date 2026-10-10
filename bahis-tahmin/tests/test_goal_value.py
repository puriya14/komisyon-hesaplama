"""Beklenen değer, oran doğrulama, karar motoru ve sanal takip günlüğü testleri."""

import datetime as dt
import sqlite3

import pytest

from bahis_tahmin.goals.decision import Assessment, DecisionPolicy, apply_concentration, decide
from bahis_tahmin.goals.ledger import Ledger
from bahis_tahmin.goals.value import (
    OddsError,
    OddsQuote,
    breakeven_probability,
    expected_value,
    fair_odds,
    kelly_fraction,
    min_required_odds,
    no_vig_probability,
    parse_odds_csv,
    safe_csv_cell,
    validate_quote,
)

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def quote(market="FT_OVER_3_5", odds=3.4, minutes_ago=5, line=3.5, period="FT", selection="OVER", **kw):
    t = NOW - dt.timedelta(minutes=minutes_ago)
    return OddsQuote(kw.pop("event_id", "T1|2026-10-17|A|B"), market, period, line, selection,
                     kw.pop("provider", "manuel"), kw.pop("bookmaker", "X"), odds, t, t, **kw)


# ------------------------------------------------------------------ EV
def test_ev_examples():
    assert expected_value(0.60, 1.50) == pytest.approx(-0.10)
    assert expected_value(0.40, 3.00) == pytest.approx(0.20)
    assert breakeven_probability(2.0) == pytest.approx(0.5)
    assert fair_odds(0.25) == pytest.approx(4.0)


@pytest.mark.parametrize("bad", [1.0, 0.95, 0.0, -2.0, float("nan"), float("inf")])
def test_invalid_odds_rejected(bad):
    with pytest.raises(OddsError):
        expected_value(0.5, bad)
    assert "GECERSIZ_ORAN" in validate_quote(quote(odds=bad))


def test_commission_and_void_cash_flows():
    # %5 komisyon: kazanınca net 0.95·(d−1)
    assert expected_value(0.5, 2.0, commission=0.05) == pytest.approx(0.5 * 0.95 - 0.5)
    # %10 iade olasılığı: o durumda para geri gelir (0)
    assert expected_value(0.45, 2.0, p_void=0.10) == pytest.approx(0.45 * 1.0 - 0.45)
    # Başabaş komisyonla yükselir
    assert breakeven_probability(2.0, 0.05) == pytest.approx(1 / 1.95)


def test_margin_not_double_counted():
    """EV oranın içindeki marjı zaten taşır: p = başabaş olasılığı ise EV tam olarak 0."""
    d = 1.90
    assert expected_value(1 / d, d) == pytest.approx(0.0, abs=1e-12)


def test_min_required_odds():
    assert min_required_odds(0.25, 0.0) == pytest.approx(4.0)
    assert min_required_odds(0.25, 0.03) == pytest.approx(1.03 / 0.25)
    assert min_required_odds(0.0) is None
    assert min_required_odds(float("nan")) is None
    d = min_required_odds(0.4, 0.05, commission=0.05)
    assert expected_value(0.4, d, commission=0.05) == pytest.approx(0.05)


def test_no_vig_requires_both_sides_same_provider():
    over = quote()
    under = quote(market="FT_UNDER_3_5", selection="UNDER", odds=1.30)
    q = no_vig_probability(over, under)
    assert q == pytest.approx((1 / 3.4) / (1 / 3.4 + 1 / 1.3))
    assert no_vig_probability(over, None) is None  # tek taraftan uydurulmaz
    assert no_vig_probability(over, quote(market="FT_UNDER_3_5", selection="UNDER", odds=1.3, bookmaker="Y")) is None
    assert no_vig_probability(over, quote(market="FT_UNDER_3_5", selection="UNDER", odds=1.3, minutes_ago=60)) is None


def test_wrong_market_or_line_detected():
    assert any(e.startswith("CIZGI_UYUSMAZ") for e in validate_quote(quote(line=2.5)))
    assert any(e.startswith("DONEM_UYUSMAZ") for e in validate_quote(quote(period="1H")))
    assert any(e.startswith("BILINMEYEN_PAZAR") for e in validate_quote(quote(market="FT_OVER_3_25")))
    assert validate_quote(quote()) == []


def test_kelly_capped_and_nonnegative():
    assert kelly_fraction(0.3, 2.0) == 0.0
    assert kelly_fraction(0.6, 2.0, fraction=1.0, cap=1.0) == pytest.approx(0.2)
    assert kelly_fraction(0.6, 2.0) <= 0.02


# --------------------------------------------------------------- karar
def assess(**kw):
    """Karar motoru birim testleri: veri uygunluğu açıkça SENTETİK olarak "geçti" verilir (S3-GATE-01). Uygunluk
    olmadan karar alınamadığı ayrı testlerde (test_eligibility.py) doğrulanır."""
    from bahis_tahmin.goals.markets import MARKETS
    from uygunluk_yardim import verified

    base = dict(event_id="T1|2026-10-17|A|B", league="T1", home="A", away="B", market_key="FT_OVER_3_5",
                p=0.40, p_low=0.36, p_high=0.44, model_validated=True, quote=quote(odds=3.2))
    base.update(kw)
    m = MARKETS.get(base["market_key"])
    primary = base["market_key"] if (m is None or m.selection in ("YES", "OVER")) else m.complement
    base.setdefault("eligibility", verified(base["event_id"], primary, NOW))
    return Assessment(**base)


def test_decision_without_eligibility_is_never_a_candidate():
    """Bağlamsız (uygunluk sonucu verilmemiş) karar çağrısı korumayı aşmaz."""
    d = decide(assess(eligibility=None), NOW)
    assert d.status == "DATA_NOT_ELIGIBLE" and d.p != d.p  # olasılık güvenilir tahmin gibi taşınmaz (NaN, 0 değil)
    assert any("BAGLAM_YOK" in r for r in d.reasons)


def test_value_candidate_only_when_all_checks_pass():
    d = decide(assess(), NOW)
    assert d.status == "VALUE_CANDIDATE"  # 0.36·3.2−1 = 0.152 ≥ 0.03
    assert d.ev == pytest.approx(0.40 * 3.2 - 1)
    assert d.ev_safe == pytest.approx(0.36 * 3.2 - 1)


def test_stale_odds_never_value():
    d = decide(assess(quote=quote(odds=3.2, minutes_ago=600)), NOW)
    assert d.status == "STALE_ODDS"
    future = decide(assess(quote=quote(odds=3.2, minutes_ago=-30)), NOW)  # karar anından sonra
    assert future.status == "STALE_ODDS"


def test_decision_statuses():
    assert decide(assess(quote=None), NOW).status == "ODDS_UNAVAILABLE"
    assert decide(assess(model_validated=False), NOW).status == "MODEL_NOT_VALIDATED"
    assert decide(assess(data_notes=["Ev sahibinin yeterli geçmişi yok"]), NOW).status == "INSUFFICIENT_DATA"
    assert decide(assess(p_low=0.20, p_high=0.60), NOW).status == "HIGH_UNCERTAINTY"
    assert decide(assess(quote=quote(odds=1.8)), NOW).status == "NO_VALUE"
    assert decide(assess(quote=quote(line=2.5, odds=3.2)), NOW).status == "MARKET_UNSUPPORTED"
    assert decide(assess(quote=quote(odds=3.2, settlement_rule_version="saglayici-x")), NOW).status == "SETTLEMENT_AMBIGUOUS"
    assert decide(assess(quote=quote(odds=9.0)), NOW).status == "SUSPICIOUS_EDGE"
    assert decide(assess(market_key="FT_OVER_2_5", quote=None), NOW).status == "MARKET_UNSUPPORTED"
    no_interval = decide(assess(p_low=None, p_high=None), NOW)
    assert no_interval.status == "HIGH_UNCERTAINTY"


def test_no_decision_after_kickoff_or_on_unknown_kickoff_day():
    import datetime as dt

    started = decide(assess(kickoff=NOW - dt.timedelta(minutes=1)), NOW)
    assert started.status == "MARKET_UNSUPPORTED"
    ok = decide(assess(kickoff=NOW + dt.timedelta(hours=3)), NOW)
    assert ok.status == "VALUE_CANDIDATE"
    late_quote = decide(assess(kickoff=NOW + dt.timedelta(minutes=10),
                               quote=quote(odds=3.2, minutes_ago=-20)), NOW + dt.timedelta(minutes=5))
    assert late_quote.status != "VALUE_CANDIDATE"
    # Saat bilinmiyorsa: maç günü (İstanbul) ve sonrasında karar yok, önceki gün serbest
    today = NOW.astimezone(dt.timezone(dt.timedelta(hours=3))).date()
    assert decide(assess(match_date=today), NOW).status == "INSUFFICIENT_DATA"
    assert decide(assess(match_date=today + dt.timedelta(days=1)), NOW).status == "VALUE_CANDIDATE"


def test_concentration_one_candidate_per_match():
    p = DecisionPolicy()
    a = decide(assess(), NOW, p)
    b = decide(assess(market_key="FH_OVER_1_5", p=0.5, p_low=0.47, p_high=0.53,
                      quote=quote(market="FH_OVER_1_5", period="1H", line=1.5, odds=2.3)), NOW, p)
    assert a.status == b.status == "VALUE_CANDIDATE"
    out = apply_concentration([a, b], {a.event_id: "T1"}, {a.event_id: "2026-10-17"}, p)
    assert [d.status for d in out].count("VALUE_CANDIDATE") == 1
    assert any("Aynı maçta" in r for d in out for r in d.reasons)


# ---------------------------------------------------------------- günlük
def _rec(**kw):
    r = dict(event_id="T1|2026-10-17|A|B", market_key="FT_OVER_3_5", decision_time=NOW.isoformat(),
             model_version="m", feature_version="f", data_cutoff="2026-10-16", p=0.4, p_low=0.36, p_high=0.44,
             odds=3.2, decision_status="VALUE_CANDIDATE", reasons=["x"], stake_units=1.0, strategy_version="s1")
    r.update(kw)
    return r


def test_ledger_is_append_only(tmp_path):
    lg = Ledger(tmp_path / "g.sqlite")
    pid = lg.record_prediction(_rec())
    with pytest.raises(sqlite3.DatabaseError):
        lg.conn.execute("UPDATE predictions SET payload='{}' WHERE id=?", (pid,))
    with pytest.raises(sqlite3.DatabaseError):
        lg.conn.execute("DELETE FROM predictions")
    lg.add_odds([quote(odds=3.2)])
    with pytest.raises(sqlite3.DatabaseError):
        lg.conn.execute("UPDATE odds SET decimal_odds = 9.9")
    with pytest.raises(sqlite3.DatabaseError):
        lg.conn.execute("DELETE FROM odds")
    lg.record_outcome(pid, "WIN", "TRUE", "football-data.co.uk")
    lg.record_outcome(pid, "WIN", "TRUE", "football-data.co.uk")  # tekrar → çoğalmaz
    with pytest.raises(ValueError):
        lg.record_outcome(pid, "LOSS", "FALSE", "x")  # gerekçesiz değişiklik reddedilir
    lg.record_outcome(pid, "VOID", "UNKNOWN", "x", note="Maç hükmen sonuçlandı (düzeltme)")
    assert lg.latest_outcome(pid)["settlement"] == "VOID"
    assert len(lg.conn.execute("SELECT * FROM outcomes").fetchall()) == 2  # geçmiş korunur
    ok, _ = lg.verify_chain()
    assert ok
    s = lg.summary()
    assert s["sonuclanan"] == 0 and s["bekleyen_veya_iade"] == 1  # VOID paydaya girmez


def test_ledger_detects_silent_tampering(tmp_path):
    path = tmp_path / "g.sqlite"
    lg = Ledger(path)
    lg.record_prediction(_rec())
    lg.record_prediction(_rec(p=0.5))
    lg.close()
    raw = sqlite3.connect(path)
    raw.execute("DROP TRIGGER predictions_no_update")
    raw.execute("UPDATE predictions SET payload = replace(payload, '0.5', '0.9') WHERE seq = 2")
    raw.commit()
    raw.close()
    ok, msg = Ledger(path).verify_chain()
    assert not ok and "#2" in msg


def test_odds_import_idempotent_and_point_in_time(tmp_path):
    csv_text = (
        "event_id,market_key,period,line,selection,provider,bookmaker,decimal_odds,quoted_at,fetched_at,status,settlement_rule_version\n"
        "E1,FT_OVER_3_5,FT,3.5,OVER,manuel,X,3.40,2026-10-17T11:00:00+03:00,2026-10-17T11:01:00+03:00,OPEN,std-v1\n"
        "E1,FT_OVER_3_5,FT,3.5,OVER,manuel,X,3.10,2026-10-17T15:00:00+03:00,2026-10-17T15:01:00+03:00,OPEN,std-v1\n"
        "E1,FT_OVER_3_5,FT,2.5,OVER,manuel,X,1.90,2026-10-17T11:00:00+03:00,2026-10-17T11:01:00+03:00,OPEN,std-v1\n"
        "E1,FH_OVER_1_5,1H,1.5,OVER,manuel,X,abc,2026-10-17T11:00:00+03:00,2026-10-17T11:01:00+03:00,OPEN,std-v1\n"
    ).encode()
    quotes, bad = parse_odds_csv(csv_text)
    assert len(quotes) == 2 and len(bad) == 2  # yanlış çizgi ve bozuk oran karantinada
    lg = Ledger(tmp_path / "g.sqlite")
    assert lg.add_odds(quotes) == 2
    assert lg.add_odds(quotes) == 0  # aynı dosya tekrar → çoğalmaz
    decision_time = dt.datetime(2026, 10, 17, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=3)))
    q = lg.latest_quote("E1", "FT_OVER_3_5", decision_time)
    assert q.decimal_odds == pytest.approx(3.40)  # karar anından sonraki 3.10 kullanılmaz


def test_csv_formula_injection_guard():
    assert safe_csv_cell("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert safe_csv_cell("@cmd") == "'@cmd"
    assert safe_csv_cell("-0.05") == "-0.05"
    assert safe_csv_cell("Galatasaray") == "Galatasaray"

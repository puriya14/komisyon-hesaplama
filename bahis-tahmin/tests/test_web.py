"""WEB-01: tarayıcı arayüzü (Flask). Masaüstüyle aynı çekirdek (``bahis_tahmin.core``) ve aynı uygunluk kuralları.

Yalnızca SENTETİK veri; ağ isteği yok (güncelleme işi sahte işlevle çalıştırılır)."""

from __future__ import annotations

import datetime as dt
import re

import pandas as pd
import pytest

pytest.importorskip("flask")

from uygunluk_yardim import (  # noqa: E402
    AS_OF,
    FIXTURE_DAY,
    full_context,
    recent_synthetic,
)

from bahis_tahmin.config import Settings  # noqa: E402
from bahis_tahmin.data.source_registry import CONSENT_SCHEMA  # noqa: E402
from bahis_tahmin.data.store import DataStore, UpdateReport  # noqa: E402
from bahis_tahmin.web import create_app  # noqa: E402

LOCAL = {"Host": "127.0.0.1:8765"}
PAGES = ["/", "/tahminler", "/en-olasi", "/analiz", "/gol/", "/gol/?sekme=mac", "/gol/?sekme=kapsam",
         "/gol/?sekme=dogrulama", "/gol/?sekme=takip", "/guc", "/test", "/veri", "/onay", "/ayarlar", "/hakkinda"]


def _client(app):
    c = app.test_client()
    c.environ_base.update({"HTTP_HOST": "127.0.0.1:8765"})
    return c


def _csrf(client, path="/ayarlar") -> str:
    html = client.get(path).get_data(as_text=True)
    return re.search(r'data-csrf="([^"]+)"', html).group(1)


@pytest.fixture
def app(tmp_home):
    a = create_app(load=False)
    a.config["TESTING"] = True
    return a


@pytest.fixture(scope="module")
def full():
    """Uygunluğu geçen tam SENTETİK bağlam: depo, motorlar, takvim, haklar ve sabit saat."""
    from bahis_tahmin.goals.engine import GoalEngine
    from bahis_tahmin.models.engine import PredictionEngine

    m = recent_synthetic()
    eng = PredictionEngine()
    eng.train(m)
    goal = GoalEngine()
    goal.train(m)
    teams = sorted(set(m["home"]))
    fx = pd.DataFrame([{"league": "T1", "date": pd.Timestamp(FIXTURE_DAY), "time": "19:00", "home": teams[2 * i],
                        "away": teams[2 * i + 1], "source": "SENTETIK-FIKSTUR"} for i in range(4)])
    return m, eng, goal, fx, teams


def _install(app, m, eng, fx, goal=None, ctx=None, clock=None):
    """Durumu doğrudan kurar (testlerde arka plan yüklemesi yok)."""
    from bahis_tahmin.goals.service import gated_goal_predictions

    core = app.extensions["bahis_tahmin"].core
    st = DataStore(core.home)
    st.matches = m
    st.fixtures = fx.reindex(columns=st.fixtures.columns)
    core.store, core.engine, core.goal_engine, core.loaded = st, eng, goal, True
    if clock is not None:
        core.clock = clock
    if ctx is not None:
        core.eligibility_context = lambda engine: ctx
    core.refresh_predictions()
    if goal is not None:
        core.set_goal_verdicts(gated_goal_predictions(goal, core.eligibility_context(goal), st.fixtures, core.now()))
    return core


# ============================================================ temel ve güvenlik


def test_first_run_pages_render(app):
    c = _client(app)
    for path in PAGES:
        r = c.get(path)
        assert r.status_code == 200, path
        assert "18+" in r.get_data(as_text=True)
    assert "Hoş geldiniz" in c.get("/").get_data(as_text=True)
    assert c.get("/yok").status_code == 404
    s = c.get("/api/is").get_json()
    assert s["busy"] is False and s["finished"] == 0


def test_local_only_host_csrf_and_security_headers(app):
    c = app.test_client()
    assert c.get("/", headers={"Host": "kotu.example:8765"}).status_code == 403  # DNS yeniden bağlama
    for host in ("127.0.0.1:8765", "localhost:8765", "[::1]:8765"):
        assert c.get("/", headers={"Host": host}).status_code == 200
    c = _client(app)
    assert c.post("/ayarlar", data={"min_ev": "0.2"}).status_code == 400  # CSRF anahtarı yok
    assert c.post("/ayarlar", data={"min_ev": "0.2", "csrf": "yanlis"}).status_code == 400
    r = c.get("/")
    csp = r.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert r.headers["X-Frame-Options"] == "DENY" and r.headers["Cache-Control"] == "no-store"
    assert "<script>" not in r.get_data(as_text=True).replace('<script src=', '')  # satır içi betik yok


def test_password_mode_requires_login_and_blocks_open_redirect(tmp_home):
    a = create_app(load=False, password="gizli-parola")
    c = a.test_client()
    c.environ_base.update({"HTTP_HOST": "192.168.1.20:8765"})  # ağda paylaşım: yerel olmayan adres
    r = c.get("/tahminler")
    assert r.status_code == 302 and "/giris" in r.headers["Location"]
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/giris").get_data(as_text=True)).group(1)
    r = c.post("/giris", data={"parola": "yanlis", "csrf": tok})
    assert "Parola yanlış" in r.get_data(as_text=True)
    r = c.post("/giris", data={"parola": "gizli-parola", "csrf": tok, "sonra": "//kotu.example/x"})
    assert r.status_code == 302 and r.headers["Location"] == "/"
    assert c.get("/tahminler").status_code == 200
    tok = re.search(r'data-csrf="([^"]+)"', c.get("/").get_data(as_text=True)).group(1)
    c.post("/cikis", data={"csrf": tok})
    assert c.get("/tahminler").status_code == 302


def test_lan_sharing_needs_password():
    from bahis_tahmin.web import serve

    assert serve(host="0.0.0.0", password=None, open_browser=False) == 2  # sunucu başlatılmaz


# ============================================================ onay, beyan ve ayarlar


def test_consent_and_declaration_rules(app):
    c = _client(app)
    tok = _csrf(c, "/onay")
    html = c.get("/onay").get_data(as_text=True)
    assert 'name="onay_football-data"' in html and 'name="beyan_football-data"' in html
    # Beyan, indirme onayı olmadan kaydedilmez
    c.post("/onay", data={"csrf": tok, "beyan_github-mirror": "1", "onay_football-data": "1",
                          "beyan_football-data": "1"})
    s = Settings.load()
    assert set(s.source_consent) == {"football-data"} and set(s.kisisel_kullanim) == {"football-data"}
    assert s.onay_surumu == CONSENT_SCHEMA
    # Onay geri alınınca beyan da kalkar
    c.post("/onay", data={"csrf": tok})
    s = Settings.load()
    assert not s.source_consent and not s.kisisel_kullanim


def test_update_asks_consent_first_and_saves_league_choice(app):
    c = _client(app)
    tok = _csrf(c)
    r = c.post("/veri/guncelle", data={"csrf": tok, "kaydet": "1", "lig_T1": "1", "lig_E0": "1", "yil": "5"})
    assert r.status_code == 302 and "/onay" in r.headers["Location"] and "guncelle" in r.headers["Location"]
    s = Settings.load()
    assert s.leagues == ["T1", "E0"] and s.years_back == 5
    assert not app.extensions["bahis_tahmin"].busy  # onay olmadan indirme başlamaz


def test_settings_are_validated_and_shared_with_desktop(app):
    c = _client(app)
    tok = _csrf(c)
    c.post("/ayarlar", data={"csrf": tok, "oran": "max", "marj": "power", "min_ev": "0,08", "min_prob": "5",
                             "min_odds": "1.5", "max_odds": "1.2", "kasa": "2500", "para": "EUR", "kelly": "0.3",
                             "tavan": "0.04", "gun": "99", "denetim": "siki", "yedek": "1"})
    s = Settings.load()  # masaüstüyle aynı settings.json
    assert s.odds_type == "max" and s.min_ev == pytest.approx(0.08) and s.min_prob == pytest.approx(0.99)
    assert s.max_odds == pytest.approx(1.5) and s.fixture_days == 60 and s.veri_denetimi == "siki"
    assert s.currency == "EUR" and s.use_mirror_fallback and not s.stake_suggestions


def test_changes_made_in_desktop_app_are_picked_up(app):
    """Masaüstü aynı anda açıkken ayar/veri/model dosyalarını değiştirirse web arayüzü hepsini yeniden yükler; web
    arayüzünün kendi kaydı ise yeniden yüklemeye yol açmaz."""
    import os

    st = app.extensions["bahis_tahmin"]
    assert st.start_load()
    st.jobs.wait(60)
    c = _client(app)
    tok = _csrf(c)
    fin = st.jobs.finished
    c.post("/ayarlar", data={"csrf": tok, "kasa": "2500", "kelly": "0.3", "tavan": "0.04", "gun": "10"})
    c.get("/tahminler")
    assert st.jobs.finished == fin and not st.busy  # kendi kaydı: yeniden yükleme yok
    s = Settings.load()  # masaüstü aynı dosyayı değiştiriyor
    s.bankroll = 4321.0
    s.save()
    p = Settings.path()
    os.utime(p, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns + 10_000_000))  # kaba saat çözünürlüğüne karşı
    c.get("/tahminler")
    st.jobs.wait(60)
    assert st.jobs.finished == fin + 1 and st.core.settings.bankroll == pytest.approx(4321.0)
    c.get("/tahminler")
    assert st.jobs.finished == fin + 1  # aynı değişiklik ikinci kez yüklenmez


# ============================================================ arka plan işi (güncelleme + tahmin)


def test_update_job_runs_and_refreshes_predictions(app, monkeypatch, synthetic, trained_engine):
    from bahis_tahmin.web import state as W

    calls = {}

    def fake_update(home, settings, old_engine, old_goal, force, progress, allowed=None, old_cup=None):
        progress(10, "sahte indirme")
        calls["allowed"] = set(allowed)
        st = DataStore(home)
        st.matches = synthetic
        fx = synthetic.tail(3)[["league", "date", "time", "home", "away", "source"]].copy()
        fx["date"] = pd.Timestamp(dt.date.today() + dt.timedelta(days=1))
        st.fixtures = fx.reindex(columns=st.fixtures.columns)
        rep = UpdateReport()
        rep.n_matches, rep.n_fixtures = len(synthetic), len(fx)
        return st, trained_engine, rep, (None, None)

    monkeypatch.setattr(W, "update_work", fake_update)
    s = app.extensions["bahis_tahmin"].core.settings
    s.source_consent["football-data"] = "2026-10-10T10:00:00"
    s.onay_surumu = CONSENT_SCHEMA
    c = _client(app)
    tok = _csrf(c)
    r = c.post("/veri/guncelle", data={"csrf": tok})
    assert r.status_code == 302
    st = app.extensions["bahis_tahmin"]
    st.jobs.wait(30)
    status = c.get("/api/is").get_json()
    assert status["finished"] == 1 and status["error"] is None and "maç" in status["notice"]
    assert calls["allowed"] == s.allowed_sources()
    assert len(st.core.predictions) == 3 and st.core.store.has_data
    # Sonuç bildirimi yalnızca iş bittikten sonraki ilk sayfada gösterilir
    assert "yaklaşan maç yüklendi" in c.get(f"/veri?bitti={status['finished']}").get_data(as_text=True)
    assert "yaklaşan maç yüklendi" not in c.get("/tahminler").get_data(as_text=True)


def test_job_runner_runs_one_job_and_reports_errors():
    import threading

    from bahis_tahmin.web.jobs import JobRunner

    j = JobRunner()
    gate = threading.Event()
    assert j.start("bir", lambda p: gate.wait(5))
    assert not j.start("iki", lambda p: None)  # aynı anda tek iş
    gate.set()
    j.wait(5)

    def boom(p):
        raise RuntimeError("bozuk dosya")

    assert j.start("hatalı iş", boom)
    j.wait(5)
    s = j.status()
    assert not s["busy"] and s["finished"] == 2 and "bozuk dosya" in s["error"]


# ============================================================ tahminler, maç ayrıntısı, en olası


def test_unverified_data_shows_reason_not_probabilities(app, synthetic, trained_engine):
    """Sentetik verinin kullanım hakkı bilinmiyor: olasılık gösterilmez, neden yazılır (masaüstüyle aynı kural)."""
    fx = synthetic.tail(2)[["league", "date", "time", "home", "away", "source"]].copy()
    fx["date"] = pd.Timestamp(dt.date.today() + dt.timedelta(days=1))
    core = _install(app, synthetic, trained_engine, fx)
    c = _client(app)
    html = c.get("/tahminler").get_data(as_text=True)
    df = core.prediction_frame()
    assert df["p1"].isna().all() and len(df) == 2
    assert df["veri"].iloc[0] in html and df["veri_neden"].iloc[0] in html.replace("&#39;", "'")
    key = re.search(r'href="(/mac\?k=[^"]+)"', html).group(1)
    detail = c.get(key.replace("&amp;", "&")).get_data(as_text=True)
    assert "Tahmin gösterilmiyor" in detail and "Takım karşılaştırması" in detail


def test_usable_predictions_detail_and_likely(app, full):
    m, eng, _goal, fx, teams = full
    ctx = full_context(m, eng, AS_OF, FIXTURE_DAY, mode="standart")
    core = _install(app, m, eng, fx, ctx=ctx, clock=lambda: AS_OF)
    assert any(p.forecast_ok_at(AS_OF) for p in core.predictions)
    c = _client(app)
    html = c.get("/tahminler").get_data(as_text=True)
    row = core.prediction_frame().iloc[0]
    from bahis_tahmin.fmt import fmt_pct

    assert fmt_pct(row["p1"]) in html and teams[0] in html
    key = re.search(r'href="(/mac\?k=[^"]+)"', html).group(1).replace("&amp;", "&")
    detail = c.get(key).get_data(as_text=True)
    assert "Marketler, adil oranlar ve değer" in detail and "Skor olasılıkları" in detail
    assert 'class="probbar"' in detail and "En olası skorlar" in detail
    likely = c.get("/en-olasi?esik=0.60&g_Çifte Şans=1&tek=1").get_data(as_text=True)
    assert "Yaklaşan maçlardaki seçimler" in likely
    assert c.get("/mac?k=yok").status_code == 302  # bilinmeyen maç: tahminlere dönülür
    # Filtreler: arama ve lig
    assert teams[0] in c.get(f"/tahminler?ara={teams[0]}").get_data(as_text=True)
    assert teams[2] not in c.get(f"/tahminler?ara={teams[0]}").get_data(as_text=True).split("<tbody>")[1]


def test_team_names_are_escaped(app, synthetic, trained_engine):
    fx = pd.DataFrame([{"league": "T1", "date": pd.Timestamp(dt.date.today() + dt.timedelta(days=1)), "time": "",
                        "home": "<script>alert(1)</script>", "away": "Takım A", "source": "x"}])
    _install(app, synthetic, trained_engine, fx)
    html = _client(app).get("/tahminler").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_manual_analysis_uses_entered_odds(app, synthetic, trained_engine):
    _install(app, synthetic, trained_engine, synthetic.iloc[0:0][["league", "date", "time", "home", "away", "source"]])
    c = _client(app)
    tok = _csrf(c, "/analiz")
    teams = trained_engine.teams("T1")
    r = c.post("/analiz", data={"csrf": tok, "lig": "T1", "ev": teams[0], "dep": teams[1], "tarih": "2026-11-04",
                                "o_1": "2.50", "o_X": "3.30", "o_2": "2.90", "piyasa": "1"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and f"{teams[0]} – {teams[1]}" in html
    assert "Girdiğiniz oranlar piyasa bilgisi olarak kullanıldı." in html
    r = c.post("/analiz", data={"csrf": tok, "lig": "T1", "ev": teams[0], "dep": teams[0]})
    assert "Lütfen iki farklı takım seçin." in r.get_data(as_text=True)


def test_dashboard_ratings_and_backtest(app, synthetic, trained_engine):
    _install(app, synthetic, trained_engine, synthetic.iloc[0:0][["league", "date", "time", "home", "away", "source"]])
    c = _client(app)
    html = c.get("/").get_data(as_text=True)
    assert "data:image/svg+xml;base64," in html and "1X2 isabeti" in html  # grafikler SVG olarak
    assert "Puan durumu" in c.get("/guc?lig=T1").get_data(as_text=True)
    bt = c.get("/test?calistir=1&m_1x2=1&m_ou=1&oran=avg&lig=T1").get_data(as_text=True)
    assert "Bahis sayısı" in bt and "Sezonlara göre" in bt


# ============================================================ gol pazarları


def test_goal_markets_scan_decide_record_and_ledger(app, full):
    m, eng, goal, fx, teams = full
    ctx = full_context(m, goal, AS_OF, FIXTURE_DAY)
    core = _install(app, m, eng, fx, goal=goal, ctx=ctx, clock=lambda: AS_OF)
    assert len(core.goal_verdicts) == 4 and all(v.forecast_ok for v in core.goal_verdicts)
    c = _client(app)
    scan = c.get("/gol/").get_data(as_text=True)
    assert scan.count("Kullanılabilir") >= 4 and "DOĞRULANMADI" in scan
    assert "Uygun aday yok" in c.get("/gol/?gorunum=value").get_data(as_text=True)
    aday = core.goal_verdicts[0].candidate_id
    mac = c.get("/gol/", query_string={"sekme": "mac", "aday": aday}).get_data(as_text=True)
    assert "Karar tablosu" in mac and "İki yarıda KG için dört koşul" in mac and "Veri uygunluğu" in mac
    tok = _csrf(c)
    r = c.post("/gol/oran", data={"csrf": tok, "aday": aday, "o_FT_OVER_3_5": "3.40", "sirket": "Test"})
    assert r.status_code == 302
    with core.ledger(create=False) as led:
        assert led is not None
    r = c.post("/gol/kaydet", data={"csrf": tok, "aday": aday})
    assert r.status_code == 302 and "takip" in r.headers["Location"]
    takip = c.get("/gol/?sekme=takip").get_data(as_text=True)
    assert "kayıt" in takip and "Kayıt yok." not in takip
    assert "✔" in c.post("/gol/zincir", data={"csrf": tok}, follow_redirects=True).get_data(as_text=True)
    csv = c.get("/gol/takip.csv")
    assert csv.headers["Content-Disposition"].endswith("sanal_takip.csv") and len(csv.data) > 10
    # ORAN-03: kapanış oranı girişi ve CLV
    assert "Kapanış oranı gir (CLV)" in takip and "Kapanış oranı (CLV):" in takip
    key = f"{aday}§FT_OVER_3_5"
    assert f'value="{key}"' in takip
    r = c.post("/gol/kapanis", data={"csrf": tok, "kayit": key, "oran": "0,9"}, follow_redirects=True)
    assert "Kayıt seçin" in r.get_data(as_text=True)
    r = c.post("/gol/kapanis", data={"csrf": tok, "kayit": key, "oran": "3,10", "karsi": "1,40", "sirket": "Test"},
               follow_redirects=True)
    assert "Kapanış oranı kaydedildi" in r.get_data(as_text=True)
    r = c.post("/gol/kapanis", data={"csrf": tok, "kayit": key, "oran": "3,20"}, follow_redirects=True)
    assert "gerekçe" in r.get_data(as_text=True)
    with core.ledger(create=False) as led:
        c0 = led.closing(aday, "FT_OVER_3_5")
        assert c0["odds"] == 3.1 and c0["opposite_odds"] == 1.4 and c0["bookmaker"] == "Test"
        assert led.closing_count() == 1
    assert "kapanış 3.10" in c.get("/gol/?sekme=takip").get_data(as_text=True)
    assert c.post("/gol/kapanis", data={"kayit": key, "oran": "3,10"}).status_code in (400, 403)  # CSRF zorunlu
    # Elle seçilen maç da aynı uygunluk kontrolünden geçer
    manual = c.get("/gol/", query_string={"sekme": "mac", "lig": "T1", "ev": teams[0], "dep": teams[1]})
    assert "Karar tablosu" in manual.get_data(as_text=True)


def test_goal_record_refused_when_data_not_eligible(app, full, synthetic, trained_engine):
    from bahis_tahmin.goals.engine import GoalEngine

    m, _eng, goal, fx, _teams = full
    core = _install(app, m, trained_engine, fx, goal=goal)  # gerçek bağlam: sentetik kaynağın hakkı yok
    assert core.goal_verdicts and not any(v.any_usable(core.now()) for v in core.goal_verdicts)
    c = _client(app)
    tok = _csrf(c)
    r = c.post("/gol/kaydet", data={"csrf": tok, "aday": core.goal_verdicts[0].candidate_id}, follow_redirects=True)
    assert "Kayıt yapılmadı" in r.get_data(as_text=True)
    with core.ledger(create=False) as led:
        assert led is None  # günlük oluşturulmadı
    assert isinstance(goal, GoalEngine)

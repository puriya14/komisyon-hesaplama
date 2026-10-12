"""Arayüz duman testleri (ekransız / offscreen)."""

import datetime as dt
import os
import sys

import pandas as pd
import pytest

if sys.platform != "win32" and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


def _istanbul_today() -> pd.Timestamp:
    from bahis_tahmin.timeutil import ISTANBUL

    return pd.Timestamp(dt.datetime.now(ISTANBUL).date())


@pytest.fixture(scope="module")
def app():
    from bahis_tahmin.ui.theme import apply_theme

    a = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    apply_theme(a)
    return a


@pytest.fixture
def window(app, synthetic, trained_engine, tmp_home):
    from bahis_tahmin.data.store import DataStore
    from bahis_tahmin.ui.main_window import MainWindow

    win = MainWindow()
    st = DataStore(tmp_home)
    st.matches = synthetic
    fx = synthetic.tail(5)[["league", "date", "time", "home", "away", "o_h", "o_d", "o_a", "o_o25", "o_u25", "source"]].copy()
    fx["date"] = _istanbul_today()  # uygulamanın maç günü İstanbul günüdür (UTC akşamı yerel tarihle çakışmasın)
    st.fixtures = fx.reindex(columns=st.fixtures.columns)
    win.ctl.store = st
    win.ctl.engine = trained_engine
    win.ctl.dataChanged.emit()
    win.ctl.modelChanged.emit()
    win.ctl.refresh_predictions()
    yield win
    win.close()


def test_all_pages_render(app, window):
    assert len(window.ctl.predictions) == 5
    # Sentetik verinin kaynak etiketi kaynak kaydında yok (kullanım hakkı bilinmiyor): standart veri denetiminde de
    # hiçbir tahmin "uygun" gösterilmez (yapısal engel)
    assert all(not p.forecast_ok and p.eligibility is not None for p in window.ctl.predictions)
    for row in range(window.nav.count()):
        window.nav.setCurrentRow(row)
        app.processEvents()
        assert window.stack.currentIndex() == row


def test_predictions_table_and_dialog(app, window):
    from bahis_tahmin.ui.match_view import MatchDialog
    from bahis_tahmin.ui.pages.predictions import PredictionsPage

    page = window.page(PredictionsPage)
    assert page.model.rowCount() == 5
    df = page.model.frame
    assert df["p1"].isna().all() and (df["value"] == "").all()  # olasılık boş (sıfır değil), değer önerisi yok
    # durum renkle değil metinle; standart modda etiket birincil nedenin türünü yazar (hak yok: "Uygun değil")
    assert df["veri"].str.startswith("Uygun değil").all() and df["veri"].str.contains("KAYNAK_HAKKI_BILINMIYOR").all()
    dlg = MatchDialog(window.ctl, window.ctl.predictions[0])
    assert dlg.detail.mk_model.rowCount() == 0 and "Tahmin gösterilmiyor" in dlg.detail.summary.text()
    dlg.close()
    # Aynı model durumuna bağlı, açıkça SENTETİK "uygun" sonuçla ayrıntı tablosu normal görünür
    from uygunluk_yardim import verified

    p = window.ctl.predictions[0]
    now = dt.datetime.now(dt.timezone.utc)
    window.ctl.clock = lambda: now
    p.eligibility = verified(p.event_id, "1X2", now, state_digest=p.state_digest)
    dlg = MatchDialog(window.ctl, p)
    assert dlg.detail.mk_model.rowCount() == 14
    dlg.close()
    assert window.ctl.prediction_frame()["p1"].notna().sum() == 1
    # Ertesi gün: aynı sonuç yeniden kullanılmaz (olasılık gösterilmez, neden yazılır)
    window.ctl.clock = lambda: now + dt.timedelta(days=1)
    df = window.ctl.prediction_frame()
    assert df["p1"].isna().all() and "BAGLAM_UYUSMUYOR" in df.loc[0, "veri"]
    dlg = MatchDialog(window.ctl, p)
    assert dlg.detail.mk_model.rowCount() == 0
    dlg.close()
    # Tahminler sayfası gün değişimini görünce uygunluğu yeniden değerlendirir
    window.ctl._match_day = (now - dt.timedelta(days=1)).date()
    page.refresh()
    assert window.ctl._match_day == window.ctl.today()
    # Sayfa geçişi (on_show) de gün değişimini denetler
    window.ctl._match_day = (now - dt.timedelta(days=1)).date()
    window.nav.setCurrentRow((window.nav.currentRow() + 1) % window.nav.count())
    assert window.ctl._match_day == window.ctl.today()


def test_backtest_and_likely_pages(app, window):
    from bahis_tahmin.ui.pages.backtest import BacktestPage
    from bahis_tahmin.ui.pages.likely import LikelyPage

    bt = window.page(BacktestPage)
    bt.sp_ev.setValue(0.0)
    bt.run()
    assert bt.c_bets.value.text() != ""
    bk = window.page(LikelyPage)
    bk.sp_thr.setValue(0.7)
    bk.refresh()
    assert bk.c_hit.value.text() != ""
    assert bk.model.rowCount() == 0 and "listelenmeyen maç: 5" in bk.gate_note.text()  # uygun olmayan listelenmez
    # Açıkça SENTETİK "uygun" sonuçla olumlu yol (liste + kupon) çalışır
    from uygunluk_yardim import verified

    now = dt.datetime.now(dt.timezone.utc)
    window.ctl.clock = lambda: now
    for p in window.ctl.predictions:
        p.eligibility = verified(p.event_id, "1X2", now, state_digest=p.state_digest)
    bk.refresh()
    assert bk.model.rowCount() > 0 and bk.gate_note.text() == ""
    if bk.model.rowCount():
        from PySide6.QtCore import Qt

        bk.model.setData(bk.model.index(0, 0), Qt.Checked, Qt.CheckStateRole)
        assert "maç" in bk.kupon.text()


def test_unmatched_only_fixtures_are_listed_with_reasons(app, window):
    """Fikstür tablosu boşken yalnızca eşleşmeyen fikstür varsa da nedenli satır üretilir (sessizce düşmez)."""
    from bahis_tahmin.ui.pages.dashboard import DashboardPage
    from bahis_tahmin.ui.pages.predictions import PredictionsPage

    ctl = window.ctl
    ctl.store.fixtures = ctl.store.fixtures.iloc[0:0]
    ctl.store.meta["eslesmeyen_fikstur"] = [{"league": "T1", "date": str(_istanbul_today().date()), "time": "",
                                             "raw_home": "Qwerty Kulubu", "raw_away": "Zyx Gucu",
                                             "source": "openfootball"}]
    ctl.refresh_predictions()
    df = ctl.prediction_frame()
    assert len(df) == 1 and df.loc[0, "_i"] == -1 and "TAKIM_ESLESMEDI" in df.loc[0, "veri"]
    assert window.page(PredictionsPage).model.rowCount() == 1
    dash = window.page(DashboardPage)
    dash.refresh()
    assert "tahmin yok 1" in dash.c_fix.sub.text()


def test_match_analysis_page(app, window):
    from bahis_tahmin.ui.pages.match import MatchPage

    page = window.page(MatchPage)
    page._fill_leagues()
    assert page.cb_home.count() > 2
    page.cb_home.setCurrentIndex(0)
    page.cb_away.setCurrentIndex(1)
    page.odds["1"].setValue(2.5)
    page.analyze()
    assert page.detail.pred is not None
    assert page.detail.pred.odds.get("1") == pytest.approx(2.5)


@pytest.fixture(scope="module")
def goal_setup():
    from bahis_tahmin.goals.engine import GoalEngine
    from uygunluk_yardim import recent_synthetic

    m = recent_synthetic()
    eng = GoalEngine()
    eng.train(m)
    return m, eng


def test_goals_page(app, window, goal_setup):
    """Açıkça SENTETİK tam bağlamla (takvim + haklar) ana ekran akışı: uygunluk geçer, kararlar ve kayıt çalışır."""
    from bahis_tahmin.goals.service import gated_goal_predictions
    from bahis_tahmin.ui.pages.goals import GoalsPage
    from uygunluk_yardim import AS_OF, FIXTURE_DAY, full_context

    m, eng = goal_setup
    ctl = window.ctl
    ctl.store.matches = m
    teams = sorted(set(m["home"]))
    fx = pd.DataFrame([{"league": "T1", "date": pd.Timestamp(FIXTURE_DAY), "time": "", "home": teams[2 * i],
                        "away": teams[2 * i + 1], "source": "SENTETIK"} for i in range(4)])
    ctx = full_context(m, eng, AS_OF, FIXTURE_DAY)
    ctl.clock = lambda: AS_OF
    ctl.eligibility_context = lambda engine: ctx
    ctl.goal_engine = eng
    ctl.goal_verdicts = gated_goal_predictions(eng, ctx, fx, AS_OF)
    assert all(v.forecast_ok for v in ctl.goal_verdicts)
    ctl.goalModelChanged.emit()
    page = window.page(GoalsPage)
    assert page.scan_model.rowCount() == 4
    assert page.scan_model.frame["data"].str.startswith("Kullanılabilir").all()
    assert "DOĞRULANMADI" in page.status_banner.text()
    page.cb_mode.setCurrentIndex(1)  # avantaj adayları: doğrulanmamış model ve oran yok → boş, açıklamalı
    assert page.scan_model.rowCount() == 0 and "Uygun aday yok" in page.scan_note.text()
    page.cb_fixture.setCurrentIndex(1)
    assert page.dec_model.rowCount() == 6
    assert not (ctl.home / "gol_pazarlari.sqlite").exists()  # görüntüleme dosya oluşturmaz
    assert page.cond_model.rowCount() == 4
    page.odds_spin["FT_OVER_3_5"].setValue(2.10)
    page.ed_book.setText("Test")
    page._save_odds()
    assert ctl.ledger.odds_count() == 1
    row = page.dec_model.frame.set_index("secim").loc["Maç sonu 3,5 Üst"]
    assert row["oran"] == pytest.approx(2.10)
    page._record()
    assert len(ctl.ledger.predictions()) == 6
    assert all(r["veri_uygunlugu"]["tahmin_uygun"] for r in ctl.ledger.predictions())
    assert page.led_model.rowCount() == 6
    # T01 (ana ekran): bilinen eksik tamamlanmış maç → olasılık gösterilmez, hiçbir pazar aday olmaz
    team = fx.loc[0, "home"]
    idx = m[(m["home"] == team) | (m["away"] == team)].index[-3]
    stale = full_context(m.drop(index=idx), eng, AS_OF, FIXTURE_DAY, schedule=m)
    for k in eng.validated:
        eng.validated[k] = True
    try:
        sv = gated_goal_predictions(eng, stale, fx.iloc[[0]], AS_OF)
        p0 = sv[0].prediction
        from bahis_tahmin.goals.markets import MARKETS as GM
        from bahis_tahmin.goals.value import OddsQuote as Q

        ctl.ledger.add_odds([Q(p0.event_id, k, GM[k].period, GM[k].line, GM[k].selection, "manuel", "t", 3.0,
                               AS_OF, AS_OF) for k in ("FT_OVER_3_5", "FH_OVER_1_5", "BTTS_BOTH_HALVES_YES")])
        saved = ctl.goal_verdicts
        ctl.goal_verdicts = sv
        page.cb_mode.setCurrentIndex(0)
        page.refresh_scan()
        row = page.scan_model.frame.iloc[0]
        assert row["data"].startswith("Eksik veri") and "DEPODA_EKSIK_MAC" in row["neden"] and row["B"] != row["B"]
        assert "ADAY" not in row["decision"] and "VERİ UYGUN DEĞİL" in row["decision"]
        page.cb_mode.setCurrentIndex(1)
        assert page.scan_model.rowCount() == 0
        page.cb_mode.setCurrentIndex(0)
        ctl.goal_verdicts = saved
        # Kayıt anında yeniden doğrulama: aday dün hesaplandı, kayıt ertesi gün → bahis adayı kaydı/stake yok
        page.refresh_scan()
        good = next((i for i, v in enumerate(ctl.goal_verdicts) if v.prediction is not None), 0)
        pv = ctl.goal_verdicts[good].prediction
        ctl.ledger.add_odds([Q(pv.event_id, k, GM[k].period, GM[k].line, GM[k].selection, "manuel", "t",
                               round(1.06 / max(pv.interval(k)[0], 0.05), 2), AS_OF, AS_OF)
                             for k in ("FT_OVER_3_5", "FH_OVER_1_5", "BTTS_BOTH_HALVES_YES")])
        page.cb_fixture.setCurrentIndex(good + 1)
        page._show(ctl.goal_verdicts[good])
        n0 = len(ctl.ledger.predictions())
        ctl.clock = lambda: AS_OF + dt.timedelta(days=3)
        page._record()
        new = ctl.ledger.predictions()[n0:]
        assert new and all(r["kayit_turu"] == "KARAR_KAYDI" and r["stake_units"] == 0 for r in new)
        # Gün değişince tarama önceki günün sonucunu "Kullanılabilir" göstermez
        page.refresh_scan()
        assert page.scan_model.frame["A"].isna().all()
        assert page.scan_model.frame["data"].str.contains("BAGLAM_UYUSMUYOR").all()
        ctl.clock = lambda: AS_OF
    finally:
        for k in eng.validated:
            eng.validated[k] = False
    # Model değişince maç analizi paneli eski tahminle kalmaz; eski tahminle kayıt yapılmaz
    page.cb_fixture.setCurrentIndex(1)
    assert page._current is not None and page.btn_record.isEnabled()
    n0 = len(ctl.ledger.predictions())
    from bahis_tahmin.goals.engine import GoalEngine

    other = GoalEngine()
    other.train(m[m["date"] < pd.Timestamp("2026-02-15")])
    ctl.goal_engine = other  # sinyal gelmeden önce bile _record eski durumu reddeder
    page._record()
    assert len(ctl.ledger.predictions()) == n0 and page._current is None and not page.btn_record.isEnabled()
    page.cb_fixture.setCurrentIndex(2)
    ctl.goal_engine = None
    page._record()  # model yok: istisna yok, kayıt yok
    assert len(ctl.ledger.predictions()) == n0
    ctl.goal_engine = eng
    ctl.goalModelChanged.emit()
    assert page._current is None and not page.btn_record.isEnabled()
    # Gün değişimi + fikstür yok: sonsuz yeniden değerlendirme döngüsü yok
    saved_fx = ctl.store.fixtures
    ctl.store.fixtures = ctl.store.fixtures.iloc[0:0]
    ctl._goal_day = (AS_OF - dt.timedelta(days=1)).date()
    ctl.goalModelChanged.emit()
    assert ctl._goal_day == ctl.today() and ctl.goal_verdicts == []
    ctl.store.fixtures = saved_fx
    ctl.goal_verdicts = gated_goal_predictions(eng, ctx, fx, AS_OF)
    # Bağlamsız (uygunluğu değerlendirilmemiş) maç: olasılık yok, neden metni var, en sona sıralanır
    blocked = gated_goal_predictions(eng, None, fx.iloc[[0]].assign(home=teams[8], away=teams[9]), AS_OF)
    ctl.goal_verdicts = ctl.goal_verdicts + blocked
    page.cb_mode.setCurrentIndex(0)
    page.refresh_scan()
    last = page.scan_model.frame.iloc[-1]
    assert last["A"] != last["A"] and last["data"].startswith("Doğrulanamıyor") and "BAGLAM_YOK" in last["neden"]
    page.refresh_coverage()
    # S4-PILOT-01: kaynak kaydına pilotun sonuç kaynağı eklendi (5. satır); ana uygulamada kullanılmadığı açıkça yazar.
    # S5-GITHUB-01: iki arşiv kaynağı eklendi (6. ve 7. satır); yalnızca ayrı GitHub arşivinde kullanıldıkları yazar.
    # KAYNAK-04: ESPN eklendi (8. satır); onay gerektirir ve onay yoksa bunu yazar.
    assert page.cov_model.rowCount() > 0 and page.src_model.rowCount() == 8
    status = dict(zip(page.src_model.frame["Kaynak"], page.src_model.frame["Durum"]))
    assert status["ESPN skor tablosu (resmi olmayan uç nokta)"] == "ONAY YOK"
    assert status["openfootball/football.json (maç sonuçları; S4 pilotu)"].startswith("S4 pilotu ve eksik dönemin")
    assert status["datasets/football-datasets (GitHub; Premier League sezon CSV'leri)"].startswith("Yalnızca GitHub arşivi")
    assert status["StatsBomb açık verisi (hudl/open-data)"].startswith("Yalnızca GitHub arşivi")
    assert status["The Odds API"] == "Entegre edilmedi" and status["openfootball/football.json"] == "Onay gerekmez"


def test_sequences_page_historical_view(app, window):
    from bahis_tahmin.sequences.synthetic import synthetic_matches
    from bahis_tahmin.ui.pages.sequences import SequencesPage

    m, _ = synthetic_matches(n_leagues=1, n_seasons=8, n_teams=8, seed=2)
    ctl = window.ctl
    ctl.store.matches = m
    ctl.seq_table = None
    ctl.ensure_sequence_table()
    ctl.wait()
    app.processEvents()
    for _ in range(50):
        if ctl.seq_table is not None:
            break
        app.processEvents()
    page = window.page(SequencesPage)
    assert ctl.seq_table is not None
    page.refresh_all()
    assert page.cb_team.count() == 8
    assert not page.rb_all.isEnabled() and "DATA_QUALITY_BLOCKED" in page.rb_all.toolTip()
    page.cb_target.setCurrentIndex(0)  # İY geride → MS galip
    page.refresh_events()
    if page.ev_model.rowCount():
        page._show_card(page.ev_proxy.index(0, 0))
        assert "Kaynak" in page.card_event.toPlainText()
        assert page.card_models["POST_EVENT"][0].text()  # pencere durumları yazılı
    # Araştırma sonucu yoksa örnek/uydurma sonuç gösterilmez
    assert page.pat_model.rowCount() == 0 and "çalıştırılmadı" in page.pat_text.text()
    assert "DATA_QUALITY_BLOCKED" in page.meth_text.toPlainText()


def test_sequences_prematch_view_has_no_post_event(app, window):
    """Maç öncesi sekmesi: yalnızca karar anından önceki koşullar; olay sonrası alan yok; başarısız örnekler gösterilir."""
    from bahis_tahmin.sequences.synthetic import synthetic_matches
    from bahis_tahmin.ui.pages.sequences import SequencesPage

    m, _ = synthetic_matches(n_leagues=1, n_seasons=8, n_teams=8, seed=4)  # YALNIZCA TEST verisi
    cut = m["date"].max() - pd.Timedelta(days=14)
    ctl = window.ctl
    ctl.store.matches = m[m["date"] <= cut].reset_index(drop=True)
    fx = m[m["date"] > cut][["league", "date", "time", "home", "away", "source"]].copy()
    ctl.store.fixtures = fx.reindex(columns=ctl.store.fixtures.columns)
    ctl.prematch = None
    ctl.ensure_prematch()
    ctl.wait()
    for _ in range(50):
        if ctl.prematch is not None:
            break
        app.processEvents()
    assert ctl.prematch is not None
    page = window.page(SequencesPage)
    page._fill_fixtures()
    assert page.cb_fixture.count() == 8  # her takımın bir sonraki maçı
    shown = False
    for i in range(page.cb_fixture.count()):
        page.cb_fixture.setCurrentIndex(i)
        page.refresh_prematch()
        assert "POST_EVENT" not in page.sim_text.text()
        if page.sim_model.rowCount():
            df = page.sim_model.frame
            assert (df["n_gecmis"] == df["isabet"] + df["iska"]).all()
            k = int(df["iska"].to_numpy().argmax())
            page._show_examples(page.sim_proxy.mapFromSource(page.sim_model.index(k, 0)))
            ex = page.sim_ex_model.frame
            if df["iska"].iloc[k] > 0:
                assert "gerçekleşmedi" in set(ex["sonuc"])
            shown = True
    assert shown


def test_sequences_page_renders_frozen_research_results(app, window):
    """Araştırma kaydı (YALNIZCA sentetik test verisiyle üretilmiş) sayfada: tüm hipotezler ve aile özetleri görünür."""
    import sys

    from bahis_tahmin.sequences import research as RS
    from bahis_tahmin.sequences.synthetic import synthetic_matches
    from bahis_tahmin.ui.controller import SEQ_DIR, load_sequence_results
    from bahis_tahmin.ui.pages.sequences import SequencesPage

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_seq_research import _s0_table

    m, probs = synthetic_matches(n_leagues=1, n_seasons=27, n_teams=12, seed=21)
    ctl = window.ctl
    out = ctl.home / SEQ_DIR
    RS.run_research(m, out, s0=_s0_table(m, probs), R=5, placebo_seeds=1, R_placebo=3, record=True,
                    experiments_path=out / "deneyler.jsonl", families=("F1", "F2", "F4", "F7"))
    ctl.seq_results = load_sequence_results(ctl.home)
    page = window.page(SequencesPage)
    page.refresh_research()
    res = ctl.seq_results
    if res.get("hipotez_tekil"):
        assert page.pat_model.rowCount() == res["hipotez_tekil"]  # başarısızlar dahil hepsi listelenir
    html = page.pat_card.toPlainText()
    assert "Deney aileleri" in html and "F7" in html and "Plasebo" in html
    assert "şike olasılığı" not in html.lower()

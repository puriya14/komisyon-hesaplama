"""Arayüz duman testleri (ekransız / offscreen)."""

import os
import sys

import pandas as pd
import pytest

if sys.platform != "win32" and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


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
    fx["date"] = pd.Timestamp.today().normalize()
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
    for row in range(window.nav.count()):
        window.nav.setCurrentRow(row)
        app.processEvents()
        assert window.stack.currentIndex() == row


def test_predictions_table_and_dialog(app, window):
    from bahis_tahmin.ui.match_view import MatchDialog
    from bahis_tahmin.ui.pages.predictions import PredictionsPage

    page = window.page(PredictionsPage)
    assert page.model.rowCount() == 5
    dlg = MatchDialog(window.ctl, window.ctl.predictions[0])
    assert dlg.detail.mk_model.rowCount() == 14
    dlg.close()


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
    if bk.model.rowCount():
        from PySide6.QtCore import Qt

        bk.model.setData(bk.model.index(0, 0), Qt.Checked, Qt.CheckStateRole)
        assert "maç" in bk.kupon.text()


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
    from bahis_tahmin.selftest import synthetic_matches

    m = synthetic_matches(n_seasons=8, n_teams=16, seed=1, half_time=True)
    eng = GoalEngine()
    eng.train(m)
    return m, eng


def test_goals_page(app, window, goal_setup):
    from bahis_tahmin.ui.pages.goals import GoalsPage

    m, eng = goal_setup
    ctl = window.ctl
    ctl.store.matches = m
    fx = m.tail(4)[["league", "date", "time", "home", "away", "source"]].copy()
    fx["date"] = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
    ctl.goal_engine = eng
    ctl.goal_predictions = eng.predict_fixtures(fx)
    ctl.goalModelChanged.emit()
    page = window.page(GoalsPage)
    assert page.scan_model.rowCount() == 4
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
    assert page.led_model.rowCount() == 6
    page.refresh_coverage()
    assert page.cov_model.rowCount() > 0 and page.src_model.rowCount() == 4

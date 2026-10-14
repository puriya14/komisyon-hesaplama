"""Takım güç sıralaması ve puan durumu."""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget

from ...analysis import standings
from ...data.leagues import LEAGUES, league_name
from .. import theme
from ..charts import ChartCanvas, plot_ratings
from ..widgets import DataFrameModel, fmt_num, make_table, section
from .base import Page

AVRUPA = "@avrupa"  # KUPA-01: ligler arası ortak ölçek
CUP_NOTE = ("Bütün lig ve kupa maçlarından kurulan ortak model: farklı liglerin takımları aynı ölçektedir. Hücum ve "
            "savunma, bütün takımların ortalamasına göre log-gol ölçeğindedir (0 = ortalama). \"Gol farkı\": ortalama "
            "bir takıma karşı tarafsız sahada beklenen gol farkı (90 dk). Ligin değeri, son 365 günde maçı olan "
            "takımlarının ortalamasıdır.")


class RatingsPage(Page):
    title = "Güç Sıralaması ve Puan Durumu"
    subtitle = "Elo puanı, beklenen gol gücü, piyasa reytingi ve güncel puan tablosu."

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Lig:"))
        self.cb_league = QComboBox()
        self.cb_league.setMinimumWidth(240)
        bar.addWidget(self.cb_league)
        self.lbl_season = QLabel("Sezon:")
        bar.addWidget(self.lbl_season)
        self.cb_season = QComboBox()
        bar.addWidget(self.cb_season)
        bar.addStretch(1)
        self.body.addLayout(bar)

        tabs = QTabWidget()
        self.r_model = DataFrameModel()
        self.r_model.headers = {
            "team": "Takım", "elo": "Elo", "attack": "Hücum", "defense": "Savunma", "xg_for": "Attığı (beklenen)",
            "xg_against": "Yediği (beklenen)", "xg_diff": "Fark", "market": "Piyasa reytingi", "form": "Son 5",
        }
        self.r_model.formatters = {
            "elo": lambda v: fmt_num(v, 0), "attack": fmt_num, "defense": fmt_num, "xg_for": fmt_num,
            "xg_against": fmt_num, "xg_diff": lambda v: f"{v:+.2f}" if v == v else "-", "market": fmt_num,
        }
        self.r_model.backgrounds = {"xg_diff": lambda v, r: theme.ev_color(float(v) / 4) if v == v else None}
        r_view, _ = make_table(self.r_model)
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        l1.addWidget(r_view)
        self.chart = ChartCanvas(7, 4.5)
        self.chart.setMinimumHeight(420)
        l1.addWidget(self.chart)
        tabs.addTab(w1, "Güç sıralaması")

        self.s_model = DataFrameModel()
        self.s_model.headers = {"O": "O", "G": "G", "B": "B", "M": "M", "AG": "AG", "YG": "YG", "AV": "AV", "P": "Puan"}
        s_view, _ = make_table(self.s_model)
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        l2.addWidget(s_view)
        note = QLabel("O: oynanan · G/B/M: galibiyet/beraberlik/mağlubiyet · AG/YG: atılan/yenilen gol · AV: averaj")
        note.setObjectName("muted")
        l2.addWidget(note)
        tabs.addTab(w2, "Puan durumu")
        tabs.setMinimumHeight(900)
        self.tabs = tabs
        self.body.addWidget(tabs)

        # KUPA-01: ligler arası ortak ölçek (kupa modeli) — liglerin ve takımların gücü
        self.cup_box = QWidget()
        cl = QVBoxLayout(self.cup_box)
        cl.setContentsMargins(0, 0, 0, 0)
        self.cup_note = QLabel(CUP_NOTE)
        self.cup_note.setObjectName("muted")
        self.cup_note.setWordWrap(True)
        cl.addWidget(self.cup_note)
        signed = lambda v: f"{v:+.2f}" if v == v else "-"  # noqa: E731
        gd_bg = {"Gol farkı": lambda v, r: theme.ev_color(float(v) / 4) if v == v else None}
        cl.addWidget(section("Liglerin gücü"))
        self.cl_model = DataFrameModel()
        self.cl_model.hidden = {"lig", "Güç"}
        self.cl_model.headers = {"Takım": "Takım sayısı (son 365 gün)"}
        self.cl_model.formatters = {"Hücum": signed, "Savunma": signed, "Gol farkı": signed}
        self.cl_model.backgrounds = gd_bg
        cl_view, _ = make_table(self.cl_model)
        cl_view.setMinimumHeight(360)
        cl.addWidget(cl_view)
        cl.addWidget(section("En güçlü takımlar"))
        self.ct_model = DataFrameModel()
        self.ct_model.hidden = {"anahtar", "Güç"}
        self.ct_model.formatters = {"Hücum": signed, "Savunma": signed, "Gol farkı": signed}
        self.ct_model.backgrounds = gd_bg
        ct_view, _ = make_table(self.ct_model)
        ct_view.setMinimumHeight(600)
        cl.addWidget(ct_view)
        self.cup_box.hide()
        self.body.addWidget(self.cup_box)

        self.cb_league.currentIndexChanged.connect(self._league_changed)
        self.cb_season.currentIndexChanged.connect(self._fill_standings)
        controller.modelChanged.connect(self._fill_leagues)
        controller.dataChanged.connect(self._fill_leagues)
        self._fill_leagues()

    def _fill_leagues(self) -> None:
        cur = self.cb_league.currentData() or "T1"
        self.cb_league.blockSignals(True)
        self.cb_league.clear()
        present = set(self.ctl.store.matches["league"].unique()) if self.ctl.store.has_data else set()
        self.cb_league.addItem("Avrupa (ligler arası ortak ölçek)", AVRUPA)
        for code in [c for c in LEAGUES if c in present]:
            self.cb_league.addItem(league_name(code), code)
        i = self.cb_league.findData(cur)
        if i < 0:
            i = self.cb_league.findData("T1")
        self.cb_league.setCurrentIndex(max(i, 0))
        self.cb_league.blockSignals(False)
        self._league_changed()

    def _league_changed(self) -> None:
        lg = self.cb_league.currentData()
        avrupa = lg == AVRUPA
        self.tabs.setVisible(not avrupa)
        self.cup_box.setVisible(avrupa)
        self.cb_season.setVisible(not avrupa)
        self.lbl_season.setVisible(not avrupa)
        if avrupa:
            self._fill_cup()
            return
        eng = self.ctl.engine
        df = eng.ratings(lg) if (eng is not None and lg) else None
        if df is not None and not df.empty:
            df.insert(0, "#", range(1, len(df) + 1))
            self.r_model.set_frame(df)
            plot_ratings(self.chart, df)
        else:
            self.r_model.set_frame(df if df is not None else None)
        self.cb_season.blockSignals(True)
        self.cb_season.clear()
        if lg and self.ctl.store.has_data:
            seasons = sorted(self.ctl.store.league_matches(lg)["season"].unique(), reverse=True)
            self.cb_season.addItems([str(s) for s in seasons])
        self.cb_season.blockSignals(False)
        self._fill_standings()

    def _fill_cup(self) -> None:
        cup = getattr(self.ctl, "cup_engine", None)
        if cup is None or not cup.trained:
            self.cup_note.setText("Kupa modeli henüz eğitilmedi. Veri sayfasında kupa turnuvalarını seçip verileri "
                                  "güncelleyin.")
            self.cl_model.set_frame(pd.DataFrame())
            self.ct_model.set_frame(pd.DataFrame())
            return
        self.cup_note.setText(CUP_NOTE)
        lt = cup.league_table()
        tt = cup.team_table(60)
        if not lt.empty:
            lt = lt[["lig", "Lig", "Hücum", "Savunma", "Gol farkı", "Takım"]]
            lt.insert(0, "#", range(1, len(lt) + 1))
        if not tt.empty:
            tt.insert(0, "#", range(1, len(tt) + 1))
        self.cl_model.set_frame(lt)
        self.ct_model.set_frame(tt)

    def _fill_standings(self) -> None:
        lg = self.cb_league.currentData()
        if lg == AVRUPA:
            return
        season = self.cb_season.currentText() or None
        if lg and self.ctl.store.has_data:
            self.s_model.set_frame(standings(self.ctl.store.matches, lg, season))

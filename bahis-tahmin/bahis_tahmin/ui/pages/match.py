"""Maç analizi: lig ve takımları seçip (isteğe bağlı kendi oranlarınızla) ayrıntılı tahmin."""

from __future__ import annotations

import datetime as dt

import pandas as pd
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ...data.leagues import LEAGUES, league_name
from ...models.engine import ODDS_SETS, _odds_dict
from ...models.markets import MARKETS
from ..match_view import MatchDetail
from ..widgets import banner
from .base import Page


class MatchPage(Page):
    title = "Maç Analizi"
    subtitle = "İstediğiniz iki takımı seçin; isterseniz bahis şirketinizin oranlarını girerek değer hesaplayın."

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        top = QHBoxLayout()
        form = QGroupBox("Maç")
        fl = QGridLayout(form)
        self.cb_league = QComboBox()
        self.cb_home = QComboBox()
        self.cb_away = QComboBox()
        self.dt = QDateEdit(QDate.currentDate())
        self.dt.setCalendarPopup(True)
        self.dt.setDisplayFormat("dd.MM.yyyy")
        for w in (self.cb_league, self.cb_home, self.cb_away):
            w.setMinimumWidth(220)
        fl.addWidget(QLabel("Lig"), 0, 0)
        fl.addWidget(self.cb_league, 0, 1)
        fl.addWidget(QLabel("Ev sahibi"), 1, 0)
        fl.addWidget(self.cb_home, 1, 1)
        fl.addWidget(QLabel("Deplasman"), 2, 0)
        fl.addWidget(self.cb_away, 2, 1)
        fl.addWidget(QLabel("Tarih"), 3, 0)
        fl.addWidget(self.dt, 3, 1)
        self.btn = QPushButton("Analiz Et")
        self.btn.setObjectName("primary")
        fl.addWidget(self.btn, 4, 0, 1, 2)
        top.addWidget(form, 1)

        odds_box = QGroupBox("Oranlarınız (isteğe bağlı, boş = 0)")
        ol = QGridLayout(odds_box)
        self.odds: dict[str, QDoubleSpinBox] = {}
        for i, (key, (label, _)) in enumerate(MARKETS.items()):
            sp = QDoubleSpinBox()
            sp.setRange(0.0, 100.0)
            sp.setDecimals(2)
            sp.setSingleStep(0.05)
            sp.setSpecialValueText("–")
            self.odds[key] = sp
            ol.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            ol.addWidget(sp, i // 2, (i % 2) * 2 + 1)
        self.chk_market = QCheckBox("Girdiğim 1X2 ve 2.5 oranlarını piyasa bilgisi olarak da kullan (önerilir)")
        self.chk_market.setChecked(True)
        self.chk_market.setToolTip(
            "Açıkken oranlarınız, modelin olasılıklarını düzeltmek için de kullanılır (daha isabetli). "
            "Kapalıyken olasılıklar yalnızca modelden gelir."
        )
        ol.addWidget(self.chk_market, 8, 0, 1, 4)
        btn_clear = QPushButton("Oranları temizle")
        btn_clear.clicked.connect(lambda: [sp.setValue(0) for sp in self.odds.values()])
        ol.addWidget(btn_clear, 9, 0, 1, 2)
        top.addWidget(odds_box, 2)
        self.body.addLayout(top)

        self.info = banner("")
        self.info.hide()
        self.body.addWidget(self.info)
        self.detail = MatchDetail(controller)
        self.detail.hide()
        self.body.addWidget(self.detail)
        self.body.addStretch(1)

        self.cb_league.currentIndexChanged.connect(self._fill_teams)
        self.cb_home.currentIndexChanged.connect(self._autofill)
        self.cb_away.currentIndexChanged.connect(self._autofill)
        self.btn.clicked.connect(self.analyze)
        controller.modelChanged.connect(self._fill_leagues)
        self._fill_leagues()

    def _fill_leagues(self) -> None:
        eng = self.ctl.engine
        cur = self.cb_league.currentData()
        self.cb_league.blockSignals(True)
        self.cb_league.clear()
        if eng is not None and eng.trained:
            for code in [c for c in LEAGUES if c in eng.states]:
                self.cb_league.addItem(league_name(code), code)
        i = self.cb_league.findData(cur) if cur else self.cb_league.findData("T1")
        self.cb_league.setCurrentIndex(max(i, 0))
        self.cb_league.blockSignals(False)
        self._fill_teams()
        self.btn.setEnabled(self.cb_league.count() > 0)

    def _fill_teams(self) -> None:
        eng = self.ctl.engine
        lg = self.cb_league.currentData()
        teams = eng.teams(lg) if (eng is not None and lg) else []
        for cb in (self.cb_home, self.cb_away):
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(teams)
            cb.blockSignals(False)
        if len(teams) > 1:
            self.cb_away.setCurrentIndex(1)
        self._autofill()

    def _fixture_row(self):
        fx = self.ctl.store.fixtures
        if fx is None or fx.empty:
            return None
        m = fx[(fx["league"] == self.cb_league.currentData()) & (fx["home"] == self.cb_home.currentText())
               & (fx["away"] == self.cb_away.currentText())]
        return None if m.empty else m.iloc[0]

    def _autofill(self) -> None:
        row = self._fixture_row()
        if row is None:
            return
        d = row["date"]
        self.dt.setDate(QDate(d.year, d.month, d.day))
        offered = _odds_dict(row.to_dict(), ODDS_SETS.get(self.ctl.settings.odds_type, ODDS_SETS["avg"]))
        for k, v in offered.items():
            if v == v:
                self.odds[k].setValue(v)

    def analyze(self) -> None:
        eng = self.ctl.engine
        if eng is None or not eng.trained:
            return
        lg = self.cb_league.currentData()
        home, away = self.cb_home.currentText(), self.cb_away.currentText()
        if not home or not away or home == away:
            self.info.setText("Lütfen iki farklı takım seçin.")
            self.info.show()
            return
        qd = self.dt.date()
        date = dt.date(qd.year(), qd.month(), qd.day())
        user = {k: sp.value() for k, sp in self.odds.items() if sp.value() > 1.0}
        row = self._fixture_row()
        notes = []
        if row is not None:
            market = {k: v for k, v in _odds_dict(row.to_dict(), ODDS_SETS["avg"]).items() if v == v}
            notes.append("Bu maç fikstürde bulundu; piyasa ortalaması oranlar olasılıklara dahil edildi.")
        elif self.chk_market.isChecked():
            market = {k: v for k, v in user.items() if k in ("1", "X", "2", "O2.5", "U2.5")}
            if market:
                notes.append("Girdiğiniz oranlar piyasa bilgisi olarak kullanıldı.")
        else:
            market = {}
        offered = user if user else (market if market else {})
        p = eng.predict_match(lg, home, away, pd.Timestamp(date), "", market, offered, source="manuel")
        # Elle seçilen maç da ortak veri uygunluk kontrolünden geçer (bağlam yoksa sonuç uygun değildir)
        from ...eligibility import gate_match_prediction

        gate_match_prediction(self.ctl.eligibility_context(eng), p, self.ctl.now())
        self.info.setText(" ".join(notes))
        self.info.setVisible(bool(notes))
        self.detail.show_prediction(p)
        self.detail.show()

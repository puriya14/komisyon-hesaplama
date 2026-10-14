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
from ...kupa.turnuvalar import COMPETITIONS
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
        self.cb_mode = QComboBox()  # KUPA-01: lig maçı / ligler arası (kupa) maçı
        self.cb_mode.addItem("Lig maçı", "lig")
        self.cb_mode.addItem("Ligler arası / kupa maçı", "kupa")
        self.cb_mode.setToolTip("Ligler arası: takımlar farklı liglerden olabilir (ör. Avrupa kupası maçı). "
                                "Olasılıklar bütün lig ve kupa maçlarından kurulan ortak modelden gelir.")
        self.cb_league = QComboBox()
        self.cb_home = QComboBox()
        self.cb_away = QComboBox()
        self.dt = QDateEdit(QDate.currentDate())
        self.dt.setCalendarPopup(True)
        self.dt.setDisplayFormat("dd.MM.yyyy")
        for w in (self.cb_mode, self.cb_league, self.cb_home, self.cb_away):
            w.setMinimumWidth(220)
        self.lbl_league = QLabel("Lig")
        fl.addWidget(QLabel("Maç türü"), 0, 0)
        fl.addWidget(self.cb_mode, 0, 1)
        fl.addWidget(self.lbl_league, 1, 0)
        fl.addWidget(self.cb_league, 1, 1)
        fl.addWidget(QLabel("Ev sahibi"), 2, 0)
        fl.addWidget(self.cb_home, 2, 1)
        fl.addWidget(QLabel("Deplasman"), 3, 0)
        fl.addWidget(self.cb_away, 3, 1)
        fl.addWidget(QLabel("Tarih"), 4, 0)
        fl.addWidget(self.dt, 4, 1)
        self.chk_neutral = QCheckBox("Tarafsız saha (final, süper kupa)")
        self.chk_neutral.hide()
        fl.addWidget(self.chk_neutral, 5, 0, 1, 2)
        self.btn = QPushButton("Analiz Et")
        self.btn.setObjectName("primary")
        fl.addWidget(self.btn, 6, 0, 1, 2)
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

        self.cb_mode.currentIndexChanged.connect(self._fill_leagues)
        self.cb_league.currentIndexChanged.connect(self._fill_teams)
        self.cb_home.currentIndexChanged.connect(self._autofill)
        self.cb_away.currentIndexChanged.connect(self._autofill)
        self.btn.clicked.connect(self.analyze)
        controller.modelChanged.connect(self._fill_leagues)
        self._fill_leagues()

    def _cup_mode(self) -> bool:
        return self.cb_mode.currentData() == "kupa"

    def _cup_engine(self):
        eng = getattr(self.ctl, "cup_engine", None)
        return eng if (eng is not None and eng.trained) else None

    def _fill_leagues(self) -> None:
        cup = self._cup_mode()
        self.lbl_league.setText("Turnuva" if cup else "Lig")
        self.chk_neutral.setVisible(cup)
        self.chk_market.setVisible(not cup)
        eng = self.ctl.engine
        cur = self.cb_league.currentData()
        self.cb_league.blockSignals(True)
        self.cb_league.clear()
        if cup:
            for code, c in COMPETITIONS.items():
                self.cb_league.addItem(c.full, code)
            default = "UCL"
        else:
            if eng is not None and eng.trained:
                for code in [c for c in LEAGUES if c in eng.states]:
                    self.cb_league.addItem(league_name(code), code)
            default = "T1"
        i = self.cb_league.findData(cur) if cur else -1
        self.cb_league.setCurrentIndex(max(i if i >= 0 else self.cb_league.findData(default), 0))
        self.cb_league.blockSignals(False)
        self._fill_teams()
        ok = (self._cup_engine() is not None) if cup else self.cb_league.count() > 0
        self.btn.setEnabled(ok)
        if cup and not ok:
            self.info.setText("Ligler arası (kupa) modeli henüz eğitilmedi: Veri sayfasında kupaları seçip "
                              "güncelleyin ve eğitin.")
            self.info.show()
        elif not cup:
            self.info.hide()

    def _fill_teams(self) -> None:
        if self._cup_mode():
            self._fill_cup_teams()
            return
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

    def _fill_cup_teams(self) -> None:
        """Takımlar lige göre gruplu (grup başlıkları seçilemez); veri = kupa modelindeki takım anahtarı."""
        from ...kupa import gorunum

        groups = gorunum.teams_for_analysis(self._cup_engine())
        prev = (self.cb_home.currentData(), self.cb_away.currentData())
        for cb in (self.cb_home, self.cb_away):
            cb.blockSignals(True)
            cb.clear()
            for title, teams in groups:
                cb.addItem(f"— {title} —", None)
                item = cb.model().item(cb.count() - 1)
                if item is not None:
                    item.setEnabled(False)
                for key, name in teams:
                    cb.addItem(name, key)
            cb.blockSignals(False)
        keys = [self.cb_home.itemData(i) for i in range(self.cb_home.count()) if self.cb_home.itemData(i)]
        for cb, want, fallback in ((self.cb_home, prev[0], 0), (self.cb_away, prev[1], 1)):
            i = cb.findData(want) if want else -1
            if i < 0 and len(keys) > fallback:
                i = cb.findData(keys[fallback])
            cb.setCurrentIndex(max(i, 0))
        self._autofill()

    def _cup_fixture_row(self):
        fx = getattr(self.ctl.store, "cup_fixtures", None)
        if fx is None or fx.empty:
            return None
        m = fx[(fx["comp"] == self.cb_league.currentData()) & (fx["home_key"] == self.cb_home.currentData())
               & (fx["away_key"] == self.cb_away.currentData())]
        return None if m.empty else m.sort_values("date").iloc[0]

    def _fixture_row(self):
        fx = self.ctl.store.fixtures
        if fx is None or fx.empty:
            return None
        m = fx[(fx["league"] == self.cb_league.currentData()) & (fx["home"] == self.cb_home.currentText())
               & (fx["away"] == self.cb_away.currentText())]
        return None if m.empty else m.iloc[0]

    def _autofill(self) -> None:
        if self._cup_mode():
            row = self._cup_fixture_row()
            if row is not None:
                d = row["date"]
                self.dt.setDate(QDate(d.year, d.month, d.day))
                self.chk_neutral.setChecked(bool(row.get("neutral")))
            return
        row = self._fixture_row()
        if row is None:
            return
        d = row["date"]
        self.dt.setDate(QDate(d.year, d.month, d.day))
        offered = _odds_dict(row.to_dict(), ODDS_SETS.get(self.ctl.settings.odds_type, ODDS_SETS["avg"]))
        for k, v in offered.items():
            if v == v:
                self.odds[k].setValue(v)

    def _analyze_cup(self) -> None:
        from ...kupa import gorunum

        eng = self._cup_engine()
        if eng is None:
            return
        comp = self.cb_league.currentData()
        hk, ak = self.cb_home.currentData(), self.cb_away.currentData()
        if not hk or not ak or hk == ak:
            self.info.setText("Lütfen iki farklı takım seçin.")
            self.info.show()
            return
        qd = self.dt.date()
        date = dt.date(qd.year(), qd.month(), qd.day())
        user = {k: sp.value() for k, sp in self.odds.items() if sp.value() > 1.0}
        names = {hk: self.cb_home.currentText(), ak: self.cb_away.currentText()}
        main = self.ctl.engine if (self.ctl.engine is not None and self.ctl.engine.trained) else None
        p = gorunum.analyze(eng, self.ctl.store, self.ctl.eligibility_context(main), self.ctl.settings, comp=comp,
                            home_key=hk, away_key=ak, names=names, date=date, neutral=self.chk_neutral.isChecked(),
                            offered=user, as_of=self.ctl.now())
        if p is None:
            self.info.setText("Takımlardan biri kupa modelinde yok.")
            self.info.show()
            self.detail.hide()
            return
        self.info.setText("Kupa maçları için veri setinde piyasa oranı yok; girdiğiniz oranlar yalnızca değer "
                          "hesabında kullanılır." if user else "")
        self.info.setVisible(bool(user))
        self.detail.show_prediction(p)
        self.detail.show()

    def analyze(self) -> None:
        if self._cup_mode():
            self._analyze_cup()
            return
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

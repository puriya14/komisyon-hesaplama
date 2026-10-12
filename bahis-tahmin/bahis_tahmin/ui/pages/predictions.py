"""Yaklaşan maçlar ve tahminler."""

from __future__ import annotations

import datetime as dt

import pandas as pd
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit

from ...data.leagues import LEAGUES, league_name
from ...models.engine import ODDS_TYPE_LABELS
from .. import theme
from ..match_view import MatchDialog
from ..widgets import DataFrameModel, banner, fmt_pct, make_table
from .base import Page

DATE_FILTERS = [("Tümü", None), ("Bugün", 0), ("Bugün + yarın", 1), ("3 gün", 2), ("7 gün", 6)]


class PredictionsPage(Page):
    title = "Tahminler"
    subtitle = "Yaklaşan maçlar için model olasılıkları. Ayrıntı için satıra çift tıklayın."

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        filters = QHBoxLayout()
        self.cb_league = QComboBox()
        self.cb_league.setMinimumWidth(220)
        self.cb_date = QComboBox()
        for label, _ in DATE_FILTERS:
            self.cb_date.addItem(label)
        self.chk_value = QCheckBox("Yalnızca değerli bahisler")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Takım ara...")
        self.search.setClearButtonEnabled(True)
        for w in (QLabel("Lig:"), self.cb_league, QLabel("Tarih:"), self.cb_date, self.chk_value):
            filters.addWidget(w)
        filters.addStretch(1)
        filters.addWidget(self.search)
        self.body.addLayout(filters)

        self.model = DataFrameModel()
        self.model.hidden = {"_i", "value_ev", "has_market", "date", "veri_neden"}
        self.model.headers = {
            "when": "Tarih", "league": "Lig", "home": "Ev sahibi", "away": "Deplasman",
            "p1": "1", "px": "X", "p2": "2", "pick": "Tahmin", "o25": "2.5 Üst", "btts": "KG Var",
            "xg": "Beklenen gol", "odds": "Oranlar 1/X/2", "value": "En iyi değer", "veri": "Veri durumu",
        }
        self.model.formatters = {
            "p1": fmt_pct, "px": fmt_pct, "p2": fmt_pct, "o25": fmt_pct, "btts": fmt_pct,
            "league": lambda v: LEAGUES[v].name if v in LEAGUES else v,
        }
        prob_bg = lambda v, r: theme.prob_color(float(v) * 0.9) if v == v else None  # noqa: E731
        self.model.backgrounds = {
            "p1": prob_bg, "px": prob_bg, "p2": prob_bg, "o25": prob_bg, "btts": prob_bg,
            "value": lambda v, r: theme.ev_color(r["value_ev"]) if v else None,
        }
        self.model.tooltips = {
            "league": lambda v, r: league_name(v),
            "odds": lambda v, r: "Piyasa oranlarıyla harmanlandı (ortalama; yedek veri setinde tek bahisçi)" if r["has_market"] else "Oran yok: yalnızca model",
            "veri": lambda v, r: r["veri_neden"],
        }
        self.view, self.proxy = make_table(self.model)
        self.view.setMinimumHeight(520)
        self.view.doubleClicked.connect(self._open)
        self.body.addWidget(self.view)
        self.footer = QLabel("")
        self.footer.setObjectName("muted")
        self.footer.setWordWrap(True)
        self.body.addWidget(self.footer)
        self.body.addWidget(banner(
            "<b>Değer (value) nedir?</b> Bir seçimin oranı, modelin hesapladığı adil orandan yüksekse beklenen "
            "kazanç pozitiftir. 'En iyi değer' sütunu, Ayarlar'da seçtiğiniz oran türüne göre hesaplanır. "
            "Kendi bahis şirketinizin oranı daha düşükse değer kaybolabilir: maç ayrıntısında her market için "
            "'Değer için min. oran' sütununa bakın."
        ))

        self.proxy.predicate = self._accept
        self.cb_league.currentIndexChanged.connect(self._refilter)
        self.cb_date.currentIndexChanged.connect(self._refilter)
        self.chk_value.toggled.connect(self._refilter)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        controller.predictionsChanged.connect(self.refresh)
        controller.settingsChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        if self.ctl.check_day():  # gün değişti: uygunluk yeniden değerlendirilir
            return  # yeniden değerlendirme sinyali bu sayfayı yeniden çizer
        df = self.ctl.prediction_frame()
        current = self.cb_league.currentData()
        self.cb_league.blockSignals(True)
        self.cb_league.clear()
        self.cb_league.addItem("Tüm ligler", None)
        if not df.empty:
            for code in [c for c in LEAGUES if c in set(df["league"])]:
                self.cb_league.addItem(league_name(code), code)
        idx = self.cb_league.findData(current)
        self.cb_league.setCurrentIndex(max(idx, 0))
        self.cb_league.blockSignals(False)
        self.model.set_frame(df)
        self._refilter()

    def _accept(self, row: int) -> bool:
        df = self.model.frame
        if df.empty:
            return True
        r = df.iloc[row]
        lg = self.cb_league.currentData()
        if lg and r["league"] != lg:
            return False
        days = DATE_FILTERS[self.cb_date.currentIndex()][1]
        if days is not None:
            limit = pd.Timestamp(dt.date.today() + dt.timedelta(days=days))
            if pd.Timestamp(r["date"]) > limit:
                return False
        if self.chk_value.isChecked() and not r["value"]:
            return False
        return True

    def _refilter(self) -> None:
        self.proxy.invalidateFilter()
        n = self.proxy.rowCount()
        total = self.model.rowCount()
        s = self.ctl.settings
        df = self.model.frame
        n_blocked = int((df["p1"].isna()).sum()) if not df.empty else 0
        n_warn = int(df["veri"].astype(str).str.startswith("Uyarılı").sum()) if not df.empty else 0
        self.footer.setText(
            f"{n} / {total} maç gösteriliyor · Değer hesabı: {ODDS_TYPE_LABELS.get(s.odds_type, s.odds_type)}, "
            f"en az %{100 * s.min_ev:.0f} beklenen değer, oran {s.min_odds:.2f}–{s.max_odds:.2f} · "
            f"tahmini gösterilemeyen {n_blocked} maç"
            + (f", uyarılı (bahis adayı olmayan) {n_warn} maç" if n_warn else "")
            + " (nedenleri Veri durumu sütununda)"
        )

    def _open(self, index) -> None:
        src = self.proxy.mapToSource(index)
        row = self.model.frame.iloc[src.row()]
        i = int(row["_i"])
        if i < 0:  # tahmini üretilemeyen fikstür: yalnızca neden gösterilir
            self.footer.setText(f"{row['home']} - {row['away']}: {row['veri_neden']}")
            return
        MatchDialog(self.ctl, self.ctl.predictions[i], self).exec()

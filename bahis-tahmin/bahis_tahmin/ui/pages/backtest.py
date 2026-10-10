"""Geriye dönük test sayfası."""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...betting.backtest import BacktestConfig, run_backtest
from ...data.leagues import LEAGUES, league_name
from ...models.engine import ODDS_TYPE_LABELS
from .. import theme
from ..charts import ChartCanvas, plot_calibration, plot_equity
from ..widgets import Card, DataFrameModel, banner, fmt_num, fmt_pct, fmt_signed_pct, make_table
from .base import Page


class BacktestPage(Page):
    title = "Geriye Dönük Test"
    subtitle = ("Model her sezonu, o sezonun maçlarını hiç görmeden tahmin etti. Burada bu tahminlerle bir bahis "
                "stratejisi uygulansaydı ne olacağını görürsünüz.")

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        top = QHBoxLayout()
        box = QGroupBox("Strateji")
        g = QGridLayout(box)
        self.cb_odds = QComboBox()
        for k, v in ODDS_TYPE_LABELS.items():
            self.cb_odds.addItem(v, k)
        self.cb_src = QComboBox()
        self.cb_src.addItem("Model + piyasa (nihai olasılık)", "final")
        self.cb_src.addItem("Yalnızca model", "model")
        self.chk_1x2 = QCheckBox("1X2")
        self.chk_1x2.setChecked(True)
        self.chk_ou = QCheckBox("2.5 Alt/Üst")
        self.chk_ou.setChecked(True)
        self.sp_ev = self._spin(0.0, 0.5, 0.05, 0.01)
        self.sp_prob = self._spin(0.0, 0.95, 0.15, 0.05)
        self.sp_min_odds = self._spin(1.01, 20, 1.3, 0.05)
        self.sp_max_odds = self._spin(1.05, 50, 8.0, 0.5)
        self.cb_stake = QComboBox()
        self.cb_stake.addItem("Sabit (kasanın %1'i)", "flat")
        self.cb_stake.addItem("Kelly (kesirli)", "kelly")
        self.sp_kelly = self._spin(0.05, 1.0, 0.25, 0.05)
        self.sp_bank = self._spin(10, 1e7, 1000, 100, decimals=0)
        rows = [
            ("Oran türü", self.cb_odds), ("Olasılık kaynağı", self.cb_src), ("Min. beklenen değer", self.sp_ev),
            ("Min. olasılık", self.sp_prob), ("Min. oran", self.sp_min_odds), ("Maks. oran", self.sp_max_odds),
            ("Bahis miktarı", self.cb_stake), ("Kelly kesri", self.sp_kelly), ("Başlangıç kasası", self.sp_bank),
        ]
        for i, (label, w) in enumerate(rows):
            g.addWidget(QLabel(label), i // 3, (i % 3) * 2)
            g.addWidget(w, i // 3, (i % 3) * 2 + 1)
        mk = QHBoxLayout()
        mk.addWidget(QLabel("Marketler:"))
        mk.addWidget(self.chk_1x2)
        mk.addWidget(self.chk_ou)
        mk.addStretch(1)
        g.addLayout(mk, 3, 0, 1, 6)
        top.addWidget(box, 3)

        side = QGroupBox("Ligler ve sezonlar")
        sl = QVBoxLayout(side)
        self.lst_leagues = QListWidget()
        self.lst_leagues.setObjectName("plain")
        self.lst_leagues.setMinimumHeight(120)
        self.lst_leagues.setMaximumHeight(170)
        self.lst_seasons = QListWidget()
        self.lst_seasons.setObjectName("plain")
        self.lst_seasons.setMinimumHeight(90)
        self.lst_seasons.setMaximumHeight(130)
        sl.addWidget(self.lst_leagues)
        sl.addWidget(self.lst_seasons)
        top.addWidget(side, 2)
        self.body.addLayout(top)

        btns = QHBoxLayout()
        self.btn_run = QPushButton("Testi Çalıştır")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self.run)
        btns.addWidget(self.btn_run)
        btns.addStretch(1)
        self.body.addLayout(btns)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.c_bets = Card("Bahis sayısı")
        self.c_hit = Card("İsabet")
        self.c_roi = Card("Getiri (ROI)")
        self.c_profit = Card("Kâr / zarar")
        self.c_dd = Card("En büyük düşüş")
        self.c_clv = Card("Kapanış oranına göre (CLV)")
        for i, c in enumerate((self.c_bets, self.c_hit, self.c_roi, self.c_profit, self.c_dd, self.c_clv)):
            grid.addWidget(c, i // 3, i % 3)
        self.body.addLayout(grid)
        self.verdict = banner("")
        self.verdict.hide()
        self.body.addWidget(self.verdict)

        charts = QHBoxLayout()
        self.ch_eq = ChartCanvas(6, 3.4)
        self.ch_cal = ChartCanvas(5, 3.4)
        self.ch_eq.setMinimumHeight(320)
        self.ch_cal.setMinimumHeight(320)
        charts.addWidget(self.ch_eq, 3)
        charts.addWidget(self.ch_cal, 2)
        holder = QWidget()
        holder.setLayout(charts)
        self.body.addWidget(holder)

        tabs = QTabWidget()
        self.m_season = self._table_model()
        self.m_league = self._table_model(league=True)
        self.m_market = self._table_model()
        self.m_quality = DataFrameModel()
        self.m_quality.headers = {
            "season": "Sezon", "n": "Maç", "acc_model_m": "Model isabeti", "acc_market": "Piyasa isabeti",
            "acc_final": "Nihai isabet", "ll_model": "Model log-kayıp", "ll_market": "Piyasa log-kayıp",
            "ll_final": "Nihai log-kayıp",
        }
        self.m_quality.formatters = {
            "acc_model_m": fmt_pct, "acc_market": fmt_pct, "acc_final": fmt_pct,
            "ll_model": lambda v: fmt_num(v, 4), "ll_market": lambda v: fmt_num(v, 4), "ll_final": lambda v: fmt_num(v, 4),
        }
        self.m_bets = DataFrameModel()
        self.m_bets.hidden = {"fold", "closing", "unit_profit"}
        self.m_bets.headers = {
            "date": "Tarih", "league": "Lig", "season": "Sezon", "home": "Ev", "away": "Deplasman", "fthg": "EG",
            "ftag": "DG", "market": "Market", "selection": "Seçim", "prob": "Olasılık", "odds": "Oran",
            "ev": "Beklenen değer", "won": "Sonuç", "stake": "Miktar", "profit": "Kâr", "bankroll": "Kasa",
        }
        self.m_bets.formatters = {
            "prob": fmt_pct, "odds": fmt_num, "ev": fmt_signed_pct, "won": lambda v: "Kazandı" if v else "Kaybetti",
            "stake": lambda v: fmt_num(v, 0), "profit": lambda v: f"{v:+,.0f}", "bankroll": lambda v: f"{v:,.0f}",
            "date": lambda v: pd.Timestamp(v).strftime("%d.%m.%Y"),
        }
        self.m_bets.backgrounds = {"won": lambda v, r: theme.ev_color(0.1 if v else -0.1)}
        for model, label in ((self.m_season, "Sezonlara göre"), (self.m_league, "Liglere göre"),
                             (self.m_market, "Marketlere göre"), (self.m_quality, "Model kalitesi"),
                             (self.m_bets, "Tüm bahisler")):
            view, _ = make_table(model)
            tabs.addTab(view, label)
        tabs.setMinimumHeight(380)
        self.body.addWidget(tabs)
        self.body.addWidget(banner(
            "<b>Nasıl okunur?</b> ROI pozitif olsa bile güven aralığı sıfırı içeriyorsa sonuç şans eseri olabilir. "
            "'En yüksek oran' seçeneği, onlarca bahis şirketi arasından en iyi oranı alabildiğinizi varsayar; "
            "gerçekte bu her zaman mümkün değildir. Geçmiş performans geleceği garanti etmez.", "warn"))
        self.body.addStretch(1)

        controller.modelChanged.connect(self._fill_lists)
        controller.settingsChanged.connect(self._load_settings)
        self._load_settings()
        self._fill_lists()

    @staticmethod
    def _spin(lo, hi, val, step, decimals=2) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(decimals)
        sp.setSingleStep(step)
        sp.setValue(val)
        return sp

    @staticmethod
    def _table_model(league: bool = False) -> DataFrameModel:
        m = DataFrameModel()
        m.headers = {"bahis": "Bahis", "kazanan": "Kazanan", "isabet": "İsabet", "ort_oran": "Ort. oran",
                     "yatırılan": "Yatırılan", "kâr": "Kâr", "roi": "ROI", "birim_roi": "Birim ROI",
                     "league": "Lig", "season": "Sezon", "market": "Market", "selection": "Seçim"}
        m.formatters = {"isabet": fmt_pct, "ort_oran": fmt_num, "yatırılan": lambda v: f"{v:,.0f}",
                        "kâr": lambda v: f"{v:+,.0f}", "roi": fmt_signed_pct, "birim_roi": fmt_signed_pct,
                        "bahis": lambda v: f"{v:.0f}", "kazanan": lambda v: f"{v:.0f}"}
        if league:
            m.formatters["league"] = league_name
        m.backgrounds = {"roi": lambda v, r: theme.ev_color(float(v)) if v == v else None}
        return m

    def _load_settings(self) -> None:
        s = self.ctl.settings
        i = self.cb_odds.findData(s.odds_type)
        self.cb_odds.setCurrentIndex(max(i, 0))
        self.sp_ev.setValue(s.min_ev)
        self.sp_prob.setValue(s.min_prob)
        self.sp_min_odds.setValue(s.min_odds)
        self.sp_max_odds.setValue(s.max_odds)
        self.sp_kelly.setValue(s.kelly_fraction)
        self.sp_bank.setValue(s.bankroll)

    def _fill_lists(self) -> None:
        eng = self.ctl.engine
        self.lst_leagues.clear()
        self.lst_seasons.clear()
        if eng is None or eng.oos is None or eng.oos.empty:
            self.btn_run.setEnabled(False)
            return
        self.btn_run.setEnabled(True)
        present = set(eng.oos["league"].unique())
        for code in [c for c in LEAGUES if c in present]:
            it = QListWidgetItem(league_name(code))
            it.setData(Qt.UserRole, code)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.lst_leagues.addItem(it)
        for y in sorted(eng.oos["fold"].unique()):
            it = QListWidgetItem(f"{y}/{(y + 1) % 100:02d}")
            it.setData(Qt.UserRole, int(y))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.lst_seasons.addItem(it)

    @staticmethod
    def _checked(lst: QListWidget) -> list:
        return [lst.item(i).data(Qt.UserRole) for i in range(lst.count()) if lst.item(i).checkState() == Qt.Checked]

    def run(self) -> None:
        eng = self.ctl.engine
        if eng is None or eng.oos is None or eng.oos.empty:
            return
        markets = tuple(m for m, cb in (("1X2", self.chk_1x2), ("OU25", self.chk_ou)) if cb.isChecked())
        cfg = BacktestConfig(
            leagues=self._checked(self.lst_leagues), seasons=self._checked(self.lst_seasons), markets=markets,
            odds_type=self.cb_odds.currentData(), prob_source=self.cb_src.currentData(), min_ev=self.sp_ev.value(),
            min_prob=self.sp_prob.value(), min_odds=self.sp_min_odds.value(), max_odds=self.sp_max_odds.value(),
            staking=self.cb_stake.currentData(), kelly_fraction=self.sp_kelly.value(),
            max_stake_pct=self.ctl.settings.max_stake_pct, bankroll=self.sp_bank.value(),
        )
        res = run_backtest(eng.oos, cfg)
        s = res.summary
        cur = self.ctl.settings.currency
        n = s.get("bahis", 0)
        self.c_bets.set(f"{n:,}".replace(",", "."), f"{s.get('kazanan', 0):,} kazanan".replace(",", ".") if n else "Bahis yok")
        if n:
            self.c_hit.set(fmt_pct(s["isabet"]), f"ortalama oran {fmt_num(s['ort_oran'])}")
            good = s["birim_roi"] > 0
            self.c_roi.set(fmt_signed_pct(s["birim_roi"]),
                           f"%95 güven aralığı: {fmt_signed_pct(s['roi_ci_low'])} … {fmt_signed_pct(s['roi_ci_high'])}",
                           color=theme.GOOD if good else theme.CRITICAL)
            self.c_profit.set(f"{s['kar']:+,.0f} {cur}", f"kasa {s['baslangic']:,.0f} → {s['bitis']:,.0f}",
                              color=theme.GOOD if s["kar"] > 0 else theme.CRITICAL)
            self.c_dd.set(fmt_pct(s["max_dusus"]), f"en uzun kayıp serisi: {s['en_uzun_kayip']}")
            if s.get("clv_n"):
                self.c_clv.set(fmt_signed_pct(s["clv"]), f"{s['clv_n']} bahiste kapanış oranı biliniyor")
            else:
                self.c_clv.set("-", "Kapanış oranı verisi yok")
            sig = s["p_value"] < 0.05 and s["birim_roi"] > 0
            self.verdict.setObjectName("banner" if sig else "warn")
            self.verdict.setStyleSheet("")
            self.verdict.setText(
                ("<b>İstatistiksel olarak anlamlı pozitif getiri</b> (p = %.3f). Yine de gerçek oranlara erişim ve "
                 "bahis limitleri sonucu değiştirebilir." % s["p_value"]) if sig else
                ("<b>Kanıt yetersiz:</b> bu stratejinin getirisi şanstan ayırt edilemiyor (p = %.2f). "
                 "Bahis şirketi marjı nedeniyle uzun vadede zarar beklenir." % s["p_value"])
            )
            self.verdict.show()
        else:
            for c in (self.c_hit, self.c_roi, self.c_profit, self.c_dd, self.c_clv):
                c.set("-", "")
            self.verdict.hide()
        plot_equity(self.ch_eq, res.bets, cfg.bankroll, cur)
        plot_calibration(self.ch_cal, res.calibration)
        self.m_season.set_frame(res.by_season)
        self.m_league.set_frame(res.by_league)
        self.m_market.set_frame(res.by_market)
        q = pd.DataFrame(eng.report.per_season) if eng.report else pd.DataFrame()
        if not q.empty:
            cols = [c for c in ("season", "n", "acc_model_m", "acc_market", "acc_final", "ll_model", "ll_market", "ll_final") if c in q]
            q = q[cols]
        self.m_quality.set_frame(q)
        self.m_bets.set_frame(res.bets)

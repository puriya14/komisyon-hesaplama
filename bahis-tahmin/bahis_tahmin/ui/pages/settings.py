"""Ayarlar sayfası."""

from __future__ import annotations

import copy

from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QLineEdit, QPushButton, QSpinBox

from ...models.engine import ODDS_TYPE_LABELS
from ..widgets import banner
from .base import Page


class SettingsPage(Page):
    title = "Ayarlar"
    subtitle = "Değer bahsi kuralları, kasa yönetimi ve uygulama davranışı."

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        g1 = QGroupBox("Değer (value) hesabı")
        f1 = QFormLayout(g1)
        self.cb_odds = QComboBox()
        for k, v in ODDS_TYPE_LABELS.items():
            self.cb_odds.addItem(v, k)
        self.cb_margin = QComboBox()
        self.cb_margin.addItem("Üs yöntemi (önerilen)", "power")
        self.cb_margin.addItem("Oransal", "proportional")
        self.sp_ev = self._dspin(0, 1, 0.01, "Bir seçimin 'değerli' sayılması için gereken en düşük beklenen kazanç")
        self.sp_prob = self._dspin(0, 0.99, 0.05)
        self.sp_min_odds = self._dspin(1.01, 50, 0.05)
        self.sp_max_odds = self._dspin(1.05, 100, 0.5)
        f1.addRow("Oran türü", self.cb_odds)
        f1.addRow("Marj temizleme yöntemi", self.cb_margin)
        f1.addRow("En düşük beklenen değer (0.05 = %5)", self.sp_ev)
        f1.addRow("En düşük olasılık", self.sp_prob)
        f1.addRow("En düşük oran", self.sp_min_odds)
        f1.addRow("En yüksek oran", self.sp_max_odds)
        self.body.addWidget(g1)

        g2 = QGroupBox("Kasa yönetimi")
        f2 = QFormLayout(g2)
        self.sp_bank = self._dspin(0, 1e9, 100, decimals=0)
        self.ed_cur = QLineEdit()
        self.ed_cur.setMaxLength(6)
        self.sp_kelly = self._dspin(0, 1, 0.05)
        self.sp_cap = self._dspin(0, 1, 0.01)
        f2.addRow("Kasa", self.sp_bank)
        f2.addRow("Para birimi", self.ed_cur)
        f2.addRow("Kelly kesri (0.25 = çeyrek Kelly)", self.sp_kelly)
        f2.addRow("Tek bahiste kasanın en fazla", self.sp_cap)
        self.chk_stake = QCheckBox("Gerçek para miktarı önerilerini göster (risk sınırlarımı yukarıda kendim belirledim)")
        self.chk_stake.setToolTip("Kapalıyken uygulama yalnızca olasılık, adil oran ve beklenen değer gösterir; para miktarı önermez.")
        f2.addRow(self.chk_stake)
        self.body.addWidget(g2)

        g3 = QGroupBox("Uygulama")
        f3 = QFormLayout(g3)
        self.chk_auto = QCheckBox("Açılışta verileri otomatik güncelle ve gerekirse modeli eğit (6 saatten eskiyse)")
        self.chk_mirror = QCheckBox("football-data.co.uk erişilemezse GitHub yedek veri setini kullan")
        self.sp_days = QSpinBox()
        self.sp_days.setRange(1, 60)
        f3.addRow(self.chk_auto)
        f3.addRow(self.chk_mirror)
        f3.addRow("Kaç günlük fikstür gösterilsin", self.sp_days)
        self.body.addWidget(g3)

        btn = QPushButton("Kaydet")
        btn.setObjectName("primary")
        btn.clicked.connect(self._save)
        self.body.addWidget(btn)
        self.body.addWidget(banner(
            "<b>Oran türü</b>: 'Piyasa ortalaması' tipik bir bahis şirketini temsil eder. 'En yüksek oran', "
            "geçmişte onlarca şirket arasındaki en iyi fiyattır; erişilebilirliği doğrulanamadığı için bu seçenekle "
            "hesaplanan değer ve getiriler varsayımsaldır. Kayıp sonrası bahis artırma (martingale vb.) ve kayıp "
            "telafisi önerileri bu uygulamada yoktur."))
        self.body.addStretch(1)
        controller.settingsChanged.connect(self._load)
        self._load()

    @staticmethod
    def _dspin(lo, hi, step, tip: str = "", decimals: int = 2) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setDecimals(decimals)
        if tip:
            sp.setToolTip(tip)
        return sp

    def _load(self) -> None:
        s = self.ctl.settings
        self.cb_odds.setCurrentIndex(max(self.cb_odds.findData(s.odds_type), 0))
        self.cb_margin.setCurrentIndex(max(self.cb_margin.findData(s.margin_method), 0))
        self.sp_ev.setValue(s.min_ev)
        self.sp_prob.setValue(s.min_prob)
        self.sp_min_odds.setValue(s.min_odds)
        self.sp_max_odds.setValue(s.max_odds)
        self.sp_bank.setValue(s.bankroll)
        self.ed_cur.setText(s.currency)
        self.sp_kelly.setValue(s.kelly_fraction)
        self.sp_cap.setValue(s.max_stake_pct)
        self.chk_auto.setChecked(s.auto_update_on_start)
        self.chk_stake.setChecked(s.stake_suggestions)
        self.chk_mirror.setChecked(s.use_mirror_fallback)
        self.sp_days.setValue(s.fixture_days)

    def _save(self) -> None:
        s = copy.deepcopy(self.ctl.settings)
        s.odds_type = self.cb_odds.currentData()
        s.margin_method = self.cb_margin.currentData()
        s.min_ev = self.sp_ev.value()
        s.min_prob = self.sp_prob.value()
        s.min_odds = self.sp_min_odds.value()
        s.max_odds = max(self.sp_max_odds.value(), s.min_odds)
        s.bankroll = self.sp_bank.value()
        s.currency = self.ed_cur.text().strip() or "TL"
        s.kelly_fraction = self.sp_kelly.value()
        s.max_stake_pct = self.sp_cap.value()
        s.auto_update_on_start = self.chk_auto.isChecked()
        s.stake_suggestions = self.chk_stake.isChecked()
        s.use_mirror_fallback = self.chk_mirror.isChecked()
        s.fixture_days = self.sp_days.value()
        self.ctl.save_settings(s)

"""Veri kaynakları: lig seçimi, indirme/güncelleme ve veri özeti."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
)

from ...config import DEFAULT_LEAGUES
from ...data.github_kaynak import PROFILE_DEFAULT, PROFILE_GITHUB
from ...data.leagues import LEAGUES, league_name
from ...data.source_registry import DECLARABLE, IMPLEMENTED, SOURCES
from ..widgets import DataFrameModel, banner, make_table, section
from .base import Page


class DataPage(Page):
    title = "Veri"
    subtitle = ("Veriler ücretsiz kaynaklardan, yalnızca sizin onay verdiğiniz kaynaklardan indirilir: maç sonuçları, "
                "istatistikler ve 1X2 / 2,5 Alt-Üst oranları football-data.co.uk'tan; site erişilemezse ve onay "
                "verdiyseniz GitHub'daki türetilmiş veri setinden alınır. 'Yalnızca GitHub' profilinde bütün güncellemeler "
                "seçili GitHub depolarından yapılır.")

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.body.addWidget(section("Kaynak onayları"))
        crow = QHBoxLayout()
        self.consent_label = QLabel("")
        self.consent_label.setWordWrap(True)
        crow.addWidget(self.consent_label, 1)
        b_consent = QPushButton("Kaynak koşulları ve onaylar...")
        b_consent.clicked.connect(self._consent)
        crow.addWidget(b_consent)
        self.body.addLayout(crow)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Veri profili:"))
        self.cb_profile = QComboBox()
        self.cb_profile.addItem("Varsayılan: football-data.co.uk (onay verildiyse GitHub yedek)", PROFILE_DEFAULT)
        self.cb_profile.addItem("Yalnızca GitHub: seçili depolar (football-data adreslerine istek yok)", PROFILE_GITHUB)
        self.cb_profile.setToolTip("Seçim yalnızca kaydedilir; indirme 'Kaydet, Güncelle ve Eğit' ile başlar.")
        self.cb_profile.currentIndexChanged.connect(self._profile_changed)
        prow.addWidget(self.cb_profile, 1)
        self.body.addLayout(prow)
        self.body.addWidget(section("Ligler"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(300)
        self.body.addWidget(self.tree)
        row = QHBoxLayout()
        row.addWidget(QLabel("Kaç yıllık geçmiş:"))
        self.sp_years = QSpinBox()
        self.sp_years.setRange(3, 33)
        row.addWidget(self.sp_years)
        self.chk_force = QCheckBox("Tüm dosyaları yeniden indir")
        row.addWidget(self.chk_force)
        row.addStretch(1)
        b_default = QPushButton("Varsayılan ligler")
        b_default.clicked.connect(lambda: self._check(set(DEFAULT_LEAGUES)))
        b_all = QPushButton("Tümünü seç")
        b_all.clicked.connect(lambda: self._check(set(LEAGUES)))
        self.btn = QPushButton("Kaydet, Güncelle ve Eğit")
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(self._apply)
        for w in (b_default, b_all, self.btn):
            row.addWidget(w)
        self.body.addLayout(row)
        self.body.addWidget(banner(
            "Daha fazla lig ve yıl, modeli genellikle güçlendirir ancak indirme ve eğitim süresini uzatır. "
            "16 lig × 10 yıl için eğitim normal bir bilgisayarda birkaç dakika sürer."))

        self.body.addWidget(section("Yüklü veriler"))
        self.model = DataFrameModel()
        self.model.headers = {"league": "Lig", "seasons": "Sezon", "matches": "Maç", "first": "İlk maç",
                              "last": "Son maç", "source": "Kaynak"}
        self.model.formatters = {"league": league_name}
        view, _ = make_table(self.model)
        view.setMinimumHeight(320)
        self.body.addWidget(view)
        self.report = QLabel("")
        self.report.setObjectName("muted")
        self.report.setWordWrap(True)
        self.body.addWidget(self.report)

        from .archive_panel import ArchivePanel

        self.body.addWidget(section("GitHub Veri ve Arşiv"))
        self.archive_panel = ArchivePanel(controller)
        self.body.addWidget(self.archive_panel)
        self.body.addStretch(1)

        self._build_tree()
        controller.dataChanged.connect(self.refresh)
        controller.settingsChanged.connect(self._load)
        controller.busyChanged.connect(lambda b: self.btn.setEnabled(not b))
        self._load()
        self.refresh()

    def _build_tree(self) -> None:
        countries: dict[str, QTreeWidgetItem] = {}
        for code, lg in LEAGUES.items():
            parent = countries.get(lg.country)
            if parent is None:
                parent = QTreeWidgetItem([lg.country])
                parent.setFlags(parent.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
                self.tree.addTopLevelItem(parent)
                countries[lg.country] = parent
            it = QTreeWidgetItem([f"{lg.name}  ({code})"])
            it.setData(0, Qt.UserRole, code)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Unchecked)
            parent.addChild(it)
        self.tree.expandAll()

    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield top.child(j)

    def _check(self, codes: set[str]) -> None:
        for it in self._items():
            it.setCheckState(0, Qt.Checked if it.data(0, Qt.UserRole) in codes else Qt.Unchecked)

    def _load(self) -> None:
        s = self.ctl.settings
        self._check(set(s.leagues))
        self.sp_years.setValue(s.years_back)
        i = self.cb_profile.findData(s.data_profile)
        if i >= 0 and i != self.cb_profile.currentIndex():
            self.cb_profile.blockSignals(True)
            self.cb_profile.setCurrentIndex(i)
            self.cb_profile.blockSignals(False)
        decl = s.declarations()
        names = [SOURCES[k].name + (" (kişisel kullanım beyanı var)" if k in decl else
                                    " (beyan yok: bu kaynağın verisiyle model eğitilmez, tahmin gösterilmez)"
                                    if k in DECLARABLE else "")
                 for k in IMPLEMENTED if SOURCES[k].requires_consent and k in s.source_consent]
        self.consent_label.setText(
            "Onay verilen kaynaklar: " + ", ".join(names) if names else
            "Geçmiş maç verisi için henüz hiçbir kaynağın kullanım koşulları onaylanmadı; veri indirilemez.")

    def _profile_changed(self) -> None:
        """Profil seçimi yalnızca ayarlara kaydedilir; indirme veya eğitim başlatmaz."""
        s = self.ctl.settings
        val = self.cb_profile.currentData()
        if val and val != s.data_profile:
            s.data_profile = val
            s.save()
            self.ctl.settingsChanged.emit()

    def _consent(self) -> None:
        from ..consent import ask_consent

        before = dict(self.ctl.settings.declarations())
        ask_consent(self.ctl, self)
        if self.ctl.settings.declarations() != before:
            self.ctl.declarations_changed(added=bool(set(self.ctl.settings.declarations()) - set(before)))

    def _apply(self) -> None:
        codes = [it.data(0, Qt.UserRole) for it in self._items() if it.checkState(0) == Qt.Checked]
        if not codes:
            self.report.setText("En az bir lig seçin.")
            return
        s = self.ctl.settings
        s.leagues = [c for c in LEAGUES if c in codes]
        s.years_back = self.sp_years.value()
        s.save()
        self.ctl.settingsChanged.emit()
        if self.ctl.needs_consent():
            from ..consent import NOT_UPDATED_TEXT, ask_consent_before_update

            if not ask_consent_before_update(self.ctl, self):
                self.report.setText(NOT_UPDATED_TEXT)
                return
        self.ctl.update_and_train(force=self.chk_force.isChecked())

    def refresh(self) -> None:
        self.model.set_frame(self.ctl.store.summary())
        txt = self.ctl.last_report_text
        upd = self.ctl.store.meta.get("updated_at")
        self.report.setText((f"Son güncelleme: {upd.replace('T', ' ')}\n" if upd else "") + txt)

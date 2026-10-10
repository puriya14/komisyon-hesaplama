"""Ana pencere: sol menü + sayfalar + durum çubuğu."""

from __future__ import annotations

from PySide6.QtCore import QSize, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_TITLE, __version__
from .controller import AppController
from .pages.about import AboutPage
from .pages.backtest import BacktestPage
from .pages.banko import BankoPage
from .pages.dashboard import DashboardPage
from .pages.data import DataPage
from .pages.match import MatchPage
from .pages.predictions import PredictionsPage
from .pages.ratings import RatingsPage
from .pages.settings import SettingsPage

NAV = [
    ("Genel Bakış", DashboardPage),
    ("Tahminler", PredictionsPage),
    ("Banko (Yüksek Güven)", BankoPage),
    ("Maç Analizi", MatchPage),
    ("Güç Sıralaması", RatingsPage),
    ("Geriye Dönük Test", BacktestPage),
    ("Veri", DataPage),
    ("Ayarlar", SettingsPage),
    ("Hakkında", AboutPage),
]


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController | None = None):
        super().__init__()
        self.ctl = controller or AppController(self)
        self.setWindowTitle(f"{APP_TITLE} {__version__}")
        self.resize(1360, 880)
        self.setMinimumSize(1024, 680)

        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(230)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 18, 0, 12)
        title = QLabel(f"  {APP_TITLE}")
        title.setObjectName("appTitle")
        sub = QLabel("   Veriye dayalı futbol tahmini")
        sub.setObjectName("appSubtitle")
        sl.addWidget(title)
        sl.addWidget(sub)
        sl.addSpacing(14)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(18, 18))
        sl.addWidget(self.nav, 1)
        ver = QLabel(f"   Sürüm {__version__} · ücretsiz veri")
        ver.setObjectName("appSubtitle")
        sl.addWidget(ver)
        lay.addWidget(side)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.pages = []
        for name, cls in NAV:
            page = cls(self.ctl)
            self.pages.append(page)
            self.stack.addWidget(page)
            QListWidgetItem(name, self.nav)
        self.nav.currentRowChanged.connect(self._switch)
        self.nav.setCurrentRow(0)

        self.status = QLabel("Hazır")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(320)
        self.progress.setRange(0, 100)
        self.progress.hide()
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.progress)

        self.ctl.progress.connect(self._progress)
        self.ctl.busyChanged.connect(self._busy)
        self.ctl.message.connect(self._message)

    def page(self, cls):
        return next(p for p in self.pages if isinstance(p, cls))

    def _switch(self, row: int) -> None:
        self.stack.setCurrentIndex(row)
        self.pages[row].on_show()

    def _progress(self, value: int, text: str) -> None:
        self.progress.setValue(value)
        self.status.setText(text)

    def _busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        if not busy:
            QTimer.singleShot(4000, lambda: self.status.setText("Hazır") if not self.ctl.busy else None)

    def _message(self, kind: str, text: str) -> None:
        if kind == "error":
            QMessageBox.critical(self, "Hata", text)
        elif kind == "popup":
            QMessageBox.information(self, APP_TITLE, text)
        else:
            self.status.setText(text.splitlines()[0] if text else "")
            self.status.setToolTip(text)

    def closeEvent(self, ev) -> None:
        if self.ctl.busy:
            ans = QMessageBox.question(
                self, APP_TITLE, "Bir işlem sürüyor. Yine de çıkmak istiyor musunuz?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                ev.ignore()
                return
            # Kayıt yarıda kalmasın diye iş bitene kadar pencereyi gizleyip bekle
            self.hide()
            self.ctl.wait()
        ev.accept()

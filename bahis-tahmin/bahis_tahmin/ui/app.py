"""Masaüstü uygulamasını başlatır."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import APP_NAME, APP_TITLE
from ..config import app_home
from .main_window import MainWindow
from .theme import apply_theme


def resource_path(rel: str) -> Path:
    """Kaynak dosya yolu (PyInstaller paketi içinde de çalışır)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / rel


def setup_logging() -> Path:
    log_dir = app_home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "bahis_tahmin.log"
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    return path


def run(argv: list[str] | None = None) -> int:
    setup_logging()
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName(APP_NAME)
    apply_theme(app)
    icon = resource_path("assets/icon.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    win = MainWindow()
    win.show()
    QTimer.singleShot(50, win.ctl.load_initial)
    return app.exec()

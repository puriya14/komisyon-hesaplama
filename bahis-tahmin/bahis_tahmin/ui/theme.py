"""Koyu tema renkleri ve Qt stil sayfası."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# Renkler Qt'den bağımsız modülde (web arayüzü ve grafikler de aynı değerleri kullanır)
from ..palette import (  # noqa: F401
    ACCENT,
    ACCENT_DARK,
    AMBER,
    AXIS,
    BG,
    BLUE,
    BORDER,
    CRITICAL,
    DRAW,
    GOOD,
    GRID,
    MUTED,
    RED,
    SERIES_1,
    SERIES_2,
    SERIES_3,
    SURFACE,
    SURFACE2,
    TEXT,
    WARNING,
    ev_hex,
    prob_rgb,
)

STYLE = f"""
* {{ font-family: "Segoe UI", "Noto Sans", Arial; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QDialog, QWidget#page {{ background: {BG}; }}
QWidget {{ background: transparent; }}
QToolTip {{ background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; }}

QFrame#sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QLabel#appTitle {{ font-size: 15pt; font-weight: 700; color: {TEXT}; }}
QLabel#appSubtitle {{ color: {MUTED}; font-size: 9pt; }}
QListWidget#nav {{ background: transparent; border: none; outline: 0; }}
QListWidget#nav::item {{ padding: 10px 14px; margin: 2px 8px; border-radius: 8px; color: {MUTED}; }}
QListWidget#nav::item:hover {{ background: {SURFACE2}; color: {TEXT}; }}
QListWidget#nav::item:selected {{ background: {SURFACE2}; color: {TEXT}; border-left: 3px solid {ACCENT}; }}

QLabel#pageTitle {{ font-size: 18pt; font-weight: 700; }}
QLabel#pageSubtitle {{ color: {MUTED}; }}
QLabel#sectionTitle {{ font-size: 12pt; font-weight: 600; margin-top: 6px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#banner {{ background: #1f2a1f; border: 1px solid {ACCENT_DARK}; border-radius: 8px; padding: 10px; color: {TEXT}; }}
QLabel#warn {{ background: #2a2414; border: 1px solid #92400e; border-radius: 8px; padding: 10px; color: {TEXT}; }}

QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QLabel#cardTitle {{ color: {MUTED}; font-size: 9pt; }}
QLabel#cardValue {{ font-size: 18pt; font-weight: 700; }}
QLabel#cardSub {{ color: {MUTED}; font-size: 9pt; }}

QPushButton {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 8px 16px; }}
QPushButton:hover {{ border-color: {MUTED}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {SURFACE2}; }}
QPushButton#primary {{ background: {ACCENT_DARK}; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT}; color: #04120a; }}
QPushButton#primary:disabled {{ background: {SURFACE2}; border-color: {BORDER}; color: {MUTED}; }}

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QDateEdit {{
    background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px; min-height: 20px;
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover, QDateEdit:hover {{ border-color: {MUTED}; }}
QComboBox QAbstractItemView {{ background: {SURFACE2}; border: 1px solid {BORDER}; selection-background-color: {BORDER}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {MUTED}; background: {SURFACE2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QTreeView::indicator, QListView::indicator, QTableView::indicator {{
    width: 14px; height: 14px; border-radius: 3px; border: 1px solid {MUTED}; background: {SURFACE2};
}}
QTreeView::indicator:checked, QListView::indicator:checked, QTableView::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
}}
QTreeView::indicator:indeterminate {{ background: {ACCENT_DARK}; border-color: {ACCENT_DARK}; }}
QStatusBar QLabel {{ padding: 2px 8px; color: {MUTED}; }}

QTableView, QTreeWidget, QListWidget#plain {{
    background: {SURFACE}; alternate-background-color: #171e27; border: 1px solid {BORDER};
    border-radius: 8px; gridline-color: {BORDER}; selection-background-color: #24344a; selection-color: {TEXT};
}}
QHeaderView::section {{ background: {SURFACE2}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px; font-weight: 600; }}
QTableCornerButton::section {{ background: {SURFACE2}; border: none; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 16px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

QGroupBox {{ border: 1px solid {BORDER}; border-radius: 10px; margin-top: 14px; padding: 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {MUTED}; }}

QProgressBar {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 6px; text-align: center; height: 16px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollArea {{ border: none; }}
QPlainTextEdit, QTextBrowser {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
QSplitter::handle {{ background: {BORDER}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(SURFACE))
    pal.setColor(QPalette.AlternateBase, QColor("#171e27"))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(SURFACE2))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor("#24344a"))
    pal.setColor(QPalette.HighlightedText, QColor(TEXT))
    pal.setColor(QPalette.ToolTipBase, QColor(SURFACE2))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(MUTED))
    pal.setColor(QPalette.Link, QColor(BLUE))
    app.setPalette(pal)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLE)


def prob_color(p: float, alpha: int = 255) -> QColor:
    """Olasılık (büyüklük) için tek tonlu ardışık renk: yüzeyden maviye."""
    rgb = prob_rgb(p)
    return QColor(0, 0, 0, 0) if rgb is None else QColor(*rgb, alpha)


def ev_color(ev: float) -> QColor:
    """Beklenen değer (durum anlamı: olumlu/olumsuz) için koyu arka plan tonları."""
    h = ev_hex(ev)
    return QColor(0, 0, 0, 0) if h is None else QColor(h)

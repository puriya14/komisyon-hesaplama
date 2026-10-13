"""Ortak arayüz bileşenleri."""

from __future__ import annotations

import datetime as dt
from typing import Callable

import numpy as np
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..fmt import fmt_num, fmt_pct, fmt_signed_pct  # noqa: F401 (sayfalar buradan içe aktarır)
from . import theme

SORT_ROLE = Qt.UserRole + 1


class DataFrameModel(QAbstractTableModel):
    """pandas DataFrame'i tabloda gösterir; sütun bazlı biçim ve renk desteği."""

    def __init__(self, df: pd.DataFrame | None = None, parent=None):
        super().__init__(parent)
        self._df = pd.DataFrame()
        self.formatters: dict[str, Callable] = {}
        self.backgrounds: dict[str, Callable] = {}
        self.foregrounds: dict[str, Callable] = {}
        self.tooltips: dict[str, Callable] = {}
        self.headers: dict[str, str] = {}
        self.hidden: set[str] = set()
        self.checkable_col: str | None = None
        self._checked: set[int] = set()
        self._cols: list[str] = []
        if df is not None:
            self.set_frame(df)

    def set_frame(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self._df = df.reset_index(drop=True) if df is not None else pd.DataFrame()
        self._cols = [c for c in self._df.columns if c not in self.hidden]
        self._checked = set()
        self.endResetModel()

    @property
    def frame(self) -> pd.DataFrame:
        return self._df

    def column_name(self, col: int) -> str:
        return self._cols[col]

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._cols)

    def checked_rows(self) -> list[int]:
        return sorted(self._checked)

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if self.checkable_col and self._cols[index.column()] == self.checkable_col:
            f |= Qt.ItemIsUserCheckable
        return f

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        col = self._cols[index.column()]
        val = self._df.iat[index.row(), self._df.columns.get_loc(col)]
        if role == Qt.DisplayRole:
            f = self.formatters.get(col)
            if f is not None:
                return f(val)
            if isinstance(val, float):
                return "-" if val != val else f"{val:.2f}"
            if isinstance(val, (pd.Timestamp, dt.date)):
                return val.strftime("%d.%m.%Y")
            return "" if val is None else str(val)
        if role == SORT_ROLE:
            if isinstance(val, (int, float, np.integer, np.floating)):
                v = float(val)
                return -1e18 if v != v else v
            if isinstance(val, pd.Timestamp):
                return val.value
            if isinstance(val, dt.date):
                return val.toordinal()
            return "" if val is None else str(val)
        if role == Qt.BackgroundRole:
            f = self.backgrounds.get(col)
            if f is not None:
                c = f(val, self._df.iloc[index.row()])
                return QBrush(c) if c is not None else None
        if role == Qt.ForegroundRole:
            f = self.foregrounds.get(col)
            if f is not None:
                c = f(val, self._df.iloc[index.row()])
                return QBrush(c) if c is not None else None
        if role == Qt.ToolTipRole:
            f = self.tooltips.get(col)
            if f is not None:
                return f(val, self._df.iloc[index.row()])
        if role == Qt.TextAlignmentRole:
            if isinstance(val, (int, float, np.integer, np.floating)):
                return int(Qt.AlignCenter)
            return int(Qt.AlignVCenter | Qt.AlignLeft)
        if role == Qt.CheckStateRole and self.checkable_col == col:
            return Qt.Checked if index.row() in self._checked else Qt.Unchecked
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role == Qt.CheckStateRole and self.checkable_col == self._cols[index.column()]:
            state = Qt.CheckState(value) if not isinstance(value, Qt.CheckState) else value
            if state == Qt.Checked:
                self._checked.add(index.row())
            else:
                self._checked.discard(index.row())
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            col = self._cols[section]
            return self.headers.get(col, col)
        return None


class FilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.predicate: Callable[[int], bool] | None = None

    def filterAcceptsRow(self, source_row, source_parent):
        if self.predicate is not None and not self.predicate(source_row):
            return False
        return super().filterAcceptsRow(source_row, source_parent)


def make_table(model: QAbstractTableModel, sortable: bool = True) -> tuple[QTableView, FilterProxy]:
    view = QTableView()
    proxy = FilterProxy(view)
    proxy.setSourceModel(model)
    proxy.setFilterKeyColumn(-1)
    view.setModel(proxy)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectRows)
    view.setSelectionMode(QAbstractItemView.SingleSelection)
    view.setEditTriggers(QAbstractItemView.NoEditTriggers)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(30)
    view.horizontalHeader().setHighlightSections(False)
    view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    view.horizontalHeader().setStretchLastSection(True)
    view.setSortingEnabled(sortable)
    view.setShowGrid(False)
    view.setWordWrap(False)
    # Qt sıralamayı açınca varsayılan olarak azalan sıralar; kaynak sırasını koru
    proxy.sort(-1)
    view.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)

    def autosize():
        view.resizeColumnsToContents()
        hh = view.horizontalHeader()
        for c in range(hh.count()):
            if hh.sectionSize(c) > 340:
                hh.resizeSection(c, 340)

    model.modelReset.connect(autosize)
    return view, proxy


class Card(QFrame):
    def __init__(self, title: str, value: str = "-", sub: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.value = QLabel(value)
        self.value.setObjectName("cardValue")
        self.sub = QLabel(sub)
        self.sub.setObjectName("cardSub")
        self.sub.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)
        lay.addStretch(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set(self, value: str, sub: str | None = None, color: str | None = None) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color: {color};" if color else "")
        if sub is not None:
            self.sub.setText(sub)


def page_header(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 8)
    lay.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("pageTitle")
    lay.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("pageSubtitle")
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


def section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setObjectName("sectionTitle")
    return lbl


def banner(text: str, kind: str = "banner") -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName(kind)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.RichText)
    lbl.setOpenExternalLinks(True)
    return lbl


class ProbBar(QWidget):
    """1 / X / 2 olasılıklarını tek bir yatay çubukta gösterir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.probs = (np.nan, np.nan, np.nan)
        self.labels = ("1", "X", "2")
        self.setMinimumHeight(44)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_probs(self, probs, labels=("1", "X", "2")) -> None:
        self.probs = tuple(float(p) for p in probs)
        self.labels = labels
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if not all(np.isfinite(self.probs)):
            p.setPen(QColor(theme.MUTED))
            p.drawText(r, Qt.AlignCenter, "Olasılık yok")
            return
        colors = [QColor(theme.SERIES_1), QColor(theme.DRAW), QColor(theme.SERIES_2)]
        x = r.left()
        total = sum(self.probs)
        font = QFont(self.font())
        font.setBold(True)
        p.setFont(font)
        for prob, col, lab in zip(self.probs, colors, self.labels):
            w = r.width() * prob / total
            seg = QRectF(x, r.top(), w, r.height())
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(seg.adjusted(1, 0, -1, 0), 6, 6)
            p.setPen(QPen(QColor("#0b0f14")))  # dolgu içinde koyu mürekkep (kontrast ≥ 4.5)
            if w > 44:
                p.drawText(seg, Qt.AlignCenter, f"{lab}  %{100 * prob:.0f}")
            x += w


class ScoreHeatmap(QWidget):
    """Skor olasılık matrisi (ev: satır, deplasman: sütun)."""

    def __init__(self, size: int = 6, parent=None):
        super().__init__(parent)
        self.size = size
        self.matrix: np.ndarray | None = None
        self.setMinimumSize(300, 300)

    def set_matrix(self, m: np.ndarray | None) -> None:
        self.matrix = m
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.matrix is None:
            return
        n = self.size
        m = self.matrix[:n, :n]
        vmax = max(float(m.max()), 1e-9)
        margin = 26
        side = min(self.width() - margin, self.height() - margin)
        cell = side / n
        p.setPen(QColor(theme.MUTED))
        for k in range(n):
            p.drawText(QRectF(margin + k * cell, 0, cell, margin), Qt.AlignCenter, str(k))
            p.drawText(QRectF(0, margin + k * cell, margin, cell), Qt.AlignCenter, str(k))
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, cell / 6.5))
        p.setFont(font)
        for i in range(n):
            for j in range(n):
                v = float(m[i, j])
                c = theme.prob_color(min(1.0, v / vmax))
                rect = QRectF(margin + j * cell, margin + i * cell, cell, cell).adjusted(1.5, 1.5, -1.5, -1.5)
                p.setPen(Qt.NoPen)
                p.setBrush(c)
                p.drawRoundedRect(rect, 4, 4)
                p.setPen(QColor(theme.TEXT))
                p.drawText(rect, Qt.AlignCenter, f"{100 * v:.1f}")


class ClickableCard(Card):
    clicked = Signal()

    def mouseReleaseEvent(self, ev):
        self.clicked.emit()
        super().mouseReleaseEvent(ev)


def hbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        else:
            lay.addWidget(w)
    return lay

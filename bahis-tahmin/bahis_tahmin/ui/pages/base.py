"""Sayfa iskeleti: kaydırılabilir içerik alanı."""

from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from ..widgets import page_header


class Page(QWidget):
    title = ""
    subtitle = ""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.ctl = controller
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setObjectName("page")
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(24, 20, 24, 20)
        self.body.setSpacing(12)
        self.header = page_header(self.title, self.subtitle)
        self.body.addWidget(self.header)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def on_show(self) -> None:
        """Sayfa görünür olduğunda çağrılır."""

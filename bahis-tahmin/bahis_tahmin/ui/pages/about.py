"""Hakkında: yöntem, veri kaynakları ve sorumlu bahis."""

from __future__ import annotations

from PySide6.QtWidgets import QTextBrowser

from ... import __version__
from ...config import app_home
from ...about_text import ABOUT_HTML
from ...models.features import FEATURES
from .base import Page


class AboutPage(Page):
    title = "Hakkında"
    subtitle = ""

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setHtml(ABOUT_HTML.format(version=__version__, home=app_home(), n_features=len(FEATURES)))
        tb.setMinimumHeight(820)
        self.body.addWidget(tb)

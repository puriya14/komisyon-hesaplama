"""Masaüstü grafik tuvali (Qt; üzerine gelince değer). Çizim işlevleri: ``bahis_tahmin.plots``."""

from __future__ import annotations

import matplotlib

matplotlib.use("QtAgg")

import matplotlib.dates as mdates  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

# Çizim işlevleri Qt'den bağımsız ``plots`` modülündedir (web arayüzü de kullanır); burada da erişilebilir
from ..plots import (  # noqa: E402,F401
    _pct,
    plot_calibration,
    plot_confidence,
    plot_equity,
    plot_goal_calibration,
    plot_ratings,
    plot_season_quality,
    style_axes,
)
from . import theme  # noqa: E402

TEXT = theme.TEXT
MUTED = theme.MUTED
SURFACE = theme.SURFACE


class ChartCanvas(FigureCanvasQTAgg):
    def __init__(self, width: float = 6, height: float = 3.2, parent=None):
        self.fig = Figure(figsize=(width, height), dpi=100, facecolor=SURFACE)
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax = self.fig.add_subplot(111)
        self._hover = None
        self._annot = None
        self.mpl_connect("motion_notify_event", self._on_move)
        self.reset()

    def reset(self, title: str = "") -> None:
        self.ax = style_axes(self.fig, title)
        self._hover = None
        self._annot = None

    def finish(self) -> None:
        self.draw_idle()

    # ----------------------------------------------------------- hover
    def set_hover(self, xs, series: list[tuple[str, np.ndarray]], fmt_x, fmt_y) -> None:
        """Fare x eksenindeki en yakın noktanın değerlerini gösterir (dikey kılavuz çizgisiyle)."""
        self._hover = (np.asarray(xs), series, fmt_x, fmt_y)
        self._vline = self.ax.axvline(xs[0] if len(xs) else 0, color=theme.AXIS, linewidth=1, visible=False)
        self._annot = self.ax.annotate(
            "", xy=(0, 0), xytext=(10, 10), textcoords="offset points", color=TEXT, fontsize=8,
            bbox={"boxstyle": "round,pad=0.4", "fc": theme.SURFACE2, "ec": theme.BORDER},
        )
        self._annot.set_visible(False)

    def _on_move(self, event) -> None:
        if self._hover is None or self._annot is None:
            return
        if event.inaxes != self.ax or event.xdata is None:
            if self._annot.get_visible():
                self._annot.set_visible(False)
                self._vline.set_visible(False)
                self.draw_idle()
            return
        xs, series, fmt_x, fmt_y = self._hover
        if len(xs) == 0:
            return
        xnum = mdates.date2num(xs) if np.issubdtype(xs.dtype, np.datetime64) else xs.astype(float)
        i = int(np.argmin(np.abs(xnum - event.xdata)))
        lines = [fmt_x(xs[i])] + [f"{name}: {fmt_y(vals[i])}" for name, vals in series]
        self._annot.xy = (xs[i], series[0][1][i])
        self._annot.set_text("\n".join(lines))
        self._annot.set_visible(True)
        self._vline.set_xdata([xs[i], xs[i]])
        self._vline.set_visible(True)
        self.draw_idle()

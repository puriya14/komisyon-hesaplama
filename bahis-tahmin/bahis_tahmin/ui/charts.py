"""matplotlib grafikleri (koyu tema, ince işaretler, saç teli ızgara, üzerine gelince değer)."""

from __future__ import annotations

import matplotlib

matplotlib.use("QtAgg")

import matplotlib.dates as mdates  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

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
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        ax = self.ax
        ax.set_facecolor(SURFACE)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(theme.AXIS)
            ax.spines[side].set_linewidth(1)
        ax.tick_params(colors=MUTED, labelsize=8, length=0)
        ax.grid(True, color=theme.GRID, linewidth=1, linestyle="-")
        ax.set_axisbelow(True)
        if title:
            ax.set_title(title, color=TEXT, fontsize=10, loc="left", pad=10)
        self._hover = None
        self._annot = None
        self.fig.subplots_adjust(left=0.1, right=0.97, top=0.88, bottom=0.16)

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


def _pct(v, _=None) -> str:
    return f"%{100 * v:.0f}"


def plot_equity(canvas: ChartCanvas, bets: pd.DataFrame, start: float, currency: str = "") -> None:
    canvas.reset("Kasa gelişimi")
    ax = canvas.ax
    if bets is None or bets.empty:
        ax.text(0.5, 0.5, "Bu ayarlarla bahis bulunamadı", color=MUTED, ha="center", va="center", transform=ax.transAxes)
        canvas.finish()
        return
    x = pd.to_datetime(bets["date"]).to_numpy()
    y = bets["bankroll"].to_numpy(dtype=float)
    ax.axhline(start, color=theme.AXIS, linewidth=1)
    ax.plot(x, y, color=theme.SERIES_1, linewidth=2, solid_joinstyle="round", solid_capstyle="round")
    ax.plot([x[-1]], [y[-1]], "o", color=theme.SERIES_1, markersize=8, markeredgecolor=SURFACE, markeredgewidth=2)
    ax.annotate(f"{y[-1]:,.0f} {currency}", (x[-1], y[-1]), xytext=(-6, 8), textcoords="offset points",
                ha="right", color=TEXT, fontsize=8)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    canvas.fig.autofmt_xdate(rotation=0, ha="center")
    canvas.set_hover(x, [("Kasa", y)], lambda d: pd.Timestamp(d).strftime("%d.%m.%Y"), lambda v: f"{v:,.0f} {currency}")
    canvas.finish()


def plot_calibration(canvas: ChartCanvas, calib: pd.DataFrame) -> None:
    canvas.reset("Kalibrasyon: tahmin edilen ve gerçekleşen olasılık")
    ax = canvas.ax
    ax.plot([0, 1], [0, 1], color=MUTED, linewidth=1, label="Kusursuz kalibrasyon")
    if calib is not None and not calib.empty:
        x = calib["tahmin"].to_numpy()
        y = calib["gercek"].to_numpy()
        ax.plot(x, y, color=theme.SERIES_1, linewidth=2, label="Model (nihai olasılık)")
        ax.plot(x, y, "o", color=theme.SERIES_1, markersize=8, markeredgecolor=SURFACE, markeredgewidth=2)
        canvas.set_hover(x, [("Gerçekleşen", y)], lambda v: f"Tahmin: %{100 * v:.1f}", lambda v: f"%{100 * v:.1f}")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.xaxis.set_major_formatter(FuncFormatter(_pct))
    ax.yaxis.set_major_formatter(FuncFormatter(_pct))
    ax.legend(frameon=False, labelcolor=TEXT, fontsize=8, loc="upper left")
    canvas.finish()


def plot_confidence(canvas: ChartCanvas, rows: list[dict], title: str) -> None:
    canvas.reset(title)
    ax = canvas.ax
    rows = [r for r in rows if r.get("n", 0) > 0]
    if not rows:
        canvas.finish()
        return
    t = np.array([r["esik"] for r in rows])
    acc = np.array([r["isabet"] for r in rows])
    cov = np.array([r["kapsam"] for r in rows])
    ax.plot(t, acc, color=theme.SERIES_1, linewidth=2, label="İsabet oranı")
    ax.plot(t, cov, color=theme.SERIES_2, linewidth=2, label="Kapsam (maçların oranı)")
    for y, col in ((acc, theme.SERIES_1), (cov, theme.SERIES_2)):
        ax.plot([t[-1]], [y[-1]], "o", color=col, markersize=8, markeredgecolor=SURFACE, markeredgewidth=2)
        ax.annotate(f"%{100 * y[-1]:.0f}", (t[-1], y[-1]), xytext=(6, 0), textcoords="offset points",
                    va="center", color=TEXT, fontsize=8)
    ax.set_ylim(0, 1.05)
    ax.set_xlim(t.min() - 0.02, t.max() + 0.05)
    ax.xaxis.set_major_formatter(FuncFormatter(_pct))
    ax.yaxis.set_major_formatter(FuncFormatter(_pct))
    ax.set_xlabel("Güven eşiği (model olasılığı en az)", color=MUTED, fontsize=8)
    ax.legend(frameon=False, labelcolor=TEXT, fontsize=8, loc="lower left")
    canvas.set_hover(t, [("İsabet", acc), ("Kapsam", cov)], lambda v: f"Eşik ≥ %{100 * v:.0f}", lambda v: f"%{100 * v:.1f}")
    canvas.finish()


def plot_season_quality(canvas: ChartCanvas, per_season: list[dict]) -> None:
    canvas.reset("Sezon bazında 1X2 isabeti (örneklem dışı)")
    ax = canvas.ax
    rows = [r for r in per_season if "acc_market" in r]
    if not rows:
        canvas.finish()
        return
    labels = [r["season"] for r in rows]
    x = np.arange(len(rows))
    model = np.array([r["acc_model_m"] for r in rows])
    market = np.array([r["acc_market"] for r in rows])
    ax.plot(x, model, color=theme.SERIES_1, linewidth=2, label="Model")
    ax.plot(x, market, color=theme.SERIES_2, linewidth=2, label="Bahis piyasası")
    for y, col in ((model, theme.SERIES_1), (market, theme.SERIES_2)):
        ax.plot(x, y, "o", color=col, markersize=8, markeredgecolor=SURFACE, markeredgewidth=2)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    lo = min(model.min(), market.min())
    hi = max(model.max(), market.max())
    ax.set_ylim(max(0.0, lo - 0.05), min(1.0, hi + 0.05))
    ax.yaxis.set_major_formatter(FuncFormatter(_pct))
    ax.legend(frameon=False, labelcolor=TEXT, fontsize=8, loc="lower left")
    canvas.set_hover(x, [("Model", model), ("Piyasa", market)], lambda i: labels[int(i)], lambda v: f"%{100 * v:.1f}")
    canvas.finish()


def plot_ratings(canvas: ChartCanvas, ratings: pd.DataFrame) -> None:
    canvas.reset("Hücum ve savunma gücü (maç başı beklenen gol)")
    ax = canvas.ax
    if ratings is None or ratings.empty or ratings["xg_for"].isna().all():
        canvas.finish()
        return
    x = ratings["xg_for"].to_numpy(dtype=float)
    y = ratings["xg_against"].to_numpy(dtype=float)
    ax.plot(x, y, "o", color=theme.SERIES_1, markersize=8, markeredgecolor=SURFACE, markeredgewidth=2)
    for xi, yi, name in zip(x, y, ratings["team"]):
        ax.annotate(name, (xi, yi), xytext=(5, 3), textcoords="offset points", color=MUTED, fontsize=7)
    ax.invert_yaxis()  # yukarı = daha az gol yiyen (iyi savunma)
    ax.set_xlabel("Atılan gol beklentisi →", color=MUTED, fontsize=8)
    ax.set_ylabel("← Yenilen gol beklentisi", color=MUTED, fontsize=8)
    canvas.fig.subplots_adjust(left=0.1, bottom=0.14)
    canvas.finish()

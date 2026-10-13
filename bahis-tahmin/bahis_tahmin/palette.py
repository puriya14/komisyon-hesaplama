"""Arayüz renkleri (Qt'den bağımsız): masaüstü teması (``ui.theme``), grafikler (``plots``) ve web arayüzü aynı
değerleri kullanır."""

from __future__ import annotations

BG = "#0e1217"
SURFACE = "#151b23"
SURFACE2 = "#1b232e"
BORDER = "#283240"
TEXT = "#e6edf3"
MUTED = "#8b98a5"
ACCENT = "#22c55e"  # arayüz vurgu rengi (butonlar, seçili menü)
ACCENT_DARK = "#15803d"
# Grafik serileri (koyu yüzey için doğrulanmış kategorik sıra: mavi, turuncu, su yeşili)
SERIES_1 = "#3987e5"
SERIES_2 = "#d95926"
SERIES_3 = "#199e70"
DRAW = "#94a3b8"  # beraberlik: nötr gri
# Durum renkleri (yalnızca iyi/kötü anlamı taşıdığında)
GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"
GRID = "#232c38"
AXIS = "#2f3a48"
BLUE = SERIES_1
AMBER = SERIES_2
RED = CRITICAL
PROB_TARGET = "#256abf"


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def prob_rgb(p: float) -> tuple[int, int, int] | None:
    """Olasılık (büyüklük) için tek tonlu ardışık renk: yüzeyden maviye. NaN için None (renk yok)."""
    if p is None or p != p:
        return None
    p = max(0.0, min(1.0, (float(p) - 0.1) / 0.75))  # %10 → yüzey, %85+ → tam ton
    (r0, g0, b0), (r1, g1, b1) = _rgb(SURFACE), _rgb(PROB_TARGET)
    return int(r0 + (r1 - r0) * p), int(g0 + (g1 - g0) * p), int(b0 + (b1 - b0) * p)


def ev_hex(ev: float) -> str | None:
    """Beklenen değer (durum anlamı: olumlu/olumsuz) için koyu arka plan tonu; renk yoksa None."""
    if ev is None or ev != ev:
        return None
    if ev >= 0.05:
        return "#12401a"
    if ev >= 0:
        return "#1a2e1f"
    if ev > -0.05:
        return None
    return "#3a1d1d"


def prob_hex(p: float) -> str | None:
    rgb = prob_rgb(p)
    return None if rgb is None else "#{:02x}{:02x}{:02x}".format(*rgb)

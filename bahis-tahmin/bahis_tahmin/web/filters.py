"""Şablon filtreleri: masaüstüyle aynı sayı biçimleri ve renk ölçekleri."""

from __future__ import annotations

import pandas as pd
from flask import Flask

from ..data.leagues import LEAGUES, league_name
from ..fmt import fmt_num, fmt_pct, fmt_signed_pct
from ..palette import ev_hex, prob_hex


def _isnan(v) -> bool:
    try:
        return v is None or v != v
    except Exception:
        return False


def prob_bg(v, scale: float = 1.0) -> str:
    """Olasılık hücresi için arka plan (``style`` niteliği); NaN için boş."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    h = prob_hex(f * scale)
    return f"background:{h}" if h else ""


def ev_bg(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    h = ev_hex(f)
    return f"background:{h}" if h else ""


def tarih(v) -> str:
    if _isnan(v) or v == "":
        return "-"
    try:
        return pd.Timestamp(v).strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return str(v)


def binlik(v, digits: int = 0) -> str:
    """Türkçe binlik ayırıcıyla sayı (12.345)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-"
    if f != f:
        return "-"
    return f"{f:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def lig(code) -> str:
    return LEAGUES[code].name if code in LEAGUES else str(code)


def register(app: Flask) -> None:
    app.jinja_env.filters.update({
        "pct": fmt_pct, "num": fmt_num, "spct": fmt_signed_pct, "prob_bg": prob_bg, "ev_bg": ev_bg,
        "tarih": tarih, "binlik": binlik, "lig": lig, "lig_tam": league_name, "isnan": _isnan,
    })
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True

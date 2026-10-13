"""Sayı biçimleri (Qt'den bağımsız): masaüstü ve web arayüzü aynı gösterimi kullanır."""

from __future__ import annotations


def fmt_pct(v, digits: int = 1) -> str:
    try:
        if v is None or v != v:
            return "-"
        return f"%{100 * float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def fmt_num(v, digits: int = 2) -> str:
    try:
        if v is None or v != v:
            return "-"
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def fmt_signed_pct(v, digits: int = 1) -> str:
    try:
        if v is None or v != v:
            return "-"
        return f"{100 * float(v):+.{digits}f}%"
    except (TypeError, ValueError):
        return "-"

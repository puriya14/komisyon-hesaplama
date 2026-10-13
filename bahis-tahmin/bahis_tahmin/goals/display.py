"""Gol pazarları ekranlarının ortak gösterim yardımcıları (Qt'den bağımsız; masaüstü ve web aynı kuralları kullanır)."""

from __future__ import annotations

import numpy as np

from ..eligibility import display_label

NAMES = {"A": "İki yarıda da KG", "B": "Maç 3,5 Üst", "C": "İlk yarı 1,5 Üst"}
KEY_OF = {"A": "BTTS_BOTH_HALVES_YES", "B": "FT_OVER_3_5", "C": "FH_OVER_1_5"}
STATUS_SHORT = {
    "VALUE_CANDIDATE": "ADAY", "NO_VALUE": "YOK", "INSUFFICIENT_DATA": "VERİ", "ODDS_UNAVAILABLE": "ORAN YOK",
    "STALE_ODDS": "ESKİ ORAN", "MARKET_UNSUPPORTED": "EŞLEŞME", "MODEL_NOT_VALIDATED": "DOĞRULANMADI",
    "HIGH_UNCERTAINTY": "BELİRSİZ", "SETTLEMENT_AMBIGUOUS": "KURAL", "SUSPICIOUS_EDGE": "KARANTİNA",
    "DATA_NOT_ELIGIBLE": "VERİ UYGUN DEĞİL",
}


def shown(verdict, now):
    """(sonuç, gösterim engeli): bu anda gösterilemeyen ilk pazar, yoksa bahsi engellenen, yoksa ilki. Gösterim
    denetimi gün, kimlik ve model durumu eşleşmesini de içerir (gün değişince eski sonuç kullanılmaz)."""
    items = [(e, verdict.display_codes(mk, now)) for mk, e in verdict.by_market.items()]
    for e, codes in items:
        if codes:
            return e, codes
    for e, codes in items:
        if not e.bet_ok:
            return e, codes
    return items[0] if items else (None, ["BAGLAM_YOK"])


def data_label(verdict, now) -> str:
    return display_label(*shown(verdict, now))[0]


def data_text(verdict, now) -> str:
    return display_label(*shown(verdict, now))[1]


def fin(v) -> float | None:
    """Sonlu sayıysa float, değilse (None/NaN/metin) None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def iv(pred, key) -> str:
    lo, hi = pred.intervals.get(key, (None, None)) if pred.intervals else (None, None)
    return f"%{100 * lo:.0f}–%{100 * hi:.0f}" if lo is not None else "-"

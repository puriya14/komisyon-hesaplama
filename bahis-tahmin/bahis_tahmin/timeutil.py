"""Zaman dilimi yardımcıları. Sistemde zamanlar açık zaman dilimiyle tutulur, kullanıcıya
Europe/Istanbul olarak gösterilir. (Windows'ta zaman dilimi veritabanı için 'tzdata' paketi gerekir.)"""

from __future__ import annotations

import datetime as dt

import pandas as pd

try:
    from zoneinfo import ZoneInfo

    ISTANBUL = ZoneInfo("Europe/Istanbul")
    LONDON = ZoneInfo("Europe/London")
    _TZ_OK = True
except Exception:  # tzdata yoksa: İstanbul sabit UTC+3 (2016'dan beri yaz saati yok)
    ISTANBUL = dt.timezone(dt.timedelta(hours=3), "Europe/Istanbul")
    LONDON = dt.timezone.utc
    _TZ_OK = False

# Fikstür kaynağına göre saatlerin yerel zaman dilimi
COUNTRY_TZ = {
    "İngiltere": "Europe/London", "İskoçya": "Europe/London", "Almanya": "Europe/Berlin",
    "İtalya": "Europe/Rome", "İspanya": "Europe/Madrid", "Fransa": "Europe/Paris",
    "Hollanda": "Europe/Amsterdam", "Belçika": "Europe/Brussels", "Portekiz": "Europe/Lisbon",
    "Türkiye": "Europe/Istanbul", "Yunanistan": "Europe/Athens", "Avusturya": "Europe/Vienna",
    "İsviçre": "Europe/Zurich", "Danimarka": "Europe/Copenhagen",
}


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def kickoff_utc(date, time_str: str, source: str, country: str = "") -> dt.datetime | None:
    """Fikstür saatini UTC'ye çevirir. Saat yoksa None (yalnızca tarih bilinir)."""
    if not time_str or not isinstance(time_str, str) or ":" not in time_str:
        return None
    try:
        hh, mm = (int(x) for x in time_str.split(":")[:2])
    except ValueError:
        return None
    d = pd.Timestamp(date).date()
    if source == "football-data.co.uk":
        tz = LONDON  # football-data.co.uk saatleri İngiltere saatidir
    else:
        name = COUNTRY_TZ.get(country, "Europe/London")
        try:
            tz = ZoneInfo(name) if _TZ_OK else dt.timezone.utc
        except Exception:
            tz = dt.timezone.utc
    return dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).astimezone(dt.timezone.utc)


def fmt_istanbul(t: dt.datetime | None, date=None) -> str:
    """Kullanıcıya gösterim: 'gg.aa.yyyy SS:DD (İstanbul)'; saat yoksa yalnızca tarih."""
    if t is None:
        return pd.Timestamp(date).strftime("%d.%m.%Y") + " (saat bilinmiyor)" if date is not None else "-"
    return t.astimezone(ISTANBUL).strftime("%d.%m.%Y %H:%M")

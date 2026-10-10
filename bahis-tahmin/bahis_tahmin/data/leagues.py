"""Desteklenen ligler ve sezon kodu yardımcıları.

Ana ligler football-data.co.uk/mmz4281/{sezon}/{kod}.csv dosyalarından,
ek ligler ise football-data.co.uk/new/{dosya}.csv (tüm sezonlar tek dosya)
dosyalarından gelir.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class League:
    code: str
    name: str
    country: str
    tier: int
    kind: str = "main"  # "main" (sezonluk dosyalar) veya "extra" (tek dosya)
    fd_file: str = ""  # ek ligler için football-data.co.uk dosya adı
    mirror_code: str = ""  # GitHub yedek veri setindeki kod
    openfootball: str = ""  # openfootball fikstür kodu (ör. "en.1")
    calendar_year: bool = False  # sezon takvim yılına göre mi (ör. Brezilya)

    @property
    def label(self) -> str:
        return f"{self.country} - {self.name}"


_MAIN = [
    League("T1", "Süper Lig", "Türkiye", 1, openfootball="tr.1"),
    League("E0", "Premier League", "İngiltere", 1, openfootball="en.1"),
    League("E1", "Championship", "İngiltere", 2, openfootball="en.2"),
    League("E2", "League One", "İngiltere", 3, openfootball="en.3"),
    League("E3", "League Two", "İngiltere", 4, openfootball="en.4"),
    League("EC", "National League", "İngiltere", 5),
    League("SC0", "Premiership", "İskoçya", 1, openfootball="sco.1"),
    League("SC1", "Championship", "İskoçya", 2),
    League("SC2", "League One", "İskoçya", 3),
    League("SC3", "League Two", "İskoçya", 4),
    League("D1", "Bundesliga", "Almanya", 1, openfootball="de.1"),
    League("D2", "2. Bundesliga", "Almanya", 2, openfootball="de.2"),
    League("I1", "Serie A", "İtalya", 1, openfootball="it.1"),
    League("I2", "Serie B", "İtalya", 2, openfootball="it.2"),
    League("SP1", "La Liga", "İspanya", 1, openfootball="es.1"),
    League("SP2", "La Liga 2", "İspanya", 2, openfootball="es.2"),
    League("F1", "Ligue 1", "Fransa", 1, openfootball="fr.1"),
    League("F2", "Ligue 2", "Fransa", 2, openfootball="fr.2"),
    League("N1", "Eredivisie", "Hollanda", 1, openfootball="nl.1"),
    League("B1", "Pro League", "Belçika", 1, openfootball="be.1"),
    League("P1", "Liga Portugal", "Portekiz", 1, openfootball="pt.1"),
    League("G1", "Super League", "Yunanistan", 1, openfootball="gr.1"),
]

_EXTRA = [
    League("ARG", "Liga Profesional", "Arjantin", 1, "extra", "ARG", "ARG", calendar_year=True),
    League("AUT", "Bundesliga", "Avusturya", 1, "extra", "AUT", "AUT", "at.1"),
    League("BRA", "Serie A", "Brezilya", 1, "extra", "BRA", "BRA", "br.1", calendar_year=True),
    League("CHN", "Super League", "Çin", 1, "extra", "CHN", "CHN", calendar_year=True),
    League("DNK", "Superliga", "Danimarka", 1, "extra", "DNK", "DEN", "dk.1"),
    League("FIN", "Veikkausliiga", "Finlandiya", 1, "extra", "FIN", "FIN", calendar_year=True),
    League("IRL", "Premier Division", "İrlanda", 1, "extra", "IRL", "IRL", calendar_year=True),
    League("JPN", "J1 League", "Japonya", 1, "extra", "JPN", "JAP", calendar_year=True),
    League("MEX", "Liga MX", "Meksika", 1, "extra", "MEX", "MEX"),
    League("NOR", "Eliteserien", "Norveç", 1, "extra", "NOR", "NOR", calendar_year=True),
    League("POL", "Ekstraklasa", "Polonya", 1, "extra", "POL", "POL"),
    League("ROU", "Liga 1", "Romanya", 1, "extra", "ROU", "ROM"),
    League("RUS", "Premier Liga", "Rusya", 1, "extra", "RUS", "RUS"),
    League("SWE", "Allsvenskan", "İsveç", 1, "extra", "SWE", "SWE", calendar_year=True),
    League("SWZ", "Super League", "İsviçre", 1, "extra", "SWZ", "SUI", "ch.1"),
    League("USA", "MLS", "ABD", 1, "extra", "USA", "USA", calendar_year=True),
]

LEAGUES: dict[str, League] = {lg.code: lg for lg in _MAIN + _EXTRA}
MIRROR_TO_CODE: dict[str, str] = {(lg.mirror_code or lg.code): lg.code for lg in LEAGUES.values()}


def league_name(code: str) -> str:
    lg = LEAGUES.get(code)
    return lg.label if lg else code


def season_start_year(date: dt.date) -> int:
    """Avrupa takvimine göre sezonun başladığı yıl (Temmuz ve sonrası yeni sezon)."""
    return date.year if date.month >= 7 else date.year - 1


def season_code(start_year: int) -> str:
    """2025 -> "2526" (football-data.co.uk URL'lerindeki sezon kodu)."""
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def season_label(start_year: int, calendar_year: bool = False) -> str:
    """Veride saklanan sezon etiketi: "2025/26" ya da takvim yılı ligleri için "2025"."""
    if calendar_year:
        return str(start_year)
    return f"{start_year}/{(start_year + 1) % 100:02d}"


def season_for_date(date: dt.date, calendar_year: bool) -> str:
    if calendar_year:
        return season_label(date.year, True)
    return season_label(season_start_year(date))


def recent_season_starts(years_back: int, today: dt.date | None = None) -> list[int]:
    """Son `years_back` tamamlanmış sezon + içinde bulunulan sezonun başlangıç yılları."""
    today = today or dt.date.today()
    cur = season_start_year(today)
    return list(range(cur - years_back, cur + 1))


def openfootball_season(today: dt.date | None = None, calendar_year: bool = False) -> str:
    today = today or dt.date.today()
    if calendar_year:
        return str(today.year)
    y = season_start_year(today)
    return f"{y}-{(y + 1) % 100:02d}"

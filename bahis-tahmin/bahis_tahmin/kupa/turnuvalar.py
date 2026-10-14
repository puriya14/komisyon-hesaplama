"""Desteklenen kupa turnuvaları (KUPA-01).

ESPN lig kodları, ESPN lig listesinin topluluk derlemesinden doğrulandı (pseudo-r/Public-ESPN-API,
``docs/sports/soccer.md``; 2026-10-14). Listede olmayan kodlar ``unverified`` işaretlidir: ESPN bu kodu vermezse
güncelleme raporu bunu yazar ve turnuva için veri alınmaz (uydurulmaz).

openfootball (CC0) yalnızca UEFA turnuvalarının geçmiş sezonlarını içerir (``openfootball/champions-league``:
Şampiyonlar Ligi 2011/12'den, Avrupa Ligi 2020/21'den, Konferans Ligi 2021/22'den, eleme turları 2024/25'ten).
Güncel sezonun fikstür ve sonuçları ESPN'den (kullanıcı onayıyla) gelir.

Gruplar (modeldeki iç saha avantajı ve doğrulama grupları):

* ``U``: UEFA ana turnuvaları (lig/grup aşaması ve sonrası)
* ``Q``: UEFA eleme turları
* ``C``: yurt içi kupalar ve süper kupalar
* ``K``: diğer kıtaların kulüp turnuvaları
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

GROUPS = ("U", "Q", "C", "K")
GROUP_NAMES = {"U": "UEFA turnuvaları", "Q": "UEFA eleme turları", "C": "Yurt içi kupalar",
               "K": "Diğer kıtaların kulüp turnuvaları"}
# Doğrulama (model statüsü) grupları: eleme turları kendi ana turnuvasıyla birlikte değerlendirilir
VALIDATION_GROUPS = {"U": "UEFA", "Q": "UEFA", "C": "YURTICI", "K": "KITA"}
VALIDATION_NAMES = {"UEFA": "UEFA turnuvaları (elemeler dahil)", "YURTICI": "Yurt içi kupalar ve süper kupalar",
                    "KITA": "Diğer kıtaların kulüp turnuvaları"}
UEFA_REGION = "UEFA"


@dataclass(frozen=True)
class Competition:
    code: str
    name: str  # kısa Türkçe ad (listelerde)
    full: str  # uzun ad
    group: str  # GROUPS
    region: str  # "UEFA", ülke adı (yurt içi kupa) veya kıta konfederasyonu
    espn: str = ""  # ESPN lig kodu
    of_stem: str = ""  # openfootball/champions-league dosya adı (ör. "cl" -> 2025-26/cl.txt)
    country: str = ""  # yurt içi kupanın ülkesi (takım kimliği kapsamı ve saat dilimi)
    calendar_year: bool = False  # sezon takvim yılına göre
    unverified: bool = False  # ESPN kodu listede yok (ülke.kupa düzenine göre yazıldı)
    default: bool = True
    super_cup: bool = False  # tek maçlık süper kupa (ESPN tarafsız saha bilgisine bakılır)

    @property
    def label(self) -> str:
        return self.full


_ALL = [
    # UEFA
    Competition("UCL", "Şampiyonlar Ligi", "UEFA Şampiyonlar Ligi", "U", UEFA_REGION, "uefa.champions", "cl"),
    Competition("UCLQ", "Şampiyonlar Ligi (eleme)", "UEFA Şampiyonlar Ligi eleme turları", "Q", UEFA_REGION,
                "uefa.champions_qual", "clq"),
    Competition("UEL", "Avrupa Ligi", "UEFA Avrupa Ligi", "U", UEFA_REGION, "uefa.europa", "el"),
    Competition("UELQ", "Avrupa Ligi (eleme)", "UEFA Avrupa Ligi eleme turları", "Q", UEFA_REGION,
                "uefa.europa_qual", "elq"),
    Competition("UECL", "Konferans Ligi", "UEFA Konferans Ligi", "U", UEFA_REGION, "uefa.europa.conf", "conf"),
    Competition("UECLQ", "Konferans Ligi (eleme)", "UEFA Konferans Ligi eleme turları", "Q", UEFA_REGION,
                "uefa.europa.conf_qual", "confq"),
    Competition("USC", "UEFA Süper Kupa", "UEFA Süper Kupa", "U", UEFA_REGION, "uefa.super_cup", super_cup=True),
    # Yurt içi kupalar (uygulamanın varsayılan liglerinin ülkeleri)
    Competition("TRC", "Türkiye Kupası", "Türkiye Kupası", "C", "Türkiye", "tur.cup", country="Türkiye",
                unverified=True),
    Competition("FAC", "FA Cup", "İngiltere FA Cup", "C", "İngiltere", "eng.fa", country="İngiltere"),
    Competition("EFL", "Lig Kupası (İngiltere)", "İngiltere Lig Kupası (Carabao Cup)", "C", "İngiltere",
                "eng.league_cup", country="İngiltere"),
    Competition("ENGS", "Community Shield", "İngiltere FA Community Shield", "C", "İngiltere", "eng.charity",
                country="İngiltere", super_cup=True),
    Competition("CDR", "Kral Kupası", "İspanya Kral Kupası (Copa del Rey)", "C", "İspanya", "esp.copa_del_rey",
                country="İspanya"),
    Competition("ESPS", "İspanya Süper Kupası", "İspanya Süper Kupası (Supercopa)", "C", "İspanya",
                "esp.super_cup", country="İspanya", super_cup=True),
    Competition("DFB", "Almanya Kupası", "Almanya Kupası (DFB-Pokal)", "C", "Almanya", "ger.dfb_pokal",
                country="Almanya"),
    Competition("GERS", "Almanya Süper Kupası", "Almanya Süper Kupası (DFL-Supercup)", "C", "Almanya",
                "ger.super_cup", country="Almanya", super_cup=True),
    Competition("CIT", "İtalya Kupası", "İtalya Kupası (Coppa Italia)", "C", "İtalya", "ita.coppa_italia",
                country="İtalya"),
    Competition("ITAS", "İtalya Süper Kupası", "İtalya Süper Kupası (Supercoppa)", "C", "İtalya", "ita.super_cup",
                country="İtalya", super_cup=True),
    Competition("CDF", "Fransa Kupası", "Fransa Kupası (Coupe de France)", "C", "Fransa", "fra.coupe_de_france",
                country="Fransa"),
    Competition("FRAS", "Fransa Süper Kupası", "Fransa Şampiyonlar Kupası (Trophée des Champions)", "C", "Fransa",
                "fra.super_cup", country="Fransa", super_cup=True),
    Competition("KNVB", "Hollanda Kupası", "Hollanda Kupası (KNVB Beker)", "C", "Hollanda", "ned.cup",
                country="Hollanda"),
    Competition("NEDS", "Johan Cruyff Kalkanı", "Hollanda Süper Kupası (Johan Cruyff Kalkanı)", "C", "Hollanda",
                "ned.supercup", country="Hollanda", super_cup=True),
    Competition("TDP", "Portekiz Kupası", "Portekiz Kupası (Taça de Portugal)", "C", "Portekiz",
                "por.taca.portugal", country="Portekiz"),
    Competition("SCOC", "İskoçya Kupası", "İskoçya Kupası (Scottish Cup)", "C", "İskoçya", "sco.tennents",
                country="İskoçya"),
    Competition("SCOL", "İskoçya Lig Kupası", "İskoçya Lig Kupası", "C", "İskoçya", "sco.cis", country="İskoçya"),
    Competition("BELC", "Belçika Kupası", "Belçika Kupası", "C", "Belçika", "bel.cup", country="Belçika",
                unverified=True),
    Competition("GREC", "Yunanistan Kupası", "Yunanistan Kupası", "C", "Yunanistan", "gre.cup", country="Yunanistan",
                unverified=True),
    # Diğer kıtalar (ilgili ligler seçilmedikçe kapalı)
    Competition("LIB", "Copa Libertadores", "CONMEBOL Copa Libertadores", "K", "CONMEBOL", "conmebol.libertadores",
                calendar_year=True, default=False),
    Competition("SUD", "Copa Sudamericana", "CONMEBOL Copa Sudamericana", "K", "CONMEBOL", "conmebol.sudamericana",
                calendar_year=True, default=False),
    Competition("ARGC", "Arjantin Kupası", "Arjantin Kupası (Copa Argentina)", "C", "Arjantin", "arg.copa",
                country="Arjantin", calendar_year=True, default=False),
    Competition("BRAC", "Brezilya Kupası", "Brezilya Kupası (Copa do Brasil)", "C", "Brezilya", "bra.copa_do_brazil",
                country="Brezilya", calendar_year=True, default=False),
    Competition("CONC", "CONCACAF Şampiyonlar Kupası", "CONCACAF Şampiyonlar Kupası", "K", "CONCACAF",
                "concacaf.champions", calendar_year=True, default=False),
    Competition("LCUP", "Leagues Cup", "Leagues Cup (MLS - Liga MX)", "K", "CONCACAF", "concacaf.leagues.cup",
                calendar_year=True, default=False),
    Competition("USOC", "ABD Açık Kupası", "ABD Açık Kupası (U.S. Open Cup)", "C", "ABD", "usa.open", country="ABD",
                calendar_year=True, default=False),
    Competition("AFC", "AFC Şampiyonlar Ligi", "AFC Şampiyonlar Ligi Elite", "K", "AFC", "afc.champions",
                default=False),
]

COMPETITIONS: dict[str, Competition] = {c.code: c for c in _ALL}
DEFAULT_COMPETITIONS: list[str] = [c.code for c in _ALL if c.default]
# Ana turnuvanın eleme turları (arayüzde birlikte seçilir)
QUALIFIERS = {"UCL": "UCLQ", "UEL": "UELQ", "UECL": "UECLQ"}

# openfootball'un FIFA ülke kodları -> uygulamanın ülke adları (yalnızca ligleri uygulamada olan ülkeler). Monaco
# Fransa liginde, Liechtenstein kulüpleri İsviçre liginde oynar. Galler kulüpleri (WAL) UEFA turnuvalarına kendi
# liglerinden gelir (İngiliz liglerindeki Galler kulüpleri ESPN'de kanıtla eşlenir): kapsam dışı sayılır.
CC_COUNTRY = {
    "ENG": "İngiltere", "SCO": "İskoçya", "GER": "Almanya", "ITA": "İtalya", "ESP": "İspanya", "FRA": "Fransa",
    "MCO": "Fransa", "NED": "Hollanda", "BEL": "Belçika", "POR": "Portekiz", "GRE": "Yunanistan", "TUR": "Türkiye",
    "AUT": "Avusturya", "DEN": "Danimarka", "SUI": "İsviçre", "LIE": "İsviçre", "SWE": "İsveç", "NOR": "Norveç",
    "POL": "Polonya", "ROU": "Romanya", "RUS": "Rusya", "FIN": "Finlandiya", "IRL": "İrlanda",
}


def competition_name(code: str) -> str:
    c = COMPETITIONS.get(code)
    return c.name if c else str(code)


def is_cup(code) -> bool:
    return str(code) in COMPETITIONS


def season_start(date: dt.date, calendar_year: bool = False) -> int:
    if calendar_year:
        return date.year
    return date.year if date.month >= 7 else date.year - 1


def season_label(start: int, calendar_year: bool = False) -> str:
    return str(start) if calendar_year else f"{start}/{(start + 1) % 100:02d}"


def season_bounds(start: int, calendar_year: bool = False) -> tuple[dt.date, dt.date]:
    """Sezon penceresi (eleme turları Haziran sonunda başlayabilir)."""
    if calendar_year:
        return dt.date(start, 1, 1), dt.date(start, 12, 31)
    return dt.date(start, 6, 15), dt.date(start + 1, 6, 30)


def openfootball_dir(start: int) -> str:
    """openfootball sezon klasörü: 2025 -> "2025-26"."""
    return f"{start}-{(start + 1) % 100:02d}"


def default_for_leagues(leagues) -> list[str]:
    """Seçili liglere göre varsayılan turnuvalar: UEFA her zaman; yurt içi kupa yalnızca ülkesinin ligi seçiliyse;
    diğer kıtaların turnuvaları o kıtanın bir ligi seçiliyse."""
    from ..data.leagues import LEAGUES

    countries = {LEAGUES[c].country for c in leagues if c in LEAGUES}
    out = []
    for c in _ALL:
        if c.region == UEFA_REGION:
            out.append(c.code)
        elif c.group == "C" and c.country in countries:
            out.append(c.code)
        elif c.code in ("LIB", "SUD") and countries & {"Arjantin", "Brezilya"}:
            out.append(c.code)
        elif c.code in ("CONC", "LCUP") and countries & {"Meksika", "ABD"}:
            out.append(c.code)
        elif c.code == "AFC" and countries & {"Japonya", "Çin"}:
            out.append(c.code)
    return out

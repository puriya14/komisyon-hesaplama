"""Farklı kaynaklardaki takım adlarını eşleştirme (yalnızca yedek fikstür kaynağı için)."""

from __future__ import annotations

import difflib
import re
import unicodedata

_STOP = {
    "fc", "cf", "afc", "sc", "ac", "as", "ssc", "ss", "cd", "ud", "sd", "rcd", "rc", "club",
    "de", "del", "la", "calcio", "sv", "vfb", "vfl", "tsg", "fsv", "bsc", "ogc", "cfc",
    "sk", "fk", "jk", "kv", "krc", "rsc", "sco", "aj", "us", "if", "bk", "ik", "cp",
    "the", "and", "1", "04", "05", "1846", "1899", "1907", "1909", "1910", "1913", "92",
}

# openfootball adı (normalize) -> football-data.co.uk adı
ALIASES = {
    "manchester united": "Man United", "manchester city": "Man City",
    "nottingham forest": "Nott'm Forest", "wolverhampton wanderers": "Wolves",
    "brighton hove albion": "Brighton", "tottenham hotspur": "Tottenham",
    "west ham united": "West Ham", "newcastle united": "Newcastle",
    "leeds united": "Leeds", "sheffield wednesday": "Sheffield Weds",
    "sheffield united": "Sheffield United", "queens park rangers": "QPR",
    "west bromwich albion": "West Brom", "leicester city": "Leicester",
    "bournemouth": "Bournemouth", "ipswich town": "Ipswich", "luton town": "Luton",
    "bayern munchen": "Bayern Munich", "borussia dortmund": "Dortmund",
    "borussia monchengladbach": "M'gladbach", "bayer leverkusen": "Leverkusen",
    "eintracht frankfurt": "Ein Frankfurt", "koln": "FC Koln", "mainz": "Mainz",
    "hoffenheim": "Hoffenheim", "union berlin": "Union Berlin", "st pauli": "St Pauli",
    "heidenheim": "Heidenheim", "hamburger": "Hamburg", "hertha": "Hertha",
    "atletico madrid": "Ath Madrid", "athletic": "Ath Bilbao", "athletic bilbao": "Ath Bilbao",
    "real betis": "Betis", "celta vigo": "Celta", "real sociedad": "Sociedad",
    "rayo vallecano": "Vallecano", "espanyol": "Espanol", "deportivo alaves": "Alaves",
    "real oviedo": "Oviedo", "sporting gijon": "Sp Gijon", "deportivo coruna": "La Coruna",
    "internazionale milano": "Inter", "internazionale": "Inter", "milan": "Milan",
    "hellas verona": "Verona", "paris saint germain": "Paris SG", "marseille": "Marseille",
    "olympique marseille": "Marseille", "olympique lyonnais": "Lyon", "saint etienne": "St Etienne",
    "stade rennais": "Rennes", "stade brestois 29": "Brest", "losc lille": "Lille",
    "istanbul basaksehir": "Buyuksehyr", "basaksehir": "Buyuksehyr", "goztepe": "Goztep",
    "fatih karagumruk": "Karagumruk", "caykur rizespor": "Rizespor", "adana demirspor": "Ad. Demirspor",
    "psv": "PSV Eindhoven", "psv eindhoven": "PSV Eindhoven", "az alkmaar": "AZ Alkmaar",
    "sporting cp": "Sp Lisbon", "sporting lisbon": "Sp Lisbon", "sporting braga": "Sp Braga",
    "braga": "Sp Braga", "vitoria guimaraes": "Guimaraes", "benfica": "Benfica", "porto": "Porto",
    "club brugge": "Club Brugge", "royal antwerp": "Antwerp", "rangers": "Rangers", "celtic": "Celtic",
    "olympiacos": "Olympiakos", "olympiakos piraeus": "Olympiakos", "paok": "PAOK", "aek athens": "AEK",
    # openfootball 2026-27 adları (S2-KABUL-01 gerçek fikstür denetiminde eşleşmeyenler)
    "nec": "Nijmegen", "nec nijmegen": "Nijmegen", "stade rennais 1901": "Rennes",
    "sport lisboa e benfica": "Benfica", "sporting clube portugal": "Sp Lisbon",
}


def norm_key(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    s = s.lower().replace("&", " and ").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    tokens = [t for t in s.split() if t not in _STOP]
    return " ".join(tokens)


def _tokens_match(a: list[str], b: list[str]) -> bool:
    """Kısa adın her kelimesi uzun adın bir kelimesinin başlangıcı mı."""
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if not short:
        return False
    return all(any(lt.startswith(st) or st.startswith(lt) for lt in long_) for st in short)


def match_team(name: str, candidates: list[str]) -> str | None:
    """`name` için `candidates` listesinden en uygun takımı bulur; emin değilse None."""
    if not candidates:
        return None
    if name in candidates:
        return name
    key = norm_key(name)
    by_key = {norm_key(c): c for c in candidates}
    if key in by_key:
        return by_key[key]
    alias = ALIASES.get(key)
    if alias and alias in candidates:
        return alias
    toks = key.split()
    hits = [c for k, c in by_key.items() if _tokens_match(toks, k.split())]
    if len(hits) == 1:
        return hits[0]
    pool = hits or list(by_key)
    scored = sorted(
        ((difflib.SequenceMatcher(None, key, norm_key(c)).ratio(), c) for c in pool), reverse=True
    )
    if scored and scored[0][0] >= 0.75 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08):
        return scored[0][1]
    return None

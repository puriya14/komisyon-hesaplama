"""Farklı kaynaklardaki takım adlarını eşleştirme (yalnızca yedek fikstür/takvim kaynağı için).

Kimlik sözleşmesi (``MATCHING_VERSION``, S3-GATE-02):

* **Kesin kimlik** (``KESIN``) yalnızca şu kanıtlardan biriyle kurulur: bağlamda (ör. ligin son iki sezonundaki
  takımlar) normalleştirilmiş adı BENZERSİZ olan tam ad eşleşmesi (``ayni_ad`` / ``normal_ad``) veya kapsamı (kaynak
  ve ülke/lig) tutan doğrulanmış takma ad (``takma_ad``). Sağlayıcı olay/takım kimliği bu kaynaklarda yoktur.
* Aynı normalleştirilmiş ada sahip birden çok aday varsa sonuç **belirsizdir** (``BELIRSIZ``); son, alfabetik veya
  sıradaki aday seçilmez. Aynı bağlamda birden çok farklı kaynak adı aynı takıma düşüyorsa (doğrulanmış takma adlar
  hariç) bu adlar da belirsiz sayılır.
* Önek veya benzerlik eşleşmesi yalnızca **öneri** (``suggestions``) üretir; kanonik takımı seçemez ve uygunluk
  kontrolünden geçemez. Tek harfli ad parçaları kimlik kanıtı değildir.
* Kategori ayrımları (rezerv/II/B, U21/U19 gibi yaş, kadın takımı) korunur: farklı kategoriler eşleşmez, öneri de
  olmaz. Boş adlar hiçbir şeyle eşleşmez.

``match_team`` geriye uyumlu imzayla yalnızca kesin kimliği döndürür (emin değilse ``None``).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, replace

MATCHING_VERSION = "takim-eslesme-v2"  # v1: önek/benzerlik ile takım seçebilen eski eşleyici (S3-GATE-02 öncesi)

KESIN = "KESIN"
BELIRSIZ = "BELIRSIZ"
BULUNAMADI = "BULUNAMADI"

_STOP = {
    "fc", "cf", "afc", "sc", "ac", "as", "ssc", "ss", "cd", "ud", "sd", "rcd", "rc", "club",
    "de", "del", "la", "calcio", "sv", "vfb", "vfl", "tsg", "fsv", "bsc", "ogc", "cfc",
    "sk", "fk", "jk", "kv", "krc", "rsc", "sco", "aj", "us", "if", "bk", "ik", "cp",
    "the", "and", "1", "04", "05", "1846", "1899", "1907", "1909", "1910", "1913", "92",
}

# Takımın kategorisini belirten ad parçaları: kategorisi farklı adlar hiçbir koşulda eşleşmez
_CATEGORY = {
    "ii", "iii", "b", "c", "reserve", "reserves", "res", "jong", "youth", "academy", "academia", "primavera",
    "juvenil", "junior", "juniors", "sub", "women", "woman", "ladies", "w", "wfc", "fem", "femenino", "feminino",
    "feminin", "feminine", "frauen", "damen", "kadin", "kadinlar", "dames", "vrouwen", "amateure", "castilla",
    "atletic", "futuro",
}
_AGE = re.compile(r"^u\d{1,2}$")

# NFKD ile ayrışmayan harfler (ör. Türkçe noktasız ı) ASCII'ye dönüştürülürken düşmesin
_FOLD = str.maketrans({"ı": "i", "ø": "o", "Ø": "O", "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
                       "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ð": "d", "þ": "th", "Þ": "TH"})

# Doğrulanmış takma adlar: openfootball adı (normalize) -> football-data.co.uk adı. Kapsam: kaynak openfootball,
# ülke aşağıdaki gruptaki lig ülkesi; hedef ad yalnızca bağlamdaki adaylar arasında (ligin son iki sezonu) varsa
# uygulanır. Sezon bazlı takma ad yoktur: aynı adı taşıyan yeniden kurulmuş kulüpler football-data'da da aynı adla
# tutulduğundan addan ayırt edilemez (açık sınırlama, raporda).
ALIAS_SOURCE = "openfootball"
ALIASES_BY_COUNTRY: dict[str, dict[str, str]] = {
    "İngiltere": {
        "manchester united": "Man United", "manchester city": "Man City", "nottingham forest": "Nott'm Forest",
        "wolverhampton wanderers": "Wolves", "brighton hove albion": "Brighton", "tottenham hotspur": "Tottenham",
        "west ham united": "West Ham", "newcastle united": "Newcastle", "leeds united": "Leeds",
        "sheffield wednesday": "Sheffield Weds", "sheffield united": "Sheffield United",
        "queens park rangers": "QPR", "west bromwich albion": "West Brom", "leicester city": "Leicester",
        "bournemouth": "Bournemouth", "ipswich town": "Ipswich", "luton town": "Luton",
    },
    "Almanya": {
        "bayern munchen": "Bayern Munich", "borussia dortmund": "Dortmund", "borussia monchengladbach": "M'gladbach",
        "bayer leverkusen": "Leverkusen", "eintracht frankfurt": "Ein Frankfurt", "koln": "FC Koln", "mainz": "Mainz",
        "hoffenheim": "Hoffenheim", "union berlin": "Union Berlin", "st pauli": "St Pauli", "heidenheim": "Heidenheim",
        "hamburger": "Hamburg", "hertha": "Hertha",
    },
    "İspanya": {
        "atletico madrid": "Ath Madrid", "athletic": "Ath Bilbao", "athletic bilbao": "Ath Bilbao",
        "real betis": "Betis", "celta vigo": "Celta", "real sociedad": "Sociedad", "rayo vallecano": "Vallecano",
        "espanyol": "Espanol", "deportivo alaves": "Alaves", "real oviedo": "Oviedo", "sporting gijon": "Sp Gijon",
        "deportivo coruna": "La Coruna",
    },
    "İtalya": {
        "internazionale milano": "Inter", "internazionale": "Inter", "milan": "Milan", "hellas verona": "Verona",
    },
    "Fransa": {
        "paris saint germain": "Paris SG", "marseille": "Marseille", "olympique marseille": "Marseille",
        "olympique lyonnais": "Lyon", "saint etienne": "St Etienne", "stade rennais": "Rennes",
        "stade brestois 29": "Brest", "losc lille": "Lille", "stade rennais 1901": "Rennes",
    },
    "Türkiye": {
        "istanbul basaksehir": "Buyuksehyr", "basaksehir": "Buyuksehyr", "goztepe": "Goztep",
        "fatih karagumruk": "Karagumruk", "caykur rizespor": "Rizespor", "adana demirspor": "Ad. Demirspor",
    },
    "Hollanda": {
        "psv": "PSV Eindhoven", "psv eindhoven": "PSV Eindhoven", "az alkmaar": "AZ Alkmaar",
        "nec": "Nijmegen", "nec nijmegen": "Nijmegen",
    },
    "Portekiz": {
        "sporting cp": "Sp Lisbon", "sporting lisbon": "Sp Lisbon", "sporting braga": "Sp Braga", "braga": "Sp Braga",
        "vitoria guimaraes": "Guimaraes", "benfica": "Benfica", "porto": "Porto",
        "sport lisboa e benfica": "Benfica", "sporting clube portugal": "Sp Lisbon",
    },
    "Belçika": {"club brugge": "Club Brugge", "royal antwerp": "Antwerp"},
    "İskoçya": {"rangers": "Rangers", "celtic": "Celtic"},
    "Yunanistan": {
        "olympiacos": "Olympiakos", "olympiakos piraeus": "Olympiakos", "paok": "PAOK", "aek athens": "AEK",
    },
}
# Geriye uyumlu düz görünüm (ülke kapsamı olmadan)
ALIASES: dict[str, str] = {k: v for group in ALIASES_BY_COUNTRY.values() for k, v in group.items()}


def norm_key(name) -> str:
    s = "" if name is None else str(name)
    s = unicodedata.normalize("NFKD", s.translate(_FOLD)).encode("ascii", "ignore").decode("ascii")
    s = s.lower().replace("&", " and ").replace("'", "")
    s = re.sub(r"\b([a-z])\.", r"\1", s)  # "F.C." -> "fc", "A.C. Milan" -> "ac milan"
    s = re.sub(r"[^a-z0-9]+", " ", s)
    tokens = [t for t in s.split() if t not in _STOP]
    return " ".join(tokens)


def category(key: str) -> frozenset:
    """Normalleştirilmiş adın kategori parçaları (rezerv, yaş grubu, kadın takımı)."""
    return frozenset(t for t in key.split() if t in _CATEGORY or _AGE.match(t))


def _identity_key(key: str) -> bool:
    """Kimlik kanıtı olabilecek ad: en az bir parçası iki harf veya daha uzun."""
    return any(len(t) >= 2 for t in key.split())


@dataclass(frozen=True)
class TeamMatch:
    """Bir kaynak adının bağlamdaki takım kimliği. ``team`` yalnızca ``status == KESIN`` iken doludur."""
    name: str
    team: str | None
    status: str  # KESIN / BELIRSIZ / BULUNAMADI
    basis: str = ""  # ayni_ad / normal_ad / takma_ad / ters_cakisma
    candidates: tuple[str, ...] = ()  # BELIRSIZ: aynı kanıtla eşleşen takımlar
    suggestions: tuple[str, ...] = ()  # yalnızca öneri; kimlik kanıtı DEĞİLDİR

    @property
    def exact(self) -> bool:
        return self.status == KESIN and self.team is not None

    def evidence(self) -> str:
        return f"{MATCHING_VERSION}:{self.status}:{self.basis or '-'}"


def _alias(key: str, league: str | None, source: str | None) -> str | None:
    if source is not None and source != ALIAS_SOURCE:
        return None
    if league is None:
        return ALIASES.get(key)
    from .leagues import LEAGUES

    lg = LEAGUES.get(league)
    if lg is None:
        return None
    return ALIASES_BY_COUNTRY.get(lg.country, {}).get(key)


def _suggest(key: str, groups: dict[str, list[str]], limit: int = 3) -> tuple[str, ...]:
    toks = [t for t in key.split() if len(t) >= 2]  # tek harfli parça kanıt sayılmaz
    if not toks:
        return ()
    cat = category(key)
    scored = []
    for k, cands in groups.items():
        if category(k) != cat:
            continue
        other = [t for t in k.split() if len(t) >= 2]
        if not other:
            continue
        short, long_ = (toks, other) if len(toks) <= len(other) else (other, toks)
        prefix = all(any(lt.startswith(st) or st.startswith(lt) for lt in long_) for st in short)
        ratio = difflib.SequenceMatcher(None, key, k).ratio()
        if prefix or ratio >= 0.75:
            scored.extend((ratio + (1.0 if prefix else 0.0), c) for c in cands)
    return tuple(c for _, c in sorted(scored, key=lambda x: (-x[0], x[1]))[:limit])


def _groups(candidates) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for c in dict.fromkeys(str(x).strip() for x in (candidates or ()) if x is not None):
        k = norm_key(c)
        if c and _identity_key(k):
            groups.setdefault(k, []).append(c)
    return groups


def resolve_team(name, candidates, league: str | None = None, source: str | None = None,
                 _groups_cache: dict | None = None) -> TeamMatch:
    """``name`` için ``candidates`` bağlamında kimlik kararı (bkz. modül açıklaması)."""
    raw = "" if name is None else str(name).strip()
    key = norm_key(raw)
    groups = _groups_cache if _groups_cache is not None else _groups(candidates)
    if not raw or not _identity_key(key):
        return TeamMatch(raw, None, BULUNAMADI)
    same = groups.get(key, [])
    if len(same) == 1:
        return TeamMatch(raw, same[0], KESIN, "ayni_ad" if same[0] == raw else "normal_ad")
    if len(same) > 1:
        return TeamMatch(raw, None, BELIRSIZ, "", tuple(sorted(same)))
    target = _alias(key, league, source)
    if target is not None:
        hits = [c for cs in groups.values() for c in cs if c == target]
        if len(hits) == 1 and category(norm_key(target)) == category(key):
            return TeamMatch(raw, target, KESIN, "takma_ad")
    return TeamMatch(raw, None, BULUNAMADI, "", (), _suggest(key, groups))


def resolve_teams(names, candidates, league: str | None = None, source: str | None = None) -> dict[str, TeamMatch]:
    """Aynı bağlamdaki (ör. bir kaynak dosyasının) bütün adlar için kimlik kararı.

    Birden çok farklı ad aynı takıma düşüyorsa, en fazla biri doğrulanmış takma ad dışındaki bir kanıta dayanabilir;
    aksi halde hangisinin o takım olduğu bilinemez ve bu adların hepsi ``BELIRSIZ`` olur."""
    groups = _groups(candidates)
    out = {n: resolve_team(n, candidates, league, source, groups) for n in dict.fromkeys(
        "" if n is None else str(n) for n in names)}
    by_team: dict[str, list[str]] = {}
    for n, m in out.items():
        if m.exact:
            by_team.setdefault(m.team, []).append(n)
    for team, ns in by_team.items():
        if len(ns) > 1 and sum(out[n].basis != "takma_ad" for n in ns) > 1:
            for n in ns:
                out[n] = replace(out[n], team=None, status=BELIRSIZ, basis="ters_cakisma", candidates=(team,))
    return out


def match_team(name, candidates, league: str | None = None, source: str | None = None) -> str | None:
    """`name` için `candidates` listesinden KESİN kimlikli takımı döndürür; emin değilse (belirsiz, yalnızca benzer veya
    bulunamadı) None. Bulanık/önek benzerliği takım seçmez (yalnızca ``resolve_team(...).suggestions``)."""
    if not candidates:
        return None
    return resolve_team(name, candidates, league, source).team

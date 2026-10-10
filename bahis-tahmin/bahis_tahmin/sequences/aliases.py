"""Takım kimliği eşlemesi (yalnızca araştırma modülü; üretim modelleri ham adı kullanmaya devam eder).

İki katman (docs/DIZI_ARASTIRMA_SOZLESMESI.md §1):
  * Katman 1 — sezon ortası ayrılma (deterministik): aynı lig-sezonda tarih aralıkları çakışmayan, birbirleriyle
    hiç karşılaşmayan ve biri sezona geç başlarken diğeri erken bitiren iki ad aynı kulüptür. Kural yalnızca
    adlar, ligler ve tarihlerden çalışır (sonuçları okumaz).
  * Katman 2 — sezonlar arası ad değişikliği: ``tools/research/alias_candidates.py`` adaylarından ELLE incelenip
    onaylananlar. Yeniden kurulmuş / ardıl kulüpler bilerek eşlenmez (varsayılan "farklı kimlik").
Zaman güvenliği: kimlik bilgisi sonuç bilgisi değildir; tablo ilk sonuçtan önce dondurulur, özeti manifestte.
"""

from __future__ import annotations

import hashlib
import json

import pandas as pd

ALIAS_VERSION = "takim-esleme-v2 (2026-10-10)"

# Katman 2: (ülke, kaynaktaki ad) -> (kanonik ad, kanıt)
MANUAL_ALIASES: dict[tuple[str, str], tuple[str, str]] = {
    ("İngiltere", "Telford United"): ("AFC Telford United", "EC 2012/13'ten itibaren kısaltılmış ad; aynı kulüp"),
    ("İngiltere", "Boston Utd"): ("Boston", "Boston United; E3'ten 2007'de düştü, EC 2024/25'te döndü"),
    ("Hollanda", "Roda"): ("Roda JC", "N1 2010/11'den itibaren kısaltılmış ad"),
    ("Hollanda", "Sparta Rotterdam"): ("Sparta", "N1'e 2016/17'de dönüş; aynı kulüp"),
}
# Katman 1'in mevcut veride bulduğu ayrılmalar (kural her yüklemede yeniden çalışır; bu liste test referansıdır)
EXPECTED_SPLITS = {("Almanya", "M'gladbach"): "MGladbach", ("Almanya", "Preußen Münster"): "Preussen Munster",
                   ("İngiltere", "Nott'm Forest"): "Nottm Forest"}
REJECTED = (
    "Ahlen/Aalen", "Cannes/Vannes", "Malatyaspor/Alanyaspor", "Malatyaspor/Yeni Malatyaspor", "Kalamaria/Kalamata",
    "Wimbledon/AFC Wimbledon", "Aves/AVS", "Gaziantepspor/Gaziantep", "Granada 74/Granada", "Extremadura/Extremadura UD",
    "Airdrie/Airdrie Utd", "Molenbeek/RWD Molenbeek", "Lommel/Lommel SK", "Murcia/UCAM Murcia", "Rouen/Quevilly Rouen",
)
_LATE_EARLY_DAYS = 45
_MAX_HANDOVER_DAYS = 60


def detect_intra_season_splits(matches: pd.DataFrame) -> dict[tuple[str, str], str]:
    """Katman 1: sezon ortası ad ayrılmaları {(ülke, yeni ad): eski ad}. Yalnızca ad/lig/tarih kullanır."""
    from ..data.leagues import LEAGUES

    tm = pd.concat([
        matches[["league", "season", "date", "home", "away"]].rename(columns={"home": "team", "away": "opp"}),
        matches[["league", "season", "date", "away", "home"]].rename(columns={"away": "team", "home": "opp"}),
    ])
    out: dict[tuple[str, str], str] = {}
    for (lg, se), g in tm.groupby(["league", "season"]):
        s0, s1 = g["date"].min(), g["date"].max()
        span = g.groupby("team")["date"].agg(["min", "max"])
        opps = g.groupby("team")["opp"].agg(set)
        early = span[(s1 - span["max"]).dt.days > _LATE_EARLY_DAYS]
        late = span[(span["min"] - s0).dt.days > _LATE_EARLY_DAYS]
        country = LEAGUES[lg].country if lg in LEAGUES else lg
        for a, ra in early.iterrows():
            for b, rb in late.iterrows():
                if a == b or not (ra["max"] < rb["min"]) or (rb["min"] - ra["max"]).days > _MAX_HANDOVER_DAYS:
                    continue
                if b in opps[a] or a in opps[b]:
                    continue  # birbirleriyle oynadılarsa aynı kulüp olamaz
                out[(country, b)] = a
    return out


class AliasMap:
    """Kanonik takım kimliği (katman 1 + katman 2)."""

    def __init__(self, splits: dict[tuple[str, str], str] | None = None):
        self.splits = dict(splits or {})
        self.table = {k: v for k, v in self.splits.items()}
        self.table.update({k: v[0] for k, v in MANUAL_ALIASES.items()})

    @classmethod
    def from_matches(cls, matches: pd.DataFrame) -> "AliasMap":
        return cls(detect_intra_season_splits(matches))

    def canonical(self, name: str, country: str) -> str:
        seen = set()
        while (country, name) in self.table and name not in seen:  # zincirleme eşleme (ör. A→B→C)
            seen.add(name)
            name = self.table[(country, name)]
        return name

    def sha256(self) -> str:
        items = sorted([f"{c}|{a}|{b}" for (c, a), b in self.table.items()])
        return hashlib.sha256(json.dumps([ALIAS_VERSION] + items, ensure_ascii=False).encode()).hexdigest()


def canonical_team(name: str, country: str, alias_map: AliasMap | None = None) -> str:
    """Kanonik takım adı. ``alias_map`` verilmezse yalnızca katman 2 + beklenen katman 1 listesi uygulanır."""
    if alias_map is not None:
        return alias_map.canonical(name, country)
    if (country, name) in EXPECTED_SPLITS:
        return EXPECTED_SPLITS[(country, name)]
    hit = MANUAL_ALIASES.get((country, name))
    return hit[0] if hit else name

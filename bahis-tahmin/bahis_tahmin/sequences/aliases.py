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


def detect_intra_season_splits(matches: pd.DataFrame,
                               rejected: list | None = None) -> dict[tuple[str, str], str]:
    """Katman 1: sezon ortası ad ayrılmaları {(ülke, yeni ad): eski ad}. Yalnızca ad/lig/tarih kullanır.

    DIZI-02 ek koşulları (yanlış eşleme iki farklı kulübün geçmişini birleştirir ve aynı takıma aynı gün iki maç
    yazar):
      * Lig-sezonda sezona erken veda eden ve geç katılan takım TEK olmalı. Birden çok takım birlikte ayrılıp
        katılıyorsa bu bir sezon sınırıdır (ör. sezon etiketi iki gerçek sezonu kapsıyor: düşen ve çıkan kulüpler).
      * Aday, ülkenin BÜTÜN maçlarıyla doğrulanır: iki ad herhangi bir sezonda aynı gün maç oynamışsa veya
        birbirleriyle karşılaşmışsa aynı kulüp olamaz. Eşleme zincirleri de grup olarak denetlenir.
    Reddedilenler verilirse ``rejected`` listesine (ülke, yeni ad, eski ad, neden) olarak eklenir."""
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
        found = []
        for a, ra in early.iterrows():
            for b, rb in late.iterrows():
                if a == b or not (ra["max"] < rb["min"]) or (rb["min"] - ra["max"]).days > _MAX_HANDOVER_DAYS:
                    continue
                if b in opps[a] or a in opps[b]:
                    continue  # birbirleriyle oynadılarsa aynı kulüp olamaz
                found.append((a, b))
        if not found:
            continue
        if len(early) > 1 or len(late) > 1:
            if rejected is not None:
                rejected.extend((country, b, a, f"{lg} {se}: {len(early)} takım erken ayrılıyor, {len(late)} takım geç "
                                                 "katılıyor (sezon sınırı; ad değişikliği değil)") for a, b in found)
            continue
        for a, b in found:
            out[(country, b)] = a
    return _validated_splits(matches, out, rejected)


def _validated_splits(matches: pd.DataFrame, cand: dict[tuple[str, str], str],
                      rejected: list | None = None) -> dict[tuple[str, str], str]:
    """Aday ayrılmaları ülke genelinde doğrular: eşlenen adların (zincir dahil) hiçbir maç günü ortak olmamalı ve
    birbirleriyle hiç karşılaşmamış olmalılar. Aksi halde eşleme aynı takıma aynı gün iki maç (veya kendisiyle maç)
    yazar; takım-maç tablosu kurulamaz ve iki kulübün geçmişi karışır."""
    if not cand:
        return {}
    from ..data.leagues import LEAGUES

    country = matches["league"].map(lambda c: LEAGUES[c].country if c in LEAGUES else c)
    days: dict[tuple[str, str], set] = {}
    met: set[tuple[str, str, str]] = set()
    for c, h, a, d in zip(country, matches["home"], matches["away"], matches["date"]):
        days.setdefault((c, h), set()).add(d)
        days.setdefault((c, a), set()).add(d)
        met.add((c, h, a))
        met.add((c, a, h))
    group: dict[tuple[str, str], tuple[str, str]] = {}  # (ülke, ad) -> grup kökü

    def root(k):
        while group.get(k, k) != k:
            k = group[k]
        return k

    members: dict[tuple[str, str], set[str]] = {}
    out: dict[tuple[str, str], str] = {}
    for (c, new), old in sorted(cand.items()):
        ra, rb = root((c, old)), root((c, new))
        if ra == rb:
            out[(c, new)] = old
            continue
        ga = members.get(ra, {old})
        gb = members.get(rb, {new})
        clash = next((f"{x} ile {y} aynı gün maç oynamış" for x in ga for y in gb
                      if days.get((c, x), set()) & days.get((c, y), set())), None)
        clash = clash or next((f"{x} ile {y} karşılaşmış" for x in ga for y in gb if (c, x, y) in met), None)
        if clash:
            if rejected is not None:
                rejected.append((c, new, old, clash))
            continue
        group[rb] = ra
        members[ra] = ga | gb
        members.pop(rb, None)
        out[(c, new)] = old
    return out


class AliasMap:
    """Kanonik takım kimliği (katman 1 + katman 2)."""

    def __init__(self, splits: dict[tuple[str, str], str] | None = None):
        self.splits = dict(splits or {})
        self.rejected_splits: list[tuple[str, str, str, str]] = []  # doğrulamadan geçmeyen katman 1 adayları
        self.table = {k: v for k, v in self.splits.items()}
        self.table.update({k: v[0] for k, v in MANUAL_ALIASES.items()})

    @classmethod
    def from_matches(cls, matches: pd.DataFrame) -> "AliasMap":
        rejected: list = []
        splits = detect_intra_season_splits(matches, rejected)
        # VERI-01: veri deposu aynı adın yazımlarını (ör. "Nottm Forest" / "Nott'm Forest") tek yazıma indirir; o
        # zaman katman 1 ayrılmayı göremez. Kimlik aynı olduğu için ön-kayıtlı tablo (ve özeti) korunur: iki yazımdan
        # yalnızca biri veride kalmışsa beklenen ayrılma aynen eklenir.
        from ..data.leagues import LEAGUES

        present: dict[str, set] = {}
        for lg, g in matches.groupby("league"):
            country = LEAGUES[lg].country if lg in LEAGUES else lg
            present.setdefault(country, set()).update(set(g["home"]) | set(g["away"]))
        for (country, new), old in EXPECTED_SPLITS.items():
            names = present.get(country, set())
            if (country, new) not in splits and (new in names) != (old in names):
                splits[(country, new)] = old
        am = cls(splits)
        am.rejected_splits = rejected
        return am

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

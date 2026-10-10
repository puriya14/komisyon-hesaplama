"""Merkezi pazar tanımları (registry), sonuç etiketleme ve bahis sonuçlandırma (settlement).

Kapsam (kural sürümü ``std-v1``):
  * Normal süre: iki devre + hakemin eklediği uzatma dakikaları dahil.
  * Uzatma devreleri ve penaltı atışları HARİÇ.
  * ``fthg/ftag`` her zaman NORMAL SÜRE sonu skorudur. Sağlayıcı uzatmalı skoru veriyorsa
    adaptör bunu ``aet_home/aet_away`` alanına koymalıdır.

İstatistiksel etiket (TRUE/FALSE/UNKNOWN) ile bahis sonucu (WIN/LOSS/VOID/PENDING/UNKNOWN)
ayrı tutulur: yarıda kalan bir maçın etiketi bilinmez, bahsi ise kurala göre VOID olur.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

RULE_VERSION = "std-v1"


class Label(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class Settlement(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    VOID = "VOID"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"


class MatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PLAY = "IN_PLAY"
    FINISHED = "FINISHED"  # normal sürede bitti
    FINISHED_AET = "FINISHED_AET"  # uzatmalara gitti (normal süre skoru ayrıca verilmeli)
    FINISHED_PEN = "FINISHED_PEN"  # penaltılarla bitti
    ABANDONED = "ABANDONED"  # yarıda kaldı
    AWARDED = "AWARDED"  # hükmen sonuç
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


FINISHED_STATES = {MatchStatus.FINISHED, MatchStatus.FINISHED_AET, MatchStatus.FINISHED_PEN}


@dataclass(frozen=True)
class MarketDef:
    key: str
    name_tr: str
    period: str  # FT, 1H, 2H, BOTH_HALVES
    line: float | None
    selection: str  # YES / NO / OVER / UNDER
    complement: str
    required: tuple[str, ...]
    description: str
    primary: bool = False


_HT_FT = ("hthg", "htag", "fthg", "ftag")
_FT = ("fthg", "ftag")

MARKETS: dict[str, MarketDef] = {}


def _add(*defs: MarketDef) -> None:
    for d in defs:
        MARKETS[d.key] = d


_add(
    MarketDef("BTTS_BOTH_HALVES_YES", "İki yarıda da karşılıklı gol – Evet", "BOTH_HALVES", None, "YES",
              "BTTS_BOTH_HALVES_NO", _HT_FT,
              "HTHG≥1 VE HTAG≥1 VE (FTHG−HTHG)≥1 VE (FTAG−HTAG)≥1", primary=True),
    MarketDef("BTTS_BOTH_HALVES_NO", "İki yarıda da karşılıklı gol – Hayır", "BOTH_HALVES", None, "NO",
              "BTTS_BOTH_HALVES_YES", _HT_FT, "BTTS_BOTH_HALVES_YES'in tersi", primary=True),
    MarketDef("FT_OVER_3_5", "Maç sonu 3,5 Üst", "FT", 3.5, "OVER", "FT_UNDER_3_5", _FT,
              "FTHG+FTAG ≥ 4 (normal süre)", primary=True),
    MarketDef("FT_UNDER_3_5", "Maç sonu 3,5 Alt", "FT", 3.5, "UNDER", "FT_OVER_3_5", _FT,
              "FTHG+FTAG ≤ 3 (normal süre)", primary=True),
    MarketDef("FH_OVER_1_5", "İlk yarı 1,5 Üst", "1H", 1.5, "OVER", "FH_UNDER_1_5", ("hthg", "htag"),
              "HTHG+HTAG ≥ 2", primary=True),
    MarketDef("FH_UNDER_1_5", "İlk yarı 1,5 Alt", "1H", 1.5, "UNDER", "FH_OVER_1_5", ("hthg", "htag"),
              "HTHG+HTAG ≤ 1", primary=True),
    # İkinci aşama (araştırma) pazarları: etiket var, öneri motoruna kapalı
    MarketDef("FT_BTTS_YES", "Maç sonu KG Var", "FT", None, "YES", "FT_BTTS_NO", _FT, "FTHG≥1 VE FTAG≥1"),
    MarketDef("FT_BTTS_NO", "Maç sonu KG Yok", "FT", None, "NO", "FT_BTTS_YES", _FT, "FT_BTTS_YES'in tersi"),
    MarketDef("FH_BTTS_YES", "İlk yarı KG Var", "1H", None, "YES", "FH_BTTS_NO", ("hthg", "htag"), "HTHG≥1 VE HTAG≥1"),
    MarketDef("FH_BTTS_NO", "İlk yarı KG Yok", "1H", None, "NO", "FH_BTTS_YES", ("hthg", "htag"), "FH_BTTS_YES'in tersi"),
    MarketDef("SH_OVER_1_5", "İkinci yarı 1,5 Üst", "2H", 1.5, "OVER", "SH_UNDER_1_5", _HT_FT, "(FT−HT) toplamı ≥ 2"),
    MarketDef("SH_UNDER_1_5", "İkinci yarı 1,5 Alt", "2H", 1.5, "UNDER", "SH_OVER_1_5", _HT_FT, "(FT−HT) toplamı ≤ 1"),
    MarketDef("FT_OVER_2_5", "Maç sonu 2,5 Üst", "FT", 2.5, "OVER", "FT_UNDER_2_5", _FT, "FTHG+FTAG ≥ 3"),
    MarketDef("FT_UNDER_2_5", "Maç sonu 2,5 Alt", "FT", 2.5, "UNDER", "FT_OVER_2_5", _FT, "FTHG+FTAG ≤ 2"),
    MarketDef("FT_OVER_4_5", "Maç sonu 4,5 Üst", "FT", 4.5, "OVER", "FT_UNDER_4_5", _FT, "FTHG+FTAG ≥ 5"),
    MarketDef("FT_UNDER_4_5", "Maç sonu 4,5 Alt", "FT", 4.5, "UNDER", "FT_OVER_4_5", _FT, "FTHG+FTAG ≤ 4"),
)

PRIMARY_YES = ("BTTS_BOTH_HALVES_YES", "FT_OVER_3_5", "FH_OVER_1_5")
SHORT = {"BTTS_BOTH_HALVES_YES": "A", "FT_OVER_3_5": "B", "FH_OVER_1_5": "C"}


@dataclass
class PeriodScore:
    """Bir maçın dönem skorları. ``fthg/ftag`` = normal süre sonu."""

    fthg: float | None = None
    ftag: float | None = None
    hthg: float | None = None
    htag: float | None = None
    status: MatchStatus = MatchStatus.FINISHED
    aet_home: float | None = None
    aet_away: float | None = None
    issues: list[str] = field(default_factory=list)


def _valid_goal(v) -> bool:
    if v is None:
        return False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f >= 0 and f == int(f)


def validate(ps: PeriodScore) -> list[str]:
    """Skor kaydındaki sorunlar (boş liste = sorun yok)."""
    issues = []
    for name in ("fthg", "ftag", "hthg", "htag"):
        v = getattr(ps, name)
        if v is not None and not (isinstance(v, float) and math.isnan(v)) and not _valid_goal(v):
            issues.append(f"GECERSIZ_DEGER:{name}")
    if all(_valid_goal(getattr(ps, n)) for n in _HT_FT):
        if ps.hthg > ps.fthg or ps.htag > ps.ftag:
            issues.append("ILK_YARI_MAC_SONUNU_ASIYOR")
    if ps.status == MatchStatus.FINISHED_AET and ps.aet_home is not None and ps.aet_away is not None:
        if _valid_goal(ps.fthg) and _valid_goal(ps.aet_home) and (ps.aet_home < ps.fthg or ps.aet_away < ps.ftag):
            issues.append("UZATMA_SKORU_NORMAL_SUREDEN_KUCUK")
    return issues


def _fields_known(ps: PeriodScore, names: tuple[str, ...]) -> bool:
    return all(_valid_goal(getattr(ps, n)) for n in names)


def _yes_condition(key: str, hthg, htag, fthg, ftag) -> bool:
    if key in ("BTTS_BOTH_HALVES_YES", "BTTS_BOTH_HALVES_NO"):
        return hthg >= 1 and htag >= 1 and (fthg - hthg) >= 1 and (ftag - htag) >= 1
    if key in ("FT_OVER_3_5", "FT_UNDER_3_5"):
        return fthg + ftag >= 4
    if key in ("FH_OVER_1_5", "FH_UNDER_1_5"):
        return hthg + htag >= 2
    if key in ("FT_BTTS_YES", "FT_BTTS_NO"):
        return fthg >= 1 and ftag >= 1
    if key in ("FH_BTTS_YES", "FH_BTTS_NO"):
        return hthg >= 1 and htag >= 1
    if key in ("SH_OVER_1_5", "SH_UNDER_1_5"):
        return (fthg - hthg) + (ftag - htag) >= 2
    if key in ("FT_OVER_2_5", "FT_UNDER_2_5"):
        return fthg + ftag >= 3
    if key in ("FT_OVER_4_5", "FT_UNDER_4_5"):
        return fthg + ftag >= 5
    raise KeyError(key)


def label(key: str, ps: PeriodScore) -> Label:
    """Pazarın istatistiksel sonucu (normal süre kuralına göre)."""
    m = MARKETS[key]
    if ps.status not in FINISHED_STATES:
        return Label.UNKNOWN
    if validate(ps):
        # Çelişkili kayıtta hangi alanın yanlış olduğu bilinemez: hiçbir pazar etiketlenmez
        return Label.UNKNOWN
    if not _fields_known(ps, m.required):
        return Label.UNKNOWN
    v = lambda n: int(getattr(ps, n)) if _valid_goal(getattr(ps, n)) else 0  # noqa: E731
    yes = _yes_condition(key, v("hthg"), v("htag"), v("fthg"), v("ftag"))
    positive = m.selection in ("YES", "OVER")
    return Label.TRUE if yes == positive else Label.FALSE


def label_all(ps: PeriodScore, keys=None) -> dict[str, Label]:
    return {k: label(k, ps) for k in (keys or MARKETS)}


def settle(key: str, ps: PeriodScore, rule_version: str = RULE_VERSION) -> Settlement:
    """Bahis sonucu. ``std-v1`` kuralı:

    * Başlamamış / oynanıyor → PENDING
    * Ertelendi / iptal → VOID
    * Yarıda kaldı → VOID (sonucu kesinleşmiş pazarlar için sağlayıcı kuralı farklıysa yeni kural sürümü gerekir)
    * Hükmen → VOID (sahada oynanmış skor değil)
    * Bitti → etikete göre WIN/LOSS; etiket bilinmiyorsa UNKNOWN (otomatik kayıp yazılmaz)
    """
    if rule_version != RULE_VERSION:
        raise ValueError(f"Bilinmeyen sonuçlandırma kuralı: {rule_version}")
    if key not in MARKETS:
        raise KeyError(key)
    if ps.status in (MatchStatus.SCHEDULED, MatchStatus.IN_PLAY):
        return Settlement.PENDING
    if ps.status in (MatchStatus.POSTPONED, MatchStatus.CANCELLED, MatchStatus.ABANDONED, MatchStatus.AWARDED):
        return Settlement.VOID
    if ps.status == MatchStatus.UNKNOWN:
        return Settlement.UNKNOWN
    lab = label(key, ps)
    if lab == Label.TRUE:
        return Settlement.WIN
    if lab == Label.FALSE:
        return Settlement.LOSS
    return Settlement.UNKNOWN


# ----------------------------------------------------------------------------
# Toplu etiketleme (geçmiş veri tabloları için)
# ----------------------------------------------------------------------------

def frame_issues(df: pd.DataFrame) -> pd.Series:
    """Her satır için doğrulama sorunları ('' = sorun yok). Ham veri değiştirilmez."""
    ft_ok = df[["fthg", "ftag"]].apply(lambda s: s.map(_valid_goal)).all(axis=1)
    ht_present = df[["hthg", "htag"]].notna().all(axis=1)
    ht_ok = df[["hthg", "htag"]].apply(lambda s: s.map(_valid_goal)).all(axis=1)
    issues = pd.Series("", index=df.index, dtype=object)
    issues[~ft_ok] = "GECERSIZ_MAC_SONU"
    bad_ht = ht_present & ~ht_ok
    issues[bad_ht & ft_ok] = "GECERSIZ_ILK_YARI"
    both = ft_ok & ht_ok
    over = both & ((df["hthg"] > df["fthg"]) | (df["htag"] > df["ftag"]))
    issues[over] = "ILK_YARI_MAC_SONUNU_ASIYOR"
    return issues


def label_frame(df: pd.DataFrame, keys=PRIMARY_YES) -> pd.DataFrame:
    """Geçmiş maçlar için etiketler: 1.0 / 0.0 / NaN (= UNKNOWN). Ham sütunlara dokunmaz."""
    issues = frame_issues(df)
    fthg = pd.to_numeric(df["fthg"], errors="coerce")
    ftag = pd.to_numeric(df["ftag"], errors="coerce")
    hthg = pd.to_numeric(df["hthg"], errors="coerce")
    htag = pd.to_numeric(df["htag"], errors="coerce")
    clean = issues == ""
    ft_known = clean & fthg.notna() & ftag.notna()
    ht_known = ft_known & hthg.notna() & htag.notna()
    out = pd.DataFrame(index=df.index)
    for key in keys:
        m = MARKETS[key]
        need_ht = any(f in m.required for f in ("hthg", "htag"))
        known = (ht_known if need_ht else ft_known).to_numpy()
        hh, ha = hthg.fillna(0).to_numpy(), htag.fillna(0).to_numpy()
        fh, fa = fthg.fillna(0).to_numpy(), ftag.fillna(0).to_numpy()
        if key.startswith("BTTS_BOTH_HALVES"):
            yes = (hh >= 1) & (ha >= 1) & (fh - hh >= 1) & (fa - ha >= 1)
        elif key.startswith("FT_OVER_3_5") or key.startswith("FT_UNDER_3_5"):
            yes = fh + fa >= 4
        elif key.startswith("FH_OVER_1_5") or key.startswith("FH_UNDER_1_5"):
            yes = hh + ha >= 2
        elif key.startswith("FT_BTTS"):
            yes = (fh >= 1) & (fa >= 1)
        elif key.startswith("FH_BTTS"):
            yes = (hh >= 1) & (ha >= 1)
        elif key.startswith("SH_"):
            yes = (fh - hh) + (fa - ha) >= 2
        elif key in ("FT_OVER_2_5", "FT_UNDER_2_5"):
            yes = fh + fa >= 3
        elif key in ("FT_OVER_4_5", "FT_UNDER_4_5"):
            yes = fh + fa >= 5
        else:
            raise KeyError(key)
        positive = m.selection in ("YES", "OVER")
        val = np.where(yes == positive, 1.0, 0.0)
        out[key] = np.where(known, val, np.nan)
    out["issues"] = issues
    return out

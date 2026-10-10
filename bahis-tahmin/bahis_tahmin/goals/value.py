"""Gerçek oran kaydı, oran doğrulama ve beklenen değer (EV) hesapları.

Tanımlar (ondalık oran d, model olasılığı p):
  * Ham başabaş olasılığı = 1/d
  * Adil oran = 1/p
  * Komisyonsuz, iadesiz birim bahiste beklenen net getiri = p·d − 1
Sunulan oran bahis şirketi marjını zaten içerir; EV hesabından sonra marj ikinci kez düşülmez.
Marjdan arındırılmış piyasa olasılığı YALNIZCA iki tarafın oranı aynı sağlayıcıdan ve uyumlu
zamanda varsa (basit normalizasyonla) hesaplanır ve "yöntem tahmini" olarak etiketlenir.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import math
from dataclasses import asdict, dataclass

from .markets import MARKETS, RULE_VERSION, get_market, parse_htft

MAX_PAIR_GAP = dt.timedelta(minutes=10)


class OddsError(ValueError):
    pass


@dataclass(frozen=True)
class OddsQuote:
    event_id: str
    market_key: str
    period: str
    line: float | None
    selection: str
    provider: str
    bookmaker: str
    decimal_odds: float
    quoted_at: dt.datetime  # oranın sağlayıcıda geçerli olduğu an (zaman dilimi bilgili)
    fetched_at: dt.datetime  # sisteme alındığı an
    status: str = "OPEN"  # OPEN / SUSPENDED / CLOSED
    settlement_rule_version: str = RULE_VERSION

    def to_dict(self) -> dict:
        d = asdict(self)
        d["quoted_at"] = self.quoted_at.isoformat()
        d["fetched_at"] = self.fetched_at.isoformat()
        return d


def validate_quote(q: OddsQuote) -> list[str]:
    """Oran kaydının pazar tanımıyla uyumu ve geçerliliği. Boş liste = geçerli."""
    errs = []
    m = get_market(q.market_key)
    if m is None:
        return [f"BILINMEYEN_PAZAR:{q.market_key}"]
    if q.period != m.period:
        errs.append(f"DONEM_UYUSMAZ:{q.period}!={m.period}")
    if (q.line is None) != (m.line is None) or (q.line is not None and abs(q.line - m.line) > 1e-9):
        errs.append(f"CIZGI_UYUSMAZ:{q.line}!={m.line}")
    if m.period == "HTFT":  # İY/MS: '0/1', 'D/H', 'X-1' gibi gösterimler merkezi olarak normalize edilir
        if parse_htft(q.selection) != m.key:
            errs.append(f"SECIM_UYUSMAZ:{q.selection}!={m.selection}")
    elif q.selection != m.selection:
        errs.append(f"SECIM_UYUSMAZ:{q.selection}!={m.selection}")
    if not (isinstance(q.decimal_odds, (int, float)) and math.isfinite(q.decimal_odds) and q.decimal_odds > 1.0):
        errs.append("GECERSIZ_ORAN")
    if q.quoted_at.tzinfo is None or q.fetched_at.tzinfo is None:
        errs.append("ZAMAN_DILIMI_YOK")
    if q.settlement_rule_version != RULE_VERSION:
        errs.append(f"SONUCLANDIRMA_KURALI_FARKLI:{q.settlement_rule_version}")
    if q.status != "OPEN":
        errs.append(f"PAZAR_ACIK_DEGIL:{q.status}")
    return errs


def is_stale(q: OddsQuote, decision_time: dt.datetime, max_age: dt.timedelta) -> bool:
    """Oran karar anına göre çok eski mi (ya da karar anından SONRA mı)?"""
    age = decision_time - q.quoted_at
    return age > max_age or age < -dt.timedelta(seconds=1)


def expected_value(p_win: float, odds: float, commission: float = 0.0, p_void: float = 0.0) -> float:
    """Birim bahis başına beklenen net getiri.

    Kazanınca net kâr (d−1)·(1−komisyon), kaybedince −1, iade (VOID) olursa 0.
    p_win + p_loss + p_void = 1.
    """
    if not (math.isfinite(odds) and odds > 1.0):
        raise OddsError("Oran 1'den büyük olmalı")
    if not (0.0 <= p_win <= 1.0 and 0.0 <= p_void <= 1.0 and p_win + p_void <= 1.0 + 1e-12):
        raise ValueError("Olasılıklar geçersiz")
    p_loss = max(0.0, 1.0 - p_win - p_void)
    return p_win * (odds - 1.0) * (1.0 - commission) - p_loss


def breakeven_probability(odds: float, commission: float = 0.0) -> float:
    if not (math.isfinite(odds) and odds > 1.0):
        raise OddsError("Oran 1'den büyük olmalı")
    net = (odds - 1.0) * (1.0 - commission)
    return 1.0 / (1.0 + net)


def fair_odds(p: float) -> float:
    return 1.0 / p if p > 0 else float("inf")


def min_required_odds(p_safe: float, margin: float = 0.0, commission: float = 0.0) -> float | None:
    """Hedef birim getiri m için gereken en düşük oran: komisyonsuz d_min = (1+m)/p_safe."""
    if not (p_safe and math.isfinite(p_safe) and 0 < p_safe <= 1):
        return None
    if commission == 0:
        return (1.0 + margin) / p_safe
    # p·(d−1)(1−c) − (1−p) = m  →  d = 1 + (m + 1 − p) / (p(1−c))
    return 1.0 + (margin + 1.0 - p_safe) / (p_safe * (1.0 - commission))


def no_vig_probability(yes: OddsQuote | None, no: OddsQuote | None) -> float | None:
    """Basit normalizasyonla marjsız 'evet' olasılığı. İki taraf, aynı sağlayıcı/bahis şirketi ve
    en fazla 10 dk arayla yoksa None (tek taraftan uydurulmaz)."""
    if yes is None or no is None:
        return None
    m = MARKETS.get(yes.market_key)  # yalnızca iki seçenekli pazarlar (İY/MS'in tümleyeni yok)
    if m is None or m.complement != no.market_key:
        return None
    if (yes.provider, yes.bookmaker) != (no.provider, no.bookmaker):
        return None
    if abs(yes.quoted_at - no.quoted_at) > MAX_PAIR_GAP:
        return None
    iy, inn = 1.0 / yes.decimal_odds, 1.0 / no.decimal_odds
    return iy / (iy + inn)


def kelly_fraction(p: float, odds: float, fraction: float = 0.25, cap: float = 0.02) -> float:
    """Teorik Kelly f = max(0, (p·d − 1)/(d − 1)); kesirli ve üst sınırlı. Tahmin hatasını hesaba katmaz."""
    if not (math.isfinite(odds) and odds > 1.0):
        return 0.0
    f = max(0.0, (p * odds - 1.0) / (odds - 1.0))
    return min(f * fraction, cap)


# ----------------------------------------------------------------------------
# Güvenli CSV içe/dışa aktarma
# ----------------------------------------------------------------------------

ODDS_CSV_FIELDS = ["event_id", "market_key", "period", "line", "selection", "provider", "bookmaker",
                   "decimal_odds", "quoted_at", "fetched_at", "status", "settlement_rule_version"]
MAX_IMPORT_BYTES = 5_000_000


def parse_odds_csv(data: bytes) -> tuple[list[OddsQuote], list[str]]:
    """Oran CSV'sini şema doğrulamasıyla okur. Hatalı satırlar karantina listesine düşer."""
    if len(data) > MAX_IMPORT_BYTES:
        raise OddsError("Dosya çok büyük (en fazla 5 MB)")
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = [f for f in ODDS_CSV_FIELDS if f not in (reader.fieldnames or [])]
    if missing:
        raise OddsError(f"Eksik sütunlar: {', '.join(missing)}")
    quotes, bad = [], []
    for i, row in enumerate(reader, start=2):
        try:
            q = OddsQuote(
                event_id=row["event_id"].strip(),
                market_key=row["market_key"].strip(),
                period=row["period"].strip(),
                line=float(row["line"]) if row["line"].strip() else None,
                selection=row["selection"].strip(),
                provider=row["provider"].strip(),
                bookmaker=row["bookmaker"].strip(),
                decimal_odds=float(row["decimal_odds"]),
                quoted_at=dt.datetime.fromisoformat(row["quoted_at"].strip()),
                fetched_at=dt.datetime.fromisoformat(row["fetched_at"].strip()),
                status=row["status"].strip() or "OPEN",
                settlement_rule_version=row["settlement_rule_version"].strip() or RULE_VERSION,
            )
        except (ValueError, KeyError) as e:
            bad.append(f"satır {i}: {e}")
            continue
        errs = validate_quote(q)
        if errs:
            bad.append(f"satır {i}: {', '.join(errs)}")
            continue
        quotes.append(q)
    return quotes, bad


def safe_csv_cell(v) -> str:
    """CSV/Excel formül enjeksiyonuna karşı: =, +, -, @, sekme ile başlayan metinleri etkisizleştirir."""
    s = "" if v is None else str(v)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        try:
            float(s)
            return s  # sayısal değer (ör. -0.05) olduğu gibi kalır
        except ValueError:
            return "'" + s
    return s

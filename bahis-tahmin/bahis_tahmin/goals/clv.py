"""Kapanış oranı karşılaştırması (CLV, ORAN-03).

Bir sanal bahsin alındığı oran (``odds``) ile aynı pazarın kapanış oranı (maç başlamadan önceki son oran)
karşılaştırılır:

* Ham CLV = alınan oran / kapanış oranı − 1. Kapanış oranı şirket marjını içerdiği için iyimserdir.
* Marjsız CLV = alınan oran × marjsız kapanış olasılığı − 1. Marjsız olasılık iki tarafın kapanış oranından orantılı
  normalizasyonla hesaplanır (yalnızca karşı taraf oranı da girildiyse). Kapanış piyasası doğruysa bu, bahsin beklenen
  getirisidir.

Kapanış oranı karar anından ÖNCE gözlenmişse karşılaştırma yapılmaz (kapanış olamaz). Maç saati biliniyorsa kaydın
maç saatine uzaklığı ayrıca gösterilir; erken girilen oran gerçek kapanış olmayabilir.

Pozitif ortalama CLV, sonuçlar azken de kazandıran bir yöntemin en iyi erken işaretidir; tek başına kazanç garantisi
değildir.
"""

from __future__ import annotations

import datetime as dt
import math

from .markets import MARKETS

EARLY_MINUTES = 60  # maç saatinden bundan daha erken kaydedilen oran "erken" etiketi alır
PAIR_GAP = dt.timedelta(minutes=10)


def clv(taken: float, close: float, close_opposite: float | None = None) -> tuple[float, float | None]:
    """(ham CLV, marjsız CLV). Karşı taraf yoksa marjsız CLV None."""
    raw = taken / close - 1.0
    if close_opposite is None:
        return raw, None
    a, b = 1.0 / close, 1.0 / close_opposite
    return raw, taken * a / (a + b) - 1.0


def _time(s) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo is not None else None


def timing(rec: dict, close: dict) -> tuple[bool, str]:
    """(karşılaştırılabilir mi, zamanlama etiketi)."""
    seen = _time(close.get("observed_at"))
    decided = _time(rec.get("decision_time"))
    if seen is None or decided is None:
        return False, "zaman bilinmiyor"
    if seen < decided:
        return False, "kapanış oranı karar anından önce (karşılaştırılmaz)"
    kick = _time(rec.get("kickoff"))
    if kick is None:
        return True, "maç saati bilinmiyor"
    mins = (kick - seen).total_seconds() / 60.0
    if mins < 0:
        return True, "maç başladıktan sonra girildi"
    if mins > EARLY_MINUTES:
        return True, f"maçtan {mins / 60:.1f} saat önce (erken; kapanış olmayabilir)"
    return True, f"maçtan {mins:.0f} dk önce"


def record_clv(ledger, rec: dict) -> dict | None:
    """Oranı olan bir kayıt için kapanış karşılaştırması; kapanış oranı yoksa None."""
    odds, mk = rec.get("odds"), rec.get("market_key")
    if not (isinstance(odds, (int, float)) and math.isfinite(odds) and odds > 1) or mk not in MARKETS:
        return None
    close = ledger.closing(rec["event_id"], mk)
    if close is None:
        return None
    ok, label = timing(rec, close)
    raw, fair = clv(float(odds), close["odds"], close["opposite_odds"]) if ok else (None, None)
    return {"kapanis": close["odds"], "karsi": close["opposite_odds"], "ham": raw, "marjsiz": fair, "gecerli": ok,
            "zamanlama": label, "sirket": close["bookmaker"]}


def _mean_ci(xs: list[float]) -> tuple[float | None, float | None, float | None]:
    n = len(xs)
    if n == 0:
        return None, None, None
    m = sum(xs) / n
    if n < 2:
        return m, None, None
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    h = 1.96 * sd / math.sqrt(n)
    return m, m - h, m + h


def clv_summary(ledger) -> dict:
    """Sanal bahisler (stake > 0, oranlı) için kapanış özeti. Ortalama marjsız CLV için yaklaşık %95 aralık (normal;
    az bahiste geniştir)."""
    bets = [r for r in ledger.predictions() if (r.get("stake_units") or 0) > 0 and r.get("odds")]
    vals = [(r, record_clv(ledger, r)) for r in bets]
    have = [c for _, c in vals if c is not None]
    ok = [c for c in have if c["gecerli"]]
    fair = [c["marjsiz"] for c in ok if c["marjsiz"] is not None]
    m, lo, hi = _mean_ci(fair)
    raw = [c["ham"] for c in ok]
    return {
        "sanal_bahis": len(bets), "kapanisli": len(have), "karsilastirilan": len(ok),
        "erken": sum(1 for c in ok if "erken" in c["zamanlama"]),
        "ham_ort": sum(raw) / len(raw) if raw else None,
        "kapanisi_gecen_payi": sum(1 for x in raw if x > 0) / len(raw) if raw else None,
        "marjsiz_n": len(fair), "marjsiz_ort": m, "marjsiz_alt": lo, "marjsiz_ust": hi,
    }


def summary_line(s: dict) -> str:
    """Kullanıcıya dönük tek satır (masaüstü, web, CLI aynı metni kullanır)."""
    if not s["sanal_bahis"]:
        return "Kapanış oranı (CLV): henüz sanal bahis yok."
    if not s["karsilastirilan"]:
        return (f"Kapanış oranı (CLV): {s['sanal_bahis']} sanal bahsin {s['kapanisli']} tanesinde kapanış oranı var; "
                "karşılaştırılabilen yok.")
    out = (f"Kapanış oranı (CLV): {s['karsilastirilan']}/{s['sanal_bahis']} bahis karşılaştırıldı · ham CLV ort. "
           f"{100 * s['ham_ort']:+.1f}% · kapanışı geçen %{100 * s['kapanisi_gecen_payi']:.0f}")
    if s["marjsiz_n"]:
        out += f" · marjsız CLV ort. {100 * s['marjsiz_ort']:+.1f}% ({s['marjsiz_n']} bahis"
        if s["marjsiz_alt"] is not None:
            out += f"; %95: {100 * s['marjsiz_alt']:+.1f}%…{100 * s['marjsiz_ust']:+.1f}%"
        out += ")"
    if s["erken"]:
        out += f" · {s['erken']} kapanış oranı maçtan 1 saatten erken girildi"
    return out


def closing_candidates(ledger) -> list[tuple[str, str, str]]:
    """Kapanış oranı girilebilecek (olay, pazar) çiftleri: oranlı kayıtlar; en yeni maç önce. (olay, pazar, etiket)."""
    seen: dict[tuple[str, str], dict] = {}
    for r in ledger.predictions():
        mk = r.get("market_key")
        if mk in MARKETS and r.get("odds"):
            seen[(r["event_id"], mk)] = r
    out = []
    for (eid, mk), r in sorted(seen.items(), key=lambda kv: (str(kv[1].get("kickoff", "")), kv[0]), reverse=True):
        c = ledger.closing(eid, mk)
        tag = f" · kapanış {c['odds']:.2f}" if c else ""
        out.append((eid, mk, f"{str(r.get('kickoff', ''))[:10]} {r.get('home', '')} - {r.get('away', '')} · "
                             f"{MARKETS[mk].name_tr} · alınan {r['odds']:.2f}{tag}"))
    return out


def add_closing(ledger, event: str, market_key: str, odds: float, opposite_odds: float | None, bookmaker: str,
                now: dt.datetime, note: str = "", source: str = "manuel") -> bool:
    """Elle girilen kapanış oranı (gözlem anı = giriş anı)."""
    return ledger.record_closing(event, market_key, odds, now, bookmaker or "belirtilmedi", source, opposite_odds,
                                 note)


def closing_from_quotes(ledger, quotes) -> tuple[int, list[str]]:
    """Oran CSV'sinden kapanış oranları (``gol-oran-ice-aktar --kapanis``): her satır bir kapanış oranı; aynı olay,
    sağlayıcı ve şirketten en fazla 10 dk arayla tümleyen pazarın oranı da varsa karşı taraf olarak eşlenir. Dönen:
    (eklenen kayıt, atlanan satır açıklamaları)."""
    by = {(q.event_id, q.market_key, q.provider, q.bookmaker): q for q in quotes}
    added, skipped, done = 0, [], set()
    for q in quotes:
        m = MARKETS.get(q.market_key)
        if m is None or not m.complement:
            skipped.append(f"{q.event_id} {q.market_key}: iki seçenekli pazar değil")
            continue
        opp = by.get((q.event_id, m.complement, q.provider, q.bookmaker))
        if opp is not None and abs(opp.quoted_at - q.quoted_at) > PAIR_GAP:
            opp = None
        pair = frozenset((q.market_key, m.complement)) if opp is not None else frozenset((q.market_key,))
        if (q.event_id, pair, q.provider, q.bookmaker) in done:
            continue
        done.add((q.event_id, pair, q.provider, q.bookmaker))
        try:
            if ledger.record_closing(q.event_id, q.market_key, q.decimal_odds, q.quoted_at, q.bookmaker, q.provider,
                                     opp.decimal_odds if opp is not None else None):
                added += 1
        except ValueError as e:
            skipped.append(f"{q.event_id} {q.market_key}: {e}")
    return added, skipped


__all__ = ["add_closing", "closing_candidates", "closing_from_quotes", "clv", "clv_summary", "record_clv",
           "summary_line", "timing"]

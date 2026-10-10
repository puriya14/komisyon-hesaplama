"""Karar motoru: her maç ve pazar için makine tarafından okunabilir karar.

"Öneri yok" geçerli bir sonuçtur. VALUE_CANDIDATE ancak aşağıdaki kontrollerin TAMAMI
geçildiğinde oluşur. Bunlardan ilki ortak veri uygunluk kontrolüdür (``bahis_tahmin.eligibility``): değerlendirmeye
bu maç, pazar, karar günü ve model durumu için üretilmiş bir uygunluk sonucu verilmemişse veya sonuç bahis için uygun
değilse durum ``DATA_NOT_ELIGIBLE`` olur (bağlamsız çağrı korumayı aşmaz; S3-GATE-01); eşikler önceden belirlenmiş ve sürümlenmiştir (sonuçlara bakılarak
ayarlanmamıştır — bu pazarlar için geçmiş gerçek oran verisi olmadığından eşikler veriyle
ayarlanamaz).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass, field

from ..timeutil import ISTANBUL
from .markets import MARKETS
from .value import (
    OddsQuote,
    breakeven_probability,
    expected_value,
    fair_odds,
    is_stale,
    min_required_odds,
    no_vig_probability,
    validate_quote,
)

STATUSES = (
    "VALUE_CANDIDATE", "NO_VALUE", "INSUFFICIENT_DATA", "ODDS_UNAVAILABLE", "STALE_ODDS",
    "MARKET_UNSUPPORTED", "MODEL_NOT_VALIDATED", "HIGH_UNCERTAINTY", "SETTLEMENT_AMBIGUOUS", "SUSPICIOUS_EDGE",
    "DATA_NOT_ELIGIBLE",
)
# Birden çok engel varsa gösterilecek birincil durum sırası
_PRIORITY = ("MARKET_UNSUPPORTED", "DATA_NOT_ELIGIBLE", "SETTLEMENT_AMBIGUOUS", "INSUFFICIENT_DATA",
             "MODEL_NOT_VALIDATED", "ODDS_UNAVAILABLE", "STALE_ODDS", "HIGH_UNCERTAINTY", "SUSPICIOUS_EDGE")

STATUS_TR = {
    "VALUE_CANDIDATE": "Avantaj adayı (sanal takip için)",
    "NO_VALUE": "Avantaj yok",
    "INSUFFICIENT_DATA": "Yetersiz veri",
    "ODDS_UNAVAILABLE": "Gerçek oran yok",
    "STALE_ODDS": "Oran eski",
    "MARKET_UNSUPPORTED": "Pazar/oran eşleşmesi desteklenmiyor",
    "MODEL_NOT_VALIDATED": "Model bu kullanım için doğrulanmadı",
    "HIGH_UNCERTAINTY": "Belirsizlik yüksek",
    "SETTLEMENT_AMBIGUOUS": "Sonuçlandırma kuralı belirsiz",
    "SUSPICIOUS_EDGE": "Olağan dışı avantaj – karantina",
    "DATA_NOT_ELIGIBLE": "Veri uygun değil (güncel/eksiksiz olduğu doğrulanmadı)",
}


# Sayısal tolerans: platformlar arası kayan nokta farkı için altın regresyon testinin olasılık toleransıyla aynı değer
# (tests/test_primary_regression.py buradan okur). Olasılıkta bu kadarlık bir farkla değişebilecek karar
# "sayısal eşik yakını" olarak gerekçede işaretlenir; durum, eşikler ve politika değişmez (S2-KABUL-01).
NUMERIC_TOLERANCE = 5e-5
NEAR_THRESHOLD = "SAYISAL_ESIK_YAKINI"


@dataclass(frozen=True)
class DecisionPolicy:
    version: str = "karar-politikasi-v1.1 (2026-10-10; v1 eşikleri aynı + SAYISAL_ESIK_YAKINI gerekçesi)"
    min_edge_safe: float = 0.03  # p_safe ile beklenen getiri en az %3
    max_odds_age: dt.timedelta = dt.timedelta(minutes=60)
    max_interval_width: float = 0.25  # %80 belirsizlik aralığı genişliği
    max_plausible_ev: float = 0.30  # üstü veri/eşleşme hatası şüphesi
    min_team_matches: int = 10  # son 365 günde (ilk yarı verili) maç
    max_candidates_per_day: int = 10
    max_candidates_per_league_day: int = 3
    commission: float = 0.0


@dataclass
class Assessment:
    event_id: str
    league: str
    home: str
    away: str
    market_key: str
    p: float  # seçimin (bu tarafın) model olasılığı
    p_low: float | None = None
    p_high: float | None = None
    model_validated: bool = False
    data_notes: list[str] = field(default_factory=list)  # boşsa veri yeterli
    quote: OddsQuote | None = None
    opposite_quote: OddsQuote | None = None
    kickoff: dt.datetime | None = None
    match_date: dt.date | None = None  # başlama saati bilinmiyorsa ihtiyatlı kural için
    # Ortak veri uygunluk sonucu (bahis_tahmin.eligibility.Eligibility). None = kontrol yapılmadı -> uygun değil.
    eligibility: object | None = None
    state_digest: str | None = None  # tahminde kullanılan lig durumunun özeti (uygunlukla bağlamak için)


@dataclass
class Decision:
    event_id: str
    market_key: str
    status: str
    reasons: list[str]
    p: float
    p_safe: float | None
    fair_odds: float | None
    odds: float | None
    breakeven: float | None
    ev: float | None
    ev_safe: float | None
    min_odds: float | None
    no_vig: float | None
    policy_version: str
    decision_time: str
    data_eligibility: dict | None = None  # uygunluk sonucunun kısa özeti (kayıtlara geriye uyumlu ek alan)

    def to_dict(self) -> dict:
        return asdict(self)


def decide(a: Assessment, decision_time: dt.datetime, policy: DecisionPolicy = DecisionPolicy()) -> Decision:
    from ..eligibility import REASONS as DATA_REASONS
    from ..eligibility import check_for_decision

    reasons: list[str] = []
    blockers: set[str] = set()
    m = MARKETS.get(a.market_key)
    if m is None or not m.primary:
        blockers.add("MARKET_UNSUPPORTED")
        reasons.append("Bu pazar öneri motoruna açık değil (yalnızca araştırma).")
    # Ortak veri uygunluk kontrolü (varsayılan: uygun değil). Uygunluk birincil (Evet/Üst) pazar için üretilir;
    # tamamlayıcı Hayır/Alt seçimi aynı sonucu kullanır.
    primary_key = a.market_key if (m is None or m.selection in ("YES", "OVER")) else m.complement
    data_block = check_for_decision(a.eligibility, a.event_id, primary_key, decision_time, a.state_digest)
    forecast_ok = bool(getattr(a.eligibility, "forecast_ok", False)) and not (
        data_block and data_block[0] in ("BAGLAM_YOK", "BAGLAM_UYUSMUYOR"))
    if data_block:
        blockers.add("DATA_NOT_ELIGIBLE")
        reasons.extend(f"Veri uygunluğu: {c} — {DATA_REASONS[c].text}" for c in data_block if c in DATA_REASONS)
    p = a.p
    if p is None or not math.isfinite(p) or not 0 <= p <= 1:
        blockers.add("INSUFFICIENT_DATA")
        reasons.append("Model olasılığı üretilemedi.")
        p = float("nan")
    elif not forecast_ok:
        p = float("nan")  # veri uygun değilse olasılık güvenilir tahmin gibi taşınmaz (sıfırla da doldurulmaz)
    if a.data_notes:
        blockers.add("INSUFFICIENT_DATA")
        reasons.extend(a.data_notes)
    if a.kickoff is not None and decision_time >= a.kickoff:
        blockers.add("MARKET_UNSUPPORTED")
        reasons.append("Maç başlamış: yalnızca maç öncesi karar desteklenir (canlı bahis kapsam dışı).")
    elif a.kickoff is None and a.match_date is not None and decision_time.astimezone(ISTANBUL).date() >= a.match_date:
        blockers.add("INSUFFICIENT_DATA")
        reasons.append("Başlama saati bilinmiyor: ihtiyat gereği maç günü ve sonrasında karar üretilmez.")
    # Veri tahmine uygun değilse olasılıktan türetilen hiçbir değer (aralık, güvenli olasılık, gereken oran) taşınmaz
    p_low, p_high = (a.p_low, a.p_high) if forecast_ok else (None, None)
    p_safe = p_low if (p_low is not None and math.isfinite(p_low)) else None
    fair = fair_odds(p) if math.isfinite(p) and p > 0 else None
    d_min = min_required_odds(p_safe, policy.min_edge_safe, policy.commission) if p_safe else None
    if not a.model_validated:
        blockers.add("MODEL_NOT_VALIDATED")
        reasons.append("Model bu pazar için zaman sıralı testte doğrulama ölçütlerini geçmedi.")
    if (p_low is not None and p_high is not None and math.isfinite(p_low) and math.isfinite(p_high)
            and p_high - p_low > policy.max_interval_width):
        blockers.add("HIGH_UNCERTAINTY")
        reasons.append(f"Belirsizlik aralığı geniş ({p_low:.2f}–{p_high:.2f}).")

    odds = ev = ev_safe = be = nv = None
    q = a.quote
    if q is None:
        blockers.add("ODDS_UNAVAILABLE")
        reasons.append("Bu pazar ve çizgi için karar anına ait gerçek oran yok.")
    else:
        errs = validate_quote(q)
        if q.market_key != a.market_key:
            errs.append("ORAN_BASKA_PAZARA_AIT")
        if any(e.startswith("SONUCLANDIRMA_KURALI") for e in errs):
            blockers.add("SETTLEMENT_AMBIGUOUS")
        if any(e.startswith(("DONEM", "CIZGI", "SECIM", "BILINMEYEN", "ORAN_BASKA")) for e in errs):
            blockers.add("MARKET_UNSUPPORTED")
        if "GECERSIZ_ORAN" in errs or any(e.startswith("PAZAR_ACIK_DEGIL") for e in errs) or "ZAMAN_DILIMI_YOK" in errs:
            blockers.add("ODDS_UNAVAILABLE")
        reasons.extend(f"Oran kaydı: {e}" for e in errs)
        if a.kickoff is not None and q.quoted_at >= a.kickoff:
            errs.append("ORAN_MAC_BASLADIKTAN_SONRA")
            blockers.add("STALE_ODDS")
        if not errs:
            odds = q.decimal_odds
            be = breakeven_probability(odds, policy.commission)
            if is_stale(q, decision_time, policy.max_odds_age):
                blockers.add("STALE_ODDS")
                reasons.append(f"Oran karar anına uygun değil (zaman: {q.quoted_at.isoformat()}).")
            if math.isfinite(p):
                ev = expected_value(p, odds, policy.commission)
                if p_safe is not None:
                    ev_safe = expected_value(p_safe, odds, policy.commission)
                if ev > policy.max_plausible_ev:
                    blockers.add("SUSPICIOUS_EDGE")
                    reasons.append(f"Beklenen değer olağan dışı yüksek (%{100 * ev:.0f}); yanlış eşleşme/eski oran/veri hatası olabilir.")
            nv = no_vig_probability(q, a.opposite_quote) if a.opposite_quote is not None else None

    near = _near_threshold(odds, ev, ev_safe, p_low, p_high, policy)
    if near:
        reasons.append(f"{NEAR_THRESHOLD}: {', '.join(near)} — olasılıktaki ±{NUMERIC_TOLERANCE:g} sayısal fark bu kararı "
                       "değiştirebilir; durum ve eşikler değiştirilmedi.")
    if blockers:
        status = next(s for s in _PRIORITY if s in blockers)
    elif ev_safe is None:
        status = "HIGH_UNCERTAINTY"
        reasons.append("Belirsizlik bilgisi olmadan öneri üretilmez.")
    elif ev_safe >= policy.min_edge_safe:
        status = "VALUE_CANDIDATE"
        reasons.append(f"Belirsizlik dahil beklenen getiri %{100 * ev_safe:.1f} ≥ %{100 * policy.min_edge_safe:.0f}.")
    else:
        status = "NO_VALUE"
        reasons.append(
            f"Oran yetersiz: belirsizlik dahil beklenen getiri %{100 * ev_safe:.1f}"
            + (f"; gereken en düşük oran {d_min:.2f}." if d_min else ".")
        )
    elig = a.eligibility.compact() if hasattr(a.eligibility, "compact") else None
    if data_block and elig is not None:
        elig = dict(elig, karar_engeli=list(data_block))
    return Decision(
        event_id=a.event_id, market_key=a.market_key, status=status, reasons=reasons, p=p, p_safe=p_safe,
        fair_odds=fair, odds=odds, breakeven=be, ev=ev, ev_safe=ev_safe, min_odds=d_min, no_vig=nv,
        policy_version=policy.version, decision_time=decision_time.isoformat(),
        data_eligibility=elig if elig is not None else {"politika": None, "karar_engeli": list(data_block)},
    )


def _near_threshold(odds, ev, ev_safe, p_low, p_high, policy: DecisionPolicy,
                    tol: float = NUMERIC_TOLERANCE) -> list[str]:
    """Kararın sayısal toleransla değişebileceği eşikler (EV = p·d − 1 ⇒ ΔEV = d·Δp)."""
    out = []
    if odds is not None:
        band = odds * tol
        if ev_safe is not None and abs(ev_safe - policy.min_edge_safe) <= band:
            out.append("asgari avantaj eşiği")
        if ev is not None and abs(ev - policy.max_plausible_ev) <= band:
            out.append("olağan dışı avantaj eşiği")
        if ev is not None and abs(ev) <= band:
            out.append("beklenen değer işareti")
    if (p_low is not None and p_high is not None and math.isfinite(p_low) and math.isfinite(p_high)
            and abs((p_high - p_low) - policy.max_interval_width) <= 2 * tol):
        out.append("belirsizlik genişliği eşiği")
    return out


def apply_concentration(decisions: list[Decision], leagues: dict[str, str], days: dict[str, str],
                        policy: DecisionPolicy = DecisionPolicy()) -> list[Decision]:
    """Risk yoğunlaşması: aynı maçta en fazla bir aday (pazarlar bağımlı: A ⊂ B, A ⊂ C),
    gün ve lig-gün başına üst sınır. Sınırı aşan adaylar NO_VALUE'ya düşer (gerekçeli)."""
    cands = sorted((d for d in decisions if d.status == "VALUE_CANDIDATE"), key=lambda d: -(d.ev_safe or 0))
    per_event: set[str] = set()
    per_day: dict[str, int] = {}
    per_league_day: dict[tuple, int] = {}
    for d in cands:
        day = days.get(d.event_id, "")
        lg = leagues.get(d.event_id, "")
        why = None
        if d.event_id in per_event:
            why = "Aynı maçta başka bir aday var (pazarlar birbirine bağımlı; ayrı ayrı çeşitlendirme sayılmaz)."
        elif per_day.get(day, 0) >= policy.max_candidates_per_day:
            why = "Günlük aday sınırı aşıldı."
        elif per_league_day.get((lg, day), 0) >= policy.max_candidates_per_league_day:
            why = "Aynı lig ve günde aday sınırı aşıldı."
        if why:
            d.status = "NO_VALUE"
            d.reasons.append(why)
            continue
        per_event.add(d.event_id)
        per_day[day] = per_day.get(day, 0) + 1
        per_league_day[(lg, day)] = per_league_day.get((lg, day), 0) + 1
    return decisions

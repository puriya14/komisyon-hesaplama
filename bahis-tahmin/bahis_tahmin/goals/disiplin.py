"""Bahis disiplini (DISIPLIN-07): sanal takipte portföy kuralları, stake yöntemi ve gerçek para hazırlık ölçütü.

* **Portföy kuralları (kayıt anında, defterdeki önceki kayıtlarla birlikte):** aynı maçta ikinci sanal bahis yok
  (aynı maçın pazarları birbirine bağlıdır: A ⊂ B, A ⊂ C); bir maç gününde en fazla ``max_candidates_per_day``, aynı lig
  ve maç gününde en fazla ``max_candidates_per_league_day`` sanal bahis. Karar motorunun ``apply_concentration``'ı aynı
  sınırları yalnızca tek bir kayıt işlemi içinde uygular; burada daha önce kaydedilmiş bahisler de sayılır.
* **Stake yöntemi:** "sabit" (1 birim = 100 birimlik başlangıç sanal kasasının %1'i; varsayılan) veya "kelly" (sanal
  kasa × kesir × Kelly payı, güvenli olasılık p_safe ile; tek bahiste kasanın en fazla ``cap`` kadarı). Sanal kasa:
  100 birim + sonuçlanmış sanal bahislerin neti.
* **Gerçek para hazırlık ölçütü** (``HAZIRLIK_KURALI``): önceden yazılmış, sürümlü; metnin parmak izi
  ``HAZIRLIK_SHA256`` (testte doğrulanır, docs/DISIPLIN_07.md).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from .decision import Decision, DecisionPolicy
from .value import kelly_fraction

DISIPLIN_VERSION = "disiplin-v1"
SANAL_KASA = 100.0
FLAT_VERSION = "sanal-sabit-birim-v1"
STAKE_METHODS = {  # ayrıntı: Staking.text() ve ayarlar sayfasındaki açıklama
    "sabit": "Sabit küçük pay (%1)",
    "kelly": "Kesirli Kelly (tavanlı)",
}

HAZIRLIK_VERSION = "hazirlik-v1"
HAZIRLIK_KURALI = """hazirlik-v1 — gerçek para hazırlık ölçütü (2026-10-16, kod yazılmadan ve hiçbir defterde çalıştırılmadan önce)

Sanal takip defterindeki sanal bahisler (stake > 0, oranlı kayıtlar) üzerinden. Altı koşulun HEPSİ sağlanırsa
"ölçüt karşılandı", aksi halde "ölçüt karşılanmadı" yazılır.

1. Kayıt zinciri sağlam (verify_chain).
2. En az 200 sonuçlanmış (WIN/LOSS) sanal bahis. VOID, PENDING, UNKNOWN sayılmaz.
3. En az 100 sanal bahiste marjsız CLV ölçülmüş (kapanış oranı ve karşı tarafın kapanış oranı girilmiş, zamanlama
   geçerli; ORAN-03 kuralları).
4. Ortalama marjsız CLV'nin %95 alt sınırı > 0 (normal yaklaşım: ortalama − 1,96·sd/√n).
5. Getirinin (yield = net / toplam stake, sonuçlanmış bahisler) %95 üst sınırı > 0. Aralık oran tahmincisiyle:
   yield ± 1,96·√(n/(n−1)·Σ(net_i − yield·stake_i)²)/Σstake_i. Sabit stake'te bahis başına getirinin ortalama aralığıyla
   aynıdır.
6. Sanal kasanın zirveden en büyük düşüşü < %30. Sanal kasa: 100 birim + sonuçlanmış bahislerin karar zamanı
   sırasıyla birikimli neti; düşüş = (zirve − kasa) / zirve, zirve başlangıç kasası dahil.

Ölçüt karşılansa bile kâr garantisi değildir; yalnızca önceden yazılmış asgari kanıttır. Ölçüt değiştirilirse sürüm
artırılır (hazirlik-v2) ve eski sürümün sonucu da gösterilir.
"""
HAZIRLIK_SHA256 = "c007300ef3b7ded3ce9f32b072ad361933722bdf291577697947236057e42fd5"
MIN_SETTLED = 200
MIN_CLV = 100
MAX_DRAWDOWN = 0.30


def rule_fingerprint() -> str:
    return hashlib.sha256(HAZIRLIK_KURALI.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------------ stake
@dataclass(frozen=True)
class Staking:
    method: str = "sabit"
    fraction: float = 0.25  # Kelly kesri (0,25 = çeyrek Kelly)
    cap: float = 0.05  # tek bahiste sanal kasanın en fazla bu kadarı
    units: float = 1.0  # sabit yöntemde birim

    @classmethod
    def from_settings(cls, s) -> "Staking":
        m = getattr(s, "sanal_stake_yontemi", "sabit")
        return cls(method=m if m in STAKE_METHODS else "sabit",
                   fraction=float(getattr(s, "kelly_fraction", 0.25) or 0.0),
                   cap=float(getattr(s, "max_stake_pct", 0.05) or 0.0))

    @property
    def version(self) -> str:
        if self.method == "kelly":
            return f"sanal-kesirli-kelly-v1 (kesir {self.fraction:g}, tavan {self.cap:g})"
        return FLAT_VERSION

    def stake(self, d: Decision, kasa: float) -> float:
        """Bir aday için sanal stake (birim). Kelly'de p_safe ve oran sonlu değilse veya kasa tükenmişse 0."""
        if self.method != "kelly":
            return float(self.units)
        p, o = d.p_safe, d.odds
        if not (kasa > 0) or p is None or o is None or not (math.isfinite(p) and math.isfinite(o)):
            return 0.0
        return round(kasa * kelly_fraction(p, o, self.fraction, self.cap), 4)

    def text(self) -> str:
        if self.method == "kelly":
            return (f"kesirli Kelly (kesir {self.fraction:g}, tek bahiste sanal kasanın en fazla "
                    f"%{100 * self.cap:g}'i; güvenli olasılıkla)").replace(".", ",")
        return "sabit 1 birim (100 birimlik sanal kasanın %1'i)"


# ------------------------------------------------------------------------------------------------ defter
def is_bet(rec: dict) -> bool:
    return (rec.get("stake_units") or 0) > 0 and bool(rec.get("odds"))


def match_day(rec: dict) -> str:
    """Kaydın maç günü (yeni kayıtlarda ``mac_gunu``; eski kayıtlarda başlama zamanının tarih kısmı)."""
    return str(rec.get("mac_gunu") or str(rec.get("kickoff") or "")[:10])


def bet_net(rec: dict) -> float | None:
    """Sonuçlanmış (WIN/LOSS) sanal bahsin neti; değilse None."""
    o = rec.get("outcome") or {}
    if not is_bet(rec) or o.get("settlement") not in ("WIN", "LOSS"):
        return None
    s = float(rec["stake_units"])
    return s * (float(rec["odds"]) - 1.0) if o["settlement"] == "WIN" else -s


def virtual_bankroll(records: list[dict]) -> float:
    return SANAL_KASA + sum(n for n in (bet_net(r) for r in records) if n is not None)


def portfolio_block(bets: list[dict], event_id: str, league: str, day: str,
                    policy: DecisionPolicy = DecisionPolicy()) -> str | None:
    """Defterdeki sanal bahislerle birlikte portföy sınırı aşılıyorsa gerekçe; aşılmıyorsa None."""
    if any(b.get("event_id") == event_id for b in bets):
        return ("Bu maçta zaten sanal bahis kayıtlı (aynı maçtaki pazarlar birbirine bağlı; ikinci bahis çeşitlendirme "
                "sayılmaz). Sanal stake yok.")
    same = [b for b in bets if match_day(b) == day]
    if len(same) >= policy.max_candidates_per_day:
        return (f"Bu maç gününde zaten {len(same)} sanal bahis kayıtlı (günlük sınır "
                f"{policy.max_candidates_per_day}). Sanal stake yok.")
    n_lg = sum(1 for b in same if b.get("league") == league)
    if n_lg >= policy.max_candidates_per_league_day:
        return (f"Aynı lig ve maç gününde zaten {n_lg} sanal bahis kayıtlı (sınır "
                f"{policy.max_candidates_per_league_day}). Sanal stake yok.")
    return None


def discipline_line(staking: Staking, policy: DecisionPolicy = DecisionPolicy()) -> str:
    return (f"Bahis disiplini ({DISIPLIN_VERSION}): sanal stake {staking.text()} · aynı maçta tek sanal bahis · maç "
            f"gününde en fazla {policy.max_candidates_per_day}, aynı lig ve günde en fazla "
            f"{policy.max_candidates_per_league_day} sanal bahis (önceki kayıtlar dahil).")


# ------------------------------------------------------------------------------------------------ hazırlık
def _pct(v, k=1) -> str:
    return "hesaplanamıyor" if v is None else f"{100 * v:+.{k}f}%".replace(".", ",")


def readiness(ledger) -> dict:
    """``HAZIRLIK_KURALI``'nın değerlendirmesi. ``ledger`` None ise boş defter gibi."""
    from .clv import clv_summary

    if ledger is None:
        recs, chain_ok, clv = [], True, {"marjsiz_n": 0, "marjsiz_ort": None, "marjsiz_alt": None}
    else:
        recs = ledger.predictions()
        chain_ok = bool(ledger.verify_chain()[0])
        clv = clv_summary(ledger)
    settled = sorted(((r, bet_net(r)) for r in recs if bet_net(r) is not None), key=lambda t: t[0]["decision_time"])
    n = len(settled)
    stakes = [float(r["stake_units"]) for r, _ in settled]
    nets = [x for _, x in settled]
    tot = sum(stakes)
    y = sum(nets) / tot if tot else None
    y_hi = None
    if y is not None and n >= 2:
        v = n / (n - 1) * sum((x - y * s) ** 2 for x, s in zip(nets, stakes))
        y_hi = y + 1.96 * math.sqrt(v) / tot
    kasa = peak = SANAL_KASA
    dd = 0.0
    for x in nets:
        kasa += x
        peak = max(peak, kasa)
        dd = max(dd, (peak - kasa) / peak if peak > 0 else 1.0)
    m, lo = clv.get("marjsiz_n") or 0, clv.get("marjsiz_alt")
    conds = [
        ("zincir", chain_ok, "kayıt zinciri sağlam" if chain_ok else "kayıt zinciri BOZUK"),
        ("sonuclanan", n >= MIN_SETTLED, f"sonuçlanan sanal bahis {n}/{MIN_SETTLED}"),
        ("clv_n", m >= MIN_CLV, f"marjsız CLV ölçülen bahis {m}/{MIN_CLV}"),
        ("clv_alt", lo is not None and lo > 0, f"ortalama marjsız CLV'nin %95 alt sınırı > 0: {_pct(lo)}"),
        ("getiri_ust", y_hi is not None and y_hi > 0, f"getirinin %95 üst sınırı > 0: {_pct(y_hi)}"),
        ("dusus", dd < MAX_DRAWDOWN, f"zirveden en büyük düşüş %{100 * dd:.0f} < %{100 * MAX_DRAWDOWN:.0f}"),
    ]
    return {"version": HAZIRLIK_VERSION, "ok": all(c[1] for c in conds), "conditions": conds, "settled": n,
            "clv_n": m, "clv_alt": lo, "yield": y, "yield_ust": y_hi, "drawdown": dd, "kasa": kasa}


def readiness_text(r: dict) -> str:
    """Tek satır (masaüstü, web ve CLI aynı metni kullanır)."""
    met = sum(1 for c in r["conditions"] if c[1])
    parts = " · ".join(f"{t} ({'tamam' if ok else 'eksik'})" for _, ok, t in r["conditions"])
    if r["ok"]:
        return (f"Gerçek para hazırlık ölçütü ({r['version']}): KARŞILANDI ({met}/{len(r['conditions'])}). {parts}. "
                "Bu önceden yazılmış asgari kanıttır, kâr garantisi değildir; gerçek parayla başlarsanız sabit küçük "
                "payla ve önceden belirlediğiniz kayıp sınırıyla başlayın.")
    return (f"Gerçek para hazırlık ölçütü ({r['version']}): karşılanmadı ({met}/{len(r['conditions'])}); gerçek parayla "
            f"başlamadan önce sanal takibe devam edin. {parts}.")


__all__ = ["DISIPLIN_VERSION", "HAZIRLIK_KURALI", "HAZIRLIK_SHA256", "HAZIRLIK_VERSION", "MAX_DRAWDOWN", "MIN_CLV",
           "MIN_SETTLED", "SANAL_KASA", "STAKE_METHODS", "Staking", "bet_net", "discipline_line", "is_bet", "match_day",
           "portfolio_block", "readiness", "readiness_text", "rule_fingerprint", "virtual_bankroll"]

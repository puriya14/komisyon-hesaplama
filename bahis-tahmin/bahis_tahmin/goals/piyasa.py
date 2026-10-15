"""Piyasanın 2,5 Üst/Alt oranından maçın gol düzeyi (ORAN-04).

Yöntem (``tools/research/piyasa_duzey.py`` P1; ön kayıtlı sınamada geliştirme ve test döneminde kabul edildi,
docs/ORAN_04.md):

* Piyasa olasılığı p_m: aynı şirketin 2,5 Üst ve 2,5 Alt oranlarından marjı orantılı olarak çıkarılmış olasılık.
* Lig maçı: bütün takım gücü girdileri (l1h, l1a, l2h, l2a, lh, la) tek bir s ile çarpılır. s, modelin yapısal 2,5 Üst
  olasılığı p_m'ye eşit olacak biçimde bulunur (s ∈ [0,25; 4], log ölçekte 30 adım ikiye bölme). Tahmin hattının
  tamamı (ayarlayıcı + ortak dağılım + IPF + A kalibrasyonu) ölçeklenmiş girdilerle yeniden çalışır.
* Kupa maçı: kalibre gol beklentileri λ', ν' aynı k ile çarpılır; k, maç sonu toplam golün Poisson dağılımında
  P(≥ 3) = p_m olacak biçimde bulunur. Kupa maçlarında geçmiş oran olmadığı için bu uyarlama geçmişte SINANMADI.

Oran kaynakları (öncelik sırasıyla): kullanıcının karar anından önce kaydettiği 2,5 Üst ve 2,5 Alt oranları (sanal takip
oran tablosu; aynı şirket, en fazla 10 dk arayla) ve football-data fikstür dosyasındaki ortalama oranlar.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

MARKET_VERSION = "piyasa-duzey-v1"
MARKET_SUFFIX = "+" + MARKET_VERSION
RATE_COLS = ("l1h", "l1a", "l2h", "l2a", "lh", "la")
S_LO, S_HI, S_ITERS = 0.25, 4.0, 30
OVER, UNDER = "FT_OVER_2_5", "FT_UNDER_2_5"


@dataclass(frozen=True)
class MarketLevel:
    """Bir maçın piyasa 2,5 Üst olasılığı ve kaynağı."""
    p: float
    over: float
    under: float
    source: str  # "girilen oran" / "fikstür ortalama oranı"
    bookmaker: str = ""
    quoted_at: str = ""

    def to_dict(self) -> dict:
        return {"p": self.p, "ust": self.over, "alt": self.under, "kaynak": self.source, "sirket": self.bookmaker,
                "zaman": self.quoted_at}


def market_prob(o_over, o_under):
    """Marjı orantılı olarak çıkarılmış 2,5 Üst olasılığı (dizi ya da tek sayı)."""
    io, iu = 1.0 / np.asarray(o_over, dtype=float), 1.0 / np.asarray(o_under, dtype=float)
    return io / (io + iu)


def _valid_odds(v) -> bool:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(v) and 1.0 < v <= 1000.0


def from_odds(over, under, source: str, bookmaker: str = "", quoted_at: str = "") -> MarketLevel | None:
    if not (_valid_odds(over) and _valid_odds(under)):
        return None
    return MarketLevel(float(market_prob(float(over), float(under))), float(over), float(under), source, bookmaker,
                       quoted_at)


def from_fixture(row) -> MarketLevel | None:
    """football-data fikstür dosyasındaki ortalama 2,5 Üst/Alt oranları (sütunlar yoksa None)."""
    return from_odds(getattr(row, "o_o25", None), getattr(row, "o_u25", None), "fikstür ortalama oranı")


def from_ledger(ledger, event: str, before: dt.datetime) -> MarketLevel | None:
    """Karar anından önce kaydedilmiş en güncel 2,5 Üst ve 2,5 Alt oranı (aynı şirket, en fazla 10 dk arayla)."""
    from .value import no_vig_probability

    if ledger is None:
        return None
    yes = ledger.latest_quote(event, OVER, before)
    no = ledger.latest_quote(event, UNDER, before)
    p = no_vig_probability(yes, no)
    if p is None:
        return None
    return MarketLevel(float(p), float(yes.decimal_odds), float(no.decimal_odds), "girilen oran", yes.bookmaker,
                       max(yes.quoted_at, no.quoted_at).isoformat())


# ------------------------------------------------------------------------------------------------ lig
def scaled(X: pd.DataFrame, s) -> pd.DataFrame:
    out = X.copy()
    s = np.asarray(s, dtype=float)
    for c in RATE_COLS:
        out[c] = out[c].to_numpy(dtype=float) * s
    return out


def market_scale(model, X: pd.DataFrame, p_m) -> np.ndarray:
    """Satır başına s: modelin yapısal 2,5 Üst olasılığı p_m'ye eşit (sınırlarda kırpılır)."""
    p_m = np.asarray(p_m, dtype=float)
    lo = np.full(len(X), np.log(S_LO))
    hi = np.full(len(X), np.log(S_HI))
    base = model.base if getattr(model, "base", None) is not None else model
    for _ in range(S_ITERS):
        mid = (lo + hi) / 2
        p = base.predict(scaled(X, np.exp(mid)))["FT_O25"]
        up = p < p_m
        lo = np.where(up, mid, lo)
        hi = np.where(up, hi, mid)
    return np.exp((lo + hi) / 2)


# ------------------------------------------------------------------------------------------------ kupa
def poisson_scale(mu_total: float, p_m: float) -> float:
    """k: Poisson(k·μ) toplamında P(≥ 3) = p_m (k ∈ [0,25; 4], log ölçekte ikiye bölme)."""
    lo, hi = math.log(S_LO), math.log(S_HI)
    for _ in range(S_ITERS):
        mid = (lo + hi) / 2
        m = math.exp(mid) * mu_total
        over = 1.0 - math.exp(-m) * (1.0 + m + m * m / 2.0)
        if over < p_m:
            lo = mid
        else:
            hi = mid
    return math.exp((lo + hi) / 2)


def card_text(info: dict) -> str:
    """Model kartı / satır notu: kullanılan piyasa düzeyi."""
    m = (info or {}).get("piyasa")
    if not m:
        return ""
    def num(v, d):
        return f"{v:.{d}f}".replace(".", ",")

    sirket = f", {m['sirket']}" if m.get("sirket") else ""
    return (f"piyasa gol düzeyi ×{num(m['olcek'], 3)} (2,5 Üst %{num(100 * m['p'], 1)}; oranlar {num(m['ust'], 2)} / "
            f"{num(m['alt'], 2)}; {m['kaynak']}{sirket})")


def market_status_text(engine) -> str:
    """Durum satırı: piyasa düzeyli tahminlerin (2,5 Üst/Alt oranı varken) doğrulama statüsü."""
    vm = getattr(engine, "validated_market", None) or {}
    if not vm or not (getattr(engine, "validation_market", None) or {}):
        return "Piyasa düzeyli tahminler (2,5 Üst/Alt oranı varken): doğrulama ölçümü yok (modeli yeniden eğitin)."
    names = (("A", "BTTS_BOTH_HALVES_YES"), ("B", "FT_OVER_3_5"), ("C", "FH_OVER_1_5"))
    return ("Piyasa düzeyli tahminler (2,5 Üst/Alt oranı varken): "
            + " · ".join(f"{s}: {'doğrulandı (sanal takip)' if vm.get(k) else 'DOĞRULANMADI'}" for s, k in names) + ".")


def league_validation_rows(engine) -> list[dict]:
    """Model doğrulama tablosu (masaüstü ve web): her pazar için modelin kendi ölçümü ve (varsa) piyasa düzeyli
    tahminlerin aynı sezonlardaki ölçümü (oranı olan maçlar)."""
    from .markets import MARKETS, PRIMARY_YES

    rows = []
    if engine is None or not engine.validation:
        return rows
    vm = getattr(engine, "validation_market", None) or {}
    validated_m = getattr(engine, "validated_market", None) or {}
    for key in PRIMARY_YES:
        for label, val, model, ok in (
                ("Model", engine.validation, engine.variant, engine.validated.get(key)),
                ("Piyasa düzeyli (2,5 oranı)", vm, f"{engine.variant}{MARKET_SUFFIX}", validated_m.get(key))):
            r = val.get(key, {})
            m = r.get("modeller", {}).get(model, {})
            b = engine.validation.get(key, {}).get("modeller", {}).get("M0_taban", {})
            if not m:
                continue
            rows.append({"Pazar": MARKETS[key].name_tr, "Tahmin": label, "Maç": r["n"], "Pozitif": r["pozitif"],
                         "Taban oran": r["taban_oran"], "LL model": m["log_loss"],
                         "LL taban": m["log_loss"] - m["ll_fark_ref"], "Δ LL": m["ll_fark_ref"],
                         "Δ alt": m["ll_fark_alt"], "Δ üst": m["ll_fark_ust"], "Brier becerisi": m["brier_skill"],
                         "AP model": m["ap"], "AP taban": b.get("ap", float("nan")), "Kal. eğim": m["kal_egim"],
                         "ECE": m["ece"],
                         "Statü": "VALIDATED_FOR_PAPER_TRADING" if ok else "MODEL_NOT_VALIDATED"})
    return rows


def league_inputs_text(info: dict) -> str:
    """Lig maçı model kartının "Girdiler" metni (masaüstü ve web aynı metni kullanır)."""
    base = ("ilk yarı / ikinci yarı / maç sonu Poisson takım güçleri (yalnızca maçtan önceki günlerin sonuçları), lig "
            "ilk yarı gol payı, yakın dönem yarı bazlı gol sıklıkları, lig taban oranları. ")
    market = card_text(info)
    if market:
        return (base + f"Maçın 2,5 Üst/Alt oranı yalnızca gol düzeyi için kullanıldı: {market}. Piyasa düzeyli "
                "tahminlerin doğrulama statüsü ayrıca ölçülür (ORAN-04). Kadro, sakatlık, xG ve hava durumu verisi "
                "KULLANILMIYOR.")
    return (base + "Bahis oranları, kadro, sakatlık, xG ve hava durumu verisi KULLANILMIYOR. Maçın 2,5 Üst/Alt oranını "
            "girerseniz tahmin piyasanın gol düzeyine ölçeklenir (ORAN-04: geçmiş verideki ön kayıtlı sınamada üç "
            "pazarın toplam log-kaybını iyileştirdi).")


__all__ = ["MARKET_SUFFIX", "MARKET_VERSION", "MarketLevel", "card_text", "from_fixture", "from_ledger", "from_odds",
           "league_inputs_text", "league_validation_rows", "market_prob", "market_status_text", "market_scale", "poisson_scale", "scaled"]

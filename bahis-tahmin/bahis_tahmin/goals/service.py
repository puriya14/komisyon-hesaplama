"""Gol pazarları için uygulama servisleri: karar üretimi ve sanal takip sonuçlandırması.

Arayüzden bağımsızdır; testlerde doğrudan kullanılır.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from .decision import Assessment, Decision, DecisionPolicy, apply_concentration, decide
from .engine import GoalEngine, GoalPrediction
from .ledger import Ledger, event_id
from .markets import MARKETS, MatchStatus, PeriodScore, label, settle
from .model import FEATURE_VERSION, MODEL_VERSION

SELECTIONS = ("BTTS_BOTH_HALVES_YES", "BTTS_BOTH_HALVES_NO", "FT_OVER_3_5", "FT_UNDER_3_5", "FH_OVER_1_5", "FH_UNDER_1_5")
STRATEGY_VERSION = "sanal-sabit-birim-v1"


def decisions_for(pred: GoalPrediction, engine: GoalEngine, ledger: Ledger | None, decision_time: dt.datetime,
                  policy: DecisionPolicy = DecisionPolicy()) -> list[Decision]:
    """Bir maçın altı seçimi için kararlar (oranlar yalnızca karar anından önceki kayıtlardan)."""
    out = []
    for key in SELECTIONS:
        primary_yes = key if MARKETS[key].selection in ("YES", "OVER") else MARKETS[key].complement
        q = ledger.latest_quote(pred.event_id, key, decision_time) if ledger else None
        opp = ledger.latest_quote(pred.event_id, MARKETS[key].complement, decision_time) if ledger else None
        lo, hi = pred.interval(key)
        a = Assessment(
            event_id=pred.event_id, league=pred.league, home=pred.home, away=pred.away, market_key=key,
            p=pred.p(key), p_low=lo, p_high=hi, model_validated=engine.validated.get(primary_yes, False),
            data_notes=list(pred.data_notes), quote=q, opposite_quote=opp, kickoff=pred.kickoff_utc,
            match_date=pd.Timestamp(pred.date).date(),
        )
        out.append(decide(a, decision_time, policy))
    leagues = {pred.event_id: pred.league}
    days = {pred.event_id: str(pred.date.date())}
    return apply_concentration(out, leagues, days, policy)


def record_decisions(ledger: Ledger, pred: GoalPrediction, decisions: list[Decision], engine: GoalEngine,
                     stake_units: float = 1.0) -> list[str]:
    """Kararları değişmez sanal kayıt olarak ekler. Yalnızca VALUE_CANDIDATE için sanal birim stake konur."""
    from .forecast_log import RECORD_BET, RECORD_DECISION

    ids = []
    for d in decisions:
        ids.append(ledger.record_prediction({
            # Bahis adayı kaydı yalnızca VALUE_CANDIDATE (zamanı doğrulanmış gerçek oranla); diğerleri karar kaydıdır.
            "kayit_turu": RECORD_BET if d.status == "VALUE_CANDIDATE" else RECORD_DECISION,
            "event_id": d.event_id, "league": pred.league, "home": pred.home, "away": pred.away,
            "kickoff": pred.kickoff_utc.isoformat() if pred.kickoff_utc else str(pred.date.date()),
            "market_key": d.market_key, "decision_time": d.decision_time,
            "model_version": f"{MODEL_VERSION}/{engine.variant}", "feature_version": FEATURE_VERSION,
            "data_cutoff": engine.data_cutoff, "p": d.p, "p_low": d.p_safe, "odds": d.odds,
            "decision_status": d.status, "reasons": d.reasons, "ev": d.ev, "ev_safe": d.ev_safe,
            "stake_units": stake_units if d.status == "VALUE_CANDIDATE" else 0.0,
            "strategy_version": STRATEGY_VERSION, "policy_version": d.policy_version,
        }))
    return ids


def settle_pending(ledger: Ledger, matches: pd.DataFrame, source: str = "veri deposu") -> dict:
    """Sonucu belli olan bekleyen sanal kayıtlara sonuç olayı ekler (idempotent)."""
    if matches is None or matches.empty:
        return {"sonuclanan": 0, "bekleyen": 0}
    idx = {event_id(r.league, r.date, r.home, r.away): r for r in matches.itertuples(index=False)}
    done = pending = 0
    for rec in ledger.predictions():
        if rec["outcome"] is not None and rec["outcome"]["settlement"] in ("WIN", "LOSS", "VOID"):
            continue
        if rec.get("p") is None or rec.get("market_key") is None:
            continue  # olasılıksız kayıtlar (TAHMIN_YOK, geçersiz ilan) sonuçlandırılmaz
        r = idx.get(rec["event_id"])
        if r is None:
            pending += 1
            continue
        ht_ok = pd.notna(r.hthg) and pd.notna(r.htag)
        ps = PeriodScore(fthg=r.fthg, ftag=r.ftag, hthg=r.hthg if ht_ok else None, htag=r.htag if ht_ok else None,
                         status=MatchStatus.FINISHED)
        st = settle(rec["market_key"], ps)
        ledger.record_outcome(rec["id"], st.value, label(rec["market_key"], ps).value, source)
        done += 1
    return {"sonuclanan": done, "bekleyen": pending}

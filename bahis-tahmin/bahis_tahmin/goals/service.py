"""Gol pazarları için uygulama servisleri: uygunluk kontrollü tahmin, karar üretimi ve sanal takip.

Arayüzden bağımsızdır; testlerde doğrudan kullanılır. Kullanıcıya dönük her yol (tarama, maç analizi, elle seçim,
CLI, kayıt) tahminleri ``gated_goal_predictions`` / ``gated_goal_match`` üzerinden alır ve kararlara aynı uygunluk
sonucunu verir (``bahis_tahmin.eligibility``). Uygunluk verilmeden üretilen kararlar ``DATA_NOT_ELIGIBLE`` olur.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from ..eligibility import GOAL_MARKETS, FixtureVerdict, finite_or_none, not_evaluated, valid_probability
from .decision import Assessment, Decision, DecisionPolicy, apply_concentration, decide
from .engine import GoalEngine, GoalPrediction
from .ledger import Ledger, event_id
from .markets import MARKETS, MatchStatus, PeriodScore, label, settle
from .model import FEATURE_VERSION, MODEL_VERSION

SELECTIONS = ("BTTS_BOTH_HALVES_YES", "BTTS_BOTH_HALVES_NO", "FT_OVER_3_5", "FT_UNDER_3_5", "FH_OVER_1_5", "FH_UNDER_1_5")
STRATEGY_VERSION = "sanal-sabit-birim-v1"


def prediction_codes(pred: GoalPrediction) -> tuple[str, ...]:
    """Motorun yapılandırılmış veri kodları + pazar başına geçersiz olasılık kodu (uygunluk kontrolü için)."""
    codes = list(pred.data_codes)
    for mk in GOAL_MARKETS:
        try:
            ok = valid_probability(pred.p(mk))
        except KeyError:
            ok = False
        if not ok:
            codes.append(f"OLASILIK_GECERSIZ:{mk}")
    return tuple(sorted(set(codes)))


def gated_goal_predictions(engine: GoalEngine | None, ctx, fixtures: pd.DataFrame | None, as_of: dt.datetime,
                           unmatched: pd.DataFrame | None = None, with_interval: bool = True) -> list[FixtureVerdict]:
    """Toplu fikstür: her fikstür için (tahmin + pazar başına uygunluk). Modelde olmayan lig ve eşleşmeyen takım
    sessizce düşürülmez; nedenli "tahmin yok" sonucu olarak döner."""
    out: list[FixtureVerdict] = []
    fx = fixtures if fixtures is not None else pd.DataFrame()
    preds = {}
    if engine is not None and engine.trained and not fx.empty:
        preds = {p.event_id: p for p in engine.predict_fixtures(fx, with_interval=with_interval)}
    for r in fx.itertuples(index=False):
        eid = event_id(r.league, r.date, r.home, r.away)
        pred = preds.get(eid)
        out.append(_verdict(ctx, r.league, r.date, getattr(r, "time", "") or "", r.home, r.away, as_of, pred,
                            source=getattr(r, "source", "") or ""))
    for r in (unmatched if unmatched is not None else pd.DataFrame()).itertuples(index=False):
        out.append(_verdict(ctx, r.league, r.date, getattr(r, "time", "") or "", r.raw_home, r.raw_away, as_of, None,
                            source=getattr(r, "source", "") or "", mapped=False))
    return out


def gated_goal_match(engine: GoalEngine | None, ctx, league: str, home: str, away: str, date, as_of: dt.datetime,
                     time_str: str = "", source: str = "manuel") -> FixtureVerdict:
    """Tek maç / elle takım seçimi: aynı uygunluk kontrolü."""
    pred = None
    if engine is not None and engine.trained and league in engine.states:
        pred = engine.predict_match(league, home, away, date, time_str, source=source)
    return _verdict(ctx, league, pd.Timestamp(date).normalize(), time_str, home, away, as_of, pred, source=source)


def _verdict(ctx, league, date, time_str, home, away, as_of, pred, source="", mapped=True) -> FixtureVerdict:
    from ..eligibility import candidate_id

    eid = event_id(league, date, home, away) if mapped else candidate_id(source, league, date, home, away)
    if ctx is None:
        by = {mk: not_evaluated(eid, mk, as_of, canonical=mapped) for mk in GOAL_MARKETS}
    else:
        by = ctx.evaluate(league=league, date=date, home=home, away=away, as_of=as_of, markets=GOAL_MARKETS,
                          source=source, mapped=mapped, raw_home=None if mapped else home,
                          raw_away=None if mapped else away,
                          prediction_codes=prediction_codes(pred) if pred is not None else None, event_id=eid)
    return FixtureVerdict(league=league, date=pd.Timestamp(date), time=time_str, home=home, away=away,
                          candidate_id=eid, canonical_id=mapped, by_market=by, prediction=pred)


def model_validated(pred: GoalPrediction, engine: GoalEngine | None) -> dict:
    """Tahminin pazar başına doğrulama statüsü: tahmine özgüyse (kupa maçları: turnuvanın doğrulama grubu) o, değilse
    motorun genel statüsü; motor yoksa hiçbir pazar doğrulanmış sayılmaz."""
    own = getattr(pred, "validated", None)
    if own is not None:
        return own
    return dict(getattr(engine, "validated", None) or {})


def is_cup_prediction(pred) -> bool:
    return bool((getattr(pred, "info", None) or {}).get("kupa"))


def decisions_for(pred: GoalPrediction, engine: GoalEngine | None, ledger: Ledger | None, decision_time: dt.datetime,
                  policy: DecisionPolicy = DecisionPolicy(), eligibility=None) -> list[Decision]:
    """Bir maçın altı seçimi için kararlar (oranlar yalnızca karar anından önceki kayıtlardan).

    ``eligibility``: bu maç için ``FixtureVerdict`` veya pazar -> ``Eligibility`` sözlüğü. Verilmezse (bağlamsız
    çağrı) bütün seçimler ``DATA_NOT_ELIGIBLE`` olur; koruma varsayılan olarak aşılmaz. Kupa maçlarında (KUPA-GOL-02)
    doğrulama statüsü tahminin kendisinden gelir (``model_validated``)."""
    by = eligibility.by_market if isinstance(eligibility, FixtureVerdict) else (eligibility or {})
    validated = model_validated(pred, engine)
    out = []
    for key in SELECTIONS:
        primary_yes = key if MARKETS[key].selection in ("YES", "OVER") else MARKETS[key].complement
        q = ledger.latest_quote(pred.event_id, key, decision_time) if ledger else None
        opp = ledger.latest_quote(pred.event_id, MARKETS[key].complement, decision_time) if ledger else None
        lo, hi = pred.interval(key)
        a = Assessment(
            event_id=pred.event_id, league=pred.league, home=pred.home, away=pred.away, market_key=key,
            p=pred.p(key), p_low=lo, p_high=hi, model_validated=bool(validated.get(primary_yes, False)),
            data_notes=list(pred.data_notes), quote=q, opposite_quote=opp, kickoff=pred.kickoff_utc,
            match_date=pd.Timestamp(pred.date).date(), eligibility=by.get(primary_yes),
            state_digest=pred.state_digest or None,
        )
        out.append(decide(a, decision_time, policy))
    leagues = {pred.event_id: pred.league}
    days = {pred.event_id: str(pred.date.date())}
    return apply_concentration(out, leagues, days, policy)


def _bet_still_valid(d: Decision, pred: GoalPrediction, record_time: dt.datetime) -> bool:
    """Önceden hesaplanmış aday kararı kayıt anında hâlâ geçerli mi? Karar ile kayıt aynı İstanbul gününde, karar
    anından önce olmayan bir anda ve maç başlamadan (saat bilinmiyorsa maç gününden) önce yapılmalı."""
    from ..eligibility import info_cutoff

    try:
        t = dt.datetime.fromisoformat(d.decision_time)
    except (TypeError, ValueError):
        return False
    if t.tzinfo is None or record_time < t - dt.timedelta(seconds=1) or info_cutoff(record_time) != info_cutoff(t):
        return False
    if pred.kickoff_utc is not None:
        return record_time < pred.kickoff_utc
    return info_cutoff(record_time) < pd.Timestamp(pred.date).date()


def record_decisions(ledger: Ledger, pred: GoalPrediction, decisions: list[Decision], engine: GoalEngine,
                     stake_units: float = 1.0, record_time: dt.datetime | None = None) -> list[str]:
    """Kararları değişmez sanal kayıt olarak ekler. Yalnızca VALUE_CANDIDATE için (veri uygunluğu da geçilmişse ve
    karar kayıt anında hâlâ geçerliyse) sanal birim stake konur; aksi halde karar kaydı (stake 0) yazılır. Veri uygun
    değilse olasılık yazılmaz (NaN/sonsuz/sahte sıfır yerine boş). ``record_time``: kayıt anı (varsayılan: şimdi)."""
    from .forecast_log import RECORD_BET, RECORD_DECISION

    record_time = record_time or dt.datetime.now(dt.timezone.utc)
    info = getattr(pred, "info", None) or {}
    # Kupa maçları (KUPA-GOL-02) kendi model sürümünü ve veri kesimini taşır
    model_version = info.get("model_version") or f"{MODEL_VERSION}/{engine.variant}"
    data_cutoff = info.get("data_cutoff") or engine.data_cutoff
    ids = []
    for d in decisions:
        elig = d.data_eligibility or {}
        bet = (d.status == "VALUE_CANDIDATE" and bool(elig.get("bahis_veri_uygun")) and not elig.get("karar_engeli")
               and _bet_still_valid(d, pred, record_time))
        # decide() veri uygun değilse olasılığı taşımaz (NaN); burada yalnızca geçerli olasılık yazılır
        p = finite_or_none(d.p) if (elig.get("tahmin_uygun") and valid_probability(d.p)) else None
        ids.append(ledger.record_prediction({
            # Bahis adayı kaydı yalnızca VALUE_CANDIDATE (zamanı doğrulanmış gerçek oranla); diğerleri karar kaydıdır.
            "kayit_turu": RECORD_BET if bet else RECORD_DECISION,
            "event_id": d.event_id, "league": pred.league, "home": pred.home, "away": pred.away,
            "kickoff": pred.kickoff_utc.isoformat() if pred.kickoff_utc else str(pred.date.date()),
            "market_key": d.market_key, "decision_time": d.decision_time,
            "model_version": model_version, "feature_version": FEATURE_VERSION,
            "data_cutoff": data_cutoff, "p": p, "p_low": finite_or_none(d.p_safe) if p is not None else None,
            "odds": finite_or_none(d.odds), "decision_status": d.status,
            "reasons": d.reasons + (["Kayıt anında aday kararı geçerliliğini yitirdi (gün değişti veya maç başladı); "
                                     "sanal stake yok."] if d.status == "VALUE_CANDIDATE" and not bet else []),
            "ev": finite_or_none(d.ev) if p is not None else None,
            "ev_safe": finite_or_none(d.ev_safe) if p is not None else None,
            "stake_units": stake_units if bet else 0.0,
            "strategy_version": STRATEGY_VERSION, "policy_version": d.policy_version,
            "veri_uygunlugu": elig or None,
        }))
    return ids


def settlement_matches(store) -> pd.DataFrame:
    """Sonuçlandırma için lig maçları + kupa maçları (kupada ``league`` = turnuva kodu; ad ve tarih fikstürdekiyle aynı
    kaynak adlarıdır, KUPA-GOL-02)."""
    cols = ["league", "date", "home", "away", "fthg", "ftag", "hthg", "htag"]
    parts = []
    m = getattr(store, "matches", None)
    if m is not None and not m.empty:
        parts.append(m[cols])
    c = getattr(store, "cup_matches", None)
    if c is not None and not c.empty:
        parts.append(c.rename(columns={"comp": "league"})[cols])
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)


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
        hthg, htag = (r.hthg, r.htag) if ht_ok else (None, None)
        if pd.isna(r.hthg) and pd.isna(r.htag) and r.fthg == 0 and r.ftag == 0:
            hthg, htag = 0, 0  # maç sonu 0-0 ise ilk yarı da 0-0 (kupa kaynakları 0-0'da devre skorunu yazmaz; KUPA-GOL-04)
        ps = PeriodScore(fthg=r.fthg, ftag=r.ftag, hthg=hthg, htag=htag, status=MatchStatus.FINISHED)
        st = settle(rec["market_key"], ps)
        # Önceki sonuç UNKNOWN idiyse (gerekli skor o gün yoktu) belli olan sonuç gerekçesiyle eklenir; eski olay silinmez
        note = ("sonuç verisi tamamlandı (önceki sonuç: UNKNOWN)"
                if rec["outcome"] is not None and rec["outcome"]["settlement"] == "UNKNOWN" and st.value != "UNKNOWN"
                else "")
        ledger.record_outcome(rec["id"], st.value, label(rec["market_key"], ps).value, source, note)
        done += 1
    return {"sonuclanan": done, "bekleyen": pending}


def ledger_rows(ledger: Ledger | None) -> list[dict]:
    """Sanal takip tablosu ve CSV dışa aktarımı için satırlar. Olasılık/oran yalnızca sonlu sayıysa yazılır (NaN,
    sonsuz veya sahte sıfır taşınmaz); veri uygunluğu bilgisi olmayan eski kayıtlar olduğu gibi okunur."""
    from ..timeutil import ISTANBUL
    from .decision import STATUS_TR

    if ledger is None:
        return []
    rows = []
    for r in ledger.predictions():
        o = r.get("outcome") or {}
        t = dt.datetime.fromisoformat(r["decision_time"])
        status = r["decision_status"]
        if status == "TAHMIN":
            karar = "Tahmin kaydı (ölçüm; bahis değil)"
        elif status == "TAHMIN_YOK":
            karar = "Tahmin yok: " + ", ".join((r.get("reasons") or ["?"])[:1])
        else:
            karar = STATUS_TR.get(status, status)
        vu = r.get("veri_uygunlugu") or {}
        if vu.get("politika"):
            veri = (f"{vu.get('guncellik')} · tahmin {'uygun' if vu.get('tahmin_uygun') else 'uygun değil'} · "
                    f"bahis {'uygun' if vu.get('bahis_veri_uygun') else 'uygun değil'}"
                    + (f" · {', '.join(vu.get('nedenler') or [])}" if vu.get("nedenler") else ""))
        elif vu.get("karar_engeli"):
            veri = "kontrol edilmedi: " + ", ".join(vu["karar_engeli"])
        else:
            veri = "- (kayıt veri uygunluk kontrolünden önce)"
        mk = r.get("market_key")
        p = finite_or_none(r.get("p"))
        rows.append({
            "Kayıt türü": r.get("kayit_turu", "KARAR_KAYDI"),
            "Karar zamanı (İstanbul)": t.astimezone(ISTANBUL).strftime("%d.%m.%Y %H:%M"),
            "Kayıt anı (UTC)": r.get("created_at", ""),
            "Maç": f"{r.get('home', '')} - {r.get('away', '')}", "Lig": r.get("league", ""),
            "Pazar": MARKETS[mk].name_tr if mk in MARKETS else (mk or "-"), "Olasılık": p,
            "Oran": finite_or_none(r.get("odds")), "Karar": karar, "Veri uygunluğu": veri,
            "Sanal birim": finite_or_none(r.get("stake_units")),
            "Sonuç": o.get("settlement", "PENDING" if p is not None else "-"), "Model": r.get("model_version", ""),
        })
    return rows


def ledger_csv(rows: list[dict]) -> str:
    """CSV metni (formül enjeksiyonuna karşı korumalı; NaN/sonsuz değer boş hücre olur)."""
    import csv
    import io

    from .value import safe_csv_cell

    if not rows:
        return ""
    cols = list(rows[0])
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow([safe_csv_cell(c) for c in cols])
    for row in rows:
        out = []
        for c in cols:
            v = row.get(c)
            if isinstance(v, float) and not valid_number(v):
                v = None
            out.append(safe_csv_cell(v))
        wr.writerow(out)
    return buf.getvalue()


def valid_number(v) -> bool:
    return finite_or_none(v) is not None

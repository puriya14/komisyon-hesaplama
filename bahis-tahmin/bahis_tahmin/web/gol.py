"""Gol pazarları (web): tarama, maç analizi, veri kapsamı, model doğrulama ve sanal takip.

Masaüstündeki ``ui.pages.goals`` ile aynı servis işlevleri ve aynı gösterim kuralları (``goals.display``)
kullanılır: veri uygunluğu doğrulanmayan pazarda olasılık ve ondan türetilen değer gösterilmez, karar ve kayıt yapılmaz.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from ..data.leagues import LEAGUES, league_name
from ..data.source_registry import SOURCES
from ..eligibility import display_label
from ..fmt import fmt_num, fmt_pct
from ..goals.coverage import coverage_matrix, coverage_summary, quarantine
from ..goals.decision import STATUS_TR, DecisionPolicy
from ..goals.display import (
    KEY_OF,
    NAMES,
    STATUS_SHORT,
    data_label,
    data_text,
    iv,
    shown,
)
from ..goals.markets import MARKETS, PRIMARY_YES, RULE_VERSION
from ..goals.model import FEATURE_VERSION, MODEL_VERSION
from ..goals.service import (
    SELECTIONS,
    decisions_for,
    gated_goal_match,
    is_cup_prediction,
    model_validated,
    ledger_csv,
    ledger_rows,
    record_decisions,
    settle_pending,
    settlement_matches,
)
from ..goals.value import OddsQuote
from ..plots import SvgCanvas, plot_goal_calibration
from . import get_state, svg_img
from .views import _started

bp = Blueprint("gol", __name__, url_prefix="/gol")

TABS = [("tarama", "Tarama"), ("mac", "Maç analizi"), ("kapsam", "Veri kapsamı"), ("dogrulama", "Model doğrulama"),
        ("takip", "Sanal takip")]


def _status_text(core) -> str:
    from ..kupa.gorunum import goal_status_line

    eng = core.goal_engine
    cup = goal_status_line(core.cup_engine) if core.settings.kupalar else ""
    if eng is None:
        err = core.goal_load_error
        return ("Lig maçları: gol pazarları modeli eğitilmedi." + (f" ({err})" if err and "yok" not in err else "")
                + " Veriler indirildikten sonra 'Gol modelini eğit' düğmesini kullanın." + (f" {cup}" if cup else ""))
    st = " · ".join(f"{s}: {'doğrulandı (sanal takip)' if eng.validated.get(KEY_OF[s]) else 'DOĞRULANMADI'}"
                    for s in ("A", "B", "C"))
    return (f"Lig maçları — {st}." + (f" {cup}" if cup else "") + " Bu pazarlar için geçmiş gerçek oran verisi "
            "olmadığından kârlılık doğrulanamaz; 'avantaj adayı' yalnızca girdiğiniz güncel gerçek oranla ve tüm "
            "kontroller geçilirse oluşur.")


def _cup_engine(core):
    from ..kupa.gorunum import goal_part

    return core.cup_engine if goal_part(core.cup_engine) is not None else None


# ================================================================== seçim (yaklaşan maç veya elle)


def _selection(core, values):
    """İstekteki seçimden güncel uygunluk sonucu: ``aday`` (yaklaşan maç) ya da ``lig``/``ev``/``dep`` (elle). Her
    istekte güncel motor ve güncel bağlamla yeniden üretilir (eski tahmin gösterilmez/kaydedilmez)."""
    eng = core.goal_engine
    aday = values.get("aday") or ""
    if aday:
        v = next((x for x in list(core.goal_verdicts) if x.candidate_id == aday), None)
        return v, {"aday": aday}
    comp = values.get("turnuva") or ""
    if comp:  # KUPA-GOL-02: elle seçilen ligler arası / kupa maçı (takım anahtarları kupa modelinin listesinden)
        from ..kupa.gorunum import goal_match, teams_for_analysis
        from ..kupa.turnuvalar import COMPETITIONS

        cup = _cup_engine(core)
        hk, ak = values.get("ev_k") or "", values.get("dep_k") or ""
        names = {k: n for _g, ts in teams_for_analysis(cup) for k, n in ts}
        neutral = values.get("tarafsiz") == "1"
        sel = {"turnuva": comp, "ev_k": hk, "dep_k": ak, **({"tarafsiz": "1"} if neutral else {})}
        if cup is None or comp not in COMPETITIONS or hk not in names or ak not in names or hk == ak:
            return None, sel
        main = core.engine if (core.engine is not None and core.engine.trained) else None
        v = goal_match(cup, core.store, core.eligibility_context(main), core.settings, comp=comp, home_key=hk,
                       away_key=ak, names=names, date=core.today(), neutral=neutral, as_of=core.now())
        return v, sel
    lg, h, a = values.get("lig") or "", values.get("ev") or "", values.get("dep") or ""
    if eng is None or not lg or not h or not a or h == a or lg not in (eng.states or {}):
        return None, {}
    ctx = core.eligibility_context(eng)
    v = gated_goal_match(eng, ctx, lg, h, a, pd.Timestamp(core.today()), core.now())
    return v, {"lig": lg, "ev": h, "dep": a}


def _eligibility_info(v) -> dict | None:
    e = v.first()
    if e is None:
        return None
    st = e.state_scope or {}
    ev = (e.data_scope or {}).get("kapsam_kanitlari") or []

    def araliklar(x) -> str:
        ar = x.get("gecmis_aralik_kaniti")
        if ar is None:
            return ""
        return "; geçmiş aralık kanıtı " + (", ".join(f"{a}–{b}" for a, b in ar) or "yok")

    kan = ", ".join((f"{x['lig']} · " if x.get("lig") else "")
                    + f"{x['kaynak']} {x['sezon']} ({'tam sezon takvimi' if x.get('tam') else 'tam sezon doğrulanmadı'}"
                    f"{araliklar(x)}, alınma {x['alinma'][:16]})" for x in ev) or "yok"
    return {"policy": e.policy_version, "evaluated": e.evaluated_at[:16], "info_cutoff": e.info_cutoff,
            "data_cutoff": e.data_cutoff or "-",
            "markets": [(k, x.status_label, ", ".join(x.reasons) or "neden yok") for k, x in v.by_market.items()],
            "state": (st.get("lig_durum_son_mac", "-"), st.get("takim_durum_son_mac", "-"),
                      st.get("model_egitim_kesimi", "-")),
            "evidence": kan, "mapping": e.team_mapping, "fields": e.required_fields, "cid": e.candidate_id,
            "canonical": bool(e.canonical_id)}


def _analysis(core, v, led) -> dict:
    """Maç analizi paneli (masaüstündeki ``GoalsPage._show`` ile aynı kurallar)."""
    p = v.prediction
    cup = is_cup_prediction(p)
    eng = _cup_engine(core) if cup else core.goal_engine
    now = core.now()
    out = {"v": v, "title": f"{v.home} - {v.away}", "league": league_name(v.league), "cards": [], "rel": None,
           "conds": [], "decisions": [], "secondary": [], "can_record": False, "model": None,
           "elig": _eligibility_info(v), "event_id": getattr(p, "event_id", None), "kupa": cup}
    usable_any = p is not None and eng is not None and v.any_usable(now)
    validated = model_validated(p, eng) if p is not None else {}
    for s in ("A", "B", "C"):
        key = KEY_OF[s]
        e = v.get(key)
        if not usable_any or not v.usable(key, now):
            label, text = display_label(e, v.display_codes(key, now))
            out["cards"].append((f"{s}: {NAMES[s]}", "—", f"Tahmin yok · {label} · {text}"))
            continue
        prob = p.probs.get(s, np.nan)
        model_ok = bool(validated.get(key))
        sub = (f"Belirsizlik (%80): {iv(p, key)} · adil oran {fmt_num(1 / prob) if prob == prob and prob > 0 else '-'}"
               f" · {'kupa' if cup else 'lig'} taban oranı {fmt_pct(p.base_rates.get(s))} · model: "
               + ("sanal takip için doğrulandı" if model_ok else "DOĞRULANMADI")
               + f" · veri: {e.status_label}" + ("" if e.bet_ok else f" (bahis adayı değil: {e.lead_code})"))
        out["cards"].append((f"{s}: {NAMES[s]}", fmt_pct(prob), sub))
    if not usable_any:
        label, text = display_label(*shown(v, now))
        out["rel"] = ("blocked", f"Veri durumu: {label} — {text}",
                      "" if v.canonical_id else f"Takım adı eşleşmedi; aday kimlik {v.candidate_id} (kanonik maç "
                                                "kimliği değildir). Sahte takım veya olasılık atanmadı.")
        out["decisions"] = [{"secim": MARKETS[k].name_tr, "durum": STATUS_TR["DATA_NOT_ELIGIBLE"],
                             "gerekce": display_label(v.get(k), v.display_codes(k, now))[1]} for k in PRIMARY_YES]
        return out
    decs = decisions_for(p, eng, led, now, eligibility=v)
    for d in decs:
        lo, hi = p.interval(d.market_key) if np.isfinite(d.p) else (None, None)
        out["decisions"].append({
            "secim": MARKETS[d.market_key].name_tr, "p": d.p,
            "aralik": f"%{100 * lo:.0f}–%{100 * hi:.0f}" if lo is not None else "-",
            "adil": d.fair_odds, "oran": d.odds, "basabas": d.breakeven, "ev": d.ev, "ev_safe": d.ev_safe,
            "min_oran": d.min_odds, "durum": STATUS_TR.get(d.status, d.status), "gerekce": " ".join(d.reasons)})
    out["can_record"] = bool(decs)
    if not v.all_usable(now):  # pazarlardan biri engelli: ortak olasılık ilişkileri gösterilmez
        out["rel"] = ("partial", f"Veri durumu: {data_label(v, now)} — {data_text(v, now)}", "")
        return out
    a, bc = p.probs.get("A", np.nan), p.probs.get("BC", np.nan)
    cond = (a / bc) if bc and bc == bc and bc > 0 else np.nan
    pct = fmt_pct
    out["rel"] = ("ok", f"Pazarlar arası bağlantı: A gerçekleşirse B ve C de gerçekleşir (A ⊆ B ∩ C). P(B ve C "
                        f"birlikte) = {pct(bc)}; bunun içinde A'nın payı P(A | B∩C) = {pct(cond)}. B ve C birlikte "
                        f"gerçekleşip A gerçekleşmeme olasılığı = {pct(bc - a if bc == bc else np.nan)}. Aynı maçtaki bu "
                        "üç seçim bağımsız değildir; kupon/çeşitlendirme gibi değerlendirilmemelidir.",
                  ("Veri notları: " + " · ".join(p.data_notes)) if p.data_notes else "")
    conds = [("Ev sahibi ilk yarıda gol atar", p.probs.get("h1_home")),
             ("Deplasman ilk yarıda gol atar", p.probs.get("h1_away")),
             ("Ev sahibi ikinci yarıda gol atar", p.probs.get("h2_home")),
             ("Deplasman ikinci yarıda gol atar", p.probs.get("h2_away"))]
    vals = [c[1] if c[1] is not None else np.nan for c in conds]
    weakest = int(np.nanargmin(vals)) if np.isfinite(vals).any() else -1
    out["conds"] = [(k, x, "en zayıf koşul" if i == weakest else "") for i, (k, x) in enumerate(conds)]
    if cup:
        from ..kupa.gorunum import goal_model_card

        out["model"] = goal_model_card(p, eng)
        out["secondary"] = [(n, p.probs.get(k, np.nan)) for n, k in
                            (("Maç sonu KG Var", "FT_BTTS"), ("İlk yarı KG Var", "FH_BTTS"),
                             ("İkinci yarı 1,5 Üst", "SH_O15"), ("Maç sonu 2,5 Üst", "FT_O25"),
                             ("Maç sonu 4,5 Üst", "FT_O45"))]
        return out
    man = eng.manifest
    meta = p.intervals.get("meta", {}) if p.intervals else {}
    out["model"] = {
        "version": f"{MODEL_VERSION} / {eng.variant} · özellik sürümü {FEATURE_VERSION} · sonuçlandırma kuralı "
                   f"{RULE_VERSION}",
        "training": f"{eng.trained_at} · veri kesimi {eng.data_cutoff} · {man.get('n_matches', 0):,} maç "
                    f"({man.get('first_date')} – {man.get('last_date')}) · kaynak: {', '.join(man.get('sources', []))}",
        "validation": ", ".join(f"{y}/{(y + 1) % 100:02d}" for y in eng.validation_years) or "-",
        "uncertainty": f"{meta.get('method', '-')}; {meta.get('draws', '-')} çekiliş, tohum {meta.get('seed', '-')}",
    }
    out["secondary"] = [(n, p.probs.get(k, np.nan)) for n, k in
                        (("Maç sonu KG Var", "FT_BTTS"), ("İlk yarı KG Var", "FH_BTTS"), ("İkinci yarı 1,5 Üst", "SH_O15"),
                         ("Maç sonu 2,5 Üst", "FT_O25"), ("Maç sonu 4,5 Üst", "FT_O45"))]
    return out


# ================================================================== sayfa


@bp.route("/")
def gol():
    core = get_state().core
    sekme = request.args.get("sekme", "tarama")
    if sekme not in dict(TABS):
        sekme = "tarama"
    eng = core.goal_engine
    ctx = {"tabs": TABS, "sekme": sekme, "status": _status_text(core), "has_data": core.store.has_data,
           "has_model": eng is not None, "names": NAMES}
    now = core.now()
    verdicts = list(core.goal_verdicts)
    if sekme == "tarama":
        mode = request.args.get("gorunum", "likely")
        msel = request.args.get("pazar", "A") if request.args.get("pazar") in NAMES else "A"
        rows, n_blocked, n_val = [], 0, 0
        with core.ledger(create=False) as led:
            for v in verdicts:
                p = v.prediction
                decs = (decisions_for(p, _cup_engine(core) if is_cup_prediction(p) else eng, led, now, eligibility=v)
                        if (p is not None and (eng is not None or is_cup_prediction(p))) else [])
                n_val += sum(1 for d in decs if d.status == "VALUE_CANDIDATE")
                by = {d.market_key: d for d in decs}
                if mode == "value" and not any(d.status == "VALUE_CANDIDATE" for d in decs):
                    continue
                probs, ivs = {}, {}
                for s, key in KEY_OF.items():
                    ok = p is not None and v.usable(key, now)
                    probs[s] = p.probs.get(s, np.nan) if ok else np.nan
                    ivs[s] = iv(p, key) if ok else "-"
                usable = any(np.isfinite(x) for x in probs.values())
                n_blocked += not usable
                sel = probs.get(msel, np.nan)
                kinds = [STATUS_SHORT.get(by[k].status, by[k].status) for k in PRIMARY_YES] if decs else []
                rows.append({
                    "_sort": -sel if np.isfinite(sel) else np.inf, "aday": v.candidate_id,
                    "when": p.kickoff_text if p is not None else f"{v.date:%d.%m.%Y}", "league": v.league,
                    "match": f"{v.home} - {v.away}" + ("" if v.canonical_id else " (takım eşleşmedi)"),
                    "A": probs["A"], "A_iv": ivs["A"], "B": probs["B"], "B_iv": ivs["B"], "C": probs["C"],
                    "C_iv": ivs["C"], "data": data_label(v, now), "neden": data_text(v, now),
                    # üç pazarın kararı aynıysa bir kez yazılır (satırlar gereksiz uzamaz)
                    "decision": ((kinds[0] if len(set(kinds)) == 1 else " / ".join(kinds))
                                 if kinds else "TAHMİN YOK")})
        rows.sort(key=lambda r: r["_sort"])  # uygun olmayan maçlar en sona (sıralama kararlı)
        note = (("Uygun aday yok: hiçbir maçta önceden tanımlı kontrollerin tamamı geçilmedi. Bu geçerli bir sonuçtur. "
                 if mode == "value" and not rows else "")
                + f"{len(verdicts)} maç · tahmini gösterilemeyen {n_blocked} maçta olasılık yok (nedeni veri sütununda)"
                f" · {n_val} avantaj adayı · karar politikası: {DecisionPolicy().version}. 'En olası' görünümü avantaj "
                "göstermez; yüksek olasılık düşük oranla birlikte gelir. Bu pazarlar için veri setinde gerçek oran "
                "yoktur: oranları Maç analizi sekmesinde siz girersiniz.")
        if eng is None and not verdicts:
            note = "Gol modeli henüz eğitilmedi."
        elif not verdicts:
            note = ("Yaklaşan maç bulunamadı (fikstür verisi yok) veya değerlendirme sürüyor. Maç analizi sekmesinden "
                    "elle maç seçebilirsiniz.")
        ctx.update(rows=rows, mode=mode, msel=msel, note=note)
    elif sekme == "mac":
        v, sel = _selection(core, request.args)
        choices = [(x.candidate_id, f"{x.prediction.kickoff_text if x.prediction is not None else f'{x.date:%d.%m.%Y}'}"
                    f" · {league_name(x.league)} · {x.home} - {x.away}"
                    + ("" if x.any_usable(now) else f" · {data_label(x, now)}")) for x in verdicts]
        leagues = [c for c in LEAGUES if eng is not None and c in (eng.states or {})]
        lig = request.args.get("lig") or (leagues[0] if leagues else "")
        teams = sorted(eng.states[lig].elo.cur_teams or eng.states[lig].elo.prev_teams) \
            if (eng is not None and lig in (eng.states or {})) else []
        with core.ledger(create=False) as led:
            panel = _analysis(core, v, led) if v is not None else None
        from ..kupa.gorunum import teams_for_analysis
        from ..kupa.turnuvalar import COMPETITIONS

        ctx.update(choices=choices, sel=sel, leagues=leagues, lig=lig, teams=teams, panel=panel,
                   selections=[(k, MARKETS[k].name_tr) for k in SELECTIONS],
                   ev=request.args.get("ev", ""), dep=request.args.get("dep", ""),
                   cup_groups=teams_for_analysis(_cup_engine(core)), comps=list(COMPETITIONS),
                   comp=request.args.get("turnuva") or "UCL", ev_k=request.args.get("ev_k", ""),
                   dep_k=request.args.get("dep_k", ""), tarafsiz=request.args.get("tarafsiz") == "1")
    elif sekme == "kapsam":
        st = core.store
        cov = coverage_matrix(st.matches, core.settings.source_consent, {}) if st.has_data else pd.DataFrame()
        lg = request.args.get("lig") or ""
        from ..kupa.gorunum import cup_ht_coverage

        ctx.update(
            cup_cov=cup_ht_coverage(getattr(st, "cup_matches", None)), cup_cov_fmts={"İY skoru oranı": fmt_pct},
            summary=coverage_summary(cov) if not cov.empty else pd.DataFrame(),
            cov=(cov[cov["league"] == lg] if (lg and not cov.empty) else cov),
            cov_leagues=[c for c in LEAGUES if not cov.empty and c in set(cov["league"])], lig=lg,
            n_quarantine=len(quarantine(st.matches)) if st.has_data else 0,
            sources=[{"Kaynak": s.name, "Lisans özeti": s.license_summary, "Ticari kullanım": s.commercial_use,
                      "Model eğitimi": s.model_training, "Maliyet": s.cost,
                      "Durum": _source_status(core, k, s)} for k, s in SOURCES.items()])
    elif sekme == "dogrulama":
        rows, chart = [], None
        pazar = request.args.get("pazar") if request.args.get("pazar") in NAMES else "A"
        if eng is not None and eng.validation:
            for key in PRIMARY_YES:
                r = eng.validation.get(key, {})
                m = r.get("modeller", {}).get(eng.variant, {})
                b = r.get("modeller", {}).get("M0_taban", {})
                if not m:
                    continue
                rows.append({"Pazar": MARKETS[key].name_tr, "Maç": r["n"], "Pozitif": r["pozitif"],
                             "Taban oran": r["taban_oran"], "LL model": m["log_loss"],
                             "LL taban": m["log_loss"] - m["ll_fark_ref"], "Δ LL": m["ll_fark_ref"],
                             "Δ alt": m["ll_fark_alt"], "Δ üst": m["ll_fark_ust"], "Brier becerisi": m["brier_skill"],
                             "AP model": m["ap"], "AP taban": b.get("ap", np.nan), "Kal. eğim": m["kal_egim"],
                             "ECE": m["ece"], "Statü": eng.status_text(key)})
            bins = eng.validation.get(KEY_OF[pazar], {}).get("modeller", {}).get(eng.variant, {}) \
                .get("kalibrasyon", [])
            c = SvgCanvas(7, 4)
            plot_goal_calibration(c, bins)
            chart = svg_img(c)
        from ..kupa.gorunum import goal_calibration_bins, goal_validation_rows, level_line
        from ..kupa.gol import GOAL_RULE

        cup = _cup_engine(core)
        cup_chart = None
        if cup is not None:
            c2 = SvgCanvas(7, 4)
            plot_goal_calibration(c2, goal_calibration_bins(cup, pazar))
            cup_chart = svg_img(c2)
        ctx.update(cup_rows=goal_validation_rows(cup), cup_chart=cup_chart, cup_rule=GOAL_RULE,
                   cup_level=level_line(cup), has_cup=cup is not None)
        ctx.update(val_rows=rows, chart=chart, pazar=pazar,
                   val_years=", ".join(f"{y}/{(y + 1) % 100:02d}" for y in eng.validation_years) if eng else "",
                   val_rule=(eng.validation.get("rule", "") or "") if (eng is not None and eng.validation) else "",
                   validated=bool(eng is not None and eng.validation))
    else:  # takip
        with core.ledger(create=False) as led:
            rows = ledger_rows(led)
            summ = led.summary() if (led is not None and rows) else None
        ctx.update(ledger=pd.DataFrame(rows), summ=summ)
    return render_template("gol.html", **ctx)


def _source_status(core, k, s) -> str:
    if k == "the-odds-api":
        return "Entegre edilmedi"
    if k == "openfootball-sonuc":
        return "S4 pilotu ve eksik dönemin tamamlanması (köken doğrulaması zorunlu)"
    if k == "football-datasets":
        return "Yalnızca GitHub arşivi (envanter; analiz ve eğitim kapalı)"
    if k == "statsbomb-acik":
        return "Yalnızca GitHub arşivi (araştırma amaçlı tarihsel inceleme; eğitim ve tahmin kapalı)"
    if not s.requires_consent:
        return "Onay gerekmez"
    if k not in core.settings.source_consent:
        return "ONAY YOK"
    return "Kullanıcı onayladı + kişisel kullanım beyanı" if k in core.settings.declarations() else \
        "Kullanıcı onayladı (beyan yok)"


def _back(sel: dict) -> str:
    return url_for("gol.gol", sekme="mac", **sel)


# ================================================================== işlemler


@bp.route("/egit", methods=["POST"])
def egit():
    st = get_state()
    block = st.training_block_text()
    if block:
        flash(block, "warn")
    else:
        _started(st.start_goal_train(), "Gol pazarları modeli eğitimi")
    return redirect(url_for("gol.gol"))


@bp.route("/oran", methods=["POST"])
def oran():
    core = get_state().core
    v, sel = _selection(core, request.form)
    p = v.prediction if v is not None else None
    if p is None:
        flash("Maç seçilmedi veya tahmin üretilemedi; oran kaydedilmedi.", "warn")
        return redirect(_back(sel))
    now = core.now()
    book = (request.form.get("sirket") or "").strip()[:60] or "belirtilmedi"
    quotes = []
    for key in SELECTIONS:
        raw = (request.form.get(f"o_{key}") or "").replace(",", ".")
        try:
            val = float(raw) if raw else 0.0
        except ValueError:
            val = 0.0
        if 1.0 < val <= 1000.0:
            m = MARKETS[key]
            quotes.append(OddsQuote(p.event_id, key, m.period, m.line, m.selection, "manuel", book, val, now, now))
    if quotes:
        with core.ledger() as led:
            led.add_odds(quotes)
        flash(f"{len(quotes)} oran kaydedildi ({book}).", "info")
    else:
        flash("Kaydedilecek oran yok (1,00'den büyük oran girin).", "warn")
    return redirect(_back(sel))


@bp.route("/kaydet", methods=["POST"])
def kaydet():
    core = get_state().core
    eng = core.goal_engine
    v, sel = _selection(core, request.form)
    now = core.now()
    cup = v is not None and is_cup_prediction(v.prediction)
    if cup:
        eng = _cup_engine(core)
    if v is None or v.prediction is None or eng is None or not v.any_usable(now):
        flash("Kayıt yapılmadı: maçın veri uygunluğu doğrulanmadı veya model yok.", "warn")
        return redirect(_back(sel))
    # Kararlar kayıt anında aynı uygunluk sonucuyla YENİDEN üretilir (önceden hesaplanmış karar yazılmaz)
    with core.ledger() as led:
        decs = decisions_for(v.prediction, eng, led, now, eligibility=v)
        record_decisions(led, v.prediction, decs, eng, record_time=now)
    flash("Kararlar sanal takibe kaydedildi (değiştirilemez).", "info")
    return redirect(url_for("gol.gol", sekme="takip"))


@bp.route("/sonuclandir", methods=["POST"])
def sonuclandir():
    core = get_state().core
    with core.ledger(create=False) as led:
        if led is None:
            flash("Henüz sanal kayıt yok.", "warn")
        else:
            res = settle_pending(led, settlement_matches(core.store))
            flash(f"Sonuçlar güncellendi: {res['sonuclanan']} sonuçlandı, {res['bekleyen']} bekliyor.", "info")
    return redirect(url_for("gol.gol", sekme="takip"))


@bp.route("/zincir", methods=["POST"])
def zincir():
    core = get_state().core
    with core.ledger(create=False) as led:
        if led is None:
            flash("Henüz sanal kayıt yok.", "warn")
        else:
            ok, msg = led.verify_chain()
            flash(("✔ " if ok else "✘ ") + msg, "info" if ok else "warn")
    return redirect(url_for("gol.gol", sekme="takip"))


@bp.route("/takip.csv")
def takip_csv():
    core = get_state().core
    with core.ledger(create=False) as led:
        rows = ledger_rows(led)
    body = ledger_csv(rows) if rows else ""
    return Response("﻿" + body, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=sanal_takip.csv"})

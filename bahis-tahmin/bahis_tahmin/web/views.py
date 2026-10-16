"""Web arayüzü sayfaları (masaüstündeki sayfaların karşılıkları; aynı veri, aynı kurallar)."""

from __future__ import annotations

import copy
import datetime as dt
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from markupsafe import Markup, escape

from .. import __version__
from ..analysis import head_to_head, standings, team_matches
from ..config import DEFAULT_LEAGUES, Settings
from ..core import apply_consent, consent_keys, needs_consent
from ..data.github_kaynak import PROFILE_DEFAULT, PROFILE_GITHUB
from ..data.leagues import LEAGUES, league_name
from ..kupa.turnuvalar import COMPETITIONS
from ..data.source_registry import DECLARABLE, IMPLEMENTED, SOURCES
from ..eligibility import display_label
from ..fmt import fmt_num, fmt_pct
from ..models.engine import (
    MARKET_GROUPS,
    ODDS_SETS,
    ODDS_TYPE_LABELS,
    _odds_dict,
    verify_selection,
)
from ..models.markets import MARKETS, top_scores
from ..plots import (
    SvgCanvas,
    plot_calibration,
    plot_confidence,
    plot_equity,
    plot_ratings,
    plot_season_quality,
)
from . import check_password, get_state, svg_img
from .state import BUSY_TEXT

bp = Blueprint("views", __name__)

DATE_FILTERS = [("Tümü", None), ("Bugün", 0), ("Bugün + yarın", 1), ("3 gün", 2), ("7 gün", 6)]
NOT_UPDATED_TEXT = ("Onaylar kaydedilmedi veya geçmiş veri kaynağı onaylanmadı; veri indirilmedi. Tahmin için kaynak "
                    "onayı ve kişisel kullanım beyanı gerekir.")


def fixture_key(league, date, home, away) -> str:
    return f"{league}|{pd.Timestamp(date):%Y-%m-%d}|{home}|{away}"


def _safe_next(target: str | None, default: str) -> str:
    """Yalnızca aynı sitedeki yol (açık yönlendirme yok)."""
    if not target:
        return default
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return default
    return target


def _float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(str(request.values.get(name, default)).replace(",", "."))
    except (TypeError, ValueError):
        return default
    return float(min(max(v, lo), hi)) if v == v else default


def _started(ok: bool, what: str) -> None:
    flash(f"{what} başladı; ilerleme üst çubukta görünür." if ok else BUSY_TEXT, "info" if ok else "warn")


def _table(df: pd.DataFrame | None) -> dict:
    """Genel tablo (sütun adları zaten Türkçe olan DataFrame'ler için)."""
    if df is None or df.empty:
        return {"cols": [], "rows": []}
    df = df.copy()
    for c in df.columns:  # tarih sütunları gün.ay.yıl olarak (masaüstüyle aynı)
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%d.%m.%Y")
    return {"cols": [str(c) for c in df.columns], "rows": df.astype(object).where(df.notna(), None).values.tolist()}


# ================================================================== giriş (parolalı paylaşım)


@bp.route("/giris", methods=["GET", "POST"])
def giris():
    if not current_app.config.get("BT_PASSWORD"):
        return redirect(url_for("views.genel"))
    hata = None
    if request.method == "POST":
        if check_password(current_app, request.form.get("parola", "")):
            session.clear()
            session["giris"] = True
            return redirect(_safe_next(request.form.get("sonra"), url_for("views.genel")))
        hata = "Parola yanlış."
    return render_template("giris.html", hata=hata, sonra=request.values.get("sonra", ""))


@bp.route("/cikis", methods=["POST"])
def cikis():
    session.clear()
    return redirect(url_for("views.giris" if current_app.config.get("BT_PASSWORD") else "views.genel"))


# ================================================================== iş durumu


@bp.route("/api/is")
def is_durumu():
    return jsonify(get_state().jobs.status())


# ================================================================== Genel Bakış


@bp.route("/")
def genel():
    st = get_state()
    core = st.core
    store, eng = core.store, core.engine
    cards = {}
    if store.has_data:
        upd = (store.meta.get("updated_at") or "-").replace("T", " ")
        last = store.matches["date"].max().strftime("%d.%m.%Y")
        cards["data"] = (f"{len(store.matches):,}".replace(",", "."),
                         f"{store.matches['league'].nunique()} lig · son maç {last} · güncelleme {upd}", "")
    else:
        cards["data"] = ("-", "Henüz veri yok", "")
    charts = []
    if eng is not None and eng.report is not None:
        m = eng.report.metrics
        cards["acc"] = (fmt_pct(m.get("acc_final", m.get("acc_model"))),
                        f"Model tek başına {fmt_pct(m.get('acc_model'))} · bahis piyasası {fmt_pct(m.get('acc_market'))}"
                        f" · {m.get('n', 0):,} maç".replace(",", "."), "")
        conf = eng.report.confidence or {}
        r90 = next((r for r in conf.get("best", []) if abs(r["esik"] - 0.9) < 1e-9), None)
        if r90 and r90["n"]:
            cards["likely"] = (fmt_pct(r90["isabet"]),
                               f"{r90['n']:,} seçim · maçların {fmt_pct(r90['kapsam'])}'i".replace(",", "."),
                               "good" if r90["isabet"] >= 0.9 else "")
        else:
            cards["likely"] = ("-", "Model eğitilince hesaplanır", "")
        c1 = SvgCanvas(5.5, 3.2)
        plot_confidence(c1, conf.get("best", []), "En olası seçim: olasılık eşiğine göre gerçekleşme ve kapsam")
        c2 = SvgCanvas(5.5, 3.2)
        plot_season_quality(c2, eng.report.per_season)
        charts = [svg_img(c1), svg_img(c2)]
    else:
        cards["acc"] = ("-", "Model henüz eğitilmedi", "")
        cards["likely"] = ("-", "", "")
    preds, unpred = list(core.predictions), list(core.match_unpredicted)
    if preds or unpred:
        now = core.now()
        shown = [p for p in preds if p.forecast_ok_at(now)]
        n_warn = sum(1 for p in shown if p.data_block(now))
        n_val = sum(1 for p in shown if p.best_value(core.settings, now=now))
        n_lg = len({p.league for p in preds} | {v.league for v in unpred})
        cards["fix"] = (str(len(preds) + len(unpred)),
                        f"tahmin {len(shown)}" + (f" (uyarılı {n_warn})" if n_warn else "")
                        + f" · tahmin yok {len(preds) + len(unpred) - len(shown)} · {n_val} değerli bahis fırsatı · "
                        f"{n_lg} lig", "")
    else:
        cards["fix"] = ("0", "Fikstür verisi yok (güncellemeyi deneyin)", "")
    return render_template("genel.html", cards=cards, charts=charts, has_data=store.has_data,
                           needs_training=core.loaded and store.has_data and (eng is None or core.needs_training()))


# ================================================================== Tahminler


@bp.route("/tahminler")
def tahminler():
    core = get_state().core
    df = core.prediction_frame()
    s = core.settings
    lig = request.args.get("lig") or ""
    gun = request.args.get("gun", "0")
    gun_i = int(gun) if gun.isdigit() and int(gun) < len(DATE_FILTERS) else 0
    deger = request.args.get("deger") == "1"
    ara = (request.args.get("ara") or "").strip()
    present = set(df["league"]) if not df.empty else set()
    leagues = [c for c in LEAGUES if c in present]
    cups = [c for c in COMPETITIONS if c in present]  # KUPA-01
    total = len(df)
    if not df.empty:
        mask = pd.Series(True, index=df.index)
        if lig == "@lig":
            mask &= df["league"].isin(list(LEAGUES))
        elif lig == "@kupa":
            mask &= df["league"].isin(list(COMPETITIONS))
        elif lig:
            mask &= df["league"] == lig
        days = DATE_FILTERS[gun_i][1]
        if days is not None:
            limit = pd.Timestamp(core.today() + dt.timedelta(days=days))
            mask &= pd.to_datetime(df["date"]) <= limit
        if deger:
            mask &= df["value"].astype(bool)
        if ara:
            low = ara.casefold()
            mask &= df["home"].str.casefold().str.contains(low, regex=False) | \
                df["away"].str.casefold().str.contains(low, regex=False)
        shown = df[mask]
    else:
        shown = df
    rows = []
    for r in shown.to_dict("records"):
        r["key"] = fixture_key(r["league"], r["date"], r["home"], r["away"]) if r["_i"] >= 0 else ""
        rows.append(r)
    n_blocked = int(df["p1"].isna().sum()) if not df.empty else 0
    n_warn = int(df["veri"].astype(str).str.startswith("Uyarılı").sum()) if not df.empty else 0
    footer = (f"{len(rows)} / {total} maç gösteriliyor · Değer hesabı: {ODDS_TYPE_LABELS.get(s.odds_type, s.odds_type)}"
              f", en az %{100 * s.min_ev:.0f} beklenen değer, oran {s.min_odds:.2f}–{s.max_odds:.2f} · tahmini "
              f"gösterilemeyen {n_blocked} maç" + (f", uyarılı (bahis adayı olmayan) {n_warn} maç" if n_warn else "")
              + " (nedenleri Veri durumu sütununda)")
    return render_template("tahminler.html", rows=rows, leagues=leagues, cups=cups, lig=lig, gun=gun_i, deger=deger,
                           ara=ara, date_filters=DATE_FILTERS, footer=footer)


# ================================================================== Maç ayrıntısı


def detail_context(core, p, odds: dict | None = None) -> dict:
    """Maç ayrıntısı (masaüstündeki ``MatchDetail`` ile aynı içerik ve aynı gösterim kuralları)."""
    s = core.settings
    now = core.now()
    e = p.eligibility
    out = {"p": p, "when": p.date.strftime("%d.%m.%Y") + (f" {p.time}" if p.time else ""),
           "league": league_name(p.league), "blocked": False, "notes": [], "markets": [], "stake": False}
    codes = p.display_codes(now)
    if codes:
        # Veri uygunluğu doğrulanmadı: olasılık, skor ve değer tablosu güvenilir tahmin gibi gösterilmez
        label, text = display_label(e, codes)
        out.update(blocked=True, label=label, text=text)
    else:
        xg = p.exp_goals
        out["probs"] = [float(x) for x in p.p_final]
        out["xg"] = f"{xg[0]:.2f} – {xg[1]:.2f}"
        out["o25"], out["btts"] = p.markets["O2.5"], p.markets["BTTS_Y"]
        if p.p_market is not None:
            out["model_vs_market"] = (" / ".join(fmt_pct(x) for x in p.p_model),
                                      " / ".join(fmt_pct(x) for x in p.p_market))
        notes = []
        if p.p_market is None:
            notes.append("Bu maç için piyasa oranı yok; olasılıklar yalnızca modelden gelir (model tek başına "
                         "piyasadan biraz daha az isabetlidir). Maç Analizi sayfasında oranları girerseniz sonuç "
                         "iyileşir.")
        block = p.data_block(now)
        if block:
            notes.append("Bahis/değer önerisi yok (stake 0): " + (e.short_text() if e is not None else ", ".join(block)))
        elif e is not None and e.freshness != "VERIFIED_CURRENT":  # standart mod: güncellik kanıtı yok
            notes.append("Veri durumu: " + e.short_text())
        out["notes"] = notes
        rows = p.value_rows(s, odds, now=now)
        for r in rows:
            r["need"] = r["fair"] * (1 + s.min_ev) if r.get("fair") == r.get("fair") else float("nan")
        out["markets"] = rows
        out["stake"] = bool(getattr(s, "stake_suggestions", False))
        mat = np.asarray(p.matrix)
        n = min(6, mat.shape[0])
        out["matrix"] = [[float(mat[i, j]) for j in range(n)] for i in range(n)]
        out["mat_max"] = float(mat[:n, :n].max()) if n else 1.0
        out["top_scores"] = ", ".join(f"{i}-{j} (%{100 * v:.1f})" for i, j, v in top_scores(p.matrix, 6))
    info = p.info or {}
    if info.get("kupa"):  # KUPA-01: kupa maçı (ligler arası ortak model)
        from ..kupa import gorunum

        eng = core.cup_engine
        generic = [n for n in out["notes"] if not n.startswith("Bu maç için piyasa oranı yok")]
        out["notes"] = gorunum.notes(p, eng) + generic
        out["kupa"] = True
        out["compare"] = gorunum.compare_rows(p, eng)
        hk, ak = info.get("home_key", ""), info.get("away_key", "")
        out["forms"] = [(f"{p.home} – son maçlar (lig + kupa)", _table(gorunum.team_recent(core.store, hk, 8))),
                        (f"{p.away} – son maçlar (lig + kupa)", _table(gorunum.team_recent(core.store, ak, 8))),
                        ("Aralarındaki son maçlar", _table(gorunum.head_to_head(core.store, hk, ak, 8)))]
        return out
    out["compare"] = [
        ("Elo puanı", fmt_num(info.get("elo_h"), 0), fmt_num(info.get("elo_a"), 0)),
        ("Son 6 maç puan ort.", fmt_num(info.get("h_ppg6")), fmt_num(info.get("a_ppg6"))),
        ("Son 6 maç attığı / yediği", f"{fmt_num(info.get('h_gf6'), 1)} / {fmt_num(info.get('h_ga6'), 1)}",
         f"{fmt_num(info.get('a_gf6'), 1)} / {fmt_num(info.get('a_ga6'), 1)}"),
        ("İç / dış saha puan ort. (son 5)", fmt_num(info.get("h_home_ppg5")), fmt_num(info.get("a_away_ppg5"))),
        ("İsabetli şut ort. (son 6)", fmt_num(info.get("h_sotf6"), 1), fmt_num(info.get("a_sotf6"), 1)),
        ("Dinlenme (gün)", fmt_num(info.get("h_rest"), 0), fmt_num(info.get("a_rest"), 0)),
        ("Lige yeni (yükselen)", "Evet" if info.get("h_new") else "Hayır", "Evet" if info.get("a_new") else "Hayır"),
    ]
    m = core.store.matches
    out["forms"] = [(f"{p.home} – son maçlar", _table(team_matches(m, p.home, 8, p.league))),
                    (f"{p.away} – son maçlar", _table(team_matches(m, p.away, 8, p.league))),
                    ("Aralarındaki son maçlar", _table(head_to_head(m, p.home, p.away, 8)))]
    return out


@bp.route("/mac")
def mac():
    core = get_state().core
    k = request.args.get("k", "")
    p = next((x for x in list(core.predictions) if fixture_key(x.league, x.date, x.home, x.away) == k), None)
    if p is None:
        flash("Maç bulunamadı (tahminler yenilenmiş olabilir).", "warn")
        return redirect(url_for("views.tahminler"))
    return render_template("mac.html", d=detail_context(core, p), geri=_safe_next(request.args.get("geri"),
                                                                                    url_for("views.tahminler")))


# ================================================================== En Olası Seçimler


@bp.route("/en-olasi")
def en_olasi():
    core = get_state().core
    thr = _float("esik", 0.90, 0.60, 0.99)
    sent = "esik" in request.args
    groups = [g for g in MARKET_GROUPS if (request.args.get(f"g_{g}") == "1") or not sent]
    one = (request.args.get("tek") == "1") or not sent
    keys = [k for g in groups for k in MARKET_GROUPS[g]]
    eng = core.engine
    cards, per_market = None, []
    if eng is not None and eng.oos is not None and not eng.oos.empty:
        v = verify_selection(eng.oos, keys, thr, one)
        if v["n"]:
            cards = {
                "hit": (fmt_pct(v["isabet"]), f"{v['n']:,} geçmiş seçimde (örneklem dışı)".replace(",", "."),
                        "good" if v["isabet"] >= 0.9 else ""),
                "cov": (fmt_pct(v["kapsam"]), f"maçların bu oranında en az bir seçim var ({v['n_mac']:,} maç)"
                        .replace(",", "."), ""),
                "odds": (fmt_num(1.0 / v["ort_olasilik"]), f"ortalama olasılık {fmt_pct(v['ort_olasilik'])}", ""),
                "roi": ((f"{100 * v['roi']:+.1f}%", f"oranı bilinen {v['roi_n']:,} seçimde, ort. oran "
                         f"{fmt_num(v['ort_oran'])}".replace(",", "."), "good" if v["roi"] > 0 else "bad")
                        if v["roi_n"] else ("Hesaplanamıyor", "Seçilen marketler için geçmiş gerçek oran yok", "")),
            }
        else:
            cards = {k: ("-", "Bu eşikte geçmiş seçim yok", "") for k in ("hit", "cov", "odds", "roi")}
        conf = eng.report.confidence if eng.report else {}
        per_market = conf.get("per_market_90", [])
    rows, skipped, warned = [], len(core.match_unpredicted), 0
    now = core.now()
    for p in list(core.predictions):
        if not p.forecast_ok_at(now):  # veri uygunluğu doğrulanmadı: "en olası" listesine girmez
            skipped += 1
            continue
        bet_ok = not p.data_block(now)
        warned += not bet_ok
        cands = [(k, float(p.markets[k])) for k in keys]
        if not cands:
            continue
        if one:
            cands = [max(cands, key=lambda kv: kv[1])]
        for k, prob in cands:
            if prob < thr:
                continue
            o = p.odds.get(k) if bet_ok else None  # yalnızca gerçek oran; türetilmiş oran kullanılmaz
            rows.append({"date": p.date, "time": p.time, "league": p.league, "match": f"{p.home} - {p.away}",
                         "selection": MARKETS[k][0], "prob": prob, "fair": 1.0 / prob, "odds": o if o else None,
                         "ev": prob * o - 1.0 if o else None,
                         "key": fixture_key(p.league, p.date, p.home, p.away)})
    notes = []
    if skipped:
        notes.append(f"Tahmini gösterilemediği için listelenmeyen maç: {skipped}.")
    if warned:
        notes.append(f"Uyarılı (bahis adayı olmayan) {warned} maçta oran ve beklenen değer gösterilmez.")
    from ..kupa.gorunum import likely_history_line

    return render_template("olasi.html", thr=thr, groups=list(MARKET_GROUPS), chosen=groups, one=one, cards=cards,
                           cup_line=likely_history_line(core.cup_engine, keys, thr, one),
                           rows=rows, per_market=per_market, has_model=eng is not None,
                           gate_note=" ".join(notes) + (" Neden ve gereken veri için Tahminler sayfasındaki 'Veri "
                                                        "durumu' sütununa bakın." if notes else ""))


# ================================================================== Maç Analizi (elle)


def _analiz_kupa(core) -> dict:
    """KUPA-01: ligler arası / kupa maçı analizi (iki takım farklı liglerden olabilir). Tahmin kupa motorundan gelir ve
    kupa uygunluk kontrolünden geçer."""
    from ..kupa import gorunum

    eng = core.cup_engine if (core.cup_engine is not None and core.cup_engine.trained) else None
    groups = gorunum.teams_for_analysis(eng)
    keys = {k: n for _g, ts in groups for k, n in ts}
    comps = [c for c in COMPETITIONS]
    comp = request.values.get("turnuva") or "UCL"
    comp = comp if comp in COMPETITIONS else "UCL"
    hk = request.values.get("ev_k") or ""
    ak = request.values.get("dep_k") or ""
    hk = hk if hk in keys else next(iter(keys), "")
    ak = ak if ak in keys else (list(keys)[1] if len(keys) > 1 else "")
    neutral = request.values.get("tarafsiz") == "1"
    tarih = request.values.get("tarih") or f"{core.today():%Y-%m-%d}"
    odds_in = {}
    for k in MARKETS:
        raw = request.form.get(f"o_{k}") if request.method == "POST" else None
        try:
            odds_in[k] = float(str(raw).replace(",", ".")) if raw not in (None, "") else None
        except ValueError:
            odds_in[k] = None
    d = info = None
    if request.method == "POST" and eng is not None:
        if not hk or not ak or hk == ak:
            info = "Lütfen iki farklı takım seçin."
        else:
            try:
                date = dt.date.fromisoformat(tarih)
            except ValueError:
                date = core.today()
            user = {k: v for k, v in odds_in.items() if v is not None and v > 1.0}
            dctx = core.eligibility_context(core.engine if (core.engine is not None and core.engine.trained)
                                            else None)
            p = gorunum.analyze(eng, core.store, dctx, core.settings, comp=comp, home_key=hk, away_key=ak, names=keys,
                                date=date, neutral=neutral, offered=user, as_of=core.now())
            if p is None:
                info = "Takımlardan biri kupa modelinde yok."
            else:
                d = detail_context(core, p, user)
    return {"mod": "kupa", "cup_groups": groups, "comps": comps, "comp": comp, "hk": hk, "ak": ak,
            "neutral": neutral, "tarih": tarih, "markets": MARKETS, "odds_in": odds_in, "d": d, "info": info,
            "has_cup_model": eng is not None, "has_model": True}


@bp.route("/analiz", methods=["GET", "POST"])
def analiz():
    core = get_state().core
    if request.values.get("mod") == "kupa":
        return render_template("analiz.html", **_analiz_kupa(core))
    eng = core.engine
    leagues = [c for c in LEAGUES if eng is not None and eng.trained and c in eng.states]
    lig = request.values.get("lig") or ("T1" if "T1" in leagues else (leagues[0] if leagues else ""))
    if lig not in leagues:
        lig = leagues[0] if leagues else ""
    teams = eng.teams(lig) if (eng is not None and lig) else []
    home = request.values.get("ev") or (teams[0] if teams else "")
    away = request.values.get("dep") or (teams[1] if len(teams) > 1 else "")
    home = home if home in teams else (teams[0] if teams else "")
    away = away if away in teams else (teams[1] if len(teams) > 1 else "")
    fx = core.store.fixtures
    row = None
    if fx is not None and not fx.empty and lig:
        mm = fx[(fx["league"] == lig) & (fx["home"] == home) & (fx["away"] == away)]
        row = None if mm.empty else mm.iloc[0]
    tarih = request.values.get("tarih") or (f"{pd.Timestamp(row['date']):%Y-%m-%d}" if row is not None
                                            else f"{core.today():%Y-%m-%d}")
    # Fikstürde bulunan maçta oranlar önceden doldurulur (masaüstüyle aynı)
    prefill = {}
    if row is not None:
        offered = _odds_dict(row.to_dict(), ODDS_SETS.get(core.settings.odds_type, ODDS_SETS["avg"]))
        prefill = {k: v for k, v in offered.items() if v == v}
    odds_in = {}
    for k in MARKETS:
        raw = request.form.get(f"o_{k}") if request.method == "POST" else None
        try:
            odds_in[k] = float(str(raw).replace(",", ".")) if raw not in (None, "") else prefill.get(k)
        except ValueError:
            odds_in[k] = None
    piyasa = request.form.get("piyasa", "1" if request.method == "GET" else "") == "1"
    d = info = None
    if request.method == "POST" and eng is not None and eng.trained:
        if not home or not away or home == away:
            info = "Lütfen iki farklı takım seçin."
        else:
            try:
                date = dt.date.fromisoformat(tarih)
            except ValueError:
                date = core.today()
            user = {k: v for k, v in odds_in.items() if v is not None and v > 1.0}
            notes = []
            if row is not None:
                market = {k: v for k, v in _odds_dict(row.to_dict(), ODDS_SETS["avg"]).items() if v == v}
                notes.append("Bu maç fikstürde bulundu; piyasa ortalaması oranlar olasılıklara dahil edildi.")
            elif piyasa:
                market = {k: v for k, v in user.items() if k in ("1", "X", "2", "O2.5", "U2.5")}
                if market:
                    notes.append("Girdiğiniz oranlar piyasa bilgisi olarak kullanıldı.")
            else:
                market = {}
            offered = user if user else (market if market else {})
            p = eng.predict_match(lig, home, away, pd.Timestamp(date), "", market, offered, source="manuel")
            # Elle seçilen maç da ortak veri uygunluk kontrolünden geçer (bağlam yoksa sonuç uygun değildir)
            from ..eligibility import gate_match_prediction

            gate_match_prediction(core.eligibility_context(eng), p, core.now())
            info = " ".join(notes)
            d = detail_context(core, p)
    return render_template("analiz.html", mod="lig", leagues=leagues, lig=lig, teams=teams, home=home, away=away,
                           tarih=tarih, markets=MARKETS, odds_in=odds_in, piyasa=piyasa, d=d, info=info,
                           has_model=bool(leagues))


# ================================================================== Güç Sıralaması


@bp.route("/guc")
def guc():
    core = get_state().core
    store, eng = core.store, core.engine
    present = set(store.matches["league"].unique()) if store.has_data else set()
    leagues = [c for c in LEAGUES if c in present]
    lig = request.args.get("lig") or ("T1" if "T1" in leagues else (leagues[0] if leagues else ""))
    cup = core.cup_engine if (core.cup_engine is not None and core.cup_engine.trained) else None
    if lig == "@avrupa" and leagues:  # KUPA-01: ligler arası ortak ölçek
        lt = cup.league_table() if cup is not None else pd.DataFrame()
        tt = cup.team_table(60) if cup is not None else pd.DataFrame()
        return render_template("guc.html", leagues=leagues, lig=lig, avrupa=True, has_cup=cup is not None,
                               league_rows=lt.to_dict("records") if not lt.empty else [],
                               team_rows=tt.to_dict("records") if not tt.empty else [])
    if lig not in leagues:
        lig = leagues[0] if leagues else ""
    ratings, chart = None, None
    if eng is not None and lig:
        df = eng.ratings(lig)
        if df is not None and not df.empty:
            ratings = df.to_dict("records")
            c = SvgCanvas(7, 4.5)
            plot_ratings(c, df)
            chart = svg_img(c)
    seasons = sorted(store.league_matches(lig)["season"].unique(), reverse=True) if (lig and store.has_data) else []
    sezon = request.args.get("sezon") or (str(seasons[0]) if seasons else "")
    table = _table(standings(store.matches, lig, sezon or None)) if (lig and store.has_data) else _table(None)
    return render_template("guc.html", leagues=leagues, lig=lig, seasons=[str(x) for x in seasons], sezon=sezon,
                           ratings=ratings, chart=chart, table=table)


# ================================================================== Geriye Dönük Test


@bp.route("/test")
def test():
    from ..betting.backtest import BacktestConfig, run_backtest

    core = get_state().core
    eng = core.engine
    s = core.settings
    if eng is None or eng.oos is None or eng.oos.empty:
        return render_template("test.html", ready=False)
    all_leagues = [c for c in LEAGUES if c in set(eng.oos["league"].unique())]
    all_seasons = [int(y) for y in sorted(eng.oos["fold"].unique())]
    run = request.args.get("calistir") == "1"
    form = {
        "oran": request.args.get("oran") if request.args.get("oran") in ODDS_TYPE_LABELS else s.odds_type,
        "kaynak": request.args.get("kaynak") if request.args.get("kaynak") in ("final", "model") else "final",
        "ev": _float("ev", s.min_ev, 0.0, 0.5), "olasilik": _float("olasilik", s.min_prob, 0.0, 0.95),
        "min_oran": _float("min_oran", s.min_odds, 1.01, 20), "max_oran": _float("max_oran", s.max_odds, 1.05, 50),
        "miktar": request.args.get("miktar") if request.args.get("miktar") in ("flat", "kelly") else "flat",
        "kelly": _float("kelly", s.kelly_fraction or 0.25, 0.05, 1.0), "kasa": _float("kasa", s.bankroll, 10, 1e7),
        "m_1x2": (request.args.get("m_1x2") == "1") or not run, "m_ou": (request.args.get("m_ou") == "1") or not run,
        # boş seçim test motorunda "hepsi" demektir; form da bunu gösterir
        "ligler": [c for c in request.args.getlist("lig") if c in all_leagues] or all_leagues,
        "sezonlar": [int(y) for y in request.args.getlist("sezon") if y.isdigit() and int(y) in all_seasons]
        or all_seasons,
    }
    out = {"ready": True, "form": form, "odds_labels": ODDS_TYPE_LABELS, "all_leagues": all_leagues,
           "all_seasons": all_seasons, "ran": False}
    if run:
        markets = tuple(m for m, on in (("1X2", form["m_1x2"]), ("OU25", form["m_ou"])) if on)
        cfg = BacktestConfig(
            leagues=form["ligler"], seasons=form["sezonlar"], markets=markets, odds_type=form["oran"],
            prob_source=form["kaynak"], min_ev=form["ev"], min_prob=form["olasilik"], min_odds=form["min_oran"],
            max_odds=max(form["max_oran"], form["min_oran"]), staking=form["miktar"], kelly_fraction=form["kelly"],
            max_stake_pct=s.max_stake_pct, bankroll=form["kasa"])
        res = run_backtest(eng.oos, cfg)
        sm = res.summary
        c1, c2 = SvgCanvas(6, 3.4), SvgCanvas(5, 3.4)
        plot_equity(c1, res.bets, cfg.bankroll, s.currency)
        plot_calibration(c2, res.calibration)
        q = pd.DataFrame(eng.report.per_season) if eng.report else pd.DataFrame()
        verdict = None
        if sm.get("bahis", 0):
            sig = sm["p_value"] < 0.05 and sm["birim_roi"] > 0
            if cfg.odds_type == "max":
                verdict = ("warn", "VARSAYIMSAL SONUÇ: 'En yüksek oran', geçmişte onlarca bahis şirketi arasındaki "
                           "en iyi fiyattır; bu oranların o anda sizin için erişilebilir, limitsiz ve askıda olmadığı "
                           f"doğrulanamaz. Bu sonuç uygulanabilir getiri olarak yorumlanmamalıdır (p = {sm['p_value']:.3f}).")
            elif sig:
                verdict = ("info", f"İstatistiksel olarak anlamlı pozitif getiri (p = {sm['p_value']:.3f}, çoklu deneme "
                           "düzeltmesi yapılmadı). Gerçek oranlara erişim, limitler ve ileriye dönük sanal takip "
                           "olmadan kâr iddiası yapılamaz.")
            else:
                verdict = ("warn", f"Kanıt yetersiz: bu stratejinin getirisi şanstan ayırt edilemiyor (p = "
                           f"{sm['p_value']:.2f}). Bahis şirketi marjı nedeniyle uzun vadede zarar beklenir.")
        if not q.empty:
            q = q[[c for c in ("season", "n", "acc_model_m", "acc_market", "acc_final", "ll_model", "ll_market",
                               "ll_final") if c in q]]
        out.update(ran=True, sm=sm, cur=s.currency, charts=[svg_img(c1), svg_img(c2)], verdict=verdict,
                   tables=_backtest_tables(res, q))
    return render_template("test.html", **out)


def _backtest_tables(res, quality: pd.DataFrame) -> list:
    """Geriye dönük test tabloları (masaüstüyle aynı başlıklar ve biçimler)."""
    from ..fmt import fmt_signed_pct
    from .filters import ev_bg, tarih

    head = {"bahis": "Bahis", "kazanan": "Kazanan", "isabet": "İsabet", "ort_oran": "Ort. oran",
            "yatırılan": "Yatırılan", "kâr": "Kâr", "roi": "ROI", "birim_roi": "Birim ROI", "league": "Lig",
            "season": "Sezon", "market": "Market", "selection": "Seçim"}
    fmts = {"isabet": fmt_pct, "ort_oran": fmt_num, "yatırılan": lambda v: f"{v:,.0f}", "kâr": lambda v: f"{v:+,.0f}",
            "roi": fmt_signed_pct, "birim_roi": fmt_signed_pct, "bahis": lambda v: f"{v:.0f}",
            "kazanan": lambda v: f"{v:.0f}", "league": league_name}
    bg = {"roi": ev_bg}
    q_head = {"season": "Sezon", "n": "Maç", "acc_model_m": "Model isabeti", "acc_market": "Piyasa isabeti",
              "acc_final": "Nihai isabet", "ll_model": "Model log-kayıp", "ll_market": "Piyasa log-kayıp",
              "ll_final": "Nihai log-kayıp"}
    q_fmts = {"acc_model_m": fmt_pct, "acc_market": fmt_pct, "acc_final": fmt_pct,
              "ll_model": lambda v: fmt_num(v, 4), "ll_market": lambda v: fmt_num(v, 4),
              "ll_final": lambda v: fmt_num(v, 4)}
    b_head = {"date": "Tarih", "league": "Lig", "season": "Sezon", "home": "Ev", "away": "Deplasman", "fthg": "EG",
              "ftag": "DG", "market": "Market", "selection": "Seçim", "prob": "Olasılık", "odds": "Oran",
              "ev": "Beklenen değer", "won": "Sonuç", "stake": "Miktar", "profit": "Kâr", "bankroll": "Kasa"}
    b_fmts = {"prob": fmt_pct, "odds": fmt_num, "ev": fmt_signed_pct, "won": lambda v: "Kazandı" if v else "Kaybetti",
              "stake": lambda v: fmt_num(v, 0), "profit": lambda v: f"{v:+,.0f}", "bankroll": lambda v: f"{v:,.0f}",
              "date": tarih}
    b_bg = {"won": lambda v: ev_bg(0.1 if v else -0.1)}
    return [("Sezonlara göre", res.by_season, head, fmts, [], bg), ("Liglere göre", res.by_league, head, fmts, [], bg),
            ("Marketlere göre", res.by_market, head, fmts, [], bg), ("Model kalitesi", quality, q_head, q_fmts, [], {}),
            ("Tüm bahisler", res.bets, b_head, b_fmts, ["fold", "closing", "unit_profit"], b_bg)]


# ================================================================== Veri


@bp.route("/veri", methods=["GET"])
def veri():
    st = get_state()
    core = st.core
    s = core.settings
    decl = s.declarations()
    names = [SOURCES[k].name + (" (kişisel kullanım beyanı var)" if k in decl else
                                " (beyan yok: bu kaynağın verisiyle model eğitilmez, tahmin gösterilmez)"
                                if k in DECLARABLE else "")
             for k in IMPLEMENTED if SOURCES[k].requires_consent and k in s.source_consent]
    countries: dict[str, list] = {}
    for code, lg in LEAGUES.items():
        countries.setdefault(lg.country, []).append((code, lg.name))
    summary = core.store.summary() if core.store.has_data else pd.DataFrame()
    from ..kupa.gorunum import choice_groups, report_rows
    from ..kupa.turnuvalar import default_for_leagues
    from ..kupa.veri import summary as cup_summary

    cup_groups = choice_groups()
    cs = cup_summary(getattr(core.store, "cup_matches", None))
    cup_rep = report_rows(core.cup_engine)
    return render_template("veri.html", names=names, countries=countries, chosen=set(s.leagues), years=s.years_back,
                           cup_groups=cup_groups, cups_chosen=set(s.kupalar or []),
                           default_cups=",".join(default_for_leagues(s.leagues)),
                           cup_summary=cs.to_dict("records") if not cs.empty else [], cup_report=cup_rep,
                           cup_fixtures=len(core.store.cup_fixtures) if getattr(core.store, "cup_fixtures", None)
                           is not None else 0,
                           profile=s.data_profile, profiles=[(PROFILE_DEFAULT, "Varsayılan: football-data.co.uk (onay "
                                                              "verildiyse GitHub yedek)"),
                                                             (PROFILE_GITHUB, "Yalnızca GitHub: seçili depolar "
                                                              "(football-data adreslerine istek yok)")],
                           summary=summary.to_dict("records") if not summary.empty else [],
                           report=core.last_report_text, updated=(core.store.meta.get("updated_at") or "")
                           .replace("T", " "), default_leagues=",".join(DEFAULT_LEAGUES),
                           needs_consent=needs_consent(s))


@bp.route("/veri/guncelle", methods=["POST"])
def veri_guncelle():
    st = get_state()
    s = st.core.settings
    if request.form.get("kaydet") == "1":
        codes = [c for c in LEAGUES if request.form.get(f"lig_{c}") == "1"]
        if not codes:
            flash("En az bir lig seçin.", "warn")
            return redirect(url_for("views.veri"))
        new = copy.deepcopy(s)
        new.leagues = codes
        new.kupalar = [c for c in COMPETITIONS if request.form.get(f"kupa_{c}") == "1"]  # KUPA-01
        try:
            new.years_back = int(request.form.get("yil", s.years_back))
        except ValueError:
            pass
        prof = request.form.get("profil")
        if prof in (PROFILE_DEFAULT, PROFILE_GITHUB):
            new.data_profile = prof
        new.validate()
        new.save()
        with st.core.lock:
            st.core.settings = new
    if needs_consent(st.core.settings):
        flash("Veri indirmeden önce kaynakların kullanım koşullarını onaylayın.", "warn")
        return redirect(url_for("views.onay", sonra="guncelle"))
    _started(st.start_update(force=request.form.get("zorla") == "1"), "Veri güncellemesi")
    return redirect(_safe_next(request.form.get("sonra"), url_for("views.veri")))


@bp.route("/model/egit", methods=["POST"])
def model_egit():
    st = get_state()
    block = st.training_block_text()
    if block:
        flash(block, "warn")
    else:
        _started(st.start_retrain(), "Model eğitimi")
    return redirect(_safe_next(request.form.get("sonra"), url_for("views.genel")))


# ================================================================== Onaylar


@bp.route("/onay", methods=["GET", "POST"])
def onay():
    st = get_state()
    core = st.core
    s = core.settings
    keys = consent_keys()
    if request.method == "POST":
        if request.form.get("vazgec"):
            if request.form.get("sonra") == "guncelle":
                flash(NOT_UPDATED_TEXT, "warn")
            return redirect(url_for("views.veri"))
        chosen = [k for k in keys if request.form.get(f"onay_{k}") == "1"]
        declared = [k for k in keys if request.form.get(f"beyan_{k}") == "1" and k in chosen and k in DECLARABLE]
        before = set(s.declarations())
        changed = apply_consent(s, chosen, declared, keys)
        added = bool(set(s.declarations()) - before)
        if request.form.get("sonra") == "guncelle":
            if needs_consent(s):
                if changed:
                    core.refresh_predictions()
                flash(NOT_UPDATED_TEXT, "warn")
                return redirect(url_for("views.veri"))
            _started(st.start_update(), "Veri güncellemesi")
            return redirect(url_for("views.veri"))
        msg = st.after_rights_change(added) if changed else None
        flash(msg or "Onaylar kaydedildi.", "info")
        return redirect(url_for("views.veri"))
    sources = [{"key": k, "s": SOURCES[k], "declarable": k in DECLARABLE, "consent": k in s.source_consent,
                "decl": k in s.source_consent and k in s.kisisel_kullanim} for k in keys]
    free = [SOURCES[k].name for k in IMPLEMENTED if not SOURCES[k].requires_consent]
    return render_template("onay.html", sources=sources, free=free, sonra=request.args.get("sonra", ""))


# ================================================================== Ayarlar


@bp.route("/ayarlar", methods=["GET", "POST"])
def ayarlar():
    st = get_state()
    s = st.core.settings
    if request.method == "POST":
        new = copy.deepcopy(s)
        f = request.form

        def num(name, default, lo, hi):
            try:
                v = float(str(f.get(name, default)).replace(",", "."))
            except ValueError:
                return default
            return float(min(max(v, lo), hi)) if v == v else default

        new.odds_type = f.get("oran", s.odds_type)
        new.margin_method = f.get("marj", s.margin_method)
        new.min_ev = num("min_ev", s.min_ev, 0, 1)
        new.min_prob = num("min_prob", s.min_prob, 0, 0.99)
        new.min_odds = num("min_odds", s.min_odds, 1.01, 50)
        new.max_odds = max(num("max_odds", s.max_odds, 1.05, 100), new.min_odds)
        new.bankroll = num("kasa", s.bankroll, 0, 1e9)
        new.currency = (f.get("para", "") or "TL").strip()[:6] or "TL"
        new.kelly_fraction = num("kelly", s.kelly_fraction, 0, 1)
        new.max_stake_pct = num("tavan", s.max_stake_pct, 0, 1)
        new.stake_suggestions = f.get("miktar_oner") == "1"
        new.auto_update_on_start = f.get("oto") == "1"
        new.use_mirror_fallback = f.get("yedek") == "1"
        try:
            new.fixture_days = int(f.get("gun", s.fixture_days))
        except ValueError:
            pass
        new.veri_denetimi = f.get("denetim", s.veri_denetimi)
        new.sanal_stake_yontemi = f.get("sanal_stake", s.sanal_stake_yontemi)
        flash(st.save_settings(new), "info")
        return redirect(url_for("views.ayarlar"))
    from ..goals.disiplin import STAKE_METHODS, readiness, readiness_text

    with st.core.ledger(create=False) as led:
        ready_line = readiness_text(readiness(led))  # DISIPLIN-07
    return render_template("ayarlar.html", s=s, odds_labels=ODDS_TYPE_LABELS, stake_methods=STAKE_METHODS,
                           ready_line=ready_line)


# ================================================================== Hakkında


@bp.route("/hakkinda")
def hakkinda():
    from ..about_text import ABOUT_HTML
    from ..models.features import FEATURES

    html = ABOUT_HTML.format(version=escape(__version__), home=escape(str(get_state().core.home)),
                             n_features=len(FEATURES))
    return render_template("hakkinda.html", about=Markup(html))


__all__ = ["bp", "fixture_key", "detail_context", "Settings"]

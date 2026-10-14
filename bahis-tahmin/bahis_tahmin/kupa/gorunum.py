"""Kupa maçlarının arayüz görünümü (KUPA-01): maç ayrıntısındaki karşılaştırma satırları, notlar ve son maçlar.

Masaüstü (``ui``) ve web (``web``) aynı işlevleri kullanır.
"""

from __future__ import annotations

import pandas as pd

from ..data.leagues import LEAGUES
from ..fmt import fmt_num, fmt_pct
from .motor import DOGRULANDI, EPOCH, STATUS_TR, key_of
from .turnuvalar import COMPETITIONS, VALIDATION_GROUPS, VALIDATION_NAMES, competition_name


def league_label(code: str | None) -> str:
    if not code:
        return "-"
    if code in LEAGUES:
        return LEAGUES[code].label
    if str(code).startswith("X:"):
        rest = str(code)[2:]
        return "Ligi veride yok" + (f" ({rest})" if rest and rest != "?" else "")
    return str(code)


def _signed(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-"
    return "-" if f != f else f"{f:+.2f}"


def is_cup_prediction(p) -> bool:
    return bool((getattr(p, "info", None) or {}).get("kupa"))


def compare_rows(p, engine) -> list[tuple[str, str, str]]:
    """Takım karşılaştırması (ortak ölçek): lig, güç, beklenen gol, son 365 günde maç, saha."""
    info = p.info or {}
    hs, as_ = info.get("home_strength"), info.get("away_strength")
    day = int((pd.Timestamp(p.date).normalize() - EPOCH).days)
    n_h = engine.team_n(info.get("home_key", ""), day) if engine is not None else None
    n_a = engine.team_n(info.get("away_key", ""), day) if engine is not None else None
    rows = [
        ("Ligi", league_label(info.get("home_league")), league_label(info.get("away_league"))),
        ("Ortak ölçekte güç (hücum + savunma)", _signed(sum(hs) if hs else None), _signed(sum(as_) if as_ else None)),
        ("Hücum / savunma gücü", f"{_signed(hs[0])} / {_signed(hs[1])}" if hs else "-",
         f"{_signed(as_[0])} / {_signed(as_[1])}" if as_ else "-"),
        ("Beklenen gol (bu maç)", fmt_num(info.get("lam"), 2), fmt_num(info.get("nu"), 2)),
        ("Son 365 günde maç (lig + kupa)", "-" if n_h is None else str(n_h), "-" if n_a is None else str(n_a)),
    ]
    rows.append(("Saha", "Tarafsız saha" if info.get("neutral") else "İç saha",
                 "Tarafsız saha" if info.get("neutral") else "Deplasman"))
    return rows


def validation_line(engine, comp: str) -> str:
    """Turnuvanın doğrulama grubundaki model ölçümü (tek satır)."""
    if engine is None or engine.report is None:
        return "Kupa modeli doğrulama raporu yok."
    c = COMPETITIONS.get(comp)
    vg = VALIDATION_GROUPS.get(c.group if c else "C", "YURTICI")
    g = engine.report.groups.get(vg, {})
    st = engine.status.get(vg)
    if not g.get("n"):
        return f"Model doğrulaması ({VALIDATION_NAMES[vg]}): {STATUS_TR.get(st, '-')} — {g.get('neden', '')}"
    txt = (f"Model doğrulaması ({VALIDATION_NAMES[vg]}): {STATUS_TR.get(st, '-')} — geçmiş {g['n']} maçta (model o "
           f"maçları görmeden) log-kayıp {fmt_num(g['ll'], 3)} (taban {fmt_num(g['ll_taban'], 3)}), isabet "
           f"{fmt_pct(g['isabet'])}")
    if st != DOGRULANDI and g.get("neden"):
        txt += f"; {g['neden']}"
    return txt + "."


def notes(p, engine) -> list[str]:
    info = p.info or {}
    out = [f"{competition_name(p.league)} maçı: olasılıklar, bütün lig ve kupa maçlarından kurulan ligler arası ortak "
           "modelden gelir; kupa maçları için veri setinde piyasa oranı yok (Maç Analizi'nde oran girebilirsiniz)."]
    if info.get("neutral"):
        out.append("Maç tarafsız sahada oynanıyor: iç saha avantajı uygulanmadı.")
    out.append(validation_line(engine, p.league))
    return out


def _team_rows(store, key: str) -> pd.DataFrame:
    """Takımın lig ve kupa maçları (tek tablo): tarih, turnuva/lig, ev, deplasman, skor, takım ev sahibi mi."""
    parts = []
    m = store.matches
    if m is not None and not m.empty and "|" in key:
        country, team = key.split("|", 1)
        codes = [c for c, lg in LEAGUES.items() if lg.country == country]
        g = m[m["league"].isin(codes) & ((m["home"] == team) | (m["away"] == team))]
        if not g.empty:
            parts.append(pd.DataFrame({"date": g["date"], "yer": g["league"].map(lambda c: LEAGUES[c].name),
                                       "home": g["home"], "away": g["away"], "fthg": g["fthg"], "ftag": g["ftag"],
                                       "is_home": g["home"] == team}))
    cups = getattr(store, "cup_matches", None)
    if cups is not None and not cups.empty:
        g = cups[(cups["home_key"] == key) | (cups["away_key"] == key)]
        if not g.empty:
            parts.append(pd.DataFrame({"date": g["date"], "yer": g["comp"].map(competition_name), "home": g["home"],
                                       "away": g["away"], "fthg": g["fthg"], "ftag": g["ftag"],
                                       "is_home": g["home_key"] == key}))
    if not parts:
        return pd.DataFrame(columns=["date", "yer", "home", "away", "fthg", "ftag", "is_home"])
    return pd.concat(parts, ignore_index=True).sort_values("date", ascending=False, kind="mergesort")


def team_recent(store, key: str, n: int = 8) -> pd.DataFrame:
    rows = []
    for r in _team_rows(store, key).head(n).itertuples(index=False):
        gf, ga = (r.fthg, r.ftag) if r.is_home else (r.ftag, r.fthg)
        rows.append({"Tarih": r.date, "Lig / turnuva": r.yer, "Rakip": r.away if r.is_home else r.home,
                     "Yer": "İç" if r.is_home else "Dış", "Skor": f"{r.fthg}-{r.ftag}",
                     "Sonuç": "G" if gf > ga else "B" if gf == ga else "M"})
    return pd.DataFrame(rows)


def head_to_head(store, home_key: str, away_key: str, n: int = 8) -> pd.DataFrame:
    """İki takımın aralarındaki son maçlar (aynı ligdeyse lig maçları dahil)."""
    a = _team_rows(store, home_key)
    other = away_key.split("|", 1)[1] if "|" in away_key else away_key
    cups = getattr(store, "cup_matches", None)
    names = {other}
    if cups is not None and not cups.empty:
        names |= set(cups.loc[cups["home_key"] == away_key, "home"]) | set(cups.loc[cups["away_key"] == away_key, "away"])
    g = a[a["home"].isin(names) | a["away"].isin(names)].head(n)
    return pd.DataFrame([{"Tarih": r.date, "Lig / turnuva": r.yer, "Ev": r.home, "Skor": f"{r.fthg}-{r.ftag}",
                          "Deplasman": r.away} for r in g.itertuples(index=False)])


def teams_for_analysis(engine) -> list[tuple[str, list[tuple[str, str]]]]:
    """Maç Analizi'nin ligler arası bölümü: (grup adı, [(anahtar, ad)]) — önce uygulamanın ligleri, sonra ligi veride
    olmayan takımlar."""
    if engine is None or not engine.trained:
        return []
    by = engine.teams_by_league()
    out = []
    for code, lg in LEAGUES.items():
        if code in by:
            out.append((lg.label, by[code]))
    rest = sorted((k for k in by if k not in LEAGUES), key=str)
    others = [t for k in rest for t in by[k]]
    if others:
        out.append(("Ligi veride olmayan takımlar (yalnızca kupa maçları)", sorted(others, key=lambda x: x[1])))
    return out


def team_country(engine, key: str) -> str:
    return engine.team_country.get(key, key.split("|", 1)[0] if "|" in key else "") if engine is not None else ""


def likely_history_line(engine, keys: list, threshold: float, one_per_match: bool) -> str:
    """En Olası Seçimler: kartlar lig modelinin geçmişidir; kupa maçları ayrı modelden gelir. Aynı eşikte kupa
    modelinin örneklem dışı geçmişi (doğrulanmış gruplarda) tek satır; model yoksa boş."""
    from ..models.engine import verify_selection

    df = getattr(engine, "oos_markets", None) if engine is not None else None
    if df is None or df.empty:
        return ""
    ok = [g for g, st in (engine.status or {}).items() if st == DOGRULANDI]
    df = df[df["vgroup"].isin(ok)]
    v = verify_selection(df, keys, threshold, one_per_match)
    head = ("Kupa ve Avrupa maçları ayrı modelden (ligler arası ortak model) gelir; kartlar yalnızca lig maçlarının "
            "geçmişidir.")
    if not v["n"]:
        return head + " Kupa modelinin doğrulanmış gruplarında bu eşikte geçmiş seçim yok."
    n = f"{v['n']:,}".replace(",", ".")
    return (f"{head} Kupa modelinde aynı eşikte geçmişte gerçekleşme: {fmt_pct(v['isabet'])} "
            f"({n} seçim, ortalama olasılık {fmt_pct(v['ort_olasilik'])}; örneklem dışı, doğrulanmış gruplar).")


def choice_groups() -> dict[str, list[tuple[str, str, bool]]]:
    """Veri sayfasındaki turnuva seçimi: başlık -> [(kod, ad, doğrulanmadı mı)]."""
    from .turnuvalar import GROUP_NAMES

    out: dict[str, list] = {}
    for code, c in COMPETITIONS.items():
        title = ("UEFA" if c.region == "UEFA" else (f"Yurt içi: {c.country}" if c.group == "C" and c.country
                                                    else GROUP_NAMES.get(c.group, c.region)))
        out.setdefault(title, []).append((code, c.name, c.unverified))
    return out


def report_rows(engine) -> list[dict]:
    """Kupa modeli doğrulama raporu (Veri sayfası): doğrulama grubu ve turnuva başına ölçümler."""
    if engine is None or getattr(engine, "report", None) is None:
        return []
    rows = []
    for g in engine.report.groups.values():
        rows.append({"ad": g.get("ad"), "n": g.get("n", 0), "ll": g.get("ll"), "taban": g.get("ll_taban"),
                     "isabet": g.get("isabet"), "o25": g.get("ll_o25"), "o25_taban": g.get("ll_o25_taban"),
                     "statu": STATUS_TR.get(g.get("statu"), "-"), "neden": g.get("neden", ""), "grup": True})
    for c in engine.report.competitions:
        rows.append({"ad": "  " + str(c.get("ad")), "n": c.get("n", 0), "ll": c.get("ll"), "taban": c.get("ll_taban"),
                     "isabet": c.get("isabet"), "o25": c.get("ll_o25"), "o25_taban": c.get("ll_o25_taban"),
                     "statu": "", "neden": "", "grup": False})
    return rows


def analyze(engine, store, dctx, settings, *, comp: str, home_key: str, away_key: str, names: dict, date,
            neutral: bool, offered: dict, as_of):
    """Elle seçilen ligler arası / kupa maçı (Maç Analizi): kupa motoru tahmini + kupa veri uygunluğu.

    Masaüstü ve web aynı yolu kullanır; uygunluk bağlamı kurulamazsa tahmin uygun sayılmaz (``CupContext``)."""
    from .turnuvalar import season_label, season_start
    from .uygunluk import build_cup_context

    hc, ac = team_country(engine, home_key), team_country(engine, away_key)
    p = engine.predict(comp, home_key, away_key, names[home_key], names[away_key], hc, ac, pd.Timestamp(date), "",
                       neutral, "manuel", offered_odds=offered)
    if p is None:
        return None
    c = COMPETITIONS[comp]
    cctx = build_cup_context(store, engine, dctx, settings)
    p.eligibility = cctx.evaluate(
        comp=comp, season=season_label(season_start(date, c.calendar_year), c.calendar_year), date=date,
        home=names[home_key], away=names[away_key], home_key=home_key, away_key=away_key, home_country=hc,
        away_country=ac, as_of=as_of, source="manuel", provider_id="", prediction=p)["1X2"]
    return p


__all__ = ["compare_rows", "notes", "team_recent", "head_to_head", "is_cup_prediction", "league_label",
           "validation_line", "teams_for_analysis", "team_country", "analyze", "choice_groups", "report_rows", "likely_history_line", "key_of"]

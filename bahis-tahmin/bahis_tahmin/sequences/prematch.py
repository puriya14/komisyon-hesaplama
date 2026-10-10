"""Maç öncesi "benzer diziler" görünümü (sözleşme §13): yalnızca karar anından (maç günü 00:00) önce bilinen bilgi.

* Yaklaşan maç, oynanmış maç tablosuna sonucu bilinmeyen bir satır olarak eklenir; dizi atomları yalnızca o takımın
  DAHA ÖNCEKİ günlerdeki maçlarından hesaplanır (``features.history_atoms``). Yaklaşan maçın kendi sonucu yoktur.
* Geçmiş benzer örnekler: aynı koşulun (tek atom veya atom çifti) doğru olduğu, ``label_known_at < decision_time``
  olan geçmiş satırlar; başarılı ve başarısız örnekler BİRLİKTE gösterilir.
* Görünümde ``POST_EVENT`` alanı yoktur (testle korunur). Statü yalnızca dondurulmuş araştırma kaydından okunur;
  ``OUT_OF_SAMPLE_SUPPORTED`` olmayan örüntüler olasılığı değiştirmez ve benzerlik puanı olasılığa eklenmez.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.parsers import MATCH_COLUMNS
from . import config as C
from .features import SeqIndex, history_atoms, outcome_codes
from .frame import target_outcomes, target_probs, team_cell_probs
from .timeline import build_team_matches, season_year

FIXTURE_SOURCE = "YAKLASAN_MAC"
MAX_EXAMPLES = 20
NO_ADJUST_NOTE = ("Olasılık değiştirilmedi: yalnızca örneklem dışında doğrulanmış (OUT_OF_SAMPLE_SUPPORTED) ve "
                  "ileriye dönük takipteki örüntüler sanal takipte ayrıca gösterilebilir; benzerlik puanı olasılık değildir.")


def append_fixtures(matches: pd.DataFrame, fixtures: pd.DataFrame) -> pd.DataFrame:
    """Oynanmamış maçları sonuç sütunları boş satırlar olarak ekler (sezon etiketi aynı ligin son sezonundan).

    Oynanmış bir maçla aynı (lig, tarih, ev, deplasman) satırlar ve son oynanmış maçtan önceki fikstürler atlanır.
    """
    if fixtures is None or fixtures.empty:
        return matches.copy()
    fx = fixtures.copy()
    fx = fx[fx["league"].isin(matches["league"].unique())]
    last = matches.sort_values("date").groupby("league").tail(1).set_index("league")
    rows = []
    for _, r in fx.iterrows():
        if r["league"] not in last.index:
            continue
        lr = last.loc[r["league"]]
        d = pd.Timestamp(r["date"])
        if d <= pd.Timestamp(lr["date"]) or int(season_year(pd.Series([d]))[0]) != int(season_year(pd.Series([lr["date"]]))[0]):
            continue
        rows.append({"league": r["league"], "season": lr["season"], "date": d, "time": r.get("time", ""),
                     "home": r["home"], "away": r["away"], "source": FIXTURE_SOURCE})
    if not rows:
        return matches.copy()
    add = pd.DataFrame(rows)
    for c in MATCH_COLUMNS:
        if c not in add.columns:
            add[c] = np.nan
    key = ["league", "date", "home", "away"]
    add = add.merge(matches[key], on=key, how="left", indicator=True)
    add = add[add["_merge"] == "left_only"].drop(columns="_merge")
    return pd.concat([matches, add[matches.columns]], ignore_index=True)


def prematch_frame(matches: pd.DataFrame, fixtures: pd.DataFrame, s0_cal: pd.DataFrame | None = None,
                   alias_map=None) -> dict:
    """Yaklaşan maç satırlarıyla takım-maç tablosu ve dizi atomları.

    ``s0_cal``: araştırmanın kalibre S0 hücreleri (event_id + 9 hücre); yoksa beklenen puanlı atomlar tanımsızdır.
    """
    allm = append_fixtures(matches, fixtures)
    tm = build_team_matches(allm, alias_map)
    raw = np.full((len(tm), 9), np.nan)
    if s0_cal is not None and len(s0_cal):
        from ..goals.markets import HTFT_KEYS

        cal = s0_cal.set_index("event_id")[list(HTFT_KEYS)]
        raw = cal.reindex(tm["event_id"]).to_numpy(dtype=float)
    tp = team_cell_probs(raw, tm["is_home"].to_numpy())
    p0 = target_probs(tp)
    exp_points = 3.0 * p0["GALIBIYET"] + p0["BERABERLIK"]
    si = SeqIndex(tm)
    ht, ft = outcome_codes(tm)
    atoms = history_atoms(si, ht, ft, exp_points)
    upcoming = (tm["source"].astype(str) == FIXTURE_SOURCE).to_numpy()
    return {"tm": tm, "atoms": atoms, "p0": p0, "y": target_outcomes(tm), "upcoming": upcoming,
            "has_s0": s0_cal is not None and len(s0_cal) > 0}


def _status_lookup(results: dict | None) -> dict[str, dict]:
    if not results:
        return {}
    out = {}
    for r in results.get("oruntuler", []) or []:
        out[f"{r.get('hedef')}|{r.get('kosul')}"] = r
    for dup, rep in (results.get("ayna_kopyalari") or {}).items():  # ayna kopyası → temsilcinin statüsü
        if rep in out:
            out[dup] = {**out[rep], "ayna_kopyasi_of": rep}
    return out


def prematch_view(pf: dict, row: int, results: dict | None = None, targets=C.TARGETS_Q1,
                  max_examples: int = MAX_EXAMPLES) -> dict:
    """Bir yaklaşan maç satırı için maç öncesi görünüm (POST_EVENT yok)."""
    tm = pf["tm"]
    if not pf["upcoming"][row]:
        raise ValueError("Maç öncesi görünüm yalnızca oynanmamış (yaklaşan) maç satırı için kurulur")
    decision = pd.Timestamp(tm.at[row, "date"]).normalize()
    atoms = pf["atoms"]
    state = {}
    for a in C.HISTORY_ATOMS:
        v = atoms[a][row]
        state[a] = None if not np.isfinite(v) else bool(v == 1)
    true_atoms = [a for a, v in state.items() if v]
    conds = [(a, (a,)) for a in true_atoms]
    conds += [(f"{a} & {b}", (a, b)) for i, a in enumerate(true_atoms) for b in true_atoms[i + 1:]]
    known = (pd.to_datetime(tm["date"]) + pd.Timedelta(days=1) < decision).to_numpy()  # label_known_at < karar anı
    lookup = _status_lookup(results)
    sections = []
    for name, at in conds:
        cmask = known.copy()
        for a in at:
            cmask &= np.nan_to_num(atoms[a], nan=0.0) == 1
        for t in targets:
            y = np.asarray(pf["y"][t], dtype=float)
            p = np.asarray(pf["p0"][t], dtype=float)
            sel = cmask & np.isfinite(y)
            idx = np.where(sel)[0]
            rec = lookup.get(f"{t}|{name}")
            hits = idx[y[idx] == 1]
            misses = idx[y[idx] == 0]
            exp = float(np.nansum(p[idx])) if pf["has_s0"] else None
            sections.append({
                "kosul": name, "hedef": t, "n_gecmis": int(len(idx)), "isabet": int(len(hits)), "iska": int(len(misses)),
                "olay_orani": float(len(hits) / len(idx)) if len(idx) else None,
                "s0_beklenen": exp, "statu": rec.get("statu") if rec else "KAYIT_YOK",
                "statu_kaynagi": "dondurulmuş araştırma kaydı" if rec else "araştırma kaydında yok / çalıştırılmadı",
                "olasiliga_etki": "yok", "ornekler_isabet": _examples(tm, hits[::-1][:max_examples], y),
                "ornekler_iska": _examples(tm, misses[::-1][:max_examples], y),
            })
    head = {k: (tm.at[row, k].isoformat() if isinstance(tm.at[row, k], pd.Timestamp) else tm.at[row, k])
            for k in ("event_id", "league", "season", "team", "opponent", "is_home")}
    head["date"] = str(decision.date())
    return {
        "gorunum": "MAC_ONCESI", "karar_ani": f"{decision.date()} 00:00 (yerel)", "kimlik": head,
        "PRE_EVENT_KOSULLARI": state, "benzer_kosullar": sections,
        "not": NO_ADJUST_NOTE,
        "zaman_kurali": "Yalnızca karar anından önceki günlerin maçları; geçmiş örneklerin sonucu ertesi gün bilinir.",
    }


def _examples(tm: pd.DataFrame, rows: np.ndarray, y: np.ndarray) -> list[dict]:
    out = []
    for r in rows:
        out.append({"tarih": str(pd.Timestamp(tm.at[r, "date"]).date()), "lig": tm.at[r, "league"],
                    "takim": tm.at[r, "team"], "rakip": tm.at[r, "opponent"], "ev": bool(tm.at[r, "is_home"]),
                    "iy_ms": tm.at[r, "htft"] if isinstance(tm.at[r, "htft"], str) else None,
                    "hedef_gerceklesti": bool(y[r] == 1)})
    return out

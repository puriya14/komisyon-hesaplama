"""StatsBomb açık verisi (hudl/open-data) okuyucuları (S5-GITHUB-01).

Şema: depodaki ``doc/Open Data Events v4.0.0.pdf`` ve ``doc/Open Data Matches v3.0.0.pdf``. Olaylardan skor:

* ``period`` 1 ve 2 normal sürenin devreleri; 3 ve 4 uzatma; 5 penaltı atışları. İY = 1. devre; MS (normal süre) =
  1. + 2. devre. Uzatma golleri MS'ye, penaltı atışları hiçbir skora girmez.
* Gol: ``Shot`` (tür 16) olayı ve sonucu ``Goal`` (97) — resmî olarak gol sayılmayan şut bu sonucu almaz. Kendi
  kalesine gol iki olayla gelir: ``Own Goal For`` (25, yararlanan takım) ve ``Own Goal Against`` (20, yiyen takım);
  yalnızca 25 sayılır, 20 eşleşme denetimidir (çift sayım yok). Sayılar tutmazsa skor üretilmez.
* Üretilen skor maç meta verisindeki skorla uzlaştırılır; uyuşmazsa skor UYDURULMAZ (``UYUSMAZ``).

Maç sırasında oluşan xG ve şutlar yalnızca o maçın geçmiş açıklamasıdır; o maçın maç öncesi özelliği yapılmaz.
"""

from __future__ import annotations

import json
from collections import Counter

STATSBOMB_PARSER = "statsbomb-olay-v1"
SHOT, OWN_GOAL_AGAINST, OWN_GOAL_FOR = 16, 20, 25
GOAL_OUTCOME = 97
REGULAR_PERIODS, EXTRA_PERIODS, SHOOTOUT = (1, 2), (3, 4), 5
# Bu uygulamanın lig kodlarına yalnızca açıkça doğrulanmış eşleme: (competition_id) -> lig
COMPETITION_TO_LEAGUE = {2: "E0"}

OK = "UZLASTI"
MISMATCH = "UYUSMAZ"
INCOMPLETE = "OLAY_KAPSAMI_EKSIK"


def season_label(name: str) -> str | None:
    """"2015/2016" -> "2015/16"; tek yıllık sezonlar aynen."""
    s = str(name or "").strip()
    if len(s) == 9 and s[4] == "/" and s[:4].isdigit() and s[5:].isdigit():
        return f"{s[:4]}/{s[7:]}"
    return s if s.isdigit() else None


def parse_competitions(data: bytes) -> list[dict]:
    rows = json.loads(data.decode("utf-8"))
    if not isinstance(rows, list):
        raise ValueError("competitions.json bir liste değil")
    return rows


def parse_matches(data: bytes) -> list[dict]:
    """Maç listesi: kimlikler, tarih/saat, takım kimlikleri ve meta skor (ham alanlar korunur)."""
    rows = json.loads(data.decode("utf-8"))
    out = []
    for m in rows if isinstance(rows, list) else []:
        comp = m.get("competition") or {}
        ht, at = m.get("home_team") or {}, m.get("away_team") or {}
        out.append({
            "match_id": m.get("match_id"), "date": m.get("match_date"), "kick_off": m.get("kick_off"),
            "competition_id": comp.get("competition_id"), "competition": comp.get("competition_name"),
            "season": season_label((m.get("season") or {}).get("season_name")),
            "home_id": ht.get("home_team_id"), "home": ht.get("home_team_name"),
            "home_gender": ht.get("home_team_gender"),
            "away_id": at.get("away_team_id"), "away": at.get("away_team_name"),
            "away_gender": at.get("away_team_gender"),
            "home_score": m.get("home_score"), "away_score": m.get("away_score"),
            "status": m.get("match_status"), "last_updated": m.get("last_updated"),
            "match_week": m.get("match_week"), "stage": (m.get("competition_stage") or {}).get("name"),
        })
    return out


def score_from_events(events: list[dict], match: dict) -> dict:
    """Olaylardan devre bazlı skor ve maç açıklaması (xG, şut). Döner: ht/ft/et skorları, uzlaşma durumu, sayımlar."""
    hid, aid = match.get("home_id"), match.get("away_id")
    side = {hid: "h", aid: "a"}
    goals = {p: Counter() for p in (1, 2, 3, 4, 5)}
    og_for, og_against = Counter(), Counter()
    xg, shots = Counter(), Counter()
    periods = set()
    unknown_team = 0
    for e in events:
        p = e.get("period")
        if isinstance(p, int):
            periods.add(p)
        t = (e.get("type") or {}).get("id")
        team = side.get((e.get("team") or {}).get("id"))
        if t not in (SHOT, OWN_GOAL_FOR, OWN_GOAL_AGAINST):
            continue
        if team is None:
            unknown_team += 1
            continue
        if t == SHOT:
            sh = e.get("shot") or {}
            if p in REGULAR_PERIODS + EXTRA_PERIODS:
                shots[team] += 1
                v = sh.get("statsbomb_xg")
                if isinstance(v, (int, float)):
                    xg[team] += float(v)
            if (sh.get("outcome") or {}).get("id") == GOAL_OUTCOME and p in goals:
                goals[p][team] += 1
        elif t == OWN_GOAL_FOR and p in goals:
            goals[p][team] += 1
            og_for[(p, team)] += 1
        elif t == OWN_GOAL_AGAINST and p in goals:
            og_against[(p, "a" if team == "h" else "h")] += 1  # yiyen takımın rakibi yararlanır
    ht = (goals[1]["h"], goals[1]["a"])
    ft = (goals[1]["h"] + goals[2]["h"], goals[1]["a"] + goals[2]["a"])
    et = (ft[0] + goals[3]["h"] + goals[4]["h"], ft[1] + goals[3]["a"] + goals[4]["a"])
    issues = []
    if not {1, 2} <= periods:
        issues.append("NORMAL_DEVRE_EKSIK")
    if unknown_team:
        issues.append("TAKIM_KIMLIGI_UYUSMAZ")
    if og_for != og_against:
        issues.append("KENDI_KALESINE_GOL_ESLESMEDI")
    meta = (match.get("home_score"), match.get("away_score"))
    has_et = bool(periods & set(EXTRA_PERIODS))
    expected = et if has_et else ft
    if issues:
        status = INCOMPLETE
    elif not all(isinstance(v, int) for v in meta) or tuple(meta) != expected:
        status = MISMATCH
    else:
        status = OK
    ok = status == OK
    return {"durum": status, "sorunlar": issues, "uzatma": has_et, "penalti_atislari": SHOOTOUT in periods,
            "iy": ht if ok else None, "ms": ft if ok else None, "uzatma_sonu": et if (ok and has_et) else None,
            "meta_skor": meta, "olaydan_ms": ft, "olaydan_iy": ht,
            "kendi_kalesine": sum(og_for.values()), "xg": {"h": round(xg["h"], 3), "a": round(xg["a"], 3)},
            "sut": {"h": shots["h"], "a": shots["a"]}, "olay_sayisi": len(events), "ayristirici": STATSBOMB_PARSER}

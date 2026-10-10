"""Takvim tamlığı ve kimlik testleri için SENTETİK yardımcılar (S3-GATE-02).

Turlu (her turda her takım bir kez oynar) sentetik lig sezonları ve bunların openfootball biçimli takvim dosyaları
üretir. Takım adları, skorlar ve tarihler uydurmadır; gerçek maç verisi değildir.
"""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd

from bahis_tahmin.data.parsers import MATCH_COLUMNS


def circle_rounds(teams: list[str], legs: int = 2) -> list[list[tuple[str, str]]]:
    """Daire yöntemiyle ``legs`` devreli lig: her tur katılımcıların tam eşleşmesi (çift sayıda takım)."""
    n = len(teams)
    assert n % 2 == 0
    idx = list(range(n))
    first = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = idx[i], idx[n - 1 - i]
            pairs.append((teams[a], teams[b]) if (r + i) % 2 == 0 else (teams[b], teams[a]))
        first.append(pairs)
        idx = [idx[0]] + [idx[-1]] + idx[1:-1]
    out = []
    for leg in range(legs):
        for pairs in first:
            out.append([(h, a) if leg % 2 == 0 else (a, h) for h, a in pairs])
    return out


def season_rows(teams: list[str], start: dt.date, season: str, league: str = "T1", legs: int = 2, seed: int = 0,
                rounds: list | None = None, first_round: int = 1) -> list[dict]:
    """Haftalık turlarla bir sezonun maç satırları (``round`` dahil)."""
    rng = np.random.default_rng(seed)
    rows = []
    for r, pairs in enumerate(rounds if rounds is not None else circle_rounds(teams, legs)):
        d = start + dt.timedelta(days=7 * r)
        for h, a in pairs:
            hg, ag = int(rng.poisson(1.4)), int(rng.poisson(1.1))
            rows.append({"league": league, "season": season, "date": pd.Timestamp(d), "time": "19:00", "home": h,
                         "away": a, "fthg": hg, "ftag": ag, "hthg": float(min(hg, rng.integers(0, 2))),
                         "htag": float(min(ag, rng.integers(0, 2))), "source": "sentetik",
                         "round": f"Matchday {r + first_round}"})
    return rows


def store_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for c in MATCH_COLUMNS:
        if c not in df:
            df[c] = np.nan
    return df[MATCH_COLUMNS].sort_values("date", kind="mergesort").reset_index(drop=True)


def openfootball_bytes(rows: list[dict], played_before: dt.date | None = None, name_map: dict | None = None) -> bytes:
    """openfootball biçimli sezon dosyası. ``played_before``: bu tarihten önceki maçlar skorlu (tamamlandı)."""
    nm = name_map or {}
    ms = []
    for r in rows:
        m = {"round": r.get("round"), "date": str(pd.Timestamp(r["date"]).date()), "time": "19:00",
             "team1": nm.get(r["home"], r["home"]), "team2": nm.get(r["away"], r["away"])}
        if played_before is None or pd.Timestamp(r["date"]).date() < played_before:
            m["score"] = {"ft": [int(r["fthg"]), int(r["ftag"])]}
        for k in ("id", "status"):
            if k in r:
                m[k] = r[k]
        ms.append(m)
    return json.dumps({"name": "Sentetik Lig", "matches": ms}, ensure_ascii=False).encode("utf-8")

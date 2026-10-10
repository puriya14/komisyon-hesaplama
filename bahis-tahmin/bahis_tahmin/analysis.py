"""Puan durumu, takım formu ve karşılıklı maç (H2H) analizleri."""

from __future__ import annotations

import pandas as pd


def standings(matches: pd.DataFrame, league: str, season: str | None = None) -> pd.DataFrame:
    m = matches[matches["league"] == league]
    if m.empty:
        return pd.DataFrame()
    season = season or sorted(m["season"].unique())[-1]
    m = m[m["season"] == season]
    rows: dict[str, dict] = {}

    def row(t):
        return rows.setdefault(t, {"Takım": t, "O": 0, "G": 0, "B": 0, "M": 0, "AG": 0, "YG": 0, "P": 0, "_form": []})

    for r in m.sort_values("date").itertuples(index=False):
        h, a = row(r.home), row(r.away)
        for t, gf, ga in ((h, r.fthg, r.ftag), (a, r.ftag, r.fthg)):
            t["O"] += 1
            t["AG"] += gf
            t["YG"] += ga
            if gf > ga:
                t["G"] += 1
                t["P"] += 3
                t["_form"].append("G")
            elif gf == ga:
                t["B"] += 1
                t["P"] += 1
                t["_form"].append("B")
            else:
                t["M"] += 1
                t["_form"].append("M")
    df = pd.DataFrame(rows.values())
    df["AV"] = df["AG"] - df["YG"]
    df["Form"] = df["_form"].apply(lambda f: "".join(f[-5:]))
    df = df.drop(columns="_form").sort_values(["P", "AV", "AG"], ascending=False).reset_index(drop=True)
    df.insert(0, "#", range(1, len(df) + 1))
    return df[["#", "Takım", "O", "G", "B", "M", "AG", "YG", "AV", "P", "Form"]]


def team_matches(matches: pd.DataFrame, team: str, n: int = 10, league: str | None = None) -> pd.DataFrame:
    m = matches[(matches["home"] == team) | (matches["away"] == team)]
    if league:
        m = m[m["league"] == league]
    m = m.sort_values("date", ascending=False).head(n)
    out = []
    for r in m.itertuples(index=False):
        home = r.home == team
        gf, ga = (r.fthg, r.ftag) if home else (r.ftag, r.fthg)
        res = "G" if gf > ga else "B" if gf == ga else "M"
        out.append({
            "Tarih": r.date, "Rakip": r.away if home else r.home, "Yer": "İç" if home else "Dış",
            "Skor": f"{r.fthg}-{r.ftag}", "Sonuç": res,
        })
    return pd.DataFrame(out)


def head_to_head(matches: pd.DataFrame, home: str, away: str, n: int = 10) -> pd.DataFrame:
    m = matches[((matches["home"] == home) & (matches["away"] == away)) | ((matches["home"] == away) & (matches["away"] == home))]
    m = m.sort_values("date", ascending=False).head(n)
    return pd.DataFrame([
        {"Tarih": r.date, "Ev": r.home, "Skor": f"{r.fthg}-{r.ftag}", "Deplasman": r.away}
        for r in m.itertuples(index=False)
    ])

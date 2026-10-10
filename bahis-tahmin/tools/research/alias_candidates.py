"""Takım adı kopukluğu adayları (gözden geçirme için; otomatik eşleme YAPMAZ).

Kullanım: python -I alias_candidates.py <matches.pkl> [cikti.csv]
Ölçüt: aynı ülke, zaman aralıkları çakışmayan (ya da tek maç kadar değen) ve normalize ad benzerliği yüksek
çiftler. Sonuç elle incelenir; onaylananlar bahis_tahmin/sequences/aliases.py içine açıkça yazılır.
"""
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd

from bahis_tahmin.data.leagues import LEAGUES


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = re.sub(r"\b(fc|cf|sc|ac|afc|jc|cd|ud|sd|fk|sk|bk|club|calcio|1|united|utd|city|town)\b", " ", s)
    return re.sub(r"\s+", "", s)


m = pd.read_pickle(sys.argv[1])
rows = []
for side in ("home", "away"):
    rows.append(m[["league", "date", side]].rename(columns={side: "team"}))
tm = pd.concat(rows)
tm["country"] = tm["league"].map(lambda c: LEAGUES[c].country if c in LEAGUES else c)
span = tm.groupby(["country", "team"]).agg(first=("date", "min"), last=("date", "max"), n=("date", "size"),
                                           leagues=("league", lambda s: ",".join(sorted(set(s))))).reset_index()
out = []
for country, g in span.groupby("country"):
    g = g.reset_index(drop=True)
    for i in range(len(g)):
        for j in range(len(g)):
            if i == j:
                continue
            a, b = g.loc[i], g.loc[j]
            if not (a["last"] < b["first"]):
                continue  # a önce, b sonra; çakışma yok
            na, nb = norm(a["team"]), norm(b["team"])
            if not na or not nb:
                continue
            sim = SequenceMatcher(None, na, nb).ratio()
            pref = na.startswith(nb) or nb.startswith(na)
            if sim >= 0.8 or (pref and min(len(na), len(nb)) >= 4):
                gap = (b["first"] - a["last"]).days
                out.append({"country": country, "eski": a["team"], "yeni": b["team"], "eski_son": a["last"].date(),
                            "yeni_ilk": b["first"].date(), "ara_gun": gap, "benzerlik": round(sim, 3), "onek": pref,
                            "eski_lig": a["leagues"], "yeni_lig": b["leagues"], "eski_n": a["n"], "yeni_n": b["n"]})
res = pd.DataFrame(out).sort_values(["country", "ara_gun"])
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 500)
print(res.to_string(index=False))
if len(sys.argv) > 2:
    res.to_csv(sys.argv[2], index=False)

"""Yapısal kontrol (sonuç DEĞERİ kullanılmaz): gerçek openfootball fikstürleri (10 gün) eşlenip
sequences.prematch.append_fixtures ile maç tablosuna eklenebiliyor mu ve her takımın veride kayıtlı SON maçı ile
fikstür tarihi arasında kaç gün var? Atom/örüntü/olasılık HESAPLANMAZ.

Kullanım: python -I -B fikstur_ekleme_yapisal.py <kod_kok> <maclar.csv.gz> <cikti_klasoru> <lig=dosya.json> [...]
"""

import json
import sys
from pathlib import Path

kod, csv_path, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
sys.path.insert(0, kod)
import pandas as pd  # noqa: E402

from bahis_tahmin.data.parsers import parse_openfootball  # noqa: E402
from bahis_tahmin.data.store import DataStore  # noqa: E402
from bahis_tahmin.data.teams import match_team  # noqa: E402
from bahis_tahmin.sequences.prematch import FIXTURE_SOURCE, append_fixtures  # noqa: E402

TODAY = pd.Timestamp("2026-10-10")
m = pd.read_csv(csv_path, parse_dates=["date"], low_memory=False)
R = {}
for code, path in (a.split("=", 1) for a in sys.argv[4:]):
    of = parse_openfootball(Path(path).read_bytes(), code)
    of = of[(of["date"] >= TODAY) & (of["date"] <= TODAY + pd.Timedelta(days=10))].copy()
    known = DataStore._recent_teams(m, code)
    of["home"] = [match_team(t, known) for t in of["home"]]
    of["away"] = [match_team(t, known) for t in of["away"]]
    of = of.dropna(subset=["home", "away"])
    lg = m[m["league"] == code]
    allm = append_fixtures(lg, of)
    added = allm[allm["source"] == FIXTURE_SOURCE]
    last_by_team = pd.concat([lg[["date", "home"]].rename(columns={"home": "t"}),
                              lg[["date", "away"]].rename(columns={"away": "t"})]).groupby("t")["date"].max()
    gaps = []
    for r in added.itertuples(index=False):
        for t in (r.home, r.away):
            gaps.append(int((pd.Timestamp(r.date) - last_by_team[t]).days))
    R[code] = {"eslenmis_fikstur_10_gun": int(len(of)), "append_fixtures_eklenen": int(len(added)),
               "sezon_etiketi": sorted(set(map(str, added["season"]))),
               "son_kayitli_mac_ile_fikstur_arasi_gun_min_medyan_max": [min(gaps), float(pd.Series(gaps).median()),
                                                                        max(gaps)] if gaps else None,
               "psv_fiksturleri": added[(added["home"] == "PSV Eindhoven") | (added["away"] == "PSV Eindhoven")][
                   ["date", "home", "away", "time"]].astype(str).to_dict("records")}
(out / "fikstur_ekleme_yapisal.json").write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(R, ensure_ascii=False, indent=1))

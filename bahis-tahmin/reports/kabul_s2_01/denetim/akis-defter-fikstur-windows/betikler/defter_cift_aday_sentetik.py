"""YALNIZCA SENTETİK: aynı VALUE_CANDIDATE kararı iki kez kaydedilirse Ledger.summary() sanal bahsi iki kez sayar mı?

Kullanım: python -I defter_cift_aday_sentetik.py <kod_kok> <cikti_klasoru>
"""

import datetime as dt
import json
import sys
from pathlib import Path

kod, out_dir = sys.argv[1], Path(sys.argv[2])
sys.path.insert(0, kod)

import pandas as pd  # noqa: E402

from bahis_tahmin.goals import service as S  # noqa: E402
from bahis_tahmin.goals.engine import GoalEngine  # noqa: E402
from bahis_tahmin.goals.ledger import Ledger  # noqa: E402
from bahis_tahmin.goals.markets import MARKETS  # noqa: E402
from bahis_tahmin.goals.value import OddsQuote  # noqa: E402
from bahis_tahmin.selftest import synthetic_matches  # noqa: E402
from bahis_tahmin.timeutil import now_utc  # noqa: E402

m = synthetic_matches(n_seasons=6, n_teams=14, league="N1", seed=11, start_year=2021, half_time=True)
ls = m[m["season"] == m["season"].iloc[-1]]
fx_day = next(d for d in sorted(ls["date"].unique()) if pd.Timestamp(d) > pd.Timestamp("2026-10-12"))
fx = ls[ls["date"] == fx_day][["league", "date", "time", "home", "away"]].assign(source="sentetik-fikstur")
eng = GoalEngine()
eng.train(m[m["date"] < fx_day])
preds = eng.predict_fixtures(fx)
eng.validated = {k: True for k in eng.validated}  # YALNIZCA bu deney: doğrulanmış varsay
now = now_utc()
qt = now - dt.timedelta(minutes=1)
db = out_dir / "sentetik_defter_cift_aday.sqlite"
if db.exists():
    db.unlink()
led = Ledger(db)
found = None
for p in preds:
    for key in S.SELECTIONS:
        lo, hi = p.interval(key)
        if lo is None or hi - lo > 0.25 or lo <= 0:
            continue
        odds = round(1.08 / lo, 2)  # p_safe ile EV ≈ %8
        if p.p(key) * odds - 1 > 0.30:
            continue
        mk = MARKETS[key]
        led.add_odds([OddsQuote(p.event_id, key, mk.period, mk.line, mk.selection, "manuel", "deneme", odds, qt, qt)])
        decs = S.decisions_for(p, eng, led, now)
        if any(d.status == "VALUE_CANDIDATE" for d in decs):
            found = (p, decs)
            break
    if found:
        break
out = {}
if found:
    p, decs = found
    S.record_decisions(led, p, decs, eng)
    out["bir_kez"] = led.summary()
    S.record_decisions(led, p, decs, eng)
    out["iki_kez"] = led.summary()
    out["aday"] = [(d.market_key, d.status, d.odds, d.ev_safe) for d in decs if d.status == "VALUE_CANDIDATE"]
else:
    out["not"] = "aday üretilemedi"
led.close()
(out_dir / "defter_cift_aday_sentetik.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                         encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))

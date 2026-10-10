"""PSV mac sayisinin sezonlara dagilimi (yalnizca fikstur sayimi; skor/sonuc kullanilmaz)."""
import sys
import pandas as pd
d = pd.read_csv(sys.argv[1], parse_dates=["date"], usecols=["league", "season", "date", "home", "away"])
psv = d[(d.home == "PSV Eindhoven") | (d.away == "PSV Eindhoven")]
n1 = d[d.league == "N1"]
t = psv.groupby("season").agg(psv_mac=("date", "size"), psv_ev=("home", lambda s: (s == "PSV Eindhoven").sum()),
                              ilk=("date", "min"), son=("date", "max"))
t["n1_mac_toplam"] = n1.groupby("season").size()
t["n1_takim"] = n1.groupby("season").apply(lambda g: len(set(g.home) | set(g.away)))
t["ilk"] = t["ilk"].dt.date; t["son"] = t["son"].dt.date
t.to_csv(sys.argv[2])
print(t.to_string()); print("toplam", int(t.psv_mac.sum()))

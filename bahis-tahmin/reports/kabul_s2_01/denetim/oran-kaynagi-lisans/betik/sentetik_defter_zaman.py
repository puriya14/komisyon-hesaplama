"""SENTETİK: tarihsel (maçtan aylar önce/sonra) zaman damgalı bir oranın karar motorunda reddedildiğini ve
1X2 pazarlarının karar motoruna açık olmadığını gösterir. Gerçek maç verisi kullanılmaz; defter geçici klasörde."""
import datetime as dt
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from bahis_tahmin.goals.decision import Assessment, decide  # noqa: E402
from bahis_tahmin.goals.ledger import Ledger  # noqa: E402
from bahis_tahmin.goals.markets import MARKETS  # noqa: E402
from bahis_tahmin.goals.value import OddsQuote  # noqa: E402

U = dt.timezone.utc
print("birincil (karar motoruna açık) pazarlar:", sorted(k for k, m in MARKETS.items() if m.primary))
print("1X2 benzeri pazar anahtarları:", sorted(k for k in MARKETS if k.startswith(("FT_1", "FT_X", "FT_2", "1X2", "MS_"))))
kick = dt.datetime(2026, 10, 17, 14, 0, tzinfo=U)
dec_t = dt.datetime(2026, 10, 17, 10, 0, tzinfo=U)
key = "FT_OVER_3_5"
m = MARKETS[key]
ev = "SENTETIK|2026-10-17|A|B"
cases = {
    "tarihsel_gecmis_zaman (CSV benzeri, 2025)": dt.datetime(2025, 8, 16, 12, 0, tzinfo=U),
    "karar_anindan_sonra": dt.datetime(2026, 10, 17, 11, 0, tzinfo=U),
    "taze (30 dk once)": dt.datetime(2026, 10, 17, 9, 30, tzinfo=U),
}
with tempfile.TemporaryDirectory() as td:
    led = Ledger(Path(td) / "sentetik.sqlite")
    for name, qa in cases.items():
        q = OddsQuote(ev + name, key, m.period, m.line, m.selection, "sentetik", "sentetik", 2.10, qa, qa)
        led.add_odds([q])
        got = led.latest_quote(ev + name, key, dec_t)
        a = Assessment(ev + name, "T1", "A", "B", key, p=0.55, p_low=0.52, p_high=0.58, model_validated=True,
                       quote=got, kickoff=kick)
        d = decide(a, dec_t)
        print(f"{name}: latest_quote={'yok' if got is None else got.quoted_at.isoformat()} -> {d.status}")
    led.close()

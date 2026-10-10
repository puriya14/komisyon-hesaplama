"""YALNIZCA SENTETİK KAYIT: Ledger zincirinin sınırları.
(1) Sondan kayıt silme (tetikleyici düşürülerek) verify_chain ile yakalanır mı?
(2) Aynı dosyaya iki bağlantı (iki uygulama örneği) sırayla yazarsa zincir çatallanır mı?

Kullanım: python -I defter_butunluk_sentetik.py <kod_kok> <cikti_klasoru>
"""

import datetime as dt
import json
import sys
from pathlib import Path

kod, out = sys.argv[1], Path(sys.argv[2])
sys.path.insert(0, kod)
from bahis_tahmin.goals.ledger import Ledger  # noqa: E402


def rec(i):
    return {"event_id": f"N1|2026-10-18|T{i}|U{i}", "market_key": "FT_OVER_3_5",
            "decision_time": dt.datetime.now(dt.timezone.utc).isoformat(), "model_version": "m", "feature_version": "f",
            "data_cutoff": "2026-09-03", "p": 0.3, "decision_status": "ODDS_UNAVAILABLE", "reasons": [],
            "stake_units": 0.0, "strategy_version": "s"}


R = {}
p1 = out / "butunluk_kuyruk.sqlite"
p1.unlink(missing_ok=True)
led = Ledger(p1)
for i in range(5):
    led.record_prediction(rec(i))
c = led.conn
c.execute("DROP TRIGGER predictions_no_delete")
c.execute("DELETE FROM predictions WHERE seq = (SELECT MAX(seq) FROM predictions)")
c.commit()
R["kuyruk_silme_sonrasi"] = {"kayit": len(led.predictions()), "verify_chain": led.verify_chain()}
led.close()

p2 = out / "butunluk_iki_yazar.sqlite"
p2.unlink(missing_ok=True)
a, b = Ledger(p2), Ledger(p2)
a.record_prediction(rec(0))
stale_prev = a._last_hash("predictions")  # A son özeti okur
orig = a._last_hash
b.record_prediction(rec(1))  # B araya yazar
a._last_hash = lambda table: stale_prev  # A, okuduğu eski özetle yazar (yarış durumunun benzetimi)
a.record_prediction(rec(2))
a._last_hash = orig
R["iki_yazar"] = {"kayit": len(a.predictions()), "verify_chain": a.verify_chain()}
a.close()
b.close()
(out / "defter_butunluk_sentetik.json").write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(R, ensure_ascii=False, indent=1))

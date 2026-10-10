"""Türkçe karakter + boşluk içeren uygulama klasöründe dosya yazma/okuma (Linux'ta; Windows yerine geçmez).

BAHIS_TAHMIN_HOME, çağıran tarafından ayarlanır. Pickle/joblib YÜKLENMEZ (yalnızca yazma denenir).
Kullanım: python -I yol_kontrol.py <kod_kok> <cikti_json>
"""

import datetime as dt
import json
import os
import sys
from pathlib import Path

kod, out = sys.argv[1], Path(sys.argv[2])
sys.path.insert(0, kod)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

R = {"BAHIS_TAHMIN_HOME": os.environ.get("BAHIS_TAHMIN_HOME")}
from bahis_tahmin.config import Settings, app_home  # noqa: E402

home = app_home()
R["app_home"] = str(home)
R["app_home_var"] = home.exists()

s = Settings.load()
s.source_consent = {"openfootball": "2026-10-10T12:00:00"}
s.currency = "TL ₺ ğüşıöç"
s.save()
R["settings_gidis_donus"] = Settings.load().currency == "TL ₺ ğüşıöç"

from bahis_tahmin.goals.ledger import Ledger  # noqa: E402

led = Ledger(home / "gol_pazarlari.sqlite")
pid = led.record_prediction({"event_id": "N1|2026-10-18|PSV Eindhoven|Go Ahead Eagles", "market_key": "FT_OVER_3_5",
                             "decision_time": dt.datetime.now(dt.timezone.utc).isoformat(), "model_version": "x",
                             "feature_version": "y", "data_cutoff": "2026-09-03", "p": 0.3,
                             "decision_status": "ODDS_UNAVAILABLE", "reasons": ["deneme ğüşİ"], "stake_units": 0.0,
                             "strategy_version": "z"})
R["ledger_kayit_ve_zincir"] = [bool(pid), led.verify_chain()]
led.close()

from bahis_tahmin.sequences.official import OfficialDecision, OfficialRegistry  # noqa: E402

reg = OfficialRegistry(home / "dizi_arastirma" / "resmi_kararlar.json")
reg.append(OfficialDecision("k1", "deneme kaynağı", dt.date(2026, 10, 1), ["N1|2026-09-01|A|B"], "hükmen", "kesin"))
R["resmi_kayit_yeniden_okuma"] = len(OfficialRegistry(home / "dizi_arastirma" / "resmi_kararlar.json"))

from bahis_tahmin.sequences.research import append_experiment  # noqa: E402

append_experiment({"asama": "yol-denemesi ğüşİ"}, home / "dizi_arastirma" / "deneyler.jsonl")
R["deneyler_jsonl_okuma"] = (home / "dizi_arastirma" / "deneyler.jsonl").read_text(encoding="utf-8").count("\n")

from bahis_tahmin.sequences.research_ledger import ResearchLedger  # noqa: E402

rl = ResearchLedger(home / "dizi_arastirma")
R["arastirma_defteri_yolu"] = str(rl.path)
rl.close()

from bahis_tahmin.models.artifacts import save_artifact  # noqa: E402

save_artifact({"a": 1}, home / "deneme_artefakt.joblib", "deneme", 1)  # yalnızca yazma; YÜKLENMEZ
R["artefakt_yazildi"] = (home / "deneme_artefakt.joblib").exists() and (home / "deneme_artefakt.manifest.json").exists()

from bahis_tahmin.ui.app import setup_logging  # noqa: E402

lp = setup_logging()
import logging  # noqa: E402

logging.getLogger("deneme").info("günlük satırı ğüşİ")
for h in logging.getLogger().handlers:
    h.flush()
R["gunluk"] = [str(lp), "günlük satırı ğüşİ" in lp.read_text(encoding="utf-8")]
R["olusan_dosyalar"] = sorted(str(p.relative_to(home)) for p in home.rglob("*"))
out.write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(json.dumps(R, ensure_ascii=False, indent=1, default=str))

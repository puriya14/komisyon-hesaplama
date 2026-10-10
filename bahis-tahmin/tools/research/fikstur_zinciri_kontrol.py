"""Gerçek fikstür zinciri denetimi (izole ana klasörde): kaynak → takım eşleme → zaman doğrulama → uygunluk →
A/B/C kaydı → değişmez defter.

* Fikstür kaynağı yalnızca openfootball (CC0); en fazla lig sayısı kadar ağ isteği. football-data.co.uk kullanılmaz.
* Geçmiş veri ve model dosyası yalnızca bu görevde üretilmiş, kaynağı bilinen dosyalardan okunur (CSV + kendi
  eğittiğimiz motor). Uygulamanın gerçek ana klasörüne dokunulmaz; yazma yalnızca ``--ev`` altındadır.
* Veri güncel değilse tahmin ÜRETİLMEZ; kayıtlar olasılıksız ``TAHMIN_YOK`` + gerekçe olarak yazılır. Uygunluk ortak
  kontrolden gelir (``bahis_tahmin.eligibility``, protokol ``ileriye-donuk-olcum-v2``; S3-GATE-01). Motorun teknik
  olarak sonlu olasılık üretip üretmediği ayrıca sayılır; değerler rapora veya deftere yazılmaz.

Kullanım: python -I fikstur_zinciri_kontrol.py --ev <izole_klasör> --motor <goal_engine.joblib> --maclar <csv.gz>
          --rapor <json> [--gun 10] [--uygula]
"""
import argparse
import datetime as dt
import json
import shutil
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from bahis_tahmin.data.leagues import LEAGUES, openfootball_season  # noqa: E402
from bahis_tahmin.data.sources import Downloader  # noqa: E402
from bahis_tahmin.data.store import DataStore, UpdateReport  # noqa: E402
from bahis_tahmin.eligibility import build_context  # noqa: E402
from bahis_tahmin.goals import forecast_log as F  # noqa: E402
from bahis_tahmin.goals.engine import GoalEngine  # noqa: E402
from bahis_tahmin.goals.ledger import Ledger  # noqa: E402
from bahis_tahmin.timeutil import kickoff_utc  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ev", required=True)
    ap.add_argument("--motor", required=True)
    ap.add_argument("--maclar", required=True)
    ap.add_argument("--rapor", required=True)
    ap.add_argument("--gun", type=int, default=10)
    ap.add_argument("--uygula", action="store_true")
    a = ap.parse_args()
    home = Path(a.ev)
    home.mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.timezone.utc)
    today = started.date()

    m = pd.read_csv(a.maclar, parse_dates=["date"], low_memory=False)
    m["time"] = m["time"].fillna("")
    st = DataStore(home)
    st.matches = m
    eng_path = home / "goal_engine.joblib"
    if not eng_path.exists():
        shutil.copy2(a.motor, eng_path)
        man = Path(a.motor).with_suffix(".manifest.json")
        if man.exists():
            shutil.copy2(man, eng_path.with_suffix(".manifest.json"))
    eng, err = GoalEngine.load(eng_path)

    leagues = [c for c, lg in LEAGUES.items() if lg.openfootball and c in set(m["league"])]
    dl = Downloader(home / "raw")
    rep = UpdateReport()
    fx = st._update_fixtures(dl, leagues, m, today, a.gun, rep, False, {"openfootball"})
    missing, files = {}, {}
    for code in leagues:
        lg = LEAGUES[code]
        p = home / "raw" / "openfootball" / openfootball_season(today, lg.calendar_year) / f"{lg.openfootball}.json"
        files[code] = p.exists()
        if p.exists():
            n = F.missing_played_openfootball(p.read_bytes(), m, code)
            if n is not None:
                missing[code] = n
    ko = [kickoff_utc(r.date, r.time or "", r.source or "", LEAGUES[r.league].country) for r in fx.itertuples()]
    rights = {"openfootball": "CC0 (openfootball/football.json)"}
    led = Ledger(home / "gol_pazarlari.sqlite") if a.uygula else None
    st.meta["eslesmeyen_fikstur"] = list(st._last_unmatched)
    ctx = build_context(st, eng, {}, today=today)  # yalnızca onay gerektirmeyen kaynaklar (openfootball, CC0)
    recs = F.build_forecast_records(eng, fx, m, ledger=led, ctx=ctx, unmatched=st.unmatched_fixtures,
                                    source_rights=rights)
    reasons = {}
    for r in recs:
        k = r["decision_status"] if r["decision_status"] == F.STATUS_FORECAST else r["reasons"][0]
        reasons[k] = reasons.get(k, 0) + 1
    # Teknik yol (kayıt değil): motor bu gerçek fikstürler için sonlu olasılık üretebiliyor mu?
    finite = 0
    if eng is not None and not fx.empty:
        for pr in eng.predict_fixtures(fx, with_interval=False):
            vals = [pr.p(k) for k in F.PRIMARY_YES]
            finite += all(isinstance(v, float) and 0.0 < v < 1.0 for v in vals)
    write = None
    chain = None
    if a.uygula:
        write = F.record_forecasts(led, recs)
        chain = led.verify_chain()
        led.close()
    last = m.groupby("league")["date"].max().dt.date.astype(str).to_dict()
    out = {
        "baslangic_utc": started.isoformat(timespec="seconds"),
        "bugun": str(today), "pencere_gun": a.gun, "fikstur_kaynagi": "openfootball (CC0)",
        "ag_istegi": {"indirilen": rep.downloaded, "onbellek": rep.from_cache,
                      "dosya_bulundu": {k: v for k, v in files.items()}},
        "eslesme_uyarilari": rep.warnings,
        "fikstur_sayisi": int(len(fx)), "lig_bazinda_fikstur": fx["league"].value_counts().to_dict() if len(fx) else {},
        "baslama_saati_bilinen": int(sum(k is not None for k in ko)),
        "motor": {"yuklendi": eng is not None, "hata": err, "kohort": F.model_cohort(eng) if eng else None},
        "veri_son_tarih_lig": last, "eksik_oynanmis_mac_lig": missing,
        "protokol": {"surum": F.ACTIVE_PROTOCOL, "govde_sha256": F.protocol_sha256(F.PROTOCOL_V2_BODY),
                     "dondurma_zamani_utc": F.PROTOCOL_V2_FROZEN["dondurma_zamani_utc"],
                     "veri_uygunluk_politikasi": F.PROTOCOL_V2_BODY["veri_uygunluk_politikasi"]},
        "eksik_oynanmis_mac_lig_v1_bilgi": "v1 kuralı yalnızca bilgi; uygunluk kararını vermez",
        "kayit_adaylari": len(recs), "neden_dagilimi": reasons,
        "teknik_yol_sonlu_olasilik_mac": finite,
        "teknik_yol_notu": "Olasılık değerleri rapora/deftere yazılmadı; veri güncel değilse tahmin sayılmaz.",
        "defter_yazimi": {k: v for k, v in (write or {}).items() if k != "kimlikler"} if write else "kuru çalıştırma",
        "zincir": chain,
        "ornek_kayit": {k: v for k, v in recs[0].items() if k not in ("protokol_sha256",)} if recs else None,
    }
    Path(a.rapor).parent.mkdir(parents=True, exist_ok=True)
    Path(a.rapor).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("fikstur_sayisi", "lig_bazinda_fikstur", "eksik_oynanmis_mac_lig",
                                          "neden_dagilimi", "teknik_yol_sonlu_olasilik_mac", "defter_yazimi",
                                          "zincir", "ag_istegi")}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

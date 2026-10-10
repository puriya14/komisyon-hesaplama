"""YALNIZCA SENTETİK VERİ: tahmin kaydı (Ledger) akışı ve veri tazeliği (data cutoff) davranışı.

Temel (01b7e9f) kod dışa aktarılmış kopyadan içe alınır. Pickle/joblib dosyası YÜKLENMEZ (yalnızca bellek içi nesneler).
Çıktı: <cikti>/defter_tazelik_sentetik.json ve konsol.

Kullanım: python -I defter_tazelik_sentetik.py <kod_kok> <cikti_klasoru>
"""

import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path

kod, out_dir = sys.argv[1], Path(sys.argv[2])
sys.path.insert(0, kod)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from bahis_tahmin.goals import service as S  # noqa: E402
from bahis_tahmin.goals.engine import GoalEngine  # noqa: E402
from bahis_tahmin.goals.ledger import Ledger  # noqa: E402
from bahis_tahmin.goals.markets import MARKETS  # noqa: E402
from bahis_tahmin.goals.value import OddsQuote  # noqa: E402
from bahis_tahmin.selftest import synthetic_matches  # noqa: E402
from bahis_tahmin.timeutil import now_utc  # noqa: E402

out_dir.mkdir(parents=True, exist_ok=True)
R: dict = {"not": "Tüm maçlar sentetiktir (bahis_tahmin.selftest.synthetic_matches); gerçek sonuç kullanılmadı."}
T0 = time.time()

# ---------------------------------------------------------------- veri: son sezon 2026/27 (2026-08-10'da başlar)
m = synthetic_matches(n_seasons=6, n_teams=14, league="N1", seed=11, start_year=2021, half_time=True)
last_season = m["season"].iloc[-1]
ls = m[m["season"] == last_season].copy()
days = sorted(ls["date"].unique())
cut = pd.Timestamp(days[3])  # 4. tur sonrası veri kesimi (ör. 2026-08-31)
fx_day = next(d for d in days if pd.Timestamp(d) > pd.Timestamp("2026-10-12"))  # bugünden sonraki ilk tur
fixtures_full = ls[ls["date"] == fx_day].copy()
stale = m[m["date"] <= cut].copy()
fresh = m[m["date"] < fx_day].copy()
fx = fixtures_full[["league", "date", "time", "home", "away"]].copy()
fx["source"] = "sentetik-fikstur"
R["veri"] = {"toplam": int(len(m)), "kesim_eski": str(cut.date()), "fikstur_gunu": str(pd.Timestamp(fx_day).date()),
             "eski_veri_mac": int(len(stale)), "guncel_veri_mac": int(len(fresh)),
             "kesim_ile_fikstur_arasi_kayitsiz_mac": int(len(fresh) - len(stale)), "fikstur_mac": int(len(fx))}

# ---------------------------------------------------------------- iki motor: eski kesim / güncel kesim
eng_old, eng_new = GoalEngine(), GoalEngine()
eng_old.train(stale)
eng_new.train(fresh)
p_old = eng_old.predict_fixtures(fx)
p_new = eng_new.predict_fixtures(fx)
rows = []
for a, b in zip(p_old, p_new):
    rows.append({"mac": f"{a.home}-{a.away}", "A_eski": a.probs["A"], "A_guncel": b.probs["A"],
                 "B_eski": a.probs["B"], "B_guncel": b.probs["B"], "C_eski": a.probs["C"], "C_guncel": b.probs["C"],
                 "notlar_eski": a.data_notes, "notlar_guncel": b.data_notes})
df = pd.DataFrame(rows)
for s in "ABC":
    df[f"fark_{s}"] = (df[f"{s}_eski"] - df[f"{s}_guncel"]).abs()
# özellik düzeyi: dinlenme (rest) ve n365, eski motorun durumundan
st_old = eng_old.states["N1"].snapshot_for(pd.Timestamp(fx_day))
st_new = eng_new.states["N1"].snapshot_for(pd.Timestamp(fx_day))
day = int((pd.Timestamp(fx_day) - pd.Timestamp("2000-01-01")).days)
r0 = fx.iloc[0]
f_old = st_old.features(r0.home, r0.away, day)
f_new = st_new.features(r0.home, r0.away, day)
R["tazelik_gol_motoru"] = {
    "eski_motor_data_cutoff": eng_old.data_cutoff, "guncel_motor_data_cutoff": eng_new.data_cutoff,
    "notlarda_kesim_uyarisi_var_mi": bool(any("kesim" in n.lower() or "eski" in n.lower() or "güncel" in n.lower()
                                              for ns in df["notlar_eski"] for n in ns)),
    "eski_notlar_ornek": df["notlar_eski"].head(3).tolist(),
    "max_mutlak_fark": {s: float(df[f"fark_{s}"].max()) for s in "ABC"},
    "ortalama_mutlak_fark": {s: float(df[f"fark_{s}"].mean()) for s in "ABC"},
    "ornek_ozellik_eski": {k: f_old[k] for k in ("h_rest", "a_rest", "h_n365", "a_n365", "season_n")},
    "ornek_ozellik_guncel": {k: f_new[k] for k in ("h_rest", "a_rest", "h_n365", "a_n365", "season_n")},
}
df.to_csv(out_dir / "tazelik_gol_motoru_sentetik.csv", index=False)

# ---------------------------------------------------------------- tanınmayan lig: sessizce atlanır mı?
fx_bad = fx.head(1).copy()
fx_bad["league"] = "XX"
R["tanimsiz_lig_fiksturu"] = {"girdi": 1, "tahmin": len(eng_old.predict_fixtures(fx_bad)),
                              "kayit_veya_neden": "yok (predict_fixtures 'continue' ile atlar)"}

# ---------------------------------------------------------------- defter akışı
db = out_dir / "sentetik_defter.sqlite"
for f in (db,):
    if f.exists():
        f.unlink()
led = Ledger(db)
now = now_utc()
pred = p_old[0]
decs = S.decisions_for(pred, eng_old, led, now)
R["aday_yokken_kararlar"] = [{"pazar": d.market_key, "durum": d.status, "neden": d.reasons[:2]} for d in decs]
ids = S.record_decisions(led, pred, decs, eng_old)
rec = led.predictions()[0]
R["kaydedilen_alanlar"] = sorted(rec.keys())
R["kaydedilen_ornek"] = {k: rec[k] for k in ("event_id", "market_key", "decision_time", "created_at", "kickoff",
                                              "data_cutoff", "model_version", "feature_version", "p", "p_low",
                                              "odds", "decision_status", "stake_units", "policy_version")}
R["p_high_kaydedildi_mi"] = "p_high" in rec
R["oran_kimligi_kaydedildi_mi"] = any(k in rec for k in ("quoted_at", "fetched_at", "bookmaker", "provider"))

# aynı kararları ikinci kez kaydet → çoğalır mı?
S.record_decisions(led, pred, decs, eng_old)
R["ayni_kararlar_iki_kez"] = {"kayit_sayisi": len(led.predictions()), "beklenen_tekil": len(decs)}

# avantaj adayı: doğrulanmış varsayıp (yalnızca bu deneyde) yüksek oran girilir; iki kez kaydedilirse özet ikiye katlanır mı
eng_val = eng_old
saved_validated = dict(eng_val.validated)
eng_val.validated = {k: True for k in eng_val.validated}
pred2 = p_old[1]
qt = now - dt.timedelta(minutes=1)
quotes = []
for key in S.SELECTIONS:
    mk = MARKETS[key]
    quotes.append(OddsQuote(pred2.event_id, key, mk.period, mk.line, mk.selection, "manuel", "deneme", 50.0, qt, qt))
led.add_odds(quotes)
d2 = S.decisions_for(pred2, eng_val, led, now)
R["aday_deneme_durumlari"] = [d.status for d in d2]
S.record_decisions(led, pred2, d2, eng_val)
s1 = led.summary()
S.record_decisions(led, pred2, d2, eng_val)
s2 = led.summary()
R["aday_iki_kez_kayit_ozet"] = {"bir_kez": s1, "iki_kez": s2}
eng_val.validated = saved_validated

# başlama saatinden SONRA kayıt: Ledger kabul ediyor mu? (geçmiş tarihli sentetik maç, karar zamanı maçtan önce)
past = m[m["date"] < cut].tail(1).copy()
pp = eng_old.predict_fixtures(past[["league", "date", "time", "home", "away"]].assign(source="sentetik"))[0]
old_dt = pp.kickoff_utc - dt.timedelta(hours=2)
d_past = S.decisions_for(pp, eng_old, led, old_dt)
before = len(led.predictions())
S.record_decisions(led, pp, d_past, eng_old)
R["baslamadan_sonra_kayit"] = {"kickoff_utc": pp.kickoff_utc.isoformat(), "decision_time": old_dt.isoformat(),
                               "created_at_gercek": now_utc().isoformat(timespec="seconds"),
                               "kabul_edilen_kayit": len(led.predictions()) - before}

# kısmi yazım: 4. kayıtta hata → kaç kayıt kalır?
orig = led.record_prediction
cnt = {"n": 0}


def flaky(record):
    cnt["n"] += 1
    if cnt["n"] == 4:
        raise RuntimeError("yapay kesinti")
    return orig(record)


led.record_prediction = flaky
before = len(led.predictions())
try:
    S.record_decisions(led, p_old[2], S.decisions_for(p_old[2], eng_old, led, now), eng_old)
except RuntimeError:
    pass
led.record_prediction = orig
R["kismi_yazim"] = {"istenen": 6, "kalan": len(led.predictions()) - before}

# oran geriye dönük ekleme: fetched_at karar anından sonra, quoted_at önce → latest_quote döner mi?
pred3 = p_old[3]
dec_time = now - dt.timedelta(minutes=30)
late_q = OddsQuote(pred3.event_id, "FT_OVER_3_5", "FT", 3.5, "OVER", "csv", "deneme", 2.5,
                   dec_time - dt.timedelta(minutes=5), now)
led.add_odds([late_q])
got = led.latest_quote(pred3.event_id, "FT_OVER_3_5", dec_time)
R["sonradan_alinan_oran"] = {"karar_ani": dec_time.isoformat(), "fetched_at": now.isoformat(),
                             "latest_quote_dondu_mu": got is not None,
                             "not": "latest_quote yalnızca quoted_at'e bakar; fetched_at > karar anı olan oran da döner"}

# zincir ve oran tablosu
ok, msg = led.verify_chain()
R["zincir"] = {"ok": ok, "mesaj": msg}
con = sqlite3.connect(db)
con.execute("INSERT INTO odds VALUES ('X','FT_OVER_3_5','FT',3.5,'OVER','csv','b',9.9,'2020-01-01T00:00:00+00:00',"
            "'2020-01-01T00:00:00+00:00','OPEN','x')")
con.commit()
ok2, msg2 = led.verify_chain()
R["oran_tablosu_zincir_disi"] = {"dogrudan_sqlite_ekleme_sonrasi_verify_chain": [ok2, msg2]}
con.close()

# sonuçlandırma: gerçek (sentetik) sonuçlar; ertelenmiş (tarih +1 gün) maç
res = fixtures_full.copy()
st_all = S.settle_pending(led, pd.concat([m[m["date"] <= fx_day]], ignore_index=True))
R["sonuclandirma"] = st_all
shifted = fixtures_full.copy()
shifted["date"] = shifted["date"] + pd.Timedelta(days=1)
led2 = Ledger(out_dir / "sentetik_defter_erteleme.sqlite") if not (out_dir / "sentetik_defter_erteleme.sqlite").exists() else None
if led2 is not None:
    S.record_decisions(led2, p_old[0], S.decisions_for(p_old[0], eng_old, led2, now), eng_old)
    R["ertelenen_mac_sonuclandirma"] = S.settle_pending(led2, pd.concat([m[m["date"] < fx_day], shifted]))
    led2.close()
led.close()

# ---------------------------------------------------------------- maç öncesi dizi görünümü (sequences) tazeliği
from bahis_tahmin.sequences.prematch import prematch_frame  # noqa: E402
from bahis_tahmin.sequences.synthetic import synthetic_matches as seq_synth  # noqa: E402

sm, _ = seq_synth(n_leagues=1, n_seasons=4, n_teams=10, start_year=2023, seed=5)
lsd = sorted(sm.loc[sm["season"] == sm["season"].iloc[-1], "date"].unique())
cut2 = pd.Timestamp(lsd[2])
fxd = next(d for d in lsd if pd.Timestamp(d) > pd.Timestamp("2026-10-10"))
fx2 = sm[sm["date"] == fxd][["league", "date", "time", "home", "away"]].assign(source="sentetik-fikstur")
pf_old = prematch_frame(sm[sm["date"] <= cut2], fx2, None)
pf_new = prematch_frame(sm[sm["date"] < fxd], fx2, None)


def up_atoms(pf):
    tm = pf["tm"]
    idx = np.where(pf["upcoming"])[0]
    keys = list(pf["atoms"].keys())
    a = pd.DataFrame({k: pf["atoms"][k][idx] for k in keys})
    a["team"] = tm["team"].to_numpy()[idx]
    a["lig_arasi_gun"] = tm["lig_arasi_gun"].to_numpy()[idx]
    a["season_complete"] = tm["season_complete"].to_numpy()[idx]
    return a.set_index("team").sort_index()


ao, an = up_atoms(pf_old), up_atoms(pf_new)
keys = [k for k in pf_old["atoms"].keys()]
defined_old = int(np.isfinite(ao[keys].to_numpy(dtype=float)).sum())
defined_new = int(np.isfinite(an[keys].to_numpy(dtype=float)).sum())
both = np.isfinite(ao[keys].to_numpy(dtype=float)) & np.isfinite(an[keys].to_numpy(dtype=float))
differ = int((ao[keys].to_numpy(dtype=float)[both] != an[keys].to_numpy(dtype=float)[both]).sum())
R["tazelik_mac_oncesi_dizi"] = {
    "kesim": str(cut2.date()), "fikstur_gunu": str(pd.Timestamp(fxd).date()),
    "yaklasan_satir": int(pf_old["upcoming"].sum()),
    "tanimli_atom_eski": defined_old, "tanimli_atom_guncel": defined_new, "ikisinde_tanimli": int(both.sum()),
    "ikisinde_tanimli_ama_farkli": differ,
    "eski_lig_arasi_gun_ornek": ao["lig_arasi_gun"].head(3).tolist(),
    "eski_season_complete": bool(ao["season_complete"].all()),
    "uyari_alani_var_mi": any(k for k in pf_old.keys() if "uyari" in k or "stale" in k or "kesim" in k),
}
R["sure_sn"] = round(time.time() - T0, 1)
(out_dir / "defter_tazelik_sentetik.json").write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str),
                                                      encoding="utf-8")
print(json.dumps(R, ensure_ascii=False, indent=1, default=str))

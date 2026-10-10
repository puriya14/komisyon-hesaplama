"""Anomali taramasının evreni (hangi maçlar raporlanabilir) — takım-maç tablosu ile, S0 OLMADAN.

Yalnızca timeline.build_team_matches (veri yapısı) kullanılır; model uyumu, örüntü araması veya sonuç testi YOK.
S0 yüklenmez (pickle yasak); has_s0 yerine kayıtlardaki sonlu sürpriz/fark değerleri kullanılır (kayıtlı maçlarda S0 var).
Uygunluk (S0 hariç) = in_seq ∧ ¬ust_tur ∧ season_complete ∧ since_league_change ≥ 8 (frame.py:116-117).
Çıktılar: evren_kayit_satir.csv, evren_kume.csv, b_ozet.json.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT / "kod" / "bahis-tahmin"))
from bahis_tahmin.sequences import config as C  # noqa: E402
from bahis_tahmin.sequences.research import data_sha256  # noqa: E402
from bahis_tahmin.sequences.timeline import build_team_matches  # noqa: E402

CSV = Path(sys.argv[1])
SEQ = Path(sys.argv[2])
t0 = time.time()
matches = pd.read_csv(CSV, parse_dates=["date"])
sha = data_sha256(matches)
tm = build_team_matches(matches)
t1 = time.time()

since = np.nan_to_num(tm["since_league_change"].to_numpy(dtype=float), nan=-1)
tm["elig_noS0"] = (tm["in_seq"].to_numpy() & ~tm["ust_tur"].to_numpy() & tm["season_complete"].to_numpy()
                   & (since >= C.LEAGUE_CHANGE_EXCLUDE))
tm["period"] = [C.period_of(int(y)) for y in tm["season_year"]]
tm["in_mask_noS0"] = tm["elig_noS0"] & tm["period"].notna()
tm["cluster"] = tm["league"].astype(str) + "|" + tm["season"].astype(str)

home = tm[tm["is_home"]].set_index("event_id")
away = tm[~tm["is_home"]].set_index("event_id")
assert home.index.is_unique and away.index.is_unique

recs = json.loads((SEQ / "anomaliler.json").read_text(encoding="utf-8"))
rows = []
for r in recs:
    e = r["event_id"]
    h, a = home.loc[e], away.loc[e]
    lig_ck = next(c for c in r["checklist"] if c["kontrol"] == "lig değişikliği sonrası ilk maçlar")
    rows.append({
        "pair_id_kayit": r["pair_id"], "cluster": r["cluster"], "period_kayit": r["period"], "period_tm": h["period"],
        "S": "UNEXPLAINED_ANOMALY" in r["flags"], "M": "MODEL_PIYASA_FARKI" in r["flags"],
        "ev_uygun": bool(h["elig_noS0"]), "dep_uygun": bool(a["elig_noS0"]),
        "ev_since": float(h["since_league_change"]), "dep_since": float(a["since_league_change"]),
        "ust_tur": bool(h["ust_tur"]), "season_complete": bool(h["season_complete"]),
        "ev_in_seq": bool(h["in_seq"]), "dep_in_seq": bool(a["in_seq"]),
        "lig_aciklar": bool(lig_ck["aciklar"]),
        "red_h": h["h_red"], "red_a": h["a_red"],
    })
ev = pd.DataFrame(rows)
ev["iki_taraf_uygun"] = ev.ev_uygun & ev.dep_uygun
ev["tek_taraf_uygun"] = ev.ev_uygun ^ ev.dep_uygun
ev["hic_uygun_degil"] = ~ev.ev_uygun & ~ev.dep_uygun
ev["min_since_lt8"] = (np.fmin(ev.ev_since, ev.dep_since) < C.LEAGUE_CHANGE_EXCLUDE)
ev.drop(columns=["pair_id_kayit", "cluster"]).to_csv(OUT / "evren_kayit_satir.csv", index=False)  # kimliksiz

# Kırmızı kart verisi eksik kayıtlar: kaynak satırlarda h_red/a_red NaN mı?
recs_df = pd.DataFrame([{"kk_calisti": next(c for c in r["checklist"] if c["kontrol"] == "kırmızı kart")["calistirildi"]}
                        for r in recs])
kk_na_src_nan = int((~recs_df.kk_calisti & (ev.red_h.isna() | ev.red_a.isna())).sum())

# Küme (lig-sezon) düzeyi: maç sayısı, İY/MS bilinen maç, rapor edilebilir maç (S0 hariç), kayıt sayıları
pairs = tm[tm["is_home"]].copy()
mask_pair = tm.groupby("pair_id")["in_mask_noS0"].max()
pairs["secilebilir_noS0"] = pairs["pair_id"].map(mask_pair).to_numpy()
pairs["iki_taraf_uygun"] = pairs["pair_id"].map(tm.groupby("pair_id")["elig_noS0"].min()).to_numpy()
kume = pairs.groupby("cluster").agg(
    mac=("pair_id", "size"), iyms_bilinen=("raw_cell", lambda s: int((s >= 0).sum())),
    secilebilir_noS0=("secilebilir_noS0", "sum"), iki_taraf_uygun=("iki_taraf_uygun", "sum"),
    ust_tur=("ust_tur", "sum"), season_complete=("season_complete", "max"), period=("period", "first"),
    season_year=("season_year", "first"))
rec_df = pd.DataFrame([{"cluster": r["cluster"], "S": "UNEXPLAINED_ANOMALY" in r["flags"],
                        "M": "MODEL_PIYASA_FARKI" in r["flags"], "s_n": r["surprise_pool_n"], "m_n": r["gap_pool_n"]}
                       for r in recs])
kume["S_kayit"] = rec_df[rec_df.S].groupby("cluster").size().reindex(kume.index).fillna(0).astype(int)
kume["M_kayit"] = rec_df[rec_df.M].groupby("cluster").size().reindex(kume.index).fillna(0).astype(int)
kume["s_havuz_n"] = rec_df.groupby("cluster")["s_n"].first().reindex(kume.index)
kume["m_havuz_n"] = rec_df.groupby("cluster")["m_n"].first().reindex(kume.index)


def n_flags(nn):
    nn = int(nn)
    return sum(1 for k in range(1, nn + 1) if (2 * k - 1) * 200 < 2 * nn)


def neden(r):
    if r.period is None or (isinstance(r.period, float) and np.isnan(r.period)):
        return "dönem yok (period None: sezon yılı > 2025 veya < 2000)"
    if not r.season_complete:
        return "lig-sezon tam değil (hiçbir satır uygun değil)"
    if r.iyms_bilinen <= 100:
        return "havuz ≤ 100 (İY/MS bilinen maç ≤ 100)"
    return "diğer (bayraklı maç seçilmemiş veya S0 yok)"


kume["S_kayit_yok_nedeni"] = [neden(r) if r.S_kayit == 0 else "" for r in kume.itertuples()]
kume["M_kayit_yok_nedeni"] = [neden(r) if r.M_kayit == 0 else "" for r in kume.itertuples()]
kume["s_havuz_vs_iyms_bilinen"] = kume["s_havuz_n"] - kume["iyms_bilinen"]
kume["s_havuz_vs_secilebilir"] = kume["s_havuz_n"] - kume["secilebilir_noS0"]
oran = np.isfinite(matches[["o_h", "o_d", "o_a"]].to_numpy(float)).all(axis=1) & (matches[["o_h", "o_d", "o_a"]].to_numpy(float) > 0).all(axis=1)
kume["oran_var"] = pd.Series(oran).groupby((matches["league"].astype(str) + "|" + matches["season"].astype(str)).to_numpy()).sum().reindex(kume.index)
# Lig kimliği yazılmaz: anonim küme kodu + sezon (lig bazında anomali sayımı üretmemek için)
import hashlib
kume["kume_kodu"] = ["K" + hashlib.sha256(c.encode()).hexdigest()[:6] for c in kume.index]
kume["sezon"] = [c.split("|")[1] for c in kume.index]
kume.reset_index(drop=True).to_csv(OUT / "evren_kume.csv", index=False)

has = kume[kume.S_kayit > 0]
res = {
    "sure_sn": round(t1 - t0, 1),
    "veri_sha256": sha, "veri_sha256_manifestle_ayni": sha == "6ca929a2c62fb0aa304bb672339d290347db416e1c8bbfea758f6a46b53b4bc2",
    "mac": int(len(matches)), "tm_satir": int(len(tm)),
    "kayit": int(len(ev)),
    "kayit_iki_taraf_uygun": int(ev.iki_taraf_uygun.sum()),
    "kayit_tek_taraf_uygun": int(ev.tek_taraf_uygun.sum()),
    "kayit_hic_uygun_degil": int(ev.hic_uygun_degil.sum()),
    "period_esit": bool((ev.period_kayit == ev.period_tm).all()),
    "lig_aciklar_vs_tek_taraf": pd.crosstab(ev.lig_aciklar, ev.tek_taraf_uygun).to_dict(),
    "lig_aciklar_eq_min_since_lt8": bool((ev.lig_aciklar == ev.min_since_lt8).all()),
    "tek_taraf_uygun_neden": Counter(
        "since<8" if r.min_since_lt8 else ("in_seq yok" if not (r.ev_in_seq and r.dep_in_seq) else "diğer")
        for r in ev[ev.tek_taraf_uygun].itertuples()),
    "tek_taraf_S": int((ev.tek_taraf_uygun & ev.S).sum()), "tek_taraf_M": int((ev.tek_taraf_uygun & ev.M).sum()),
    "kume_sayisi": int(len(kume)), "kume_S_kayitli": int((kume.S_kayit > 0).sum()),
    "kume_M_kayitli": int((kume.M_kayit > 0).sum()),
    "kume_S_kayitsiz_neden": Counter(kume.loc[kume.S_kayit == 0, "S_kayit_yok_nedeni"]),
    "kume_M_kayitsiz_neden": Counter(kume.loc[kume.M_kayit == 0, "M_kayit_yok_nedeni"]),
    "S_kayitsiz_diger_kumeler_sezon": Counter(kume.loc[(kume.S_kayit == 0) & kume.S_kayit_yok_nedeni.str.startswith("diğer"), "sezon"]),
    "M_kayitsiz_diger_kumeler_sezon": Counter(kume.loc[(kume.M_kayit == 0) & kume.M_kayit_yok_nedeni.str.startswith("diğer"), "sezon"]),
    "S_var_M_yok_kume": int(((kume.S_kayit > 0) & (kume.M_kayit == 0)).sum()),
    "S_var_M_yok_kume_oran_var_le100": int(((kume.S_kayit > 0) & (kume.M_kayit == 0) & (kume.oran_var <= 100)).sum()),
    "S_var_M_yok_kume_oran_var_hepsi": bool((kume.loc[(kume.S_kayit > 0) & (kume.M_kayit == 0), "oran_var"]
                                            == kume.loc[(kume.S_kayit > 0) & (kume.M_kayit == 0), "mac"]).all()),
    "S_var_M_yok_kural_tahmini_M": int(sum(n_flags(n) for n in kume.loc[(kume.S_kayit > 0) & (kume.M_kayit == 0), "oran_var"])),
    "M_havuz_le_oran_var": bool((kume.loc[kume.M_kayit > 0, "m_havuz_n"] <= kume.loc[kume.M_kayit > 0, "oran_var"]).all()),
    "M_havuz_eq_oran_var_kume": int((kume.loc[kume.M_kayit > 0, "m_havuz_n"] == kume.loc[kume.M_kayit > 0, "oran_var"]).sum()),
    "S_havuz_gt_secilebilir_kume": int((has.s_havuz_vs_secilebilir > 0).sum()),
    "S_havuz_minus_secilebilir_toplam": int(has.s_havuz_vs_secilebilir.clip(lower=0).sum()),
    "S_havuz_le_iyms_bilinen": bool((has.s_havuz_vs_iyms_bilinen <= 0).all()),
    "S_havuz_eq_iyms_bilinen_kume": int((has.s_havuz_vs_iyms_bilinen == 0).sum()),
    "secilebilir_mac_toplam_noS0": int(kume.secilebilir_noS0.sum()),
    "secilebilir_mac_period_dagilim_noS0": {str(k): int(v) for k, v in
                                            pairs[pairs.secilebilir_noS0].groupby("period").size().items()},
    "iki_taraf_uygun_mac_period_noS0": {str(k): int(v) for k, v in
                                        pairs[pairs.iki_taraf_uygun & pairs.period.notna()].groupby("period").size().items()},
    "kk_na_kaynakta_red_NaN": kk_na_src_nan,
    "kume_mac_le100": int((kume.iyms_bilinen <= 100).sum()),
}
# Kural bayrak sayısı (eşitsiz) − kayıt: kural gereği bayraklanan ama raporlanmayan (seçilmemiş) maç sayısı
has_s = kume[kume.S_kayit > 0]
res["S_kural_eksi_kayit"] = int(sum(n_flags(n) for n in has_s.s_havuz_n) - has_s.S_kayit.sum())
has_m = kume[kume.M_kayit > 0]
res["M_kural_eksi_kayit"] = int(sum(n_flags(n) for n in has_m.m_havuz_n) - has_m.M_kayit.sum())
(OUT / "b_ozet.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1, default=str))

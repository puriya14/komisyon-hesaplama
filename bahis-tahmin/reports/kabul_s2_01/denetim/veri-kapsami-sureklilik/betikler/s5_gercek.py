"""Adım 5: gerçek veride (yalnızca tanımlayıcı sayım; hipotez testi/model yok) süreklilik nicelemesi.

(i)  5/10 pencereleri eksik lig-sezona dokunan takım-maç satırları (atom penceresi ve S1 penceresi ayrı).
(ii) 'Tam' sayılan sezonlarda takım-sezon eksikleri (kurala göre) ve bunlara dokunan geçerli pencereler (üst sınır).
(iii) Mod A aralıkları (team_events mantığı, iki olay, tüm takımlar): eksik sezon / GAP_GT_400D / SEASON_SKIP /
     lig değişikliği / bilinmeyen sonuç / atlanan UST_TUR maçı; sol kesik (veri başı / kapsama giriş), sağ sansür.
(iv) F4 event_gaps kayıt sayılarının yeniden üretimi (dizi_sonuclar.json ile karşılaştırma).
"""
import json, types
import numpy as np, pandas as pd
from ortak import OUT, build_tm
from bahis_tahmin.sequences.features import SeqIndex
from bahis_tahmin.sequences.timeline import team_events
from bahis_tahmin.sequences.frame import target_outcomes
from bahis_tahmin.sequences import hazard as H
from bahis_tahmin.sequences import config as C

m, tm = build_tm()
R = {}
si = SeqIndex(tm)
rows = si.rows
seq = tm.iloc[rows]
bad = ~seq["season_complete"].to_numpy()
cb = np.r_[0, np.cumsum(bad)]
pos = si.pos_in_spell
j = np.arange(si.n)
since_lc = np.nan_to_num(seq["since_league_change"].to_numpy(dtype=float), nan=-1)
elig_nos0 = seq["season_complete"].to_numpy() & (since_lc >= C.LEAGUE_CHANGE_EXCLUDE)  # S0 koşulu hariç 'eligible'
lc = seq["league_changed"].to_numpy()
clc = np.r_[0, np.cumsum(lc)]
# --- (ii) takım-sezon eksikleri: tam, devam etmeyen, kısaltılmamış lig-sezonlarda takım normal maç < kural
reg_rows = tm[tm["in_seq"]]
ts = reg_rows.groupby(["league", "season", "team"]).agg(n=("row_id", "size"), reg=("regular_len", "first"),
                                                       tam=("season_complete", "first"), ong=("season_ongoing", "first"),
                                                       short=("season_shortened", "first")).reset_index()
ts["eksik"] = (ts["reg"] - ts["n"]).clip(lower=0)
ts_def = ts[ts["tam"] & ~ts["ong"] & ~ts["short"] & (ts["eksik"] > 0)]
ts_def.to_csv(f"{OUT}/takim_sezon_eksik_tam_sezonlarda.csv", index=False)
R["ii_tam_sezonda_takim_sezon_eksik"] = {
    "takim_sezon": int(len(ts_def)), "eksik_mac_takim_satiri": int(ts_def["eksik"].sum()),
    "lig_sezon": int(ts_def[["league", "season"]].drop_duplicates().shape[0]),
    "lig_sezonlar": sorted({f"{a} {b}" for a, b in zip(ts_def["league"], ts_def["season"])}),
}
defkey = set(zip(ts_def["league"], ts_def["season"], ts_def["team"]))
is_def = np.array([(a, b, c) in defkey for a, b, c in zip(seq["league"], seq["season"], seq["team"])])
cd = np.r_[0, np.cumsum(is_def)]
# UST_TUR maçları (pencere dizisine girmez): takımın dizideki iki ardışık maçı arasında atlanan üst tur sayısı
ust = tm[tm["ust_tur"]]
ust_dates = ust.groupby("team")["date"].apply(lambda s: np.sort(pd.to_datetime(s).to_numpy()))
d_seq = pd.to_datetime(seq["date"]).to_numpy()
t_seq = seq["team"].to_numpy()
ust_before = np.zeros(si.n, dtype=np.int64)  # takımın bu satırdan önceki toplam üst tur maçı
for t, idx in pd.Series(np.arange(si.n)).groupby(t_seq):
    if t in ust_dates.index:
        ust_before[idx.to_numpy()] = np.searchsorted(ust_dates[t], d_seq[idx.to_numpy()], side="left")
win = {}
for k in (5, 10):
    full = pos >= k
    lo_atom = np.clip(j - k, 0, None)
    lo_s1 = j - np.minimum(pos, k)
    touch_atom = (cb[j + 1] - cb[lo_atom]) > 0
    touch_s1 = (cb[j] - cb[lo_s1]) > 0  # S1 penceresi yalnızca önceki maçlar
    wok = si.window_ok(k)
    touch_def = (cd[j + 1] - cd[np.where(full, lo_atom, lo_s1)]) > 0
    mixed_lg = (clc[j + 1] - clc[np.where(full, lo_atom, lo_s1) + 1]) > 0
    lo_any = np.where(full, lo_atom, lo_s1)
    ust_in = (ust_before[j] - ust_before[lo_any]) > 0
    win[k] = {
        "dizi_satiri": int(si.n), "k_mac_mevcut": int(full.sum()),
        "k_mevcut_ve_eksik_sezona_dokunan": int((full & touch_atom).sum()),
        "window_ok": int(wok.sum()),
        "S1_penceresi_eksik_sezona_dokunan_tum": int(((np.minimum(pos, k) > 0) & touch_s1).sum()),
        "S1_penceresi_eksik_sezona_dokunan_uygun_satir_S0haric": int((elig_nos0 & (np.minimum(pos, k) > 0) & touch_s1).sum()),
        "uygun_satir_S0haric": int(elig_nos0.sum()),
        "window_ok_ve_tam_sezon_takim_eksigine_dokunan_ust_sinir": int((wok & touch_def).sum()),
        "window_ok_ve_lig_degisimi_iceren": int((wok & mixed_lg).sum()),
        "uygun_satir_ve_window_ok_ve_lig_degisimi_iceren": int((elig_nos0 & wok & mixed_lg).sum()),
        "window_ok_ve_arada_UST_TUR_atlanan": int((wok & ust_in).sum()),
    }
R["i_pencereler"] = win

# --- (iii) Mod A aralıkları (team_events ile aynı mantık, vektörel) ---
y_all = target_outcomes(tm)
known_seq = {}
seq_no = pd.Series(np.ones(si.n)).groupby(t_seq).cumsum().to_numpy() - 1
spell = seq["spell_id"].to_numpy()
skip = seq["season_skip"].to_numpy()
cs = np.r_[0, np.cumsum(skip)]
data_start = pd.Timestamp(tm["date"].min()); data_end = pd.Timestamp(tm["date"].max())
first_date = pd.Series(d_seq).groupby(t_seq).transform("min").to_numpy()
modeA = {}
iv_rows = []
for ev in C.HAZARD_EVENTS:
    y = np.asarray(y_all[ev], dtype=float)[rows]
    unk = ~np.isfinite(y)
    cu = np.r_[0, np.cumsum(unk)]
    hit = np.where(y == 1)[0]
    same = np.r_[False, t_seq[hit[1:]] == t_seq[hit[:-1]]]
    p, c = hit[:-1][same[1:]], hit[1:][same[1:]]
    n_mac = seq_no[c] - seq_no[p]
    f_inc = (cb[c + 1] - cb[p]) > 0
    f_gap = spell[c] != spell[p]
    f_skip = (cs[c + 1] - cs[p + 1]) > 0
    f_lc = (clc[c + 1] - clc[p + 1]) > 0
    f_unk = (cu[c] - cu[p + 1]) > 0
    f_ust = (ust_before[c] - ust_before[p]) > 0
    f_def = (cd[c + 1] - cd[p]) > 0
    clean = ~(f_inc | f_gap | f_skip | f_lc | f_unk | f_ust | f_def)
    # sol kesik: her takımın ilk olayı (Mod A'da onceki_olaydan_mac = NaN)
    first_ev = hit[~same]
    lt_data_start = first_date[first_ev] <= np.datetime64(data_start + pd.Timedelta(days=45))
    teams_all = pd.unique(t_seq)
    teams_ev = set(t_seq[hit])
    # sağ sansür: censored_tail (son olay → takımın son dizi satırı, TÜM dilimler boyunca)
    last_pos = pd.Series(np.arange(si.n)).groupby(t_seq).max()
    last_ev = pd.Series(hit).groupby(t_seq[hit]).max()
    tail = []
    for t, le in last_ev.items():
        lp = int(last_pos[t])
        tail.append({"team": t, "acik_aralik_mac": int(seq_no[lp] - seq_no[le]),
                     "bitis_nedeni": seq["spell_end"].iloc[lp],
                     "eksik_sezon": bool((cb[lp + 1] - cb[le]) > 0), "dilim_asar": bool(spell[lp] != spell[le]),
                     "season_skip": bool((cs[lp + 1] - cs[le + 1]) > 0), "lig_degisimi": bool((clc[lp + 1] - clc[le + 1]) > 0)})
    tail = pd.DataFrame(tail)
    no_ev = [t for t in teams_all if t not in teams_ev]
    modeA[ev] = {
        "olay_sayisi": int(len(hit)), "tamamlanan_aralik": int(len(p)),
        "eksik_lig_sezona_dokunan": int(f_inc.sum()), "GAP_GT_400D_dilim_asan": int(f_gap.sum()),
        "SEASON_SKIP_iceren": int(f_skip.sum()), "lig_degisimi_iceren": int(f_lc.sum()),
        "arada_bilinmeyen_sonuc": int(f_unk.sum()), "arada_atlanan_UST_TUR": int(f_ust.sum()),
        "tam_sezon_takim_eksigine_dokunan_ust_sinir": int(f_def.sum()),
        "eksik_sezon_veya_GAP_veya_SKIP_orta_bosluk": int((f_inc | f_gap | f_skip).sum()),
        "temiz": int(clean.sum()),
        "orta_bosluklu_aralik_mac_toplami": int(n_mac[f_inc | f_gap | f_skip].sum()),
        "temiz_aralik_medyan_mac": float(np.median(n_mac[clean])) if clean.any() else None,
        "tum_tamamlanan_medyan_mac": float(np.median(n_mac)) if len(n_mac) else None,
        "sol_kesik_ilk_olay": int(len(first_ev)), "sol_kesik_veri_basi": int(lt_data_start.sum()),
        "sol_kesik_kapsama_sonradan_giris": int((~lt_data_start).sum()),
        "hic_olayi_olmayan_takim": int(len(no_ev)),
        "sag_sansur_takim": int(len(tail)),
        "sag_sansur_bitis_nedeni": tail["bitis_nedeni"].value_counts().to_dict(),
        "sag_sansur_acik_aralik_dilim_asan": int(tail["dilim_asar"].sum()),
        "sag_sansur_acik_aralik_eksik_sezona_dokunan": int(tail["eksik_sezon"].sum()),
        "sag_sansur_acik_aralik_lig_degisimi": int(tail["lig_degisimi"].sum()),
    }
    for a, b, nm, fi, fg, fs, fl, fu, fus in zip(p, c, n_mac, f_inc, f_gap, f_skip, f_lc, f_unk, f_ust):
        pass
    iv = pd.DataFrame({"olay": ev, "takim": t_seq[c], "onceki_olay_tarihi": d_seq[p], "olay_tarihi": d_seq[c],
                       "onceki_olaydan_mac": n_mac, "eksik_sezon": f_inc, "GAP_GT_400D": f_gap, "SEASON_SKIP": f_skip,
                       "lig_degisimi": f_lc, "bilinmeyen_sonuc": f_unk, "UST_TUR_atlanan": f_ust, "takim_sezon_eksigi": f_def,
                       "temiz": clean})
    iv_rows.append(iv)
R["iii_modA"] = modeA
pd.concat(iv_rows).to_csv(f"{OUT}/modA_aralik_siniflari.csv.gz", index=False)

# team_events ile eşdeğerlik kontrolü (örnek takımlar)
chk = []
rng = np.random.default_rng(0)
sample = ["PSV Eindhoven", "Rangers", "Fiorentina"] + list(rng.choice(pd.unique(t_seq), 25, replace=False))
iv_all = pd.concat(iv_rows)
for t in sample:
    for ev in C.HAZARD_EVENTS:
        e = team_events(tm, t, target=ev)
        a = e["onceki_olaydan_mac"].dropna().astype(int).tolist()
        b = iv_all[(iv_all["takim"] == t) & (iv_all["olay"] == ev)]["onceki_olaydan_mac"].astype(int).tolist()
        chk.append(a == b)
R["iii_team_events_esdegerlik"] = {"kontrol": len(chk), "esit": int(sum(chk))}

# --- (iv) F4 event_gaps kayıtlarının yeniden üretimi ---
fr = types.SimpleNamespace(tm=tm, y=y_all)
f4 = {}
for ev in C.HAZARD_EVENTS:
    g = H.event_gaps(fr, ev)
    comp = g[g["kind"] == "COMPLETED"]
    f4[ev] = {k: g.attrs[k] for k in ("n_blocks", "n_intervals", "n_completed", "n_censored", "n_left_truncated",
                                      "left_truncated_matches", "at_risk_matches", "censor_reasons")}
    f4[ev]["COMPLETED_lig_degisimi_iceren"] = int((comp["league_changes"] > 0).sum())
    f4[ev]["COMPLETED_bilinmeyen_iceren"] = int((comp["n_unknown"] > 0).sum())
    f4[ev]["COMPLETED_medyan_mac"] = float(comp["matches"].median())
R["iv_F4_yeniden"] = f4
js = json.load(open(f"{OUT}/dizi_sonuclar_01b7e9f.json"))["aileler"]["F4"]["events"]
R["iv_F4_kayit_ile_esit"] = {ev: all(f4[ev][k] == js[ev]["gaps"][k] for k in ("n_blocks", "n_intervals", "n_completed", "n_censored",
                                                                          "n_left_truncated", "left_truncated_matches", "at_risk_matches", "censor_reasons"))
                             for ev in C.HAZARD_EVENTS}
json.dump(R, open(f"{OUT}/s5_gercek.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(R, ensure_ascii=False, indent=1, default=str))

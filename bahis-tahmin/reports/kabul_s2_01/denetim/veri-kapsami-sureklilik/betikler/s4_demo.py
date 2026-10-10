"""Adım 4: süreklilik soruları için SENTETİK gösterimler (baseline 01b7e9f kodu; gerçek sonuç kullanılmaz).

Sentetik veri: synthetic_matches(n_leagues=1, n_seasons=5, n_teams=10, seed=S) → takım başı sezonda 18 maç,
lig-sezon 90 maç. Tamlık eşiği COMPLETE_SHARE=0.97: aynı lig-sezondan 2 maç silmek → pay 176/180=0.978 (TAM kalır),
3 maç silmek → 174/180=0.967 (KISMI).
"""
import json, sys
import numpy as np, pandas as pd
from ortak import OUT
from bahis_tahmin.sequences.synthetic import synthetic_matches
from bahis_tahmin.sequences.timeline import build_team_matches, team_events, coverage_report
from bahis_tahmin.sequences.frame import build_frame
from bahis_tahmin.sequences.features import SeqIndex
from bahis_tahmin.sequences import hazard as H
from bahis_tahmin.sequences import patterns as P
from bahis_tahmin.goals.ledger import event_id

EV = "IY_GERIDE_MS_GALIP"
rep = {}
lines = []
def say(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)

def eid(df):
    return [event_id(l, d, h, a) for l, d, h, a in zip(df["league"], df["date"], df["home"], df["away"])]

def frame(m, probs):
    tm = build_team_matches(m)
    return build_frame(tm, probs), tm

# ---------- bir takım + iki ardışık olay + aralarında aynı sezonda >=3 maç bul ----------
def find_case(seed):
    m, probs = synthetic_matches(n_leagues=1, n_seasons=5, n_teams=10, seed=seed)
    fr, tm = frame(m, probs)
    for team in sorted(tm["team"].unique()):
        ev = team_events(tm, team, target=EV)
        for i in range(1, len(ev)):
            a, b = ev.iloc[i - 1], ev.iloc[i]
            if a["season"] == b["season"] and a["season"] in ("2001/02", "2002/03") and b["seq_no"] - a["seq_no"] >= 5:
                return m, probs, fr, tm, team, a, b
    return None

for seed in range(50):
    r = find_case(seed)
    if r:
        break
m, probs, fr0, tm0, team, a, b = r
say(f"[kurulum] tohum={seed}, takım={team}, olaylar {pd.Timestamp(a['date']).date()} ve {pd.Timestamp(b['date']).date()} "
    f"(sezon {a['season']}), arada {int(b['seq_no'] - a['seq_no'] - 1)} maç")
rep["kurulum"] = {"tohum": seed, "takim": team, "olay1": str(pd.Timestamp(a["date"]).date()), "olay2": str(pd.Timestamp(b["date"]).date()),
                  "sezon": a["season"], "arada_mac": int(b["seq_no"] - a["seq_no"] - 1)}

# takımın iki olay arasındaki maçları (ham tablo indeksleri)
tmask = ((m["home"] == team) | (m["away"] == team)) & (m["date"] > a["date"]) & (m["date"] < b["date"])
between = m.index[tmask].tolist()

def drop(k):
    keep = ~m.index.isin(between[:k])
    return m[keep].reset_index(drop=True)

# ---------- (a) pencere atomları ve S1 ----------
res_a = {}
for k in (2, 3):
    mk = drop(k)
    frk, tmk = frame(mk, probs)
    cov = coverage_report(tmk)
    se_row = cov[(cov["season"] == a["season"])].iloc[0]
    # olay b satırı (aynı event_id) — önceki 5/10 pencere geçerliliği ve kapsadığı tarihler
    eb = event_id("T1", b["date"], *(m.loc[(m["date"] == b["date"]) & ((m["home"] == team) | (m["away"] == team)), ["home", "away"]].iloc[0]))
    rk = int(tmk.index[(tmk["event_id"] == eb) & (tmk["team"] == team)][0])
    r0 = int(tm0.index[(tm0["event_id"] == eb) & (tm0["team"] == team)][0])
    si_k, si_0 = frk.seq, fr0.seq
    out = {"silinen_mac": k, "sezon_payi": float(se_row["pay"]), "sezon_tam": bool(se_row["tam"])}
    for w in (5, 10):
        okk = si_k.window_ok(w)[si_k.pos_of_tm[rk]]
        ok0 = si_0.window_ok(w)[si_0.pos_of_tm[r0]]
        # pencerenin kapsadığı maç tarihleri (aynı dilim, önceki w konum)
        rows_k = si_k.rows[max(0, si_k.pos_of_tm[rk] - w): si_k.pos_of_tm[rk]]
        rows_0 = si_0.rows[max(0, si_0.pos_of_tm[r0] - w): si_0.pos_of_tm[r0]]
        dk = [str(pd.Timestamp(x).date()) for x in tmk.loc[rows_k, "date"]]
        d0 = [str(pd.Timestamp(x).date()) for x in tm0.loc[rows_0, "date"]]
        out[f"window_ok_{w}"] = {"silinmis": bool(okk), "tam_veri": bool(ok0)}
        out[f"pencere_ilk_tarih_{w}"] = {"silinmis": dk[0], "tam_veri": d0[0]}
        out[f"pencere_takvim_gun_{w}"] = {"silinmis": int((pd.Timestamp(b['date']) - pd.Timestamp(dk[0])).days),
                                         "tam_veri": int((pd.Timestamp(b['date']) - pd.Timestamp(d0[0])).days)}
    for at in ("SON5_IY_GERIDE_EN_AZ_2", "SON5_GALIBIYETSIZ", "SON10_IY_GERIDE_MS_GALIP_EN_AZ_2", "SON3_MAGLUBIYET"):
        out[f"atom_{at}"] = {"silinmis": None if np.isnan(frk.atoms[at][rk]) else float(frk.atoms[at][rk]),
                             "tam_veri": None if np.isnan(fr0.atoms[at][r0]) else float(fr0.atoms[at][r0])}
    for f in ("trail5", "comeback10", "ppg5", "navail10", "since_log", "since_none", "gap_log"):
        out[f"s1_{f}"] = {"silinmis": float(frk.s1[f].iloc[rk]), "tam_veri": float(fr0.s1[f].iloc[r0])}
    out["satir_uygun_eligible"] = {"silinmis": bool(frk.eligible[rk]), "tam_veri": bool(fr0.eligible[r0])}
    # (a2) sonraki sezonun ilk maçları: 10-pencere eksik sezona uzanıyor mu? (yalnızca k=3 anlamlı)
    nxt = tmk[(tmk["team"] == team) & (tmk["season"] > a["season"])].head(3)
    out["sonraki_sezon_ilk3"] = [{
        "tarih": str(pd.Timestamp(x["date"]).date()), "sezon_tam": bool(x["season_complete"]),
        "eligible_s0siz": bool(x["in_seq"] and not x["ust_tur"] and x["season_complete"]),
        "window_ok10": bool(si_k.window_ok(10)[si_k.pos_of_tm[i]]),
        "s1_comeback10": float(frk.s1["comeback10"].iloc[i]), "s1_navail10": float(frk.s1["navail10"].iloc[i]),
        "atom_SON10": (None if np.isnan(frk.atoms["SON10_IY_GERIDE_MS_GALIP_EN_AZ_2"][i]) else float(frk.atoms["SON10_IY_GERIDE_MS_GALIP_EN_AZ_2"][i])),
        "pencere10_eksik_sezona_uzaniyor": bool((tmk.loc[si_k.rows[max(0, si_k.pos_of_tm[i] - 10): si_k.pos_of_tm[i]], "season_complete"] == False).any()),
    } for i, x in nxt.iterrows()]
    # aynı takımın, iki tabloda da pencere geçerli olan tüm satırlarında atom farkı sayısı (eşleşme: event_id+takım)
    key0 = tm0[tm0["team"] == team].set_index("event_id")
    keyk = tmk[tmk["team"] == team].set_index("event_id")
    common = keyk.index.intersection(key0.index)
    diff = {}
    for at in ("SON5_IY_GERIDE_EN_AZ_2", "SON5_IY_ONDE_EN_AZ_3", "SON5_GALIBIYET_EN_AZ_4", "SON5_GALIBIYETSIZ", "SON3_MAGLUBIYET",
               "SON10_IY_GERIDE_MS_GALIP_EN_AZ_2", "SON10_IY_SONRASI_IYILESME_EN_AZ_4"):
        v0 = fr0.atoms[at][key0.loc[common, "row_id"].to_numpy()]
        vk = frk.atoms[at][keyk.loc[common, "row_id"].to_numpy()]
        both = np.isfinite(v0) & np.isfinite(vk)
        diff[at] = {"ikisinde_de_tanimli": int(both.sum()), "deger_farkli": int((v0[both] != vk[both]).sum()),
                    "yalniz_silinmiste_NaN": int((np.isfinite(v0) & ~np.isfinite(vk)).sum())}
    out["takim_tum_satirlar_atom_farki"] = diff
    s1d = {}
    for f in ("trail5", "comeback10", "ppg5", "improve10", "since_log"):
        v0 = fr0.s1[f].to_numpy()[key0.loc[common, "row_id"].to_numpy()]
        vk = frk.s1[f].to_numpy()[keyk.loc[common, "row_id"].to_numpy()]
        both = np.isfinite(v0) & np.isfinite(vk)
        s1d[f] = {"ikisinde_de_tanimli": int(both.sum()), "deger_farkli": int((np.abs(v0[both] - vk[both]) > 1e-12).sum())}
    out["takim_tum_satirlar_S1_farki"] = s1d
    res_a[f"sil_{k}"] = out
rep["a_pencere_ve_S1"] = res_a
say("[a] k=2 (sezon TAM kalır):", json.dumps(res_a["sil_2"], ensure_ascii=False))
say("[a] k=3 (sezon KISMI olur):", json.dumps(res_a["sil_3"], ensure_ascii=False))

# ---------- (b) Mod A aralığı ve F4 event_gaps ----------
res_b = {}
for k in (0, 2, 3):
    mk = drop(k) if k else m
    frk, tmk = frame(mk, probs)
    ev = team_events(tmk, team, target=EV)
    row = ev[pd.to_datetime(ev["date"]) == pd.Timestamp(b["date"])].iloc[0]
    g = H.event_gaps(frk, EV, team=team)
    gb = g[pd.to_datetime(g["end_date"]) == pd.Timestamp(b["date"])]
    ga = g[pd.to_datetime(g["start_date"]) == pd.Timestamp(a["date"])]
    res_b[f"sil_{k}"] = {
        "ModA_onceki_olaydan_mac": float(row["onceki_olaydan_mac"]), "ModA_onceki_olaydan_gun": float(row["onceki_olaydan_gun"]),
        "ModA_ayni_dilim": bool(row["ayni_dilim"]), "ModA_sezon_gecisi": bool(row["sezon_gecisi"]),
        "F4_olay2_ile_biten": gb[["kind", "matches", "days", "n_unknown", "censor_reason"]].to_dict("records"),
        "F4_olay1_ile_baslayan": ga[["kind", "matches", "days", "n_unknown", "censor_reason"]].to_dict("records"),
    }
rep["b_ModA_aralik"] = res_b
say("[b]", json.dumps(res_b, ensure_ascii=False, default=str))

# ---------- (c) bilinmeyen sonuç: olay maçının İY skoru silinirse ----------
m_unk = m.copy()
ia = m.index[(m["date"] == a["date"]) & ((m["home"] == team) | (m["away"] == team))][0]
m_unk.loc[ia, ["hthg", "htag"]] = np.nan
fru, tmu = frame(m_unk, probs)
evu = team_events(tmu, team, target=EV)
rowu = evu[pd.to_datetime(evu["date"]) == pd.Timestamp(b["date"])].iloc[0]
gu = H.event_gaps(fru, EV, team=team)
gbu = gu[pd.to_datetime(gu["end_date"]) == pd.Timestamp(b["date"])]
sl0 = H.since_last_event(fr0, EV)
slu = H.since_last_event(fru, EV)
r0b = int(tm0.index[(tm0["team"] == team) & (pd.to_datetime(tm0["date"]) == pd.Timestamp(b["date"]))][0])
rub = int(tmu.index[(tmu["team"] == team) & (pd.to_datetime(tmu["date"]) == pd.Timestamp(b["date"]))][0])
# Q2: olay a artık aday değil; ufku bilinmeyen içeren örnekte hedef NaN
mask0 = np.ones(len(tm0), dtype=bool)
q0 = P.q2_prepare(fr0, mask0)
qu = P.q2_prepare(fru, np.ones(len(tmu), dtype=bool))
ra0 = int(tm0.index[(tm0["team"] == team) & (pd.to_datetime(tm0["date"]) == pd.Timestamp(a["date"]))][0])
rau = int(tmu.index[(tmu["team"] == team) & (pd.to_datetime(tmu["date"]) == pd.Timestamp(a["date"]))][0])
inst0 = P.q2_instances(fr0, mask0, prep=q0)
instu = P.q2_instances(fru, None, prep=qu)
res_c = {
    "ModA_onceki_olaydan_mac_olay2": {"tam": res_b["sil_0"]["ModA_onceki_olaydan_mac"], "olay1_bilinmiyor": float(rowu["onceki_olaydan_mac"])},
    "F4_olay2_ile_biten": gbu[["kind", "matches", "n_unknown"]].to_dict("records"),
    "since_last_event_olay2_satiri": {"tam": float(sl0[r0b]), "olay1_bilinmiyor": float(slu[rub])},
    "s1_since_log_olay2": {"tam": float(fr0.s1["since_log"].iloc[r0b]), "olay1_bilinmiyor": float(fru.s1["since_log"].iloc[rub])},
    "Q2_olay1_ornek_mi": {"tam": bool(((inst0["event_row"] == ra0) & (inst0["event"] == EV)).any()),
                          "olay1_bilinmiyor": bool(((instu["event_row"] == rau) & (instu["event"] == EV)).any())},
    "atom_SON_MAC_IY_GERIDE_MS_GALIP_olay1_sonrasi": {
        "tam": None if np.isnan(fr0.atoms["SON_MAC_IY_GERIDE_MS_GALIP"][int(tm0.index[(tm0['team'] == team) & (tm0['row_id'] > ra0)][0])]) else 1,
        "olay1_bilinmiyor": None if np.isnan(fru.atoms["SON_MAC_IY_GERIDE_MS_GALIP"][int(tmu.index[(tmu['team'] == team) & (tmu['row_id'] > rau)][0])]) else 1},
}
rep["c_bilinmeyen"] = res_c
say("[c]", json.dumps(res_c, ensure_ascii=False, default=str))

# (c2) bütün bir sezon yok (ara sezon verisi kayıp) → Mod A dilimler arasında aralık verir mi?
m_gap = m[m["season"] != "2002/03"].reset_index(drop=True)
frg, tmg = frame(m_gap, probs)
evs = []
for t in sorted(tmg["team"].unique()):
    e = team_events(tmg, t, target=EV)
    cross = e[(~e["ayni_dilim"]) & e["onceki_olaydan_mac"].notna()]
    evs.append(len(cross))
gg = H.event_gaps(frg, EV)
rep["c2_sezon_kaybi"] = {
    "ModA_dilim_asan_aralik_sayisi": int(sum(evs)),
    "F4_dilim_asan_COMPLETED": int(((gg["kind"] == "COMPLETED") & (gg["season_transitions"] > 0) & (gg["start_season"] == "2001/02") & (gg["end_season"] == "2003/04")).sum()),
    "spell_end_dagilimi": tmg.groupby("spell_id")["spell_end"].first().value_counts().to_dict(),
    "season_skip_satir": int(tmg["season_skip"].sum()),
}
say("[c2]", json.dumps(rep["c2_sezon_kaybi"], ensure_ascii=False))

# ---------- (d) ad değişikliği ve lig geçişi ----------
def rename(mm, old, new, mask):
    mm = mm.copy()
    mm.loc[mask & (mm["home"] == old), "home"] = new
    mm.loc[mask & (mm["away"] == old), "away"] = new
    return mm
season_dates = m[m["season"] == "2002/03"]["date"]
mid = season_dates.min() + (season_dates.max() - season_dates.min()) / 2
# d1: sezon ortası ad değişikliği (aynı kulüp) → katman 1 birleştirir
m_d1 = rename(m, team, "Yeni Ad FK", (m["season"] == "2002/03") & (m["date"] > mid))
tm_d1 = build_team_matches(m_d1)
# d2: sezonlar arası ad değişikliği → katman 1 yakalamaz (iki kimlik, sahte kopukluk)
m_d2 = rename(m, team, "Yeni Ad FK", m["season"] >= "2003/04")
tm_d2 = build_team_matches(m_d2)
# d3: FARKLI kulüp — takım sezon ortasında çekiliyor, yerine başka kulüp geliyor (veri biçimi d1 ile aynı)
#     kural ikisini ayırt edemez → tek kimlik (sahte süreklilik)
rep["d_kimlik"] = {
    "d1_sezon_ortasi_ad_degisimi": {"splits": tm_d1.attrs["intra_season_splits"],
                                     "kanonik_takim_sayisi": int(tm_d1["team"].nunique()),
                                     "takim_dilim_sayisi": int(tm_d1.loc[tm_d1["team"] == team, "spell_id"].nunique())},
    "d2_sezonlar_arasi_ad_degisimi": {"splits": tm_d2.attrs["intra_season_splits"],
                                       "kanonik_takim_sayisi": int(tm_d2["team"].nunique()),
                                       "eski_ad_spell_end": tm_d2.loc[tm_d2["team"] == team, "spell_end"].dropna().unique().tolist(),
                                       "yeni_ad_ilk_satir_spell_seq": float(tm_d2.loc[tm_d2["team"] == "Yeni Ad FK", "spell_seq"].iloc[0])},
    "d3_not": "d1 ile aynı veri biçimi: ad/lig/tarih kuralı 'yeniden adlandırma' ile 'çekilen kulübün yerine gelen farklı kulüp' ayrımını yapamaz; ikisi de tek kimliğe birleşir.",
}
# d4: lig geçişi — iki ligli sentetik, bir takımı sezon sonunda diğer lige taşı
m2, probs2 = synthetic_matches(n_leagues=2, n_seasons=4, n_teams=10, seed=seed)
lg_a, lg_b = "T1", "N1"
ta = f"{lg_a}-Takım A"; tb = f"{lg_b}-Takım A"
# 2002/03'ten itibaren N1'deki 'N1-Takım A' adını 'T1-Takım A' yap (ülke farklı olduğundan eşleme ülke anahtarlı: ayrı kimlik!)
m2x = m2.copy()
sel = (m2x["league"] == lg_b) & (m2x["season"] >= "2002/03")
m2x.loc[sel & (m2x["home"] == tb), "home"] = ta
m2x.loc[sel & (m2x["away"] == tb), "away"] = ta
# T1'de 2002/03+ 'T1-Takım A' yerine yeni ad (takım N1'e "geçti")
sel2 = (m2x["league"] == lg_a) & (m2x["season"] >= "2002/03")
m2x.loc[sel2 & (m2x["home"] == ta), "home"] = "T1-Yeni"
m2x.loc[sel2 & (m2x["away"] == ta), "away"] = "T1-Yeni"
tm4 = build_team_matches(m2x)
x = tm4[tm4["team"] == ta]
rep["d_kimlik"]["d4_ulkeler_arasi_ayni_ad"] = {
    "not": "Kimlik anahtarı yalnızca kanonik AD'dır (tm['team']); ülke yalnızca eşleme tablosunu aramak için kullanılır. Farklı ülkelerdeki aynı ad tek kimliğe birleşir.",
    "T1-Takım A_ligleri": sorted(x["league"].unique().tolist()), "dilim_sayisi": int(x["spell_id"].nunique()),
    "league_changed_satir": int(x["league_changed"].sum()),
}
say("[d]", json.dumps(rep["d_kimlik"], ensure_ascii=False, default=str))

json.dump(rep, open(f"{OUT}/s4_demo.json", "w"), ensure_ascii=False, indent=1, default=str)
open(f"{OUT}/s4_demo_cikti.txt", "w").write("\n".join(lines) + "\n")

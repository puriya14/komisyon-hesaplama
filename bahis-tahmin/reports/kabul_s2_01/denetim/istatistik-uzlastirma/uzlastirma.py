"""İstatistik uzlaştırma (salt-okunur): yalnızca 01b7e9f'deki yayımlanmış sayılar üzerinde aritmetik.

Girdi: <OUT>/kod/bahis-tahmin (git archive 01b7e9f) içindeki reports/dizi_sonuclar.json,
reports/dizi_f1_hipotezler.csv, reports/experiments.jsonl ve kaynak kod (satır numaraları için).
Maç verisi / ham veri AÇILMAZ; sonuçlardan yeniden istatistik hesaplanmaz.

Çalıştırma:  PYTHONDONTWRITEBYTECODE=1 /home/user/venv-bahis/bin/python -I uzlastirma.py <OUT>
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import beta, norm, binom

OUT = Path(sys.argv[1])
K = OUT / "kod" / "bahis-tahmin"
REP = K / "reports"
J = json.loads((REP / "dizi_sonuclar.json").read_text(encoding="utf-8"))
CSV = pd.read_csv(REP / "dizi_f1_hipotezler.csv")
F1 = J["aileler"]["F1"]
F7 = J["aileler"]["F7"]
MAN = J["manifest"]
R = int(F1["R"])
ALPHA = 0.05
NUM: dict = {}  # tüm hesaplanan sayılar (hesap_ciktisi.json)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


NUM["girdi_sha256"] = {p.name: sha(p) for p in (REP / "dizi_sonuclar.json", REP / "dizi_f1_hipotezler.csv",
                                                 REP / "experiments.jsonl")}


def find_line(rel: str, pattern: str, nth: int = 1) -> str:
    """Kaynak dosyada regex'in nth eşleştiği satır → 'dosya:satır'."""
    lines = (K / rel).read_text(encoding="utf-8").splitlines()
    k = 0
    for i, ln in enumerate(lines, 1):
        if re.search(pattern, ln):
            k += 1
            if k == nth:
                return f"{rel}:{i}"
    raise SystemExit(f"desen bulunamadı: {rel} {pattern}")


# ----------------------------------------------------------------------------
# Tanımlar (features.history_atoms / context_atoms / frame.target_outcomes)
# ----------------------------------------------------------------------------
ATOM_TR = {
    "SON5_GALIBIYET_EN_AZ_4": ("takımın aynı dilimdeki son 5 lig maçının en az 4'ünü kazanmış olması "
                               "(5 maçın MS sonucu bilinmeli, pencere tam)",
                               find_line("bahis_tahmin/sequences/features.py", r'a\["SON5_GALIBIYET_EN_AZ_4"\]')),
    "SON5_IY_ONDE_EN_AZ_3": ("takımın son 5 lig maçının en az 3'ünde ilk yarıyı önde kapatmış olması "
                             "(5 maçın İY sonucu bilinmeli)",
                             find_line("bahis_tahmin/sequences/features.py", r'a\["SON5_IY_ONDE_EN_AZ_3"\]')),
    "FORM_BEKLENTI_USTU": ("son 10 maçta Σ(puan − kalibre S0 beklenen puan) ≥ +4 (FORM_DIFF=4; 10 maçın MS'si ve "
                           "S0 beklenen puanı mevcut olmalı)",
                           find_line("bahis_tahmin/sequences/features.py", r'a\["FORM_BEKLENTI_USTU"\]')),
    "RAKIP_SON5_IY_ONDE_EN_AZ_3": ("RAKİBİN kendi son 5 lig maçının en az 3'ünde ilk yarıyı önde kapatmış olması "
                                   "(rakip satırının SON5_IY_ONDE_EN_AZ_3 değeri)",
                                   find_line("bahis_tahmin/sequences/features.py",
                                             r'a\["RAKIP_SON5_IY_ONDE_EN_AZ_3"\]')),
    "FAVORI": ("bağlam: kalibre S0 galibiyet olasılığı ≥ 0,55",
               find_line("bahis_tahmin/sequences/features.py", r'"FAVORI": np.where')),
    "EV_SAHIBI": ("bağlam: takım ev sahibi",
                  find_line("bahis_tahmin/sequences/features.py", r'"EV_SAHIBI": tm\["is_home"\]')),
}
TARGET_TR = {"GALIBIYET": "takım maçı kazanır (MS G)", "MAGLUBIYET": "takım maçı kaybeder (MS M)",
             "IY_GERIDE_MS_GALIP": "takım İY geride, MS galip", "IY_ONDE_MS_MAGLUP": "takım İY önde, MS mağlup"}
TARGET_LINE = find_line("bahis_tahmin/sequences/frame.py", r'for t, r in \(\("GALIBIYET", 0\)')


def plain(hyp: str) -> str:
    t, cond = hyp.split("|", 1)
    atoms = [a.strip() for a in cond.split("&")]
    return (f"Hedef: {TARGET_TR[t]}. Koşul: " + " VE ".join(ATOM_TR[a][0] for a in atoms) + ".")


def refs(hyp: str) -> str:
    t, cond = hyp.split("|", 1)
    return "; ".join([ATOM_TR[a.strip()][1] for a in cond.split("&")] + [TARGET_LINE])


# ----------------------------------------------------------------------------
# 1) Aday + EXPLORATORY tablosu
# ----------------------------------------------------------------------------
u = CSV[CSV["tekil"]].set_index("hyp_id")
sig = u[(u["supported"]) & (u["p_adj"] < ALPHA) & (u["ci_hi"] < ALPHA)]
cands = {c["hyp_id"]: c for c in F1["adaylar"]}
assert len(sig) == F1["wy_anlamli"] == 8, len(sig)
expl = [h for h in sig.index if u.at[h, "statu"] == "EXPLORATORY"]
order = [c["hyp_id"] for c in sorted(F1["adaylar"], key=lambda c: c["sira"])] + sorted(
    expl, key=lambda h: u.at[h, "p_adj"])

# Aday seçimi yeniden kurulumu (patterns.select_candidates; yayımlanan lift/aralıklarla)
ref = pd.DataFrame(F1["baglam_tanilama"])
singles = {}
for src in (CSV, ref):
    for t, cond, lift in zip(src["target"], src["condition"], src["lift"]):
        at = [a.strip() for a in cond.split("&")]  # koşul adı 'A & B' (patterns.PAIR_SEP)
        if len(at) == 1:
            singles.setdefault((t, at[0]), float(np.log(lift)))
sel_rows = []
for h in sig.index:
    t, at = u.at[h, "target"], [a.strip() for a in u.at[h, "condition"].split("&")]
    ll = float(np.log(u.at[h, "lift"]))
    if len(at) == 1:
        pair_ok, pair_note = True, "tek atom (çift kuralı uygulanmaz)"
    else:
        ok, notes = True, []
        for a in at:
            s = singles[(t, a)]
            good = abs(ll) > abs(s) and (s == 0 or np.sign(s) == np.sign(ll))
            ok &= good
            notes.append(f"{a}: log O/E {s:+.4f}")
        pair_ok, pair_note = ok, f"çift log O/E {ll:+.4f} vs " + ", ".join(notes)
    lift, lo, hi = u.at[h, "lift"], u.at[h, "lift_lo"], u.at[h, "lift_hi"]
    lcb = math.log(lo) if lift >= 1 else -math.log(hi)
    sel_rows.append({"hyp_id": h, "target": t, "atoms": at, "pair_ok": pair_ok, "pair_note": pair_note, "lcb": lcb})
sel = pd.DataFrame(sel_rows).sort_values(["lcb", "hyp_id"], ascending=[False, True])
used, chosen, why_not = set(), [], {}
for _, r in sel.iterrows():
    if not r["pair_ok"]:
        why_not[r["hyp_id"]] = "çift kuralı"
        continue
    if len(chosen) >= 5:
        why_not[r["hyp_id"]] = "aday sınırı (5)"
        continue
    clash = [a for a in r["atoms"] if (r["target"], a) in used]
    if clash:
        blockers = [c[0] for c in chosen if c[2] == r["target"] and any(a in c[1] for a in clash)]
        why_not[r["hyp_id"]] = (f"aynı hedefte ortak atom ({', '.join(clash)}) — daha yüksek LCB'li seçilmiş aday(lar): "
                                + " + ".join(blockers))
        continue
    chosen.append((r["hyp_id"], tuple(r["atoms"]), r["target"]))
    used.update((r["target"], a) for a in r["atoms"])
assert [c[0] for c in chosen] == [c["hyp_id"] for c in sorted(F1["adaylar"], key=lambda c: c["sira"])], chosen
sel["lcb_sira"] = np.arange(1, len(sel) + 1)
sel["secim_sonucu"] = [("ADAY sıra " + str([c[0] for c in chosen].index(h) + 1)) if h in [c[0] for c in chosen]
                       else why_not[h] for h in sel["hyp_id"]]
sel[["lcb_sira", "hyp_id", "lcb", "pair_ok", "pair_note", "secim_sonucu"]].to_csv(OUT / "aday_secimi_yeniden.csv",
                                                                                   index=False)

FCHK = ("1_birim_cikarma", "2_ust_yuzde1_cikarma", "3_sezon_yonu", "4_eslestirilmis", "5_piyasa")


def first_fail_and_all(c: dict) -> tuple[str, str]:
    fails = []
    if not c["parametre"]["gecti"]:
        fails.append("parametre Holm")
    if "test" in c and not c["test"]["gecti"]:
        fails.append("test Holm")
    g = c.get("gosterge", {})
    if g.get("durum") == "OK" and not g["fark"]["ci_hi"] < 0:
        fails.append("test ΔLL üst sınır ≥ 0")
    for per in ("parametre", "test"):
        f = c["yanlislama"].get(per, {})
        for k in FCHK:
            if f.get("checks", {}).get(k, {}).get("passed") is not True:
                fails.append(f"7b/{k[0]} {per}")
    return c["gerekce"], "; ".join(fails)


rows = []
for h in order:
    r = u.loc[h]
    rec = {
        "hyp_id": h, "rol": (f"ADAY (sıra {cands[h]['sira']})" if h in cands else "EXPLORATORY (aday değil)"),
        "hedef": r["target"], "kosul": r["condition"], "tur": r["kind"], "tanim": plain(h), "tanim_kod": refs(h),
        "yon": ("−1 (daha az)" if r["lift"] < 1 else "+1 (daha çok)"),
        "referans": "katmanlı S0 beklentisi E_adj = Σ p_i·r_s (katman: taraf×lig×p0 beşlisi; dönem içinde)",
        "kesif_n": int(r["n"]), "kesif_olay_O": r["O"], "kesif_E_adj": r["E_adj"], "kesif_E_ham_S0": r["E_raw"],
        "kesif_OE": r["lift"], "kesif_OE_lo95": r["lift_lo"], "kesif_OE_hi95": r["lift_hi"], "kesif_z": r["z"],
        "kesif_V": r["V"], "kesif_G_kume": int(r["G"]),
        "wy_p_adj": r["p_adj"], "wy_c_sayim": int(round(r["p_adj"] * (R + 1) - 1)),
        "wy_mc99_lo": r["ci_lo"], "wy_mc99_hi": r["ci_hi"], "by_p_tanimlayici": r["p_by_tanimlayici"],
        "aday_secimi": sel.set_index("hyp_id").at[h, "secim_sonucu"],
    }
    if h in cands:
        c = cands[h]
        for per in ("parametre", "test"):
            e = c[per]
            rec.update({f"{per}_n": e["n"], f"{per}_olay_O": e["O"], f"{per}_E_adj": e["E_adj"],
                        f"{per}_E_ham_S0": e["E_raw"], f"{per}_OE": e["lift"], f"{per}_OE_lo95": e["lift_lo"],
                        f"{per}_OE_hi95": e["lift_hi"], f"{per}_z": e["z"], f"{per}_p_tek": e["p_tek"],
                        f"{per}_p_holm_k4": e["p_holm"], f"{per}_holm_gecti": e["gecti"]})
        g = c["gosterge"]
        rec.update({
            "ll_egitim_n": g["n_egitim"], "ll_test_n": g["n_test"], "ll_test_kosul_n": g["n_test_kosul"],
            "egitim_son_tarih": g["egitim_son_tarih"], "beta_gosterge_logodds": g["gosterge_log_odds"],
            "sabit_gosterge_modeli": g["uyum"]["sabit"], "sabit_S0_sabit_modeli": g["uyum_sabit"]["sabit"],
            "ll_S0_ham": g["ll_s0"], "ll_S0_sabit": g["ll_s0_sabit"], "ll_S0_sabit_gosterge": g["ll_s0_gosterge"],
            "dLL_aday_eksi_ref": g["fark"]["diff"], "dLL_boot95_lo": g["fark"]["ci_lo"],
            "dLL_boot95_hi": g["fark"]["ci_hi"], "dLL_boot_se": g["fark"]["se"],
            "dLL_p_tek_normal": g["fark"]["p_one_sided"], "dLL_p_boot": g["fark"]["p_boot"],
            "dLL_boot_kume_lig_sezon": g["fark"]["n_clusters"], "dLL_boot_tekrar": g["fark"]["reps"],
            "dLL_isohafta95_lo": g["iso_hafta"]["ci_lo"], "dLL_isohafta95_hi": g["iso_hafta"]["ci_hi"],
            "dLL_isohafta_p_tek": g["iso_hafta"]["p_one_sided"], "dLL_isohafta_kume": g["iso_hafta"]["n_clusters"],
            "dLL_hamS0_fark": g["fark_ham_s0"]["diff"], "dLL_hamS0_lo": g["fark_ham_s0"]["ci_lo"],
            "dLL_hamS0_hi": g["fark_ham_s0"]["ci_hi"],
        })
        for per in ("parametre", "test"):
            ch = c["yanlislama"][per]["checks"]
            rec[f"7b_{per}"] = " ".join(f"{k[0]}:{'G' if ch[k]['passed'] else 'K'}" for k in FCHK)
            rec[f"7b2_{per}_OE_aralik"] = (f"{ch['2_ust_yuzde1_cikarma']['lift']:.4f} "
                                          f"[{ch['2_ust_yuzde1_cikarma']['lift_lo']:.4f}; "
                                          f"{ch['2_ust_yuzde1_cikarma']['lift_hi']:.4f}]")
            rec[f"7b3_{per}_pay"] = f"{ch['3_sezon_yonu']['ayni_yon']}/{ch['3_sezon_yonu']['n_sezon']}"
            rec[f"7b5_{per}_S0p_OE_aralik"] = (f"{ch['5_piyasa']['lift']:.4f} [{ch['5_piyasa']['lift_lo']:.4f}; "
                                              f"{ch['5_piyasa']['lift_hi']:.4f}]")
        rec["statu"] = c["statu"]
        rec["gerekce_kayitli_ilk_basarisiz"], rec["tum_basarisiz_kontroller"] = first_fail_and_all(c)
    else:
        rec["parametre_n"] = rec["test_n"] = "kayıt yok (örneklem dışı değerlendirilmedi)"
        rec["statu"] = r["statu"]
        rec["gerekce_kayitli_ilk_basarisiz"] = r["gerekce"]
        rec["tum_basarisiz_kontroller"] = "uygulanmadı (aday değil)"
    rows.append(rec)
AD = pd.DataFrame(rows)
AD.to_csv(OUT / "adaylar.csv", index=False)

# ----------------------------------------------------------------------------
# 2) ΔLL uzlaştırması
# ----------------------------------------------------------------------------
C4 = [cands[h] for h in order[:4]]
d = np.array([c["gosterge"]["fark"]["diff"] for c in C4])
lo = np.array([c["gosterge"]["fark"]["ci_lo"] for c in C4])
hi = np.array([c["gosterge"]["fark"]["ci_hi"] for c in C4])
inc0 = (lo <= 0) & (hi >= 0)
dll = pd.DataFrame({"hyp_id": order[:4], "dLL": d, "ci_lo": lo, "ci_hi": hi, "ci_sifiri_iceriyor": inc0,
                    "n_test": [c["gosterge"]["n_test"] for c in C4],
                    "n_test_kosul": [c["gosterge"]["n_test_kosul"] for c in C4],
                    "ll_S0_sabit": [c["gosterge"]["ll_s0_sabit"] for c in C4]})
dll["goreli_iyilesme_yuzde"] = -dll["dLL"] / dll["ll_S0_sabit"] * 100
dll["kosul_satiri_basina_olcek"] = dll["dLL"] * dll["n_test"] / dll["n_test_kosul"]
dll.to_csv(OUT / "dll_uzlastirma.csv", index=False)
NUM["dLL"] = {"degerler": d.tolist(), "ortalama": float(d.mean()), "ortanca": float(np.median(d)),
              "min": float(d.min()), "max": float(d.max()), "ci_sifiri_iceren": int(inc0.sum()),
              "ci_sifiri_icerenlerin_ortalamasi": float(d[inc0].mean()),
              "goreli_iyilesme_yuzde": dll["goreli_iyilesme_yuzde"].tolist()}

# ----------------------------------------------------------------------------
# 3) Çoklu test (4 test-değerlendirilen aday) + büyüklük
# ----------------------------------------------------------------------------


def holm(p):
    p = np.asarray(p, float)
    m = len(p)
    o = np.argsort(p, kind="mergesort")
    adj = np.empty(m)
    adj[o] = np.minimum(1, np.maximum.accumulate((m - np.arange(m)) * p[o]))
    return adj


mt = []
for name, key in (("p_tek_normal (Φ(d/se))", lambda g: g["fark"]["p_one_sided"]),
                  ("p_boot ((1+#boot≥0)/1001)", lambda g: g["fark"]["p_boot"]),
                  ("ISO-hafta p_tek_normal", lambda g: g["iso_hafta"]["p_one_sided"]),
                  ("ham S0'a göre p_tek_normal", lambda g: g["fark_ham_s0"]["p_one_sided"])):
    p = np.array([key(c["gosterge"]) for c in C4])
    ho, bo = holm(p), np.minimum(1, p * 4)
    for h, pi, a, b in zip(order[:4], p, ho, bo):
        mt.append({"p_turu": name, "hyp_id": h, "p": pi, "holm_k4": a, "bonferroni_k4": b,
                   "holm_lt_0_05": a < ALPHA, "bonf_lt_0_05": b < ALPHA})
MT = pd.DataFrame(mt)
MT.to_csv(OUT / "coklu_test_dll.csv", index=False)
NUM["dLL_coklu_test"] = MT.to_dict(orient="records")

mag = []
for c in C4:
    g, te = c["gosterge"], c["test"]
    b = g["gosterge_log_odds"]
    p_adj_rate = te["E_adj"] / te["n"]
    p_raw_rate = te["E_raw"] / te["n"]
    shift_c = g["uyum"]["sabit"] + b - g["uyum_sabit"]["sabit"]
    shift_n = g["uyum"]["sabit"] - g["uyum_sabit"]["sabit"]
    s0p = c["yanlislama"]["test"]["checks"]["5_piyasa"]
    rec = {"hyp_id": c["hyp_id"], "beta": b, "taban_oran_E_adj_n": p_adj_rate, "taban_oran_ham_S0": p_raw_rate,
           "dp_beta": p_adj_rate * (1 - p_adj_rate) * b,
           "net_logit_kayma_kosul": shift_c, "net_logit_kayma_kosul_disi": shift_n,
           "dp_net_kosul": p_adj_rate * (1 - p_adj_rate) * shift_c,
           "gozlenen_dp_test_(O-Eadj)/n": (te["O"] - te["E_adj"]) / te["n"],
           "S0p_kontrollu_OE_test": s0p["lift"], "S0p_kontrollu_OE_lo": s0p["lift_lo"],
           "S0p_kontrollu_OE_hi": s0p["lift_hi"],
           "S0p_kontrollu_dp_yaklasik": (s0p["lift"] - 1) * te["O"] / s0p["lift"] / s0p["n"]}
    for m in (0.03, 0.05, 0.08):
        rec[f"marj_payi_bu_yon_m{int(m*100)}"] = p_adj_rate * m          # takım kazanır tarafı (p·m)
        rec[f"marj_payi_karsi_yon_m{int(m*100)}"] = (1 - p_adj_rate) * m  # takım kazanmaz tarafı ((1−p)·m)
    mag.append(rec)
MAG = pd.DataFrame(mag)
MAG.to_csv(OUT / "buyukluk.csv", index=False)
NUM["buyukluk"] = MAG.to_dict(orient="records")

# ----------------------------------------------------------------------------
# 4) z_crit ve MDE
# ----------------------------------------------------------------------------
S = u[u["supported"]].copy()
S["az"] = S["z"].abs()
S = S.sort_values("az", ascending=False)
above = S[S["p_adj"] < ALPHA]
below = S[S["p_adj"] >= ALPHA]
z1, p1 = float(above["az"].iloc[-1]), float(above["p_adj"].iloc[-1])   # son p<0,05 (sıra 8)
z2, p2 = float(below["az"].iloc[0]), float(below["p_adj"].iloc[0])     # ilk p≥0,05 (sıra 9)
zc_log = z2 + (math.log(p2) - math.log(ALPHA)) / (math.log(p2) - math.log(p1)) * (z1 - z2)
zc_lin = z2 + (p2 - ALPHA) / (p2 - p1) * (z1 - z2)
fit = S[(S["p_adj"] > 0.005) & (S["p_adj"] < 0.5)]
A = np.column_stack([np.ones(len(fit)), fit["az"] ** 2])
coef, *_ = np.linalg.lstsq(A, np.log(fit["p_adj"]), rcond=None)
zc_fit = math.sqrt((math.log(ALPHA) - coef[0]) / coef[1])
ZC = pd.DataFrame([
    {"yontem": "log p doğrusal ara değer (sıra 8 ↔ 9) [BİRİNCİL]", "z_crit": zc_log,
     "not": f"|z| {z1:.4f} (p_adj {p1:.6f}) ile |z| {z2:.4f} (p_adj {p2:.6f}) arasında"},
    {"yontem": "p doğrusal ara değer (sıra 8 ↔ 9)", "z_crit": zc_lin, "not": "duyarlılık"},
    {"yontem": "log p ~ a + b·z² EKK uyumu (0,005<p_adj<0,5)", "z_crit": zc_fit,
     "not": f"n={len(fit)} desteklenen tekil hipotez; a={coef[0]:.4f}, b={coef[1]:.4f}"},
    {"yontem": "parantez (alt/üst)", "z_crit": float("nan"), "not": f"[{z2:.4f}, {z1:.4f}]"},
    {"yontem": "karşılaştırma: Bonferroni m=430 (iki yönlü)", "z_crit": float(norm.isf(ALPHA / 2 / 430)),
     "not": "bağımsızlık/normal varsayımı; WY değil"},
    {"yontem": "karşılaştırma: Bonferroni m=780 (iki yönlü)", "z_crit": float(norm.isf(ALPHA / 2 / 780)),
     "not": "bağımsızlık/normal varsayımı; WY değil"},
    {"yontem": "karşılaştırma: m=430 bağımsız normal |z| maksimumunun ortancası", "z_crit":
        float(norm.isf((1 - 0.5 ** (1 / 430)) / 2)), "not": f"yayımlanan referans ortanca {F1['referans_ozeti']['null_max_abs_z_medyan']:.4f}"},
])
ZC.to_csv(OUT / "zcrit.csv", index=False)
NUM["zcrit"] = ZC.to_dict(orient="records")
zp = {"50": 0.0, "80": float(norm.ppf(0.80))}
M = S[["target", "condition", "kind", "n", "O", "E_raw", "E_adj", "V", "z", "lift", "p_adj"]].copy()
M["se_rel"] = np.sqrt(M["V"]) / M["E_adj"]
for k, zpv in zp.items():
    M[f"mde_goreli_g{k}"] = (zc_log + zpv) * M["se_rel"]
    M[f"mde_OE_ust_g{k}"] = 1 + M[f"mde_goreli_g{k}"]
    M[f"mde_OE_alt_g{k}"] = (1 - M[f"mde_goreli_g{k}"]).clip(lower=0)
    for nm, zc in (("lin", zc_lin), ("fit", zc_fit)):
        M[f"mde_goreli_g{k}_{nm}"] = (zc + zpv) * M["se_rel"]
M.reset_index().to_csv(OUT / "mde_hipotez.csv", index=False)
summ = []
for t in ("IY_GERIDE_MS_GALIP", "IY_ONDE_MS_MAGLUP", "GALIBIYET", "MAGLUBIYET"):
    a = M[M["target"] == t]
    uu = u[u["target"] == t]
    rec = {"hedef": t, "tekil": len(uu), "desteklenen": len(a), "E_adj_ortanca": a["E_adj"].median(),
           "n_ortanca": a["n"].median(), "max_abs_z_gozlenen": a["z"].abs().max()}
    for k in zp:
        x = a[f"mde_goreli_g{k}"]
        rec.update({f"g{k}_min_%": 100 * x.min(), f"g{k}_ortanca_%": 100 * x.median(), f"g{k}_max_%": 100 * x.max(),
                    f"g{k}_OE_ust_ortanca": 1 + x.median(), f"g{k}_OE_alt_ortanca": max(0.0, 1 - x.median()),
                    f"g{k}_alt_tarafta_tespit_edilemez_(mde>=1)": int((x >= 1).sum())})
    rec["g80_ortanca_%_zc_lin"] = 100 * a["mde_goreli_g80_lin"].median()
    rec["g80_ortanca_%_zc_fit"] = 100 * a["mde_goreli_g80_fit"].median()
    summ.append(rec)
MS = pd.DataFrame(summ)
MS.to_csv(OUT / "mde_hedef_ozet.csv", index=False)
NUM["mde_ozet"] = MS.to_dict(orient="records")
# adayların gözlenen etkisi vs keşif MDE'si
NUM["aday_gozlenen_vs_mde80"] = {h: {"gozlenen_|OE-1|": abs(u.at[h, "lift"] - 1),
                                     "mde80": float(M.at[h, "mde_goreli_g80"])} for h in order}

# ----------------------------------------------------------------------------
# 5) Yeniden örnekleme sayıları ve p formülü
# ----------------------------------------------------------------------------
CF = "bahis_tahmin/sequences/config.py"
NL = "bahis_tahmin/sequences/null.py"
RS = "bahis_tahmin/sequences/research.py"
MD_ = "bahis_tahmin/sequences/models.py"
CL = "bahis_tahmin/cli.py"
RD = "tools/research/run_dizi.py"
RM = [
    {"kavram": "R_inner (F1 WY ailesi başına referans tekrarı)", "deger": 1000,
     "kod": "; ".join([find_line(CF, r"^N_NULL = 1000"), find_line(CL, r'add_argument\("--R"'),
                       find_line(RD, r'add_argument\("--R"'), find_line(RS, r"def run_research"),
                       find_line(RS, r"null = parallel_null_q1\(fr, disc, R, seed"),
                       find_line(NL, r"def run_null\(fr, mask, R: int = C.N_NULL")]),
     "manifest": f"manifest.R={MAN['R']}; F1.R={F1['R']}",
     "not": "CLI varsayılanı sabit 1000 (config'e bağlı değil); run_dizi.py config.N_NULL'u okur; tohum 20261010"},
    {"kavram": "R_inner (F2 Sorgu 2 WY ailesi)", "deger": 1000,
     "kod": find_line(RS, r"null = parallel_null_q2\(fr, disc, R, seed \+ 2"),
     "manifest": f"F2.R={J['aileler']['F2']['R']}", "not": "aynı R, tohum seed+2"},
    {"kavram": "R_outer (plasebo tohum sayısı)", "deger": 20,
     "kod": "; ".join([find_line(CF, r"^N_PLACEBO_SEEDS = 20"), find_line(CL, r'add_argument\("--plasebo-tohum"'),
                       find_line(RD, r'add_argument\("--plasebo-tohum"'),
                       find_line(RS, r"placebo_seeds: int = C.N_PLACEBO_SEEDS"),
                       find_line(RS, r"\[seed \+ 1000 \+ k for k in range\(placebo_seeds\)\]")]),
     "manifest": f"manifest.plasebo.tohum_sayisi={MAN['plasebo']['tohum_sayisi']}; F7.n_seeds={F7['n_seeds']}",
     "not": "tohumlar 20262010…20262029 (seed+1000+k)"},
    {"kavram": "plasebo iç R (tohum başına referans tekrarı)", "deger": 200,
     "kod": "; ".join([find_line(CF, r"^N_NULL_PLACEBO = 200"), find_line(CL, r'add_argument\("--plasebo-R"'),
                       find_line(RD, r'add_argument\("--plasebo-R"'),
                       find_line(RS, r"R_placebo: int = C.N_NULL_PLACEBO"),
                       find_line(NL, r"def run_placebo\(fr, mask, seeds=None, R: int = C.N_NULL_PLACEBO")]),
     "manifest": f"manifest.plasebo.R={MAN['plasebo']['R']}; F7.R={F7['R']}",
     "not": "toplam plasebo tam araması 20 × 200 = 4000 (+20 gözlenen)"},
    {"kavram": "plasebo geçme sınırı", "deger": 1,
     "kod": "; ".join([find_line(CF, r"^PLACEBO_MAX_DISCOVERIES = 1"),
                       find_line(RS, r'"passed": n_with <= C.PLACEBO_MAX_DISCOVERIES')]),
     "manifest": f"F7.passed={F7['passed']}; n_seeds_with_discovery={F7['n_seeds_with_discovery']}", "not": ""},
    {"kavram": "bootstrap tekrarı (ΔLL; lig-sezon ve ISO-hafta kümeli)", "deger": 1000,
     "kod": "; ".join([find_line(MD_, r"^MIN_BOOT = 1000"), find_line(MD_, r"if reps < MIN_BOOT"),
                       find_line(RS, r"n_boot: int = 1000, progress"),
                       find_line(RS, r"def indicator_dll"), find_line(RS, r"d = M.cluster_bootstrap_diff\(l1, l0")]),
     "manifest": f"manifest.bootstrap={MAN['bootstrap']}; adaylar.gosterge.fark.reps="
                 f"{sorted({c['gosterge']['fark']['reps'] for c in C4})}",
     "not": "CLI'da bootstrap bayrağı yok (run_research varsayılanı); her aday için aynı tohum 20261010"},
    {"kavram": "MC aralık düzeyi (WY p_adj için Clopper–Pearson)", "deger": 0.99,
     "kod": "; ".join([find_line(CF, r"^MC_CI_LEVEL = 0.99"), find_line(NL, r"def clopper_pearson")]),
     "manifest": "-", "not": "c/R üzerinde iki yönlü %99"},
    {"kavram": "WY p formülü", "deger": "(c+1)/(R+1)",
     "kod": "; ".join([find_line(NL, r"counts = \(q >= np.abs\(z_obs\[order\]\)"),
                       find_line(NL, r"counts = np.maximum.accumulate\(counts\)"),
                       find_line(NL, r"p_adj\[order\] = \(counts \+ 1.0\) / \(R \+ 1.0\)"),
                       find_line(NL, r"l, h = clopper_pearson\(counts, R\)")]),
     "manifest": "-", "not": "|z| maxT (iki yönlü), adım adım azalan; gözlenen-desteklenmeyen ama tekrarda desteklenen "
                            "hipotezler her adımın maksimumuna girer (muhafazakâr)"},
    {"kavram": "F1 keşif kuralı (katı)", "deger": "supported ∧ p_adj<0,05 ∧ MC99_üst<0,05",
     "kod": find_line(RS, r'sig = uniq\["supported"\].astype\(bool\) & \(uniq\["p_adj"\] < C.ALPHA\)'),
     "manifest": f"F1.wy_anlamli={F1['wy_anlamli']}", "not": ""},
    {"kavram": "F7 keşif kuralı (gevşek)", "deger": "p_adj<0,05 (MC üst sınırı ŞART DEĞİL)",
     "kod": "; ".join([find_line(NL, r"disc = np.nan_to_num\(p_adj, nan=1.0\) < C.ALPHA"),
                       find_line(NL, r"strict = disc & ")]),
     "manifest": "F7.seeds[*].n_discoveries / n_discoveries_strict",
     "not": "katı sayı yalnızca raporlanır; geçme kuralı gevşek sayıyı kullanır (plasebo için daha zor ölçüt)"},
]
RMD = pd.DataFrame(RM)
RMD.to_csv(OUT / "yeniden_ornekleme.csv", index=False)

# Clopper–Pearson eşikleri


def cp_hi(c, n, level=0.99):
    return float(beta.ppf(1 - (1 - level) / 2, c + 1, n - c)) if c < n else 1.0


cp_rows = []
for RR in (1000, 200):
    cmax = max(c for c in range(0, RR) if cp_hi(c, RR) < ALPHA)
    cp_rows.append({"R": RR, "en_buyuk_c_CP99_ust<0,05": cmax, "CP99_ust(cmax)": cp_hi(cmax, RR),
                    "CP99_ust(cmax+1)": cp_hi(cmax + 1, RR), "p_adj(cmax)=(c+1)/(R+1)": (cmax + 1) / (RR + 1),
                    "p_adj(cmax+1)": (cmax + 2) / (RR + 1),
                    "en_buyuk_c_p_adj<0,05": max(c for c in range(RR) if (c + 1) / (RR + 1) < ALPHA),
                    "min_p_adj=1/(R+1)": 1 / (RR + 1)})
CP = pd.DataFrame(cp_rows)
CP.to_csv(OUT / "cp_esikler.csv", index=False)
NUM["cp"] = CP.to_dict(orient="records")
# yayımlanan p_adj ızgarası ve ci_hi = CP(c, 1000) doğrulaması
cc = np.round(S["p_adj"] * (R + 1) - 1).astype(int)
grid_ok = np.allclose(S["p_adj"], (cc + 1) / (R + 1), atol=1e-12)
cphi = np.array([cp_hi(c, R) for c in cc])
cplo = np.array([float(beta.ppf(0.005, c, R - c + 1)) if c > 0 else 0.0 for c in cc])
NUM["wy_yeniden_uretim"] = {"n": int(len(S)), "p_adj_izgarada": bool(grid_ok),
                            "ci_hi_max_mutlak_fark": float(np.max(np.abs(cphi - S["ci_hi"]))),
                            "ci_lo_max_mutlak_fark": float(np.max(np.abs(cplo - S["ci_lo"]))),
                            "c_8_hipotez": {h: int(round(u.at[h, 'p_adj'] * (R + 1) - 1)) for h in sig.index}}

# ----------------------------------------------------------------------------
# 6) 0/20 plasebo sınırları
# ----------------------------------------------------------------------------
n_s = F7["n_seeds"]
k_s = F7["n_seeds_with_discovery"]
mins = np.array([s["min_p_adj"] for s in F7["seeds"]])
c_min = int(round(mins.min() * (F7["R"] + 1) - 1))
pl = {
    "k/n": f"{k_s}/{n_s}",
    "tek_yonlu_kesin_%95_ust": 1 - 0.05 ** (1 / n_s),
    "iki_yonlu_CP_%95_ust": float(beta.ppf(0.975, k_s + 1, n_s - k_s)),
    "uc_kurali_3/n": 3 / n_s,
    "P(0/20 | p=0,05)": float(binom.pmf(0, n_s, 0.05)),
    "P(<=1/20 | p=0,05) (gecme olasiligi, kalibre surec)": float(binom.cdf(1, n_s, 0.05)),
    "P(gecme | p=0,10)": float(binom.cdf(1, n_s, 0.10)),
    "P(gecme | p=0,15)": float(binom.cdf(1, n_s, 0.15)),
    "P(gecme | p=0,20)": float(binom.cdf(1, n_s, 0.20)),
    "n_etkin_duyarlilik_tek_yonlu_ust": {str(ne): 1 - 0.05 ** (1 / ne) for ne in (20, 10, 5, 2, 1)},
    "min_p_adj_tohumlar": mins.tolist(),
    "min_p_adj_en_kucuk": float(mins.min()), "c_en_kucuk": c_min,
    "min_p_adj_ortalama": float(mins.mean()), "min_p_adj_ortanca": float(np.median(mins)),
    "P(20 tohumun hepsinde p_adj>=gozlenen en kucuk | bagimsiz, ayrik-uniform)":
        ((F7["R"] + 1 - c_min) / (F7["R"] + 1)) ** n_s,
    "n_supported_tohum_araligi": [min(s["n_supported"] for s in F7["seeds"]),
                                  max(s["n_supported"] for s in F7["seeds"])],
    "n_discoveries_strict_toplam": int(sum(s["n_discoveries_strict"] for s in F7["seeds"])),
}
NUM["plasebo"] = pl
pd.DataFrame([{"olcu": k, "deger": json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v}
              for k, v in pl.items()]).to_csv(OUT / "plasebo_sinirlar.csv", index=False)

# ----------------------------------------------------------------------------
# Yayımlanan sayıların iç tutarlılığı (aritmetik)
# ----------------------------------------------------------------------------
chk = {}
allrec = []
for h in order:
    r = u.loc[h]
    allrec.append(("kesif", h, r["O"], r["E_adj"], r["V"], r["z"], r["lift"], r["lift_lo"], r["lift_hi"]))
for c in C4:
    for per in ("parametre", "test"):
        e = c[per]
        allrec.append((per, c["hyp_id"], e["O"], e["E_adj"], e["V"], e["z"], e["lift"], e["lift_lo"], e["lift_hi"]))
dz = dl = dci = 0.0
for _, h, O, E, V, z, lf, l, hh in allrec:
    dz = max(dz, abs((O - E) / math.sqrt(V) - z))
    dl = max(dl, abs(O / E - lf))
    dci = max(dci, abs(lf - 1.96 * math.sqrt(V) / E - l), abs(lf + 1.96 * math.sqrt(V) / E - hh))
chk["z=T/sqrt(V)_max_fark"] = dz
chk["OE=O/E_adj_max_fark"] = dl
chk["OE_aralik=OE±1,96·sqrt(V)/E_adj_max_fark"] = dci
for per in ("parametre", "test"):
    zz = [c[per]["z"] for c in C4]
    dirs = [c["yon"] for c in C4]
    p1 = norm.sf(np.array(zz) * np.array(dirs))
    chk[f"{per}_holm_max_fark"] = float(np.max(np.abs(holm(p1) - np.array([c[per]["p_holm"] for c in C4]))))
    chk[f"{per}_p_tek_max_fark"] = float(np.max(np.abs(p1 - np.array([c[per]["p_tek"] for c in C4]))))
chk["dLL=ll_gosterge-ll_sabit_max_fark"] = float(max(abs(c["gosterge"]["ll_s0_gosterge"] - c["gosterge"]["ll_s0_sabit"]
                                                       - c["gosterge"]["fark"]["diff"]) for c in C4))
chk["dLL_p_tek=Phi(d/se)_max_fark"] = float(max(abs(norm.cdf(c["gosterge"]["fark"]["diff"] / c["gosterge"]["fark"]["se"])
                                                   - c["gosterge"]["fark"]["p_one_sided"]) for c in C4))
NUM["ic_tutarlilik"] = chk
NUM["f1_sayilar"] = {k: F1[k] for k in ("hipotez_ham", "hipotez_tekil", "ayna_kopyasi_sayisi", "desteklenen_tekil",
                                        "wy_anlamli", "statu_sayilari", "referans_ozeti")}
NUM["iy_hedefleri_max_abs_z_desteklenen"] = {t: float(M[M["target"] == t]["z"].abs().max())
                                             for t in ("IY_GERIDE_MS_GALIP", "IY_ONDE_MS_MAGLUP")}
NUM["iy_hedefleri_max_abs_z_tum_tekil"] = {t: float(u[u["target"] == t]["z"].abs().max())
                                           for t in ("IY_GERIDE_MS_GALIP", "IY_ONDE_MS_MAGLUP")}
(OUT / "hesap_ciktisi.json").write_text(json.dumps(NUM, ensure_ascii=False, indent=1, default=float),
                                        encoding="utf-8")
print(json.dumps(NUM, ensure_ascii=False, indent=1, default=float)[:20000])

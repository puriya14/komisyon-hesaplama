"""Madde 4: sayısal oynamanın (±4,1e-6 ve ±5e-5) karar katmanına etkisi — yalnızca altın (sentetik) olasılıklar + sentetik oranlar.

Kullanılan kod (01b7e9f, değiştirilmeden içe aktarılır): goals.decision (decide, DecisionPolicy, apply_concentration),
goals.service.decisions_for (uygulamanın 6 seçim + yoğunlaşma akışı), goals.engine.GoalPrediction (EVET/HAYIR tarafı
olasılık ve aralık eşlemesi), goals.value (fair_odds, min_required_odds, expected_value, breakeven_probability).
Gerçek maç sonucu KULLANILMAZ. Oranlar sentetiktir (eşik çevresinde kurulmuştur).

Kullanım: python karar_etkisi.py <kod_kökü(bahis-tahmin)> <çıktı_klasörü>
"""
from __future__ import annotations

import datetime as dt
import itertools
import json
import math
import sys
import time

import numpy as np
import pandas as pd

root, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, root)
from bahis_tahmin.goals.decision import Assessment, DecisionPolicy, decide  # noqa: E402
from bahis_tahmin.goals.engine import GoalPrediction  # noqa: E402
from bahis_tahmin.goals.markets import MARKETS, PRIMARY_YES  # noqa: E402
from bahis_tahmin.goals.service import SELECTIONS, decisions_for  # noqa: E402
from bahis_tahmin.goals.value import (OddsQuote, breakeven_probability, expected_value, fair_odds,  # noqa: E402
                                      min_required_odds)

t_start = time.time()
POL = DecisionPolicy()
assert POL.commission == 0.0
T0 = dt.datetime(2026, 10, 10, 12, 0, tzinfo=dt.timezone.utc)
KO = T0 + dt.timedelta(days=1)
QT = T0 - dt.timedelta(minutes=5)
DELTAS = (4.1e-6, 5e-5)
DELTA_NUM = 5e-5  # önerilen bayrak bandı = altın testin TOL'u (aşağıdaki gerekçe)
SHORT = {"BTTS_BOTH_HALVES_YES": "A", "FT_OVER_3_5": "B", "FH_OVER_1_5": "C"}

gold = json.load(open(f"{OUT}/cikti/golden_primary_01b7e9f.json"))
P = {s: np.array(gold["predict"][s], dtype=float) for s in ("A", "B", "C")}
IV = {k: np.array(gold["interval"][k], dtype=float).reshape(-1, 2) for k in PRIMARY_YES}
N_IV = len(IV["BTTS_BOTH_HALVES_YES"])  # 20 satırın aralığı var

# --------------------------------------------------------------------------- senaryolar
SIGNS = list(itertools.product((-1, 1), repeat=3))  # (p, alt uç, üst uç) işaretleri
SCENARIOS = [(scope, d, s) for scope in ("ABC", "A") for d in DELTAS for s in SIGNS]


def yes_side(i, scen=None):
    """i. satırın EVET tarafı (A,B,C) olasılık ve aralıkları; senaryo varsa sarsılmış."""
    probs = {s: float(P[s][i]) for s in ("A", "B", "C")}
    ivs = {k: (float(IV[k][i, 0]), float(IV[k][i, 1])) for k in PRIMARY_YES} if i < N_IV else {}
    if scen is not None:
        scope, d, (sp, sl, sh) = scen
        for k, s in SHORT.items():
            if scope == "A" and s != "A":
                continue
            probs[s] += sp * d
            if k in ivs:
                ivs[k] = (ivs[k][0] + sl * d, ivs[k][1] + sh * d)
    return probs, ivs


def make_pred(i, scen=None) -> GoalPrediction:
    probs, ivs = yes_side(i, scen)
    return GoalPrediction(event_id=f"SENTETIK-{i}", league="SYN", home=f"H{i}", away=f"D{i}", date=pd.Timestamp(KO.date()),
                          time="", kickoff_utc=KO, kickoff_text="", probs=probs, intervals=ivs, base_rates={}, data_notes=[])


def quote(ev_id, key, d) -> OddsQuote:
    m = MARKETS[key]
    return OddsQuote(ev_id, key, m.period, m.line, m.selection, "SENTETIK", "SENTETIK", float(d), QT, QT)


class StubEngine:
    validated = {k: True for k in PRIMARY_YES}  # MODEL_NOT_VALIDATED engeli kaldırılır: ekonomik eşikler görünür olsun


class StubLedger:
    def __init__(self, odds: dict):
        self.odds = odds

    def latest_quote(self, ev_id, key, before):
        d = self.odds.get(key)
        return quote(ev_id, key, d) if d is not None else None


def decide_one(pred: GoalPrediction, key: str, d: float):
    lo, hi = pred.interval(key)
    a = Assessment(event_id=pred.event_id, league="SYN", home=pred.home, away=pred.away, market_key=key, p=pred.p(key),
                   p_low=lo, p_high=hi, model_validated=True, data_notes=[], quote=quote(pred.event_id, key, d),
                   opposite_quote=None, kickoff=KO, match_date=KO.date())
    return decide(a, T0, POL)


def sel_side(pred: GoalPrediction, key):
    lo, hi = pred.interval(key)
    return pred.p(key), lo, hi


def flag(p, lo, hi, d, dn=DELTA_NUM):
    """Önerilen SAYISAL_ESIK_YAKINI bayrağı (durumu DEĞİŞTİRMEZ; gerekçeye bilgi ekler). Vektörel."""
    ev = p * (d - 1.0) - np.maximum(0.0, 1.0 - p)
    evs = lo * (d - 1.0) - np.maximum(0.0, 1.0 - lo)
    w = hi - lo
    return ((np.abs(evs - POL.min_edge_safe) <= d * dn) | (np.abs(ev - POL.max_plausible_ev) <= d * dn)
            | (np.abs(w - POL.max_interval_width) <= 2 * dn) | (np.abs(ev) <= d * dn))


def classify(p, lo, hi, d):
    """decide()'ın (engelsiz, geçerli ve taze oranlı, doğrulanmış model) durum mantığının vektörel kopyası.
    Öncelik sırası _PRIORITY ile aynı: HIGH_UNCERTAINTY > SUSPICIOUS_EDGE; sonra ev_safe ≥ min_edge_safe."""
    ev = p * (d - 1.0) * (1.0 - POL.commission) - np.maximum(0.0, 1.0 - p)
    evs = lo * (d - 1.0) * (1.0 - POL.commission) - np.maximum(0.0, 1.0 - lo)
    st = np.where(hi - lo > POL.max_interval_width, "HIGH_UNCERTAINTY",
                  np.where(ev > POL.max_plausible_ev, "SUSPICIOUS_EDGE",
                           np.where(evs >= POL.min_edge_safe, "VALUE_CANDIDATE", "NO_VALUE")))
    return st, ev, evs


results = {"policy": {"version": POL.version, "min_edge_safe": POL.min_edge_safe, "max_interval_width": POL.max_interval_width,
                      "max_plausible_ev": POL.max_plausible_ev, "commission": POL.commission},
           "deltas": DELTAS, "delta_num": DELTA_NUM, "n_rows_predict": len(P["A"]), "n_rows_interval": N_IV,
           "n_scenarios": len(SCENARIOS)}

# --------------------------------------------------------------------------- 0) eşik payları (altın değerler)
widths = np.concatenate([IV[k][:, 1] - IV[k][:, 0] for k in PRIMARY_YES])
results["genislik_esik_payi_min"] = float(np.min(np.abs(widths - POL.max_interval_width)))
results["genislik_max"] = float(widths.max())
results["genislik_esik_ustu_sayisi"] = int((widths > POL.max_interval_width).sum())

# --------------------------------------------------------------------------- 1) adil oran / min oran / gösterim
fmt2 = lambda v: f"{v:.2f}"  # noqa: E731  ui.widgets.fmt_num (2 hane)
fmtp = lambda v: f"%{100 * v:.1f}"  # noqa: E731  ui.widgets.fmt_pct (1 hane)
disp_rows = []
for (scope, d, sg) in SCENARIOS:
    n_fair = n_fair_disp = n_p_disp = n_min = n_min_disp = 0
    max_rel_fair = max_rel_min = 0.0
    for i in range(len(P["A"])):
        p0, p1 = make_pred(i), make_pred(i, (scope, d, sg))
        for key in SELECTIONS:
            a0, a1 = p0.p(key), p1.p(key)
            f0, f1 = fair_odds(a0), fair_odds(a1)
            n_fair += f0 != f1
            n_fair_disp += fmt2(f0) != fmt2(f1)
            n_p_disp += fmtp(a0) != fmtp(a1)
            max_rel_fair = max(max_rel_fair, abs(f1 / f0 - 1))
            if i < N_IV:
                l0, l1 = p0.interval(key)[0], p1.interval(key)[0]
                m0, m1 = min_required_odds(l0, POL.min_edge_safe), min_required_odds(l1, POL.min_edge_safe)
                n_min += m0 != m1
                n_min_disp += fmt2(m0) != fmt2(m1)
                max_rel_min = max(max_rel_min, abs(m1 / m0 - 1))
    disp_rows.append({"kapsam": scope, "delta": d, "isaret_p_lo_hi": str(sg), "adil_oran_n": len(P["A"]) * 6,
                      "adil_oran_degisen_float": n_fair, "adil_oran_degisen_2hane": n_fair_disp,
                      "olasilik_gosterim_degisen_%1hane": n_p_disp, "adil_oran_max_goreli": max_rel_fair,
                      "min_oran_n": N_IV * 6, "min_oran_degisen_float": n_min, "min_oran_degisen_2hane": n_min_disp,
                      "min_oran_max_goreli": max_rel_min})
disp = pd.DataFrame(disp_rows)
disp.to_csv(f"{OUT}/cikti/karar_gosterim.csv", index=False, float_format="%.6g")
agg = disp.groupby(["kapsam", "delta"]).agg({"adil_oran_degisen_2hane": "max", "min_oran_degisen_2hane": "max",
                                              "olasilik_gosterim_degisen_%1hane": "max", "adil_oran_max_goreli": "max",
                                              "min_oran_max_goreli": "max"}).reset_index()
results["gosterim_ozet"] = agg.to_dict(orient="records")

# --------------------------------------------------------------------------- 2) F1: eşiğe bitişik oranlar (gerçek decide)
EPS = sorted({s * e for e in (1e-2, 1e-3, 3e-4, 1e-4, 3e-5, 1e-5, 3e-6, 1e-6, 1e-7) for s in (-1, 1)})
f1_rows = []
for i in range(N_IV):
    pred0 = make_pred(i)
    preds = {sc: make_pred(i, sc) for sc in SCENARIOS}
    for key in SELECTIONS:
        p, lo, hi = sel_side(pred0, key)
        bases = {"VALUE(ev_safe=0.03)": (1 + POL.min_edge_safe) / lo, "EV=0": 1.0 / p,
                 "SUSPICIOUS(ev=0.30)": (1 + POL.max_plausible_ev) / p}
        for thr, base in bases.items():
            for eps in EPS:
                d = base * (1 + eps)
                if not d > 1.0:
                    continue
                r0 = decide_one(pred0, key, d)
                for sc in SCENARIOS:
                    r1 = decide_one(preds[sc], key, d)
                    p1, lo1, hi1 = sel_side(preds[sc], key)
                    dp, dlo = abs(p1 - p), abs(lo1 - lo)
                    # bant: |ΔEV| ≤ oran·|Δp|  (komisyonsuz EV = p·d − 1 ⇒ ΔEV = d·Δp)
                    in_band_value = abs(r0.ev_safe - POL.min_edge_safe) <= d * dlo * (1 + 1e-9) + 1e-12
                    in_band_ev0 = abs(r0.ev) <= d * dp * (1 + 1e-9) + 1e-12
                    in_band_susp = abs(r0.ev - POL.max_plausible_ev) <= d * dp * (1 + 1e-9) + 1e-12
                    st_flip = r0.status != r1.status
                    ev_flip = (r0.ev >= 0) != (r1.ev >= 0)
                    vflip = (r0.ev_safe >= POL.min_edge_safe) != (r1.ev_safe >= POL.min_edge_safe)
                    sflip = (r0.ev > POL.max_plausible_ev) != (r1.ev > POL.max_plausible_ev)
                    f1_rows.append({"esik": thr, "eps": eps, "kapsam": sc[0], "delta": sc[1], "isaret": str(sc[2]), "anahtar": key,
                                    "satir": i, "oran": d, "durum0": r0.status, "durum1": r1.status, "durum_degisti": st_flip,
                                    "ev_isaret_degisti": ev_flip, "value_esigi_gecisi": vflip, "susp_esigi_gecisi": sflip,
                                    "bantta_value": in_band_value, "bantta_ev0": in_band_ev0, "bantta_susp": in_band_susp,
                                    "dEV_olculen": (r1.ev - r0.ev), "d_dp": d * (p1 - p),
                                    "bayrak_dnum": bool(flag(p, lo, hi, d))})
f1 = pd.DataFrame(f1_rows)
f1["dEV_hatasi"] = (f1["dEV_olculen"] - f1["d_dp"]).abs()
f1_sum = (f1.groupby(["esik", "delta", "kapsam", "eps"])
          .agg(n=("durum_degisti", "size"), durum_degisen=("durum_degisti", "sum"), ev_isaret_degisen=("ev_isaret_degisti", "sum"),
               value_gecis=("value_esigi_gecisi", "sum"), susp_gecis=("susp_esigi_gecisi", "sum")).reset_index())
f1_sum.to_csv(f"{OUT}/cikti/karar_F1_esik_bitisik_ozet.csv", index=False)
results["F1"] = {
    "n_vaka": int(len(f1)), "n_decide_cagrisi": int(len(f1) + len(f1) / len(SCENARIOS)),
    "value_gecis_bant_disinda": int((f1["value_esigi_gecisi"] & ~f1["bantta_value"]).sum()),
    "ev0_gecis_bant_disinda": int((f1["ev_isaret_degisti"] & ~f1["bantta_ev0"]).sum()),
    "susp_gecis_bant_disinda": int((f1["susp_esigi_gecisi"] & ~f1["bantta_susp"]).sum()),
    "value_gecis_toplam": int(f1["value_esigi_gecisi"].sum()), "ev_isaret_degisen_toplam": int(f1["ev_isaret_degisti"].sum()),
    "susp_gecis_toplam": int(f1["susp_esigi_gecisi"].sum()), "durum_degisen_toplam": int(f1["durum_degisti"].sum()),
    "dEV_eq_oran_carpi_dp_max_hata": float(f1["dEV_hatasi"].max()),
    "bayraksiz_durum_degisimi_delta<=dnum": int((f1["durum_degisti"] & ~f1["bayrak_dnum"] & (f1["delta"] <= DELTA_NUM)).sum()),
    "bayraksiz_ev_isaret_degisimi_delta<=dnum": int((f1["ev_isaret_degisti"] & ~f1["bayrak_dnum"] & (f1["delta"] <= DELTA_NUM)).sum()),
}
# durum geçiş türleri
results["F1"]["gecis_turleri"] = (f1[f1["durum_degisti"]].groupby(["durum0", "durum1"]).size().rename("n").reset_index()
                                  .to_dict(orient="records"))

# --------------------------------------------------------------------------- 3) F2: gerçekçi 0,01 kotasyon ızgarası (vektörel)
f2_rows = []
verify = []
rng = np.random.default_rng(20261010)
for i in range(N_IV):
    pred0 = make_pred(i)
    for key in SELECTIONS:
        p, lo, hi = sel_side(pred0, key)
        top = min(max(1.25 * (1 + POL.min_edge_safe) / lo, 1.25 * (1 + POL.max_plausible_ev) / p), 1000.0)
        grid = np.round(np.arange(101, int(math.ceil(top * 100)) + 1) / 100.0, 2)
        st0, ev0, evs0 = classify(p, lo, hi, grid)
        fl = flag(p, lo, hi, grid, DELTA_NUM)
        fl_small = flag(p, lo, hi, grid, 4.1e-6)
        # vektörel sınıflandırıcıyı gerçek decide() ile örneklemle doğrula
        for j in rng.choice(len(grid), size=min(40, len(grid)), replace=False):
            r = decide_one(pred0, key, float(grid[j]))
            verify.append((r.status == st0[j]) and (r.ev == ev0[j]) and (r.ev_safe == evs0[j]))
        for sc in SCENARIOS:
            p1, lo1, hi1 = sel_side(make_pred(i, sc), key)
            st1, ev1, evs1 = classify(p1, lo1, hi1, grid)
            ch = st0 != st1
            evc = (ev0 >= 0) != (ev1 >= 0)
            disp_ev = np.array([f"{100 * a:+.1f}" != f"{100 * b:+.1f}" for a, b in zip(evs0, evs1)])
            f2_rows.append({"satir": i, "anahtar": key, "kapsam": sc[0], "delta": sc[1], "isaret": str(sc[2]), "n_oran": len(grid),
                            "durum_degisen": int(ch.sum()), "value<->no_value": int((ch & np.isin(st0, ["VALUE_CANDIDATE", "NO_VALUE"])
                                                                                    & np.isin(st1, ["VALUE_CANDIDATE", "NO_VALUE"])).sum()),
                            "ev_isaret_degisen": int(evc.sum()), "ev_safe_gosterim_degisen": int(disp_ev.sum()),
                            "bayrakli_dnum": int(fl.sum()), "bayrakli_4.1e-6": int(fl_small.sum()),
                            "degisen_ama_bayraksiz_dnum": int(((ch | evc) & ~fl).sum()),
                            "degisen_ama_bayraksiz_4.1e-6": int(((ch | evc) & ~fl_small).sum())})
f2 = pd.DataFrame(f2_rows)
f2.to_csv(f"{OUT}/cikti/karar_F2_izgara_ayrinti.csv", index=False)
f2a = (f2.groupby(["kapsam", "delta"]).agg(
    n_oran_x_senaryo=("n_oran", "sum"), durum_degisen=("durum_degisen", "sum"), value_no_value=("value<->no_value", "sum"),
    ev_isaret=("ev_isaret_degisen", "sum"), ev_safe_gosterim=("ev_safe_gosterim_degisen", "sum"),
    bayraksiz_degisim_dnum=("degisen_ama_bayraksiz_dnum", "sum"), bayraksiz_degisim_4e6=("degisen_ama_bayraksiz_4.1e-6", "sum"))
       .reset_index())
f2_key = (f2[f2["kapsam"] == "ABC"].groupby(["anahtar", "delta"]).agg(
    n=("n_oran", "sum"), durum_degisen=("durum_degisen", "sum"), ev_isaret=("ev_isaret_degisen", "sum")).reset_index())
f2a.to_csv(f"{OUT}/cikti/karar_F2_izgara_ozet.csv", index=False)
f2_key.to_csv(f"{OUT}/cikti/karar_F2_izgara_anahtar.csv", index=False)
first = f2.drop_duplicates(["satir", "anahtar"])
results["F2"] = {"n_oran_noktasi": int(first["n_oran"].sum()), "bayrakli_dnum": int(first["bayrakli_dnum"].sum()),
                 "bayrakli_oran_dnum": float(first["bayrakli_dnum"].sum() / first["n_oran"].sum()),
                 "bayrakli_4.1e-6": int(first["bayrakli_4.1e-6"].sum()),
                 "vektorel_vs_decide_dogrulama_n": len(verify), "vektorel_vs_decide_uyusmazlik": int(len(verify) - sum(verify)),
                 "ozet": f2a.to_dict(orient="records"), "anahtar": f2_key.to_dict(orient="records")}

# --------------------------------------------------------------------------- 4) F3/F4: pazar sıralaması (decisions_for + apply_concentration)


def rank_and_top(decs):
    order = [d.market_key for d in sorted(decs, key=lambda d: -(d.ev_safe if d.ev_safe is not None else -9))]
    top = [d.market_key for d in decs if d.status == "VALUE_CANDIDATE"]
    return tuple(order), tuple(top), tuple(d.status for d in decs)


f3_rows = []
for gap in (0.0, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2):
    for i in range(N_IV):
        pred0 = make_pred(i)
        odds = {}
        for k_idx, key in enumerate(SELECTIONS):
            lo = pred0.interval(key)[0]
            odds[key] = (1.0 + 0.10 + k_idx * gap) / lo  # ev_safe = 0.10 + k·gap (eşitlik/yakınlık kurgusu)
        led = StubLedger(odds)
        base = rank_and_top(decisions_for(pred0, StubEngine(), led, T0, POL))
        for sc in SCENARIOS:
            cur = rank_and_top(decisions_for(make_pred(i, sc), StubEngine(), led, T0, POL))
            f3_rows.append({"bosluk": gap, "satir": i, "kapsam": sc[0], "delta": sc[1], "isaret": str(sc[2]),
                            "siralama_degisti": base[0] != cur[0], "ust_aday_degisti": base[1] != cur[1],
                            "durum_degisti": base[2] != cur[2]})
f3 = pd.DataFrame(f3_rows)
f3s = f3.groupby(["bosluk", "kapsam", "delta"]).agg(n=("satir", "size"), siralama=("siralama_degisti", "sum"),
                                                   ust_aday=("ust_aday_degisti", "sum"), durum=("durum_degisti", "sum")).reset_index()
f3s.to_csv(f"{OUT}/cikti/karar_F3_siralama_kurgu.csv", index=False)
results["F3"] = f3s.to_dict(orient="records")

f4_rows = []
REPS = 50
for i in range(N_IV):
    pred0 = make_pred(i)
    preds = {sc: make_pred(i, sc) for sc in SCENARIOS}
    for rep in range(REPS):
        odds = {}
        for key in SELECTIONS:
            lo = pred0.interval(key)[0]
            odds[key] = max(1.01, round((1 + POL.min_edge_safe) / lo * rng.uniform(0.9, 1.2), 2))
        led = StubLedger(odds)
        decs0 = decisions_for(pred0, StubEngine(), led, T0, POL)
        base = rank_and_top(decs0)
        # olay düzeyi bayrak: herhangi bir seçim eşik bandında VEYA herhangi iki seçimin ev_safe farkı ≤ (d_i + d_j)·δ_num
        ev_s = {d.market_key: d.ev_safe for d in decs0}
        per_m = any(bool(flag(*sel_side(pred0, k), odds[k])) for k in SELECTIONS)
        pair = any(abs(ev_s[a] - ev_s[b]) <= (odds[a] + odds[b]) * DELTA_NUM for a, b in itertools.combinations(SELECTIONS, 2))
        # karar düzeyi: yalnızca yoğunlaşma kuralında kazananı belirleyen ilk iki VALUE adayı
        # (yoğunlaşma ÖNCESİ ham kararlar: decisions_for çıktısında kaybeden adaylar zaten NO_VALUE'ya düşürülmüştür)
        raw = [decide_one(pred0, k, odds[k]) for k in SELECTIONS]
        cands = sorted([d for d in raw if d.status == "VALUE_CANDIDATE"], key=lambda d: -d.ev_safe)
        top2 = len(cands) >= 2 and abs(cands[0].ev_safe - cands[1].ev_safe) <= (odds[cands[0].market_key] + odds[cands[1].market_key]) * DELTA_NUM
        for sc in SCENARIOS:
            cur = rank_and_top(decisions_for(preds[sc], StubEngine(), led, T0, POL))
            f4_rows.append({"satir": i, "rep": rep, "kapsam": sc[0], "delta": sc[1], "siralama_degisti": base[0] != cur[0],
                            "ust_aday_degisti": base[1] != cur[1], "durum_degisti": base[2] != cur[2],
                            "aday_var": len(base[1]) > 0, "olay_bayragi": per_m or pair,
                            "karar_bayragi": per_m or top2})
f4 = pd.DataFrame(f4_rows)
f4["herhangi_degisim"] = f4["siralama_degisti"] | f4["ust_aday_degisti"] | f4["durum_degisti"]
f4["bayraksiz_degisim"] = f4["herhangi_degisim"] & ~f4["olay_bayragi"]
f4["karar_degisimi"] = f4["ust_aday_degisti"] | f4["durum_degisti"]
f4["karar_bayraksiz_karar_degisimi"] = f4["karar_degisimi"] & ~f4["karar_bayragi"]
f4["karar_bayraksiz_siralama_degisimi"] = f4["siralama_degisti"] & ~f4["karar_bayragi"]
f4s = f4.groupby(["kapsam", "delta"]).agg(n=("satir", "size"), aday_var=("aday_var", "sum"), siralama=("siralama_degisti", "sum"),
                                          ust_aday=("ust_aday_degisti", "sum"), herhangi_durum=("durum_degisti", "sum"),
                                          olay_bayrakli=("olay_bayragi", "sum"),
                                          bayraksiz_degisim=("bayraksiz_degisim", "sum"),
                                          karar_bayrakli=("karar_bayragi", "sum"),
                                          karar_bayraksiz_karar_degisimi=("karar_bayraksiz_karar_degisimi", "sum"),
                                          karar_bayraksiz_siralama_degisimi=("karar_bayraksiz_siralama_degisimi", "sum")).reset_index()
f4s.to_csv(f"{OUT}/cikti/karar_F4_siralama_gercekci.csv", index=False)
results["F4"] = f4s.to_dict(orient="records")

# --------------------------------------------------------------------------- 5) analitik bant tablosu
band = []
for ps in (0.0265, 0.05, 0.10, 0.30, 0.50, 0.90):
    for d in DELTAS:
        dstar = (1 + POL.min_edge_safe) / ps
        lo_d, hi_d = (1 + POL.min_edge_safe) / (ps + d), (1 + POL.min_edge_safe) / (ps - d)
        band.append({"p_safe": ps, "delta": d, "esik_oran_d*": dstar, "EV_bandi_d*xdelta": dstar * d,
                     "oran_bandi_genisligi_iki_yonlu": hi_d - lo_d, "0.01_adim_sayisi": (hi_d - lo_d) / 0.01})
bdf = pd.DataFrame(band)
bdf.to_csv(f"{OUT}/cikti/karar_bant_tablosu.csv", index=False, float_format="%.6g")
results["bant"] = bdf.to_dict(orient="records")
results["sure_s"] = round(time.time() - t_start, 1)
json.dump(results, open(f"{OUT}/cikti/karar_etkisi_ozet.json", "w"), ensure_ascii=False, indent=1, default=float)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
print(json.dumps({k: v for k, v in results.items() if k in ("F1", "genislik_esik_payi_min", "genislik_max", "genislik_esik_ustu_sayisi", "sure_s")},
                 ensure_ascii=False, indent=1, default=float))
print(agg.to_string()); print(f2a.to_string()); print(f2_key.to_string()); print(f3s.to_string()); print(f4s.to_string()); print(bdf.to_string())
print({k: results["F2"][k] for k in ("n_oran_noktasi", "bayrakli_dnum", "bayrakli_oran_dnum", "bayrakli_4.1e-6",
                                     "vektorel_vs_decide_dogrulama_n", "vektorel_vs_decide_uyusmazlik")})

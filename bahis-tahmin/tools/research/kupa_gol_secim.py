"""KUPA-GOL-05: kupa gol pazarı modelinin seçimi (KUPA-GOL-02 adayları), ileriye dönük yeniden çalıştırma.

Kullanım (veri uygulamanın veri klasöründen, ``BAHIS_TAHMIN_HOME``; ağ isteği yok):

    python -I tools/research/kupa_gol_secim.py <çıktı_klasörü> [--test]

``--test`` verilmezse yalnızca geliştirme dönemi yazdırılır ve seçim yapılır; test dönemi seçimden sonra ayrıca istenir.

ÖN KAYITLI SEÇİM KURALI (ilk çalıştırmadan, sonuçlar görülmeden yazıldı; 2026-10-15; docs/KUPA_GOL_05.md):
  Adaylar (KUPA-GOL-02 ile aynı): S2, H2, SK1, SK0 (uygulamadaki model), K1, MIX.
  Ana ölçüt: geliştirme dönemi (2019/20–2021/22; ilk örneklem dışı sezon yalnızca kalibrasyon için) bütün kupa
    maçlarında A, B ve C ortalama log-kayıplarının TOPLAMI (KUPA-GOL-02 tablosundaki "Toplam" satırıyla aynı tanım).
  Eşdeğerlik: ana ölçütte en iyiye 0,001'den yakın adaylar eşdeğerdir; eşdeğerler içinde sadelik sırasındaki ilk aday
    seçilir. Sadelik sırası (ek parametre ve ek model sayısına göre): SK0 < SK1 < S2 < K1 < MIX < H2.
  Grup koruması (KUPA-GOL-02'de tek grup vardı; şimdi iki): SK0 dışındaki bir aday ancak UEFA'nın ve yurt içi
    kupaların geliştirme dönemi toplamlarının HER BİRİNDE SK0'dan en fazla 0,001 kötüyse seçilebilir. Sağlamazsa
    eşdeğerler listesinde sıradakine geçilir; hiçbiri sağlamazsa SK0.
  ECE ve kalibrasyon eğimi raporlanır, seçimde kullanılmaz.
  Test dönemi (2022/23–2025/26) seçimden SONRA raporlanır ve seçimi değiştirmez.

Adaylar:
  SK0  kalibre maç sonu beklentisi + ilk yarı payı s ile bölme (uygulamadaki ``kupa-gol-v2``)
  SK1  SK0 + ikinci yarı skor durumu çarpanları
  S2   kalibrasyonsuz maç sonu beklentisi + s ile bölme + durum çarpanları + pazar kalibrasyonu (Platt + IPF)
  K1   ayrı ilk yarı / ikinci yarı ligler arası takım güçleri + her yarıya ayrı kalibrasyon + durum çarpanları
  MIX  SK1 ile K1'in yarı yarıya karışımı
  H2   ayrı yarı güçleri (kalibrasyonsuz) + durum çarpanları + Platt + IPF

Ölçüm uygulamadaki gibidir (``kupa-gol-dogrulama-v3``): İY skoru ``kupa.gol.ht_scores`` ile (maç sonu 0-0 → İY 0-0);
ilk yarı payı ve taban oranları sezon başından önceki, aynı doğrulama grubundaki kupa maçlarından. SK kalibrasyonu sezon
başından önceki bütün örneklem dışı maçlardan (motorla aynı). Durum çarpanları, Platt ve yarı kalibrasyonları sezon
başından önceki, İY skoru geçerli örneklem dışı maçlardan; önceki dönemin kendi tahminleri aynı parametrelerle üretilir.
Maç sonu modeli kupa motorunun ileriye dönük döngüsüyle aynıdır; SK0 olasılıkları uygulamanın ölçtüğü olasılıklarla
birebir aynı çıkar (betik denetler)."""

from __future__ import annotations

import os
import sys
import warnings
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

DEV = ("2019/20", "2020/21", "2021/22")
TEST = ("2022/23", "2023/24", "2024/25", "2025/26")
ORDER = ("SK0", "SK1", "S2", "K1", "MIX", "H2")
EQ = 0.001
GROUPS = ("UEFA", "YURTICI")
VARIANTS = {  # (yapı, durum çarpanı, Platt + IPF)
    "S2": ("S", True, True), "H2": ("H", True, True), "SK1": ("SK", True, False), "SK0": ("SK", False, False),
    "K1": ("K", True, False),
}


# ------------------------------------------------------------------------------------------- ileriye dönük hat
def walk_forward(dom: pd.DataFrame, cups: pd.DataFrame, cfg=None, progress=print) -> pd.DataFrame:
    """Haftalık ileriye dönük üç ligler arası model (maç sonu, ilk yarı, ikinci yarı) → kupa maçı başına ham
    beklentiler. Üç modelin ısınma başlangıcı ayrı ilerler; maç sonu modeli kupa motorunun döngüsüyle aynıdır."""
    from bahis_tahmin.kupa.gol import ht_scores
    from bahis_tahmin.kupa.model import EPOCH, ModelConfig, build_data, fit
    from bahis_tahmin.kupa.motor import WARMUP_DAYS, CupEngine, _week_start, group_of, key_of, vgroup_of

    cfg = cfg or ModelConfig()
    cups = cups.sort_values("date", kind="mergesort").reset_index(drop=True)
    data, tl = build_data(dom, cups, key_of, group_of)
    d_day = ((pd.to_datetime(dom["date"]) - EPOCH).dt.days).to_numpy(int)
    c_day = ((pd.to_datetime(cups["date"]) - EPOCH).dt.days).to_numpy(int)
    order = np.argsort(np.concatenate([d_day, c_day]), kind="mergesort")
    if not np.array_equal(np.concatenate([d_day, c_day])[order], data.day):
        raise RuntimeError("build_data maç sırası beklenenden farklı")
    dh, da = ht_scores(dom)
    ch, ca = ht_scores(cups)
    hh = np.concatenate([dh, ch])[order]
    ha = np.concatenate([da, ca])[order]
    ok = np.isfinite(hh) & np.isfinite(ha) & (hh <= data.hg) & (ha <= data.ag)

    def sub(mask, hg, ag):
        return replace(data, day=data.day[mask], home=data.home[mask], away=data.away[mask], hlg=data.hlg[mask],
                       alg=data.alg[mask], hgrp=data.hgrp[mask], hg=hg[mask].astype(int), ag=ag[mask].astype(int),
                       cup=data.cup[mask])

    d1 = sub(ok, hh, ha)
    d2 = sub(ok, data.hg - np.nan_to_num(hh), data.ag - np.nan_to_num(ha))
    eng = CupEngine()
    eng.timeline = tl
    start = int(data.day.min()) + WARMUP_DAYS
    by_week: dict = {}
    for i in np.nonzero(c_day >= start)[0]:
        by_week.setdefault(_week_start(c_day[i]), []).append(i)
    rows = []
    iF = i1 = i2 = None
    weeks = sorted(by_week)
    for n, wk in enumerate(weeks):
        PF, P1, P2 = fit(data, wk, cfg, iF), fit(d1, wk, cfg, i1), fit(d2, wk, cfg, i2)
        iF = PF.as_dict() if PF is not None else iF
        i1 = P1.as_dict() if P1 is not None else i1
        i2 = P2.as_dict() if P2 is not None else i2
        if PF is None:
            continue
        for i in by_week[wk]:
            r = cups.iloc[i]
            hl = eng.league_for(r["home_key"], r["home_country"], c_day[i])
            al = eng.league_for(r["away_key"], r["away_country"], c_day[i])
            spec = (r["home_key"], r["away_key"], hl, al, group_of(r["comp"]), bool(r["neutral"]))
            f = PF.rates(*spec)
            if f is None:
                continue
            a = P1.rates(*spec) if P1 is not None else None
            b = P2.rates(*spec) if P2 is not None else None
            rows.append({"i": int(i), "comp": r["comp"], "vgroup": vgroup_of(r["comp"]), "season": str(r["season"]),
                         "date": r["date"], "week": wk, "neutral": bool(r["neutral"]), "fthg": int(r["fthg"]),
                         "ftag": int(r["ftag"]), "hthg": r["hthg"], "htag": r["htag"], "lam": f[0], "nu": f[1],
                         "r1h": a[0] if a else np.nan, "r1a": a[1] if a else np.nan,
                         "r2h": b[0] if b else np.nan, "r2a": b[1] if b else np.nan})
        if progress and n % 50 == 0:
            progress(f"hafta {n + 1}/{len(weeks)}")
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------ adaylar
def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _platt(y, p):
    from sklearn.linear_model import LogisticRegression

    m = LogisticRegression(C=1e6, max_iter=1000).fit(_logit(p)[:, None], y)
    return float(m.intercept_[0]), float(m.coef_[0, 0])


def _apply_platt(ab, p):
    return 1 / (1 + np.exp(-(ab[0] + ab[1] * _logit(p))))


def _mults(prev, r2h, r2a, k=30.0):
    from bahis_tahmin.goals.joint import N_STATES

    c = prev["c"].to_numpy()
    mh = (np.bincount(c, weights=prev["h2h"], minlength=N_STATES) + k) / (
        np.bincount(c, weights=r2h, minlength=N_STATES) + k)
    ma = (np.bincount(c, weights=prev["h2a"], minlength=N_STATES) + k) / (
        np.bincount(c, weights=r2a, minlength=N_STATES) + k)
    return mh, ma


def _rates(d, kind, share, th, t12):
    from bahis_tahmin.kupa.model import calibrate_rates

    if kind == "S":
        lam, nu = d["lam"].to_numpy(), d["nu"].to_numpy()
        return share * lam, share * nu, (1 - share) * lam, (1 - share) * nu
    if kind == "SK":
        lam, nu = calibrate_rates(d["lam"], d["nu"], th, d["neutral"])
        return share * lam, share * nu, (1 - share) * lam, (1 - share) * nu
    if kind == "K":
        a, b = calibrate_rates(d["r1h"], d["r1a"], t12[0], d["neutral"])
        c, e = calibrate_rates(d["r2h"], d["r2a"], t12[1], d["neutral"])
        return a, b, c, e
    return d["r1h"].to_numpy(), d["r1a"].to_numpy(), d["r2h"].to_numpy(), d["r2a"].to_numpy()


def evaluate(oos: pd.DataFrame, cups: pd.DataFrame) -> dict:
    """Altı adayın örneklem dışı A, B, C olasılıkları ve taban oranları (ölçüm kuralları modül belgesinde)."""
    from bahis_tahmin.goals.joint import joint_regions, tilt_to_targets
    from bahis_tahmin.kupa.gol import MIN_GROUP_BASE, first_half_share, ht_mask, ht_scores, labels
    from bahis_tahmin.kupa.model import fit_calibration
    from bahis_tahmin.kupa.motor import vgroup_of

    warnings.simplefilter("ignore")
    cups = cups.sort_values("date", kind="mergesort").reset_index(drop=True)
    o = oos.sort_values(["date", "i"], kind="mergesort").reset_index(drop=True)
    cvg = np.array([vgroup_of(c) for c in cups["comp"]])
    cd = pd.to_datetime(cups["date"]).to_numpy()
    cok, clab = ht_mask(cups), labels(cups)
    okm = ht_mask(o)
    h1h, h1a = ht_scores(o)
    o["h1h"], o["h1a"] = h1h, h1a
    o["h2h"], o["h2a"] = o["fthg"] - o["h1h"], o["ftag"] - o["h1a"]
    for k, v in labels(o).items():
        o[f"y{k}"] = v
    o["c"] = np.where(okm, np.minimum(np.nan_to_num(h1h), 2) * 3 + np.minimum(np.nan_to_num(h1a), 2), 0).astype(int)
    half_ok = o[["r1h", "r1a", "r2h", "r2a"]].notna().all(axis=1).to_numpy()
    res = {v: {k: np.full(len(o), np.nan) for k in "ABC"} for v in VARIANTS}
    base = {k: np.full(len(o), np.nan) for k in "ABC"}
    first = o["date"].min()
    for s in sorted(o["season"].unique()):
        cur_s = (o["season"] == s).to_numpy()
        s0 = o.loc[cur_s, "date"].min()
        prev_all = (o["date"] < s0).to_numpy()
        if prev_all.sum() < 50 or s0 <= first:
            continue
        th = fit_calibration(o.loc[prev_all, "lam"], o.loc[prev_all, "nu"], o.loc[prev_all, "fthg"],
                             o.loc[prev_all, "ftag"], o.loc[prev_all, "neutral"])
        before_all = cok & (cd < np.datetime64(pd.Timestamp(s0)))
        shares = {}
        for vg in set(o["vgroup"]):
            before = before_all & (cvg == vg)
            shares[vg] = first_half_share(cups[before])
            src = before if before.sum() >= MIN_GROUP_BASE else before_all
            cur = cur_s & (o["vgroup"] == vg).to_numpy()
            for k in "ABC":
                base[k][cur] = clab[k][src].mean() if src.sum() >= MIN_GROUP_BASE else np.nan
        sh = o["vgroup"].map(shares).to_numpy(float)
        pm = prev_all & okm & half_ok
        prev = o[pm]
        t1 = fit_calibration(prev["r1h"], prev["r1a"], prev["h1h"], prev["h1a"], prev["neutral"])
        t2 = fit_calibration(prev["r2h"], prev["r2a"], prev["h2h"], prev["h2a"], prev["neutral"])
        cm = cur_s & okm & half_ok
        dcur = o[cm]
        for v, (kind, use_m, use_p) in VARIANTS.items():
            p1h, p1a, p2h, p2a = _rates(prev, kind, sh[pm], th, (t1, t2))
            c1h, c1a, c2h, c2a = _rates(dcur, kind, sh[cm], th, (t1, t2))
            mh, ma = _mults(prev, p2h, p2a) if use_m else (None, None)
            regc = joint_regions(c1h, c1a, c2h, c2a, mh, ma)
            Bc, Cc = regc["BC"] + regc["BnC"], regc["BC"] + regc["nBC"]
            if use_p:
                regp = joint_regions(p1h, p1a, p2h, p2a, mh, ma)
                Bp, Cp = regp["BC"] + regp["BnC"], regp["BC"] + regp["nBC"]
                pb, pc = _platt(prev["yB"].to_numpy(), Bp), _platt(prev["yC"].to_numpy(), Cp)
                tc = tilt_to_targets(regc, _apply_platt(pb, Bc), _apply_platt(pc, Cc))
                A, B, C = tc["A"], tc["B"], tc["C"]
            else:
                A, B, C = regc["A"], Bc, Cc
            res[v]["A"][cm], res[v]["B"][cm], res[v]["C"][cm] = A, B, C
    res["MIX"] = {k: 0.5 * res["SK1"][k] + 0.5 * res["K1"][k] for k in "ABC"}
    measured = np.isfinite(res["SK0"]["A"]) & np.isfinite(base["A"])
    return {"o": o, "res": res, "base": base, "measured": measured, "n_half_missing": int((~half_ok).sum())}


def table(ev: dict, seasons, label: str) -> pd.DataFrame:
    """Dönem × grup (UEFA, YURTICI, TÜMÜ) × aday: A, B, C log-kaybı, toplam ve ECE; taban satırıyla."""
    from bahis_tahmin.goals.validation import _ll
    from bahis_tahmin.kupa.gol import ece

    o, res, base = ev["o"], ev["res"], ev["base"]
    per = o["season"].isin(seasons).to_numpy() & ev["measured"]
    rows = []
    for grp in GROUPS + ("TÜMÜ",):
        m = per & ((o["vgroup"] == grp).to_numpy() if grp != "TÜMÜ" else True)
        if not m.any():
            continue
        for v in list(ORDER) + ["taban"]:
            r = {"dönem": label, "grup": grp, "aday": v, "n": int(m.sum()), "toplam": 0.0}
            for k in "ABC":
                y = o.loc[m, f"y{k}"].to_numpy()
                p = base[k][m] if v == "taban" else res[v][k][m]
                r[f"ll{k}"] = float(_ll(y, p).mean())
                r[f"ece{k}"] = float("nan") if v == "taban" else ece(y, p)
                r["toplam"] += r[f"ll{k}"]
            rows.append(r)
    return pd.DataFrame(rows)


def select(dev: pd.DataFrame) -> dict:
    """Ön kayıtlı kural (modül belgesi): ana ölçüt, 0,001 eşdeğerlik, sadelik sırası, grup koruması."""
    tot = dev[dev["grup"] == "TÜMÜ"].set_index("aday")["toplam"]
    best = min(ORDER, key=lambda v: tot[v])
    eq = [v for v in ORDER if tot[v] <= tot[best] + EQ]
    grp = {g: dev[dev["grup"] == g].set_index("aday")["toplam"] for g in GROUPS if (dev["grup"] == g).any()}
    chosen, notes = "SK0", []
    for v in eq:
        if v == "SK0":
            notes.append("SK0: eşdeğerler içinde sadelikte ilk")
            break
        ok = all(grp[g][v] <= grp[g]["SK0"] + EQ for g in grp)
        notes.append(f"{v}: grup koruması {'geçti' if ok else 'geçmedi'} ("
                     + ", ".join(f"{g} {grp[g][v] - grp[g]['SK0']:+.5f}" for g in grp) + ")")
        if ok:
            chosen = v
            break
    return {"secilen": chosen, "en_iyi": best, "esdeger": eq, "notlar": notes,
            "toplam": {v: float(tot[v]) for v in ORDER}}


def engine_check(ev: dict, engine) -> dict:
    """SK0 olasılıkları ve taban oranları, uygulamanın ölçtüğüyle (``engine.goal.oos``) aynı mı: en büyük farklar."""
    o = ev["o"]
    mine = pd.DataFrame({"i": o["i"], **{f"p{k}": ev["res"]["SK0"][k] for k in "ABC"},
                         **{f"b{k}": ev["base"][k] for k in "ABC"}})[ev["measured"]].set_index("i")
    g = engine.goal.oos.set_index("i")
    common = mine.index.intersection(g.index)
    return {"ortak": int(len(common)), "motor": int(len(g)), "prototip": int(len(mine)),
            "en_buyuk_fark": {c: float(np.max(np.abs(mine.loc[common, c] - g.loc[common, c]))) for c in mine.columns}}


def main(argv: list[str]) -> int:
    from bahis_tahmin.config import app_home
    from bahis_tahmin.data.store import DataStore
    from bahis_tahmin.kupa.motor import CupEngine

    if not argv:
        print(__doc__)
        return 2
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    st = DataStore(app_home())
    st.load()
    oos_path = out / "oos.pkl"
    if oos_path.exists():
        oos = pd.read_pickle(oos_path)
    else:
        oos = walk_forward(st.matches, st.cup_matches)
        oos.to_pickle(oos_path)
    ev = evaluate(oos, st.cup_matches)
    print(f"ölçülen maç: {int(ev['measured'].sum())} (yarı modeli olmayan {ev['n_half_missing']})")
    eng = CupEngine.load(Path(os.environ.get("BAHIS_TAHMIN_HOME", app_home())) / "kupa_engine.joblib")
    if eng is not None:
        print("SK0 = motor denetimi:", engine_check(ev, eng))
    pd.set_option("display.width", 250)
    cols = ["grup", "aday", "n", "llA", "llB", "llC", "toplam", "eceA", "eceB", "eceC"]
    dev = table(ev, DEV, "dev")
    print("=== GELİŞTİRME DÖNEMİ (2019/20–2021/22) ===")
    print(dev[cols].round(5).to_string(index=False))
    sel = select(dev)
    print("ana ölçüt (TÜMÜ toplam):", {k: round(v, 5) for k, v in sel["toplam"].items()})
    print("en iyi:", sel["en_iyi"], "| eşdeğerler (sadelik sırasıyla):", sel["esdeger"])
    for line in sel["notlar"]:
        print("  ", line)
    print("SEÇİLEN:", sel["secilen"])
    tabs = {"dev": dev}
    if "--test" in argv:
        for name, seasons in (("test", TEST), ("tümü", DEV + TEST)):
            tabs[name] = table(ev, seasons, name)
            print(f"=== {name.upper()} ===")
            print(tabs[name][cols].round(5).to_string(index=False))
    pd.to_pickle({"secim": sel, "tablolar": tabs}, out / "secim.pkl")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

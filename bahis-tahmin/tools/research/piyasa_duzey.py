"""ORAN-04: Piyasanın 2,5 Üst/Alt oranını Gol Pazarları modelinin gol düzeyine katmak (salt okunur sınama).

Kullanım (veri uygulamanın veri klasöründen, ``BAHIS_TAHMIN_HOME``; ağ isteği yok):

    python -I tools/research/piyasa_duzey.py <çıktı_klasörü>          # geliştirme dönemi ve seçim
    python -I tools/research/piyasa_duzey.py <çıktı_klasörü> --test   # test dönemi de (seçimden sonra)

İlk çalıştırma sezonluk ileriye dönük tahminleri ``<çıktı_klasörü>/piyasa_tahmin.pkl`` dosyasına yazar; sonraki
çalıştırmalar onu kullanır.

ÖN KAYITLI KURAL (ilk çalıştırmadan, sonuç görülmeden yazıldı; 2026-10-15; docs/ORAN_04.md)

Soru: maçın ortalama 2,5 Üst/Alt oranından çıkan gol düzeyi, uygulamanın üç pazarının (A = iki yarıda KG, B = maç
sonu 3,5 Üst, C = İY 1,5 Üst) olasılığını iyileştirir mi?

Veri ve hat:
- Depodaki lig maçları; özellikler maç gününden önceki maçlardan (``build_goal_features``).
- Model: seçili varyant (``SELECTED_VARIANT``). Her sezon Y için 2016/17 ≤ sezon < Y maçlarıyla eğitilir; en az 2000
  eğitim satırı gerekir.
- Oran: ortalama 2,5 Üst/Alt (``o_o25``, ``o_u25``), marjı orantılı olarak çıkarılmış piyasa olasılığı p_m.
- Örneklem: takım güçleri kurulmuş, ilk yarı skoru geçerli, iki oranı da 1'den büyük ve bütün adayların A, B, C
  olasılıkları sonlu maçlar.

Adaylar:
- P0 (mevcut): modelin kendi A, B, C'si.
- P1 (ölçek): bütün takım gücü girdileri (l1h, l1a, l2h, l2a, lh, la) maç başına tek bir s ile çarpılır. s, modelin
  yapısal 2,5 Üst olasılığı p_m'ye eşit olacak biçimde seçilir (s ∈ [0,25; 4], log ölçekte ikiye bölme). Tahmin hattı
  (ayarlayıcı + ortak dağılım + IPF + A kalibrasyonu) ölçeklenmiş girdilerle yeniden çalışır.
- P2 (öğrenilmiş kaydırma): g = logit p_m − logit p_model(2,5 Üst). B ve C hedefleri logit B' = logit B + δ_B + γ_B·g,
  logit C' = logit C + δ_C + γ_C·g; (δ, γ) eğitim satırlarında (oranlı) en çok olabilirlikle öğrenilir. Ortak
  dağılım B', C'ye eğilir; A, modelin kendi A kalibrasyonuyla aynı dağılımdan gelir.

Ölçüt: maç başına A, B ve C log-kayıplarının toplamı. Fark ve %95 aralığı hafta bloklu bootstrap ile.

Seçim (geliştirme dönemi 2017/18–2020/21):
- Bir aday, P0'a göre toplam farkının %95 üst sınırı < 0 ise uygundur.
- Uygun adaylardan ortalama toplam kaybı en düşük olan seçilir. Uygun aday yoksa P0 kalır (değişiklik yok).

Test (2021/22 ve sonrası, ``--test``; yalnızca seçilen aday için karar):
- KABUL: P0'a göre toplam farkın %95 üst sınırı < 0 VE A, B, C'nin hiçbirinde farkın %95 alt sınırı > 0 değil
  (hiçbir pazar anlamlı kötüleşmiyor).
- Aksi halde RED: uygulama değişmez.

Bilgi için (karara girmez): pazar başına fark, kalibrasyon eğimi ve ECE, sezon başına fark, s'nin sezon ortalaması.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

WARMUP_YEAR = 2016
DEV_YEARS = (2017, 2018, 2019, 2020)
TEST_FIRST = 2021
KEY = ["league", "date", "home", "away"]
RATE_COLS = ("l1h", "l1a", "l2h", "l2a", "lh", "la")
LABELS = {"A": "BTTS_BOTH_HALVES_YES", "B": "FT_OVER_3_5", "C": "FH_OVER_1_5"}
CANDS = ("P0", "P1", "P2")
S_LO, S_HI, S_ITERS = 0.25, 4.0, 30


def season_year(dates) -> np.ndarray:
    d = pd.to_datetime(pd.Series(dates))
    return np.where(d.dt.month >= 7, d.dt.year, d.dt.year - 1)


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.asarray(z, dtype=float)))


def market_prob(o_over, o_under) -> np.ndarray:
    io, iu = 1.0 / np.asarray(o_over, dtype=float), 1.0 / np.asarray(o_under, dtype=float)
    return io / (io + iu)


# ------------------------------------------------------------------------------------------- adaylar
def scaled(df: pd.DataFrame, s) -> pd.DataFrame:
    out = df.copy()
    s = np.asarray(s, dtype=float)
    for c in RATE_COLS:
        out[c] = out[c].to_numpy(dtype=float) * s
    return out


def market_scale(model, df: pd.DataFrame, p_m) -> np.ndarray:
    """Maç başına s: modelin yapısal 2,5 Üst olasılığı p_m'ye eşit (log ölçekte ikiye bölme; sınırlarda kırpılır)."""
    p_m = np.asarray(p_m, dtype=float)
    lo = np.full(len(df), np.log(S_LO))
    hi = np.full(len(df), np.log(S_HI))
    base = model.base if model.base is not None else model
    for _ in range(S_ITERS):
        mid = (lo + hi) / 2
        p = base.predict(scaled(df, np.exp(mid)))["FT_O25"]
        up = p < p_m
        lo = np.where(up, mid, lo)
        hi = np.where(up, hi, mid)
    return np.exp((lo + hi) / 2)


def predict_with_targets(model, df: pd.DataFrame, t_b, t_c) -> dict[str, np.ndarray]:
    """Ortak dağılımı verilen B ve C hedeflerine eğer; A, modelin A kalibrasyonuyla (M10) aynı dağılımdan."""
    from bahis_tahmin.goals.joint import joint_regions, tilt_to_targets

    lam, bad = model.structural_rates(df)
    b = model.base
    reg = joint_regions(lam[:, 0], lam[:, 1], lam[:, 2], lam[:, 3], b.mult_h, b.mult_a, b.phi)
    til = tilt_to_targets(reg, np.clip(t_b, 1e-4, 1 - 1e-4), np.clip(t_c, 1e-4, 1 - 1e-4))
    a = til["BC"] * model._q_cal(til["A"], til["BC"]) if model.qcal is not None else til["A"]
    return {k: np.where(bad, np.nan, v) for k, v in (("A", a), ("B", til["B"]), ("C", til["C"]))}


def fit_shift(y, p, g) -> tuple[float, float]:
    """logit p' = logit p + δ + γ·g; (δ, γ) en çok olabilirlik."""
    from scipy.optimize import minimize

    ok = np.isfinite(y) & np.isfinite(p) & np.isfinite(g)
    y, z, g = np.asarray(y)[ok], logit(np.asarray(p)[ok]), np.asarray(g)[ok]

    def nll(t):
        eta = z + t[0] + t[1] * g
        return float(np.sum(np.logaddexp(0.0, eta) - y * eta))

    def grad(t):
        r = sigmoid(z + t[0] + t[1] * g) - y
        return np.array([r.sum(), (r * g).sum()])

    res = minimize(nll, np.zeros(2), jac=grad, method="L-BFGS-B")
    return float(res.x[0]), float(res.x[1])


def candidates(model, train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    """Test satırları için üç adayın A, B, C'si (+ s, g, p_m)."""
    from bahis_tahmin.goals.model import ht_rows, usable_rows

    p0 = model.predict(test)
    pm = market_prob(test["o_o25"], test["o_u25"])
    has = np.isfinite(pm)
    out = pd.DataFrame({"p_m": pm, "p_o25": p0["FT_O25"]}, index=test.index)
    for k in "ABC":
        out[f"P0_{k}"] = p0[k]
    # P1: ölçek
    s = np.full(len(test), np.nan)
    idx = np.where(has & usable_rows(test))[0]
    if len(idx):
        sub = test.iloc[idx]
        s[idx] = market_scale(model, sub, pm[idx])
        p1 = model.predict(scaled(sub, s[idx]))
        for k in "ABC":
            col = np.full(len(test), np.nan)
            col[idx] = p1[k]
            out[f"P1_{k}"] = col
    else:
        for k in "ABC":
            out[f"P1_{k}"] = np.nan
    out["s"] = s
    # P2: öğrenilmiş kaydırma (eğitim satırlarında)
    tr = train[usable_rows(train) & ht_rows(train)]
    tr = tr[(tr["o_o25"] > 1) & (tr["o_u25"] > 1)]
    pt = model.predict(tr)
    g_tr = logit(market_prob(tr["o_o25"], tr["o_u25"])) - logit(pt["FT_O25"])
    dB, gB = fit_shift(tr[LABELS["B"]].to_numpy(dtype=float), pt["B"], g_tr)
    dC, gC = fit_shift(tr[LABELS["C"]].to_numpy(dtype=float), pt["C"], g_tr)
    g = logit(pm) - logit(p0["FT_O25"])
    tb = sigmoid(logit(p0["B"]) + dB + gB * g)
    tc = sigmoid(logit(p0["C"]) + dC + gC * g)
    p2 = predict_with_targets(model, test, np.nan_to_num(tb, nan=0.5), np.nan_to_num(tc, nan=0.5))
    for k in "ABC":
        out[f"P2_{k}"] = np.where(np.isfinite(g), p2[k], np.nan)
    out["g"] = g
    out.attrs["p2"] = {"dB": dB, "gB": gB, "dC": dC, "gC": gC, "n": int(len(tr))}
    return out


def walk_forward(feat: pd.DataFrame, variant: str | None = None, progress=print) -> pd.DataFrame:
    from bahis_tahmin.goals.engine import SELECTED_VARIANT
    from bahis_tahmin.goals.model import GoalModel

    variant = variant or SELECTED_VARIANT
    parts, coefs = [], {}
    for y in sorted(int(v) for v in feat["fold"].unique() if v > WARMUP_YEAR):
        train = feat[(feat["fold"] < y) & (feat["fold"] >= WARMUP_YEAR)]
        test = feat[feat["fold"] == y]
        if test.empty or len(train) < 2000:
            continue
        if progress:
            progress(f"sezon {y}/{(y + 1) % 100:02d}: {len(train)} eğitim, {len(test)} tahmin")
        m = GoalModel(variant).fit(train)
        c = candidates(m, train, test)
        coefs[y] = c.attrs["p2"]
        keep = test[KEY + ["fold", "issues", "hthg", "htag"] + list(LABELS.values())]
        parts.append(pd.concat([keep, c], axis=1))
    out = pd.concat(parts)
    out.attrs["p2"] = coefs
    return out


def features_with_odds(matches: pd.DataFrame) -> pd.DataFrame:
    from bahis_tahmin.goals.features import build_goal_features

    feat, _ = build_goal_features(matches)
    feat = feat.copy()
    feat["date"] = pd.to_datetime(feat["date"])
    odds = matches[KEY + ["o_o25", "o_u25"]].copy()
    odds["date"] = pd.to_datetime(odds["date"])
    feat = feat.merge(odds, on=KEY, how="left", validate="one_to_one")
    feat["fold"] = season_year(feat["date"])
    return feat


# ------------------------------------------------------------------------------------------------ ölçüm
def _ll(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def sample(pred: pd.DataFrame) -> pd.DataFrame:
    ok = (pred["issues"] == "") & pred["hthg"].notna() & pred["htag"].notna() & np.isfinite(pred["p_m"])
    for c in CANDS:
        for k in "ABC":
            ok &= np.isfinite(pred[f"{c}_{k}"])
    for lab in LABELS.values():
        ok &= pred[lab].notna()
    d = pred[ok].copy()
    d["week"] = (pd.to_datetime(d["date"]) - pd.Timestamp("2000-01-03")).dt.days // 7
    return d


def losses(d: pd.DataFrame, cand: str) -> dict[str, np.ndarray]:
    out = {k: _ll(d[LABELS[k]].to_numpy(dtype=float), d[f"{cand}_{k}"].to_numpy(dtype=float)) for k in "ABC"}
    out["toplam"] = out["A"] + out["B"] + out["C"]
    return out


def block_ci(values, blocks, reps: int = 2000, seed: int = 7):
    from bahis_tahmin.goals.validation import block_bootstrap_diff

    v = np.asarray(values, dtype=float)
    return block_bootstrap_diff(v, np.zeros_like(v), np.asarray(blocks), reps=reps, seed=seed)


def compare(d: pd.DataFrame, cand: str) -> dict:
    """Adayın P0'a göre farkları (toplam ve pazar başına)."""
    l0, lc = losses(d, "P0"), losses(d, cand)
    out = {"n": int(len(d)), "ort": float(lc["toplam"].mean())}
    for k in ("toplam", "A", "B", "C"):
        m, lo, hi = block_ci(lc[k] - l0[k], d["week"])
        out[k] = {"fark": m, "alt": lo, "ust": hi}
    return out


def select(dev: pd.DataFrame) -> tuple[str, dict]:
    res = {c: compare(dev, c) for c in CANDS[1:]}
    ok = [c for c in res if res[c]["toplam"]["ust"] < 0]
    best = min(ok, key=lambda c: res[c]["ort"]) if ok else "P0"
    return best, res


def accept(r: dict) -> bool:
    return r["toplam"]["ust"] < 0 and all(r[k]["alt"] <= 0 for k in "ABC")


def calibration(d: pd.DataFrame, cand: str) -> dict:
    from bahis_tahmin.goals.validation import calibration_bins, calibration_slope

    out = {}
    for k in "ABC":
        y = d[LABELS[k]].to_numpy(dtype=float)
        p = d[f"{cand}_{k}"].to_numpy(dtype=float)
        bins = calibration_bins(y, p)
        ece = sum(b["n"] * abs(b["tahmin"] - b["gercek"]) for b in bins) / max(1, len(y))
        out[k] = {"egim": calibration_slope(y, p)[0], "ece": float(ece), "ort_tahmin": float(p.mean()),
                  "gercek": float(y.mean())}
    return out


def evaluate(pred: pd.DataFrame, with_test: bool) -> dict:
    d = sample(pred)
    dev = d[d["fold"].isin(DEV_YEARS)]
    best, dev_res = select(dev)
    out = {"secilen": best, "gelistirme": dev_res, "gelistirme_n": int(len(dev)),
           "s_sezon": d.groupby("fold")["s"].mean().to_dict(), "p2_katsayi": pred.attrs.get("p2", {})}
    if with_test:
        test = d[d["fold"] >= TEST_FIRST]
        out["test"] = {c: compare(test, c) for c in CANDS[1:]}
        out["test_sezon"] = {c: {int(y): compare(g, c)["toplam"] for y, g in test.groupby("fold")} for c in CANDS[1:]}
        out["kalibrasyon"] = {c: calibration(test, c) for c in CANDS}
        out["karar"] = ("RED (uygun aday yok; P0 kalır)" if best == "P0"
                        else ("KABUL" if accept(out["test"][best]) else "RED"))
    return out


def _fmt(r: dict) -> str:
    return f"{r['fark']:+.5f} [{r['alt']:+.5f}; {r['ust']:+.5f}]"


def main(argv: list[str]) -> int:
    from bahis_tahmin.config import app_home
    from bahis_tahmin.data.store import DataStore

    if not argv:
        print(__doc__)
        return 2
    warnings.simplefilter("ignore")
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "piyasa_tahmin.pkl"
    if cache.exists():
        pred = pd.read_pickle(cache)
    else:
        st = DataStore(Path(os.environ.get("BAHIS_TAHMIN_HOME", app_home())))
        st.load()
        pred = walk_forward(features_with_odds(st.matches))
        pred.to_pickle(cache)
    test = "--test" in argv
    res = evaluate(pred, test)
    pd.to_pickle(res, out / ("piyasa_sonuc_test.pkl" if test else "piyasa_sonuc_gel.pkl"))
    print(f"Geliştirme (2017/18–2020/21): {res['gelistirme_n']} maç")
    for c, r in res["gelistirme"].items():
        print(f"  {c}: toplam {_fmt(r['toplam'])} · A {_fmt(r['A'])} · B {_fmt(r['B'])} · C {_fmt(r['C'])}")
    print(f"Seçilen aday: {res['secilen']}")
    if test:
        for c, r in res["test"].items():
            print(f"Test {c} ({r['n']} maç): toplam {_fmt(r['toplam'])} · A {_fmt(r['A'])} · B {_fmt(r['B'])} · "
                  f"C {_fmt(r['C'])}")
        print(f"Karar: {res['karar']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

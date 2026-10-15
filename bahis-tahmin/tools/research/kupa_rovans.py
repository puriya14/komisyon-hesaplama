"""KUPA-ROV-06: İki ayaklı eşleşmelerde rövanş etkisi (salt okunur sınama).

Kullanım (veri ve kayıtlı kupa modeli uygulamanın veri klasöründen, ``BAHIS_TAHMIN_HOME``; ağ isteği yok):

    python -I tools/research/kupa_rovans.py [çıktı_klasörü]          # geliştirme dönemi ve seçim
    python -I tools/research/kupa_rovans.py [çıktı_klasörü] --test   # test dönemi de (seçimden sonra)

ÖN KAYITLI KURAL (ilk çalıştırmadan, sonuç görülmeden yazıldı; 2026-10-16; docs/KUPA_ROV_06.md)

Soru: ilk maçın skoru rövanşta takımların gol beklentisini kupa modelinin hesabından farklılaştırıyor mu (önde olan
savunur, geride olan saldırır; eşleşme kopmuşsa tempo düşer)?

Eşleşme (iki ayaklı tur) tanımı:
- Aynı turnuva ve sezon; ikinci maçta ev sahibi ilk maçın deplasmanı (takım anahtarları ters); ikinci maç ilk maçtan
  3–70 gün sonra.
- Grup ve lig aşaması maçları hariç (tur adında "group", "gruppe" ya da "league phase" geçen ikinci maçlar).
- FA Cup (FAC) hariç: oradaki ters eşleşmeler tekrar maçıdır, toplam skorlu eşleşme değildir.
- Bir maç en fazla bir eşleşmenin ikinci maçı olur; ilk maç, kendisi başka bir eşleşmenin ikinci maçı olamaz. İkinci
  maç için en yakın uygun önceki maç ilk maç sayılır.
- d: rövanşın ev sahibinin ilk maçtaki gol farkı (attığı − yediği; ilk maçta deplasmandı). d_c = d, [−3, 3] aralığına
  kırpılmış. Skorlar normal süre (90 dk) skorlarıdır.

Veri: kayıtlı kupa modelinin örneklem dışı tahminleri (``CupEngine.oos``; λ' ev sahibi, ν' deplasman); yalnızca ikinci
maçlar (rövanşlar) ölçülür.

Adaylar (log λ', log ν''ye ek terim; katsayılar geliştirme döneminde Poisson en çok olabilirlikle):
- V1 (motivasyon, k = 1): λ'·e^(−β·d_c), ν'·e^(+β·d_c). β > 0: önde olan daha az, geride olan daha çok gol atar.
- V2 (kopmuş eşleşme, k = 1): |d| ≥ 3 ise iki gol beklentisi de × e^γ.
- V3 (V1 + V2, k = 2).

Dönemler: geliştirme 2019/20–2022/23, test 2023/24–2025/26 (sezon: Temmuz–Haziran). Rövanş sayısı az olduğundan
geliştirme dönemi diğer kupa çalışmalarından (2019/20–2021/22) bir sezon uzundur.

Seçim (geliştirme): ΔAIC = 2k − 2·(ℓ_aday − ℓ_V0) (rövanşların skor log olabilirliği, bağımsız Poisson). En küçük
ΔAIC < 0 olan aday seçilir; yoksa V0 kalır (değişiklik yok).

Test (yalnızca seçilen aday için karar; katsayılar geliştirme döneminden): KABUL = rövanş başına skor log-kaybı
farkının (aday − V0) hafta bloklu %95 üst sınırı < 0 VE 1X2 log-kaybı farkının %95 alt sınırı ≤ 0. Aksi halde RED.

Bilgi için (karara girmez): üç adayın test sonuçları; UEFA deplasman golü kuralının kalktığı 2021/22 öncesi/sonrası;
d'ye göre gerçekleşen − tahmin edilen gol.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

EPOCH = pd.Timestamp("2000-01-01")
DEV = (2019, 2020, 2021, 2022)
TEST = (2023, 2024, 2025)
GAP_MIN, GAP_MAX = 3, 70
EXCLUDE_STAGE = ("group", "gruppe", "league phase")
EXCLUDE_COMPS = ("FAC",)
CANDS = {"V1": 1, "V2": 1, "V3": 2}


def season_year(dates) -> np.ndarray:
    d = pd.to_datetime(pd.Series(dates))
    return np.where(d.dt.month >= 7, d.dt.year, d.dt.year - 1)


# ------------------------------------------------------------------------------------------- eşleşmeler
def ties(cups: pd.DataFrame) -> pd.DataFrame:
    """İkinci maç (rövanş) satırları: i2 (ikinci maç), i1 (ilk maç), d (rövanş ev sahibinin ilk maç gol farkı).

    ``cups`` tarihe göre sıralı ve 0..n−1 dizinli olmalı (kupa modelinin ``oos['i']`` ile aynı sıra)."""
    c = cups.copy()
    c["i"] = np.arange(len(c))
    c["day"] = (pd.to_datetime(c["date"]) - EPOCH).dt.days
    keep = ~c["comp"].isin(EXCLUDE_COMPS)
    c = c[keep]
    first_of: dict[int, tuple[int, int]] = {}
    used_second: set[int] = set()
    by = {}
    for r in c.itertuples(index=False):
        by.setdefault((r.comp, str(r.season), r.home_key, r.away_key), []).append((r.day, r.i))
    rows = []
    for r in c.sort_values("i").itertuples(index=False):
        st = str(r.stage or "").lower()
        if any(w in st for w in EXCLUDE_STAGE):
            continue
        cands = [(day, i) for day, i in by.get((r.comp, str(r.season), r.away_key, r.home_key), [])
                 if GAP_MIN <= r.day - day <= GAP_MAX and i not in used_second]
        if not cands:
            continue
        day1, i1 = max(cands)  # en yakın önceki maç
        if i1 in first_of or r.i in first_of:
            continue
        first_of[i1] = (r.i, day1)
        used_second.add(r.i)
        rows.append({"i2": int(r.i), "i1": int(i1)})
    out = pd.DataFrame(rows, columns=["i2", "i1"])
    if out.empty:
        out["d"] = []
        return out
    f = cups.iloc[out["i1"].to_numpy()]
    # rövanşın ev sahibi ilk maçta deplasmandı: attığı = ilk maçın deplasman golü
    out["d"] = f["ftag"].to_numpy(dtype=float) - f["fthg"].to_numpy(dtype=float)
    return out


# ------------------------------------------------------------------------------------------------ adaylar
def design(d: pd.DataFrame, cand: str) -> tuple[np.ndarray, np.ndarray]:
    """Ev sahibi log λ'ya ve deplasman log ν''ye eklenen değişkenler (n, k)."""
    dc = np.clip(d["d"].to_numpy(float), -3, 3)
    big = (np.abs(d["d"].to_numpy(float)) >= 3).astype(float)
    if cand == "V1":
        return -dc[:, None], dc[:, None]
    if cand == "V2":
        return big[:, None], big[:, None]
    if cand == "V3":
        return np.c_[-dc, big], np.c_[dc, big]
    raise KeyError(cand)


def rates(d: pd.DataFrame, cand: str, theta) -> tuple[np.ndarray, np.ndarray]:
    lam, nu = d["lam_c"].to_numpy(float), d["nu_c"].to_numpy(float)
    if cand == "V0":
        return lam, nu
    xh, xa = design(d, cand)
    t = np.asarray(theta, dtype=float)
    return lam * np.exp(xh @ t), nu * np.exp(xa @ t)


def score_nll(d: pd.DataFrame, lam, nu) -> np.ndarray:
    from scipy.special import gammaln

    hg, ag = d["hg"].to_numpy(float), d["ag"].to_numpy(float)
    return (lam - hg * np.log(lam) + gammaln(hg + 1)) + (nu - ag * np.log(nu) + gammaln(ag + 1))


def x2_ll(d: pd.DataFrame, lam, nu) -> np.ndarray:
    from bahis_tahmin.kupa.motor import probs_from_rates

    P, _, _ = probs_from_rates(lam, nu)
    hg, ag = d["hg"].to_numpy(), d["ag"].to_numpy()
    y = np.where(hg > ag, 0, np.where(hg == ag, 1, 2))
    return -np.log(np.clip(P[np.arange(len(y)), y], 1e-9, 1.0))


def fit(d: pd.DataFrame, cand: str) -> np.ndarray:
    from scipy.optimize import minimize

    xh, xa = design(d, cand)
    lam, nu = d["lam_c"].to_numpy(float), d["nu_c"].to_numpy(float)
    hg, ag = d["hg"].to_numpy(float), d["ag"].to_numpy(float)

    def f(t):
        lh, la = lam * np.exp(xh @ t), nu * np.exp(xa @ t)
        return (float(np.sum(lh - hg * np.log(lh)) + np.sum(la - ag * np.log(la))),
                xh.T @ (lh - hg) + xa.T @ (la - ag))

    return minimize(f, np.zeros(xh.shape[1]), jac=True, method="L-BFGS-B").x


def block_ci(values, blocks, reps: int = 2000, seed: int = 7):
    from bahis_tahmin.goals.validation import block_bootstrap_diff

    v = np.asarray(values, dtype=float)
    return block_bootstrap_diff(v, np.zeros_like(v), np.asarray(blocks), reps=reps, seed=seed)


def select(dev: pd.DataFrame) -> tuple[str, dict]:
    l0 = -score_nll(dev, *rates(dev, "V0", None)).sum()
    res = {}
    for c, k in CANDS.items():
        th = fit(dev, c)
        lc = -score_nll(dev, *rates(dev, c, th)).sum()
        res[c] = {"theta": th, "daic": float(2 * k - 2 * (lc - l0)), "dll": float(lc - l0)}
    ok = [c for c in CANDS if res[c]["daic"] < 0]
    return (min(ok, key=lambda c: res[c]["daic"]) if ok else "V0"), res


def compare(d: pd.DataFrame, cand: str, theta) -> dict:
    s0, s1 = score_nll(d, *rates(d, "V0", None)), score_nll(d, *rates(d, cand, theta))
    x0, x1 = x2_ll(d, *rates(d, "V0", None)), x2_ll(d, *rates(d, cand, theta))
    ms, los, his = block_ci(s1 - s0, d["week_b"])
    mx, lox, hix = block_ci(x1 - x0, d["week_b"])
    return {"n": int(len(d)), "skor": {"fark": ms, "alt": los, "ust": his}, "x2": {"fark": mx, "alt": lox, "ust": hix}}


def accept(r: dict) -> bool:
    return r["skor"]["ust"] < 0 and r["x2"]["alt"] <= 0


def residual_table(d: pd.DataFrame) -> pd.DataFrame:
    """d'ye göre rövanş ev sahibinin ve deplasmanının gerçekleşen − tahmin edilen golü (bilgi)."""
    g = d.assign(dk=np.clip(d["d"], -3, 3).astype(int), ev_fark=d["hg"] - d["lam_c"], dep_fark=d["ag"] - d["nu_c"])
    return g.groupby("dk").agg(n=("hg", "size"), ev_tahmin=("lam_c", "mean"), ev_gercek=("hg", "mean"),
                               dep_tahmin=("nu_c", "mean"), dep_gercek=("ag", "mean")).round(3)


def evaluate(d: pd.DataFrame, with_test: bool) -> dict:
    dev = d[d["fold"].isin(DEV)]
    best, res = select(dev)
    out = {"secilen": best, "gelistirme": res, "n_gel": int(len(dev))}
    if with_test:
        test = d[d["fold"].isin(TEST)]
        out["test"] = {c: compare(test, c, res[c]["theta"]) for c in CANDS}
        out["kalinti"] = residual_table(d)
        out["karar"] = ("RED (uygun aday yok; V0 kalır)" if best == "V0"
                        else ("KABUL" if accept(out["test"][best]) else "RED"))
    return out


def second_legs(oos: pd.DataFrame, cups_sorted: pd.DataFrame) -> pd.DataFrame:
    t = ties(cups_sorted)
    d = oos.merge(t, left_on="i", right_on="i2", how="inner")
    d["fold"] = season_year(d["date"])
    d["week_b"] = (pd.to_datetime(d["date"]) - EPOCH).dt.days // 7
    return d


def main(argv: list[str]) -> int:
    from bahis_tahmin.config import app_home
    from bahis_tahmin.data.store import DataStore
    from bahis_tahmin.kupa.motor import CupEngine

    warnings.simplefilter("ignore")
    home = Path(os.environ.get("BAHIS_TAHMIN_HOME", app_home()))
    st = DataStore(home)
    st.load()
    eng = CupEngine.load(home / "kupa_engine.joblib")
    eng = eng[0] if isinstance(eng, tuple) else eng
    cups = st.cup_matches.sort_values("date", kind="mergesort").reset_index(drop=True)
    oos = eng.oos
    if not (cups.loc[oos["i"], "home_key"].to_numpy() == oos["home_key"].to_numpy()).all():
        print("Kupa kaydı ile örneklem dışı tablo eşleşmiyor (model güncel veriyle yeniden eğitilmeli).")
        return 2
    d = second_legs(oos, cups)
    res = evaluate(d, "--test" in argv)
    print(f"Rövanş (örneklem dışı): {len(d)} · geliştirme {res['n_gel']}")
    for c, r in res["gelistirme"].items():
        print(f"  {c}: katsayılar {np.round(r['theta'], 4).tolist()} Δℓ={r['dll']:+.2f} ΔAIC={r['daic']:+.2f}")
    print(f"Seçilen aday: {res['secilen']}")
    if "--test" in argv:
        for c, r in res["test"].items():
            print(f"Test {c} ({r['n']} maç): skor {r['skor']['fark']:+.5f} [{r['skor']['alt']:+.5f}; "
                  f"{r['skor']['ust']:+.5f}] · 1X2 {r['x2']['fark']:+.5f} [{r['x2']['alt']:+.5f}; "
                  f"{r['x2']['ust']:+.5f}]")
        print(res["kalinti"].to_string())
        print(f"Karar: {res['karar']}")
    out = [x for x in argv if not x.startswith("--")]
    if out:
        Path(out[0]).mkdir(parents=True, exist_ok=True)
        pd.to_pickle(res, Path(out[0]) / ("kupa_rovans_test.pkl" if "--test" in argv else "kupa_rovans_gel.pkl"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

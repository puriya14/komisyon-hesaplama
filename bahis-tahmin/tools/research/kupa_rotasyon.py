"""KUPA-ROT-05: Kupada rotasyon (salt okunur sınama).

Kullanım (veri ve kayıtlı kupa modeli uygulamanın veri klasöründen, ``BAHIS_TAHMIN_HOME``; ağ isteği yok):

    python -I tools/research/kupa_rotasyon.py [çıktı_klasörü]          # geliştirme dönemi ve seçim
    python -I tools/research/kupa_rotasyon.py [çıktı_klasörü] --test   # test dönemi de (seçimden sonra)

ÖN KAYITLI KURAL (ilk çalıştırmadan, sonuç görülmeden yazıldı; 2026-10-15; docs/KUPA_ROT_05.md)

Soru: büyük kulüplerin kupada yedek oynatması (rotasyon) kupa modelinin gol beklentilerinde sistematik bir hata
bırakıyor mu? Rotasyonun iki gözlenebilir göstergesi sınanır.

Veri: kayıtlı kupa modelinin örneklem dışı (ileriye dönük) tahminleri (``CupEngine.oos``; her hafta yalnızca önceki
maçlarla, kalibre ve dinamik gol düzeyli λ', ν'). Maçın turu kupa kaydından; takımların maç takvimi depodaki lig ve kupa
maçlarından.

Tanımlar:
- Güçlü taraf: λ' ≥ ν' ise ev sahibi, değilse deplasman.
- Erken tur: yurt içi kupa (doğrulama grubu YURTICI) ve turu çeyrek final, yarı final ya da final değil (tur adında
  "quarter", "semi", "final" geçmiyor; büyük/küçük harf duyarsız).
- Takvimi bilinen takım: maçtan önceki ya da sonraki 60 gün içinde depoda lig maçı olan takım.
- Yoğun fikstür: takvimi bilinen takımın önceki maçından bu yana ya da sonraki maçına kadar en fazla 3 gün olması
  (önceki/sonraki maç: herhangi bir lig ya da kupa maçı, aynı gün hariç).

Adaylar (log λ'ya ek terim; katsayılar geliştirme döneminde Poisson en çok olabilirlikle):
- R0: mevcut model.
- R1 (erken tur favorisi): erken turda güçlü tarafın gol beklentisi × e^a, zayıf tarafınki × e^b.
- R2 (yoğun fikstür; bütün kupa maçları): yoğun fikstürlü takımın gol beklentisi × e^a, rakibininki × e^b (iki
  takım da yoğunsa ikisi de uygulanır).

Seçim (geliştirme dönemi: sezon 2019/20–2021/22, tarihten: Temmuz–Haziran):
- Her aday için ΔAIC = 2·k − 2·(ℓ_aday − ℓ_R0); ℓ bütün örneklem dışı maçların skor (bağımsız Poisson) log
  olabilirliği, k = 2.
- En küçük ΔAIC < 0 olan aday seçilir; yoksa R0 kalır (değişiklik yok).

Test (2022/23–2025/26, ``--test``; yalnızca seçilen aday için karar; katsayılar geliştirme döneminden, yeniden
kestirilmez):
- KABUL: maç başına skor log-kaybı farkının (aday − R0) hafta bloklu %95 üst sınırı < 0 VE 1X2 log-kaybı farkının
  %95 alt sınırı ≤ 0 (1X2 anlamlı kötüleşmiyor). Aksi halde RED: uygulama değişmez.

Bilgi için (karara girmez): iki adayın test sonuçları, gruplara göre farklar, katsayıların e^a / e^b değerleri,
gösterge sıklıkları.
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
DEV = (2019, 2020, 2021)
TEST = (2022, 2023, 2024, 2025)
KNOWN_WINDOW = 60
BUSY_DAYS = 3
LATE = ("quarter", "semi", "final")
CANDS = ("R1", "R2")


def season_year(dates) -> np.ndarray:
    d = pd.to_datetime(pd.Series(dates))
    return np.where(d.dt.month >= 7, d.dt.year, d.dt.year - 1)


# ------------------------------------------------------------------------------------------- göstergeler
def schedules(matches: pd.DataFrame, cups: pd.DataFrame) -> tuple[dict, dict]:
    """Takım anahtarı → sıralı maç günleri (lig + kupa) ve → lig maç günleri."""
    from bahis_tahmin.kupa.motor import key_of

    allday: dict[str, list] = {}
    league: dict[str, list] = {}
    days = (pd.to_datetime(matches["date"]) - EPOCH).dt.days.to_numpy()
    for lg, h, a, d in zip(matches["league"], matches["home"], matches["away"], days):
        for t in (key_of(lg, h), key_of(lg, a)):
            allday.setdefault(t, []).append(int(d))
            league.setdefault(t, []).append(int(d))
    cdays = (pd.to_datetime(cups["date"]) - EPOCH).dt.days.to_numpy()
    for h, a, d in zip(cups["home_key"], cups["away_key"], cdays):
        for t in (h, a):
            allday.setdefault(t, []).append(int(d))
    return ({k: np.unique(v) for k, v in allday.items()}, {k: np.unique(v) for k, v in league.items()})


def rest_gap(sched: dict, key: str, day: int) -> tuple[float, float]:
    """Önceki maçtan bu yana ve sonraki maça kadar gün (aynı gün hariç; yoksa NaN)."""
    d = sched.get(key)
    if d is None or len(d) == 0:
        return np.nan, np.nan
    i = np.searchsorted(d, day, side="left")
    j = np.searchsorted(d, day, side="right")
    prev = day - d[i - 1] if i > 0 else np.nan
    nxt = d[j] - day if j < len(d) else np.nan
    return float(prev), float(nxt)


def known(league_days: dict, key: str, day: int) -> bool:
    d = league_days.get(key)
    if d is None or len(d) == 0:
        return False
    i = np.searchsorted(d, day - KNOWN_WINDOW, side="left")
    return i < len(d) and d[i] <= day + KNOWN_WINDOW


def is_early(vgroup: str, stage) -> bool:
    s = str(stage or "").lower()
    return vgroup == "YURTICI" and not any(w in s for w in LATE)


def indicators(oos: pd.DataFrame, cups_sorted: pd.DataFrame, sched: dict, league_days: dict) -> pd.DataFrame:
    """Örneklem dışı satırlara gösterge sütunları: early, fav_home, busy_h, busy_a, known_h, known_a."""
    d = oos.copy()
    st = cups_sorted["stage"].to_numpy()
    d["stage"] = [st[int(i)] for i in d["i"]]
    d["day"] = (pd.to_datetime(d["date"]) - EPOCH).dt.days.astype(int)
    d["early"] = [is_early(g, s) for g, s in zip(d["vgroup"], d["stage"])]
    d["fav_home"] = d["lam_c"] >= d["nu_c"]
    for side in ("h", "a"):
        col = "home_key" if side == "h" else "away_key"
        kn, busy, rest, gap = [], [], [], []
        for k, day in zip(d[col], d["day"]):
            r, g = rest_gap(sched, k, day)
            ok = known(league_days, k, day)
            kn.append(ok)
            rest.append(r)
            gap.append(g)
            busy.append(bool(ok and np.nanmin([r, g, np.inf]) <= BUSY_DAYS))
        d[f"known_{side}"], d[f"busy_{side}"], d[f"rest_{side}"], d[f"gap_{side}"] = kn, busy, rest, gap
    d["fold"] = season_year(d["date"])
    d["week_b"] = d["day"] // 7
    return d


# ------------------------------------------------------------------------------------------------ adaylar
def design(d: pd.DataFrame, cand: str) -> tuple[np.ndarray, np.ndarray]:
    """(ev sahibi log λ'ya eklenen [x_a, x_b], deplasman log ν'ya eklenen [x_a, x_b]) — her biri (n, 2)."""
    if cand == "R1":
        e = d["early"].to_numpy(bool)
        fh = d["fav_home"].to_numpy(bool)
        xh = np.c_[e & fh, e & ~fh].astype(float)  # ev: güçlüyse a, zayıfsa b
        xa = np.c_[e & ~fh, e & fh].astype(float)  # deplasman: güçlüyse a, zayıfsa b
        return xh, xa
    if cand == "R2":
        bh = d["busy_h"].to_numpy(bool).astype(float)
        ba = d["busy_a"].to_numpy(bool).astype(float)
        return np.c_[bh, ba], np.c_[ba, bh]  # yoğun takımın kendi golü a, rakibinin golü b
    raise KeyError(cand)


def rates(d: pd.DataFrame, cand: str, theta) -> tuple[np.ndarray, np.ndarray]:
    lam, nu = d["lam_c"].to_numpy(float), d["nu_c"].to_numpy(float)
    if cand == "R0":
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
        val = float(np.sum(lh - hg * np.log(lh)) + np.sum(la - ag * np.log(la)))
        g = xh.T @ (lh - hg) + xa.T @ (la - ag)
        return val, g

    return minimize(f, np.zeros(2), jac=True, method="L-BFGS-B").x


def block_ci(values, blocks, reps: int = 2000, seed: int = 7):
    from bahis_tahmin.goals.validation import block_bootstrap_diff

    v = np.asarray(values, dtype=float)
    return block_bootstrap_diff(v, np.zeros_like(v), np.asarray(blocks), reps=reps, seed=seed)


def select(dev: pd.DataFrame) -> tuple[str, dict]:
    l0 = -score_nll(dev, *rates(dev, "R0", None)).sum()
    res = {}
    for c in CANDS:
        th = fit(dev, c)
        lc = -score_nll(dev, *rates(dev, c, th)).sum()
        res[c] = {"theta": th, "exp": np.exp(th), "daic": float(2 * 2 - 2 * (lc - l0)), "dll": float(lc - l0)}
    ok = [c for c in CANDS if res[c]["daic"] < 0]
    return (min(ok, key=lambda c: res[c]["daic"]) if ok else "R0"), res


def compare(d: pd.DataFrame, cand: str, theta) -> dict:
    s0, s1 = score_nll(d, *rates(d, "R0", None)), score_nll(d, *rates(d, cand, theta))
    x0, x1 = x2_ll(d, *rates(d, "R0", None)), x2_ll(d, *rates(d, cand, theta))
    ms, los, his = block_ci(s1 - s0, d["week_b"])
    mx, lox, hix = block_ci(x1 - x0, d["week_b"])
    return {"n": int(len(d)), "skor": {"fark": ms, "alt": los, "ust": his}, "x2": {"fark": mx, "alt": lox, "ust": hix}}


def accept(r: dict) -> bool:
    return r["skor"]["ust"] < 0 and r["x2"]["alt"] <= 0


def evaluate(d: pd.DataFrame, with_test: bool) -> dict:
    dev = d[d["fold"].isin(DEV)]
    best, res = select(dev)
    out = {"secilen": best, "gelistirme": res, "n_gel": int(len(dev)),
           "siklik": {"erken": float(d["early"].mean()), "yogun_ev": float(d["busy_h"].mean()),
                      "yogun_dep": float(d["busy_a"].mean()), "bilinen_ev": float(d["known_h"].mean()),
                      "bilinen_dep": float(d["known_a"].mean())}}
    if with_test:
        test = d[d["fold"].isin(TEST)]
        out["test"] = {c: compare(test, c, res[c]["theta"]) for c in CANDS}
        out["test_grup"] = {c: {g: compare(x, c, res[c]["theta"]) for g, x in test.groupby("vgroup")} for c in CANDS}
        out["karar"] = ("RED (uygun aday yok; R0 kalır)" if best == "R0"
                        else ("KABUL" if accept(out["test"][best]) else "RED"))
    return out


def load(home: Path):
    from bahis_tahmin.data.store import DataStore
    from bahis_tahmin.kupa.motor import CupEngine

    st = DataStore(home)
    st.load()
    eng = CupEngine.load(home / "kupa_engine.joblib")
    eng = eng[0] if isinstance(eng, tuple) else eng
    cups = st.cup_matches.sort_values("date", kind="mergesort").reset_index(drop=True)
    return st.matches, cups, eng


def main(argv: list[str]) -> int:
    from bahis_tahmin.config import app_home

    warnings.simplefilter("ignore")
    home = Path(os.environ.get("BAHIS_TAHMIN_HOME", app_home()))
    matches, cups, eng = load(home)
    oos = eng.oos
    ok = (cups.loc[oos["i"], "home_key"].to_numpy() == oos["home_key"].to_numpy()).all()
    if not ok:
        print("Kupa kaydı ile örneklem dışı tablo eşleşmiyor (model güncel veriyle yeniden eğitilmeli).")
        return 2
    sched, ldays = schedules(matches, cups)
    d = indicators(oos, cups, sched, ldays)
    res = evaluate(d, "--test" in argv)
    print(f"Geliştirme ({len(DEV)} sezon): {res['n_gel']} maç · sıklıklar {res['siklik']}")
    for c, r in res["gelistirme"].items():
        print(f"  {c}: e^a={r['exp'][0]:.3f} e^b={r['exp'][1]:.3f} Δℓ={r['dll']:+.2f} ΔAIC={r['daic']:+.2f}")
    print(f"Seçilen aday: {res['secilen']}")
    if "--test" in argv:
        for c, r in res["test"].items():
            print(f"Test {c} ({r['n']} maç): skor {r['skor']['fark']:+.5f} [{r['skor']['alt']:+.5f}; "
                  f"{r['skor']['ust']:+.5f}] · 1X2 {r['x2']['fark']:+.5f} [{r['x2']['alt']:+.5f}; "
                  f"{r['x2']['ust']:+.5f}]")
            for g, x in res["test_grup"][c].items():
                print(f"    {g} ({x['n']}): skor {x['skor']['fark']:+.5f} [{x['skor']['alt']:+.5f}; "
                      f"{x['skor']['ust']:+.5f}] · 1X2 {x['x2']['fark']:+.5f}")
        print(f"Karar: {res['karar']}")
    out = [x for x in argv if not x.startswith("--")]
    if out:  # isteğe bağlı çıktı klasörü (veri klasörüne yazılmaz)
        Path(out[0]).mkdir(parents=True, exist_ok=True)
        pd.to_pickle(res, Path(out[0]) / ("kupa_rotasyon_test.pkl" if "--test" in argv else "kupa_rotasyon_gel.pkl"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

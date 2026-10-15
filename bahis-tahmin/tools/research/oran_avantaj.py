"""ORAN-02: En iyi oranı aramanın (line shopping) değeri — gerçek oranlarla (salt okunur, modelsiz).

Kullanım (veri uygulamanın veri klasöründen, ``BAHIS_TAHMIN_HOME``; ağ isteği yok):

    python -I tools/research/oran_avantaj.py <çıktı_klasörü>          # betimsel bölüm + geliştirme dönemi seçimi
    python -I tools/research/oran_avantaj.py <çıktı_klasörü> --test   # test dönemi de (seçimden sonra)

ÖN KAYITLI KURAL (ilk çalıştırmadan, sonuç görülmeden yazıldı; 2026-10-15; docs/ORAN_01_02.md)

Veri: depodaki lig maçları; football-data ortalama (``o_*``) ve en yüksek (``omax_*``) oranları, maç öncesi toplanır.
Pazarlar: 1X2 (üç seçenek) ve 2,5 Üst/Alt (iki seçenek), ayrı ayrı. Bir pazarın bütün seçeneklerinde iki oran türü de
1'den büyük olan maçlar.

A) Betimsel (seçim yok): sezon başına piyasa marjı (Σ 1/oran − 1) ortalama ve en yüksek oranla. Her maçta her seçeneğe
   1 birim oynamanın getirisi (ROI) ortalama ve en yüksek oranla; aradaki fark "en iyi oranın değeri"dir.

B) Ortalama-oran uzlaşısı stratejisi (modelsiz):
   - Uzlaşı olasılığı = ortalama oranların marjı orantılı olarak çıkarılmış hali.
   - Maç başına en fazla bir seçenek: EV = uzlaşı olasılığı × en yüksek oran − 1 en yüksek olan, EV ≥ e ise; sabit
     1 birim, en yüksek oranla ödenir.
   - e, geliştirme döneminde (2016/17–2020/21) {0; 0,01; 0,02; 0,03; 0,04; 0,05; 0,07; 0,10} içinden en az 500
     bahisle en yüksek ROI'yi veren değer (pazar başına ayrı).
   - Test (2021/22 ve sonrası, ``--test``): ROI'nin hafta bloklu %95 alt sınırı > 0 → "kazandırıyor (bu veride)"; üst
     sınırı < 0 → "kaybettiriyor"; aksi halde "belirsiz". Aynı seçimlerin ortalama oranla ödenmesi bilgi içindir.

Sınır (sonuçtan bağımsız, baştan): "en yüksek oran" çok sayıda şirketin toplama anındaki en iyisidir. Tek bir kişinin
hepsinde hesabı olmayabilir, oran kısa sürede değişebilir, hatalı/eski oran olabilir, kazanan hesaplar sınırlanabilir.
Bu yüzden B'nin sonucu ulaşılabilecek getirinin üst sınırıdır.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

DEV_YEARS = (2016, 2017, 2018, 2019, 2020)
TEST_FIRST = 2021
GRID = (0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10)
MIN_BETS = 500
MARKETS = {
    "1X2": {"avg": ("o_h", "o_d", "o_a"), "max": ("omax_h", "omax_d", "omax_a"), "names": ("1", "X", "2")},
    "OU25": {"avg": ("o_o25", "o_u25"), "max": ("omax_o25", "omax_u25"), "names": ("Üst", "Alt")},
}


def season_year(dates) -> np.ndarray:
    d = pd.to_datetime(pd.Series(dates))
    return np.where(d.dt.month >= 7, d.dt.year, d.dt.year - 1)


def outcomes(df: pd.DataFrame, market: str) -> np.ndarray:
    """Seçenek başına kazandı mı (satır × seçenek, 0/1)."""
    h, a = df["fthg"].to_numpy(dtype=float), df["ftag"].to_numpy(dtype=float)
    if market == "1X2":
        return np.c_[h > a, h == a, h < a].astype(float)
    over = (h + a) >= 3
    return np.c_[over, ~over].astype(float)


def market_frame(matches: pd.DataFrame, market: str) -> pd.DataFrame:
    """Bir pazarın örneklemi: iki oran türü de tam ve sonuç bilinen maçlar; sezon yılı ve hafta."""
    spec = MARKETS[market]
    cols = list(spec["avg"]) + list(spec["max"])
    d = matches[["league", "date", "home", "away", "fthg", "ftag"] + cols].copy()
    ok = d[["fthg", "ftag"]].notna().all(axis=1)
    for c in cols:
        ok &= pd.to_numeric(d[c], errors="coerce") > 1.0
    d = d[ok].reset_index(drop=True)
    d["date"] = pd.to_datetime(d["date"])
    d["fold"] = season_year(d["date"])
    d["week"] = (d["date"] - pd.Timestamp("2000-01-03")).dt.days // 7
    return d


def margin(odds: np.ndarray) -> np.ndarray:
    return (1.0 / odds).sum(axis=1) - 1.0


def consensus(avg: np.ndarray) -> np.ndarray:
    inv = 1.0 / avg
    return inv / inv.sum(axis=1, keepdims=True)


def block_ci(values, blocks, reps: int = 2000, seed: int = 7) -> tuple[float, float, float]:
    from bahis_tahmin.goals.validation import block_bootstrap_diff

    v = np.asarray(values, dtype=float)
    return block_bootstrap_diff(v, np.zeros_like(v), np.asarray(blocks), reps=reps, seed=seed)


def _roi(profit, weeks) -> dict:
    profit = np.asarray(profit, dtype=float)
    if profit.size == 0:
        return {"n": 0, "roi": float("nan"), "alt": float("nan"), "ust": float("nan")}
    m, lo, hi = block_ci(profit, weeks)
    return {"n": int(profit.size), "roi": m, "alt": lo, "ust": hi}


def bet_all(d: pd.DataFrame, market: str, kind: str) -> dict:
    """Her maçta her seçeneğe 1 birim: ROI (kind: 'avg' veya 'max')."""
    odds = d[list(MARKETS[market][kind])].to_numpy(dtype=float)
    y = outcomes(d, market)
    profit = (y * odds - 1.0).ravel()
    weeks = np.repeat(d["week"].to_numpy(), odds.shape[1])
    return _roi(profit, weeks)


def descriptive(d: pd.DataFrame, market: str) -> pd.DataFrame:
    rows = []
    for y, g in d.groupby("fold"):
        avg = g[list(MARKETS[market]["avg"])].to_numpy(dtype=float)
        mx = g[list(MARKETS[market]["max"])].to_numpy(dtype=float)
        a, m = bet_all(g, market, "avg"), bet_all(g, market, "max")
        rows.append({"sezon": f"{y}/{(y + 1) % 100:02d}", "mac": len(g), "marj_ort": float(margin(avg).mean()),
                     "marj_enyuksek": float(margin(mx).mean()), "negatif_marj_payi": float((margin(mx) < 0).mean()),
                     "roi_hepsi_ort": a["roi"], "roi_hepsi_enyuksek": m["roi"]})
    return pd.DataFrame(rows)


def strategy(d: pd.DataFrame, market: str, e: float, pay: str = "max") -> pd.DataFrame:
    """Uzlaşı stratejisi: maç başına en fazla bir seçenek. Dönen: seçilen bahisler (hafta, seçenek, oran, kâr)."""
    spec = MARKETS[market]
    p = consensus(d[list(spec["avg"])].to_numpy(dtype=float))
    mx = d[list(spec["max"])].to_numpy(dtype=float)
    ev = p * mx - 1.0
    k = ev.argmax(axis=1)
    best = ev[np.arange(len(d)), k]
    sel = best >= e
    paid = d[list(spec[pay])].to_numpy(dtype=float)[np.arange(len(d)), k]
    win = outcomes(d, market)[np.arange(len(d)), k] == 1
    out = d.loc[sel, ["league", "date", "fold", "week"]].copy()
    out["secenek"] = np.array(spec["names"])[k[sel]]
    out["oran"] = paid[sel]
    out["ev"] = best[sel]
    out["kar"] = np.where(win[sel], paid[sel] - 1.0, -1.0)
    return out


def roi(b: pd.DataFrame) -> dict:
    r = _roi(b["kar"], b["week"])
    if r["n"]:
        r["ort_oran"] = float(b["oran"].mean())
        r["secenek"] = b["secenek"].value_counts(normalize=True).round(3).to_dict()
    return r


def select_threshold(dev: pd.DataFrame, market: str) -> tuple[float, list]:
    rows = [(e, roi(strategy(dev, market, e))) for e in GRID]
    ok = [(e, r) for e, r in rows if r["n"] >= MIN_BETS]
    return (max(ok, key=lambda t: t[1]["roi"])[0] if ok else GRID[0]), rows


def verdict(r: dict) -> str:
    if not r["n"]:
        return "bahis yok"
    if r["alt"] > 0:
        return "kazandırıyor (bu veride)"
    if r["ust"] < 0:
        return "kaybettiriyor"
    return "belirsiz"


def evaluate(matches: pd.DataFrame, with_test: bool) -> dict:
    out = {}
    for mk in MARKETS:
        d = market_frame(matches, mk)
        dev, test = d[d["fold"].isin(DEV_YEARS)], d[d["fold"] >= TEST_FIRST]
        e, grid = select_threshold(dev, mk)
        res = {"betimsel": descriptive(d, mk), "hepsi_ort_gel": bet_all(dev, mk, "avg"),
               "hepsi_enyuksek_gel": bet_all(dev, mk, "max"), "esik": e, "gelistirme_izgara": grid}
        if with_test:
            b = strategy(test, mk, e)
            res.update({
                "hepsi_ort_test": bet_all(test, mk, "avg"), "hepsi_enyuksek_test": bet_all(test, mk, "max"),
                "test": roi(b), "test_ortalama_odeme": roi(strategy(test, mk, e, pay="avg")),
                "test_izgara": [(g, roi(strategy(test, mk, g))) for g in GRID],
                "test_lig": {lg: roi(g) for lg, g in b.groupby("league")},
                "test_sezon": {int(y): roi(g) for y, g in b.groupby("fold")},
            })
            res["karar"] = verdict(res["test"])
        out[mk] = res
    return out


def _fmt(r: dict) -> str:
    if not r.get("n"):
        return "bahis yok"
    return f"{r['n']} bahis, ROI {100 * r['roi']:+.2f}% [%95: {100 * r['alt']:+.2f}%; {100 * r['ust']:+.2f}%]"


def main(argv: list[str]) -> int:
    from bahis_tahmin.config import app_home
    from bahis_tahmin.data.store import DataStore

    if not argv:
        print(__doc__)
        return 2
    warnings.simplefilter("ignore")
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    st = DataStore(Path(os.environ.get("BAHIS_TAHMIN_HOME", app_home())))
    st.load()
    test = "--test" in argv
    res = evaluate(st.matches, test)
    pd.to_pickle(res, out / ("oran_avantaj_test.pkl" if test else "oran_avantaj_gel.pkl"))
    for mk, r in res.items():
        print(f"\n=== {mk} ===")
        print(r["betimsel"].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
        print(f"Geliştirme, her seçeneğe 1 birim: ortalama oranla {_fmt(r['hepsi_ort_gel'])}; en yüksek oranla "
              f"{_fmt(r['hepsi_enyuksek_gel'])}")
        for e, g in r["gelistirme_izgara"]:
            print(f"  e = {e:.2f}: {_fmt(g)}")
        print(f"Seçilen eşik e = {r['esik']:.2f}")
        if test:
            print(f"Test, her seçeneğe 1 birim: ortalama {_fmt(r['hepsi_ort_test'])}; en yüksek "
                  f"{_fmt(r['hepsi_enyuksek_test'])}")
            print(f"Test, uzlaşı stratejisi (en yüksek oranla): {_fmt(r['test'])} → {r['karar']}")
            print(f"Aynı seçimler ortalama oranla ödenseydi: {_fmt(r['test_ortalama_odeme'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

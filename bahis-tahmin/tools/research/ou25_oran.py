"""ORAN-01/02: Gol Pazarları modelinin 2,5 Üst/Alt olasılığının gerçek oranlarla sınanması (salt okunur).

Kullanım (veri uygulamanın veri klasöründen, ``BAHIS_TAHMIN_HOME``; ağ isteği yok):

    python -I tools/research/ou25_oran.py <çıktı_klasörü>          # geliştirme dönemi ve eşik seçimi
    python -I tools/research/ou25_oran.py <çıktı_klasörü> --test   # test dönemi de (seçimden sonra)

İlk çalıştırma özellikleri ve haftalık (sezonluk) ileriye dönük tahminleri ``<çıktı_klasörü>/ou25_tahmin.pkl`` olarak
saklar; sonraki çalıştırmalar onu kullanır.

ÖN KAYITLI KURAL (ilk çalıştırmadan, sonuç görülmeden yazıldı; 2026-10-15; docs/ORAN_01_02.md)

Model ve veri:
- Model: Gol Pazarları motorunun seçili varyantı (``goals.engine.SELECTED_VARIANT``). Olasılık "maç sonu 2,5 Üst"
  (``FT_O25``). Her sezon yalnızca önceki sezonların maçlarıyla eğitilir; özellikler maç gününden önceki maçlardan
  gelir. Bahis oranları modele girmez.
- Oran: depodaki ortalama 2,5 Üst/Alt oranları (``o_o25``, ``o_u25``; football-data ortalaması, maç öncesi toplanır;
  kapanış oranı değildir). Sonuç: normal süre toplam gol ≥ 3.
- Dönemler: ısınma 2016/17 (yalnızca takım güçleri); geliştirme 2017/18–2020/21; test 2021/22 ve sonrası. Test
  dönemi seçimden SONRA raporlanır (``--test``).

Ölçütler:
- Log-kayıp: model, piyasa (marj orantılı olarak çıkarılmış olasılık) ve taban (önceki sezonların oranı). Model −
  piyasa farkı için hafta bloklu %95 aralık.
- Bilgi testi: geliştirme döneminde y ~ logit(p_piyasa) + logit(p_model) lojistik regresyonu. Test döneminde birleşik
  tahminin piyasaya göre log-kayıp farkı ve aralığı.
- Bahis kuralı:
  - maç başına en fazla bir seçim (Üst ya da Alt): EV = p·oran − 1 en yüksek olan, EV ≥ e ise;
  - sabit 1 birim;
  - e, geliştirme döneminde {0; 0,02; 0,04; 0,06; 0,08; 0,10; 0,15} içinden en az 500 bahisle en yüksek ROI'yi veren
    değer.
- Karar (test dönemi, ortalama oran): ROI'nin hafta bloklu %95 alt sınırı > 0 → "kazandırıyor (bu veride)"; üst
  sınırı < 0 → "kaybettiriyor"; aksi halde "belirsiz".
- ORAN-02 (en iyi oran): aynı seçimler en yüksek oranla (``omax_*``) ayrıca ödenir. Ayrıca seçim de en yüksek oranla
  yapılır. Bilgi içindir, kuralı değiştirmez. Piyasa marjı (ortalama ve en yüksek oran) modelden bağımsız raporlanır.
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
GRID = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15)
MIN_BETS = 500
KEY = ["league", "date", "home", "away"]
ODDS = ["o_o25", "o_u25", "omax_o25", "omax_u25"]


def season_year(dates) -> np.ndarray:
    d = pd.to_datetime(pd.Series(dates))
    return np.where(d.dt.month >= 7, d.dt.year, d.dt.year - 1)


# ------------------------------------------------------------------------------------------- tahmin hattı
def walk_forward_ou(matches: pd.DataFrame, variant: str | None = None, progress=print) -> pd.DataFrame:
    """Sezon başına ileriye dönük 2,5 Üst olasılığı: Y sezonu, WARMUP_YEAR < sezon < Y maçlarıyla eğitilen modelle.
    Dönen tablo: anahtar, sezon yılı, gol, olasılık ve oranlar."""
    from bahis_tahmin.goals.engine import SELECTED_VARIANT
    from bahis_tahmin.goals.features import build_goal_features
    from bahis_tahmin.goals.model import GoalModel, usable_rows

    variant = variant or SELECTED_VARIANT
    feat, _ = build_goal_features(matches)
    feat = feat.copy()
    feat["fold"] = season_year(feat["date"])
    parts = []
    for y in sorted(int(v) for v in feat["fold"].unique() if v > WARMUP_YEAR):
        train = feat[(feat["fold"] < y) & (feat["fold"] >= WARMUP_YEAR)]
        test = feat[feat["fold"] == y]
        if test.empty or len(train) < 2000:
            continue
        if progress:
            progress(f"sezon {y}/{(y + 1) % 100:02d}: {len(train)} eğitim, {len(test)} tahmin")
        m = GoalModel(variant).fit(train)
        p = m.predict(test)
        out = test[KEY + ["fold", "fthg", "ftag"]].copy()
        out["p_o25"] = np.where(usable_rows(test), p["FT_O25"], np.nan)
        parts.append(out)
    pred = pd.concat(parts, ignore_index=True)
    odds = matches[KEY + ODDS].copy()
    odds["date"] = pd.to_datetime(odds["date"])
    pred["date"] = pd.to_datetime(pred["date"])
    return pred.merge(odds, on=KEY, how="left", validate="one_to_one")


# ------------------------------------------------------------------------------------------------ ölçüm
def market_prob(o_over, o_under) -> np.ndarray:
    """Marjı orantılı olarak çıkarılmış piyasa 2,5 Üst olasılığı."""
    io, iu = 1.0 / np.asarray(o_over, dtype=float), 1.0 / np.asarray(o_under, dtype=float)
    return io / (io + iu)


def _ll(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def sample(pred: pd.DataFrame) -> pd.DataFrame:
    """Ölçüm örneklemi: olasılık, iki oran ve sonuç bilinen maçlar; y, piyasa olasılığı, hafta."""
    d = pred[np.isfinite(pred["p_o25"]) & (pred["o_o25"] > 1.0) & (pred["o_u25"] > 1.0)
             & pred["fthg"].notna() & pred["ftag"].notna()].copy()
    d["y"] = ((d["fthg"] + d["ftag"]) >= 3).astype(float)
    d["p_mkt"] = market_prob(d["o_o25"], d["o_u25"])
    d["week"] = (pd.to_datetime(d["date"]) - pd.Timestamp("2000-01-03")).dt.days // 7
    return d.reset_index(drop=True)


def block_ci(values, blocks, reps: int = 2000, seed: int = 7) -> tuple[float, float, float]:
    """Hafta bloklu bootstrap: ortalama ve %95 aralık."""
    from bahis_tahmin.goals.validation import block_bootstrap_diff

    v = np.asarray(values, dtype=float)
    return block_bootstrap_diff(v, np.zeros_like(v), np.asarray(blocks), reps=reps, seed=seed)


def bets(d: pd.DataFrame, e: float, p_col: str = "p_o25", pick: tuple = ("o_o25", "o_u25"),
         pay: tuple | None = None) -> pd.DataFrame:
    """Maç başına en fazla bir seçim: EV'si en yüksek taraf, EV ≥ e ise. ``pick`` seçim oranları, ``pay`` ödeme oranları
    (varsayılan aynı). Dönen: seçilen satırlar, taraf, oran, kâr (1 birim)."""
    pay = pay or pick
    p = d[p_col].to_numpy(dtype=float)
    ev_o = p * d[pick[0]].to_numpy(dtype=float) - 1
    ev_u = (1 - p) * d[pick[1]].to_numpy(dtype=float) - 1
    over = ev_o >= ev_u
    ev = np.where(over, ev_o, ev_u)
    sel = np.isfinite(ev) & (ev >= e)
    odds = np.where(over, d[pay[0]].to_numpy(dtype=float), d[pay[1]].to_numpy(dtype=float))
    win = np.where(over, d["y"].to_numpy() == 1, d["y"].to_numpy() == 0)
    sel &= np.isfinite(odds) & (odds > 1)
    out = d.loc[sel, ["league", "date", "fold", "week"]].copy()
    out["taraf"] = np.where(over[sel], "Üst", "Alt")
    out["oran"] = odds[sel]
    out["ev"] = ev[sel]
    out["kar"] = np.where(win[sel], odds[sel] - 1, -1.0)
    return out


def roi(b: pd.DataFrame) -> dict:
    if b.empty:
        return {"n": 0, "roi": float("nan"), "alt": float("nan"), "ust": float("nan")}
    m, lo, hi = block_ci(b["kar"], b["week"])
    return {"n": int(len(b)), "roi": m, "alt": lo, "ust": hi, "ust_orani": float((b["taraf"] == "Üst").mean()),
            "ort_oran": float(b["oran"].mean())}


def select_threshold(dev: pd.DataFrame) -> tuple[float, list]:
    rows = [(e, roi(bets(dev, e))) for e in GRID]
    ok = [(e, r) for e, r in rows if r["n"] >= MIN_BETS]
    best = max(ok, key=lambda t: t[1]["roi"])[0] if ok else GRID[0]
    return best, rows


def info_test(dev: pd.DataFrame, test: pd.DataFrame) -> dict:
    """Geliştirme döneminde y ~ logit(p_piyasa) + logit(p_model); test döneminde birleşik − piyasa log-kayıp farkı."""
    from sklearn.linear_model import LogisticRegression

    def X(d):
        lg = lambda p: np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))  # noqa: E731
        return np.c_[lg(d["p_mkt"].to_numpy()), lg(d["p_o25"].to_numpy())]

    lr = LogisticRegression(C=1e6, max_iter=1000).fit(X(dev), dev["y"])
    pc = lr.predict_proba(X(test))[:, 1]
    d, lo, hi = block_ci(_ll(test["y"], pc) - _ll(test["y"], test["p_mkt"]), test["week"])
    return {"katsayi_piyasa": float(lr.coef_[0, 0]), "katsayi_model": float(lr.coef_[0, 1]),
            "kesisim": float(lr.intercept_[0]), "fark": d, "alt": lo, "ust": hi}


def loglosses(d: pd.DataFrame) -> dict:
    lm, lp = _ll(d["y"], d["p_o25"]), _ll(d["y"], d["p_mkt"])
    diff, lo, hi = block_ci(lm - lp, d["week"])
    return {"n": int(len(d)), "y_ort": float(d["y"].mean()), "model": float(lm.mean()), "piyasa": float(lp.mean()),
            "fark": diff, "alt": lo, "ust": hi, "p_model_ort": float(d["p_o25"].mean()),
            "p_piyasa_ort": float(d["p_mkt"].mean())}


def margins(d: pd.DataFrame) -> dict:
    """Piyasa marjı (modelden bağımsız): ortalama oran ve en yüksek oranla."""
    avg = 1 / d["o_o25"] + 1 / d["o_u25"] - 1
    ok = (d["omax_o25"] > 1) & (d["omax_u25"] > 1)
    mx = 1 / d.loc[ok, "omax_o25"] + 1 / d.loc[ok, "omax_u25"] - 1
    return {"n": int(len(d)), "ortalama_oran": float(avg.mean()), "en_yuksek_oran": float(mx.mean()),
            "en_yuksek_negatif_marj_payi": float((mx < 0).mean())}


def verdict(r: dict) -> str:
    if not r["n"]:
        return "bahis yok"
    if r["alt"] > 0:
        return "kazandırıyor (bu veride)"
    if r["ust"] < 0:
        return "kaybettiriyor"
    return "belirsiz"


def evaluate(pred: pd.DataFrame, with_test: bool) -> dict:
    d = sample(pred)
    dev = d[d["fold"].isin(DEV_YEARS)]
    test = d[d["fold"] >= TEST_FIRST]
    e, grid_dev = select_threshold(dev)
    out = {"esik": e, "gelistirme_izgara": grid_dev, "gelistirme_logkayip": loglosses(dev),
           "gelistirme_marj": margins(dev)}
    if with_test:
        b_avg = bets(test, e)
        out.update({
            "test_logkayip": loglosses(test), "test_marj": margins(test), "bilgi_testi": info_test(dev, test),
            "test_ortalama_oran": roi(b_avg),
            "test_ayni_secim_en_yuksek_odeme": roi(bets(test, e, pay=("omax_o25", "omax_u25"))),
            "test_en_yuksek_oranla_secim": roi(bets(test, e, pick=("omax_o25", "omax_u25"))),
            "test_izgara": [(g, roi(bets(test, g))) for g in GRID],
            "test_lig": {lg: roi(g) for lg, g in b_avg.groupby("league")},
            "test_sezon": {int(y): roi(g) for y, g in b_avg.groupby("fold")},
        })
        out["karar"] = verdict(out["test_ortalama_oran"])
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
    cache = out / "ou25_tahmin.pkl"
    if cache.exists():
        pred = pd.read_pickle(cache)
    else:
        st = DataStore(Path(os.environ.get("BAHIS_TAHMIN_HOME", app_home())))
        st.load()
        pred = walk_forward_ou(st.matches)
        pred.to_pickle(cache)
    res = evaluate(pred, "--test" in argv)
    pd.to_pickle(res, out / ("ou25_sonuc_test.pkl" if "--test" in argv else "ou25_sonuc_gel.pkl"))
    g = res["gelistirme_logkayip"]
    print(f"Geliştirme (2017/18–2020/21): {g['n']} maç; log-kayıp model {g['model']:.5f}, piyasa {g['piyasa']:.5f}, "
          f"fark {g['fark']:+.5f} [{g['alt']:+.5f}; {g['ust']:+.5f}]")
    for e, r in res["gelistirme_izgara"]:
        print(f"  e = {e:.2f}: {_fmt(r)}")
    print(f"Seçilen eşik e = {res['esik']:.2f}")
    if "--test" in argv:
        t = res["test_logkayip"]
        print(f"\nTest (2021/22–): {t['n']} maç; log-kayıp model {t['model']:.5f}, piyasa {t['piyasa']:.5f}, "
              f"fark {t['fark']:+.5f} [{t['alt']:+.5f}; {t['ust']:+.5f}]")
        it = res["bilgi_testi"]
        print(f"Bilgi testi: katsayı piyasa {it['katsayi_piyasa']:.3f}, model {it['katsayi_model']:.3f}; birleşik − "
              f"piyasa {it['fark']:+.5f} [{it['alt']:+.5f}; {it['ust']:+.5f}]")
        print(f"Ortalama oranla: {_fmt(res['test_ortalama_oran'])} → {res['karar']}")
        print(f"Aynı seçimler en yüksek oranla ödenseydi: {_fmt(res['test_ayni_secim_en_yuksek_odeme'])}")
        print(f"Seçim de en yüksek oranla: {_fmt(res['test_en_yuksek_oranla_secim'])}")
        m = res["test_marj"]
        print(f"Piyasa marjı: ortalama oran %{100 * m['ortalama_oran']:.2f}, en yüksek oran "
              f"%{100 * m['en_yuksek_oran']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

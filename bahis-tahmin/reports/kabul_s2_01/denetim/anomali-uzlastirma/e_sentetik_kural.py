"""SENTETİK gösterim: sonuçlar tam olarak bilinen modelden çekildiğinde (gerçek anomali YOK) de seçim kuralı
her lig-sezonda sabit sayıda bayrak üretir → bayrak sayısı kuralın ürünüdür, yaygınlık tahmini değildir.

Yalnızca bahis_tahmin.sequences.synthetic kullanılır (gerçek maç verisi okunmaz). Piyasa sütunu testlerdeki gibi
"S0 + küçük gürültü" (tests/test_seq_anomaly.py::_market_like_s0 ile aynı tarif) — fark tamamen gürültüdür.
Çıktı: sentetik_kural.csv
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT / "kod" / "bahis-tahmin"))
from bahis_tahmin.sequences import anomaly as A  # noqa: E402
from bahis_tahmin.sequences.synthetic import synthetic_frame  # noqa: E402


def market_like_s0(fr, seed=3, scale=0.01):
    rng = np.random.default_rng(seed)
    mkt = np.column_stack([fr.p0["GALIBIYET"], fr.p0["BERABERLIK"], fr.p0["MAGLUBIYET"]]).astype(float)
    mkt[:, 0] = np.clip(mkt[:, 0] + rng.normal(0, scale, len(mkt)), 0.01, 0.99)
    return mkt


def n_rule(n):
    return sum(1 for k in range(1, n + 1) if (2 * k - 1) * 200 < 2 * n)


rows = []
for n_teams in (10, 11, 14, 18, 20, 24):
    for seed in (0, 1, 2):
        fr, _, _ = synthetic_frame(seed=seed, n_leagues=2, n_seasons=3, n_teams=n_teams, start_year=2006)
        fr = dataclasses.replace(fr, mkt=market_like_s0(fr, seed=seed + 3))
        mask = np.asarray(fr.eligible, dtype=bool) & pd.notna(pd.Series(fr.period)).to_numpy()  # research.py:892
        recs_all = A.flag_anomalies(fr)  # maske yok: kuralın ürettiği tüm bayraklar
        recs_mask = A.flag_anomalies(fr, mask=mask)
        for cl in sorted(set(np.asarray(fr.cluster, dtype=object))):
            s_all = [r for r in recs_all if r["cluster"] == cl and A.TYPE_SURPRISE in r["flags"]]
            m_all = [r for r in recs_all if r["cluster"] == cl and A.TYPE_MARKET in r["flags"]]
            s_m = [r for r in recs_mask if r["cluster"] == cl and A.TYPE_SURPRISE in r["flags"]]
            n_cl = int((fr.tm["is_home"] & (pd.Series(fr.cluster) == cl).to_numpy()).sum())
            rows.append({"takim": n_teams, "tohum": seed, "kume": cl, "mac": n_cl, "kural_bayrak": n_rule(n_cl),
                         "S_bayrak_maskesiz": len(s_all), "M_bayrak_maskesiz": len(m_all),
                         "S_bayrak_maskeli": len(s_m),
                         "S_aciklanamayan_maskeli": sum(r["status_by_flag"][A.TYPE_SURPRISE] == A.TYPE_SURPRISE
                                                        for r in s_m)})
df = pd.DataFrame(rows)
df.to_csv(OUT / "sentetik_kural.csv", index=False)
agg = df.groupby(["takim", "mac"]).agg(kume=("kume", "size"), kural=("kural_bayrak", "first"),
                                       S_maskesiz_min=("S_bayrak_maskesiz", "min"),
                                       S_maskesiz_max=("S_bayrak_maskesiz", "max"),
                                       M_maskesiz_min=("M_bayrak_maskesiz", "min"),
                                       M_maskesiz_max=("M_bayrak_maskesiz", "max"),
                                       S_maskeli_toplam=("S_bayrak_maskeli", "sum"),
                                       S_aciklanamayan_toplam=("S_aciklanamayan_maskeli", "sum")).reset_index()
print(agg.to_string(index=False))
print("S maskesiz == kural her kümede:", bool((df.S_bayrak_maskesiz == df.kural_bayrak).all()))
print("M maskesiz == kural her kümede:", bool((df.M_bayrak_maskesiz == df.kural_bayrak).all()))

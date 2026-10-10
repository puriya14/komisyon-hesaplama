"""Yalnızca oran sütunları: Odd* > Max* (aynı seçim) satırlarının sezon yılına dağılımı ve marj (sonuç kullanılmaz)."""
import sys
import numpy as np
import pandas as pd
reb = pd.read_csv(sys.argv[1], parse_dates=["date"], low_memory=False)
sy = np.where(reb["date"].dt.month >= 7, reb["date"].dt.year, reb["date"].dt.year - 1)
reb["season_year"] = sy
# omax == o (doldurma) olmayan, yani ham Max'ın bulunduğu satırları ayırmak için omax != o veya her iki değer var
v = np.zeros(len(reb), dtype=bool)
for s in "hda":
    v |= (reb[f"o_{s}"] > reb[f"omax_{s}"] + 1e-9).to_numpy()
reb["odd_gt_max"] = v
g = reb.groupby("season_year").agg(n=("odd_gt_max", "size"), odd_gt_max=("odd_gt_max", "sum"))
g["pay"] = (g["odd_gt_max"] / g["n"]).round(5)
g.to_csv(sys.argv[2])
print(g.to_string())

"""1X2 oran kapsamının farklı tanımlarla payı (salt-okunur, yalnızca sayım)."""
import sys
import numpy as np
import pandas as pd
m = pd.read_csv(sys.argv[1], parse_dates=["date"], low_memory=False)
ok3 = np.isfinite(m[["o_h", "o_d", "o_a"]].to_numpy(dtype=float)).all(axis=1)
okh = m["o_h"].notna().to_numpy()
sy = np.where(m["date"].dt.month >= 7, m["date"].dt.year, m["date"].dt.year - 1)
print("tum satirlar, uc oran:", round(ok3.mean() * 100, 2), "% eksik", int((~ok3).sum()))
print("tum satirlar, o_h dolu:", round(okh.mean() * 100, 2))
for lo in (2002, 2005, 2006):
    s = sy >= lo
    print(f"sezon yili >= {lo}:", round(ok3[s].mean() * 100, 2))
s = (sy >= 2006) & (sy <= 2025)
print("2006-2025 (kesif+parametre+test):", round(ok3[s].mean() * 100, 2))
print("lig bazinda en dusuk 6:")
print(pd.Series(ok3).groupby(m["league"]).mean().sort_values().head(6).round(4).to_string())

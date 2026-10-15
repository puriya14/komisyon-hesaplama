"""KUPA-GOL-06: kupa maçlarında gol düzeyi izleme (salt okunur).

Kayıtlı kupa modelinin ileriye dönük (örneklem dışı) tahminlerinde gerçekleşen gol ile tahmin edilen golü doğrulama
grubu ve sezon bazında karşılaştırır. Ayrıca grup başına dinamik düzeyi yazar: R = (Σ w·gerçekleşen + τ) /
(Σ w·tahmin + τ). Toplam aynı gruptan, o haftadan önceki haftaların maçları üzerindendir; w = 0,5^(gün / 180), τ = 150
gol. Modeli değiştirmez. KUPA-GOL-06'da R'yi tahmine uygulayan aday (D1) ön kayıtlı kuralı geçemedi
(docs/KUPA_GOL_06.md); bu araç yalnızca kaymayı ileriye dönük izlemek içindir.

Kullanım (``BAHIS_TAHMIN_HOME`` uygulamanın veri klasörü; ağ isteği yok):

    python -I tools/research/kupa_gol_duzey.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HALF_LIFE = 180.0  # gün
TAU = 150.0  # gol (R'yi 1'e çeken önbilgi)


def level_series(oos: pd.DataFrame, half_life: float = HALF_LIFE, tau: float = TAU) -> np.ndarray:
    """Satır başına dinamik düzey R: aynı doğrulama grubundan ve satırın haftasından ÖNCEKİ haftaların maçları
    (``week`` < satırın haftası), w = 0,5^((hafta − maç günü) / yarı ömür). Gerekli sütunlar: vgroup, week, date, hg,
    ag, lam_c, nu_c."""
    from bahis_tahmin.kupa.model import EPOCH

    day = (pd.to_datetime(oos["date"]) - EPOCH).dt.days.to_numpy(dtype=float)
    tot = (oos["hg"] + oos["ag"]).to_numpy(dtype=float)
    mu = (oos["lam_c"] + oos["nu_c"]).to_numpy(dtype=float)
    week = oos["week"].to_numpy(dtype=float)
    grp = oos["vgroup"].to_numpy()
    out = np.ones(len(oos))
    for g in np.unique(grp):
        idx = np.nonzero(grp == g)[0]
        for wk in np.unique(week[idx]):
            past = idx[week[idx] < wk]
            if len(past):
                w = 0.5 ** ((wk - day[past]) / half_life)
                out[idx[week[idx] == wk]] = (np.sum(w * tot[past]) + tau) / (np.sum(w * mu[past]) + tau)
    return out


def season_table(oos: pd.DataFrame) -> pd.DataFrame:
    """Grup × sezon: maç, gerçekleşen ve tahmin edilen gol ortalaması, fark ve aşırı yayılım düzeltmeli z."""
    d = oos.assign(tot=oos["hg"] + oos["ag"], mu=oos["lam_c"] + oos["nu_c"])
    rows = []
    for g, gg in d.groupby("vgroup"):
        phi = float(np.mean((gg["tot"] - gg["mu"]) ** 2 / gg["mu"]))  # Pearson yayılım oranı (grup)
        for s, x in gg.groupby("season"):
            diff = float((x["tot"] - x["mu"]).mean())
            se = float(np.sqrt(phi * x["mu"].mean() / len(x)))
            rows.append({"grup": g, "sezon": s, "maç": len(x), "gol": float(x["tot"].mean()),
                         "tahmin": float(x["mu"].mean()), "fark": diff, "z": diff / se if se > 0 else float("nan")})
    return pd.DataFrame(rows)


def main() -> int:
    from bahis_tahmin.config import app_home
    from bahis_tahmin.kupa.motor import CupEngine

    eng = CupEngine.load(Path(os.environ.get("BAHIS_TAHMIN_HOME", app_home())) / "kupa_engine.joblib")
    if eng is None or eng.oos is None or eng.oos.empty:
        print("Kayıtlı kupa modeli yok ya da örneklem dışı ölçüm yok:", CupEngine.last_load_error or "-")
        return 1
    o = eng.oos
    pd.set_option("display.width", 200)
    print("=== Sezon bazında gerçekleşen / tahmin edilen gol (ileriye dönük) ===")
    print(season_table(o).round(3).to_string(index=False))
    r = level_series(o)
    print(f"\n=== Dinamik düzey R (yarı ömür {HALF_LIFE:.0f} gün, τ = {TAU:.0f} gol) ===")
    for g in sorted(set(o["vgroup"])):
        m = (o["vgroup"] == g).to_numpy()
        last = o.loc[m, "date"].max()
        print(f"{g}: son maç {str(last)[:10]}, R = {r[m][o.loc[m, 'date'].to_numpy() == last][0]:.3f}")
    print("\nR > 1: gerçekleşen gol tahminden fazla (model golü düşük tahmin ediyor); R < 1: tersi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Mevcut uygulama maç motorunun örneklem dışı 3.5 Üst olasılıkları (yalnızca kıyas için).

PredictionEngine.train içindeki walk-forward döngüsünün aynısı; yalnızca 2016+ sezonları için çalışır
(2019+ final test sezonlarında karıştırıcının önceki üç sezonun OOS tahminleriyle eğitilmesi için)."""
import sys, time, warnings
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from bahis_tahmin.models import engine as E
from bahis_tahmin.models.features import build_features
from bahis_tahmin.models.ml import MarketBlender, OutcomeModel
from bahis_tahmin.models.markets import batch_adjust, batch_markets, batch_score_matrices

m = pd.read_pickle(sys.argv[1])
t = time.time()
feat, _ = build_features(m)
print("features", round(time.time() - t), flush=True)
pk, pko = E.market_probs(feat, "power")
feat[["pk_h", "pk_d", "pk_a"]] = pk
feat["pk_o25"] = pko
years = E.season_year(feat["date"])
feat["fold"] = years
first = int(years.min())
usable = feat[(feat["date"] >= pd.Timestamp(first + 1, 7, 1)) & feat["dc_ph"].notna()]
parts = []
for Y in range(2016, 2027):
    tr = usable[usable["date"] < pd.Timestamp(Y, 7, 1)]
    te = usable[usable["fold"] == Y]
    if te.empty:
        continue
    mdl = OutcomeModel().fit(tr)
    pr = mdl.predict(te)
    part = te[E.KEEP_COLS + ["pk_h", "pk_d", "pk_a", "pk_o25", "fold"]].copy()
    part[["pm_h", "pm_d", "pm_a"]] = pr["res"]
    part["pm_o25"] = pr["o25"]
    part["pm_btts"] = pr["btts"]
    parts.append(part)
    print("fold", Y, round(time.time() - t), flush=True)
oos = pd.concat(parts)
pf = np.full((len(oos), 3), np.nan)
pfo = np.full(len(oos), np.nan)
for Y in sorted(oos["fold"].unique()):
    prev = oos[oos["fold"] < Y]
    cur = (oos["fold"] == Y).to_numpy()
    b = E.PredictionEngine._fit_blender(prev) if len(prev) >= 500 else MarketBlender()
    pf[cur] = b.blend_res(oos.loc[cur, ["pm_h", "pm_d", "pm_a"]].to_numpy(), oos.loc[cur, ["pk_h", "pk_d", "pk_a"]].to_numpy())
    pfo[cur] = b.blend_o25(oos.loc[cur, "pm_o25"].to_numpy(), oos.loc[cur, "pk_o25"].to_numpy())
lam = oos["dc_lh"].fillna(oos["dc_lh"].median()).to_numpy()
nu = oos["dc_la"].fillna(oos["dc_la"].median()).to_numpy()
mats = batch_adjust(batch_score_matrices(lam, nu, oos["dc_rho"].to_numpy()), pf, pfo, oos["pm_btts"].to_numpy())
oos[E.PMK_COLS] = batch_markets(mats)
out = oos[["league", "date", "home", "away", "fold", "pmk_O3.5", "pf_o25" if "pf_o25" in oos else "pm_o25"]].copy()
out.to_pickle(sys.argv[2])
print("done", len(out), round(time.time() - t), flush=True)

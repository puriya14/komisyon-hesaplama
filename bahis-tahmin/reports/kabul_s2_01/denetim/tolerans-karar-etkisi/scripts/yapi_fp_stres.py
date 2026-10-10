"""A ≤ BC ≤ min(B,C) özelliğinin KAYAN NOKTADA kesinliği: gerçek fonksiyonlarla (tilt_to_targets, GoalModel._q_cal)
uç durum stres testi. Sentetik/yapay girdiler; maç verisi kullanılmaz."""
import sys, json
import numpy as np
sys.path.insert(0, sys.argv[1])
from bahis_tahmin.goals.joint import tilt_to_targets, REGIONS, COND_KEYS
from bahis_tahmin.goals.model import GoalModel
rng = np.random.default_rng(7)
n = 200_000
res = {}
# 1) Rastgele bölge kütleleri (A ⊆ BC; A/BC oranı 0..1 dahil uçlar), rastgele hedefler
w = rng.dirichlet(np.ones(4), n)
w[: n // 10] *= np.array([1e-12, 1, 1, 1]); w /= w.sum(1, keepdims=True)  # çok küçük BC
reg = {r: w[:, i] for i, r in enumerate(REGIONS)}
ratio = rng.uniform(0, 1, n); ratio[: n // 20] = 1.0; ratio[n // 20: n // 10] = 1 - 1e-16
reg["A"] = reg["BC"] * ratio
for c in COND_KEYS:
    for r in REGIONS:
        reg[f"{c}:{r}"] = reg[r] * 0.5
t_b = rng.uniform(1e-4, 1 - 1e-4, n); t_c = rng.uniform(1e-4, 1 - 1e-4, n)
til = tilt_to_targets(reg, t_b, t_c)
res["tilt_BC>B"] = int((til["BC"] > til["B"]).sum()); res["tilt_BC>C"] = int((til["BC"] > til["C"]).sum())
res["tilt_A>BC (qcal YOK yolu, M9)"] = int((til["A"] > til["BC"]).sum())
res["tilt_A-BC_max (qcal YOK yolu)"] = float(np.max(til["A"] - til["BC"]))
# 2) M10 yolu: A = BC · q_kal ; q_kal = 1/(1+exp(-(a + b·logit q)))  (aşırı katsayılar dahil)
worst = 0; cnt = 0
for a, b in [(-0.17, 0.64), (40.0, 1.0), (800.0, 5.0), (-800.0, 5.0), (0.0, 50.0)]:
    m = GoalModel("M10_ipf_kosullu"); m.qcal = (a, b)
    with np.errstate(all="ignore"):
        q = m._q_cal(til["A"], til["BC"])
    A10 = til["BC"] * q
    cnt += int((A10 > til["BC"]).sum()); worst = max(worst, int((q > 1).sum()))
res["M10_A>BC"] = cnt; res["M10_qkal>1"] = worst
print(json.dumps(res, ensure_ascii=False, indent=1))
json.dump(res, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)

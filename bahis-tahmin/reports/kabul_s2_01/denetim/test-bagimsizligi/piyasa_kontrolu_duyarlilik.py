"""7b/5 (piyasa kontrolü) çıkarılırsa statüler değişir mi? YALNIZCA yayımlanmış kayıtlar (reports/dizi_sonuclar.json,
01b7e9f) üzerinde, 01b7e9f'teki statü fonksiyonları yeniden uygulanır; yeni hesap/uyum yok.

F1: research._candidate_status — 5_piyasa 'passed' True yapılır.
F3: models._f3_status — her dönemin yanlislama['5_piyasa']['gecti'] True yapılır.
F4: hazard._status — her dönemin falsification['5_piyasa']['gecti'] True yapılır.
Ayrıca F1 adayları için "karar veren ilk kural" yazılır.
Çıktı: piyasa_kontrolu_duyarlilik.csv
"""
import copy
import csv
import json
import sys
from pathlib import Path

KOD, JS, OUT = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
sys.path.insert(0, str(KOD))
from bahis_tahmin.sequences import hazard as H  # noqa: E402
from bahis_tahmin.sequences import models as M  # noqa: E402
from bahis_tahmin.sequences import research as RS  # noqa: E402

d = json.load(open(JS, encoding="utf-8"))
rows = []

# F1
for c in d["aileler"]["F1"]["adaylar"]:
    st0, why0 = RS._candidate_status(c)
    c2 = copy.deepcopy(c)
    for per in ("parametre", "test"):
        f = c2.get("yanlislama", {}).get(per)
        if f:
            f["checks"]["5_piyasa"]["passed"] = True
            f["passed_all"] = bool(f.get("passed_1_4"))
    st1, why1 = RS._candidate_status(c2)
    g = c["gosterge"]["fark"]
    rows.append({
        "aile": "F1", "kayit": c["hyp_id"], "yayimlanan_statu": c["statu"], "yeniden_uygulanan_statu": st0,
        "statu_7b5_cikarilinca": st1, "statu_degisir_mi": st0 != st1, "karar_veren_kural": why0,
        "p_holm_parametre": c["parametre"].get("p_holm"), "p_holm_test": c["test"].get("p_holm"),
        "dll_test": g["diff"], "dll_test_ust": g["ci_hi"],
        "7b_1_4_parametre": c["yanlislama"]["parametre"].get("passed_1_4"),
        "7b_1_4_test": c["yanlislama"]["test"].get("passed_1_4"),
        "7b5_parametre": c["yanlislama"]["parametre"]["checks"]["5_piyasa"]["passed"],
        "7b5_test": c["yanlislama"]["test"]["checks"]["5_piyasa"]["passed"],
        "7b5_test_lift": c["yanlislama"]["test"]["checks"]["5_piyasa"].get("lift"),
        "7b5_test_aralik": [c["yanlislama"]["test"]["checks"]["5_piyasa"].get("lift_lo"),
                            c["yanlislama"]["test"]["checks"]["5_piyasa"].get("lift_hi")],
    })

# F3
f3 = d["aileler"]["F3"]
for r in f3["holm"]:
    t, m = r["hedef"], r["model"]
    par = f3["hedefler"][t]["donemler"]["parametre"]["s0_fark"][m]
    te = f3["hedefler"][t]["donemler"]["test"]["s0_fark"][m]
    st0, why0 = M._f3_status(par, te, r["p_holm_parametre"], r["p_holm_test"])
    par2, te2 = copy.deepcopy(par), copy.deepcopy(te)
    for x in (par2, te2):
        if isinstance(x.get("yanlislama"), dict) and isinstance(x["yanlislama"].get("5_piyasa"), dict):
            x["yanlislama"]["5_piyasa"]["gecti"] = True
    st1, why1 = M._f3_status(par2, te2, r["p_holm_parametre"], r["p_holm_test"])
    rows.append({
        "aile": "F3", "kayit": f"{t}/{m}", "yayimlanan_statu": r["statu"], "yeniden_uygulanan_statu": st0,
        "statu_7b5_cikarilinca": st1 + (" (önceden görülmüş aile → en fazla EXPLORATORY)" if st1 ==
                                         "OUT_OF_SAMPLE_SUPPORTED" else ""),
        "statu_degisir_mi": st0 != st1, "karar_veren_kural": why0,
        "p_holm_parametre": r["p_holm_parametre"], "p_holm_test": r["p_holm_test"],
        "dll_test": r["dll_test"], "dll_test_ust": r["dll_test_ust"],
        "7b5_parametre": (par.get("yanlislama") or {}).get("5_piyasa", {}).get("gecti"),
        "7b5_test": (te.get("yanlislama") or {}).get("5_piyasa", {}).get("gecti"),
        "7b5_test_lift": (te.get("yanlislama") or {}).get("5_piyasa", {}).get("diff"),
        "7b5_test_aralik": [(te.get("yanlislama") or {}).get("5_piyasa", {}).get("ci_lo"),
                            (te.get("yanlislama") or {}).get("5_piyasa", {}).get("ci_hi")],
    })

# F4
for e, v in d["aileler"]["F4"]["events"].items():
    st0, why0 = H._status(v["oos"], v["p_param_holm"], v["p_test_holm"])
    oos2 = copy.deepcopy(v["oos"])
    for per in ("parametre", "test"):
        f = oos2.get(per, {}).get("falsification", {})
        if isinstance(f.get("5_piyasa"), dict):
            f["5_piyasa"]["gecti"] = True
    st1, why1 = H._status(oos2, v["p_param_holm"], v["p_test_holm"])
    te = v["oos"]["test"]
    rows.append({
        "aile": "F4", "kayit": e, "yayimlanan_statu": v["status"], "yeniden_uygulanan_statu": st0,
        "statu_7b5_cikarilinca": st1, "statu_degisir_mi": st0 != st1, "karar_veren_kural": why0,
        "p_holm_parametre": v["p_param_holm"], "p_holm_test": v["p_test_holm"],
        "dll_test": te.get("diff"), "dll_test_ust": te.get("ci_hi"),
        "7b5_parametre": v["oos"]["parametre"]["falsification"].get("5_piyasa", {}).get("gecti"),
        "7b5_test": te["falsification"].get("5_piyasa", {}).get("gecti"),
        "7b5_test_lift": te["falsification"].get("5_piyasa", {}).get("diff"),
        "7b5_test_aralik": [te["falsification"].get("5_piyasa", {}).get("ci_lo"),
                            te["falsification"].get("5_piyasa", {}).get("ci_hi")],
    })

keys = sorted({k for r in rows for k in r}, key=lambda k: list(rows[0]).index(k) if k in rows[0] else 99)
with open(OUT, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=keys)
    w.writeheader()
    for r in rows:
        w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v) for k, v in r.items()})
for r in rows:
    print(r["aile"], r["kayit"], "|", r["yayimlanan_statu"], "| yeniden:", r["yeniden_uygulanan_statu"],
          "| 7b5 yok:", r["statu_7b5_cikarilinca"], "| karar:", r["karar_veren_kural"][:90])

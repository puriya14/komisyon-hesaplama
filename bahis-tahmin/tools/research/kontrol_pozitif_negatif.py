"""Pozitif ve negatif kontrol: YALNIZCA sentetik veriyle tam Sorgu 1 akışı (WY + aday seçimi + parametre/test Holm +
gösterge ΔLL + 7b yanlışlama + piyasa kontrolü).

* Pozitif kontrol: üretici modelde bilinen, maç öncesinde erişilebilir bir ilişki — takımın bir önceki maçı "İY geride →
  MS galip" ise o takımın ikinci yarı gol yoğunluğu ``boost`` ile çarpılır (``synthetic_matches(comeback_boost=...)``).
  S0 = üreticinin bu etkiyi İÇERMEYEN kesin olasılıkları; "piyasa" oranları da aynı olasılıklardan (%5 marj, gürültü)
  üretilir, yani piyasa etkiyi bilmez. Gelecek bilgisi kullanılmaz (etki yalnızca önceki maça bağlıdır).
* Negatif kontrol: aynı akış, ``boost = 1`` (etki yok).

Parametreler ve başarı ölçütleri sonuçlardan ÖNCE ``plan`` dosyasına yazılır (zaman damgası + SHA-256). Sentetik
sonuçlar gerçek futbol avantajı olarak raporlanamaz.

Kullanım: python -I kontrol_pozitif_negatif.py <cikti_klasoru> [--isci 2]
"""
import argparse
import datetime as dt
import hashlib
import json
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402

from bahis_tahmin.goals.ledger import event_id  # noqa: E402
from bahis_tahmin.goals.markets import HTFT_KEYS  # noqa: E402
from bahis_tahmin.sequences import config as C  # noqa: E402
from bahis_tahmin.sequences import models as M  # noqa: E402
from bahis_tahmin.sequences import research as RS  # noqa: E402
from bahis_tahmin.sequences.frame import build_frame  # noqa: E402
from bahis_tahmin.sequences.synthetic import synthetic_matches  # noqa: E402
from bahis_tahmin.sequences.timeline import build_team_matches  # noqa: E402

PLAN = {
    "surum": "kontrol-plani-v1",
    "veri": "YALNIZCA sentetik (bahis_tahmin.sequences.synthetic.synthetic_matches)",
    "orneklem": {"n_leagues": 4, "n_teams": 20, "n_seasons": 27, "start_year": 2000},
    "tohumlar": [101, 102, 103],
    "kosullar": {"pozitif": {"comeback_boost": 2.0}, "negatif": {"comeback_boost": 1.0},
                 "duyarlilik_kucuk_etki": {"comeback_boost": 1.3}},
    "S0": "üreticinin etkiyi içermeyen kesin İY/MS olasılıkları",
    "piyasa": {"marj": 0.05, "lognormal_gurultu_sd": 0.05, "eksik_oran": 0.0,
               "not": "oranlar etkiyi içermeyen olasılıklardan; piyasa etkiyi bilmez"},
    "R_inner": 200, "bootstrap": 1000, "destek_esikleri": {"min_n": C.MIN_N, "min_e": C.MIN_E},
    "basari_olcutleri": {
        "pozitif": ("Her tohumda, atomları SON_MAC_IY_GERIDE_MS_GALIP veya SON3_IY_GERIDE_MS_GALIP_VAR içeren ve "
                    "hedefi GALIBIYET ya da IY_GERIDE_MS_GALIP olan en az bir hipotez (a) WY ile anlamlı (p_adj < 0,05 "
                    "ve MC %99 üst sınır < 0,05) ve (b) OUT_OF_SAMPLE_SUPPORTED olmalı."),
        "negatif": "Hiçbir tohumda OUT_OF_SAMPLE_SUPPORTED olmamalı; WY anlamlı hipotez sayısı raporlanır.",
        "duyarlilik_kucuk_etki": "Başarı ölçütü yok; yalnızca güç/MDE için betimsel (yakalanma oranı raporlanır).",
    },
    "maliyet_olcumu": "Plan öncesi tek ölçüm (tohum 9001, etkisiz, sonuçlara bakılmadan): çerçeve 22,6 sn, "
                      "referans süreç R=4 için 0,6 sn (2 işçi) → R=200 ≈ 30 sn/çalıştırma.",
    "durdurma": "Tohum listesi ve R sabittir; sonuca göre tekrar veya ek tohum yok.",
}
PLANTED_ATOMS = {"SON_MAC_IY_GERIDE_MS_GALIP", "SON3_IY_GERIDE_MS_GALIP_VAR"}
PLANTED_TARGETS = {"GALIBIYET", "IY_GERIDE_MS_GALIP"}


def _plan_sha() -> str:
    return hashlib.sha256(json.dumps(PLAN, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def synthetic_frame_with_market(seed: int, boost: float):
    o = PLAN["orneklem"]
    m, probs = synthetic_matches(n_leagues=o["n_leagues"], n_seasons=o["n_seasons"], n_teams=o["n_teams"],
                                 start_year=o["start_year"], seed=seed, comeback_boost=boost)
    eid = [event_id(lg, d, h, a) for lg, d, h, a in zip(m["league"], m["date"], m["home"], m["away"])]
    P = probs.set_index("event_id").reindex(eid)[list(HTFT_KEYS)].to_numpy()
    ft = np.array([k.split("_")[2] for k in HTFT_KEYS])
    p3 = np.column_stack([P[:, ft == c].sum(axis=1) for c in ("1", "X", "2")])
    rng = np.random.default_rng(seed + 7)
    mk = PLAN["piyasa"]
    odds = 1.0 / (p3 * (1 + mk["marj"])) * np.exp(rng.normal(0.0, mk["lognormal_gurultu_sd"], p3.shape))
    m = m.copy()
    m["o_h"], m["o_d"], m["o_a"] = odds[:, 0], odds[:, 1], odds[:, 2]
    return build_frame(build_team_matches(m), probs)


def run_one(seed: int, boost: float, workers: int) -> dict:
    t = time.time()
    fr = synthetic_frame_with_market(seed, boost)
    masks = RS.period_masks(fr)
    s0p = {tg: M.s0p_predict(fr, tg)[0] for tg in C.TARGETS_Q1}
    f1 = RS.run_f1(fr, masks, R=PLAN["R_inner"], seed=seed, workers=workers, s0p=s0p, n_boot=PLAN["bootstrap"])
    h = f1.get("hipotezler")
    out = {"tohum": seed, "boost": boost, "durum": f1.get("durum"), "sure_sn": round(time.time() - t, 1),
           "kalibrasyon_kapisi": f1["kalibrasyon_kapisi"]["gecti"]}
    if h is None or len(h) == 0:
        return out
    u = h[h["tekil"]]
    sig = u["supported"].astype(bool) & (u["p_adj"] < C.ALPHA) & (u["ci_hi"] < C.ALPHA)
    planted = u[[bool(set(a) & PLANTED_ATOMS) and t_ in PLANTED_TARGETS for a, t_ in zip(u["atoms"], u["target"])]]
    p_sig = planted["supported"].astype(bool) & (planted["p_adj"] < C.ALPHA) & (planted["ci_hi"] < C.ALPHA)
    out.update({
        "wy_anlamli": int(sig.sum()), "wy_anlamli_hipotezler": u.loc[sig, "hyp_id"].tolist(),
        "statu_sayilari": f1["statu_sayilari"],
        "ekili_aile_wy_anlamli": planted.loc[p_sig, "hyp_id"].tolist(),
        "ekili_aile_oos_destekli": planted.loc[planted["statu"] == "OUT_OF_SAMPLE_SUPPORTED", "hyp_id"].tolist(),
        "oos_destekli_tum": u.loc[u["statu"] == "OUT_OF_SAMPLE_SUPPORTED", "hyp_id"].tolist(),
        "adaylar": [{"hyp_id": c["hyp_id"], "statu": c["statu"], "gerekce": c["gerekce"],
                     "kesif_lift": c["kesif"]["lift"], "test_lift": (c.get("test") or {}).get("lift"),
                     "gosterge_dll": ((c.get("gosterge") or {}).get("fark") or {}).get("diff"),
                     "gosterge_dll_ust": ((c.get("gosterge") or {}).get("fark") or {}).get("ci_hi")}
                    for c in f1["adaylar"]],
    })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--isci", type=int, default=2)
    ap.add_argument("--sadece-plan", action="store_true", help="Yalnızca plan dosyasını yaz (sonuçlardan önce)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    plan_doc = {"plan": PLAN, "plan_sha256": _plan_sha(),
                "yazilma_zamani_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    plan_path = out / "kontroller_plan.json"
    if plan_path.exists():
        old = json.loads(plan_path.read_text(encoding="utf-8"))
        if old.get("plan_sha256") != plan_doc["plan_sha256"]:
            print("Plan değişmiş: mevcut plan dosyası korunuyor, çalıştırma durduruldu.", file=sys.stderr)
            return 2
        plan_doc = old
    else:
        plan_path.write_text(json.dumps(plan_doc, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.sadece_plan:
        print(json.dumps(plan_doc, ensure_ascii=False))
        return 0
    results = []
    for cond, cfg in PLAN["kosullar"].items():
        for seed in PLAN["tohumlar"]:
            r = run_one(seed, cfg["comeback_boost"], a.isci)
            r["kosul"] = cond
            results.append(r)
            print(json.dumps({k: r.get(k) for k in ("kosul", "tohum", "wy_anlamli", "ekili_aile_wy_anlamli",
                                                     "ekili_aile_oos_destekli", "oos_destekli_tum", "sure_sn")},
                             ensure_ascii=False), flush=True)
    pos = [r for r in results if r["kosul"] == "pozitif"]
    neg = [r for r in results if r["kosul"] == "negatif"]
    small = [r for r in results if r["kosul"] == "duyarlilik_kucuk_etki"]
    verdict = {
        "pozitif_wy_yakalama": f"{sum(bool(r.get('ekili_aile_wy_anlamli')) for r in pos)}/{len(pos)}",
        "pozitif_oos_destek": f"{sum(bool(r.get('ekili_aile_oos_destekli')) for r in pos)}/{len(pos)}",
        "negatif_oos_destekli_tohum": f"{sum(bool(r.get('oos_destekli_tum')) for r in neg)}/{len(neg)}",
        "negatif_wy_anlamli_toplam": sum(r.get("wy_anlamli", 0) for r in neg),
        "pozitif_olcut_gecti": all(r.get("ekili_aile_wy_anlamli") and r.get("ekili_aile_oos_destekli") for r in pos),
        "negatif_olcut_gecti": all(not r.get("oos_destekli_tum") for r in neg),
        "kucuk_etki_wy_yakalama": f"{sum(bool(r.get('ekili_aile_wy_anlamli')) for r in small)}/{len(small)}",
        "kucuk_etki_oos_destek": f"{sum(bool(r.get('ekili_aile_oos_destekli')) for r in small)}/{len(small)}",
        "not": "Sentetik kontrol; gerçek futbol avantajı değildir.",
    }
    doc = {"plan_sha256": plan_doc["plan_sha256"], "plan_yazilma_zamani_utc": plan_doc["yazilma_zamani_utc"],
           "bitis_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "karar": verdict,
           "sonuclar": results}
    (out / "kontroller_sonuc.json").write_text(json.dumps(RS.jsonable(doc), ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

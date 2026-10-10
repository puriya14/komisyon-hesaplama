"""Ön-kayıtlı dizi araştırmasını açık dosya yollarıyla çalıştırır (tekrarlanabilir rapor üretimi).

Kullanım:
  python -I run_dizi.py <matches.pkl> <s0.pkl> <cikti_klasoru> [--isci 3] [--R 1000] [--plasebo-tohum 20]
                        [--plasebo-R 200] [--depo]

--depo: aile sonuçlarını depodaki reports/experiments.jsonl'e ekler ve reports/dizi_sonuclar.json,
reports/dizi_f1_hipotezler.csv dosyalarını yazar (tekil maç anomali kayıtları depoya yazılmaz).
Uygulama veri klasörüne veya üretim kayıtlarına dokunmaz.
"""
import argparse
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
import pandas as pd  # noqa: E402

from bahis_tahmin.sequences import config as C  # noqa: E402
from bahis_tahmin.sequences.research import run_research  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("matches")
    ap.add_argument("s0")
    ap.add_argument("out")
    ap.add_argument("--isci", type=int, default=1)
    ap.add_argument("--R", type=int, default=C.N_NULL)
    ap.add_argument("--plasebo-tohum", type=int, default=C.N_PLACEBO_SEEDS)
    ap.add_argument("--plasebo-R", type=int, default=C.N_NULL_PLACEBO)
    ap.add_argument("--depo", action="store_true")
    a = ap.parse_args()
    t = time.time()
    log = lambda s: print(f"[{time.time() - t:7.0f} sn] {s}", flush=True)  # noqa: E731
    m = pd.read_pickle(a.matches)
    s0 = pd.read_pickle(a.s0)
    out = Path(a.out)
    res = run_research(m, out, s0=s0, R=a.R, placebo_seeds=a.plasebo_tohum, R_placebo=a.plasebo_R, workers=a.isci,
                       progress=log, record=True,
                       experiments_path=(ROOT / "reports" / "experiments.jsonl") if a.depo else out / "deneyler.jsonl",
                       reports_dir=(ROOT / "reports") if a.depo else None, data_label=Path(a.matches).name)
    log("bitti")
    for k, v in res["aileler"].items():
        print(f"{k}: {v.get('ozet')}")
    print("temiz test:", res["manifest"]["temiz_test"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

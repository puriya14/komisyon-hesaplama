"""YALNIZCA SENTETİK: dizi araştırması (run_research) yarıda kesilirse dosyalara ne olur?
1) Tam bir sentetik çalıştırma (küçük R) → çıktı dosyaları.
2) İkinci çalıştırma F1 kaydı yazıldıktan sonra KeyboardInterrupt ile kesilir.
Sonra: deneyler.jsonl satır sayıları, son_sonuclar.json'un hangi çalıştırmaya ait olduğu.

Kullanım: python -I -B arastirma_kesinti_sentetik.py <kod_kok> <cikti_klasoru>
"""

import json
import shutil
import sys
import time
from pathlib import Path

kod, out = sys.argv[1], Path(sys.argv[2])
sys.path.insert(0, kod)
sys.path.insert(0, str(Path(kod) / "tests"))

from bahis_tahmin.sequences import research as RS  # noqa: E402
from bahis_tahmin.sequences.synthetic import synthetic_matches  # noqa: E402
from test_seq_research import _s0_table  # noqa: E402  (testin sentetik S0 yardımcı işlevi)

base = out / "arastirma_kesinti"
shutil.rmtree(base, ignore_errors=True)
base.mkdir(parents=True)
od, exp = base / "dizi_arastirma", base / "dizi_arastirma" / "deneyler.jsonl"
m, probs = synthetic_matches(n_leagues=2, n_seasons=27, n_teams=16, seed=11)
s0 = _s0_table(m, probs)
R = {}
t = time.time()
r1 = RS.run_research(m, od, s0=s0, R=12, placebo_seeds=2, R_placebo=6, workers=1, record=True,
                     experiments_path=exp, data_label="SENTETIK-TEST")
R["calistirma1"] = {"sure_sn": round(time.time() - t, 1), "zaman_utc": r1["manifest"]["zaman_utc"],
                    "deneyler_satir": len(exp.read_text(encoding="utf-8").splitlines()),
                    "dosyalar": sorted(p.name for p in od.iterdir())}
time.sleep(1.1)
state = {"f1": False}


def prog(msg):
    if state["f1"]:
        raise KeyboardInterrupt("yapay kesinti (Ctrl+C benzetimi)")
    if str(msg).startswith("F1:"):
        state["f1"] = True


mtimes = {p.name: p.stat().st_mtime for p in od.iterdir()}
try:
    RS.run_research(m, od, s0=s0, R=12, placebo_seeds=2, R_placebo=6, workers=1, record=True,
                    experiments_path=exp, data_label="SENTETIK-TEST", progress=prog)
    R["calistirma2"] = "kesilmedi"
except KeyboardInterrupt:
    lines = [json.loads(x) for x in exp.read_text(encoding="utf-8").splitlines()]
    son = json.loads((od / "son_sonuclar.json").read_text(encoding="utf-8"))
    R["calistirma2_kesildi"] = {
        "deneyler_satir": len(lines), "son_eklenen_asamalar": [x.get("asama") for x in lines[R["calistirma1"]["deneyler_satir"]:]],
        "degisen_dosyalar": sorted(p.name for p in od.iterdir() if p.stat().st_mtime != mtimes.get(p.name)),
        "son_sonuclar_manifest_zamani": son.get("manifest", {}).get("zaman_utc"),
        "son_sonuclar_calistirma1_mi": son.get("manifest", {}).get("zaman_utc") == R["calistirma1"]["zaman_utc"],
    }
(out / "arastirma_kesinti_sentetik.json").write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(R, ensure_ascii=False, indent=1))

"""Alt ajan ve ana oturum araç çağrılarında gerçek veri dosyalarına/gerçek veri hesaplarına temasları listeler.

Yalnızca düzleştirilmiş dökümleri okur. Çıktı: gercek_veri_temaslari.csv (ts, etiket, arac, description, eşleşen anahtarlar,
komut başı) — kanıt satırları. Sınıflandırma ayrı (elle, bulgu tablosunda).
"""
import csv
import glob
import json
import os
import re

O = os.path.dirname(os.path.abspath(__file__))
KEYS = [r"tm_v2\.pkl", r"tm_v1\.pkl", r"s0_v1\.pkl", r"s0_cal_v1\.pkl", r"fr_real\w*\.pkl", r"home30", r"real_f3\w*",
        r"abc_check\w*", r"run_f3\w*", r"calibration_gate", r"evaluate\(", r"falsification\(", r"matches\.pkl",
        r"goal_feat\w*\.pkl", r"run_dizi", r"build_s0", r"compare_models\(", r"run_f[1-7]\(", r"run_hazard_family",
        r"abc_added_value|abc_check|run_abc", r"economic\w*\(", r"scan_anomal\w*|run_anomal\w*", r"placebo\w*\(",
        r"search_q1|run_search|q1_search|null_q1|westfall|wy_", r"s0p_predict|p0_market", r"\.csv\.gz|mirror",
        r"seq/\w+\.pkl", r"/seq/"]
rx = [(k, re.compile(k)) for k in KEYS]
rows = []
for f in sorted(glob.glob(os.path.join(O, "olaylar*.jsonl"))):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l)
        if r["tur"] != "tool_use":
            continue
        txt = r["metin"] or ""
        hits = [k for k, x in rx if x.search(txt)]
        if not hits:
            continue
        try:
            inp = json.loads(txt)
        except ValueError:
            inp = {}
        desc = inp.get("description", "") if isinstance(inp, dict) else ""
        cmd = (inp.get("command") or inp.get("file_path") or "") if isinstance(inp, dict) else ""
        rows.append({"ts": r["ts"], "etiket": r["etiket"], "arac": r["arac"], "id": r["id"], "description": desc,
                     "anahtarlar": ";".join(hits), "komut_bas": cmd[:400].replace("\n", " | ")})
rows.sort(key=lambda r: r["ts"])
with open(os.path.join(O, "gercek_veri_temaslari.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(len(rows))

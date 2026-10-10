"""Düzleştirilmiş olay dosyalarında desen arar (yalnızca okuma).

Kullanım: python ara.py <desen_regex> [--tur tool_use|tool_result|text] [--ajan etiket_alt_dizgi] [--bas ts] [--bit ts]
          [--uzun N] [--tam]
"""
import argparse
import glob
import json
import os
import re

O = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("desen")
ap.add_argument("--tur")
ap.add_argument("--ajan")
ap.add_argument("--bas", default="")
ap.add_argument("--bit", default="9")
ap.add_argument("--uzun", type=int, default=300)
ap.add_argument("--tam", action="store_true")
ap.add_argument("--id")
a = ap.parse_args()
rx = re.compile(a.desen, re.S)
rows = []
for f in sorted(glob.glob(os.path.join(O, "olaylar*.jsonl"))):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l)
        rows.append(r)
rows.sort(key=lambda r: (r["ts"] or "", r["satir_no"]))
for r in rows:
    if a.tur and r["tur"] != a.tur:
        continue
    if a.ajan and a.ajan not in (r["etiket"] or ""):
        continue
    if not (a.bas <= (r["ts"] or "") <= a.bit):
        continue
    if a.id and r.get("id") != a.id:
        continue
    m = rx.search(r["metin"] or "")
    if not m:
        continue
    txt = r["metin"]
    if a.tam:
        snip = txt
    else:
        s = max(0, m.start() - a.uzun // 3)
        snip = txt[s:s + a.uzun]
    print(f"[{r['ts']}] {r['etiket']} {r['tur']} {r.get('arac') or ''} id={r.get('id')} satir={r['satir_no']}")
    print("   ", snip.replace("\n", "\n    "))

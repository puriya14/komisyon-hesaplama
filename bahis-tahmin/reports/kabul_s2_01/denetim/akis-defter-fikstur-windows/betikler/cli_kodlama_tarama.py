"""cli.py içindeki print() metin parçalarında Windows ANSI kod sayfalarıyla (cp1252, cp1254) kodlanamayan
karakterleri statik olarak bulur (yönlendirilmiş stdout'ta UnicodeEncodeError riski).

Kullanım: python -I cli_kodlama_tarama.py <cli.py> <cikti_csv>
"""

import ast
import csv
import sys
from pathlib import Path

src = Path(sys.argv[1]).read_text(encoding="utf-8")
tree = ast.parse(src)
rows = []
for node in ast.walk(tree):
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
        to_stderr = any(k.arg == "file" for k in node.keywords)
        texts = [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        for enc in ("cp1252", "cp1254"):
            bad = set()
            for t in texts:
                for ch in t:
                    try:
                        ch.encode(enc)
                    except UnicodeEncodeError:
                        bad.add(ch)
            if bad:
                rows.append({"satir": node.lineno, "kodlama": enc, "akim": "stderr" if to_stderr else "stdout",
                             "kodlanamayan": "".join(sorted(bad)),
                             "ornek": (texts[0][:60] if texts else "")})
with open(sys.argv[2], "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["satir", "kodlama", "akim", "kodlanamayan", "ornek"])
    w.writeheader()
    w.writerows(rows)
for r in rows:
    print(r)

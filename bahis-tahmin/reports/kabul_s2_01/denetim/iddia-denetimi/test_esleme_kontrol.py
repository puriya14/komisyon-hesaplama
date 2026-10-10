"""SONUCLARI belgesindeki zorunlu test eşlemesinde adı geçen test fonksiyonlarının baseline'da var olup olmadığı."""
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
doc = (root / "docs/DIZI_ARASTIRMA_SONUCLARI.md").read_text(encoding="utf-8")
refs = sorted(set(re.findall(r"`(test_[a-z_]+\.py)::([A-Za-z0-9_]+)`", doc)))
missing = []
for f, fn in refs:
    src = (root / "tests" / f).read_text(encoding="utf-8")
    if not re.search(rf"^def {fn}\(", src, re.M):
        missing.append(f"{f}::{fn}")
print("referans", len(refs), "eksik", len(missing), missing)

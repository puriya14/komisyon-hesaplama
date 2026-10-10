"""Kod/sözleşme/karar özetlerini iki commit için hesaplar (salt-okunur, gerçek veri kullanmaz)."""
import hashlib, sys, importlib, json
from pathlib import Path
res = {}
for label, root in (("398b60b", sys.argv[1]), ("01b7e9f", sys.argv[2])):
    root = Path(root)
    pkg = root / "bahis_tahmin" / "sequences"
    h = hashlib.sha256()
    for f in sorted(pkg.glob("*.py")):
        h.update(f.name.encode()); h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    c = (root / "docs" / "DIZI_ARASTIRMA_SOZLESMESI.md").read_bytes()
    crlf = c.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    res[label] = {"kod_sha256(sequences/*.py)": h.hexdigest(),
                  "sozlesme_sha256_LF": hashlib.sha256(c).hexdigest(),
                  "sozlesme_sha256_CRLF": hashlib.sha256(crlf).hexdigest(),
                  "sozlesme_CRLF_iceriyor": b"\r\n" in c}
# parametre özeti ve karar özeti: baseline kodundan
sys.path.insert(0, sys.argv[2])
from bahis_tahmin.sequences import config as C, research as R
res["01b7e9f"]["config_hash"] = C.config_hash()
res["01b7e9f"]["run_decisions_sha256"] = R.run_decisions_sha256()
res["01b7e9f"]["TEST_OPENED.kod_sha256"] = R.TEST_OPENED["kod_sha256"]
print(json.dumps(res, indent=1, ensure_ascii=False))

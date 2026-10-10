"""research.code_sha256() algoritmasını (01b7e9f research.py:189-195) git nesnelerinden yeniden üretir.

Algoritma: sequences/*.py dosyaları ada göre sıralı; her dosya için sha256.update(ad) ve update(içerik CRLF→LF).
Depoya dokunmaz; yalnızca `git show <commit>:<yol>` okur.
"""
import hashlib
import subprocess
import sys

REPO = "/home/user/komisyon-hesaplama/bahis-tahmin"
PFX = "bahis-tahmin/bahis_tahmin/sequences/"


def files(commit):
    out = subprocess.run(["git", "-C", REPO, "ls-tree", "--name-only", commit, "bahis_tahmin/sequences/"],
                         capture_output=True, text=True, check=True).stdout.split()
    return sorted(f.rsplit("/", 1)[1] for f in out if f.endswith(".py"))


def blob(commit, name):
    return subprocess.run(["git", "-C", REPO, "show", f"{commit}:{PFX}{name}"], capture_output=True,
                          check=True).stdout


def code_sha(commit):
    h = hashlib.sha256()
    for f in files(commit):
        h.update(f.encode())
        h.update(blob(commit, f).replace(b"\r\n", b"\n"))
    return h.hexdigest()


for c in sys.argv[1:]:
    print(c, code_sha(c), len(files(c)), "dosya")

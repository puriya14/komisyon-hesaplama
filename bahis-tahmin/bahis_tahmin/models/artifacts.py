"""Model dosyalarının manifestli kaydı ve doğrulamalı yüklenmesi.

joblib/pickle dosyaları yüklenirken kod çalıştırabilir; bu yüzden bir dosya ancak:
  * yanında manifest (JSON) varsa,
  * manifestteki SHA-256 özeti dosyayla birebir eşleşiyorsa,
  * tür ve sürüm beklenenle aynıysa,
  * scikit-learn / numpy ana-ara sürümleri uyumluysa
yüklenir. Aksi halde yükleme reddedilir ve nedeni bildirilir (sessizce devam edilmez).
Not: Bu kontrol, uygulamanın kendi ürettiği dosyaların bozulmasını/karışmasını yakalar; bilgisayara
erişimi olan birinin hem dosyayı hem manifesti değiştirmesine karşı tam koruma sağlamaz.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
from pathlib import Path

import joblib


def _versions() -> dict:
    import numpy
    import pandas
    import scipy
    import sklearn

    from .. import __version__

    return {"app": __version__, "python": platform.python_version(), "numpy": numpy.__version__,
            "pandas": pandas.__version__, "scipy": scipy.__version__, "sklearn": sklearn.__version__}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_path(path: Path) -> Path:
    return Path(path).with_suffix(".manifest.json")


def save_artifact(obj, path: Path, kind: str, version: int, meta: dict | None = None) -> dict:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    joblib.dump(obj, tmp, compress=3)
    tmp.replace(path)
    man = {
        "kind": kind,
        "version": version,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sha256": _sha256(path),
        "dependencies": _versions(),
        **(meta or {}),
    }
    manifest_path(path).write_text(json.dumps(man, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return man


def _minor(v: str) -> str:
    return ".".join(str(v).split(".")[:2])


def load_artifact(path: Path, kind: str, version: int):
    """(nesne, manifest, sorun) döndürür; sorun varsa nesne None'dır."""
    path = Path(path)
    if not path.exists():
        return None, None, "Model dosyası yok."
    mp = manifest_path(path)
    if not mp.exists():
        return None, None, "Model manifesti yok; dosya doğrulanamadığı için yüklenmedi (yeniden eğitin)."
    try:
        man = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None, "Model manifesti okunamadı."
    if man.get("kind") != kind or man.get("version") != version:
        return None, man, f"Model türü/sürümü uyumsuz ({man.get('kind')} v{man.get('version')}); yeniden eğitin."
    if _sha256(path) != man.get("sha256"):
        return None, man, "Model dosyasının özeti manifestle eşleşmiyor (bozulmuş veya değiştirilmiş); yüklenmedi."
    cur = _versions()
    dep = man.get("dependencies", {})
    for lib in ("sklearn", "numpy"):
        if _minor(dep.get(lib, "")) != _minor(cur[lib]):
            return None, man, f"{lib} sürümü değişmiş ({dep.get(lib)} → {cur[lib]}); model yeniden eğitilmeli."
    try:
        obj = joblib.load(path)
    except Exception as e:  # bozuk dosya
        return None, man, f"Model yüklenemedi: {e}"
    return obj, man, None

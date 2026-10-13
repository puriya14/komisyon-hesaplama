# -*- mode: python ; coding: utf-8 -*-
# Windows için paketleme:  pyinstaller --noconfirm --clean BahisTahmin.spec
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hidden = collect_submodules("bahis_tahmin") + [
    "matplotlib.backends.backend_qtagg",
    "sklearn.ensemble._hist_gradient_boosting",
    "sklearn.utils._typedefs",
    "sklearn.neighbors._partition_nodes",
    "scipy.special._cdflib",
]

try:  # Windows'ta zaman dilimi veritabanı (Europe/Istanbul) için
    tz_datas = collect_data_files("tzdata")
except Exception:
    tz_datas = []

a = Analysis(
    ["run_app.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets/icon.ico", "assets"), ("assets/icon.png", "assets"),
           # web arayüzü (BahisTahmin.exe web) sayfa şablonları ve stilleri
           ("bahis_tahmin/web/templates", "bahis_tahmin/web/templates"),
           ("bahis_tahmin/web/static", "bahis_tahmin/web/static")] + tz_datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "IPython", "pytest", "notebook", "jupyter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BahisTahmin",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
    version="version_info.txt",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="BahisTahmin")

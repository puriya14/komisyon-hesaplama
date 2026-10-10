"""PyInstaller giriş noktası ve kaynak koddan çalıştırma: python run_app.py"""

import multiprocessing
import os
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    os.environ.setdefault("QT_API", "pyside6")
    from bahis_tahmin.cli import main

    sys.exit(main())

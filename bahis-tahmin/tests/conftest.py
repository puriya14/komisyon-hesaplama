import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).parent / "fixtures"


def pytest_addoption(parser):
    parser.addoption("--network", action="store_true", help="gerçek veri kaynaklarına bağlanan testleri çalıştır")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--network") or os.environ.get("RUN_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="ağ testleri için --network kullanın")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


def pytest_sessionfinish(session, exitstatus):
    """Testlerde açılan Qt pencerelerini, uygulama nesnesi hâlâ ayaktayken belirli bir sırayla siler.

    Pencereler testlerde kapatılır ama silinmez; yorumlayıcı kapanırken sarmalayıcıların silinme sırası belirsiz
    olduğundan aynı Qt nesnesi iki kez silinebiliyor ("QObject: shared QObject was deleted directly" ve ardından
    malloc hatasıyla çökme). Test sonuçlarını değiştirmez; yalnızca kapanışı belirlenimci yapar."""
    qw = sys.modules.get("PySide6.QtWidgets")
    app = qw.QApplication.instance() if qw is not None else None
    if app is None:
        return
    import gc

    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent, QThread

    for t in [o for o in gc.get_objects() if isinstance(o, QThread)]:
        if shiboken6.isValid(t) and t.isRunning():
            t.wait(10_000)
    for w in qw.QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("BAHIS_TAHMIN_HOME", str(home))
    return home


@pytest.fixture(scope="session")
def synthetic():
    from bahis_tahmin.selftest import synthetic_matches

    return synthetic_matches(n_seasons=5, n_teams=14, seed=1)


@pytest.fixture(scope="session")
def trained_engine(synthetic):
    from bahis_tahmin.models.engine import PredictionEngine

    eng = PredictionEngine()
    eng.train(synthetic)
    return eng


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()

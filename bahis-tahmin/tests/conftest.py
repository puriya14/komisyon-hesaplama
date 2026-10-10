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

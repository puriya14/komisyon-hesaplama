import datetime as dt
import io

import pandas as pd
import pytest
from conftest import fixture_bytes

from bahis_tahmin.data.sources import FD_BASE, MIRROR_URL, OPENFOOTBALL_BASE, DownloadError
from bahis_tahmin.data.source_registry import SOURCES, allowed_sources
from bahis_tahmin.data.store import DataStore

ALL = {"football-data", "github-mirror", "openfootball"}


class FakeDownloader:
    """İnternete çıkmadan Downloader davranışını taklit eder."""

    def __init__(self, files: dict[str, bytes], fd_down: bool = False):
        self.files = files
        self.fd_down = fd_down
        self.stats = {"network": 0, "cache": 0, "failed": 0}
        self.requested: list[str] = []

    def host_down(self, url):
        return self.fd_down and url.startswith(FD_BASE)

    def cache_path(self, rel):
        from pathlib import Path

        return Path("/nonexistent") / rel

    def get(self, url, cache_rel, max_age_hours=None, force=False):
        self.requested.append(url)
        if self.fd_down and url.startswith(FD_BASE):
            raise DownloadError(url, "bağlantı hatası")
        if url in self.files:
            self.stats["network"] += 1
            return self.files[url]
        raise DownloadError(url, "dosya bulunamadı (404)", 404)


def _mirror_csv() -> bytes:
    rows = []
    for k, d in enumerate(pd.date_range("2024-08-10", periods=12, freq="7D")):
        rows.append({
            "Division": "T1", "MatchDate": d.strftime("%Y-%m-%d"), "MatchTime": "19:00:00",
            "HomeTeam": ["Galatasaray", "Besiktas"][k % 2], "AwayTeam": ["Fenerbahce", "Goztep"][k % 2],
            "FTHome": k % 3, "FTAway": 1, "OddHome": 1.9, "OddDraw": 3.5, "OddAway": 4.0,
            "MaxHome": 2.0, "MaxDraw": 3.7, "MaxAway": 4.3, "Over25": 1.8, "Under25": 2.0,
        })
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode()


def test_update_from_football_data(tmp_home):
    files = {
        f"{FD_BASE}/mmz4281/1617/T1.csv": fixture_bytes("T1_1617.csv"),
        f"{FD_BASE}/mmz4281/2425/E0.csv": fixture_bytes("E0_2425.csv"),
        f"{FD_BASE}/fixtures.csv": fixture_bytes("fixtures.csv"),
    }
    st = DataStore(tmp_home)
    rep = st.update(["T1", "E0"], 10, today=dt.date(2026, 10, 10), downloader=FakeDownloader(files), allowed=ALL)
    assert rep.n_matches == 7
    assert rep.leagues == {"T1": "football-data.co.uk", "E0": "football-data.co.uk"}
    assert set(st.fixtures["league"]) == {"T1", "E0"}
    assert st.matches["date"].is_monotonic_increasing
    # Kaydedilen veri yeniden yüklenebilmeli
    st2 = DataStore(tmp_home)
    assert st2.load() and len(st2.matches) == 7
    assert st2.summary()["matches"].sum() == 7


def test_mirror_fallback_and_openfootball_fixtures(tmp_home):
    files = {
        MIRROR_URL: _mirror_csv(),
        f"{OPENFOOTBALL_BASE}/2026-27/tr.1.json": (
            b'{"matches": [{"date": "2026-10-12", "time": "19:00", "team1": "Galatasaray SK", '
            b'"team2": "Fenerbahce SK"}, {"date": "2026-10-13", "time": "19:00", "team1": "Foo FC", "team2": "Bar FC"}]}'
        ),
    }
    st = DataStore(tmp_home)
    rep = st.update(["T1"], 3, today=dt.date(2026, 10, 10), downloader=FakeDownloader(files, fd_down=True), allowed=ALL)
    assert rep.used_mirror
    assert rep.leagues["T1"] == "GitHub yedek veri seti"
    assert len(st.matches) == 12
    assert len(st.fixtures) == 1  # eşleşmeyen takımlı maç atılır
    fx = st.fixtures.iloc[0]
    assert (fx["home"], fx["away"]) == ("Galatasaray", "Fenerbahce")
    assert any("eşleştirilemedi" in w for w in rep.warnings)


def test_no_data_keeps_previous(tmp_home):
    st = DataStore(tmp_home)
    files = {f"{FD_BASE}/mmz4281/2425/E0.csv": fixture_bytes("E0_2425.csv")}
    st.update(["E0"], 3, today=dt.date(2025, 3, 1), downloader=FakeDownloader(files), allowed=ALL)
    assert len(st.matches) == 4
    rep = st.update(["E0"], 3, today=dt.date(2025, 3, 1), downloader=FakeDownloader({}, fd_down=True),
                    use_mirror_fallback=False, allowed=ALL)
    assert len(st.matches) == 4
    assert any("korunuyor" in w for w in rep.warnings)


@pytest.mark.network
def test_real_download_football_data(tmp_home):
    """Gerçek football-data.co.uk sunucusundan bir sezon ve fikstür indirir (CI'da çalışır)."""
    from bahis_tahmin.data.sources import Downloader

    st = DataStore(tmp_home)
    rep = st.update(["T1", "E0"], 2, downloader=Downloader(tmp_home / "raw"), use_mirror_fallback=False,
                    allowed={"football-data"})
    assert rep.leagues.get("T1") == "football-data.co.uk", rep.summary()
    assert rep.leagues.get("E0") == "football-data.co.uk", rep.summary()
    assert len(st.matches) > 500
    assert st.matches["o_h"].notna().mean() > 0.9
    assert st.matches["h_sot"].notna().mean() > 0.9


def test_sources_without_consent_are_not_used(tmp_home):
    """Kullanım koşulları onaylanmamış kaynak etkinleşmez (indirme isteği bile yapılmaz)."""
    files = {
        f"{FD_BASE}/mmz4281/2425/E0.csv": fixture_bytes("E0_2425.csv"),
        MIRROR_URL: _mirror_csv(),
    }
    dl = FakeDownloader(files)
    st = DataStore(tmp_home)
    rep = st.update(["E0"], 3, today=dt.date(2025, 3, 1), downloader=dl)  # allowed verilmedi
    assert rep.n_matches == 0
    assert set(rep.blocked_sources) == {"football-data", "github-mirror"}
    assert not any(u.startswith(FD_BASE) or u == MIRROR_URL for u in dl.requested)
    assert "kullanım koşulları onaylanmadığı" in rep.summary()


def test_allowed_sources_policy():
    assert allowed_sources(None) == {"openfootball"}
    assert allowed_sources({"football-data": "2026-10-10T10:00:00"}) == {"openfootball", "football-data"}
    # Entegre edilmemiş/ücretli kaynak onaylansa bile etkinleşmez
    assert "the-odds-api" not in allowed_sources({"the-odds-api": "x"})
    assert SOURCES["openfootball"].requires_consent is False
    assert SOURCES["football-data"].requires_consent is True

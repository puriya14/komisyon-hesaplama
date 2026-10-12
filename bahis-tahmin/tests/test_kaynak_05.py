"""KAYNAK-05: Süper Lig ve 2. Bundesliga için ESPN; ESPN'den veri gelen ligde geride kalmış openfootball kullanılmaz,
ESPN'e ulaşılamazsa openfootball yedeği (FIKSTUR-03) çalışır. Yalnızca SENTETİK veri ve sahte indirici (ağ yok)."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import test_fikstur_03 as F3
from test_kaynak_04 import EspnFake, _event

from bahis_tahmin import eligibility as E
from bahis_tahmin.data.completion import COMPLETION_LABEL
from bahis_tahmin.data.espn import ESPN_BASE, ESPN_LABEL, ESPN_LEAGUES
from bahis_tahmin.data.source_registry import allowed_sources
from bahis_tahmin.data.sources import MIRROR_URL, DownloadError
from bahis_tahmin.data.store import DataStore

TODAY = F3.TODAY
WITH_ESPN = allowed_sources({"github-mirror": "t", "espn": "t"})
WITHOUT_ESPN = allowed_sources({"github-mirror": "t"})
TXT_JSON = ("openfootball", "2026-27", "tr.1.txt.json")


def _t1_events(played_until="2026-10-04"):
    """ESPN'in Süper Lig verisi: depo adlarıyla aynı adlar; 4 Ekim'e kadar sonuçlu. Oynanmamış turlar ESPN'de
    openfootball'dan bir gün önce (gerçek maç günü; openfootball'daki tarih yer tutucu)."""
    out = []
    for i, season, d, h, a in F3._indexed():
        if d <= pd.Timestamp(played_until):
            ft, ht = F3._score(i)
            out.append((d, _event(i, d, h, a, ft, (min(ht[0], ft[0]), min(ht[1], ft[1])))))
        else:
            d2 = d - pd.Timedelta(days=1)
            out.append((d2, _event(i, d2, h, a)))
    return out


def _files():
    return {MIRROR_URL: F3._mirror(), F3.TXT_URL: F3._txt(played_until="2026-09-20")}


def _update(home, dl, allowed):
    st = DataStore(home)
    st.load()
    rep = st.update(["T1"], 3, today=TODAY, downloader=dl, allowed=allowed)
    return st, rep


class EspnDown(EspnFake):
    def get(self, url, cache_rel, max_age_hours=None, force=False):
        if url.startswith(ESPN_BASE):
            self.requested.append(url)
            raise DownloadError(url, "bağlantı hatası")
        return super().get(url, cache_rel, max_age_hours, force)


def test_t1_and_d2_are_espn_leagues():
    assert ESPN_LEAGUES["T1"] == "tur.1" and ESPN_LEAGUES["D2"] == "ger.2"


def test_espn_takes_precedence_over_stale_openfootball(tmp_home):
    # 1) ESPN onayı yok: FIKSTUR-03 davranışı (metin dosyası; 20 Eylül'den sonra sonuç yok)
    st, rep = _update(tmp_home, EspnFake(_files(), _t1_events()), WITHOUT_ESPN)
    assert rep.txt_sources and rep.espn == {} and (st.raw_dir.joinpath(*TXT_JSON)).is_file()
    assert set(st.fixtures["date"]) == {pd.Timestamp("2026-10-18")}
    # 2) ESPN onaylı: ESPN kullanılır; openfootball dosyası istenmez, sonucu/fikstürü/takvimi kullanılmaz
    dl = EspnFake(_files(), _t1_events())
    st, rep = _update(tmp_home, dl, WITH_ESPN)
    assert rep.espn["T1"]["sonuc"] == 8 and rep.espn["T1"]["eslesmeyen"] == []
    assert rep.txt_sources == {} and "T1" not in rep.completed and F3.TXT_URL not in dl.requested
    src = set(st.matches["source"])
    assert ESPN_LABEL in src and COMPLETION_LABEL not in src
    fx = st.fixtures
    assert set(fx["source"]) == {ESPN_LABEL} and set(fx["date"]) == {pd.Timestamp("2026-10-17")} and len(fx) == 2
    # Eski openfootball takvimi diskte kalsa da aynı sezonda ESPN takvimi kullanılır
    covs = E.cached_coverages(st.raw_dir, ["T1"], TODAY, {"T1": F3.FD})["T1"]
    assert {c.source for c in covs} == {ESPN_LABEL}


def test_espn_unreachable_falls_back_to_openfootball_and_drops_old_calendar(tmp_home):
    st, rep = _update(tmp_home, EspnFake(_files(), _t1_events()), WITH_ESPN)
    cal = st.raw_dir / "espn" / "2026-27" / "T1.json"
    assert cal.is_file()
    st, rep = _update(tmp_home, EspnDown(_files(), []), WITH_ESPN)
    assert rep.espn == {} and any("ESPN'den veri alınamadı" in w for w in rep.warnings)
    assert rep.txt_sources and rep.completed == {"T1": 4} and not cal.exists()
    assert set(st.fixtures["source"]) == {"openfootball"}
    covs = E.cached_coverages(st.raw_dir, ["T1"], TODAY, {"T1": F3.FD})["T1"]
    assert {c.source for c in covs} == {"openfootball"}


def test_revoked_consent_removes_espn_rows_and_calendar(tmp_home):
    st, _ = _update(tmp_home, EspnFake(_files(), _t1_events()), WITH_ESPN)
    assert (st.matches["source"] == ESPN_LABEL).any()
    dl = EspnFake(_files(), _t1_events())
    st, rep = _update(tmp_home, dl, WITHOUT_ESPN)
    assert not any(u.startswith(ESPN_BASE) for u in dl.requested)
    assert not (st.matches["source"] == ESPN_LABEL).any() and not list((st.raw_dir / "espn").glob("*/T1.json"))
    assert rep.txt_sources  # openfootball yedeğine dönüldü
    assert dt.date(2026, 10, 18) in {d.date() for d in st.fixtures["date"]}

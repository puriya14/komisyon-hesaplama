"""S4-PILOT-01: openfootball sonuç adaptörü, kaynak kökeni, yalıtılmış pilot klasörü ve pilot akışı.

YALNIZCA açıkça SENTETİK veri kullanılır: uydurma takım adları ("Pilot Takim A"...), skorlar ve tarihler; sahte commit
özetleri; katılımcı referansı ``example.invalid`` adresli sentetik dosya. Ağ isteği yapılmaz (indirici sahte), gerçek
veri deposuna, kullanıcı defterine, modele veya ayarlara dokunulmaz. Bu testler gerçek veri pilotunun sonucunu
DOĞRULAMAZ; yalnızca kod yolunu sınar (gerçek pilot sonuçları ayrı raporlanır).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from takvim_yardim import circle_rounds

from bahis_tahmin import pilot as PL
from bahis_tahmin.cli import main
from bahis_tahmin.data.parsers import (
    OPENFOOTBALL_RESULT_LABEL,
    parse_openfootball,
    parse_openfootball_results,
)
from bahis_tahmin.data.provenance import rows_sha256, verified_labels, verify_results
from bahis_tahmin.data.sources import DownloadError
from bahis_tahmin.data.store import DataStore
from bahis_tahmin.eligibility import training_rights_codes
from bahis_tahmin.goals import forecast_log as F
from bahis_tahmin.goals.ledger import Ledger
from bahis_tahmin.goals.markets import PRIMARY_YES

UTC = dt.timezone.utc
TEAMS = [f"Pilot Takim {c}" for c in "ABCDEFGHIJKLMNOP"]  # 16 sentetik takım
REF_A = "a" * 40  # sahte (sentetik) commit özetleri
REF_B = "b" * 40


def _of(matches: list[dict]) -> bytes:
    return json.dumps({"name": "Sentetik Lig", "matches": matches}, ensure_ascii=False).encode("utf-8")


def _m(date: str, t1: str, t2: str, score=None, rnd: str = "Matchday 1", **extra) -> dict:
    m = {"round": rnd, "date": date, "time": "15:00", "team1": t1, "team2": t2}
    if score is not None:
        m["score"] = score
    m.update(extra)
    return m


def _parse(matches: list[dict], season: str = "2030/31"):
    return parse_openfootball_results(_of(matches), "E0", season)


# =============================================================== 1) sonuç adaptörü
def test_ht_ft_dict_is_read_with_both_halves():
    res = _parse([_m("2030-08-10", "A", "B", {"ht": [1, 0], "ft": [2, 1]})])
    r = res.matches.iloc[0]
    assert (r["fthg"], r["ftag"], r["hthg"], r["htag"]) == (2, 1, 1.0, 0.0)
    assert r["source"] == OPENFOOTBALL_RESULT_LABEL and r["season"] == "2030/31" and r["league"] == "E0"
    assert (res.oynanmis, res.ht, res.yalniz_ft, res.karantina) == (1, 1, 0, [])


def test_ft_only_list_is_not_counted_as_half_time():
    res = _parse([_m("2030-08-10", "A", "B", [3, 2]),
                  _m("2030-08-10", "C", "D", {"ft": [1, 1]})])  # sözlükte yalnızca ft da İY değildir
    assert res.oynanmis == 2 and res.ht == 0 and res.yalniz_ft == 2
    assert res.matches["hthg"].isna().all() and res.matches["htag"].isna().all()
    assert sorted(res.matches["fthg"]) == [1, 3]


def test_real_nil_nil_is_distinct_from_missing_score():
    from bahis_tahmin.data.parsers import OPENFOOTBALL_RESULT_PARSER_V1

    matches = [_m("2030-08-10", "A", "B", {"ht": [0, 0], "ft": [0, 0]}),
               _m("2030-08-10", "C", "D"),  # skor yok: oynanmamış, sonuç satırı DEĞİL
               _m("2030-08-10", "E", "F", {"ft": [0, 0]}),  # MS 0-0, İY alanı yok
               _m("2030-08-10", "G", "H", {"ft": [2, 1]})]  # MS 0-0 değil, İY alanı yok: gerçekten eksik
    res = _parse(matches)
    m = res.matches.set_index("home")
    assert (m.loc["A", "fthg"], m.loc["A", "ftag"], m.loc["A", "hthg"], m.loc["A", "htag"]) == (0, 0, 0.0, 0.0)
    assert "C" not in m.index and res.oynanmamis == 1 and res.tamamlanmamis_tarihler == ["2030-08-10"]
    # S4-MODEL-01 (v2): MS 0-0 ise İY mantıksal olarak 0-0 (0 ≤ İY ≤ MS) ve açıkça işaretli; bu bir tahmin değildir
    assert (m.loc["E", "fthg"], m.loc["E", "ftag"], m.loc["E", "hthg"], m.loc["E", "htag"]) == (0, 0, 0.0, 0.0)
    assert m.loc["E", "iy_mantiksal"] and not m.loc["A", "iy_mantiksal"] and res.iy_mantiksal == 1
    # gerçekten eksik İY eksik kalır (0-0 yapılmaz, MS'den tahmin edilmez)
    assert (m.loc["G", "fthg"], m.loc["G", "ftag"]) == (2, 1) and np.isnan(m.loc["G", "hthg"])
    assert not m.loc["G", "iy_mantiksal"]
    # v1 (S4-PILOT-01 kuralı) hâlâ okunabilir: İY alanı yoksa bilinmiyor
    v1 = parse_openfootball_results(_of(matches), "E0", "2030/31", OPENFOOTBALL_RESULT_PARSER_V1).matches
    v1 = v1.set_index("home")
    assert np.isnan(v1.loc["E", "hthg"]) and np.isnan(v1.loc["G", "hthg"]) and not v1["iy_mantiksal"].any()


@pytest.mark.parametrize("score, reason", [
    ({"ft": [-1, 0]}, "SKOR_GECERSIZ"),
    ({"ft": [1.5, 0]}, "SKOR_GECERSIZ"),
    ({"ft": [True, 0]}, "SKOR_GECERSIZ"),
    ({"ft": [1, "2"]}, "SKOR_GECERSIZ"),
    ([31, 0], "SKOR_GECERSIZ"),
    ([1, 2, 3], "BICIM_BILINMIYOR"),
    ({"ft": [1, 0], "ht": [2, 0]}, "IY_MS_CELISKI"),
    ({"ft": [1, 1], "et": [2, 1]}, "UZATMA_ALANI"),
    ({"ft": [1, 1], "p": [4, 3]}, "UZATMA_ALANI"),
    ({"ht": [1, 0]}, "BICIM_BILINMIYOR"),  # ft yok
    ({"ft": [1, 0], "xg": [1, 0]}, "BICIM_BILINMIYOR"),  # bilinmeyen alan sessizce kabul edilmez
    ("2-1", "BICIM_BILINMIYOR"),
])
def test_invalid_or_ambiguous_scores_are_quarantined(score, reason):
    res = _parse([_m("2030-08-10", "A", "B", score), _m("2030-08-10", "C", "D", {"ft": [1, 0]})])
    assert res.matches["home"].tolist() == ["C"]
    assert [k["neden"] for k in res.karantina] == [reason]


def test_status_and_dates_are_not_guessed():
    res = _parse([
        _m("2030-08-10", "A", "B", rnd="Matchday 1"),
        _m("2030-08-17", "A", "C", {"ft": [3, 0]}, rnd="Matchday 2", status="awarded"),  # hükmen: normal süre değil
        _m("2030-08-17", "B", "D", rnd="Matchday 2", status="postponed"),  # skorsuz ertelenen: oynanmamış
        _m("2029-08-24", "E", "F", {"ft": [1, 0]}, rnd="Matchday 3"),  # yılı sezon dışı: düzeltilmez
        _m("2030-13-01", "G", "H", {"ft": [1, 0]}, rnd="Matchday 3"),
        _m("2030-08-24", "G", "G", {"ft": [1, 0]}, rnd="Matchday 3"),
    ])
    assert res.matches.empty and res.oynanmamis == 1 and res.oynanmamis_durumlu == 1
    assert sorted(k["neden"] for k in res.karantina) == ["DURUM_BELIRSIZ", "TAKIM_GECERSIZ", "TARIH_GECERSIZ",
                                                          "TARIH_SEZON_DISI"]


def test_duplicates_are_idempotent_and_conflicts_are_not_overwritten():
    ok = _m("2030-08-10", "A", "B", {"ht": [0, 0], "ft": [1, 0]}, id=7)
    res = _parse([ok, dict(ok), dict(ok, round="Matchday 1 (tekrar)"),
                  _m("2030-08-10", "C", "D", {"ft": [2, 2]}), _m("2030-08-10", "C", "D", {"ft": [2, 1]}),
                  _m("2030-08-17", "E", "F", {"ft": [1, 0]}, rnd="Matchday 2"),
                  _m("2030-08-17", "E", "G", {"ft": [0, 0]}, rnd="Matchday 2")])
    assert res.matches["home"].tolist() == ["A"] and res.yinelenen == 2
    reasons = sorted(k["neden"] for k in res.karantina)
    assert reasons == ["AYNI_GUN_IKI_MAC", "AYNI_GUN_IKI_MAC", "CAKISAN_KAYIT", "CAKISAN_KAYIT"]
    # aynı dosyayı yeniden okumak aynı satırları üretir (çoğaltma yok, deterministik)
    again = _parse([ok, dict(ok), dict(ok, round="Matchday 1 (tekrar)"),
                    _m("2030-08-10", "C", "D", {"ft": [2, 2]}), _m("2030-08-10", "C", "D", {"ft": [2, 1]}),
                    _m("2030-08-17", "E", "F", {"ft": [1, 0]}, rnd="Matchday 2"),
                    _m("2030-08-17", "E", "G", {"ft": [0, 0]}, rnd="Matchday 2")])
    assert again.sha256 == res.sha256 and rows_sha256(again.matches) == rows_sha256(res.matches)
    pd.testing.assert_frame_equal(again.matches, res.matches)


def test_only_registry_listed_alternative_names_are_canonicalised():
    from bahis_tahmin.data.parsers import OPENFOOTBALL_CLUB_ALIASES

    old = _parse([_m("2018-08-11", "Manchester City", "Arsenal FC", {"ht": [1, 0], "ft": [2, 0]})], "2018/19")
    new = _parse([_m("2021-08-14", "Manchester City FC", "Arsenal FC", {"ht": [0, 0], "ft": [1, 0]})], "2021/22")
    assert old.matches["home"].tolist() == new.matches["home"].tolist() == ["Manchester City FC"]
    assert old.ozet()["kanonik_ad_eslemesi"] == {"Manchester City": "Manchester City FC"}
    assert new.ozet()["kanonik_ad_eslemesi"] == {}
    # kayıtta olmayan kısaltma veya benzer ad otomatik birleştirilmez; eşleme yalnızca kendi liginde uygulanır
    other = _parse([_m("2021-08-14", "Man City", "Arsenal", {"ft": [1, 0]})])
    assert other.matches[["home", "away"]].values.tolist() == [["Man City", "Arsenal"]]
    assert parse_openfootball_results(_of([_m("2021-08-14", "Manchester City", "B", {"ft": [1, 0]})]), "E1",
                                      "2021/22").matches["home"].tolist() == ["Manchester City"]
    # kanonik ada çevrilince aynı gün iki kez oynayan veya kendisiyle oynayan takım karantinaya alınır
    clash = _parse([_m("2021-08-14", "Manchester City", "B", {"ft": [1, 0]}),
                    _m("2021-08-14", "Manchester City FC", "C", {"ft": [0, 0]}),
                    _m("2021-08-14", "Manchester United", "Manchester United FC", {"ft": [0, 0]})])
    assert clash.matches.empty
    assert sorted(k["neden"] for k in clash.karantina) == ["AYNI_GUN_IKI_MAC", "AYNI_GUN_IKI_MAC", "TAKIM_GECERSIZ"]
    assert all(v.endswith(("FC", "AFC")) for v in OPENFOOTBALL_CLUB_ALIASES["E0"].values())


def test_result_adapter_leaves_fixture_adapter_behaviour_unchanged():
    data = _of([_m("2030-08-10", "A", "B", {"ht": [1, 0], "ft": [2, 1]}),
                _m("2030-08-10", "C", "D", [1, 1]),
                _m("2030-08-17", "A", "C", rnd="Matchday 2"),
                _m("2030-08-17", "B", "D", {"ht": [0, 0]}, rnd="Matchday 2")])  # ft'siz skor fikstür sayılır
    fx = parse_openfootball(data, "E0")
    assert fx[["home", "away"]].values.tolist() == [["A", "C"], ["B", "D"]]
    assert set(fx["source"]) == {"openfootball"}  # fikstür etiketi değişmedi; sonuç etiketi ayrı
    res = parse_openfootball_results(data, "E0", "2030/31")
    assert res.matches["home"].tolist() == ["A", "C"] and res.oynanmamis == 1
    assert [k["neden"] for k in res.karantina] == ["BICIM_BILINMIYOR"]


def test_unreadable_or_unknown_file_yields_no_rows():
    assert parse_openfootball_results(b"{bozuk", "E0", "2030/31").matches.empty
    res = parse_openfootball_results(b'{"rounds": []}', "E0", "2030/31")
    assert res.matches.empty and res.karantina[0]["neden"] == "BICIM_BILINMIYOR"


# =============================================================== 2) köken ve haklar
class _FakeStore:
    def __init__(self, matches, records, raw_dir):
        self.matches, self.meta, self.raw_dir = matches, {"kaynak_kokeni": records}, Path(raw_dir)


def _record(res, path: str, cache_rel: str, ref: str = REF_A) -> dict:
    from bahis_tahmin.data.parsers import OPENFOOTBALL_RESULT_PARSER
    from bahis_tahmin.data.provenance import OPENFOOTBALL_REPO, SourceFile

    return SourceFile(OPENFOOTBALL_REPO, path, ref, f"https://example.invalid/{ref}/{path}",
                      "2030-09-01T00:00:00+00:00", res.sha256, "E0", "2030/31", OPENFOOTBALL_RESULT_PARSER,
                      len(res.matches), rows_sha256(res.matches), cache_rel).to_dict()


def _cached(tmp_path, data: bytes) -> tuple[Path, str]:
    raw = tmp_path / "raw"
    rel = "openfootball/2030-31/en.1.json"
    (raw / rel).parent.mkdir(parents=True, exist_ok=True)
    (raw / rel).write_bytes(data)
    return raw, rel


def test_verified_source_rows_gain_rights_only_with_provenance(tmp_path):
    data = _of([_m("2030-08-10", "A", "B", {"ht": [1, 0], "ft": [2, 1]}),
                _m("2030-08-10", "C", "D", {"ht": [0, 0], "ft": [0, 1]})])
    res = parse_openfootball_results(data, "E0", "2030/31")
    raw, rel = _cached(tmp_path, data)
    good = _FakeStore(res.matches, [_record(res, "2030-31/en.1.json", rel)], raw)
    assert verified_labels(good) == {OPENFOOTBALL_RESULT_LABEL}
    assert training_rights_codes(good.matches, {}, verified_labels(good)) == []
    # köken kaydı yoksa aynı satırlar hak kazanamaz
    assert training_rights_codes(res.matches, {}, set()) == ["KAYNAK_KOKENI_DOGRULANAMADI"]
    assert training_rights_codes(res.matches, {}) == ["KAYNAK_KOKENI_DOGRULANAMADI"]


def test_relabelled_old_rows_cannot_pass_the_provenance_check(tmp_path):
    data = _of([_m("2030-08-10", "A", "B", {"ht": [1, 0], "ft": [2, 1]})])
    res = parse_openfootball_results(data, "E0", "2030/31")
    raw, rel = _cached(tmp_path, data)
    rec = _record(res, "2030-31/en.1.json", rel)
    # başka kaynaktan (ör. football-data) gelen satır etiketi değiştirilerek eklenirse köken doğrulanmaz
    foreign = res.matches.copy()
    foreign.loc[0, ["home", "away", "fthg", "ftag"]] = ["X", "Y", 4, 4]
    mixed = pd.concat([res.matches, foreign], ignore_index=True)
    st = _FakeStore(mixed, [rec], raw)
    ok, problems = verify_results(st.matches, [rec], raw)
    assert not ok and "aynı değil" in problems[0] and verified_labels(st) == set()
    assert "KAYNAK_KOKENI_DOGRULANAMADI" in training_rights_codes(mixed, {}, verified_labels(st))
    # önbellekteki dosya değiştirilirse (özet uyuşmaz) veya kayıt sahteyse yine doğrulanmaz
    (raw / rel).write_bytes(data + b" ")
    assert verify_results(res.matches, [rec], raw)[0] is False
    (raw / rel).write_bytes(data)
    assert verify_results(res.matches, [dict(rec, ref="master")], raw)[0] is False
    assert verify_results(res.matches, [dict(rec, parser="baska-v9")], raw)[0] is False
    # fikstür etiketiyle ("openfootball") sonuç satırı hâlâ hak kazanamaz (S3 negatif kontrolü korunur)
    relabel = res.matches.assign(source="openfootball")
    assert "KAYNAK_ETIKETI_UYUMSUZ" in training_rights_codes(relabel, {}, {OPENFOOTBALL_RESULT_LABEL})
    # eski kaynakların hakları gevşemedi
    assert training_rights_codes(res.matches.assign(source="football-data.co.uk"), {"football-data": "x"})


# =============================================================== 3) yalıtılmış pilot klasörü
def test_pilot_dir_must_be_separate_from_user_app_home(tmp_home, tmp_path):
    for bad in (tmp_home, tmp_home / "pilot", tmp_home.parent):
        with pytest.raises(PL.PilotError):
            PL.check_pilot_dir(bad, create=True)
    with pytest.raises(PL.PilotError):
        PL.check_pilot_dir("", create=True)
    other = tmp_path / "baska"
    other.mkdir()
    (other / "kullanici.txt").write_text("x", encoding="utf-8")
    with pytest.raises(PL.PilotError):  # boş olmayan ve pilot işareti taşımayan klasöre yazılmaz
        PL.check_pilot_dir(other, create=True)
    with pytest.raises(PL.PilotError):  # salt okunur komutlar hazırlanmamış klasörü reddeder
        PL.check_pilot_dir(tmp_path / "yok")
    assert not (tmp_path / "yok").exists()
    ok = PL.check_pilot_dir(tmp_path / "pilot", create=True)
    assert (ok / PL.MARKER).is_file() and PL.check_pilot_dir(ok) == ok
    assert sorted(p.name for p in tmp_home.iterdir()) == []


def test_pilot_seasons_and_ref_rules():
    assert PL.pilot_seasons(dt.date(2030, 11, 1), 2) == ["2030-31", "2029-30", "2028-29"]
    assert PL.pilot_seasons(dt.date(2031, 3, 1), 1) == ["2030-31", "2029-30"]
    with pytest.raises(PL.PilotError):
        PL.pilot_seasons(dt.date(2030, 11, 1), PL.MAX_SEASON_FILES)  # devam eden dahil en çok 17 dosya
    assert PL.resolve_ref(REF_A.upper()) == (REF_A, None, "verilen")
    with pytest.raises(PL.PilotError):
        PL.resolve_ref("master")  # sabitlenmemiş ref ile indirme yapılmaz

    class _NoNet:
        def get(self, *a, **k):
            raise OSError("ağ yok")

    with pytest.raises(PL.PilotError):
        PL.resolve_ref(None, session=_NoNet())


def test_participant_reference_requires_exact_identity(tmp_path):
    store_teams = ["Pilot Takim A", "Pilot Takim B", "Pilot Takim C", "Pilot Takim D", "City FC", "City SC"]
    ref = {"lig": "E0", "kaynak": "https://example.invalid/katilimci", "alinma_utc": "2030-11-01T00:00:00+00:00",
           "sezonlar": {"2030/31": store_teams[:4], "2029/30": store_teams[:3] + ["City"],
                        "2028/29": store_teams[:3] + ["Bilinmeyen"], "2027/28": "bozuk"}}
    p = tmp_path / "k.json"
    p.write_text(json.dumps(ref), encoding="utf-8")
    parts, report = PL.load_participants(p, store_teams)
    assert parts == {("E0", "2030/31"): frozenset(store_teams[:4])}
    assert report["sezonlar"]["2029/30"]["durum"] == "ESLESMEYEN_AD"  # belirsiz ad kesinleşmez
    assert report["sezonlar"]["2029/30"]["eslesmeyen_adlar"] == {"City": ["City FC", "City SC"]}
    assert report["sezonlar"]["2028/29"]["durum"] == "ESLESMEYEN_AD"
    assert report["sezonlar"]["2027/28"]["durum"] == "GECERSIZ_BICIM"
    for broken in ({**ref, "lig": "SP1"}, {**ref, "kaynak": ""}, {**ref, "alinma_utc": None}):
        p.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(PL.PilotError):
            PL.load_participants(p, store_teams)


# =============================================================== 4) sentetik uçtan uca pilot
def _as_of() -> dt.datetime:
    """Gerçek saatten SONRAKİ ilk 1 Kasım 12:00 UTC: eğitim ve dosya alımı her zaman değerlendirme anından önce kalır
    (testin sonucu çalıştırıldığı güne bağlı değildir)."""
    now = dt.datetime.now(UTC)
    y = now.year if now < dt.datetime(now.year, 11, 1, 12, tzinfo=UTC) else now.year + 1
    return dt.datetime(y, 11, 1, 12, tzinfo=UTC)


AS_OF = _as_of()
Y = AS_OF.year


def _season_start(y: int) -> dt.date:
    d = dt.date(y, 8, 10)
    return d + dt.timedelta(days=(5 - d.weekday()) % 7)  # ilk cumartesi


def _season_bytes(y: int, played_before: dt.date | None = None, unscored: set | None = None) -> bytes:
    """Sentetik çift devreli sezon (16 takım, 30 tur, haftalık). ``played_before``: bu tarihten önceki maçlar skorlu;
    ``unscored``: tarihi geçmiş olsa da skoru verilmeyen turlar (bayat kaynak)."""
    rng = np.random.default_rng(y)
    start = _season_start(y)
    ms = []
    for r, pairs in enumerate(circle_rounds(TEAMS, 2)):
        d = start + dt.timedelta(days=7 * r)
        for h, a in pairs:
            m = _m(str(d), h, a, rnd=f"Matchday {r + 1}")
            if (played_before is None or d < played_before) and r + 1 not in (unscored or set()):
                hg, ag = int(rng.poisson(1.5)), int(rng.poisson(1.2))
                hh, ha = int(rng.integers(0, hg + 1)), int(rng.integers(0, ag + 1))
                m["score"] = {"ht": [hh, ha], "ft": [hg, ag]} if (r + 7 * len(ms)) % 11 else [hg, ag]
            ms.append(m)
    return _of(ms)


def _folder(y: int) -> str:
    return f"{y}-{(y + 1) % 100:02d}"


def _label(y: int) -> str:
    return f"{y}/{(y + 1) % 100:02d}"


class _StubDownloader:
    """Sahte indirici: ağ yok; yalnızca verilen sentetik sezon dosyaları."""

    def __init__(self, files: dict):
        self.files, self.calls = files, []

    def get(self, url, cache_rel, max_age_hours=None, force=False):
        self.calls.append(url)
        for folder, data in self.files.items():
            if url.endswith(f"/{folder}/en.1.json"):
                return data
        raise DownloadError(url, "yok", 404)


def _files(unscored: set | None = None, missing: tuple = ()) -> dict:
    today = AS_OF.date()
    out = {_folder(Y): _season_bytes(Y, played_before=today, unscored=unscored)}
    for k in range(1, 5):
        out[_folder(Y - k)] = _season_bytes(Y - k)
    return {f: d for f, d in out.items() if f not in missing}


def _participants(tmp_path, seasons) -> Path:
    p = tmp_path / f"katilimci_{len(seasons)}.json"
    p.write_text(json.dumps({"lig": "E0", "kaynak": "https://example.invalid/sentetik-katilimcilar",
                             "alinma_utc": "2030-01-01T00:00:00+00:00",
                             "sezonlar": {_label(y): TEAMS for y in seasons}}), encoding="utf-8")
    return p


def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def trained_pilot(tmp_path_factory):
    """Bir kez hazırlanıp eğitilen sentetik pilot (4 tamamlanmış + devam eden sezon, bağımsız sentetik katılımcılar)."""
    base = tmp_path_factory.mktemp("s4")
    user = base / "kullanici"
    user.mkdir()
    mp = pytest.MonkeyPatch()
    mp.setenv("BAHIS_TAHMIN_HOME", str(user))
    try:
        (user / "settings.json").write_text('{"leagues": ["E0"]}', encoding="utf-8")
        (user / "gol_pazarlari.sqlite").write_bytes(b"kullanici-defteri")
        before = _snapshot(user)
        home = base / "pilot"
        dl = _StubDownloader(_files())
        prep = PL.prepare(home, ref=REF_A, completed=4, participants_file=_participants(base, range(Y - 4, Y + 1)),
                          downloader=dl, now=AS_OF)
        trained = PL.train(home)
        after = _snapshot(user)
    finally:
        mp.undo()
    return {"home": home, "prep": prep, "train": trained, "user_before": before, "user_after": after, "dl": dl,
            "base": base}


def _copy(trained_pilot, tmp_path) -> Path:
    dst = tmp_path / "pilot_kopya"
    shutil.copytree(trained_pilot["home"], dst)
    return dst


@pytest.fixture
def fixed_write_clock(monkeypatch):
    monkeypatch.setattr(F, "_now", lambda: AS_OF + dt.timedelta(minutes=1))


def test_prepare_records_provenance_and_counts_without_touching_user_files(trained_pilot):
    prep, home = trained_pilot["prep"], trained_pilot["home"]
    assert prep["koken_dogrulandi"] is True and prep["eksik_sezon_dosyasi"] == []
    assert prep["kaynak_commit"] == REF_A and prep["fikstur"] > 0 and prep["eslesmeyen_fikstur"] == 0
    assert prep["gecerli_katilimci_sezonu"] == sorted(_label(y) for y in range(Y - 4, Y + 1))
    cur = prep["sezonlar"][_label(Y)]
    assert cur["oynanmamis"] > 0 and cur["bilgi_kesiminden_once_sonucsuz"] == 0
    assert all(s["ilk_yari_gecerli"] + s["yalniz_mac_sonu"] == s["oynanmis_gecerli"] for s in prep["sezonlar"].values())
    st = DataStore(home)
    assert st.load() and set(st.matches["source"]) == {OPENFOOTBALL_RESULT_LABEL}
    for rec in st.meta["kaynak_kokeni"]:
        assert rec["ref"] == REF_A and rec["repo"] == "openfootball/football.json" and rec["retrieved_at"]
        assert len(rec["sha256"]) == 64 and len(rec["rows_sha256"]) == 64 and rec["parser"]
    assert trained_pilot["user_after"] == trained_pilot["user_before"]  # kullanıcı dosyaları değişmedi
    # pilot klasöründe yalnızca pilot dosyaları; geçici indirme klasörü kalmaz
    names = {p.name for p in home.iterdir()}
    assert {PL.MARKER, PL.GOAL_ENGINE_FILE, PL.MODEL_INFO, "raw"} <= names
    assert not any(".indirme" in str(p) and p.is_file() for p in (home / "raw").rglob("*"))


def test_prepare_is_idempotent_and_reuses_pinned_cache(trained_pilot, tmp_path):
    home = _copy(trained_pilot, tmp_path)
    st0 = DataStore(home)
    st0.load()
    dl = _StubDownloader({})  # aynı commit ve özet: yeniden indirme yok
    out = PL.prepare(home, ref=REF_A, completed=4, downloader=dl, now=AS_OF)
    st1 = DataStore(home)
    st1.load()
    assert dl.calls == [] and out["sonuc_satiri"] == len(st0.matches) == len(st1.matches)
    assert rows_sha256(st1.matches) == rows_sha256(st0.matches) and out["koken_dogrulandi"] is True
    assert out["gecerli_katilimci_sezonu"] == trained_pilot["prep"]["gecerli_katilimci_sezonu"]  # referans korunur


def test_missing_previous_season_file_is_reported_not_filled(tmp_path):
    home = tmp_path / "pilot"
    out = PL.prepare(home, ref=REF_A, completed=4, downloader=_StubDownloader(_files(missing=(_folder(Y - 1),))),
                     now=AS_OF)
    assert out["eksik_sezon_dosyasi"] == [_folder(Y - 1)] and _label(Y - 1) not in out["sezonlar"]
    with pytest.raises(PL.PilotError):  # içinde bulunulan sezon dosyası yoksa pilot hazırlanmaz
        PL.prepare(tmp_path / "p2", ref=REF_A, completed=1, downloader=_StubDownloader({}), now=AS_OF)


def test_training_uses_existing_engine_rules_and_writes_only_pilot_files(trained_pilot):
    from bahis_tahmin.goals.engine import MIN_TRAIN_ROWS

    tr, home = trained_pilot["train"], trained_pilot["home"]
    assert tr["durum"] == "EGITILDI" and tr["en_az"] == MIN_TRAIN_ROWS == 500
    assert tr["egitim_satiri"] >= MIN_TRAIN_ROWS and tr["ilk_yari_skorlu"] < tr["ham_mac"]
    assert tr["kaynaklar"] == [OPENFOOTBALL_RESULT_LABEL] and tr["kaynak_commit"] == REF_A
    assert set(tr["dogrulama"]) == set(PRIMARY_YES)
    assert set(tr["dogrulama"].values()) <= {"MODEL_NOT_VALIDATED", "VALIDATED_FOR_PAPER_TRADING"}
    for k, v in tr["dogrulama"].items():  # mevcut kural: ölçüt yoksa veya 200 pozitif yoksa doğrulanmış sayılmaz
        m = tr["olcutler"].get(k)
        if m is None or (m["pozitif"] or 0) < 200:
            assert v == "MODEL_NOT_VALIDATED"
    assert (home / PL.GOAL_ENGINE_FILE).is_file() and json.loads((home / PL.MODEL_INFO).read_text("utf-8"))["durum"]
    assert trained_pilot["user_after"] == trained_pilot["user_before"]


def test_training_refuses_unverified_or_foreign_rows(trained_pilot, tmp_path):
    home = _copy(trained_pilot, tmp_path)
    st = DataStore(home)
    st.load()
    st.matches.loc[st.matches.index[:5], "source"] = "football-data.co.uk"
    st.save()
    with pytest.raises(PL.PilotError, match="beklenmeyen kaynak"):
        PL.train(home)
    st.matches["source"] = OPENFOOTBALL_RESULT_LABEL
    st.matches.loc[st.matches.index[0], "fthg"] = 9  # kaynak dosyasıyla uyuşmayan satır
    st.save()
    with pytest.raises(PL.PilotError, match="Eğitim yapılmadı"):
        PL.train(home)


def test_forecast_records_probabilities_without_bet_candidates(trained_pilot, tmp_path, fixed_write_clock):
    home = _copy(trained_pilot, tmp_path)
    dry = PL.forecast(home, apply=False, now=AS_OF)
    assert not (home / PL.LEDGER_FILE).exists()  # kuru çalıştırma yazmaz
    assert dry["model_yuklendi"] and dry["mac"] == trained_pilot["prep"]["fikstur"] and dry["tahmin"] > 0
    assert dry["stake_toplam"] == 0.0 and dry["bahis_adayi"] == 0 and dry["zamani_dogrulanmis_oranli"] == 0
    assert dry["model_dogrulama"] == trained_pilot["train"]["dogrulama"]  # doğrulama etiketi gizlenmez
    out = PL.forecast(home, apply=True, now=AS_OF)
    assert out["yazildi"]["yazilan"] == out["aday_kayit"] and out["yazildi"]["gec_kalan"] == 0
    led = Ledger(home / PL.LEDGER_FILE)
    try:
        recs = led.predictions()
        ok, _ = led.verify_chain()
    finally:
        led.close()
    assert ok and len(recs) == out["aday_kayit"]
    st = DataStore(home)
    st.load()
    src_fixtures = {(r.home, r.away, str(pd.Timestamp(r.date).date())) for r in st.fixtures.itertuples()}
    for r in recs:
        assert r["stake_units"] == 0.0 and r["protokol"] == F.ACTIVE_PROTOCOL and r["market_key"] in PRIMARY_YES
        assert (r["home"], r["away"], r["mac_tarihi"]) in src_fixtures  # yalnızca kaynaktaki gerçek fikstürler
        assert dt.date.fromisoformat(r["mac_tarihi"]) > AS_OF.date()  # geçmiş maç ileriye dönük kayda girmez
        if r["decision_status"] == F.STATUS_FORECAST:
            assert 0 < r["p"] < 1 and r["oran"] is None and r["ekonomik_statu"] == "ORAN_YOK"
            assert r["model_veri_sha256"] == trained_pilot["train"]["veri_sha256"]
        else:
            assert r["p"] is None and r["reasons"]
    again = PL.forecast(home, apply=True, now=AS_OF)  # aynı maç/pazar ikinci kez yazılmaz
    assert again["yazildi"]["yazilan"] == 0 and again["yazildi"]["atlanan_mukerrer"] == out["aday_kayit"]
    assert PL.summary(home)["defter"]["kayit"] == out["aday_kayit"]


def test_missed_window_is_not_backfilled(trained_pilot, tmp_path, monkeypatch):
    home = _copy(trained_pilot, tmp_path)
    st = DataStore(home)
    st.load()
    first = st.fixtures["date"].min()
    n_first = int((st.fixtures["date"] == first).sum())
    late = F.decision_target(pd.Timestamp(first)) + dt.timedelta(hours=1)
    out = PL.forecast(home, apply=False, now=late)
    assert out["birincil_neden"].get("PENCERE_KACIRILDI", 0) == 3 * n_first
    # Hesap anı geriye verilse de yazma anı saatle yeniden denetlenir: hedefi geçmiş kayıt olasılık taşımaz
    monkeypatch.setattr(F, "_now", lambda: late)
    out = PL.forecast(home, apply=True, now=AS_OF)
    assert out["yazildi"]["gec_kalan"] == 3 * n_first
    led = Ledger(home / PL.LEDGER_FILE)
    try:
        recs = led.predictions()
    finally:
        led.close()
    day = str(pd.Timestamp(first).date())
    first_day = [r for r in recs if r["mac_tarihi"] == day]
    assert len(first_day) == 3 * n_first
    assert all(r["p"] is None and r["reasons"][0] == "PENCERE_KACIRILDI" for r in first_day)


def _gated(out: dict) -> int:
    """Uygunluk denetiminden geçen aday kayıt sayısı (zaman kuralına takılanlar hariç)."""
    return out["aday_kayit"] - sum(out["birincil_neden"].get(k, 0) for k in ("PENCERE_KACIRILDI", "PROTOKOLDEN_ONCE",
                                                                             "MAC_SONUCU_BILINIYOR"))


def test_without_independent_participants_coverage_is_not_proven(trained_pilot, tmp_path):
    home = _copy(trained_pilot, tmp_path)
    (home / PL.PARTICIPANTS_COPY).unlink()  # bağımsız referans yok: aynı kaynak zinciri kendini doğrulayamaz
    out = PL.forecast(home, apply=False, now=AS_OF)
    assert out["tahmin"] == 0 and _gated(out) > 0
    assert out["tum_nedenler"].get("KAYNAK_KAPSAMI_KISMI", 0) == _gated(out)


def test_previous_season_without_reference_does_not_cover_window(trained_pilot, tmp_path):
    home = _copy(trained_pilot, tmp_path)
    only_current = _participants(tmp_path, [Y])  # önceki sezon için bağımsız referans yok
    PL.prepare(home, ref=REF_A, completed=4, participants_file=only_current, downloader=_StubDownloader({}),
               now=AS_OF)
    out = PL.forecast(home, apply=False, now=AS_OF)
    assert out["tahmin"] == 0 and _gated(out) > 0
    assert out["tum_nedenler"].get("KAYNAK_ARALIK_DISI", 0) == _gated(out)


def test_stale_source_blocks_forecasts(trained_pilot, tmp_path):
    home = _copy(trained_pilot, tmp_path)
    # Kaynak yeni commit'te son oynanmış turun skorlarını vermiyor (bayat kaynak): tarihi geçmiş, sonucu bilinmiyor
    last_round = max(r + 1 for r in range(30) if _season_start(Y) + dt.timedelta(days=7 * r) < AS_OF.date())
    files = _files(unscored={last_round})
    out = PL.prepare(home, ref=REF_B, completed=4, participants_file=_participants(tmp_path, range(Y - 4, Y + 1)),
                     downloader=_StubDownloader(files), now=AS_OF)
    assert out["sezonlar"][_label(Y)]["bilgi_kesiminden_once_sonucsuz"] == len(TEAMS) // 2
    res = PL.forecast(home, apply=False, now=AS_OF)
    assert res["tahmin"] == 0 and _gated(res) > 0
    assert res["tum_nedenler"].get("KAYNAK_DURUMU_BELIRSIZ", 0) == _gated(res)


# =============================================================== 5) komut satırı
def test_cli_pilot_commands_have_help_and_refuse_user_home(tmp_home, tmp_path, capsys):
    for cmd in ("pilot-kapsam", "pilot-hazirla", "pilot-egit", "pilot-tahmin"):
        with pytest.raises(SystemExit) as e:
            main([cmd, "--help"])
        assert e.value.code == 0
        assert "--ev" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["pilot-kapsam"])  # --ev zorunlu: varsayılan yol yok
    capsys.readouterr()
    assert main(["pilot-hazirla", "--ev", str(tmp_home), "--ref", REF_A]) == 3
    assert main(["pilot-tahmin", "--ev", str(tmp_home / "alt"), "--uygula"]) == 3
    assert main(["pilot-kapsam", "--ev", str(tmp_path / "yok")]) == 3
    assert main(["pilot-hazirla", "--ev", str(tmp_path / "p"), "--ref", "master"]) == 3
    err = capsys.readouterr().err
    assert "kullanıcı uygulama klasörüyle çakışıyor" in err and "40 karakter" in err
    assert sorted(p.name for p in tmp_home.iterdir()) == []


def test_cli_pilot_coverage_is_read_only(trained_pilot, tmp_path, capsys):
    home = _copy(trained_pilot, tmp_path)
    before = _snapshot(home)
    assert main(["pilot-kapsam", "--ev", str(home)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["koken_dogrulandi"] is True and out["model"]["durum"] == "EGITILDI"
    assert _snapshot(home) == before


def test_pilot_code_does_not_ship_real_data():
    root = Path(__file__).resolve().parents[1]
    bad = [p for d in ("bahis_tahmin", "tests", "docs", "reports") for p in (root / d).rglob("*")
           if p.is_file() and (p.suffix in {".joblib", ".sqlite", ".pkl", ".parquet"} or p.name == "en.1.json")]
    assert bad == []

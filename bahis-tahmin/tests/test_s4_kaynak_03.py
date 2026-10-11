"""S4-KAYNAK-03: bağımsız katılımcı referansının erişilebilirlik zamanı (sentetik).

Referans, takvim tamlığının (A/B) kanıtıdır; değerlendirme anında henüz erişilebilir olmayan referans o anın kanıtı
olamaz (kaynak dosyasının ``retrieved_at <= as_of`` kuralıyla aynı sınır). Erişilebilirlik anı: referanstaki
``alinma_utc`` (zaman dilimli olmalı) ile dosyanın bu sistemdeki değiştirilme zamanının GEÇ olanı; dosyadaki tarih
tek başına daha erken erişilebilirlik kanıtı değildir.

YALNIZCA sentetik takımlar, skorlar ve tarihler; geçici dizinler. Gerçek pilot, model veya defter kullanılmaz.
"""

from __future__ import annotations

import datetime as dt
import json
import os

import pandas as pd
import pytest
from takvim_yardim import openfootball_bytes, season_rows, store_frame
from uygunluk_yardim import UTC, synthetic_rights

from bahis_tahmin import eligibility as E
from bahis_tahmin import pilot as PL

TEAMS = [f"Kulup {c} FC" for c in "ABCDEFGHIJKLMNOPQRST"]  # depo adları (20 sentetik kulüp)
REF_NAMES = [t.removesuffix(" FC") for t in TEAMS]  # resmî yazım: "FC" eki yok (normalleştirilmiş tam ad eşleşir)
LEAGUE = "E0"
CUT = dt.date(2026, 10, 20)  # bilgi kesimi (İstanbul günü)
AT = dt.datetime(2026, 10, 20, 6, tzinfo=UTC)  # kaynak takvim dosyasının alınma anı (aynı gün, erken)
T_REF = dt.datetime(2026, 10, 20, 9, tzinfo=UTC)  # referansın erişilebilir olduğu an
AFTER = dt.datetime(2026, 10, 20, 12, tzinfo=UTC)
BEFORE = T_REF - dt.timedelta(seconds=1)
IST = dt.timezone(dt.timedelta(hours=3))

ROWS = []
for _k, _y in enumerate((2024, 2025, 2026)):
    ROWS += season_rows(TEAMS, dt.date(_y, 8, 8), f"{_y}/{(_y + 1) % 100:02d}", league=LEAGUE, seed=_k)
ALL = store_frame(ROWS)
STORE = ALL[ALL["date"] < pd.Timestamp(CUT)].reset_index(drop=True)
FIXTURE = next(r for r in ROWS if r["season"] == "2026/27" and r["round"] == "Matchday 12")


def _reference(tmp_path, alinma, mtime: dt.datetime | None = None, name: str = "katilimci.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"lig": LEAGUE, "kaynak": "https://example.invalid/resmi-katilimci", "alinma_utc": alinma,
                             "sezonlar": {"2025/26": REF_NAMES, "2026/27": REF_NAMES}}), encoding="utf-8")
    ts = (mtime or (T_REF - dt.timedelta(days=1))).timestamp()  # varsayılan: dosya alınma anından önce sistemde
    os.utime(p, (ts, ts))
    return p


def _coverages(parts) -> list:
    return [E.coverage_from_openfootball(openfootball_bytes([r for r in ROWS if r["season"] == s], CUT), LEAGUE, s,
                                         AT, TEAMS, parts.get((LEAGUE, s))) for s in ("2025/26", "2026/27")]


def _ctx(parts) -> E.EligibilityContext:
    return E.EligibilityContext(STORE, None, {LEAGUE: _coverages(parts)}, rights=synthetic_rights())


def _judge(ctx, as_of):
    return ctx.evaluate(league=LEAGUE, date=FIXTURE["date"], home=FIXTURE["home"], away=FIXTURE["away"],
                        as_of=as_of, markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]


def _verified(e) -> bool:
    kan = e.data_scope["kapsam_kanitlari"]
    return (e.freshness == E.VERIFIED_CURRENT and "KAYNAK_KAPSAMI_KISMI" not in e.reasons
            and all(k["gecmis_aralik_kaniti"] and k["bagimsiz_katilimci"] == 20 for k in kan))


def _blocked(e) -> bool:
    kan = e.data_scope["kapsam_kanitlari"]
    return (e.freshness == E.UNKNOWN and "KAYNAK_KAPSAMI_KISMI" in e.reasons
            and all(not k["gecmis_aralik_kaniti"] and k["bagimsiz_katilimci"] is None for k in kan))


def test_twenty_club_reference_maps_exactly_and_records_its_availability(tmp_path):
    parts, report = PL.load_participants(_reference(tmp_path, T_REF.isoformat()), set(STORE["home"]))
    assert set(parts) == {(LEAGUE, "2025/26"), (LEAGUE, "2026/27")}
    assert all(v == frozenset(TEAMS) and v.available_since == T_REF for v in parts.values())
    assert all(s["durum"] == "GECERLI" and s["eslesen"] == 20 for s in report["sezonlar"].values())
    assert report["erisilebilir_utc"] == T_REF.isoformat() and report["alinma_utc"] == T_REF.isoformat()


def test_reference_obtained_before_the_evaluation_is_coverage_evidence(tmp_path):
    parts, _ = PL.load_participants(_reference(tmp_path, T_REF.isoformat()), TEAMS)
    assert _verified(_judge(_ctx(parts), AFTER))


def test_same_instant_follows_the_source_file_rule(tmp_path):
    parts, _ = PL.load_participants(_reference(tmp_path, T_REF.isoformat()), TEAMS)
    assert _verified(_judge(_ctx(parts), T_REF))  # retrieved_at <= as_of ile aynı: aynı an kullanılabilir


def test_reference_obtained_after_the_evaluation_is_not_evidence(tmp_path):
    parts, _ = PL.load_participants(_reference(tmp_path, T_REF.isoformat()), TEAMS)
    e = _judge(_ctx(parts), BEFORE)
    assert _blocked(e) and not e.forecast_ok and not e.bet_ok


def test_file_date_cannot_make_the_reference_available_earlier(tmp_path):
    # Dosyadaki tarih kriptografik kanıt değildir: dosya sisteme değerlendirme anından SONRA geldiyse kanıt değildir
    p = _reference(tmp_path, (T_REF - dt.timedelta(days=30)).isoformat(), mtime=T_REF)
    parts, report = PL.load_participants(p, TEAMS)
    assert all(v.available_since == T_REF for v in parts.values()) and report["erisilebilir_utc"] == T_REF.isoformat()
    assert _blocked(_judge(_ctx(parts), BEFORE)) and _verified(_judge(_ctx(parts), T_REF))


@pytest.mark.parametrize("alinma", [None, "", "dün", "2026-10-20T09:00:00", "2026-10-20", 1760950800,
                                    "2026-13-40T09:00:00+00:00"])
def test_missing_malformed_or_naive_retrieval_time_is_rejected(tmp_path, alinma):
    with pytest.raises(PL.PilotError, match="alınma"):
        PL.load_participants(_reference(tmp_path, alinma), TEAMS)


def test_utc_offsets_are_compared_as_instants(tmp_path):
    utc_parts, _ = PL.load_participants(_reference(tmp_path, "2026-10-20T09:00:00Z", name="a.json"), TEAMS)
    ist_parts, _ = PL.load_participants(_reference(tmp_path, "2026-10-20T12:00:00+03:00", name="b.json"), TEAMS)
    assert {v.available_since for v in utc_parts.values()} == {v.available_since for v in ist_parts.values()} == {T_REF}
    for parts in (utc_parts, ist_parts):
        same = _judge(_ctx(parts), T_REF.astimezone(IST))
        assert _verified(same) and same.reasons == _judge(_ctx(parts), T_REF).reasons
        assert _blocked(_judge(_ctx(parts), BEFORE.astimezone(IST)))


def test_cached_result_is_not_reused_for_an_earlier_moment(tmp_path):
    parts, _ = PL.load_participants(_reference(tmp_path, T_REF.isoformat()), TEAMS)
    ctx = _ctx(parts)
    assert E.info_cutoff(AFTER) == E.info_cutoff(BEFORE) == CUT  # aynı bilgi kesimi günü
    assert _verified(_judge(ctx, AFTER))
    assert _blocked(_judge(ctx, BEFORE))  # sonraki anın önbellekteki "doğrulandı" sonucu kullanılmaz
    assert _verified(_judge(ctx, AFTER)) and len(ctx._cache) == 2


def test_store_derived_participants_are_unchanged():
    # Başka sağlayıcının depo satırlarından türetilen katılımcılar (zaman bilgisi yok) eski davranışla kalır
    parts = {k: v for k, v in E.season_participants(STORE).items()}
    assert all(not hasattr(v, "available_since") for v in parts.values())
    assert _verified(_judge(_ctx(parts), BEFORE))

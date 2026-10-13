"""S3-GATE-02: takım kimliği, kullanım kapsamı ve kaynak tamlığı.

YALNIZCA açıkça SENTETİK veri (uydurma takım adları, skorlar, tarihler; kaynak etiketi ``sentetik``), sentetik hak
kaydı ve geçici dizinler kullanılır. Gerçek veri deposuna, kullanıcı defterine veya ayarlarına dokunulmaz.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
import unicodedata

import pandas as pd
import pytest
from takvim_yardim import circle_rounds, openfootball_bytes, season_rows, store_frame
from uygunluk_yardim import UTC, register_synthetic_source, synthetic_rights

from bahis_tahmin import eligibility as E
from bahis_tahmin.data.teams import (
    ALIASES,
    BELIRSIZ,
    BULUNAMADI,
    KESIN,
    MATCHING_VERSION,
    match_team,
    norm_key,
    resolve_team,
    resolve_teams,
)
from bahis_tahmin.goals.engine import GoalEngine

TEAMS = [f"Takim {c}" for c in "ABCDEFGHIJKLMNOP"]  # 16 sentetik takım
AS_OF = dt.datetime(2026, 10, 14, 12, tzinfo=UTC)  # 2026/27'nin 10. turundan sonra
CUT = dt.date(2026, 10, 14)
AT = AS_OF - dt.timedelta(hours=1)


# =============================================================== 1) takım kimliği
@pytest.mark.parametrize("name, candidates", [
    ("Foo FC", ["Takim F"]),  # tek harfli parça önek kanıtı sayılıyordu → "Takim F"
    ("City", ["City FC", "City SC"]),  # normalleştirilmiş çakışma: son aday seçiliyordu → "City SC"
    ("City", ["City SC", "City FC"]),  # sıraya bağlı seçim → "City FC"
    ("City", ["City U21"]),  # yaş grubu farkı önekle geçiyordu → "City U21"
])
def test_reproduced_false_matches_no_longer_pick_a_team(name, candidates):
    assert match_team(name, candidates) is None
    r = resolve_team(name, candidates)
    assert not r.exact and r.team is None


def test_collisions_are_ambiguous_independent_of_order():
    a = resolve_team("City", ["City FC", "City SC"])
    b = resolve_team("City", ["City SC", "City FC"])
    assert a.status == b.status == BELIRSIZ and a.candidates == b.candidates == ("City FC", "City SC")
    # tam ad da bağlamda benzersiz değilse kimlik kanıtı değildir
    assert resolve_team("City", ["City", "City FC"]).status == BELIRSIZ
    # ters çakışma: aynı dosyadaki iki farklı ad aynı takıma düşüyorsa ikisi de belirsiz
    res = resolve_teams(["Foo FC", "Foo SC", "Bar"], ["Foo", "Bar"])
    assert res["Foo FC"].status == res["Foo SC"].status == BELIRSIZ and res["Bar"].team == "Bar"
    # aynı kanonik takımın doğrulanmış takma adları yanlış belirsizlik üretmez
    res = resolve_teams(["Athletic Club", "Athletic Bilbao", "Real Betis"], ["Ath Bilbao", "Betis"], "SP1")
    assert res["Athletic Club"].team == res["Athletic Bilbao"].team == "Ath Bilbao" and res["Real Betis"].exact


def test_empty_and_single_letter_names_are_never_identity_evidence():
    for name in ("", "   ", None, "FC", "F.C.", "A"):
        assert match_team(name, ["A FC", "Takim A", "FC"]) is None
    assert match_team("Takim", ["Takim F"]) is None  # önek
    assert resolve_team("Foo FC", ["Takim F"]).suggestions == ()  # tek harf öneri kanıtı da değil
    assert match_team("X", []) is None and match_team("X", None) is None


def test_fuzzy_and_prefix_only_suggest():
    r = resolve_team("Kingsbridge City FC", ["Kingsbridge", "Arsenal"])  # takma adı olmayan (uydurma) ad
    assert r.status == BULUNAMADI and r.team is None and r.suggestions[:1] == ("Kingsbridge",)
    r = resolve_team("Arsenall", ["Arsenal", "Chelsea"])
    assert r.team is None and r.suggestions[:1] == ("Arsenal",)


def test_unicode_turkish_and_accent_normalization():
    assert norm_key("Kasımpaşa") == norm_key("Kasimpasa") == "kasimpasa"  # noktasız ı düşmez
    assert match_team("Kasımpaşa", ["Kasimpasa", "Besiktas"]) == "Kasimpasa"
    assert match_team("BEŞİKTAŞ JK", ["Besiktas", "Kasimpasa"]) == "Besiktas"
    assert match_team("Fenerbahçe SK", ["Fenerbahce"]) == "Fenerbahce"
    assert match_team("Brøndby IF", ["Brondby"]) == "Brondby"
    nfd = unicodedata.normalize("NFD", "Göztepe")
    assert match_team(nfd, ["Goztep"]) == match_team("Göztepe", ["Goztep"]) == "Goztep"  # NFC/NFD aynı
    assert match_team("İstanbul Başakşehir", ["Buyuksehyr"]) == "Buyuksehyr"
    assert match_team("Real Madrid C.F.", ["Real Madrid", "Barcelona"]) == "Real Madrid"


@pytest.mark.parametrize("name, cand", [
    ("Galatasaray", "Galatasaray II"), ("Galatasaray II", "Galatasaray"), ("Barcelona", "Barcelona B"),
    ("City", "City U19"), ("City U19", "City U21"), ("City", "City Women"), ("City Ladies", "City"),
    ("Real Madrid", "Real Madrid Castilla"), ("Ajax", "Jong Ajax"),
])
def test_categories_are_kept_apart_and_not_even_suggested(name, cand):
    r = resolve_team(name, [cand])
    assert r.team is None and cand not in r.suggestions


def test_refounded_club_with_new_name_is_only_a_suggestion():
    r = resolve_team("Foo 2015", ["Foo"])  # yeniden kurulmuş kulüp: yeni adla kimlik kurulmaz
    assert r.team is None and r.status == BULUNAMADI and r.suggestions == ("Foo",)


def test_same_name_in_other_country_and_alias_scope():
    # "rangers" takma adı yalnızca İskoçya kapsamında; QPR takma adı yalnızca İngiltere kapsamında
    assert match_team("Queens Park Rangers FC", ["QPR"], league="E1") == "QPR"
    assert match_team("Queens Park Rangers FC", ["QPR"], league="SC0") is None
    assert match_team("Athletic Club", ["Ath Bilbao"], league="E0") is None
    assert match_team("Athletic Club", ["Ath Bilbao"], league="SP1") == "Ath Bilbao"
    # takma ad başka kaynağın adlarına uygulanmaz (kaynak kapsamı)
    assert resolve_team("Athletic Club", ["Ath Bilbao"], "SP1", source="baska-kaynak").team is None
    # takma adın hedefi bağlamda yoksa (ör. ligin son iki sezonunda değil) eşleşme yok
    assert match_team("Athletic Club", ["Betis"], league="SP1") is None
    # bütün doğrulanmış takma adlar korunuyor (S3-GATE-01'deki düz tablo aynı)
    assert ALIASES["nec"] == "Nijmegen" and ALIASES["sporting clube portugal"] == "Sp Lisbon" and len(ALIASES) >= 80


def test_matching_result_is_explicit():
    r = resolve_team("Manchester United FC", ["Man United", "Man City"], "E0")
    assert (r.status, r.team, r.basis) == (KESIN, "Man United", "takma_ad")
    assert r.evidence() == f"{MATCHING_VERSION}:KESIN:takma_ad"
    assert resolve_team("Arsenal FC", ["Arsenal"]).basis == "normal_ad"
    assert resolve_team("Arsenal", ["Arsenal"]).basis == "ayni_ad"


# =============================================================== 2) veri deposu: eşlenmeyen kaybolmaz
def test_store_keeps_unmatched_with_raw_names_and_provenance(tmp_home):
    from bahis_tahmin.data.sources import OPENFOOTBALL_BASE, DownloadError
    from bahis_tahmin.data.store import DataStore

    known = store_frame(season_rows(["Takim A", "Takim F", "City FC", "City SC"] + TEAMS[1:5] + TEAMS[6:10],
                                    dt.date(2025, 8, 10), "2025/26"))
    file = {"matches": [
        {"id": 101, "date": "2026-10-12", "time": "19:00", "team1": "Takim A FC", "team2": "Takim B"},  # kesin
        {"id": 102, "date": "2026-10-12", "time": "19:00", "team1": "Foo FC", "team2": "Takim C"},  # bulunamadı
        {"id": 103, "date": "2026-10-13", "time": "19:00", "team1": "City", "team2": "Takim D"},  # belirsiz
        {"id": 104, "date": "2026-10-13", "time": "20:00", "team1": "Takim E FC", "team2": "Takim E SC"},
    ]}

    class Fake:
        stats = {"network": 0, "cache": 0, "failed": 0}

        def host_down(self, url):
            return False

        def cache_path(self, rel):
            return tmp_home / "raw" / rel

        def get(self, url, cache_rel, max_age_hours=None, force=False):
            if url == f"{OPENFOOTBALL_BASE}/2026-27/tr.1.json":
                return json.dumps(file).encode()
            raise DownloadError(url, "yok (404)", 404)

    st = DataStore(tmp_home)
    rep = type("R", (), {"warnings": []})()
    fx = st._update_fixtures(Fake(), ["T1"], known, dt.date(2026, 10, 10), 10, rep, False, {"openfootball"})
    assert fx[["home", "away"]].values.tolist() == [["Takim A", "Takim B"]]
    row = fx.iloc[0]
    assert (row["raw_home"], row["raw_away"]) == ("Takim A FC", "Takim B")
    assert row["eslesme"] == f"{MATCHING_VERSION}:KESIN:normal_ad|{MATCHING_VERSION}:KESIN:ayni_ad"
    un = {r["provider_id"]: r for r in st._last_unmatched}
    assert set(un) == {"102", "103", "104"}  # hiçbiri düşmedi
    assert un["102"]["eslesme_durumu"] == "BULUNAMADI" and un["102"]["raw_home"] == "Foo FC"
    assert un["103"]["eslesme_durumu"] == BELIRSIZ and set(un["103"]["oneriler"]["ev"]) == {"City FC", "City SC"}
    assert un["104"]["eslesme_durumu"] in (BELIRSIZ, "AYNI_TAKIM")  # ev ve deplasman aynı takıma eşlenmez
    assert all(r["eslesme_surumu"] == MATCHING_VERSION for r in un.values())
    # kalıcılık ve eski kayıtların okunması (yeni alanlar yoksa boş)
    st.meta["eslesmeyen_fikstur"] = list(st._last_unmatched) + [
        {"league": "T1", "date": "2026-10-14", "time": "", "raw_home": "Eski", "raw_away": "Kayit",
         "source": "openfootball"}]
    st.fixtures = fx
    st.save()
    st2 = DataStore(tmp_home)
    assert st2.load()
    u = st2.unmatched_fixtures
    assert len(u) == 4 and u.loc[u["raw_home"] == "Eski", "eslesme_surumu"].isna().all()
    assert st2.fixtures.iloc[0]["raw_home"] == "Takim A FC"


# =============================================================== 3) takvim tamlığı (A ve B ayrı)
def _seasons(n_teams: int = 16, years=range(2020, 2027), teams=None, rounds_by_season=None) -> list[dict]:
    teams = teams or TEAMS[:n_teams]
    rows = []
    for k, y in enumerate(years):
        season = f"{y}/{(y + 1) % 100:02d}"
        rows += season_rows(teams, dt.date(y, 8, 9), season, seed=k,
                            rounds=(rounds_by_season or {}).get(season))
    return rows


ROWS = _seasons()
ALL = store_frame(ROWS)
STORE = ALL[ALL["date"] < pd.Timestamp(CUT)].reset_index(drop=True)
CUR = [r for r in ROWS if r["season"] == "2026/27"]
PREV = [r for r in ROWS if r["season"] == "2025/26"]
R11 = next(r for r in CUR if r["round"] == "Matchday 11")


@pytest.fixture(scope="module")
def eng():
    e = GoalEngine()
    e.train(STORE)
    return e


def cov(rows, season="2026/27", store=STORE, league="T1", known=None, participants="depo", name_map=None,
        played_before=CUT, at=AT):
    parts = E.season_participants(store).get((league, season)) if participants == "depo" else participants
    return E.coverage_from_openfootball(openfootball_bytes(rows, played_before, name_map), league, season, at,
                                        known if known is not None else TEAMS, parts)


def judge(covs, store=STORE, engine=None, fixture=R11, as_of=AS_OF, source="", rights=None):
    sv = E.state_view(engine) if engine is not None else None
    c = E.EligibilityContext(store, sv, {"T1": covs}, rights=rights or synthetic_rights())
    return c.evaluate(league="T1", date=fixture["date"], home=fixture["home"], away=fixture["away"], as_of=as_of,
                      markets=("FT_OVER_3_5",), prediction_codes=(), source=source)["FT_OVER_3_5"]


def test_valid_rounded_calendar_is_verified_end_to_end(eng):
    c_prev, c_cur = cov(PREV, "2025/26"), cov(CUR)
    assert c_prev.complete and c_cur.complete and c_cur.participants == 16
    e = judge([c_prev, c_cur], engine=eng)
    assert e.freshness == E.VERIFIED_CURRENT and e.forecast_ok and e.bet_ok, e.reasons
    kan = e.data_scope["kapsam_kanitlari"]
    assert all(k["tam"] and k["gecmis_aralik_kaniti"] and k["bagimsiz_katilimci"] == 16 for k in kan)


def test_source_team_count_is_not_independent_evidence():
    # v1 kuralı (takım sayısı dosyadan): 4 takımlık, kendi içinde kusursuz çift devre "tam" sayılırdı
    sub = [r for r in CUR if r["home"] in TEAMS[:4] and r["away"] in TEAMS[:4]]
    c = cov(sub)
    assert not c.complete and c.verified_windows == ()
    assert "bağımsız katılımcı listesiyle uyuşmuyor" in c.detail
    # bağımsız katılımcı listesi yoksa tam görünen dosya da kanıt değildir
    c = cov(CUR, participants=None)
    assert not c.complete and c.verified_windows == () and "bağımsız katılımcı listesi yok" in c.detail
    e = judge([cov(PREV, "2025/26"), c])
    assert e.freshness == E.UNKNOWN and "KAYNAK_ARALIK_DISI" in e.reasons and not e.forecast_ok


def test_team_completely_absent_from_source_is_detected():
    gone = TEAMS[15]
    c = cov([r for r in CUR if gone not in (r["home"], r["away"])])
    assert not c.complete and c.verified_windows == ()
    e = judge([cov(PREV, "2025/26"), c])
    assert e.freshness == E.UNKNOWN and not e.forecast_ok


def test_duplicates_cannot_replace_missing_rows():
    r5 = [i for i, r in enumerate(CUR) if r["round"] == "Matchday 5"]
    rows = [r for i, r in enumerate(CUR) if i != r5[0]] + [dict(CUR[r5[1]])]  # bir maç eksik, bir maç iki kez
    c = cov(rows)
    assert "1 yinelenen kayıt elendi" in c.detail and "doğrulanan ardışık tur: 4" in c.detail and not c.complete
    assert E.day_to_date(c.verified_windows[0][1]) < R11["date"].date()
    # bütün turlar + birebir tekrarlar: tekrar sayımı artırmaz, takvim yine tam
    c = cov(CUR + [dict(r) for r in CUR[:7]])
    assert c.complete and "7 yinelenen kayıt elendi" in c.detail
    # aynı anahtarlı farklı içerik (skor) birleştirilmez: çakışma turu doğrulanmamış yapar
    clash = dict(CUR[r5[1]], fthg=CUR[r5[1]]["fthg"] + 5)
    c = cov(CUR + [clash])
    assert not c.complete and "1 çakışan anahtar" in c.detail and "doğrulanan ardışık tur: 4" in c.detail
    # kaynak maç kimliği varsa tekilleştirme onunla yapılır
    with_id = [dict(r, id=i) for i, r in enumerate(CUR)]
    assert cov(with_id + [dict(with_id[3])]).complete


def test_regular_season_is_not_taken_as_including_playoffs():
    # Normal sezon 30 tur + numarasız play-off aşaması (8 takım): play-off tarihleri kanıtlanmış aralığa girmez
    po_start = dt.date(2027, 3, 14)
    playoff = []
    for k, (h, a) in enumerate([(TEAMS[i], TEAMS[i + 4]) for i in range(4)] * 2):
        playoff.append(dict(CUR[0], date=pd.Timestamp(po_start + dt.timedelta(days=7 * (k // 4))), home=h, away=a,
                            round=f"Championship Round {k // 4 + 1}"))
    c = cov(CUR + playoff, played_before=dt.date(2027, 3, 25))
    assert not c.complete and "doğrulanmamış tur veya aşama" in c.detail
    assert E.day_to_date(c.verified_windows[0][1]) < po_start
    store = store_frame(ROWS + playoff)  # depo play-off maçlarını da içeriyor (eksik maç yok)
    store = store[store["date"] < pd.Timestamp("2027-03-25")]
    fx = dict(playoff[4], date=pd.Timestamp("2027-03-28"))
    e = judge([cov(PREV, "2025/26", store=store), c], store=store, fixture=fx,
              as_of=dt.datetime(2027, 3, 25, 12, tzinfo=UTC))
    assert "KAYNAK_ARALIK_DISI" in e.reasons and e.freshness == E.UNKNOWN
    # split'li lig formatı (SC0: 12 takım, 33 tur): split turları listelenmeden takvim "tam sezon" değildir
    t12 = TEAMS[:12]
    three = circle_rounds(t12, legs=3)
    rows = season_rows(t12, dt.date(2026, 8, 2), "2026/27", league="SC0", rounds=three)
    st12 = store_frame(rows)
    c = cov(rows, store=st12[st12["date"] < pd.Timestamp(CUT)], league="SC0", known=t12)
    assert len(three) == 33 and not c.complete and "split/play-off" in c.detail and c.verified_windows


def test_past_seasons_are_not_forced_into_todays_format():
    # SC0 bugünkü formatı 12 takım × 33 tur; 10 takımlı eski bir sezona zorla uygulanmaz (A doğrulanamaz)
    t10 = TEAMS[:10]
    rows = season_rows(t10, dt.date(1999, 8, 1), "1999/00", league="SC0", rounds=circle_rounds(t10, legs=4))
    c = cov(rows, "1999/00", store=store_frame(rows), league="SC0", known=t10, played_before=None)
    assert not c.complete and "format" in c.detail
    assert c.verified_windows  # turlar katılımcıların tam eşleşmesi: geçmiş aralık (B) yine kanıtlanır


def test_per_team_counts_do_not_prove_home_away_distribution():
    rows = [dict(r) for r in CUR]
    i = next(k for k, r in enumerate(rows) if r["round"] == "Matchday 20")
    rows[i]["home"], rows[i]["away"] = rows[i]["away"], rows[i]["home"]  # takım başına sayı ve turlar aynı kalır
    c = cov(rows)
    assert not c.complete and "iç-dış saha" in c.detail and c.verified_windows


def test_history_window_is_separate_from_full_season_and_unpublished_fixtures(eng):
    # A yok (yalnızca 12/30 tur yayımlandı) ama gerekli geçmiş aralık (B) kanıtlı: reddedilmez
    published = [r for r in CUR if int(r["round"].split()[1]) <= 12]
    c = cov(published)
    assert not c.complete and "12/30" in c.detail and c.verified_windows
    e = judge([cov(PREV, "2025/26"), c], engine=eng)
    assert e.freshness == E.VERIFIED_CURRENT and e.forecast_ok, e.reasons
    # yalnızca 9 tur yayımlanmışsa (10. tur oynandı) aralık bilgi kesimine ulaşmaz: UNKNOWN
    c9 = cov([r for r in CUR if int(r["round"].split()[1]) <= 9])
    e = judge([cov(PREV, "2025/26"), c9], engine=eng)
    assert e.freshness == E.UNKNOWN and "KAYNAK_ARALIK_DISI" in e.reasons and not e.forecast_ok
    # önceki sezon takvimi yoksa 365 gün kapsanmaz (gereksinim kısaltılmaz)
    e = judge([cov(CUR)], engine=eng)
    assert "KAYNAK_ARALIK_DISI" in e.reasons and not e.forecast_ok


def test_season_break_bridge_and_preseason(eng):
    summer = dt.datetime(2026, 7, 20, 12, tzinfo=UTC)
    store = ALL[ALL["date"] < pd.Timestamp("2026-07-20")].reset_index(drop=True)
    e_summer = GoalEngine()
    e_summer.train(store)
    nxt = cov(CUR, store=store, played_before=dt.date(2026, 7, 20), at=summer - dt.timedelta(hours=1))
    assert nxt.verified_windows == ()  # yeni sezonun bağımsız katılımcısı henüz depoda yok
    first = next(r for r in CUR if r["round"] == "Matchday 1")
    prev = cov(PREV, "2025/26", store=store, at=summer - dt.timedelta(hours=1))
    prev2 = cov([r for r in ROWS if r["season"] == "2024/25"], "2024/25", store=store,
                at=summer - dt.timedelta(hours=1))
    e = judge([prev2, prev, nxt], store=store, engine=e_summer, fixture=first, as_of=summer)
    assert e.freshness == E.VERIFIED_CURRENT and e.forecast_ok, e.reasons  # sezon başlamadı: ara kapsanır
    # arada depoda maç varsa (ör. kaynakta olmayan aşama) ara kapsanmaz
    stray = store_frame([dict(PREV[0], date=pd.Timestamp("2026-05-10"), round="Play-off Final")])
    store2 = pd.concat([store, stray], ignore_index=True)
    e = judge([prev2, prev, nxt], store=store2, fixture=first, as_of=summer)
    assert "KAYNAK_ARALIK_DISI" in e.reasons and e.freshness == E.UNKNOWN


def test_bridge_requires_verified_season_end_and_empty_gap():
    """Sezonlar arası köprü yalnızca önceki sezonun listelenen takvimi sonuna kadar doğrulanmışsa ve arada (bilgi
    kesiminden önce) ne depoda ne kaynakta maç yoksa kurulur; aksi halde ara (ör. play-off dönemi) kapsanmaz."""
    playoff = [dict(PREV[0], date=pd.Timestamp(dt.date(2026, 3, 8) + dt.timedelta(days=7 * (k // 4))),
                    home=TEAMS[k % 4], away=TEAMS[k % 4 + 4], round=f"Championship Round {k // 4 + 1}")
               for k in range(8)]
    store = pd.concat([STORE, store_frame(playoff)], ignore_index=True)
    prev = cov(PREV + playoff, "2025/26", store=store)
    assert not prev.complete and not prev.season_end_verified and prev.verified_windows
    e = judge([prev, cov(CUR, store=store)], store=store)
    assert "KAYNAK_ARALIK_DISI" in e.reasons and e.freshness == E.UNKNOWN  # play-off dönemi kanıtsız
    # önceki sezon sonu doğrulanmış ama arada depoda (kaynakta olmayan) maç var: köprü yok
    e = judge([cov(PREV, "2025/26", store=store), cov(CUR, store=store)], store=store)
    assert "KAYNAK_ARALIK_DISI" in e.reasons and e.freshness == E.UNKNOWN
    # kontrol: ara boş ve önceki sezon sonu doğrulanmış → kapsanır
    e = judge([cov(PREV, "2025/26"), cov(CUR)])
    assert "KAYNAK_ARALIK_DISI" not in e.reasons and e.freshness == E.VERIFIED_CURRENT


def test_store_match_missing_from_verified_source_is_a_conflict():
    extra = store_frame([dict(CUR[0], date=pd.Timestamp("2026-09-01"), home=R11["home"], away=R11["away"],
                              round=None)])
    store = pd.concat([STORE, extra], ignore_index=True)
    e = judge([cov(PREV, "2025/26", store=store), cov(CUR, store=store)], store=store)
    assert "KAYNAK_DEPO_CELISKISI" in e.reasons and e.freshness == E.UNKNOWN and not e.forecast_ok


def test_partial_calendar_still_reports_known_missing_without_completeness_claim():
    drop = STORE[(STORE["home"] == R11["home"]) & (STORE["season"] == "2026/27")].index[-1]
    store = STORE.drop(index=drop)
    c = cov(CUR, store=store, participants=None)  # tamlık kanıtı yok
    e = judge([c], store=store)
    assert "DEPODA_EKSIK_MAC" in e.reasons and e.freshness == E.KNOWN_STALE and "kontrol" not in e.data_scope


# =============================================================== 4) eşleme güveni uygunluğa bağlı
def test_mapped_fixture_identity_is_rebuilt_from_the_source_calendar(eng):
    nm = {t: f"{t} FC" for t in TEAMS}  # kaynak adları farklı, kesin kimlikle eşleşir
    c_prev, c_cur = cov(PREV, "2025/26", name_map=nm), cov(CUR, name_map=nm)
    e = judge([c_prev, c_cur], engine=eng, source="openfootball")
    assert e.team_mapping == "ESLESTI" and e.forecast_ok, e.reasons
    assert e.data_scope["eslesme"]["kaynak_takviminde_yeniden_kuruldu"] is True
    # eski eşleyicinin ürettiği kayıt: "Foo FC" -> R11 ev sahibi (yanlış takım) — yeni eşleyici yeniden kuramaz
    nm2 = dict(nm, **{R11["home"]: "Foo FC"})
    e = judge([cov(PREV, "2025/26", name_map=nm), cov(CUR, name_map=nm2)], engine=eng, source="openfootball")
    assert "TAKIM_ESLESMESI_DOGRULANAMADI" in e.reasons and e.team_mapping == "DOGRULANAMADI"
    assert e.freshness != E.VERIFIED_CURRENT and not e.forecast_ok and not e.bet_ok
    # kaynak dosyası hiç yoksa da eşleme doğrulanmış sayılmaz
    e = judge([], engine=eng, source="openfootball")
    assert "TAKIM_ESLESMESI_DOGRULANAMADI" in e.reasons and not e.forecast_ok


def test_home_and_away_never_map_to_the_same_team(eng):
    e = judge([cov(PREV, "2025/26"), cov(CUR)], engine=eng, fixture=dict(R11, away=R11["home"]))
    assert "TAKIM_ESLESMESI_DOGRULANAMADI" in e.reasons and not e.forecast_ok
    rows = [dict(r) for r in CUR]
    c = cov(rows, name_map={R11["home"]: "Takim X FC", R11["away"]: "Takim X SC"}, known=TEAMS + ["Takim X"])
    assert {"Takim X FC", "Takim X SC"} <= set(c.unmapped_names) and not c.complete


def test_unmatched_fixture_keeps_candidate_id_and_never_becomes_canonical(eng):
    from bahis_tahmin.goals.service import gated_goal_predictions

    ctx = E.EligibilityContext(STORE, E.state_view(eng), {"T1": [cov(PREV, "2025/26"), cov(CUR)]},
                               rights=synthetic_rights())
    un = pd.DataFrame([{"league": "T1", "date": R11["date"], "time": "", "raw_home": "Foo FC",
                        "raw_away": R11["away"], "source": "openfootball"}])
    v = gated_goal_predictions(eng, ctx, pd.DataFrame(), AS_OF, unmatched=un)[0]
    assert v.prediction is None and not v.canonical_id and v.candidate_id.startswith("aday:")
    assert all(e.lead_code == "TAKIM_ESLESMEDI" and not e.forecast_ok for e in v.by_market.values())


def test_matching_version_is_part_of_cache_key_and_fingerprint(monkeypatch):
    c = E.EligibilityContext(STORE, None, {"T1": [cov(CUR)]}, rights=synthetic_rights())
    kw = dict(league="T1", date=R11["date"], home=R11["home"], away=R11["away"], as_of=AS_OF,
              markets=("FT_OVER_3_5",), prediction_codes=())
    c.evaluate(**kw)
    assert len(c._cache) == 1 and next(iter(c._cache))[1] == MATCHING_VERSION
    assert cov(CUR).matching_version == "takim-eslesme-v2"
    monkeypatch.setattr(E, "MATCHING_VERSION", "takim-eslesme-test")
    c.evaluate(**kw)
    assert len(c._cache) == 2  # eşleme sürümü değişince önceki sonuç kullanılmaz
    c2 = E.EligibilityContext(STORE, None, {"T1": [cov(CUR)]}, rights=synthetic_rights())
    assert c2.fingerprint != c.fingerprint


# =============================================================== 5) kullanım kapsamı (yerel analiz istisnası yok)
def test_documented_scope_allows_and_unneeded_rights_do_not_block(eng):
    r = synthetic_rights()
    u = r.by_label["sentetik"]
    assert u.yeniden_dagitim == "IZIN_VARSAYILMAZ" and u.ticari_kullanim == "IZIN_VARSAYILMAZ"
    e = judge([cov(PREV, "2025/26"), cov(CUR)], engine=eng, rights=r)
    assert e.forecast_ok and e.bet_ok  # yeniden dağıtım / ticari hak yerel tahmin ve bahis için gerekmez


@pytest.mark.parametrize("field, code", [
    ("result_use", "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI"),
    ("model_training", "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI"),
    ("model_use", "KAYNAK_MODEL_KULLANIMI_DOGRULANAMADI"),
])
def test_each_unverified_scope_blocks_forecast_and_bet(eng, field, code):
    e = judge([cov(PREV, "2025/26"), cov(CUR)], engine=eng, rights=synthetic_rights(**{field: "DOGRULANAMADI"}))
    assert code in e.reasons and not e.forecast_ok and not e.bet_ok and e.lead_code == code
    assert e.freshness == E.VERIFIED_CURRENT  # veri güncel; engel yalnızca kullanım kapsamı


def test_consent_alone_never_grants_scope_and_no_label_spoofing():
    consent = {k: "2026-10-10T10:00:00" for k in ("football-data", "github-mirror", "openfootball", "x")}
    for label in ("football-data.co.uk", "github-yedek"):
        r = E.rights_from_registry({label}, consent)
        assert r.by_label[label].erisim == "ONAY_VAR"
        codes = r.codes({label}, {label}, "tahmin")
        assert {"KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI", "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI",
                "KAYNAK_MODEL_KULLANIMI_DOGRULANAMADI"} <= set(codes)
    # yalnızca fikstür sağlayan CC0 kaynağın etiketiyle sonuç verisi hak kazanamaz
    spoof = E.rights_from_registry({"openfootball"}, consent)
    assert spoof.codes({"openfootball"}, {"openfootball"}, "tahmin") == ["KAYNAK_ETIKETI_UYUMSUZ"]
    for fake in ("Football-Data.co.uk", "football-data.co.uk ", "sentetik", "openfootball-results"):
        assert E.rights_from_registry({fake}, consent).codes({fake}, set()) == ["KAYNAK_HAKKI_BILINMIYOR"]
    # S4-PILOT-01: "openfootball-sonuc" artık kayıtlı sonuç adaptörü etiketidir, ancak etiket tek başına hak vermez:
    # kökeni doğrulanmamış satır engelli kalır (etiket değiştirerek hak atlatma negatif kontrolü korunur)
    lb = "openfootball-sonuc"
    assert E.rights_from_registry({lb}, consent).codes({lb}, {lb}, "tahmin") == ["KAYNAK_KOKENI_DOGRULANAMADI"]
    assert E.rights_from_registry({lb}, consent, set()).codes({lb}, set()) == ["KAYNAK_KOKENI_DOGRULANAMADI"]
    assert E.rights_from_registry({lb}, consent, {lb}).codes({lb}, {lb}, "tahmin") == []
    # GitHub yedeğinin depo lisansı asıl kaynağın haklarını kanıtlamaz; belgeye erişilemeyen kaynak izinli değil
    from bahis_tahmin.data.source_registry import USE_RIGHTS

    for key in ("football-data", "github-mirror"):
        assert not any(v == "IZINLI_BELGELI" for v in USE_RIGHTS[key].values()) and USE_RIGHTS[key]["belge"] == ""


def test_model_without_training_provenance_is_blocked(eng):
    sv = dataclasses.replace(E.state_view(eng), train_sources=None)
    c = E.EligibilityContext(STORE, sv, {"T1": [cov(PREV, "2025/26"), cov(CUR)]}, rights=synthetic_rights())
    e = c.evaluate(league="T1", date=R11["date"], home=R11["home"], away=R11["away"], as_of=AS_OF,
                   markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert "MODEL_EGITIM_KOKENI_YOK" in e.reasons and not e.forecast_ok


def test_forecast_records_under_unverified_scope_are_reasoned_and_probability_free(eng):
    from bahis_tahmin.goals import forecast_log as F

    real = STORE.assign(source="football-data.co.uk")
    rights = E.rights_from_registry({"football-data.co.uk"}, {"football-data": "x"})
    sv = dataclasses.replace(E.state_view(eng), train_sources=("football-data.co.uk",))
    ctx = E.EligibilityContext(real, sv, {"T1": [cov(PREV, "2025/26"), cov(CUR)]}, rights=rights)
    fx = pd.DataFrame([{"league": "T1", "date": R11["date"], "time": "", "home": R11["home"], "away": R11["away"],
                        "source": "manuel"}])
    recs = F.build_forecast_records(eng, fx, real, now=AS_OF, ctx=ctx)
    assert len(recs) == 3 and all(r["p"] is None and r["decision_status"] == F.STATUS_NO_FORECAST for r in recs)
    assert all(r["reasons"][0] == "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI" and r["stake_units"] == 0.0 for r in recs)
    assert all(r["protokol"] == F.PROTOCOL_V3_VERSION for r in recs)
    ok = F.build_forecast_records(eng, fx, STORE, now=AS_OF, ctx=E.EligibilityContext(
        STORE, E.state_view(eng), {"T1": [cov(PREV, "2025/26"), cov(CUR)]}, rights=synthetic_rights()))
    assert all(r["p"] is not None for r in ok)  # geçerli senaryo çalışmaya devam ediyor


def test_training_on_real_data_requires_documented_training_scope(tmp_home, capsys, monkeypatch):
    from bahis_tahmin import cli
    from bahis_tahmin.config import Settings
    from bahis_tahmin.data.store import DataStore

    real = STORE.assign(source="football-data.co.uk")
    consent = {"football-data": "2026-10-10T10:00:00"}
    assert set(E.training_rights_codes(real, consent)) == {"KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI",
                                                          "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI"}
    assert E.training_rights_codes(STORE.assign(source="openfootball"), consent) == ["KAYNAK_ETIKETI_UYUMSUZ"]
    assert "KAYNAK_HAKKI_BILINMIYOR" in E.training_rights_codes(STORE.assign(source=None), consent)
    s = Settings.load()
    s.source_consent.update(consent)
    s.save()
    st = DataStore(tmp_home)
    st.matches = real
    st.save()
    for cmd in ("train", "gol-egit"):
        assert cli.main([cmd]) == 3
        assert "kullanım kapsamı doğrulanmadı" in capsys.readouterr().err
    assert not list(tmp_home.glob("*.joblib"))  # model dosyası yazılmadı
    for cmd in ("train", "gol-egit"):  # eğitim komutlarında kapsamı aşan bayrak yok
        with pytest.raises(SystemExit):
            cli.main([cmd, "--help"])
        assert not re.search(r"--(force|zorla|uygunluk|atla|skip|izin)", capsys.readouterr().out), cmd
    # izin verme durumu: kapsamı belgeli (yalnızca testte kayıtlı, açıkça sentetik) kaynakla eğitim yapılır
    register_synthetic_source(monkeypatch)
    assert E.training_rights_codes(STORE, {}) == []
    st.matches = STORE
    st.save()
    assert cli.main(["gol-egit"]) == 0 and (tmp_home / "goal_engine.joblib").exists()


def test_ui_training_paths_refuse_unverified_scope(tmp_home):
    qw = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    qw.QApplication.instance() or qw.QApplication([])
    from bahis_tahmin.ui.controller import AppController

    ctl = AppController()
    ctl.store.matches = STORE.assign(source="football-data.co.uk")
    ctl.settings.source_consent["football-data"] = "2026-10-10T10:00:00"
    msgs = []
    ctl.message.connect(lambda kind, text: msgs.append((kind, text)))
    assert ctl.retrain() is False and ctl.train_goal_engine() is False
    assert len(msgs) == 2 and all(k == "warn" and "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI" in t for k, t in msgs)


# =============================================================== 6) sürümler ve eski kayıtlar
def test_policy_v1_results_are_not_accepted_for_decisions():
    from uygunluk_yardim import verified

    e = verified("T1|2026-10-18|A|B", "FT_OVER_3_5", AS_OF)
    assert E.check_for_decision(e, e.candidate_id, "FT_OVER_3_5", AS_OF) == []
    old = dataclasses.replace(e, policy_version="veri-uygunluk-v1")
    assert E.check_for_decision(old, e.candidate_id, "FT_OVER_3_5", AS_OF) == ["BAGLAM_UYUSMUYOR"]
    assert E.POLICY_VERSION == "veri-uygunluk-v2"


# =============================================================== 7) bağımsız inceleme bulguları için ek testler
def test_missing_earlier_seasons_cannot_shorten_the_window():
    """Pencerenin başı depodaki ilk maçtan alınmaz: önceki sezonları eksik depo + yalnızca bu sezonun takvimi,
    tam depodan daha "uygun" görünmemeli (inceleme M1)."""
    only_cur = STORE[STORE["season"] == "2026/27"].reset_index(drop=True)
    e = judge([cov(CUR, store=only_cur)], store=only_cur)
    assert "KAYNAK_ARALIK_DISI" in e.reasons and e.freshness == E.UNKNOWN and not e.forecast_ok
    full = judge([cov(PREV, "2025/26"), cov(CUR)])
    assert full.freshness == E.VERIFIED_CURRENT  # kanıtlı tam pencere


def test_unlabeled_rows_and_empty_training_provenance_fail_closed(eng, monkeypatch):
    """Kaynak etiketi olmayan satırların hakkı bilinemez; boş eğitim kökeni "bilinen köken" değildir (inceleme M2)."""
    register_synthetic_source(monkeypatch)  # "sentetik" etiketi belgeli: engel yalnızca etiketsiz satırlardan gelir
    covs = {"T1": [cov(PREV, "2025/26"), cov(CUR)]}
    kw = dict(league="T1", date=R11["date"], home=R11["home"], away=R11["away"], as_of=AS_OF,
              markets=("FT_OVER_3_5",), prediction_codes=())
    ok = E.EligibilityContext(STORE, E.state_view(eng), covs, consent={}).evaluate(**kw)["FT_OVER_3_5"]
    assert ok.forecast_ok, ok.reasons  # kontrol: hepsi etiketli
    half = STORE.copy()
    half.loc[half.index[::2], "source"] = None
    e = E.EligibilityContext(half, E.state_view(eng), covs, consent={}).evaluate(**kw)["FT_OVER_3_5"]
    assert "KAYNAK_HAKKI_BILINMIYOR" in e.reasons and not e.forecast_ok
    sv = dataclasses.replace(E.state_view(eng), train_sources=())
    e = E.EligibilityContext(STORE, sv, covs, rights=synthetic_rights()).evaluate(
        league="T1", date=R11["date"], home=R11["home"], away=R11["away"], as_of=AS_OF, markets=("FT_OVER_3_5",),
        prediction_codes=())["FT_OVER_3_5"]
    assert "MODEL_EGITIM_KOKENI_YOK" in e.reasons and not e.forecast_ok
    g = GoalEngine()
    g.train(half)
    assert "etiketsiz" in g.manifest["sources"]  # eğitim kökeni etiketsiz satırı açıkça kaydeder
    assert "KAYNAK_HAKKI_BILINMIYOR" in E.training_rights_codes(half, {})


def test_sequence_research_is_behind_the_training_gate(tmp_home, capsys, monkeypatch):
    from bahis_tahmin import cli
    from bahis_tahmin.data.store import DataStore
    from bahis_tahmin.sequences import research

    def boom(*a, **k):
        raise AssertionError("S0 gerçek veriyle eğitilmemeliydi")

    monkeypatch.setattr(research, "load_or_build_s0", boom)
    st = DataStore(tmp_home)
    st.matches = STORE.assign(source="football-data.co.uk")
    st.save()
    assert cli.main(["dizi-arastir"]) == 3  # inceleme M3
    assert "kullanım kapsamı doğrulanmadı" in capsys.readouterr().err


def test_preseason_uses_cached_calendars_of_three_seasons(tmp_home, monkeypatch):
    """Sezon arasında 365 günlük pencere üç sezona dokunur; uygulama önbellekteki üç sezon dosyasını okur
    (indirme yok). İki sezon dosyasıyla pencere kanıtlanamaz."""
    import os

    from bahis_tahmin.data.store import DataStore

    register_synthetic_source(monkeypatch)
    summer = dt.datetime(2026, 7, 20, 12, tzinfo=UTC)
    st = DataStore(tmp_home)
    st.matches = ALL[ALL["date"] < pd.Timestamp("2026-07-20")].reset_index(drop=True)
    e_summer = GoalEngine()
    e_summer.train(st.matches)
    mtime = (summer - dt.timedelta(hours=2)).timestamp()
    seasons = {"2024-25": "2024/25", "2025-26": "2025/26", "2026-27": "2026/27"}
    for folder, label in seasons.items():
        path = tmp_home / "raw" / "openfootball" / folder / "tr.1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [r for r in ROWS if r["season"] == label]
        path.write_bytes(openfootball_bytes(rows, dt.date(2026, 7, 20)))
        os.utime(path, (mtime, mtime))
    first = next(r for r in CUR if r["round"] == "Matchday 1")
    kw = dict(league="T1", date=first["date"], home=first["home"], away=first["away"], as_of=summer,
              markets=("FT_OVER_3_5",), prediction_codes=())
    ctx = E.build_context(st, e_summer, {}, today=dt.date(2026, 7, 20))
    assert sorted(c.season for c in ctx.coverages["T1"]) == ["2024/25", "2025/26", "2026/27"]
    e = ctx.evaluate(**kw)["FT_OVER_3_5"]
    assert e.freshness == E.VERIFIED_CURRENT and e.forecast_ok, e.reasons
    (tmp_home / "raw" / "openfootball" / "2024-25" / "tr.1.json").unlink()
    e = E.build_context(st, e_summer, {}, today=dt.date(2026, 7, 20)).evaluate(**kw)["FT_OVER_3_5"]
    assert "KAYNAK_ARALIK_DISI" in e.reasons and not e.forecast_ok


def test_post_stage_leagues_never_claim_season_end():
    """Split/play-off'lu liglerde listelenen takvim sezon sonunu kanıtlamaz (inceleme bulgusu: 33 tur + bir split
    turu "tam sezon" sayılıyordu); B1 gibi play-off'lu ligde yalnızca normal sezon dosyası da tam sezon değildir."""
    t12 = TEAMS[:12]
    rounds = circle_rounds(t12, legs=3)
    split = [[(t12[i], t12[i + 1]) for i in range(0, 12, 2)]]
    rows = season_rows(t12, dt.date(2025, 8, 2), "2025/26", league="SC0", rounds=rounds + split)
    st = store_frame(rows)
    c = cov(rows, "2025/26", store=st, league="SC0", known=t12, played_before=None)
    assert not c.complete and not c.season_end_verified and "split/play-off" in c.detail
    assert E.day_to_date(c.verified_windows[0][1]) == dt.date(2026, 3, 21)  # 34 tur (split turu dahil) B'de
    rows = season_rows(TEAMS, dt.date(2025, 8, 9), "2025/26", league="B1")
    c = cov(rows, "2025/26", store=store_frame(rows), league="B1", played_before=None)
    assert not c.complete and c.verified_windows and "split/play-off" in c.detail
    rows = season_rows(TEAMS, dt.date(2025, 8, 9), "2025/26", league="E1")
    assert cov(rows, "2025/26", store=store_frame(rows), league="E1", played_before=None).complete  # kontrol


def test_match_result_path_also_rebuilds_cross_source_identity():
    """1X2 yolu (gate_match_prediction / gated_match_predictions) da openfootball kimliğini yeniden kurar."""
    nm = {t: f"{t} FC" for t in TEAMS}
    ctx = E.EligibilityContext(STORE, None, {"T1": [cov(PREV, "2025/26", name_map=nm),
                                                    cov(CUR, name_map=dict(nm, **{R11["home"]: "Foo FC"}))]},
                               rights=synthetic_rights())
    fx = pd.DataFrame([{"league": "T1", "date": R11["date"], "time": "", "home": R11["home"], "away": R11["away"],
                        "source": "openfootball"}])
    _, missing = E.gated_match_predictions(None, ctx, fx, AS_OF)
    assert "TAKIM_ESLESMESI_DOGRULANAMADI" in missing[0].first().reasons
    pred = type("P", (), {"league": "T1", "date": R11["date"], "home": R11["home"], "away": R11["away"],
                          "p_final": [0.4, 0.3, 0.3], "source": "openfootball",
                          "event_id": f"T1|{R11['date'].date()}|{R11['home']}|{R11['away']}"})()
    e = E.gate_match_prediction(ctx, pred, AS_OF)
    assert "TAKIM_ESLESMESI_DOGRULANAMADI" in e.reasons and not e.forecast_ok and not e.bet_ok


def test_update_flow_does_not_auto_train_without_documented_scope(tmp_home, monkeypatch):
    qw = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    qw.QApplication.instance() or qw.QApplication([])
    from bahis_tahmin.data.store import DataStore, UpdateReport
    from bahis_tahmin.models.engine import PredictionEngine
    from bahis_tahmin import core
    from bahis_tahmin.ui import controller as C

    def fake_update(self, *a, **k):
        self.matches = STORE.assign(source="football-data.co.uk")
        return UpdateReport()

    def no_train(*a, **k):
        raise AssertionError("eğitim yapılmamalıydı")

    monkeypatch.setattr(DataStore, "update", fake_update)
    monkeypatch.setattr(PredictionEngine, "train", no_train)
    monkeypatch.setattr(C, "_train_goal", no_train)
    monkeypatch.setattr(core, "train_goal", no_train)  # eğitim ortak çekirdekte (bahis_tahmin.core)
    ctl = C.AppController()
    ctl.settings.source_consent["football-data"] = "2026-10-10T10:00:00"
    from bahis_tahmin.data.source_registry import CONSENT_SCHEMA

    ctl.settings.onay_surumu = CONSENT_SCHEMA  # VERI-01: onay penceresi kaydedildi, kişisel kullanım beyanı verilmedi
    results = []
    monkeypatch.setattr(ctl, "_run", lambda work, done, msg: results.append(work(lambda p, m: None)) or True)
    assert ctl.update_and_train()
    store, engine, report, (goal, gerr) = results[0]
    assert engine is None and goal is None and gerr is None
    assert any("Model eğitimi yapılmadı" in w and "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI" in w for w in report.warnings)


def test_malformed_calendar_entries_do_not_crash():
    bad = json.dumps({"matches": [
        {"date": ["2026-08-09"], "team1": "Takim A", "team2": "Takim B"},
        {"date": "2026-08-09", "team1": {"code": "x"}, "team2": "Takim B"},
        {"date": "2026-08-09", "team1": "Takim A", "team2": "Takim B", "round": 7},
        {"date": "yok", "team1": "Takim A", "team2": "Takim B"}, "metin", None]}).encode()
    c = E.coverage_from_openfootball(bad, "T1", "2026/27", AT, TEAMS, TEAMS)
    assert not c.complete and c.verified_windows == () and len(c.matches) == 1
    assert E.coverage_from_openfootball(b'{"matches": {"a": 1}}', "T1", "2026/27", AT, TEAMS).matches == ()

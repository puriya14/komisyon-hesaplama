"""KAYNAK-06: bütün ligler için ESPN. Önceki sezonun lig dışı aşamaları (play-off) takvime girmez; veri deposu güncel
sezona ulaşmıyorsa istekler deponun son döneminden başlar ve lige sonradan katılan takım ESPN adıyla eklenir; adları
yeterince eşlenmeyen veya ESPN'de bulunmayan lig için ESPN kullanılmaz.

Yalnızca SENTETİK veri ve sahte indirici (ağ yok)."""

from __future__ import annotations

import datetime as dt
import io
import json

import pandas as pd
import test_kaynak_04 as K4
from test_kaynak_04 import EspnFake, _event

from bahis_tahmin import eligibility as E
from bahis_tahmin.data.espn import ESPN_BASE, ESPN_LABEL, ESPN_LEAGUES, MAX_FAILS, UNVERIFIED
from bahis_tahmin.data.leagues import LEAGUES
from bahis_tahmin.data.source_registry import allowed_sources
from bahis_tahmin.data.sources import MIRROR_URL, DownloadError
from bahis_tahmin.data.store import DataStore

TODAY = dt.date(2026, 10, 12)
CONSENT = {"github-mirror": "t", "espn": "t"}
ALLOWED = allowed_sources(CONSENT)
PAIRS = [(0, 1, 2, 3), (0, 2, 1, 3), (0, 3, 1, 2)]


def _round(teams, k: int):
    a, b, c, d = PAIRS[k % 3]
    return [(teams[a], teams[b]), (teams[c], teams[d])] if k % 2 == 0 else [(teams[b], teams[a]),
                                                                           (teams[d], teams[c])]


def _schedule(parts):
    """parts: (sezon, ilk tur tarihi, tur sayısı, 4 takım). Döner: (sıra, sezon, tarih, ev, deplasman)."""
    out = []
    for season, start, n, teams in parts:
        for k in range(n):
            d = pd.Timestamp(start) + pd.Timedelta(days=7 * k)
            out += [(season, d, h, a) for h, a in _round(teams, k)]
    return [(i, *x) for i, x in enumerate(out)]


def _score(i: int):
    ft = ((i * 7) % 5, (i * 3) % 4)
    return ft, (min(ft[0], i % 2), min(ft[1], (i // 2) % 2))


def _mirror(division, sched, until) -> bytes:
    rows = []
    for i, _, d, h, a in sched:
        if d > pd.Timestamp(until):
            continue
        (fh, fa), (hh, ha) = _score(i)
        rows.append({"Division": division, "MatchDate": d.strftime("%Y-%m-%d"), "MatchTime": "18:30:00",
                     "HomeTeam": h, "AwayTeam": a, "FTHome": fh, "FTAway": fa, "HTHome": hh, "HTAway": ha,
                     "OddHome": 2.0, "OddDraw": 3.2, "OddAway": 3.5})
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode()


def _espn(sched, names, played_until="2026-10-04"):
    out = []
    for i, _, d, h, a in sched:
        hn, an = names.get(h, h), names.get(a, a)
        if d <= pd.Timestamp(played_until):
            ft, ht = _score(i)
            out.append((d, _event(i, d, hn, an, ft, ht)))
        else:
            out.append((d, _event(i, d, hn, an)))
    return out


def _update(home, league, dl, allowed=ALLOWED, progress=None):
    st = DataStore(home)
    st.load()
    rep = st.update([league], 2, today=TODAY, downloader=dl, allowed=allowed, progress=progress)
    return st, rep


def _verdict(st, fx, league):
    ctx = E.build_context(st, None, CONSENT, today=TODAY, declarations=CONSENT, mode="standart")
    as_of = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=1)
    return ctx.evaluate(league=league, date=fx["date"], home=fx["home"], away=fx["away"], as_of=as_of,
                        markets=("1X2",), source=ESPN_LABEL, prediction_codes=())["1X2"]


def test_every_league_has_an_espn_code():
    assert set(ESPN_LEAGUES) == set(LEAGUES)
    assert len(set(ESPN_LEAGUES.values())) == len(ESPN_LEAGUES)  # iki lig aynı ESPN koduna düşmez
    assert UNVERIFIED <= set(ESPN_LEAGUES) and UNVERIFIED == {"FIN", "POL", "ROU", "SWZ"}
    assert ESPN_LEAGUES["E0"] == "eng.1" and ESPN_LEAGUES["SWZ"] == "sui.1" and ESPN_LEAGUES["USA"] == "usa.1"


# ============================================================ üst lig: önceki sezonun play-off'ları

E1_FD = ["Leeds", "Sunderland", "Burnley", "Luton"]
E1_ES = {"Leeds": "Leeds United", "Luton": "Luton Town"}
# Normal sezon 28 Şubat'ta biter (football-data play-off tutmaz); ESPN'de ardından 4 play-off maçı var
E1_SCHED = _schedule([("2025/26", "2025-08-09", 30, E1_FD), ("2026/27", "2026-08-08", 12, E1_FD)])
E1_PLAYOFF = [(dt.date(2026, 3, 7), "Leeds", "Luton", (1, 0)), (dt.date(2026, 3, 10), "Luton", "Leeds", (2, 2)),
              (dt.date(2026, 3, 8), "Sunderland", "Burnley", (0, 0)), (dt.date(2026, 3, 11), "Burnley", "Sunderland",
                                                                        (1, 3))]


def _e1_events():
    out = _espn(E1_SCHED, E1_ES)
    for k, (d, h, a, ft) in enumerate(E1_PLAYOFF):
        out.append((pd.Timestamp(d), _event(800 + k, d, E1_ES.get(h, h), E1_ES.get(a, a), ft, (0, 0))))
    return out


def test_top_league_uses_espn_and_previous_season_playoffs_stay_out_of_calendar(tmp_home):
    old = tmp_home / "raw" / "espn" / "2023-24" / "E1.json"  # geçmiş bir güncellemeden kalan sezon takvimi
    old.parent.mkdir(parents=True)
    old.write_text("{}")
    msgs = []
    dl = EspnFake({MIRROR_URL: _mirror("E1", E1_SCHED, "2026-08-30")}, _e1_events())
    st, rep = _update(tmp_home, "E1", dl, progress=lambda p, m: msgs.append(m))
    assert any(m.startswith("ESPN verileri alınıyor: İngiltere - Championship (1/1)") for m in msgs)
    r = rep.espn["E1"]
    assert r["eslesmeyen"] == [] and r["sonuc"] == 10 and r["fikstur"] == 2 and "ESPN (onayınızla" in rep.summary()
    assert st.meta["espn_eslesme"]["E1"]["eslesme"]["Leeds United"]["takim"] == "Leeds"
    # Play-off maçları deponun 2025/26 sezonunun son maç gününden sonra: takvime yazılmaz, veriye eklenmez
    assert st.meta["espn_eslesme"]["E1"]["sezon_sonu_disarida"] == {"2025/26": 4}
    gap = st.matches[st.matches["source"] == ESPN_LABEL]
    assert gap["date"].min() > pd.Timestamp("2026-08-30")
    cal = json.loads((st.raw_dir / "espn" / "2025-26" / "E1.json").read_text())
    assert not any(m["id"].startswith("98") for m in cal["matches"]) and not old.exists()
    fx = st.fixtures[(st.fixtures["home"] == "Leeds") | (st.fixtures["away"] == "Leeds")].iloc[0]
    assert "DEPODA_EKSIK_MAC" not in _verdict(st, fx, "E1").reasons
    # Karşı olgu: play-off maçları takvimde olsaydı Leeds kalıcı olarak "veride eksik maç" görünürdü
    for k, (d, h, a, ft) in enumerate(E1_PLAYOFF):
        cal["matches"].append({"id": str(800 + k), "date": d.isoformat(), "time": "18:30", "team1": h, "team2": a,
                               "score": {"ft": list(ft)}})
    (st.raw_dir / "espn" / "2025-26" / "E1.json").write_text(json.dumps(cal))
    assert "DEPODA_EKSIK_MAC" in _verdict(st, fx, "E1").reasons


# ============================================================ ek lig: veri deposu bir sezondan fazla geride

US_OLD = ["Seattle", "Portland", "LA Galaxy", "San Jose"]
US_NEW = ["Seattle", "Portland", "LA Galaxy", "San Diego FC"]  # San Jose ayrıldı, San Diego FC 2025'te katıldı
US_ES = {"Seattle": "Seattle Sounders FC", "Portland": "Portland Timbers", "San Jose": "San Jose Earthquakes"}
US_SCHED = _schedule([("2024", "2024-03-02", 40, US_OLD), ("2025", "2025-03-01", 36, US_NEW),
                      ("2026", "2026-02-28", 34, US_NEW)])


def test_store_behind_extends_window_maps_by_overlap_and_adds_new_team(tmp_home):
    dl = EspnFake({MIRROR_URL: _mirror("USA", US_SCHED, "2024-11-30")}, _espn(US_SCHED, US_ES))
    st, rep = _update(tmp_home, "USA", dl)
    espn_urls = [u for u in dl.requested if u.startswith(ESPN_BASE)]
    # Yedek veri 30 Kasım 2024'te bitiyor: istekler Ağustos 2024'ten başlar (ortak dönem), Ocak 2025'ten değil
    assert "/usa.1/" in espn_urls[0] and "dates=20240801-20240831" in espn_urls[0]
    rec = st.meta["espn_eslesme"]["USA"]
    assert rec["eslesme"]["Seattle Sounders FC"]["takim"] == "Seattle"
    assert rec["eslesme"]["Seattle Sounders FC"]["kanit"].startswith("mac_kaniti")
    assert rec["eslesme"]["LA Galaxy"]["kanit"] == "ayni_ad"
    assert rec["eslesme"]["San Diego FC"]["takim"] == "San Diego FC"
    assert rec["eslesme"]["San Diego FC"]["kanit"].startswith("yeni_takim")
    r = rep.espn["USA"]
    assert r["yeni_takim"] == ["San Diego FC"] and r["eslesmeyen"] == []
    assert any("yeni takım olarak eklendi" in w for w in rep.warnings)
    # Eksik dönem 2025 ve 2026 sezonlarının tamamı (yalnızca güncel sezon değil); depo adlarıyla
    want = sum(1 for _, s, d, _, _ in US_SCHED if pd.Timestamp("2024-11-30") < d <= pd.Timestamp("2026-10-04"))
    gap = st.matches[st.matches["source"] == ESPN_LABEL]
    assert r["sonuc"] == want == len(gap) and set(gap["season"]) == {"2025", "2026"}
    assert set(gap["home"]) | set(gap["away"]) == set(US_NEW)
    fx = st.fixtures
    assert len(fx) == 2 and set(fx["date"]) == {pd.Timestamp("2026-10-17")} and set(fx["source"]) == {ESPN_LABEL}
    for season in ("2024", "2025", "2026"):
        assert (st.raw_dir / "espn" / season / "USA.json").is_file()
    sd = fx[(fx["home"] == "San Diego FC") | (fx["away"] == "San Diego FC")].iloc[0]
    reasons = _verdict(st, sd, "USA").reasons
    assert "TAKIM_ESLESMESI_DOGRULANAMADI" not in reasons and "DEPODA_EKSIK_MAC" not in reasons


def test_new_team_rule_needs_store_behind_current_season():
    # Depo güncel sezonda maç içeriyorsa lige yeni giren ad yeni takım sayılmaz (eşleşmezse eşleşmeyen kalır)
    from bahis_tahmin.data.espn import map_teams

    base = K4._base([("2026/27", "2026-08-22", "Bari", "Pisa", 1, 0, 0, 0)])
    evs = [K4._ev(1, "2026-08-22", "Bari", "Pisa", (1, 0)), K4._ev(2, "2026-09-05", "Bari", "Nuova", (2, 0))]
    assert "Nuova" not in map_teams(evs, base, "I2", "2026/27", evs).mapping
    tm = map_teams(evs, base, "I2", "2026/27", evs, new_after=dt.date(2026, 8, 23))
    assert tm.mapping["Nuova"] == "Nuova" and tm.basis["Nuova"].startswith("yeni_takim")
    # Ad depodaki bir takımla (aynı ülkenin başka liginde) aynıysa o takıma bağlanır, yeni takım açılmaz
    tm2 = map_teams(evs, base, "I2", "2026/27", evs, new_after=dt.date(2026, 8, 23), wider=["Nuova", "Lecco"])
    assert tm2.mapping["Nuova"] == "Nuova" and tm2.basis["Nuova"].startswith("ulke_ici_ayni_ad")


# ============================================================ ad değişikliği, ligler arası kanıt, kadro elemesi


def test_renamed_team_keeps_both_names_only_if_periods_do_not_overlap():
    from bahis_tahmin.data.espn import map_teams

    rows, evs = [], []
    for k in range(6):  # depoda tek ad; ESPN'de 2025-26 "Aberdeen FC", 2026-27 "Aberdeen"
        d = pd.Timestamp("2026-03-01" if k < 3 else "2026-08-02") + pd.Timedelta(days=7 * (k % 3))
        rows.append(("2025/26" if k < 3 else "2026/27", d, "Aberdeen", "Hearts", k, 0, 0, 0))
        evs.append(K4._ev(k, d, "Aberdeen FC" if k < 3 else "Aberdeen", "Hearts", (k, 0)))
    base = K4._base(rows)
    tm = map_teams(evs, base, "SC0", "2026/27", evs[3:])
    assert tm.mapping["Aberdeen FC"] == tm.mapping["Aberdeen"] == "Aberdeen"
    assert tm.basis["Aberdeen FC"].endswith("ad_degisikligi")
    # Aynı dönemde iki ad aynı takıma düşüyorsa hangisinin o takım olduğu bilinemez
    evs2 = evs + [K4._ev(9, "2026-08-23", "Aberdeen FC", "Hearts", (4, 4))]
    tm2 = map_teams(evs2, base, "SC0", "2026/27", evs2[3:])
    assert "Aberdeen" not in tm2.mapping and tm2.unmapped["Aberdeen FC"][0] == "TERS_CAKISMA"


def test_share_mappings_rules():
    from bahis_tahmin.data.espn import TeamMap, share_mappings

    def tms():
        d2 = TeamMap({"SC Paderborn 07": "Paderborn"}, {"SC Paderborn 07": "mac_kaniti 30 mac, %100"})
        d1 = TeamMap({"FC Bayern": "Bayern Munich"}, {"FC Bayern": "ayni_ad"}, {"SC Paderborn 07": ("KANIT_YOK", ())})
        return d1, d2

    d1, d2 = tms()
    share_mappings({"D1": ("Almanya", d1), "D2": ("Almanya", d2)})
    assert d1.mapping["SC Paderborn 07"] == "Paderborn" and d1.basis["SC Paderborn 07"].startswith("diger_lig (D2:")
    d1, d2 = tms()  # başka ülkenin ligi kanıt olmaz
    share_mappings({"D1": ("Almanya", d1), "D2": ("Avusturya", d2)})
    assert "SC Paderborn 07" not in d1.mapping
    d1, d2 = tms()  # hedef takım bu ligde başka bir ada verilmişse kullanılmaz
    d1.mapping["Paderborn 07"], d1.basis["Paderborn 07"] = "Paderborn", "mac_kaniti 5 mac, %100"
    share_mappings({"D1": ("Almanya", d1), "D2": ("Almanya", d2)})
    assert "SC Paderborn 07" not in d1.mapping


def test_roster_elimination_maps_last_remaining_team():
    from bahis_tahmin.data.espn import map_teams

    # Bari/Pisa kanıtla eşlenir; iki yeni takımdan birinin tek oyu var (kadro kısıtı), diğerinin hiç yok (eleme)
    base = K4._base([("2025/26", "2026-03-01", "Bari", "Pisa", 1, 0, 0, 0), ("2025/26", "2026-03-08", "Pisa", "Bari", 2, 2, 1, 1),
                     ("2025/26", "2026-03-15", "Bari", "Pisa", 0, 3, 0, 1),
                     ("2026/27", "2026-08-22", "Bari", "Ascoli", 2, 0, 1, 0),
                     ("2026/27", "2026-08-29", "Pisa", "Vicenza", 5, 5, 0, 0)])
    cur = [K4._ev(1, "2026-08-22", "Bari", "Ascoli Calcio 1898 FC", (2, 0)),
           K4._ev(2, "2026-08-29", "Pisa", "LR Vicenza", (1, 1)),  # depodakiyle skoru farklı: oy yok
           K4._ev(3, "2026-09-05", "LR Vicenza", "Ascoli Calcio 1898 FC", (0, 0))]
    tm = map_teams(cur, base, "I2", "2026/27", cur)
    assert tm.mapping["Ascoli Calcio 1898 FC"] == "Ascoli" and tm.basis["Ascoli Calcio 1898 FC"].startswith("kadro_kisiti")
    assert tm.mapping["LR Vicenza"] == "Vicenza" and tm.basis["LR Vicenza"].startswith("kadro_eleme")


class EspnBySlug(EspnFake):
    """Lig koduna göre ayrı ESPN olayları."""

    def __init__(self, files, by_slug):
        super().__init__(files, [])
        self.by_slug = by_slug

    def get(self, url, cache_rel, max_age_hours=None, force=False):
        if url.startswith(ESPN_BASE):
            self.events = self.by_slug.get(url[len(ESPN_BASE) + 1:].split("/")[0], [])
        return super().get(url, cache_rel, max_age_hours, force)


D1_OLD = ["Bayern Munich", "Dortmund", "Leipzig", "Bochum"]
D1_NEW = ["Bayern Munich", "Dortmund", "Leipzig", "Paderborn"]  # Bochum düştü, Paderborn çıktı
D2_OLD = ["Paderborn", "Kiel", "Hertha", "Schalke"]
D2_NEW = ["Bochum", "Kiel", "Hertha", "Schalke"]
DE_ES = {"Dortmund": "Borussia Dortmund", "Leipzig": "RB Leipzig", "Paderborn": "SC Paderborn 07",
         "Kiel": "Holstein Kiel", "Hertha": "Hertha Berlin"}


def test_promoted_team_is_mapped_with_evidence_from_lower_league(tmp_home):
    # Yaz arası: yedek veride Bundesliga'nın 2026/27 sezonu hiç yok (depo güncel sezona ulaşmıyor). Lige çıkan
    # "SC Paderborn 07"nin Bundesliga'da kanıtı yok; 2. Bundesliga'daki geçen sezon maçları kanıttır (aynı ESPN adı).
    d1 = _schedule([("2025/26", "2025-08-22", 30, D1_OLD), ("2026/27", "2026-08-21", 12, D1_NEW)])
    d2 = _schedule([("2025/26", "2025-08-01", 30, D2_OLD), ("2026/27", "2026-08-07", 12, D2_NEW)])
    d2 = [(i + 1000, *x) for i, *x in d2]  # olay kimlikleri ve skorlar ligden lige farklı
    mirror = _mirror("D1", d1, "2026-06-30") + b"\n".join(_mirror("D2", d2, "2026-08-30").split(b"\n")[1:])
    dl = EspnBySlug({MIRROR_URL: mirror}, {"ger.1": _espn(d1, DE_ES), "ger.2": _espn(d2, DE_ES)})
    st = DataStore(tmp_home)
    st.load()
    rep = st.update(["D1", "D2"], 2, today=TODAY, downloader=dl, allowed=ALLOWED)
    m1, m2 = st.meta["espn_eslesme"]["D1"]["eslesme"], st.meta["espn_eslesme"]["D2"]["eslesme"]
    assert m2["SC Paderborn 07"]["takim"] == "Paderborn" and m2["SC Paderborn 07"]["kanit"].startswith("mac_kaniti")
    assert m1["SC Paderborn 07"]["takim"] == "Paderborn" and m1["SC Paderborn 07"]["kanit"].startswith("diger_lig (D2:")
    assert rep.espn["D1"]["yeni_takim"] == [] and rep.espn["D1"]["eslesmeyen"] == []
    gap = st.matches[(st.matches["source"] == ESPN_LABEL) & (st.matches["league"] == "D1")]
    assert set(gap["season"]) == {"2026/27"} and "Paderborn" in set(gap["home"]) | set(gap["away"])
    assert set(st.fixtures["league"]) == {"D1", "D2"} and set(st.fixtures["source"]) == {ESPN_LABEL}


# ============================================================ ESPN kullanılmayan durumlar


def test_poorly_mapped_league_is_not_used(tmp_home):
    # ESPN yanıtı başka bir yarışmanın maçlarını veriyor (yanlış lig kodu gibi): adlar eşlenmez, ESPN kullanılmaz
    events = []
    for d, e in K4._espn_events():
        e = json.loads(json.dumps(e))
        for c in e["competitions"][0]["competitors"]:
            c["team"]["displayName"] = "Başka " + c["team"]["displayName"]
            c["score"] = str(int(c["score"]) + 5)
            c.pop("linescores", None)
        events.append((d, e))
    st, rep, _ = K4._update(tmp_home, events=events)
    assert rep.espn == {} and any("yeterince eşlenemedi" in w for w in rep.warnings)
    assert st.meta["espn_eslesme"]["I2"]["kullanilmadi"] == "ESLESME_YETERSIZ"
    assert not (st.matches["source"] == ESPN_LABEL).any() and st.fixtures.empty
    assert not list((st.raw_dir / "espn").glob("*/I2.json"))


class EspnMissingLeague(EspnFake):
    def get(self, url, cache_rel, max_age_hours=None, force=False):
        if url.startswith(ESPN_BASE):
            self.requested.append(url)
            raise DownloadError(url, "HTTP 400", 400)
        return super().get(url, cache_rel, max_age_hours, force)


def test_unverified_code_missing_on_espn_stops_early(tmp_home):
    sched = _schedule([("2024/25", "2024-07-27", 18, ["Basel", "Young Boys", "Servette", "Lugano"])])
    dl = EspnMissingLeague({MIRROR_URL: _mirror("SUI", sched, "2024-11-30")}, [])
    st, rep = _update(tmp_home, "SWZ", dl)
    assert len([u for u in dl.requested if u.startswith(ESPN_BASE)]) == MAX_FAILS  # kalan aylar istenmez
    assert rep.espn == {} and any("doğrulanamamıştı" in w and "sui.1" in w for w in rep.warnings)
    assert not (st.matches["source"] == ESPN_LABEL).any()

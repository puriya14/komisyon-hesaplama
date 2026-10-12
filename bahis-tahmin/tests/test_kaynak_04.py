"""KAYNAK-04: ESPN (onaylı kaynak) ile Serie B / La Liga 2 / Ligue 2 fikstürü, eksik dönem ve sezon takvimi.

Yalnızca SENTETİK veri ve sahte indirici (ağ yok). ESPN yanıtları, uç noktanın bilinen biçimiyle üretilir.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from urllib.parse import parse_qs, urlsplit

import pandas as pd
from test_store import FakeDownloader

from bahis_tahmin import eligibility as E
from bahis_tahmin.data.espn import (
    ESPN_BASE,
    ESPN_LABEL,
    EspnEvent,
    calendar_json,
    map_teams,
    month_chunks,
    parse_scoreboard,
)
from bahis_tahmin.data.provenance import verified_labels
from bahis_tahmin.data.source_registry import DECLARABLE, SOURCES, allowed_sources
from bahis_tahmin.data.sources import MIRROR_URL
from bahis_tahmin.data.store import DataStore

TODAY = dt.date(2026, 10, 12)
FD = ["Palermo", "Sampdoria", "Sudtirol", "Cosenza"]  # yedek veri (football-data) adları
# ESPN adları: ikisi aynı ad (biri yalnızca aksan farkı), ikisi yalnızca maç kanıtıyla eşlenebilir
ES = {"Palermo": "Palermo", "Sampdoria": "Sampdoria", "Sudtirol": "FC Südtirol Bolzano", "Cosenza": "Cosenza 1914"}
PAIRS = [(0, 1, 2, 3), (0, 2, 1, 3), (0, 3, 1, 2)]
CONSENT = {"github-mirror": "t", "espn": "t"}
ALLOWED = allowed_sources(CONSENT)


def _round(k: int):
    a, b, c, d = PAIRS[k % 3]
    return [(FD[a], FD[b]), (FD[c], FD[d])] if k % 2 == 0 else [(FD[b], FD[a]), (FD[d], FD[c])]


def _schedule():
    out = []
    for season, start, n in (("2025/26", "2025-08-23", 30), ("2026/27", "2026-08-22", 12)):
        for k in range(n):
            d = pd.Timestamp(start) + pd.Timedelta(days=7 * k)
            out += [(season, d, h, a) for h, a in _round(k)]
    return [(i, *x) for i, x in enumerate(out)]


def _score(i: int):
    ft = ((i * 7) % 5, (i * 3) % 4)
    return ft, (min(ft[0], i % 2), min(ft[1], (i // 2) % 2))


def _mirror(until="2026-08-30") -> bytes:
    rows = []
    for i, _, d, h, a in _schedule():
        if d > pd.Timestamp(until):
            continue
        (fh, fa), (hh, ha) = _score(i)
        rows.append({"Division": "I2", "MatchDate": d.strftime("%Y-%m-%d"), "MatchTime": "18:30:00", "HomeTeam": h,
                     "AwayTeam": a, "FTHome": fh, "FTAway": fa, "HTHome": hh, "HTAway": ha,
                     "OddHome": 2.0, "OddDraw": 3.2, "OddAway": 3.5})
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode()


def _event(i, d, h, a, ft=None, ht=None, name=None, state=None, completed=None, utc="16:30", **comp_extra):
    def side(where, team, k):
        c = {"homeAway": where, "team": {"displayName": team, "abbreviation": team[:3].upper()},
             "score": str(ft[k]) if ft else "0"}
        if ht and ft:
            c["linescores"] = [{"value": float(ht[k])}, {"value": float(ft[k] - ht[k])}]
        return c

    name = name or ("STATUS_FULL_TIME" if ft else "STATUS_SCHEDULED")
    comp = {"date": f"{pd.Timestamp(d):%Y-%m-%d}T{utc}Z", "competitors": [side("home", h, 0), side("away", a, 1)],
            "status": {"type": {"name": name, "state": state or ("post" if ft else "pre"),
                                "completed": bool(ft) if completed is None else completed}}, **comp_extra}
    return {"id": str(9000 + i), "date": comp["date"], "name": f"{a} at {h}", "competitions": [comp]}


def _espn_events(played_until="2026-10-04"):
    out = []
    for i, _, d, h, a in _schedule():
        if d <= pd.Timestamp(played_until):
            ft, ht = _score(i)
            out.append((d, _event(i, d, ES[h], ES[a], ft, ht)))
        else:
            out.append((d, _event(i, d, ES[h], ES[a])))
    return out


class EspnFake(FakeDownloader):
    """ESPN skor tablosu isteklerine tarih aralığına göre yanıt verir; diğer adresler sözlükten."""

    def __init__(self, files, events, fd_down=True):
        super().__init__(files, fd_down=fd_down)
        self.events = events

    def get(self, url, cache_rel, max_age_hours=None, force=False):
        if not url.startswith(ESPN_BASE):
            return super().get(url, cache_rel, max_age_hours, force)
        self.requested.append(url)
        a, b = parse_qs(urlsplit(url).query)["dates"][0].split("-")
        lo, hi = pd.Timestamp(a), pd.Timestamp(b)
        return json.dumps({"events": [e for d, e in self.events if lo <= d <= hi]}).encode()


def _update(home, allowed=ALLOWED, events=None, mirror_until="2026-08-30"):
    st = DataStore(home)
    st.load()
    dl = EspnFake({MIRROR_URL: _mirror(mirror_until)}, _espn_events() if events is None else events)
    rep = st.update(["I2"], 2, today=TODAY, downloader=dl, allowed=allowed)
    return st, rep, dl


# ============================================================ ayrıştırıcı


def test_parser_reads_normal_results_and_never_guesses():
    events = [
        _event(1, "2026-10-17", "Bari", "Pisa", (2, 1), (1, 0)),  # 16:30Z -> Roma 18:30 (yaz saati)
        _event(2, "2026-10-17", "Bari", "Modena", (1, 1), None, name="STATUS_FINAL_AET"),  # uzatma: okunmaz
        _event(3, "2026-10-18", "Pisa", "Bari", name="STATUS_POSTPONED", state="post", completed=False),
        _event(4, "2026-10-19", "Modena", "Pisa", timeValid=False),  # saat kesin değil
        {"id": "5", "competitions": [{"competitors": []}]},  # takımsız kayıt
        {"id": "7", "name": "yarışma bilgisi yok"},  # bozuk kayıt
    ]
    ev5 = _event(6, "2026-10-20", "Cesena", "Bari", (3, 0), (2, 1))  # devre skorları MS ile tutarsız -> İY yok
    ev5["competitions"][0]["competitors"][0]["score"] = {"value": 3.0, "displayValue": "3"}
    ev5["competitions"][0]["competitors"][0]["linescores"] = [{"value": 1.0}, {"value": 1.0}]
    r = parse_scoreboard(json.dumps({"events": events + [ev5]}).encode(), "İtalya")
    got = {e.event_id: e for e in r.events}
    e1 = got["9001"]
    assert (e1.date, e1.time, e1.ft, e1.ht, e1.home, e1.away) == (dt.date(2026, 10, 17), "18:30", (2, 1), (1, 0),
                                                                  "Bari", "Pisa")
    assert "9002" not in got and r.skipped["NORMAL_SURE_DISI"] == 1
    assert got["9003"].ft is None and got["9003"].status == "STATUS_POSTPONED"
    assert got["9004"].time == "" and got["9004"].date == dt.date(2026, 10, 19)
    assert got["9006"].ft == (3, 0) and got["9006"].ht is None
    assert r.skipped["TAKIM_GECERSIZ"] == 1 and r.skipped["BICIM_BILINMIYOR"] == 1
    assert parse_scoreboard(b"<html>", "İtalya").skipped["BICIM_BILINMIYOR"] == 1
    # Takvimde ertelenen maç durumuyla, normal sonuç skorla yazılır
    cal = json.loads(calendar_json(r.events, map_teams([], pd.DataFrame(columns=["season", "home", "away", "date",
                                                                                  "fthg", "ftag", "hthg", "htag"]),
                                                                  "I2", "2026/27", []), "x"))
    st = {m["id"]: m for m in cal["matches"]}
    assert st["9003"]["status"] == "postponed" and st["9001"]["score"] == {"ft": [2, 1], "ht": [1, 0]}
    assert st["9001"]["team1"] == "[ESPN] Bari"  # eşlenmemiş ad depodaki bir takımla karışmaz


def test_month_chunks_cover_range_without_gaps():
    ch = month_chunks(dt.date(2025, 7, 1), dt.date(2026, 10, 22))
    assert ch[0] == (dt.date(2025, 7, 1), dt.date(2025, 7, 31)) and ch[-1] == (dt.date(2026, 10, 1), dt.date(2026, 10, 22))
    assert all(b + dt.timedelta(days=1) == c for (_, b), (c, _) in zip(ch, ch[1:]))


# ============================================================ takım kimliği


def _base(rows):
    df = pd.DataFrame(rows, columns=["season", "date", "home", "away", "fthg", "ftag", "hthg", "htag"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def _ev(i, d, h, a, ft):
    return EspnEvent(str(i), pd.Timestamp(d).date(), "18:30", h, a, "post", "STATUS_FULL_TIME", ft, None)


def test_roster_rule_maps_promoted_teams_with_little_evidence():
    # Ascoli ve Vicenza lige yeni çıktı: depoda yalnızca bu sezonun 1. turu var (1'er maç kanıtı)
    base = _base([("2025/26", "2026-03-01", "Bari", "Pisa", 1, 0, 0, 0), ("2025/26", "2026-03-08", "Pisa", "Bari", 2, 2, 1, 1),
                  ("2025/26", "2026-03-15", "Bari", "Pisa", 0, 3, 0, 1),
                  ("2026/27", "2026-08-22", "Bari", "Ascoli", 2, 0, 1, 0),
                  ("2026/27", "2026-08-22", "Pisa", "Vicenza", 1, 1, 0, 0)])
    cur = [_ev(1, "2026-08-22", "Bari", "Ascoli Calcio 1898 FC", (2, 0)), _ev(2, "2026-08-22", "Pisa", "LR Vicenza", (1, 1)),
           _ev(3, "2026-09-05", "LR Vicenza", "Bari", (0, 0)), _ev(4, "2026-09-05", "Ascoli Calcio 1898 FC", "Pisa", (1, 2))]
    tm = map_teams(cur, base, "I2", "2026/27", cur)
    assert tm.mapping == {"Bari": "Bari", "Pisa": "Pisa", "Ascoli Calcio 1898 FC": "Ascoli", "LR Vicenza": "Vicenza"}
    assert tm.basis["LR Vicenza"].startswith("kadro_kisiti")
    # Kadro büyüklükleri farklıysa (ESPN'de fazladan takım) kadro kısıtı uygulanmaz
    extra = cur + [_ev(5, "2026-09-12", "Modena", "Bari", (1, 0))]
    tm2 = map_teams(extra, base, "I2", "2026/27", extra)
    assert "LR Vicenza" not in tm2.mapping and tm2.unmapped["LR Vicenza"][0] == "KANIT_YOK"


def test_same_name_contradicted_by_evidence_is_not_mapped():
    # ESPN'deki "Pisa" adıyla verilen maçlar depoda hep "Bari"nin maçları: aynı ad güvenilmez
    rows, evs = [], []
    for k in range(4):
        d = pd.Timestamp("2026-03-01") + pd.Timedelta(days=7 * k)
        rows.append(("2025/26", d, "Bari", "Lecco", k, 0, 0, 0))
        evs.append(_ev(k, d, "Pisa", "Lecco", (k, 0)))
    rows.append(("2025/26", "2026-04-05", "Pisa", "Lecco", 5, 5, 0, 0))
    tm = map_teams(evs, _base(rows), "I2", "2026/27", [])
    assert "Pisa" not in tm.mapping and tm.unmapped["Pisa"][0] == "KANIT_CELISKISI"


# ============================================================ veri deposu


def test_espn_fills_gap_fixtures_and_calendar_with_consent(tmp_home):
    st, rep, dl = _update(tmp_home)
    r = rep.espn["I2"]
    # Yedek veri 29 Ağustos'ta bitiyor; ESPN 5 Eylül - 3 Ekim arası 5 turu (10 maç) oynanmış gösteriyor
    assert r["sonuc"] == 10 and r["fikstur"] == 2 and r["eslesmeyen"] == [] and "ESPN (onayınızla" in rep.summary()
    gap = st.matches[st.matches["source"] == ESPN_LABEL]
    assert len(gap) == 10 and set(gap["home"]) | set(gap["away"]) == set(FD)  # depo adlarıyla
    assert gap["date"].min() > pd.Timestamp("2026-08-30") and gap["date"].max() <= pd.Timestamp("2026-10-04")
    assert gap["hthg"].notna().all() and gap[["o_h", "o_d", "o_a"]].isna().all().all()
    assert not st.matches.duplicated(["league", "date", "home", "away"]).any()
    fx = st.fixtures
    assert len(fx) == 2 and set(fx["source"]) == {ESPN_LABEL} and set(fx["date"]) == {pd.Timestamp("2026-10-17")}
    assert (fx["time"] == "18:30").all() and set(fx["home"]) | set(fx["away"]) == set(FD)
    assert st.unmatched_fixtures.empty
    rec = st.meta["espn_eslesme"]["I2"]
    assert rec["eslesme"]["FC Südtirol Bolzano"]["takim"] == "Sudtirol"
    assert rec["eslesme"]["Cosenza 1914"]["kanit"].startswith("mac_kaniti")
    # Takvimler yazıldı; uygunluk kontrolü ESPN takvimini kaynak etiketiyle okur
    covs = E.cached_coverages(st.raw_dir, ["I2"], TODAY, {"I2": FD})["I2"]
    assert {c.source for c in covs} == {ESPN_LABEL} and len(covs) == 2
    cur = next(c for c in covs if c.season == "2026/27")
    assert {m.home for m in cur.matches} == set(FD) and not cur.unmapped_names
    # Tamamlanmış aylar yeniden istenmez: ikinci güncellemede aynı sonuçlar
    st2, rep2, _ = _update(tmp_home)
    assert rep2.espn["I2"]["sonuc"] == 10 and (st2.matches["source"] == ESPN_LABEL).sum() == 10


def test_without_consent_espn_is_never_requested(tmp_home):
    st, rep, dl = _update(tmp_home, allowed=allowed_sources({"github-mirror": "t"}))
    assert not any(u.startswith(ESPN_BASE) for u in dl.requested)
    assert rep.espn == {} and (st.matches["source"] == ESPN_LABEL).sum() == 0 and st.fixtures.empty


def test_espn_rows_need_consent_and_declaration_for_training(tmp_home):
    st, _, _ = _update(tmp_home)
    vl = verified_labels(st)
    decl = {"github-mirror": "t", "espn": "t"}
    assert E.training_rights_codes(st.matches, CONSENT, vl, decl) == []
    assert "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI" in E.training_rights_codes(st.matches, CONSENT, vl,
                                                                           {"github-mirror": "t"})
    assert "KAYNAK_ERISIM_IZNI_YOK" in E.training_rights_codes(st.matches, {"github-mirror": "t"}, vl, decl)
    assert "espn" in DECLARABLE and SOURCES["espn"].requires_consent


def test_eligibility_reverifies_espn_fixture_and_sees_known_gap(tmp_home):
    st, _, _ = _update(tmp_home)
    as_of = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=1)
    fx = st.fixtures.iloc[0]

    def verdict(store):
        ctx = E.build_context(store, None, CONSENT, today=TODAY, declarations=CONSENT, mode="standart")
        return ctx.evaluate(league="I2", date=fx["date"], home=fx["home"], away=fx["away"], as_of=as_of,
                            markets=("1X2",), source=ESPN_LABEL, prediction_codes=())["1X2"]

    e = verdict(st)
    assert e.data_scope["eslesme"]["kaynak_takviminde_yeniden_kuruldu"] is True
    assert "TAKIM_ESLESMESI_DOGRULANAMADI" not in e.reasons and "DEPODA_EKSIK_MAC" not in e.reasons
    # Ev sahibinin ESPN'de oynanmış bir maçı depodan çıkarılırsa bilinen eksik olarak görünür
    gap = st.matches[(st.matches["source"] == ESPN_LABEL)
                     & ((st.matches["home"] == fx["home"]) | (st.matches["away"] == fx["home"]))]
    st.matches = st.matches.drop(gap.index[-1])
    assert "DEPODA_EKSIK_MAC" in verdict(st).reasons


def test_unmapped_espn_name_gives_reasoned_no_prediction(tmp_home):
    # Yeni bir ad (kanıtı yok): o takımın maçları eklenmez, fikstürü nedenli "tahmin yok" olur
    events = []
    for d, e in _espn_events():
        e = json.loads(json.dumps(e))
        for c in e["competitions"][0]["competitors"]:
            if c["team"]["displayName"] == "Cosenza 1914" and d > pd.Timestamp("2026-08-30"):
                c["team"]["displayName"] = "Cosenza Nuova"
        events.append((d, e))
    st, rep, _ = _update(tmp_home, events=events)
    assert rep.espn["I2"]["eslesmeyen"] == ["Cosenza Nuova"]
    assert any("kanıtla eşleşmedi" in w for w in rep.warnings)
    gap = st.matches[st.matches["source"] == ESPN_LABEL]
    assert "Cosenza" not in set(gap["home"]) | set(gap["away"]) and len(gap) == 5
    um = st.unmatched_fixtures
    assert len(um) == 1 and set(um["source"]) == {ESPN_LABEL} and len(st.fixtures) == 1

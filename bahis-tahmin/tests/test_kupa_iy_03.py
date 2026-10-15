"""KUPA-IY-03: yurt içi kupalar için ilk yarı skorları (openfootball ülke depoları).

Yalnızca SENTETİK veri (``kupa_yardim`` dünyası + sentetik FA Cup); ağ isteği yok."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from kupa_yardim import (
    E0,
    OF_NAME,
    FakeCupDownloader,
    espn_event,
    espn_world,
    openfootball_files,
    world,
)

TODAY = dt.date(2026, 9, 1)  # 2025/26 bitti, 2026/27 başladı
AMATEUR = ["Hereford FC", "Marine AFC", "Curzon Ashton", "Alfreton Town", "Horsham FC", "Maidstone United"]
_DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@pytest.fixture(scope="module")
def w():
    return world()


def fa_cup(seed: int = 5, seasons: int = 5, rounds: int = 5) -> pd.DataFrame:
    """Sentetik FA Cup: sezon başına ``rounds`` tur × 8 maç (her takım günde bir maç): 6 amatör ev sahibi – Premier
    League deplasman (UEFA'dan farklı sonuç dağılımı: deplasman ağırlıklı) ve 2 Premier League eşleşmesi."""
    from bahis_tahmin.data.leagues import season_label
    from bahis_tahmin.kupa.kimlik import outside_key
    from bahis_tahmin.kupa.veri import CUP_MATCH_COLUMNS

    def ident(name: str, mapped: bool) -> tuple:
        return ((name, f"İngiltere|{name}", "İngiltere", True) if mapped
                else (name, outside_key("ENG", name), "ENG", False))

    rng = np.random.default_rng(seed)
    games = []
    for s in range(seasons):
        y = 2021 + s
        sat = dt.date(y, 11, 6) + dt.timedelta(days=(5 - dt.date(y, 11, 6).weekday()) % 7)
        for k in range(rounds):
            d = sat + dt.timedelta(days=7 * k)
            pros = [E0[i] for i in rng.permutation(len(E0))]
            games += [(y, d, ident(pros[0], True), ident(pros[1], True), 1.5, 1.2),
                      (y, d, ident(pros[2], True), ident(pros[3], True), 1.5, 1.2)]
            games += [(y, d, ident(am, False), ident(pro, True), 0.7, 2.1) for am, pro in zip(AMATEUR, pros[4:])]
    rows = []
    for y, d, (hn, hk, hc, hm), (an, ak, ac, am), lam, nu in games:
        hg, ag = int(rng.poisson(lam)), int(rng.poisson(nu))
        rows.append({"comp": "FAC", "season": season_label(y), "stage": "Round 1", "date": pd.Timestamp(d),
                     "time": "15:00", "home": hn, "away": an, "home_key": hk, "away_key": ak, "home_country": hc,
                     "away_country": ac, "home_mapped": hm, "away_mapped": am, "fthg": hg, "ftag": ag,
                     "hthg": float(rng.binomial(hg, 0.45)), "htag": float(rng.binomial(ag, 0.45)),
                     "extra_time": False, "neutral": False, "source": "sentetik", "provider_id": f"fa:{len(rows)}",
                     "home_raw": hn, "away_raw": an})
    return pd.DataFrame(rows, columns=CUP_MATCH_COLUMNS)


def _of_name(name: str) -> str:
    return name if name in AMATEUR else OF_NAME.get(name, name + " FC")


def fa_files(fa: pd.DataFrame, extra: dict | None = None, mid: bool = False) -> dict:
    """(depo, yol) -> openfootball/england FA Cup dosyası baytları (ülke kodu yok; ``mid``: skor-ortada biçim)."""
    out = {}
    for season, g in fa.groupby("season"):
        y = int(str(season)[:4])
        d = f"{y}-{(y + 1) % 100:02d}"
        lines = [f"= English FA Cup {season}", "", "▪ Round 1"]
        for day, gd in g.groupby("date"):
            lines.append(f"  {_DOW[day.weekday()]} {_MON[day.month - 1]} {day.day} {day.year}")
            for r in gd.itertuples(index=False):
                h, a, sc = _of_name(r.home), _of_name(r.away), f"{r.fthg}-{r.ftag} ({int(r.hthg)}-{int(r.htag)})"
                lines.append(f"    15:00  {h:<24}  {sc}  {a}" if mid else f"    15:00  {h:<24}v {a:<24}  {sc}")
        lines += (extra or {}).get(d, [])
        out[("openfootball/england", f"{d}/facup.txt")] = "\n".join(lines).encode("utf-8")
    return out


class FakeDomesticDownloader(FakeCupDownloader):
    """openfootball/champions-league + ülke depoları (``(depo, yol)`` sözlüğü) + ESPN, ağ olmadan."""

    def __init__(self, of_files, domestic: dict, espn, cache):
        super().__init__(of_files, espn, cache)
        self.domestic = domestic

    def get(self, url, cache_rel, max_age_hours=None, force=False):
        from bahis_tahmin.data.sources import DownloadError

        raw = "https://raw.githubusercontent.com/"
        if url.startswith(raw) and not url.startswith(self.base + "/"):
            self.requested.append(url)
            repo_branch, _, path = url[len(raw):].partition("/master/")
            hit = self.domestic.get((repo_branch, path))
            if hit is None:
                raise DownloadError(url, "dosya bulunamadı (404)", 404)
            return hit
        return super().get(url, cache_rel, max_age_hours, force)


# =============================================================================================== okuyucu


def test_parser_reads_domestic_formats_with_half_time():
    from bahis_tahmin.kupa.openfootball import parse_cup_txt

    txt = """= DFB Pokal 2023/24
▪ Round 1
Fri Aug 11
  18:00  1. FC Saarbrücken        2-1 (0-0)  Karlsruher SC
         SV Sandhausen            4-2 pen. 3-3 a.e.t. (3-3, 1-2)  Hannover 96
         Preußen Münster          2-0  VfL Wolfsburg            [awarded]
         CD Cardassar             -  AD CF Épila
         FC Teutonia 05           0-8 (0-3)  1. FC Köln
▪ Semifinals
Sat Apr 20 2024
  15:00  Nottingham Forest        v Bury FC                  10-9 pen. (1-1, 0-1)
         Millwall FC              v Gillingham FC            3-1 pen. (0-0)
         Fethiyespor              v Düzcespor                4-3 pen.
         Zonguldakspor FK         v Kırıkkale FK             2-4 a.e.t.
         Club Brugge (BEL)        v Arsenal FC               2-1 a.e.t. (1-0, 0-0)
▪ Final
Sat May 25 2024
  20:00  Bayer Leverkusen         1-0 (1-0)  1. FC Kaiserslautern
"""
    pr = parse_cup_txt(txt.encode("utf-8"), "2023-24", default_cc="GER", neutral_rounds=frozenset({"semifinals"}))
    m = {(r["team1"], r["team2"]): r for r in pr.matches}
    sa = m[("1. FC Saarbrücken", "Karlsruher SC")]
    assert sa["score"] == {"ft": [2, 1], "ht": [0, 0]} and sa["cc1"] == sa["cc2"] == "GER" and not sa["neutral"]
    assert sa["date"] == "2023-08-11" and sa["time"] == "18:00"
    assert m[("SV Sandhausen", "Hannover 96")]["score"] == {"ft": [3, 3], "et": [3, 3], "ht": [1, 2], "pen": [4, 2]}
    assert m[("FC Teutonia 05", "1. FC Köln")]["score"]["ht"] == [0, 3]  # deplasman adı rakamla başlayabilir
    # Uzatmasız penaltı: parantez normal süre (ve ilk yarı); tek parantezde ilk yarı bilinmiyor
    assert m[("Nottingham Forest", "Bury FC")]["score"] == {"ft": [1, 1], "ht": [0, 1], "pen": [10, 9]}
    assert m[("Millwall FC", "Gillingham FC")]["score"] == {"ft": [0, 0], "pen": [3, 1]}
    # İki ayaklı eşleşmede uzatmaya toplam skor götürür: normal süre berabere olmak zorunda değil
    br = m[("Club Brugge", "Arsenal FC")]
    assert br["score"] == {"ft": [1, 0], "et": [2, 1], "ht": [0, 0]} and br["cc1"] == "BEL" and br["cc2"] == "GER"
    assert br["neutral"] and m[("Bayer Leverkusen", "1. FC Kaiserslautern")]["neutral"]  # yarı final + final
    assert pr.skipped == {"NOT_HUKMEN": 1, "BILINMEYEN_SATIR": 1, "UZATMA_NORMAL_SURE_YOK": 2}
    assert len(pr.matches) == 7
    # Aynı satırlar ülke kodu ve tarafsız tur verilmeden: ülke kodu boş, yarı final tarafsız değil
    pr0 = parse_cup_txt(txt.encode("utf-8"), "2023-24")
    nf = [r for r in pr0.matches if r["team1"] == "Nottingham Forest"][0]
    assert nf["cc1"] == "" and not nf["neutral"]


def test_parser_keeps_uefa_semantics():
    """UEFA dosyalarında v1 ile aynı sonuç (gerçek veride 25 dosyada denetlendi): normal, uzatma, penaltı biçimleri."""
    from bahis_tahmin.kupa.openfootball import parse_cup_txt

    txt = """= UEFA Champions League 2025/26
▪ League, Matchday 1
  Tue Sep 16 2025
    18:45  Athletic Club (ESP)     v Arsenal FC (ENG)         0-2 (0-0)
           PSV (NED)               v Royale Union Saint-Gilloise (BEL)  1-3 (0-2)
▪ Finals, Final
  Sat May 30 2026
    18:00  Paris Saint-Germain FC (FRA) v Arsenal FC (ENG)    4-3 pen. 1-1 a.e.t. (1-1, 0-1)
"""
    pr = parse_cup_txt(txt.encode("utf-8"), "2025-26")
    assert [(r["team1"], r["cc1"], r["team2"], r["cc2"], r["score"], r["neutral"]) for r in pr.matches] == [
        ("Athletic Club", "ESP", "Arsenal FC", "ENG", {"ft": [0, 2], "ht": [0, 0]}, False),
        ("PSV", "NED", "Royale Union Saint-Gilloise", "BEL", {"ft": [1, 3], "ht": [0, 2]}, False),
        ("Paris Saint-Germain FC", "FRA", "Arsenal FC", "ENG", {"ft": [1, 1], "et": [1, 1], "ht": [0, 1],
                                                              "pen": [4, 3]}, True)]
    assert pr.skipped == {}


# =============================================================================================== katalog


def test_competition_catalog_for_domestic_files():
    from bahis_tahmin.kupa.motor import kickoff_country
    from bahis_tahmin.kupa.turnuvalar import CC_COUNTRY, COMPETITIONS
    from bahis_tahmin.kupa.veri import of_spec

    dom = [c for c in COMPETITIONS.values() if c.of_path]
    assert {c.code for c in dom} == {"TRC", "FAC", "EFL", "CDR", "DFB", "CIT", "CDF", "KNVB", "TDP", "BELC"}
    labels = [of_spec(c.code, "2024-25").label for c in dom]
    assert len(set(labels)) == len(labels)  # üç ülkenin "2024-25/cup.txt" dosyası ayrı bağlam
    for c in dom:
        assert c.group == "C" and CC_COUNTRY[c.default_cc] == c.country and c.of_first >= 2018
    ucl = of_spec("UCL", "2024-25")
    assert (ucl.repo, ucl.path, ucl.label) == ("openfootball/champions-league", "2024-25/cl.txt", "2024-25/cl.txt")
    assert COMPETITIONS["UCL"].default_cc == "" and of_spec("ENGS", "2024-25") is None  # süper kupa dosyası yok
    assert of_spec("DFB", "2024-25").label == "openfootball/deutschland:2024-25/cup.txt"
    assert of_spec("TRC", "2024-25").path == "turkey/2024-25_trcup.txt"
    assert "semifinals" in COMPETITIONS["FAC"].of_neutral  # FA Cup yarı finalleri Wembley'de
    # Saat dilimi: openfootball yurt içi dosyaları ülkenin saati, UEFA dosyaları Orta Avrupa saati
    assert kickoff_country("FAC", "openfootball-kupa") == "İngiltere"
    assert kickoff_country("UCL", "openfootball-kupa") == "Almanya"
    assert kickoff_country("UCL", "espn") == "Türkiye" and kickoff_country("DFB", "espn") == "Almanya"


# =============================================================================================== kimlik


def _depot(rows):
    return pd.DataFrame([{"league": lg, "date": pd.Timestamp(d), "home": h, "away": a} for lg, d, h, a in rows])


def test_domestic_identity_guards():
    from bahis_tahmin.kupa.kimlik import map_openfootball

    m = _depot([("P1", "2024-09-01", "Benfica", "Porto"), ("P1", "2024-09-08", "Porto", "Benfica"),
                ("SP2", "2019-09-01", "Extremadura UD", "Alcorcon"), ("SP2", "2021-09-01", "Alcorcon", "Sabadell")])
    rec = lambda h, a, cc: {"team1": h, "team2": a, "cc1": cc, "cc2": cc}  # noqa: E731
    files = {"pt": [rec("SL Benfica", "CF Benfica", "POR"), rec("FC Porto", "CF Benfica", "POR")],
             "es": [rec("CD Extremadura", "AD Alcorcón", "ESP")], "es2": [rec("UD Extremadura", "CE Sabadell", "ESP")]}
    om = map_openfootball(files, m, domestic={"pt", "es", "es2"})
    assert om.get("pt", "POR", "SL Benfica").key == "Portekiz|Benfica"  # doğrulanmış takma ad
    cf = om.get("pt", "POR", "CF Benfica")
    assert not cf.mapped and cf.key == "POR|benfica" and "ters_cakisma_yurt_ici" in cf.basis
    assert om.get("pt", "POR", "FC Porto").key == "Portekiz|Porto"
    ex = om.get("es", "ESP", "CD Extremadura")
    assert not ex.mapped and "tur_eki_celiskisi" in ex.basis  # CD ≠ UD (farklı kulüp)
    assert om.get("es2", "ESP", "UD Extremadura").key == "İspanya|Extremadura UD"  # ortak ek: aynı kulüp
    assert om.get("es", "ESP", "AD Alcorcón").key == "İspanya|Alcorcon"  # KUPA-IY-03 takma adları
    assert om.get("es2", "ESP", "CE Sabadell").key == "İspanya|Sabadell"
    # Korumalar yalnızca yurt içi dosyalarında: UEFA kuralıyla iki Benfica adı da bağlanır (KUPA-01 davranışı)
    om0 = map_openfootball(files, m)
    assert om0.get("pt", "POR", "CF Benfica").mapped and om0.get("es", "ESP", "CD Extremadura").mapped
    assert ("POR", "CF Benfica") in om.unmapped and om.unmapped[("POR", "CF Benfica")][0].startswith("BELIRSIZ")


# =============================================================================================== güncelleme


def _update(w, tmp_path, comps=("UCL", "UEL", "FAC"), fa=None, espn=None, domestic=None, allowed=("openfootball",),
            years_back=6):
    from bahis_tahmin.kupa.veri import update_cups

    dom, cups = w
    fa = fa_cup() if fa is None else fa
    of = openfootball_files(cups[cups["season"] < "2025/26"])
    dl = FakeDomesticDownloader(of, fa_files(fa) if domestic is None else domestic, espn, tmp_path / "onbellek")
    res = update_cups(tmp_path / "raw", dl, None, list(comps), years_back, dom, TODAY, 30, set(allowed))
    return res, dl


def test_update_reads_domestic_cup_history_with_half_time_and_provenance(w, tmp_path):
    from bahis_tahmin.kupa.veri import rows_sha256, verify_cup_rows

    fa = fa_cup()
    # Aynı dosyada takma adla Man City'ye bağlanan "Manchester City FC" varken normal adı aynı düşen amatör "FC Man City"
    # depodaki takıma bağlanmaz (ters çakışma koruması güncelleme akışında da çalışır)
    clash = ["▪ Round 2", "  Sat Jan 7 2023", "    15:00  FC Man City              v Hereford FC               1-2 (0-1)"]
    res, dl = _update(w, tmp_path, fa=fa, domestic=fa_files(fa, extra={"2022-23": clash}), years_back=10)
    m = res.matches
    odd = m[(m["comp"] == "FAC") & (m["home_raw"] == "FC Man City (ENG)")]
    assert len(odd) == 1 and odd["home_key"].iloc[0] == "ENG|man city" and not odd["home_mapped"].iloc[0]
    f = m[(m["comp"] == "FAC")].drop(index=odd.index)
    assert len(f) == len(fa) and f["hthg"].notna().all() and set(f["source"]) == {"openfootball-kupa"}
    assert (f["home_key"] == "İngiltere|Man City").any() or (f["away_key"] == "İngiltere|Man City").any()
    assert any("openfootball/england/master/2021-22/facup.txt" in u for u in dl.requested)
    # 10 sezon geriye bakılsa da turnuvanın ilk dosya sezonundan (FA Cup 2018/19) öncesi istenmez
    assert any("2018-19/facup.txt" in u for u in dl.requested)
    assert not any("2017-18/facup.txt" in u or "2016-17/facup.txt" in u for u in dl.requested)
    # Kimlik: Premier League adları depo kimliğine, amatörler ülke kapsamlı ayrı kimliğe
    j = f.merge(fa, on=["date", "home_key", "away_key"], suffixes=("", "_s"))
    assert len(j) == len(fa)
    for col in ("fthg", "ftag", "hthg", "htag", "home_mapped", "away_mapped"):
        assert (j[col] == j[f"{col}_s"]).all(), col
    assert set(f.loc[~f["home_mapped"], "home_key"]) <= {f"ENG|{n.lower().replace(' fc', '').replace(' afc', '')}"
                                                         for n in AMATEUR}
    assert f["provider_id"].str.startswith("openfootball/england:").all()
    assert f["home_raw"].str.endswith("(ENG)").all()  # ülke turnuvadan
    assert res.warnings == []
    recs = {(r["turnuva"], r["sezon"]): r for r in res.meta["koken"]}
    r = recs[("FAC", "2023/24")]
    assert (r["depo"], r["yol"], r["klasor"]) == ("openfootball/england", "2023-24/facup.txt", "2023-24")
    raw = tmp_path / "raw"
    assert verify_cup_rows(m, res.meta["koken"], raw) == (True, [])
    # Kurcalama yakalanır: ilk yarı skoru değişirse satırlar dosyadan yeniden üretilemez
    bad = m.copy()
    i = bad.index[bad["comp"] == "FAC"][3]
    bad.loc[i, "hthg"] = bad.loc[i, "hthg"] + 1
    ok, why = verify_cup_rows(bad, res.meta["koken"], raw)
    assert not ok and any("FAC" in x for x in why)
    # Kayıttaki depo veya yol turnuvanınkiyle aynı değilse kabul edilmez
    wrong = [dict(x, depo="openfootball/europe") if x["turnuva"] == "FAC" else x for x in res.meta["koken"]]
    assert not verify_cup_rows(m, wrong, raw)[0]
    # KUPA-01 kayıtları (okuyucu v1, sezon klasörü alanı yok) aynı satırları ürettiği için doğrulanır
    old = [{k: v for k, v in dict(x, ayristirici="kupa-football-txt-v1").items() if k != "klasor"}
           for x in res.meta["koken"] if x["turnuva"] != "FAC"]
    uefa = m[m["comp"] != "FAC"]
    assert verify_cup_rows(uefa, old, raw) == (True, [])
    assert rows_sha256(f[f["season"] == "2023/24"]) == r["satir_ozeti"]


def test_mid_score_files_and_neutral_semifinals(w, tmp_path):
    fa = fa_cup(seasons=2)
    files = fa_files(fa, mid=True, extra={"2022-23": ["▪ Semifinals", "  Sat Apr 22 2023",
                                                      "    17:45  Arsenal FC                2-1 (1-1)  Chelsea FC"]})
    res, _ = _update(w, tmp_path, comps=("FAC",), fa=fa, domestic=files)
    f = res.matches
    assert len(f) == len(fa) + 1 and f["hthg"].notna().all()
    sf = f[f["stage"] == "Semifinals"].iloc[0]
    assert (sf["home"], sf["away"], sf["fthg"], sf["hthg"], bool(sf["neutral"])) == ("Arsenal", "Chelsea", 2, 1, True)
    assert not f.loc[f["stage"] == "Round 1", "neutral"].any()


def _espn_fa(fa: pd.DataFrame, season: str) -> list:
    from kupa_yardim import ESPN_ID

    out = []
    ids = {**ESPN_ID, **{n: str(900 + i) for i, n in enumerate(AMATEUR)}}
    for i, r in enumerate(fa[fa["season"] == season].itertuples(index=False)):
        d = pd.Timestamp(r.date).date()
        out.append((d, espn_event(f"F{i}", d, r.home, r.away, ids[r.home], ids[r.away], (int(r.fthg), int(r.ftag)),
                                  (int(r.hthg), int(r.htag)))))
    return out


@pytest.mark.parametrize("complete", [True, False])
def test_incomplete_openfootball_season_is_taken_from_espn(w, tmp_path, complete):
    from bahis_tahmin.data.store import UpdateReport

    dom, cups = w
    fa = fa_cup()
    last = fa[fa["season"] == "2025/26"]
    keep = fa if complete else fa.drop(index=last.index[len(last) // 2:])  # finalsiz/eksik dosya
    espn = espn_world(dom, cups, TODAY)
    espn["eng.fa"] = _espn_fa(fa, "2025/26")
    res, _ = _update(w, tmp_path, comps=("FAC",), fa=fa, domestic=fa_files(keep), espn=espn,
                     allowed=("openfootball", "espn"))
    rep = res.report["FAC"]
    m = res.matches[res.matches["season"] == "2025/26"]
    if complete:
        assert rep["kaynak"]["2025/26"] == "openfootball" and "eksik_openfootball" not in rep
        assert set(m["source"]) == {"openfootball-kupa"} and len(m) == len(last)
    else:
        assert rep["kaynak"]["2025/26"] == "espn" and set(m["source"]) == {"espn"} and len(m) == len(last)
        assert rep["eksik_openfootball"] == {"2025/26": {"openfootball": len(last) // 2, "espn": len(last)}}
        assert "openfootball dosyası eksik" in UpdateReport(kupa=res.report).summary()
    assert rep["kaynak"]["2024/25"] == "openfootball"  # ESPN'de olmayan bitmiş sezon her durumda openfootball


# =============================================================================================== ölçüm


@pytest.fixture(scope="module")
def trained(w):
    from bahis_tahmin.kupa.motor import CupEngine

    dom, cups = w
    both = pd.concat([cups, fa_cup()], ignore_index=True)
    e_both, e_uefa = CupEngine(), CupEngine()
    e_both.train(dom, both)
    e_uefa.train(dom, cups)
    return e_both, e_uefa, both


def test_baselines_and_share_come_from_the_validation_group(trained):
    from bahis_tahmin.kupa.gol import first_half_share, ht_mask

    e_both, e_uefa, both = trained
    ev = e_both.oos
    assert set(ev["vgroup"]) == {"UEFA", "YURTICI"}
    cd = pd.to_datetime(both["date"])
    y = np.where(both["fthg"] > both["ftag"], 0, np.where(both["fthg"] == both["ftag"], 1, 2))
    grp = np.where(both["comp"] == "FAC", "YURTICI", "UEFA")
    for (season, vg), g in ev.groupby(["season", "vgroup"]):
        start = ev.loc[ev["season"] == season, "date"].min()
        before = (cd < start).to_numpy() & (grp == vg)
        if before.sum() < 30:
            before = (cd < start).to_numpy()
        want = np.bincount(y[before], minlength=3) / before.sum()
        np.testing.assert_allclose(g[["b_h", "b_d", "b_a"]].to_numpy(), np.tile(want, (len(g), 1)), atol=1e-12)
    # Yurt içi kupanın (deplasman ağırlıklı) tabanı UEFA tabanından farklı
    last = ev[ev["season"] == ev["season"].max()]
    assert last.loc[last["vgroup"] == "YURTICI", "b_a"].iloc[0] > last.loc[last["vgroup"] == "UEFA", "b_a"].iloc[0]
    # UEFA'nın tabanları yurt içi kupa eklenince değişmez (gol pazarları dahil)
    key = ["comp", "date", "home_key", "away_key"]
    a = e_both.oos[e_both.oos["vgroup"] == "UEFA"].set_index(key)[["b_h", "b_d", "b_a"]]
    b = e_uefa.oos.set_index(key)[["b_h", "b_d", "b_a"]]
    common = a.index.intersection(b.index)
    assert len(common) > 100
    np.testing.assert_allclose(a.loc[common].to_numpy(), b.loc[common].to_numpy(), atol=1e-12)
    ga = e_both.goal.oos[e_both.goal.oos["vgroup"] == "UEFA"].set_index(key)[["bA", "bB", "bC"]]
    gb = e_uefa.goal.oos.set_index(key)[["bA", "bB", "bC"]]
    common = ga.index.intersection(gb.index)
    np.testing.assert_allclose(ga.loc[common].to_numpy(), gb.loc[common].to_numpy(), atol=1e-12)
    # İlk yarı payı: grup başına; UEFA'nınki yalnızca UEFA kupalarından
    sh = e_both.goal.share_by_group
    uefa = both[both["comp"] != "FAC"]
    assert abs(sh["UEFA"] - first_half_share(uefa[ht_mask(uefa)])) < 1e-12
    assert abs(sh["UEFA"] - e_uefa.goal.share_by_group["UEFA"]) < 1e-12
    fa = both[both["comp"] == "FAC"]
    assert abs(sh["YURTICI"] - first_half_share(fa[ht_mask(fa)])) < 1e-12
    # Tahmin, turnuvanın grubunun payını kullanır
    day = pd.Timestamp("2026-11-07")
    p_fa = e_both.predict_goals("FAC", "İngiltere|Arsenal", "İngiltere|Chelsea", "Arsenal", "Chelsea", "İngiltere",
                                "İngiltere", day, "15:00", False, "espn", with_interval=False)
    p_cl = e_both.predict_goals("UCL", "İngiltere|Arsenal", "Türkiye|Galatasaray", "Arsenal", "Galatasaray",
                                "İngiltere", "Türkiye", day, "21:00", False, "espn", with_interval=False)
    assert p_fa.info["share"] == sh["YURTICI"] and p_cl.info["share"] == sh["UEFA"]
    assert p_fa.info["validation_group"] == "YURTICI" and p_fa.validated == e_both.goal.validated["YURTICI"]
    from bahis_tahmin.kupa.motor import VALIDATION_RULE

    assert e_both.report.groups["YURTICI"]["n"] > 0 and VALIDATION_RULE.startswith("kupa-dogrulama-v2")

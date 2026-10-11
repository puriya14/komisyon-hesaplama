"""S6-OLAY-02: kayıtlı araştırmadan çoklu olay öncesi/sonrası karşılaştırması.

Bütün testler açıkça sentetik satırlarla (bellekteki arşiv nesnesi veya geçici klasörde sentetik hazırlanmış arşiv) ve
geçici çalışma alanlarıyla çalışır; gerçek veri, ağ veya kullanıcı dosyası gerekmez.
"""

from __future__ import annotations

import datetime as dt
import json
import socket

import numpy as np
import pytest

from bahis_tahmin import archive as A
from bahis_tahmin import calisma as C
from bahis_tahmin import olay_karsilastirma as O
from bahis_tahmin.data import source_registry
from test_s5_arsiv_02 import archive, of, rows, sb
from test_s6_calisma import FORBIDDEN, all_keys, snapshot_dir

OF, SB = "openfootball-sonuc", "statsbomb-acik"
ARS = "Arsenal FC"
TEAMS = (ARS, "Chelsea FC", "Everton FC", "Stoke City FC")
# 4 takımlı çift devre: 6 hafta × 2 maç; her takım sezonda 6 maç (normal sezon = 2(n−1)). Arsenal her hafta j=0
# maçında: ev (hafta 0, 2, 4) ve deplasman (hafta 1, 3, 5).
ROUNDS = (((0, 1), (2, 3)), ((2, 0), (1, 3)), ((0, 3), (1, 2)), ((1, 0), (3, 2)), ((0, 2), (3, 1)), ((3, 0), (2, 1)))
HOME_21 = ((2, 1), (0, 1))  # İY 0-1, MS 2-1: ham İY/MS 2/1


def season(year: int, special=None, drop=(), label=None, src=of, teams=TEAMS, league="E0"):
    """Sentetik lig-sezonu. Varsayılan skorlarda Arsenal'in İY/MS 2/1 maçı yoktur; ``special`` {(hafta, sıra): (MS, İY
    veya None)} belirli maçları verir (İY None = ilk yarı skoru yok)."""
    special = special or {}
    label = label or f"{year}/{(year + 1) % 100:02d}"
    out = []
    for i, rnd in enumerate(ROUNDS):
        day = (dt.date(year, 8, 8) + dt.timedelta(days=7 * i)).isoformat()
        for j, (h, a) in enumerate(rnd):
            if (i, j) in drop:
                continue
            if (i, j) in special:
                ft, ht = special[(i, j)]
            else:
                ft = ((year + i + j) % 3, (year + 2 * i + j) % 2)
                ht = (min(ft[0], (i + j) % 2), min(ft[1], j % 2))
            out.append(src(day, teams[h], teams[a], ft, ht, season=label, league=league))
    return out


def eid(day: str, home: str, away: str, league="E0") -> str:
    return f"{league}|{day}|{home}|{away}"


# Arsenal'in üç İY/MS 2/1 olayı: 2014-09-05 ev (İY geride MS galip), 2015-08-22 ev, 2015-08-29 deplasman (İY önde MS
# mağlup). 2015/16 arşivin son sezonu.
DATA = season(2014, {(4, 0): HOME_21}) + season(2015, {(2, 0): HOME_21, (3, 0): HOME_21})
E14 = eid("2014-09-05", ARS, "Everton FC")
E_HOME = eid("2015-08-22", ARS, "Stoke City FC")
E_AWAY = eid("2015-08-29", "Chelsea FC", ARS)
EVENTS = [E14, E_HOME, E_AWAY]
G_2015 = {"lig": "E0", "sezonlar": ["2015/16"], "takim": ARS, "sonuc": {"iy_ms": ["HTFT_2_1"]}}
G_ALL = {"lig": "E0", "takim": ARS, "sonuc": {"iy_ms": ["HTFT_2_1"]}}


def ar(recs=DATA, **kw):
    return archive(rows(*recs), **kw)


def sb_copy(x, ht=None):
    """openfootball satırının aynı MS'li StatsBomb kopyası (kaynağın kendi takım adlarıyla)."""
    def name(t):
        return t.replace(" FC", "")
    return sb(x["date"], name(x["home"]), name(x["away"]), (x["fthg"], x["ftag"]),
              ht if ht is not None else ((x["hthg"], x["htag"]) if x["hthg"] is not None else None), season=x["season"])


def of_row(day, away=None, home=None):
    return next(x for x in DATA if x["date"] == day and (away is None or x["away"] == away)
                and (home is None or x["home"] == home))


def explicit(a, ids=EVENTS, kaynak="openfootball", **kw):
    return O.olay_karsilastir(a, ARS, kaynak=kaynak, olaylar=list(ids), **kw)


def ws_with_run(tmp_path, a, **tanim):
    ws = C.CalismaAlani.olustur_veya_ac(tmp_path / "ws")
    t = {"baslik": "Arsenal 2/1", "kaynak": "openfootball", "grup_1": G_2015, "grup_2": G_ALL}
    t.update(tanim)
    rid = ws.arastirma_olustur(t)["arastirma_id"]
    run = ws.calistir(a, rid)
    return ws, rid, run


def observed(ev, side):
    return [p for p in ev["konumlar"] if p["durum"] == "GOZLENDI" and p["konum"].startswith(side)]


def by_id(res, e):
    return next(x for x in res["olaylar"] if x["olay_kimligi"] == e)


def old_event_card_for(archive_, mac_kimligi, team, kaynak=None, liste_filtresi=None):
    """S6-OLAY-02 öncesi ``archive.event_card_for`` gövdesi (geriye uyum karşılaştırması için birebir kopya)."""
    from bahis_tahmin.data.parsers import MATCH_COLUMNS
    from bahis_tahmin.sequences.timeline import build_team_matches, event_card

    v = A.view(archive_, kaynak)
    merged = v.merged
    row = merged[merged["mac_kimligi"] == mac_kimligi]
    lg = row["league"].iloc[0]
    m = merged[(merged["league"] == lg) & (merged["durum"] == "TAMAM")].copy()
    m["source"] = m["kaynaklar"]
    tm = build_team_matches(m.reindex(columns=MATCH_COLUMNS))
    hit = tm.index[(tm["event_id"] == mac_kimligi) & (tm["team_raw"] == team)]
    card = event_card(tm, int(hit[0]), data_meta={"updated_at": archive_.catalog.get("olusturma_utc")})
    card["gorunum"] = A._card_scope(card, v, liste_filtresi)
    return card


# ----------------------------------------------------------------------------- 1, 20: tekil kartla tutarlılık

@pytest.mark.parametrize("once,sonra", [(5, 3), (10, 5), (5, 1)])
def test_multi_event_windows_match_existing_single_cards(once, sonra):
    a = ar()
    res = explicit(a, once=once, sonra=sonra)
    assert [e["olay_kimligi"] for e in res["olaylar"]] == EVENTS
    for ev in res["olaylar"]:
        card = A.event_card_for(a, ev["olay_kimligi"], ARS, kaynak="openfootball")
        pre, post = card["PRE_EVENT"][f"onceki_{once}"], card["POST_EVENT"][f"sonraki_{sonra}"]
        assert [p["olay_kimligi"] for p in observed(ev, "t-")] == [r["event_id"] for r in pre["maclar"]]
        assert [p["olay_kimligi"] for p in observed(ev, "t+")] == [r["event_id"] for r in post["maclar"]]
        assert ev["onceki"]["durum"] == pre["durum"] and ev["sonraki"]["durum"] == post["durum"]
        assert len(ev["konumlar"]) == once + 1 + sonra
        assert [p["konum"] for p in ev["konumlar"]] == ([f"t-{k}" for k in range(once, 0, -1)] + ["t0"]
                                                        + [f"t+{k}" for k in range(1, sonra + 1)])
        out = card["EVENT_OUTCOME"]
        tp = ev["takim_perspektifi"]
        assert (tp["iy_ms_ham"], tp["takim_iy"], tp["takim_ms"]) == (out["iy_ms_ham"], out["takim_iy"], out["takim_ms"])
        assert (tp["iy_skor_takim"], tp["ms_skor_takim"]) == (out["iy_takim"], out["ms_takim"])
        assert ev["kaynak"] == card["kaynak"]
        for p, r in zip(observed(ev, "t-"), pre["maclar"]):  # aynı kayıt, aynı perspektif
            assert (p["tarih"], p["ev_sahibi"], p["takim_iy"], p["takim_ms"]) == (
                str(r["date"])[:10], bool(r["is_home"]), r["ht_res"], r["ft_res"])


def test_single_card_output_unchanged_and_labels_from_central_registry():
    recs = DATA + [{**sb_copy(of_row("2015-08-15", away=ARS)), "xg_h": 0.4, "xg_a": 1.9}]
    a = ar(recs)
    for kaynak in ("openfootball", None, "hudl"):
        v = A.view(a, kaynak)
        ids = [m for m in v.merged["mac_kimligi"] if ARS in m or "Arsenal" in m][:8]
        team = ARS if kaynak != "hudl" else "Arsenal"
        for m in ids:
            for flt in (None, {"sezon": "2015/16"}, {"takim": ARS, "yer": "ev"}):
                new = A.event_card_for(a, m, team, kaynak=kaynak, liste_filtresi=flt)
                assert C.canon(new) == C.canon(old_event_card_for(a, m, team, kaynak, flt))
    # Pozisyonlardaki A/B/C ve İY/MS merkezi pazar kaydının (archive.labelled) değerleriyle aynı
    res = explicit(a)
    lab = A.labelled(A.view(a, "openfootball").merged).set_index("mac_kimligi")
    seen = 0
    for ev in res["olaylar"]:
        for p in ev["konumlar"]:
            if p["durum"] != "GOZLENDI":
                continue
            row = lab.loc[p["olay_kimligi"]]
            for k in ("A", "B", "C"):
                assert p[k] == (None if np.isnan(row[k]) else int(row[k]))
            assert p["iy_ms_ham"] == row["iy_ms"]
            seen += 1
    assert seen >= 15


# ----------------------------------------------------------------------------- 2, 3: saklı çalıştırma yolu

def test_stored_run_uses_its_own_revision_definition_and_event_set(tmp_path):
    a = ar()
    ws, rid, run = ws_with_run(tmp_path, a)
    ws.arastirma_revize(rid, {"grup_1": {**G_2015, "sonuc": {"iy_ms": ["HTFT_1_1"]}}})  # yeni revizyon: başka seçim
    res = O.olay_karsilastir(a, ARS, alan=ws, calistirma_id=run["calistirma_id"], grup=1)
    s = res["secim"]
    assert res["durum"] == "TAMAMLANDI" and s["tur"] == O.MODE_STORED and s["revizyon"] == 1
    assert s["grup_filtresi"] == run["tanim"]["grup_1"] and s["sonuca_gore_secildi"] is True
    assert s["olay_kumesi_ozeti"] == run["olay_kumeleri"]["1"]["olay_ozeti"] and s["grup_olay_sayisi"] == 2
    assert [e["olay_kimligi"] for e in res["olaylar"]] == [E_HOME, E_AWAY]
    assert res["veri"]["veri_ozeti"] == run["veri"]["veri_ozeti"]
    assert res["gorunum"]["kaynak"] == OF and res["sayfalama"]["toplam_aday"] == 2
    assert any(w["kod"] == C.SELECTED_BY_OUTCOME for w in res["uyarilar"])
    g2 = O.olay_karsilastir(a, ARS, alan=ws, calistirma_id=run["calistirma_id"], grup="2")
    assert [e["olay_kimligi"] for e in g2["olaylar"]] == EVENTS
    run2 = ws.calistir(a, rid)  # revizyon 2'nin çalıştırması kendi (farklı) olay kümesini kullanır
    r2 = O.olay_karsilastir(a, ARS, alan=ws, calistirma_id=run2["calistirma_id"], grup=1)
    assert r2["secim"]["revizyon"] == 2 and E_HOME not in [e["olay_kimligi"] for e in r2["olaylar"]]
    with pytest.raises(C.DogrulamaHatasi):
        O.olay_karsilastir(a, ARS, alan=ws, calistirma_id=run["calistirma_id"], grup=3)
    rid1 = ws.arastirma_olustur({"baslik": "tek grup", "kaynak": "openfootball", "grup_1": G_2015})["arastirma_id"]
    one = ws.calistir(a, rid1)
    with pytest.raises(C.DogrulamaHatasi, match="grup 2 yok"):
        O.olay_karsilastir(a, ARS, alan=ws, calistirma_id=one["calistirma_id"], grup=2)


def test_changed_data_is_not_silently_used_for_stored_run(tmp_path):
    a = ar()
    ws, rid, run = ws_with_run(tmp_path, a)
    before = ws.calistirma(run["calistirma_id"], olaylar=True)
    changed = [dict(x) for x in DATA]
    changed[-1] = of("2015-09-12", "Stoke City FC", ARS, (0, 4), (0, 2), season="2015/16")
    res = O.olay_karsilastir(ar(changed), ARS, alan=ws, calistirma_id=run["calistirma_id"], grup=1)
    assert res["durum"] == "VERI_SURUMU_DEGISTI" and res["olaylar"] == []
    assert res["sakli_veri_ozeti"] == run["veri"]["veri_ozeti"] != res["guncel_veri_ozeti"]
    assert "toplu" not in res and "ortusme" not in res and "yeni veriyle hesaplanmadı" in res["metin"]
    assert ws.calistirma(run["calistirma_id"], olaylar=True) == before
    assert ws.conn.execute("SELECT COUNT(*) FROM calistirmalar").fetchone()[0] == 1


# ----------------------------------------------------------------------------- 4, 5: açık liste ve kimlik

def test_explicit_list_is_deduplicated_and_sorted_deterministically():
    a = ar()
    ref = explicit(a)
    dup = explicit(a, ids=[E_AWAY, E14, E_HOME, E14, E_AWAY])
    assert dup["secim"]["tur"] == O.MODE_MANUAL and dup["secim"]["girdi_olay_sayisi"] == 5
    assert dup["secim"]["tekil_olay_sayisi"] == 3 and dup["secim"]["tekrar_eden_girdi"] == 2
    assert [e["olay_kimligi"] for e in dup["olaylar"]] == EVENTS  # tarih, sonra kimlik sırası
    assert {k: v for k, v in dup.items() if k not in ("secim", "sonuc_ozeti")} == {
        k: v for k, v in ref.items() if k not in ("secim", "sonuc_ozeti")}
    assert dup["secim"]["olay_kumesi_ozeti"] == ref["secim"]["olay_kumesi_ozeti"]
    assert any(w["kod"] == O.MODE_MANUAL for w in dup["uyarilar"]) and "ön-kayıt" in dup["secim"]["aciklama"]


def test_no_mixing_of_teams_leagues_or_unresolved_identities():
    e1 = season(2016, league="E1", teams=(ARS, "Leeds United FC", "Derby County FC", "Hull City FC"))
    unresolved = [sb("2015-08-22", "Arsenal", "Arsenal Women", (1, 0)),
                  sb("2015-08-29", "Chelsea U21", "Arsenal", (0, 0))]
    a = ar(DATA + e1 + unresolved)
    with pytest.raises(C.DogrulamaHatasi, match="Benzer ad eşlemesi yapılmaz"):
        O.olay_karsilastir(a, "Arsenal", kaynak="openfootball", olaylar=EVENTS)
    e1_id = eid("2016-08-08", ARS, "Leeds United FC", "E1")
    with pytest.raises(C.DogrulamaHatasi, match="birden çok ligde"):
        explicit(a, ids=EVENTS + [e1_id])
    res = explicit(a, ids=EVENTS + [e1_id, eid("2015-08-08", "Everton FC", "Stoke City FC"), "E0|yok|x|y"], lig="E0")
    reasons = {x["olay_kimligi"]: x["neden"] for x in res["gecersiz_olaylar"]}
    assert reasons == {e1_id: "LIG_KAPSAMI_DISI", "E0|yok|x|y": "GORUNUMDE_YOK",
                       eid("2015-08-08", "Everton FC", "Stoke City FC"): "TAKIM_BU_MACTA_YOK"}
    assert [e["olay_kimligi"] for e in res["olaylar"]] == EVENTS and res["takim"]["lig"] == "E0"
    assert all(p["olay_kimligi"].startswith("E0|") for e in res["olaylar"] for p in e["konumlar"]
               if p["durum"] == "GOZLENDI")
    # Birleştirilmiş görünüm: kimliği kesinleşmeyen kaynak satırları pencereye girmez, ayrıca sayılır
    m = O.olay_karsilastir(a, ARS, kaynak="birlesik", olaylar=EVENTS, lig="E0")
    assert m["kimlik_incelemesi"]["takim_kaynak_satiri"] >= 1
    win = {p["olay_kimligi"] for e in m["olaylar"] for p in e["konumlar"] if p["durum"] == "GOZLENDI"}
    assert not any("Women" in x or "U21" in x for x in win)
    assert {e["takim_perspektifi"]["rakip"] for e in m["olaylar"]} <= set(TEAMS)


# ----------------------------------------------------------------------------- 6, 7, 8: perspektif ve pencereler

def test_home_and_away_perspective_of_same_raw_code_are_not_merged():
    res = explicit(ar())
    home, away = by_id(res, E_HOME)["takim_perspektifi"], by_id(res, E_AWAY)["takim_perspektifi"]
    assert home["iy_ms_ham"] == away["iy_ms_ham"] == "HTFT_2_1"
    assert (home["yer"], home["takim_iy"], home["takim_ms"], home["takim_iy_ms"]) == ("ev", "M", "G",
                                                                                       "IY_GERIDE_MS_GALIP")
    assert (away["yer"], away["takim_iy"], away["takim_ms"], away["takim_iy_ms"]) == ("deplasman", "G", "M",
                                                                                       "IY_ONDE_MS_MAGLUP")
    assert (home["ilk_yari_atilan"], home["ilk_yari_yenilen"], home["ikinci_yari_atilan"],
            home["ikinci_yari_yenilen"]) == (0, 1, 2, 0)
    assert (away["ilk_yari_atilan"], away["ilk_yari_yenilen"], away["ikinci_yari_atilan"],
            away["ikinci_yari_yenilen"]) == (1, 0, 0, 2)
    assert (home["iy_skor_takim"], home["ms_skor_takim"]) == ("0-1", "2-1")
    assert (away["iy_skor_takim"], away["ms_skor_takim"]) == ("1-0", "1-2")
    assert home["rakip"] == "Stoke City FC" and away["rakip"] == "Chelsea FC"


def test_event_itself_is_excluded_from_pre_and_post_summaries():
    res = explicit(ar(), ids=[E_HOME])
    ev = res["olaylar"][0]
    t0 = [p for p in ev["konumlar"] if p["konum"] == "t0"]
    assert len(t0) == 1 and t0[0]["olay_kimligi"] == E_HOME
    for side, key in (("t-", "onceki"), ("t+", "sonraki")):
        obs = observed(ev, side)
        assert E_HOME not in [p["olay_kimligi"] for p in obs]
        s = ev[key]
        assert s["gozlenen_kayit"] == len(obs)
        valid = [p for p in obs if p["takim_ms"] is not None]
        assert s["gol"]["atilan"] == sum(int(p["ms_skor_takim"].split("-")[0]) for p in valid)
        assert s["gol"]["yenilen"] == sum(int(p["ms_skor_takim"].split("-")[1]) for p in valid)
        assert s["takim_ms"]["G"] + s["takim_ms"]["B"] + s["takim_ms"]["M"] == len(valid)
    assert res["toplu"]["olaylar"]["gozlenen_kayit"] == 1 and res["toplu"]["olaylar"]["takim_ms"]["G"] == 1
    assert res["toplu"]["onceki"]["gozlenen_kayit"] == ev["onceki"]["gozlenen_kayit"]


def test_selection_filter_does_not_narrow_windows(tmp_path):
    a = ar()
    ws, _, run = ws_with_run(tmp_path, a)
    res = O.olay_karsilastir(a, ARS, alan=ws, calistirma_id=run["calistirma_id"], grup=1)
    ev = by_id(res, E_HOME)
    pre = observed(ev, "t-")
    assert len(pre) == 5 and ev["onceki"]["durum"] == "COMPLETE"
    assert any(p["iy_ms_ham"] != "HTFT_2_1" for p in pre)  # 2/1 seçimi pencereyi daraltmaz
    assert any(p["sezon"] == "2014/15" for p in pre)  # grup yalnızca 2015/16 iken pencere önceki sezona taşar
    k = res["pencere_kapsami"]
    assert "2014/15" in k["pencere_sezonlari"] and k["secim_sezonlari"] == ["2015/16"]
    assert k["secim_filtresi_disi_pencere_maci"] >= 3 and k["secim_kumesi_disi_pencere_maci"] >= 5
    assert k["secim_tarih_araligi"] == ["2015-08-22", "2015-08-29"] and k["secim_tarih_araligi_disi_pencere_maci"] >= 5
    assert {p["secim_filtresinde"] for p in pre} == {False, True}
    assert "daraltmaz" in k["not"]


# ----------------------------------------------------------------------------- 9, 10, 13: eksik veri

def test_season_skip_incomplete_season_missing_ht_and_awarded_are_preserved():
    skip = ar(season(2014, {(4, 0): HOME_21}, label="2013/14") + season(2015, {(2, 0): HOME_21}))
    e13 = eid("2014-09-05", ARS, "Everton FC")
    res = explicit(skip, ids=[e13, E_HOME])
    assert by_id(res, E_HOME)["onceki"]["durum"] == "SEASON_SKIP"
    assert by_id(res, E_HOME)["onceki"]["ardisiklik"] == O.ORDER_NOTE
    iv = res[O.INTERVAL_KEY][1]
    assert iv["onceki_secili_olay"] == e13 and "SEZON_ATLAMASI" in {f["kod"] for f in iv["isaretler"]}
    assert iv["dogrulanmis_oynanan_mac"] is None and iv["arsivde_gozlenen_kayit"] == 3

    incomplete = ar(season(2014) + season(2015, {(2, 0): HOME_21}, drop={(1, 1)}) + season(2016))
    res = explicit(incomplete, ids=[E_HOME])
    ev = res["olaylar"][0]
    assert ev["onceki"]["durum"] == "INCOMPLETE_SEASON" and not ev["onceki"]["tam_pencere"]
    assert ev["onceki"]["gozlenen_kayit"] == 5  # gözlenen kayıtlar gösterilir, tam pencere sayılmaz

    gaps = ar(season(2014, {(4, 0): HOME_21, (5, 0): ((3, 0), None)}) + season(2015, {(3, 0): ((1, 1), None)}))
    res = explicit(gaps, ids=[E14, eid("2015-09-12", "Stoke City FC", ARS)])
    post = by_id(res, E14)["sonraki"]
    assert post["durum"] == "POSSIBLE_AWARDED"
    awarded = [p for p in observed(by_id(res, E14), "t+") if p["hukmen_olabilir"]]
    assert len(awarded) == 1 and awarded[0]["takim_ms"] is None and awarded[0]["ms_skor_takim"] == "0-3"
    assert post["kullanilabilir_mac"] == 2 and post["sonucu_bilinmeyen_kayit"] == 1 and post["gol"]["gecerli_mac"] == 2
    last = by_id(res, eid("2015-09-12", "Stoke City FC", ARS))
    assert last["onceki"]["durum"] == "HT_MISSING"
    miss = [p for p in observed(last, "t-") if p["ilk_yari_skoru_yok"]]
    assert len(miss) == 1 and miss[0]["A"] is None and miss[0]["C"] is None and miss[0]["B"] is not None
    assert miss[0]["ilk_yari_atilan"] is None and miss[0]["ikinci_yari_atilan"] is None
    s = last["onceki"]
    assert s["ilk_yari_gol"]["gecerli_mac"] == 4 and s["pazarlar"]["A"]["gecerli"] == 4
    assert s["pazarlar"]["A"]["bilinmiyor"] == 1 and s["pazarlar"]["B"]["gecerli"] == 5


def test_missing_matches_at_archive_end_are_not_counted_as_zero_or_loss():
    blocks = [{"kaynak": OF, "lig": "E0", "sezon": "2014/15", "dosya_sha256": "x1", "satir_ozeti": "y1", "yol": "a",
               "blok": 0, "kapsam": "TAM", "oynanmamis": 0, "tarihi_gecmis_sonucsuz": 0},
              {"kaynak": OF, "lig": "E0", "sezon": "2015/16", "dosya_sha256": "x2", "satir_ozeti": "y2", "yol": "b",
               "blok": 0, "kapsam": "KISMI", "oynanmamis": 2, "tarihi_gecmis_sonucsuz": 1}]
    res = explicit(ar(blocks=blocks))
    ev = by_id(res, E_AWAY)
    s = ev["sonraki"]
    assert s["durum"] == "RIGHT_CENSORED" and s["gozlenen_kayit"] == 2 and s["eksik_konum"] == 1
    assert not s["tam_pencere"] and ev["konumlar"][-1] == {**ev["konumlar"][-1], "konum": "t+3", "durum": "KAYIT_YOK",
                                                           "neden": "RIGHT_CENSORED"}
    obs = observed(ev, "t+")
    assert s["kullanilabilir_mac"] == 2 and s["takim_ms"]["M"] == sum(p["takim_ms"] == "M" for p in obs)
    assert s["gol"]["atilan"] == sum(int(p["ms_skor_takim"].split("-")[0]) for p in obs)
    assert {r["kod"] for r in s["sonraki_kayit_yok"]} == {"HENUZ_OYNANMAMIS_OLABILIR", "KAYNAK_GUNCEL_DEGIL_OLABILIR"}
    # Tam görünen pencere, kaynağın kısmi işaretlediği sezona değiyorsa çelişki açıkça yazılır
    post14 = by_id(res, E14)["sonraki"]
    assert post14["durum"] == "COMPLETE" and post14["celiski"]["kod"] == "PENCERE_TAM_AMA_KAYNAKTA_BILINEN_BOSLUK"
    assert [g["sezon"] for g in post14["bilinen_kaynak_bosluklari"]] == ["2015/16"]
    assert post14["ardisiklik"] == O.COMPLETE_ORDER_NOTE and "bağımsız tamlık kanıtı değildir" in O.COMPLETE_ORDER_NOTE


def test_zero_denominators_are_null_not_zero():
    a = ar(season(2014) + season(2015, {(1, 0): ((1, 1), None)}))
    first = eid("2014-08-08", ARS, "Chelsea FC")
    res = explicit(a, ids=[first], sonra=1)
    pre = res["olaylar"][0]["onceki"]
    assert pre["gozlenen_kayit"] == 0 and pre["eksik_konum"] == 5 and pre["durum"] == "DATA_START"
    assert all(pre["pazarlar"][k]["oran"] is None and pre["pazarlar"][k]["gecerli"] == 0 for k in "ABC")
    assert pre["gol"] == {"gecerli_mac": 0, "atilan": None, "yenilen": None}
    assert all(p["durum"] == "KAYIT_YOK" and p["neden"] == "DATA_START" for p in res["olaylar"][0]["konumlar"][:5])
    res2 = explicit(a, ids=[eid("2015-08-08", ARS, "Chelsea FC")], sonra=1)
    post = res2["olaylar"][0]["sonraki"]
    assert post["gozlenen_kayit"] == 1 and post["pazarlar"]["A"] == {"evet": 0, "gecerli": 0, "bilinmiyor": 1,
                                                                    "oran": None}
    assert post["pazarlar"]["B"]["gecerli"] == 1 and post["ilk_yari_gol"]["atilan"] is None


# ----------------------------------------------------------------------------- 11, 12: ortak pencere maçları

def test_match_in_several_windows_is_counted_once():
    res = explicit(ar())
    o = res["ortusme"]
    assert o["toplam_pencere_konumu"] == sum(len(observed(e, "t-")) + len(observed(e, "t+")) for e in res["olaylar"])
    assert o["benzersiz_mac"] < o["toplam_pencere_konumu"]
    shared = {x["olay_kimligi"]: x["pencere_sayisi"] for x in o["birden_fazla_pencerede"]}
    assert shared[eid("2015-08-08", ARS, "Chelsea FC")] == 3  # E14 sonrası, E_HOME ve E_AWAY öncesi
    assert all(n >= 2 for n in shared.values())
    assert res["toplu"]["onceki"]["gozlenen_kayit"] == o["onceki_benzersiz"]
    assert res["toplu"]["sonraki"]["gozlenen_kayit"] == o["sonraki_benzersiz"]
    assert o["onceki_ve_sonraki_ortak"] >= 1 and o["bagimsiz_ornek_degil"] and o["istatistiksel_test"] == "YAPILMADI"


def test_selected_event_inside_another_events_window_is_flagged():
    res = explicit(ar())
    home = by_id(res, E_HOME)
    nxt = [p for p in home["konumlar"] if p["konum"] == "t+1"][0]
    assert nxt["olay_kimligi"] == E_AWAY and nxt["secili_olay"] is True
    assert E_AWAY in home["penceresindeki_secili_olaylar"]
    assert {"olay": E_HOME, "taraf": "sonraki", "konum": "t+1"} in by_id(res, E_AWAY)["baska_olayin_penceresinde"]
    flagged = {x["olay_kimligi"] for x in res["ortusme"]["pencerede_secili_olay"]}
    assert flagged == {E14, E_HOME, E_AWAY}
    alone = explicit(ar(), ids=[E_AWAY])  # tek olayda diğerleri seçili değil
    assert not any(p.get("secili_olay") for p in alone["olaylar"][0]["konumlar"] if p["konum"] != "t0")


# ----------------------------------------------------------------------------- 14, 15: kaynak ve haklar

def test_single_source_view_does_not_carry_fields_from_other_sources():
    src = of_row("2015-08-15", away=ARS)
    ht = (src["fthg"], src["ftag"])  # StatsBomb'da İY var (MS'ye eşit), openfootball'da yok
    recs = [x if x is not src else {**x, "hthg": None, "htag": None} for x in DATA]
    recs.append({**sb_copy(src, ht), "xg_h": 0.4, "xg_a": 1.9, "sut_h": 5, "sut_a": 9})
    a = ar(recs)
    target = eid("2015-08-15", "Everton FC", ARS)
    single = explicit(a, ids=[E_HOME])
    p = [x for x in single["olaylar"][0]["konumlar"] if x.get("olay_kimligi") == target][0]
    assert p["ilk_yari_skoru_yok"] and p["iy_ms_ham"] is None and p["A"] is None and p["kaynak"] == OF
    assert p["alan_kokeni"] == "" and single["veri"]["kullanilan_kaynaklar"] == [OF]
    assert all(x["kaynak"] == OF for e in single["olaylar"] for x in e["konumlar"] if x["durum"] == "GOZLENDI")
    assert not any(k.startswith(("xg", "sut")) for k in all_keys(single))
    merged = explicit(a, ids=[E_HOME], kaynak="birlesik")
    q = [x for x in merged["olaylar"][0]["konumlar"] if x.get("olay_kimligi") == target][0]
    assert (q["iy_skor_takim"], q["kaynak"]) == (f"{ht[1]}-{ht[0]}", f"{OF},{SB}") and "İY: hudl" in q["alan_kokeni"]
    assert any(w["kod"] == "BIRLESTIRILMIS_GORUNUM" for w in merged["uyarilar"])


def test_closed_source_cannot_be_reached_through_stored_run_or_list(tmp_path, monkeypatch):
    a = ar(DATA + [sb_copy(x) for x in DATA])
    g = {"lig": "E0", "takim": "Arsenal"}
    ws, _, run = ws_with_run(tmp_path, a, kaynak="hudl", grup_1=g, grup_2=None)
    ok = O.olay_karsilastir(a, "Arsenal", alan=ws, calistirma_id=run["calistirma_id"], grup=1, limit=2)
    assert ok["durum"] == "TAMAMLANDI" and ok["sayfalama"]["toplam_aday"] == 12
    monkeypatch.setitem(source_registry.ARCHIVE_SCOPES[SB], "tarihsel_analiz", "DOGRULANAMADI")
    res = O.olay_karsilastir(a, "Arsenal", alan=ws, calistirma_id=run["calistirma_id"], grup=1)
    assert res["durum"] == "KULLANIM_KAPSAMI_KAPALI" and res["kapali_kaynaklar"] == [SB] and res["olaylar"] == []
    txt = json.dumps(res, ensure_ascii=False)
    assert "Arsenal|" not in txt and "|Arsenal" not in txt and "veri" not in res and "toplu" not in res
    assert "olay_kumesi_ozeti" not in res["secim"]
    closed = explicit(a, kaynak="datasets")
    assert closed["durum"] == "KULLANIM_KAPSAMI_KAPALI" and closed["olaylar"] == []


# ----------------------------------------------------------------------------- 16, 17: sıra ve sayfalama

def test_row_order_and_input_order_do_not_change_result():
    base = rows(*DATA)
    rng = np.random.default_rng(7)
    ref = None
    for _ in range(4):
        r = base.iloc[rng.permutation(len(base))].reset_index(drop=True)
        ids = list(np.array(EVENTS)[rng.permutation(3)])
        out = explicit(archive(r), ids=ids)
        key = (out["sonuc_ozeti"], C.canon(out))
        ref = ref or key
        assert key == ref


def test_limit_offset_are_explicit_stable_and_result_independent():
    a = ar()
    ids = [eid(x["date"], x["home"], x["away"]) for x in DATA if ARS in (x["home"], x["away"])]
    full = explicit(a, ids=ids, limit=50)
    assert full["sayfalama"]["toplam_aday"] == 12 and full["sayfalama"]["kalan"] == 0
    pages, off = [], 0
    while True:
        p = explicit(a, ids=ids, limit=5, offset=off)
        sp = p["sayfalama"]
        assert sp["limit"] == 5 and sp["offset"] == off and sp["siralama"] == O.SORT_RULE
        pages.append(p)
        if sp["sonraki_offset"] is None:
            break
        assert sp["kalan"] == 12 - sp["sonraki_offset"] and any(w["kod"] == "SAYFALAMA" for w in p["uyarilar"])
        off = sp["sonraki_offset"]
    assert [len(p["olaylar"]) for p in pages] == [5, 5, 2]
    keys = ("sira", "olay_kimligi", "takim_perspektifi", "konumlar", "onceki", "sonraki")
    flat = [e for p in pages for e in p["olaylar"]]
    assert [{k: e[k] for k in keys} for e in flat] == [{k: e[k] for k in keys} for e in full["olaylar"]]
    assert [x for p in pages for x in p[O.INTERVAL_KEY]] == full[O.INTERVAL_KEY]  # sayfa sınırında da aynı aralık
    assert explicit(a, ids=ids)["sayfalama"]["bu_sayfada"] == 12 and O.DEFAULT_LIMIT == 20
    for bad in ({"limit": 51}, {"limit": 0}, {"offset": -1}, {"once": 7}, {"sonra": 2}, {"limit": True}):
        with pytest.raises(C.DogrulamaHatasi):
            explicit(a, ids=ids, **bad)
    beyond = explicit(a, ids=ids, offset=40)
    assert beyond["olaylar"] == [] and beyond["sayfalama"]["kalan"] == 0


# ----------------------------------------------------------------------------- girdi hataları ve JSON

def test_conflicting_or_invalid_inputs_raise_validation_errors(tmp_path):
    a = ar()
    ws, _, run = ws_with_run(tmp_path, a)
    cid = run["calistirma_id"]
    cases = [dict(alan=ws, calistirma_id=cid, grup=1, olaylar=EVENTS),  # iki yol birden
             dict(),  # hiçbiri
             dict(alan=ws, calistirma_id=cid, grup=1, kaynak="openfootball"),
             dict(olaylar=EVENTS),  # görünüm açık değil
             dict(kaynak="openfootball", olaylar=EVENTS, grup=1),
             dict(kaynak="openfootball", olaylar="E0|x"),
             dict(kaynak="openfootball", olaylar=[]),
             dict(kaynak="yok", olaylar=EVENTS),
             dict(kaynak="openfootball", olaylar=EVENTS, lig="ZZ")]
    for kw in cases:
        with pytest.raises(C.DogrulamaHatasi):
            O.olay_karsilastir(a, ARS, **kw)
    with pytest.raises(C.DogrulamaHatasi):
        O.olay_karsilastir(a, " ", kaynak="openfootball", olaylar=EVENTS)
    with pytest.raises(C.CalismaError, match="bulunamadı"):
        O.olay_karsilastir(a, ARS, alan=ws, calistirma_id="cr_yok", grup=1)
    conflict = ar(DATA + [sb("2015-08-22", "Arsenal", "Stoke City", (3, 1), (0, 1))])
    res = O.olay_karsilastir(conflict, ARS, kaynak="birlesik", olaylar=EVENTS)
    assert {x["olay_kimligi"]: (x["neden"], x["durum"]) for x in res["gecersiz_olaylar"]} == {
        E_HOME: ("SKOR_DOGRULANMADI", "CELISKI")}
    assert res["gecersiz_ozeti"] == {"SKOR_DOGRULANMADI": 1} and len(res["olaylar"]) == 2


def test_json_is_finite_descriptive_and_free_of_decision_fields():
    res = explicit(ar(season(2014) + season(2015, {(1, 0): ((1, 1), None)})),
                   ids=[eid("2014-08-08", ARS, "Chelsea FC"), eid("2015-08-08", ARS, "Chelsea FC")])

    def reject(c):
        raise AssertionError(f"sonlu olmayan sayı: {c}")

    data = json.loads(C.to_json(res), parse_constant=reject)
    assert data == res and data["statu"] == C.STATUS == "DESCRIPTIVE_RESEARCH"
    keys = set(all_keys(res))
    assert not keys & FORBIDDEN
    assert "şike tespiti" in res["aciklamalar"][0]["metin"] and "öneri yoktur" in res["aciklamalar"][0]["metin"]
    assert "normal süre" in res["kapsam"]["lig_disi_maclar"] and "kupa" in res["kapsam"]["lig_disi_maclar"]
    assert res["kapsam"]["gorunum_tum_resmi"].startswith("DATA_QUALITY_BLOCKED")
    v = res["surumler"]
    assert v["olay_analiz_surumu"] == O.OLAY_ANALIZ_SURUMU and v["olay_kod_ozeti"] and v["analiz_surumu"]


def test_view_data_change_during_computation_is_not_mixed(monkeypatch):
    a = ar()
    orig = A.event_card_in
    calls = {"n": 0}

    def mutate(archive_, v, *args, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            v.rows.loc[0, "fthg"] = 9.0  # başka bir işlemin veriyi hesap ortasında değiştirmesi
        return orig(archive_, v, *args, **kw)

    monkeypatch.setattr(A, "event_card_in", mutate)
    with pytest.raises(C.CalismaError, match="karışık sonuç"):
        explicit(a)


# ----------------------------------------------------------------------------- 18, 19: salt okunur ve CLI

def test_cli_stored_and_explicit_paths_are_read_only(tmp_path, tmp_home, capsys, monkeypatch):
    from test_s5_github import build

    from bahis_tahmin.cli import main

    home, _, _ = build(tmp_path)  # sentetik arşiv: openfootball 2024/25 (Arsenal'in 2 maçı) + StatsBomb 2015/16
    ws = tmp_path / "calisma"
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    (pilot / "data_meta.json").write_text("{}")
    for name in ("settings.json", "matches.pkl", "goal_engine.joblib", "gol_pazarlari.sqlite"):
        (tmp_home / name).write_bytes(b"veri")

    def run(*argv):
        code = main(list(argv))
        cap = capsys.readouterr()
        return code, (json.loads(cap.out) if cap.out.strip().startswith("{") else cap.out), cap.err

    code, rec, _ = run("calisma-olustur", "--calisma", str(ws), "--baslik", "Arsenal 2024/25", "--kaynak",
                       "openfootball", "--g1-lig", "E0", "--g1-takim", ARS, "--g2-tum")
    assert code == 0
    code, runrec, _ = run("calisma-calistir", "--calisma", str(ws), "--ev", str(home), "--arastirma",
                          rec["arastirma_id"])
    assert code == 0
    cid = runrec["calistirma_id"]
    code, stored_before, _ = run("calisma-calistirma-oku", "--calisma", str(ws), "--calistirma", cid, "--olaylar")
    protected = snapshot_dir(home, pilot, tmp_home, ws)

    def no_net(*a, **k):
        raise AssertionError("salt okunur komut ağ isteği yaptı")

    monkeypatch.setattr(socket.socket, "connect", no_net)
    code, res, err = run("calisma-olay-karsilastir", "--calisma", str(ws), "--ev", str(home), "--calistirma", cid,
                         "--grup", "1", "--takim", ARS, "--once", "10", "--sonra", "1")
    assert code == 0, err
    assert res["durum"] == "TAMAMLANDI" and res["secim"]["calistirma_id"] == cid
    assert [e["olay_kimligi"] for e in res["olaylar"]] == ["E0|2024-08-17|Arsenal FC|Chelsea FC",
                                                          "E0|2024-08-24|Everton FC|Arsenal FC"]
    assert res["secenekler"]["once"] == 10 and len(res["olaylar"][0]["konumlar"]) == 12
    ids_file = tmp_path / "olaylar.txt"
    ids_file.write_text("# yorum\nE0|2024-08-24|Everton FC|Arsenal FC\n\nE0|2024-08-17|Arsenal FC|Chelsea FC\n",
                        encoding="utf-8")
    code, res2, err = run("calisma-olay-karsilastir", "--ev", str(home), "--kaynak", "openfootball", "--takim", ARS,
                          "--olay-dosyasi", str(ids_file), "--olay", "E0|2024-08-17|Arsenal FC|Chelsea FC")
    assert code == 0, err
    assert res2["secim"]["tekrar_eden_girdi"] == 1 and len(res2["olaylar"]) == 2
    assert res["olaylar"][0]["takim_perspektifi"] == res2["olaylar"][0]["takim_perspektifi"]
    for argv, want in [(("--calistirma", cid, "--grup", "1", "--olay", "x", "--kaynak", "openfootball"), 2),
                       (("--calistirma", cid), 2),
                       (("--olay", "x"), 2),
                       (("--kaynak", "openfootball", "--olay", "x", "--grup", "1"), 2),
                       (("--kaynak", "openfootball", "--olay", "x", "--limit", "60"), 2),
                       (("--kaynak", "openfootball", "--olay", "x", "--once", "3"), 2),
                       (("--calisma", str(tmp_path / "olmayan"), "--calistirma", cid, "--grup", "1"), 3)]:
        code, out, err = run("calisma-olay-karsilastir", "--ev", str(home), "--takim", ARS, *argv)
        assert code == want, (argv, err)
    assert not (tmp_path / "olmayan").exists()
    assert snapshot_dir(home, pilot, tmp_home, ws) == protected  # arşiv, pilot, uygulama ve çalışma alanı değişmedi
    code, stored_after, _ = run("calisma-calistirma-oku", "--calisma", str(ws), "--calistirma", cid, "--olaylar")
    assert stored_after == stored_before


def test_service_does_not_write_workspace_or_existing_records(tmp_path):
    a = ar()
    ws, rid, run = ws_with_run(tmp_path, a)
    ws.not_ekle(rid, "not", mac_kimligi=E_HOME, archive=a)
    db = tmp_path / "ws" / "calisma.sqlite"
    before = (snapshot_dir(tmp_path / "ws"), ws.arastirma(rid), ws.calistirma(run["calistirma_id"], olaylar=True))
    ro = C.CalismaAlani.ac(tmp_path / "ws")
    changes = ro.conn.total_changes
    for g in (1, 2):
        O.olay_karsilastir(a, ARS, alan=ro, calistirma_id=run["calistirma_id"], grup=g, once=10, sonra=5)
    assert ro.conn.total_changes == changes
    ro.close()
    after = (snapshot_dir(tmp_path / "ws"), ws.arastirma(rid), ws.calistirma(run["calistirma_id"], olaylar=True))
    assert after == before
    assert db.is_file() and ws.conn.execute("SELECT COUNT(*) FROM calistirmalar").fetchone()[0] == 1

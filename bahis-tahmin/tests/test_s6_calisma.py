"""S6-CALISMA-01: kayıtlı araştırmalar, revizyonlar, çalıştırma kaydı, notlar ve iki grup karşılaştırması.

Bütün testler açıkça sentetik satırlarla (bellekteki arşiv nesnesi veya geçici klasörde sentetik hazırlanmış arşiv) ve
geçici çalışma alanlarıyla çalışır; gerçek veri, ağ veya kullanıcı dosyası gerekmez.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bahis_tahmin import archive as A
from bahis_tahmin import calisma as C
from bahis_tahmin.data import source_registry
from test_s5_arsiv_02 import CONFLICT, archive, of, rows, sb, season_rows

OF, SB = "openfootball-sonuc", "statsbomb-acik"

# 2015/16 openfootball: Arsenal'in 4 maçı (biri İY'siz), StatsBomb: aynı ilk maç İY + xG ile
DATA = [
    of("2015-08-08", "Arsenal FC", "Chelsea FC", (2, 1)),                 # İY yok (openfootball)
    of("2015-08-15", "Everton FC", "Arsenal FC", (1, 3), (0, 1)),
    of("2015-08-22", "Arsenal FC", "Everton FC", (2, 2), (1, 1)),
    of("2015-08-29", "Arsenal FC", "Stoke City FC", (4, 0), (2, 0)),
    of("2015-09-05", "Chelsea FC", "Everton FC", (0, 0)),                  # MS 0-0 (mantıksal İY ayrıştırıcıda)
    sb("2015-08-08", "Arsenal", "Chelsea", (2, 1), (1, 0), xg_h=1.4, xg_a=0.6, sut_h=12, sut_a=7),
]
G_ARS_HOME = {"lig": "E0", "sezonlar": ["2015/16"], "takim": "Arsenal FC", "yer": "ev"}
G_ALL = {"lig": "E0", "sezonlar": ["2015/16"]}


def ar(recs=DATA):
    return archive(rows(*recs))


def defn(**kw):
    base = {"baslik": "Arsenal ev maçları", "kaynak": "openfootball", "grup_1": G_ARS_HOME, "grup_2": G_ALL}
    base.update(kw)
    return base


def ws_new(tmp_path, name="ws"):
    return C.CalismaAlani.olustur_veya_ac(tmp_path / name)


def snapshot_dir(*dirs) -> dict:
    out = {}
    for d in dirs:
        for p in sorted(Path(d).rglob("*")):
            if p.is_file():
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


FORBIDDEN = {"olasilik", "probability", "p_degeri", "p_value", "anlamlilik", "strateji_basarisi", "sinyal", "oneri",
             "stake", "kelly", "edge", "bahis", "MODEL_VALIDATED", "VALUE_CANDIDATE"}


def all_keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield str(k)
            yield from all_keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from all_keys(v)


def all_strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from all_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from all_strings(v)
    elif isinstance(o, str):
        yield o


# ----------------------------------------------------------------------------- tanım ve revizyon

def test_definition_roundtrip_unchanged(tmp_path):
    ws = ws_new(tmp_path)
    d = defn(aciklama="Türkçe açıklama: ğüşiöç İĞÜŞÖÇ", etiketler=["deneme", "ev"], pazarlar=["C", "A"])
    rec = ws.arastirma_olustur(d)
    expect = C.validate_definition(d)
    assert rec["tanim"] == expect and rec["revizyon"] == 1 and rec["tanim"]["pazarlar"] == ["A", "C"]
    assert rec["tanim"]["gorunum"] == {"tur": A.VIEW_SINGLE, "kaynak": OF}
    assert rec["on_kayit_kaniti"] == "YOK" and "ön-kayıt" in rec["aciklama"]
    ws.close()
    ro = C.CalismaAlani.ac(tmp_path / "ws")
    again = ro.arastirma(rec["arastirma_id"])
    assert again["tanim"] == expect and again["tanim_ozeti"] == rec["tanim_ozeti"]
    assert ro.arastirmalar()[0]["baslik"] == "Arsenal ev maçları"


@pytest.mark.parametrize("bad, msg", [
    ({"kaynak": "openfootball", "grup_1": {"lig": "E0", "renk": "kırmızı"}}, "bilinmeyen alan"),
    ({"kaynak": "openfootball", "sql": "DROP TABLE"}, "bilinmeyen alan"),
    ({"grup_1": {}}, "kaynak: açıkça verilmeli"),
    ({"kaynak": "openfootball", "grup_1": {"yer": "ev"}}, "yalnızca takım"),
    ({"kaynak": "openfootball", "grup_1": {"sezonlar": ["2015/17"]}}, "geçersiz değer"),
    ({"kaynak": "openfootball", "grup_1": {"bas": "2015/08/01"}}, "YYYY-AA-GG"),
    ({"kaynak": "openfootball", "grup_1": {"lig": "XX9"}}, "bilinmeyen lig"),
    ({"kaynak": "openfootball", "grup_1": {"sonuc": {"B": "bazen"}}}, "değerlerinden biri"),
    ({"kaynak": "openfootball", "grup_1": {"sonuc": {"iy_ms": ["HTFT_9_9"]}}}, "merkezi kayıttaki kodlar"),
    ({"kaynak": "openfootball", "pazarlar": ["D"]}, "pazarlar"),
    ({"kaynak": "football-data"}, "kaynak"),
    ({"kaynak": "openfootball", "baslik": "x" * 201}, "en çok 200"),
    ({"kaynak": "openfootball", "baslik": "kontrol\x00karakteri"}, "kontrol karakteri"),
    ({"kaynak": "openfootball", "baslik": "\ud800bozuk"}, "UTF-8"),
])
def test_validation_rejects_unknown_or_invalid_fields(bad, msg):
    d = {"baslik": "t", **bad}
    with pytest.raises(C.DogrulamaHatasi, match=msg):
        C.validate_definition(d)


def test_revision_does_not_change_old_revision_or_runs(tmp_path):
    ws = ws_new(tmp_path)
    rec = ws.arastirma_olustur(defn())
    run1 = ws.calistir(ar(), rec["arastirma_id"])
    raw1 = ws.conn.execute("SELECT kayit FROM calistirmalar WHERE calistirma_id=?", (run1["calistirma_id"],)).fetchone()
    r2 = ws.arastirma_revize(rec["arastirma_id"], {"grup_2": {"lig": "E0", "sezonlar": ["2015/16"], "takim": "Chelsea FC"}},
                             temel_revizyon=1)
    assert r2["revizyon"] == 2 and r2["kayit_aninda_onceki_calistirma"] == 1
    run2 = ws.calistir(ar(), rec["arastirma_id"])
    assert run2["revizyon"] == 2 and run1["revizyon"] == 1
    assert ws.conn.execute("SELECT kayit FROM calistirmalar WHERE calistirma_id=?",
                           (run1["calistirma_id"],)).fetchone() == raw1
    assert ws.arastirma(rec["arastirma_id"], 1)["tanim"] == rec["tanim"]
    assert ws.calistirma(run1["calistirma_id"])["tanim"]["grup_2"] == rec["tanim"]["grup_2"]
    # Veritabanı düzeyinde de değiştirilemez / silinemez (her tabloda gerçek satır üzerinde)
    ws.not_ekle(rec["arastirma_id"], "not")
    for sql in ("UPDATE arastirma_revizyonlari SET tanim='{}'", "DELETE FROM calistirmalar",
                "UPDATE notlar SET metin='x'", "DELETE FROM notlar", "DELETE FROM calistirma_gruplari",
                "UPDATE calistirmalar SET sonuc_ozeti='x'", "DELETE FROM arastirma_revizyonlari"):
        with pytest.raises(sqlite3.DatabaseError):
            ws.conn.execute(sql)
    with pytest.raises(C.DogrulamaHatasi, match="tanım değişmedi"):
        ws.arastirma_revize(rec["arastirma_id"], {"baslik": "Arsenal ev maçları"})


# ----------------------------------------------------------------------------- notlar

def test_unicode_notes_preserved_and_versioned(tmp_path):
    ws = ws_new(tmp_path)
    rid = ws.arastirma_olustur(defn())["arastirma_id"]
    text = "Şüpheli buldum: İY 0-1 → MS 3-1; ğüşiöç İĞÜŞÖÇ — naïve café ⚽ 日本語\nikinci satır"
    n = ws.not_ekle(rid, text)
    assert n["metin"] == text and n["surum"] == 1 and n["durum"] == "aktif"
    n2 = ws.not_guncelle(n["not_id"], metin=text + " (düzeltme)")
    assert n2["surum"] == 2 and n2["onceki_surumler"][0]["metin"] == text
    n3 = ws.not_guncelle(n["not_id"], durum="arsivlendi")
    assert n3["durum"] == "arsivlendi" and n3["metin"] == text + " (düzeltme)" and len(n3["onceki_surumler"]) == 2
    assert ws.notlar(rid, arsivlenenler=False) == []
    ws.close()
    assert C.CalismaAlani.ac(tmp_path / "ws").not_oku(n["not_id"])["onceki_surumler"][0]["metin"] == text
    ws = C.CalismaAlani.yazmak_icin_ac(tmp_path / "ws")
    for bad in ("\ud83d yalnız vekil", "a" * 4001, "", "boş\x07zil"):
        with pytest.raises(C.DogrulamaHatasi):
            ws.not_ekle(rid, bad)


def test_note_changes_no_match_label_or_model_field(tmp_path):
    a = ar(season_rows())
    ws = ws_new(tmp_path)
    rid = ws.arastirma_olustur(defn(grup_1=G_ALL, grup_2=None))["arastirma_id"]
    run = ws.calistir(a, rid)
    before_rows = a.rows.copy()
    before_lab = A.explore(a, kaynak="openfootball")[0]
    mid = "E0|2015-08-08|Arsenal FC|Chelsea FC"
    n = ws.not_ekle(rid, "Şüpheli buldum, şike olabilir", mac_kimligi=mid, archive=a)
    assert n["gorunum_kaynak"] == OF and n["mac_kimligi"] == mid and "şike tespiti" in n["aciklama"]
    pd.testing.assert_frame_equal(a.rows, before_rows)
    pd.testing.assert_frame_equal(A.explore(a, kaynak="openfootball")[0], before_lab)
    assert ws.calistirma(run["calistirma_id"]) == run
    run2 = ws.calistir(a, rid)
    assert run2["sonuc_ozeti"] == run["sonuc_ozeti"]  # serbest metin hiçbir hesabı değiştirmez
    card = ws.not_karti(a, n["not_id"], "Arsenal FC")
    assert card["gorunum"]["kaynak"] == OF and card["not"]["metin"].startswith("Şüpheli") and card["kaynak"]["kaynak"] == OF
    # Arşivde olmayan maç veya başka görünümün maçı: not eklenmez, sahte kart yok
    n_before = ws.conn.execute("SELECT COUNT(*) FROM notlar").fetchone()[0]
    with pytest.raises(C.CalismaError, match="görünümde yok"):
        ws.not_ekle(rid, "yok", mac_kimligi="E0|2015-08-08|Yok FC|Hiç FC", archive=a)
    with pytest.raises(C.CalismaError, match="görünümde yok"):  # StatsBomb adlarıyla kimlik openfootball görünümünde yok
        ws.not_ekle(rid, "başka kaynak", mac_kimligi="E0|2015-08-08|Arsenal|Chelsea", archive=a)
    assert ws.conn.execute("SELECT COUNT(*) FROM notlar").fetchone()[0] == n_before
    ok = ws.not_ekle(rid, "StatsBomb görünümüne açıkça bağlı", mac_kimligi="E0|2015-08-08|Arsenal|Chelsea", archive=a,
                     kaynak="hudl")
    assert ok["gorunum_kaynak"] == SB
    # Bağlı maç sonradan veride yoksa kart üretilmez (başka görünüme geçilmez)
    gone = ar([x for x in season_rows() if x["kaynak"] == OF])
    with pytest.raises(A.ArchiveError):
        ws.not_karti(gone, ok["not_id"], "Arsenal")


# ----------------------------------------------------------------------------- grup hesapları

def test_single_source_and_merged_views_stay_separate():
    r_of = C.compute(ar(), defn(grup_2=None))
    g = r_of["sonuc"]["grup_1"]
    assert r_of["gorunum"]["tur"] == A.VIEW_SINGLE and g["mac"] == 3
    assert g["pazarlar"]["C"]["gecerli"] == 2 and g["pazarlar"]["C"]["bilinmiyor"] == 1  # StatsBomb İY'si taşınmaz
    assert g["alan_birlesimi_iceren_mac"] == 0
    r_m = C.compute(ar(), defn(kaynak="birlesik", grup_2=None))
    gm = r_m["sonuc"]["grup_1"]
    assert r_m["gorunum"]["tur"] == A.VIEW_MERGED and gm["pazarlar"]["C"]["gecerli"] == 3
    assert gm["alan_birlesimi_iceren_mac"] == 1
    assert any(w["kod"] == "BIRLESTIRILMIS_GORUNUM" for w in r_m["sonuc"]["uyarilar"])
    assert r_of["veri"]["veri_ozeti"] != r_m["veri"]["veri_ozeti"]


def test_group_filters_give_same_match_set_as_archive_query():
    a = ar(season_rows() + DATA[1:5])
    for g in (G_ARS_HOME, G_ALL, {"lig": "E0", "sezonlar": ["2015/16"], "takim": "Everton FC", "bas": "2015-08-20",
                                    "son": "2015-09-05"}, {"takim": "Arsenal FC", "yer": "deplasman"}):
        res, ids = C.group_result(a, A.view(a, "openfootball"), C.validate_group(g, "g"), C.MARKETS)
        lab, out = A.explore(a, kaynak="openfootball", lig=g.get("lig"), sezon=(g.get("sezonlar") or [None])[0],
                             takim=g.get("takim"), yer=g.get("yer"), bas=g.get("bas"), son=g.get("son"))
        assert ids == sorted(lab["mac_kimligi"]) and res["mac"] == out["mac"]
        for k in ("A", "B", "C"):
            assert res["pazarlar"][k] == out["pazarlar"][k]
        assert res["iy_ms"]["dagilim"] == out["iy_ms"]
    multi = {"lig": "E0", "sezonlar": ["2014/15", "2015/16"]}
    _, ids = C.group_result(a, A.view(a, "openfootball"), C.validate_group(multi, "g"), C.MARKETS)
    expect = sorted(set(A.explore(a, kaynak="openfootball", sezon="2014/15")[0]["mac_kimligi"])
                    | set(A.explore(a, kaynak="openfootball", sezon="2015/16")[0]["mac_kimligi"]))
    assert ids == expect


def test_market_denominators_handle_missing_data():
    g = C.compute(ar(), defn(grup_1=G_ALL, grup_2=None))["sonuc"]["grup_1"]
    assert g["mac"] == 5 and g["pazarlar"]["B"]["gecerli"] == 5
    # MS 0-0 maçın İY'si v2 kuralıyla mantıksal 0-0 olabilir; İY'si hiç olmayan maç İY pazarlarında bilinmiyor
    assert g["pazarlar"]["C"]["gecerli"] + g["pazarlar"]["C"]["bilinmiyor"] == 5
    assert g["pazarlar"]["C"]["bilinmiyor"] >= 1 and g["pazarlar"]["A"]["gecerli"] == g["pazarlar"]["C"]["gecerli"]
    assert g["iy_ms"]["gecerli"] == g["pazarlar"]["C"]["gecerli"]
    for k in ("A", "B", "C"):
        p = g["pazarlar"][k]
        assert p["gerceklesme_orani"] == p["evet"] / p["gecerli"]


def test_empty_group_does_not_produce_fake_zero():
    res = C.compute(ar(), defn(grup_2={"takim": "Olmayan Takım FC"}))
    g2, comp = res["sonuc"]["grup_2"], res["sonuc"]["karsilastirma"]
    assert g2["mac"] == 0 and g2["olay_sayisi"] == 0 and g2["tarih_araligi"] is None
    for k in ("A", "B", "C"):
        assert g2["pazarlar"][k]["gerceklesme_orani"] is None and g2["pazarlar"][k]["gecerli"] == 0
        assert comp["pazarlar"][k]["fark_yuzde_puan"] is None and comp["pazarlar"][k]["oran_grup_2"] is None
    assert all(v["pay_grup_2"] is None and v["fark_yuzde_puan"] is None for v in comp["iy_ms"]["kodlar"].values())
    assert {a["kod"] for a in g2["aciklamalar"]} >= {"BOS_GRUP", "TAKIM_GORUNUMDE_YOK"}
    assert "null" in C.to_json(g2["pazarlar"]) and "NaN" not in C.to_json(res)


def test_percentage_point_difference_and_overlap():
    res = C.compute(ar(), defn())
    g1, g2, comp = res["sonuc"]["grup_1"], res["sonuc"]["grup_2"], res["sonuc"]["karsilastirma"]
    for k in ("A", "B", "C"):
        o1, o2 = g1["pazarlar"][k]["gerceklesme_orani"], g2["pazarlar"][k]["gerceklesme_orani"]
        assert comp["pazarlar"][k]["fark_yuzde_puan"] == pytest.approx(100.0 * (o1 - o2), abs=0)
    b = comp["pazarlar"]["B"]  # Grup 1: Arsenal evde 3 maç, 2'si 3,5 üst (2-1 değil, 2-2 ve 4-0) -> 2/3; Grup 2: 3/5
    assert (b["oran_grup_1"], b["oran_grup_2"]) == (2 / 3, 3 / 5)
    assert b["fark_yuzde_puan"] == 100.0 * (2 / 3 - 3 / 5)
    assert "göreli yüzde değişim değildir" in comp["birim"] and comp["istatistiksel_test"] == "YAPILMADI"
    o = comp["ortusme"]
    assert (o["ortak"], o["yalniz_grup_1"], o["yalniz_grup_2"]) == (3, 0, 2)
    assert o["bagimsiz_ornek_degil"] and not o["tam_ortusme"] and o["not"]
    assert any(w["kod"] == "ORTUSEN_GRUPLAR" for w in res["sonuc"]["uyarilar"])


def test_identical_groups_give_zero_difference_and_full_overlap():
    res = C.compute(ar(), defn(grup_2=G_ARS_HOME))
    comp = res["sonuc"]["karsilastirma"]
    assert all(v["fark_yuzde_puan"] == 0.0 for v in comp["pazarlar"].values())
    assert all(v["fark_yuzde_puan"] in (0.0, None) for v in comp["iy_ms"]["kodlar"].values())
    assert comp["ortusme"]["tam_ortusme"] and comp["ortusme"]["yalniz_grup_1"] == comp["ortusme"]["yalniz_grup_2"] == 0
    assert res["sonuc"]["grup_1"]["olay_kumesi_ozeti"] == res["sonuc"]["grup_2"]["olay_kumesi_ozeti"]


def test_outcome_filter_is_marked_descriptive_selection():
    res = C.compute(ar(), defn(grup_1={**G_ALL, "sonuc": {"B": "gerceklesti"}}, grup_2=G_ALL))
    g1 = res["sonuc"]["grup_1"]
    assert g1["pazarlar"]["B"]["gerceklesme_orani"] == 1.0 and g1["sonuca_gore_secildi"]
    assert C.SELECTED_BY_OUTCOME in {a["kod"] for a in g1["aciklamalar"]}
    assert C.SELECTED_BY_OUTCOME in {w["kod"] for w in res["sonuc"]["uyarilar"]}
    assert g1["kimlik_incelemesi_kaynak_satiri"] is None  # sonuç filtresine indirgenemez
    assert res["statu"] == res["sonuc"]["statu"] == C.STATUS == "DESCRIPTIVE_RESEARCH"
    assert not (set(all_keys(res)) & FORBIDDEN)
    assert not any(s in ("MODEL_VALIDATED", "VALUE_CANDIDATE") for s in all_strings(res))
    iyms = C.compute(ar(), defn(grup_1={**G_ALL, "sonuc": {"iy_ms": ["HTFT_1_1"]}}, grup_2=None))["sonuc"]["grup_1"]
    assert iyms["iy_ms"]["dagilim"]["HTFT_1_1"] == iyms["iy_ms"]["gecerli"] == iyms["mac"]
    unknown = C.compute(ar(), defn(grup_1={**G_ALL, "sonuc": {"C": "bilinmiyor"}}, grup_2=None))["sonuc"]["grup_1"]
    assert unknown["pazarlar"]["C"]["gecerli"] == 0 and unknown["pazarlar"]["C"]["bilinmiyor"] == unknown["mac"] >= 1


def test_row_order_does_not_change_results():
    base = rows(*DATA, *season_rows(), *[{**x, "season": "2014/15", "date": "2015-04-20"} for x in CONFLICT])
    ref = None
    rng = np.random.default_rng(3)
    for _ in range(5):
        r = base.iloc[rng.permutation(len(base))].reset_index(drop=True)
        out = [(C.compute(archive(r), defn(kaynak=k, grup_2=G_ALL))) for k in ("openfootball", "birlesik")]
        key = [(o["veri"]["veri_ozeti"], o["sonuc_ozeti"], C.canon(o["sonuc"])) for o in out]
        if ref is None:
            ref = key
        assert key == ref


# ----------------------------------------------------------------------------- veri sürümü ve haklar

def test_changed_data_creates_new_snapshot_and_keeps_old_run(tmp_path):
    ws = ws_new(tmp_path)
    rid = ws.arastirma_olustur(defn())["arastirma_id"]
    run1 = ws.calistir(ar(), rid)
    assert run1["onceki_calistirmaya_gore_veri"]["durum"] == "ILK_CALISTIRMA"
    same = ws.calistir(ar(), rid)
    assert same["onceki_calistirmaya_gore_veri"]["durum"] == "AYNI"
    assert same["sonuc_ozeti"] == run1["sonuc_ozeti"] and same["calistirma_id"] != run1["calistirma_id"]
    changed = [dict(x) for x in DATA]
    changed[3] = of("2015-08-29", "Arsenal FC", "Stoke City FC", (1, 0), (1, 0))
    run3 = ws.calistir(ar(changed), rid)
    assert run3["veri"]["veri_ozeti"] != run1["veri"]["veri_ozeti"]
    assert run3["onceki_calistirmaya_gore_veri"]["durum"] == "DEGISTI" and run3["sonuc_ozeti"] != run1["sonuc_ozeti"]
    assert ws.calistirma(run1["calistirma_id"]) == run1  # önceki sonuç değişmedi


def test_missing_old_snapshot_is_not_silently_replaced(tmp_path):
    ws = ws_new(tmp_path)
    rid = ws.arastirma_olustur(defn())["arastirma_id"]
    run = ws.calistir(ar(), rid)
    assert ws.dogrula(ar(), run["calistirma_id"])["durum"] == "DOGRULANDI"
    changed = [*DATA, of("2015-09-12", "Arsenal FC", "Chelsea FC", (1, 1), (0, 0))]
    v = ws.dogrula(ar(changed), run["calistirma_id"])
    assert v["durum"] == "VERI_SURUMU_DEGISTI" and v["yeniden_hesaplanarak_dogrulandi"] is False
    assert v["sakli_veri_ozeti"] == run["veri"]["veri_ozeti"] != v["guncel_veri_ozeti"]
    stored = ws.calistirma(run["calistirma_id"])
    assert stored["sonuc_ozeti"] == run["sonuc_ozeti"] and stored["sonuc"] == run["sonuc"]  # saklı sonuç okunabilir
    assert ws.conn.execute("SELECT COUNT(*) FROM calistirmalar").fetchone()[0] == 1  # doğrulama yazmaz


def test_closed_source_cannot_be_reached_by_query_or_stored_result(tmp_path, monkeypatch):
    ws = ws_new(tmp_path)
    rid_ds = ws.arastirma_olustur(defn(kaynak="datasets"))["arastirma_id"]
    r = ws.calistir(ar(), rid_ds)
    assert r["sonuc"]["durum"] == "KULLANIM_KAPSAMI_KAPALI" and r["sonuc"].get("grup_1") is None
    assert r["olay_kumeleri"]["1"]["olay_sayisi"] in (0, None)
    pv = C.compute(ar(), defn(kaynak="xgabora"))
    assert pv["sonuc"]["durum"] == "KULLANIM_KAPSAMI_KAPALI" and pv["_olaylar"] == {1: [], 2: []}
    # Saklı sonuç: kaynak sonradan tarihsel analize kapanırsa toplu sonuç ve olay listesi gösterilmez
    rid = ws.arastirma_olustur(defn(kaynak="hudl", grup_1={}, grup_2=None))["arastirma_id"]
    run = ws.calistir(ar(), rid)
    assert run["sonuc"]["durum"] == "TAMAMLANDI" and run["sonuc"]["grup_1"]["mac"] == 1
    monkeypatch.setitem(source_registry.ARCHIVE_SCOPES[SB], "tarihsel_analiz", "DOGRULANAMADI")
    closed = ws.calistirma(run["calistirma_id"], olaylar=True)
    assert closed["sonuc"]["durum"] == "KULLANIM_KAPSAMI_KAPALI" and closed["sonuc"]["kapali_kaynaklar"] == [SB]
    assert "grup_1" not in closed["sonuc"] and closed["olay_kumeleri"]["1"] == {"olay_sayisi": None, "olay_ozeti": None}
    assert ws.dogrula(ar(), run["calistirma_id"])["durum"] == "KULLANIM_KAPSAMI_KAPALI"
    # Birleştirilmiş görünüm de kapanan kaynağın satırlarını artık kullanmaz
    merged = C.compute(ar(), defn(kaynak="birlesik", grup_1={}, grup_2=None))
    assert merged["veri"]["kullanilan_kaynaklar"] == [OF]
    assert merged["sonuc"]["grup_1"]["kaynak_satiri"] == 5 and merged["sonuc"]["grup_1"]["alan_birlesimi_iceren_mac"] == 0


# ----------------------------------------------------------------------------- saklama ve hatalar

def test_interrupted_run_leaves_no_successful_record(tmp_path, monkeypatch):
    ws = ws_new(tmp_path)
    rid = ws.arastirma_olustur(defn())["arastirma_id"]
    calls = {"n": 0}
    orig = C.CalismaAlani._insert_group

    def boom(self, run_id, grp, ids):
        calls["n"] += 1
        if grp == 2:
            raise RuntimeError("yapay kesinti")
        return orig(self, run_id, grp, ids)

    monkeypatch.setattr(C.CalismaAlani, "_insert_group", boom)
    with pytest.raises(RuntimeError, match="yapay kesinti"):
        ws.calistir(ar(), rid)
    assert calls["n"] == 2
    assert ws.conn.execute("SELECT COUNT(*) FROM calistirmalar").fetchone()[0] == 0
    assert ws.conn.execute("SELECT COUNT(*) FROM calistirma_gruplari").fetchone()[0] == 0
    assert ws.calistirmalar(rid) == []


def test_concurrent_writes_do_not_overwrite(tmp_path):
    w1 = ws_new(tmp_path)
    rid = w1.arastirma_olustur(defn())["arastirma_id"]
    w2 = C.CalismaAlani.yazmak_icin_ac(tmp_path / "ws")
    w1.arastirma_revize(rid, {"baslik": "Birinci değişiklik"}, temel_revizyon=1)
    with pytest.raises(C.CakismaHatasi):
        w2.arastirma_revize(rid, {"aciklama": "ikinci değişiklik"}, temel_revizyon=1)
    w2.arastirma_revize(rid, {"aciklama": "ikinci değişiklik"})  # en son revizyonun üzerine uygulanır
    head = w1.arastirma(rid)
    assert head["revizyon"] == 3 and head["tanim"]["baslik"] == "Birinci değişiklik"
    assert head["tanim"]["aciklama"] == "ikinci değişiklik"
    errors, made = [], []

    def worker(i):
        try:
            w = C.CalismaAlani.yazmak_icin_ac(tmp_path / "ws", timeout=30)
            r = w.arastirma_olustur(defn(baslik=f"eşzamanlı {i}"))
            w.not_ekle(r["arastirma_id"], f"not {i} — ğüş")
            w.arastirma_revize(rid, {"etiketler": [f"e{i}"]})
            made.append(r["arastirma_id"])
            w.close()
        except Exception as e:  # pragma: no cover - hata ayrıntısı
            errors.append(repr(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    ids = {x["arastirma_id"] for x in w1.arastirmalar()}
    assert set(made) <= ids and len(ids) == 9
    revs = [r["revizyon"] for r in w1.arastirma(rid)["revizyonlar"]]
    assert revs == list(range(1, 12))  # 3 + 8 eşzamanlı revizyon, boşluksuz ve çakışmasız
    assert w1.conn.execute("SELECT COUNT(*) FROM notlar").fetchone()[0] == 8


def test_corrupt_foreign_and_locked_files_are_not_overwritten(tmp_path):
    bad = tmp_path / "bozuk"
    bad.mkdir()
    (bad / C.DB_NAME).write_bytes(b"bu bir veritabani degil" * 100)
    before = (bad / C.DB_NAME).read_bytes()
    with pytest.raises(C.CalismaError, match="bozuk"):
        C.CalismaAlani.olustur_veya_ac(bad)
    with pytest.raises(C.CalismaError, match="bozuk"):
        C.CalismaAlani.ac(bad)
    assert (bad / C.DB_NAME).read_bytes() == before
    foreign = tmp_path / "yabanci"
    foreign.mkdir()
    con = sqlite3.connect(foreign / C.DB_NAME)
    con.execute("CREATE TABLE predictions (id TEXT)")
    con.commit()
    con.close()
    fb = (foreign / C.DB_NAME).read_bytes()
    with pytest.raises(C.CalismaError, match="geçersiz şema|çalışma alanı olmayan"):
        C.CalismaAlani.olustur_veya_ac(foreign)
    with pytest.raises(C.CalismaError, match="şema"):
        C.CalismaAlani.ac(foreign)
    assert (foreign / C.DB_NAME).read_bytes() == fb
    ws = ws_new(tmp_path, "kilit")
    ws.arastirma_olustur(defn())
    lock = sqlite3.connect(tmp_path / "kilit" / C.DB_NAME, isolation_level=None)
    lock.execute("BEGIN EXCLUSIVE")
    ws.conn.execute("PRAGMA busy_timeout=200")
    with pytest.raises(C.CalismaError, match="kilitli"):
        ws.arastirma_olustur(defn(baslik="kilitliyken"))
    lock.execute("ROLLBACK")
    lock.close()
    assert len(ws.arastirmalar()) == 1  # kilitliyken yazılmak istenen kayıt oluşmadı
    with pytest.raises(C.CalismaError, match="Çalışma alanı yok"):
        C.CalismaAlani.ac(tmp_path / "olmayan")
    assert not (tmp_path / "olmayan").exists()  # okuma çalışma alanı oluşturmaz


def test_workspace_location_is_separate_from_app_archive_dirs(tmp_path, tmp_home):
    with pytest.raises(C.CalismaError, match="uygulama veri klasörü"):
        C.CalismaAlani.olustur_veya_ac(tmp_home / "calisma")
    with pytest.raises(C.CalismaError, match="arşiv klasörü"):
        C.CalismaAlani.olustur_veya_ac(A.archive_home_path() / "calisma")
    with pytest.raises(C.CalismaError, match="verilen klasör"):
        C.CalismaAlani.olustur_veya_ac(tmp_path / "arsiv" / "ic", ayri=[tmp_path / "arsiv"])
    assert C.workspace_home_path() == tmp_home.with_name(tmp_home.name + "-Calisma")


def test_json_output_is_finite_and_explicit():
    res = C.compute(ar(), defn(grup_2={"takim": "Olmayan Takım FC"}))
    res.pop("_olaylar")
    txt = C.to_json(res)

    def reject(c):
        raise AssertionError(f"sonlu olmayan sayı: {c}")

    data = json.loads(txt, parse_constant=reject)
    assert data["sonuc"]["durum"] == "TAMAMLANDI" and data["statu"] == C.STATUS
    assert data["veri"]["not"] == C.HASH_NOTE and "zaman damgası" in C.HASH_NOTE
    assert C.canon({"x": float("nan")}) == '{"x":null}'


# ----------------------------------------------------------------------------- CLI ve mevcut verinin korunması

def test_cli_end_to_end_and_read_only_commands(tmp_path, tmp_home, capsys, monkeypatch):
    from test_s5_github import build

    from bahis_tahmin.cli import main

    home, _, _ = build(tmp_path)  # sentetik arşiv (openfootball 2024/25 + StatsBomb 2015/16)
    ws = tmp_path / "calisma"
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    (pilot / "data_meta.json").write_text("{}")
    for name in ("settings.json", "matches.pkl", "goal_engine.joblib", "gol_pazarlari.sqlite"):
        (tmp_home / name).write_bytes(b"veri")
    protected = snapshot_dir(home, pilot, tmp_home)

    def run(*argv):
        code = main(list(argv))
        cap = capsys.readouterr()
        return code, (json.loads(cap.out) if cap.out.strip().startswith("{") else cap.out), cap.err

    code, rec, _ = run("calisma-olustur", "--calisma", str(ws), "--baslik", "Arsenal evde — 2024/25", "--kaynak",
                       "openfootball", "--g1-lig", "E0", "--g1-sezon", "2024/25", "--g1-takim", "Arsenal FC",
                       "--g1-yer", "ev", "--g2-lig", "E0", "--g2-sezon", "2024/25", "--etiket", "deneme")
    assert code == 0 and rec["revizyon"] == 1
    rid = rec["arastirma_id"]
    code, out, err = run("calisma-olustur", "--calisma", str(ws), "--baslik", "x", "--kaynak", "openfootball",
                         "--g1-yer", "ev")
    assert code == 2 and "Doğrulama" in err
    code, out, err = run("calisma-revize", "--calisma", str(ws), "--arastirma", rid, "--temel-revizyon", "5",
                         "--aciklama", "yeni")
    assert code == 4 and "Çakışma" in err
    code, runrec, _ = run("calisma-calistir", "--calisma", str(ws), "--ev", str(home), "--arastirma", rid)
    assert code == 0 and runrec["sonuc"]["durum"] == "TAMAMLANDI" and runrec["statu"] == C.STATUS
    assert runrec["sonuc"]["grup_1"]["mac"] == 1 and runrec["sonuc"]["grup_2"]["mac"] == 4
    assert runrec["veri"]["kaynak_commitleri"] == {OF: ["a" * 40]}
    code, note, _ = run("calisma-not", "--calisma", str(ws), "--arastirma", rid, "--metin", "İlginç maç: ğüş",
                        "--mac", "E0|2024-08-17|Arsenal FC|Chelsea FC", "--ev", str(home))
    assert code == 0 and note["metin"] == "İlginç maç: ğüş"
    code, out, err = run("calisma-not", "--calisma", str(ws), "--arastirma", rid, "--metin", "x", "--mac",
                         "E0|2024-08-17|Yok FC|Chelsea FC", "--ev", str(home))
    assert code == 3 and "görünümde yok" in err
    # Salt okunur komutlar: ağ yok, çalışma alanı ve arşiv dosyaları değişmez
    import socket

    def no_net(*a, **k):
        raise AssertionError("salt okunur komut ağ isteği yaptı")

    monkeypatch.setattr(socket.socket, "connect", no_net)
    before = snapshot_dir(ws, home)
    reads = [("calisma-liste", "--calisma", str(ws)), ("calisma-oku", "--calisma", str(ws), "--arastirma", rid),
             ("calisma-calistirma-oku", "--calisma", str(ws), "--calistirma", runrec["calistirma_id"], "--olaylar"),
             ("calisma-dogrula", "--calisma", str(ws), "--ev", str(home), "--calistirma", runrec["calistirma_id"]),
             ("calisma-not-kart", "--calisma", str(ws), "--ev", str(home), "--not", note["not_id"], "--takim",
              "Arsenal FC"),
             ("calisma-karsilastir", "--ev", str(home), "--kaynak", "openfootball", "--g1-takim", "Arsenal FC",
              "--g2-tum")]
    results = {}
    for argv in reads:
        code, out, err = run(*argv)
        assert code == 0, (argv, err)
        results[argv[0]] = out
    assert snapshot_dir(ws, home) == before
    assert results["calisma-dogrula"]["durum"] == "DOGRULANDI"
    assert results["calisma-calistirma-oku"]["olay_kumeleri"]["1"]["olaylar"] == ["E0|2024-08-17|Arsenal FC|Chelsea FC"]
    assert results["calisma-karsilastir"]["kaydedildi"] is False
    assert results["calisma-karsilastir"]["sonuc"]["karsilastirma"]["ortusme"]["ortak"] == 2
    assert len(results["calisma-oku"]["calistirmalar"]) == 1 and len(results["calisma-oku"]["notlar"]) == 1
    code, out, err = run("calisma-karsilastir", "--ev", str(home), "--kaynak", "openfootball", "--g1-takim", "Arsenal FC")
    assert code == 2 and "Grup 2" in err
    missing = tmp_path / "olmayan-calisma"
    code, out, err = run("calisma-liste", "--calisma", str(missing))
    assert code == 3 and not missing.exists()
    code, out, err = run("calisma-calistir", "--calisma", str(missing), "--ev", str(home), "--arastirma", rid)
    assert code == 3 and not missing.exists()  # yazan komut da var olmayan alanı sessizce oluşturmaz
    assert snapshot_dir(home, pilot, tmp_home) == protected  # arşiv, pilot ve uygulama verisi değişmedi

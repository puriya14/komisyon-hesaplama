"""S5-ARSIV-02: tek kaynak / birleştirilmiş görünüm ayrımı ve filtreli özet sayaçları.

Bütün testler açıkça sentetik satırlarla, bellekteki bir arşiv nesnesiyle (veya geçici klasörde sentetik
hazırlanmış bir arşivle) çalışır; gerçek veri veya ağ gerekmez.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from bahis_tahmin import archive as A

OF, SB, DS = "openfootball-sonuc", "statsbomb-acik", "football-datasets"


def rows(*recs) -> pd.DataFrame:
    base = {"etiket": None, "blok": 0, "league": "E0", "season": "2015/16", "time": "", "hthg": np.nan,
            "htag": np.nan, "iy_mantiksal": False, "olay_durumu": None, "saglayici_mac_id": None, "xg_h": np.nan,
            "xg_a": np.nan, "sut_h": np.nan, "sut_a": np.nan}
    out = []
    for r in recs:
        x = {**base, **r}
        x["asil_kaynak"] = A.UPSTREAM[x["kaynak"]]
        x["blok"] = x["blok"] if "blok" in r else {OF: 0, SB: 1, DS: 2}[x["kaynak"]]
        x["date"] = pd.Timestamp(x["date"])
        for c in ("fthg", "ftag", "hthg", "htag", "xg_h", "xg_a", "sut_h", "sut_a"):
            x[c] = float(x[c]) if x.get(c) is not None else np.nan
        out.append(x)
    return pd.DataFrame(out).reindex(columns=A.ROW_COLUMNS)


def of(date, home, away, ft, ht=None, **kw):
    return {"kaynak": OF, "date": date, "home": home, "away": away, "fthg": ft[0], "ftag": ft[1],
            "hthg": ht[0] if ht else None, "htag": ht[1] if ht else None, **kw}


def sb(date, home, away, ft, ht=None, **kw):
    return {"kaynak": SB, "date": date, "home": home, "away": away, "fthg": ft[0], "ftag": ft[1],
            "hthg": ht[0] if ht else None, "htag": ht[1] if ht else None, **kw}


def archive(r: pd.DataFrame, blocks=None, rejected=None) -> A.Archive:
    return A.Archive(None, {"bloklar": blocks or [], "olusturma_utc": "2026-10-11T00:00:00+00:00"}, r,
                     rejected or [])


# Aynı maç: openfootball'da yalnızca MS; StatsBomb'da aynı MS + İY + xG + şut + saat + sağlayıcı kimliği
BASE = [of("2015-08-08", "Arsenal FC", "Chelsea FC", (2, 1)),
        sb("2015-08-08", "Arsenal", "Chelsea", (2, 1), (1, 0), xg_h=1.4, xg_a=0.6, sut_h=12, sut_a=7, time="12:45",
           saglayici_mac_id="101")]
# Kaynaklar arasında çelişki: openfootball 3-1, StatsBomb 2-1 (ikisi de kendi içinde tutarlı)
CONFLICT = [of("2015-08-15", "Chelsea FC", "Arsenal FC", (3, 1), (1, 1)),
            sb("2015-08-15", "Chelsea", "Arsenal", (2, 1), (1, 1))]


def one(lab: pd.DataFrame, mid: str) -> pd.Series:
    hit = lab[lab["mac_kimligi"] == mid]
    assert len(hit) == 1, (mid, len(hit))
    return hit.iloc[0]


MID = "E0|2015-08-08|Arsenal FC|Chelsea FC"
MID_C = "E0|2015-08-15|Chelsea FC|Arsenal FC"


# 1
def test_single_source_does_not_carry_other_source_fields():
    lab, out = A.explore(archive(rows(*BASE)), kaynak="openfootball")
    r = one(lab, MID)
    assert np.isnan(r["xg_h"]) and np.isnan(r["xg_a"]) and np.isnan(r["sut_h"]) and np.isnan(r["sut_a"])
    assert r["time"] == "" and r["saglayici_mac_id"] is None
    assert r["kaynaklar"] == OF and r["kaynak_satiri"] == 1 and not r["alan_birlesimi"] and r["alan_kokeni"] == ""
    assert out["gorunum"]["tur"] == A.VIEW_SINGLE and out["gorunum"]["kaynak"] == OF
    assert "başka kaynaktan alan taşınmaz" in out["gorunum"]["aciklama"]
    # StatsBomb tek kaynakta kendi alanları duruyor
    lab_sb, _ = A.explore(archive(rows(*BASE)), kaynak="hudl")
    r_sb = one(lab_sb, "E0|2015-08-08|Arsenal|Chelsea")
    assert r_sb["xg_h"] == 1.4 and r_sb["sut_h"] == 12 and r_sb["time"] == "12:45"


# 2
def test_single_source_missing_ht_is_not_completed_from_other_source():
    lab, out = A.explore(archive(rows(*BASE)), kaynak="openfootball")
    r = one(lab, MID)
    assert np.isnan(r["hthg"]) and np.isnan(r["htag"]) and r["veri_kalitesi"] == "IY_YOK"
    assert np.isnan(r["A"]) and np.isnan(r["C"]) and r["iy_ms"] is None and r["B"] == 0.0  # MS pazarı bilinir
    assert out["iy_gecerli"] == 0 and out["pazarlar"]["C"] == {**out["pazarlar"]["C"], "gecerli": 0, "bilinmiyor": 1}
    # Birleştirilmiş görünümde İY StatsBomb'dan gelir ve bu açıkça yazılır
    labm, outm = A.explore(archive(rows(*BASE)))
    m = one(labm, MID)
    assert (m["hthg"], m["htag"]) == (1.0, 0.0) and m["iy_kaynaklari"] == SB and m["alan_birlesimi"]
    assert "İY: hudl" in m["alan_kokeni"] and "xG: hudl" in m["alan_kokeni"]
    assert outm["alan_birlesimi_iceren_mac"] == 1


# 3
def test_merged_view_dedups_and_lists_sources():
    lab, out = A.explore(archive(rows(*BASE)), kaynak="birlesik")
    assert len(lab) == 1 and out["mac"] == 1 and out["liste_satiri"] == 1 and out["kaynak_satiri"] == 2
    r = one(lab, MID)
    assert r["kaynaklar"] == f"{OF},{SB}" and r["ms_kaynaklari"] == f"{OF},{SB}" and r["bagimsiz_kaynak"] == 2
    assert out["gorunum"]["tur"] == A.VIEW_MERGED and out["gorunum"]["kaynak"] is None
    assert "tek bir kaynak değildir" in out["gorunum"]["aciklama"]
    assert "alan birleştirmesi" in out["gorunum"]["aciklama"]
    assert "model eğitimi veya tahmin gösterimi izni değildir" in out["gorunum"]["kullanim"]


# 4 + 5
def test_single_source_not_blocked_by_other_sources_conflict_but_merged_shows_it():
    ar = archive(rows(*BASE, *CONFLICT))
    lab_of, out_of = A.explore(ar, kaynak="openfootball")
    r = one(lab_of, MID_C)
    assert r["durum"] == "TAMAM" and (r["fthg"], r["ftag"]) == (3.0, 1.0) and out_of["celiskili"] == 0
    lab_sb, _ = A.explore(ar, kaynak="hudl")
    assert one(lab_sb, "E0|2015-08-15|Chelsea|Arsenal")["fthg"] == 2.0
    lab_m, out_m = A.explore(ar)
    m = one(lab_m, MID_C)
    assert m["durum"] == "CELISKI" and np.isnan(m["fthg"]) and np.isnan(m["B"])  # çoğunluk/son commit seçilmez
    assert out_m["celiskili"] == 1 and out_m["celiski_kaynak_satiri"] == 2 and out_m["birlesik_gecerli"] == 1


# 6
def test_closed_source_selection_does_not_bring_other_sources():
    # Savunma: arşiv satırlarına analizi kapalı kaynağın satırı karışmış olsa bile hiçbir görünüme girmez
    r = rows(*BASE, of("2015-08-22", "Arsenal FC", "Everton FC", (1, 1)),
             {"kaynak": DS, "date": "2015-08-22", "home": "Arsenal", "away": "Everton", "fthg": 1, "ftag": 1})
    ar = archive(r)
    lab, out = A.explore(ar, kaynak="datasets")
    assert lab.empty and out["mac"] == 0 and out["gorunum"]["tarihsel_analiz_kapali"]
    assert "kapalı" in out["gorunum"]["aciklama"] and out["pazarlar"]["B"]["gecerli"] == 0
    lab_m, _ = A.explore(ar)
    assert DS not in ",".join(lab_m["kaynaklar"])


# 7
def test_other_season_conflict_not_in_selected_season_counters():
    r = rows(*BASE, *[{**x, "season": "2014/15", "date": "2015-04-15"} for x in CONFLICT])
    ar = archive(r)
    _, s16 = A.explore(ar, sezon="2015/16")
    assert s16["celiskili"] == 0 and s16["celiski_kaynak_satiri"] == 0 and s16["celiski_kaydi"] == 0
    _, s15 = A.explore(ar, sezon="2014/15")
    assert s15["celiskili"] == 1 and s15["celiski_kaynak_satiri"] == 2
    _, all_ = A.explore(ar)
    assert all_["celiskili"] == 1


TEAM_ROWS = [
    of("2015-08-08", "Arsenal FC", "Chelsea FC", (2, 1), (1, 0)),
    of("2015-08-15", "Everton FC", "Arsenal FC", (0, 3), (0, 2)),
    of("2015-08-22", "Arsenal FC", "Everton FC", (1, 1), (1, 1)),
    of("2015-08-29", "Chelsea FC", "Everton FC", (4, 0), (2, 0)),
    sb("2015-08-08", "Arsenal", "Chelsea", (2, 1), (1, 0)),
    # kimliği kesinleşmeyen kaynak satırları
    sb("2015-08-22", "Arsenal", "Arsenal Women", (1, 0)),        # ev tarafı Arsenal FC'ye çözülüyor
    sb("2015-08-29", "Chelsea U21", "Everton", (0, 0)),           # ev tarafı çözülemiyor, deplasman Everton FC
    sb("2015-08-15", "Everton Reserves", "Chelsea", (1, 1)),      # ev tarafı çözülemiyor, deplasman Chelsea FC
]


# 8
def test_team_and_side_filters_identical_for_list_and_counters():
    ar = archive(rows(*TEAM_ROWS))
    lab, out = A.explore(ar, takim="Arsenal FC", yer="ev")
    assert set(lab["home"]) == {"Arsenal FC"} and len(lab) == 2 and out["mac"] == 2
    ok = lab[lab["durum"] == "TAMAM"]
    for short in ("A", "B", "C"):
        assert out["pazarlar"][short]["gecerli"] + out["pazarlar"][short]["bilinmiyor"] == len(ok)
        assert out["pazarlar"][short]["evet"] == int((ok[short] == 1.0).sum())
    assert out["iy_ms_gecerli"] == int(ok["iy_ms"].notna().sum())
    assert out["kimlik_incelemesi_kaynak_satiri"] == 1  # yalnızca Arsenal'in ev sahibi olduğu çözülmemiş satır
    lab_d, out_d = A.explore(ar, takim="Arsenal FC", yer="deplasman")
    assert set(lab_d["away"]) == {"Arsenal FC"} and out_d["kimlik_incelemesi_kaynak_satiri"] == 0
    # Başka takımın inceleme kaydı seçili takımın sorunu gibi görünmez; bilinemeyenler ayrı sayılır
    _, out_any = A.explore(ar, takim="Arsenal FC")
    assert out_any["kimlik_incelemesi_kaynak_satiri"] == 1
    assert out_any["kimlik_incelemesi_takima_indirgenemeyen"] == 2
    _, out_all = A.explore(ar)
    assert out_all["kimlik_incelemesi_kaynak_satiri"] == 3 and out_all["kimlik_incelemesi_takima_indirgenemeyen"] is None


# 9
def test_date_bounds_identical_for_list_denominator_and_review():
    ar = archive(rows(*TEAM_ROWS))
    lab, out = A.explore(ar, bas="2015-08-22", son="2015-08-22")
    assert list(lab["date"].dt.strftime("%Y-%m-%d")) == ["2015-08-22"]  # sınırlar dahil
    assert out["pazarlar"]["B"]["gecerli"] == 1 and out["mac"] == 1
    assert out["kimlik_incelemesi_kaynak_satiri"] == 1  # yalnızca aynı günün çözülmemiş satırı
    lab2, out2 = A.explore(ar, bas="2015-08-16", son="2015-08-29")
    assert len(lab2) == 2 and out2["kimlik_incelemesi_kaynak_satiri"] == 2


# 10
def test_conflicting_match_with_two_source_rows_is_one_match():
    _, out = A.explore(archive(rows(*CONFLICT)))
    assert out["mac"] == 1 and out["liste_satiri"] == 1 and out["celiskili"] == 1
    assert out["celiski_kaynak_satiri"] == 2 and out["kaynak_satiri"] == 2 and out["blok_sayisi"] == 2
    assert out["birimler"]["mac"].startswith("benzersiz maç")
    # Tarih uyuşmazlığı: iki aday satır tek eşleşme olarak sayılır
    r = rows(of("2015-08-15", "Chelsea FC", "Arsenal FC", (3, 1)), sb("2015-08-16", "Chelsea", "Arsenal", (3, 1)))
    _, out_t = A.explore(archive(r))
    assert out_t["incelemede"] == 1 and out_t["incelemede_liste_satiri"] == 2 and out_t["mac"] == 1
    assert out_t["kimlik_veya_tarih_incelemesi"] == 0  # aynı uyuşmazlık iki kez sayılmaz


# 11
def test_file_level_quarantine_is_not_a_filtered_exact_zero(tmp_path, capsys):
    blocks = [{"kaynak": OF, "lig": "E0", "sezon": "2015/16", "yol": "2015-16/en.1.json", "dosya_sha256": "x",
               "tarihsel_analiz": True, "karantina": {"TARIH_SEZON_DISI": 66}, "blok": 0}]
    ar = archive(rows(*TEAM_ROWS), blocks=blocks)
    _, out = A.explore(ar, sezon="2015/16", takim="Arsenal FC", bas="2015-08-01")
    k = out["kaynak_karantinasi_kapsami"]
    assert out["kaynak_karantinasi"] == {"TARIH_SEZON_DISI": 66} and k["toplam"] == 66
    assert k["takim_tarih_filtresine_indirgenebilir"] is False and k["takim_tarih_filtresi_var"] is True
    assert "indirgenemez" in k["not"]
    _, other = A.explore(ar, sezon="2016/17")
    assert other["kaynak_karantinasi_kapsami"]["toplam"] == 0 and other["kaynak_karantinasi_kapsami"]["blok_sayisi"] == 0
    from bahis_tahmin.cli import _archive_counter_lines

    text = "\n".join(_archive_counter_lines(out))
    assert "toplam karantina: 66" in text and "takım/tarih filtresine indirgenemez" in text
    assert "Genel arşiv durumu (filtreden bağımsız)" in text
    from bahis_tahmin.ui.pages.archive_panel import summary_html

    assert "toplam karantina: 66" in summary_html(out) and "indirgenemez" in summary_html(out)


# 12
def test_short_name_and_registry_key_give_identical_results():
    ar = archive(rows(*BASE, *CONFLICT))
    for short, key in A.SHORT_NAMES.items():
        l1, o1 = A.explore(ar, kaynak=short)
        l2, o2 = A.explore(ar, kaynak=key)
        pd.testing.assert_frame_equal(l1, l2)
        assert json.dumps(o1, sort_keys=True, default=str) == json.dumps(o2, sort_keys=True, default=str)
    l3, o3 = A.explore(ar, kaynak=None)
    l4, o4 = A.explore(ar, kaynak="birlesik")
    pd.testing.assert_frame_equal(l3, l4)
    with pytest.raises(A.ArchiveError):
        A.explore(ar, kaynak="football-data")


def season_rows():
    """İki sezon: 2014/15 sonu ve 2015/16 başı (openfootball), 2015/16'da StatsBomb İY'si."""
    out = []
    for i, (h, a, ft, ht) in enumerate([("Arsenal FC", "Chelsea FC", (1, 0), (1, 0)),
                                        ("Everton FC", "Arsenal FC", (0, 0), None),
                                        ("Arsenal FC", "Everton FC", (2, 2), (1, 1))]):
        out.append(of(f"2015-0{3 + i}-01", h, a, ft, ht, season="2014/15"))
    out += [of("2015-08-08", "Arsenal FC", "Chelsea FC", (2, 1)),
            of("2015-08-15", "Everton FC", "Arsenal FC", (1, 3), (0, 1)),
            sb("2015-08-08", "Arsenal", "Chelsea", (2, 1), (1, 0), xg_h=1.4, xg_a=0.6)]
    return out


# 13
def test_single_source_card_uses_same_view_and_marks_window_scope():
    ar = archive(rows(*season_rows()))
    flt = {"sezon": "2015/16"}
    card = A.event_card_for(ar, MID, "Arsenal FC", kaynak="openfootball", liste_filtresi=flt)
    g = card["gorunum"]
    assert g["tur"] == A.VIEW_SINGLE and g["kaynak"] == OF
    assert card["kaynak"]["kaynak"] == OF  # olay satırının kaynağı: yalnızca seçili kaynak
    assert card["EVENT_OUTCOME"]["iy_ev_dep"] is None  # openfootball'da İY yok; StatsBomb'dan tamamlanmaz
    pre = [rec for w in card["PRE_EVENT"].values() for rec in w["maclar"]]
    assert pre and {rec["source"] for rec in pre} == {OF}
    assert "2014/15" in g["pencere_sezonlari"] and g["liste_disi_pencere_maci"] >= 3  # önceki sezona taşıyor
    assert "önceki/sonraki sezona taşabilir" in g["pencere_kapsami"]
    merged = A.event_card_for(ar, MID, "Arsenal FC")
    assert merged["gorunum"]["kaynak"] is None and merged["EVENT_OUTCOME"]["iy_ev_dep"] == "1-0"
    with pytest.raises(A.ArchiveError):  # StatsBomb görünümünde bu kimlik (openfootball adları) yok
        A.event_card_for(ar, MID, "Arsenal FC", kaynak="hudl")
    sbc = A.event_card_for(ar, "E0|2015-08-08|Arsenal|Chelsea", "Arsenal", kaynak="hudl")
    assert sbc["kaynak"]["kaynak"] == SB and sbc["EVENT_OUTCOME"]["iy_ev_dep"] == "1-0"


# 14
def test_row_order_does_not_change_results():
    recs = [*BASE, *CONFLICT, *TEAM_ROWS[1:4], of("2015-09-01", "Arsenal FC", "Stoke City FC", (1, 0), time="15:00"),
            sb("2015-09-01", "Arsenal", "Stoke City", (1, 0), (0, 0), time="12:45", saglayici_mac_id="9"),
            sb("2015-09-01", "Arsenal", "Stoke City", (1, 0), (0, 0), time="12:45", saglayici_mac_id="8", blok=3)]
    base = rows(*recs)
    ref = None
    rng = np.random.default_rng(7)
    for _ in range(6):
        r = base.iloc[rng.permutation(len(base))].reset_index(drop=True)
        ar = archive(r)
        res = []
        for k in (None, "openfootball", "hudl"):
            lab, out = A.explore(ar, kaynak=k)
            res.append((lab.sort_values("mac_kimligi").reset_index(drop=True), json.dumps(out, sort_keys=True,
                                                                                            default=str)))
        if ref is None:
            ref = res
            m = one(res[0][0], "E0|2015-09-01|Arsenal FC|Stoke City FC")
            assert m["time"] == "15:00" and m["saat_kaynagi"] == OF and m["saglayici_mac_id"] == "8,9"
            continue
        for (l1, o1), (l2, o2) in zip(ref, res):
            pd.testing.assert_frame_equal(l1, l2)
            assert o1 == o2


# 15
def test_market_labels_unchanged_against_central_registry():
    from bahis_tahmin.goals.markets import PRIMARY_YES, SHORT, htft_frame, label_frame

    r = rows(*TEAM_ROWS[:4])
    lab, _ = A.explore(archive(r), kaynak="openfootball")
    lab = lab.sort_values("date").reset_index(drop=True)
    raw = r.sort_values("date").reset_index(drop=True)
    expect = label_frame(raw, PRIMARY_YES)
    for key in PRIMARY_YES:
        np.testing.assert_array_equal(lab[SHORT[key]].to_numpy(dtype=float), expect[key].to_numpy(dtype=float))
    assert list(lab["iy_ms"]) == list(htft_frame(raw))


# 16
def test_filters_never_reuse_a_previous_summary():
    ar = archive(rows(*season_rows(), *CONFLICT))
    seq = [{"sezon": "2014/15"}, {"sezon": "2015/16", "kaynak": "openfootball"}, {}, {"sezon": "2014/15"},
           {"kaynak": "hudl"}]
    fresh = [A.explore(archive(rows(*season_rows(), *CONFLICT)), **f)[1] for f in seq]
    got = [A.explore(ar, **f)[1] for f in seq]
    for a, b in zip(fresh, got):
        assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    assert [g["filtre"] for g in got] == [{"kaynak": "birlesik", "sezon": "2014/15"},
                                          {"kaynak": OF, "sezon": "2015/16"}, {"kaynak": "birlesik"},
                                          {"kaynak": "birlesik", "sezon": "2014/15"}, {"kaynak": SB}]
    assert got[0] == got[3] and got[0]["mac"] == 3 and got[4]["mac"] == 2 and got[2]["celiskili"] == 1
    assert got[1]["celiskili"] == 0 and got[0]["celiskili"] == 0  # başka sezon/görünüm çelişkisi karışmaz


# 13 + 16 (arayüz): liste, özet ve kart aynı görünümde; filtre değişince özet yeniden hesaplanır
def test_ui_panel_list_summary_and_card_share_view(tmp_home):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from bahis_tahmin.ui.controller import AppController
    from bahis_tahmin.ui.pages.archive_panel import ArchivePanel, summary_html

    ar = archive(rows(*season_rows()))
    panel = ArchivePanel(AppController())
    panel.show_archive(ar)
    app.processEvents()
    assert panel._listed[0].kaynak is None and "Birleştirilmiş görünüm" in panel.view_note.text()
    panel.cb_source.setCurrentIndex(panel.cb_source.findData(OF))  # görünüm değişimi listeyi ve özeti yeniler
    v, flt = panel._listed
    assert v.kaynak == OF and set(panel.match_model.frame["kaynaklar"]) == {OF}
    assert panel.summary.text() == summary_html(A.explore_view(ar, v, **flt)[1])
    assert set(panel.match_model.frame["alan_kokeni"]) == {""}
    assert panel.cb_team.findData("Arsenal") == -1 and panel.cb_team.findData("Arsenal FC") >= 0
    panel.cb_season.setCurrentIndex(panel.cb_season.findData("2014/15"))
    panel.apply_filters()
    assert panel.summary.text() == summary_html(A.explore(ar, kaynak=OF, sezon="2014/15")[1])
    assert set(panel.match_model.frame["mac_kimligi"].str[3:7]) == {"2015"}
    panel.cb_season.setCurrentIndex(panel.cb_season.findData("2015/16"))
    panel.apply_filters()
    row = panel.match_model.frame.index[panel.match_model.frame["mac_kimligi"] == MID][0]
    panel.match_view.selectRow(int(row))
    # Seçim kutusu sinyalsiz değişse bile kart, LİSTELENEN görünümle açılır
    panel.cb_source.blockSignals(True)
    panel.cb_source.setCurrentIndex(0)
    panel.cb_source.blockSignals(False)
    panel.show_card()
    text = panel.card.toPlainText()
    assert f"Tek kaynak: {OF}" in text and "pencere maçı seçili listenin filtresi dışında" in text
    assert "MS (ev-dep) 2-1" in text and "İY (ev-dep) 1-0" not in text  # StatsBomb İY'si karta taşınmaz
    assert set(panel.card_model.frame["source"]) == {OF}

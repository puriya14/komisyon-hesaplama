"""Dizi araştırması orkestratörü ve maç öncesi görünüm.

YALNIZCA sentetik (açıkça test amaçlı, ``SENTETIK-TEST`` kaynaklı) veri ve geçici dizinler kullanılır; gerçek veri,
uygulama klasörü veya depo raporları okunmaz/yazılmaz.
"""

import json

import numpy as np
import pandas as pd
import pytest

from bahis_tahmin.goals.markets import HTFT_KEYS
from bahis_tahmin.sequences import config as C
from bahis_tahmin.sequences import null as N
from bahis_tahmin.sequences import patterns as P
from bahis_tahmin.sequences import research as RS
from bahis_tahmin.sequences.frame import build_frame
from bahis_tahmin.sequences.prematch import FIXTURE_SOURCE, prematch_frame, prematch_view
from bahis_tahmin.sequences.synthetic import synthetic_matches
from bahis_tahmin.sequences.timeline import build_team_matches, season_year


def _s0_table(m: pd.DataFrame, probs: pd.DataFrame) -> pd.DataFrame:
    """Sentetik 'S0 soy kaydı': üretici modelin kesin İY/MS olasılıkları + sabit A/B/C (yalnızca test)."""
    s0 = probs.copy()
    d = m.set_index(probs.index)["date"] if len(m) == len(probs) else None
    from bahis_tahmin.goals.ledger import event_id

    dates = {event_id(lg, dd, h, a): dd for lg, dd, h, a in zip(m["league"], m["date"], m["home"], m["away"])}
    s0["date"] = s0["event_id"].map(dates)
    s0["fold"] = season_year(s0["date"])
    s0["league"] = s0["event_id"].str.split("|").str[0] if d is None else m["league"].to_numpy()
    s0["train_until"] = ""
    s0["model_hash"] = "SENTETIK-TEST"
    s0["A"], s0["B"], s0["C"] = 0.08, 0.25, 0.25
    s0["HTFT_KUYRUK"] = 0.0
    return s0


@pytest.fixture(scope="module")
def synth():
    m, probs = synthetic_matches(n_leagues=2, n_seasons=27, n_teams=10, seed=11)
    return m, probs, _s0_table(m, probs)


@pytest.fixture(scope="module")
def frame(synth):
    m, probs, _ = synth
    return build_frame(build_team_matches(m), probs)


def test_parallel_reference_process_equals_serial(frame):
    masks = RS.period_masks(frame)
    prep = P.prepare(frame, masks["kesif"])
    ids = prep.hyp_ids[:60]
    serial = N.run_null(frame, masks["kesif"], 6, 123, prep=prep, hyp_ids=ids)
    par = RS.parallel_null_q1(frame, masks["kesif"], 6, 123, prep, ids, workers=2)
    assert np.array_equal(np.nan_to_num(serial["z"], nan=9e9), np.nan_to_num(par["z"], nan=9e9))
    assert np.array_equal(serial["supported"], par["supported"])
    # tek tekrarlık parça da aynı tohum akışını kullanır
    one = N.run_null(frame, masks["kesif"], 6, 123, prep=prep, hyp_ids=ids, reps=range(4, 6))
    assert np.array_equal(np.nan_to_num(one["z"], nan=9e9), np.nan_to_num(serial["z"][4:6], nan=9e9))


def test_pair_symmetric_masks_keep_twin_rows_together(frame):
    masks = RS.period_masks(frame)
    mr = frame.tm["mirror_row"].to_numpy()
    for m in masks.values():
        assert (m == m[mr]).all()


@pytest.fixture(scope="module")
def run(synth, tmp_path_factory):
    m, _, s0 = synth
    base = tmp_path_factory.mktemp("dizi")
    exp = base / "deneyler.jsonl"
    res = RS.run_research(m, base / "out", s0=s0, R=12, placebo_seeds=2, R_placebo=6, workers=1, record=True,
                          experiments_path=exp, reports_dir=base / "rep", data_label="SENTETIK-TEST")
    return res, base, exp


def test_research_records_every_hypothesis_and_family(run):
    res, base, exp = run
    f1 = res["aileler"]["F1"]
    assert f1["kalibrasyon_kapisi"]["gecti"] in (True, False)
    if f1["durum"] == "TAMAM":
        h = f1["hipotezler"]
        assert len(h) == f1["hipotez_ham"] == 800
        assert set(h["statu"]) <= set(C.STATUSES)
        assert h["statu"].notna().all() and h["gerekce"].notna().all()
        csv = pd.read_csv(base / "out" / "f1_hipotezler.csv")
        assert len(csv) == 800  # başarısızlar dahil hepsi kayıtlı
    lines = [json.loads(x) for x in exp.read_text(encoding="utf-8").splitlines()]
    stages = [x["asama"] for x in lines]
    assert stages[0].startswith("dizi-uygulama-kararlari")
    for fam in ("F1", "F2", "F3", "F4", "F5", "F6", "F7"):
        assert f"dizi-arastirma {fam}" in stages
    man = res["manifest"]
    for k in ("veri_sha256", "kod_sha256", "parametre_ozeti", "uygulama_kararlari_sha256", "satir_kumeleri", "tohum",
              "temiz_test", "hesaplama_butcesi"):
        assert k in man
    assert man["hesaplama_butcesi"]["harici_api_cagrisi"] == 0


def test_null_synthetic_data_does_not_declare_supported_patterns(run):
    """Sentetik veri S0'ın kendisinden üretildi (gerçek dizi etkisi yok): örneklem dışı desteklenen örüntü çıkmamalı."""
    res, _, _ = run
    for fam in ("F1", "F2"):
        f = res["aileler"][fam]
        df = f.get("hipotezler")
        if isinstance(df, pd.DataFrame) and len(df):
            assert (df["statu"] != "OUT_OF_SAMPLE_SUPPORTED").all()


def test_economic_family_never_reports_zero_roi_for_unavailable_markets(run):
    res, _, _ = run
    f6 = res["aileler"]["F6"]
    for per in ("parametre", "test"):
        for t in ("IY_GERIDE_MS_GALIP", "IY_ONDE_MS_MAGLUP"):
            assert f6[per]["hedefler"][t]["roi"] == C.ROI_UNAVAILABLE
        for t in ("GALIBIYET", "MAGLUBIYET"):  # sentetik veride oran yok → hesaplanamıyor, sıfır değil
            for src in f6[per]["hedefler"][t]["kaynaklar"].values():
                assert src["roi"] == C.ROI_UNAVAILABLE


def test_outputs_keep_anomalies_local_and_unaggregated(run):
    res, base, _ = run
    rep = json.loads((base / "rep" / "dizi_sonuclar.json").read_text(encoding="utf-8"))
    assert "anomaliler" not in rep  # depoya tekil maç anomali kaydı yazılmaz
    summ = rep["anomali_ozeti"]
    assert set(summ) <= {"toplam", "tur", "durum", "donem", "tur_durum_donem", "not", "baglanti"}
    text = json.dumps(summ, ensure_ascii=False).lower()
    assert "şike olasılığı" not in text.replace("suç/şike olasılığı değildir", "")
    ui = json.loads((base / "out" / "son_sonuclar.json").read_text(encoding="utf-8"))
    for r in ui["anomaliler"]:
        assert "team" not in r and "opponent" not in r and "referee" not in r


def test_rerun_with_same_manifest_and_seed_is_identical(frame):
    masks = RS.period_masks(frame)
    a = RS.run_f1(frame, masks, R=8, seed=7)
    b = RS.run_f1(frame, masks, R=8, seed=7)
    if a["durum"] == "TAMAM":
        pa, pb = a["hipotezler"]["p_adj"].to_numpy(), b["hipotezler"]["p_adj"].to_numpy()
        assert np.array_equal(np.nan_to_num(pa, nan=-1), np.nan_to_num(pb, nan=-1))
        assert a["statu_sayilari"] == b["statu_sayilari"]


def test_changed_definition_after_test_opened_is_not_clean():
    man = {"on_kayitla_uyum": {"sozlesme": True, "parametre": True, "esleme": True}, "parametre_ozeti": "p1",
           "uygulama_kararlari_sha256": "k1", "kod_sha256": "c2"}
    earlier = [{"asama": "dizi-arastirma F1", "zaman_utc": "2026-10-10T10:00:00+00:00", "parametre_ozeti": "p1",
                "kararlar_sha256": "k1", "kod_sha256": "c1"}]
    st = RS.clean_test_status(man, earlier)
    assert not st["temiz"] and "kod_sha256" in st["nedenler"][0]
    assert RS.clean_test_status({**man, "kod_sha256": "c1"}, earlier)["temiz"]
    # YALNIZCA TEST: elle kurulmuş statü tablosu
    hyp = pd.DataFrame({"hyp_id": ["X|a"], "statu": ["OUT_OF_SAMPLE_SUPPORTED"], "gerekce": ["-"], "tekil": [True]})
    results = {"aileler": {"F1": {"hipotezler": hyp, "adaylar": [{"statu": "OUT_OF_SAMPLE_SUPPORTED"}]},
                           "F3": {"holm": [{"statu": "OUT_OF_SAMPLE_SUPPORTED"}]},
                           "F4": {"events": {"E": {"status": "OUT_OF_SAMPLE_SUPPORTED"}}}}}
    RS._downgrade_unclean(results, st)
    assert hyp["statu"].iloc[0] == "EXPLORATORY" and "temiz değil" in hyp["gerekce"].iloc[0]
    assert results["aileler"]["F1"]["adaylar"][0]["statu"] == "EXPLORATORY"
    assert results["aileler"]["F3"]["holm"][0]["statu"] == "EXPLORATORY"
    assert results["aileler"]["F4"]["events"]["E"]["status"] == "EXPLORATORY"
    assert RS.clean_test_status({**man, "on_kayitla_uyum": {"parametre": False}}, [])["temiz"] is False


# ----------------------------------------------------------------------------- maç öncesi görünüm

@pytest.fixture(scope="module")
def prematch(synth):
    m, probs, _ = synth
    last = m["date"].max()
    cut = last - pd.Timedelta(days=21)  # son 3 hafta "yaklaşan" kabul edilir (sonuçları gizlenir)
    played = m[m["date"] <= cut].reset_index(drop=True)
    fx = m[m["date"] > cut][["league", "date", "time", "home", "away"]].copy()
    fx["source"] = "SENTETIK-TEST"
    pf = prematch_frame(played, fx, probs)
    return pf, m, probs


def test_prematch_atoms_equal_full_data_atoms_for_next_match(prematch):
    pf, m, probs = prematch
    full = build_frame(build_team_matches(m), probs, with_s1=False)
    tm = pf["tm"]
    up = np.where(pf["upcoming"])[0]
    first = tm.iloc[up].groupby("team").head(1).index.to_numpy()  # takımın bir sonraki maçı
    assert len(first) > 0
    key = full.tm.set_index(["event_id", "is_home"])
    for r in first:
        j = key.index.get_loc((tm.at[r, "event_id"], bool(tm.at[r, "is_home"])))
        for a in C.HISTORY_ATOMS:
            x, y = pf["atoms"][a][r], full.atoms[a][j]
            assert (np.isnan(x) and np.isnan(y)) or x == y, a


def test_prematch_view_has_no_post_event_and_keeps_failures(prematch):
    pf, _, _ = prematch
    tm = pf["tm"]
    up = np.where(pf["upcoming"])[0]
    views = [prematch_view(pf, int(r)) for r in tm.iloc[up].groupby("team").head(1).index]
    text = json.dumps(views, ensure_ascii=False, default=str)
    assert "POST_EVENT" not in text and "EVENT_OUTCOME" not in text
    secs = [s for v in views for s in v["benzer_kosullar"]]
    assert secs, "en az bir takımın doğru koşulu olmalı"
    for s in secs:
        assert s["n_gecmis"] == s["isabet"] + s["iska"]  # başarısız örnekler dışlanmaz
        if s["iska"]:
            assert s["ornekler_iska"] and not any(e["hedef_gerceklesti"] for e in s["ornekler_iska"])
        assert s["olasiliga_etki"] == "yok"  # ham benzerlik olasılık olarak kullanılmaz
        assert s["statu"] == "KAYIT_YOK"
    played = int(np.where(~pf["upcoming"])[0][0])
    with pytest.raises(ValueError):
        prematch_view(pf, played)


def test_prematch_examples_only_use_labels_known_before_decision(prematch):
    pf, _, _ = prematch
    tm = pf["tm"]
    r = int(np.where(pf["upcoming"])[0][0])
    v = prematch_view(pf, r)
    dec = pd.Timestamp(v["kimlik"]["date"])
    for s in v["benzer_kosullar"]:
        for e in s["ornekler_isabet"] + s["ornekler_iska"]:
            assert pd.Timestamp(e["tarih"]) + pd.Timedelta(days=1) < dec
    assert (tm.loc[pf["upcoming"], "source"] == FIXTURE_SOURCE).all()

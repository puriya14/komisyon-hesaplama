"""Anomali görünümü, resmî karar kaydı ve ileriye dönük araştırma defteri (sözleşme §9 PAPER_TRADING, §11).

Yalnızca sentetik veri ve geçici dizinler.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import inspect
import json
import re

import numpy as np
import pytest

from bahis_tahmin.sequences import anomaly as A
from bahis_tahmin.sequences import config as C
from bahis_tahmin.sequences import official as O
from bahis_tahmin.sequences import research_ledger as RL
from bahis_tahmin.sequences.synthetic import synthetic_frame
from bahis_tahmin.timeutil import ISTANBUL, now_utc

WRONGDOING = ("sike", "şike", "suc", "suç", "fraud", "manip", "wrong", "hile", "crime", "guilt", "probability_of")
GROUP_WORDS = ("team", "takim", "takım", "opponent", "rakip", "league", "lig", "referee", "hakem", "kulup", "kulüp",
               "club", "player", "oyuncu")


@pytest.fixture(scope="module")
def syn():
    # 20 takım → lig-sezon başına 380 maç (gerçek liglere benzer havuz); 2004–2009 → ısınma + keşif dönemleri
    fr, _, _ = synthetic_frame(seed=0, n_leagues=2, n_seasons=6, n_teams=20, start_year=2004)
    return fr


def _with_tm(fr, **cols):
    """tm kopyası; ``cols``: sütun → {satır: değer}."""
    tm = fr.tm.copy()
    for c, upd in cols.items():
        vals = tm[c].to_numpy().copy()
        for r, v in upd.items():
            vals[r] = v
        tm[c] = vals
    return dataclasses.replace(fr, tm=tm)


def _market_like_s0(fr, seed=3, scale=0.01):
    """Piyasa ≈ S0 + küçük gürültü (eşitlik olmasın diye); yalnızca galibiyet sütunu kullanılır."""
    rng = np.random.default_rng(seed)
    mkt = np.column_stack([fr.p0["GALIBIYET"], fr.p0["BERABERLIK"], fr.p0["MAGLUBIYET"]]).astype(float)
    mkt[:, 0] = np.clip(mkt[:, 0] + rng.normal(0, scale, len(mkt)), 0.01, 0.99)
    return mkt


def _keys(obj) -> list[str]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            out += _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _keys(v)
    return out


def _unexplained_candidate(records):
    for r in records:
        if r["type"] == A.TYPE_SURPRISE and r["status"] == A.TYPE_SURPRISE and r["flags"] == [A.TYPE_SURPRISE]:
            return r
    raise AssertionError("açıklanamayan aday bulunamadı")


def _rows_of(fr, pair_id):
    tm = fr.tm
    idx = np.where(tm["pair_id"].to_numpy() == pair_id)[0]
    home = int(idx[tm["is_home"].to_numpy()[idx]][0])
    return home, int(tm["mirror_row"].to_numpy()[home])


def _brute_top(values: np.ndarray, top: float) -> np.ndarray:
    """Kaba kuvvet orta-sıra üst pay kuralı: (daha büyük + eşitlerin yarısı, kendisi dahil) / n < top."""
    v = np.asarray(values, dtype=float)
    ok = ~np.isnan(v)
    out = np.zeros(len(v), dtype=bool)
    w = v[ok]
    greater = (w[None, :] > w[:, None]).sum(axis=1)
    equal = (w[None, :] == w[:, None]).sum(axis=1)
    out[ok] = (greater + 0.5 * equal) / len(w) < top - 1e-12
    return out


def _surprise_pairs(recs) -> set:
    return {r["pair_id"] for r in recs if A.TYPE_SURPRISE in r["flags"]}


def _set_realised_p(fr, pairs, p):
    """Verilen maçların gerçekleşen hücre olasılığını ``p`` yapar (iki satırda da)."""
    raw = fr.raw_probs.copy()
    cell = fr.tm["raw_cell"].to_numpy()
    for pid in pairs:
        for r in _rows_of(fr, pid):
            raw[r, cell[r]] = p
    return dataclasses.replace(fr, raw_probs=raw)


# ----------------------------------------------------------------------------
# Anomali: sürpriz bittir, aday kuralı, kontrol listesi
# ----------------------------------------------------------------------------

def test_surprise_is_bits_of_realised_cell(syn):
    bits = A.surprise_bits(syn)
    cell = syn.tm["raw_cell"].to_numpy()
    i = np.arange(len(cell))
    expected = -np.log2(syn.raw_probs[i, cell])
    assert np.allclose(bits, expected)
    assert (bits > 0).all()
    mirror = syn.tm["mirror_row"].to_numpy()
    assert np.array_equal(bits, bits[mirror])  # maç düzeyi: ikiz satırlar aynı
    # Bilinmeyen hücre veya S0 yoksa NaN
    h, a = _rows_of(syn, 5)
    raw = syn.raw_probs.copy()
    raw[[h, a]] = np.nan
    fr2 = _with_tm(dataclasses.replace(syn, raw_probs=raw), raw_cell={10: -1})
    b2 = A.surprise_bits(fr2)
    assert np.isnan(b2[[h, a, 10]]).all()
    assert np.isfinite(np.delete(b2, [h, a, 10])).all()


def test_records_carry_bits_and_no_wrongdoing_probability(syn):
    recs = A.flag_anomalies(syn)
    assert recs
    for r in recs:
        assert r["note"] == "Anomali puanı suç/şike olasılığı değildir; kulüp/oyuncu/hakem etiketi verilmez."
        assert r["surprise_bits"] == pytest.approx(-np.log2(r["s0_p_gerceklesen"]))
        assert all(not any(w in k.lower() for w in WRONGDOING) for k in _keys(r))
        assert r["status"] not in C.STATUSES and r["type"] in A.TYPES
        assert not any(k in r for k in ("pattern_status", "decision", "stake", "ledger"))
    summ = A.anomaly_summary(recs)
    assert all(not any(w in k.lower() for w in WRONGDOING) for k in _keys(summ))


def test_candidates_are_top_share_within_league_season(syn):
    recs = A.flag_anomalies(syn)
    got = _surprise_pairs(recs)
    tm = syn.tm
    home = tm["is_home"].to_numpy()
    bits = A.surprise_bits(syn)[home]
    pair = tm["pair_id"].to_numpy()[home]
    cl = np.asarray(syn.cluster)[home]
    top = 1 - C.ANOMALY_QUANTILE
    expected = set()
    for c in np.unique(cl):
        sel = cl == c
        assert sel.sum() == 380
        hit = _brute_top(bits[sel], top)
        assert hit.sum() == 2  # 380 sürekli değerde ≈ round(380 × %0,5) = 2 (nominal paya yakın)
        expected |= set(pair[sel][hit].tolist())
    assert got == expected
    assert len({r["pair_id"] for r in recs}) == len(recs)  # pair_id başına tek kayıt
    for r in recs:
        assert r["surprise_pool_n"] == 380 and r["surprise_top_share"] < top
    # Maske: yalnızca maskedeki maçlar raporlanır; referans havuz maskeden bağımsızdır (aynı kayıtlar)
    per = np.asarray(syn.period, dtype=object)
    sub = A.flag_anomalies(syn, per == "kesif")
    full = {r["pair_id"]: r for r in recs}
    assert sub and all(r["period"] == "kesif" for r in sub)
    assert all(full[r["pair_id"]] == r for r in sub)
    assert {r["pair_id"] for r in sub} == {p for p, r in full.items() if r["period"] == "kesif"}


def test_mask_cannot_build_team_pool(syn):
    """Tek takımlık maske takım bazında "en üst" maç üretemez: yalnızca tam görünümdeki adaylardan o takımınkiler."""
    tm = syn.tm
    full = _surprise_pairs(A.flag_anomalies(syn))
    for team in tm["team"].unique()[:4]:
        m = (tm["team"] == team).to_numpy()
        got = _surprise_pairs(A.flag_anomalies(syn, m))
        assert got == full & set(tm.loc[m, "pair_id"])
    with pytest.raises(ValueError):
        A.flag_anomalies(syn, np.ones(len(tm), dtype=int))  # boolean olmayan maske
    with pytest.raises(ValueError):
        A.flag_anomalies(syn, np.ones(len(tm) - 1, dtype=bool))


def test_small_pool_yields_no_candidate(syn):
    """En üst %0,5 ancak > 100 maçlık havuzda tanımlıdır: küçük havuzda (ör. devam eden sezon) en büyük değer bile aday değil."""
    tm = syn.tm
    home = tm["is_home"].to_numpy()
    c0 = np.asarray(syn.cluster)[home][0]
    pairs = tm["pair_id"].to_numpy()[home][np.asarray(syn.cluster)[home] == c0]
    target = int(pairs[50])
    for keep, flagged in ((100, False), (101, True)):
        fr = _set_realised_p(syn, [target], 1e-12)
        raw = fr.raw_probs.copy()
        drop = np.isin(tm["pair_id"].to_numpy(), pairs[keep:])
        raw[drop] = np.nan  # S0 yok → havuz dışında
        fr = dataclasses.replace(fr, raw_probs=raw)
        recs = [r for r in A.flag_anomalies(fr) if r["cluster"] == c0]
        assert (target in _surprise_pairs(recs)) is flagged
        assert len(_surprise_pairs(recs)) == int(flagged)
        if flagged:
            assert recs[0]["surprise_pool_n"] == keep


def test_ties_and_infinite_surprise_are_deterministic(syn):
    tm = syn.tm
    home = tm["is_home"].to_numpy()
    cl = np.asarray(syn.cluster)[home]
    c0 = cl[0]
    pairs = tm["pair_id"].to_numpy()[home][cl == c0]
    # p = 0 → +∞ bit; iki eşit +∞: orta-sıra üst pay 1/380 < %0,5 → ikisi de aday, başka aday yok
    two = [int(pairs[10]), int(pairs[200])]
    fr2 = _set_realised_p(syn, two, 0.0)
    recs = [r for r in A.flag_anomalies(fr2) if r["cluster"] == c0]
    assert _surprise_pairs(recs) == set(two)
    assert all(r["surprise_bits"] == np.inf and r["s0_p_gerceklesen"] == 0.0 for r in recs)
    # dört eşit +∞: orta-sıra üst pay 2/380 > %0,5 → eşit blok birlikte dışarıda kalır (aynı karar), aday yok
    four = [int(pairs[k]) for k in (10, 100, 200, 300)]
    fr4 = _set_realised_p(syn, four, 0.0)
    assert not [r for r in A.flag_anomalies(fr4) if r["cluster"] == c0]
    b = A.surprise_bits(fr4)[home][cl == c0]
    assert np.array_equal(_brute_top(b, 1 - C.ANOMALY_QUANTILE), np.zeros(len(b), dtype=bool))


def test_checklist_items_and_unavailable_checks(syn):
    recs = A.flag_anomalies(syn)
    for r in recs:
        names = [c["kontrol"] for c in r["checklist"]]
        assert names == list(A.CHECK_NAMES)
        by = {c["kontrol"]: c for c in r["checklist"]}
        for n in A.UNAVAILABLE_CHECKS:
            assert by[n]["sonuc"] == "değerlendirilemedi (veri yok)" and not by[n]["aciklar"]
        assert "ortak kaynak" in by["ortak veri kaynağı"]["sonuc"] and not by["ortak veri kaynağı"]["aciklar"]
        assert by["kırmızı kart"]["sonuc"] == "değerlendirilemedi"  # sentetik veride kırmızı kart yok
        explained = any(c["aciklar"] for c in r["checklist"])
        assert r["status"] == ("açıklanabilir" if explained else A.TYPE_SURPRISE)


def test_red_card_explains_surprise_but_not_market_gap(syn):
    base = A.flag_anomalies(syn)
    cand = _unexplained_candidate(base)
    h, a = _rows_of(syn, cand["pair_id"])
    # Piyasa farkı: bu maçın piyasa olasılığını S0'dan çok uzaklaştır → ayrı bayrak
    mkt = _market_like_s0(syn)
    mkt[h, 0] = np.clip(syn.p_win[h] + 0.5, 0, 0.99) if syn.p_win[h] < 0.45 else syn.p_win[h] - 0.4
    fr_m = dataclasses.replace(syn, mkt=mkt)
    zero = _with_tm(fr_m, red_for={h: 0.0, a: 0.0}, red_against={h: 0.0, a: 0.0})
    rec0 = next(r for r in A.flag_anomalies(zero) if r["pair_id"] == cand["pair_id"])
    assert rec0["flags"] == [A.TYPE_SURPRISE, A.TYPE_MARKET]
    assert rec0["status"] == A.TYPE_SURPRISE
    assert {c["kontrol"]: c["sonuc"] for c in rec0["checklist"]}["kırmızı kart"] == "kırmızı kart yok"
    red = _with_tm(fr_m, red_for={h: 1.0, a: 0.0}, red_against={h: 0.0, a: 1.0})
    rec = next(r for r in A.flag_anomalies(red) if r["pair_id"] == cand["pair_id"])
    by = {c["kontrol"]: c for c in rec["checklist"]}
    assert by["kırmızı kart"]["sonuc"] == "açıklanabilir: kırmızı kart" and by["kırmızı kart"]["aciklar"]
    assert rec["status"] == "açıklanabilir" and rec["explained_by"] == ["kırmızı kart"]
    assert rec["status_by_flag"] == {A.TYPE_SURPRISE: "açıklanabilir", A.TYPE_MARKET: A.TYPE_MARKET}
    assert rec["surprise_bits"] == cand["surprise_bits"]  # açıklama sürprizi değiştirmez


@pytest.mark.parametrize("change, check", [
    ("awarded", "hükmen olabilir"),
    ("name", "takım adı kopukluğu"),
    ("league", "lig değişikliği sonrası ilk maçlar"),
    ("validation", "veri doğrulama"),
])
def test_other_runnable_checks_explain(syn, change, check):
    cand = _unexplained_candidate(A.flag_anomalies(syn))
    h, a = _rows_of(syn, cand["pair_id"])
    if change == "awarded":
        fr = _with_tm(syn, awarded={h: True, a: True})
    elif change == "name":
        fr = _with_tm(syn, team_raw={h: "Eski Ad"}, opponent_raw={a: "Eski Ad"})
    elif change == "league":
        fr = _with_tm(syn, since_league_change={a: 2.0})
    else:
        fr = _with_tm(syn, gf_ht={h: 9.0}, ga_ht={a: 9.0})
    rec = next(r for r in A.flag_anomalies(fr) if r["pair_id"] == cand["pair_id"])
    by = {c["kontrol"]: c for c in rec["checklist"]}
    assert by[check]["aciklar"] and by[check]["sonuc"].startswith("açıklanabilir")
    assert rec["status"] == "açıklanabilir" and check in rec["explained_by"]


def test_model_market_gap_flag_is_separate(syn):
    mkt = _market_like_s0(syn)
    fr = dataclasses.replace(syn, mkt=mkt)
    recs = A.flag_anomalies(fr)
    m = [r for r in recs if A.TYPE_MARKET in r["flags"]]
    assert m and all(r["model_market_gap"] is not None for r in m)
    # Kaba kuvvet: her iki takımın |S0 p_win − piyasa p_win| değerinin büyüğü, lig-sezon içi orta-sıra kuralı
    tm = fr.tm
    home = np.where(tm["is_home"].to_numpy())[0]
    mir = tm["mirror_row"].to_numpy()[home]
    gap = np.maximum(np.abs(fr.p_win[home] - mkt[home, 0]), np.abs(fr.p_win[mir] - mkt[mir, 0]))
    cl = np.asarray(fr.cluster)[home]
    exp = set()
    for c in np.unique(cl):
        exp |= set(tm["pair_id"].to_numpy()[home][cl == c][_brute_top(gap[cl == c], 1 - C.ANOMALY_QUANTILE)].tolist())
    assert {r["pair_id"] for r in m} == exp
    for r in m:
        h, a = _rows_of(fr, r["pair_id"])
        assert r["model_market_gap"] == pytest.approx(max(abs(fr.p_win[h] - mkt[h, 0]), abs(fr.p_win[a] - mkt[a, 0])))
    for r in m:
        if r["flags"] == [A.TYPE_MARKET]:
            assert r["type"] == A.TYPE_MARKET and r["status"] in (A.TYPE_MARKET, "açıklanabilir")
            assert r["status_by_flag"].keys() == {A.TYPE_MARKET}
    # Oran yoksa (sentetik veri) piyasa bayrağı hiç oluşmaz
    assert not any(A.TYPE_MARKET in r["flags"] for r in A.flag_anomalies(syn))


def test_summary_counts_only_type_status_period(syn):
    fr = dataclasses.replace(syn, mkt=_market_like_s0(syn))
    recs = A.flag_anomalies(fr)
    summ = A.anomaly_summary(recs)
    assert set(summ) == {"toplam", "tur", "durum", "donem", "tur_durum_donem", "not", "baglanti"}
    for k in _keys(summ):
        assert not any(w in k.lower() for w in GROUP_WORDS), k
    assert summ["toplam"] == len(recs) == sum(summ["durum"].values()) == sum(summ["donem"].values())
    assert summ["tur"][A.TYPE_SURPRISE] == sum(A.TYPE_SURPRISE in r["flags"] for r in recs)
    assert sum(n for s in summ["tur_durum_donem"].values() for p in s.values() for n in p.values()) == sum(
        summ["tur"].values())
    # Kayıtlarda takım/lig alanı olsa bile özete sızmaz
    leaked = [{**r, "team": "Gizli Takım", "referee": "Gizli Hakem", "league": "ZZ9"} for r in recs]
    dumped = json.dumps(A.anomaly_summary(leaked), ensure_ascii=False)
    assert "Gizli" not in dumped and "ZZ9" not in dumped and "T1" not in dumped


def test_module_has_no_group_aggregation_or_links():
    funcs = [n for n, o in inspect.getmembers(A, inspect.isfunction) if o.__module__ == A.__name__]
    assert "flag_anomalies" in funcs and "anomaly_summary" in funcs
    banned = GROUP_WORDS + ("rank", "sira", "sıra", "by_", "top_", "leader", "worst")
    for n in funcs:
        assert not any(b in n.lower() for b in banned), n
    sig = inspect.signature(A.anomaly_summary)
    assert list(sig.parameters) == ["records"]
    src = inspect.getsource(A)
    assert not re.search(r"groupby\([^)]*(team|opponent|league|referee|hakem|takim)", src)
    assert "STATUSES" not in src
    tree = ast.parse(src)
    mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    mods += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    for m in mods:
        assert not any(x in m for x in ("decision", "ledger", "patterns", "null", "official", "engine", "service")), m


def test_anomaly_outputs_reproducible(syn):
    fr = dataclasses.replace(syn, mkt=_market_like_s0(syn))
    a, b = A.flag_anomalies(fr), A.flag_anomalies(fr)
    assert json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)
    assert A.anomaly_summary(a) == A.anomaly_summary(b)
    assert [r["date"] for r in a] == sorted(r["date"] for r in a)


# ----------------------------------------------------------------------------
# Resmî kararlar
# ----------------------------------------------------------------------------

def _dec(i, day, events=("T1|2026-10-11|A|B",), finality="kesinlesmedi", supersedes=None):
    return O.OfficialDecision(decision_id=f"K{i}", source="federasyon duyurusu (elle)", decision_date=day,
                              scope_event_ids=list(events), kind="hukmen", finality=finality, note="",
                              supersedes=supersedes)


def _ist(y, m, d, hh=0):
    return dt.datetime(y, m, d, hh, tzinfo=ISTANBUL)


def test_official_absence_is_kayit_yok(tmp_path):
    reg = O.OfficialRegistry(tmp_path / "resmi.json")
    assert len(reg) == 0 and reg.decisions() == []
    st = reg.status_for_event("T1|2026-10-11|A|B", _ist(2026, 10, 20))
    assert st == "KAYIT_YOK" == O.NO_RECORD
    assert st not in ("TEMIZ", "clean", "CLEAN")
    assert "entegre değil" in reg.note and "temiz" in reg.summary()["not"]
    assert not (tmp_path / "resmi.json").exists()  # salt okuma dosya oluşturmaz


def test_official_decision_invisible_before_its_date(tmp_path):
    reg = O.OfficialRegistry(tmp_path / "resmi.json")
    ev = "T1|2026-10-11|A|B"
    reg.append(_dec(1, dt.date(2026, 10, 12), events=(ev,)))
    assert reg.status_for_event(ev, _ist(2026, 10, 11)) == "KAYIT_YOK"
    assert reg.status_for_event(ev, _ist(2026, 10, 12)) == "KAYIT_YOK"  # aynı gün: henüz bilinmiyor
    assert reg.status_for_event(ev, _ist(2026, 10, 12, 23)) == "KAYIT_YOK"
    assert reg.decisions_known_at(_ist(2026, 10, 12)) == []
    got = reg.status_for_event(ev, _ist(2026, 10, 13))
    assert isinstance(got, O.OfficialDecision) and got.decision_id == "K1"
    assert reg.status_for_event("başka|olay", _ist(2026, 10, 13)) == "KAYIT_YOK"
    # UTC 22:30 (12 Ekim) = İstanbul 13 Ekim 01:30 → İstanbul tarihi kullanılır
    assert reg.status_for_event(ev, dt.datetime(2026, 10, 12, 22, 30, tzinfo=dt.timezone.utc)).decision_id == "K1"
    with pytest.raises(ValueError):
        reg.decisions_known_at(dt.datetime(2026, 10, 13))  # zaman dilimsiz


def test_official_append_only_and_corrections(tmp_path):
    path = tmp_path / "resmi.json"
    reg = O.OfficialRegistry(path)
    ev = "T1|2026-10-11|A|B"
    for name in ("delete", "remove", "update", "replace", "edit", "clear", "pop"):
        assert not hasattr(reg, name)
    reg.append(_dec(1, dt.date(2026, 10, 12), events=(ev,)))
    with pytest.raises(ValueError):
        reg.append(_dec(1, dt.date(2026, 10, 15), events=(ev,)))  # aynı kimlik: değiştirilemez
    with pytest.raises(ValueError):
        reg.append(_dec(2, dt.date(2026, 10, 15), supersedes="YOK"))
    with pytest.raises(ValueError):
        reg.append(_dec(2, dt.date(2026, 10, 10), supersedes="K1"))  # düzeltme öncekinden önce olamaz
    reg.append(_dec(2, dt.date(2026, 10, 20), events=(ev,), finality="kesin", supersedes="K1"))
    assert [d.decision_id for d in reg.decisions()] == ["K1", "K2"]  # eski kayıt silinmedi
    assert reg.status_for_event(ev, _ist(2026, 10, 15)).decision_id == "K1"  # düzeltme henüz bilinmiyor
    latest = reg.status_for_event(ev, _ist(2026, 10, 21))
    assert latest.decision_id == "K2" and latest.finality == "kesin"
    # Kapsamı daraltan düzeltme: eski kararın kapsadığı olay için zincirin son kararı döner (geri alındığı görünür)
    ev2 = "T1|2026-10-11|C|D"
    reg.append(_dec(5, dt.date(2026, 10, 12), events=(ev2,)))
    assert reg.status_for_event(ev2, _ist(2026, 10, 14)).decision_id == "K5"
    reg.append(_dec(6, dt.date(2026, 10, 16), events=("T1|2026-10-11|E|F",), supersedes="K5"))
    assert reg.status_for_event(ev2, _ist(2026, 10, 16)).decision_id == "K5"  # düzeltme o gün henüz bilinmiyor
    later = reg.status_for_event(ev2, _ist(2026, 10, 17))
    assert later.decision_id == "K6" and ev2 not in later.scope_event_ids and later.supersedes == "K5"
    # Diskten yeniden okuma aynı içeriği verir
    again = O.OfficialRegistry(path)
    assert [d.to_dict() for d in again.decisions()] == [d.to_dict() for d in reg.decisions()]
    # Dosya dışarıdan değiştirilirse zincir bozulur ve ekleme reddedilir
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["records"][0]["payload"]["decision"]["finality"] = "itiraz_edildi"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        reg.append(_dec(3, dt.date(2026, 10, 25)))
    with pytest.raises(ValueError):
        O.OfficialRegistry(path)


def test_official_field_validation():
    ok = dict(decision_id="K1", source="kaynak", decision_date=dt.date(2026, 10, 12), scope_event_ids=["e1"],
              kind="hukmen", finality="itiraz_edildi")
    O.OfficialDecision(**ok)
    bad = [
        {"finality": "temiz"}, {"decision_date": dt.datetime(2026, 10, 12, tzinfo=ISTANBUL)},
        {"decision_date": "2026-10-12"}, {"scope_event_ids": []}, {"scope_event_ids": "e1"},
        {"scope_event_ids": ["e1", "e1"]}, {"decision_id": ""}, {"source": " "}, {"kind": ""},
        {"supersedes": "K1"},
    ]
    for b in bad:
        with pytest.raises(ValueError):
            O.OfficialDecision(**{**ok, **b})
    d = O.OfficialDecision(**ok)
    assert O.OfficialDecision.from_dict(d.to_dict()) == d
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.finality = "kesin"


# ----------------------------------------------------------------------------
# İleriye dönük araştırma defteri
# ----------------------------------------------------------------------------

class _Clock:
    def __init__(self, t: dt.datetime):
        self.t = t

    def __call__(self) -> dt.datetime:
        return self.t


def _future_dtime(days: int) -> dt.datetime:
    """Gerçek saatten ve sözleşme tarihinden sonraki bir maç günü (defter gerçek kayıt anını da damgalar)."""
    today = max(dt.datetime.now(ISTANBUL).date(), dt.date.fromisoformat(C.FORWARD_FROM))
    return RL.decision_time_for(today + dt.timedelta(days=days))


def _fc(led, dtime, created, pattern="P1", event="T1|e1", is_home=True, **kw):
    args = dict(pattern_id=pattern, event_id=event, target="GALIBIYET", decision_time=dtime, created_at=created,
                p0=0.4, p_pattern=0.45, contract_version=C.CONTRACT_VERSION, config_hash=C.config_hash(),
                s0_model_hash="s0-abc", is_home=is_home, league="T1", season="2026/27")
    args.update(kw)
    return led.record_forecast(**args)


def test_research_ledger_separate_file(tmp_path):
    led = RL.ResearchLedger(tmp_path)
    assert led.path == tmp_path / "dizi_arastirma.sqlite" and led.path.exists()
    led.close()
    with pytest.raises(ValueError):
        RL.ResearchLedger(tmp_path / "gol_pazarlari.sqlite")
    # Ana defter (araştırma türü olmayan, kayıt içeren) dosya araştırma defteri olarak açılamaz
    from bahis_tahmin.goals.ledger import Ledger

    other = Ledger(tmp_path / "baska.sqlite")
    other.record_prediction({"event_id": "x", "market_key": "FT_OVER_2_5", "decision_time": "t", "model_version": "m",
                             "feature_version": "f", "data_cutoff": "d", "p": 0.5, "decision_status": "NO_BET",
                             "reasons": [], "stake_units": 0, "strategy_version": "s"})
    other.close()
    with pytest.raises(ValueError):
        RL.ResearchLedger(tmp_path / "baska.sqlite")


def test_research_ledger_refuses_late_or_naive_forecasts(tmp_path):
    clock = _Clock(now_utc())
    led = RL.ResearchLedger(tmp_path, clock=clock)
    dtime = _future_dtime(3)
    early = clock.t - dt.timedelta(minutes=1)
    with pytest.raises(ValueError):
        _fc(led, dtime, dt.datetime.now())  # zaman dilimsiz created_at
    with pytest.raises(ValueError):
        _fc(led, dtime.replace(tzinfo=None), early)  # zaman dilimsiz decision_time
    with pytest.raises(ValueError):
        _fc(led, dtime, dtime)  # created_at == decision_time
    with pytest.raises(ValueError):
        _fc(led, dtime, dtime + dt.timedelta(hours=5))  # maç günü içinde: geç
    with pytest.raises(ValueError):
        _fc(led, dtime.astimezone(dt.timezone.utc).replace(hour=0) + dt.timedelta(days=1), early)  # 00:00 İst. değil
    with pytest.raises(ValueError):
        _fc(led, dtime, early, config_hash="baska")
    with pytest.raises(ValueError):
        _fc(led, dtime, early, p_pattern=1.0)
    with pytest.raises(ValueError):
        _fc(led, dtime, clock.t + dt.timedelta(minutes=5))  # created_at defter saatinden ileride
    late_clock = _Clock(dtime + dt.timedelta(hours=1))  # geriye tarihleme: gerçek kayıt anı karar zamanından sonra
    led_late = RL.ResearchLedger(tmp_path / "gec.sqlite", clock=late_clock)
    with pytest.raises(ValueError):
        _fc(led_late, dtime, dtime - dt.timedelta(days=1))
    old_clock = _Clock(dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc))  # sözleşme tarihinden önceki maç
    led_old = RL.ResearchLedger(tmp_path / "eski.sqlite", clock=old_clock)
    with pytest.raises(ValueError):
        _fc(led_old, RL.decision_time_for("2026-10-10"), dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc))
    assert led.records_with_outcomes() == []
    for x in (led, led_late, led_old):
        x.close()


def test_research_ledger_accepts_early_forecast_and_outcome(tmp_path):
    clock = _Clock(now_utc())
    led = RL.ResearchLedger(tmp_path, clock=clock)
    dtime = _future_dtime(3)
    fid = _fc(led, dtime, clock.t - dt.timedelta(minutes=5))
    _fc(led, dtime, clock.t - dt.timedelta(minutes=5), is_home=False, p0=0.3, p_pattern=0.28)  # ikiz satır
    with pytest.raises(ValueError):
        _fc(led, dtime, clock.t - dt.timedelta(minutes=1))  # aynı tahmin tekrar kaydedilemez
    raw = led._ledger.predictions()
    assert len(raw) == 2 and all(r["stake_units"] == 0 and r["virtual"] for r in raw)
    assert all(r["decision_status"] in C.STATUSES for r in raw)
    recs = led.records_with_outcomes()
    assert recs[0]["outcome_state"] == RL.OUTCOME_PENDING and recs[0]["y"] is None
    with pytest.raises(ValueError):
        led.record_outcome(fid, 1, source="test")  # sonuç maç günü + 1'den önce bilinemez
    clock.t = dtime + dt.timedelta(days=1, hours=1)
    led.record_outcome(fid, 1, source="test")
    recs = {r["id"]: r for r in led.records_with_outcomes()}
    assert recs[fid]["y"] == 1.0 and recs[fid]["outcome_state"] == RL.OUTCOME_KNOWN
    ok, _ = led.verify_chain()
    assert ok
    season = RL._season_year(dtime.astimezone(ISTANBUL).date())
    ev = led.evaluate("P1", season)
    assert ev["status"] == "PAPER_TRADING" and ev["evaluation_point_reached"] is False
    assert ev["excluded"].get("bekleyen") == 1
    led.close()


def test_research_ledger_season_limit_uses_clock(tmp_path):
    """Kayıt gelmese bile sezon sınırı defter saatiyle dolar (sessiz uzatma yok)."""
    clock = _Clock(now_utc())
    led = RL.ResearchLedger(tmp_path, clock=clock)
    ids = []
    for k, lg in enumerate(("T1", "E0", "D1", "I1")):
        dtime = _future_dtime(3 + k)
        ids.append(_fc(led, dtime, clock.t - dt.timedelta(minutes=5), event=f"{lg}|e{k}", league=lg))
    season = RL._season_year(_future_dtime(3).astimezone(ISTANBUL).date())
    end = dt.date(season + C.PAPER_MAX_SEASONS, 7, 1)
    clock.t = RL.decision_time_for(end) - dt.timedelta(days=2)
    for k, fid in enumerate(ids):
        led.record_outcome(fid, k % 2, source="test")
    before = led.evaluate("P1", season)
    assert before["evaluation_point_reached"] is False and before["status"] == "PAPER_TRADING"
    clock.t = RL.decision_time_for(end) + dt.timedelta(hours=1)
    after = led.evaluate("P1", season)
    assert after["evaluation_point_reached"] is True and after["trigger"] == "sezon" and after["n_used"] == 4
    assert after["status"] in ("PAPER_TRADING", "NO_ADDED_VALUE") and after["succeeded"] is not None
    # Modül düzeyi işlev as_of verilmezse kayıtlara göre (tekrarlanabilir) karar verir: sınır henüz dolmamış
    assert RL.paper_evaluation(led.records_with_outcomes("P1"), season)["evaluation_point_reached"] is False
    led.close()


def _paper_records(n, start, per_day=8, effect=True, seed=1, leagues=("T1", "E0", "D1", "I1", "SP1", "F1"),
                   pattern="P1"):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        day = start + dt.timedelta(days=i // per_day)
        dtime = RL.decision_time_for(day)
        p0 = float(rng.uniform(0.1, 0.3))
        p_true = min(0.9, 2.2 * p0) if effect else p0
        y = float(rng.random() < p_true)
        pp = p_true if effect else float(np.clip(p0 * np.exp(rng.normal(0, 0.6)), 0.02, 0.95))
        lg = leagues[i % len(leagues)]
        season = f"{RL._season_year(day)}/{(RL._season_year(day) + 1) % 100:02d}"
        created = (dtime - dt.timedelta(days=1)).astimezone(dt.timezone.utc).isoformat()
        out.append({"id": f"{pattern}-{i}", "created_at": created, "pattern_id": pattern, "event_id": f"{lg}|{day}|{i}",
                    "target": "GALIBIYET", "is_home": bool(i % 2), "decision_time": dtime.isoformat(),
                    "forecast_created_at": created, "p0": p0, "p_pattern": pp, "contract_version": C.CONTRACT_VERSION,
                    "config_hash": C.config_hash(), "s0_model_hash": "s0", "league": lg, "season": season,
                    "cluster": f"{lg}|{season}", "match_date": day.isoformat(), "outcome_state": RL.OUTCOME_KNOWN,
                    "y": y})
    return out


START = dt.date(2026, 10, 15)


def test_paper_evaluation_ongoing_success_failure():
    few = RL.paper_evaluation(_paper_records(120, START), 2026)
    assert few["status"] == "PAPER_TRADING" and few["evaluation_point_reached"] is False and few["succeeded"] is None
    good = RL.paper_evaluation(_paper_records(320, START), 2026)
    assert good["evaluation_point_reached"] and good["trigger"] == "satir"
    assert good["n_used"] == 304 and good["n_used"] >= C.PAPER_MIN_ROWS  # 300'e ulaşılan günün tüm satırları
    assert good["succeeded"] is True and good["status"] == "PAPER_TRADING"
    assert good["diff"] < 0 and good["ci_hi"] < 0 and good["p_one_sided"] < C.ALPHA
    bad = RL.paper_evaluation(_paper_records(320, START, effect=False), 2026)
    assert bad["evaluation_point_reached"] and bad["succeeded"] is False and bad["status"] == "NO_ADDED_VALUE"
    for r in (few, good, bad):
        assert r["status"] in C.STATUSES and r["no_extension"] is True


def test_paper_evaluation_no_extension_and_reproducible():
    base = _paper_records(320, START, effect=False)
    r1 = RL.paper_evaluation(base, 2026)
    more = base + _paper_records(400, START + dt.timedelta(days=60), effect=True, seed=9)
    for k, rec in enumerate(more[len(base):]):
        rec["id"] = f"ek-{k}"
    r2 = RL.paper_evaluation(more, 2026)
    for key in ("status", "succeeded", "diff", "ci_hi", "p_one_sided", "rows_sha256", "n_used", "evaluation_point"):
        assert r1[key] == r2[key], key
    assert r2["status"] == "NO_ADDED_VALUE"  # sonradan gelen iyi satırlar başarısızlığı kurtarmaz
    assert json.dumps(r1, sort_keys=True) == json.dumps(RL.paper_evaluation(base, 2026), sort_keys=True)


def test_paper_evaluation_season_limit_and_exclusions():
    recs = _paper_records(100, START, per_day=1)  # 100 gün, < 300 satır
    on = RL.paper_evaluation(recs, 2026, as_of=dt.date(2028, 6, 30))
    assert on["evaluation_point_reached"] is False and on["status"] == "PAPER_TRADING"
    done = RL.paper_evaluation(recs, 2026, as_of=dt.date(2028, 7, 1))
    assert done["evaluation_point_reached"] and done["trigger"] == "sezon" and done["n_used"] == 100
    assert done["season_end"] == "2028-07-01"
    # Geç kaydedilmiş satır nitelikli sayılmaz
    late = [dict(r) for r in recs]
    late[0]["forecast_created_at"] = late[0]["decision_time"]
    late[1]["created_at"] = (dt.datetime.fromisoformat(late[1]["decision_time"]) + dt.timedelta(hours=2)).isoformat()
    r = RL.paper_evaluation(late, 2026, as_of=dt.date(2028, 7, 1))
    assert r["excluded"]["gec_kayit"] == 2 and r["n_used"] == 98
    # Karar zamanı maç günü 00:00 (İstanbul) değilse satır nitelikli değildir (ör. maç günü 23:00 → geç tahmin)
    odd = [dict(r) for r in recs]
    odd[0]["decision_time"] = (dt.datetime.fromisoformat(odd[0]["decision_time"]) + dt.timedelta(hours=23)).isoformat()
    odd[0]["forecast_created_at"] = odd[0]["created_at"] = (
        dt.datetime.fromisoformat(odd[0]["decision_time"]) - dt.timedelta(hours=1)).isoformat()
    r = RL.paper_evaluation(odd, 2026, as_of=dt.date(2028, 7, 1))
    assert r["excluded"]["gecersiz_zaman"] == 1 and r["n_used"] == 99
    # Değerlendirme noktasından önce sonucu beklenen satır varsa değerlendirme bekler
    pend = _paper_records(320, START)
    pend[3]["outcome_state"], pend[3]["y"] = RL.OUTCOME_PENDING, None
    w = RL.paper_evaluation(pend, 2026)
    assert w["evaluation_point_reached"] is False and w["waiting_outcomes"] == 1 and w["status"] == "PAPER_TRADING"
    with pytest.raises(ValueError):
        RL.paper_evaluation(recs + _paper_records(5, START, pattern="P2"), 2026)  # birden fazla örüntü
    with pytest.raises(ValueError):
        RL.paper_evaluation(recs, 2026, prior_status="EXPLORATORY")
    with pytest.raises(ValueError):
        RL.paper_evaluation(recs, 2025)

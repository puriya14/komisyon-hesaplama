"""S6-PERF-03: arşiv görünümü (``archive.unified``) hızlandırmasının sonuçları değiştirmediğinin kanıtı.

``_old_unified`` S6-PERF-03 öncesi ``archive.unified`` gövdesinin birebir kopyasıdır (yalnızca modül adları ``A.``
önekiyle yazıldı) ve karşılaştırma için referans olarak kullanılır; ürün kodunda tek birleştirme motoru vardır. Yeni
çıktı hem istenen kenar durumlarında hem de sabit tohumlu rastgele girdilerde hücre değeri, hücre tipi, sütun tipi,
satır sırası ve indeks dahil KATI olarak karşılaştırılır. Aşağı akış (görünüm, filtreli özet, olay kartı, çoklu olay
karşılaştırması) ``A.unified`` eski gövdeyle değiştirilerek aynı girdide karşılaştırılır. Bütün veriler sentetiktir.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from bahis_tahmin import archive as A
from bahis_tahmin import calisma as C
from bahis_tahmin import olay_karsilastirma as O
from test_s5_arsiv_02 import CONFLICT, TEAM_ROWS, archive, of, rows, sb, season_rows

OF, SB, DS, XG = "openfootball-sonuc", "statsbomb-acik", "football-datasets", "github-mirror"


def _old_unified(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """S6-PERF-03 öncesi ``archive.unified`` (birebir; referans)."""
    from bahis_tahmin.goals.ledger import event_id

    cols = ["mac_kimligi", "league", "season", "date", "time", "home", "away", "fthg", "ftag", "hthg", "htag",
            "iy_mantiksal", "kaynaklar", "asil_kaynaklar", "bagimsiz_kaynak", "saglayici_mac_id", "xg_h", "xg_a",
            "sut_h", "sut_a", "durum", "kaynak_satiri", "bloklar", *A.FIELD_COLUMNS]
    if rows is None or rows.empty:
        return pd.DataFrame(columns=cols), pd.DataFrame(), pd.DataFrame()
    r = rows.copy()
    r["k_home"], r["k_away"] = None, None
    for (lg, season), g in r.groupby(["league", "season"], sort=False):
        present = [s for s in A.PRIORITY if s in set(g["kaynak"])]
        prim = present[0]
        pn = sorted(set(g.loc[g["kaynak"] == prim, "home"]) | set(g.loc[g["kaynak"] == prim, "away"]))
        for s in present:
            gi = g[g["kaynak"] == s]
            names = sorted(set(gi["home"]) | set(gi["away"]))
            mp = {n: n for n in names} if s == prim else A._map_names(names, pn, lg, s, prim)
            r.loc[gi.index, "k_home"] = gi["home"].map(mp)
            r.loc[gi.index, "k_away"] = gi["away"].map(mp)
    unresolved = r["k_home"].isna() | r["k_away"].isna()
    review = r[unresolved].assign(neden="TAKIM_KIMLIGI_KESIN_DEGIL")
    ok = r[~unresolved].copy()
    ok["_day"] = pd.to_datetime(ok["date"]).dt.normalize()
    ok["_prio"] = ok["kaynak"].map({k: i for i, k in enumerate(A.PRIORITY)}).fillna(len(A.PRIORITY))
    ok["_blok"] = pd.to_numeric(ok["blok"], errors="coerce").fillna(-1)
    ok["_time"] = ok["time"].map(A._txt)
    ok["_sid"] = ok["saglayici_mac_id"].map(lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v))
                                            else str(v))
    ok = ok.sort_values(["league", "_day", "k_home", "k_away", "_prio", "_blok", "_time", "_sid", "fthg", "ftag",
                         "hthg", "htag", "xg_h", "xg_a", "sut_h", "sut_a"], kind="mergesort", na_position="last")
    out, conflicts = [], []

    def pairs(g, a, b):
        return {(x, y) for x, y in zip(g[a], g[b]) if pd.notna(x) and pd.notna(y)}

    def first_pair(g, a, b):
        both = g[g[a].notna() & g[b].notna()]
        if both.empty:
            return np.nan, np.nan, None
        return both[a].iloc[0], both[b].iloc[0], both["kaynak"].iloc[0]

    for (lg, day, h, a), g in ok.groupby(["league", "_day", "k_home", "k_away"], sort=True):
        ft, ht = pairs(g, "fthg", "ftag"), pairs(g, "hthg", "htag")
        real_ht = pairs(g[~g["iy_mantiksal"].astype(bool)], "hthg", "htag")
        status = "CELISKI" if (len(ft) > 1 or len(ht) > 1) else "TAMAM"
        mid = event_id(lg, day, h, a)
        if status == "CELISKI":
            for _, x in g.iterrows():
                conflicts.append({"mac_kimligi": mid, "kaynak": x["kaynak"], "blok": x["blok"],
                                  "asil_kaynak": x["asil_kaynak"], "ms": (x["fthg"], x["ftag"]),
                                  "iy": (x["hthg"], x["htag"])})
        f = next(iter(ft)) if len(ft) == 1 else (np.nan, np.nan)
        hh = next(iter(ht)) if len(ht) == 1 else (np.nan, np.nan)
        srcs = sorted(set(g["kaynak"]))
        ms_src = sorted(set(g.loc[g["fthg"].notna() & g["ftag"].notna(), "kaynak"]))
        iy_src = sorted(set(g.loc[g["hthg"].notna() & g["htag"].notna(), "kaynak"]))
        timed = g[g["_time"] != ""]
        t, t_src = (timed["_time"].iloc[0], timed["kaynak"].iloc[0]) if len(timed) else ("", None)
        xh, xa, x_src = first_pair(g, "xg_h", "xg_a")
        sh, sa, s_src = first_pair(g, "sut_h", "sut_a")
        shown = [set(ms_src) if status == "TAMAM" and ms_src else None,
                 set(iy_src) if status == "TAMAM" and iy_src else None,
                 {t_src} if t_src else None, {x_src} if x_src else None, {s_src} if s_src else None]
        sid = sorted({v for v in g["_sid"] if v})
        out.append({"mac_kimligi": mid, "league": lg, "season": g["season"].iloc[0], "date": day, "time": t,
                    "home": h, "away": a,
                    "fthg": f[0] if status == "TAMAM" else np.nan, "ftag": f[1] if status == "TAMAM" else np.nan,
                    "hthg": hh[0] if status == "TAMAM" else np.nan, "htag": hh[1] if status == "TAMAM" else np.nan,
                    "iy_mantiksal": bool(status == "TAMAM" and len(ht) == 1 and not real_ht),
                    "kaynaklar": ",".join(srcs), "asil_kaynaklar": ",".join(sorted(set(g["asil_kaynak"]))),
                    "bagimsiz_kaynak": len(set(g["asil_kaynak"])), "saglayici_mac_id": ",".join(sid) or None,
                    "xg_h": xh, "xg_a": xa, "sut_h": sh, "sut_a": sa, "durum": status, "kaynak_satiri": int(len(g)),
                    "bloklar": ",".join(str(int(b)) for b in sorted(set(g["_blok"])) if b >= 0),
                    "ms_kaynaklari": ",".join(ms_src), "iy_kaynaklari": ",".join(iy_src), "saat_kaynagi": t_src,
                    "xg_kaynagi": x_src, "sut_kaynagi": s_src,
                    "alan_birlesimi": bool(len(srcs) > 1 and any(s is not None and s != set(srcs) for s in shown))})
    merged = pd.DataFrame(out, columns=cols)
    if len(merged):
        dup = merged.duplicated(subset=["league", "season", "home", "away"], keep=False)
        merged.loc[dup, "durum"] = "TARIH_UYUSMAZ"
        if dup.any():
            review = pd.concat([review, merged[dup].assign(neden="AYNI_ESLESME_FARKLI_TARIH")], ignore_index=True)
    conflicts = pd.DataFrame(conflicts)
    if len(conflicts):
        conflicts = conflicts.sort_values(["mac_kimligi", "kaynak", "blok"], kind="mergesort").reset_index(drop=True)
    if len(review):
        keys = review.reindex(columns=["neden", "league", "season", "date", "kaynak", "home", "away"]).astype(str)
        review = review.loc[keys.sort_values(list(keys.columns), kind="mergesort").index]
    return merged.reset_index(drop=True), conflicts, review.reset_index(drop=True)


# ----------------------------------------------------------------------------- katı karşılaştırma

def _cell(v):
    if isinstance(v, float) and math.isnan(v):
        return ("float", "NaN")
    if isinstance(v, tuple):
        return ("tuple", tuple(_cell(x) for x in v))
    if isinstance(v, pd.Timestamp):
        return ("Timestamp", v.isoformat(), v.unit)
    if v is None or v is pd.NaT or v is pd.NA:
        return (type(v).__name__,)
    return (type(v).__name__, v)


def frame_key(df: pd.DataFrame):
    """Sütunlar, sütun tipleri, indeks ve her hücrenin (tip, değer) çifti; NaN'lar eşit sayılır."""
    return (list(df.columns), [str(t) for t in df.dtypes], list(df.index),
            [tuple(_cell(x) for x in row) for row in df.itertuples(index=False, name=None)])


def assert_same(new, old):
    for part, (x, y) in zip(("merged", "conflicts", "review"), zip(new, old)):
        assert frame_key(x) == frame_key(y), part


# ----------------------------------------------------------------------------- sentetik girdiler

def _row(src, day, home, away, ft, ht=None, **kw):
    return (of if src == OF else sb)(day, home, away, ft, ht, **kw) if src in (OF, SB) else {
        "kaynak": src, "date": day, "home": home, "away": away, "fthg": ft[0], "ftag": ft[1],
        "hthg": ht[0] if ht else None, "htag": ht[1] if ht else None, **kw}


CASES = {
    "tek_kaynak_tekil": [of("2015-08-08", "Arsenal FC", "Chelsea FC", (2, 1), (1, 0)),
                         of("2015-08-09", "Everton FC", "Stoke City FC", (0, 0), (0, 0))],
    "ayni_kaynak_yinelenen": [of("2015-08-08", "Arsenal FC", "Chelsea FC", (2, 1), (1, 0)),
                              of("2015-08-08", "Arsenal FC", "Chelsea FC", (2, 1), (1, 0), blok=3),
                              of("2015-08-15", "Chelsea FC", "Arsenal FC", (1, 1), (0, 0)),
                              of("2015-08-15", "Chelsea FC", "Arsenal FC", (2, 1), (0, 0), blok=4)],
    "cok_kaynak_ayni_mac": [of("2015-08-08", "Arsenal FC", "Chelsea FC", (2, 1)),
                            sb("2015-08-08", "Arsenal", "Chelsea", (2, 1), (1, 0), xg_h=1.4, xg_a=0.6, sut_h=12,
                               sut_a=7, time="12:45", saglayici_mac_id="101"),
                            _row(XG, "2015-08-08", "Arsenal", "Chelsea", (2, 1), (1, 0), blok=5, time="15:00")],
    "ms_celiskisi": list(CONFLICT),
    "iy_celiskisi": [of("2015-08-22", "Arsenal FC", "Everton FC", (2, 2), (1, 1)),
                     sb("2015-08-22", "Arsenal", "Everton", (2, 2), (0, 2))],
    "iy_bir_kaynakta_eksik": [of("2015-08-29", "Stoke City FC", "Arsenal FC", (0, 3)),
                              sb("2015-08-29", "Stoke City", "Arsenal", (0, 3), (0, 1), xg_h=0.3, xg_a=2.1)],
    "gercek_ve_mantiksal_0_0": [of("2015-09-05", "Chelsea FC", "Everton FC", (0, 0), (0, 0), iy_mantiksal=True),
                                of("2015-09-12", "Everton FC", "Chelsea FC", (0, 0), (0, 0)),
                                sb("2015-09-05", "Chelsea", "Everton", (0, 0), (0, 0)),
                                of("2015-09-26", "Stoke City FC", "Hull City FC", (0, 0), (0, 0), iy_mantiksal=True)],
    "tarih_uyusmazligi": [of("2015-09-19", "Arsenal FC", "Stoke City FC", (1, 0), (1, 0)),
                          sb("2015-09-20", "Arsenal", "Stoke City", (1, 0), (1, 0))],
    "belirsiz_kimlik": list(TEAM_ROWS),
    "ayni_gun_farkli_maclar": [of("2015-10-03", "Arsenal FC", "Chelsea FC", (1, 0), (0, 0)),
                               of("2015-10-03", "Everton FC", "Stoke City FC", (2, 2), (1, 1)),
                               of("2015-10-03", "Leeds United FC", "Hull City FC", (0, 1), (0, 1), league="E1"),
                               sb("2015-10-03", "Everton", "Stoke City", (2, 2), (1, 1))],
    "iki_sezon": season_rows(),
    "tarihi_eksik_kayit": [of(None, "Arsenal FC", "Everton FC", (1, 0), (0, 0)),
                           of("2015-10-10", "Everton FC", "Arsenal FC", (2, 0), (1, 0)),
                           sb(None, "Everton", "Arsenal", (2, 0), (1, 0))],
    "zaman_ve_kimlik_alanlari": [of("2015-10-17", "Arsenal FC", "Hull City FC", (3, 1), (1, 1), time="16:00"),
                                 sb("2015-10-17", "Arsenal", "Hull City", (3, 1), (1, 1), time="15:30",
                                    saglayici_mac_id=77, xg_h=np.nan, xg_a=1.0, sut_h=9, sut_a=None)],
}


def random_rows(seed: int, n: int = 40) -> pd.DataFrame:
    """Sabit tohumlu karışık girdi: çok kaynak, yinelenen kayıt, MS/İY çelişkisi, eksik İY, mantıksal 0-0, tarih
    kayması, aynı gün maçlar, kimliği çözülemeyen ad, saat/sağlayıcı/xG/şut alanları, eksik blok."""
    rng = np.random.default_rng(seed)
    teams = ["Arsenal FC", "Chelsea FC", "Everton FC", "Stoke City FC", "Hull City FC", "Leeds United FC"]
    short = {t: t.replace(" FC", "") for t in teams}
    out = []
    base = dt.date(2015, 8, 1)
    for _ in range(n):
        h, a = rng.choice(len(teams), size=2, replace=False)
        day = base + dt.timedelta(days=int(rng.integers(0, 20)))
        season = ["2014/15", "2015/16"][int(rng.integers(0, 2))]
        league = ["E0", "E0", "E1"][int(rng.integers(0, 3))]
        ft = (int(rng.integers(0, 4)), int(rng.integers(0, 4)))
        ht = None if rng.random() < 0.25 else (int(rng.integers(0, ft[0] + 1)), int(rng.integers(0, ft[1] + 1)))
        for src in [s for s in (OF, SB, XG) if rng.random() < (0.9 if s == OF else 0.4)] or [OF]:
            for _ in range(1 + int(rng.random() < 0.15)):  # aynı kaynakta yinelenen kayıt
                f, hh, d = ft, ht, day
                if rng.random() < 0.08:
                    f = (ft[0] + 1, ft[1])
                if rng.random() < 0.08 and hh is not None:
                    hh = (0, 0)
                if rng.random() < 0.15:
                    hh = None
                if rng.random() < 0.05:
                    d = day + dt.timedelta(days=1)
                hn, an = (teams[h], teams[a]) if src == OF else (short[teams[h]], short[teams[a]])
                if rng.random() < 0.04:
                    hn = hn + " U21"
                kw = {"season": season, "league": league, "blok": int(rng.integers(0, 4)) if rng.random() < 0.9
                      else np.nan,
                      "time": ["", "15:00", "17:30", None][int(rng.integers(0, 4))],
                      "iy_mantiksal": bool(f == (0, 0) and hh == (0, 0) and rng.random() < 0.5),
                      "saglayici_mac_id": [None, "9", 12, np.nan][int(rng.integers(0, 4))]}
                if rng.random() < 0.4:
                    kw.update(xg_h=float(rng.integers(0, 30)) / 10, xg_a=(None if rng.random() < 0.3
                                                                           else float(rng.integers(0, 30)) / 10))
                if rng.random() < 0.4:
                    kw.update(sut_h=int(rng.integers(0, 20)), sut_a=int(rng.integers(0, 20)))
                out.append(_row(src, d.isoformat(), hn, an, f, hh, **kw))
    return rows(*out)


# ----------------------------------------------------------------------------- 1. çekirdek eşdeğerlik

@pytest.mark.parametrize("name", sorted(CASES))
def test_unified_matches_previous_implementation_on_edge_cases(name):
    r = rows(*CASES[name])
    assert_same(A.unified(r), _old_unified(r))
    for k in (OF, SB, XG, DS):  # tek kaynak görünümü: satırlar birleştirmeden önce süzülür
        part = r[r["kaynak"] == k].reset_index(drop=True)
        assert_same(A.unified(part), _old_unified(part))


@pytest.mark.parametrize("seed", range(40))
def test_unified_matches_previous_implementation_on_seeded_random_inputs(seed):
    r = random_rows(seed)
    new = A.unified(r)
    assert_same(new, _old_unified(r))
    perm = r.iloc[np.random.default_rng(seed + 1000).permutation(len(r))].reset_index(drop=True)
    shuffled = A.unified(perm)
    assert_same(shuffled, _old_unified(perm))  # karıştırılmış girdide de önceki uygulamayla aynı
    # Birleşik maçlar ve çelişkiler girdi sırasından bağımsız. (İnceleme satırlarında yedi sıralama anahtarı aynı olan
    # kayıtlar girdi sırasında kalır; bu önceki uygulamanın da davranışıdır ve değiştirilmedi.)
    assert frame_key(shuffled[0]) == frame_key(new[0]) and frame_key(shuffled[1]) == frame_key(new[1])


def test_case_coverage_is_real_not_vacuous():
    """Kenar durumları gerçekten oluşuyor: çelişki, tarih ve kimlik incelemesi, alan birleşimi, mantıksal İY."""
    m, c, rv = A.unified(rows(*[x for v in CASES.values() for x in v]))
    assert {"TAMAM", "CELISKI", "TARIH_UYUSMAZ"} <= set(m["durum"])
    assert len(c) >= 4 and {"TAKIM_KIMLIGI_KESIN_DEGIL", "AYNI_ESLESME_FARKLI_TARIH"} <= set(rv["neden"])
    assert m["alan_birlesimi"].any() and m["iy_mantiksal"].any() and (m["kaynak_satiri"] >= 3).any()
    rnd = [A.unified(random_rows(s)) for s in range(40)]
    assert sum((x[0]["durum"] == "CELISKI").sum() for x in rnd) >= 20
    assert sum((x[0]["durum"] == "TARIH_UYUSMAZ").sum() for x in rnd) >= 5
    assert sum(len(x[2]) for x in rnd) >= 20


def test_empty_and_closed_views_match():
    empty = rows(*CASES["tek_kaynak_tekil"]).iloc[0:0]
    assert_same(A.unified(empty), _old_unified(empty))
    assert_same(A.unified(None), _old_unified(None))
    ar = archive(rows(*CASES["cok_kaynak_ayni_mac"], *CASES["ms_celiskisi"]))
    closed = A.view(ar, "datasets")
    assert closed.kapali and closed.merged.empty and closed.rows.empty


# ----------------------------------------------------------------------------- 2. aşağı akış eşdeğerliği

def _season(year, special=None, src=of, rename=None):
    teams = ("Arsenal FC", "Chelsea FC", "Everton FC", "Stoke City FC")
    rounds = (((0, 1), (2, 3)), ((2, 0), (1, 3)), ((0, 3), (1, 2)), ((1, 0), (3, 2)), ((0, 2), (3, 1)),
              ((3, 0), (2, 1)))
    out = []
    for i, rnd in enumerate(rounds):
        day = (dt.date(year, 8, 8) + dt.timedelta(days=7 * i)).isoformat()
        for j, (h, a) in enumerate(rnd):
            ft, ht = (special or {}).get((i, j), (((year + i + j) % 3, (year + 2 * i + j) % 2), None))
            if ht is None and (i, j) not in (special or {}):
                ht = (min(ft[0], (i + j) % 2), min(ft[1], j % 2))
            hn, an = (rename or (lambda x: x))(teams[h]), (rename or (lambda x: x))(teams[a])
            out.append(src(day, hn, an, ft, ht, season=f"{year}/{(year + 1) % 100:02d}"))
    return out


def _downstream(ar):
    """Görünüm, filtreli özet, olay kartı ve çoklu olay çıktıları (karşılaştırma için kanonik)."""
    res = {}
    for k in (None, "openfootball", "hudl", "datasets"):
        v = A.view(ar, k)
        res[f"v{k}"] = [frame_key(x) for x in (v.rows, v.merged, v.conflicts, v.review)] + [v.kapali,
                                                                                             C.snapshot(ar, v)]
        for f in ({}, {"sezon": "2015/16"}, {"takim": "Arsenal FC", "yer": "ev"}, {"takim": "Arsenal"}):
            lab, out = A.explore_view(ar, v, **f)
            res[f"e{k}{sorted(f.items())}"] = (frame_key(lab), C.canon(out))
        ok = v.merged[v.merged["durum"] == "TAMAM"]
        for mid, h in zip(ok["mac_kimligi"].tolist()[::5], ok["home"].tolist()[::5]):
            res[f"k{k}{mid}"] = C.canon(A.event_card_for(ar, mid, h, gorunum=v, liste_filtresi={"sezon": "2015/16"}))
    ids = [m for m in A.view(ar, "openfootball").merged["mac_kimligi"] if "Arsenal FC" in m]
    for kw in ({}, {"once": 10, "sonra": 5, "limit": 4, "offset": 3}, {"sonra": 1, "limit": 2, "offset": 9}):
        for kaynak in ("openfootball", "birlesik"):
            res[f"o{kaynak}{sorted(kw.items())}"] = C.canon(O.olay_karsilastir(ar, "Arsenal FC", kaynak=kaynak,
                                                                               olaylar=ids, **kw))
    return res


def test_views_summaries_cards_and_multi_event_results_match_previous_implementation(monkeypatch):
    recs = (_season(2014) + _season(2015, {(2, 0): ((2, 1), (0, 1))})
            + _season(2015, src=sb, rename=lambda t: t.replace(" FC", ""))
            + [sb("2015-08-15", "Everton", "Arsenal", (3, 3), (1, 1)),  # MS çelişkisi (birleşik görünümde)
               of("2015-10-01", "Arsenal FC", "Chelsea FC", (1, 0), (1, 0), season="2015/16"),  # tarih uyuşmazlığı
               sb("2015-08-23", "Arsenal", "Arsenal Women", (1, 0))])  # kimliği kesinleşmeyen satır
    blocks = [{"kaynak": OF, "lig": "E0", "sezon": "2014/15", "dosya_sha256": "a", "satir_ozeti": "b", "yol": "x",
               "blok": 0, "kapsam": "TAM", "karantina": {"MS_YOK": 2}, "tarihsel_analiz": True},
              {"kaynak": OF, "lig": "E0", "sezon": "2015/16", "dosya_sha256": "c", "satir_ozeti": "d", "yol": "y",
               "blok": 0, "kapsam": "KISMI", "oynanmamis": 3, "tarihsel_analiz": True}]
    ar = archive(rows(*recs), blocks=blocks)
    new = _downstream(ar)
    monkeypatch.setattr(A, "unified", _old_unified)
    old = _downstream(ar)
    assert new.keys() == old.keys() and len(new) >= 39
    assert [k for k in new if new[k] != old[k]] == []
    merged = A.view(ar, None).merged
    assert {"CELISKI", "TARIH_UYUSMAZ"} <= set(merged["durum"])  # karşılaştırma boş durumlarda değil


# ----------------------------------------------------------------------------- 3. yan etki ve işlem sayısı

def test_inputs_and_returned_results_are_not_shared_between_calls():
    r = random_rows(3)
    before = frame_key(r)
    m1, c1, rv1 = A.unified(r)
    assert frame_key(r) == before  # girdi yerinde değişmez
    ref = [frame_key(x) for x in (m1, c1, rv1)]
    m1.loc[:, "fthg"] = 99.0
    m1.loc[0, "durum"] = "DEGISTI"
    if len(c1):
        c1.loc[:, "kaynak"] = "x"
    assert [frame_key(x) for x in A.unified(r)] == ref  # dönen sonucun değiştirilmesi sonraki çağrıya bulaşmaz
    ar = archive(r)
    v_ref = [frame_key(x) for x in (A.view(ar, None).merged, A.view(ar, "openfootball").merged)]
    v1 = A.view(ar, None)
    v1.merged.loc[:, "home"] = "Başka"
    v1.rows.loc[:, "fthg"] = -1.0
    assert [frame_key(x) for x in (A.view(ar, None).merged, A.view(ar, "openfootball").merged)] == v_ref
    assert frame_key(ar.rows) == before


def test_group_work_does_not_scale_with_pandas_selections(monkeypatch):
    """Maç başına DataFrame seçimi yapılmaz: DataFrame.__getitem__ çağrı sayısı maç sayısıyla büyümez; bir çoklu olay
    isteğinde görünüm ve takım-maç tablosu birer kez kurulur."""
    counts = {"getitem": 0}
    orig = pd.DataFrame.__getitem__

    def counting(self, key):
        counts["getitem"] += 1
        return orig(self, key)

    small = rows(*_season(2015))
    big = rows(*_season(2010), *_season(2011), *_season(2012), *_season(2013), *_season(2014), *_season(2015))

    def count(fn, r):
        counts["getitem"] = 0
        fn(r)
        return counts["getitem"]

    monkeypatch.setattr(pd.DataFrame, "__getitem__", counting)
    n_small, n_big = count(A.unified, small), count(A.unified, big)
    o_small, o_big = count(_old_unified, small), count(_old_unified, big)
    monkeypatch.setattr(pd.DataFrame, "__getitem__", orig)
    extra_seasons, extra_matches = 5, len(big) - len(small)
    assert extra_matches == 60
    assert n_big - n_small <= 20 * extra_seasons  # yalnızca sezon başına sabit iş (ad eşleme); maç başına seçim yok
    assert o_big - o_small >= 5 * extra_matches  # önceki uygulama maç başına seçim yapıyordu (testin duyarlılığı)
    calls = {"unified": 0, "team_matches": 0}
    real_u, real_t = A.unified, A.team_matches

    def cu(r):
        calls["unified"] += 1
        return real_u(r)

    def ct(v, lg):
        calls["team_matches"] += 1
        return real_t(v, lg)

    monkeypatch.setattr(A, "unified", cu)
    monkeypatch.setattr(A, "team_matches", ct)
    ar = archive(big)
    ids = [m for m in A.view(ar, "openfootball").merged["mac_kimligi"] if "Arsenal FC" in m]
    calls.update(unified=0, team_matches=0)
    res = O.olay_karsilastir(ar, "Arsenal FC", kaynak="openfootball", olaylar=ids, limit=10)
    assert res["durum"] == "TAMAMLANDI" and len(res["olaylar"]) == 10
    assert calls == {"unified": 1, "team_matches": 1}

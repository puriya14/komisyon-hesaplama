"""Takım-maç tablosu (her maç için ev ve deplasman satırı), kapsam/dilim bayrakları ve olay kartları.

Zaman ve veri kuralları (docs/DIZI_ARASTIRMA_SOZLESMESI.md §1, §3, §4):
  * Takım içi sıra = gerçek oynanma tarihi (aynı takımın aynı gün iki maçı yoktur; kontrol edilir).
  * Kimlik: kanonik takım (``aliases.AliasMap``); pencereler kapsanan ligler arasında devam eder,
    lig değişikliği bayraklanır.
  * Lig-sezon tamlığı format tablosuyla (takım başına normal sezon = 2(n−1); SC0 33, SC1–SC3 36). Normal sezon
    sayısını aşan maçlar ``ust_tur`` (grup/play-off turu) olarak işaretlenir ve pencere/hedeflerden çıkarılır.
  * Dilim: 400 günden uzun ara yeni dilim başlatır. Pencere geçerliliği ayrıca lig-sezon tamlığına (≥ %97) ve
    ardışık sezon etiketlerine bağlıdır.
  * ``awarded`` (hükmen olabilir) satırların sonucu karar anında bilinmediği için "bilinmiyor"dur.
  * Oynanmamış sonraki maçlar "sansürlü" kalır; başarısızlık veya sıfır gol sayılmaz.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.leagues import LEAGUES
from ..goals.ledger import event_id as make_event_id
from ..goals.markets import HTFT_KEYS, PRIMARY_YES, TEAM_TARGETS, htft_frame, label_frame
from .aliases import ALIAS_VERSION, AliasMap

SPELL_GAP_DAYS = 400
COMPLETE_SHARE = 0.97
FORFEIT_SCORES = {(3, 0), (0, 3), (5, 0), (0, 5)}
STAT_COLS = ("h_shots", "a_shots", "h_sot", "a_sot", "h_corners", "a_corners")
REGULAR_LEN_OVERRIDE = {"SC0": 33, "SC1": 36, "SC2": 36, "SC3": 36}  # takım başına normal sezon maçı
# Kısaltılmış sezonlar (COVID): oynanmayan maçlar veri boşluğu değildir; oynananların tamamı kayıtlı kabul edilir.
SHORTENED_SEASONS = {
    ("B1", "2019/20"), ("E2", "2019/20"), ("E3", "2019/20"), ("EC", "2019/20"), ("F1", "2019/20"), ("F2", "2019/20"),
    ("N1", "2019/20"), ("SC0", "2019/20"), ("SC1", "2019/20"), ("SC2", "2019/20"), ("SC3", "2019/20"),
    ("SC1", "2020/21"), ("SC2", "2020/21"), ("SC3", "2020/21"),
}
SHORTENED_MIN_SHARE = 0.6
ONGOING_MAX_LAG = 2  # devam eden sezonda takım maç sayıları arasında olağan erteleme farkı
RES_POINTS = {"G": 3, "B": 1, "M": 0}
TEAM_CELLS = tuple((h, f) for h in "GBM" for f in "GBM")  # takım İY/MS hücresi 0..8
CELL_INDEX = {c: i for i, c in enumerate(TEAM_CELLS)}
_HOME_RES = {"1": "G", "X": "B", "2": "M"}
_AWAY_RES = {"1": "M", "X": "B", "2": "G"}
# Ham ev perspektifi İY/MS hücresi (HTFT_KEYS sırası) → (ev takım hücresi, deplasman takım hücresi)
RAW_TO_TEAM_CELL = {
    i: (CELL_INDEX[(_HOME_RES[k.split("_")[1]], _HOME_RES[k.split("_")[2]])],
        CELL_INDEX[(_AWAY_RES[k.split("_")[1]], _AWAY_RES[k.split("_")[2]])])
    for i, k in enumerate(HTFT_KEYS)
}

WINDOW_STATES = ("COMPLETE", "DATA_START", "COVERAGE_EXIT", "GAP_GT_400D", "RIGHT_CENSORED", "INCOMPLETE_SEASON",
                 "SEASON_SKIP", "HT_MISSING", "POSSIBLE_AWARDED", "UST_TUR")


def season_year(dates) -> np.ndarray:
    """Tarihe göre sezon yılı (1 Temmuz). Dönem/fold sınırları için; sezon içi sıra kaynağın 'season' etiketiyle."""
    d = pd.to_datetime(dates)
    return np.where(d.dt.month >= 7, d.dt.year, d.dt.year - 1)


def possible_awarded(m: pd.DataFrame, sensitive: bool = False) -> np.ndarray:
    """Hükmen olabilecek satırlar. Ana kural: İY skoru yok ve MS ∈ {3-0, 0-3, 5-0, 0-5}.

    ``sensitive=True`` (duyarlılık): ayrıca İY 0-0, MS 3-0/0-3 ve hiç maç istatistiği olmayan satırlar.
    """
    fh, fa = m["fthg"].to_numpy(dtype=float), m["ftag"].to_numpy(dtype=float)
    ht_missing = m["hthg"].isna().to_numpy() | m["htag"].isna().to_numpy()
    score = np.array([(a, b) in FORFEIT_SCORES for a, b in zip(fh, fa)], dtype=bool)
    out = ht_missing & score
    if sensitive:
        cols = [c for c in STAT_COLS if c in m.columns]
        no_stats = m[cols].isna().all(axis=1).to_numpy() if cols else np.ones(len(m), dtype=bool)
        ht00 = (m["hthg"].to_numpy(dtype=float) == 0) & (m["htag"].to_numpy(dtype=float) == 0)
        three = np.array([(a, b) in {(3, 0), (0, 3)} for a, b in zip(fh, fa)], dtype=bool)
        out = out | (ht00 & three & no_stats)
    return out


def _season_start(season) -> np.ndarray:
    return pd.to_numeric(pd.Series(season).astype(str).str[:4], errors="coerce").to_numpy()


def build_team_matches(matches: pd.DataFrame, alias_map: AliasMap | None = None,
                       sensitive_awarded: bool = False) -> pd.DataFrame:
    """Maç tablosundan takım-maç tablosu (ham tablo değişmez). Her maç için iki satır (aynı event_id, pair_id)."""
    alias_map = alias_map or AliasMap.from_matches(matches)
    m = matches.sort_values(["date", "league", "home"], kind="mergesort").reset_index(drop=True)
    country = m["league"].map(lambda c: LEAGUES[c].country if c in LEAGUES else c)
    home_c = [alias_map.canonical(t, c) for t, c in zip(m["home"], country)]
    away_c = [alias_map.canonical(t, c) for t, c in zip(m["away"], country)]
    home_c, away_c, collided = _country_scoped_names(home_c, away_c, list(country))
    codes = htft_frame(m)
    awarded = possible_awarded(m, sensitive_awarded)
    labs = label_frame(m, PRIMARY_YES)
    data_end = pd.Timestamp(m["date"].max())
    raw_cell = np.array([HTFT_KEYS.index(c) if isinstance(c, str) else -1 for c in codes], dtype=np.int16)
    stat_cols = [c for c in STAT_COLS if c in m.columns]
    base = pd.DataFrame({
        "pair_id": np.arange(len(m)),
        "event_id": [make_event_id(lg, d, h, a) for lg, d, h, a in zip(m["league"], m["date"], m["home"], m["away"])],
        "league": m["league"].to_numpy(), "country": country.to_numpy(), "season": m["season"].astype(str).to_numpy(),
        "season_year": season_year(m["date"]), "date": m["date"].to_numpy(),
        "time": m["time"].fillna("").astype(str).to_numpy() if "time" in m.columns else "",
        "htft": codes.to_numpy(), "raw_cell": raw_cell, "awarded": awarded,
        "source": m["source"].to_numpy() if "source" in m.columns else "",
        "has_odds": (np.isfinite(m[["o_h", "o_d", "o_a"]].to_numpy(dtype=float)).all(axis=1)
                     if "o_h" in m.columns else np.zeros(len(m), dtype=bool)),
        "has_stats": m[stat_cols].notna().any(axis=1).to_numpy() if stat_cols else np.zeros(len(m), dtype=bool),
        "A": labs["BTTS_BOTH_HALVES_YES"].to_numpy(), "B": labs["FT_OVER_3_5"].to_numpy(), "C": labs["FH_OVER_1_5"].to_numpy(),
    })
    for c in ("o_h", "o_d", "o_a", "h_red", "a_red"):
        base[c] = m[c].to_numpy(dtype=float) if c in m.columns else np.nan
    fh, fa = m["fthg"].to_numpy(dtype=float), m["ftag"].to_numpy(dtype=float)
    hh, ha = m["hthg"].to_numpy(dtype=float), m["htag"].to_numpy(dtype=float)
    parts = []
    for is_home in (True, False):
        t = base.copy()
        t["is_home"] = is_home
        t["team"] = home_c if is_home else away_c
        t["team_raw"] = (m["home"] if is_home else m["away"]).to_numpy()
        t["opponent"] = away_c if is_home else home_c
        t["opponent_raw"] = (m["away"] if is_home else m["home"]).to_numpy()
        t["gf_ft"], t["ga_ft"] = (fh, fa) if is_home else (fa, fh)
        t["gf_ht"], t["ga_ht"] = (hh, ha) if is_home else (ha, hh)
        t["red_for"], t["red_against"] = (base["h_red"], base["a_red"]) if is_home else (base["a_red"], base["h_red"])
        parts.append(t)
    tm = pd.concat(parts, ignore_index=True)
    tm["gf_2h"] = tm["gf_ft"] - tm["gf_ht"]
    tm["ga_2h"] = tm["ga_ft"] - tm["ga_ht"]
    _team_results(tm)
    tm = tm.sort_values(["team", "date"], kind="mergesort").reset_index(drop=True)
    dup = tm.duplicated(["team", "date"])
    if dup.any():
        ex = tm.loc[dup, ["team", "league", "date"]].drop_duplicates("team").head(3)
        examples = ", ".join(f"{r.team} ({r.league} {pd.Timestamp(r.date).date()})" for r in ex.itertuples())
        raise ValueError(f"Aynı takımın aynı gün birden fazla maçı var ({int(dup.sum())}); sıra belirsiz. "
                         f"Örnekler: {examples}")
    tm["row_id"] = np.arange(len(tm))
    tm["mirror_row"] = _mirror_rows(tm)
    tm["season_ord"] = tm.groupby(["team", "season"]).cumcount() + 1
    _coverage_flags(tm, data_end)
    _sequence_flags(tm, data_end)
    tm.attrs.update({"alias_version": ALIAS_VERSION, "alias_sha256": alias_map.sha256(), "n_awarded": int(awarded.sum()),
                     "data_end": str(data_end.date()),
                     "intra_season_splits": {f"{k[0]}|{k[1]}": v for k, v in alias_map.splits.items()},
                     "rejected_splits": [list(r) for r in getattr(alias_map, "rejected_splits", [])],
                     "country_scoped_names": sorted(collided)})
    return tm


def _country_scoped_names(home: list, away: list, country: list) -> tuple[list, list, set]:
    """Farklı ülkelerde aynı adı taşıyan kulüpler ayrı takımdır (ör. iki ayrı "Nacional"): bu adlar
    "Ad (Ülke)" biçiminde ayrılır; aksi halde aynı gün iki maç ya da iki kulübün karışmış geçmişi oluşur.
    Tek ülkede geçen adlara dokunulmaz."""
    seen: dict[str, set] = {}
    for c, h, a in zip(country, home, away):
        seen.setdefault(h, set()).add(c)
        seen.setdefault(a, set()).add(c)
    collided = {n for n, cs in seen.items() if len(cs) > 1}
    if not collided:
        return home, away, set()
    home = [f"{h} ({c})" if h in collided else h for h, c in zip(home, country)]
    away = [f"{a} ({c})" if a in collided else a for a, c in zip(away, country)]
    return home, away, collided


def _team_results(tm: pd.DataFrame) -> None:
    ft_known = ~tm["awarded"].to_numpy() & np.isfinite(tm["gf_ft"].to_numpy()) & np.isfinite(tm["ga_ft"].to_numpy())
    ft = np.where(tm["gf_ft"] > tm["ga_ft"], "G", np.where(tm["gf_ft"] == tm["ga_ft"], "B", "M")).astype(object)
    ft[~ft_known] = None
    ht_known = tm["htft"].notna().to_numpy()
    raw_ht = [k.split("_")[1] if isinstance(k, str) else None for k in tm["htft"]]
    ht = np.array([(_HOME_RES if ih else _AWAY_RES)[r] if r else None for r, ih in zip(raw_ht, tm["is_home"])], dtype=object)
    ht[~ht_known] = None
    tm["ht_res"], tm["ft_res"] = ht, ft
    ok = ht_known & ft_known
    cell = np.full(len(tm), -1, dtype=np.int16)
    cell[ok] = [CELL_INDEX[(a, b)] for a, b in zip(ht[ok], ft[ok])]
    tm["cell"] = cell
    tm["ft_known"] = ft_known
    for name, (a, b) in TEAM_TARGETS.items():
        tm[name] = np.where(ok, ((ht == a) & (ft == b)).astype(float), np.nan)
    for name, r in (("GALIBIYET", "G"), ("BERABERLIK", "B"), ("MAGLUBIYET", "M")):
        tm[name] = np.where(ft_known, (ft == r).astype(float), np.nan)
    tm["points"] = np.where(ft_known, pd.Series(ft).map(RES_POINTS).to_numpy(dtype=float), np.nan)


def _mirror_rows(tm: pd.DataFrame) -> np.ndarray:
    order = np.lexsort((tm["is_home"].to_numpy(), tm["pair_id"].to_numpy()))
    a, b = order[0::2], order[1::2]
    if not (tm["pair_id"].to_numpy()[a] == tm["pair_id"].to_numpy()[b]).all():
        raise ValueError("Her maç için tam iki takım satırı olmalı")
    mirror = np.empty(len(tm), dtype=np.int64)
    mirror[a], mirror[b] = b, a
    return mirror


def _coverage_flags(tm: pd.DataFrame, data_end: pd.Timestamp) -> None:
    """Lig-sezon tamlığı ve üst tur (normal sezon sonrası) bayrakları."""
    n_teams = tm.groupby(["league", "season"])["team"].transform("nunique").to_numpy()
    reg = np.array([REGULAR_LEN_OVERRIDE.get(lg, 2 * (n - 1)) for lg, n in zip(tm["league"], n_teams)], dtype=float)
    tm["regular_len"] = reg
    over = tm["season_ord"].to_numpy() > reg  # iki takımdan biri için normal sezonu aşan maç → üst tur
    tm["ust_tur"] = pd.Series(over).groupby(tm["pair_id"].to_numpy()).transform("max").to_numpy()
    regular = ~tm["ust_tur"].to_numpy()
    keys = [tm["league"], tm["season"]]
    n_reg_rows = pd.Series(regular).groupby(keys).transform("sum").to_numpy()  # takım satırı = 2 × maç
    team_reg = pd.Series(regular).groupby([tm["league"], tm["season"], tm["team"]]).transform("sum")
    max_count = team_reg.groupby(keys).transform("max").to_numpy()
    last = pd.Series(pd.to_datetime(tm["date"])).groupby(keys).transform("max")
    min_count = team_reg.groupby(keys).transform("min").to_numpy()
    share_full = n_reg_rows / np.maximum(n_teams * reg, 1)
    ongoing = (last >= data_end - pd.Timedelta(days=14)).to_numpy() & (share_full < COMPLETE_SHARE)
    shortened = np.array([(lg, se) in SHORTENED_SEASONS for lg, se in zip(tm["league"], tm["season"])], dtype=bool)
    tm["season_share"] = share_full
    tm["season_ongoing"] = ongoing
    tm["season_shortened"] = shortened
    tm["season_complete"] = (share_full >= COMPLETE_SHARE) | (shortened & (share_full >= SHORTENED_MIN_SHARE)) | (
        ongoing & (min_count >= max_count - ONGOING_MAX_LAG))


def _sequence_flags(tm: pd.DataFrame, data_end: pd.Timestamp) -> None:
    """Pencere dizisi (üst tur satırları hariç takım sırası): dilim, sezon atlaması, lig değişikliği, bitiş nedeni."""
    seq_idx = np.where(~tm["ust_tur"].to_numpy())[0]
    tm["in_seq"] = ~tm["ust_tur"].to_numpy()
    t_seq = tm["team"].to_numpy()[seq_idx]
    d = pd.to_datetime(tm["date"].to_numpy()[seq_idx])
    same_team = np.r_[False, t_seq[1:] == t_seq[:-1]]
    gap = np.full(len(seq_idx), np.nan)
    gap[1:] = (d[1:] - d[:-1]).days
    gap[~same_team] = np.nan
    new_spell = ~same_team | (gap > SPELL_GAP_DAYS)
    spell = np.cumsum(new_spell) - 1
    ss = _season_start(tm["season"].to_numpy()[seq_idx])
    season_jump = np.r_[False, (ss[1:] - ss[:-1]) > 1] & same_team & ~new_spell
    lg = tm["league"].to_numpy()[seq_idx]
    league_change = np.r_[False, lg[1:] != lg[:-1]] & same_team & ~new_spell
    reset = new_spell | league_change
    grp = np.cumsum(reset)
    since = pd.Series(np.ones(len(seq_idx))).groupby(grp).cumsum().to_numpy() - 1  # lig değişikliği/dilim başından beri
    cols = {"lig_arasi_gun": np.where(new_spell, np.nan, gap), "spell_id": spell.astype(float),
            "spell_seq": pd.Series(spell).groupby(spell).cumcount().to_numpy().astype(float), "since_league_change": since}
    for k, v in cols.items():
        full = np.full(len(tm), np.nan)
        full[seq_idx] = v
        tm[k] = full
    for k, v in (("season_skip", season_jump), ("league_changed", league_change)):
        full = np.zeros(len(tm), dtype=bool)
        full[seq_idx] = v
        tm[k] = full
    # Dilim bitiş nedeni: veri sonu (sağdan sansür) / uzun ara sonrası yeniden görülme / kapsamdan çıkış
    last_by_spell = pd.Series(d).groupby(spell).max()
    team_of_spell = pd.Series(t_seq).groupby(spell).first()
    team_last = pd.Series(d).groupby(t_seq).max()
    reason = {}
    for sp, dl in last_by_spell.items():
        if dl >= data_end - pd.Timedelta(days=45):
            reason[sp] = "RIGHT_CENSORED"
        elif dl < team_last[team_of_spell[sp]]:
            reason[sp] = "GAP_GT_400D"
        else:
            reason[sp] = "COVERAGE_EXIT"
    er = np.full(len(tm), None, dtype=object)
    er[seq_idx] = [reason[s] for s in spell]
    tm["spell_end"] = er


# ----------------------------------------------------------------------------
# Pencereler ve olay kartı
# ----------------------------------------------------------------------------

CARD_COLS = ["row_id", "event_id", "date", "time", "league", "season", "team", "opponent", "is_home", "gf_ht", "ga_ht",
             "gf_ft", "ga_ft", "htft", "ht_res", "ft_res", "awarded", "lig_arasi_gun", "has_odds", "has_stats",
             "red_for", "red_against", "source"]


def window_rows(tm: pd.DataFrame, row: int, k: int, forward: bool) -> tuple[pd.DataFrame, str]:
    """Takımın aynı dilimdeki önceki/sonraki k pencere maçı ve pencere durumu (``WINDOW_STATES``)."""
    r = tm.loc[row]
    if not r["in_seq"]:
        return tm.iloc[0:0][CARD_COLS], "UST_TUR"
    team_rows = np.where((tm["team"].to_numpy() == r["team"]) & (tm["spell_id"].to_numpy() == r["spell_id"]))[0]
    pos = int(np.searchsorted(team_rows, row))
    sel = team_rows[pos + 1: pos + 1 + k] if forward else team_rows[max(0, pos - k): pos]
    w = tm.iloc[sel]
    if len(w) < k:
        if forward:
            state = r["spell_end"] or "RIGHT_CENSORED"
        else:
            first = pd.Timestamp(tm["date"].min())
            start = pd.Timestamp(tm.iloc[team_rows[0]]["date"])
            state = "DATA_START" if start <= first + pd.Timedelta(days=45) else "GAP_GT_400D"
    elif not w["season_complete"].all() or (not forward and not r["season_complete"]):
        state = "INCOMPLETE_SEASON"
    elif w["season_skip"].iloc[1:].any() or (r["season_skip"] if not forward else w["season_skip"].iloc[0]):
        state = "SEASON_SKIP"
    elif w["awarded"].any():
        state = "POSSIBLE_AWARDED"
    elif w["ht_res"].isna().any():
        state = "HT_MISSING"
    else:
        state = "COMPLETE"
    return w[CARD_COLS], state


def event_card(tm: pd.DataFrame, row: int, pre=(5, 10), post=(1, 3, 5), data_meta: dict | None = None,
               s0_strength: dict | None = None) -> dict:
    """Olay kartı: PRE_EVENT, EVENT_OUTCOME, POST_EVENT ve RAKIP_PRE_EVENT ayrı bloklar.

    POST_EVENT yalnızca geçmiş inceleme içindir; maç öncesi ekranına taşınmaz.
    ``s0_strength``: row_id → o maç öncesi S0 galibiyet olasılığı (varsa kartta gösterilir).
    """
    r = tm.loc[row]
    mrow = int(r["mirror_row"])
    teams = tm["team"].to_numpy()

    def rows(w):
        out = w.to_dict("records")
        for rec in out:
            i = int(rec["row_id"])
            rec["onceki_mac"] = i - 1 if i > 0 and teams[i - 1] == rec["team"] else None
            rec["sonraki_mac"] = i + 1 if i + 1 < len(tm) and teams[i + 1] == rec["team"] else None
            if s0_strength is not None:
                rec["s0_guc"] = s0_strength.get(i)
                rec["s0_guc_rakip"] = s0_strength.get(int(tm.iloc[i]["mirror_row"]))
            rec["saat_dilimi"] = "doğrulanmadı" if rec.get("time") else "saat yok"
        return out

    card = {
        "kimlik": {"event_id": r["event_id"], "pair_id": int(r["pair_id"]), "tarih": str(pd.Timestamp(r["date"]).date()),
                   "lig": r["league"], "sezon": r["season"], "takim": r["team"], "takim_kaynak_adi": r["team_raw"],
                   "rakip": r["opponent"], "ev_sahibi": bool(r["is_home"])},
        "EVENT_OUTCOME": {
            "iy_takim": _score(r["gf_ht"], r["ga_ht"]), "ms_takim": _score(r["gf_ft"], r["ga_ft"]),
            "iy_ev_dep": _score(*((r["gf_ht"], r["ga_ht"]) if r["is_home"] else (r["ga_ht"], r["gf_ht"]))),
            "ms_ev_dep": _score(*((r["gf_ft"], r["ga_ft"]) if r["is_home"] else (r["ga_ft"], r["gf_ft"]))),
            "iy_ms_ham": r["htft"], "takim_iy": r["ht_res"], "takim_ms": r["ft_res"],
            "hukmen_olabilir": bool(r["awarded"]), "ust_tur": bool(r["ust_tur"])},
        "PRE_EVENT": {}, "POST_EVENT": {}, "RAKIP_PRE_EVENT": {},
        "kapsam": {"alanlar": "İY ve MS skoru, maç istatistikleri (varsa), 1X2 ve 2,5 oranları (zamanı doğrulanamaz)",
                   "yok": "kupa/Avrupa maçları, dakika bazlı goller, İY/MS oranları, kadro, xG, resmî kararlar",
                   "gorunum_lig": "lig maçları", "gorunum_tum_resmi": "DATA_QUALITY_BLOCKED (kupa/Avrupa maçı verisi yok)"},
        "kaynak": {"kaynak": r["source"], "veri_guncelleme": (data_meta or {}).get("updated_at"),
                   "yayimlanma_zamani": "doğrulanamaz (geçmiş veri sonradan derlenmiştir)",
                   "esleme": tm.attrs.get("alias_version", ALIAS_VERSION)},
    }
    for k in pre:
        w, st = window_rows(tm, row, k, forward=False)
        card["PRE_EVENT"][f"onceki_{k}"] = {"durum": st, "maclar": rows(w)}
        w, st = window_rows(tm, mrow, k, forward=False)
        card["RAKIP_PRE_EVENT"][f"onceki_{k}"] = {"durum": st, "maclar": rows(w)}
    for k in post:
        w, st = window_rows(tm, row, k, forward=True)
        card["POST_EVENT"][f"sonraki_{k}"] = {"durum": st, "maclar": rows(w)}
    return card


def _score(a, b) -> str | None:
    return f"{int(a)}-{int(b)}" if np.isfinite(a) and np.isfinite(b) else None


def team_events(tm: pd.DataFrame, team: str, target: str | None = None, htft_key: str | None = None) -> pd.DataFrame:
    """Mod A (tanımlayıcı, olay seçimli): takımın olayları — takım hedefi (ör. IY_GERIDE_MS_GALIP) veya ham İY/MS.

    Olaylar arası gün, lig maçı sayısı ve sezon geçişi eklenir; son olaydan gözlem sonuna kadar olan açık aralık
    ``censored_tail`` özniteliğinde verilir (gözlem süresi bitmiş olay aralıkları kaybolmaz). ``aralik_durumu``:
    aralığın veri boşluğu işaretleri (``GAP_FLAG_TEXT``); boş = işaretsiz. Maç sayısı veride gözlenen maçtır.
    """
    if (target is None) == (htft_key is None):
        raise ValueError("target veya htft_key'den yalnızca biri verilmeli")
    if htft_key and htft_key not in HTFT_KEYS:
        raise KeyError(htft_key)
    t = tm[(tm["team"] == team) & tm["in_seq"]]
    t = t.assign(seq_no=np.arange(len(t)))
    hit = (t[target] == 1) if target else (t["htft"] == htft_key)
    known = t[target].notna() if target else t["htft"].notna()
    ev = t[hit.to_numpy()].copy()
    ev["onceki_olaydan_gun"] = pd.to_datetime(ev["date"]).diff().dt.days
    ev["onceki_olaydan_mac"] = ev["seq_no"].diff()
    ev["sezon_gecisi"] = ev["season"].ne(ev["season"].shift()) & ev["season"].shift().notna()
    ev["ayni_dilim"] = ev["spell_id"].eq(ev["spell_id"].shift())
    pos = ev["seq_no"].to_numpy(dtype=int)
    ev["aralik_durumu"] = [_gap_flags(t, known, int(pos[i - 1]), int(pos[i]), closed=True) if i else ""
                           for i in range(len(ev))]
    if len(t):
        last = t.iloc[-1]
        start = ev.iloc[-1] if len(ev) else t.iloc[0]
        ev.attrs["censored_tail"] = {
            "son_olay_tarihi": str(pd.Timestamp(start["date"]).date()) if len(ev) else None,
            "son_mac_tarihi": str(pd.Timestamp(last["date"]).date()),
            "acik_aralik_mac": int(last["seq_no"] - start["seq_no"]) + (0 if len(ev) else 1),
            "bitis_nedeni": last["spell_end"],
            "aralik_durumu": _gap_flags(t, known, int(start["seq_no"]) - (0 if len(ev) else 1), int(last["seq_no"]),
                                        closed=False),
            "not": "Açık (sansürlü) aralık: olay henüz tekrarlanmadı veya gözlem bitti; 'olmayacak' anlamına gelmez.",
        }
    return ev


# Mod A aralık işaretleri: aralık, veride GÖZLENEN lig maçı sayısıdır. Aşağıdaki durumlarda gerçek aralık farklı
# olabilir (eksik maçlar sayılmaz, bilinmeyen sonuç olaysız sayılır). Planlanan maçların ≥%97'si bulunan
# lig-sezonlardaki tekil eksik maçlar fikstür listesi olmadan algılanamaz (işaretlenmez).
GAP_FLAG_TEXT = {
    "EKSIK_SEZON": "aralık tam olmayan lig-sezondan geçiyor (eksik maçlar sayılmadı)",
    "DILIM_DEGISTI": "aralık uzun bir kapsam boşluğundan (>400 gün) geçiyor",
    "SEZON_ATLAMASI": "aralıkta veride olmayan sezon var",
    "LIG_DEGISTI": "aralıkta lig değişikliği var",
    "BILINMEYEN_SONUC": "aralıkta sonucu bilinmeyen maç olaysız sayıldı",
}


def _gap_flags(t: pd.DataFrame, known: pd.Series, a: int, b: int, closed: bool) -> str:
    """t'nin (a, b] satır aralığındaki veri boşluğu işaretleri; boşsa '' (temiz). ``closed``: b bir olay satırı."""
    w = t.iloc[a + 1:b + 1]  # aralığa giren maçlar (başlangıç olayı hariç)
    span = t.iloc[max(a, 0):b + 1]  # uçlar dahil: eksik maçlar uçların sezonunda da olabilir
    if w.empty:
        return ""
    inner = known.iloc[a + 1:b] if closed else known.iloc[a + 1:b + 1]
    flags = []
    if not span["season_complete"].all():
        flags.append("EKSIK_SEZON")
    if span["spell_id"].nunique() > 1:
        flags.append("DILIM_DEGISTI")
    if w["season_skip"].any():
        flags.append("SEZON_ATLAMASI")
    if w["league_changed"].any():
        flags.append("LIG_DEGISTI")
    if (~inner).any():
        flags.append("BILINMEYEN_SONUC")
    return ",".join(flags)


def coverage_report(tm: pd.DataFrame) -> pd.DataFrame:
    """Lig-sezon tamlık tablosu (pencere geçerliliği ve raporlama için)."""
    g = tm.groupby(["league", "season"])
    return pd.DataFrame({
        "takim": g["team"].nunique(), "normal_sezon_mac": g["regular_len"].first(),
        "pay": g["season_share"].first().round(3), "tam": g["season_complete"].first(),
        "devam_ediyor": g["season_ongoing"].first(), "kisaltilmis": g["season_shortened"].first(),
        "ust_tur_satir": g["ust_tur"].sum(),
    }).reset_index()

"""Araştırma çerçevesi: takım-maç tablosu + kalibre S0 + atomlar + S1 özellikleri (modüllerin ortak veri sözleşmesi).

``ResearchFrame`` alanları (hepsi ``tm`` satırlarına hizalı):
  tm            : timeline.build_team_matches çıktısı (row_id sırası)
  raw_probs     : (n, 9) maçın kalibre S0 İY/MS hücreleri, EV perspektifi, HTFT_KEYS sırası (S0 yoksa NaN)
  team_probs    : (n, 9) aynı dağılımın takım perspektifi (İY, MS) ∈ {G,B,M}² hücreleri (timeline.TEAM_CELLS sırası)
  p0[target]    : takım hedefi olasılığı (team_probs hücre toplamı) — ikiz satırlar tutarlı
  y[target]     : gerçekleşen hedef (1/0/NaN)
  exp_points    : 3·P(G) + P(B) (kalibre S0)
  p_win         : P(takım MS galip)
  mkt_win/draw/loss, mkt_points : marjsız Bet365 1X2 (oran yoksa NaN; zamanı doğrulanamaz)
  opp_strength  : rakibin galibiyet olasılığı (rakip satırının p_win'i)
  eligible      : değerlendirmeye uygun (pencere dizisinde, üst tur değil, lig değişikliğinden ≥ 8 maç sonra,
                  S0 var, lig-sezon tam)
  period        : satırın dönemi (config.PERIODS) veya None
  cluster       : lig|sezon küme kimliği (varyans ve bootstrap için; ikiz satırlar, takım-sezon ve hafta iç içe)
  atoms         : dizi + bağlam atomları (features)
  s1            : S1/S2 sürekli özellikleri (features.s1_features)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..goals.markets import HTFT_KEYS, TEAM_TARGETS
from . import config as C
from .features import SeqIndex, context_atoms, history_atoms, outcome_codes, s1_features
from .timeline import CELL_INDEX, RAW_TO_TEAM_CELL, TEAM_CELLS

TARGET_TEAM_CELLS: dict[str, tuple[int, ...]] = {name: (CELL_INDEX[cells],) for name, cells in TEAM_TARGETS.items()}
TARGET_TEAM_CELLS.update({
    "GALIBIYET": tuple(i for i, (h, f) in enumerate(TEAM_CELLS) if f == "G"),
    "BERABERLIK": tuple(i for i, (h, f) in enumerate(TEAM_CELLS) if f == "B"),
    "MAGLUBIYET": tuple(i for i, (h, f) in enumerate(TEAM_CELLS) if f == "M"),
})


def team_cell_probs(raw_probs: np.ndarray, is_home: np.ndarray) -> np.ndarray:
    """Ev perspektifi 9 İY/MS hücresini takım perspektifi hücrelerine çevirir (satır başına permütasyon)."""
    out = np.full_like(raw_probs, np.nan)
    home_map = np.array([RAW_TO_TEAM_CELL[i][0] for i in range(9)])
    away_map = np.array([RAW_TO_TEAM_CELL[i][1] for i in range(9)])
    h = np.asarray(is_home, dtype=bool)
    out[np.ix_(h, home_map)] = raw_probs[h]
    out[np.ix_(~h, away_map)] = raw_probs[~h]
    return out


def devig_1x2(o_h, o_d, o_a) -> np.ndarray:
    """Basit normalizasyonla marjsız 1X2 olasılıkları (n, 3); oran yoksa NaN."""
    inv = 1.0 / np.column_stack([o_h, o_d, o_a]).astype(float)
    ok = np.isfinite(inv).all(axis=1) & (inv > 0).all(axis=1)
    out = np.full(inv.shape, np.nan)
    out[ok] = inv[ok] / inv[ok].sum(axis=1, keepdims=True)
    return out


@dataclass
class ResearchFrame:
    tm: pd.DataFrame
    raw_probs: np.ndarray
    team_probs: np.ndarray
    p0: dict
    y: dict
    exp_points: np.ndarray
    p_win: np.ndarray
    mkt: np.ndarray  # (n, 3) takım perspektifi: galip, berabere, mağlup
    mkt_points: np.ndarray
    opp_strength: np.ndarray
    eligible: np.ndarray
    period: np.ndarray
    cluster: np.ndarray
    seq: SeqIndex
    atoms: dict = field(default_factory=dict)
    s1: pd.DataFrame | None = None
    meta: dict = field(default_factory=dict)


def target_probs(team_probs: np.ndarray) -> dict[str, np.ndarray]:
    return {t: team_probs[:, list(cells)].sum(axis=1) for t, cells in TARGET_TEAM_CELLS.items()}


def target_outcomes(tm: pd.DataFrame, ht: np.ndarray | None = None, ft: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """Hedef sonuçları; ``ht``/``ft`` verilirse (ör. referans süreç) onlardan, verilmezse gerçek veriden."""
    if ht is None:
        return {t: tm[t].to_numpy(dtype=float) for t in TARGET_TEAM_CELLS}
    code = {"G": 0, "B": 1, "M": 2}
    out = {}
    both = (ht >= 0) & (ft >= 0)
    for t, (hh, ff) in TEAM_TARGETS.items():
        out[t] = np.where(both, ((ht == code[hh]) & (ft == code[ff])).astype(float), np.nan)
    for t, r in (("GALIBIYET", 0), ("BERABERLIK", 1), ("MAGLUBIYET", 2)):
        out[t] = np.where(ft >= 0, (ft == r).astype(float), np.nan)
    return out


def build_frame(tm: pd.DataFrame, s0_cal: pd.DataFrame, with_s1: bool = True) -> ResearchFrame:
    """``s0_cal``: event_id + HTFT_KEYS kalibre hücreleri (s0.calibrated_cells çıktısı)."""
    cal = s0_cal.set_index("event_id")[list(HTFT_KEYS)]
    raw = cal.reindex(tm["event_id"]).to_numpy(dtype=float)
    is_home = tm["is_home"].to_numpy()
    tp = team_cell_probs(raw, is_home)
    p0 = target_probs(tp)
    p_win, p_draw = p0["GALIBIYET"], p0["BERABERLIK"]
    exp_points = 3.0 * p_win + p_draw
    m3 = devig_1x2(tm["o_h"].to_numpy(), tm["o_d"].to_numpy(), tm["o_a"].to_numpy())
    mkt = np.where(is_home[:, None], m3, m3[:, ::-1])  # takım perspektifi: galip, berabere, mağlup
    mkt_points = 3.0 * mkt[:, 0] + mkt[:, 1]
    mirror = tm["mirror_row"].to_numpy()
    sy = tm["season_year"].to_numpy()
    period = np.array([C.period_of(int(y)) for y in sy], dtype=object)
    has_s0 = np.isfinite(raw).all(axis=1)
    eligible = (tm["in_seq"].to_numpy() & ~tm["ust_tur"].to_numpy() & has_s0 & tm["season_complete"].to_numpy()
                & (np.nan_to_num(tm["since_league_change"].to_numpy(dtype=float), nan=-1) >= C.LEAGUE_CHANGE_EXCLUDE))
    si = SeqIndex(tm)
    ht, ft = outcome_codes(tm)
    atoms = history_atoms(si, ht, ft, exp_points)
    atoms.update(context_atoms(tm, p_win))
    fr = ResearchFrame(
        tm=tm, raw_probs=raw, team_probs=tp, p0=p0, y=target_outcomes(tm), exp_points=exp_points, p_win=p_win,
        mkt=mkt, mkt_points=mkt_points, opp_strength=p_win[mirror], eligible=eligible, period=period,
        cluster=(tm["league"].astype(str) + "|" + tm["season"].astype(str)).to_numpy(), seq=si, atoms=atoms,
    )
    if with_s1:
        fr.s1 = s1_features(tm, si, exp_points, fr.opp_strength, mkt_points)
    fr.meta = {"n_rows": len(tm), "n_eligible": int(eligible.sum()), "has_s0": int(has_s0.sum())}
    return fr

"""Olaylar arası süre ve ayrık zamanlı tehlike modeli (sözleşme §8, deney ailesi F4).

Olaylar ``config.HAZARD_EVENTS`` (takım perspektifi İY/MS geçişleri); kaynak ``fr.y[olay]`` (1/0/NaN). Zaman birimi
takımın LİG maçıdır (pencere dizisi ``in_seq``; üst tur hariç). Kurallar:
  * Gözlem bloğu = takımın aynı dilimindeki (``spell_id``) ardışık, lig-sezonu tam (``season_complete``) pencere
    maçları. Eksik lig-sezonu veya sezon atlaması bloğu keser (aradaki olaylar gözlenmemiş olabilir).
  * Risk altı süre her blokta İLK GÖZLENEN olaydan başlar (sol kesik). Blok başı → ilk olay dilimi
    ``LEFT_TRUNCATED`` olarak saklanır ve sayılır; risk süresine ve Kaplan–Meier'e girmez.
  * Son olay → blok sonu açık (sansürlü) aralıktır; neden ``tm.spell_end`` (RIGHT_CENSORED / COVERAGE_EXIT /
    GAP_GT_400D) veya blok kesilmişse INCOMPLETE_SEASON / SEASON_SKIP. Sansürlü aralıklar kaybolmaz.
  * Sonucu bilinmeyen maçlar (İY eksik, hükmen olabilir) maç sayısına girer, olay sayılmaz; aralıkta ayrıca sayılır.
  * "Tüm resmî maçlar" sayımı ve teknik direktör/kadro dönemleri: DATA_QUALITY_BLOCKED (veri yok).
Tehlike modeli: logit P(olay) = logit p0 (kalibre S0, offset) + a + b·kırılganlık + Σ_k c_k·[son olaydan beri maç ∈ k]
(referans kategori 4–10). Keşifte takım kümeli sağlam Wald testi (küçük örneklem duyarlılığı: takım kümeli skor
testi); parametre/testte dondurulmuş uyumla örneklem dışı log-kayıp ve 7b yanlışlama listesinin tehlike modeline
uyarlanmış hâli (lig/takım çıkarma, en çok katkı veren %1, sezon yönü, piyasa kontrolü). "Uzun süredir olmadı, olmak
zorunda" kuralı kurulmaz; frekans/döngü taraması yapılmaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import chi2, norm
from scipy.stats import f as f_dist

from ..goals.validation import calibration_bins, calibration_slope
from . import config as C
from .frame import ResearchFrame

_BLOCKED = "DATA_QUALITY_BLOCKED"
assert _BLOCKED in C.STATUSES
_REF_BIN = (4, 10)
assert _REF_BIN in C.HAZARD_BINS


def _bin_name(lo, hi) -> str:
    return f"{int(lo)}+" if not np.isfinite(hi) else f"{int(lo)}-{int(hi)}"


BIN_NAMES = tuple(_bin_name(lo, hi) for lo, hi in C.HAZARD_BINS)
REF_BIN_INDEX = C.HAZARD_BINS.index(_REF_BIN)
BIN_COLS = tuple(f"bin_{n}" for i, n in enumerate(BIN_NAMES) if i != REF_BIN_INDEX)
_BIN_LOWS = np.array([lo for lo, _ in C.HAZARD_BINS], dtype=float)

GAP_KINDS = ("COMPLETED", "CENSORED", "LEFT_TRUNCATED", "LEFT_TRUNCATED_CENSORED")
MKT_COLS = ("mkt_galip_logit", "mkt_maglup_logit")  # 7b/5 piyasa kontrolü ortak değişkenleri


def _check_event(event: str) -> None:
    if event not in C.HAZARD_EVENTS:
        raise ValueError(f"Tehlike olayı {C.HAZARD_EVENTS} içinden olmalı: {event!r}")


# ----------------------------------------------------------------------------
# Gözlem blokları ve "son olaydan beri maç"
# ----------------------------------------------------------------------------

def observation_blocks(tm: pd.DataFrame) -> tuple[np.ndarray, dict[int, str]]:
    """Gözlem bloğu kimliği (tm'ye hizalı; blok dışı −1) ve blok başına bitiş nedeni.

    Blok = aynı dilimde ardışık, lig-sezonu tam pencere maçları. Sonuçlardan bağımsızdır (yalnızca takvim/kapsam).
    """
    rows = np.where(tm["in_seq"].to_numpy())[0]
    spell = tm["spell_id"].to_numpy()[rows]
    ok = tm["season_complete"].to_numpy()[rows].astype(bool)
    skip = tm["season_skip"].to_numpy()[rows].astype(bool)
    end = tm["spell_end"].to_numpy()[rows]
    n = len(rows)
    same_spell = np.r_[False, spell[1:] == spell[:-1]] if n else np.zeros(0, dtype=bool)
    prev_ok = np.r_[False, ok[:-1]] if n else np.zeros(0, dtype=bool)
    new_block = ok & (~same_spell | ~prev_ok | skip)
    seq = np.cumsum(new_block) - 1
    blk = np.where(ok, seq, -1)
    block = np.full(len(tm), -1, dtype=np.int64)
    block[rows] = blk
    reasons: dict[int, str] = {}
    pos = np.where(ok)[0]
    if len(pos):
        last = pos[np.r_[blk[pos][1:] != blk[pos][:-1], True]]  # her bloğun son dizi konumu
        for j in last:
            b = int(blk[j])
            if j + 1 < n and same_spell[j + 1]:
                reasons[b] = "INCOMPLETE_SEASON" if not ok[j + 1] else "SEASON_SKIP"
            else:
                reasons[b] = end[j] if isinstance(end[j], str) else "RIGHT_CENSORED"
    return block, reasons


@dataclass
class _EventState:
    rows: np.ndarray       # blok satırları (tm konumu), takım/tarih sırası; bloklar bitişik
    block: np.ndarray      # blok kimliği (rows'a hizalı)
    reasons: dict
    ev: np.ndarray         # gözlenen olay (y == 1)
    known: np.ndarray      # sonuç biliniyor
    since: np.ndarray      # son gözlenen olaydan beri lig maçı (rows'a hizalı; yoksa NaN)


def _event_state(fr: ResearchFrame, event: str) -> _EventState:
    _check_event(event)
    block_full, reasons = observation_blocks(fr.tm)
    rows = np.where(block_full >= 0)[0]
    b = block_full[rows]
    y = np.asarray(fr.y[event], dtype=float)[rows]
    known = np.isfinite(y)
    ev = known & (y == 1)
    idx = np.arange(len(rows))
    cm = pd.Series(np.where(ev, idx, -1)).groupby(b).cummax().to_numpy() if len(rows) else np.zeros(0)
    same = np.r_[False, b[1:] == b[:-1]] if len(rows) else np.zeros(0, dtype=bool)
    prev = np.where(same, cm, -1)
    since = np.where(prev >= 0, idx - prev, np.nan).astype(float)
    return _EventState(rows=rows, block=b, reasons=reasons, ev=ev, known=known, since=since)


def since_last_event(fr: ResearchFrame, event: str) -> np.ndarray:
    """Aynı gözlem bloğunda son GÖZLENEN olaydan beri lig maçı sayısı (tm'ye hizalı; olaydan sonraki maç = 1).

    Blokta henüz olay gözlenmemişse (sol kesik dilim) veya satır blok dışındaysa NaN. Yalnızca önceki maçları kullanır.
    """
    st = _event_state(fr, event)
    out = np.full(len(fr.tm), np.nan)
    out[st.rows] = st.since
    return out


def duration_bin(since) -> np.ndarray:
    """``config.HAZARD_BINS`` kategori indeksi (since < 1 veya NaN → −1)."""
    s = np.asarray(since, dtype=float)
    out = np.searchsorted(_BIN_LOWS, np.nan_to_num(s, nan=0.0), side="right") - 1
    return np.where(np.isfinite(s) & (s >= 1), out, -1)


# ----------------------------------------------------------------------------
# Olaylar arası aralıklar ve Kaplan–Meier
# ----------------------------------------------------------------------------

def event_gaps(fr: ResearchFrame, event: str, team: str | None = None) -> pd.DataFrame:
    """Takım (kanonik kimlik) başına olaylar arası aralıklar — tanımlayıcı (Mod A), tahmin değildir.

    Satır türleri (``kind``):
      COMPLETED                olay → sonraki olay (``matches`` = sonraki olaya kadar lig maçı, olay maçı dahil)
      CENSORED                 son olay → blok sonu (``matches`` = olaysız gözlenen maç; açık aralık)
      LEFT_TRUNCATED           blok başı → ilk gözlenen olay (önceki olay görülmedi; risk süresine girmez, sayılır)
      LEFT_TRUNCATED_CENSORED  hiç olay gözlenmeyen blok (sol kesik ve sansürlü; risk süresine girmez, sayılır)
    ``censor_reason``: RIGHT_CENSORED / COVERAGE_EXIT / GAP_GT_400D (tm.spell_end), INCOMPLETE_SEASON, SEASON_SKIP.
    ``tum_resmi_mac`` ve ``teknik_direktor_kadro_donemi`` sütunları DATA_QUALITY_BLOCKED'dır.
    """
    st = _event_state(fr, event)
    tm = fr.tm
    rows, b = st.rows, st.block
    team_arr = tm["team"].to_numpy()[rows]
    if team is not None:
        keep = team_arr == team
        rows, b, team_arr = rows[keep], b[keep], team_arr[keep]
        ev, known = st.ev[keep], st.known[keep]
    else:
        ev, known = st.ev, st.known
    n = len(rows)
    dates = pd.to_datetime(tm["date"].to_numpy()[rows])
    season = tm["season"].to_numpy()[rows]
    league = tm["league"].to_numpy()[rows]
    spell = tm["spell_id"].to_numpy()[rows]
    row_id = tm["row_id"].to_numpy()[rows]
    same = np.r_[False, b[1:] == b[:-1]] if n else np.zeros(0, dtype=bool)
    cum_sc = np.r_[0, np.cumsum(same & np.r_[False, season[1:] != season[:-1]])] if n else np.zeros(1)
    cum_lc = np.r_[0, np.cumsum(same & np.r_[False, league[1:] != league[:-1]])] if n else np.zeros(1)
    cum_unk = np.r_[0, np.cumsum(~known)]
    starts = np.where(~same)[0]
    ends = np.r_[starts[1:] - 1, n - 1] if len(starts) else np.zeros(0, dtype=int)

    recs = []

    def add(kind, a, z, event_end, reason, left):
        """a..z: dizi konumları (dahil). Geçiş ve bilinmeyen sayımları a'dan sonraki maçlarda."""
        if left:
            matches = z - a + 1
            unk = cum_unk[z + 1 - int(event_end)] - cum_unk[a]
        else:
            matches = z - a
            unk = cum_unk[z + 1 - int(event_end)] - cum_unk[a + 1]
        recs.append((team_arr[a], int(spell[a]), int(b[a]), kind, int(row_id[a]), int(row_id[z]), dates[a], dates[z],
                     int((dates[z] - dates[a]).days), int(matches), int(cum_sc[z + 1] - cum_sc[a + 1]),
                     int(cum_lc[z + 1] - cum_lc[a + 1]), int(unk), bool(event_end), reason is not None, reason,
                     bool(left), not left, season[a], season[z]))

    for s, z in zip(starts, ends):
        reason = st.reasons[int(b[s])]
        e = s + np.where(ev[s:z + 1])[0]
        if len(e) == 0:
            add("LEFT_TRUNCATED_CENSORED", s, z, False, reason, True)
            continue
        add("LEFT_TRUNCATED", s, e[0], True, None, True)
        for a, c in zip(e[:-1], e[1:]):
            add("COMPLETED", a, c, True, None, False)
        add("CENSORED", e[-1], z, False, reason, False)

    cols = ["team", "spell_id", "block_id", "kind", "start_row", "end_row", "start_date", "end_date", "days", "matches",
            "season_transitions", "league_changes", "n_unknown", "event_end", "censored", "censor_reason",
            "left_truncated", "at_risk", "start_season", "end_season"]
    gaps = pd.DataFrame.from_records(recs, columns=cols)
    gaps["tum_resmi_mac"] = _BLOCKED
    gaps["teknik_direktor_kadro_donemi"] = _BLOCKED
    lt = gaps["left_truncated"].to_numpy(dtype=bool)
    cens = gaps["censored"].to_numpy(dtype=bool)
    gaps.attrs.update({
        "event": event, "team": team, "n_blocks": int(len(starts)), "n_intervals": int(len(gaps)),
        "n_completed": int((gaps["kind"] == "COMPLETED").sum()), "n_censored": int((cens & ~lt).sum()),
        "n_left_truncated": int(lt.sum()), "left_truncated_matches": int(gaps.loc[lt, "matches"].sum()),
        "at_risk_matches": int(gaps.loc[~lt, "matches"].sum()),
        "censor_reasons": {str(k): int(v) for k, v in gaps.loc[cens, "censor_reason"].value_counts().items()},
        "tum_resmi_mac": _BLOCKED, "teknik_direktor_kadro_donemi": _BLOCKED,
        "not": "Olay seçimli tanımlayıcı aralıklar; açık (sansürlü) aralık 'olmayacak' veya 'sırası geldi' anlamına "
               "gelmez. Süre birimi lig maçıdır (kupa/Avrupa maçları veride yok).",
    })
    return gaps


def km_survival(gaps: pd.DataFrame) -> pd.DataFrame:
    """Kaplan–Meier S(t) = P(sonraki olaya kadar geçen lig maçı > t); sansürlü aralıklar risk kümesinde kalır.

    Yalnızca risk altındaki aralıklar (COMPLETED, CENSORED) kullanılır; sol kesik dilimler dışlanır ve sayılır.
    Sansür t'de: aralık t maç boyunca olaysız gözlendi → t'deki risk kümesindedir. Greenwood SE, log(−log) %95 aralık.
    """
    d = gaps[gaps["at_risk"].astype(bool)]
    t = d["matches"].to_numpy(dtype=np.int64)
    e = d["event_end"].to_numpy(dtype=bool)
    cols = ["t", "n_at_risk", "n_events", "n_censored", "survival", "se", "ci_lo", "ci_hi"]
    times, inv = np.unique(t, return_inverse=True)
    n_ev = np.bincount(inv, weights=e.astype(float), minlength=len(times))
    n_c = np.bincount(inv, weights=(~e).astype(float), minlength=len(times))
    n_risk = len(t) - np.r_[0, np.cumsum(n_ev + n_c)[:-1]] if len(times) else np.zeros(0)
    with np.errstate(divide="ignore", invalid="ignore"):
        surv = np.cumprod(np.where(n_risk > 0, 1.0 - n_ev / n_risk, 1.0))
        gw = np.cumsum(np.where(n_risk > n_ev, n_ev / (n_risk * (n_risk - n_ev)), 0.0))
        se = surv * np.sqrt(gw)
        ll = np.log(-np.log(surv))
        se_ll = np.sqrt(gw) / np.abs(np.log(surv))
        lo = np.exp(-np.exp(ll + 1.96 * se_ll))
        hi = np.exp(-np.exp(ll - 1.96 * se_ll))
    edge = (surv >= 1.0) | (surv <= 0.0) | ~np.isfinite(lo)
    lo = np.where(edge, surv, lo)
    hi = np.where(edge, surv, hi)
    km = pd.DataFrame({"t": times, "n_at_risk": n_risk.astype(int), "n_events": n_ev.astype(int),
                       "n_censored": n_c.astype(int), "survival": surv, "se": se, "ci_lo": lo, "ci_hi": hi},
                      columns=cols)
    below = km.loc[km["survival"] <= 0.5, "t"]
    lt = gaps["left_truncated"].astype(bool)
    km.attrs.update({
        "n_intervals": int(len(d)), "n_events": int(e.sum()), "n_censored": int((~e).sum()),
        "n_censored_total": int(gaps["censored"].astype(bool).sum()), "n_excluded_left_truncated": int(lt.sum()),
        "excluded_left_truncated_matches": int(gaps.loc[lt, "matches"].sum()),
        "median_matches": int(below.iloc[0]) if len(below) else None, "unit": "lig maçı",
    })
    return km


# ----------------------------------------------------------------------------
# Tehlike veri seti
# ----------------------------------------------------------------------------

def frailty_covariate(fr: ResearchFrame, event: str, prior: float = 50.0, n_prev: int = 2) -> pd.DataFrame:
    """Takım kırılganlığı: önceki ``n_prev`` sezondaki küçültülmüş kendi olay oranı (tm'ye hizalı; zaman güvenli).

    Satırın sezon yılı Y (1 Temmuz) için yalnızca Y−1 … Y−n_prev sezon yıllarının bilinen sonuçları (hepsi Y'nin
    ilk gününden önce bilinir): ``(O + prior·base)/(n + prior)``; base = satırın liginin aynı sezonlardaki olay oranı
    (lig verisi yoksa tüm ligler; o da yoksa NaN). Mevcut ve sonraki sezonların sonuçları hiç okunmaz.
    """
    _check_event(event)
    tm = fr.tm
    y = np.asarray(fr.y[event], dtype=float)
    known = tm["in_seq"].to_numpy() & np.isfinite(y)
    sy = tm["season_year"].to_numpy().astype(np.int64)
    team, league = tm["team"].to_numpy(), tm["league"].to_numpy()
    agg = pd.DataFrame({"team": team, "league": league, "sy": sy, "o": np.where(known, y, 0.0),
                        "n": known.astype(float)})
    ts = agg.groupby(["team", "sy"])[["o", "n"]].sum()
    ls = agg.groupby(["league", "sy"])[["o", "n"]].sum()
    gs = agg.groupby("sy")[["o", "n"]].sum()
    o = np.zeros(len(tm))
    n = np.zeros(len(tm))
    lo_, ln_, go_, gn_ = (np.zeros(len(tm)) for _ in range(4))
    for lag in range(1, n_prev + 1):
        kt = pd.MultiIndex.from_arrays([team, sy - lag])
        kl = pd.MultiIndex.from_arrays([league, sy - lag])
        t_ = ts.reindex(kt).fillna(0.0)
        l_ = ls.reindex(kl).fillna(0.0)
        g_ = gs.reindex(sy - lag).fillna(0.0)
        o += t_["o"].to_numpy()
        n += t_["n"].to_numpy()
        lo_ += l_["o"].to_numpy()
        ln_ += l_["n"].to_numpy()
        go_ += g_["o"].to_numpy()
        gn_ += g_["n"].to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        base = np.where(ln_ > 0, lo_ / ln_, np.where(gn_ > 0, go_ / gn_, np.nan))
    frail = (o + prior * base) / (n + prior)
    return pd.DataFrame({"frailty": frail, "frailty_base": base, "frailty_o": o, "frailty_n": n}, index=tm.index)


def hazard_dataset(fr: ResearchFrame, event: str, mask: np.ndarray | None = None) -> pd.DataFrame:
    """Risk altındaki satırlar: uygun (``fr.eligible``), sonuç biliniyor, blokta ilk gözlenen olaydan SONRA.

    Sütunlar: y, offset = logit(p0), frailty (zaman güvenli), since (son gözlenen olaydan beri maç), bin + kategori
    göstergeleri (referans 4–10), team (Wald kümesi), cluster (lig-sezon; bootstrap), pair_id (ikiz satır), period,
    date, ``MKT_COLS`` (marjsız Bet365 galip/mağlup logiti, takım perspektifi; yalnızca 7b/5 piyasa kontrolünde
    kullanılır; oran yoksa NaN). ``mask`` (tm'ye hizalı bool) aday satırları ayrıca sınırlar (ör. dönem). Sol kesik
    dilimdeki aday satırlar dışlanır ve ``attrs['n_left_truncated_rows']`` olarak sayılır.
    """
    st = _event_state(fr, event)
    tm = fr.tm
    since = np.full(len(tm), np.nan)
    since[st.rows] = st.since
    y = np.asarray(fr.y[event], dtype=float)
    p0 = np.asarray(fr.p0[event], dtype=float)
    m = np.ones(len(tm), dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    cand = m & np.asarray(fr.eligible, dtype=bool) & np.isfinite(y) & np.isfinite(p0) & (p0 > 0) & (p0 < 1)
    fc = frailty_covariate(fr, event)
    frail = fc["frailty"].to_numpy()
    left = cand & ~np.isfinite(since)
    no_frail = cand & np.isfinite(since) & ~np.isfinite(frail)
    keep = cand & np.isfinite(since) & np.isfinite(frail)
    idx = np.where(keep)[0]
    pc = np.clip(p0[idx], 1e-9, 1 - 1e-9)
    bins = duration_bin(since[idx])
    mkt = np.asarray(fr.mkt, dtype=float)[idx]
    with np.errstate(divide="ignore", invalid="ignore"):
        mk = np.log(mkt) - np.log1p(-mkt)
    mk = np.where(np.isfinite(mk), mk, np.nan)
    ds = pd.DataFrame({
        "row_id": tm["row_id"].to_numpy()[idx], "pair_id": tm["pair_id"].to_numpy()[idx],
        "team": tm["team"].to_numpy()[idx],
        "league": tm["league"].to_numpy()[idx], "season": tm["season"].to_numpy()[idx],
        "season_year": tm["season_year"].to_numpy()[idx], "date": pd.to_datetime(tm["date"].to_numpy()[idx]),
        "period": np.asarray(fr.period, dtype=object)[idx], "cluster": np.asarray(fr.cluster)[idx],
        "y": y[idx], "p0": p0[idx], "offset": np.log(pc) - np.log1p(-pc),
        "frailty": frail[idx], "frailty_base": fc["frailty_base"].to_numpy()[idx],
        "frailty_n": fc["frailty_n"].to_numpy()[idx], "since": since[idx], "bin": bins,
        "bin_name": np.array(BIN_NAMES, dtype=object)[bins],
        MKT_COLS[0]: mk[:, 0], MKT_COLS[1]: mk[:, 2],
    })
    for i, name in enumerate(BIN_NAMES):
        if i != REF_BIN_INDEX:
            ds[f"bin_{name}"] = (bins == i).astype(float)
    ds.attrs.update({"event": event, "n_candidates": int(cand.sum()), "n_left_truncated_rows": int(left.sum()),
                     "n_no_frailty": int(no_frail.sum()), "n_rows": int(len(ds)), "n_events": int(ds["y"].sum()),
                     "reference_bin": BIN_NAMES[REF_BIN_INDEX]})
    return ds


# ----------------------------------------------------------------------------
# Uyum: offsetli lojistik (L-BFGS) + takım kümeli sandviç kovaryans + kategori Wald testi
# ----------------------------------------------------------------------------

@dataclass
class HazardFit:
    names: list[str]
    coef: np.ndarray
    cov: np.ndarray
    n: int
    n_events: int
    n_clusters: int
    loglik: float
    converged: bool
    bins: bool
    wald: dict | None = None
    dropped: list = field(default_factory=list)

    @property
    def se(self) -> np.ndarray:
        return np.sqrt(np.clip(np.diag(self.cov), 0, None))

    def predict(self, ds: pd.DataFrame) -> np.ndarray:
        """Dondurulmuş katsayılarla olay olasılığı (yeniden uyum yok). Uyumda düşen kategoriler referansa katılır."""
        return expit(ds["offset"].to_numpy(dtype=float) + _design(ds, self.names) @ self.coef)

    def summary(self) -> dict:
        return {"names": list(self.names), "coef": [float(v) for v in self.coef], "se": [float(v) for v in self.se],
                "n": self.n, "n_events": self.n_events, "n_clusters": self.n_clusters, "loglik": float(self.loglik),
                "converged": bool(self.converged), "bins": self.bins, "wald": self.wald, "dropped": list(self.dropped),
                "reference_bin": BIN_NAMES[REF_BIN_INDEX]}


def _design(ds: pd.DataFrame, names: list[str]) -> np.ndarray:
    cols = [np.ones(len(ds)) if nm == "intercept" else ds[nm].to_numpy(dtype=float) for nm in names]
    return np.column_stack(cols) if cols else np.zeros((len(ds), 0))


def _ml(X: np.ndarray, y: np.ndarray, off: np.ndarray) -> tuple[np.ndarray, bool]:
    """Offsetli lojistik ML (L-BFGS). İlk sütun kesişim olmalı; diğer sütunlar optimizasyon için standartlaştırılır ve
    katsayılar özgün ölçeğe doğrusal olarak geri çevrilir. Dönüş: (katsayılar, yakınsadı mı)."""
    n, k = X.shape
    mu = X[:, 1:].mean(axis=0)
    sd = X[:, 1:].std(axis=0)
    sd = np.where(sd > 1e-12, sd, 1.0)
    Z = X.copy()
    Z[:, 1:] = (X[:, 1:] - mu) / sd

    def fg(g):
        eta = off + Z @ g
        val = (np.logaddexp(0.0, eta) - y * eta).sum() / n
        return val, Z.T @ (expit(eta) - y) / n

    res = minimize(fg, np.zeros(k), jac=True, method="L-BFGS-B",
                   options={"maxiter": 5000, "gtol": 1e-10, "ftol": 1e-15})
    beta = res.x.copy()
    beta[1:] = res.x[1:] / sd
    beta[0] = res.x[0] - float(np.sum(res.x[1:] * mu / sd))

    def nll(b):
        eta = off + X @ b
        return float((np.logaddexp(0.0, eta) - y * eta).sum())

    for _ in range(5):  # Newton cilası (amaç azalmıyorsa durur)
        p = expit(off + X @ beta)
        try:
            step = np.linalg.solve(X.T @ (X * (p * (1 - p))[:, None]), X.T @ (y - p))
        except np.linalg.LinAlgError:
            break
        if not np.all(np.isfinite(step)) or nll(beta + step) > nll(beta) + 1e-9:
            break
        beta = beta + step
        if np.max(np.abs(step)) < 1e-10:
            break
    p = expit(off + X @ beta)
    grad_ok = bool(np.max(np.abs(X.T @ (y - p))) / n < 1e-6)
    return beta, bool(res.success or grad_ok)


def fit_hazard(ds: pd.DataFrame, bins: bool = True, cluster_col: str = "team", extra: tuple = ()) -> HazardFit:
    """logit P(olay) = offset + a + b·frailty (+ ``extra`` ortak değişkenleri) (+ kategori göstergeleri), L-BFGS ile ML.

    Kovaryans: ``cluster_col`` (takım) kümeli sandviç, CR1 düzeltmesi G/(G−1)·(N−1)/(N−K). ``bins=True`` ise
    kategori katsayıları için ortak Wald testi, stat = c'V⁻¹c: ``p`` = F(df, G−1) referansıyla (stat/df), ``p_chi2`` =
    χ²(df) (büyük G'de ikisi aynı). Küçük örneklem duyarlılığı: ``p_score`` = kategorisiz (kısıtlı) uyumda takım
    kümeli etkin skor (LM) testi, χ²(df). Sentetik sıfır benzetimlerinde (40 takım kümesi, ~110 olay; 1000 tekrar)
    α = 0,05'te red oranı: Wald-χ² %9, Wald-F %6,4, skor %5; 80 küme / ~500 olayda üçü de ≈ %4–6. Satırı olmayan veya
    olayı olmayan kategoriler (ML sonsuza gider) tasarımdan düşer (satırları referansa katılır) ve ``dropped`` içinde
    raporlanır. ``extra`` sütunları sonlu olmalıdır (ör. 7b/5 piyasa kontrolünde oranlı satırlar).
    """
    y = ds["y"].to_numpy(dtype=float)
    off = ds["offset"].to_numpy(dtype=float)
    names = ["intercept", "frailty"]
    dropped = []
    fr_col = ds["frailty"].to_numpy(dtype=float) if len(ds) else np.zeros(0)
    if len(ds) == 0 or np.ptp(fr_col) < 1e-12:
        names.remove("frailty")
        dropped.append({"name": "frailty", "reason": "sabit veya satır yok"})
    names += list(extra)
    if bins:
        for c in BIN_COLS:
            col = ds[c].to_numpy(dtype=float) if c in ds else np.zeros(len(ds))
            if col.sum() == 0:
                dropped.append({"name": c, "reason": "satır yok"})
            elif (col * y).sum() == 0 or (col * (1 - y)).sum() == 0:
                dropped.append({"name": c, "reason": "olay yok veya hepsi olay"})
            else:
                names.append(c)
    X = _design(ds, names)
    n, k = X.shape
    if n == 0 or y.sum() == 0 or y.sum() == n:
        raise ValueError("Tehlike uyumu için hem olaylı hem olaysız satır gerekir")
    if not (np.isfinite(X).all() and np.isfinite(off).all()):
        raise ValueError("Tasarım veya offset sonlu olmayan değer içeriyor")
    beta, converged = _ml(X, y, off)
    eta = off + X @ beta
    p = expit(eta)
    loglik = float(-(np.logaddexp(0.0, eta) - y * eta).sum())
    H = X.T @ (X * (p * (1 - p))[:, None])
    try:
        bread = np.linalg.inv(H)
    except np.linalg.LinAlgError:
        bread = np.linalg.pinv(H)
    _, inv = np.unique(ds[cluster_col].to_numpy(), return_inverse=True)
    G = int(inv.max()) + 1
    Sg = np.zeros((G, k))
    np.add.at(Sg, inv, X * (y - p)[:, None])
    corr = (G / max(G - 1, 1)) * ((n - 1) / max(n - k, 1))
    cov = corr * bread @ (Sg.T @ Sg) @ bread
    fit = HazardFit(names=names, coef=beta, cov=cov, n=int(n), n_events=int(y.sum()), n_clusters=G, loglik=loglik,
                    converged=converged, bins=bins, dropped=dropped)
    if bins:
        fit.wald = _wald(fit)
        fit.wald.update(_score_test(X, y, off, names, inv, G))
    return fit


def _wald(fit: HazardFit) -> dict:
    idx = [i for i, nm in enumerate(fit.names) if nm.startswith("bin_")]
    if not idx:
        return {"stat": float("nan"), "df": 0, "p": float("nan"), "p_chi2": float("nan"), "terms": []}
    c = fit.coef[idx]
    V = fit.cov[np.ix_(idx, idx)]
    try:
        stat = float(c @ np.linalg.solve(V, c))
        df = len(idx)
    except np.linalg.LinAlgError:
        stat = float(c @ np.linalg.pinv(V) @ c)
        df = int(np.linalg.matrix_rank(V))
    p_chi2 = float(chi2.sf(stat, df)) if df > 0 else float("nan")
    p_f = float(f_dist.sf(stat / df, df, fit.n_clusters - 1)) if df > 0 and fit.n_clusters > 1 else float("nan")
    return {"stat": stat, "df": int(df), "p": p_f, "p_chi2": p_chi2, "terms": [fit.names[i] for i in idx],
            "cluster": "takım", "n_clusters": fit.n_clusters}


def _score_test(X: np.ndarray, y: np.ndarray, off: np.ndarray, names: list[str], inv: np.ndarray, G: int) -> dict:
    """Kategori katsayıları = 0 için takım kümeli etkin skor (LM) testi (kısıtlı uyumda; yalnızca duyarlılık)."""
    b_idx = [i for i, nm in enumerate(names) if nm.startswith("bin_")]
    r_idx = [i for i, nm in enumerate(names) if not nm.startswith("bin_")]
    if not b_idx or G < 2:
        return {"score_stat": float("nan"), "p_score": float("nan")}
    beta_r, _ = _ml(X[:, r_idx], y, off)
    p = expit(off + X[:, r_idx] @ beta_r)
    Hm = X.T @ (X * (p * (1 - p))[:, None])
    A = Hm[np.ix_(b_idx, r_idx)] @ np.linalg.pinv(Hm[np.ix_(r_idx, r_idx)])
    Sg = np.zeros((G, X.shape[1]))
    np.add.at(Sg, inv, X * (y - p)[:, None])
    Ut = Sg[:, b_idx] - Sg[:, r_idx] @ A.T
    U = Ut.sum(axis=0)
    V = (G / (G - 1)) * (Ut.T @ Ut)
    stat = float(U @ np.linalg.pinv(V) @ U)
    df = int(np.linalg.matrix_rank(V))
    return {"score_stat": stat, "p_score": float(chi2.sf(stat, df)) if df > 0 else float("nan")}


# ----------------------------------------------------------------------------
# Örneklem dışı karşılaştırma (dondurulmuş uyum) ve aile
# ----------------------------------------------------------------------------

def _log_loss(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return -(y * np.log(p) + (1 - y) * np.log1p(-p))


def _cluster_bootstrap(diff: np.ndarray, clusters: np.ndarray, reps: int, seed: int) -> np.ndarray:
    """Kümeler (lig-sezon; duyarlılıkta ISO hafta) yerine koymalı yeniden örneklenir; ortalama farkın dağılımı."""
    _, inv = np.unique(clusters, return_inverse=True)
    s = np.bincount(inv, weights=diff)
    c = np.bincount(inv).astype(float)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(s), size=(reps, len(s)))
    return s[draws].sum(axis=1) / c[draws].sum(axis=1)


def _boot_summary(diff: np.ndarray, clusters: np.ndarray, reps: int, seed: int) -> dict:
    """Ortalama fark, kümeli bootstrap %95 aralığı, SE ve tek yönlü p (H1: fark < 0; normal yaklaşım + bootstrap)."""
    boot = _cluster_bootstrap(diff, clusters, reps, seed)
    se = float(np.std(boot, ddof=1))
    d = float(diff.mean())
    return {"diff": d, "ci_lo": float(np.quantile(boot, 0.025)), "ci_hi": float(np.quantile(boot, 0.975)), "se": se,
            "p_one_sided": float(norm.cdf(d / se)) if se > 0 else float("nan"),
            "p_boot": float((1 + (boot >= 0).sum()) / (reps + 1)), "n_clusters": int(len(np.unique(clusters)))}


def _calibration(y: np.ndarray, p: np.ndarray) -> dict:
    slope, icpt = calibration_slope(y, p)
    bins = calibration_bins(y, p)
    ece = float(np.sum([b["n"] * abs(b["tahmin"] - b["gercek"]) for b in bins]) / max(len(y), 1))
    return {"slope": slope, "intercept": icpt, "ece": ece}


def _iso_week(dates: pd.Series) -> np.ndarray:
    iso = pd.DatetimeIndex(pd.to_datetime(dates)).isocalendar()
    return (iso["year"].to_numpy(dtype=np.int64) * 100 + iso["week"].to_numpy(dtype=np.int64))


def _falsification(te: pd.DataFrame, diff: np.ndarray, reps: int, seed: int, top_share: float = 0.01,
                   season_share: float = 0.6, n_counter: int = 20) -> dict:
    """Sözleşme 7b'nin tehlike modeline uyarlanmış hâli (fark = kategorili − kategorisiz log-kayıp; ön-kayıtlı yön < 0).

    1 bir lig veya bir takım çıkarıldığında ortalama fark < 0 kalmalı; 2 farka en çok katkı veren %1 satır (en negatif
    fark) çıkarıldığında fark < 0 ve kümeli bootstrap üst sınırı < 0; 3 sezonların ≥ %60'ında fark < 0; 4 eşleştirilmiş
    ampirik karşılaştırma bu modelde uygulanamaz; 5 piyasa kontrolü ``_market_check``'te; 6 en büyük 20 karşı örnek
    (kategorili modelin en kötü olduğu satırlar; yalnızca satır kimliği ve tarih).
    """
    n = len(diff)
    tot = float(diff.sum())
    out: dict = {}
    loo, ok1 = {}, True
    for col in ("league", "team"):
        _, inv = np.unique(te[col].to_numpy(), return_inverse=True)
        s = np.bincount(inv, weights=diff)
        rest = n - np.bincount(inv).astype(float)
        m = (tot - s[rest > 0]) / rest[rest > 0]
        loo[col] = {"n_grup": int(len(s)), "en_buyuk_fark": float(m.max()) if len(m) else float("nan"),
                    "yon_degisen": int((m >= 0).sum())}
        ok1 = ok1 and len(m) > 0 and bool((m < 0).all())
    out["1_lig_takim_cikarma"] = {"gecti": bool(ok1), **loo}
    k = int(np.ceil(top_share * n))
    keep = np.ones(n, dtype=bool)
    keep[np.argsort(diff, kind="mergesort")[:k]] = False
    b = _boot_summary(diff[keep], te["cluster"].to_numpy()[keep], reps, seed) if keep.any() else {}
    out["2_en_cok_katki_yuzde1"] = {"gecti": bool(b and b["diff"] < 0 and b["ci_hi"] < 0), "cikarilan": k, **b}
    sy = te["season_year"].to_numpy()
    years, inv = np.unique(sy, return_inverse=True)
    sm = np.bincount(inv, weights=diff) / np.bincount(inv)
    share = float((sm < 0).mean()) if len(sm) else float("nan")
    out["3_sezon_yonu"] = {"gecti": bool(len(sm) > 0 and share >= season_share), "pay": share, "esik": season_share,
                           "sezon_fark": {int(y): float(v) for y, v in zip(years, sm)}}
    out["4_eslestirilmis_ampirik"] = {
        "gecti": None, "durum": "UYGULANAMAZ",
        "neden": "Tehlike modelinde koşul/tümleyen yoktur; karşılaştırma aynı satırlarda kategorisiz modelledir."}
    top = np.argsort(-diff, kind="mergesort")[:n_counter]
    out["6_karsi_ornekler"] = [
        {"row_id": int(te["row_id"].iat[i]), "tarih": str(pd.Timestamp(te["date"].iat[i]).date()),
         "son_olaydan_beri": int(te["since"].iat[i]), "y": int(te["y"].iat[i]), "fark": float(diff[i])} for i in top]
    return out


def _market_check(tr: pd.DataFrame, te: pd.DataFrame, reps: int, seed: int) -> dict:
    """7b/5: piyasa (marjsız Bet365 1X2 logitleri) ortak değişken olarak eklendiğinde kategori katkısı sürmeli.

    Aynı dönem planı (eğitim ``tr``, dondurulmuş değerlendirme ``te``), yalnızca oranlı satırlar. Geçme: fark < 0 ve
    lig-sezon kümeli bootstrap üst sınırı < 0. Oran yoksa uyum yapılamaz → geçmedi (``durum`` = VERI_YOK).
    """
    cols = list(MKT_COLS)
    trm = tr[np.isfinite(tr[cols].to_numpy(dtype=float)).all(axis=1)]
    tem = te[np.isfinite(te[cols].to_numpy(dtype=float)).all(axis=1)]
    base = {"n": int(len(tem)), "n_dislanan": int(len(te) - len(tem)), "train_n": int(len(trm))}
    if len(tem) == 0:
        return {"gecti": False, "durum": "VERI_YOK", "neden": "Değerlendirme döneminde oranlı satır yok.", **base}
    try:
        fb = fit_hazard(trm, bins=True, extra=MKT_COLS)
        f0 = fit_hazard(trm, bins=False, extra=MKT_COLS)
    except ValueError as exc:
        return {"gecti": False, "durum": "VERI_YOK", "neden": str(exc), **base}
    yv = tem["y"].to_numpy(dtype=float)
    diff = _log_loss(yv, fb.predict(tem)) - _log_loss(yv, f0.predict(tem))
    b = _boot_summary(diff, tem["cluster"].to_numpy(), reps, seed)
    return {"gecti": bool(b["diff"] < 0 and b["ci_hi"] < 0), "durum": "OK", **base, **b,
            "fit_bins": fb.summary()}


OOS_PLAN = (("parametre", ("kesif",)), ("test", ("kesif", "parametre")))


def oos_compare(fr: ResearchFrame, event: str, n_boot: int = 1000, seed: int = C.SEED) -> dict:
    """Kategorili ve kategorisiz tehlike modelinin örneklem dışı ortalama log-kaybı (fark = kategorili − kategorisiz).

    Parametre dönemi: keşifte uyum; test dönemi: keşif + parametrede uyum, test için DONDURULUR (test içinde yeniden
    uyum yok). Eğitim satırları arındırılır: label_known_at (maç günü + 1) < değerlendirme döneminin ilk günü.
    Belirsizlik: lig-sezon kümeli bootstrap (``n_boot`` ≥ 1000, ``config.SEED``); tek yönlü p (H1: fark < 0),
    bootstrap SE ile normal yaklaşım. Ayrıca (§9): S0 (yalnız offset) log-kaybı, taban sıklık, göreli iyileşme,
    Brier, kalibrasyon (eğim, ECE), ISO hafta blokları duyarlılığı ve 7b uyarlaması (``falsification``).
    """
    if n_boot < 1000:
        raise ValueError("Sözleşme gereği bootstrap tekrar sayısı en az 1000 olmalı")
    ds = hazard_dataset(fr, event)
    per = ds["period"].to_numpy(dtype=object)
    out = {}
    for k, (ev_name, train_names) in enumerate(OOS_PLAN):
        cutoff = pd.Timestamp(C.PERIODS[ev_name][0], 7, 1)
        tr_mask = np.isin(per, train_names) & ((ds["date"] + pd.Timedelta(days=1)) < cutoff).to_numpy()
        tr, te = ds[tr_mask], ds[per == ev_name]
        rec = {"eval_period": ev_name, "train_periods": list(train_names), "cutoff": str(cutoff.date()),
               "n": int(len(te)), "n_events": int(te["y"].sum()) if len(te) else 0, "train_n": int(len(tr)),
               "train_events": int(tr["y"].sum()) if len(tr) else 0,
               "train_last_date": str(tr["date"].max().date()) if len(tr) else None,
               "refit_in_eval": False, "reps": int(n_boot)}
        try:
            fit_b = fit_hazard(tr, bins=True)
            fit_0 = fit_hazard(tr, bins=False)
        except ValueError as exc:
            rec.update({"status": "NO_FIT", "reason": str(exc), "p_one_sided": float("nan")})
            out[ev_name] = rec
            continue
        if len(te) == 0:
            rec.update({"status": "NO_ROWS", "p_one_sided": float("nan"), "fit_bins": fit_b.summary()})
            out[ev_name] = rec
            continue
        yv = te["y"].to_numpy(dtype=float)
        pb, p0_, ps0 = fit_b.predict(te), fit_0.predict(te), te["p0"].to_numpy(dtype=float)
        lb, l0, ls0 = _log_loss(yv, pb), _log_loss(yv, p0_), _log_loss(yv, ps0)
        diff = lb - l0
        main = _boot_summary(diff, te["cluster"].to_numpy(), n_boot, seed + k)
        iso = _boot_summary(diff, _iso_week(te["date"]), n_boot, seed + 100 + k)
        fals = _falsification(te, diff, n_boot, seed + 200 + k)
        fals["5_piyasa"] = _market_check(tr, te, n_boot, seed + 300 + k)
        fals["gecti"] = all(v["gecti"] for key, v in fals.items()
                            if isinstance(v, dict) and v.get("gecti") is not None)
        rec.update({
            "status": "OK", "ll_bins": float(lb.mean()), "ll_no_bins": float(l0.mean()), "ll_s0": float(ls0.mean()),
            **main, "rel_diff": float(main["diff"] / l0.mean()), "diff_vs_s0": float(lb.mean() - ls0.mean()),
            "base_rate": float(yv.mean()),
            "brier_bins": float(((pb - yv) ** 2).mean()), "brier_no_bins": float(((p0_ - yv) ** 2).mean()),
            "brier_s0": float(((ps0 - yv) ** 2).mean()),
            "calibration": {"bins": _calibration(yv, pb), "no_bins": _calibration(yv, p0_), "s0": _calibration(yv, ps0)},
            "iso_week": {key: iso[key] for key in ("ci_lo", "ci_hi", "se", "p_one_sided", "n_clusters")},
            "falsification": fals, "fit_bins": fit_b.summary(), "fit_no_bins": fit_0.summary(),
        })
        out[ev_name] = rec
    return out


def prob_next_k(p, k: int):
    """Sonraki k maçta EN AZ BİR KEZ olay olasılığı: 1 − Π_{i=1..k} (1 − p_i).

    "Sonraki maçta" olasılığı yalnızca p_1'dir (k = 1). "Sonraki k maçta en az bir kez" her zaman ≥ p_1'dir ve k ile
    artar; bu artış daha fazla maçın toplanmasından gelir, "sırası geldi / olmak zorunda" anlamına gelmez.
    ``p``: skaler (her maç için aynı olasılık → 1 − (1 − p)^k), uzunluğu ≥ k olan dizi (ilk k maç) veya (n, ≥k)
    matris (satır başına). Tehlike modelinde p_i, önceki i−1 maçta olay OLMADIĞI varsayımıyla (son olaydan beri maç
    sayısı her adımda bir artar) hesaplanmış koşullu olasılık olmalıdır.
    """
    if int(k) != k or k < 1:
        raise ValueError("k pozitif tam sayı olmalı")
    k = int(k)
    arr = np.asarray(p, dtype=float)
    if np.any((arr < 0) | (arr > 1)):
        raise ValueError("Olasılıklar [0, 1] aralığında olmalı")
    if arr.ndim == 0:
        return float(1.0 - (1.0 - arr) ** k)
    if arr.shape[-1] < k:
        raise ValueError(f"En az {k} maç olasılığı gerekli (verilen {arr.shape[-1]})")
    q = np.prod(1.0 - arr[..., :k], axis=-1)
    return 1.0 - q if arr.ndim > 1 else float(1.0 - q)


def holm(pvals) -> np.ndarray:
    """Holm adım adım düzeltilmiş p değerleri (NaN'lar ailede sayılmaz ve NaN kalır)."""
    p = np.asarray(pvals, dtype=float)
    out = np.full(p.shape, np.nan)
    ok = np.where(np.isfinite(p))[0]
    m = len(ok)
    if m == 0:
        return out
    order = ok[np.argsort(p[ok], kind="mergesort")]
    adj = np.minimum(1.0, np.maximum.accumulate((m - np.arange(m)) * p[order]))
    out[order] = adj
    return out


_HONESTY = ("Test dönemi koşullu örüntüler için ön-kayıtlıdır; S0 İY/MS kalibrasyonu test döneminde görülmüştür. "
            "Tamamen temiz kanıt yalnızca ileriye dönük dönemdir.")


def _failed_checks(oos: dict) -> list[str]:
    out = []
    for name in ("parametre", "test"):
        fals = oos.get(name, {}).get("falsification", {})
        out += [f"{name}:{key}" for key, v in fals.items() if isinstance(v, dict) and v.get("gecti") is False]
    return out


def _status(oos: dict, p_param_holm: float, p_test_holm: float) -> tuple[str, str]:
    par, te = oos.get("parametre", {}), oos.get("test", {})
    par_ok, te_ok = par.get("status") == "OK", te.get("status") == "OK"
    if not par_ok and not te_ok:
        return "INSUFFICIENT_EVIDENCE", "Örneklem dışı değerlendirme yapılamadı (satır/olay yok)."
    par_pass = par_ok and np.isfinite(p_param_holm) and p_param_holm < C.ALPHA
    te_pass = te_ok and np.isfinite(p_test_holm) and p_test_holm < C.ALPHA and te.get("ci_hi", np.inf) < 0
    if par_ok and te_ok:
        if par_pass and te_pass:
            failed = _failed_checks(oos)
            if not failed:
                return "OUT_OF_SAMPLE_SUPPORTED", ("Parametre ve test dönemlerinde tek yönlü Holm geçti; test log-kaybı "
                                                   "bootstrap üst sınırı < 0; 7b uyarlaması (1, 2, 3, 5) iki dönemde "
                                                   "geçti. " + _HONESTY)
            if all(f.endswith("5_piyasa") for f in failed):
                return "NO_ADDED_VALUE", "Piyasa kontrolünde katkı sürmedi (piyasa/temel model bilgisi)."
            return "NO_ADDED_VALUE", "Holm ve bootstrap geçti; 7b yanlışlama uyarlaması geçmedi: " + ", ".join(failed)
        return "NO_ADDED_VALUE", "Örneklem dışı log-kayıp katkısı doğrulanmadı."
    if (par_ok and not par_pass) or (te_ok and not te_pass):
        return "NO_ADDED_VALUE", "Değerlendirilebilen örneklem dışı dönemde log-kayıp katkısı yok."
    return "EXPLORATORY", "Yalnızca bir örneklem dışı dönem değerlendirilebildi."


def run_hazard_family(fr: ResearchFrame, n_boot: int = 1000) -> dict:
    """F4: iki olay türü için aralıklar, Kaplan–Meier, keşif Wald testi ve örneklem dışı log-kayıp; Holm (k = 2).

    Holm ayrı ayrı uygulanır: keşif Wald p'leri (tanımlayıcı), parametre ve test dönemi tek yönlü p'leri.
    Statü (``config.STATUSES``): OUT_OF_SAMPLE_SUPPORTED yalnızca parametre ve test Holm < α, test bootstrap üst
    sınırı < 0 ve 7b uyarlaması (1 lig/takım çıkarma, 2 en çok katkı veren %1, 3 sezon yönü, 5 piyasa kontrolü) iki
    dönemde geçtiyse; değerlendirilen ama geçmeyen → NO_ADDED_VALUE. Keşif Wald testi tanımlayıcıdır (statüyü
    belirlemez; ön-kayıtlı tek hipotez her olay için örneklem dışında değerlendirilir).
    """
    events = list(C.HAZARD_EVENTS)
    res: dict = {}
    for ev in events:
        gaps = event_gaps(fr, ev)
        km = km_survival(gaps)
        disc = hazard_dataset(fr, ev, mask=(np.asarray(fr.period, dtype=object) == "kesif"))
        try:
            fit = fit_hazard(disc, bins=True)
            disc_rec = {"status": "OK", **fit.summary()}
            p_w = fit.wald["p"]
        except ValueError as exc:
            disc_rec = {"status": "NO_FIT", "reason": str(exc)}
            p_w = float("nan")
        res[ev] = {
            "gaps": dict(gaps.attrs), "km": km, "km_summary": dict(km.attrs),
            "discovery": {**disc_rec, "dataset": dict(disc.attrs)}, "p_wald": p_w,
            "oos": oos_compare(fr, ev, n_boot=n_boot),
        }
    pw = holm([res[e]["p_wald"] for e in events])
    pp = holm([res[e]["oos"].get("parametre", {}).get("p_one_sided", np.nan) for e in events])
    pt = holm([res[e]["oos"].get("test", {}).get("p_one_sided", np.nan) for e in events])
    for i, e in enumerate(events):
        res[e]["p_wald_holm"] = float(pw[i])
        res[e]["p_param_holm"] = float(pp[i])
        res[e]["p_test_holm"] = float(pt[i])
        st, why = _status(res[e]["oos"], pp[i], pt[i])
        assert st in C.STATUSES
        res[e]["status"] = st
        res[e]["status_reason"] = why
    return {
        "family": "F4", "contract": C.CONTRACT_VERSION, "config_hash": C.config_hash(), "events": res,
        "multiple_testing": {"method": "Holm", "k": len(events), "alpha": C.ALPHA},
        "blocked": {key: {"status": _BLOCKED, "reason": C.DATA_QUALITY_BLOCKED_ITEMS[key]}
                    for key in ("TUM_RESMI_MACLAR", "TEKNIK_DIREKTOR_KADRO_DONEMI")},
        "notes": [
            "Süre birimi lig maçıdır; 'tüm resmî maçlar' görünümü DATA_QUALITY_BLOCKED.",
            "Uzun süredir olmadı → olmak zorunda kuralı kurulmaz; frekans/döngü taraması yapılmaz.",
            "Test dönemi: koşullu örüntüler için ön-kayıtlı; S0 İY/MS kalibrasyonu test döneminde görülmüştür.",
            "7b yanlışlama listesi tehlike modeline uyarlandı: 1 lig/takım çıkarma, 2 en çok katkı veren %1, 3 sezon "
            "yönü, 5 piyasa (marjsız Bet365 1X2 logitleri) kontrolü; 4 eşleştirilmiş ampirik karşılaştırma bu modelde "
            "uygulanamaz; 6 en büyük 20 karşı örnek satır kimliğiyle listelenir.",
            "Keşif Wald testi takım kümelidir (ikiz satırlar farklı takım kümelerindedir; aynı olay türünde ikisi "
            "birlikte gerçekleşemez); örneklem dışı bootstrap lig-sezon kümelidir (ikiz satırlar aynı kümede).",
        ],
    }

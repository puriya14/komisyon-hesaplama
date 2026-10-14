"""Kupa motoru (KUPA-01): eğitim, ileriye dönük doğrulama, kalibrasyon, doğrulama statüsü ve maç tahmini.

Eğitim:

1. Bütün lig ve kupa maçlarıyla ortak model (``kupa.model``).
2. İleriye dönük (walk-forward) doğrulama: kupa maçı olan her hafta, model yalnızca o haftanın başından ÖNCEKİ
   maçlarla kurulur ve o haftanın kupa maçları tahmin edilir (model o maçları görmez).
3. Kalibrasyon (toplam gol ve güç farkı, ``model.calibrate_rates``): her sezonun tahminleri yalnızca ÖNCEKİ sezonların
   örneklem dışı tahminleriyle kalibre edilir. İlk sezon yalnızca kalibrasyon için ayrılır, ölçümlere girmez.
4. Doğrulama statüsü (önceden tanımlı kural, ``VALIDATION_RULE``) doğrulama grubu başına: örneklem dışı en az
   ``MIN_VALIDATION`` maç ve 1X2 log-kayıp farkının (model − taban) hafta bloklu bootstrap %95 üst sınırı sıfırın
   altında. Taban: sezon başına, önceki sezonların kupa maçlarındaki ev/beraberlik/deplasman oranları. Doğrulanmayan
   grubun tahmini gösterilir ama bahis adayı olmaz (``kupa.uygunluk``).

Tahminlerde piyasa oranıyla karıştırma yoktur (kupa maçları için veri setinde oran yok); kullanıcı Maç Analizi'nde
oran girerse değer hesabı yapılır.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .. import __version__
from ..data.leagues import LEAGUES
from .kimlik import store_key
from .model import EPOCH, LeagueTimeline, ModelConfig, build_data, calibrate_rates, fit, fit_calibration, \
    outside_league
from .turnuvalar import COMPETITIONS, VALIDATION_GROUPS, VALIDATION_NAMES, competition_name

log = logging.getLogger(__name__)

CUP_ENGINE_VERSION = 2  # 2: tarafsız sahada kalibrasyonun iç saha terimi (δ) uygulanmaz
MODEL_VERSION = "kupa-model-v2"
VALIDATION_RULE = ("kupa-dogrulama-v1: örneklem dışı en az 300 maç ve 1X2 log-kayıp farkının (model − önceki "
                   "sezonların sonuç oranları) hafta bloklu bootstrap %95 üst sınırı < 0")
MIN_VALIDATION = 300
WARMUP_DAYS = 730  # ilk örneklem dışı tahminden önce en az bu kadar günlük lig verisi
BOOTSTRAP = 2000
DOGRULANDI, DOGRULANMADI = "DOGRULANDI", "DOGRULANMADI"
STATUS_TR = {DOGRULANDI: "doğrulandı", DOGRULANMADI: "doğrulanmadı"}
DEFAULT_BASE = np.array([0.46, 0.24, 0.30])
ProgressFn = Callable[[int, str], None]


def group_of(comp: str) -> str:
    c = COMPETITIONS.get(str(comp))
    return c.group if c else "C"


def key_of(league: str, team: str) -> str:
    lg = LEAGUES.get(league)
    return store_key(lg.country if lg else league, str(team))


def _week_start(day: int) -> int:
    d = EPOCH + pd.Timedelta(days=int(day))
    return int(day) - d.weekday()


def probs_from_rates(lam, nu, max_goals: int = 10):
    """(1X2 olasılıkları (n,3), 2,5 Üst, KG Var) — bağımsız Poisson skor matrisinden."""
    from scipy.stats import poisson

    lam = np.atleast_1d(np.asarray(lam, dtype=float))
    nu = np.atleast_1d(np.asarray(nu, dtype=float))
    g = np.arange(max_goals + 1)
    ph = poisson.pmf(g[None, :], lam[:, None])
    pa = poisson.pmf(g[None, :], nu[:, None])
    M = ph[:, :, None] * pa[:, None, :]
    M /= M.sum(axis=(1, 2), keepdims=True)
    tri = np.subtract.outer(g, g)
    p_h = (M * (tri > 0)).sum(axis=(1, 2))
    p_d = (M * (tri == 0)).sum(axis=(1, 2))
    p_a = 1.0 - p_h - p_d
    tot = np.add.outer(g, g)
    o25 = 1.0 - (M * (tot <= 2)).sum(axis=(1, 2))
    btts = 1.0 - M[:, 0, :].sum(axis=1) - M[:, :, 0].sum(axis=1) + M[:, 0, 0]
    return np.c_[p_h, p_d, p_a], o25, btts


def _ll3(P, y) -> np.ndarray:
    P = np.clip(np.asarray(P, dtype=float), 1e-9, 1.0)
    return -np.log(P[np.arange(len(y)), y])


def _ll2(p, y) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _bootstrap_upper(diff: np.ndarray, blocks: np.ndarray, seed: int = 20261014) -> float:
    """Ortalama farkın hafta bloklu bootstrap %95 üst sınırı (tek yönlü değil: %97,5 yüzdelik)."""
    if len(diff) == 0:
        return float("nan")
    ub = np.unique(blocks)
    idx = {b: np.nonzero(blocks == b)[0] for b in ub}
    sums = np.array([diff[idx[b]].sum() for b in ub])
    cnts = np.array([len(idx[b]) for b in ub])
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(ub), size=(BOOTSTRAP, len(ub)))
    means = sums[pick].sum(axis=1) / cnts[pick].sum(axis=1)
    return float(np.quantile(means, 0.975))


def _market_frame(ev: pd.DataFrame) -> pd.DataFrame:
    """Ölçülen örneklem dışı tahminlerin bütün market olasılıkları (``models.engine.verify_selection`` biçimi:
    ``pmk_*`` sütunları + gerçek skor). Kupa maçlarında gerçek oran yok: getiri hesaplanmaz."""
    from ..models.engine import PMK_COLS
    from ..models.markets import MARKET_KEYS, markets_from_matrix, score_matrix

    rows = [[mk[k] for k in MARKET_KEYS] for mk in (markets_from_matrix(score_matrix(lam, nu, 0.0))
                                                    for lam, nu in zip(ev.get("lam_c", ()), ev.get("nu_c", ())))]
    df = pd.DataFrame(rows, columns=PMK_COLS)
    if len(df):
        df["fthg"], df["ftag"] = ev["hg"].to_numpy(), ev["ag"].to_numpy()
        df["comp"], df["vgroup"] = ev["comp"].to_numpy(), ev["vgroup"].to_numpy()
    return df


@dataclass
class CupReport:
    trained_at: str = ""
    duration: float = 0.0
    n_cup_matches: int = 0
    n_domestic: int = 0
    n_oos: int = 0
    groups: dict = field(default_factory=dict)  # doğrulama grubu -> ölçümler + statü
    competitions: list = field(default_factory=list)  # turnuva başına ölçümler
    seasons: list = field(default_factory=list)
    calibration: tuple = (0.0, 1.0, 0.0, 1.0)
    rule: str = VALIDATION_RULE


class CupEngine:
    def __init__(self, cfg: ModelConfig | None = None):
        self.version = CUP_ENGINE_VERSION
        self.app_version = __version__
        self.cfg = cfg or ModelConfig()
        self.params = None
        self.calib = (0.0, 1.0, 0.0, 1.0)
        self.oos: pd.DataFrame | None = None
        self.oos_markets: pd.DataFrame | None = None  # ölçülen örneklem dışı tahminlerin market olasılıkları
        self.report: CupReport | None = None
        self.status: dict = {}
        self.data_signature = ""
        self.train_sources: list[str] | None = None
        self.last_day: int | None = None
        self.team_days: dict = {}  # anahtar -> modelin bildiği maç günleri (son 400 gün)
        self.team_names: dict = {}
        self.team_country: dict = {}
        self.timeline: LeagueTimeline | None = None
        self.state_available_since: dt.datetime | None = None
        self.digest = ""

    # ------------------------------------------------------------------ durum
    @property
    def trained(self) -> bool:
        return self.params is not None

    @staticmethod
    def signature(domestic: pd.DataFrame, cups: pd.DataFrame) -> str:
        h = hashlib.sha1()
        h.update(f"{CUP_ENGINE_VERSION}|{MODEL_VERSION}|{len(domestic)}|{len(cups)}".encode())
        for lg, g in domestic.groupby("league"):
            h.update(f"{lg}:{len(g)}:{g['date'].max()}:{int(g['fthg'].sum())}:{int(g['ftag'].sum())}".encode())
            h.update("|".join(sorted(set(g["home"].astype(str)) | set(g["away"].astype(str)))).encode())
        if len(cups):
            for c, g in cups.groupby("comp"):
                h.update(f"{c}:{len(g)}:{g['date'].max()}:{int(g['fthg'].sum())}:{int(g['ftag'].sum())}".encode())
                h.update("|".join(sorted(set(g["home_key"].astype(str)) | set(g["away_key"].astype(str)))).encode())
        return h.hexdigest()

    def league_for(self, key: str, country: str, day: int) -> str:
        lg = self.timeline.league_at(key, int(day)) if self.timeline is not None else None
        return lg or outside_league(country)

    # ------------------------------------------------------------------ eğitim
    def train(self, domestic: pd.DataFrame, cups: pd.DataFrame, progress: ProgressFn | None = None) -> CupReport:
        progress = progress or (lambda p, m: None)
        t0 = time.time()
        if domestic is None or domestic.empty:
            raise ValueError("Kupa modeli için lig verisi yok.")
        cups = cups if cups is not None else pd.DataFrame()
        cups = cups.sort_values("date", kind="mergesort").reset_index(drop=True)
        progress(2, "Kupa modeli: veriler hazırlanıyor...")
        data, tl = build_data(domestic, cups, key_of, group_of)
        self.timeline = tl
        cup_day = ((pd.to_datetime(cups["date"]) - EPOCH).dt.days.to_numpy(dtype=int) if len(cups)
                   else np.zeros(0, dtype=int))
        start = int(data.day.min()) + WARMUP_DAYS
        todo = np.nonzero(cup_day >= start)[0]
        weeks = sorted({_week_start(cup_day[i]) for i in todo})
        rows = []
        init = None
        hl_all = [self.league_for(k, c, d) for k, c, d in zip(cups.get("home_key", []), cups.get("home_country", []),
                                                               cup_day)] if len(cups) else []
        al_all = [self.league_for(k, c, d) for k, c, d in zip(cups.get("away_key", []), cups.get("away_country", []),
                                                               cup_day)] if len(cups) else []
        by_week: dict = {}
        for i in todo:
            by_week.setdefault(_week_start(cup_day[i]), []).append(i)
        for n, wk in enumerate(weeks):
            if n % 10 == 0:
                progress(5 + int(80 * n / max(len(weeks), 1)),
                         f"Kupa modeli: ileriye dönük doğrulama ({n + 1}/{len(weeks)} hafta)...")
            par = fit(data, wk, self.cfg, init)
            if par is None:
                continue
            init = par.as_dict()
            for i in by_week[wk]:
                r = cups.iloc[i]
                rt = par.rates(r["home_key"], r["away_key"], hl_all[i], al_all[i], group_of(r["comp"]),
                               bool(r["neutral"]))
                if rt is None:
                    continue
                rows.append({"i": i, "comp": r["comp"], "season": str(r["season"]), "date": r["date"], "week": wk,
                             "home_key": r["home_key"], "away_key": r["away_key"], "hg": int(r["fthg"]),
                             "ag": int(r["ftag"]), "lam": rt[0], "nu": rt[1], "neutral": bool(r["neutral"]),
                             "outside": hl_all[i].startswith("X:") or al_all[i].startswith("X:")})
        oos = pd.DataFrame(rows)
        progress(86, "Kupa modeli: kalibrasyon ve ölçümler...")
        self._calibrate_and_measure(oos, cups)
        progress(92, "Kupa modeli: bütün verilerle kuruluyor...")
        self.last_day = int(data.day.max())
        self.params = fit(data, self.last_day + 1, self.cfg, init)
        if self.params is None:
            raise ValueError("Kupa modeli için yeterli maç yok.")
        # Uygunluk için durum bilgisi: takımın modelce bilinen maç günleri, adı ve ülkesi
        recent = data.day >= self.last_day - 400
        td: dict = {}
        for hh, aa, dd in zip(data.home[recent], data.away[recent], data.day[recent]):
            td.setdefault(data.teams[hh], []).append(int(dd))
            td.setdefault(data.teams[aa], []).append(int(dd))
        self.team_days = {k: tuple(sorted(v)) for k, v in td.items()}
        names, countries = {}, {}
        for k in data.teams:
            names[k] = k.split("|", 1)[1] if "|" in k else k
            countries[k] = k.split("|", 1)[0] if "|" in k else ""
        if len(cups):
            for side in ("home", "away"):
                for k, nm, ct in zip(cups[f"{side}_key"], cups[side], cups[f"{side}_country"]):
                    names[k], countries[k] = str(nm), str(ct)
        self.team_names, self.team_country = names, countries
        labels = set(domestic["source"].dropna().astype(str)) if "source" in domestic else set()
        if len(cups) and "source" in cups:
            labels |= set(cups["source"].dropna().astype(str))
        self.train_sources = sorted(labels)
        self.data_signature = self.signature(domestic, cups)
        self.state_available_since = dt.datetime.now(dt.timezone.utc)
        self.digest = hashlib.sha256(json.dumps(
            [MODEL_VERSION, self.last_day, self.params.n_matches, round(self.params.mu, 9),
             hashlib.sha256(np.round(np.r_[self.params.attack, self.params.defense], 9).tobytes()).hexdigest(),
             self.calib], default=str).encode()).hexdigest()
        rep = self.report
        rep.trained_at = dt.datetime.now().isoformat(timespec="seconds")
        rep.duration = time.time() - t0
        rep.n_cup_matches = int(len(cups))
        rep.n_domestic = int(len(domestic))
        progress(100, "Kupa modeli hazır.")
        return rep

    def _calibrate_and_measure(self, oos: pd.DataFrame, cups: pd.DataFrame) -> None:
        rep = CupReport()
        self.report = rep
        if oos.empty:
            self.oos = oos
            self.status = {g: DOGRULANMADI for g in VALIDATION_NAMES}
            rep.groups = {g: {"ad": VALIDATION_NAMES[g], "n": 0, "statu": DOGRULANMADI,
                              "neden": "örneklem dışı kupa maçı yok"} for g in VALIDATION_NAMES}
            return
        oos = oos.sort_values(["date", "i"], kind="mergesort").reset_index(drop=True)
        seasons = sorted(oos["season"].unique(), key=lambda s: (str(s)[:4], str(s)))
        lam = np.zeros(len(oos))
        nu = np.zeros(len(oos))
        used = np.zeros(len(oos), dtype=bool)
        first = oos["date"].min()
        for s in seasons:
            cur = (oos["season"] == s).to_numpy()
            prev = (oos["date"] < oos.loc[cur, "date"].min()).to_numpy()
            if prev.sum() < 50 or oos.loc[cur, "date"].min() <= first:
                continue
            th = fit_calibration(oos.loc[prev, "lam"], oos.loc[prev, "nu"], oos.loc[prev, "hg"], oos.loc[prev, "ag"],
                                 oos.loc[prev, "neutral"])
            lam[cur], nu[cur] = calibrate_rates(oos.loc[cur, "lam"], oos.loc[cur, "nu"], th, oos.loc[cur, "neutral"])
            used[cur] = True
        self.calib = fit_calibration(oos["lam"], oos["nu"], oos["hg"], oos["ag"], oos["neutral"])
        rep.calibration = tuple(round(x, 4) for x in self.calib)
        ev = oos[used].copy()
        ev["lam_c"], ev["nu_c"] = lam[used], nu[used]
        P, o25, btts = probs_from_rates(ev["lam_c"], ev["nu_c"]) if len(ev) else (np.zeros((0, 3)), [], [])
        ev[["ph", "pd", "pa"]] = P
        ev["po25"], ev["pbtts"] = o25, btts
        y = np.where(ev["hg"] > ev["ag"], 0, np.where(ev["hg"] == ev["ag"], 1, 2))
        ev["y"] = y
        # Taban: her sezon için önceki sezonların bütün kupa maçlarındaki oranlar
        cd = pd.to_datetime(cups["date"])
        cy = np.where(cups["fthg"] > cups["ftag"], 0, np.where(cups["fthg"] == cups["ftag"], 1, 2))
        co = ((cups["fthg"] + cups["ftag"]) >= 3).to_numpy()
        cb = ((cups["fthg"] > 0) & (cups["ftag"] > 0)).to_numpy()
        base = np.zeros((len(ev), 3))
        bo = np.zeros(len(ev))
        bb = np.zeros(len(ev))
        for s in ev["season"].unique():
            cur = (ev["season"] == s).to_numpy()
            before = (cd < ev.loc[cur, "date"].min()).to_numpy()
            if before.sum() >= 30:
                b = np.bincount(cy[before], minlength=3) / before.sum()
                base[cur] = b
                bo[cur] = co[before].mean()
                bb[cur] = cb[before].mean()
            else:
                base[cur] = DEFAULT_BASE
                bo[cur], bb[cur] = 0.55, 0.5
        ev["b_h"], ev["b_d"], ev["b_a"] = base[:, 0], base[:, 1], base[:, 2]
        ev["b_o25"], ev["b_btts"] = bo, bb
        ev["vgroup"] = [VALIDATION_GROUPS.get(group_of(c), "YURTICI") for c in ev["comp"]]
        self.oos = ev.reset_index(drop=True)
        self.oos_markets = _market_frame(self.oos)
        rep.n_oos = int(len(ev))

        def measure(g: pd.DataFrame) -> dict:
            if g.empty:
                return {"n": 0}
            yy = g["y"].to_numpy()
            Pm = g[["ph", "pd", "pa"]].to_numpy()
            Pb = g[["b_h", "b_d", "b_a"]].to_numpy()
            lm, lb = _ll3(Pm, yy), _ll3(Pb, yy)
            yo = ((g["hg"] + g["ag"]) >= 3).to_numpy().astype(int)
            yb = ((g["hg"] > 0) & (g["ag"] > 0)).to_numpy().astype(int)
            return {"n": int(len(g)), "ll": float(lm.mean()), "ll_taban": float(lb.mean()),
                    "ll_fark_ust95": _bootstrap_upper(lm - lb, g["week"].to_numpy()),
                    "isabet": float(np.mean(Pm.argmax(1) == yy)),
                    "brier": float(np.mean(np.sum((Pm - np.eye(3)[yy]) ** 2, axis=1))),
                    "ll_o25": float(_ll2(g["po25"], yo).mean()), "ll_o25_taban": float(_ll2(g["b_o25"], yo).mean()),
                    "ll_kg": float(_ll2(g["pbtts"], yb).mean()), "ll_kg_taban": float(_ll2(g["b_btts"], yb).mean()),
                    "ilk": str(pd.Timestamp(g["date"].min()).date()), "son": str(pd.Timestamp(g["date"].max()).date())}

        self.status = {}
        for vg, name in VALIDATION_NAMES.items():
            mm = measure(ev[ev["vgroup"] == vg])
            ok = mm.get("n", 0) >= MIN_VALIDATION and mm.get("ll_fark_ust95", 1.0) < 0
            if mm.get("n", 0) < MIN_VALIDATION:
                why = f"örneklem dışı maç sayısı az ({mm.get('n', 0)} < {MIN_VALIDATION})"
            elif not ok:
                why = "model, önceki sezonların sonuç oranlarından anlamlı biçimde iyi değil"
            else:
                why = ""
            self.status[vg] = DOGRULANDI if ok else DOGRULANMADI
            rep.groups[vg] = dict(mm, ad=name, statu=self.status[vg], neden=why)
        rep.competitions = [dict(measure(g), turnuva=c, ad=competition_name(c)) for c, g in ev.groupby("comp")]
        rep.seasons = [dict(measure(g), sezon=s) for s, g in ev.groupby("season")]

    # ------------------------------------------------------------------ tahmin
    def rates(self, home_key: str, away_key: str, home_country: str, away_country: str, date, comp: str,
              neutral: bool) -> dict | None:
        """Kalibre edilmiş gol beklentileri ve açıklama alanları; takımlardan biri modelde yoksa None."""
        if not self.trained:
            return None
        day = int((pd.Timestamp(date).normalize() - EPOCH).days)
        hl = self.league_for(home_key, home_country, day)
        al = self.league_for(away_key, away_country, day)
        grp = group_of(comp)
        raw = self.params.rates(home_key, away_key, hl, al, grp, bool(neutral))
        if raw is None:
            return None
        lam, nu = calibrate_rates([raw[0]], [raw[1]], self.calib, [bool(neutral)])
        hs = self.params.team_strength(home_key, hl)
        as_ = self.params.team_strength(away_key, al)
        return {"lam": float(lam[0]), "nu": float(nu[0]), "lam_raw": raw[0], "nu_raw": raw[1], "home_league": hl,
                "away_league": al, "group": grp, "neutral": bool(neutral), "home_strength": hs,
                "away_strength": as_}

    def team_n(self, key: str, before_day: int, days: int = 365) -> int:
        return sum(1 for d in self.team_days.get(key, ()) if before_day - days <= d < before_day)

    def predict(self, comp: str, home_key: str, away_key: str, home: str, away: str, home_country: str,
                away_country: str, date, time_str: str = "", neutral: bool = False, source: str = "",
                offered_odds: dict | None = None):
        """Tek maç tahmini (``models.engine.MatchPrediction``; ``league`` alanı turnuva kodudur). Takım modelde yoksa
        None."""
        from ..models.engine import MatchPrediction
        from ..models.markets import markets_from_matrix, score_matrix

        r = self.rates(home_key, away_key, home_country, away_country, date, comp, neutral)
        if r is None:
            return None
        P, o25, btts = probs_from_rates([r["lam"]], [r["nu"]])
        p = P[0]
        m = score_matrix(r["lam"], r["nu"], 0.0)
        info = dict(r)
        info.update({"kupa": True, "comp": comp, "home_key": home_key, "away_key": away_key,
                     "home_country": home_country, "away_country": away_country, "dc_lambda": r["lam"],
                     "dc_nu": r["nu"], "validation_group": VALIDATION_GROUPS.get(r["group"], "YURTICI")})
        odds = {k: float(v) for k, v in (offered_odds or {}).items() if v is not None and np.isfinite(v) and v > 1}
        return MatchPrediction(
            league=comp, home=home, away=away, date=pd.Timestamp(date).normalize(), time=time_str or "",
            p_model=p, p_market=None, p_final=p, o25_model=float(o25[0]), o25_market=float("nan"),
            o25_final=float(o25[0]), btts_final=float(btts[0]), matrix=m, markets=markets_from_matrix(m), odds=odds,
            info=info, source=source, state_digest=self.digest)

    def predict_fixtures(self, fixtures: pd.DataFrame | None) -> list:
        out = []
        if fixtures is None or fixtures.empty or not self.trained:
            return out
        for r in fixtures.itertuples(index=False):
            try:
                p = self.predict(r.comp, r.home_key, r.away_key, r.home, r.away, r.home_country, r.away_country,
                                 r.date, r.time or "", bool(r.neutral), r.source)
            except Exception as e:  # tek maçın hatası listeyi durdurmaz
                log.warning("Kupa tahmini hatası %s %s-%s: %s", r.comp, r.home, r.away, e)
                p = None
            if p is not None:
                out.append(p)
        return out

    # ------------------------------------------------------------------ güç tabloları
    def league_table(self) -> pd.DataFrame:
        """Liglerin ortak ölçekteki gücü: ligin son 365 günde maçı olan takımlarının ortalama gücü (hücum + savunma,
        log-gol ölçeği; 0 = bütün takımların ortalaması)."""
        if not self.trained or self.timeline is None:
            return pd.DataFrame()
        rows = []
        cur = {}
        for k in self.params.teams:
            if self.team_n(k, self.last_day + 1) == 0:
                continue
            lg = self.timeline.last_league(k)
            if lg is None:
                lg = outside_league(self.team_country.get(k, ""))
            s = self.params.team_strength(k, lg)
            if s is not None:
                cur.setdefault(lg, []).append(s)
        mu = self.params.mu
        for lg, vals in cur.items():
            if lg not in LEAGUES:
                continue  # ligi veride olmayan ülkelerin tek tük takımları lig gücü değildir
            a = np.array(vals)
            att, dfn = float(a[:, 0].mean()), float(a[:, 1].mean())
            rows.append({"lig": lg, "Lig": LEAGUES[lg].label, "Takım": len(a), "Hücum": att, "Savunma": dfn,
                         "Güç": att + dfn, "Gol farkı": float(np.exp(mu + att) - np.exp(mu - dfn))})
        df = pd.DataFrame(rows)
        return df.sort_values("Güç", ascending=False).reset_index(drop=True) if not df.empty else df

    def team_table(self, limit: int = 50) -> pd.DataFrame:
        """Ortak ölçekte en güçlü takımlar (son 365 günde maçı olan)."""
        if not self.trained:
            return pd.DataFrame()
        rows = []
        for k in self.params.teams:
            n = self.team_n(k, self.last_day + 1)
            if n == 0:
                continue
            lg = (self.timeline.last_league(k) if self.timeline is not None else None) or \
                outside_league(self.team_country.get(k, ""))
            s = self.params.team_strength(k, lg)
            if s is None:
                continue
            rows.append({"anahtar": k, "Takım": self.team_names.get(k, k),
                         "Lig": LEAGUES[lg].label if lg in LEAGUES else f"(ligi veride yok: {lg[2:]})",
                         "Hücum": s[0], "Savunma": s[1], "Güç": s[0] + s[1],
                         "Gol farkı": float(np.exp(self.params.mu + s[0]) - np.exp(self.params.mu - s[1])),
                         "Maç (365 gün)": n})
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        return df.sort_values("Güç", ascending=False).head(limit).reset_index(drop=True)

    def teams_by_league(self) -> dict:
        """Maç Analizi için: lig -> son 365 günde maçı olan takımlar (anahtar, ad); ligi veride olmayanlar ayrı."""
        out: dict = {}
        if not self.trained:
            return out
        for k in self.params.teams:
            if self.team_n(k, self.last_day + 1) == 0:
                continue
            lg = (self.timeline.last_league(k) if self.timeline is not None else None) or \
                outside_league(self.team_country.get(k, ""))
            out.setdefault(lg, []).append((k, self.team_names.get(k, k)))
        return {lg: sorted(v, key=lambda x: x[1]) for lg, v in out.items()}

    # ------------------------------------------------------------------ kayıt
    def save(self, path: Path) -> None:
        from ..models.artifacts import save_artifact

        rep = self.report
        save_artifact(self, path, "kupa-engine", CUP_ENGINE_VERSION, meta={
            "model": MODEL_VERSION, "trained_at": rep.trained_at if rep else None,
            "data_cutoff": str((EPOCH + pd.Timedelta(days=self.last_day)).date()) if self.last_day is not None else None,
            "data_signature": self.data_signature, "validation_rule": VALIDATION_RULE,
            "status": self.status, "sources": self.train_sources,
        })

    last_load_error: str | None = None

    @staticmethod
    def load(path: Path) -> "CupEngine | None":
        from ..models.artifacts import load_artifact

        eng, _man, err = load_artifact(path, "kupa-engine", CUP_ENGINE_VERSION)
        CupEngine.last_load_error = err
        if err or not isinstance(eng, CupEngine):
            if err:
                log.info("Kupa modeli yüklenmedi: %s", err)
            return None
        eng.state_available_since = dt.datetime.now(dt.timezone.utc)
        return eng

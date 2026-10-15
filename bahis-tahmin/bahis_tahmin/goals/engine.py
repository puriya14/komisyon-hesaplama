"""Gol pazarları motoru: eğitim, zaman sıralı iç doğrulama, doğrulama statüsü ve maç tahmini.

Eğitim yalnızca kullanıcı isteğiyle yapılır; tahmin isteği yeniden eğitim tetiklemez.
Doğrulama statüsü kuralı (önceden tanımlı, sürümlü):
  Bir pazar ``VALIDATED_FOR_PAPER_TRADING`` olur ancak motorun kendi son sezonlarındaki zaman
  sıralı testinde (model o maçları görmeden) şunların HEPSİ sağlanırsa:
    1) log-kayıp, lig taban oranından iyi ve %95 blok-bootstrap aralığının üst sınırı < 0,
    2) kalibrasyon eğimi 0.8–1.25 ve beklenen kalibrasyon hatası (ECE) ≤ 0.02,
    3) en az 200 gerçekleşen (pozitif) örnek.
  Aksi halde ``MODEL_NOT_VALIDATED``. Bu statü yalnızca OLASILIK KALİTESİ içindir; gerçek oranlı
  getiri doğrulaması bu pazarlarda geçmiş oran verisi olmadığından yapılamaz.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from ..data.leagues import LEAGUES
from ..timeutil import fmt_istanbul, kickoff_utc
from .features import GOAL_FEATURES, build_goal_features
from .ledger import event_id
from .markets import PRIMARY_YES, SHORT
from .model import FEATURE_VERSION, MODEL_VERSION, GoalModel, ht_rows, usable_rows
from .piyasa import MARKET_SUFFIX, MarketLevel, from_fixture, market_scale, scaled
from .validation import BURN_IN_LAST, data_manifest, evaluate, season_year, walk_forward

log = logging.getLogger(__name__)

GOAL_ENGINE_VERSION = 1
SELECTED_VARIANT = "M10_ipf_kosullu"
VALIDATION_RULE = "dogrulama-kurali-v1: LL üst %95 < 0, eğim 0.8–1.25, ECE ≤ 0.02, pozitif ≥ 200"
MIN_TEAM_MATCHES = 10
HOLDOUT_SEASONS = 3
MIN_TRAIN_ROWS = 500  # ilk yarı skoru geçerli ve takım güçleri kurulmuş en az maç


class GoalDataError(ValueError):
    """Gol pazarları modeli için yeterli (ilk yarı skorlu) veri yok."""


def validated_by_rule(validation: dict, model: str) -> dict[str, bool]:
    """Doğrulama kuralı (``VALIDATION_RULE``) pazar başına."""
    out = {}
    for key in PRIMARY_YES:
        r = validation.get(key, {}).get("modeller", {}).get(model)
        pos = validation.get(key, {}).get("pozitif", 0)
        out[key] = bool(r and r["ll_fark_ust"] < 0 and 0.8 <= r["kal_egim"] <= 1.25 and r["ece"] <= 0.02 and pos >= 200)
    return out


def with_market_odds(feat: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """Özellik tablosuna maçların ortalama 2,5 Üst/Alt oranları (yoksa NaN) eklenir (ORAN-04 doğrulaması)."""
    key = ["league", "date", "home", "away"]
    if not {"o_o25", "o_u25"} <= set(matches.columns):
        return feat.assign(o_o25=np.nan, o_u25=np.nan)
    odds = matches[key + ["o_o25", "o_u25"]].copy()
    odds["date"] = pd.to_datetime(odds["date"]).dt.normalize()
    odds = odds.drop_duplicates(key, keep="last")
    f = feat.drop(columns=[c for c in ("o_o25", "o_u25") if c in feat.columns]).copy()
    f["_d"] = pd.to_datetime(f["date"]).dt.normalize()
    out = f.merge(odds.rename(columns={"date": "_d"}), on=["league", "_d", "home", "away"], how="left",
                  validate="many_to_one")
    out.index = feat.index
    return out.drop(columns="_d")


@dataclass
class GoalPrediction:
    event_id: str
    league: str
    home: str
    away: str
    date: pd.Timestamp
    time: str
    kickoff_utc: dt.datetime | None
    kickoff_text: str
    probs: dict
    intervals: dict
    base_rates: dict
    data_notes: list[str]
    info: dict = field(default_factory=dict)
    # Yapılandırılmış veri kodları (veri uygunluk kontrolü bunları okur; metin aranmaz) ve tahminde kullanılan lig
    # durumunun özeti (uygunluk sonucunun AYNI durumdan geldiğini bağlamak için). Olasılık hesabını etkilemez.
    data_codes: tuple = ()
    state_digest: str = ""
    # Pazar başına doğrulama statüsü bu tahmine özgüyse (kupa maçları: turnuvanın doğrulama grubu; KUPA-GOL-02). None:
    # motorun genel statüsü (``GoalEngine.validated``) geçerlidir.
    validated: dict | None = None

    def p(self, market_key: str) -> float:
        """Seçim olasılığı (Hayır/Alt tarafı için tümleyen)."""
        yes = {"BTTS_BOTH_HALVES": "A", "FT_OVER_3_5": "B", "FT_UNDER_3_5": "B", "FH_OVER_1_5": "C",
               "FH_UNDER_1_5": "C"}
        for prefix, s in yes.items():
            if market_key.startswith(prefix):
                v = float(self.probs.get(s, np.nan))
                return 1.0 - v if market_key.endswith(("_NO", "UNDER_3_5", "UNDER_1_5")) else v
        raise KeyError(market_key)

    def interval(self, market_key: str) -> tuple[float | None, float | None]:
        base = {"A": "BTTS_BOTH_HALVES_YES", "B": "FT_OVER_3_5", "C": "FH_OVER_1_5"}
        for s, key in base.items():
            other = {"A": "BTTS_BOTH_HALVES_NO", "B": "FT_UNDER_3_5", "C": "FH_UNDER_1_5"}[s]
            if market_key in (key, other):
                lo, hi = self.intervals.get(key, (None, None))
                if lo is None:
                    return None, None
                return (lo, hi) if market_key == key else (1 - hi, 1 - lo)
        return None, None


class GoalEngine:
    def __init__(self, variant: str = SELECTED_VARIANT):
        self.version = GOAL_ENGINE_VERSION
        self.variant = variant
        self.model: GoalModel | None = None
        self.states: dict = {}
        self.validation: dict = {}
        self.validated: dict[str, bool] = {}
        self.validation_years: list[int] = []
        self.trained_at = ""
        self.data_cutoff = ""
        self.manifest: dict = {}
        self.league_ht_share: dict[str, float] = {}
        self.state_available_since: dt.datetime | None = None  # eğitim/yükleme anı; köken bilgisi yoksa None
        # ORAN-04: piyasa düzeyli tahminlerin (2,5 Üst/Alt oranı varken) aynı kuralla ayrı doğrulaması. Bu alanlar
        # olmadan kaydedilmiş eski motorlarda piyasa düzeyli tahminler doğrulanmamış sayılır (yeniden eğitim gerekir).
        self.validation_market: dict = {}
        self.validated_market: dict[str, bool] = {}

    @property
    def trained(self) -> bool:
        return self.model is not None

    @property
    def data_sha(self) -> str:
        """Eğitimde kullanılan maç verisinin SHA-256 özeti (veri değişti mi kontrolü için)."""
        return self.manifest.get("sha256", "")

    # ------------------------------------------------------------------ eğit
    def train(self, matches: pd.DataFrame, progress: Callable[[int, str], None] | None = None) -> dict:
        progress = progress or (lambda p, m: None)
        progress(2, "Gol pazarları: yarı bazlı güçler hesaplanıyor...")
        feat, states = build_goal_features(
            matches, progress=lambda f, lg: progress(2 + int(55 * f), f"Gol pazarları: {lg}") if lg else None
        )
        n_ok = int((usable_rows(feat) & ht_rows(feat)).sum())
        if n_ok < MIN_TRAIN_ROWS:
            raise GoalDataError(
                f"Gol pazarları modeli eğitilemedi: ilk yarı skoru geçerli ve takım güçleri hesaplanmış yalnızca "
                f"{n_ok} maç var (en az {MIN_TRAIN_ROWS} gerekli). İlk yarı skoru içeren lig/sezon ekleyin.")
        years = season_year(feat["date"])
        last = int(years.max())
        val_years = [y for y in range(last - HOLDOUT_SEASONS, last + 1) if (years == y).any()]
        progress(60, "Gol pazarları: zaman sıralı doğrulama...")
        feat_odds = with_market_odds(feat, matches)
        pred, _ = walk_forward(feat_odds, val_years, ["M0_taban", self.variant], market=True)
        self.validation = evaluate(pred, [self.variant]) if not pred.empty else {}
        # ORAN-04: aynı modellerin piyasa düzeyli tahminleri (oranı olan maçlar), aynı kuralla
        mv = f"{self.variant}{MARKET_SUFFIX}"
        has_market = not pred.empty and f"{mv}:B" in pred.columns and np.isfinite(pred[f"{mv}:B"]).sum() > 0
        self.validation_market = evaluate(pred, [mv]) if has_market else {}
        self.apply_validation_rule()
        progress(85, "Gol pazarları: nihai model tüm verilerle eğitiliyor...")
        train_rows = feat[years > BURN_IN_LAST] if (years > BURN_IN_LAST).sum() > 2000 else feat
        self.model = GoalModel(self.variant).fit(train_rows)
        self.states = states
        self.validation_years = [int(y) for y in val_years]
        self.trained_at = dt.datetime.now().isoformat(timespec="seconds")
        self.data_cutoff = str(pd.Timestamp(matches["date"].max()).date())
        self.manifest = data_manifest(matches)
        # Durumun (ve içindeki bilginin) en geç bu anda var olduğu kesin (veri uygunluk kontrolünün zaman kuralı)
        self.state_available_since = dt.datetime.now(dt.timezone.utc)
        # Köken bilgisi (olasılık hesabını etkilemez): her lig durumunun kurulduğu (karantinada olmayan) maç kümesi
        from ..eligibility import rows_digest

        ing = feat[(feat["issues"] == "") & feat["fthg"].notna() & feat["ftag"].notna()]
        for lg, st in self.states.items():
            g = ing[ing["league"] == lg]
            st.row_digest = rows_digest(g, "gol")
        ok = (feat["issues"] == "") & feat["hthg"].notna()
        self.league_ht_share = feat.assign(ok=ok).groupby("league")["ok"].mean().to_dict()
        progress(100, "Gol pazarları modeli hazır.")
        return self.validation

    def apply_validation_rule(self) -> None:
        """Doğrulama kuralı: modelin kendi ölçümünden ``validated``, piyasa düzeyli ölçümden ``validated_market``."""
        self.validated = validated_by_rule(self.validation, self.variant)
        self.validated_market = validated_by_rule(self.validation_market, f"{self.variant}{MARKET_SUFFIX}")

    def save(self, path) -> None:
        from ..models.artifacts import save_artifact

        save_artifact(self, path, "goal-engine", GOAL_ENGINE_VERSION, meta={
            "model_version": MODEL_VERSION, "feature_version": FEATURE_VERSION, "variant": self.variant,
            "trained_at": self.trained_at, "data_cutoff": self.data_cutoff, "data_manifest": self.manifest,
            "feature_schema": GOAL_FEATURES, "validation_rule": VALIDATION_RULE,
            "validated": self.validated, "validation_years": self.validation_years,
        })

    @staticmethod
    def load(path) -> tuple["GoalEngine | None", str | None]:
        from ..models.artifacts import load_artifact

        eng, _man, err = load_artifact(path, "goal-engine", GOAL_ENGINE_VERSION)
        if err:
            return None, err
        if not isinstance(eng, GoalEngine):
            return None, "Beklenmeyen model nesnesi."
        # Dosyadan yüklenen durum en geç yükleme anında vardı: dosyadaki değer kullanılmaz, yükleme anıyla değiştirilir
        # (dosya güncellenmez; köken bilgisi uydurulmaz)
        eng.state_available_since = dt.datetime.now(dt.timezone.utc)
        return eng, None

    # ---------------------------------------------------------------- tahmin
    def predict_fixtures(self, fixtures: pd.DataFrame, with_interval: bool = True) -> list[GoalPrediction]:
        if not self.trained or fixtures is None or fixtures.empty:
            return []
        rows, metas, market = [], [], []
        for r in fixtures.itertuples(index=False):
            st = self.states.get(r.league)
            if st is None:
                continue
            date = pd.Timestamp(r.date).normalize()
            snap = st.snapshot_for(date)
            day = int((date - pd.Timestamp("2000-01-01")).days)
            rows.append(snap.features(r.home, r.away, day))
            metas.append((r, snap))
            market.append(from_fixture(r))  # football-data fikstür dosyasında 2,5 Üst/Alt oranı varsa (ORAN-04)
        return self._predict_rows(rows, metas, with_interval, market)

    def predict_match(self, league: str, home: str, away: str, date, time_str: str = "", source: str = "manuel",
                      market: MarketLevel | None = None):
        """``market``: maçın 2,5 Üst/Alt piyasa düzeyi (ORAN-04); verilirse tahmin piyasa düzeyine ölçeklenir."""
        st = self.states.get(league)
        if st is None or not self.trained:
            raise KeyError(f"{league} için gol modeli yok")
        date = pd.Timestamp(date).normalize()
        snap = st.snapshot_for(date)
        day = int((date - pd.Timestamp("2000-01-01")).days)
        row = type("R", (), {"league": league, "home": home, "away": away, "date": date, "time": time_str, "source": source})
        return self._predict_rows([snap.features(home, away, day)], [(row, snap)], True, [market])[0]

    def market_prediction(self, pred: GoalPrediction, market: MarketLevel) -> GoalPrediction:
        """Aynı maçın piyasa düzeyli tahmini (ORAN-04): aynı lig durumundan yeniden hesaplanır; maç saati ve kimlik
        bilgileri önceki tahminden aynen alınır."""
        import dataclasses

        new = self.predict_match(pred.league, pred.home, pred.away, pred.date, pred.time, market=market)
        return dataclasses.replace(pred, probs=new.probs, intervals=new.intervals, info=new.info,
                                   data_notes=new.data_notes, data_codes=new.data_codes,
                                   state_digest=new.state_digest, validated=new.validated)

    def _predict_rows(self, rows, metas, with_interval, market=None) -> list[GoalPrediction]:
        if not rows:
            return []
        X = pd.DataFrame(rows, columns=GOAL_FEATURES)
        X["issues"] = ""
        X["hthg"] = 0.0
        X["htag"] = 0.0
        usable = usable_rows(X)
        # ORAN-04: 2,5 Üst/Alt piyasa olasılığı olan satırlarda takım gücü girdileri tek bir s ile ölçeklenir
        market = list(market or [None] * len(rows))
        scale = np.full(len(X), np.nan)
        idx = np.array([i for i, m in enumerate(market) if m is not None and usable[i]], dtype=int)
        Xm = X
        if len(idx):
            scale[idx] = market_scale(self.model, X.iloc[idx], [market[i].p for i in idx])
            Xm = scaled(X, np.where(np.isfinite(scale), scale, 1.0))
        probs = self.model.predict(Xm)
        ivals = self.model.interval(Xm) if with_interval else None
        from ..eligibility import league_state_digest

        out = []
        for i, (r, snap) in enumerate(metas):
            notes, codes = [], []
            if not usable[i]:
                notes.append("Takım güçleri hesaplanamadı (ilk yarı skoru verisi yok veya yetersiz).")
                codes.append("TAKIM_GUCU_YOK")
            share = self.league_ht_share.get(r.league, 0.0)
            if share < 0.8:
                notes.append(f"Bu ligde geçerli ilk yarı skoru oranı düşük (%{100 * share:.0f}).")
                codes.append("LIG_IY_ORANI_DUSUK")
            for side, team in (("h", r.home), ("a", r.away)):
                n365 = X.loc[i, f"{side}_n365"]
                if not (n365 >= MIN_TEAM_MATCHES):
                    notes.append(f"{team}: son 365 günde bu ligde yalnızca {int(n365 or 0)} maç (lig önbilgisi ağırlıklı).")
                    codes.append("TAKIM_N365_AZ")
            lg = LEAGUES.get(r.league)
            ko = kickoff_utc(r.date, getattr(r, "time", "") or "", getattr(r, "source", ""), lg.country if lg else "")
            p = {k: float(v[i]) for k, v in probs.items() if np.ndim(v) and len(v) > i}
            iv = {}
            if ivals:
                for key in PRIMARY_YES:
                    lo, hi = ivals[key]
                    iv[key] = (float(lo[i]), float(hi[i])) if np.isfinite(lo[i]) else (None, None)
                iv["meta"] = ivals["meta"]
            info = {k: float(X.loc[i, k]) for k in ("h_n365", "a_n365", "l1h", "l1a", "l2h", "l2a", "lh", "la")}
            validated = None
            if np.isfinite(scale[i]):  # piyasa düzeyli tahmin: kendi sürümü ve kendi doğrulama statüsü
                info["piyasa"] = {**market[i].to_dict(), "olcek": float(scale[i])}
                info["model_version"] = f"{MODEL_VERSION}/{self.variant}{MARKET_SUFFIX}"
                validated = {k: bool(v) for k, v in (getattr(self, "validated_market", None) or {}).items()}
                validated = {k: validated.get(k, False) for k in PRIMARY_YES}
            out.append(GoalPrediction(
                event_id=event_id(r.league, r.date, r.home, r.away), league=r.league, home=r.home, away=r.away,
                date=pd.Timestamp(r.date), time=getattr(r, "time", "") or "", kickoff_utc=ko,
                kickoff_text=fmt_istanbul(ko, r.date), probs=p, intervals=iv,
                base_rates={"A": float(X.loc[i, "bA"]), "B": float(X.loc[i, "bB"]), "C": float(X.loc[i, "bC"])},
                data_notes=notes, info=info,
                data_codes=tuple(sorted(set(codes))), state_digest=league_state_digest(self.states.get(r.league)),
                validated=validated,
            ))
        return out

    def status_text(self, market_key: str) -> str:
        return "VALIDATED_FOR_PAPER_TRADING" if self.validated.get(market_key) else "MODEL_NOT_VALIDATED"


def short(key: str) -> str:
    return SHORT.get(key, key)

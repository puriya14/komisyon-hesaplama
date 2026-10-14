"""Kupa maçları için veri uygunluğu (KUPA-01).

Lig maçlarındaki ortak kural (``eligibility``) kupa maçına iki takımın AYRI ligleri üzerinden uygulanır; sonuç aynı
``Eligibility`` nesnesidir (gösterim ve karar denetimleri değişmez). Denetimler:

* Zaman ve model: maç günü bilgi kesiminden önceyse ``MAC_GECMISTE``; kupa modeli yoksa ``MODEL_YOK``; takım modelin
  durumunda yoksa ``TAKIM_DURUMDA_YOK``; modelin bildiği son maçtan sonra depoda bu takımın tamamlanmış maçı varsa
  ``DURUM_DEPODAN_GERIDE``; model değerlendirme gününde/sonrasında oynanmış maç içeriyor ve durum o andan önce yoksa
  ``DURUM_KARAR_ANINDAN_SONRA``.
* Takım verisi: son 365 günde lig + kupa maçı 5'ten azsa ``KUPA_TAKIM_VERISI_YOK`` (tahmin yok), 10'dan azsa
  ``TAKIM_GECMISI_YETERSIZ``; takımın ligi veride yoksa ``KUPA_TAKIM_LIGI_VERIDE_YOK``.
* Takımın kendi ligi: lig maçlarıyla aynı kaynak takvimi denetimleri (eksik maç, sonucu belirsiz maç, kapsam)
  ``EligibilityContext``'in tek takım için çalıştırılmasıyla.
* Kupa takvimi (ESPN): takımın kupa maçlarından kaynakta tamamlanmış görünüp depoda olmayan ``DEPODA_EKSIK_MAC``,
  sonucu bilinmeyen ``KAYNAK_DURUMU_BELIRSIZ`` / ``SON_SONUC_BEKLENIYOR``; turnuvanın takvimi yoksa
  ``KUPA_TAKVIMI_YOK``. ESPN fikstürünün takım kimlikleri takvimde yeniden bulunmalıdır
  (``TAKIM_ESLESMESI_DOGRULANAMADI``).
* Haklar: lig ve kupa satırlarının kaynakları ile modelin eğitim kaynakları (``RightsStatus``).
* Model doğrulama statüsü: turnuvanın doğrulama grubu doğrulanmadıysa ``KUPA_MODEL_DOGRULANMADI``.

Güncellik kanıtı (``VERIFIED_CURRENT``) ancak iki takımın lig takvimi kanıtı ve turnuvanın takvimi varsa oluşur; ligi
veride olmayan takımda oluşmaz (sıkı modda bu maçların tahmini gösterilmez).
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from ..eligibility import (
    PAIR_DAY_TOLERANCE,
    PENDING_GRACE_DAYS,
    PREDICTION_CODE_MAP,
    EligibilityContext,
    FixtureVerdict,
    _digest,
    _finalize,
    _restamp,
    day_number,
    day_to_date,
    info_cutoff,
    rights_from_registry,
)
from .motor import DOGRULANDI, MODEL_VERSION, key_of
from .turnuvalar import COMPETITIONS, VALIDATION_GROUPS

MARKETS = ("1X2",)
MIN_HARD = 5  # bundan az maç: tahmin yok
MIN_SOFT = 10  # bundan az maç: bahis adayı değil (lig kuralıyla aynı eşik)
LOOKBACK = 365


class CupContext:
    """Veri deposu (lig + kupa) + kupa motoru + lig uygunluk bağlamı (kapsam takvimleri) + haklar."""

    def __init__(self, store, engine, dctx: EligibilityContext | None, consent: dict | None = None,
                 declarations: dict | None = None, mode: str = "siki", verified=None):
        from ..data.provenance import verified_labels
        from .veri import read_calendars

        self.store, self.engine, self.dctx, self.mode = store, engine, dctx, mode
        dom = store.matches
        cups = getattr(store, "cup_matches", None)
        cups = cups if cups is not None else pd.DataFrame(columns=["source"])
        days: dict = {}
        if dom is not None and not dom.empty:
            dd = ((pd.to_datetime(dom["date"]) - pd.Timestamp("2000-01-01")).dt.days).to_numpy(dtype=int)
            for side in ("home", "away"):
                for k, d in zip((key_of(lg, t) for lg, t in zip(dom["league"], dom[side])), dd):
                    days.setdefault(k, []).append(int(d))
        if not cups.empty:
            cd = ((pd.to_datetime(cups["date"]) - pd.Timestamp("2000-01-01")).dt.days).to_numpy(dtype=int)
            for side in ("home_key", "away_key"):
                for k, d in zip(cups[side].astype(str), cd):
                    days.setdefault(k, []).append(int(d))
        self.team_days = {k: np.array(sorted(v), dtype=int) for k, v in days.items()}
        labels = set()
        if dom is not None and "source" in dom:
            labels |= set(dom["source"].dropna().astype(str))
        if not cups.empty:
            labels |= set(cups["source"].dropna().astype(str))
        self.labels = sorted(labels)
        train = set(getattr(engine, "train_sources", None) or []) if engine is not None else set()
        self.train = sorted(train)
        ver = verified if verified is not None else verified_labels(store)
        self.rights = rights_from_registry(set(self.labels) | train, consent, ver, declarations)
        self.calendars = read_calendars(getattr(store, "raw_dir", "."))
        self.sources = ((getattr(store, "meta", None) or {}).get("kupa") or {}).get("kaynaklar") or {}
        self.cup_index: dict = {}
        if not cups.empty:
            for c, h, a, d in zip(cups["comp"], cups["home_key"], cups["away_key"], pd.to_datetime(cups["date"])):
                self.cup_index.setdefault((c, h, a), []).append(day_number(d))
        self._cache: dict = {}
        self.fingerprint = _digest([getattr(engine, "digest", ""), len(dom) if dom is not None else 0, len(cups),
                                    sorted(self.calendars), self.labels, mode,
                                    getattr(dctx, "fingerprint", "") if dctx is not None else ""])

    # ------------------------------------------------------------------ yardımcılar
    def _live(self, as_of: dt.datetime) -> bool:
        av = getattr(self.engine, "state_available_since", None)
        return av is not None and as_of >= av

    def _team_domestic(self, league: str, team: str, as_of: dt.datetime, cut_day: int, codes: list, detail: dict,
                       base: dict) -> bool:
        """Takımın kendi liginde kaynak takvimi denetimleri (lig maçlarındaki kuralın tek takımlık hâli). Döner:
        güncellik kanıtı (doğrulanmış takvim aralığı) var mı."""
        ctx = self.dctx
        if ctx is None:
            codes.append("KAYNAK_KAPSAMI_YOK")
            return False
        g_all = ctx.league_matches(league)
        g = g_all[g_all["day"] < cut_day]
        covs = ctx.coverages.get(league, ())
        usable = ctx.coverages_at(league, as_of)
        evidence = [c for c in usable if c.verified_windows]
        if not covs:
            codes.append("KAYNAK_KAPSAMI_YOK")
        elif not usable:
            codes.append("KAYNAK_KARAR_ANINDAN_SONRA")
        elif not evidence:
            codes.append("KAYNAK_KAPSAMI_KISMI")
        near = g_all[g_all["day"] < cut_day + PAIR_DAY_TOLERANCE]
        partial = [c for c in usable if not c.verified_windows]
        sub = {"data_scope": {}}
        if partial:
            EligibilityContext._missing_in_partial(team, None, near[near["ingest"]], near, partial, cut_day, codes,
                                                   detail)
        if evidence:
            EligibilityContext._check_against_source(team, None, near[near["ingest"]], near, evidence, cut_day, codes,
                                                     detail, sub, PENDING_GRACE_DAYS if self.mode == "standart" else 0)
            EligibilityContext._store_vs_source(team, None, g, evidence, cut_day, codes, detail)
            if not any(team in (m.home, m.away) for c in evidence for m in c.matches):
                codes.append("KAYNAK_ESLESME_BELIRSIZ")
            elif not EligibilityContext._window_covered(team, g, usable, evidence, cut_day):
                codes.append("KAYNAK_ARALIK_DISI")
        for c in usable:
            base["data_scope"]["kapsam_kanitlari"].append({
                "lig": league, "kaynak": c.source, "sezon": c.season, "alinma": c.retrieved_at.isoformat(),
                "tam": c.complete,
                "gecmis_aralik_kaniti": [[str(day_to_date(s)), str(day_to_date(e))] for s, e in c.verified_windows],
                "ozet": c.sha256[:16]})
        if "kontrol" in sub["data_scope"]:
            detail["kontrol"] = sub["data_scope"]["kontrol"]
        return bool(evidence)

    def _team_cups(self, key: str, as_of: dt.datetime, cut_day: int, codes: list, detail: dict) -> None:
        """Takımın kupa maçları: ESPN kupa takviminde tamamlanmış görünüp depoda olmayan veya sonucu bilinmeyen maç."""
        from ..data.espn import NOT_PLAYED

        missing, unknown, pending = [], [], []
        for (comp, _season), (at, recs) in self.calendars.items():
            if at > as_of:
                continue
            for r in recs:
                if key not in (r.get("home_key"), r.get("away_key")):
                    continue
                try:
                    md = day_number(r["date"])
                except (KeyError, TypeError, ValueError):
                    continue
                if md >= cut_day or r.get("status") in NOT_PLAYED:
                    continue
                have = self.cup_index.get((comp, r.get("home_key"), r.get("away_key")), ())
                if any(abs(d - md) <= PAIR_DAY_TOLERANCE for d in have):
                    continue
                if "ft" in r:
                    missing.append(str(r["date"]))
                elif self.mode == "standart" and md >= cut_day - PENDING_GRACE_DAYS:
                    pending.append(str(r["date"]))
                else:
                    unknown.append(str(r["date"]))
        if missing:
            codes.append("DEPODA_EKSIK_MAC")
            detail["kupa_depoda_eksik"] = missing[-5:]
        if unknown:
            codes.append("KAYNAK_DURUMU_BELIRSIZ")
            detail["kupa_sonucu_belirsiz"] = unknown[-5:]
        if pending:
            codes.append("SON_SONUC_BEKLENIYOR")
            detail["kupa_sonucu_bekleniyor"] = pending[-5:]

    def _fixture_identity(self, comp: str, season: str, source: str, provider_id: str, home_key: str,
                          away_key: str) -> bool:
        """Fikstürün takım kimlikleri kaynağında yeniden kurulabiliyor mu (eski kayıt yeni eşleyiciden geçmiş sayılmaz).
        Maç Analizi'nde (``manuel``) takımlar modelin takım listesinden seçilir: kimlik seçimin kendisidir."""
        if source == "manuel":
            return True
        if source == "espn":
            hit = self.calendars.get((comp, season))
            if hit is None:
                return False
            eid = str(provider_id).split(":", 1)[-1]
            return any(str(r.get("id")) == eid and r.get("home_key") == home_key and r.get("away_key") == away_key
                       for r in hit[1])
        if source == "openfootball-kupa":
            return self.sources.get(f"{comp} {season}") == "openfootball"
        return False

    # ------------------------------------------------------------------ değerlendirme
    def evaluate(self, *, comp: str, season: str, date, home: str, away: str, home_key: str, away_key: str,
                 home_country: str, away_country: str, as_of: dt.datetime, source: str = "", provider_id: str = "",
                 prediction=None, markets=MARKETS, prediction_codes=None) -> dict:
        """Pazar başına uygunluk. 1X2: ``prediction`` (``MatchPrediction``) verilirse olasılıkların geçerliliği
        denetlenir. Gol pazarları (KUPA-GOL-02): ``markets=GOAL_MARKETS`` ve ``prediction_codes`` (``goals.service.
        prediction_codes``; None ise gerekli alanlar denetlenmemiş sayılır ve tahmin uygun olmaz)."""
        from ..goals.ledger import event_id as make_event_id

        markets = tuple(markets)
        cut = info_cutoff(as_of)
        pcodes = None if prediction_codes is None else tuple(sorted(prediction_codes))
        if prediction is not None and pcodes is None:
            ok = bool(np.all(np.isfinite(np.asarray(prediction.p_final, dtype=float))))
            pcodes = () if ok else ("OLASILIK_GECERSIZ",)
        key = (self.fingerprint, comp, str(season), str(pd.Timestamp(date).date()), home_key, away_key, source,
               provider_id, cut, self._live(as_of), pcodes is None, pcodes, markets)
        hit = self._cache.get(key)
        if hit is None:
            hit = self._evaluate(comp, str(season), date, home, away, home_key, away_key, home_country, away_country,
                                 as_of, cut, source, provider_id, pcodes, make_event_id(comp, pd.Timestamp(date).date(),
                                                                                         home, away), markets)
            self._cache[key] = hit
        stamp = as_of.astimezone(dt.timezone.utc).isoformat()
        return {mk: _restamp(e, stamp) for mk, e in hit.items()}

    def _evaluate(self, comp, season, date, home, away, home_key, away_key, home_country, away_country, as_of, cut,
                  source, provider_id, pcodes, eid, markets=MARKETS):
        eng = self.engine
        cut_day = day_number(cut)
        fx_day = day_number(date)
        codes: list[str] = []
        teams_detail: dict = {}
        last_days = []
        for k in (home_key, away_key):
            arr = self.team_days.get(k)
            if arr is not None and len(arr):
                before = arr[arr < cut_day]
                if len(before):
                    last_days.append(int(before.max()))
        base = dict(candidate_id=eid, canonical_id=True, league=comp, home=home, away=away,
                    match_date=str(pd.Timestamp(date).date()), evaluated_at="", info_cutoff=str(cut),
                    team_mapping="ESLESTI",
                    data_cutoff=str(day_to_date(max(last_days))) if last_days else None,
                    data_scope={"kupa": True, "turnuva": comp, "sezon": season, "kaynaklar": self.labels,
                                "kapsam_kanitlari": [], "takimlar": teams_detail},
                    state_scope={"tur": "kupa", "model": MODEL_VERSION,
                                 "model_veri_kesimi": (str(day_to_date(eng.last_day)) if eng is not None
                                                       and eng.last_day is not None else None),
                                 "egitim_kaynaklari": self.train, "durum_ozeti": getattr(eng, "digest", "") or ""},
                    source_use=self.rights.summary(set(self.labels) | set(self.train)))
        if fx_day < cut_day:
            codes.append("MAC_GECMISTE")
        codes += self.rights.codes(self.labels, self.train, "tahmin")
        if home_key == away_key or not self._fixture_identity(comp, season, source, provider_id, home_key, away_key):
            codes.append("TAKIM_ESLESMESI_DOGRULANAMADI")
            base["team_mapping"] = "DOGRULANAMADI"
        model_codes: list[str] = []  # yalnızca 1X2: maç sonucu modelinin doğrulama statüsü
        if eng is None or not getattr(eng, "trained", False):
            codes.append("MODEL_YOK")
        else:
            if eng.last_day is not None and eng.last_day >= cut_day and not self._live(as_of):
                codes.append("DURUM_KARAR_ANINDAN_SONRA")
            vg = VALIDATION_GROUPS.get(COMPETITIONS[comp].group if comp in COMPETITIONS else "C", "YURTICI")
            if eng.status.get(vg) != DOGRULANDI:
                model_codes.append("KUPA_MODEL_DOGRULANMADI")
        evidence_all = True
        for k, ctry, nm in ((home_key, home_country, home), (away_key, away_country, away)):
            td: dict = {}
            teams_detail[nm] = td
            arr = self.team_days.get(k, np.zeros(0, dtype=int))
            n365 = int(((arr >= cut_day - LOOKBACK) & (arr < cut_day)).sum())
            td["mac_365"] = n365
            if n365 < MIN_HARD:
                codes.append("KUPA_TAKIM_VERISI_YOK")
            elif n365 < MIN_SOFT:
                codes.append("TAKIM_GECMISI_YETERSIZ")
            league = eng.league_for(k, ctry, fx_day) if eng is not None and getattr(eng, "trained", False) else None
            td["lig"] = league
            if eng is not None and getattr(eng, "trained", False):
                if k not in eng.params.team_index:
                    codes.append("TAKIM_DURUMDA_YOK")
                known = set(eng.team_days.get(k, ()))
                newer = [int(d) for d in arr if d < cut_day and (eng.last_day is None or d > eng.last_day)
                         and d not in known]
                if newer:
                    codes.append("DURUM_DEPODAN_GERIDE")
                    td["modelde_olmayan_mac"] = [str(day_to_date(d)) for d in newer[-5:]]
            if league is None or str(league).startswith("X:") or "|" not in k or k.startswith(("ESPN|", "ESPN-AD|")):
                codes.append("KUPA_TAKIM_LIGI_VERIDE_YOK")
                evidence_all = False
            else:
                team = k.split("|", 1)[1]
                if not self._team_domestic(str(league), team, as_of, cut_day, codes, td, base):
                    evidence_all = False
            self._team_cups(k, as_of, cut_day, codes, td)
        if (comp, season) not in self.calendars:
            codes.append("KUPA_TAKVIMI_YOK")
            evidence_all = False
        per_market = {}
        for mk in markets:
            if mk == "1X2":
                per_market[mk] = tuple(pcodes or ()) + tuple(model_codes)
                continue
            # Gol pazarları: motorun yapılandırılmış kodları ("KOD" veya "KOD:PAZAR") lig gol pazarlarıyla aynı eşleme;
            # pazarın model doğrulaması karar motorunda denetlenir (MODEL_NOT_VALIDATED)
            req = []
            for pc in pcodes or ():
                code, _, only = pc.partition(":")
                if only and only != mk:
                    continue
                hit = PREDICTION_CODE_MAP.get(code)
                if hit:
                    req.append(hit[0])
            per_market[mk] = tuple(req)
        return _finalize(base, codes, markets, per_market, evidence_checked=evidence_all,
                         required_checked=pcodes is not None, mode=self.mode)


def build_cup_context(store, engine, dctx, settings) -> CupContext:
    return CupContext(store, engine, dctx, settings.source_consent, settings.declarations(), settings.veri_denetimi)


def gate_cup_prediction(cctx: CupContext | None, pred, row, as_of: dt.datetime):
    """Kupa tahminine uygunluk sonucunu bağlar (``pred.eligibility``)."""
    from ..eligibility import not_evaluated

    if cctx is None:
        e = not_evaluated(pred.event_id, "1X2", as_of, canonical=True)
    else:
        e = cctx.evaluate(comp=row.comp, season=row.season, date=row.date, home=row.home, away=row.away,
                          home_key=row.home_key, away_key=row.away_key, home_country=row.home_country,
                          away_country=row.away_country, as_of=as_of, source=row.source,
                          provider_id=row.provider_id, prediction=pred)["1X2"]
    pred.eligibility = e
    return e


def gated_cup_goal_predictions(engine, cctx: CupContext | None, fixtures: pd.DataFrame | None, as_of: dt.datetime,
                               with_interval: bool = True) -> list:
    """Kupa maçları için gol pazarları (KUPA-GOL-02): her fikstüre (tahmin + pazar başına uygunluk). Tahmini
    üretilemeyen maç sessizce düşürülmez; nedenli "tahmin yok" sonucu olarak döner (``FixtureVerdict``)."""
    from ..eligibility import GOAL_MARKETS, not_evaluated
    from ..goals.ledger import event_id
    from ..goals.service import prediction_codes

    out = []
    if fixtures is None or fixtures.empty:
        return out
    for row in fixtures.itertuples(index=False):
        p = None
        if engine is not None and getattr(engine, "trained", False) and getattr(engine, "goal", None) is not None:
            try:
                p = engine.predict_goals(row.comp, row.home_key, row.away_key, row.home, row.away, row.home_country,
                                         row.away_country, row.date, row.time or "", bool(row.neutral), row.source,
                                         with_interval=with_interval)
            except Exception:  # tek maçın hatası listeyi durdurmaz; nedenli "tahmin yok" olarak kalır
                p = None
        eid = event_id(row.comp, pd.Timestamp(row.date).date(), row.home, row.away)
        if cctx is None:
            by = {mk: not_evaluated(eid, mk, as_of, canonical=True) for mk in GOAL_MARKETS}
        else:
            by = cctx.evaluate(comp=row.comp, season=row.season, date=row.date, home=row.home, away=row.away,
                               home_key=row.home_key, away_key=row.away_key, home_country=row.home_country,
                               away_country=row.away_country, as_of=as_of, source=row.source,
                               provider_id=row.provider_id, markets=GOAL_MARKETS,
                               prediction_codes=prediction_codes(p) if p is not None else None)
        out.append(FixtureVerdict(league=row.comp, date=pd.Timestamp(row.date), time=row.time or "", home=row.home,
                                  away=row.away, candidate_id=eid, canonical_id=True, by_market=by, prediction=p))
    return out


def gated_cup_predictions(engine, cctx: CupContext | None, fixtures: pd.DataFrame | None, as_of: dt.datetime):
    """Toplu kupa tahmini: (uygunluğu bağlanmış tahminler, tahmini olmayan fikstürlerin nedenli sonuçları)."""
    from ..eligibility import not_evaluated
    from ..goals.ledger import event_id

    preds, missing = [], []
    if fixtures is None or fixtures.empty:
        return preds, missing
    for row in fixtures.itertuples(index=False):
        p = None
        if engine is not None and getattr(engine, "trained", False):
            try:
                p = engine.predict(row.comp, row.home_key, row.away_key, row.home, row.away, row.home_country,
                                   row.away_country, row.date, row.time or "", bool(row.neutral), row.source)
            except Exception:  # tek maçın hatası listeyi durdurmaz; nedenli "tahmin yok" olarak kalır
                p = None
        if p is not None:
            gate_cup_prediction(cctx, p, row, as_of)
            preds.append(p)
            continue
        eid = event_id(row.comp, pd.Timestamp(row.date).date(), row.home, row.away)
        if cctx is None:
            by = {"1X2": not_evaluated(eid, "1X2", as_of, canonical=True)}
        else:
            by = cctx.evaluate(comp=row.comp, season=row.season, date=row.date, home=row.home, away=row.away,
                               home_key=row.home_key, away_key=row.away_key, home_country=row.home_country,
                               away_country=row.away_country, as_of=as_of, source=row.source,
                               provider_id=row.provider_id, prediction=None)
        missing.append(FixtureVerdict(league=row.comp, date=pd.Timestamp(row.date), time=row.time or "",
                                      home=row.home, away=row.away, candidate_id=eid, canonical_id=True, by_market=by))
    return preds, missing

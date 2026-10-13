"""Uygulama çekirdeği (Qt'den bağımsız).

Masaüstü arayüzü (``ui.controller.AppController``) ve web arayüzü (``web``) aynı kuralları buradan kullanır: kaynak
onayı ve kişisel kullanım beyanı, güncelleme + eğitim (hak kapısı dahil), uygunluk bağlamı ve tahmin tablosu. Böylece
iki arayüz arasında veri uygunluğu veya eğitim kuralı ayrışmaz.

``AppCore``: web arayüzünün durum nesnesi (Qt sinyali/iş parçacığı yok; arka plan işini çağıran yönetir).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
import threading
from pathlib import Path
from typing import Callable

import pandas as pd

from .config import Settings, app_home
from .data.provenance import verified_labels
from .data.store import DataStore
from .eligibility import training_rights_codes
from .goals.engine import GoalDataError, GoalEngine
from .goals.validation import data_manifest
from .models.engine import PredictionEngine

log = logging.getLogger(__name__)

ENGINE_FILE = "engine.joblib"
GOAL_ENGINE_FILE = "goal_engine.joblib"
LEDGER_FILE = "gol_pazarlari.sqlite"
SEQ_DIR = "dizi_arastirma"
STALE_HOURS = 6.0
DECLARATION_HINT = ("Kişisel (ticari olmayan) kullanım beyanını Veri sayfasındaki 'Kaynak koşulları ve onaylar...' "
                    "penceresinden verebilirsiniz.")

Progress = Callable[[int, str], None]


# ------------------------------------------------------------------ modeller


def train_goal(matches: pd.DataFrame, home, progress) -> tuple[GoalEngine | None, str | None]:
    """Gol pazarları modelini eğitip kaydeder. Veri yetersizse (ör. ilk yarı skoru yok) hata metni döner."""
    goal = GoalEngine()
    try:
        goal.train(matches, progress=progress)
    except GoalDataError as e:
        return None, str(e)
    goal.save(Path(home) / GOAL_ENGINE_FILE)
    return goal, None


def load_saved(home, progress: Progress | None = None):
    """Kayıtlı veri deposu, maç sonucu modeli ve gol modeli. Döner: (store, engine, goal, goal_hata)."""
    progress = progress or (lambda p, m: None)
    home = Path(home)
    progress(10, "Kayıtlı veriler yükleniyor...")
    store = DataStore(home)
    store.load()
    progress(50, "Kayıtlı model yükleniyor...")
    engine = PredictionEngine.load(home / ENGINE_FILE)
    progress(75, "Gol pazarları modeli yükleniyor...")
    goal, gerr = GoalEngine.load(home / GOAL_ENGINE_FILE)
    return store, engine, goal, gerr


def training_block_codes(store: DataStore, settings: Settings, matches: pd.DataFrame | None = None) -> list[str]:
    """Gerçek veriyle eğitimin hak engelleri (S3-GATE-02; onay kutusu bu kontrolü aşamaz). Boşsa eğitilebilir."""
    m = store.matches if matches is None else matches
    return training_rights_codes(m, settings.source_consent, verified_labels(store), settings.declarations())


def needs_training(store: DataStore, engine: PredictionEngine | None, settings: Settings) -> bool:
    if not store.has_data:
        return False
    if engine is None:
        return True
    return PredictionEngine.signature(store.matches, settings.margin_method) != engine.data_signature


def data_age_hours(store: DataStore) -> float:
    ts = store.meta.get("updated_at")
    if not ts:
        return float("inf")
    try:
        return (dt.datetime.now() - dt.datetime.fromisoformat(ts)).total_seconds() / 3600.0
    except ValueError:
        return float("inf")


def update_work(home, settings: Settings, old_engine, old_goal, force: bool, progress: Progress,
                allowed: set[str] | None = None):
    """Verileri günceller; veri değiştiyse ve kullanım hakkı doğrulandıysa modelleri eğitir. ``allowed``: işin
    başlatıldığı andaki izinli kaynaklar (verilmezse ayarlardan).

    Döner: (store, engine, report, (goal, goal_hata)). ``goal`` None ve hata yoksa gol modeli değişmedi."""
    s = settings
    allowed = s.allowed_sources() if allowed is None else allowed
    home = Path(home)
    store = DataStore(home)
    store.load()

    def p1(p, m):
        progress(int(p * 0.3), m)

    report = store.update(
        s.leagues, s.years_back, progress=p1, force=force,
        use_mirror_fallback=s.use_mirror_fallback, fixture_days=s.fixture_days,
        allowed=allowed, profile=s.data_profile,
    )
    engine = old_engine
    sig = PredictionEngine.signature(store.matches, s.margin_method)
    blocked = training_block_codes(store, s) if store.has_data else []
    if blocked:  # hak kapsamı doğrulanmayan gerçek veriyle eğitim yapılmaz (S3-GATE-02)
        report.warnings.append("Model eğitimi yapılmadı: veri kaynağının kullanım kapsamı doğrulanmadı ("
                               + ", ".join(blocked) + "). " + declaration_hint(s, store.matches))
    elif store.has_data and (engine is None or engine.data_signature != sig):
        engine = PredictionEngine()

        def p2(p, m):
            progress(30 + int(p * 0.7), m)

        engine.train(store.matches, progress=p2, margin_method=s.margin_method)
        progress(70, "Model kaydediliyor...")
        engine.save(home / ENGINE_FILE)
    goal = gerr = None
    if store.has_data and not blocked and (old_goal is None
                                           or old_goal.data_sha != data_manifest(store.matches)["sha256"]):
        goal, gerr = train_goal(store.matches, home, lambda p, m: progress(70 + int(p * 0.29), m))
    return store, engine, report, (goal, gerr)


def retrain_work(matches: pd.DataFrame, settings: Settings, home, progress: Progress):
    """Maç sonucu ve gol modelini yeniden eğitir (hak kapısı çağırandan önce denetlenir). Döner: (engine, goal,
    goal_hata)."""
    engine = PredictionEngine()
    engine.train(matches, progress=lambda p, m: progress(int(p * 0.7), m), margin_method=settings.margin_method)
    engine.save(Path(home) / ENGINE_FILE)
    goal, gerr = train_goal(matches, home, lambda p, m: progress(70 + int(p * 0.29), m))
    return engine, goal, gerr


# ------------------------------------------------------------------ onay ve beyan


def needs_consent(settings: Settings) -> bool:
    """Onay penceresi gösterilmeli mi? Geçmiş maç verisi sağlayan hiçbir kaynağın kullanım koşulları onaylanmamışsa
    veya kullanıcı onay penceresinin güncel sürümünü (VERI-01: kişisel kullanım beyanı) henüz kaydetmediyse. GitHub
    veri profilinde football-data kullanılmadığı için yalnızca GitHub yedek veri setinin onayı sayılır."""
    from .data.github_kaynak import PROFILE_GITHUB
    from .data.source_registry import CONSENT_SCHEMA

    keys = {"github-mirror"} if settings.data_profile == PROFILE_GITHUB else {"football-data", "github-mirror"}
    return not (keys & settings.allowed_sources()) or settings.onay_surumu < CONSENT_SCHEMA


def consent_review_needed(settings: Settings) -> bool:
    """Onay var ama onay penceresinin güncel sürümü (kişisel kullanım beyanı) henüz kaydedilmedi."""
    from .data.source_registry import CONSENT_SCHEMA

    return bool(settings.source_consent) and settings.onay_surumu < CONSENT_SCHEMA


def declaration_hint(settings: Settings, matches: pd.DataFrame) -> str:
    """Eğitim/tahmin hak engeli için kullanıcıya gösterilecek somut yol (beyan gereken kaynakların adlarıyla)."""
    from .data.source_registry import SOURCES, missing_declarations

    miss = missing_declarations(set(matches["source"].dropna().astype(str)), settings.source_consent,
                                settings.kisisel_kullanim) if "source" in matches else []
    names = ", ".join(SOURCES[k].name for k in miss)
    return (f"Kişisel (ticari olmayan) kullanım beyanı gereken kaynak: {names}. " if names else "") + DECLARATION_HINT


def _now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def record_consent(settings: Settings, keys) -> None:
    now = _now_iso()
    for k in keys:
        settings.source_consent[k] = now
    settings.save()


def revoke_consent(settings: Settings, key: str) -> None:
    settings.source_consent.pop(key, None)
    settings.kisisel_kullanim.pop(key, None)  # onay olmadan beyan da geçmez
    settings.save()


def record_declaration(settings: Settings, keys) -> None:
    """Kişisel (ticari olmayan) kullanım beyanı: yalnızca beyan verilebilen ve indirme onayı olan kaynaklar."""
    from .data.source_registry import DECLARABLE

    now = _now_iso()
    for k in keys:
        if k in DECLARABLE and k in settings.source_consent:
            settings.kisisel_kullanim[k] = now
    settings.save()


def revoke_declaration(settings: Settings, key: str) -> None:
    settings.kisisel_kullanim.pop(key, None)
    settings.save()


def mark_consent_reviewed(settings: Settings) -> None:
    """Kullanıcı onay penceresinin güncel sürümünü kaydetti (beyan verse de vermese de bir daha sorulmaz)."""
    from .data.source_registry import CONSENT_SCHEMA

    settings.onay_surumu = CONSENT_SCHEMA
    settings.save()


def consent_keys() -> list[str]:
    """Onay penceresinde gösterilen (onay gerektiren, uygulanmış) kaynaklar."""
    from .data.source_registry import IMPLEMENTED, SOURCES

    return [k for k in IMPLEMENTED if SOURCES[k].requires_consent]


def apply_consent(settings: Settings, chosen, declared, keys=None) -> bool:
    """Onay penceresindeki seçimleri uygular (beyan yalnızca indirme onayı da seçiliyse geçerlidir). Beyanlar
    değiştiyse True (tahminler yeni haklarla yeniden değerlendirilmeli)."""
    keys = list(consent_keys() if keys is None else keys)
    chosen = set(chosen)
    declared = set(declared) & chosen
    before = set(settings.declarations())
    for key in keys:
        if key in chosen and key not in settings.source_consent:
            record_consent(settings, [key])
        elif key not in chosen and key in settings.source_consent:
            revoke_consent(settings, key)
    for key in keys:
        if key in declared and key not in settings.kisisel_kullanim:
            record_declaration(settings, [key])
        elif key not in declared and key in settings.kisisel_kullanim:
            revoke_declaration(settings, key)
    mark_consent_reviewed(settings)
    return set(settings.declarations()) != before


# ------------------------------------------------------------------ uygunluk ve tahminler


def istanbul_today(now: dt.datetime) -> dt.date:
    """Bilgi kesimiyle aynı takvim: İstanbul günü."""
    from .timeutil import ISTANBUL

    return now.astimezone(ISTANBUL).date()


def context_key(store: DataStore, engine, settings: Settings, today: dt.date) -> tuple:
    """Uygunluk bağlamı önbellek anahtarı: veri deposu, motor durumu, kaynak dosyaları, onaylar, beyanlar, veri
    denetimi modu ve gün değişince değişir (eski "uygun" sonucu yeni veri/durum/kapsamla kullanılmaz)."""
    raw = store.raw_dir / "openfootball"
    try:
        files = tuple(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in raw.rglob("*.json"))) \
            if raw.exists() else ()
    except OSError:
        files = ()
    m = store.matches
    return (id(engine), getattr(engine, "state_available_since", None), id(m), len(m), store.meta.get("updated_at"),
            files, tuple(sorted(settings.source_consent)), tuple(sorted(settings.declarations())),
            settings.veri_denetimi, today)


def build_eligibility_context(store: DataStore, engine, settings: Settings, today: dt.date):
    from .eligibility import build_context

    return build_context(store, engine, settings.source_consent, today=today, declarations=settings.declarations(),
                         mode=settings.veri_denetimi)


def prediction_rows(predictions, unpredicted, settings: Settings, now: dt.datetime) -> pd.DataFrame:
    """Tahmin listesini tabloya uygun DataFrame'e çevirir.

    Veri uygunluğu doğrulanmayan maçlarda olasılıklar gösterilmez (boş; sıfır değil), değer önerisi yoktur ve durum
    metinle yazılır. Tahmini hiç üretilemeyen fikstürler (modelde olmayan lig, eşleşmeyen takım) de nedenleriyle
    listelenir (``_i`` = -1)."""
    from .eligibility import display_label

    rows = []
    s = settings
    nan = float("nan")
    for i, p in enumerate(predictions):
        codes = p.display_codes(now)  # gün/kimlik/model durumu eşleşmesi dahil
        ok = not codes
        label, text = display_label(p.eligibility, codes)
        best = p.best_value(s, now=now) if ok else None
        xg = p.exp_goals
        pick_idx = int(p.p_final.argmax())
        rows.append({
            "_i": i,
            "date": p.date,
            "when": p.date.strftime("%d.%m.%Y") + (f" {p.time}" if p.time else ""),
            "league": p.league,
            "home": p.home,
            "away": p.away,
            "p1": float(p.p_final[0]) if ok else nan,
            "px": float(p.p_final[1]) if ok else nan,
            "p2": float(p.p_final[2]) if ok else nan,
            "pick": ("1", "X", "2")[pick_idx] if ok else "-",
            "o25": float(p.markets["O2.5"]) if ok else nan,
            "btts": float(p.markets["BTTS_Y"]) if ok else nan,
            "xg": f"{xg[0]:.1f} - {xg[1]:.1f}" if ok else "-",
            "odds": " / ".join(f"{p.odds[k]:.2f}" for k in ("1", "X", "2") if k in p.odds) or "-",
            "value": f"{best['label']} @{best['odds']:.2f} ({100 * best['ev']:+.0f}%)" if best else "",
            "value_ev": float(best["ev"]) if best else nan,
            "has_market": p.p_market is not None,
            "veri": label,
            "veri_neden": text,
        })
    for v in unpredicted:
        label, text = display_label(v.first(), v.display_codes("1X2", now))
        rows.append({
            "_i": -1, "date": v.date, "when": v.date.strftime("%d.%m.%Y") + (f" {v.time}" if v.time else ""),
            "league": v.league, "home": v.home, "away": v.away + ("" if v.canonical_id else " (eşleşmedi)"),
            "p1": nan, "px": nan, "p2": nan, "pick": "-", "o25": nan, "btts": nan, "xg": "-", "odds": "-",
            "value": "", "value_ev": nan, "has_market": False, "veri": label, "veri_neden": text,
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ web arayüzünün durum nesnesi


class AppCore:
    """Web arayüzünün uygulama durumu (masaüstündeki ``AppController``'ın Qt'siz karşılığı).

    Durum alanları ``lock`` ile korunur; uzun işler (güncelleme, eğitim) çağıranın arka plan iş parçacığında
    ``*_work`` işlevleriyle yapılır ve sonuç ``apply_*`` ile kilit altında uygulanır."""

    def __init__(self, home=None):
        self.home = Path(home) if home is not None else app_home()
        self.settings = Settings.load()
        self.store = DataStore(self.home)
        self.engine: PredictionEngine | None = None
        self.goal_engine: GoalEngine | None = None
        self.goal_load_error: str | None = None
        self.predictions: list = []
        self.match_unpredicted: list = []
        self.goal_verdicts: list = []
        self.last_report_text = ""
        self.loaded = False
        self.clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.timezone.utc)
        self.lock = threading.RLock()
        self._ctx_cache: dict = {}
        self._match_day: dt.date | None = None
        self._goal_day: dt.date | None = None

    # ----------------------------------------------------------- zaman
    def now(self) -> dt.datetime:
        return self.clock()

    def today(self) -> dt.date:
        return istanbul_today(self.now())

    # ----------------------------------------------------------- durum
    def apply_loaded(self, res) -> None:
        with self.lock:
            self.store, self.engine, self.goal_engine, self.goal_load_error = res
            self.loaded = True
            self._ctx_cache.clear()

    def apply_update(self, res) -> None:
        store, engine, report, (goal, gerr) = res
        with self.lock:
            self.store = store
            self.engine = engine
            if goal is not None or gerr:
                self.goal_engine = goal
                self.goal_load_error = gerr
            self.last_report_text = report.summary()
            self.loaded = True

    def needs_consent(self) -> bool:
        return needs_consent(self.settings)

    def needs_training(self) -> bool:
        return needs_training(self.store, self.engine, self.settings)

    def training_blocked(self) -> list[str]:
        return training_block_codes(self.store, self.settings) if self.store.has_data else []

    # ----------------------------------------------------------- uygunluk
    def eligibility_context(self, engine):
        """Ortak veri uygunluk bağlamı (önbellekli). Kurulamazsa None: tahminler uygun sayılmaz."""
        key = context_key(self.store, engine, self.settings, self.today())
        with self.lock:
            ctx = self._ctx_cache.get(key)
        if ctx is not None:
            return ctx
        try:
            ctx = build_eligibility_context(self.store, engine, self.settings, self.today())
        except Exception:
            log.exception("Veri uygunluk bağlamı kurulamadı")
            return None
        with self.lock:
            if len(self._ctx_cache) >= 2:  # gol ve 1X2 motoru için birer güncel bağlam
                self._ctx_cache.pop(next(iter(self._ctx_cache)))
            self._ctx_cache[key] = ctx
        return ctx

    def refresh_predictions(self) -> str | None:
        """1X2 tahminlerini ortak uygunluk kontrolünden geçirerek yeniler. Hata olursa metni döner."""
        from .eligibility import gated_match_predictions

        err = None
        unpredicted = []
        if self.store.fixtures.empty and self.store.unmatched_fixtures.empty:
            preds = []
        else:
            # Model yoksa da fikstürler nedenli "tahmin yok" satırı olarak listelenir (sessizce düşürülmez)
            eng = self.engine if (self.engine is not None and self.engine.trained) else None
            try:
                ctx = self.eligibility_context(eng)
                preds, unpredicted = gated_match_predictions(eng, ctx, self.store.fixtures, self.now(),
                                                             self.settings.odds_type, self.store.unmatched_fixtures)
            except Exception as e:
                log.exception("Tahminler hesaplanamadı")
                preds, err = [], f"Tahminler hesaplanamadı: {e}"
        with self.lock:
            self.predictions, self.match_unpredicted = preds, unpredicted
            self._match_day = self.today()
        return err

    def compute_goal_verdicts(self, progress: Progress | None = None) -> list:
        """Gol pazarları: veri uygunluğu, tahminler ve belirsizlik aralıkları (yavaş olabilir; arka planda)."""
        from .goals.service import gated_goal_predictions

        eng = self.goal_engine
        fixtures, unmatched = self.store.fixtures, self.store.unmatched_fixtures
        if eng is None or not eng.trained or (fixtures.empty and unmatched.empty):
            return []
        if progress:
            progress(10, "Gol pazarları: veri uygunluğu, tahminler ve belirsizlik aralıkları hesaplanıyor...")
        ctx = self.eligibility_context(eng)
        return gated_goal_predictions(eng, ctx, fixtures, self.now(), unmatched=unmatched)

    def set_goal_verdicts(self, verdicts) -> None:
        with self.lock:
            self.goal_verdicts = list(verdicts)
            self._goal_day = self.today()

    def match_day_stale(self) -> bool:
        return self._match_day is not None and self._match_day != self.today()

    def goal_day_stale(self) -> bool:
        return self._goal_day is not None and self._goal_day != self.today()

    def prediction_frame(self) -> pd.DataFrame:
        with self.lock:
            preds, unpred = list(self.predictions), list(self.match_unpredicted)
        return prediction_rows(preds, unpred, self.settings, self.now())

    # ----------------------------------------------------------- sanal takip
    @contextlib.contextmanager
    def ledger(self, create: bool = True):
        """Sanal takip günlüğü; her kullanımda açılıp kapanır (sqlite bağlantısı iş parçacıkları arasında
        paylaşılmaz). ``create=False``: dosya henüz yoksa oluşturmadan None verir (salt okuma)."""
        from .goals.ledger import Ledger

        if not create and not (self.home / LEDGER_FILE).exists():
            yield None
            return
        led = Ledger(self.home / LEDGER_FILE)
        try:
            yield led
        finally:
            led.close()

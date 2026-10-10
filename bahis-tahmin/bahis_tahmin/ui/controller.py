"""Uygulama durumu ve arka plan işleri (veri güncelleme, model eğitimi)."""

from __future__ import annotations

import datetime as dt
import logging
import traceback
from typing import Callable

import pandas as pd
from PySide6.QtCore import QObject, QThread, Signal

from ..config import Settings, app_home
from ..data.store import DataStore
from ..goals.engine import GoalDataError, GoalEngine, GoalPrediction
from ..goals.ledger import Ledger
from ..goals.validation import data_manifest
from ..models.engine import MatchPrediction, PredictionEngine

log = logging.getLogger(__name__)

ENGINE_FILE = "engine.joblib"
GOAL_ENGINE_FILE = "goal_engine.joblib"
LEDGER_FILE = "gol_pazarlari.sqlite"
STALE_HOURS = 6.0


class Task(QThread):
    progress = Signal(int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self) -> None:
        try:
            res = self.fn(lambda p, m: self.progress.emit(int(p), str(m)))
        except Exception as e:  # arayüze hata olarak ilet
            log.exception("Arka plan işi başarısız")
            self.failed.emit(f"{e}\n\n{traceback.format_exc(limit=4)}")
            return
        self.done.emit(res)


def _train_goal(matches: pd.DataFrame, home, progress) -> tuple[GoalEngine | None, str | None]:
    """Gol pazarları modelini eğitip kaydeder. Veri yetersizse (ör. ilk yarı skoru yok) hata metni döner."""
    goal = GoalEngine()
    try:
        goal.train(matches, progress=progress)
    except GoalDataError as e:
        return None, str(e)
    goal.save(home / GOAL_ENGINE_FILE)
    return goal, None


class AppController(QObject):
    dataChanged = Signal()
    modelChanged = Signal()
    predictionsChanged = Signal()
    goalModelChanged = Signal()
    goalPredictionsChanged = Signal()
    ledgerChanged = Signal()
    settingsChanged = Signal()
    busyChanged = Signal(bool)
    progress = Signal(int, str)
    message = Signal(str, str)  # tür (popup/status/warn/error), metin

    def __init__(self, parent=None):
        super().__init__(parent)
        self.home = app_home()
        self.settings = Settings.load()
        self.store = DataStore(self.home)
        self.engine: PredictionEngine | None = None
        self.predictions: list[MatchPrediction] = []
        self.goal_engine: GoalEngine | None = None
        self.goal_load_error: str | None = None
        self.goal_predictions: list[GoalPrediction] = []
        self._ledger: Ledger | None = None
        self.last_report_text = ""
        self._task: Task | None = None
        self._queue: list[Callable[[], None]] = []

    # ------------------------------------------------------------ helpers
    @property
    def busy(self) -> bool:
        return self._task is not None

    def _run(self, fn: Callable, on_done: Callable[[object], None], label: str) -> bool:
        if self._task is not None:
            self.message.emit("warn", "Başka bir işlem sürüyor, lütfen bekleyin.")
            return False
        task = Task(fn, self)
        task.progress.connect(self.progress)
        task.done.connect(lambda res: self._finish(task, on_done, res))
        task.failed.connect(lambda err: self._fail(task, err))
        self._task = task
        self.busyChanged.emit(True)
        self.progress.emit(0, label)
        task.start()
        return True

    def _finish(self, task: Task, on_done, res) -> None:
        task.wait()
        self._task = None
        try:
            on_done(res)
        finally:
            # on_done yeni bir arka plan işi başlatmış olabilir (ör. gol tahminleri): durumu doğru yansıt
            self.busyChanged.emit(self.busy)
            if not self.busy:
                self.progress.emit(100, "Hazır")
            if self._queue and not self.busy:
                self._queue.pop(0)()

    def _fail(self, task: Task, err: str) -> None:
        task.wait()
        self._task = None
        self._queue.clear()
        self.busyChanged.emit(False)
        self.progress.emit(0, "Hata")
        self.message.emit("error", err)

    def wait(self) -> None:
        """(Testler için) çalışan işin bitmesini bekle."""
        if self._task is not None:
            self._task.wait()

    # ------------------------------------------------------------ startup
    def load_initial(self) -> None:
        home = self.home

        def work(progress):
            progress(10, "Kayıtlı veriler yükleniyor...")
            store = DataStore(home)
            store.load()
            progress(50, "Kayıtlı model yükleniyor...")
            engine = PredictionEngine.load(home / ENGINE_FILE)
            progress(75, "Gol pazarları modeli yükleniyor...")
            goal, gerr = GoalEngine.load(home / GOAL_ENGINE_FILE)
            return store, engine, goal, gerr

        def done(res):
            store, engine, goal, gerr = res
            self.store = store
            self.engine = engine
            self.goal_engine = goal
            self.goal_load_error = gerr
            self.dataChanged.emit()
            self.modelChanged.emit()
            self.goalModelChanged.emit()
            self.refresh_predictions()
            self.refresh_goal_predictions()
            # Açılışta eğitim yapılmaz; yalnızca kullanıcı açıkça otomatik güncellemeyi seçtiyse güncellenir
            if (self.settings.auto_update_on_start and self.store.has_data and not self.needs_consent()
                    and self.data_age_hours() >= STALE_HOURS):
                self._queue.append(lambda: self.update_and_train(quiet=True))
            elif self.store.has_data and (self.engine is None or self.needs_training()):
                self.message.emit("status", "Model verilerle uyumlu değil; 'Modeli Yeniden Eğit' ile güncelleyin.")

        self._run(work, done, "Yükleniyor...")

    def data_age_hours(self) -> float:
        ts = self.store.meta.get("updated_at")
        if not ts:
            return float("inf")
        try:
            return (dt.datetime.now() - dt.datetime.fromisoformat(ts)).total_seconds() / 3600.0
        except ValueError:
            return float("inf")

    def needs_training(self) -> bool:
        if not self.store.has_data:
            return False
        if self.engine is None:
            return True
        sig = PredictionEngine.signature(self.store.matches, self.settings.margin_method)
        return sig != self.engine.data_signature

    # ------------------------------------------------------------ actions
    def needs_consent(self) -> bool:
        """Geçmiş maç verisi sağlayan hiçbir kaynağın kullanım koşulları onaylanmamış mı?"""
        return not ({"football-data", "github-mirror"} & self.settings.allowed_sources())

    def record_consent(self, keys: list[str]) -> None:
        now = dt.datetime.now().isoformat(timespec="seconds")
        for k in keys:
            self.settings.source_consent[k] = now
        self.settings.save()
        self.settingsChanged.emit()

    def revoke_consent(self, key: str) -> None:
        self.settings.source_consent.pop(key, None)
        self.settings.save()
        self.settingsChanged.emit()

    def update_and_train(self, force: bool = False, quiet: bool = False) -> bool:
        s = self.settings
        home = self.home
        old_engine = self.engine
        old_goal = self.goal_engine
        allowed = s.allowed_sources()
        if self.needs_consent():
            self.message.emit("consent", "Veri kaynaklarının kullanım koşullarını onaylamanız gerekiyor.")
            return False

        def work(progress):
            store = DataStore(home)
            store.load()

            def p1(p, m):
                progress(int(p * 0.3), m)

            report = store.update(
                s.leagues, s.years_back, progress=p1, force=force,
                use_mirror_fallback=s.use_mirror_fallback, fixture_days=s.fixture_days,
                allowed=allowed,
            )
            engine = old_engine
            sig = PredictionEngine.signature(store.matches, s.margin_method)
            if store.has_data and (engine is None or engine.data_signature != sig):
                engine = PredictionEngine()

                def p2(p, m):
                    progress(30 + int(p * 0.7), m)

                engine.train(store.matches, progress=p2, margin_method=s.margin_method)
                progress(70, "Model kaydediliyor...")
                engine.save(home / ENGINE_FILE)
            goal = gerr = None
            if store.has_data and (old_goal is None or old_goal.data_sha != data_manifest(store.matches)["sha256"]):
                goal, gerr = _train_goal(store.matches, home, lambda p, m: progress(70 + int(p * 0.29), m))
            return store, engine, report, (goal, gerr)

        def done(res):
            store, engine, report, (goal, gerr) = res
            self.store = store
            self.engine = engine
            if goal is not None or gerr:
                self.goal_engine = goal
                self.goal_load_error = gerr
                self.goalModelChanged.emit()
            self.last_report_text = report.summary()
            self.dataChanged.emit()
            self.modelChanged.emit()
            self.refresh_predictions()
            self.refresh_goal_predictions()
            self.message.emit("status" if quiet else "popup", report.summary())

        return self._run(work, done, "Veriler güncelleniyor...")

    def retrain(self) -> bool:
        if not self.store.has_data:
            self.message.emit("warn", "Önce verileri indirin.")
            return False
        matches = self.store.matches
        method = self.settings.margin_method
        home = self.home

        def work(progress):
            engine = PredictionEngine()
            engine.train(matches, progress=lambda p, m: progress(int(p * 0.7), m), margin_method=method)
            engine.save(home / ENGINE_FILE)
            goal, gerr = _train_goal(matches, home, lambda p, m: progress(70 + int(p * 0.29), m))
            return engine, goal, gerr

        def done(res):
            self.engine, self.goal_engine, self.goal_load_error = res
            self.modelChanged.emit()
            self.goalModelChanged.emit()
            self.refresh_predictions()
            self.refresh_goal_predictions()

        return self._run(work, done, "Model eğitiliyor...")

    def train_goal_engine(self) -> bool:
        """Yalnızca gol pazarları modelini eğitir (maç sonucu modeline dokunmaz)."""
        if not self.store.has_data:
            self.message.emit("warn", "Önce verileri indirin.")
            return False
        matches = self.store.matches
        home = self.home

        def work(progress):
            return _train_goal(matches, home, progress)

        def done(res):
            self.goal_engine, self.goal_load_error = res
            self.goalModelChanged.emit()
            self.refresh_goal_predictions()
            self.message.emit("status", self.goal_load_error or "Gol pazarları modeli eğitildi.")

        return self._run(work, done, "Gol pazarları modeli eğitiliyor...")

    def refresh_predictions(self) -> None:
        if self.engine is None or not self.engine.trained or self.store.fixtures.empty:
            self.predictions = []
        else:
            try:
                self.predictions = self.engine.predict_fixtures(self.store.fixtures, self.settings.odds_type)
            except Exception as e:
                log.exception("Tahminler hesaplanamadı")
                self.predictions = []
                self.message.emit("error", f"Tahminler hesaplanamadı: {e}")
        self.predictionsChanged.emit()

    @property
    def ledger(self) -> Ledger:
        """Sanal takip günlüğü (dosya yalnızca ilk kullanımda oluşturulur)."""
        if self._ledger is None:
            self._ledger = Ledger(self.home / LEDGER_FILE)
        return self._ledger

    def ledger_if_exists(self) -> Ledger | None:
        """Okuma amaçlı: sanal takip dosyası henüz yoksa oluşturmadan None döner."""
        if self._ledger is None and not (self.home / LEDGER_FILE).exists():
            return None
        return self.ledger

    def refresh_goal_predictions(self) -> None:
        eng = self.goal_engine
        if eng is None or not eng.trained or self.store.fixtures.empty:
            self.goal_predictions = []
            self.goalPredictionsChanged.emit()
            return
        fixtures = self.store.fixtures

        def work(progress):
            progress(10, "Gol pazarları tahminleri ve belirsizlik aralıkları hesaplanıyor...")
            return eng.predict_fixtures(fixtures, with_interval=True)

        def done(preds):
            self.goal_predictions = preds
            self.goalPredictionsChanged.emit()

        if self.busy:  # başka iş bitince sessizce sıraya al
            self._queue.append(self.refresh_goal_predictions)
            return
        self._run(work, done, "Gol pazarları tahminleri...")

    def save_settings(self, s: Settings) -> None:
        leagues_changed = (s.leagues != self.settings.leagues) or (s.years_back != self.settings.years_back)
        method_changed = s.margin_method != self.settings.margin_method
        self.settings = s
        s.save()
        self.settingsChanged.emit()
        self.refresh_predictions()
        if leagues_changed:
            self.message.emit("popup", "Lig/sezon seçimi değişti. Yeni verileri almak için 'Verileri Güncelle' butonunu kullanın.")
        elif method_changed and self.store.has_data:
            self.message.emit("status", "Marj yöntemi değişti; model yeniden eğitiliyor.")
            self.retrain()
        else:
            self.message.emit("status", "Ayarlar kaydedildi.")

    # ------------------------------------------------------------ queries
    def prediction_frame(self) -> pd.DataFrame:
        """Tahmin listesini tabloya uygun DataFrame'e çevirir."""
        rows = []
        s = self.settings
        for i, p in enumerate(self.predictions):
            best = p.best_value(s)
            xg = p.exp_goals
            pick_idx = int(p.p_final.argmax())
            rows.append({
                "_i": i,
                "date": p.date,
                "when": p.date.strftime("%d.%m.%Y") + (f" {p.time}" if p.time else ""),
                "league": p.league,
                "home": p.home,
                "away": p.away,
                "p1": float(p.p_final[0]),
                "px": float(p.p_final[1]),
                "p2": float(p.p_final[2]),
                "pick": ("1", "X", "2")[pick_idx],
                "o25": float(p.markets["O2.5"]),
                "btts": float(p.markets["BTTS_Y"]),
                "xg": f"{xg[0]:.1f} - {xg[1]:.1f}",
                "odds": " / ".join(f"{p.odds[k]:.2f}" for k in ("1", "X", "2") if k in p.odds) or "-",
                "value": f"{best['label']} @{best['odds']:.2f} ({100 * best['ev']:+.0f}%)" if best else "",
                "value_ev": float(best["ev"]) if best else float("nan"),
                "has_market": p.p_market is not None,
            })
        return pd.DataFrame(rows)

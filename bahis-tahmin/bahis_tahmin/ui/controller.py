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
from ..models.engine import MatchPrediction, PredictionEngine

log = logging.getLogger(__name__)

ENGINE_FILE = "engine.joblib"
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


class AppController(QObject):
    dataChanged = Signal()
    modelChanged = Signal()
    predictionsChanged = Signal()
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
            self.busyChanged.emit(False)
            self.progress.emit(100, "Hazır")
            if self._queue:
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
            return store, engine

        def done(res):
            store, engine = res
            self.store = store
            self.engine = engine
            self.dataChanged.emit()
            self.modelChanged.emit()
            self.refresh_predictions()
            if self.settings.auto_update_on_start and self.store.has_data and self.data_age_hours() >= STALE_HOURS:
                self._queue.append(lambda: self.update_and_train(quiet=True))
            elif self.store.has_data and (self.engine is None or self.needs_training()):
                self._queue.append(self.retrain)

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
    def update_and_train(self, force: bool = False, quiet: bool = False) -> bool:
        s = self.settings
        home = self.home
        old_engine = self.engine

        def work(progress):
            store = DataStore(home)
            store.load()

            def p1(p, m):
                progress(int(p * 0.3), m)

            report = store.update(
                s.leagues, s.years_back, progress=p1, force=force,
                use_mirror_fallback=s.use_mirror_fallback, fixture_days=s.fixture_days,
            )
            engine = old_engine
            sig = PredictionEngine.signature(store.matches, s.margin_method)
            if store.has_data and (engine is None or engine.data_signature != sig):
                engine = PredictionEngine()

                def p2(p, m):
                    progress(30 + int(p * 0.7), m)

                engine.train(store.matches, progress=p2, margin_method=s.margin_method)
                progress(99, "Model kaydediliyor...")
                engine.save(home / ENGINE_FILE)
            return store, engine, report

        def done(res):
            store, engine, report = res
            self.store = store
            self.engine = engine
            self.last_report_text = report.summary()
            self.dataChanged.emit()
            self.modelChanged.emit()
            self.refresh_predictions()
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
            engine.train(matches, progress=progress, margin_method=method)
            progress(99, "Model kaydediliyor...")
            engine.save(home / ENGINE_FILE)
            return engine

        def done(engine):
            self.engine = engine
            self.modelChanged.emit()
            self.refresh_predictions()

        return self._run(work, done, "Model eğitiliyor...")

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

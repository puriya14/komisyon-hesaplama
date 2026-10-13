"""Uygulama durumu ve arka plan işleri (veri güncelleme, model eğitimi)."""

from __future__ import annotations

import datetime as dt
import logging
import traceback
from typing import Callable

import pandas as pd
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .. import core
from ..config import Settings, app_home
from ..core import (  # noqa: F401 (eski içe aktarma yolları için de burada)
    DECLARATION_HINT,
    ENGINE_FILE,
    GOAL_ENGINE_FILE,
    LEDGER_FILE,
    SEQ_DIR,
    STALE_HOURS,
)
from ..data.store import DataStore
from ..goals.engine import GoalEngine, GoalPrediction
from ..goals.ledger import Ledger
from ..models.engine import MatchPrediction, PredictionEngine

log = logging.getLogger(__name__)


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


def load_sequence_results(home) -> dict | None:
    """Uygulama klasöründeki son dizi araştırması sonuçları (``dizi_arastirma/son_sonuclar.json``); yoksa None."""
    import json

    path = home / SEQ_DIR / "son_sonuclar.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.exception("Dizi araştırması sonuçları okunamadı")
        return None


def _train_goal(matches: pd.DataFrame, home, progress) -> tuple[GoalEngine | None, str | None]:
    """Gol pazarları modelini eğitip kaydeder (``core.train_goal``)."""
    return core.train_goal(matches, home, progress)


class AppController(QObject):
    dataChanged = Signal()
    modelChanged = Signal()
    predictionsChanged = Signal()
    goalModelChanged = Signal()
    goalPredictionsChanged = Signal()
    ledgerChanged = Signal()
    sequenceChanged = Signal()
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
        # Ortak veri uygunluk kontrolünden geçmiş sonuçlar (S3-GATE-01): her fikstür için tahmin (varsa) + pazar başına
        # uygunluk. Modelde olmayan lig ve eşleşmeyen takım da nedenli sonuç olarak burada yer alır.
        self.goal_verdicts: list = []
        self.match_unpredicted: list = []  # 1X2: tahmini olmayan fikstürlerin nedenli sonuçları
        self._ctx_cache: dict = {}
        # Tek zaman kaynağı: uygunluk değerlendirmesi ve karar anı aynı saatten alınır (testlerde sabitlenebilir)
        self.clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.timezone.utc)
        self._match_day: dt.date | None = None  # uygunluğun son değerlendirildiği İstanbul günü (1X2 / gol)
        self._goal_day: dt.date | None = None
        # Uygulama açıkken gün değişirse uygunluk yeniden değerlendirilir (önceki günün sonucu gösterilmez)
        self._day_timer = QTimer(self)
        self._day_timer.setInterval(60_000)
        self._day_timer.timeout.connect(self.check_day)
        self._day_timer.start()
        self._ledger: Ledger | None = None
        self.seq_table: pd.DataFrame | None = None  # dizi araştırması: takım-maç tablosu (istek üzerine kurulur)
        self.seq_results: dict | None = None  # son araştırma çalıştırmasının sonuçları (varsa)
        self.seq_error: str | None = None  # takım-maç tablosu kurulamadıysa kullanıcıya gösterilecek neden
        self.prematch: dict | None = None  # maç öncesi benzer diziler (yaklaşan maç satırları + atomlar)
        self.prematch_error: str | None = None
        self.last_report_text = ""
        self._task: Task | None = None
        self._queue: list[Callable[[], None]] = []

    # ------------------------------------------------------------ helpers
    @property
    def busy(self) -> bool:
        return self._task is not None

    @property
    def busy_critical(self) -> bool:
        """Kapanışta kullanıcıya sorulması gereken (yazma yapan) bir iş sürüyor mu?"""
        return self._task is not None and getattr(self._task, "critical", True)

    def _run(self, fn: Callable, on_done: Callable[[object], None], label: str, critical: bool = True) -> bool:
        if self._task is not None:
            self.message.emit("warn", "Başka bir işlem sürüyor, lütfen bekleyin.")
            return False
        task = Task(fn, self)
        task.critical = critical  # False: salt okuma (kapanışta onay sorulmaz, yalnızca beklenir)
        task.progress.connect(self.progress)
        task.done.connect(lambda res: self._finish(task, on_done, res))
        task.failed.connect(lambda err: self._fail(task, err))
        self._task = task
        self.busyChanged.emit(True)
        self.progress.emit(0, label)
        task.start()
        return True

    def run_job(self, fn: Callable, on_done: Callable[[object], None], label: str, critical: bool = True) -> bool:
        """Sayfalar için aynı tek görev yöneticisi: ``fn(progress)`` arka planda, ``on_done(sonuç)`` ana iş
        parçacığında. Başka iş sürüyorsa başlatmaz (False). ``critical``: yazan iş (kapanışta onay sorulur)."""
        return self._run(fn, on_done, label, critical=critical)

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
            return core.load_saved(home, progress)

        def done(res):
            store, engine, goal, gerr = res
            self.store = store
            self.seq_table = None  # veri değişti: dizi tablosu yeniden kurulacak
            self.seq_error = None
            self.prematch = None
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
            elif self.settings.auto_update_on_start and self.store.has_data and self.consent_review_needed():
                self.message.emit("status", "Otomatik güncelleme yapılmadı: kaynak onaylarınızı (kişisel kullanım "
                                            "beyanı) bir kez gözden geçirin — 'Verileri Güncelle'.")
            elif self.store.has_data and (self.engine is None or self.needs_training()):
                self.message.emit("status", "Model verilerle uyumlu değil; 'Modeli Yeniden Eğit' ile güncelleyin.")

        self._run(work, done, "Yükleniyor...")

    def data_age_hours(self) -> float:
        return core.data_age_hours(self.store)

    def needs_training(self) -> bool:
        return core.needs_training(self.store, self.engine, self.settings)

    # ------------------------------------------------------------ actions
    def needs_consent(self) -> bool:
        """Onay penceresi gösterilmeli mi? (``core.needs_consent``)"""
        return core.needs_consent(self.settings)

    def consent_review_needed(self) -> bool:
        """Onay var ama onay penceresinin güncel sürümü (kişisel kullanım beyanı) henüz kaydedilmedi."""
        return core.consent_review_needed(self.settings)

    def declaration_hint(self, matches=None) -> str:
        """Eğitim/tahmin hak engeli için kullanıcıya gösterilecek somut yol (beyan gereken kaynakların adlarıyla)."""
        return core.declaration_hint(self.settings, self.store.matches if matches is None else matches)

    def record_consent(self, keys: list[str]) -> None:
        core.record_consent(self.settings, keys)
        self.settingsChanged.emit()

    def revoke_consent(self, key: str) -> None:
        core.revoke_consent(self.settings, key)
        self.settingsChanged.emit()

    def record_declaration(self, keys: list[str]) -> None:
        """Kişisel (ticari olmayan) kullanım beyanı: yalnızca beyan verilebilen ve indirme onayı olan kaynaklar."""
        core.record_declaration(self.settings, keys)
        self.settingsChanged.emit()

    def revoke_declaration(self, key: str) -> None:
        core.revoke_declaration(self.settings, key)
        self.settingsChanged.emit()

    def declarations_changed(self, added: bool) -> None:
        """Beyan değişti: tahminler yeni haklarla yeniden değerlendirilir. Yeni beyan verildiyse ve veri olduğu halde
        model yoksa/eskiyse model eğitilir (eğitim yine hak denetiminden geçer)."""
        self.refresh_predictions()
        if added and self.store.has_data:
            # Koşul çalışma anında yeniden denetlenir: o sırada süren bir güncelleme modeli zaten eğitmiş olabilir
            self._queue.append(self._retrain_if_needed)
        self.refresh_goal_predictions()
        if not self.busy and self._queue:
            self._queue.pop(0)()

    def _retrain_if_needed(self) -> None:
        if self.store.has_data and (self.engine is None or self.needs_training()):
            self.retrain()

    def mark_consent_reviewed(self) -> None:
        """Kullanıcı onay penceresinin güncel sürümünü kaydetti (beyan verse de vermese de bir daha sorulmaz)."""
        core.mark_consent_reviewed(self.settings)
        self.settingsChanged.emit()

    # ------------------------------------------------------------ GitHub arşivi (S5-GITHUB-01)
    def open_archive(self, on_done: Callable[[object], None], home=None) -> bool:
        """Arşiv klasörünü SALT OKUNUR açar: ağ isteği ve yazma yoktur; köken yeniden doğrulanır."""
        from .. import archive

        return self._run(lambda progress: archive.load(home), on_done, "GitHub arşivi okunuyor...", critical=False)

    def build_archive(self, on_done: Callable[[object], None], consent=(), home=None) -> bool:
        """Yalnızca kullanıcı isteğiyle: seçili GitHub depolarını sabit commit'ten AYRI arşiv klasörüne alır. Kullanıcı
        veri deposu, model, pilot ve defter değişmez; eğitim yapılmaz. ``consent``: bu çalıştırmaya özgü erişim onayı
        (kaydedilmez, analiz hakkı vermez)."""
        from .. import archive

        allowed = tuple(set(consent) | set(self.settings.source_consent))

        def work(progress):
            archive.build(home, consent=allowed, progress=progress)
            return archive.load(home)

        return self._run(work, on_done, "GitHub arşivi hazırlanıyor...", critical=True)

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
            return core.update_work(home, s, old_engine, old_goal, force, progress, allowed)

        def done(res):
            store, engine, report, (goal, gerr) = res
            self.store = store
            self.seq_table = None  # veri değişti: dizi tablosu yeniden kurulacak
            self.seq_error = None
            self.prematch = None
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

    def _training_blocked(self) -> bool:
        """Gerçek veriyle eğitimin hak kapsamı (onay kutusu bu kontrolü aşamaz)."""
        from ..eligibility import reason_texts

        codes = core.training_block_codes(self.store, self.settings)
        if codes:
            # İlk satır durum çubuğunda görünür: ne yapılacağı orada yazar
            self.message.emit("warn", "Model eğitimi yapılmadı. " + self.declaration_hint() + "\nVeri kaynağının "
                              "kullanım kapsamı doğrulanmadı:\n" + reason_texts(codes))
        return bool(codes)

    def retrain(self) -> bool:
        if not self.store.has_data:
            self.message.emit("warn", "Önce verileri indirin.")
            return False
        if self._training_blocked():
            return False
        matches = self.store.matches
        settings = self.settings
        home = self.home

        def work(progress):
            return core.retrain_work(matches, settings, home, progress)

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
        if self._training_blocked():
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

    # ------------------------------------------------------- veri uygunluğu
    def now(self) -> dt.datetime:
        return self.clock()

    def today(self) -> dt.date:
        """Bilgi kesimiyle aynı takvim: İstanbul günü."""
        return core.istanbul_today(self.now())

    def match_day_stale(self) -> bool:
        """1X2 uygunluğu başka bir gün değerlendirildiyse yeniden değerlendirilmelidir."""
        return self._match_day is not None and self._match_day != self.today()

    def goal_day_stale(self) -> bool:
        return self._goal_day is not None and self._goal_day != self.today()

    def check_day(self) -> bool:
        """Gün değiştiyse uygunluğu yeniden değerlendirir. Yeniden değerlendirme başlatıldıysa True."""
        changed = False
        if self.match_day_stale():
            self.refresh_predictions()
            changed = True
        if self.goal_day_stale():
            self.refresh_goal_predictions()
            changed = True
        return changed

    def eligibility_context(self, engine):
        """Ortak veri uygunluk bağlamı (veri deposu + bu motorun durumu + önbellekteki kaynak takvimleri + haklar).

        Önbellek anahtarı; veri deposu, motor durumu, kaynak dosyaları ve onaylar değişince değişir (eski "uygun"
        sonucu yeni veri/durum/kapsamla kullanılmaz). Bağlam kurulamazsa None döner: tahminler uygun sayılmaz."""
        key = core.context_key(self.store, engine, self.settings, self.today())
        ctx = self._ctx_cache.get(key)
        if ctx is None:
            try:
                ctx = core.build_eligibility_context(self.store, engine, self.settings, self.today())
            except Exception:
                log.exception("Veri uygunluk bağlamı kurulamadı")
                return None
            if len(self._ctx_cache) >= 2:  # gol ve 1X2 motoru için birer güncel bağlam
                self._ctx_cache.pop(next(iter(self._ctx_cache)))
            self._ctx_cache[key] = ctx
        return ctx

    def refresh_predictions(self) -> None:
        from ..eligibility import gated_match_predictions

        self.match_unpredicted = []
        self._match_day = self.today()
        if self.store.fixtures.empty and self.store.unmatched_fixtures.empty:
            self.predictions = []
        else:
            # Model yoksa da fikstürler nedenli "tahmin yok" satırı olarak listelenir (sessizce düşürülmez)
            eng = self.engine if (self.engine is not None and self.engine.trained) else None
            try:
                ctx = self.eligibility_context(eng)
                self.predictions, self.match_unpredicted = gated_match_predictions(
                    eng, ctx, self.store.fixtures, self.now(), self.settings.odds_type,
                    self.store.unmatched_fixtures)
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

    # ------------------------------------------------------------ dizi araştırması
    def ensure_sequence_table(self) -> None:
        """Takım-maç tablosunu (dizi araştırması) arka planda kurar; veri değişmediyse yeniden kurmaz."""
        if self.seq_table is not None or not self.store.has_data:
            return
        matches = self.store.matches

        def work(progress):
            from ..sequences.timeline import build_team_matches

            progress(20, "Dizi araştırması: takım-maç tablosu kuruluyor...")
            try:
                return build_team_matches(matches), None
            except ValueError as exc:  # veri sıralaması belirsiz vb.: sayfada açıklanır, modal hata açılmaz
                return None, str(exc)

        def done(res):
            tm, err = res
            self.seq_table = tm
            self.seq_error = err
            self.seq_results = load_sequence_results(self.home) if tm is not None else None
            self.sequenceChanged.emit()

        if self.seq_error is not None:
            return
        if self.busy:
            self._queue.append(self.ensure_sequence_table)
            return
        self._run(work, done, "Dizi araştırması hazırlanıyor...", critical=False)

    def ensure_prematch(self) -> None:
        """Maç öncesi görünüm için yaklaşan maçları (fikstür) sonucu bilinmeyen satırlar olarak ekleyip dizi atomlarını
        yalnızca önceki günlerin maçlarından hesaplar (arka planda, salt okuma)."""
        if not self.store.has_data:
            return
        if self.store.fixtures.empty:
            self.prematch, self.prematch_error = None, "Yaklaşan maç (fikstür) verisi yok."
            self.sequenceChanged.emit()
            return
        matches, fixtures, home = self.store.matches, self.store.fixtures, self.home

        def work(progress):
            import pandas as pd

            from ..sequences.prematch import prematch_frame

            progress(20, "Maç öncesi görünüm: yaklaşan maçlar hazırlanıyor...")
            cal_path = home / SEQ_DIR / "s0_kalibre.pkl"
            cal = pd.read_pickle(cal_path) if cal_path.exists() else None
            try:
                return prematch_frame(matches, fixtures, cal), None
            except ValueError as exc:
                return None, str(exc)

        def done(res):
            self.prematch, self.prematch_error = res
            self.sequenceChanged.emit()

        if self.busy:
            self._queue.append(self.ensure_prematch)
            return
        self._run(work, done, "Maç öncesi görünüm hazırlanıyor...", critical=False)

    def ledger_if_exists(self) -> Ledger | None:
        """Okuma amaçlı: sanal takip dosyası henüz yoksa oluşturmadan None döner."""
        if self._ledger is None and not (self.home / LEDGER_FILE).exists():
            return None
        return self.ledger

    def refresh_goal_predictions(self) -> None:
        eng = self.goal_engine
        stale = self.goal_day_stale()
        self._goal_day = self.today()  # her dalda önce işaretlenir (yeniden giriş/sonsuz döngü olmaz)
        if eng is None or not eng.trained or (self.store.fixtures.empty and self.store.unmatched_fixtures.empty):
            self.goal_predictions = []
            self.goal_verdicts = []
            self.goalPredictionsChanged.emit()
            return
        fixtures, unmatched = self.store.fixtures, self.store.unmatched_fixtures
        if stale:  # yeni değerlendirme bitene kadar önceki günün sonucu gösterilmez
            self.goal_predictions = []
            self.goal_verdicts = []
            self.goalPredictionsChanged.emit()

        def work(progress):
            from ..goals.service import gated_goal_predictions

            progress(10, "Gol pazarları: veri uygunluğu, tahminler ve belirsizlik aralıkları hesaplanıyor...")
            ctx = self.eligibility_context(eng)
            return gated_goal_predictions(eng, ctx, fixtures, self.now(), unmatched=unmatched)

        def done(verdicts):
            self.goal_verdicts = verdicts
            self.goal_predictions = [v.prediction for v in verdicts if v.prediction is not None]
            self.goalPredictionsChanged.emit()

        if self.busy:  # başka iş bitince sessizce sıraya al
            self._queue.append(self.refresh_goal_predictions)
            return
        self._run(work, done, "Gol pazarları tahminleri...")

    def save_settings(self, s: Settings) -> None:
        leagues_changed = (s.leagues != self.settings.leagues) or (s.years_back != self.settings.years_back)
        method_changed = s.margin_method != self.settings.margin_method
        mode_changed = s.veri_denetimi != self.settings.veri_denetimi
        self.settings = s
        s.save()
        self.settingsChanged.emit()
        self.refresh_predictions()
        retraining = not leagues_changed and method_changed and self.store.has_data
        if mode_changed and not retraining:  # yeniden eğitim gol tahminlerini de yeniler (iki iş çakışmasın)
            self.refresh_goal_predictions()
        if leagues_changed:
            self.message.emit("popup", "Lig/sezon seçimi değişti. Yeni verileri almak için 'Verileri Güncelle' butonunu kullanın.")
        elif method_changed and self.store.has_data:
            self.message.emit("status", "Marj yöntemi değişti; model yeniden eğitiliyor.")
            self.retrain()
        else:
            self.message.emit("status", "Ayarlar kaydedildi.")

    # ------------------------------------------------------------ queries
    def prediction_frame(self) -> pd.DataFrame:
        """Tahmin listesini tabloya uygun DataFrame'e çevirir (``core.prediction_rows``): veri uygunluğu
        doğrulanmayan maçlarda olasılıklar gösterilmez, tahmini üretilemeyen fikstürler nedenleriyle listelenir."""
        return core.prediction_rows(self.predictions, self.match_unpredicted, self.settings, self.now())

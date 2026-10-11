"""Uygulama durumu ve arka plan işleri (veri güncelleme, model eğitimi)."""

from __future__ import annotations

import datetime as dt
import logging
import traceback
from typing import Callable

import pandas as pd
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from ..config import Settings, app_home
from ..data.provenance import verified_labels
from ..data.store import DataStore
from ..eligibility import training_rights_codes
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


SEQ_DIR = "dizi_arastirma"


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
        """Geçmiş maç verisi sağlayan hiçbir kaynağın kullanım koşulları onaylanmamış mı? GitHub veri profilinde
        football-data kullanılmadığı için yalnızca GitHub yedek veri setinin onayı sayılır."""
        from ..data.github_kaynak import PROFILE_GITHUB

        keys = {"github-mirror"} if self.settings.data_profile == PROFILE_GITHUB else {"football-data", "github-mirror"}
        return not (keys & self.settings.allowed_sources())

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
            blocked = (training_rights_codes(store.matches, s.source_consent, verified_labels(store))
                       if store.has_data else [])
            if blocked:  # hak kapsamı doğrulanmayan gerçek veriyle eğitim yapılmaz (S3-GATE-02)
                report.warnings.append("Model eğitimi yapılmadı: veri kaynağının kullanım kapsamı doğrulanmadı ("
                                       + ", ".join(blocked) + ").")
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
                goal, gerr = _train_goal(store.matches, home, lambda p, m: progress(70 + int(p * 0.29), m))
            return store, engine, report, (goal, gerr)

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

        codes = training_rights_codes(self.store.matches, self.settings.source_consent, verified_labels(self.store))
        if codes:
            self.message.emit("warn", "Model eğitimi yapılmadı; veri kaynağının kullanım kapsamı doğrulanmadı:\n"
                              + reason_texts(codes))
        return bool(codes)

    def retrain(self) -> bool:
        if not self.store.has_data:
            self.message.emit("warn", "Önce verileri indirin.")
            return False
        if self._training_blocked():
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
        from ..timeutil import ISTANBUL

        return self.now().astimezone(ISTANBUL).date()

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
        from ..eligibility import build_context

        raw = self.store.raw_dir / "openfootball"
        try:
            files = tuple(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in raw.rglob("*.json"))) \
                if raw.exists() else ()
        except OSError:
            files = ()
        m = self.store.matches
        key = (id(engine), getattr(engine, "state_available_since", None), id(m), len(m),
               self.store.meta.get("updated_at"), files, tuple(sorted(self.settings.source_consent)),
               self.today())
        ctx = self._ctx_cache.get(key)
        if ctx is None:
            try:
                ctx = build_context(self.store, engine, self.settings.source_consent, today=self.today())
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
        """Tahmin listesini tabloya uygun DataFrame'e çevirir.

        Veri uygunluğu doğrulanmayan maçlarda olasılıklar gösterilmez (boş; sıfır değil), değer önerisi yoktur ve
        durum metinle yazılır. Tahmini hiç üretilemeyen fikstürler (modelde olmayan lig, eşleşmeyen takım) de
        nedenleriyle listelenir (``_i`` = -1)."""
        from ..eligibility import display_label

        rows = []
        s = self.settings
        nan = float("nan")
        now = self.now()
        for i, p in enumerate(self.predictions):
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
        for v in self.match_unpredicted:
            label, text = display_label(v.first(), v.display_codes("1X2", now))
            rows.append({
                "_i": -1, "date": v.date, "when": v.date.strftime("%d.%m.%Y") + (f" {v.time}" if v.time else ""),
                "league": v.league, "home": v.home, "away": v.away + ("" if v.canonical_id else " (eşleşmedi)"),
                "p1": nan, "px": nan, "p2": nan, "pick": "-", "o25": nan, "btts": nan, "xg": "-", "odds": "-",
                "value": "", "value_ev": nan, "has_market": False, "veri": label, "veri_neden": text,
            })
        return pd.DataFrame(rows)

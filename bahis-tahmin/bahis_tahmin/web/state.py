"""Web arayüzünün durumu: ortak çekirdek (``core.AppCore``) + tek arka plan işi (``jobs.JobRunner``).

İş akışları masaüstüyle aynıdır (``ui.controller``): güncelleme → (hak doğrulandıysa) eğitim → tahminlerin ortak veri
uygunluk kontrolünden geçirilmesi → gol pazarları değerlendirmesi. Uygunluk ve eğitim kuralları ``core``'dadır.
"""

from __future__ import annotations

import logging

from ..config import Settings
from ..core import (
    CUP_ENGINE_FILE,
    ENGINE_FILE,
    GOAL_ENGINE_FILE,
    AppCore,
    cup_training_block_codes,
    next_cup_engine,
    declaration_hint,
    load_saved,
    retrain_work,
    train_goal,
    update_work,
)
from .jobs import JobRunner

log = logging.getLogger(__name__)

BUSY_TEXT = "Başka bir işlem sürüyor, lütfen bitmesini bekleyin."


class WebState:
    def __init__(self, home=None):
        self.core = AppCore(home)
        self.jobs = JobRunner()
        self._stamp: tuple | None = None  # son bilinen dosya durumu (masaüstündeki değişiklikleri fark etmek için)

    # ------------------------------------------------------------ yardımcılar
    @property
    def busy(self) -> bool:
        return self.jobs.busy

    def _refresh_all(self, progress=None) -> str | None:
        """1X2 tahminleri ve gol pazarları değerlendirmesi (aynı uygunluk bağlamıyla). Hata metni döner."""
        core = self.core
        if progress:
            progress(96, "Tahminler değerlendiriliyor...")
        err = core.refresh_predictions()
        try:
            core.set_goal_verdicts(core.compute_goal_verdicts(progress))
        except Exception as e:  # gol değerlendirmesi 1X2 tahminlerini engellemez
            log.exception("Gol pazarları değerlendirilemedi")
            core.set_goal_verdicts([])
            err = (err + " · " if err else "") + f"Gol pazarları değerlendirilemedi: {e}"
        return err

    # ------------------------------------------------------------ ortak dosyalar
    def _disk_stamp(self) -> tuple:
        """Ayar, veri ve model dosyalarının değişiklik zamanları. ``data_meta.json`` veri kaydında en son yazılır."""
        h = self.core.home
        out = []
        for p in (Settings.path(), h / "data_meta.json", h / ENGINE_FILE, h / GOAL_ENGINE_FILE, h / CUP_ENGINE_FILE):
            try:
                out.append(p.stat().st_mtime_ns)
            except OSError:
                out.append(None)
        return tuple(out)

    def remember_disk(self) -> None:
        """Web arayüzünün kendi yazdığı dosyalar yeniden yüklemeye yol açmasın."""
        self._stamp = self._disk_stamp()

    def _start(self, label: str, work, done=None) -> bool:
        def wrapped(progress):
            try:
                return work(progress)
            finally:
                self.remember_disk()

        return self.jobs.start(label, wrapped, done)

    # ------------------------------------------------------------ işler
    def start_load(self) -> bool:
        core = self.core

        def work(progress):
            core.apply_loaded(load_saved(core.home, progress))
            return self._refresh_all(progress)

        return self._start("Kayıtlı veriler yükleniyor...", work, lambda err: err)

    def start_update(self, force: bool = False) -> bool:
        """Verileri günceller ve gerekiyorsa modeli eğitir (onay denetimi çağıranda)."""
        core = self.core
        s = core.settings
        allowed = s.allowed_sources()
        old_engine, old_goal, old_cup = core.engine, core.goal_engine, core.cup_engine

        def work(progress):
            res = update_work(core.home, s, old_engine, old_goal, force, progress, allowed, old_cup=old_cup)
            core.apply_update(res)
            err = self._refresh_all(progress)
            summary = res[2].summary()
            return summary + (f"\n{err}" if err else "")

        return self._start("Veriler güncelleniyor...", work, lambda summary: summary)

    def training_block_text(self) -> str | None:
        """Gerçek veriyle eğitimin hak engeli varsa kullanıcıya gösterilecek metin (yoksa None)."""
        from ..eligibility import reason_texts

        core = self.core
        if not core.store.has_data:
            return "Önce verileri indirin."
        codes = core.training_blocked()
        if not codes:
            return None
        return ("Model eğitimi yapılmadı. " + declaration_hint(core.settings, core.store.matches)
                + "\nVeri kaynağının kullanım kapsamı doğrulanmadı:\n" + reason_texts(codes))

    def start_retrain(self) -> bool:
        core = self.core
        matches, settings, home = core.store.matches, core.settings, core.home
        cups = getattr(core.store, "cup_matches", None)
        cup_ok = not cup_training_block_codes(core.store, settings)

        def work(progress):
            engine, goal, gerr, (cup, cerr) = retrain_work(matches, settings, home, progress, cups, cup_ok)
            with core.lock:
                core.engine, core.goal_engine, core.goal_load_error = engine, goal, gerr
                core.cup_engine = next_cup_engine(core.cup_engine, cup, settings)
                core.cup_error = cerr
            self._refresh_all(progress)
            return ("Model eğitildi." + (f" Gol pazarları: {gerr}" if gerr else "")
                    + (f" Kupa modeli: {cerr}" if cerr else ""))

        return self._start("Model eğitiliyor...", work, lambda msg: msg)

    def start_goal_train(self) -> bool:
        core = self.core
        matches, home = core.store.matches, core.home

        def work(progress):
            goal, gerr = train_goal(matches, home, progress)
            with core.lock:
                core.goal_engine, core.goal_load_error = goal, gerr
            core.set_goal_verdicts(core.compute_goal_verdicts(progress))
            return gerr or "Gol pazarları modeli eğitildi."

        return self._start("Gol pazarları modeli eğitiliyor...", work, lambda msg: msg)

    def start_goal_refresh(self) -> bool:
        core = self.core

        def work(progress):
            core.set_goal_verdicts(core.compute_goal_verdicts(progress))

        return self._start("Gol pazarları tahminleri...", work)

    # ------------------------------------------------------------ günlük yenileme
    def ensure_fresh(self) -> None:
        """Masaüstü uygulaması ayarları, verileri veya modeli değiştirdiyse hepsi yeniden yüklenir; gün değiştiyse
        uygunluk yeniden değerlendirilir (önceki günün sonucu gösterilmez)."""
        core = self.core
        if not core.loaded or self.busy:
            return
        if self._stamp is not None and self._disk_stamp() != self._stamp:
            log.info("Ayar/veri/model dosyaları başka bir pencerede değişti; yeniden yükleniyor")
            with core.lock:
                core.settings = Settings.load()
            self.start_load()
            return
        if core.match_day_stale():
            core.refresh_predictions()
        if core.goal_day_stale():
            core.set_goal_verdicts([])  # yeni değerlendirme bitene kadar eski gün gösterilmez
            self.start_goal_refresh()

    # ------------------------------------------------------------ ayarlar
    def save_settings(self, new: Settings) -> str:
        """Ayarları kaydeder (masaüstündeki ``save_settings`` ile aynı sonuçlar). Kullanıcıya gösterilecek metin."""
        core = self.core
        old = core.settings
        leagues_changed = (new.leagues != old.leagues) or (new.years_back != old.years_back)
        method_changed = new.margin_method != old.margin_method
        mode_changed = new.veri_denetimi != old.veri_denetimi
        new.validate()
        new.save()
        with core.lock:
            core.settings = new
        core.refresh_predictions()
        if leagues_changed:
            return "Ayarlar kaydedildi. Lig/sezon seçimi değişti; yeni veriler için 'Verileri Güncelle'yi kullanın."
        if method_changed and core.store.has_data:
            block = self.training_block_text()
            if block:
                return "Ayarlar kaydedildi. " + block
            if self.start_retrain():
                return "Ayarlar kaydedildi. Marj yöntemi değişti; model yeniden eğitiliyor."
            return "Ayarlar kaydedildi. " + BUSY_TEXT
        if mode_changed:
            self.start_goal_refresh()
        return "Ayarlar kaydedildi."

    def after_rights_change(self, added: bool) -> str | None:
        """Beyan değişti: tahminler yeni haklarla yeniden değerlendirilir; yeni beyan verildiyse ve model yoksa veya
        veriyle uyumsuzsa model eğitilir (eğitim yine hak denetiminden geçer)."""
        core = self.core
        core.refresh_predictions()
        if added and core.store.has_data and (core.engine is None or core.needs_training()):
            if self.training_block_text() is None and self.start_retrain():
                return "Kişisel kullanım beyanı kaydedildi; model eğitiliyor."
        if not self.start_goal_refresh():
            return None
        return None

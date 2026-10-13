"""Web arayüzünün arka plan işleri: aynı anda tek iş (masaüstündeki tek görev yöneticisiyle aynı kural).

İş ``work(progress)`` olarak ayrı iş parçacığında çalışır; ``done(sonuç)`` da aynı iş parçacığında, iş bittikten
sonra çağrılır ve sonucu uygulama durumuna kilit altında yazar. Tarayıcı ``status()`` ile ilerlemeyi izler.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)


class JobRunner:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.label = ""
        self.pct = 0
        self.msg = "Hazır"
        self.error: str | None = None  # son işin hatası (bir sonraki iş başlayınca temizlenir)
        self.notice: str | None = None  # son işin kullanıcıya gösterilecek sonucu (ör. güncelleme raporu)
        self.finished = 0  # tamamlanan iş sayacı (tarayıcı sayfayı yenilemek için izler)
        self.started_at: float | None = None

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._thread is not None

    def start(self, label: str, work: Callable, done: Callable | None = None) -> bool:
        """İşi başlatır; başka iş sürüyorsa başlatmaz (False)."""
        with self._lock:
            if self._thread is not None:
                return False
            self.label, self.pct, self.msg = label, 0, label
            self.error = self.notice = None
            self.started_at = time.time()
            t = threading.Thread(target=self._run, args=(work, done), name=f"is:{label}", daemon=True)
            self._thread = t
        t.start()
        return True

    def _progress(self, pct, msg) -> None:
        with self._lock:
            self.pct = max(0, min(100, int(pct)))
            self.msg = str(msg)

    def _run(self, work: Callable, done: Callable | None) -> None:
        try:
            res = work(self._progress)
            notice = done(res) if done is not None else None
            with self._lock:
                self.notice = notice if isinstance(notice, str) else None
                self.pct, self.msg = 100, "Hazır"
        except Exception as e:  # tarayıcıya hata olarak iletilir (ayrıntı günlükte)
            log.exception("Arka plan işi başarısız: %s", self.label)
            with self._lock:
                self.error = f"{self.label}: {e}"
                self.pct, self.msg = 0, "Hata"
        finally:
            with self._lock:
                self._thread = None
                self.finished += 1

    def wait(self, timeout: float | None = None) -> None:
        """(Testler ve kapanış için) süren işin bitmesini bekler."""
        t = self._thread
        if t is not None:
            t.join(timeout)

    def status(self) -> dict:
        with self._lock:
            return {"busy": self._thread is not None, "label": self.label, "pct": self.pct, "msg": self.msg,
                    "error": self.error, "notice": self.notice, "finished": self.finished}

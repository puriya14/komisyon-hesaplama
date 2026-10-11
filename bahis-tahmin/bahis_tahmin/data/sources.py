"""Önbellekli HTTP indirici."""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from .. import __version__

FD_BASE = "https://www.football-data.co.uk"
MIRROR_URL = (
    "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"
)
OPENFOOTBALL_BASE = "https://raw.githubusercontent.com/openfootball/football.json/master"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    f"BahisTahmin/{__version__}"
)


class DownloadError(Exception):
    def __init__(self, url: str, message: str, status: int | None = None, policy: bool = False):
        super().__init__(f"{url}: {message}")
        self.url = url
        self.status = status
        self.policy = policy  # veri profili adresi/yönlendirmeyi reddetti (istek gönderilmedi veya izlenmedi)

    @property
    def network(self) -> bool:
        """Sunucuya hiç ulaşılamadı mı (404 gibi HTTP hatalarından ve profil reddinden farklı olarak)."""
        return self.status is None and not self.policy


class Downloader:
    def __init__(
        self,
        cache_dir: Path,
        timeout: tuple[float, float] = (10.0, 40.0),
        retries: int = 1,
        polite_delay: float = 0.15,
        offline: bool = False,
        allowed_hosts: frozenset[str] | None = None,
    ):
        """``allowed_hosts``: verilirse (ör. GitHub veri profili) yalnızca bu adreslere istek gönderilir; başka adres
        önbellekten de okunmaz ve yönlendirmeler elle izlenir (izinli adres dışına çıkan yönlendirme durdurulur)."""
        self.cache_dir = Path(cache_dir)
        self.allowed_hosts = None if allowed_hosts is None else frozenset(allowed_hosts)
        self.timeout = timeout
        self.retries = retries
        self.polite_delay = polite_delay
        self.offline = offline
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._down_hosts: dict[str, int] = {}
        # stale: indirme başarısız olduğu için eski kopya kullanıldı (güncel sayılmaz; raporda ayrıca gösterilir)
        self.stats = {"network": 0, "cache": 0, "failed": 0, "stale": 0}
        self.stale_files: list[str] = []

    def cache_path(self, rel: str) -> Path:
        return self.cache_dir / rel

    @staticmethod
    def _host(url: str) -> str:
        return url.split("/")[2] if "://" in url else url

    def host_down(self, url: str) -> bool:
        return self._down_hosts.get(self._host(url), 0) >= 2

    def get(self, url: str, cache_rel: str, max_age_hours: float | None = None, force: bool = False) -> bytes:
        """URL içeriğini döndürür.

        max_age_hours=None ise önbellekteki dosya hiç eskimez (tamamlanmış sezonlar).
        İndirme başarısız olursa ve önbellekte eski bir kopya varsa o kullanılır; bu durum ``stats["stale"]`` ve
        ``stale_files`` ile ayrıca kaydedilir (yeni alınmış veri gibi gösterilmez).
        """
        self._check_host(url)
        path = self.cache_path(cache_rel)
        if path.exists() and not force:
            age_h = (time.time() - path.stat().st_mtime) / 3600.0
            if max_age_hours is None or age_h < max_age_hours or self.offline:
                self.stats["cache"] += 1
                return path.read_bytes()
        if self.offline:
            raise DownloadError(url, "çevrimdışı mod ve önbellekte yok")
        try:
            data = self._download(url)
        except DownloadError as e:
            if path.exists() and not e.policy:
                self.stats["cache"] += 1
                self.stats["stale"] += 1
                self.stale_files.append(cache_rel)
                return path.read_bytes()
            self.stats["failed"] += 1
            raise
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        self.stats["network"] += 1
        return data

    def _check_host(self, url: str) -> None:
        if self.allowed_hosts is None:
            return
        parts = urlsplit(url)
        if parts.scheme != "https" or (parts.hostname or "").lower() not in self.allowed_hosts:
            raise DownloadError(url, "seçili veri profili bu adrese istek göndermez", policy=True)

    def _request(self, url: str):
        if self.allowed_hosts is None:
            return self.session.get(url, timeout=self.timeout)
        for _ in range(4):
            r = self.session.get(url, timeout=self.timeout, allow_redirects=False)
            if r.status_code not in (301, 302, 303, 307, 308):
                return r
            nxt = urljoin(url, r.headers.get("Location", ""))
            try:
                self._check_host(nxt)
            except DownloadError:
                raise DownloadError(url, f"yönlendirme izinli adres dışına çıkıyor ({nxt}); izlenmedi",
                                    r.status_code, policy=True) from None
            url = nxt
        raise DownloadError(url, "çok fazla yönlendirme", policy=True)

    def _download(self, url: str) -> bytes:
        host = self._host(url)
        if self.host_down(url):
            raise DownloadError(url, "sunucuya ulaşılamıyor")
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                if self.polite_delay:
                    time.sleep(self.polite_delay)
                r = self._request(url)
            except requests.RequestException as e:
                last = e
                time.sleep(min(2.0 * (attempt + 1), 5.0))
                continue
            if r.status_code == 200 and r.content:
                self._down_hosts.pop(host, None)
                return r.content
            if r.status_code in (404, 410):
                raise DownloadError(url, "dosya bulunamadı (404)", r.status_code)
            last = DownloadError(url, f"HTTP {r.status_code}", r.status_code)
            if r.status_code < 500 and r.status_code != 429:
                raise last
            time.sleep(min(2.0 * (attempt + 1), 5.0))
        self._down_hosts[host] = self._down_hosts.get(host, 0) + 1
        if isinstance(last, DownloadError):
            raise last
        raise DownloadError(url, f"bağlantı hatası: {last}")

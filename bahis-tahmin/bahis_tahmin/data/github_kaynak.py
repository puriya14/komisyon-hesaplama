"""GitHub veri profili: yalnızca kullanıcının seçtiği public GitHub depolarından, sabit commit'e bağlı ve dosya özeti
doğrulanan veri alımı (S5-GITHUB-01).

* İstekler yalnızca ``GITHUB_HOSTS`` adreslerine gider; başka adres (ör. football-data siteleri) istek gönderilmeden
  reddedilir. Yönlendirmeler elle izlenir; GitHub dışına çıkan yönlendirme isteği durdurur.
* Dal ucu bir işlem için BİR KEZ çözülür (git ``info/refs`` ilanı; API kotası ve git kurulumu gerekmez); dosyalar o
  commit'in ``raw.githubusercontent.com`` adresinden alınır. Hareketli dal üzerinden karışık sürüm toplanmaz.
* Önbellek anahtarı depo + commit + dosya yolu; eski commit'in dosyası ezilmez. Özeti kayıtla uyuşmayan dosya
  kullanılmaz (``OZET_UYUSMAZ``).
* Durum her zaman açıktır: kaynaktan yeni alındı / doğrulanmış önbellekten okundu / güncelleme başarısız, eski
  kopya kullanıldı. Hiçbiri güncel tahmin uygunluğunu kendiliğinden geçirmez (``eligibility`` ayrıdır).
* Depoların kendi güncelleme betikleri (ör. ``process.py``) çalıştırılmaz: bunlar GitHub dışındaki asıl sitelere
  istek gönderebilir; yalnızca depodaki mevcut dosyalar okunur.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urljoin, urlsplit

GITHUB_HOSTS = frozenset({"github.com", "raw.githubusercontent.com", "api.github.com"})
PROFILE_DEFAULT = "varsayilan"
PROFILE_GITHUB = "github"
PROFILES = (PROFILE_DEFAULT, PROFILE_GITHUB)

FETCHED = "KAYNAKTAN_ALINDI"
VERIFIED_CACHE = "DOGRULANMIS_ONBELLEK"
STALE_COPY = "GUNCELLEME_BASARISIZ_ESKI_KOPYA"
IMPORTED = "PILOT_ONBELLEGINDEN_KOPYALANDI"
STATUS_TEXT = {FETCHED: "kaynaktan yeni alındı", VERIFIED_CACHE: "doğrulanmış önbellekten okundu",
               STALE_COPY: "güncelleme başarısız, eski kopya kullanıldı",
               IMPORTED: "pilotun doğrulanmış önbelleğinden kopyalandı (özet doğrulandı)"}

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class RepoSpec:
    """Kullanıcının seçtiği GitHub deposu. ``source_key``: ``source_registry`` anahtarı; ``label``: satırların kaynak
    etiketi; ``origin``: verinin asıl kökeni (aynı asıl kökenden beslenen iki depo bağımsız doğrulama değildir)."""
    repo: str
    branch: str
    source_key: str
    label: str
    origin: str
    aliases: tuple[str, ...] = ()
    identity_note: str = ""


REPOS: dict[str, RepoSpec] = {
    "openfootball/football.json": RepoSpec(
        "openfootball/football.json", "master", "openfootball-sonuc", "openfootball-sonuc",
        "openfootball topluluk derlemesi (CC0)"),
    "datasets/football-datasets": RepoSpec(
        "datasets/football-datasets", "main", "football-datasets", "football-datasets",
        "football-data.co.uk (depodaki scripts/process.py asıl siteden derler)"),
    "xgabora/Club-Football-Match-Data-2000-2025": RepoSpec(
        "xgabora/Club-Football-Match-Data-2000-2025", "main", "github-mirror", "github-yedek",
        "football-data.co.uk (maçlar) + ClubElo (Elo; 2025-06-15 sonrası yazarın geçici devam serisi)",
        aliases=("xgabora/Club-Football-Match-Data",),
        identity_note=("Verilen ad ve README atfındaki 'Club-Football-Match-Data' adı git ve raw üzerinde aynı commit'i "
                       "veriyor (2026-10-11: 25882a58a736). Hangisinin kanonik ad olduğu API bu oturumda bu depoya "
                       "kapalı olduğu için doğrulanamadı; benzer adlı başka depo kullanılmaz.")),
    "hudl/open-data": RepoSpec(
        "hudl/open-data", "master", "statsbomb-acik", "statsbomb-acik", "StatsBomb (Hudl) olay verisi"),
}


def _txt_repo_specs() -> dict[str, RepoSpec]:
    from .football_txt import TXT_REPOS

    return {r: RepoSpec(r, "master", "openfootball-sonuc", "openfootball-sonuc",
                        "openfootball topluluk derlemesi (CC0; Football.TXT metin deposu)") for r in TXT_REPOS}


# FIKSTUR-03: openfootball'un ulusal Football.TXT depoları (football.json bu depolardan derlenir; lisans dosyaları
# football.json'unkiyle aynı git nesnesi, CC0 1.0). Yalnızca football.json'da güncel sezon dosyası olmayan liglerin
# fikstür, takvim ve eksik dönem yedeği olarak okunur; tarihsel arşive (``REPOS``) girmez.
TXT_REPO_SPECS: dict[str, RepoSpec] = _txt_repo_specs()


class GitHubError(Exception):
    """GitHub erişim hatası. ``kind``: IZINSIZ_ADRES, YONLENDIRME_DISARI, BULUNAMADI, KOTA, HTTP, AG, BICIM,
    OZET_UYUSMAZ, CEVRIMDISI."""

    def __init__(self, kind: str, message: str, url: str | None = None, status: int | None = None):
        super().__init__(f"{kind}: {message}" + (f" ({url})" if url else ""))
        self.kind, self.url, self.status = kind, url, status


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def check_url(url: str) -> None:
    """İstek göndermeden önce: yalnızca https ve ``GITHUB_HOSTS``."""
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in GITHUB_HOSTS:
        raise GitHubError("IZINSIZ_ADRES", "GitHub profili yalnızca github.com, raw.githubusercontent.com ve "
                                           "api.github.com adreslerine istek gönderir", url)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class GitHubTransport:
    """Yalnızca GitHub adreslerine giden HTTP istemcisi. ``calls``: yapılan istekler (adres, durum) — denetim için."""

    def __init__(self, session=None, timeout: tuple[float, float] = (10.0, 90.0), max_redirects: int = 3,
                 polite_delay: float = 0.2):
        if session is None:
            import requests

            from .. import __version__

            session = requests.Session()
            session.headers["User-Agent"] = f"BahisTahmin/{__version__} (GitHub veri profili)"
        self.session, self.timeout, self.max_redirects, self.polite_delay = session, timeout, max_redirects, polite_delay
        self.calls: list[tuple[str, int | None]] = []

    def get(self, url: str, headers: dict | None = None) -> bytes:
        import time

        import requests

        for _ in range(self.max_redirects + 1):
            check_url(url)
            if self.polite_delay:
                time.sleep(self.polite_delay)
            try:
                r = self.session.get(url, headers=headers or {}, timeout=self.timeout, allow_redirects=False)
            except requests.RequestException as e:
                self.calls.append((url, None))
                raise GitHubError("AG", f"bağlantı hatası: {e}", url) from e
            self.calls.append((url, r.status_code))
            if r.status_code in (301, 302, 303, 307, 308):
                nxt = urljoin(url, r.headers.get("Location", ""))
                if host_of(nxt) not in GITHUB_HOSTS or urlsplit(nxt).scheme != "https":
                    raise GitHubError("YONLENDIRME_DISARI", f"yönlendirme GitHub dışına çıkıyor: {nxt}", url,
                                      r.status_code)
                url = nxt
                continue
            if r.status_code == 200:
                return r.content
            if r.status_code in (404, 410):
                raise GitHubError("BULUNAMADI", "dosya veya depo bulunamadı", url, r.status_code)
            if r.status_code in (403, 429):
                raise GitHubError("KOTA", f"erişim reddedildi veya kota doldu (HTTP {r.status_code})", url,
                                  r.status_code)
            raise GitHubError("HTTP", f"HTTP {r.status_code}", url, r.status_code)
        raise GitHubError("HTTP", "çok fazla yönlendirme", url)

    def resolve_ref(self, repo: str, branch: str) -> str:
        """Dalın ucu (40 karakter). git akıllı HTTP ilanı (``info/refs``) okunur: API kotası ve git kurulumu gerekmez."""
        if not _REPO.match(repo):
            raise GitHubError("BICIM", f"geçersiz depo adı: {repo}")
        data = self.get(f"https://github.com/{repo}.git/info/refs?service=git-upload-pack")
        refs = parse_ref_advertisement(data)
        sha = refs.get(f"refs/heads/{branch}")
        if sha is None:
            raise GitHubError("BICIM", f"{repo}: '{branch}' dalı ilanında yok")
        return sha

    @staticmethod
    def raw_url(repo: str, commit: str, path: str) -> str:
        return f"https://raw.githubusercontent.com/{repo}/{commit}/{quote(path)}"

    def fetch(self, repo: str, commit: str, path: str) -> bytes:
        if not _SHA40.match(commit or ""):
            raise GitHubError("BICIM", "dosyalar yalnızca 40 karakterlik sabit commit'ten alınır")
        return self.get(self.raw_url(repo, commit, path))


def parse_ref_advertisement(data: bytes) -> dict[str, str]:
    """git ``pkt-line`` ilanından {ref: sha}."""
    out: dict[str, str] = {}
    i = 0
    while i + 4 <= len(data):
        try:
            n = int(data[i:i + 4], 16)
        except ValueError:
            break
        if n == 0:
            i += 4
            continue
        line = data[i + 4:i + n].split(b"\0", 1)[0].decode("utf-8", "replace").strip()
        i += n
        parts = line.split(" ", 1)
        if len(parts) == 2 and _SHA40.match(parts[0]):
            out[parts[1]] = parts[0]
    return out


# ----------------------------------------------------------------------------
# Sürümlü önbellek (depo + commit + yol)
# ----------------------------------------------------------------------------

@dataclass
class CachedFile:
    data: bytes
    record: dict
    status: str


def _safe_path(path: str) -> PurePosixPath:
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise GitHubError("BICIM", f"geçersiz dosya yolu: {path}")
    return p


class GitHubCache:
    """``<kök>/github/<sahip__depo>/<commit>/<yol>`` + yanında ``.kaynak.json`` kaydı (depo, commit, yol, SHA-256, boyut,
    alım anı, yöntem). Aynı anahtarın farklı içeriği yazılmaz; özeti uyuşmayan dosya okunmaz."""

    def __init__(self, root):
        self.root = Path(root) / "github"

    def path(self, repo: str, commit: str, path: str) -> Path:
        if not _REPO.match(repo) or not _SHA40.match(commit or ""):
            raise GitHubError("BICIM", f"önbellek anahtarı geçersiz: {repo}@{commit}")
        return self.root / repo.replace("/", "__") / commit / Path(*_safe_path(path).parts)

    @staticmethod
    def _meta_path(p: Path) -> Path:
        return p.with_name(p.name + ".kaynak.json")

    def read(self, repo: str, commit: str, path: str) -> CachedFile | None:
        p = self.path(repo, commit, path)
        mp = self._meta_path(p)
        if not p.is_file() or not mp.is_file():
            return None
        rec = json.loads(mp.read_text(encoding="utf-8"))
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() != rec.get("sha256") or (rec.get("repo"), rec.get("commit"),
                                                                      rec.get("path")) != (repo, commit, path):
            raise GitHubError("OZET_UYUSMAZ", f"önbellekteki dosya kayıtla uyuşmuyor; kullanılmadı: {repo}@{commit[:12]}:"
                                              f"{path}")
        return CachedFile(data, rec, VERIFIED_CACHE)

    def put(self, repo: str, commit: str, path: str, data: bytes, method: str, url: str | None = None,
            retrieved_at: str | None = None, extra: dict | None = None) -> dict:
        p = self.path(repo, commit, path)
        sha = hashlib.sha256(data).hexdigest()
        if p.exists():
            old = self.read(repo, commit, path)  # özet uyuşmazsa hata: ezilmez
            if old is not None and old.record["sha256"] != sha:
                raise GitHubError("OZET_UYUSMAZ", "aynı depo/commit/yol için farklı içerik; eski kopya ezilmez")
            if old is not None:
                return old.record
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)
        rec = {"repo": repo, "commit": commit, "path": path, "sha256": sha, "boyut": len(data),
               "alinma_utc": retrieved_at or _now().isoformat(timespec="seconds"), "yontem": method, "url": url,
               **(extra or {})}
        self._meta_path(p).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        return rec

    def get(self, transport: GitHubTransport | None, repo: str, commit: str, path: str,
            offline: bool = False) -> CachedFile:
        hit = self.read(repo, commit, path)
        if hit is not None:
            return hit
        if offline or transport is None:
            raise GitHubError("CEVRIMDISI", f"önbellekte yok: {repo}@{commit[:12]}:{path}")
        data = transport.fetch(repo, commit, path)
        rec = self.put(repo, commit, path, data, FETCHED, url=transport.raw_url(repo, commit, path))
        return CachedFile(data, rec, FETCHED)

    # ---------------------------------------------------------------- dal ucu kayıtları
    @property
    def _refs_path(self) -> Path:
        return self.root / "uclar.json"

    def ref_history(self) -> dict:
        if not self._refs_path.is_file():
            return {}
        return json.loads(self._refs_path.read_text(encoding="utf-8"))

    def record_ref(self, repo: str, branch: str, commit: str, method: str) -> None:
        hist = self.ref_history()
        rows = hist.setdefault(repo, [])
        if not rows or rows[-1]["commit"] != commit:
            rows.append({"dal": branch, "commit": commit, "cozulme_utc": _now().isoformat(timespec="seconds"),
                         "yontem": method})
        self.root.mkdir(parents=True, exist_ok=True)
        self._refs_path.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")

    def resolve(self, transport: GitHubTransport | None, spec: RepoSpec, offline: bool = False) -> tuple[str, str, str]:
        """(commit, durum, açıklama). Uç çözülemezse SON KAYITLI commit kullanılır ve durum açıkça
        ``STALE_COPY`` olur; hiç kayıt yoksa hata (sessiz başarı yok)."""
        hist = self.ref_history().get(spec.repo) or []
        if not offline and transport is not None:
            try:
                sha = transport.resolve_ref(spec.repo, spec.branch)
                self.record_ref(spec.repo, spec.branch, sha, "git-info-refs")
                prev = hist[-1]["commit"] if hist else None
                note = "uç değişmedi" if prev == sha else ("ilk çözüm" if prev is None else f"uç değişti ({prev[:12]} → "
                                                                                             f"{sha[:12]})")
                return sha, FETCHED, note
            except GitHubError as e:
                if not hist:
                    raise
                return hist[-1]["commit"], STALE_COPY, f"uç çözülemedi ({e.kind}); son kayıtlı commit kullanıldı"
        if not hist:
            raise GitHubError("CEVRIMDISI", f"{spec.repo}: kayıtlı commit yok")
        return hist[-1]["commit"], VERIFIED_CACHE, "çevrimdışı: son kayıtlı commit"

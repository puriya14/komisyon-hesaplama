"""Maç verilerini indirir, birleştirir ve diskte saklar."""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .football_txt import SKIP_REASONS, TXT_CONVERTER, TXT_FILES, TXT_FORMAT, convert_football_txt
from .github_kaynak import (
    GITHUB_HOSTS,
    PROFILE_DEFAULT,
    PROFILE_GITHUB,
    PROFILES,
    REPOS,
    STATUS_TEXT,
    TXT_REPO_SPECS,
)
from .leagues import LEAGUES, openfootball_season, recent_season_starts, season_code, season_label
from .parsers import (
    FIXTURE_COLUMNS,
    MATCH_COLUMNS,
    normalize_extra,
    normalize_fixtures,
    normalize_main,
    normalize_mirror,
    openfootball_team_names,
    parse_openfootball,
    read_csv_robust,
)
from .source_registry import SOURCES, allowed_sources
from .sources import FD_BASE, MIRROR_URL, OPENFOOTBALL_BASE, Downloader, DownloadError
from .teams import BELIRSIZ, MATCHING_VERSION, resolve_teams, spelling_key

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, str], None]

# Takım adı yazımı birleştirilen kaynaklar (football-data adlandırması). Kökeni dosyayla doğrulanan sonuç satırlarına
# (ör. openfootball-sonuc) dokunulmaz: ad değişirse yeniden ayrıştırma denetimi tutmaz.
UNIFY_SOURCES = frozenset({"football-data.co.uk", "github-yedek"})

CURRENT_SEASON_MAX_AGE_H = 3.0
EXTRA_MAX_AGE_H = 12.0
FIXTURES_MAX_AGE_H = 1.0
MIRROR_MAX_AGE_H = 24.0
STORE_VERSION = 1


@dataclass
class UpdateReport:
    leagues: dict[str, str] = field(default_factory=dict)  # lig -> kaynak açıklaması
    warnings: list[str] = field(default_factory=list)
    n_matches: int = 0
    n_fixtures: int = 0
    used_mirror: bool = False
    downloaded: int = 0
    from_cache: int = 0
    blocked_sources: list[str] = field(default_factory=list)  # kullanım koşulları onaylanmamış
    profile: str = PROFILE_DEFAULT
    stale: int = 0  # indirme başarısız olduğu için önbellekteki ESKİ kopyası kullanılan dosya
    github: dict = field(default_factory=dict)  # GitHub profili: depo -> commit / uç durumu / dosya durumu
    completed: dict = field(default_factory=dict)  # VERI-02: lig -> openfootball ile eklenen maç sayısı
    txt_sources: dict = field(default_factory=dict)  # FIKSTUR-03: lig -> kullanılan openfootball metin dosyası
    espn: dict = field(default_factory=dict)  # KAYNAK-04: lig -> {"fikstur", "sonuc", "eslesen", "eslesmeyen"}

    def summary(self) -> str:
        lines = [
            f"{self.n_matches} maç, {self.n_fixtures} yaklaşan maç yüklendi "
            f"({self.downloaded} dosya indirildi, {self.from_cache} dosya önbellekten).",
        ]
        if self.profile == PROFILE_GITHUB:
            lines.append("Veri profili: yalnızca GitHub (football-data adreslerine istek gönderilmedi).")
            for repo, g in self.github.items():
                lines.append(f"{repo}: commit {str(g.get('commit') or '-')[:12]} — {g.get('aciklama', '')}")
        if self.stale:
            lines.append(f"{self.stale} dosya güncellenemedi; önbellekteki ESKİ kopya kullanıldı (güncel sayılmaz).")
        if self.used_mirror and self.profile != PROFILE_GITHUB:
            lines.append("football-data.co.uk'a ulaşılamadığı için GitHub yedek veri seti kullanıldı.")
        if self.txt_sources:
            lines.append("football.json'da güncel sezon dosyası olmayan ligler için openfootball metin dosyaları "
                         "kullanıldı (CC0): " + ", ".join(f"{k} ({v})" for k, v in self.txt_sources.items()) + ".")
        if self.completed:
            lines.append("Eksik dönem openfootball sonuçlarıyla tamamlandı (CC0; köken doğrulamalı): "
                         + ", ".join(f"{k} {v} maç" for k, v in self.completed.items()) + ".")
        if self.espn:
            lines.append("ESPN (onayınızla; resmi olmayan uç nokta): " + ", ".join(
                f"{k} {v['fikstur']} yaklaşan maç, {v['sonuc']} sonuç" + (f", {len(v['eslesmeyen'])} takım adı "
                                                                       "eşleşmedi" if v["eslesmeyen"] else "")
                for k, v in self.espn.items()) + ".")
        for key in self.blocked_sources:
            lines.append(f"{SOURCES[key].name}: kullanım koşulları onaylanmadığı için kullanılmadı.")
        lines += self.warnings
        return "\n".join(lines)


@dataclass
class _OFData:
    """Bir openfootball sezon dosyası, football.json biçiminde. ``txt``: dosya Football.TXT'den dönüştürüldüyse ASIL
    metin baytları (köken kanıtı olarak saklanan budur); ``source``: depo:yol; ``parse``: dönüştürme özeti."""
    data: bytes
    txt: bytes | None = None
    source: str = ""
    parse: object | None = None


class DataStore:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.raw_dir = self.home / "raw"
        self.matches = pd.DataFrame(columns=MATCH_COLUMNS)
        self.fixtures = pd.DataFrame(columns=FIXTURE_COLUMNS)
        self.meta: dict = {}
        self._last_unmatched: list[dict] = []
        self._of_memo: dict = {}

    # ------------------------------------------------------------------ disk
    @property
    def _matches_path(self) -> Path:
        return self.home / "matches.pkl"

    @property
    def _fixtures_path(self) -> Path:
        return self.home / "fixtures.pkl"

    @property
    def _meta_path(self) -> Path:
        return self.home / "data_meta.json"

    def load(self) -> bool:
        try:
            meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
            if meta.get("version") != STORE_VERSION:
                return False
            matches = pd.read_pickle(self._matches_path)
            fixtures = pd.read_pickle(self._fixtures_path)
        except Exception as e:  # dosya yok/bozuk/uyumsuz pandas sürümü
            log.info("Kayıtlı veri yüklenemedi: %s", e)
            return False
        # VERI-01 öncesi kaydedilmiş veride aynı takımın yazım farkları olabilir: yüklemede de birleştirilir (yalnızca
        # bellekte; dosya bir sonraki güncellemede yazılır) ki yeniden eğitim ve uygunluk aynı adları görsün
        matches, renames = unify_spellings(matches)
        if renames:
            matches = self._clean_matches(matches)
            canon = _spelling_index(matches)
            if canon and not fixtures.empty:
                fixtures = fixtures.copy()
                for col in ("home", "away"):
                    fixtures[col] = [canon.get((_country(lg), spelling_key(t)), t) if isinstance(t, str) else t
                                     for lg, t in zip(fixtures["league"], fixtures[col])]
        self.matches, self.fixtures, self.meta = matches, fixtures, meta
        return True

    def save(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.matches.to_pickle(self._matches_path)
        self.fixtures.to_pickle(self._fixtures_path)
        self.meta["version"] = STORE_VERSION
        self._meta_path.write_text(json.dumps(self.meta, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def has_data(self) -> bool:
        return not self.matches.empty

    @property
    def unmatched_fixtures(self) -> pd.DataFrame:
        """Takım adı kesin olarak eşleşmeyen yaklaşan maçlar (ham adlarla; kanonik maç kimliği yok).

        Eşleme durumu/sürümü ve sağlayıcı kimliği S3-GATE-02'den itibaren yazılır; eski kayıtlarda boştur."""
        cols = ["league", "date", "time", "raw_home", "raw_away", "source", "provider_id", "eslesme_durumu",
                "eslesme_surumu"]
        rows = self.meta.get("eslesmeyen_fikstur") or []
        df = pd.DataFrame(rows, columns=cols)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        return df

    # ---------------------------------------------------------------- update
    def update(
        self,
        leagues: list[str],
        years_back: int,
        progress: ProgressFn | None = None,
        force: bool = False,
        use_mirror_fallback: bool = True,
        fixture_days: int = 10,
        today: dt.date | None = None,
        downloader: Downloader | None = None,
        allowed: set[str] | None = None,
        profile: str = PROFILE_DEFAULT,
        github_transport=None,
    ) -> UpdateReport:
        """Verileri indirir. ``allowed``: kullanılmasına izin verilen kaynak anahtarları
        (bkz. ``source_registry``); verilmezse yalnızca onay gerektirmeyen kaynaklar kullanılır.

        ``profile="github"`` (S5-GITHUB-01): bütün güncelleme yolları yalnızca seçili GitHub depolarını kullanır;
        football-data adreslerine (sonuç ve fikstür) istek gönderilmez, gizli geri dönüş yoktur. Depo ucu bir kez
        çözülür, dosyalar o commit'ten alınır ve depo + commit + yol anahtarlı, özeti doğrulanan önbellekte saklanır.
        Uç çözülemezse son kayıtlı commit'in doğrulanmış kopyası açıkça "eski kopya" olarak kullanılır; hiç kopya
        yoksa o kaynak atlanır."""
        if profile not in PROFILES:
            raise ValueError(f"Bilinmeyen veri profili: {profile}")
        github = profile == PROFILE_GITHUB
        today = today or dt.date.today()
        progress = progress or (lambda p, m: None)
        dl = downloader or Downloader(self.raw_dir, allowed_hosts=GITHUB_HOSTS if github else None)
        report = UpdateReport(profile=profile)
        self._of_memo = {}  # bu güncellemede alınan openfootball sezon dosyaları (tamamlama ve fikstür aynı dosyayı kullanır)
        allowed = allowed_sources(None) if allowed is None else set(allowed)
        use_fd = "football-data" in allowed and not github
        # GitHub profilinde yedek veri seti asıl sonuç kaynağıdır (football-data kullanılmaz)
        use_mirror_fallback = (use_mirror_fallback or github) and "github-mirror" in allowed
        for key in ("football-data", "github-mirror"):
            if key not in allowed and not (github and key == "football-data"):
                report.blocked_sources.append(key)
        gh = _GitHubFiles(self.raw_dir, github_transport, report) if github else None
        starts = recent_season_starts(years_back, today)
        frames: list[pd.DataFrame] = []
        need_mirror: list[str] = []
        leagues = [c for c in leagues if c in LEAGUES]
        n_steps = max(1, len(leagues))

        for i, code in enumerate(leagues):
            lg = LEAGUES[code]
            progress(int(80 * i / n_steps), f"{lg.label} verileri alınıyor...")
            got: list[pd.DataFrame] = []
            if not use_fd:
                pass
            elif lg.kind == "main":
                for y in starts:
                    sc = season_code(y)
                    url = f"{FD_BASE}/mmz4281/{sc}/{code}.csv"
                    # Güncel ve bir önceki sezon dosyaları güncellenebilir; eskiler değişmez.
                    max_age = CURRENT_SEASON_MAX_AGE_H if y >= starts[-1] - 1 else None
                    if dl.host_down(url) and not dl.cache_path(f"fd/{sc}/{code}.csv").exists():
                        continue
                    try:
                        data = dl.get(url, f"fd/{sc}/{code}.csv", max_age, force)
                    except DownloadError as e:
                        if e.status == 404 and y == starts[-1]:
                            report.warnings.append(f"{lg.label}: {season_label(y)} sezonu henüz yayınlanmamış.")
                        elif not e.network:
                            report.warnings.append(f"{lg.label} {season_label(y)}: {e}")
                        continue
                    try:
                        df = normalize_main(read_csv_robust(data), code, season_label(y))
                    except Exception as e:  # bozuk dosya
                        report.warnings.append(f"{lg.label} {season_label(y)} okunamadı: {e}")
                        continue
                    if not df.empty:
                        got.append(df)
            elif lg.kind == "extra":
                url = f"{FD_BASE}/new/{lg.fd_file}.csv"
                try:
                    data = dl.get(url, f"fd/new/{lg.fd_file}.csv", EXTRA_MAX_AGE_H, force)
                    df = normalize_extra(read_csv_robust(data), code)
                    cutoff = pd.Timestamp(starts[0], 1, 1)
                    df = df[df["date"] >= cutoff]
                    if not df.empty:
                        got.append(df)
                except DownloadError as e:
                    if not e.network:
                        report.warnings.append(f"{lg.label}: {e}")
                except Exception as e:
                    report.warnings.append(f"{lg.label} okunamadı: {e}")
            if got:
                frames.extend(got)
                report.leagues[code] = "football-data.co.uk"
            elif use_mirror_fallback:
                need_mirror.append(code)
            elif use_fd:
                report.warnings.append(f"{lg.label}: veri alınamadı.")

        if need_mirror:
            progress(82, "Yedek veri seti (GitHub) alınıyor...")
            try:
                if gh is not None:
                    data = gh.get("xgabora/Club-Football-Match-Data-2000-2025", "data/Matches.csv")
                else:
                    data = dl.get(MIRROR_URL, "mirror/Matches.csv", MIRROR_MAX_AGE_H, force)
                raw = pd.read_csv(io.BytesIO(data), low_memory=False)
                mdf = normalize_mirror(raw, need_mirror)
                for code in need_mirror:
                    lg = LEAGUES[code]
                    cutoff = pd.Timestamp(starts[0], 1 if lg.calendar_year else 7, 1)
                    part = mdf[(mdf["league"] == code) & (mdf["date"] >= cutoff)]
                    if part.empty:
                        report.warnings.append(f"{lg.label}: hiçbir kaynaktan veri alınamadı.")
                        continue
                    frames.append(part)
                    report.leagues[code] = "GitHub yedek veri seti"
                    report.used_mirror = True
            except DownloadError as e:
                report.warnings.append(f"Yedek veri setine de ulaşılamadı: {e}")
            except _GitHubUnavailable as e:
                report.warnings.append(f"GitHub yedek veri seti alınamadı (başka kaynağa geçilmedi): {e}")

        progress(88, "Veriler birleştiriliyor...")
        if frames:
            matches = pd.concat([f for f in frames if not f.empty], ignore_index=True)
        else:
            matches = pd.DataFrame(columns=MATCH_COLUMNS)
        matches = self._clean_matches(matches)
        if matches.empty and self.has_data:
            report.warnings.append("Yeni veri alınamadı; mevcut veriler korunuyor.")
            matches = self.matches[self.matches["league"].isin(leagues)]
        # Aynı takımın yalnızca yazımı farklı adları (ör. yedek veri setinde "Nottm Forest" / "Nott'm Forest") tek
        # takıma indirilir; aksi halde takımın geçmişi ikiye bölünür ve fikstür adı eşleşmez.
        matches, renames = unify_spellings(matches)
        if renames:
            matches = self._clean_matches(matches)
        # VERI-02: geride kalan ligleri openfootball'un oynanmış maç sonuçlarıyla tamamla (fikstürle aynı dosya)
        completion = []
        if "openfootball" in allowed and not matches.empty:
            matches, completion = self._complete_from_openfootball(dl, gh, leagues, matches, today, report, force)
        # KAYNAK-04: başka güncel kaynağı olmayan ligler için ESPN (yalnızca kullanıcı onayıyla; GitHub profilinde yok)
        espn_fx, espn_unmatched, espn_meta = None, [], {}
        if "espn" in allowed and not github and not matches.empty:
            progress(90, "ESPN verileri alınıyor...")
            matches, espn_fx, espn_unmatched, espn_meta = self._from_espn(dl, leagues, matches, today, fixture_days,
                                                                          report, force)

        progress(92, "Yaklaşan maçlar (fikstür) alınıyor...")
        self._last_unmatched = []
        fixtures = self._update_fixtures(dl, leagues, matches, today, fixture_days, report, force,
                                         allowed - {"football-data"} if github else allowed, gh, espn_fx)
        self._last_unmatched += espn_unmatched

        self.matches = matches.reset_index(drop=True)
        self.fixtures = fixtures.reset_index(drop=True)
        self.meta.update({
            "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "leagues": leagues,
            "years_back": years_back,
            "sources": report.leagues,
            # Takım adı eşleşmeyen fikstürler sessizce düşürülmez: ham adlarıyla saklanır; uygulama bunlar için
            # aday kimlikli, nedenli "tahmin yok" sonucu gösterir (S3-GATE-01).
            "eslesmeyen_fikstur": list(self._last_unmatched),
            "veri_profili": profile,
            "github_kaynak": report.github if github else {},
            "eski_kopya_dosyalari": list(getattr(dl, "stale_files", [])) + (gh.stale if gh else []),
            "tamamlama_kokeni": completion,
            "espn_eslesme": espn_meta,
        })
        report.n_matches = len(self.matches)
        report.n_fixtures = len(self.fixtures)
        report.downloaded = dl.stats["network"] + (gh.network if gh else 0)
        report.from_cache = dl.stats["cache"] + (gh.cache_hits if gh else 0)
        report.stale = dl.stats.get("stale", 0) + (len(gh.stale) if gh else 0)
        self.save()
        progress(100, "Veriler hazır.")
        return report

    @staticmethod
    def _clean_matches(m: pd.DataFrame) -> pd.DataFrame:
        if m.empty:
            return pd.DataFrame(columns=MATCH_COLUMNS)
        m = m.copy()
        m["date"] = pd.to_datetime(m["date"])
        m["fthg"] = m["fthg"].astype(int)
        m["ftag"] = m["ftag"].astype(int)
        m = m[(m["fthg"] >= 0) & (m["ftag"] >= 0) & (m["fthg"] < 20) & (m["ftag"] < 20)]
        m = m.drop_duplicates(subset=["league", "date", "home", "away"], keep="first")
        return m.sort_values(["date", "league", "time", "home"], kind="mergesort").reset_index(drop=True)

    def _openfootball_file(self, dl, gh, code: str, season: str, force: bool, report=None) -> _OFData | None:
        """Ligin openfootball sezon dosyası (football.json biçiminde). football.json'da yoksa (FIKSTUR-03) ligin
        openfootball metin deposundaki Football.TXT dosyası dönüştürülür. Aynı güncellemede bir kez alınır."""
        key = (code, season)
        if key in self._of_memo:
            return self._of_memo[key]
        lg = LEAGUES[code]
        out = None
        try:
            if gh is not None:
                data = gh.get("openfootball/football.json", f"{season}/{lg.openfootball}.json")
            else:
                data = dl.get(f"{OPENFOOTBALL_BASE}/{season}/{lg.openfootball}.json",
                              f"openfootball/{season}/{lg.openfootball}.json", 6.0, force)
            out = _OFData(data)
            self._txt_json_path(code, season).unlink(missing_ok=True)  # asıl dosya varken eski dönüşüm kullanılmaz
        except (DownloadError, _GitHubUnavailable):
            out = self._openfootball_txt(dl, gh, code, season, force, report)
        self._of_memo[key] = out
        return out

    def _txt_json_path(self, code: str, season: str) -> Path:
        """Football.TXT dönüşümünün yazıldığı yer (uygunluk kontrolü takvimi buradan okur; ``cached_coverages``)."""
        return self.raw_dir / "openfootball" / season / f"{LEAGUES[code].openfootball}.txt.json"

    def _openfootball_txt(self, dl, gh, code: str, season: str, force: bool, report=None) -> _OFData | None:
        lg = LEAGUES[code]
        for f in TXT_FILES.get(code, ()):
            path = f.resolve(season)
            try:
                if gh is not None:
                    raw = gh.get(f.repo, path)
                else:
                    raw = dl.get(f.url(season), f"openfootball_txt/{f.repo.split('/')[-1]}/{path}", 6.0, force)
            except (DownloadError, _GitHubUnavailable):
                continue
            data, parse = convert_football_txt(raw, season, f.label(season))
            if not parse.matches:
                if report is not None:
                    report.warnings.append(f"{lg.label}: {f.label(season)} okunamadı (maç bulunamadı); kullanılmadı.")
                continue
            out_path = self._txt_json_path(code, season)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = out_path.with_name(out_path.name + ".part")
            tmp.write_bytes(data)
            tmp.replace(out_path)
            if report is not None:
                report.txt_sources[code] = f.label(season)
                skipped = {k: v for k, v in parse.skipped.items() if k != "NOT_ISARETI"}
                if skipped:
                    report.warnings.append(
                        f"{lg.label}: openfootball metin dosyasında {sum(skipped.values())} satır okunmadı ("
                        + "; ".join(f"{v} × {SKIP_REASONS.get(k, k)}" for k, v in sorted(skipped.items()))
                        + "). Bu maçlar uydurulmadı.")
            return _OFData(data, raw, f.label(season), parse)
        return None

    def _complete_from_openfootball(self, dl, gh, leagues, matches, today, report, force):
        """Ligin depodaki son maç gününden sonra oynanmış, depoda olmayan maçları openfootball sezon dosyasından ekler
        (``data.completion``). Döner: (veri, köken kayıtları)."""
        from ..eligibility import _norm_season
        from .completion import COMPLETION_LABEL, build_record, select_rows

        def proof_of(of: _OFData, lg, of_season: str):
            """(kopya yolu, köken kanıtı baytları, biçim alanları): Football.TXT ise ASIL metin dosyası saklanır."""
            if of.txt is None:
                return f"tamamlama/{of_season}/{lg.openfootball}.json", of.data, None
            return (f"tamamlama/{of_season}/{lg.openfootball}.txt", of.txt,
                    {"bicim": TXT_FORMAT, "donusturucu": TXT_CONVERTER, "kaynak": of.source})

        base = matches[matches["source"].astype(str) != COMPLETION_LABEL]
        added, records = [], []
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        for code in leagues:
            lg = LEAGUES[code]
            g = base[base["league"] == code]
            if not lg.openfootball or g.empty:
                continue
            last = pd.Timestamp(g["date"].max()).date()
            cur = openfootball_season(today, lg.calendar_year)
            seasons = [cur]
            prev = openfootball_season(today - dt.timedelta(days=365), lg.calendar_year)
            if prev != cur and last < today - dt.timedelta(days=60):  # depo önceki sezonda kalmış olabilir
                seasons.insert(0, prev)
            n_lg = 0
            for of_season in seasons:
                of = self._openfootball_file(dl, gh, code, of_season, force, report)
                if of is None:
                    continue
                season = _norm_season(of_season, lg.calendar_year)
                rows, names = select_rows(of.data, code, season, base, last, today)
                if rows.empty:
                    continue
                rel, proof, fmt = proof_of(of, lg, of_season)
                path = self.raw_dir / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(proof)  # kökenin kanıtı: kullanılan baytların birebir kopyası
                records.append(build_record(code, season, of_season, proof, rel, last, today, rows, names, now, fmt))
                added.append(rows)
                n_lg += len(rows)
            if n_lg:
                report.completed[code] = n_lg
        # Önceki güncellemenin tamamlama satırları her zaman yeniden üretilir (kaydı olmayan satır kalmaz)
        if not added:
            return (base.reset_index(drop=True) if len(base) != len(matches) else matches), []
        out = self._clean_matches(pd.concat([base] + added, ignore_index=True))
        return out, records

    def _from_espn(self, dl, leagues, matches, today, days, report, force):
        """KAYNAK-04: football-data'dan ve openfootball'dan güncel verisi gelmeyen ligler için ESPN skor tablosu
        (``data.espn``). Bir önceki sezonun başından fikstür penceresinin sonuna kadar aylık istek atılır; tamamlanmış
        ayların yanıtları önbellekte kalır. Takım adları yalnızca kanıtla eşlenir.

        Döner: (veri, fikstür satırları | None, eşleşmeyen fikstürler, eşleme kayıtları). Önceki güncellemenin ESPN
        satırları her seferinde yeniden kurulur."""
        from collections import Counter

        from .completion import COMPLETION_LABEL
        from .espn import ESPN_LABEL, ESPN_LEAGUES, ESPN_MATCHING, ESPN_PARSER, PAIR_DAYS
        from .espn import SKIP_REASONS as ESPN_SKIPS
        from .espn import calendar_json, map_teams, month_chunks, parse_scoreboard, scoreboard_url
        from .leagues import season_for_date, season_start_year

        src = matches["source"].astype(str)
        keep = matches[src != ESPN_LABEL]
        base_all = matches[~src.isin({COMPLETION_LABEL, ESPN_LABEL})]
        added, fixtures, unmatched, meta = [], [], [], {}
        lo, hi = today, today + dt.timedelta(days=days)
        for code in leagues:
            slug = ESPN_LEAGUES.get(code)
            if slug is None or report.leagues.get(code) == "football-data.co.uk":
                continue
            lg = LEAGUES[code]
            cal = lg.calendar_year
            of_cur = openfootball_season(today, cal)
            if lg.openfootball and self._openfootball_file(dl, None, code, of_cur, force, report) is not None:
                continue  # openfootball'da güncel sezon dosyası var: ESPN gerekmez
            base = base_all[base_all["league"] == code]
            if base.empty:
                continue
            y = today.year if cal else season_start_year(today)
            cur_start = dt.date(y, 1, 1) if cal else dt.date(y, 7, 1)
            prev_start = dt.date(y - 1, 1, 1) if cal else dt.date(y - 1, 7, 1)
            events, skips, errors = {}, Counter(), []
            for a, b in month_chunks(prev_start, hi):
                rel = f"espn/{slug}/{a:%Y-%m}.json"
                p = dl.cache_path(rel)
                try:  # ay bitip sonuçlar oturduktan SONRA alınmış yanıt değişmez; diğerleri saatlik yenilenir
                    done = (b < today - dt.timedelta(days=3) and p.exists()
                            and dt.date.fromtimestamp(p.stat().st_mtime) > b + dt.timedelta(days=3))
                except OSError:
                    done = False
                try:
                    data = dl.get(scoreboard_url(slug, a, b), rel, None if done else 1.0, force)
                except DownloadError as e:
                    errors.append("bağlantı kurulamadı" if e.network or e.status is None else f"HTTP {e.status}")
                    if e.network:
                        break
                    continue
                pr = parse_scoreboard(data, lg.country)
                skips.update(pr.skipped)
                events.update({ev.event_id: ev for ev in pr.events})
            if not events:
                report.warnings.append(f"{lg.label}: ESPN'den veri alınamadı" + (f" ({errors[0]})" if errors else "")
                                       + "; bu lig için yaklaşan maç ve yeni sonuç eklenmedi.")
                continue
            evs = sorted(events.values(), key=lambda e: (e.date, e.time, e.event_id))
            cur = [e for e in evs if e.date >= cur_start]
            tm = map_teams(evs, base, code, season_for_date(today, cal), cur)
            cur_names = {e.home for e in cur} | {e.away for e in cur}
            # Sonuçlar: depodaki son maç gününden sonra oynanmış, iki adı da eşlenmiş ve depoda olmayan maçlar
            last = pd.Timestamp(base["date"].max()).date()
            have: dict = {}
            for h, a, d in zip(base["home"], base["away"], base["date"]):
                have.setdefault((h, a), []).append(pd.Timestamp(d).date())
            rows = []
            for e in cur:
                if e.ft is None or not (last < e.date < today):
                    continue
                h, a = tm.mapping.get(e.home), tm.mapping.get(e.away)
                if h is None or a is None or h == a or any(abs((d - e.date).days) <= PAIR_DAYS
                                                           for d in have.get((h, a), ())):
                    continue
                rows.append({"league": code, "season": season_for_date(e.date, cal), "date": pd.Timestamp(e.date),
                             "time": e.time, "home": h, "away": a, "fthg": e.ft[0], "ftag": e.ft[1],
                             "hthg": float(e.ht[0]) if e.ht else np.nan, "htag": float(e.ht[1]) if e.ht else np.nan,
                             "source": ESPN_LABEL})
            if rows:
                added.append(pd.DataFrame(rows).reindex(columns=MATCH_COLUMNS))
            # Fikstür: oynanmamış maçlar (pencere içinde)
            n_fx = 0
            for e in cur:
                if e.ft is not None or e.state not in ("pre", "in") or not (lo <= e.date <= hi):
                    continue
                h, a = tm.mapping.get(e.home), tm.mapping.get(e.away)
                if h is not None and a is not None and h != a:
                    n_fx += 1
                    fixtures.append({"league": code, "date": pd.Timestamp(e.date), "time": e.time, "home": h,
                                     "away": a, "source": ESPN_LABEL, "raw_home": e.home, "raw_away": e.away,
                                     "provider_id": e.event_id,
                                     "eslesme": f"{ESPN_MATCHING}:{tm.basis.get(e.home)}|{tm.basis.get(e.away)}"})
                    continue
                unmatched.append({
                    "league": code, "date": str(e.date), "time": e.time, "raw_home": e.home, "raw_away": e.away,
                    "source": ESPN_LABEL, "provider_id": e.event_id,
                    "eslesme_durumu": "AYNI_TAKIM" if h is not None and h == a else "BULUNAMADI",
                    "eslesme_surumu": ESPN_MATCHING,
                    "oneriler": {"ev": [str(x) for x in tm.unmapped.get(e.home, ("", ()))[1]],
                                 "deplasman": [str(x) for x in tm.unmapped.get(e.away, ("", ()))[1]]}})
            # Sezon takvimleri (uygunluk kontrolü bilinen eksiği buradan görür; ``eligibility.cached_coverages``)
            prev_of = openfootball_season(cur_start - dt.timedelta(days=1), cal)
            for of_season, group in ((of_cur, cur), (prev_of, [e for e in evs if e.date < cur_start])):
                if not group:
                    continue
                path = self.raw_dir / "espn" / of_season / f"{code}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(path.name + ".part")
                tmp.write_bytes(calendar_json(group, tm, f"ESPN {slug} {of_season}"))
                tmp.replace(path)
            miss = sorted(n for n in tm.unmapped if n in cur_names)
            report.espn[code] = {"fikstur": n_fx, "sonuc": len(rows), "eslesen": len(tm.mapping), "eslesmeyen": miss}
            if miss:
                report.warnings.append(
                    f"{lg.label}: ESPN'deki {len(miss)} takım adı veri deposundaki bir takımla kanıtla eşleşmedi ("
                    + ", ".join(miss[:6]) + ("…" if len(miss) > 6 else "")
                    + "); bu takımların maçları 'tahmin yok' olarak gösterilir, sonuçları eklenmez.")
            if skips:
                report.warnings.append(f"{lg.label}: ESPN'de {sum(skips.values())} kayıt okunmadı ("
                                       + "; ".join(f"{v} × {ESPN_SKIPS.get(k, k)}" for k, v in sorted(skips.items()))
                                       + "). Bu maçlar uydurulmadı.")
            meta[code] = {**tm.record(), "ayristirici": ESPN_PARSER}
        if added:
            out = self._clean_matches(pd.concat([keep] + added, ignore_index=True))
        else:
            out = keep.reset_index(drop=True) if len(keep) != len(matches) else matches
        fx = pd.DataFrame(fixtures) if fixtures else None
        return out, fx, unmatched, meta

    def _update_fixtures(self, dl, leagues, matches, today, days, report, force, allowed, gh=None,
                         extra_fixtures: pd.DataFrame | None = None) -> pd.DataFrame:
        lo = pd.Timestamp(today)
        hi = pd.Timestamp(today) + pd.Timedelta(days=days)
        frames = []
        for name in ("fixtures.csv", "new_league_fixtures.csv") if "football-data" in allowed else ():
            try:
                data = dl.get(f"{FD_BASE}/{name}", f"fd/{name}", FIXTURES_MAX_AGE_H, force)
                frames.append(normalize_fixtures(read_csv_robust(data)))
            except DownloadError:
                continue
            except Exception as e:
                report.warnings.append(f"{name} okunamadı: {e}")
        fd = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=FIXTURE_COLUMNS)
        fd = fd[fd["league"].isin(leagues) & (fd["date"] >= lo) & (fd["date"] <= hi)]
        canon = _spelling_index(matches)
        if canon and not fd.empty:  # football-data fikstüründe de maç verisindeki yazım kullanılır
            fd = fd.copy()
            for col in ("home", "away"):
                fd[col] = [canon.get((_country(lg), spelling_key(t)), t) for lg, t in zip(fd["league"], fd[col])]

        from ..eligibility import PENDING_GRACE_DAYS

        extra = []
        for code in leagues if "openfootball" in allowed else ():
            lg = LEAGUES[code]
            if not lg.openfootball:
                continue
            last_fd = fd.loc[fd["league"] == code, "date"].max()
            known = self._recent_teams(matches, code)
            if not known:
                continue
            season = openfootball_season(today, lg.calendar_year)
            src = self._openfootball_file(dl, gh, code, season, force, report)
            if src is None:
                continue
            data = src.data
            allof = parse_openfootball(data, code, keep_provider_id=True)
            of = allof[(allof["date"] >= lo) & (allof["date"] <= hi)]
            if pd.notna(last_fd):
                of = of[of["date"] > last_fd]
            if of.empty:
                continue
            of = of.copy()
            # Kaynağın kendisi geride mi: tarihi (sonuç gecikme payından da) geçmiş, sonucu ne kaynakta ne veride olan
            # maçlar. Bu durumda kaynağın yaklaşan maç tarihleri de güncellenmemiş olabilir.
            last_known = matches.loc[matches["league"] == code, "date"].max()
            stale = allof[(allof["date"] < lo - pd.Timedelta(days=PENDING_GRACE_DAYS))
                          & ((allof["date"] > last_known) if pd.notna(last_known) else True)]
            if len(stale) >= 3:
                report.warnings.append(
                    f"{lg.label}: kaynak takviminde tarihi geçmiş ama sonucu hiçbir kaynakta olmayan {len(stale)} maç var "
                    f"(en eskisi {pd.Timestamp(stale['date'].min()):%d.%m.%Y}); kaynak geride, yaklaşan maçların "
                    "tarihleri kesin olmayabilir.")
            # Kimlik bağlamı: dosyadaki bütün adlar (ters çakışma denetimi) + ligin son iki sezonundaki takımlar.
            # Yalnızca KESİN kimlik eşleşir; belirsiz/benzer adlar eşleşmemiş olarak ham adlarıyla saklanır.
            res = resolve_teams(openfootball_team_names(data) + list(of["home"]) + list(of["away"]), known, code,
                                "openfootball")
            hm = [res[str(t)] for t in of["home"]]
            am = [res[str(t)] for t in of["away"]]
            ok = pd.Series([h.exact and a.exact and h.team != a.team for h, a in zip(hm, am)], index=of.index)
            of["raw_home"], of["raw_away"] = of["home"].astype(str), of["away"].astype(str)
            of["eslesme"] = [f"{h.evidence()}|{a.evidence()}" for h, a in zip(hm, am)]
            of["home"] = [h.team if k else None for h, k in zip(hm, ok)]
            of["away"] = [a.team if k else None for a, k in zip(am, ok)]
            unmatched = ~ok
            if unmatched.any():
                report.warnings.append(
                    f"{lg.label}: {int(unmatched.sum())} fikstür maçında takım adı kesin olarak eşleştirilemedi "
                    "(nedenli 'tahmin yok' olarak gösterilir)."
                )
                for i, h, a, k in zip(of.index, hm, am, ok):
                    if k:
                        continue
                    status = ("AYNI_TAKIM" if h.exact and a.exact else
                              BELIRSIZ if BELIRSIZ in (h.status, a.status) else "BULUNAMADI")
                    pid = of.at[i, "provider_id"]
                    self._last_unmatched.append({
                        "league": code, "date": str(pd.Timestamp(of.at[i, "date"]).date()),
                        "time": str(of.at[i, "time"] or "") if "time" in of else "",
                        "raw_home": h.name, "raw_away": a.name, "source": "openfootball",
                        "provider_id": None if pd.isna(pid) else str(pid), "eslesme_durumu": status,
                        "eslesme_surumu": MATCHING_VERSION,
                        "oneriler": {"ev": list(h.suggestions or h.candidates),
                                     "deplasman": list(a.suggestions or a.candidates)}})
            no_time = int((of["time"].fillna("").astype(str) == "").sum())
            if no_time:
                report.warnings.append(f"{lg.label}: {no_time} yaklaşan maçın saati kaynakta yok (tarih kesinleşmemiş "
                                       "olabilir; 'saat bilinmiyor' gösterilir).")
            extra.append(of[~unmatched])
        if extra_fixtures is not None and not extra_fixtures.empty:
            extra.append(extra_fixtures)
        fx = pd.concat([fd] + extra, ignore_index=True) if extra else fd
        if fx.empty:
            return pd.DataFrame(columns=FIXTURE_COLUMNS)
        # Oynanmış maçları çıkar
        if not matches.empty:
            played = set(zip(matches["league"], matches["home"], matches["away"], matches["date"]))
            fx = fx[[(lg, h, a, d) not in played for lg, h, a, d in zip(fx["league"], fx["home"], fx["away"], fx["date"])]]
        fx = fx.drop_duplicates(subset=["league", "date", "home", "away"], keep="first")
        return fx.sort_values(["date", "time", "league"], kind="mergesort").reset_index(drop=True)

    @staticmethod
    def _recent_teams(matches: pd.DataFrame, league: str, seasons: int = 2) -> list[str]:
        m = matches[matches["league"] == league]
        if m.empty:
            return []
        recent = sorted(m["season"].unique())[-seasons:]
        m = m[m["season"].isin(recent)]
        return sorted(set(m["home"]) | set(m["away"]))

    # --------------------------------------------------------------- queries
    def league_matches(self, league: str) -> pd.DataFrame:
        return self.matches[self.matches["league"] == league]

    def teams(self, league: str, seasons: int = 1) -> list[str]:
        return self._recent_teams(self.matches, league, seasons)

    def available_leagues(self) -> list[str]:
        present = set(self.matches["league"].unique())
        return [c for c in LEAGUES if c in present]

    def summary(self) -> pd.DataFrame:
        if self.matches.empty:
            return pd.DataFrame(columns=["league", "seasons", "matches", "first", "last", "source"])
        g = self.matches.groupby("league")
        out = pd.DataFrame({
            "seasons": g["season"].nunique(),
            "matches": g.size(),
            "first": g["date"].min().dt.date,
            "last": g["date"].max().dt.date,
            "source": g["source"].agg(lambda s: ", ".join(sorted(set(s)))),
        }).reset_index()
        order = {c: i for i, c in enumerate(LEAGUES)}
        return out.sort_values("league", key=lambda s: s.map(order)).reset_index(drop=True)


def _country(code: str) -> str:
    lg = LEAGUES.get(code)
    return lg.country if lg is not None else str(code)


def _spelling_index(m: pd.DataFrame) -> dict:
    """(ülke, yazım anahtarı) -> maç verisindeki ad (``UNIFY_SOURCES`` satırları; ``unify_spellings`` sonrası tekildir)."""
    if m is None or m.empty or "source" not in m:
        return {}
    sel = m[m["source"].isin(UNIFY_SOURCES)]
    out: dict = {}
    for col in ("home", "away"):
        for lg, t in zip(sel["league"].astype(str), sel[col].astype(str)):
            out.setdefault((_country(lg), spelling_key(t)), t)
    return out


def unify_spellings(m: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Aynı ülkenin liglerinde yalnızca yazımı farklı takım adlarını (``teams.spelling_key``) tek yazıma indirir.

    Seçilen yazım, o ülkede en son kullanılan yazımdır (eşitlikte en sık kullanılan). Yalnızca ``UNIFY_SOURCES``
    satırları değişir. Dönüş: (veri, {(ülke, eski ad): yeni ad})."""
    if m is None or m.empty or "source" not in m:
        return m, {}
    sel = m["source"].isin(UNIFY_SOURCES).to_numpy()
    if not sel.any():
        return m, {}
    country = m["league"].astype(str).map(_country).to_numpy()
    dates = pd.to_datetime(m["date"]).to_numpy()
    names: dict[tuple, dict[str, list]] = {}
    for col in ("home", "away"):
        for c, t, d, ok in zip(country, m[col].astype(str), dates, sel):
            if not ok:
                continue
            k = spelling_key(t)
            if not k:
                continue
            st = names.setdefault((c, k), {}).setdefault(t, [d, 0])
            st[0] = max(st[0], d)
            st[1] += 1
    renames: dict[tuple, str] = {}
    for (c, _), spellings in names.items():
        if len(spellings) < 2:
            continue
        canon = max(spellings, key=lambda n: (spellings[n][0], spellings[n][1], n))
        renames.update({(c, n): canon for n in spellings if n != canon})
    if not renames:
        return m, {}
    m = m.copy()
    for col in ("home", "away"):
        m[col] = [renames.get((c, t), t) if ok else t for c, t, ok in zip(country, m[col], sel)]
    return m, renames


class _GitHubUnavailable(Exception):
    """GitHub profilinde dosya alınamadı ve doğrulanmış kopyası da yok (başka kaynağa geçilmez)."""


class _GitHubFiles:
    """GitHub profili için depo başına bir kez çözülen commit'ten, özeti doğrulanan önbellekle dosya alımı."""

    def __init__(self, raw_dir: Path, transport, report: UpdateReport):
        from .github_kaynak import GitHubCache, GitHubTransport

        self._cache = GitHubCache(raw_dir)
        self.transport = transport if transport is not None else GitHubTransport()
        self.report = report
        self.commits: dict[str, tuple[str, str, str]] = {}
        self.network = self.cache_hits = 0
        self.stale: list[str] = []

    def get(self, repo: str, path: str) -> bytes:
        from .github_kaynak import FETCHED, STALE_COPY, GitHubError

        spec = REPOS.get(repo) or TXT_REPO_SPECS[repo]
        try:
            if repo not in self.commits:
                self.commits[repo] = self._cache.resolve(self.transport, spec)
            commit, ref_status, note = self.commits[repo]
        except GitHubError as e:
            self.report.github[repo] = {"commit": None, "durum": e.kind, "aciklama": f"alınamadı: {e}"}
            raise _GitHubUnavailable(str(e)) from e
        try:
            cf = self._cache.get(self.transport, repo, commit, path)
        except GitHubError as e:
            # Bu commit'in dosyası alınamadı: daha önce kaydedilmiş bir commit'in DOĞRULANMIŞ kopyası varsa açıkça
            # "eski kopya" olarak kullanılır; yoksa kaynak atlanır (başka siteye geçilmez).
            cf = None
            for old in reversed(self._cache.ref_history().get(repo) or []):
                if old["commit"] == commit:
                    continue
                try:
                    cf = self._cache.read(repo, old["commit"], path)
                except GitHubError:
                    cf = None
                if cf is not None:
                    commit, ref_status, note = old["commit"], STALE_COPY, f"dosya alınamadı ({e.kind}); {note}"
                    break
            if cf is None:
                # Depoda olmayan tek dosya (ör. ligin o sezon dosyası yok), aynı depodan alınmış dosyaların durumunu ezmez
                if not (e.kind == "BULUNAMADI" and repo in self.report.github):
                    self.report.github[repo] = {"commit": commit, "durum": e.kind, "aciklama": f"alınamadı: {e}"}
                raise _GitHubUnavailable(str(e)) from e
        status = STALE_COPY if ref_status == STALE_COPY else cf.status
        if cf.status == FETCHED:
            self.network += 1
        else:
            self.cache_hits += 1
        if status == STALE_COPY:
            self.stale.append(f"{repo}@{commit[:12]}:{path}")
        self.report.github[repo] = {"commit": commit, "uc_durumu": ref_status, "uc_notu": note, "durum": status,
                                    "aciklama": f"{STATUS_TEXT.get(status, status)}; {note}"}
        return cf.data

"""Maç verilerini indirir, birleştirir ve diskte saklar."""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

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
from .teams import BELIRSIZ, MATCHING_VERSION, resolve_teams

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, str], None]

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

    def summary(self) -> str:
        lines = [
            f"{self.n_matches} maç, {self.n_fixtures} yaklaşan maç yüklendi "
            f"({self.downloaded} dosya indirildi, {self.from_cache} dosya önbellekten).",
        ]
        if self.used_mirror:
            lines.append("football-data.co.uk'a ulaşılamadığı için GitHub yedek veri seti kullanıldı.")
        for key in self.blocked_sources:
            lines.append(f"{SOURCES[key].name}: kullanım koşulları onaylanmadığı için kullanılmadı.")
        lines += self.warnings
        return "\n".join(lines)


class DataStore:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.raw_dir = self.home / "raw"
        self.matches = pd.DataFrame(columns=MATCH_COLUMNS)
        self.fixtures = pd.DataFrame(columns=FIXTURE_COLUMNS)
        self.meta: dict = {}
        self._last_unmatched: list[dict] = []

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
    ) -> UpdateReport:
        """Verileri indirir. ``allowed``: kullanılmasına izin verilen kaynak anahtarları
        (bkz. ``source_registry``); verilmezse yalnızca onay gerektirmeyen kaynaklar kullanılır."""
        today = today or dt.date.today()
        progress = progress or (lambda p, m: None)
        dl = downloader or Downloader(self.raw_dir)
        report = UpdateReport()
        allowed = allowed_sources(None) if allowed is None else set(allowed)
        use_fd = "football-data" in allowed
        use_mirror_fallback = use_mirror_fallback and "github-mirror" in allowed
        for key in ("football-data", "github-mirror"):
            if key not in allowed:
                report.blocked_sources.append(key)
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

        progress(88, "Veriler birleştiriliyor...")
        if frames:
            matches = pd.concat([f for f in frames if not f.empty], ignore_index=True)
        else:
            matches = pd.DataFrame(columns=MATCH_COLUMNS)
        matches = self._clean_matches(matches)
        if matches.empty and self.has_data:
            report.warnings.append("Yeni veri alınamadı; mevcut veriler korunuyor.")
            matches = self.matches[self.matches["league"].isin(leagues)]

        progress(92, "Yaklaşan maçlar (fikstür) alınıyor...")
        self._last_unmatched = []
        fixtures = self._update_fixtures(dl, leagues, matches, today, fixture_days, report, force, allowed)

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
        })
        report.n_matches = len(self.matches)
        report.n_fixtures = len(self.fixtures)
        report.downloaded = dl.stats["network"]
        report.from_cache = dl.stats["cache"]
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

    def _update_fixtures(self, dl, leagues, matches, today, days, report, force, allowed) -> pd.DataFrame:
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
            url = f"{OPENFOOTBALL_BASE}/{season}/{lg.openfootball}.json"
            try:
                data = dl.get(url, f"openfootball/{season}/{lg.openfootball}.json", 6.0, force)
            except DownloadError:
                continue
            of = parse_openfootball(data, code, keep_provider_id=True)
            of = of[(of["date"] >= lo) & (of["date"] <= hi)]
            if pd.notna(last_fd):
                of = of[of["date"] > last_fd]
            if of.empty:
                continue
            of = of.copy()
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
            extra.append(of[~unmatched])
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

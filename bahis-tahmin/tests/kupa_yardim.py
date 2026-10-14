"""KUPA-01 testleri için SENTETİK yardımcılar: iki lig (İngiltere, Türkiye) + Avrupa kupası dünyası.

Buradaki maçlar, takım güçleri, openfootball dosyaları ve ESPN yanıtları AÇIKÇA SENTETİKTİR (kaynak etiketi
``sentetik``). Ligler arasındaki güç farkı yalnızca kupa maçlarında görünür: lig maçlarında ligin hücum ve savunma
kayması birbirini götürür. Gerçek maç analizi veya gerçek entegrasyon kanıtı değildir.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

UTC = dt.timezone.utc
E0 = ["Arsenal", "Chelsea", "Liverpool", "Man City", "Man United", "Tottenham", "Newcastle", "Aston Villa",
      "Brighton", "West Ham"]
T1 = ["Galatasaray", "Fenerbahce", "Besiktas", "Trabzonspor", "Basaksehir", "Konyaspor", "Antalyaspor", "Sivasspor",
      "Kasimpasa", "Alanyaspor"]
WORLD = {"E0": ("İngiltere", E0, 0.30), "T1": ("Türkiye", T1, -0.20)}  # lig -> (ülke, takımlar, lig gücü kayması)
SLAVIA_KEY = "CZE|slavia praha"  # ligi veride olmayan takım (openfootball kimliği)
# openfootball ve ESPN'deki adlar depodaki adlardan farklı yazılır (kimlik yalnızca kanıtla kurulur)
OF_NAME = {"Man City": "Manchester City FC", "Fenerbahce": "Fenerbahçe SK", "Besiktas": "Beşiktaş JK",
           "Galatasaray": "Galatasaray AŞ"}
ESPN_NAME = {"Man City": "Manchester City"}
ESPN_ID = {**{n: str(100 + i) for i, n in enumerate(E0)}, **{n: str(200 + i) for i, n in enumerate(T1)},
           "Slavia Praha": "999"}
SEASONS = 5  # 2021/22 – 2025/26
AS_OF = dt.datetime(2026, 9, 14, 12, 0, tzinfo=UTC)  # bütün sezonlardan sonra (uygunluk testleri)
CUP_DAY = dt.date(2026, 9, 16)


def _first_weekday(d: dt.date, weekday: int) -> dt.date:
    return d + dt.timedelta(days=(weekday - d.weekday()) % 7)


def world(seed: int = 11, seasons: int = SEASONS, cup_weeks: int = 30, per_week: int = 6):
    """(lig maçları, kupa maçları). Lig sezonu Ağustos–Aralık; Şampiyonlar Ligi salı günleri (haftada ``per_week``
    İngiltere–Türkiye maçı), Avrupa Ligi her beş haftada bir perşembe (Slavia Praha – bir Türk takımı)."""
    from bahis_tahmin.data.leagues import season_label
    from bahis_tahmin.data.parsers import MATCH_COLUMNS
    from bahis_tahmin.kupa.veri import CUP_MATCH_COLUMNS

    rng = np.random.default_rng(seed)
    strength = {}
    dom = []
    for lg, (ctry, names, off) in WORLD.items():
        n = len(names)
        att, dfn = rng.normal(0, 0.25, n), rng.normal(0, 0.25, n)
        strength[lg] = (ctry, names, att + off, dfn + off)
        for s in range(seasons):
            y = 2021 + s
            pairs = [(i, j) for i in range(n) for j in range(n) if i != j]
            rng.shuffle(pairs)
            for k, (i, j) in enumerate(pairs):
                d = pd.Timestamp(y, 8, 7) + pd.Timedelta(days=7 * (k // (n // 2)))
                lam, nu = np.exp(0.45 + att[i] - dfn[j]), np.exp(0.2 + att[j] - dfn[i])
                hg, ag = int(rng.poisson(lam)), int(rng.poisson(nu))
                dom.append({"league": lg, "season": season_label(y), "date": d, "time": "19:00", "home": names[i],
                            "away": names[j], "fthg": hg, "ftag": ag, "hthg": int(rng.binomial(hg, 0.45)),
                            "htag": int(rng.binomial(ag, 0.45)), "source": "sentetik"})
    dom = pd.DataFrame(dom).reindex(columns=MATCH_COLUMNS)

    def side(x):
        if x[0] == "X":
            return "CZE", "Slavia Praha", -0.1, -0.1, SLAVIA_KEY, False
        ctry, names, at, df = strength[x[0]]
        return ctry, names[x[1]], at[x[1]], df[x[1]], f"{ctry}|{names[x[1]]}", True

    cups = []
    for s in range(seasons):
        y = 2021 + s
        tue = _first_weekday(dt.date(y, 9, 15), 1)
        for w in range(cup_weeks):
            d = tue + dt.timedelta(days=7 * w)
            ei, ti = rng.permutation(len(E0))[:per_week], rng.permutation(len(T1))[:per_week]
            games = [("UCL", d, ("E0", a), ("T1", b)) if rng.random() < 0.5 else ("UCL", d, ("T1", b), ("E0", a))
                     for a, b in zip(ei, ti)]
            if w % 5 == 0:
                b = int(rng.integers(len(T1)))
                thu = d + dt.timedelta(days=2)
                games.append(("UEL", thu, ("X", 0), ("T1", b)) if rng.random() < 0.5 else ("UEL", thu, ("T1", b),
                                                                                           ("X", 0)))
            for comp, day, h, a in games:
                hc, hn, ha_, hd, hk, hm = side(h)
                ac, an, aa, ad, ak, am = side(a)
                lam, nu = np.exp(0.45 + ha_ - ad), np.exp(0.2 + aa - hd)
                hg, ag = int(rng.poisson(lam)), int(rng.poisson(nu))
                cups.append({"comp": comp, "season": season_label(y), "stage": "", "date": pd.Timestamp(day),
                             "time": "21:00", "home": hn, "away": an, "home_key": hk, "away_key": ak,
                             "home_country": hc, "away_country": ac, "home_mapped": hm, "away_mapped": am,
                             "fthg": hg, "ftag": ag, "hthg": float(rng.binomial(hg, 0.45)),
                             "htag": float(rng.binomial(ag, 0.45)), "extra_time": False, "neutral": False,
                             "source": "sentetik", "provider_id": f"syn:{len(cups)}", "home_raw": hn, "away_raw": an})
    return dom, pd.DataFrame(cups, columns=CUP_MATCH_COLUMNS)


# ------------------------------------------------------------------------------------------ openfootball dosyaları


_DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _of_team(name: str, country: str) -> str:
    if country == "CZE":
        return "SK Slavia Praha (CZE)"
    cc = "ENG" if country == "İngiltere" else "TUR"
    return f"{OF_NAME.get(name, name + (' FC' if cc == 'ENG' else ''))} ({cc})"


def openfootball_files(cups: pd.DataFrame) -> dict[str, bytes]:
    """Sezon klasörü/dosya -> Football.TXT baytları (bütün maçlar oynanmış)."""
    from bahis_tahmin.kupa.turnuvalar import COMPETITIONS

    out = {}
    for (comp, season), g in cups.groupby(["comp", "season"]):
        y = int(str(season)[:4])
        lines = [f"= {COMPETITIONS[comp].full} {season}", ""]
        for k, (d, gd) in enumerate(g.groupby("date"), start=1):
            # İngilizce gün/ay adları elle (strftime yerel ayara bağlıdır)
            lines += [f"▪ League, Matchday {k}", f"  {_DOW[d.weekday()]} {_MON[d.month - 1]} {d.day} {d.year}"]
            for r in gd.itertuples(index=False):
                lines.append(f"    21:00  {_of_team(r.home, r.home_country)}  v {_of_team(r.away, r.away_country)}"
                             f"   {r.fthg}-{r.ftag} ({int(r.hthg)}-{int(r.htag)})")
        out[f"{y}-{(y + 1) % 100:02d}/{COMPETITIONS[comp].of_stem}.txt"] = "\n".join(lines).encode("utf-8")
    return out


# ------------------------------------------------------------------------------------------ ESPN yanıtları


def espn_event(eid: str, day, home: str, away: str, hid: str, aid: str, ft=None, ht=None, name: str | None = None,
               linescores=None, neutral: bool = False, utc: str = "18:00") -> dict:
    """ESPN skor tablosu olayı (``data.espn.parse_scoreboard`` biçimi)."""
    def comp_side(where, team, tid, k):
        c = {"homeAway": where, "team": {"id": tid, "displayName": team}, "score": str(ft[k]) if ft else "0"}
        if linescores is not None:
            c["linescores"] = [{"value": float(v)} for v in linescores[k]]
        elif ht is not None and ft is not None:
            c["linescores"] = [{"value": float(ht[k])}, {"value": float(ft[k] - ht[k])}]
        return c

    name = name or ("STATUS_FULL_TIME" if ft else "STATUS_SCHEDULED")
    comp = {"date": f"{pd.Timestamp(day):%Y-%m-%d}T{utc}Z", "neutralSite": neutral,
            "competitors": [comp_side("home", home, hid, 0), comp_side("away", away, aid, 1)],
            "status": {"type": {"name": name, "state": "post" if ft else "pre", "completed": bool(ft)}}}
    return {"id": str(eid), "date": comp["date"], "competitions": [comp]}


def _espn_name(n: str) -> str:
    return ESPN_NAME.get(n, n)


def espn_world(dom: pd.DataFrame, cups: pd.DataFrame, today: dt.date, cup_seasons=("2024/25", "2025/26")) -> dict:
    """ESPN kısa adı -> [(gün, olay)]: lig maçları (eng.1, tur.1) ve kupa maçları (son iki sezon; bugünden sonrası
    oynanmamış)."""
    out: dict = {"eng.1": [], "tur.1": [], "uefa.champions": [], "uefa.europa": []}
    for i, r in enumerate(dom.itertuples(index=False)):
        slug = "eng.1" if r.league == "E0" else "tur.1"
        d = pd.Timestamp(r.date).date()
        played = d < today
        ft = (int(r.fthg), int(r.ftag)) if played else None
        ht = (int(r.hthg), int(r.htag)) if played else None
        out[slug].append((d, espn_event(f"L{i}", d, _espn_name(r.home), _espn_name(r.away), ESPN_ID[r.home],
                                        ESPN_ID[r.away], ft, ht, utc="15:00")))
    for i, r in enumerate(cups[cups["season"].isin(cup_seasons)].itertuples(index=False)):
        slug = "uefa.champions" if r.comp == "UCL" else "uefa.europa"
        d = pd.Timestamp(r.date).date()
        played = d < today
        ft = (int(r.fthg), int(r.ftag)) if played else None
        ht = (int(r.hthg), int(r.htag)) if played else None
        out[slug].append((d, espn_event(f"K{i}", d, _espn_name(r.home), _espn_name(r.away), ESPN_ID[r.home],
                                        ESPN_ID[r.away], ft, ht)))
    return out


class FakeCupDownloader:
    """İnternete çıkmadan: openfootball kupa dosyaları sözlükten, ESPN skor tablosu tarih aralığına göre."""

    def __init__(self, of_files: dict, espn: dict | None, cache: Path):
        from bahis_tahmin.kupa.openfootball import CUP_RAW_BASE

        self.base = CUP_RAW_BASE
        self.of_files, self.espn, self.cache = of_files, espn, Path(cache)
        self.requested: list[str] = []

    def cache_path(self, rel):
        return self.cache / rel

    def get(self, url, cache_rel, max_age_hours=None, force=False):
        from bahis_tahmin.data.espn import ESPN_BASE
        from bahis_tahmin.data.sources import DownloadError

        self.requested.append(url)
        if url.startswith(self.base + "/"):
            path = url[len(self.base) + 1:]
            if path in self.of_files:
                return self.of_files[path]
            raise DownloadError(url, "dosya bulunamadı (404)", 404)
        if url.startswith(ESPN_BASE) and self.espn is not None:
            u = urlparse(url)
            slug = u.path.split("/soccer/")[1].split("/")[0]
            a, b = parse_qs(u.query)["dates"][0].split("-")
            lo, hi = dt.datetime.strptime(a, "%Y%m%d").date(), dt.datetime.strptime(b, "%Y%m%d").date()
            evs = [e for d, e in self.espn.get(slug, []) if lo <= d <= hi]
            return json.dumps({"events": evs}).encode("utf-8")
        raise DownloadError(url, "bağlantı kurulamadı")


# ------------------------------------------------------------------------------------------ uygunluk bağlamı


def league_context(dom: pd.DataFrame, as_of: dt.datetime = AS_OF, mode: str = "standart", next_start=None,
                   drop: set | None = None):
    """İki ligin bütün sezonlarının tam SENTETİK takvimi + yeni sezon fikstürü (karar anından sonra başlar)."""
    from uygunluk_yardim import next_season_schedule, season_coverage, synthetic_rights

    from bahis_tahmin.eligibility import EligibilityContext

    ret = as_of - dt.timedelta(hours=2)
    covs = {}
    for lg in WORLD:
        g = dom[dom["league"] == lg]
        covs[lg] = [season_coverage(g, s, ret, league=lg, drop=drop) for s in sorted(g["season"].unique())]
        covs[lg].append(next_season_schedule(g, next_start or (as_of.date() + dt.timedelta(days=5)), ret, "2026/27",
                                             league=lg))
    return EligibilityContext(dom, None, covs, rights=synthetic_rights(), mode=mode)


def write_cup_calendar(raw_dir: Path, comp: str, season: str, recs: list, at: dt.datetime) -> Path:
    """ESPN kupa takvimi dosyası (``kupa.veri.write_calendars`` biçimi), alınma anı ``at``."""
    import os

    p = Path(raw_dir) / "espn_kupa" / season.replace("/", "-") / f"{comp}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"turnuva": comp, "sezon": season, "kaynak": "espn", "maclar": recs}), encoding="utf-8")
    t = at.timestamp()
    os.utime(p, (t, t))
    return p

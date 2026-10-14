"""Kupa verisinin indirilmesi, birleştirilmesi ve kökeni (KUPA-01).

Kaynaklar:

* **openfootball/champions-league** (CC0, onay gerekmez): UEFA turnuvalarının geçmiş sezonları. Dosyanın kullanılan
  baytları özetiyle ayrıca saklanır; satırlar yalnızca bu kopyadan aynı okuyucuyla yeniden üretilebiliyorsa hak kazanır
  (``verify_cup_rows``; VERI-02 tamamlama kuralıyla aynı ilke).
* **ESPN** (kullanıcı onayıyla; GitHub profilinde kullanılmaz): bütün turnuvaların içinde bulunulan ve bir önceki
  sezonu (fikstür, sonuç, tarafsız saha bilgisi). ESPN takım numaraları ``kupa.kimlik`` ile kanıtla eşlenir; bunun için
  ESPN'deki yurt içi lig maçları (son ``EVIDENCE_DAYS`` gün) depodaki lig maçlarıyla karşılaştırılır.

Bir turnuvanın bir sezonu tek kaynaktan alınır: bitmiş sezonlarda openfootball dosyası varsa o, yoksa ESPN; içinde
bulunulan sezonda ESPN (yoksa openfootball). Lig maçlarının verisine (``DataStore.matches``) dokunulmaz.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .kimlik import KIMLIK_SURUMU, EspnMap, TeamIdentity, domestic_espn_ids, map_espn, map_openfootball
from .openfootball import CUP_LABEL, CUP_PARSER, CUP_RAW_BASE, CUP_REPO, SKIP_REASONS, parse_cup_txt
from .turnuvalar import COMPETITIONS, UEFA_REGION, openfootball_dir, season_bounds, season_label, season_start

CUP_MATCH_COLUMNS = ["comp", "season", "stage", "date", "time", "home", "away", "home_key", "away_key",
                     "home_country", "away_country", "home_mapped", "away_mapped", "fthg", "ftag", "hthg", "htag",
                     "extra_time", "neutral", "source", "provider_id", "home_raw", "away_raw"]
CUP_FIXTURE_COLUMNS = ["comp", "season", "stage", "date", "time", "home", "away", "home_key", "away_key",
                       "home_country", "away_country", "home_mapped", "away_mapped", "neutral", "source",
                       "provider_id"]
OF_FIRST_SEASON = 2011  # openfootball/champions-league ilk sezonu
OF_MAX_AGE_H = 6.0
ESPN_SEASONS = 2  # ESPN: içinde bulunulan + bir önceki sezon
EVIDENCE_DAYS = 100  # ESPN yurt içi lig kanıtı penceresi
MAX_FAILS = 3
PROOF_DIR = "kupa_koken"
CALENDAR_DIR = "espn_kupa"


def empty_matches() -> pd.DataFrame:
    return pd.DataFrame(columns=CUP_MATCH_COLUMNS)


def empty_fixtures() -> pd.DataFrame:
    return pd.DataFrame(columns=CUP_FIXTURE_COLUMNS)


def _tz_for(comp) -> object:
    """ESPN saatleri: UEFA ve kıta turnuvaları İstanbul saatiyle, yurt içi kupalar ülkenin saatiyle."""
    from ..data.espn import _tz
    from ..timeutil import ISTANBUL

    return _tz(comp.country) if comp.country else ISTANBUL


def rows_sha256(df: pd.DataFrame) -> str:
    """Kaynak satırlarının içerik özeti (sıra bağımsız): kaynakta yazan alanlar (eşleme sonucu değil)."""
    def cell(v) -> str:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return ""
        return "" if f != f else str(int(f))

    keys = sorted("|".join([str(c), str(se), str(pd.Timestamp(d).date()), str(h), str(a), cell(fh), cell(fa),
                            cell(hh), cell(ha)])
                  for c, se, d, h, a, fh, fa, hh, ha in zip(df["comp"], df["season"], df["date"], df["home_raw"],
                                                            df["away_raw"], df["fthg"], df["ftag"], df["hthg"],
                                                            df["htag"]))
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


def _raw_name(name: str, cc: str) -> str:
    return f"{name} ({cc})" if cc else name


def of_rows(recs: list, comp: str, season: str, label: str, ofmap) -> tuple[list, list]:
    """openfootball maç sözlükleri -> (sonuç satırları, oynanmamış maçlar)."""
    played, todo = [], []
    for r in recs:
        h = ofmap.get(label, r.get("cc1", ""), r["team1"])
        a = ofmap.get(label, r.get("cc2", ""), r["team2"])
        base = {"comp": comp, "season": season, "stage": r.get("round") or "", "date": pd.Timestamp(r["date"]),
                "time": r.get("time") or "", "home": h.name, "away": a.name, "home_key": h.key, "away_key": a.key,
                "home_country": h.country, "away_country": a.country, "home_mapped": h.mapped,
                "away_mapped": a.mapped, "neutral": bool(r.get("neutral")), "source": CUP_LABEL,
                "provider_id": f"{label}:{r.get('line')}",
                "home_raw": _raw_name(r["team1"], r.get("cc1", "")), "away_raw": _raw_name(r["team2"], r.get("cc2", ""))}
        sc = r.get("score")
        if sc is None:
            todo.append(base)
            continue
        ht = sc.get("ht")
        played.append(dict(base, fthg=int(sc["ft"][0]), ftag=int(sc["ft"][1]),
                           hthg=float(ht[0]) if ht else float("nan"), htag=float(ht[1]) if ht else float("nan"),
                           extra_time="et" in sc))
    return played, todo


def espn_rows(events, comp: str, emap: EspnMap) -> tuple[list, list]:
    """ESPN olayları -> (sonuç satırları, oynanmamış maçlar). Saat kaynakta kesin değilse boş."""
    from ..data.espn import NOT_PLAYED

    c = COMPETITIONS[comp]
    played, todo = [], []
    for e in events:
        h, a = emap.get(e.home_id, e.home), emap.get(e.away_id, e.away)
        if h.key == a.key:
            continue
        season = season_label(season_start(e.date, c.calendar_year), c.calendar_year)
        base = {"comp": comp, "season": season, "stage": "", "date": pd.Timestamp(e.date), "time": e.time or "",
                "home": h.name, "away": a.name, "home_key": h.key, "away_key": a.key, "home_country": h.country,
                "away_country": a.country, "home_mapped": h.mapped, "away_mapped": a.mapped,
                "neutral": bool(e.neutral), "source": "espn", "provider_id": f"espn:{e.event_id}",
                "home_raw": e.home, "away_raw": e.away}
        if e.ft is not None:
            ht = e.ht
            played.append(dict(base, fthg=int(e.ft[0]), ftag=int(e.ft[1]),
                               hthg=float(ht[0]) if ht else float("nan"), htag=float(ht[1]) if ht else float("nan"),
                               extra_time=bool(e.extra_time)))
        elif e.status not in NOT_PLAYED and e.state in ("pre", ""):
            todo.append(base)
    return played, todo


@dataclass
class CupResult:
    matches: pd.DataFrame
    fixtures: pd.DataFrame
    meta: dict = field(default_factory=dict)
    report: dict = field(default_factory=dict)  # turnuva -> özet
    warnings: list = field(default_factory=list)


def _proof(raw_dir: Path, data: bytes, stem: str) -> tuple[str, str]:
    sha = hashlib.sha256(data).hexdigest()
    rel = f"{PROOF_DIR}/{sha[:16]}_{stem}.txt"
    p = Path(raw_dir) / rel
    if not p.is_file():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)
    return rel, sha


def _openfootball_files(dl, gh, comps, years_back: int, today: dt.date, force: bool, warnings: list) -> dict:
    """(comp, sezon klasörü) -> baytlar. Dosyası olmayan sezon (ör. turnuva o yıl yoktu) sessizce atlanır."""
    from ..data.sources import DownloadError
    from ..data.store import _GitHubUnavailable

    cur = season_start(today)
    out = {}
    for code in comps:
        c = COMPETITIONS[code]
        if not c.of_stem:
            continue
        for y in range(max(OF_FIRST_SEASON, cur - years_back), cur + 1):
            d = openfootball_dir(y)
            path = f"{d}/{c.of_stem}.txt"
            try:
                if gh is not None:
                    data = gh.get(CUP_REPO, path)
                else:
                    data = dl.get(f"{CUP_RAW_BASE}/{path}", f"openfootball_kupa/{path}",
                                  None if y < cur - 1 else OF_MAX_AGE_H, force)
            except (DownloadError, _GitHubUnavailable) as e:
                status = getattr(e, "status", None)
                if status not in (404, 410) and not isinstance(e, _GitHubUnavailable) and not getattr(e, "network", 0):
                    warnings.append(f"openfootball kupa dosyası {path} alınamadı: {e}")
                continue
            out[(code, d)] = data
    return out


def _espn_months(dl, slug: str, start: dt.date, end: dt.date, today: dt.date, force: bool, cache_root: str,
                 tz, allow_extra: bool):
    """Aylık ESPN istekleri (tamamlanmış ayların yanıtları kalıcı önbellekte). Döner: (olaylar, atlananlar, hatalar).

    ``tz``: olayların yerel tarih/saati için zaman dilimi (yurt içi lig kanıtında ligin ülkesi)."""
    from ..data.espn import month_chunks, parse_scoreboard, scoreboard_url
    from ..data.sources import DownloadError

    events, skips, errors, fails = {}, Counter(), [], 0
    for a, b in month_chunks(start, end):
        rel = f"{cache_root}/{slug}/{a:%Y-%m}.json"
        p = dl.cache_path(rel)
        try:
            done = (b < today - dt.timedelta(days=3) and p.exists()
                    and dt.date.fromtimestamp(p.stat().st_mtime) > b + dt.timedelta(days=3))
        except OSError:
            done = False
        try:
            data = dl.get(scoreboard_url(slug, a, b), rel, None if done else 1.0, force)
        except DownloadError as e:
            errors.append("bağlantı kurulamadı" if e.network or e.status is None else f"HTTP {e.status}")
            fails += 1
            if e.network or (fails >= MAX_FAILS and not events):
                break
            continue
        fails = 0
        pr = parse_scoreboard(data, "", allow_extra_time=allow_extra, tz=tz)
        skips.update(pr.skipped)
        events.update({ev.event_id: ev for ev in pr.events})
    return sorted(events.values(), key=lambda e: (e.date, e.time, e.event_id)), skips, errors


def _domestic_evidence(dl, matches: pd.DataFrame, today: dt.date, force: bool, progress) -> tuple[dict, dict]:
    """ESPN yurt içi lig kanıtı: numara -> (ülke, depo adı, kanıt). Aynı numara iki farklı takıma düşüyorsa çıkarılır.

    ESPN lig yanıtları ESPN lig yoluyla aynı önbellek anahtarındadır (``espn/{kod}/{ay}``): o yol bu güncellemede aynı
    ayı aldıysa yeniden istenmez."""
    from ..data.completion import COMPLETION_LABEL
    from ..data.espn import ESPN_LABEL, ESPN_LEAGUES, _tz, map_teams
    from ..data.leagues import LEAGUES, season_for_date
    from .turnuvalar import season_start as ss

    src = matches["source"].astype(str)
    base_all = matches[~src.isin({COMPLETION_LABEL, ESPN_LABEL})]
    out: dict = {}
    clash: set = set()
    stats: dict = {}
    codes = [c for c in sorted(set(base_all["league"])) if c in ESPN_LEAGUES]
    for i, code in enumerate(codes):
        lg = LEAGUES[code]
        progress(f"Kupa takım kimlikleri: ESPN lig maçları ({lg.label}, {i + 1}/{len(codes)})...")
        base = base_all[base_all["league"] == code]
        if base.empty:
            continue
        start = (today - dt.timedelta(days=EVIDENCE_DAYS)).replace(day=1)
        events, _skips, _err = _espn_months(dl, ESPN_LEAGUES[code], start, today, today, force, "espn",
                                            _tz(lg.country), False)
        if not events:
            continue
        y = today.year if lg.calendar_year else ss(today)
        cur_start = dt.date(y, 1, 1) if lg.calendar_year else dt.date(y, 7, 1)
        cur = [e for e in events if e.date >= cur_start]
        tm = map_teams(events, base, code, season_for_date(today, lg.calendar_year), cur)
        ids = domestic_espn_ids(events, tm, lg.country)
        stats[code] = {"olay": len(events), "eslesen_numara": len(ids)}
        for eid, (team, why) in ids.items():
            val = (lg.country, team, why)
            if eid in out and out[eid][:2] != val[:2]:
                clash.add(eid)
            out.setdefault(eid, val)
    for eid in clash:
        out.pop(eid, None)
    return out, stats


def update_cups(raw_dir, dl, gh, comps, years_back: int, matches: pd.DataFrame, today: dt.date, fixture_days: int,
                allowed: set, force: bool = False, progress=None) -> CupResult:
    """Seçili turnuvaların sonuç ve fikstürleri (modül açıklaması)."""
    from ..data.espn import SKIP_REASONS as ESPN_SKIPS

    say = (lambda m: progress(m)) if progress else (lambda m: None)
    comps = [c for c in comps if c in COMPETITIONS]
    warnings: list[str] = []
    report: dict = {c: {"kaynak": {}, "sonuc": 0, "fikstur": 0} for c in comps}
    if not comps:
        return CupResult(empty_matches(), empty_fixtures(), {"turnuvalar": []}, {}, [])
    raw_dir = Path(raw_dir)
    cur_lo = {c: season_start(today, COMPETITIONS[c].calendar_year) for c in comps}

    # 1) openfootball (CC0)
    of_data = {}
    if "openfootball" in allowed:
        say("Kupa verileri: openfootball (UEFA geçmiş sezonları)...")
        of_data = _openfootball_files(dl, gh, comps, years_back, today, force, warnings)
    parsed = {}
    for (code, d), data in sorted(of_data.items()):
        pr = parse_cup_txt(data, d)
        label = f"{d}/{COMPETITIONS[code].of_stem}.txt"
        parsed[(code, d)] = (label, pr, data)
        skipped = {k: v for k, v in pr.skipped.items() if k not in ("NOT_HUKMEN", "NOT_IPTAL")}
        if skipped:
            warnings.append(f"openfootball kupa {label}: {sum(skipped.values())} satır okunmadı ("
                            + "; ".join(f"{v} × {SKIP_REASONS.get(k, k)}" for k, v in sorted(skipped.items())) + ").")
    ofmap = map_openfootball({lab: pr.matches for lab, pr, _ in parsed.values()}, matches)
    of_played: dict = {}
    of_todo: dict = {}
    for (code, d), (label, pr, _data) in parsed.items():
        start = int(d[:4])
        season = season_label(start, COMPETITIONS[code].calendar_year)
        pl, td = of_rows(pr.matches, code, season, label, ofmap)
        of_played[(code, season)] = pl
        of_todo[(code, season)] = td

    # 2) ESPN (onay; GitHub profilinde yok)
    espn_events: dict = {}
    if "espn" in allowed and gh is None:
        hi = today + dt.timedelta(days=fixture_days)
        for i, code in enumerate(comps):
            c = COMPETITIONS[code]
            if not c.espn:
                continue
            say(f"Kupa verileri: ESPN {c.name} ({i + 1}/{len(comps)})...")
            first = cur_lo[code] - (ESPN_SEASONS - 1)
            start = season_bounds(first, c.calendar_year)[0].replace(day=1)
            events, skips, errors = _espn_months(dl, c.espn, start, hi, today, force, "espn_kupa", _tz_for(c), True)
            if not events:
                why = f" ({errors[0]})" if errors else ""
                if c.unverified:
                    warnings.append(f"{c.full}: ESPN'de bulunamadı{why}; '{c.espn}' kodu önceden doğrulanamamıştı.")
                elif errors:
                    warnings.append(f"{c.full}: ESPN'den veri alınamadı{why}.")
                continue
            espn_events[code] = events
            bad = {k: v for k, v in skips.items() if k != "NORMAL_SURE_DISI"}
            if bad:
                warnings.append(f"{c.full} (ESPN): {sum(bad.values())} kayıt okunmadı ("
                                + "; ".join(f"{v} × {ESPN_SKIPS.get(k, k)}" for k, v in sorted(bad.items())) + ").")
            if skips.get("NORMAL_SURE_DISI"):
                report[code]["normal_sure_okunamayan"] = int(skips["NORMAL_SURE_DISI"])

    # 3) ESPN kimlikleri (yurt içi lig kanıtı + openfootball kupa kanıtı)
    emap = EspnMap()
    dom_stats: dict = {}
    if espn_events:
        domestic, dom_stats = _domestic_evidence(dl, matches, today, force, say)
        of_df = pd.DataFrame([r for rows in of_played.values() for r in rows])
        emap = map_espn(espn_events, domestic, of_df if not of_df.empty else None)
    es_played: dict = {}
    es_todo: dict = {}
    for code, events in espn_events.items():
        pl, td = espn_rows(events, code, emap)
        for r in pl:
            es_played.setdefault((code, r["season"]), []).append(r)
        for r in td:
            es_todo.setdefault((code, r["season"]), []).append(r)

    # 4) Turnuva-sezon başına tek kaynak
    played, todo, records, sources = [], [], [], {}
    keys = sorted(set(of_played) | set(es_played) | set(of_todo) | set(es_todo))
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for code, season in keys:
        c = COMPETITIONS[code]
        start = int(str(season)[:4])
        finished = season_bounds(start, c.calendar_year)[1] < today
        has_of = (code, season) in of_played and bool(of_played[(code, season)] or of_todo.get((code, season)))
        has_es = bool(es_played.get((code, season)) or es_todo.get((code, season)))
        use = ("openfootball" if (has_of and (finished or not has_es)) else "espn" if has_es else None)
        if use is None:
            continue
        sources[f"{code} {season}"] = use
        report[code]["kaynak"][season] = use
        if use == "openfootball":
            rows = of_played.get((code, season), [])
            played += rows
            if not finished:
                todo += of_todo.get((code, season), [])
            d = openfootball_dir(start)
            label, pr, data = parsed[(code, d)]
            rel, sha = _proof(raw_dir, data, f"{d}_{c.of_stem}")
            df = pd.DataFrame(rows, columns=CUP_MATCH_COLUMNS)
            records.append({"turnuva": code, "sezon": season, "depo": CUP_REPO, "yol": label, "kopya": rel,
                            "sha256": sha, "ayristirici": CUP_PARSER, "kimlik": KIMLIK_SURUMU, "satir": len(df),
                            "satir_ozeti": rows_sha256(df) if len(df) else "", "alinma": now_iso})
        else:
            played += es_played.get((code, season), [])
            if not finished:
                todo += es_todo.get((code, season), [])
    m = pd.DataFrame(played, columns=CUP_MATCH_COLUMNS)
    if not m.empty:
        m["date"] = pd.to_datetime(m["date"])
        m = m.drop_duplicates(subset=["comp", "date", "home_key", "away_key"], keep="first")
        m = m.sort_values(["date", "comp", "time", "home"], kind="mergesort").reset_index(drop=True)
    fx = pd.DataFrame(todo, columns=CUP_FIXTURE_COLUMNS)
    if not fx.empty:
        fx["date"] = pd.to_datetime(fx["date"])
        lo, hi = pd.Timestamp(today), pd.Timestamp(today + dt.timedelta(days=fixture_days))
        fx = fx[(fx["date"] >= lo) & (fx["date"] <= hi)]
        fx = fx.drop_duplicates(subset=["comp", "date", "home_key", "away_key"], keep="first")
        fx = fx.sort_values(["date", "time", "comp", "home"], kind="mergesort").reset_index(drop=True)
    for code in comps:
        report[code]["sonuc"] = int((m["comp"] == code).sum()) if not m.empty else 0
        report[code]["fikstur"] = int((fx["comp"] == code).sum()) if not fx.empty else 0
    write_calendars(raw_dir, espn_events, emap, today)
    meta = {
        "turnuvalar": comps, "kaynaklar": sources, "koken": records,
        "eslesme": {"surum": KIMLIK_SURUMU,
                    "openfootball_eslesmeyen": [{"ulke": cc, "ad": n, "neden": why, "oneriler": list(sug)}
                                                for (cc, n), (why, sug) in sorted(ofmap.unmapped.items())],
                    "espn": {eid: {"anahtar": t.key, "ad": t.name, "kanit": t.basis} for eid, t in
                             sorted(emap.by_id.items())},
                    "espn_celiski": {eid: list(v) for eid, v in sorted(emap.conflicts.items())},
                    "espn_lig_kaniti": dom_stats},
        "guncelleme": now_iso,
    }
    return CupResult(m, fx, meta, report, warnings)


def write_calendars(raw_dir: Path, espn_events: dict, emap: EspnMap, today: dt.date) -> None:
    """ESPN kupa takvimleri (uygunluk kontrolü bunları okur): turnuva başına, içinde bulunulan ve önceki sezon.
    Takımlar modelin anahtarlarıyla yazılır. Bu güncellemede ESPN'den gelmeyen turnuvaların eski takvimleri silinir
    (onay geri alındıysa eski takvim kanıt olarak kullanılmaz)."""
    root = Path(raw_dir) / CALENDAR_DIR
    keep = set()
    for code, events in espn_events.items():
        c = COMPETITIONS[code]
        by_season: dict = {}
        for e in events:
            s = season_label(season_start(e.date, c.calendar_year), c.calendar_year)
            by_season.setdefault(s, []).append(e)
        for season, evs in by_season.items():
            recs = []
            for e in sorted(evs, key=lambda x: (x.date, x.time, x.event_id)):
                h, a = emap.get(e.home_id, e.home), emap.get(e.away_id, e.away)
                rec = {"id": e.event_id, "date": e.date.isoformat(), "time": e.time, "home_key": h.key,
                       "away_key": a.key, "status": e.status}
                if e.ft is not None:
                    rec["ft"] = list(e.ft)
                recs.append(rec)
            path = root / season.replace("/", "-") / f"{code}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".part")
            tmp.write_text(json.dumps({"turnuva": code, "sezon": season, "kaynak": "espn", "maclar": recs},
                                      ensure_ascii=False, sort_keys=True), encoding="utf-8")
            tmp.replace(path)
            keep.add(path)
    if root.exists():
        for p in root.glob("*/*.json"):
            if p not in keep:
                p.unlink(missing_ok=True)


def read_calendars(raw_dir) -> dict:
    """(turnuva, sezon) -> (alınma anı, maç kayıtları)."""
    root = Path(raw_dir) / CALENDAR_DIR
    out = {}
    if not root.exists():
        return out
    for p in sorted(root.glob("*/*.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            at = dt.datetime.fromtimestamp(p.stat().st_mtime, tz=dt.timezone.utc)
        except (OSError, ValueError):
            continue
        out[(obj.get("turnuva"), obj.get("sezon"))] = (at, obj.get("maclar") or [])
    return out


def verify_cup_rows(cup_matches: pd.DataFrame | None, records, raw_dir) -> tuple[bool, list[str]]:
    """``openfootball-kupa`` etiketli bütün satırlar, kayıtlı ve önbellekte doğrulanabilen kopyadan aynı okuyucuyla
    yeniden üretilebiliyor mu? Döner: (doğrulandı mı, sorunlar). Etiketli satır yoksa doğrulanmış sayılmaz."""
    if cup_matches is None or cup_matches.empty:
        return False, ["kupa satırı yok"]
    rows = cup_matches[cup_matches["source"] == CUP_LABEL]
    if rows.empty:
        return False, ["openfootball kupa satırı yok"]
    problems: list[str] = []
    recs = {}
    for r in records or ():
        try:
            recs[(r["turnuva"], r["sezon"])] = r
        except (KeyError, TypeError):
            problems.append("geçersiz köken kaydı")
    for (code, season), g in rows.groupby([rows["comp"], rows["season"].astype(str)]):
        rec = recs.get((code, season))
        if rec is None:
            problems.append(f"{code} {season}: köken kaydı yok")
            continue
        if rec.get("ayristirici") != CUP_PARSER or rec.get("depo") != CUP_REPO:
            problems.append(f"{code} {season}: kaynak deposu veya okuyucu sürümü farklı")
            continue
        path = Path(raw_dir) / str(rec.get("kopya", ""))
        if not path.is_file():
            problems.append(f"{code} {season}: kaynak dosyası kopyası yok")
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != rec.get("sha256"):
            problems.append(f"{code} {season}: dosya özeti kayıtla uyuşmuyor")
            continue
        d = str(rec.get("yol", "")).split("/")[0]
        pr = parse_cup_txt(data, d)
        again = []
        for r in pr.matches:
            sc = r.get("score")
            if sc is None:
                continue
            ht = sc.get("ht")
            again.append({"comp": code, "season": season, "date": pd.Timestamp(r["date"]),
                          "home_raw": _raw_name(r["team1"], r.get("cc1", "")),
                          "away_raw": _raw_name(r["team2"], r.get("cc2", "")), "fthg": sc["ft"][0],
                          "ftag": sc["ft"][1], "hthg": ht[0] if ht else float("nan"),
                          "htag": ht[1] if ht else float("nan")})
        dig = rows_sha256(g)
        if dig != rows_sha256(pd.DataFrame(again, columns=["comp", "season", "date", "home_raw", "away_raw", "fthg",
                                                           "ftag", "hthg", "htag"])) or dig != rec.get("satir_ozeti"):
            problems.append(f"{code} {season}: depodaki satırlar kaynak dosyasından üretilenlerle aynı değil")
    return (not problems), problems


def summary(cup_matches: pd.DataFrame) -> pd.DataFrame:
    """Veri sayfası için turnuva özeti."""
    from .turnuvalar import competition_name

    if cup_matches is None or cup_matches.empty:
        return pd.DataFrame(columns=["comp", "Turnuva", "Sezon", "Maç", "İlk maç", "Son maç", "Kaynak"])
    rows = []
    for code, g in cup_matches.groupby("comp"):
        rows.append({"comp": code, "Turnuva": competition_name(code), "Sezon": g["season"].nunique(), "Maç": len(g),
                     "İlk maç": g["date"].min().date(), "Son maç": g["date"].max().date(),
                     "Kaynak": ", ".join(sorted(set(g["source"].astype(str))))})
    order = {c: i for i, c in enumerate(COMPETITIONS)}
    return pd.DataFrame(rows).sort_values("comp", key=lambda s: s.map(order)).reset_index(drop=True)


__all__ = ["CUP_MATCH_COLUMNS", "CUP_FIXTURE_COLUMNS", "CupResult", "update_cups", "verify_cup_rows", "read_calendars",
           "summary", "empty_matches", "empty_fixtures", "TeamIdentity", "UEFA_REGION"]

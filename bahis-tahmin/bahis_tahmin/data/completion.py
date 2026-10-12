"""Eksik dönemin openfootball sonuçlarıyla tamamlanması (VERI-02).

football-data.co.uk erişilemediğinde geçmiş veri GitHub yedek veri setinden gelir ve bu set güncel sezonda haftalarca
geride kalabilir. Bu durumda openfootball takvimi oynanmış ama veride olmayan maçları gösterir (``DEPODA_EKSIK_MAC``) ve
model güncel sonuçları bilmez. Bu modül, aynı güncellemede indirilen openfootball sezon dosyasından (CC0) oynanmış maç
sonuçlarını alır ve şu koşullarla veri deposuna ekler:

* Sonuçlar pilotun sonuç ayrıştırıcısıyla okunur (``parse_openfootball_results``): belirsiz veya çelişkili kayıt
  karantinaya gider, tahmin edilmez.
* Takım adları yalnızca KESİN kimlikle (aynı ad veya doğrulanmış takma ad; ``data.teams``) veri deposunun adlarına
  çevrilir. Eşleşmeyen adlı maç eklenmez.
* Yalnızca ligin depodaki son maç gününden SONRA ve güncelleme gününden ÖNCE oynanmış, depoda (±3 gün) bulunmayan
  maçlar eklenir. Var olan satırlar değiştirilmez.
* Kaynak etiketi ``openfootball-tamamlama``. Satırlar ancak kökenleri doğrulanırsa hak kazanır (``verify_completion``):
  kullanılan dosya baytları önbellekte saklanır; dosya özeti, ayrıştırıcı sürümü, seçim kuralının girdileri ve ad
  eşlemesi kayda yazılır. Doğrulama aynı dosyadan aynı kuralla aynı satırları yeniden üretmeyi şart koşar; başka
  kaynaktan gelen satırın etiketini değiştirmek hak kazandırmaz.

Oran ve maç istatistikleri openfootball'da yoktur: bu sütunlar boş kalır (sıfırla doldurulmaz).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pandas as pd

from .parsers import MATCH_COLUMNS, OPENFOOTBALL_RESULT_PARSER, OPENFOOTBALL_RESULT_PARSERS, parse_openfootball_results
from .teams import MATCHING_VERSION, resolve_teams

COMPLETION_LABEL = "openfootball-tamamlama"
COMPLETION_VERSION = "tamamlama-v1"
PAIR_DAYS = 3  # depodaki aynı eşleşmenin tarih toleransı (uygunluk kontrolüyle aynı)


def recent_teams(matches: pd.DataFrame, league: str, seasons: int = 2) -> list[str]:
    """Ligin son iki sezonundaki takımlar (tamamlama satırları hariç; fikstür eşlemesiyle aynı bağlam)."""
    m = matches[(matches["league"] == league) & (matches["source"].astype(str) != COMPLETION_LABEL)]
    if m.empty:
        return []
    recent = sorted(m["season"].dropna().astype(str).unique())[-seasons:]
    m = m[m["season"].astype(str).isin(recent)]
    return sorted(set(m["home"]) | set(m["away"]))


def rows_sha256(df: pd.DataFrame) -> str:
    """Satır içeriği özeti (sıra bağımsız): lig, sezon, tarih, takımlar, MS ve İY skorları."""
    def cell(v) -> str:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return ""
        return "" if f != f else str(int(f))

    keys = sorted("|".join([str(lg), str(se), str(pd.Timestamp(d).date()), str(h), str(a), cell(fh), cell(fa),
                            cell(hh), cell(ha)])
                  for lg, se, d, h, a, fh, fa, hh, ha in zip(df["league"], df["season"], df["date"], df["home"],
                                                              df["away"], df["fthg"], df["ftag"], df["hthg"],
                                                              df["htag"]))
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


def select_rows(data: bytes, league: str, season: str, base: pd.DataFrame, after: dt.date, before: dt.date,
                parser: str = OPENFOOTBALL_RESULT_PARSER) -> tuple[pd.DataFrame, dict[str, str]]:
    """Kuralın kendisi (oluşturma ve doğrulamada aynı): ``base`` = veri deposunun tamamlama dışı satırları.

    Döner: (eklenecek satırlar, kullanılan ad eşlemesi {kaynak adı: depo adı})."""
    parsed = parse_openfootball_results(data, league, season, parser).matches
    empty = pd.DataFrame(columns=MATCH_COLUMNS)
    if parsed.empty:
        return empty, {}
    known = recent_teams(base, league)
    if not known:
        return empty, {}
    p = parsed[(parsed["date"] > pd.Timestamp(after)) & (parsed["date"] < pd.Timestamp(before))]
    if p.empty:
        return empty, {}
    names = sorted(set(parsed["home"]) | set(parsed["away"]))  # ters çakışma denetimi bütün dosya adlarıyla
    res = resolve_teams(names, known, league, "openfootball")
    lg = base[base["league"] == league]
    have: dict[tuple, list] = {}
    for h, a, d in zip(lg["home"], lg["away"], pd.to_datetime(lg["date"])):
        have.setdefault((h, a), []).append(d)
    rows, used = [], {}
    for r in p.itertuples(index=False):
        mh, ma = res.get(r.home), res.get(r.away)
        if mh is None or ma is None or not (mh.exact and ma.exact) or mh.team == ma.team:
            continue
        if any(abs((d - r.date).days) <= PAIR_DAYS for d in have.get((mh.team, ma.team), ())):
            continue
        used[r.home], used[r.away] = mh.team, ma.team
        rows.append({**{c: getattr(r, c) for c in MATCH_COLUMNS if hasattr(r, c)}, "home": mh.team,
                     "away": ma.team, "source": COMPLETION_LABEL})
    if not rows:
        return empty, {}
    out = pd.DataFrame(rows)
    for c in MATCH_COLUMNS:
        if c not in out.columns:
            out[c] = float("nan")
    return out[MATCH_COLUMNS].reset_index(drop=True), dict(sorted(used.items()))


def build_record(league: str, season: str, of_season: str, data: bytes, cache_rel: str, after: dt.date,
                 before: dt.date, rows: pd.DataFrame, names: dict, retrieved_at: str) -> dict:
    return {"surum": COMPLETION_VERSION, "league": league, "season": season, "openfootball_sezon": of_season,
            "cache_rel": cache_rel, "sha256": hashlib.sha256(data).hexdigest(), "ayristirici": OPENFOOTBALL_RESULT_PARSER,
            "eslesme_surumu": MATCHING_VERSION, "sonra": str(after), "once": str(before), "ad_eslemesi": names,
            "rows": int(len(rows)), "rows_sha256": rows_sha256(rows), "alinma": retrieved_at}


def verify_completion(matches: pd.DataFrame | None, records, raw_dir) -> tuple[bool, list[str]]:
    """``openfootball-tamamlama`` etiketli satırların hepsi kayıtlı, önbellekte saklanan dosyadan aynı kuralla yeniden
    üretilebiliyor mu? Döner: (doğrulandı mı, sorunlar). Etiketli satır yoksa doğrulanmış sayılmaz."""
    if matches is None or matches.empty or "source" not in matches:
        return False, ["tamamlama satırı yok"]
    src = matches["source"].astype(str)
    rows = matches[src == COMPLETION_LABEL]
    if rows.empty:
        return False, ["tamamlama satırı yok"]
    base = matches[src != COMPLETION_LABEL]
    recs = {}
    problems: list[str] = []
    for r in records or ():
        try:
            key = (str(r["league"]), str(r["season"]))
            ok = (r["surum"] == COMPLETION_VERSION and r["ayristirici"] in OPENFOOTBALL_RESULT_PARSERS
                  and r["eslesme_surumu"] == MATCHING_VERSION)
        except (KeyError, TypeError):
            problems.append("geçersiz tamamlama kaydı")
            continue
        if not ok:
            problems.append(f"{key[0]} {key[1]}: kayıt sürümü farklı")
            continue
        recs[key] = r
    for (lg, season), g in rows.groupby([rows["league"].astype(str), rows["season"].astype(str)]):
        r = recs.get((lg, season))
        if r is None:
            problems.append(f"{lg} {season}: tamamlama kaydı yok")
            continue
        path = Path(raw_dir) / str(r["cache_rel"])
        if not path.is_file():
            problems.append(f"{lg} {season}: kaynak dosyası önbellekte yok")
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != r["sha256"]:
            problems.append(f"{lg} {season}: dosya özeti kayıtla uyuşmuyor")
            continue
        try:
            after, before = dt.date.fromisoformat(r["sonra"]), dt.date.fromisoformat(r["once"])
        except (TypeError, ValueError):
            problems.append(f"{lg} {season}: seçim tarihleri geçersiz")
            continue
        redo, names = select_rows(data, lg, season, base, after, before, r["ayristirici"])
        digest = rows_sha256(g)
        if (names != r.get("ad_eslemesi") or digest != rows_sha256(redo) or digest != r["rows_sha256"]
                or len(g) != int(r["rows"])):
            problems.append(f"{lg} {season}: depodaki satırlar kaynak dosyasından aynı kuralla üretilemiyor")
    return (not problems), problems

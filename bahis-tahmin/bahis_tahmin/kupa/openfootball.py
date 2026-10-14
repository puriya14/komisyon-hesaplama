"""openfootball/champions-league (CC0) Football.TXT kupa dosyalarının okuyucusu (KUPA-01).

Dosya biçimi (``2025-26/cl.txt``)::

    = UEFA Champions League 2025/26
    ▪ League, Matchday 1
      Tue Sep 16 2025
        18:45  Athletic Club (ESP)     v Arsenal FC (ENG)         0-2 (0-0)
               PSV (NED)               v Royale Union Saint-Gilloise (BEL)  1-3 (0-2)
    ▪ Finals, Final
      Sat May 30
        18:00  Paris Saint-Germain FC (FRA) v Arsenal FC (ENG)    4-3 pen. 1-1 a.e.t. (1-1, 0-1)

Okuma kuralları (tahmin yapılmaz; tanınmayan satır nedeniyle sayılır ve atlanır, maç uydurulmaz):

* Skor normal süre (90 dk) sonucu olarak saklanır. Uzatmaya giden maçta ("a.e.t.") normal süre skoru parantez içindeki
  ilk skordur ("1-1 a.e.t. (1-1, 0-1)": uzatmalar sonunda 1-1, normal süre 1-1, ilk yarı 0-1). Normal süre skoru
  yazılmamış uzatmalı maç atlanır. Penaltı sonucu ("4-3 pen.") yalnızca bilgi olarak tutulur.
* İlk yarı skoru yalnızca yazılmışsa alınır (normal maçta "(0-0)", uzatmalı maçta ikinci parantez skoru).
* Hükmen ("[awarded]"), iptal ("[cancelled]") ve benzeri notlu satırlar sonuç sayılmaz.
* Takım adının sonundaki üç harfli ülke kodu ("(ENG)") ayrı alınır; takım kimliği ``kupa.kimlik`` ile kurulur.
* Final turu (aşama adının son parçası "Final") tarafsız sahada sayılır.
* Yılı yazılmayan tarihin yılı önceki tarihten çıkarılır; haftanın günü tarihle uyuşmalıdır; tarih sezon penceresi
  dışındaysa maç atlanır.

Çıktı deterministiktir: aynı dosya baytları aynı satırları verir (köken doğrulaması buna dayanır).
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from dataclasses import dataclass, field

CUP_REPO = "openfootball/champions-league"
CUP_BRANCH = "master"
CUP_RAW_BASE = f"https://raw.githubusercontent.com/{CUP_REPO}/{CUP_BRANCH}"
CUP_PARSER = "kupa-football-txt-v1"
CUP_LABEL = "openfootball-kupa"  # veri deposu kaynak etiketi (haklar: openfootball-sonuc, köken doğrulamalı)

_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"), start=1)}
_DOWS = {d: i for i, d in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}
_DATE = re.compile(r"^(?:(?P<dow>mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+)?(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|"
                   r"sep|oct|nov|dec)[a-z]*\.?\s+(?P<day>\d{1,2})(?:,?\s+(?P<year>\d{4}))?$", re.I)
_TIME = re.compile(r"^(?P<time>\d{1,2}[:.]\d{2})\s+(?P<rest>\S.*)$")
_TEAM = r"\S.*?\([A-Z]{3}\)"
_MATCH_CC = re.compile(rf"^(?P<home>{_TEAM})\s+v\s+(?P<away>{_TEAM})(?:\s+(?P<rest>\S.*))?$")
_MATCH = re.compile(r"^(?P<home>\S.*?)\s+v\s+(?P<away>\S.*?)(?:\s{2,}(?P<rest>\S.*))?$")
_SCORE = re.compile(r"^(?:(?P<p1>\d{1,2})-(?P<p2>\d{1,2})\s+pen\.\s+)?(?P<f1>\d{1,2})-(?P<f2>\d{1,2})"
                    r"(?P<aet>\s+a\.e\.t\.)?(?:\s+\((?P<a1>\d{1,2})-(?P<a2>\d{1,2})"
                    r"(?:,\s*(?P<b1>\d{1,2})-(?P<b2>\d{1,2}))?\))?$")
_CC = re.compile(r"^(?P<name>.*\S)\s+\((?P<cc>[A-Z]{3})\)$")
_NOTE = re.compile(r"\[(?P<note>[^\]]*)\]")
_FINAL_WORDS = frozenset({"final", "finale", "endspiel"})

SKIP_REASONS = {
    "BILINMEYEN_SATIR": "satır biçimi tanınmadı",
    "SKOR_OKUNAMADI": "skor tanınan biçimlerden birine uymuyor",
    "UZATMA_NORMAL_SURE_YOK": "uzatmalı maçın normal süre skoru yazılmamış",
    "NOT_HUKMEN": "hükmen sonuç (sahada oynanmadı)",
    "NOT_IPTAL": "iptal edilen veya ertelenen maç",
    "NOT_DIGER": "anlamı bilinmeyen not ([...])",
    "TARIH_YOK": "maçın tarihi yok",
    "TARIH_GUN_UYUSMAZ": "yazılan haftanın günü tarihle uyuşmuyor",
    "TARIH_SEZON_DISI": "tarih sezon penceresinin dışında",
    "TARIH_GECERSIZ": "tarih geçersiz",
    "TAKIM_GECERSIZ": "takım adı boş veya iki takım aynı",
}


@dataclass
class CupParse:
    name: str = ""
    matches: list = field(default_factory=list)  # oynanmış veya oynanacak maçlar (sözlük)
    skipped: Counter = field(default_factory=Counter)
    samples: list = field(default_factory=list)

    def skip(self, lineno: int, reason: str, line: str) -> None:
        self.skipped[reason] += 1
        if len(self.samples) < 8:
            self.samples.append((lineno, reason, line.strip()[:120]))


def _bounds(season_dir: str) -> tuple[int, dt.date, dt.date]:
    start = int(str(season_dir)[:4])
    return start, dt.date(start, 6, 1), dt.date(start + 1, 8, 31)  # 2019/20: final turnuvası Ağustos 2020


def _date(text: str, prev: dt.date | None, start: int):
    """Tarih satırıysa (tarih | None, hata | None); değilse False."""
    m = _DATE.match(text.strip())
    if not m:
        return False
    mon, day = _MONTHS[m["mon"][:3].lower()], int(m["day"])
    try:
        if m["year"]:
            d = dt.date(int(m["year"]), mon, day)
        elif prev is not None:
            cands = []
            for y in (prev.year - 1, prev.year, prev.year + 1):
                try:
                    cands.append(dt.date(y, mon, day))
                except ValueError:
                    continue
            if not cands:
                raise ValueError
            d = min(cands, key=lambda c: abs((c - prev).days))
        else:
            d = dt.date(start if mon >= 6 else start + 1, mon, day)
    except ValueError:
        return None, "TARIH_GECERSIZ"
    if m["dow"] and _DOWS[m["dow"][:3].lower()] != d.weekday():
        return None, "TARIH_GUN_UYUSMAZ"
    return d, None


def is_final(stage: str | None) -> bool:
    if not stage:
        return False
    last = str(stage).split(",")[-1].strip().lower()
    return last in _FINAL_WORDS


def _split_team(text: str) -> tuple[str, str]:
    m = _CC.match(text.strip())
    return (m["name"], m["cc"]) if m else (text.strip(), "")


def parse_cup_txt(data: bytes, season_dir: str) -> CupParse:
    """Kupa dosyasının baytlarından maç listesi (``season_dir``: "2025-26")."""
    from ..data.parsers import decode_bytes

    start, lo, hi = _bounds(season_dir)
    res = CupParse()
    stage: str | None = None
    day: dt.date | None = None
    day_err: str | None = "TARIH_YOK"
    last: dt.date | None = None
    last_time = ""
    for lineno, raw in enumerate(decode_bytes(data).splitlines(), start=1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("="):
            if not res.name:
                res.name = s.lstrip("= ").strip()
            continue
        if s[0] in "▪»":
            stage = s[1:].strip() or None
            day, day_err, last_time = None, "TARIH_YOK", ""
            continue
        if s.startswith("("):  # gol satırı (bu dosyalarda yok; varsa atlanır)
            continue
        parsed = _date(s, last, start)
        if parsed is not False:
            day, day_err = parsed
            last_time = ""
            if day is not None:
                if not (lo <= day <= hi):
                    day, day_err = None, "TARIH_SEZON_DISI"
                else:
                    last = day
            continue
        t = _TIME.match(s)
        rest_line, time_txt = (t["rest"], t["time"]) if t else (s, None)
        m = _MATCH_CC.match(rest_line) or _MATCH.match(rest_line)
        if m is None or " v " not in rest_line:
            res.skip(lineno, "BILINMEYEN_SATIR", s)
            continue
        if time_txt is not None:
            last_time = time_txt.replace(".", ":").zfill(5)
        if day is None:
            res.skip(lineno, day_err or "TARIH_YOK", s)
            continue
        home, cc1 = _split_team(m["home"])
        away, cc2 = _split_team(m["away"])
        if not home or not away or (home, cc1) == (away, cc2):
            res.skip(lineno, "TAKIM_GECERSIZ", s)
            continue
        rest = (m["rest"] or "").strip()
        note = _NOTE.search(rest)
        if note:
            n = note["note"].strip().lower()
            res.skip(lineno, "NOT_HUKMEN" if n.startswith("award") else
                     "NOT_IPTAL" if n.startswith(("cancel", "postpon", "abandon", "suspend")) else "NOT_DIGER", s)
            continue
        rec = {"round": stage, "date": day.isoformat(), "time": last_time, "team1": home, "team2": away,
               "cc1": cc1, "cc2": cc2, "neutral": is_final(stage), "line": lineno}
        if rest:
            sc = _SCORE.match(re.sub(r"\s+", " ", rest))
            if sc is None:
                res.skip(lineno, "SKOR_OKUNAMADI", s)
                continue
            score: dict = {}
            if sc["aet"]:
                if sc["a1"] is None:
                    res.skip(lineno, "UZATMA_NORMAL_SURE_YOK", s)
                    continue
                score["ft"] = [int(sc["a1"]), int(sc["a2"])]
                score["et"] = [int(sc["f1"]), int(sc["f2"])]
                if sc["b1"] is not None:
                    score["ht"] = [int(sc["b1"]), int(sc["b2"])]
            else:
                if sc["b1"] is not None:  # normal maçta iki parantez skoru olmaz
                    res.skip(lineno, "SKOR_OKUNAMADI", s)
                    continue
                score["ft"] = [int(sc["f1"]), int(sc["f2"])]
                if sc["a1"] is not None:
                    score["ht"] = [int(sc["a1"]), int(sc["a2"])]
            if sc["p1"] is not None:
                score["pen"] = [int(sc["p1"]), int(sc["p2"])]
            ht = score.get("ht")
            if ht is not None and (ht[0] > score["ft"][0] or ht[1] > score["ft"][1]):
                res.skip(lineno, "SKOR_OKUNAMADI", s)  # ilk yarı skoru maç sonundan büyük olamaz
                continue
            rec["score"] = score
        res.matches.append(rec)
    return res

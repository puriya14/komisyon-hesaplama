"""openfootball (CC0) Football.TXT kupa dosyalarının okuyucusu (KUPA-01; yurt içi kupalar KUPA-IY-03).

UEFA dosyası (``openfootball/champions-league``, ``2025-26/cl.txt``)::

    = UEFA Champions League 2025/26
    ▪ League, Matchday 1
      Tue Sep 16 2025
        18:45  Athletic Club (ESP)     v Arsenal FC (ENG)         0-2 (0-0)
               PSV (NED)               v Royale Union Saint-Gilloise (BEL)  1-3 (0-2)
    ▪ Finals, Final
      Sat May 30
        18:00  Paris Saint-Germain FC (FRA) v Arsenal FC (ENG)    4-3 pen. 1-1 a.e.t. (1-1, 0-1)

Yurt içi kupa dosyaları (ülke depoları, ör. ``openfootball/deutschland`` ``2023-24/cup.txt``) aynı biçimdedir; iki
farkı vardır: takım adlarında ülke kodu yoktur (ülke turnuvadan gelir, ``default_cc``) ve bazı depolarda skor iki takım
adının arasında yazılır ("1. FC Saarbrücken        2-1 (0-0)  Karlsruher SC").

Okuma kuralları (tahmin yapılmaz; tanınmayan satır nedeniyle sayılır ve atlanır, maç uydurulmaz):

* Skor normal süre (90 dk) sonucu olarak saklanır. Uzatmaya giden maçta ("a.e.t.") normal süre skoru parantez içindeki
  ilk skordur ("1-1 a.e.t. (1-1, 0-1)": uzatmalar sonunda 1-1, normal süre 1-1, ilk yarı 0-1). Uzatmasız penaltılı
  maçta ("10-9 pen. (1-1, 0-1)") normal süre parantezdeki ilk, ilk yarı ikinci skordur. Normal süre skoru yazılmamış
  uzatmalı/penaltılı maç atlanır. Normal sürenin berabere bitmesi aranmaz (iki ayaklı eşleşmede uzatmaya toplam skor
  götürür). Penaltı sonucu yalnızca bilgi olarak tutulur.
* İlk yarı skoru yalnızca yazılmışsa alınır (normal maçta "(0-0)", uzatmalı/penaltılı maçta ikinci parantez skoru).
  Tek parantezli uzatmalı/penaltılı maçta ("3-1 pen. (0-0)") parantez normal süredir; ilk yarı bilinmiyor kalır.
* Hükmen ("[awarded]"), iptal ("[cancelled]") ve benzeri notlu satırlar sonuç sayılmaz.
* Takım adının sonundaki üç harfli ülke kodu ("(ENG)") ayrı alınır; kodu olmayan ada ``default_cc`` verilir. Takım
  kimliği ``kupa.kimlik`` ile kurulur.
* Final turu (aşama adının son parçası "Final") ve ``neutral_rounds`` turları tarafsız sahada sayılır.
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
CUP_PARSER = "kupa-football-txt-v2"  # v2 (KUPA-IY-03): skor-ortada satır, uzatmasız penaltı, varsayılan ülke kodu
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
# Skor-ortada satır: "Ev  <skor>  Deplasman[  [not]]" (skor içinde art arda iki boşluk olmaz)
_MATCH_MID = re.compile(r"^(?P<home>\S.*?)\s{2,}(?P<score>\d{1,2}-\d{1,2}(?:\s\S+)*?)\s{2,}(?P<away>\S.*?)"
                        r"(?:\s{2,}(?P<note>\[[^\]]*\]))?$")
# [penaltı "p1-p2 pen."] [skor "f1-f2" [" a.e.t."]] [parantez "(a1-a2[, b1-b2])"]
_SCORE = re.compile(r"^(?:(?P<p1>\d{1,2})-(?P<p2>\d{1,2})\s+pen\.(?:\s+|$))?"
                    r"(?:(?P<f1>\d{1,2})-(?P<f2>\d{1,2})(?P<aet>\s+a\.e\.t\.)?(?:\s+|$))?"
                    r"(?:\((?P<a1>\d{1,2})-(?P<a2>\d{1,2})(?:,\s*(?P<b1>\d{1,2})-(?P<b2>\d{1,2}))?\))?$")
_CC = re.compile(r"^(?P<name>.*\S)\s+\((?P<cc>[A-Z]{3})\)$")
_NOTE = re.compile(r"\[(?P<note>[^\]]*)\]")
_FINAL_WORDS = frozenset({"final", "finale", "endspiel"})

SKIP_REASONS = {
    "BILINMEYEN_SATIR": "satır biçimi tanınmadı",
    "SKOR_OKUNAMADI": "skor tanınan biçimlerden birine uymuyor",
    "UZATMA_NORMAL_SURE_YOK": "uzatmalı veya penaltılı maçın normal süre skoru yazılmamış",
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


def is_final(stage: str | None, extra: frozenset = frozenset()) -> bool:
    """Tarafsız sahadaki tur mu: aşama adının son parçası "Final" ya da ``extra`` içindeki (küçük harfli) bir ad."""
    if not stage:
        return False
    last = str(stage).split(",")[-1].strip().lower()
    return last in _FINAL_WORDS or last in extra


def _split_team(text: str, default_cc: str = "") -> tuple[str, str]:
    m = _CC.match(text.strip())
    return (m["name"], m["cc"]) if m else (text.strip(), default_cc)


def _score(text: str) -> tuple[dict | None, str | None]:
    """Skor metni -> (skor sözlüğü, None) veya (None, atlama nedeni). Kurallar modül açıklamasında."""
    sc = _SCORE.match(re.sub(r"\s+", " ", text.strip()))
    if sc is None or (sc["p1"] is None and sc["f1"] is None):
        return None, "SKOR_OKUNAMADI"
    pair = (lambda a, b: [int(sc[a]), int(sc[b])] if sc[a] is not None else None)
    pen, f, a, b = pair("p1", "p2"), pair("f1", "f2"), pair("a1", "a2"), pair("b1", "b2")
    score: dict = {}
    if sc["aet"]:  # uzatma: f uzatmalar sonu, a normal süre, b ilk yarı
        if a is None:
            return None, "UZATMA_NORMAL_SURE_YOK"
        score["ft"], score["et"] = a, f
        if b is not None:
            score["ht"] = b
    elif f is None:  # uzatmasız penaltı: a normal süre, b ilk yarı
        if a is None:
            return None, "UZATMA_NORMAL_SURE_YOK"
        score["ft"] = a
        if b is not None:
            score["ht"] = b
    else:  # normal süre: f, ilk yarı a (normal maçta iki parantez skoru olmaz)
        if b is not None:
            return None, "SKOR_OKUNAMADI"
        score["ft"] = f
        if a is not None:
            score["ht"] = a
    if pen is not None:
        score["pen"] = pen
    # Normal sürenin berabere bitmesi aranmaz: iki ayaklı eşleşmede uzatmaya/penaltıya toplam skor götürür (ilk maç 1-0,
    # rövanş 1-0 -> rövanşta uzatma)
    ht = score.get("ht")
    if ht is not None and (ht[0] > score["ft"][0] or ht[1] > score["ft"][1]):
        return None, "SKOR_OKUNAMADI"  # ilk yarı skoru maç sonundan büyük olamaz
    return score, None


def parse_cup_txt(data: bytes, season_dir: str, default_cc: str = "",
                  neutral_rounds: frozenset = frozenset()) -> CupParse:
    """Kupa dosyasının baytlarından maç listesi (``season_dir``: "2025-26"). ``default_cc``: ülke kodu yazılmamış
    takımların ülkesi (yurt içi kupa); ``neutral_rounds``: finalden başka tarafsız sahadaki turlar (küçük harf)."""
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
        if " v " in rest_line:
            m = _MATCH_CC.match(rest_line) or _MATCH.match(rest_line)
            home_txt, away_txt, rest = (m["home"], m["away"], (m["rest"] or "").strip()) if m else (None, None, "")
        else:  # skor-ortada satır (yurt içi depolar); notu skordan sonra okunur
            m = _MATCH_MID.match(rest_line)
            home_txt, away_txt = (m["home"], m["away"]) if m else (None, None)
            rest = f"{m['score']} {m['note'] or ''}".strip() if m else ""
        if m is None:
            res.skip(lineno, "BILINMEYEN_SATIR", s)
            continue
        if time_txt is not None:
            last_time = time_txt.replace(".", ":").zfill(5)
        if day is None:
            res.skip(lineno, day_err or "TARIH_YOK", s)
            continue
        home, cc1 = _split_team(home_txt, default_cc)
        away, cc2 = _split_team(away_txt, default_cc)
        if not home or not away or (home, cc1) == (away, cc2):
            res.skip(lineno, "TAKIM_GECERSIZ", s)
            continue
        note = _NOTE.search(rest)
        if note:
            n = note["note"].strip().lower()
            res.skip(lineno, "NOT_HUKMEN" if n.startswith("award") else
                     "NOT_IPTAL" if n.startswith(("cancel", "postpon", "abandon", "suspend")) else "NOT_DIGER", s)
            continue
        rec = {"round": stage, "date": day.isoformat(), "time": last_time, "team1": home, "team2": away,
               "cc1": cc1, "cc2": cc2, "neutral": is_final(stage, neutral_rounds), "line": lineno}
        if rest:
            score, why = _score(rest)
            if score is None:
                res.skip(lineno, why, s)
                continue
            rec["score"] = score
        res.matches.append(rec)
    return res

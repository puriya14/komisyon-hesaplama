"""openfootball Football.TXT sezon dosyaları (FIKSTUR-03).

openfootball'un derlenmiş JSON deposunda (football.json) güncel sezon dosyası olmayan ligler için (ör. 2026-27'de
Süper Lig, İskoçya, Yunanistan, 2. Bundesliga, Avusturya, İsviçre) aynı topluluğun ulusal metin depolarındaki
Football.TXT dosyaları okunur. Depoların hepsi CC0 1.0'dır; lisans dosyası football.json'unkiyle aynı git nesnesidir
(670154e3538863b2). Dosya football.json biçimine çevrilir; fikstür, takvim kapsamı (uygunluk) ve eksik dönemin
tamamlanması (VERI-02) aynı kodla çalışır.

Dönüştürücü bilinçli olarak dardır ve tahmin yapmaz:

* Yalnızca tanıdığı satır biçimlerini okur: tur başlığı (``▪``/``»``), tarih satırı ("Fri Aug 14 2026", "Sat Aug 15",
  "[Sat Aug/15]", "2026-08-15"), maç satırı (isteğe bağlı saat; "Ev  2-1 (1-0)  Deplasman", "Ev  v  Deplasman",
  "Ev v Deplasman 2-1 (1-0)") ve gol satırları (parantez bloğu; atlanır). Tanımadığı satır atlanır ve nedeniyle
  sayılır; maç uydurulmaz.
* Yılı yazılmayan tarihin yılı önceki tarihten (yoksa sezondan) çıkarılır. Haftanın günü yazılmışsa tarihle uyuşması
  şarttır; uyuşmayan veya sezon penceresi dışındaki tarihin altındaki maçlar atlanır. Tarihi olmayan maç ("TBC",
  tarihsiz tur) atlanır.
* Saat yazılmayan satır aynı günün önceki saatini taşır (Football.TXT'de saat yalnızca değişince yazılır). Hiç
  oynanmamış bir turun bütün maçları aynı gün ve aynı saatteyse bu saat kaynağın yer tutucusudur (ör. openligadb'nin
  kesinleşmemiş turları): saat boş bırakılır, arayüz "saat bilinmiyor" gösterir.
* Uzatma, penaltı, hükmen ve benzeri notlu skorlar okunmaz (satır atlanır): normal süre sonucu olduğu kanıtlanamaz.

Çıktı deterministiktir: aynı dosya baytları aynı JSON baytlarını verir (köken doğrulaması buna dayanır).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field

TXT_CONVERTER = "football-txt-v1"
TXT_FORMAT = "football.txt"
TXT_BRANCH = "master"
TXT_RAW_BASE = "https://raw.githubusercontent.com"


@dataclass(frozen=True)
class TxtFile:
    """openfootball metin deposundaki bir lig dosyası. ``path`` içindeki ``{season}`` openfootball sezon adıdır
    ("2026-27"; takvim yılı liglerinde "2026")."""
    repo: str
    path: str

    def resolve(self, season: str) -> str:
        return self.path.format(season=season)

    def url(self, season: str) -> str:
        return f"{TXT_RAW_BASE}/{self.repo}/{TXT_BRANCH}/{self.resolve(season)}"

    def label(self, season: str) -> str:
        return f"{self.repo}:{self.resolve(season)}"


_EU, _EN, _DE = "openfootball/europe", "openfootball/england", "openfootball/deutschland"
_ES, _IT = "openfootball/espana", "openfootball/italy"

# Lig -> aday dosyalar (sırayla denenir). Yalnızca depoda en az bir sezonu görülen yollar; yalnızca openfootball kodu
# olan ligler (``leagues.League.openfootball``). football.json'da dosya varsa o kullanılır; bunlar yalnızca yedektir.
TXT_FILES: dict[str, tuple[TxtFile, ...]] = {
    "T1": (TxtFile(_EU, "turkey/{season}_tr1.txt"),),
    "E0": (TxtFile(_EN, "{season}/1-premierleague.txt"),),
    "E1": (TxtFile(_EN, "{season}/2-championship.txt"),),
    "E2": (TxtFile(_EN, "{season}/3-league1.txt"),),
    "E3": (TxtFile(_EN, "{season}/4-league2.txt"),),
    "SC0": (TxtFile(_EU, "scotland/{season}_sco1.txt"),),
    "D1": (TxtFile(_DE, "{season}/1-bundesliga.txt"),),
    "D2": (TxtFile(_DE, "{season}/2-bundesliga2.txt"), TxtFile(_DE, "openliga/{season}_de.2.txt")),
    "I1": (TxtFile(_IT, "{season}/1-seriea.txt"),),
    "I2": (TxtFile(_IT, "{season}/2-serieb.txt"),),
    "SP1": (TxtFile(_ES, "{season}/1-liga.txt"),),
    "SP2": (TxtFile(_ES, "{season}/2-liga2.txt"),),
    "F1": (TxtFile(_EU, "france/{season}_fr1.txt"),),
    "F2": (TxtFile(_EU, "france/{season}_fr2.txt"),),
    "N1": (TxtFile(_EU, "netherlands/{season}_nl1.txt"),),
    "B1": (TxtFile("openfootball/belgium", "{season}/be1.txt"),),
    "P1": (TxtFile(_EU, "portugal/{season}_pt1.txt"),),
    "G1": (TxtFile(_EU, "greece/{season}_gr1.txt"),),
    "AUT": (TxtFile("openfootball/austria", "{season}/1-bundesliga.txt"),),
    "BRA": (TxtFile("openfootball/south-america", "brazil/{season}_br1.txt"),),
    "DNK": (TxtFile(_EU, "denmark/{season}_dk1.txt"),),
    "SWZ": (TxtFile(_EU, "switzerland/{season}_ch1.txt"),),
}
TXT_REPOS = tuple(sorted({f.repo for files in TXT_FILES.values() for f in files}))

_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"), start=1)}
_DOWS = {d: i for i, d in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}
_DOW = r"(?P<dow>mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?"
_MON = r"(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATE_TEXT = re.compile(rf"^(?:{_DOW}\s+)?{_MON}\s+(?P<day>\d{{1,2}})(?:,?\s+(?P<year>\d{{4}}))?$", re.I)
_DATE_BRACKET = re.compile(rf"^\[(?:{_DOW}\s+)?{_MON}/(?P<day>\d{{1,2}})(?:\s+(?P<year>\d{{4}}))?\]$", re.I)
_DATE_ISO = re.compile(r"^(?P<year>\d{4})-(?P<mon>\d{2})-(?P<day>\d{2})$")
_TBC = re.compile(r"^(?:tbc|tbd|tba|n/a)\b", re.I)
_TIME = re.compile(r"^(?P<time>\d{1,2}[:.]\d{2}|--:--|-:-)\s+(?P<rest>\S.*)$")
_SCORE = r"(?P<f1>\d{1,2})-(?P<f2>\d{1,2})(?:\s+\((?P<h1>\d{1,2})-(?P<h2>\d{1,2})\))?"
_MID = re.compile(r"^(?P<home>\S.*?)\s{2,}" + _SCORE + r"\s{2,}(?P<away>\S.*)$")
_VS = re.compile(r"^(?P<home>\S.*?)\s+v\s+(?P<away>\S.*?)(?:\s+" + _SCORE + r")?$")
_HAS_VS = re.compile(r"\sv\s")
_FOOTNOTE = re.compile(r"\s*\(\*+\)\s*$")

# Atlanan satır nedenleri
SKIP_REASONS = {
    "BILINMEYEN_SATIR": "satır biçimi tanınmadı",
    "MAC_SATIRI_OKUNAMADI": "maç satırı tanınan biçimlerden birine uymuyor (ör. uzatma/penaltı/hükmen notu)",
    "TARIH_YOK": "maçın tarihi kaynakta yok (TBC veya tarihsiz tur)",
    "TARIH_GUN_UYUSMAZ": "yazılan haftanın günü tarihle uyuşmuyor",
    "TARIH_SEZON_DISI": "tarih sezon penceresinin dışında",
    "TARIH_GECERSIZ": "tarih geçersiz",
    "NOT_ISARETI": "satırda anlamı bilinmeyen not işareti ([...])",
    "TAKIM_GECERSIZ": "takım adı boş veya iki takım aynı",
    "GOL_BLOGU_KAPANMADI": "gol satırı parantezi kapanmadan yeni tur/tarih başladı",
}


@dataclass
class TxtParse:
    name: str = ""
    matches: list = field(default_factory=list)  # football.json biçiminde maç sözlükleri
    skipped: Counter = field(default_factory=Counter)  # neden -> satır sayısı
    samples: list = field(default_factory=list)  # [(satır no, neden, satır)] ilk birkaç örnek
    placeholder_times: int = 0  # yer tutucu olduğu için boşaltılan saat sayısı

    def skip(self, lineno: int, reason: str, line: str) -> None:
        self.skipped[reason] += 1
        if len(self.samples) < 8:
            self.samples.append((lineno, reason, line.strip()[:120]))


def _season_bounds(season: str) -> tuple[int, bool, dt.date, dt.date]:
    """(başlangıç yılı, takvim yılı mı, pencere başı, pencere sonu)."""
    start = int(str(season)[:4])
    if "-" in str(season):
        return start, False, dt.date(start, 6, 1), dt.date(start + 1, 7, 31)
    return start, True, dt.date(start, 1, 1), dt.date(start + 1, 2, 28)


def _parse_date(text: str, prev: dt.date | None, start: int, calendar: bool):
    """Tarih satırı ise (tarih | None, hata kodu | None); tarih satırı değilse ``False``."""
    s = text.strip()
    m = _DATE_ISO.match(s)
    if m:
        try:
            return dt.date(int(m["year"]), int(m["mon"]), int(m["day"])), None
        except ValueError:
            return None, "TARIH_GECERSIZ"
    m = _DATE_TEXT.match(s) or _DATE_BRACKET.match(s)
    if not m:
        return False
    mon, day = _MONTHS[m["mon"][:3].lower()], int(m["day"])
    try:
        if m["year"]:
            d = dt.date(int(m["year"]), mon, day)
        elif prev is not None:
            # Önceki tarihe en yakın yıl (yıl geçişi ileri; ertelenen maç blokları gibi geriye dönüşler de olur)
            cands = []
            for y in (prev.year - 1, prev.year, prev.year + 1):
                try:
                    cands.append(dt.date(y, mon, day))
                except ValueError:  # 29 Şubat
                    continue
            if not cands:
                raise ValueError
            d = min(cands, key=lambda c: abs((c - prev).days))
        else:
            d = dt.date(start if calendar or mon >= 7 else start + 1, mon, day)
    except ValueError:
        return None, "TARIH_GECERSIZ"
    if m["dow"] and _DOWS[m["dow"][:3].lower()] != d.weekday():
        return None, "TARIH_GUN_UYUSMAZ"
    return d, None


def _score(m) -> dict | None:
    if m["f1"] is None:
        return None
    out = {"ft": [int(m["f1"]), int(m["f2"])]}
    if m["h1"] is not None:
        out["ht"] = [int(m["h1"]), int(m["h2"])]
    return out


def parse_football_txt(data: bytes, season: str) -> TxtParse:
    """Football.TXT baytlarından football.json biçiminde maç listesi (``season``: "2026-27" veya "2026")."""
    from .parsers import decode_bytes

    start, calendar, lo, hi = _season_bounds(season)
    res = TxtParse()
    rnd: str | None = None
    day: dt.date | None = None
    day_err: str | None = "TARIH_YOK"  # ilk tarih satırından önce maç olursa tarihi yoktur
    last_date: dt.date | None = None
    last_time = ""
    depth = 0  # gol satırı parantez derinliği
    for lineno, raw in enumerate(decode_bytes(data).splitlines(), start=1):
        line = raw.rstrip()
        s = line.strip()
        if not s:
            continue
        if depth > 0:
            # Gol bloğu: kapanmadan tur başlığı veya tarih gelirse blok bozuktur (kalan dosya yutulmaz)
            if s[0] in "▪»" or _parse_date(s, last_date, start, calendar) is not False:
                res.skip(lineno, "GOL_BLOGU_KAPANMADI", s)
                depth = 0
            else:
                depth += s.count("(") - s.count(")")
                continue
        if s.startswith("#"):
            continue
        if s.startswith("="):
            if not res.name:
                res.name = s.lstrip("= ").strip()
            continue
        if s[0] in "▪»":
            # Yeni tur önceki turun tarihini taşımaz: tarih satırı olmayan tur (ör. "datum TBC") tarihsizdir
            rnd = s[1:].strip() or None
            day, day_err, last_time = None, "TARIH_YOK", ""
            continue
        if s.startswith("("):
            depth = s.count("(") - s.count(")")
            continue
        parsed = _parse_date(s, last_date, start, calendar)
        if parsed is not False:
            day, day_err = parsed
            last_time = ""
            if day is not None:
                if not (lo <= day <= hi):
                    day, day_err = None, "TARIH_SEZON_DISI"
                else:
                    last_date = day
            continue
        if _TBC.match(s):
            day, day_err, last_time = None, "TARIH_YOK", ""
            continue
        t = _TIME.match(s)
        rest, time_txt = (t["rest"], t["time"]) if t else (s, None)
        rest = _FOOTNOTE.sub("", rest).strip()
        if "[" in rest or "]" in rest:
            res.skip(lineno, "NOT_ISARETI", s)
            continue
        m = _VS.match(rest) if _HAS_VS.search(rest) else _MID.match(rest)
        if m is None:
            res.skip(lineno, "MAC_SATIRI_OKUNAMADI" if (t or _HAS_VS.search(rest)) else "BILINMEYEN_SATIR", s)
            continue
        if time_txt is not None:
            last_time = "" if "-" in time_txt else time_txt.replace(".", ":").zfill(5)
        if day is None:
            res.skip(lineno, day_err or "TARIH_YOK", s)
            continue
        home, away = m["home"].strip(), m["away"].strip()
        if not home or not away or home == away:
            res.skip(lineno, "TAKIM_GECERSIZ", s)
            continue
        rec = {"round": rnd, "date": day.isoformat(), "time": last_time, "team1": home, "team2": away}
        sc = _score(m)
        if sc is not None:
            rec["score"] = sc
        res.matches.append(rec)
    if depth > 0:
        res.skip(lineno, "GOL_BLOGU_KAPANMADI", "")
    _blank_placeholder_times(res)
    return res


def _blank_placeholder_times(res: TxtParse) -> None:
    """Hiç oynanmamış ve en az 4 maçlı bir turun bütün maçları aynı gün ve aynı saatteyse saat yer tutucudur."""
    by_round: dict[str, list[dict]] = {}
    for m in res.matches:
        if m["round"]:
            by_round.setdefault(m["round"], []).append(m)
    for ms in by_round.values():
        if len(ms) < 4 or any("score" in m for m in ms):
            continue
        if len({(m["date"], m["time"]) for m in ms}) == 1 and ms[0]["time"]:
            for m in ms:
                m["time"] = ""
            res.placeholder_times += len(ms)


def convert_football_txt(data: bytes, season: str, source: str = "") -> tuple[bytes, TxtParse]:
    """Football.TXT -> football.json biçiminde JSON baytları (deterministik) ve ayrıştırma özeti. JSON'daki
    ``donusum`` alanı kökeni taşır (asıl dosya özeti ve dönüştürücü sürümü); diğer okuyucular bu alanı yok sayar."""
    res = parse_football_txt(data, season)
    obj = {"name": res.name, "matches": res.matches,
           "donusum": {"bicim": TXT_FORMAT, "donusturucu": TXT_CONVERTER, "kaynak": source,
                       "kaynak_sha256": hashlib.sha256(data).hexdigest(), "atlanan": dict(sorted(res.skipped.items())),
                       "yer_tutucu_saat": res.placeholder_times}}
    out = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return out, res


def converted_origin(data: bytes) -> dict | None:
    """Dönüştürülmüş JSON ise ``donusum`` kaydı; football.json dosyası ise None."""
    try:
        obj = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    d = obj.get("donusum") if isinstance(obj, dict) else None
    return d if isinstance(d, dict) and d.get("bicim") == TXT_FORMAT else None

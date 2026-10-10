"""Ham veri dosyalarını ortak maç tablosu biçimine dönüştüren ayrıştırıcılar.

Desteklenen kaynaklar:
  * football-data.co.uk sezon dosyaları (mmz4281/{sezon}/{lig}.csv)
  * football-data.co.uk ek lig dosyaları (new/{ülke}.csv)
  * football-data.co.uk fikstür dosyaları (fixtures.csv, new_league_fixtures.csv)
  * GitHub yedek veri seti (xgabora/Club-Football-Match-Data, aynı kaynaktan derlenmiş)
  * openfootball JSON fikstürleri (yalnızca yedek fikstür kaynağı)
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .leagues import LEAGUES, MIRROR_TO_CODE, season_for_date, season_label, season_start_year

STAT_MAP = {
    "h_shots": "HS", "a_shots": "AS", "h_sot": "HST", "a_sot": "AST",
    "h_corners": "HC", "a_corners": "AC", "h_fouls": "HF", "a_fouls": "AF",
    "h_yellow": "HY", "a_yellow": "AY", "h_red": "HR", "a_red": "AR",
}
STAT_COLUMNS = list(STAT_MAP)
ODDS_COLUMNS = [
    "o_h", "o_d", "o_a", "omax_h", "omax_d", "omax_a",
    "b365_h", "b365_d", "b365_a", "ps_h", "ps_d", "ps_a",
    "oc_h", "oc_d", "oc_a", "o_o25", "o_u25", "omax_o25", "omax_u25",
]
MATCH_COLUMNS = (
    ["league", "season", "date", "time", "home", "away", "fthg", "ftag", "hthg", "htag"]
    + STAT_COLUMNS + ODDS_COLUMNS + ["source"]
)
FIXTURE_COLUMNS = ["league", "date", "time", "home", "away"] + ODDS_COLUMNS + ["source"]

# Ortalama/maksimum oran sütunu yoksa satır bazında kullanılacak bahis şirketi önekleri
_BOOKIE_PREFIXES = (
    "B365", "BW", "IW", "LB", "PS", "WH", "VC", "SJ", "SB", "GB", "BS", "SO", "SY",
    "1XB", "BFD", "BMGM", "BV", "CL",
)

COUNTRY_TO_CODE = {
    "Argentina": "ARG", "Austria": "AUT", "Brazil": "BRA", "China": "CHN",
    "Denmark": "DNK", "Finland": "FIN", "Ireland": "IRL", "Japan": "JPN",
    "Mexico": "MEX", "Norway": "NOR", "Poland": "POL", "Romania": "ROU",
    "Russia": "RUS", "Sweden": "SWE", "Switzerland": "SWZ", "USA": "USA",
}


# ----------------------------------------------------------------------------
# Genel yardımcılar
# ----------------------------------------------------------------------------

def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def read_csv_robust(data: bytes) -> pd.DataFrame:
    """Hatalı satırları (fazla/eksik virgül) kaybetmeden CSV okur. Tüm hücreler metindir."""
    text = decode_bytes(data)
    rows = [r for r in csv.reader(io.StringIO(text)) if r and any(c.strip() for c in r)]
    if not rows:
        return pd.DataFrame()
    header = [h.strip() for h in rows[0]]
    while header and not header[-1]:
        header.pop()
    seen: dict[str, int] = {}
    cols = []
    for i, h in enumerate(header):
        h = h or f"_col{i}"
        if h in seen:
            seen[h] += 1
            h = f"{h}_{seen[h]}"
        else:
            seen[h] = 0
        cols.append(h)
    n = len(cols)
    body = [(r + [""] * (n - len(r)))[:n] for r in rows[1:]]
    df = pd.DataFrame(body, columns=cols, dtype=object)
    df = df.apply(lambda s: s.str.strip() if s.dtype == object else s)
    return df.replace("", np.nan)


def parse_dates(s: pd.Series) -> pd.Series:
    """dd/mm/yyyy, dd/mm/yy ve yyyy-mm-dd biçimlerini destekler."""
    s = s.astype("string").str.strip()
    out = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    for fmt in ("%d/%m/%y", "%Y-%m-%d", "%d.%m.%Y"):
        m = out.isna() & s.notna()
        if not m.any():
            break
        out = out.where(~m, pd.to_datetime(s.where(m), format=fmt, errors="coerce"))
    return out.dt.normalize()


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(np.nan, index=df.index, dtype=float)


def _first(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    out = pd.Series(np.nan, index=df.index, dtype=float)
    for c in cols:
        if c in df.columns:
            out = out.fillna(_num(df, c))
    return out


def _odds(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce").astype(float)
    return s.where((s > 1.0) & (s < 1000.0))


def _bookie_frame(df: pd.DataFrame, suffix: str) -> pd.DataFrame:
    cols = [p + suffix for p in _BOOKIE_PREFIXES if p + suffix in df.columns]
    if not cols:
        return pd.DataFrame(index=df.index)
    return pd.DataFrame({c: _odds(df[c]) for c in cols}, index=df.index)


def _clean_time(s: pd.Series) -> pd.Series:
    s = s.astype("string").str.strip()
    hhmm = s.str.extract(r"(\d{1,2}):(\d{2})")
    out = hhmm[0].str.zfill(2) + ":" + hhmm[1]
    return out.fillna("").astype(object)


def _odds_block(df: pd.DataFrame) -> dict[str, pd.Series]:
    """football-data.co.uk sütunlarından standart oran sütunlarını üretir."""
    res: dict[str, pd.Series] = {}
    for side, suf in (("h", "H"), ("d", "D"), ("a", "A")):
        books = _bookie_frame(df, suf)
        avg = _odds(_first(df, [f"Avg{suf}", f"BbAv{suf}"]))
        mx = _odds(_first(df, [f"Max{suf}", f"BbMx{suf}"]))
        if not books.empty:
            avg = avg.fillna(books.mean(axis=1))
            mx = mx.fillna(books.max(axis=1))
        # Ek liglerde yalnızca kapanış oranları bulunabilir
        avg = avg.fillna(_odds(_first(df, [f"AvgC{suf}"])))
        mx = mx.fillna(_odds(_first(df, [f"MaxC{suf}"])))
        res[f"o_{side}"] = avg
        res[f"omax_{side}"] = mx.fillna(avg)
        res[f"b365_{side}"] = _odds(_first(df, [f"B365{suf}", f"B365C{suf}"]))
        res[f"ps_{side}"] = _odds(_first(df, [f"PS{suf}", f"P{suf}", f"PSC{suf}"]))
        res[f"oc_{side}"] = _odds(_first(df, [f"AvgC{suf}", f"PSC{suf}"]))
        res[f"o_{side}"] = res[f"o_{side}"].fillna(res[f"b365_{side}"]).fillna(res[f"ps_{side}"])
        res[f"omax_{side}"] = res[f"omax_{side}"].fillna(res[f"o_{side}"])
    for side, sign in (("o25", ">2.5"), ("u25", "<2.5")):
        avg = _odds(_first(df, [f"Avg{sign}", f"BbAv{sign}", f"B365{sign}", f"P{sign}", f"GB{sign}"]))
        mx = _odds(_first(df, [f"Max{sign}", f"BbMx{sign}"]))
        res[f"o_{side}"] = avg
        res[f"omax_{side}"] = mx.fillna(avg)
    return res


def _finish(out: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for c in columns:
        if c not in out.columns:
            out[c] = np.nan
    out = out[columns]
    out = out.dropna(subset=["date", "home", "away"])
    out["home"] = out["home"].astype(str).str.strip()
    out["away"] = out["away"].astype(str).str.strip()
    out = out[(out["home"] != "") & (out["away"] != "") & (out["home"] != out["away"])]
    return out.reset_index(drop=True)


# ----------------------------------------------------------------------------
# football-data.co.uk
# ----------------------------------------------------------------------------

def normalize_main(raw: pd.DataFrame, league: str, season: str) -> pd.DataFrame:
    """Sezonluk ana lig dosyası (ör. mmz4281/2526/T1.csv)."""
    if raw.empty:
        return pd.DataFrame(columns=MATCH_COLUMNS)
    df = raw
    out = pd.DataFrame(index=df.index)
    out["league"] = league
    out["season"] = season
    out["date"] = parse_dates(df["Date"]) if "Date" in df.columns else pd.NaT
    out["time"] = _clean_time(df["Time"]) if "Time" in df.columns else ""
    out["home"] = df.get("HomeTeam", df.get("Home"))
    out["away"] = df.get("AwayTeam", df.get("Away"))
    out["fthg"] = _first(df, ["FTHG", "HG"])
    out["ftag"] = _first(df, ["FTAG", "AG"])
    out["hthg"] = _num(df, "HTHG")
    out["htag"] = _num(df, "HTAG")
    for k, c in STAT_MAP.items():
        out[k] = _num(df, c)
    for k, s in _odds_block(df).items():
        out[k] = s
    out["source"] = "football-data.co.uk"
    out = out.dropna(subset=["fthg", "ftag"])
    return _finish(out, MATCH_COLUMNS)


def _season_from_text(text: str, calendar_year: bool) -> str | None:
    m = re.match(r"^\s*(\d{4})\s*/\s*(\d{2,4})\s*$", str(text))
    if m:
        start = int(m.group(1))
        return f"{start}/{(start + 1) % 100:02d}"
    m = re.match(r"^\s*(\d{4})\s*$", str(text))
    if m:
        return m.group(1)
    return None


def normalize_extra(raw: pd.DataFrame, league: str) -> pd.DataFrame:
    """Ek lig dosyası (ör. new/BRA.csv): tüm sezonlar tek dosyada."""
    if raw.empty:
        return pd.DataFrame(columns=MATCH_COLUMNS)
    lg = LEAGUES[league]
    df = raw
    out = pd.DataFrame(index=df.index)
    out["league"] = league
    out["date"] = parse_dates(df["Date"])
    if "Season" in df.columns:
        out["season"] = [
            _season_from_text(s, lg.calendar_year) for s in df["Season"].astype(str)
        ]
    else:
        out["season"] = None
    missing = out["season"].isna() & out["date"].notna()
    if missing.any():
        out.loc[missing, "season"] = [
            season_for_date(d.date(), lg.calendar_year) for d in out.loc[missing, "date"]
        ]
    out["time"] = _clean_time(df["Time"]) if "Time" in df.columns else ""
    out["home"] = df.get("Home", df.get("HomeTeam"))
    out["away"] = df.get("Away", df.get("AwayTeam"))
    out["fthg"] = _first(df, ["HG", "FTHG"])
    out["ftag"] = _first(df, ["AG", "FTAG"])
    for k, s in _odds_block(df).items():
        out[k] = s
    out["source"] = "football-data.co.uk"
    out = out.dropna(subset=["fthg", "ftag"])
    return _finish(out, MATCH_COLUMNS)


def normalize_fixtures(raw: pd.DataFrame) -> pd.DataFrame:
    """fixtures.csv ve new_league_fixtures.csv dosyaları."""
    if raw.empty:
        return pd.DataFrame(columns=FIXTURE_COLUMNS)
    df = raw
    out = pd.DataFrame(index=df.index)
    if "Div" in df.columns:
        out["league"] = df["Div"].astype(str).str.strip()
    elif "Country" in df.columns:
        out["league"] = df["Country"].astype(str).str.strip().map(COUNTRY_TO_CODE)
    else:
        return pd.DataFrame(columns=FIXTURE_COLUMNS)
    out["date"] = parse_dates(df["Date"])
    out["time"] = _clean_time(df["Time"]) if "Time" in df.columns else ""
    out["home"] = df.get("HomeTeam", df.get("Home"))
    out["away"] = df.get("AwayTeam", df.get("Away"))
    for k, s in _odds_block(df).items():
        out[k] = s
    out["source"] = "football-data.co.uk"
    out = out[out["league"].isin(LEAGUES.keys())]
    return _finish(out, FIXTURE_COLUMNS)


# ----------------------------------------------------------------------------
# GitHub yedek veri seti (xgabora/Club-Football-Match-Data)
# ----------------------------------------------------------------------------

def normalize_mirror(raw: pd.DataFrame, leagues: list[str] | None = None) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=MATCH_COLUMNS)
    df = raw.copy()
    df["league"] = df["Division"].astype(str).map(MIRROR_TO_CODE)
    df = df[df["league"].notna()]
    if leagues is not None:
        df = df[df["league"].isin(leagues)]
    if df.empty:
        return pd.DataFrame(columns=MATCH_COLUMNS)
    out = pd.DataFrame(index=df.index)
    out["league"] = df["league"]
    out["date"] = pd.to_datetime(df["MatchDate"], errors="coerce").dt.normalize()
    out["time"] = _clean_time(df["MatchTime"]) if "MatchTime" in df.columns else ""
    out["home"] = df["HomeTeam"]
    out["away"] = df["AwayTeam"]
    out["fthg"] = _num(df, "FTHome")
    out["ftag"] = _num(df, "FTAway")
    out["hthg"] = _num(df, "HTHome")
    out["htag"] = _num(df, "HTAway")
    mstats = {
        "h_shots": "HomeShots", "a_shots": "AwayShots", "h_sot": "HomeTarget",
        "a_sot": "AwayTarget", "h_corners": "HomeCorners", "a_corners": "AwayCorners",
        "h_fouls": "HomeFouls", "a_fouls": "AwayFouls", "h_yellow": "HomeYellow",
        "a_yellow": "AwayYellow", "h_red": "HomeRed", "a_red": "AwayRed",
    }
    for k, c in mstats.items():
        out[k] = _num(df, c)
    for side, c, mc in (("h", "OddHome", "MaxHome"), ("d", "OddDraw", "MaxDraw"), ("a", "OddAway", "MaxAway")):
        b365 = _odds(_num(df, c))
        out[f"o_{side}"] = b365
        out[f"b365_{side}"] = b365
        out[f"omax_{side}"] = _odds(_num(df, mc)).fillna(b365)
    out["o_o25"] = _odds(_num(df, "Over25"))
    out["o_u25"] = _odds(_num(df, "Under25"))
    out["omax_o25"] = _odds(_num(df, "MaxOver25")).fillna(out["o_o25"])
    out["omax_u25"] = _odds(_num(df, "MaxUnder25")).fillna(out["o_u25"])
    out["source"] = "github-yedek"
    out = out.dropna(subset=["fthg", "ftag", "date"])
    out["season"] = assign_seasons(out)
    return _finish(out, MATCH_COLUMNS)


def assign_seasons(df: pd.DataFrame) -> pd.Series:
    """Sezon bilgisi olmayan veride sezonları tarihlerden çıkarır.

    Yaz aylarında (Temmuz-Eylül) 20 günden uzun aradan sonra gelen ilk maç yeni
    sezonun başlangıcı sayılır; böylece 2019/20 gibi yaza sarkan sezonlar doğru
    etiketlenir.
    """
    out = pd.Series(index=df.index, dtype=object)
    for lg, g in df.groupby("league"):
        cal = LEAGUES[lg].calendar_year if lg in LEAGUES else False
        if cal:
            out.loc[g.index] = [season_label(d.year, True) for d in g["date"]]
            continue
        dates = np.sort(g["date"].unique())
        starts = [dates[0]]
        for prev, cur in zip(dates[:-1], dates[1:]):
            gap = (cur - prev) / np.timedelta64(1, "D")
            # 150 günden uzun boşluk: veri kesintisi, yeni sezondan devam
            if (gap >= 20 and pd.Timestamp(cur).month in (7, 8, 9)) or gap >= 150:
                starts.append(cur)
        labels = [season_label(season_start_year(pd.Timestamp(s).date())) for s in starts]
        idx = np.searchsorted(np.array(starts), g["date"].values, side="right") - 1
        out.loc[g.index] = [labels[i] for i in idx]
    return out


# ----------------------------------------------------------------------------
# openfootball (yedek fikstür kaynağı)
# ----------------------------------------------------------------------------

def openfootball_team_names(data: bytes) -> list[str]:
    """Sezon dosyasındaki (oynanmış ve oynanmamış) bütün takım adları: ad eşlemesinin bağlamı."""
    try:
        obj = json.loads(decode_bytes(data))
    except ValueError:
        return []
    names: dict[str, None] = {}
    for m in obj.get("matches", []) if isinstance(obj, dict) else []:
        if not isinstance(m, dict):
            continue
        for t in (m.get("team1"), m.get("team2")):
            t = t.get("name") if isinstance(t, dict) else t
            if t and str(t).strip():
                names[str(t).strip()] = None
    return list(names)


def parse_openfootball(data: bytes, league: str, keep_provider_id: bool = False) -> pd.DataFrame:
    """openfootball/football.json biçimindeki sezon dosyasından oynanmamış maçlar.

    ``keep_provider_id``: kaynakta maç kimliği (``id``) varsa ``provider_id`` sütununda tutulur (yoksa boş)."""
    cols = FIXTURE_COLUMNS + (["provider_id"] if keep_provider_id else [])
    try:
        obj = json.loads(decode_bytes(data))
    except ValueError:
        return pd.DataFrame(columns=cols)
    rows = []
    for m in obj.get("matches", []):
        score = m.get("score")
        if isinstance(score, dict):
            played = bool(score.get("ft"))
        elif isinstance(score, list):
            played = len(score) >= 2 and score[0] is not None and score[1] is not None
        else:
            played = False
        if played or (m.get("score1") is not None and m.get("score2") is not None):
            continue
        t1, t2 = m.get("team1"), m.get("team2")
        if isinstance(t1, dict):
            t1 = t1.get("name")
        if isinstance(t2, dict):
            t2 = t2.get("name")
        if not t1 or not t2 or not m.get("date"):
            continue
        pid = m.get("id")
        rows.append({
            "league": league,
            "date": m.get("date"),
            "time": str(m.get("time") or "")[:5],
            "home": t1,
            "away": t2,
            "provider_id": str(pid) if isinstance(pid, (str, int)) and not isinstance(pid, bool) else None,
        })
    if not rows:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows)
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    out["time"] = _clean_time(out["time"])
    out["source"] = "openfootball"
    return _finish(out, cols)


# ----------------------------------------------------------------------------
# openfootball sonuçları (S4-PILOT-01: tek ligde gerçek veri pilotu)
# ----------------------------------------------------------------------------

OPENFOOTBALL_RESULT_LABEL = "openfootball-sonuc"  # sonuç satırlarının kaynak etiketi (fikstür etiketi "openfootball")
OPENFOOTBALL_RESULT_PARSER = "openfootball-sonuc-v1"
_OF_SCORE_KEYS = frozenset({"ht", "ft", "et", "p"})
_OF_NOT_PLAYED = frozenset({"postponed", "cancelled", "canceled", "abandoned", "suspended"})

# Sağlayıcının kendi kulüp kaydındaki doğrulanmış alternatif adlar -> kanonik ad (lig başına). football.json eski
# sezonlarda "Manchester City", 2020/21'den itibaren "Manchester City FC" yazar; ikisi ayrı takım sayılırsa takım
# geçmişi sezon sınırında kopar. Kanıt: openfootball/clubs commit ae3800227c449447b3a337fc0aac79a8f02f4c8b,
# europe/england/eng.clubs.txt (git nesnesi 685470b0704b, CC0 1.0): her ad kayıtta YALNIZCA bu kulübün alternatif
# adı olarak listelenir. Yalnızca pilot verisinde görülen adlar; ek silme veya benzerlikle otomatik birleştirme YOK.
OPENFOOTBALL_CLUB_ALIAS_SOURCE = "openfootball/clubs@ae3800227c449447b3a337fc0aac79a8f02f4c8b:europe/england/eng.clubs.txt"
OPENFOOTBALL_CLUB_ALIASES: dict[str, dict[str, str]] = {
    "E0": {
        "Aston Villa": "Aston Villa FC", "Brighton & Hove Albion": "Brighton & Hove Albion FC",
        "Crystal Palace": "Crystal Palace FC", "Huddersfield Town": "Huddersfield Town AFC",
        "Hull City": "Hull City AFC", "Leicester City": "Leicester City FC",
        "Manchester City": "Manchester City FC", "Manchester United": "Manchester United FC",
        "Newcastle United": "Newcastle United FC", "Norwich City": "Norwich City FC",
        "Sheffield United": "Sheffield United FC", "Stoke City": "Stoke City FC",
        "Tottenham Hotspur": "Tottenham Hotspur FC", "West Bromwich Albion": "West Bromwich Albion FC",
        "West Ham United": "West Ham United FC", "Wolverhampton Wanderers": "Wolverhampton Wanderers FC",
    },
}


@dataclass
class ResultParse:
    """Bir openfootball sezon dosyasının sonuç ayrıştırması. ``matches`` yalnızca geçerli tamamlanmış maçlar
    (``MATCH_COLUMNS`` + ``kaynak_ozeti``); ``karantina`` kayda alınmayan kayıtların nedenleri (takım adı yok)."""
    matches: pd.DataFrame
    sha256: str
    toplam: int = 0
    oynanmis: int = 0
    ht: int = 0
    yalniz_ft: int = 0
    oynanmamis: int = 0
    oynanmamis_durumlu: int = 0
    yinelenen: int = 0
    karantina: list = field(default_factory=list)  # [{"neden": KOD, "tarih": "YYYY-MM-DD"|None, "tur": str|None}]
    takim: int = 0
    tur: int = 0
    ilk_tarih: str | None = None
    son_tarih: str | None = None
    son_tamamlanan: str | None = None
    tamamlanmamis_tarihler: list = field(default_factory=list)  # oynanmamış maçların tarihleri (bayatlık ölçümü)
    ad_eslemesi: dict = field(default_factory=dict)  # kaynak adı -> sağlayıcı kaydındaki kanonik ad (uygulananlar)

    def ozet(self) -> dict:
        from collections import Counter

        return {"toplam": self.toplam, "oynanmis_gecerli": self.oynanmis, "ilk_yari_gecerli": self.ht,
                "yalniz_mac_sonu": self.yalniz_ft, "oynanmamis": self.oynanmamis,
                "oynanmamis_durumlu": self.oynanmamis_durumlu, "yinelenen": self.yinelenen,
                "karantina": dict(Counter(k["neden"] for k in self.karantina)), "takim": self.takim, "tur": self.tur,
                "ilk_tarih": self.ilk_tarih, "son_tarih": self.son_tarih, "son_tamamlanan": self.son_tamamlanan,
                "kanonik_ad_eslemesi": dict(sorted(self.ad_eslemesi.items()))}


def _of_pair(v) -> tuple[tuple[int, int] | None, str | None]:
    """[ev, deplasman] skor çifti: tam sayı (bool değil), negatif değil, makul aralıkta."""
    if not (isinstance(v, (list, tuple)) and len(v) == 2):
        return None, "BICIM_BILINMIYOR"
    if any(isinstance(x, bool) or not isinstance(x, int) for x in v):
        return None, "SKOR_GECERSIZ"
    if any(x < 0 or x > 30 for x in v):
        return None, "SKOR_GECERSIZ"
    return (int(v[0]), int(v[1])), None


def _of_score(m: dict) -> tuple[str, tuple | None, tuple | None, str | None]:
    """(durum, ms, iy, karantina_nedeni). durum: OYNANDI / OYNANMADI / KARANTINA.

    Biçimler: ``score: {"ft": [a, b], "ht": [c, d]}`` (ht isteğe bağlı), ``score: [a, b]`` (yalnızca maç sonu; ilk
    yarı YOK sayılır, uydurulmaz), eski ``score1``/``score2``. Uzatma/penaltı alanı (et/p) lig maçında belirsizdir."""
    s = m.get("score")
    if s is None:
        s1, s2 = m.get("score1"), m.get("score2")
        if s1 is None and s2 is None:
            return "OYNANMADI", None, None, None
        ft, err = _of_pair([s1, s2])
        return ("OYNANDI", ft, None, None) if err is None else ("KARANTINA", None, None, err)
    if isinstance(s, list):
        ft, err = _of_pair(s)
        return ("OYNANDI", ft, None, None) if err is None else ("KARANTINA", None, None, err)
    if not isinstance(s, dict) or not s or not set(s) <= _OF_SCORE_KEYS or "ft" not in s:
        return "KARANTINA", None, None, "BICIM_BILINMIYOR"
    if "et" in s or "p" in s:
        return "KARANTINA", None, None, "UZATMA_ALANI"
    ft, err = _of_pair(s["ft"])
    if err:
        return "KARANTINA", None, None, err
    ht = None
    if "ht" in s:
        ht, err = _of_pair(s["ht"])
        if err:
            return "KARANTINA", None, None, err
        if ht[0] > ft[0] or ht[1] > ft[1]:
            return "KARANTINA", None, None, "IY_MS_CELISKI"
    return "OYNANDI", ft, ht, None


def parse_openfootball_results(data: bytes, league: str, season: str) -> ResultParse:
    """openfootball sezon dosyasındaki tamamlanmış maç sonuçları (normal süre). Belirsiz/çelişkili kayıt karantinaya
    alınır; birebir tekrar sayılmaz; aynı anahtarla farklı içerik ikisi birden karantinaya alınır. Eksik ilk yarı
    eksik kalır (0-0 yapılmaz); 0-0 gerçek sonuçtur. Takım adları yalnızca sağlayıcının kulüp kaydındaki doğrulanmış
    alternatif adlarla (``OPENFOOTBALL_CLUB_ALIASES``) kanonik ada çevrilir; tekrar/çakışma/aynı gün denetimleri
    kanonik adla yapılır. Deterministik (aynı dosya → aynı satırlar)."""
    import hashlib
    from collections import Counter

    aliases = OPENFOOTBALL_CLUB_ALIASES.get(league, {})
    sha = hashlib.sha256(data).hexdigest()
    try:
        obj = json.loads(decode_bytes(data))
    except ValueError:
        return ResultParse(pd.DataFrame(columns=MATCH_COLUMNS + ["kaynak_ozeti"]), sha,
                           karantina=[{"neden": "DOSYA_OKUNAMADI", "tarih": None, "tur": None}])
    raw = obj.get("matches") if isinstance(obj, dict) else None
    if not isinstance(raw, list):
        return ResultParse(pd.DataFrame(columns=MATCH_COLUMNS + ["kaynak_ozeti"]), sha,
                           karantina=[{"neden": "BICIM_BILINMIYOR", "tarih": None, "tur": None}])
    res = ResultParse(pd.DataFrame(), sha, toplam=len(raw))
    # Sezon penceresi: 1. turun ilk günü .. +400 gün. Dışındaki tarih (ör. yılı yanlış yazılmış kayıt) karantinaya
    # alınır; yıl tahmin edilip düzeltilmez.
    from ..eligibility import round_number

    first_round = []
    for m in raw:
        if isinstance(m, dict) and isinstance(m.get("round"), str) and round_number(m["round"]) == 1:
            try:
                first_round.append(dt.date.fromisoformat(m.get("date")))
            except (TypeError, ValueError):
                pass
    season_start = min(first_round) if first_round else None
    kept: dict[tuple, dict] = {}
    conflict: set[tuple] = set()
    teams, rounds, dates, open_dates = set(), set(), [], []
    for m in raw:
        if not isinstance(m, dict):
            res.karantina.append({"neden": "BICIM_BILINMIYOR", "tarih": None, "tur": None})
            continue
        t1, t2 = m.get("team1"), m.get("team2")
        t1 = t1.get("name") if isinstance(t1, dict) else t1
        t2 = t2.get("name") if isinstance(t2, dict) else t2
        rnd = m.get("round") if isinstance(m.get("round"), str) else None
        d = m.get("date")
        try:
            day = dt.date.fromisoformat(d) if isinstance(d, str) else None
        except ValueError:
            day = None
        if day is None:
            res.karantina.append({"neden": "TARIH_GECERSIZ", "tarih": None, "tur": rnd})
            continue
        if season_start is not None and not (season_start <= day <= season_start + dt.timedelta(days=400)):
            res.karantina.append({"neden": "TARIH_SEZON_DISI", "tarih": str(day), "tur": rnd})
            continue
        if not (isinstance(t1, str) and isinstance(t2, str) and t1.strip() and t2.strip()
                and t1.strip() != t2.strip()):
            res.karantina.append({"neden": "TAKIM_GECERSIZ", "tarih": str(day), "tur": rnd})
            continue
        t1, t2 = t1.strip(), t2.strip()
        for t in (t1, t2):
            if t in aliases:
                res.ad_eslemesi[t] = aliases[t]
        t1, t2 = aliases.get(t1, t1), aliases.get(t2, t2)
        if t1 == t2:
            res.karantina.append({"neden": "TAKIM_GECERSIZ", "tarih": str(day), "tur": rnd})
            continue
        teams |= {t1, t2}
        if rnd:
            rounds.add(rnd)
        dates.append(day)
        state, ft, ht, err = _of_score(m)
        status = m.get("status")
        if status is not None:
            st_norm = str(status).strip().lower()
            if st_norm in _OF_NOT_PLAYED and state == "OYNANMADI":
                res.oynanmamis_durumlu += 1
                continue
            state, err = "KARANTINA", "DURUM_BELIRSIZ"  # skorlu ertelenmiş, hükmen vb.: normal süre sonucu değil
        if state == "KARANTINA":
            res.karantina.append({"neden": err, "tarih": str(day), "tur": rnd})
            continue
        if state == "OYNANMADI":
            res.oynanmamis += 1
            open_dates.append(day)
            continue
        pid = m.get("id")
        key = (("id", str(pid)) if isinstance(pid, (str, int)) and not isinstance(pid, bool) else ("mac", day, t1, t2))
        content = {"date": day, "home": t1, "away": t2, "round": rnd, "ft": ft, "ht": ht,
                   "time": str(m.get("time") or "")[:5]}
        alt = ("mac", day, t1, t2)  # farklı tur etiketiyle aynı maç da aynı olaydır
        prev = kept.get(key) or kept.get(alt)
        if prev is not None:
            if (prev["ft"], prev["ht"]) == (ft, ht) and (prev["home"], prev["away"]) == (t1, t2):
                res.yinelenen += 1  # birebir tekrar: sayımı artırmaz
            else:
                conflict.add(key if key in kept else alt)
                res.karantina.append({"neden": "CAKISAN_KAYIT", "tarih": str(day), "tur": rnd})
            continue
        kept[key] = content
        if key != alt:
            kept[alt] = content
    seen_ids = set()
    rows = []
    for key, c in kept.items():
        if id(c) in seen_ids:
            continue
        seen_ids.add(id(c))
        if key in conflict or ("mac", c["date"], c["home"], c["away"]) in conflict:
            res.karantina.append({"neden": "CAKISAN_KAYIT", "tarih": str(c["date"]), "tur": c["round"]})
            continue
        rows.append(c)
    # Aynı gün iki kez oynayan takım: kayıtlardan hangisinin doğru olduğu bilinemez (ikisi de karantina)
    per_day = Counter((c["date"], t) for c in rows for t in (c["home"], c["away"]))
    bad = {k for k, n in per_day.items() if n > 1}
    if bad:
        keep = []
        for c in rows:
            if (c["date"], c["home"]) in bad or (c["date"], c["away"]) in bad:
                res.karantina.append({"neden": "AYNI_GUN_IKI_MAC", "tarih": str(c["date"]), "tur": c["round"]})
            else:
                keep.append(c)
        rows = keep
    res.oynanmis = len(rows)
    res.ht = sum(1 for c in rows if c["ht"] is not None)
    res.yalniz_ft = res.oynanmis - res.ht
    res.takim, res.tur = len(teams), len(rounds)
    res.ilk_tarih = str(min(dates)) if dates else None
    res.son_tarih = str(max(dates)) if dates else None
    res.son_tamamlanan = str(max(c["date"] for c in rows)) if rows else None
    res.tamamlanmamis_tarihler = sorted(str(x) for x in open_dates)
    if not rows:
        res.matches = pd.DataFrame(columns=MATCH_COLUMNS + ["kaynak_ozeti"])
        return res
    out = pd.DataFrame({
        "league": league, "season": season, "date": pd.to_datetime([str(c["date"]) for c in rows]),
        "time": [c["time"] for c in rows], "home": [c["home"] for c in rows], "away": [c["away"] for c in rows],
        "fthg": [c["ft"][0] for c in rows], "ftag": [c["ft"][1] for c in rows],
        "hthg": [float(c["ht"][0]) if c["ht"] is not None else np.nan for c in rows],
        "htag": [float(c["ht"][1]) if c["ht"] is not None else np.nan for c in rows],
    })
    out["time"] = _clean_time(out["time"])
    out["source"] = OPENFOOTBALL_RESULT_LABEL
    out = _finish(out, MATCH_COLUMNS)
    out = out.sort_values(["date", "home", "away"], kind="mergesort").reset_index(drop=True)
    out["kaynak_ozeti"] = sha
    res.matches = out
    return res

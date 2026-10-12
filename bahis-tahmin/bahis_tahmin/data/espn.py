"""ESPN'in herkese açık skor tablosu uç noktası (KAYNAK-04, KAYNAK-05).

Verisi football-data.co.uk'tan gelmeyen Serie B, La Liga 2, Ligue 2, Süper Lig ve 2. Bundesliga için fikstür, eksik
dönem sonuçları ve sezon takvimi. ESPN'den veri gelen ligde openfootball kullanılmaz; ESPN'e ulaşılamazsa openfootball
yedeği (FIKSTUR-03) çalışır.

**Kullanım koşulları.** Uç nokta belgelenmemiştir ve açık bir lisans metni yoktur. Bu yüzden kaynak yalnızca kullanıcının
indirme onayıyla kullanılır. Sonuçlar model eğitimi ve tahminde yalnızca kişisel (ticari olmayan) kullanım beyanıyla
kullanılabilir (``source_registry``). GitHub veri profilinde kullanılmaz.

**Okuma kuralları (tahmin yapılmaz).**

* Yalnızca normal sürede biten maç (``STATUS_FULL_TIME``) sonuç sayılır. Uzatma, penaltı ve benzeri durumlar okunmaz.
* İlk yarı skoru yalnızca iki devre skoru varsa ve toplamı maç sonucuna eşitse alınır; yoksa bilinmiyor kalır.
* Ertelenen, iptal edilen ve yarıda kalan maçlar takvimde durumlarıyla tutulur; fikstür veya sonuç sayılmaz.
* Saat kaynakta kesin değilse (``timeValid: false``) boş bırakılır.

**Takım kimliği.** ESPN adları veri deposunun adlarına yalnızca kanıtla çevrilir (``map_teams``):

1. aynı ad (yazım farkı hariç), ya da
2. maç kanıtı: aynı lig, tarih ±1 gün, aynı MS skoru (ikisinde de varsa aynı İY skoru) ve tek aday. En az 3 tekil maç,
   oyların en az %90'ı tek takımda ve ev ile deplasman oyları aynı takımda olmalıdır. VERI-01 ile aynı kuraldır.
3. Güncel sezonda maç kanıtı yetmeyen adlar için sezon kadrosu kısıtı: iki kaynağın kadrosu aynı büyüklükte, diğer
   bütün adlar kanıtla eşleşmiş ve kalan her ad bütün oylarıyla kalan takımlardan tekine işaret ediyor. Tek ad tek
   takım kaldıysa eleme ile eşlenir.

Aynı ad kanıtla çelişirse ya da iki ad aynı takıma düşerse eşleme yapılmaz. Eşleşmeyen adın maçı fikstürde nedenli
"tahmin yok" olarak gösterilir ve sonucu veriye eklenmez. Benzerlikle eşleme yapılmaz.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_LABEL = "espn"  # veri deposu ve fikstür kaynak etiketi
ESPN_PARSER = "espn-scoreboard-v1"
ESPN_MATCHING = "espn-eslesme-v1"
# Lig -> ESPN lig kodu. Kullanıcının istediği ligler: KAYNAK-04 (başka güncel kaynağı olmayan Serie B, La Liga 2,
# Ligue 2) ve KAYNAK-05 (openfootball metin dosyası 11 Eylül'de kalan Süper Lig ve 2. Bundesliga).
ESPN_LEAGUES: dict[str, str] = {"I2": "ita.2", "SP2": "esp.2", "F2": "fra.2", "T1": "tur.1", "D2": "ger.2"}

NORMAL_FINISH = frozenset({"STATUS_FULL_TIME", "STATUS_FINAL"})
NOT_PLAYED = {"STATUS_POSTPONED": "postponed", "STATUS_CANCELED": "cancelled", "STATUS_CANCELLED": "cancelled",
              "STATUS_ABANDONED": "abandoned", "STATUS_SUSPENDED": "suspended"}
MIN_N, MIN_SHARE = 3, 0.90  # maç kanıtı eşikleri (VERI-01 ile aynı)
EVIDENCE_DAYS = 1  # maç kanıtında tarih toleransı
PAIR_DAYS = 3  # depoda aynı eşleşme varsa sonuç eklenmez (tamamlama ile aynı tolerans)

SKIP_REASONS = {
    "BICIM_BILINMIYOR": "olay kaydı beklenen biçimde değil",
    "TARIH_GECERSIZ": "tarih okunamadı",
    "TAKIM_GECERSIZ": "ev/deplasman takımı okunamadı",
    "SKOR_GECERSIZ": "skor okunamadı veya makul aralıkta değil",
    "NORMAL_SURE_DISI": "normal süre dışında biten maç (uzatma, penaltı, hükmen vb.)",
}


@dataclass(frozen=True)
class EspnEvent:
    event_id: str
    date: dt.date  # lig ülkesinin yerel tarihi
    time: str  # yerel "SS:DD"; kaynakta kesin değilse ""
    home: str
    away: str
    state: str  # pre / in / post
    status: str  # ESPN durum adı
    ft: tuple | None = None  # normal süre sonucu
    ht: tuple | None = None  # ilk yarı (yalnızca tutarlı devre skorlarından)


@dataclass
class EspnParse:
    events: list = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)


def month_chunks(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """[start, end] aralığını takvim aylarına böler (her istek bir ay)."""
    out, a = [], start
    while a <= end:
        nxt = (a.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        b = min(nxt - dt.timedelta(days=1), end)
        out.append((a, b))
        a = nxt
    return out


def scoreboard_url(slug: str, a: dt.date, b: dt.date) -> str:
    return f"{ESPN_BASE}/{slug}/scoreboard?dates={a:%Y%m%d}-{b:%Y%m%d}&limit=500"


def _tz(country: str):
    from ..timeutil import _TZ_OK, COUNTRY_TZ

    name = COUNTRY_TZ.get(country)
    if name and _TZ_OK:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(name)
        except Exception:
            pass
    return dt.timezone.utc


def _goals(v) -> int | None:
    if isinstance(v, dict):
        v = v.get("value", v.get("displayValue"))
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f < 0 or f > 30 or f != int(f):
        return None
    return int(f)


def _half(c: dict) -> int | None:
    ls = c.get("linescores")
    if not isinstance(ls, list) or len(ls) != 2:
        return None
    vals = [_goals(x) for x in ls]
    return None if None in vals else vals


def parse_scoreboard(data: bytes, country: str) -> EspnParse:
    """ESPN skor tablosu yanıtından maçlar. Tanınmayan kayıt atlanır ve nedeniyle sayılır."""
    res = EspnParse()
    try:
        obj = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        res.skipped["BICIM_BILINMIYOR"] += 1
        return res
    events = obj.get("events") if isinstance(obj, dict) else None
    if not isinstance(events, list):
        res.skipped["BICIM_BILINMIYOR"] += 1
        return res
    tz = _tz(country)
    for e in events:
        comp = (e.get("competitions") or [None])[0] if isinstance(e, dict) else None
        if not isinstance(comp, dict) or not isinstance(comp.get("competitors"), list):
            res.skipped["BICIM_BILINMIYOR"] += 1
            continue
        side = {}
        for c in comp["competitors"]:
            if isinstance(c, dict) and c.get("homeAway") in ("home", "away") and isinstance(c.get("team"), dict):
                name = str(c["team"].get("displayName") or c["team"].get("name") or "").strip()
                side[c["homeAway"]] = (name, c)
        if set(side) != {"home", "away"} or not side["home"][0] or not side["away"][0] \
                or side["home"][0] == side["away"][0]:
            res.skipped["TAKIM_GECERSIZ"] += 1
            continue
        try:
            ts = pd.Timestamp(str(comp.get("date") or e.get("date")))
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        except (TypeError, ValueError):
            res.skipped["TARIH_GECERSIZ"] += 1
            continue
        if comp.get("timeValid", True) is False:
            day, time = ts.date(), ""
        else:
            local = ts.to_pydatetime().astimezone(tz)
            day, time = local.date(), local.strftime("%H:%M")
        st = (comp.get("status") or e.get("status") or {}).get("type") or {}
        name, state = str(st.get("name") or ""), str(st.get("state") or "")
        ft = ht = None
        if st.get("completed") is True:
            if name not in NORMAL_FINISH:
                res.skipped["NORMAL_SURE_DISI"] += 1
                continue
            ft = (_goals(side["home"][1].get("score")), _goals(side["away"][1].get("score")))
            if None in ft:
                res.skipped["SKOR_GECERSIZ"] += 1
                continue
            hh, ha = _half(side["home"][1]), _half(side["away"][1])
            if hh and ha and hh[0] + hh[1] == ft[0] and ha[0] + ha[1] == ft[1]:
                ht = (hh[0], ha[0])
        res.events.append(EspnEvent(str(e.get("id") or f"{day}|{side['home'][0]}|{side['away'][0]}"), day, time,
                                    side["home"][0], side["away"][0], state, name, ft, ht))
    return res


# ----------------------------------------------------------------------------------------------- takım kimliği


@dataclass
class TeamMap:
    mapping: dict = field(default_factory=dict)  # ESPN adı -> depo adı
    basis: dict = field(default_factory=dict)  # ESPN adı -> kanıt
    unmapped: dict = field(default_factory=dict)  # ESPN adı -> (neden, öneriler)

    def record(self) -> dict:
        return {"surum": ESPN_MATCHING,
                "eslesme": {n: {"takim": t, "kanit": self.basis.get(n, "")} for n, t in sorted(self.mapping.items())},
                "eslesmeyen": {n: {"neden": r, "oneriler": list(s)} for n, (r, s) in sorted(self.unmapped.items())}}


def _votes(events, base: pd.DataFrame):
    """ESPN adı -> {"h": Counter, "a": Counter, "mac": set} (tek adaylı maç kanıtı)."""
    by_day: dict = {}
    for r in base.itertuples(index=False):
        by_day.setdefault(pd.Timestamp(r.date).date(), []).append(r)
    votes: dict = {}
    for e in events:
        if e.ft is None:
            continue
        cands = []
        for dd in range(-EVIDENCE_DAYS, EVIDENCE_DAYS + 1):
            for r in by_day.get(e.date + dt.timedelta(days=dd), ()):
                if (int(r.fthg), int(r.ftag)) != e.ft:
                    continue
                if e.ht is not None and pd.notna(r.hthg) and pd.notna(r.htag) and (int(r.hthg), int(r.htag)) != e.ht:
                    continue
                cands.append(r)
        if len(cands) != 1:
            continue
        c = cands[0]
        for side, name, team in (("h", e.home, c.home), ("a", e.away, c.away)):
            v = votes.setdefault(name, {"h": Counter(), "a": Counter(), "mac": set()})
            v[side][team] += 1
            v["mac"].add(e.event_id)
    return votes


def map_teams(events, base: pd.DataFrame, league: str, season_label: str, current) -> TeamMap:
    """ESPN adlarını kanıtla veri deposu adlarına çevirir (modül açıklaması). ``base``: ligin depo satırları (ESPN ve
    tamamlama satırları hariç); ``current``: güncel sezonun ESPN olayları (kadro kısıtı için)."""
    from .teams import resolve_teams

    tm = TeamMap()
    names = sorted({e.home for e in events} | {e.away for e in events})
    seasons = sorted(base["season"].dropna().astype(str).unique())[-2:]
    recent = base[base["season"].astype(str).isin(seasons)]
    known = sorted(set(recent["home"]) | set(recent["away"]))
    res = resolve_teams(names, known, league, ESPN_LABEL)
    votes = _votes(events, base)

    def tops(n):
        v = votes.get(n)
        if not v:
            return None, 0, 0.0, None, None
        tot = v["h"] + v["a"]
        top, cnt = tot.most_common(1)[0]
        hs = v["h"].most_common(1)[0][0] if v["h"] else None
        aw = v["a"].most_common(1)[0][0] if v["a"] else None
        return top, len(v["mac"]), cnt / sum(tot.values()), hs, aw

    for n in names:
        top, nm, share, hs, aw = tops(n)
        m = res[n]
        if m.exact:
            if top is not None and top != m.team and nm >= MIN_N and share >= MIN_SHARE:
                tm.unmapped[n] = ("KANIT_CELISKISI", (m.team, top))  # aynı ad başka takımın maçlarıyla eşleşiyor
                continue
            tm.mapping[n], tm.basis[n] = m.team, m.basis
        elif top is not None and nm >= MIN_N and share >= MIN_SHARE and hs == aw == top:
            tm.mapping[n], tm.basis[n] = top, f"mac_kaniti {nm} mac, %{100 * share:.0f}"
    # Kadro kısıtı (güncel sezon)
    cur_names = sorted({e.home for e in current} | {e.away for e in current})
    cur_store = base[base["season"].astype(str) == str(season_label)]
    roster = sorted(set(cur_store["home"]) | set(cur_store["away"]))
    rem_n = [n for n in cur_names if n not in tm.mapping and n not in tm.unmapped]
    rem_t = [t for t in roster if t not in set(tm.mapping.values())]
    if roster and len(cur_names) == len(roster) and rem_n and len(rem_n) == len(rem_t):
        pick = {}
        for n in rem_n:
            v = votes.get(n)
            tot = (v["h"] + v["a"]) if v else Counter()
            inside = {t: c for t, c in tot.items() if t in rem_t}
            if len(rem_n) == 1 and set(tot) <= {rem_t[0]}:
                pick[n] = (rem_t[0], f"kadro_eleme ({sum(tot.values())} oy)")
            elif len(inside) == 1 and sum(inside.values()) == sum(tot.values()):
                pick[n] = (next(iter(inside)), f"kadro_kisiti ({sum(tot.values())} oy)")
        if len(pick) == len(rem_n) and len({p[0] for p in pick.values()}) == len(pick):
            for n, (t, why) in pick.items():
                tm.mapping[n], tm.basis[n] = t, why
    # Birebirlik: iki ad aynı takıma düşüyorsa hangisinin o takım olduğu bilinemez
    by_team: dict = {}
    for n, t in tm.mapping.items():
        by_team.setdefault(t, []).append(n)
    for t, ns in by_team.items():
        if len(ns) > 1:
            for n in ns:
                del tm.mapping[n]
                tm.basis.pop(n, None)
                tm.unmapped[n] = ("TERS_CAKISMA", (t,))
    for n in names:
        if n not in tm.mapping and n not in tm.unmapped:
            tm.unmapped[n] = ("KANIT_YOK", tuple(res[n].suggestions or res[n].candidates))
    return tm


# --------------------------------------------------------------------------------------------- çıktılar


def calendar_json(events, tm: TeamMap, name: str) -> bytes:
    """Sezon takvimi, football.json biçiminde (uygunluk kontrolünün kapsam okuyucusu için). Eşleşen adlar depo
    adıyla, eşleşmeyenler "[ESPN] ad" biçiminde yazılır (depodaki bir takımla yanlışlıkla eşleşmesin)."""
    def nm(n):
        return tm.mapping.get(n) or f"[ESPN] {n}"

    matches = []
    for e in sorted(events, key=lambda x: (x.date, x.time, x.home)):
        rec = {"id": e.event_id, "date": e.date.isoformat(), "time": e.time, "team1": nm(e.home), "team2": nm(e.away)}
        if e.ft is not None:
            rec["score"] = {"ft": list(e.ft), **({"ht": list(e.ht)} if e.ht is not None else {})}
        elif e.status in NOT_PLAYED:
            rec["status"] = NOT_PLAYED[e.status]
        matches.append(rec)
    obj = {"name": name, "matches": matches, "kaynak": {"etiket": ESPN_LABEL, "ayristirici": ESPN_PARSER,
                                                        "eslesme": ESPN_MATCHING}}
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

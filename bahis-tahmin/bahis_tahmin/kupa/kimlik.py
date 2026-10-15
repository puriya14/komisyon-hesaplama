"""Kupa maçlarındaki takımların kimliği (KUPA-01).

Kupa kaynaklarının takım adları veri deposundaki (lig verisi) adlarla aynı değildir ("Manchester City FC (ENG)",
ESPN "Manchester City"; depoda "Man City"). Kimlik yalnızca kanıtla kurulur (``data.teams`` sözleşmesiyle aynı ilke):

**openfootball kupa dosyaları.** Takım adının yanındaki ülke kodu ("ENG") ülkeyi verir. Ad, o ülkenin veri deposundaki
takımları arasında ``data.teams.resolve_teams`` ile aranır (aynı/normal ad veya o ülke kapsamındaki doğrulanmış takma
ad). Bağlam tek dosyadır (bir turnuvanın bir sezonu): aynı kulübün yıllar içinde farklı yazılan adları ("Real Madrid",
"Real Madrid CF") ayrı dosyalarda kendi başlarına eşlenir. Belirsiz veya bulunamayan ad depodaki hiçbir takıma
bağlanmaz.

**ESPN.** ESPN her takıma turnuvadan bağımsız bir kimlik numarası verir. Bir numara depodaki bir takıma iki yoldan
bağlanır ve ikisi çelişirse bağlanmaz:

1. yurt içi lig kanıtı: aynı takımın ESPN'deki lig maçları, depodaki lig maçlarıyla maç kanıtıyla (tarih, skor; KAYNAK-04
   kuralı ``data.espn.map_teams``) eşlenmiştir;
2. kupa kanıtı: ESPN kupa maçları ile openfootball kupa maçları aynı turnuvada, tarih ±1 gün ve aynı normal süre (varsa
   ilk yarı) skoruyla tek adaylı eşleşir; en az iki maç ve oyların hepsi aynı takımda olmalıdır.

**Yurt içi kupa dosyaları (KUPA-IY-03).** Adlarda ülke kodu yoktur; ülke turnuvadan gelir. Bu dosyalarda depoda
olmayan alt lig ve amatör kulüpler çoktur ve ad normalleştirmesi ("CF Benfica" -> "benfica") farklı kulüpleri aynı
anahtara düşürebilir. Bu yüzden iki ek koruma uygulanır:

1. ters çakışma: aynı dosyada birden çok ad aynı depo takımına düşüyorsa yalnızca doğrulanmış takma adla eşleşenler
   bağlanır (Portekiz Kupası'nda "SL Benfica" takma adla Benfica'dır; amatör "CF Benfica" bağlanmaz);
2. kulüp türü eki çelişkisi: normal adla (takma ad olmadan) eşleşmede iki adın da kulüp türü eki varsa ve ortak eki
   yoksa bağlanmaz (2022'de kurulan "CD Extremadura", 2020'de dağılan "Extremadura UD" değildir).

Sezon kadrosu şartı aranmaz: depo liglerinden düşen kulüpler (ör. 3. kademedeki Bolton, Portsmouth) aynı kulüptür.

**Kapsam dışı takımlar.** Ligi uygulamada olmayan (ör. Çekya, Azerbaycan) veya depoda bulunamayan takımlar depodaki
bir takımla birleştirilmez; kendi kupa geçmişleriyle ayrı bir kimlik alır (openfootball: ülke kodu + normalleştirilmiş
ad; ESPN: kimlik numarası, kupa kanıtıyla openfootball kimliğine bağlanabilir). Bu takımların tahmini yapılabilir ama
veri uygunluğu onları "ligi veride yok" olarak işaretler (bahis adayı olmaz).

Benzerlikle eşleme yapılmaz; öneriler yalnızca raporda gösterilir.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from ..data.leagues import LEAGUES
from ..data.teams import norm_key, resolve_teams
from .turnuvalar import CC_COUNTRY

KIMLIK_SURUMU = "kupa-kimlik-v2"  # v2 (KUPA-IY-03): yurt içi kupa dosyalarında ters çakışma ve tür eki koruması
MIN_CUP_EVIDENCE = 2  # ESPN ↔ openfootball kupa kanıtı: en az bu kadar tekil maç ve oyların hepsi aynı takımda
# Kulüp türü ekleri (``data.teams`` normalleştirmesinin attığı parçaların kulüp türünü belirtenleri)
DESIGNATORS = frozenset({"fc", "cf", "afc", "sc", "ac", "as", "ssc", "ss", "cd", "ud", "sd", "rcd", "rc", "sv", "vfb",
                         "vfl", "tsg", "fsv", "bsc", "ogc", "cfc", "sk", "fk", "jk", "kv", "krc", "rsc", "sco", "aj",
                         "us", "if", "bk", "ik", "cp", "sl", "ad", "ce", "ca", "cs", "gd", "ssd", "spvgg", "rkc"})


@dataclass(frozen=True)
class TeamIdentity:
    key: str  # modelin takım anahtarı: "Ülke|depo adı" veya kapsam dışı "KOD|ad" / "ESPN|numara"
    name: str  # gösterim adı (depo adı veya kaynaktaki ad)
    country: str  # uygulamanın ülke adı, kapsam dışıysa FIFA kodu veya ""
    mapped: bool  # depodaki bir lig takımıyla aynı (kanıtla)
    basis: str = ""


def store_key(country: str, team: str) -> str:
    return f"{country}|{team}"


def outside_key(cc: str, name: str) -> str:
    return f"{cc or '?'}|{norm_key(name) or name}"


def espn_key(espn_id: str) -> str:
    return f"ESPN|{espn_id}"


def store_teams(matches: pd.DataFrame | None) -> dict[str, list[str]]:
    """Ülke -> veri deposunda o ülkenin liglerinde oynamış takımlar (bütün sezonlar)."""
    out: dict[str, set] = {}
    if matches is None or matches.empty:
        return {}
    for lg, g in matches.groupby("league"):
        lgi = LEAGUES.get(lg)
        if lgi is None:
            continue
        out.setdefault(lgi.country, set()).update(g["home"].astype(str))
        out[lgi.country].update(g["away"].astype(str))
    return {c: sorted(v) for c, v in out.items()}


def _country_league(country: str, matches: pd.DataFrame) -> str | None:
    """Takma ad kapsamı için ülkenin (depoda bulunan) bir lig kodu."""
    for code, lg in LEAGUES.items():
        if lg.country == country and (matches["league"] == code).any():
            return code
    return None


@dataclass
class OpenfootballMap:
    """openfootball kupa dosyası (bağlam) başına ad -> kimlik."""
    by_file: dict = field(default_factory=dict)  # (dosya etiketi, ülke kodu, ad) -> TeamIdentity
    unmapped: dict = field(default_factory=dict)  # (ülke kodu, ad) -> (neden, öneriler) — ülkesi kapsamda olanlar

    def get(self, label: str, cc: str, name: str) -> TeamIdentity:
        hit = self.by_file.get((label, cc, name))
        return hit if hit is not None else TeamIdentity(outside_key(cc, name), name, cc, False, "kapsam_disi")


def designators(name: str) -> frozenset:
    """Adın kulüp türü ekleri ("CD Extremadura" -> {"cd"}; "Extremadura UD" -> {"ud"})."""
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"\b([a-z])\.", r"\1", s)
    return frozenset(t for t in re.split(r"[^a-z0-9]+", s) if t in DESIGNATORS)


def map_openfootball(files: dict, matches: pd.DataFrame, domestic=None) -> OpenfootballMap:
    """``files``: dosya etiketi -> maç sözlükleri (``kupa.openfootball.parse_cup_txt``). Her dosya ayrı bağlamdır.

    ``domestic``: yurt içi kupa dosyalarının etiketleri; bu dosyalarda ters çakışma ve tür eki korumaları uygulanır
    (modül açıklaması)."""
    out = OpenfootballMap()
    teams = store_teams(matches)
    league_of = {c: _country_league(c, matches) for c in teams}
    domestic = set(domestic or ())
    for label, recs in files.items():
        by_cc: dict[str, set] = {}
        for r in recs:
            by_cc.setdefault(r.get("cc1", ""), set()).add(r["team1"])
            by_cc.setdefault(r.get("cc2", ""), set()).add(r["team2"])
        for cc, names in by_cc.items():
            country = CC_COUNTRY.get(cc)
            cands = teams.get(country, []) if country else []
            if not cands:
                for n in names:
                    out.by_file[(label, cc, n)] = TeamIdentity(outside_key(cc, n), n, cc, False,
                                                               "ligi_veride_yok" if country is None else "ulke_verisi_yok")
                continue
            res = resolve_teams(sorted(names), cands, league_of.get(country), "openfootball")
            if label in domestic:
                res = _domestic_guard(res)
            for n, m in res.items():
                if m.exact:
                    out.by_file[(label, cc, n)] = TeamIdentity(store_key(country, m.team), m.team, country, True,
                                                               f"{m.basis} ({m.evidence()})")
                else:
                    why = f"{m.status}:{m.basis}" if m.basis else m.status
                    out.by_file[(label, cc, n)] = TeamIdentity(outside_key(cc, n), n, cc, False, f"eslesmedi:{why}")
                    out.unmapped[(cc, n)] = (why, tuple(m.suggestions or m.candidates))
    return out


def _domestic_guard(res: dict) -> dict:
    """Yurt içi kupa dosyası için ters çakışma ve tür eki korumaları (``resolve_teams`` sonucuna)."""
    from dataclasses import replace

    from ..data.teams import BELIRSIZ, BULUNAMADI

    out = dict(res)
    by_team: dict[str, list[str]] = {}
    for n, m in res.items():
        if m.exact:
            by_team.setdefault(m.team, []).append(n)
    for team, ns in by_team.items():
        if len(ns) > 1 and any(res[n].basis == "takma_ad" for n in ns):
            for n in ns:
                if res[n].basis != "takma_ad":
                    out[n] = replace(res[n], team=None, status=BELIRSIZ, basis="ters_cakisma_yurt_ici",
                                     candidates=(team,))
    for n, m in out.items():
        if m.exact and m.basis != "takma_ad":
            a, b = designators(n), designators(m.team)
            if a and b and not (a & b):
                out[n] = replace(m, team=None, status=BULUNAMADI, basis="tur_eki_celiskisi", candidates=(m.team,))
    return out


@dataclass
class EspnMap:
    by_id: dict = field(default_factory=dict)  # ESPN numarası -> TeamIdentity
    names: dict = field(default_factory=dict)  # ESPN numarası -> son görülen ad
    conflicts: dict = field(default_factory=dict)  # ESPN numarası -> (kanıt 1, kanıt 2)

    def get(self, espn_id: str, name: str) -> TeamIdentity:
        if espn_id and espn_id in self.by_id:
            return self.by_id[espn_id]
        if espn_id:
            return TeamIdentity(espn_key(espn_id), self.names.get(espn_id, name), "", False, "espn_kapsam_disi")
        # Kimlik numarası olmayan kayıt (beklenmez): ad + ESPN önekiyle ayrı tutulur, hiçbir takımla birleşmez
        return TeamIdentity(f"ESPN-AD|{norm_key(name) or name}", name, "", False, "espn_numarasiz")


def domestic_espn_ids(events, team_map, country: str) -> dict[str, tuple[str, str]]:
    """Bir ligin ESPN olayları + o ligin ESPN ad eşlemesi (``data.espn.TeamMap``) -> numara -> (depo adı, kanıt).

    Bir numaranın farklı adları farklı takımlara düşüyorsa numara kullanılmaz."""
    seen: dict[str, set] = {}
    for e in events:
        for eid, nm in ((getattr(e, "home_id", ""), e.home), (getattr(e, "away_id", ""), e.away)):
            if eid and nm in team_map.mapping:
                seen.setdefault(eid, set()).add((team_map.mapping[nm], team_map.basis.get(nm, "")))
    out = {}
    for eid, vals in seen.items():
        teams = {t for t, _ in vals}
        if len(teams) == 1:
            t = next(iter(teams))
            out[eid] = (t, f"espn_lig_kaniti ({country}: {sorted(vals)[0][1]})")
    return out


def map_espn(events_by_comp: dict, domestic: dict, of_rows: pd.DataFrame | None) -> EspnMap:
    """ESPN kupa olayları (turnuva -> olaylar) için numara -> kimlik.

    ``domestic``: numara -> (ülke, depo adı, kanıt) — yurt içi lig kanıtı. ``of_rows``: openfootball kupa satırları
    (``kupa.veri.of_rows``: comp, date, fthg, ftag, hthg, htag, home, away, home_key, away_key, home_country,
    away_country, home_mapped, away_mapped) — kupa kanıtı."""
    out = EspnMap()
    for evs in events_by_comp.values():
        for e in evs:
            if getattr(e, "home_id", ""):
                out.names[e.home_id] = e.home
            if getattr(e, "away_id", ""):
                out.names[e.away_id] = e.away
    # 2) Kupa kanıtı: ESPN ↔ openfootball, aynı turnuva, tarih ±1, aynı skor, tek aday
    votes: dict[str, Counter] = {}
    ident: dict[str, TeamIdentity] = {}
    if of_rows is not None and not of_rows.empty:
        idx: dict = {}
        for r in of_rows.itertuples(index=False):
            idx.setdefault((r.comp, pd.Timestamp(r.date).date()), []).append(r)
        for comp, evs in events_by_comp.items():
            for e in evs:
                if e.ft is None:
                    continue
                cands = []
                for dd in (-1, 0, 1):
                    for r in idx.get((comp, e.date + dt.timedelta(days=dd)), ()):
                        if (int(r.fthg), int(r.ftag)) != tuple(e.ft):
                            continue
                        if e.ht is not None and pd.notna(r.hthg) and pd.notna(r.htag) and \
                                (int(r.hthg), int(r.htag)) != tuple(e.ht):
                            continue
                        cands.append(r)
                if len(cands) != 1:
                    continue
                c = cands[0]
                for eid, key, nm, ctry, mp in ((e.home_id, c.home_key, c.home, c.home_country, c.home_mapped),
                                               (e.away_id, c.away_key, c.away, c.away_country, c.away_mapped)):
                    if not eid:
                        continue
                    votes.setdefault(eid, Counter())[(key, e.event_id)] += 1
                    ident[key] = TeamIdentity(key, nm, ctry, bool(mp), "")
    cup_ev: dict[str, tuple[str, int]] = {}
    for eid, cnt in votes.items():
        keys = Counter()
        for (key, _ev), _n in cnt.items():
            keys[key] += 1
        if len(keys) == 1:
            key, n = keys.most_common(1)[0]
            if n >= MIN_CUP_EVIDENCE:
                cup_ev[eid] = (key, n)
    for eid in sorted(set(domestic) | set(cup_ev)):
        dom = domestic.get(eid)
        cup = cup_ev.get(eid)
        if dom is not None:
            country, team, why = dom
            key = store_key(country, team)
            if cup is not None and cup[0] != key:
                out.conflicts[eid] = (f"lig: {key}", f"kupa: {cup[0]}")
                continue
            basis = why + (f" + kupa_kaniti {cup[1]} maç" if cup else "")
            out.by_id[eid] = TeamIdentity(key, team, country, True, basis)
        elif cup is not None:
            key, n = cup
            base = ident[key]
            out.by_id[eid] = TeamIdentity(key, base.name, base.country, base.mapped, f"kupa_kaniti {n} maç")
    return out

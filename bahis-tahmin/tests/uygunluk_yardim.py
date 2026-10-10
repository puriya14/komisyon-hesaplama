"""Veri uygunluk testleri için SENTETİK yardımcılar (S3-GATE-01).

Buradaki veriler, kaynak takvimleri ve haklar AÇIKÇA SENTETİKTİR (kaynak etiketi ``sentetik``, hak kaydı
``SENTETIK-TEST``). Gerçek maç analizi veya gerçek entegrasyon kanıtı değildir; gerçek kaynak kaydına
(``source_registry``) dokunulmaz.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from bahis_tahmin.eligibility import (
    FINISHED,
    POLICY_VERSION,
    SCHEDULED_OR_UNKNOWN,
    Eligibility,
    EligibilityContext,
    RightsStatus,
    ScheduledMatch,
    SourceCoverage,
    info_cutoff,
    state_view,
)
from bahis_tahmin.selftest import synthetic_matches

UTC = dt.timezone.utc
SYN_LABEL = "sentetik"


def synthetic_rights(label: str = SYN_LABEL, model_training: str = "IZINLI_BELGELI",
                     result_use: str = "IZINLI_BELGELI", access: str = "IZINLI") -> RightsStatus:
    """Testte açıkça belgeli sayılan SENTETİK kaynak hakları (gerçek kaynak kaydını değiştirmez)."""
    from bahis_tahmin.eligibility import SourceUse

    return RightsStatus({label: SourceUse(label, "SENTETIK-TEST", access, result_use, model_training,
                                          "IZIN_VARSAYILMAZ")})


# Sabit, gerçek saatten bağımsız test anı: v2 protokol dondurma gününden sonra; sentetik veri 2020/21–2025/26
# sezonlarını (Ağustos–Mart) içerir ve bu andan önce biter.
AS_OF = dt.datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
FIXTURE_DAY = dt.date(2026, 11, 4)


def recent_synthetic(n_seasons: int = 6, n_teams: int = 16, seed: int = 1, half_time: bool = True) -> pd.DataFrame:
    """Son sezonu ``AS_OF``dan önce biten sentetik lig."""
    return synthetic_matches(n_seasons=n_seasons, n_teams=n_teams, seed=seed, start_year=2026 - n_seasons,
                             half_time=half_time)


def season_coverage(matches: pd.DataFrame, season: str, retrieved_at: dt.datetime, league: str = "T1",
                    drop: set | None = None, extra: list | None = None, complete: bool = True) -> SourceCoverage:
    """Depodaki bir sezonun maçlarından (tamamlanmış) sentetik tam sezon takvimi."""
    g = matches[(matches["league"] == league) & (matches["season"].astype(str) == season)]
    out = []
    for r in g.itertuples(index=False):
        out.append(ScheduledMatch(pd.Timestamp(r.date).date(), r.home, r.away, r.home, r.away, FINISHED))
    out += list(extra or [])
    if drop:
        out = [m for m in out if (m.home, m.away, m.date) not in drop]
    return SourceCoverage(league, "SENTETIK-TAKVIM", season, retrieved_at, tuple(out), complete,
                          "sentetik takvim", f"sentetik-{season}-{len(out)}")


def next_season_schedule(matches: pd.DataFrame, start: dt.date, retrieved_at: dt.datetime, season: str,
                         league: str = "T1") -> SourceCoverage:
    """Yeni sezonun tam (henüz oynanmamış) sentetik fikstür takvimi: haftalık turlar, çift devre."""
    teams = sorted(set(matches["home"]) | set(matches["away"]))
    pairs = [(h, a) for h in teams for a in teams if h != a]
    per_round = len(teams) // 2
    out = [ScheduledMatch(start + dt.timedelta(days=7 * (k // per_round)), h, a, h, a, SCHEDULED_OR_UNKNOWN)
           for k, (h, a) in enumerate(pairs)]
    return SourceCoverage(league, "SENTETIK-TAKVIM", season, retrieved_at, tuple(out), True, "sentetik fikstür",
                          f"sentetik-{season}-fikstur")


def full_context(matches: pd.DataFrame, engine, as_of: dt.datetime, fixture_day: dt.date | None = None,
                 rights: RightsStatus | None = None, drop: set | None = None,
                 schedule: pd.DataFrame | None = None, retrieved: dt.datetime | None = None) -> EligibilityContext:
    """Sentetik depo + motor durumu + bütün sezonların tam takvimi + yeni sezon fikstürü + sentetik haklar.

    ``schedule``: kaynak takviminin kurulacağı TAM maç listesi (verilmezse depo; depo eksikken takvim tam
    kalsın diye ayrı verilir)."""
    sched = matches if schedule is None else schedule
    seasons = sorted(sched["season"].astype(str).unique())
    retrieved = retrieved or (as_of - dt.timedelta(hours=1))
    covs = [season_coverage(sched, s, retrieved, drop=drop) for s in seasons]
    last = seasons[-1]
    y = int(last.split("/")[0]) + 1
    nxt = f"{y}/{(y + 1) % 100:02d}"
    start = fixture_day or (info_cutoff(as_of) + dt.timedelta(days=3))
    covs.append(next_season_schedule(sched, start, retrieved, nxt))
    return EligibilityContext(matches, state_view(engine), {"T1": covs}, rights=rights or synthetic_rights())


def verified(event_id: str, market: str, as_of: dt.datetime, *, forecast_ok: bool = True, bet_ok: bool = True,
             reasons: tuple = (), state_digest: str = "") -> Eligibility:
    """Karar motoru birim testleri için doğrudan kurulmuş SENTETİK uygunluk sonucu (kullanıcı yolunda kullanılmaz)."""
    return Eligibility(
        candidate_id=event_id, canonical_id=True, league="T1", home="A", away="B", match_date="", market=market,
        evaluated_at=as_of.astimezone(UTC).isoformat(), info_cutoff=str(info_cutoff(as_of)), data_cutoff=None,
        data_scope={"sentetik": True}, state_scope={"durum_ozeti": state_digest} if state_digest else {},
        freshness="VERIFIED_CURRENT" if forecast_ok else "UNKNOWN", continuity="TAM", team_mapping="ESLESTI",
        required_fields="YETERLI", source_use={}, reasons=tuple(reasons), forecast_ok=forecast_ok, bet_ok=bet_ok,
        primary_text="sentetik", fix_text="-", policy_version=POLICY_VERSION, fingerprint="sentetik")

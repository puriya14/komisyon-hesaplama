"""Veri kapsamı denetimi: lig–sezon bazında sonuç, ilk yarı skoru, etiket ve oran kapsamı.

Üç katman ayrı raporlanır:
  A. Sonuç katmanı (maç sonu + ilk yarı skorları)
  B. Zenginleştirilmiş analiz katmanı (şut vb. istatistikler)
  C. Oran katmanı (ilgili pazarın GERÇEK oran kaydı)

Not: Geçmiş veriler bugün indirildiği için "o anda erişilebilirlik" kanıtlanamaz; tüm geçmiş
özellikler "yeniden oluşturulmuş (yalnızca maç tarihi bilinir)" statüsündedir.
"""

from __future__ import annotations

import pandas as pd

from ..data.leagues import LEAGUES
from ..data.source_registry import SOURCES
from .markets import PRIMARY_YES, SHORT, label_frame

SOURCE_KEYS = {"football-data.co.uk": "football-data", "github-yedek": "github-mirror"}
POINT_IN_TIME = "yeniden oluşturulmuş (yalnızca maç tarihi; yayın zamanı doğrulanamaz)"


def coverage_matrix(
    matches: pd.DataFrame, consent: dict | None = None, odds_counts: dict | None = None
) -> pd.DataFrame:
    """Her lig–sezon için kapsam satırı.

    odds_counts: {(lig, sezon, pazar): gerçek oran kaydı sayısı} (oran deposundan); yoksa 0.
    """
    if matches is None or matches.empty:
        return pd.DataFrame()
    consent = consent or {}
    odds_counts = odds_counts or {}
    lab = label_frame(matches, PRIMARY_YES)
    df = matches[["league", "season", "home", "away", "fthg", "ftag", "hthg", "htag", "h_sot", "o_o25", "source"]].copy()
    df = pd.concat([df, lab], axis=1)
    rows = []
    for (lg, season), g in df.groupby(["league", "season"], sort=False):
        teams = pd.unique(pd.concat([g["home"], g["away"]]))
        n_teams = len(teams)
        expected = n_teams * (n_teams - 1)
        src_names = sorted(set(g["source"].dropna()))
        src_keys = [SOURCE_KEYS.get(s, s) for s in src_names]
        lic = []
        for k in src_keys:
            info = SOURCES.get(k)
            if info is None:
                lic.append(f"{k}: bilinmiyor")
            elif not info.requires_consent:
                lic.append(f"{info.name}: serbest")
            else:
                lic.append(f"{info.name}: {'kullanıcı onaylı' if k in consent else 'ONAY YOK'}")
        row = {
            "league": lg,
            "season": season,
            "takim": n_teams,
            "beklenen_tahmini": expected,
            "bulunan": len(g),
            "ms_gecerli": int(g["fthg"].notna().sum()),
            "iy_gecerli": int((g["hthg"].notna() & g["htag"].notna() & (g["issues"] == "")).sum()),
            "iy_eksik": int((g["hthg"].isna() | g["htag"].isna()).sum()),
            "celiskili": int((g["issues"] != "").sum()),
            "sut_verisi": int(g["h_sot"].notna().sum()),
            "oran_2_5_gercek": int(g["o_o25"].notna().sum()),
        }
        for key in PRIMARY_YES:
            s = SHORT[key]
            row[f"{s}_bilinen"] = int(g[key].notna().sum())
            row[f"{s}_pozitif"] = int((g[key] == 1).sum())
            row[f"{s}_oran_gercek"] = int(odds_counts.get((lg, season, key), 0))
        row["kaynak"] = ", ".join(src_names)
        row["lisans"] = "; ".join(lic)
        row["zaman_dogrulama"] = POINT_IN_TIME
        rows.append(row)
    out = pd.DataFrame(rows)
    order = {c: i for i, c in enumerate(LEAGUES)}
    return out.sort_values(["league", "season"], key=lambda s: s.map(order) if s.name == "league" else s).reset_index(drop=True)


def coverage_summary(cov: pd.DataFrame) -> pd.DataFrame:
    """Lig bazında özet: kaç sezon sonuç, kaç sezon ilk yarı skoru, kaç sezon gerçek oran."""
    if cov.empty:
        return cov
    g = cov.groupby("league", sort=False)
    out = pd.DataFrame({
        "sezon_sonuc": g["ms_gecerli"].apply(lambda s: int((s > 0).sum())),
        "sezon_ilk_yari": g.apply(lambda d: int((d["iy_gecerli"] >= 0.9 * d["bulunan"]).sum()), include_groups=False),
        "sezon_A_orani": g["A_oran_gercek"].apply(lambda s: int((s > 0).sum())),
        "sezon_B_orani": g["B_oran_gercek"].apply(lambda s: int((s > 0).sum())),
        "sezon_C_orani": g["C_oran_gercek"].apply(lambda s: int((s > 0).sum())),
        "ilk_sezon": g["season"].min(),
        "son_sezon": g["season"].max(),
        "maç": g["bulunan"].sum(),
        "A_pozitif": g["A_pozitif"].sum(),
    }).reset_index()
    return out


def quarantine(matches: pd.DataFrame) -> pd.DataFrame:
    """Doğrulamadan geçemeyen (karantinaya alınan) kayıtlar. Ham veri değiştirilmez."""
    if matches is None or matches.empty:
        return pd.DataFrame()
    lab = label_frame(matches, PRIMARY_YES)
    bad = lab["issues"] != ""
    out = matches.loc[bad, ["league", "season", "date", "home", "away", "hthg", "htag", "fthg", "ftag", "source"]].copy()
    out["sorun"] = lab.loc[bad, "issues"]
    return out.reset_index(drop=True)

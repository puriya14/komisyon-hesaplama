"""İki ayaklı eşleşmelerde rövanş etkisi (KUPA-ROV-07; kullanıcı kararıyla uygulandı).

KUPA-ROV-06'nın ön kayıtlı sınamasında geliştirme dönemi (181 rövanş) etkiyi görmeye yetmedi ve kural geçilmedi
(docs/KUPA_ROV_06.md). Test dönemi ve bütün verideki kestirim küçük bir "motivasyon" etkisi gösterdi; kullanıcı bu etkinin
uygulanmasına karar verdi (docs/KUPA_ROV_07.md).

Model (KUPA-ROV-06 V1): rövanşın ev sahibinin ilk maçtaki gol farkı d (attığı − yediği; ilk maçta deplasmandı),
x = d'nin [−3, 3] aralığına kırpılmış hali.

    ev sahibinin gol beklentisi × e^(−β·x),   deplasmanınki × e^(+β·x)

β > 0: önde olan takım daha az, geride olan daha çok gol atar. β, kalibre ve dinamik gol düzeyli örneklem dışı
beklentilerle Poisson en çok olabilirlikle kestirilir:

* Ölçümde (doğrulama statüleri, gol pazarları): her rövanşın β'sı yalnızca o haftadan ÖNCEKİ haftaların rövanşlarından
  (en az ``MIN_LEGS`` rövanş yoksa β = 0). O haftanın sonuçları kullanılmaz.
* Tahminde: bütün örneklem dışı rövanşlardan (en az ``MIN_LEGS``; yoksa β = 0).

Eşleşme tanımı araştırma aracıyla (``tools/research/kupa_rovans.py``) aynıdır: aynı turnuva ve sezon, ters takımlar,
3–70 gün; grup/lig aşaması ve FA Cup tekrar maçları hariç. Skorlar normal süre (90 dk) skorlarıdır.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

ROVANS_VERSION = "rovans-v1"
EPOCH = pd.Timestamp("2000-01-01")
GAP_MIN, GAP_MAX = 3, 70
EXCLUDE_STAGE = ("group", "gruppe", "league phase")
EXCLUDE_COMPS = ("FAC",)
D_CLIP = 3.0
MIN_LEGS = 200
RESULT_COLUMNS = ["comp", "season", "stage", "date", "home_key", "away_key", "fthg", "ftag"]


def _group_stage(stage) -> bool:
    s = str(stage if stage is not None and stage == stage else "").lower()
    return any(w in s for w in EXCLUDE_STAGE)


def ties(cups: pd.DataFrame) -> pd.DataFrame:
    """İkinci maç (rövanş) satırları: i2 (ikinci maç), i1 (ilk maç), d. ``cups`` tarihe göre sıralı, 0..n−1 dizinli.

    Araştırma aracındaki ``ties`` ile aynı kurallar (testte karşılaştırılır)."""
    c = cups.copy()
    c["i"] = np.arange(len(c))
    c["day"] = (pd.to_datetime(c["date"]) - EPOCH).dt.days
    c = c[~c["comp"].isin(EXCLUDE_COMPS)]
    first_of: dict[int, tuple[int, int]] = {}
    used_second: set[int] = set()
    by: dict = {}
    for r in c.itertuples(index=False):
        by.setdefault((r.comp, str(r.season), r.home_key, r.away_key), []).append((r.day, r.i))
    rows = []
    for r in c.sort_values("i").itertuples(index=False):
        if _group_stage(r.stage):
            continue
        cands = [(day, i) for day, i in by.get((r.comp, str(r.season), r.away_key, r.home_key), [])
                 if GAP_MIN <= r.day - day <= GAP_MAX and i not in used_second]
        if not cands:
            continue
        day1, i1 = max(cands)
        if i1 in first_of or r.i in first_of:
            continue
        first_of[i1] = (r.i, day1)
        used_second.add(r.i)
        rows.append({"i2": int(r.i), "i1": int(i1)})
    out = pd.DataFrame(rows, columns=["i2", "i1"])
    if out.empty:
        out["d"] = pd.Series(dtype=float)
        return out
    f = cups.iloc[out["i1"].to_numpy()]
    out["d"] = f["ftag"].to_numpy(dtype=float) - f["fthg"].to_numpy(dtype=float)
    return out


def clip_d(d) -> np.ndarray:
    return np.clip(np.asarray(d, dtype=float), -D_CLIP, D_CLIP)


def factors(d, beta) -> tuple[np.ndarray, np.ndarray]:
    """(ev sahibi çarpanı, deplasman çarpanı); d NaN ise 1."""
    x = np.nan_to_num(clip_d(d), nan=0.0)
    b = np.asarray(beta, dtype=float)
    return np.exp(-b * x), np.exp(b * x)


def fit_beta(lam, nu, hg, ag, d) -> tuple[float, float]:
    """β ve standart hatası (Poisson en çok olabilirlik, Newton). Satır yoksa (0, nan)."""
    lam, nu = np.asarray(lam, float), np.asarray(nu, float)
    hg, ag = np.asarray(hg, float), np.asarray(ag, float)
    x = clip_d(d)
    if len(x) == 0:
        return 0.0, float("nan")
    b = 0.0
    for _ in range(50):
        lh, la = lam * np.exp(-b * x), nu * np.exp(b * x)
        # NLL(β) = Σ[λe^(−βx) + βx·hg] + Σ[νe^(βx) − βx·ag]
        g = float(np.sum(x * (hg - lh)) - np.sum(x * (ag - la)))  # dNLL/dβ
        h = float(np.sum(x * x * lh) + np.sum(x * x * la))
        if h <= 0:
            return 0.0, float("nan")
        step = g / h
        b -= step
        if abs(step) < 1e-12:
            break
    lh, la = lam * np.exp(-b * x), nu * np.exp(b * x)
    h = float(np.sum(x * x * lh) + np.sum(x * x * la))
    return float(b), (1.0 / math.sqrt(h)) if h > 0 else float("nan")


def beta_series(ev: pd.DataFrame, min_legs: int | None = None) -> np.ndarray:
    """Ölçüm için satır başına β: aynı haftadan ÖNCEKİ haftaların rövanşlarından (en az ``min_legs``, yoksa 0).
    Gerekli sütunlar: week, rovans_d (rövanş değilse NaN), lam_b, nu_b (rövanşsız beklenti), hg, ag."""
    min_legs = MIN_LEGS if min_legs is None else min_legs
    out = np.zeros(len(ev))
    d = ev["rovans_d"].to_numpy(dtype=float)
    leg = np.isfinite(d)
    if not leg.any():
        return out
    week = ev["week"].to_numpy(dtype=float)
    lam, nu = ev["lam_b"].to_numpy(float), ev["nu_b"].to_numpy(float)
    hg, ag = ev["hg"].to_numpy(float), ev["ag"].to_numpy(float)
    for wk in np.unique(week[leg]):
        past = leg & (week < wk)
        if past.sum() < min_legs:
            continue
        b, _ = fit_beta(lam[past], nu[past], hg[past], ag[past], d[past])
        out[leg & (week == wk)] = b
    return out


def results_table(cups: pd.DataFrame) -> pd.DataFrame:
    """Tahminde ilk maçı bulmak için saklanan kupa sonuçları (tarih sıralı)."""
    if cups is None or cups.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)
    t = cups.reindex(columns=RESULT_COLUMNS).copy()
    t["season"] = t["season"].astype(str)
    t["stage"] = t["stage"].astype(object)
    return t.sort_values("date", kind="mergesort").reset_index(drop=True)


def first_leg(table: pd.DataFrame | None, comp: str, season: str, stage, home_key: str, away_key: str,
              date) -> dict | None:
    """Maç bir eşleşmenin rövanşıysa ilk maç bilgisi: {d, tarih, skor (ilk maçın ev−deplasman)}; değilse None.

    Aynı ``ties`` kuralı: tablo + bu maç (en sona) üzerinde çalıştırılır. Maçın turu bilinmiyorsa (elle seçim) ilk
    maçın turu grup/lig aşaması olmamalıdır."""
    if stage is not None and (stage != stage or str(stage).strip() == ""):  # NaN / boş: tur bilinmiyor
        stage = None
    if table is None or table.empty or str(comp) in EXCLUDE_COMPS or _group_stage(stage):
        return None
    sub = table[(table["comp"] == comp) & (table["season"] == str(season))]
    day = pd.Timestamp(date).normalize()
    sub = sub[pd.to_datetime(sub["date"]) < day]
    if sub.empty:
        return None
    me = pd.DataFrame([{"comp": comp, "season": str(season), "stage": stage if stage is not None else "",
                        "date": day, "home_key": home_key, "away_key": away_key, "fthg": np.nan, "ftag": np.nan}])
    frame = pd.concat([sub, me], ignore_index=True).sort_values("date", kind="mergesort").reset_index(drop=True)
    t = ties(frame)
    hit = t[t["i2"] == len(frame) - 1]
    if hit.empty:
        return None
    f = frame.iloc[int(hit["i1"].iloc[0])]
    if stage is None and _group_stage(f["stage"]):
        return None
    return {"d": float(hit["d"].iloc[0]), "tarih": str(pd.Timestamp(f["date"]).date()),
            "skor": f"{int(f['fthg'])}-{int(f['ftag'])}"}


def card_text(rv: dict | None) -> str:
    """Maç kartı satırı: kullanılan rövanş çarpanları (yoksa boş)."""
    if not rv:
        return ""

    def num(v, k=3):
        return f"{v:.{k}f}".replace(".", ",")

    return (f"rövanş: ilk maç {rv['tarih']} {rv['skor']} (ev sahibi açısından {int(rv['d']):+d}); gol beklentisi ev "
            f"×{num(rv['ev_carpan'])}, deplasman ×{num(rv['dep_carpan'])} (β {num(rv['beta'])}; kullanıcı kararıyla, "
            "KUPA-ROV-06'da ön kayıtlı kuralı geçmedi)")


def engine_line(engine) -> str:
    """Doğrulama sekmesi / kupa-rapor bilgi satırı: tahminde kullanılan β (yoksa boş)."""
    rv = getattr(engine, "rovans", None) if engine is not None else None
    if not rv or not getattr(engine, "rovans_on", False):
        return ""
    if not rv.get("beta"):
        return (f"Rövanş etkisi (KUPA-ROV-07): örneklem dışı rövanş sayısı {rv.get('n', 0)} < {MIN_LEGS}; çarpan "
                "uygulanmıyor.")
    se = rv.get("se")
    se_txt = f", standart hata {se:.3f}".replace(".", ",") if se == se and se is not None else ""
    return (f"Rövanş etkisi (KUPA-ROV-07): β {rv['beta']:.3f}".replace(".", ",") + se_txt
            + f" ({rv.get('n', 0)} örneklem dışı rövanştan): ilk maçta 1 gol önde olan takımın rövanştaki gol beklentisi "
            f"×{math.exp(-rv['beta']):.3f}".replace(".", ",")
            + ", rakibininki " + f"×{math.exp(rv['beta']):.3f}".replace(".", ",")
            + ". Ön kayıtlı kuralı geçmedi, kullanıcı kararıyla uygulandı (docs/KUPA_ROV_06.md, KUPA_ROV_07.md).")


__all__ = ["MIN_LEGS", "ROVANS_VERSION", "beta_series", "card_text", "clip_d", "engine_line", "factors", "first_leg",
           "fit_beta", "results_table", "ties"]

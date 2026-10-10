"""Anomali incelemesi — tahminden AYRI görünüm (sözleşme §11).

* ``UNEXPLAINED_ANOMALY`` = tek maç: gerçekleşen ham İY/MS hücresinin kalibre S0'a göre sürprizi (−log₂ p, bit)
  kendi lig-sezonunun (``fr.cluster``) en üst ``1 − config.ANOMALY_QUANTILE`` payında ve çalıştırılabilen
  kontrollerle açıklanamıyor.
* ``MODEL_PIYASA_FARKI`` = ayrı bayrak: |S0 galibiyet olasılığı − marjsız piyasa galibiyet olasılığı| kendi
  lig-sezonunun en üst aynı payında. İkisi birbirini güçlendirmez; ayrı sayılır.
* "En üst pay" sonlu örneklemde orta-sıra (yüzdelik sıra) tanımıyla ölçülür: üst pay = (değeri daha büyük maç
  sayısı + eşitlerin yarısı, kendisi dahil) / n; aday ⇔ üst pay < 1 − q. Böylece lig-sezon başına ≈ round(n·%0,5)
  aday çıkar ve ≤ 100 maçlık havuzlarda (ör. devam eden sezon) aday üretilmez (en büyük değer bile en üst %0,5'te
  değildir). Referans havuz her zaman lig-sezonun TÜM değerlendirilebilir maçlarıdır; ``mask`` yalnızca hangi
  maçların raporlanacağını seçer (maske ile takım/lig bazında alt havuz kurulamaz).
* Sürpriz bir BİT değeridir; suç, şike veya herhangi bir kasıt olasılığı değildir ve öyle bir alan üretilmez.
* Bu modül takım, lig veya hakem bazında toplama/sıralama YAPMAZ ve böyle bir işlev sunmaz (testle korunur).
  Özet yalnızca tür, durum ve dönem sayımlarıdır. Lig-sezon yalnızca sürprizin referans dağılımıdır.
* Karar motoruna, sanal takibe (defter) ve örüntü statülerine bağlantı yoktur.
"""

from __future__ import annotations

from fractions import Fraction

import numpy as np
import pandas as pd

from ..goals.markets import HTFT_KEYS, frame_issues
from . import config as C

TYPE_SURPRISE = "UNEXPLAINED_ANOMALY"
TYPE_MARKET = "MODEL_PIYASA_FARKI"
TYPES = (TYPE_SURPRISE, TYPE_MARKET)
EXPLAINED = "açıklanabilir"
NOT_EVALUATED = "değerlendirilemedi"
NO_DATA = "değerlendirilemedi (veri yok)"
ANOMALY_NOTE = "Anomali puanı suç/şike olasılığı değildir; kulüp/oyuncu/hakem etiketi verilmez."
NO_LINK_NOTE = "Karar motoruna, sanal takibe ve örüntü statüsüne bağlı değildir; tahmin üretmez."
NO_PERIOD = "donem_disi"

# Verisi olmayan (çalıştırılamayan) kontroller — sonuç her zaman "değerlendirilemedi (veri yok)"
UNAVAILABLE_CHECKS = ("eski oran", "düşük likidite", "kadro haberi", "maç içi bilgi", "sağlayıcı gecikmesi")
CHECK_NAMES = ("veri doğrulama", "hükmen olabilir", "takım adı kopukluğu", "lig değişikliği sonrası ilk maçlar",
               "kırmızı kart") + UNAVAILABLE_CHECKS + ("ortak veri kaynağı",)


def surprise_bits(fr) -> np.ndarray:
    """Gerçekleşen ham İY/MS hücresinin kalibre S0'a göre sürprizi, −log₂ p (bit; tm satırlarına hizalı).

    İkiz satırlar aynı değeri taşır (maç düzeyi, ev perspektifi). Hücre bilinmiyorsa (İY eksik, çelişkili kayıt)
    veya S0 yoksa NaN. p = 0 ise +∞ (sonsuz sürpriz). Olasılık değildir; yalnızca bilgi miktarıdır.
    """
    cell = fr.tm["raw_cell"].to_numpy(dtype=np.int64)
    raw = np.asarray(fr.raw_probs, dtype=float)
    has_s0 = np.isfinite(raw).all(axis=1)
    ok = (cell >= 0) & (cell < len(HTFT_KEYS)) & has_s0
    p = np.full(len(cell), np.nan)
    idx = np.where(ok)[0]
    p[idx] = raw[idx, cell[idx]]
    out = np.full(len(cell), np.nan)
    pos = ok & (p >= 0)
    with np.errstate(divide="ignore"):
        out[pos] = -np.log2(p[pos])
    return out


def _tail_fraction() -> Fraction:
    """1 − ``config.ANOMALY_QUANTILE`` tam kesir olarak (0,995 → 1/200; kayan nokta sınır hatası olmasın)."""
    top = Fraction(1) - Fraction(repr(float(C.ANOMALY_QUANTILE))).limit_denominator(10 ** 9)
    if not (0 < top < 1):
        raise ValueError("ANOMALY_QUANTILE (0, 1) aralığında olmalı")
    return top


def _upper_share(values: np.ndarray, groups: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Grup içi orta-sıra üst payı, grup büyüklüğü ve "en üst pay" bayrağı (NaN değerler havuz dışında).

    üst pay = (daha büyük değer sayısı + eşit değer sayısının yarısı, kendisi dahil) / n. Eşitler aynı payı ve
    aynı kararı alır (deterministik); +∞ değerler en üsttedir. Bayrak tam sayı aritmetiğiyle: 2·üst·n < 2·top·n.
    """
    s = pd.Series(np.asarray(values, dtype=float))
    valid = s.notna().to_numpy()
    share = np.full(len(s), np.nan)
    size = np.zeros(len(s), dtype=np.int64)
    flag = np.zeros(len(s), dtype=bool)
    if valid.any():
        g = np.asarray(groups, dtype=object)[valid]
        sv = s[valid]
        grp = sv.groupby(g)
        r_min = grp.rank(method="min", ascending=False).to_numpy()  # 1 + daha büyük sayısı
        r_max = grp.rank(method="max", ascending=False).to_numpy()  # daha büyük + eşit sayısı
        n = grp.transform("size").to_numpy().astype(np.int64)
        twice = (r_min - 1.0) + r_max  # 2·(daha büyük) + eşit = 2 × orta-sıra üst sayım (tam sayı)
        top = _tail_fraction()
        share[valid] = twice / (2.0 * n)
        size[valid] = n
        flag[valid] = twice.astype(np.int64) * top.denominator < 2 * n * top.numerator
    return share, size, flag


def _match_table(fr, mask: np.ndarray | None) -> pd.DataFrame:
    """Maç düzeyi tablo (pair_id başına bir satır; ev satırı temsilci).

    Paylar lig-sezonun TÜM maçlarından hesaplanır (referans havuz maskeden bağımsızdır); ``selected`` sütunu maskede
    en az bir satırı olan maçları gösterir.
    """
    tm = fr.tm
    n = len(tm)
    m = np.ones(n, dtype=bool) if mask is None else np.asarray(mask)
    if m.shape != (n,) or m.dtype != bool:
        raise ValueError("mask, tm satırlarına hizalı boolean dizi olmalı")
    pair = tm["pair_id"].to_numpy()
    in_mask_pair = pd.Series(m).groupby(pair).transform("max").to_numpy(dtype=bool)
    home = tm["is_home"].to_numpy(dtype=bool)
    rows = np.where(home)[0]
    mirror = tm["mirror_row"].to_numpy()[rows]
    bits = surprise_bits(fr)
    p_win = np.asarray(fr.p_win, dtype=float)
    mkt_win = np.asarray(fr.mkt, dtype=float)[:, 0]
    gap_home = np.abs(p_win[rows] - mkt_win[rows])
    gap_away = np.abs(p_win[mirror] - mkt_win[mirror])
    gap = np.fmax(gap_home, gap_away)  # her iki takımın |S0 p_win − piyasa p_win| değerinin büyüğü
    gap[~(np.isfinite(gap_home) & np.isfinite(gap_away))] = np.nan
    cell = tm["raw_cell"].to_numpy(dtype=np.int64)[rows]
    raw = np.asarray(fr.raw_probs, dtype=float)
    p_real = np.full(len(rows), np.nan)
    okc = (cell >= 0) & (cell < len(HTFT_KEYS))
    p_real[okc] = raw[rows[okc], cell[okc]]
    period = np.asarray(fr.period, dtype=object)[rows]
    mt = pd.DataFrame({
        "row": rows, "mirror": mirror, "pair_id": tm["pair_id"].to_numpy()[rows],
        "event_id": tm["event_id"].to_numpy()[rows], "date": pd.to_datetime(tm["date"].to_numpy()[rows]),
        "league": tm["league"].to_numpy()[rows], "season": tm["season"].to_numpy()[rows],
        "cluster": np.asarray(fr.cluster, dtype=object)[rows],
        "period": [p if isinstance(p, str) else NO_PERIOD for p in period],
        "htft": tm["htft"].to_numpy()[rows], "p_real": p_real, "bits": bits[rows], "gap": gap,
        "selected": in_mask_pair[rows],
    })
    mt["bits_share"], mt["bits_n"], mt["is_s"] = _upper_share(mt["bits"].to_numpy(), mt["cluster"].to_numpy())
    mt["gap_share"], mt["gap_n"], mt["is_m"] = _upper_share(mt["gap"].to_numpy(), mt["cluster"].to_numpy())
    return mt


def _fnum(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _check(name: str, result: str, ran: bool, explains: bool, scope: tuple[str, ...] = TYPES) -> dict:
    return {"kontrol": name, "sonuc": result, "calistirildi": ran, "aciklar": bool(ran and explains),
            "kapsam": list(scope)}


_CHECK_COLS = ("gf_ft", "ga_ft", "gf_ht", "ga_ht", "awarded", "team", "team_raw", "opponent", "opponent_raw",
               "since_league_change", "red_for", "red_against", "source")


def _check_arrays(tm: pd.DataFrame) -> dict[str, np.ndarray]:
    """Kontrol listesi için gereken sütunlar bir kez diziye alınır (eksik sütun → NaN)."""
    out = {c: (tm[c].to_numpy() if c in tm.columns else np.full(len(tm), np.nan)) for c in _CHECK_COLS}
    if "issues" in tm.columns:
        out["issues"] = tm["issues"].to_numpy()
    return out


def _score_issues(cols: dict[str, np.ndarray], rows: np.ndarray) -> list[str]:
    """Merkezi doğrulama kuralları (goals.markets.frame_issues), ev perspektifi skorlarla; toplu hesap."""
    score = pd.DataFrame({"fthg": cols["gf_ft"][rows], "ftag": cols["ga_ft"][rows], "hthg": cols["gf_ht"][rows],
                          "htag": cols["ga_ht"][rows]})
    return frame_issues(score).tolist() if len(rows) else []


def _checklist(cols: dict[str, np.ndarray], r: int, mr: int, score_issue: str) -> list[dict]:
    """Alternatif açıklamalar. ``r``: ev satırı, ``mr``: deplasman satırı (tm konumları);
    ``score_issue``: ev satırı skorlarının doğrulama sonucu ('' = sorun yok)."""
    home, away = ({c: v[i] for c, v in cols.items()} for i in (r, mr))
    out = []
    # 1) Veri doğrulama: merkezi doğrulama kuralları + ikiz satır tutarlılığı (+ varsa tm 'issues' sütunu)
    issues = [score_issue] if score_issue else []
    twin_ok = all(
        (_fnum(home[a]) == _fnum(away[b])) for a, b in (("gf_ft", "ga_ft"), ("ga_ft", "gf_ft"), ("gf_ht", "ga_ht"),
                                                         ("ga_ht", "gf_ht")))
    if not twin_ok:
        issues.append("IKIZ_SATIR_SKOR_TUTARSIZ")
    issues += [str(v) for v in (home.get("issues"), away.get("issues")) if isinstance(v, str) and v]
    issues = sorted(set(issues))
    out.append(_check("veri doğrulama",
                      f"{EXPLAINED}: veri doğrulama sorunu ({', '.join(issues)})" if issues
                      else "sorun yok (doğrulama kuralları geçti)", True, bool(issues)))
    # 2) Hükmen olabilir (sonucun sahada oynanmamış olma olasılığı) — sonuç sürprizini açıklar
    aw = any(isinstance(x["awarded"], (bool, np.bool_)) and bool(x["awarded"]) for x in (home, away))
    out.append(_check("hükmen olabilir", f"{EXPLAINED}: hükmen olabilir (POSSIBLE_AWARDED)" if aw else "hayır",
                      True, aw, (TYPE_SURPRISE,)))
    # 3) Takım adı kopukluğu / yanlış eşleşme (kaynak adı kanonik kimlikten farklı)
    names = [(x[a], x[b]) for x in (home, away) for a, b in (("team_raw", "team"), ("opponent_raw", "opponent"))]
    if not all(isinstance(a, str) and isinstance(b, str) for a, b in names):
        out.append(_check("takım adı kopukluğu", NOT_EVALUATED, False, False))
    else:
        broken = any(a != b for a, b in names)
        out.append(_check("takım adı kopukluğu",
                          f"{EXPLAINED}: kaynak adı kanonik kimlikten farklı (eşleme tablosu kullanıldı)" if broken
                          else "hayır (kaynak adları kanonik kimlikle aynı)", True, broken))
    # 4) Lig değişikliği / dilim başı sonrası ilk maçlar (S0 soğuk başlangıç)
    since = [_fnum(x["since_league_change"]) for x in (home, away)]
    if any(s is not None and s < C.LEAGUE_CHANGE_EXCLUDE for s in since):
        out.append(_check("lig değişikliği sonrası ilk maçlar",
                          f"{EXPLAINED}: lig değişikliği/dilim başından sonraki ilk {C.LEAGUE_CHANGE_EXCLUDE} maç "
                          "içinde (S0 soğuk başlangıç)", True, True))
    elif any(s is None for s in since):
        out.append(_check("lig değişikliği sonrası ilk maçlar", NOT_EVALUATED, False, False))
    else:
        out.append(_check("lig değişikliği sonrası ilk maçlar", "hayır", True, False))
    # 5) Kırmızı kart (yalnızca maç içi sonuç sürprizini açıklayabilir; maç öncesi piyasa farkını açıklamaz)
    reds = [_fnum(home["red_for"]), _fnum(home["red_against"])]
    if any(v is not None and v > 0 for v in reds):
        out.append(_check("kırmızı kart", f"{EXPLAINED}: kırmızı kart", True, True, (TYPE_SURPRISE,)))
    elif any(v is None for v in reds):
        out.append(_check("kırmızı kart", NOT_EVALUATED, False, False, (TYPE_SURPRISE,)))
    else:
        out.append(_check("kırmızı kart", "kırmızı kart yok", True, False, (TYPE_SURPRISE,)))
    # 6) Verisi olmayan kontroller
    for name in UNAVAILABLE_CHECKS:
        out.append(_check(name, NO_DATA, False, False))
    # 7) Ortak veri kaynağı notu (bağımsız kanıt sayılmaz)
    src = str(home["source"]) if isinstance(home["source"], str) and home["source"] else "bilinmiyor"
    out.append(_check("ortak veri kaynağı",
                      f"not: veri kaynağı '{src}'; birden fazla sitede aynı hareket bağımsız kanıt sayılmaz "
                      "(ortak kaynak olasılığı)", False, False))
    return out


def flag_anomalies(fr, mask: np.ndarray | None = None) -> list[dict]:
    """Maç düzeyi anomali kayıtları (pair_id başına en fazla bir kayıt; tarih, pair_id sırasında).

    Aday kuralı (her ölçüt kendi lig-sezonunun TÜM değerlendirilebilir maçlarına göre): orta-sıra üst pay
    < 1 − ``config.ANOMALY_QUANTILE`` (modül belgesine bakın; ≤ 100 maçlık havuzda aday yok). ``mask`` (tm satırlarına
    hizalı) yalnızca raporlanacak maçları seçer — iki satırından biri maskedeyse maç dahildir — referans havuzu
    değiştirmez. Sürpriz adayı ``UNEXPLAINED_ANOMALY`` türüdür; çalıştırılabilen bir kontrol açıklarsa durumu
    ``açıklanabilir`` olur. Piyasa farkı ayrı ``MODEL_PIYASA_FARKI`` bayrağıdır (açıklanamazsa durumu
    ``MODEL_PIYASA_FARKI``).
    """
    top = _tail_fraction()
    mt = _match_table(fr, mask)
    is_s = mt["is_s"].to_numpy(dtype=bool)
    is_m = mt["is_m"].to_numpy(dtype=bool)
    sel = mt[(is_s | is_m) & mt["selected"].to_numpy(dtype=bool)].sort_values(["date", "pair_id"], kind="mergesort")
    cols = _check_arrays(fr.tm)
    score_issues = _score_issues(cols, sel["row"].to_numpy(dtype=np.int64))
    records = []
    for k, (_, row) in enumerate(sel.iterrows()):
        flags = [t for t, on in ((TYPE_SURPRISE, bool(row["is_s"])), (TYPE_MARKET, bool(row["is_m"]))) if on]
        checks = _checklist(cols, int(row["row"]), int(row["mirror"]), score_issues[k])
        by_flag = {}
        for f in flags:
            exp = [c["kontrol"] for c in checks if c["aciklar"] and f in c["kapsam"]]
            by_flag[f] = EXPLAINED if exp else f
        explained_by = sorted({c["kontrol"] for c in checks if c["aciklar"]
                               and any(f in c["kapsam"] for f in flags)}, key=CHECK_NAMES.index)
        records.append({
            "pair_id": int(row["pair_id"]), "event_id": str(row["event_id"]),
            "date": str(pd.Timestamp(row["date"]).date()), "league": str(row["league"]), "season": str(row["season"]),
            "cluster": str(row["cluster"]), "period": str(row["period"]),
            "htft": row["htft"] if isinstance(row["htft"], str) else None,
            "s0_p_gerceklesen": _fnum(row["p_real"]),
            "surprise_bits": float(row["bits"]) if pd.notna(row["bits"]) else None,
            "surprise_top_share": _fnum(row["bits_share"]), "surprise_pool_n": int(row["bits_n"]),
            "model_market_gap": _fnum(row["gap"]), "gap_top_share": _fnum(row["gap_share"]),
            "gap_pool_n": int(row["gap_n"]),
            "flags": flags, "type": flags[0], "status_by_flag": by_flag, "status": by_flag[flags[0]],
            "explained_by": explained_by, "checklist": checks,
            "reference": (f"lig-sezonun tüm maçlarına göre orta-sıra üst pay < {float(top):.3%} "
                          f"(config.ANOMALY_QUANTILE = {C.ANOMALY_QUANTILE}); ≤ {top.denominator // (2 * top.numerator)} "
                          "maçlık havuzda aday yok"),
            "note": ANOMALY_NOTE, "link_note": NO_LINK_NOTE,
        })
    return records


def anomaly_summary(records: list[dict]) -> dict:
    """YALNIZCA tür, durum ve dönem sayımları. Takım, lig veya hakem alanları okunmaz; toplama/sıralama yoktur."""
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_period: dict[str, int] = {}
    cross: dict[str, dict[str, dict[str, int]]] = {}
    for rec in records:
        period = str(rec.get("period") or NO_PERIOD)
        by_period[period] = by_period.get(period, 0) + 1
        status = str(rec.get("status"))
        by_status[status] = by_status.get(status, 0) + 1
        for f in rec.get("flags", []):
            st = str(rec.get("status_by_flag", {}).get(f, status))
            by_type[f] = by_type.get(f, 0) + 1
            cell = cross.setdefault(f, {}).setdefault(st, {})
            cell[period] = cell.get(period, 0) + 1
    srt = lambda d: dict(sorted(d.items()))  # noqa: E731
    return {
        "toplam": len(records),
        "tur": srt(by_type),
        "durum": srt(by_status),
        "donem": srt(by_period),
        "tur_durum_donem": {f: {s: srt(p) for s, p in sorted(v.items())} for f, v in sorted(cross.items())},
        "not": ANOMALY_NOTE,
        "baglanti": NO_LINK_NOTE,
    }

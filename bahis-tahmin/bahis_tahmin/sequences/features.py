"""Zaman güvenli dizi özellikleri ve atomları (sözleşme §6–7).

Tüm dizi atomları yalnızca takımın İY ve MS SONUÇ KODLARINDAN (``ht``, ``ft``: 0=G, 1=B, 2=M, −1 bilinmiyor) ve
sabit girdilerden (kalibre S0 beklenen puanı, takvim) hesaplanır. Böylece referans süreç simüle edilmiş kodlarla
AYNI fonksiyonu çalıştırır ve gerçek gol sütunlarını hiç okumaz.

Pencere = takımın aynı dilimdeki (``spell_id``) önceki k pencere maçı (``in_seq``; üst tur hariç). Bir atom ancak
pencere TAM ise tanımlıdır: k maç mevcut, penceredeki ve mevcut maçın lig-sezonu tam, sezon atlaması yok, gerekli
sonuç kodları biliniyor (İY gerektiren atomlarda İY, MS gerektirenlerde MS). Aksi halde NaN (satır o koşulun hem
içinden hem tümleyeninden çıkar).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C

G, B, M = 0, 1, 2


class SeqIndex:
    """Pencere dizisi için önceden hesaplanan sabit yapı (takvim, dilim, kapsam). Sonuçlardan bağımsızdır."""

    def __init__(self, tm: pd.DataFrame):
        seq = tm["in_seq"].to_numpy()
        self.rows = np.where(seq)[0]  # tm satırı → dizi konumu
        self.n_tm = len(tm)
        spell = tm["spell_id"].to_numpy()[self.rows]
        self.pos_in_spell = tm["spell_seq"].to_numpy()[self.rows].astype(np.int64)
        self.n = len(self.rows)
        bad_season = ~tm["season_complete"].to_numpy()[self.rows]
        skip = tm["season_skip"].to_numpy()[self.rows]
        self.cum_bad = np.r_[0, np.cumsum(bad_season)]
        self.cum_skip = np.r_[0, np.cumsum(skip)]
        self.spell = spell
        self.mirror_tm = tm["mirror_row"].to_numpy()
        pos = np.full(len(tm), -1, dtype=np.int64)
        pos[self.rows] = np.arange(self.n)
        self.pos_of_tm = pos

    def window_ok(self, k: int) -> np.ndarray:
        """Yapısal pencere geçerliliği (sonuçtan bağımsız): k maç mevcut, sezonlar tam, sezon atlaması yok."""
        j = np.arange(self.n)
        avail = self.pos_in_spell >= k
        lo = np.clip(j - k, 0, None)
        bad = (self.cum_bad[j + 1] - self.cum_bad[lo]) > 0  # pencere + mevcut maç
        skip = (self.cum_skip[j + 1] - self.cum_skip[np.clip(lo + 1, 0, None)]) > 0
        return avail & ~bad & ~skip

    def window_sum(self, x: np.ndarray, k: int) -> np.ndarray:
        """Aynı dilimdeki önceki en fazla k konumun x toplamı (dilim başını ASLA aşmaz: başka takıma/döneme taşmaz)."""
        c = np.r_[0.0, np.cumsum(x)]
        j = np.arange(self.n)
        lo = np.maximum(j - k, j - self.pos_in_spell)
        return c[j] - c[lo]

    def to_tm(self, v: np.ndarray) -> np.ndarray:
        out = np.full(self.n_tm, np.nan)
        out[self.rows] = v
        return out


def outcome_codes(tm: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Gerçek veriden takım İY ve MS kodları (0=G, 1=B, 2=M, −1 bilinmiyor)."""
    code = {"G": G, "B": B, "M": M}
    ht = np.array([code.get(v, -1) if isinstance(v, str) else -1 for v in tm["ht_res"]], dtype=np.int8)
    ft = np.array([code.get(v, -1) if isinstance(v, str) else -1 for v in tm["ft_res"]], dtype=np.int8)
    return ht, ft


def history_atoms(si: SeqIndex, ht: np.ndarray, ft: np.ndarray, exp_points: np.ndarray) -> dict[str, np.ndarray]:
    """16 dizi atomu (tm satırlarına hizalı 1/0/NaN). ``exp_points``: kalibre S0 beklenen puanı (yoksa NaN)."""
    h, f = ht[si.rows], ft[si.rows]
    hk, fk = h >= 0, f >= 0
    both = hk & fk
    ep = exp_points[si.rows]
    pts = np.where(f == G, 3.0, np.where(f == B, 1.0, 0.0))
    ind = {
        "trail": (h == M).astype(float), "lead": (h == G).astype(float), "win": (f == G).astype(float),
        "loss": (f == M).astype(float), "comeback": ((h == M) & (f == G)).astype(float),
        "leadloss": ((h == G) & (f == M)).astype(float),
        "improve": (((h == M) & (f != M) & fk) | ((h == B) & (f == G))).astype(float),
    }
    unk_h = (~hk).astype(float)
    unk_f = (~fk).astype(float)
    unk_b = (~both).astype(float)
    form_ok = (fk & np.isfinite(ep)).astype(float)
    form_val = np.where(fk & np.isfinite(ep), pts - np.nan_to_num(ep), 0.0)
    cache: dict = {}

    def wsum(name, x, k):
        key = (name, k)
        if key not in cache:
            cache[key] = si.window_sum(x, k)
        return cache[key]

    def ok(k, need):  # need: "f" (MS), "b" (İY+MS), "form"
        base = si.window_ok(k)
        if need == "f":
            return base & (wsum("unk_f", unk_f, k) == 0)
        if need == "b":
            return base & (wsum("unk_b", unk_b, k) == 0)
        if need == "h":
            return base & (wsum("unk_h", unk_h, k) == 0)
        return base & (wsum("form_ok", form_ok, k) == k)

    def atom(cond, valid):
        return si.to_tm(np.where(valid, cond.astype(float), np.nan))

    a = {}
    a["SON_MAC_IY_GERIDE_MS_GALIP"] = atom(wsum("comeback", ind["comeback"], 1) >= 1, ok(1, "b"))
    a["SON_MAC_IY_ONDE_MS_MAGLUP"] = atom(wsum("leadloss", ind["leadloss"], 1) >= 1, ok(1, "b"))
    a["SON5_IY_GERIDE_EN_AZ_2"] = atom(wsum("trail", ind["trail"], 5) >= 2, ok(5, "h"))
    a["SON5_IY_ONDE_EN_AZ_3"] = atom(wsum("lead", ind["lead"], 5) >= 3, ok(5, "h"))
    a["SON5_GALIBIYET_EN_AZ_4"] = atom(wsum("win", ind["win"], 5) >= 4, ok(5, "f"))
    a["SON5_GALIBIYETSIZ"] = atom(wsum("win", ind["win"], 5) == 0, ok(5, "f"))
    a["SON3_MAGLUBIYET"] = atom(wsum("loss", ind["loss"], 3) == 3, ok(3, "f"))
    a["SON10_IY_GERIDE_MS_GALIP_EN_AZ_2"] = atom(wsum("comeback", ind["comeback"], 10) >= 2, ok(10, "b"))
    a["SON10_IY_SONRASI_IYILESME_EN_AZ_4"] = atom(wsum("improve", ind["improve"], 10) >= 4, ok(10, "b"))
    a["SON20_IY_GERIDE_MS_GALIP_YOK"] = atom(wsum("comeback", ind["comeback"], 20) == 0, ok(20, "b"))
    a["SON3_IY_GERIDE_MS_GALIP_VAR"] = atom(wsum("comeback", ind["comeback"], 3) >= 1, ok(3, "b"))
    form10 = wsum("form", form_val, 10)
    a["FORM_BEKLENTI_USTU"] = atom(form10 >= C.FORM_DIFF, ok(10, "form"))
    a["FORM_BEKLENTI_ALTI"] = atom(form10 <= -C.FORM_DIFF, ok(10, "form"))
    # Rakip atomları: aynı maçtaki rakip satırının kendi geçmişi
    m = si.mirror_tm
    lead5 = atom(wsum("lead", ind["lead"], 5) >= 3, ok(5, "h"))
    leadloss10 = atom(wsum("leadloss", ind["leadloss"], 10) >= 2, ok(10, "b"))
    loss3 = a["SON3_MAGLUBIYET"]
    a["RAKIP_SON5_IY_ONDE_EN_AZ_3"] = lead5[m]
    a["RAKIP_SON10_IY_ONDE_MS_MAGLUP_EN_AZ_2"] = leadloss10[m]
    a["RAKIP_SON3_MAGLUBIYET"] = loss3[m]
    return {k: a[k] for k in C.HISTORY_ATOMS}


def context_atoms(tm: pd.DataFrame, p_win: np.ndarray) -> dict[str, np.ndarray]:
    """Bağlam atomları (sonuçtan bağımsız; yalnızca kısıt/katman olarak kullanılır)."""
    gap = tm["lig_arasi_gun"].to_numpy(dtype=float)
    stage = tm["season_ord"].to_numpy(dtype=float) / tm["regular_len"].to_numpy(dtype=float)
    stage_ok = tm["season_complete"].to_numpy() & tm["in_seq"].to_numpy()
    return {
        "EV_SAHIBI": tm["is_home"].to_numpy().astype(float),
        "FAVORI": np.where(np.isfinite(p_win), (p_win >= C.FAVORI_THRESHOLD).astype(float), np.nan),
        "LIG_YOGUN_KISA_ARA": np.where(np.isfinite(gap), (gap <= C.SHORT_GAP_DAYS).astype(float), np.nan),
        "SEZON_SONU": np.where(stage_ok, (stage >= C.SEASON_END_SHARE).astype(float), np.nan),
    }


S1_FEATURES = (
    "trail5", "lead5", "comeback10", "leadloss10", "ppg5", "form10", "gd2h10", "improve10", "home10", "oppstr10",
    "mkt10", "since_log", "since_none", "gap_log", "gap_none", "navail10",
    "opp_trail5", "opp_lead5", "opp_comeback10", "opp_leadloss10", "opp_ppg5", "opp_form10",
)


def s1_features(tm: pd.DataFrame, si: SeqIndex, exp_points: np.ndarray, opp_strength: np.ndarray,
                mkt_points: np.ndarray) -> pd.DataFrame:
    """S1/S2 sürekli dizi özellikleri (eksik pencerede mevcut maçlar üzerinden + gösterge; tm'ye hizalı).

    ``opp_strength``: o maç öncesi rakibin kalibre S0 galibiyet olasılığı; ``mkt_points``: marjsız 1X2 beklenen puan.
    Gol sayıları burada kullanılabilir (bu özellikler referans sürecine girmez).
    """
    ht, ft = outcome_codes(tm)
    h, f = ht[si.rows], ft[si.rows]
    hk, fk = h >= 0, f >= 0
    both = hk & fk
    r = si.rows
    pts = np.where(f == G, 3.0, np.where(f == B, 1.0, 0.0))
    gd2h = (tm["gf_2h"].to_numpy(dtype=float) - tm["ga_2h"].to_numpy(dtype=float))[r]
    ep, osr, mp = exp_points[r], opp_strength[r], mkt_points[r]
    avail = lambda k: np.minimum(si.pos_in_spell, k).astype(float)  # noqa: E731

    def mean_over(x, valid, k):
        s = si.window_sum(np.where(valid, x, 0.0), k)
        n = si.window_sum(valid.astype(float), k)
        return np.where(n > 0, s / np.maximum(n, 1), np.nan), n

    out = {}
    out["trail5"], _ = mean_over((h == M).astype(float), hk, 5)
    out["lead5"], _ = mean_over((h == G).astype(float), hk, 5)
    out["comeback10"], _ = mean_over(((h == M) & (f == G)).astype(float), both, 10)
    out["leadloss10"], _ = mean_over(((h == G) & (f == M)).astype(float), both, 10)
    out["ppg5"], _ = mean_over(pts, fk, 5)
    out["form10"], _ = mean_over(pts - np.nan_to_num(ep), fk & np.isfinite(ep), 10)
    out["gd2h10"], _ = mean_over(np.nan_to_num(gd2h), both & np.isfinite(gd2h), 10)
    imp = (((h == M) & (f != M)) | ((h == B) & (f == G))).astype(float)
    out["improve10"], _ = mean_over(imp, both, 10)
    home = tm["is_home"].to_numpy()[r].astype(float)
    out["home10"], _ = mean_over(home, np.ones(si.n, dtype=bool), 10)
    out["oppstr10"], _ = mean_over(np.nan_to_num(osr), np.isfinite(osr), 10)
    out["mkt10"], _ = mean_over(pts - np.nan_to_num(mp), fk & np.isfinite(mp), 10)
    # son olaydan (İY geride → MS galip) beri dilim içi maç sayısı
    ev = ((h == M) & (f == G))
    last = np.full(si.n, -1)
    cur = -1
    prev_spell = None
    for j in range(si.n):
        if si.spell[j] != prev_spell:
            cur, prev_spell = -1, si.spell[j]
        last[j] = cur
        if ev[j]:
            cur = j
    since = np.where(last >= 0, np.arange(si.n) - last, np.nan)
    out["since_log"] = np.log1p(np.minimum(np.nan_to_num(since, nan=60.0), 60.0))
    out["since_none"] = np.isnan(since).astype(float)
    gap = tm["lig_arasi_gun"].to_numpy(dtype=float)[r]
    out["gap_log"] = np.log1p(np.minimum(np.nan_to_num(gap, nan=7.0), 30.0))
    out["gap_none"] = np.isnan(gap).astype(float)
    out["navail10"] = avail(10) / 10.0
    full = {k: si.to_tm(v) for k, v in out.items()}
    mrow = si.mirror_tm
    for k in ("trail5", "lead5", "comeback10", "leadloss10", "ppg5", "form10"):
        full[f"opp_{k}"] = full[k][mrow]
    df = pd.DataFrame({k: full[k] for k in S1_FEATURES}, index=tm.index)
    return df

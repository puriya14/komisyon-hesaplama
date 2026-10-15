"""Kupa ve Avrupa maçlarında gol pazarları (KUPA-GOL-02): A (iki yarıda da KG), B (maç sonu 3,5 Üst), C (İY 1,5 Üst).

Model ``kupa-gol-v2`` ("maç sonu bölme"): ligler arası ortak modelin (``kupa.model``) KALİBRE maç sonu gol beklentileri
λ (ev), ν (deplasman) ilk yarı payı s ile yarılara bölünür:

    İY golleri  ~ Poisson(s·λ) × Poisson(s·ν)
    2Y golleri  ~ Poisson((1−s)·λ) × Poisson((1−s)·ν)

Bütün pazarlar bu tek ortak dağılımdan (``goals.joint.joint_probs``) türetilir: A ⊆ B ∩ C yapısal olarak korunur, kırpma
yoktur. s, tahmin anından ÖNCEKİ ve AYNI doğrulama grubundaki (UEFA / yurt içi / kıta) kupa maçlarında ilk yarı
gollerinin bütün gollere oranıdır (lig önbilgisi 0,44 ile yumuşatılır). v1'den farkı (KUPA-IY-03): v1'de bütün kupalar
birlikteydi; kupa verisinin tamamı UEFA'dan geldiği için UEFA'da v1 ile v2 aynıdır.

Seçim (docs/KUPA_GOL_02.md): ayrı ilk yarı / ikinci yarı ligler arası takım güçleri, ikinci yarı skor durumu çarpanları,
pazar kalibrasyonu (Platt + IPF) ve yarı yoğunluk kalibrasyonu denendi. Geliştirme döneminde (2019/20–2021/22 kupa
maçları) en iyi seçenekler log-kayıpta eşdeğerdi (fark < 0,001); ek parametresi olmayan ve A, B'de kalibrasyon hatası en
düşük olan bu en sade kurgu seçildi.

Ölçüm örneklemi (KUPA-GOL-04): maç sonu 0-0 biten maçlar, kaynak devre skorunu yazmasa da İY 0-0 olarak ölçüme girer
(``ht_scores``). openfootball 0-0 maçlarda devre skorunu neredeyse hiç yazmıyor; v2 kuralında bu maçlar "İY skoru yok"
diye dışarıda kalıyor, ölçülen örneklem gol yönünde seçilmiş oluyordu (gerçek veride kupa maçlarının yaklaşık %6'sı).

Doğrulama kuralı ``kupa-gol-dogrulama-v3`` (doğrulama grubu ve pazar başına; lig gol motorunun dört ölçütü): örneklem dışı
log-kayıp farkının (model − aynı doğrulama grubunun önceki sezonlarındaki kupa taban oranı; grupta 30 maçtan azsa bütün
kupalar) hafta bloklu %95 üst sınırı < 0, kalibrasyon eğimi
0,8–1,25, ECE ≤ max(0,02; mükemmel kalibrasyonda örneklem gürültüsüyle beklenen ECE'nin %95 üst sınırı), en az 200
gerçekleşen (pozitif) örnek. ECE ölçütündeki örneklem payı: lig motorunun on binlerce maçına karşı kupada birkaç bin maç
vardır; kusursuz kalibre bir model bile bu örneklemde gürültüden ötürü 0,02'yi aşabilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..goals.markets import PRIMARY_YES, SHORT

GOAL_MODEL_VERSION = "kupa-gol-v2"  # v2 (KUPA-IY-03): ilk yarı payı doğrulama grubunun kendi geçmişinden
# v3 (KUPA-GOL-04): eşikler v2 ile aynı; maç sonu 0-0 maçlar İY 0-0 olarak örnekleme girer (``ht_scores``)
GOAL_RULE = ("kupa-gol-dogrulama-v3: örneklem dışı log-kayıp farkının (model − aynı doğrulama grubunun önceki "
             "sezonlarındaki kupa taban oranı) hafta bloklu %95 üst sınırı < 0, kalibrasyon eğimi 0,8–1,25, ECE ≤ "
             "max(0,02; mükemmel kalibrasyonda örneklem gürültüsünün %95 üst sınırı), en az 200 pozitif; maç sonu 0-0 "
             "maçlar İY 0-0 olarak örneklemde")
MIN_GROUP_BASE = 30  # taban oranı için grupta en az bu kadar önceki maç; yoksa bütün kupalar
MIN_POSITIVE = 200
SHARE_PRIOR = 0.44  # lig önbilgisi (ilk yarı gol payı)
SHARE_PRIOR_GOALS = 100.0
INTERVAL_DRAWS = 200
INTERVAL_SEED = 20261015
INTERVAL_LEVEL = 0.8
MIN_HT_SHARE = 0.8  # turnuvada geçerli ilk yarı skoru oranı bundan düşükse bahis adayı olmaz (lig kuralıyla aynı eşik)
ECE_NOISE_REPS = 400
ECE_NOISE_SEED = 20261015


def ht_scores(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """İlk yarı skorları. Maç sonu (normal süre) 0-0 ise ve kaynak iki devre skorunu da yazmamışsa İY 0-0'dır: golsüz
    maçın ilk yarısı da golsüzdür (tahmin değil, mantıksal zorunluluk). openfootball dosyaları 0-0 maçlarda devre skorunu
    neredeyse hiç yazmaz; bu satırlar ölçümden düşünce örneklem gol yönünde seçilmiş oluyordu (KUPA-GOL-04). Depodaki
    ham satır değişmez."""
    hh, ha = df["hthg"].to_numpy(dtype=float).copy(), df["htag"].to_numpy(dtype=float).copy()
    fh, fa = df["fthg"].to_numpy(dtype=float), df["ftag"].to_numpy(dtype=float)
    nil = (fh == 0) & (fa == 0) & np.isnan(hh) & np.isnan(ha)
    hh[nil] = 0.0
    ha[nil] = 0.0
    return hh, ha


def ht_mask(df: pd.DataFrame) -> np.ndarray:
    """İlk yarı skoru geçerli satırlar (İY ≤ MS; maç sonu 0-0 ise İY 0-0, ``ht_scores``)."""
    hh, ha = ht_scores(df)
    fh, fa = df["fthg"].to_numpy(dtype=float), df["ftag"].to_numpy(dtype=float)
    return np.isfinite(hh) & np.isfinite(ha) & (hh <= fh) & (ha <= fa)


def labels(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """A, B, C gerçekleşmeleri (yalnızca İY skoru geçerli satırlarda anlamlıdır)."""
    hh, ha = ht_scores(df)
    fh, fa = df["fthg"].to_numpy(dtype=float), df["ftag"].to_numpy(dtype=float)
    return {"A": ((hh >= 1) & (ha >= 1) & (fh - hh >= 1) & (fa - ha >= 1)).astype(float),
            "B": (fh + fa >= 4).astype(float), "C": (hh + ha >= 2).astype(float)}


def first_half_share(cups: pd.DataFrame) -> float:
    """İlk yarı gollerinin bütün gollere oranı (İY skoru geçerli kupa maçları; lig önbilgisiyle yumuşatılmış)."""
    if cups is None or cups.empty:
        return SHARE_PRIOR
    ok = ht_mask(cups)
    hh, ha = ht_scores(cups)
    ht = float((hh[ok] + ha[ok]).sum())
    ft = float((cups["fthg"].to_numpy(dtype=float)[ok] + cups["ftag"].to_numpy(dtype=float)[ok]).sum())
    return (ht + SHARE_PRIOR * SHARE_PRIOR_GOALS) / (ft + SHARE_PRIOR_GOALS)


def market_probs(lam, nu, share: float) -> dict[str, np.ndarray]:
    """Kalibre maç sonu gol beklentilerinden ortak yarı-gol dağılımı ve pazarlar (``goals.joint.OUTPUT_KEYS``)."""
    from ..goals.joint import joint_probs

    lam = np.asarray(lam, dtype=float)
    nu = np.asarray(nu, dtype=float)
    return joint_probs(share * lam, share * nu, (1 - share) * lam, (1 - share) * nu)


def ece(y, p) -> float:
    from ..goals.validation import calibration_bins

    bins = calibration_bins(np.asarray(y, dtype=float), np.asarray(p, dtype=float))
    return float(sum(b["n"] * abs(b["tahmin"] - b["gercek"]) for b in bins) / max(len(y), 1))


def ece_noise_q95(p, reps: int = ECE_NOISE_REPS, seed: int = ECE_NOISE_SEED) -> float:
    """Tahminler kusursuz kalibre olsaydı (y ~ Bernoulli(p)) örneklem gürültüsüyle oluşacak ECE'nin %95 yüzdeliği."""
    p = np.asarray(p, dtype=float)
    if len(p) == 0:
        return float("nan")
    rng = np.random.default_rng(seed)
    vals = [ece((rng.random(len(p)) < p).astype(float), p) for _ in range(reps)]
    return float(np.quantile(vals, 0.95))


def measure(y, p, base, weeks) -> dict:
    """Tek pazar, tek doğrulama grubu: kural ölçütleri ve statü."""
    from ..goals.validation import _ll, block_bootstrap_diff, calibration_bins, calibration_slope

    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    base = np.asarray(base, dtype=float)
    n, pos = int(len(y)), int(y.sum())
    if n == 0:
        return {"n": 0, "pozitif": 0, "statu": False, "neden": "örneklem dışı maç yok"}
    lm, lb = _ll(y, p), _ll(y, base)
    d, lo, hi = block_bootstrap_diff(lm, lb, np.asarray(weeks))
    slope, icpt = calibration_slope(y, p)
    e = ece(y, p)
    e_lim = max(0.02, ece_noise_q95(p))
    brier, brier_b = float(np.mean((p - y) ** 2)), float(np.mean((base - y) ** 2))
    why = []
    if not hi < 0:
        why.append("log-kayıp taban orandan anlamlı biçimde iyi değil")
    if not (slope == slope and 0.8 <= slope <= 1.25):
        why.append("kalibrasyon eğimi 0,8–1,25 dışında")
    if not e <= e_lim:
        why.append("kalibrasyon hatası (ECE) yüksek")
    if pos < MIN_POSITIVE:
        why.append(f"gerçekleşen örnek az ({pos} < {MIN_POSITIVE})")
    return {"n": n, "pozitif": pos, "taban_oran": float(y.mean()), "log_loss": float(lm.mean()),
            "ll_taban": float(lb.mean()), "ll_fark_ref": d, "ll_fark_alt": lo, "ll_fark_ust": hi,
            "kal_egim": slope, "kal_kesisim": icpt, "ece": e, "ece_esik": e_lim, "brier": brier,
            "brier_skill": float(1 - brier / brier_b) if brier_b > 0 else float("nan"),
            "ort_tahmin": float(p.mean()), "kalibrasyon": calibration_bins(y, p),
            "statu": not why, "neden": "; ".join(why)}


@dataclass
class GoalPart:
    """Kupa motorunun gol pazarları bölümü (eğitimde kurulur, tahminde kullanılır)."""
    share: float = SHARE_PRIOR  # bütün kupalar (gösterim)
    share_by_group: dict = field(default_factory=dict)  # doğrulama grubu -> ilk yarı payı (tahminde bu kullanılır)
    base: dict = field(default_factory=dict)  # doğrulama grubu -> {"A","B","C"} kupa taban oranları
    comp_ht_share: dict = field(default_factory=dict)  # turnuva -> geçerli İY skoru oranı
    results: dict = field(default_factory=dict)  # doğrulama grubu -> pazar anahtarı -> ölçümler
    validated: dict = field(default_factory=dict)  # doğrulama grubu -> pazar anahtarı -> bool
    oos: pd.DataFrame | None = None  # ölçülen örneklem dışı tahminler (A, B, C + gerçekleşmeler)
    rule: str = GOAL_RULE
    version: str = GOAL_MODEL_VERSION
    n_ht: int = 0


def build_goal_part(ev: pd.DataFrame, cups: pd.DataFrame, vgroup_of, group_names: dict) -> GoalPart:
    """Kupa motorunun ölçülen örneklem dışı tahminlerinden (``ev``: i, comp, season, date, week, lam_c, nu_c) gol
    pazarları ölçümü. Her sezonun ilk yarı payı ve taban oranları yalnızca o sezondan ÖNCEKİ ve aynı doğrulama
    grubundaki kupa maçlarından (taban: grupta ``MIN_GROUP_BASE`` maçtan azsa bütün kupalar)."""
    part = GoalPart()
    cups = cups.reset_index(drop=True)
    ok_all = ht_mask(cups) if len(cups) else np.zeros(0, dtype=bool)
    part.n_ht = int(ok_all.sum())
    cd = pd.to_datetime(cups["date"]) if len(cups) else pd.Series(dtype="datetime64[ns]")
    lab_all = labels(cups) if len(cups) else {k: np.zeros(0) for k in "ABC"}
    vg_all = np.array([vgroup_of(c) for c in cups["comp"]]) if len(cups) else np.zeros(0, dtype=object)
    if len(cups):
        part.comp_ht_share = {str(c): float(g.mean()) for c, g in pd.Series(ok_all).groupby(cups["comp"].to_numpy())}
        for vg in group_names:
            sel = ok_all & (vg_all == vg)
            src = sel if sel.sum() >= 100 else ok_all
            part.base[vg] = {k: float(lab_all[k][src].mean()) if src.any() else float("nan") for k in "ABC"}
            part.share_by_group[vg] = first_half_share(cups[sel])  # az veride önbilgiye yakın kalır
        part.share = first_half_share(cups[ok_all])
    if ev is None or ev.empty or not len(cups):
        part.results = {vg: {k: {"n": 0, "pozitif": 0, "statu": False, "neden": "örneklem dışı maç yok"}
                             for k in PRIMARY_YES} for vg in group_names}
        part.validated = {vg: {k: False for k in PRIMARY_YES} for vg in group_names}
        part.oos = pd.DataFrame()
        return part
    rows = ev.copy()
    src = cups.iloc[rows["i"].to_numpy()]
    for c in ("hthg", "htag", "fthg", "ftag"):
        rows[c] = src[c].to_numpy()
    rows = rows[ht_mask(rows)].reset_index(drop=True)
    for k, v in labels(rows).items():
        rows[f"y{k}"] = v
    pa, pb, pc = (np.full(len(rows), np.nan) for _ in range(3))
    ba, bb, bc = (np.full(len(rows), np.nan) for _ in range(3))
    rows["vgroup"] = [vgroup_of(c) for c in rows["comp"]]
    for season in rows["season"].unique():
        in_season = (rows["season"] == season).to_numpy()
        before_all = ok_all & (cd < rows.loc[in_season, "date"].min()).to_numpy()
        for vg in rows.loc[in_season, "vgroup"].unique():
            cur = in_season & (rows["vgroup"] == vg).to_numpy()
            before = before_all & (vg_all == vg)
            s = first_half_share(cups[before])
            pr = market_probs(rows.loc[cur, "lam_c"], rows.loc[cur, "nu_c"], s)
            pa[cur], pb[cur], pc[cur] = pr["A"], pr["B"], pr["C"]
            src = before if before.sum() >= MIN_GROUP_BASE else before_all
            if src.sum() >= MIN_GROUP_BASE:
                ba[cur], bb[cur], bc[cur] = (lab_all[k][src].mean() for k in "ABC")
            else:  # önceki kupa maçı yoksa lig gol motorunun tipik oranları (yalnızca ilk sezonlarda olabilir)
                ba[cur], bb[cur], bc[cur] = 0.08, 0.27, 0.33
    rows["pA"], rows["pB"], rows["pC"] = pa, pb, pc
    rows["bA"], rows["bB"], rows["bC"] = ba, bb, bc
    part.oos = rows
    for vg in group_names:
        g = rows[rows["vgroup"] == vg]
        part.results[vg] = {}
        part.validated[vg] = {}
        for key in PRIMARY_YES:
            s = SHORT[key]
            m = measure(g[f"y{s}"], g[f"p{s}"], g[f"b{s}"], g["week"]) if len(g) else \
                {"n": 0, "pozitif": 0, "statu": False, "neden": "örneklem dışı maç yok"}
            part.results[vg][key] = m
            part.validated[vg][key] = bool(m.get("statu"))
    return part


def interval(draw_fn, cov, raw: tuple[float, float]) -> dict:
    """Girdi belirsizliği Monte Carlo aralığı: ham (log λ, log ν) ortak normal çekilir (Laplace kovaryansı), her
    çekilişte bütün hat (kalibrasyon + ortak dağılım) yeniden çalışır. Aralık model varsayımlarına bağlıdır; gerçek
    olasılığın kesin sınırı değildir."""
    meta = {"draws": INTERVAL_DRAWS, "seed": INTERVAL_SEED, "level": INTERVAL_LEVEL,
            "method": "girdi belirsizliği Monte Carlo (ortak modelin ters Hessian kovaryansı; ev ve deplasman gol "
                      "beklentisi birlikte çekilir, kalibrasyon ve ortak dağılım her çekilişte yeniden)"}
    out = {k: (None, None) for k in PRIMARY_YES}
    out["meta"] = meta
    if cov is None or not np.all(np.isfinite(cov)):
        meta["method"] = "aralık hesaplanamadı (kovaryans yok)"
        return out
    try:
        rng = np.random.default_rng(INTERVAL_SEED)
        d = rng.multivariate_normal(np.zeros(2), cov, size=INTERVAL_DRAWS, method="cholesky")
    except (np.linalg.LinAlgError, ValueError):
        meta["method"] = "aralık hesaplanamadı (kovaryans geçersiz)"
        return out
    lam = raw[0] * np.exp(d[:, 0])
    nu = raw[1] * np.exp(d[:, 1])
    p = draw_fn(lam, nu)
    lo, hi = (1 - INTERVAL_LEVEL) / 2, 1 - (1 - INTERVAL_LEVEL) / 2
    for key in PRIMARY_YES:
        v = np.asarray(p[SHORT[key]], dtype=float)
        out[key] = (float(np.nanquantile(v, lo)), float(np.nanquantile(v, hi)))
    return out


__all__ = ["GOAL_MODEL_VERSION", "GOAL_RULE", "GoalPart", "build_goal_part", "market_probs", "first_half_share",
           "labels", "ht_mask", "ht_scores", "measure", "interval"]

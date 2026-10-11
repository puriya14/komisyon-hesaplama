"""M10 aşama tanılaması (S4-MODEL-01): ölçütlerin bağımsız hesabı ve aynı modelin ara çıktıları.

Amaç yeni model aramak değil, mevcut ``M10_ipf_kosullu`` olasılıklarının nerede bozulduğunu ölçmektir. Her doğrulama
sezonu için ürünün ``walk_forward`` bölmesi aynen izlenir ve kat başına TEK bir M10 eğitilir; aşamalar bu aynı
modelin kendi bileşenlerinden okunur (bağımsız yeniden eğitilmiş bir M5 kullanılmaz):

  S0  M0_taban          : ligin geçmiş taban oranları (bA, bB, bC)
  S1  M10.base (M5)     : yapısal ortak dağılımın A, B, C, B∩C kütleleri (``joint_regions``)
  S2  M10.calibrator    : B ve C için lojistik hedefler (A yalnızca bilgi; M10'da kullanılmaz)
  S3  IPF               : B/C hedeflerine eğilmiş dağılım (q kalibrasyonu ÖNCESİ A)
  S4  nihai M10         : A = P(B∩C)·q_kal

Ölçütler ürünün ``validation`` fonksiyonlarından bağımsız yazılmıştır (log-kayıp doğrudan formül, kalibrasyon eğimi
cezasız Newton-IRLS, AUC sıra formülü). Kalibrasyon eğimi sabit tahmin, tek sınıf veya ayrışmada TANIMSIZ döner;
sahte kesin sayı üretilmez. Bu modül tahmin yayınlamaz ve kayıt defterine yazmaz.
"""

from __future__ import annotations

import inspect
from contextlib import contextmanager

import numpy as np
import pandas as pd

from .markets import PRIMARY_YES, SHORT

DIAG_VERSION = "m10-asama-tani-v1"
STAGES = ("S0_M0", "S1_yapisal", "S2_lojistik", "S3_ipf", "S4_nihai")
BOOT_REPS = 1000  # önceden kayıtlı (S4-MODEL-01 planı); sonuca göre değiştirilmez
BOOT_SEED = 20261011
N_BINS = 10
EPS = 1e-12

# Kalibrasyon uyumunun durumu
KAL_TAMAM = "TAMAM"
KAL_SABIT = "SABIT_TAHMIN"  # logit(p) değişmiyor: eğim kesişimden ayrılamaz
KAL_TEK_SINIF = "TEK_SINIF"
KAL_AYRISMA = "AYRISMA"  # tam/yarı tam ayrışma: en çok olabilirlik kestirimi sonlu değil
KAL_YAKINSAMADI = "YAKINSAMADI"
KAL_GECERSIZ = "GECERSIZ_GIRDI"


# ----------------------------------------------------------------------------
# Bağımsız ölçütler
# ----------------------------------------------------------------------------

def _clean(y, p) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    if y.shape != p.shape or y.ndim != 1:
        raise ValueError("y ve p aynı uzunlukta tek boyutlu olmalı")
    return y, p


def valid_pairs(y, p) -> np.ndarray:
    """Ölçüt hesaplanabilecek satırlar: hedef 0/1, olasılık sonlu ve [0, 1] içinde."""
    y, p = _clean(y, p)
    return np.isin(y, (0.0, 1.0)) & np.isfinite(p) & (p >= 0) & (p <= 1)


def log_loss(y, p) -> float:
    """Ortalama ikili log-kayıp: −[y·ln p + (1−y)·ln(1−p)], p ∈ [1e-12, 1−1e-12]. Geçersiz satır varsa hata."""
    y, p = _clean(y, p)
    if len(y) == 0 or not valid_pairs(y, p).all():
        raise ValueError("log-kayıp için geçersiz veya boş girdi")
    q = np.minimum(np.maximum(p, EPS), 1 - EPS)
    return float(-np.mean(np.where(y == 1, np.log(q), np.log1p(-q))))


def brier(y, p) -> float:
    y, p = _clean(y, p)
    if len(y) == 0 or not valid_pairs(y, p).all():
        raise ValueError("Brier için geçersiz veya boş girdi")
    return float(np.mean((p - y) ** 2))


def auc(y, p) -> float:
    """ROC-AUC, Mann-Whitney sıra formülü (bağlar ortalama sıra). Tek sınıfta NaN."""
    from scipy.stats import rankdata

    y, p = _clean(y, p)
    n1 = int((y == 1).sum())
    n0 = int((y == 0).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = rankdata(p)
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def calibration_fit(y, p, max_iter: int = 100, tol: float = 1e-10) -> dict:
    """logit P(Y=1) = a + b·logit(p) için cezasız en çok olabilirlik (Newton-IRLS).

    Döner: {"egim": b, "kesisim": a, "durum": ..., "iter": k}. Eğim yalnızca durum TAMAM iken sayıdır; sabit tahmin,
    tek sınıf ve ayrışmada (sonlu kestirim yok) NaN döner."""
    y, p = _clean(y, p)
    nan = float("nan")
    if len(y) == 0 or not valid_pairs(y, p).all():
        return {"egim": nan, "kesisim": nan, "durum": KAL_GECERSIZ, "iter": 0}
    if y.min() == y.max():
        return {"egim": nan, "kesisim": nan, "durum": KAL_TEK_SINIF, "iter": 0}
    q = np.minimum(np.maximum(p, 1e-9), 1 - 1e-9)
    x = np.log(q) - np.log1p(-q)
    if np.ptp(x) < 1e-9:
        return {"egim": nan, "kesisim": nan, "durum": KAL_SABIT, "iter": 0}
    # Tek boyutta ayrışma: bir sınıfın bütün değerleri diğerininkilerden büyük-eşit (ya da küçük-eşit)
    x1, x0 = x[y == 1], x[y == 0]
    if x1.min() >= x0.max() or x1.max() <= x0.min():
        return {"egim": nan, "kesisim": nan, "durum": KAL_AYRISMA, "iter": 0}
    # Merkezlenmiş/ölçeklenmiş tasarımda Newton (dar aralıkta tekil matris olmasın); sonuç özgün ölçeğe döndürülür
    xm, xs = float(x.mean()), float(x.std())
    X = np.column_stack([np.ones_like(x), (x - xm) / xs])
    beta = np.array([np.log(y.mean() / (1 - y.mean())), 0.0])
    for it in range(1, max_iter + 1):
        eta = X @ beta
        mu = 1.0 / (1.0 + np.exp(-eta))
        w = mu * (1 - mu)
        g = X.T @ (y - mu)
        H = X.T @ (X * w[:, None])
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        beta = beta + step
        if not np.all(np.isfinite(beta)):
            break
        if np.max(np.abs(step)) < tol:
            b = float(beta[1]) / xs
            return {"egim": b, "kesisim": float(beta[0]) - b * xm, "durum": KAL_TAMAM, "iter": it}
    return {"egim": nan, "kesisim": nan, "durum": KAL_YAKINSAMADI, "iter": max_iter}


def calibration_fit_grouped(y, p, groups) -> dict:
    """Grup (sezon) sabit etkili eğim: logit P = a_g + b·logit(p). Yalnızca tanılama (sezon düzeyi kaymayı ayırır)."""
    y, p = _clean(y, p)
    g = np.asarray(groups)
    nan = float("nan")
    if len(y) == 0 or not valid_pairs(y, p).all():
        return {"egim": nan, "durum": KAL_GECERSIZ}
    q = np.minimum(np.maximum(p, 1e-9), 1 - 1e-9)
    x = np.log(q) - np.log1p(-q)
    levels = [lv for lv in pd.unique(g) if 0 < y[g == lv].mean() < 1]
    keep = np.isin(g, levels)
    y, x, g = y[keep], x[keep], g[keep]
    if len(levels) == 0 or np.ptp(x) < 1e-9:
        return {"egim": nan, "durum": KAL_SABIT if len(levels) else KAL_TEK_SINIF}
    D = np.column_stack([(g == lv).astype(float) for lv in levels] + [x])
    beta = np.zeros(D.shape[1])
    for lv_i, lv in enumerate(levels):
        m = y[g == lv].mean()
        beta[lv_i] = np.log(m / (1 - m))
    for _ in range(100):
        mu = 1.0 / (1.0 + np.exp(-(D @ beta)))
        w = mu * (1 - mu)
        step = np.linalg.solve(D.T @ (D * w[:, None]), D.T @ (y - mu))
        beta = beta + step
        if np.max(np.abs(step)) < 1e-10:
            return {"egim": float(beta[-1]), "durum": KAL_TAMAM, "gruplar": [str(v) for v in levels]}
    return {"egim": nan, "durum": KAL_YAKINSAMADI}


def bins_table(y, p, n_bins: int = N_BINS) -> list[dict]:
    """Tahmine göre sıralı, eşit sayılı bölmeler: ortalama tahmin, gerçekleşme, n (kararlı sıralama)."""
    y, p = _clean(y, p)
    order = np.argsort(p, kind="mergesort")
    out = []
    for i, idx in enumerate(np.array_split(order, n_bins)):
        if len(idx):
            out.append({"bolme": i + 1, "n": int(len(idx)), "ort_tahmin": float(p[idx].mean()),
                        "gerceklesme": float(y[idx].mean()), "tahmin_min": float(p[idx].min()),
                        "tahmin_max": float(p[idx].max())})
    return out


def distribution(p) -> dict:
    p = np.asarray(p, dtype=float)
    p = p[np.isfinite(p)]
    if len(p) == 0:
        return {"n": 0}
    qs = np.quantile(p, [0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0])
    return {"n": int(len(p)), "ort": float(p.mean()), "sd": float(p.std()),
            **{k: float(v) for k, v in zip(("min", "p05", "p25", "medyan", "p75", "p95", "max"), qs)}}


def block_bootstrap(y, p, ref, blocks, reps: int = BOOT_REPS, seed: int = BOOT_SEED) -> dict:
    """Hafta blokları yeniden örneklenerek Δ log-kayıp (p − ref) ve kalibrasyon eğimi için %95 yüzdelik aralık.

    Tekrar sayısı ve tohum önceden kayıtlıdır. Eğimi tanımsız çıkan tekrar sayısı ayrıca bildirilir (atılmaz,
    gizlenmez)."""
    y, p = _clean(y, p)
    ref = np.asarray(ref, dtype=float)
    blocks = np.asarray(blocks)
    q = lambda v: np.minimum(np.maximum(v, EPS), 1 - EPS)  # noqa: E731
    lp = -np.where(y == 1, np.log(q(p)), np.log1p(-q(p)))
    lr = -np.where(y == 1, np.log(q(ref)), np.log1p(-q(ref)))
    codes, inv = np.unique(blocks, return_inverse=True)
    members = [np.flatnonzero(inv == i) for i in range(len(codes))]
    rng = np.random.default_rng(seed)
    dll, slopes, undefined = [], [], 0
    for _ in range(reps):
        pick = rng.integers(0, len(codes), size=len(codes))
        idx = np.concatenate([members[i] for i in pick])
        dll.append(float(np.mean(lp[idx] - lr[idx])))
        f = calibration_fit(y[idx], p[idx])
        if f["durum"] == KAL_TAMAM:
            slopes.append(f["egim"])
        else:
            undefined += 1
    dll, slopes = np.array(dll), np.array(slopes)
    ci = lambda v: [float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))] if len(v) else [None, None]  # noqa: E731
    return {"tekrar": reps, "tohum": seed, "blok_sayisi": int(len(codes)), "dll_ara": ci(dll),
            "egim_ara": ci(slopes), "egim_tanimsiz_tekrar": undefined}


def metric_block(y, p, ref=None, blocks=None, with_boot: bool = False) -> dict:
    """Tek olasılık dizisi için ölçüt özeti (geçersiz girdide sahte sayı yerine hata/NaN)."""
    from sklearn.metrics import average_precision_score

    y, p = _clean(y, p)
    ok = valid_pairs(y, p)
    out = {"n": int(len(y)), "gecerli": int(ok.sum()), "pozitif": int((y[ok] == 1).sum())}
    if not ok.all() or len(y) == 0:
        out["durum"] = KAL_GECERSIZ
        return out
    fit = calibration_fit(y, p)
    out.update({"log_loss": log_loss(y, p), "brier": brier(y, p), "auc": auc(y, p),
                "ap": float(average_precision_score(y, p)) if 0 < y.sum() < len(y) else float("nan"),
                "gerceklesme": float(y.mean()), "kal_egim": fit["egim"], "kal_kesisim": fit["kesisim"],
                "kal_durum": fit["durum"], "dagilim": distribution(p), "bolmeler": bins_table(y, p)})
    if ref is not None:
        out["dll_ref"] = out["log_loss"] - log_loss(y, ref)
        if with_boot and blocks is not None:
            out["bootstrap"] = block_bootstrap(y, p, ref, blocks)
    return out


# ----------------------------------------------------------------------------
# Aşama çıktıları (ürünün walk_forward bölmesi; kat başına tek M10 eğitimi)
# ----------------------------------------------------------------------------

@contextmanager
def _record_minimize(sink: list):
    """``goals.model`` içindeki ``minimize`` çağrılarını AYNI argümanlarla çalıştırıp sonucunu kaydeder (hesap değişmez).

    Ürün kodu bu çağrılarda uyarıları bastırdığı için yakınsama durumu ``OptimizeResult`` üzerinden okunur."""
    from . import model as M

    orig = M.minimize

    def wrapped(fun, x0, *args, **kwargs):
        res = orig(fun, x0, *args, **kwargs)
        caller = inspect.stack()[1].function
        bounds = kwargs.get("bounds")
        at_bound = []
        if bounds is not None:
            for i, (lo, hi) in enumerate(bounds):
                v = float(res.x[i])
                if (lo is not None and abs(v - lo) < 1e-8) or (hi is not None and abs(v - hi) < 1e-8):
                    at_bound.append(i)
        jac = getattr(res, "jac", None)
        sink.append({"cagiran": caller, "basari": bool(res.success), "durum": int(res.status),
                     "mesaj": str(res.message), "iter": int(getattr(res, "nit", -1)), "nfev": int(res.nfev),
                     "amac": float(res.fun), "x": [float(v) for v in res.x],
                     "sinirda": at_bound, "gradyan_max": float(np.max(np.abs(jac))) if jac is not None else None})
        return res

    M.minimize = wrapped
    try:
        yield
    finally:
        M.minimize = orig


def _event_ids(df: pd.DataFrame) -> np.ndarray:
    from .ledger import event_id

    return np.array([event_id(lg, d, h, a) for lg, d, h, a in zip(df["league"], df["date"], df["home"], df["away"])])


def _stage_frame(m, test: pd.DataFrame) -> pd.DataFrame:
    """Aynı eğitilmiş M10'un aşama çıktıları (satır sırası ``test`` ile aynı)."""
    from .joint import joint_regions
    from .model import GoalModel

    p0 = GoalModel("M0_taban").predict(test)
    lam, bad = m.structural_rates(test)
    reg = joint_regions(lam[:, 0], lam[:, 1], lam[:, 2], lam[:, 3], m.base.mult_h, m.base.mult_a, m.base.phi)
    base = m.base.predict(test)
    cal = m.calibrator.predict(test)
    ipf = m._predict_ipf(test)
    fin = m.predict(test)
    nanb = lambda v: np.where(bad, np.nan, v)  # noqa: E731
    out = pd.DataFrame(index=test.index)
    out["S0_M0:A"], out["S0_M0:B"], out["S0_M0:C"] = p0["A"], p0["B"], p0["C"]
    out["S1_yapisal:A"] = nanb(reg["A"])
    out["S1_yapisal:B"] = nanb(reg["BC"] + reg["BnC"])
    out["S1_yapisal:C"] = nanb(reg["BC"] + reg["nBC"])
    out["S1_yapisal:BC"] = nanb(reg["BC"])
    out["S1_base_predict:A"], out["S1_base_predict:B"], out["S1_base_predict:C"] = base["A"], base["B"], base["C"]
    out["S2_lojistik:A"], out["S2_lojistik:B"], out["S2_lojistik:C"] = cal["A"], cal["B"], cal["C"]
    out["S3_ipf:A"], out["S3_ipf:B"], out["S3_ipf:C"], out["S3_ipf:BC"] = ipf["A"], ipf["B"], ipf["C"], ipf["BC"]
    out["S4_nihai:A"], out["S4_nihai:B"], out["S4_nihai:C"] = fin["A"], fin["B"], fin["C"]
    out["S4_nihai:BC"] = fin["BC"]
    with np.errstate(invalid="ignore", divide="ignore"):
        out["q_ham"] = ipf["A"] / ipf["BC"]
        out["q_kal"] = fin["A"] / fin["BC"]
    out["hedef_B_nan"] = ~np.isfinite(cal["B"])
    out["hedef_C_nan"] = ~np.isfinite(cal["C"])
    out["hedef_B_kirpildi"] = np.isfinite(cal["B"]) & ((cal["B"] < 1e-4) | (cal["B"] > 1 - 1e-4))
    out["hedef_C_kirpildi"] = np.isfinite(cal["C"]) & ((cal["C"] < 1e-4) | (cal["C"] > 1 - 1e-4))
    return out


def _lr_info(calibrator, train: pd.DataFrame, test: pd.DataFrame) -> dict:
    """Lojistik katmanın katsayıları (standartlaştırılmış ölçek), yakınsama ve test özelliklerinin eğitim ölçeğine
    göre konumu (z: eğitim ortalaması ve sapmasıyla)."""
    info = {}
    for key, pipe in calibrator.models.items():
        imp, sc, lr = pipe[0], pipe[1], pipe[-1]
        feats = list(calibrator.features)
        zt = sc.transform(imp.transform(test[feats]))
        info[SHORT[key]] = {
            "ozellik_sayisi": len(feats), "C": float(lr.C), "iter": int(np.max(lr.n_iter_)), "max_iter": int(lr.max_iter),
            "yakinsadi": bool(np.max(lr.n_iter_) < lr.max_iter),
            "kesisim": float(lr.intercept_[0]), "siniflar": [int(c) for c in lr.classes_],
            "katsayi": {f: float(c) for f, c in zip(feats, lr.coef_[0])},
            "test_z_ort": {f: float(v) for f, v in zip(feats, zt.mean(axis=0))},
            "test_katki_ort": {f: float(v) for f, v in zip(feats, (zt * lr.coef_[0]).mean(axis=0))},
            "egitim_eksik_oran": {f: float(v) for f, v in zip(feats, train[feats].isna().mean().to_numpy())},
            "test_eksik_oran": {f: float(v) for f, v in zip(feats, test[feats].isna().mean().to_numpy())},
        }
    return info


def stage_walk_forward(feat: pd.DataFrame, years) -> tuple[pd.DataFrame, list[dict]]:
    """Ürünün ``walk_forward`` bölmesiyle (aynı kat, aynı eğitim kümesi, aynı 2000 satır kuralı) kat başına TEK M10
    eğitimi ve aynı modelin aşama çıktıları. Döner: (satır tablosu, kat bilgileri)."""
    from .model import GoalModel, ht_rows, usable_rows
    from .validation import BURN_IN_LAST, season_year

    feat = feat.copy()
    feat["fold"] = season_year(feat["date"])
    parts, folds = [], []
    for Y in years:
        train = feat[(feat["fold"] < Y) & (feat["fold"] > BURN_IN_LAST)]
        test = feat[feat["fold"] == Y]
        if test.empty or len(train) < 2000:  # ürünle aynı kural (validation.walk_forward)
            continue
        opt: list = []
        with _record_minimize(opt):
            m = GoalModel("M10_ipf_kosullu").fit(train)
        rows = test[["league", "season", "date", "fold", "home", "away", "fthg", "ftag", "hthg", "htag", "issues",
                     *PRIMARY_YES]].copy()
        rows["usable"] = usable_rows(test)
        rows = pd.concat([rows, _stage_frame(m, test)], axis=1)
        rows.insert(0, "event_id", _event_ids(test))
        d = train[usable_rows(train) & ht_rows(train)]
        info = {
            "fold": int(Y), "egitim_ilk": str(pd.Timestamp(train["date"].min()).date()),
            "egitim_son": str(pd.Timestamp(train["date"].max()).date()),
            "test_ilk": str(pd.Timestamp(test["date"].min()).date()),
            "test_son": str(pd.Timestamp(test["date"].max()).date()),
            "egitim_satir": int(len(train)), "egitim_usable": int(usable_rows(train).sum()),
            "egitim_usable_iy": int(len(d)), "test_satir": int(len(test)),
            "egitim_pozitif": {SHORT[k]: int(np.nansum(train.loc[usable_rows(train), k].to_numpy(dtype=float)))
                               for k in PRIMARY_YES},
            "m5": {"n_train": int(m.base.n_train), "coef": [float(v) for v in m.base.coef], "phi": float(m.base.phi),
                   "mult_h": [float(v) for v in m.base.mult_h], "mult_a": [float(v) for v in m.base.mult_a]},
            "qcal": list(m.qcal) if m.qcal is not None else None,
            "optimizasyon": opt, "lojistik": _lr_info(m.calibrator, train, test),
        }
        # q kalibrasyonunun eğitim (örneklem içi) uyumu: aynı eğitim satırlarında (B∩C gerçekleşen)
        yb, yc, ya = (d[k].to_numpy(dtype=float) for k in ("FT_OVER_3_5", "FH_OVER_1_5", "BTTS_BOTH_HALVES_YES"))
        sel = (yb == 1) & (yc == 1) & np.isfinite(ya)
        info["qcal_ornek"] = int(sel.sum())
        if sel.sum() and m.qcal is not None:
            pi = m._predict_ipf(d[sel])
            with np.errstate(invalid="ignore", divide="ignore"):
                q_raw = pi["A"] / pi["BC"]
            q_c = m._q_cal(pi["A"], pi["BC"])
            ok = np.isfinite(q_raw) & np.isfinite(q_c)
            info["qcal_egitim"] = {"n": int(ok.sum()), "gerceklesme": float(ya[sel][ok].mean()),
                                   "ll_ham": log_loss(ya[sel][ok], q_raw[ok]), "ll_kal": log_loss(ya[sel][ok], q_c[ok])}
        # Örneklem içi (eğitim) ile dış test farkı: aynı model, eğitim satırlarında
        tr = _stage_frame(m, d)
        info["egitim_ici"] = {}
        for key in PRIMARY_YES:
            s = SHORT[key]
            y = d[key].to_numpy(dtype=float)
            row = {}
            for st in STAGES:
                p = tr[f"{st}:{s}"].to_numpy(dtype=float)
                ok = np.isfinite(y) & np.isfinite(p)
                row[st] = log_loss(y[ok], p[ok]) if ok.any() else None
            info["egitim_ici"][s] = row
        parts.append(rows)
        folds.append(info)
    return (pd.concat(parts) if parts else pd.DataFrame()), folds


def as_validation_pred(rows: pd.DataFrame) -> pd.DataFrame:
    """Aşama tablosunu ürünün ``evaluate`` girdisine (M0_taban / M10_ipf_kosullu sütunları) dönüştürür."""
    pred = rows[["league", "season", "date", "fold", "home", "away", "fthg", "ftag", "hthg", "htag", "issues",
                 *PRIMARY_YES, "usable"]].copy()
    for s in ("A", "B", "C"):
        pred[f"M0_taban:{s}"] = rows[f"S0_M0:{s}"]
        pred[f"M10_ipf_kosullu:{s}"] = rows[f"S4_nihai:{s}"]
    return pred


def eval_mask(rows: pd.DataFrame, key: str) -> np.ndarray:
    """Ürün ``evaluate`` ile aynı örneklem: etiket var, usable, M0 ve nihai M10 sonlu."""
    s = SHORT[key]
    ok = rows[key].notna().to_numpy() & rows["usable"].to_numpy(dtype=bool)
    for c in (f"S0_M0:{s}", f"S4_nihai:{s}"):
        ok &= np.isfinite(rows[c].to_numpy(dtype=float))
    return ok


def stage_report(rows: pd.DataFrame, with_boot: bool = True) -> dict:
    """Pazar × aşama × (toplu, sezon) ölçütleri; aynı pazarın bütün aşamaları aynı maç kümesinde."""
    weeks = pd.to_datetime(rows["date"]).dt.strftime("%G-%V").to_numpy()
    out = {}
    for key in PRIMARY_YES:
        s = SHORT[key]
        mask = eval_mask(rows, key)
        stage_cols = [st for st in STAGES if f"{st}:{s}" in rows]
        for st in stage_cols:  # aşama sütunu da bu maskede sonlu olmalı (değilse açıkça bildirilir)
            mask_st = np.isfinite(rows[f"{st}:{s}"].to_numpy(dtype=float))
            if not mask_st[mask].all():
                out.setdefault("uyari", []).append(f"{s}:{st} ortak maskede sonlu olmayan değer içeriyor")
        mask &= np.all([np.isfinite(rows[f"{st}:{s}"].to_numpy(dtype=float)) for st in stage_cols], axis=0)
        y = rows.loc[mask, key].to_numpy(dtype=float)
        ref = rows.loc[mask, f"S0_M0:{s}"].to_numpy(dtype=float)
        folds = rows.loc[mask, "fold"].to_numpy()
        wk = weeks[mask]
        mk = {"n": int(mask.sum()), "pozitif": int(y.sum()), "asamalar": {}, "sezonlar": {}}
        for st in stage_cols:
            p = rows.loc[mask, f"{st}:{s}"].to_numpy(dtype=float)
            mk["asamalar"][st] = metric_block(y, p, ref, wk, with_boot=with_boot and st != "S0_M0")
            mk["asamalar"][st]["sezon_sabit_etkili_egim"] = calibration_fit_grouped(y, p, folds)
        for f in sorted(set(folds.tolist())):
            fm = folds == f
            mk["sezonlar"][str(f)] = {st: metric_block(y[fm], rows.loc[mask, f"{st}:{s}"].to_numpy(dtype=float)[fm],
                                                       ref[fm]) for st in stage_cols}
        out[s] = mk
    return out


def structural_checks(rows: pd.DataFrame, tol: float = 1e-9) -> dict:
    """Aşama ilişkileri: A ≤ B∩C ≤ min(B, C); S3→S4 arasında B ve C değişmez; S3'te B/C lojistik hedeflere eşit."""
    out = {}
    for st in ("S1_yapisal", "S3_ipf", "S4_nihai"):
        a, b, c, bc = (rows[f"{st}:{k}"].to_numpy(dtype=float) for k in ("A", "B", "C", "BC"))
        ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(c) & np.isfinite(bc)
        out[st] = {"n": int(ok.sum()), "A>BC": int((a[ok] > bc[ok] + tol).sum()), "A>B": int((a[ok] > b[ok] + tol).sum()),
                   "A>C": int((a[ok] > c[ok] + tol).sum()), "BC>B": int((bc[ok] > b[ok] + tol).sum()),
                   "BC>C": int((bc[ok] > c[ok] + tol).sum()),
                   "aralik_disi": int(((a[ok] < 0) | (b[ok] > 1) | (c[ok] > 1) | (a[ok] > 1)).sum())}
    fin = np.isfinite(rows["S3_ipf:B"].to_numpy(dtype=float))
    for s in ("B", "C"):
        d34 = np.abs(rows[f"S3_ipf:{s}"].to_numpy(dtype=float) - rows[f"S4_nihai:{s}"].to_numpy(dtype=float))[fin]
        t = np.clip(rows[f"S2_lojistik:{s}"].to_numpy(dtype=float), 1e-4, 1 - 1e-4)
        d23 = np.abs(rows[f"S3_ipf:{s}"].to_numpy(dtype=float) - t)[fin]
        out[f"{s}_S3_S4_max_fark"] = float(d34.max()) if len(d34) else None
        out[f"{s}_S3_hedef_max_fark"] = float(d23.max()) if len(d23) else None
    a3 = rows["S3_ipf:A"].to_numpy(dtype=float)
    out["A_S3_S4_degisen"] = int((np.abs(a3 - rows["S4_nihai:A"].to_numpy(dtype=float))[np.isfinite(a3)] > 1e-12).sum())
    b1 = np.abs(rows["S1_yapisal:B"].to_numpy(dtype=float) - rows["S1_base_predict:B"].to_numpy(dtype=float))
    out["S1_yapisal_vs_base_predict_B_max_fark"] = float(np.nanmax(b1)) if np.isfinite(b1).any() else None
    for k in ("hedef_B_nan", "hedef_C_nan", "hedef_B_kirpildi", "hedef_C_kirpildi"):
        out[k] = int(rows[k].sum())
    return out


def ht_missing_profile(matches: pd.DataFrame) -> dict:
    """İlk yarı skoru eksik maçların tanımlayıcı dağılımı (sezon, MS gol toplamı grubu, takım başına sayı)."""
    m = matches[matches["fthg"].notna() & matches["ftag"].notna()]
    miss = m["hthg"].isna() | m["htag"].isna()
    tot = (m["fthg"] + m["ftag"]).astype(int)
    grp = pd.cut(tot, [-1, 1, 3, 100], labels=["0-1", "2-3", "4+"])
    by_team = pd.concat([m.loc[miss, "home"], m.loc[miss, "away"]]).value_counts()
    return {
        "toplam": int(miss.sum()), "mac": int(len(m)),
        "sezon": {str(k): {"eksik": int(v), "mac": int(n)} for (k, v), n in
                  zip(miss.groupby(m["season"]).sum().items(), m.groupby("season").size().to_numpy())},
        "ms_gol_grubu": {str(k): {"eksik": int(miss[grp == k].sum()), "mac": int((grp == k).sum())}
                         for k in grp.cat.categories},
        "takim_basina": {"takim_sayisi": int(len(by_team)), "en_cok": int(by_team.max()) if len(by_team) else 0,
                         "medyan": float(by_team.median()) if len(by_team) else 0.0},
    }


def quarantine_profile(data: bytes, league: str, season: str) -> dict:
    """Bir sezon dosyasındaki karantina kayıtlarının ham tarih/tur özeti ve sezonun geçerli tarih aralığı."""
    import json as _json

    from ..data.parsers import decode_bytes, parse_openfootball_results

    res = parse_openfootball_results(data, league, season)
    raw = _json.loads(decode_bytes(data)).get("matches", [])
    out = {}
    for reason in sorted({k["neden"] for k in res.karantina}):
        ks = [k for k in res.karantina if k["neden"] == reason]
        dates = sorted(k["tarih"] for k in ks if k["tarih"])
        out[reason] = {"sayi": len(ks), "turlar": sorted({k["tur"] for k in ks if k["tur"]}),
                       "ilk_tarih": dates[0] if dates else None, "son_tarih": dates[-1] if dates else None,
                       "yillar": sorted({d[:4] for d in dates})}
    valid = res.matches["date"]
    return {"karantina": out, "ham_kayit": len(raw),
            "gecerli_ilk": str(valid.min().date()) if len(valid) else None,
            "gecerli_son": str(valid.max().date()) if len(valid) else None}


def compare_validation(new: dict, saved: dict) -> dict:
    """Yeniden hesaplanan ``evaluate`` sonucunun kayıtlı doğrulamayla birebir (bit düzeyi) karşılaştırması."""
    keys = ("n", "pozitif", "taban_oran")
    mkeys = ("log_loss", "brier", "brier_skill", "ll_fark_ref", "ll_fark_alt", "ll_fark_ust", "ap", "kal_egim",
             "kal_kesisim", "ece", "ort_tahmin")
    diffs, max_abs = [], 0.0
    for key, sv in saved.items():
        nv = new.get(key)
        if nv is None:
            diffs.append(f"{key}: yeniden hesapta yok")
            continue
        for k in keys:
            if nv[k] != sv[k]:
                diffs.append(f"{key}.{k}: {sv[k]} → {nv[k]}")
        for m, sm in sv["modeller"].items():
            nm = nv["modeller"].get(m, {})
            for k in mkeys:
                a, b = sm.get(k), nm.get(k)
                if a != b and not (a != a and b != b):
                    d = abs(float(a) - float(b)) if a is not None and b is not None else float("inf")
                    max_abs = max(max_abs, d)
                    diffs.append(f"{key}.{m}.{k}: {a!r} → {b!r}")
    return {"birebir": not diffs, "farklar": diffs, "max_mutlak_fark": max_abs}

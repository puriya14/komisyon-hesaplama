"""Dizi araştırması orkestratörü (sözleşme ``dizi-sozlesme-v2``): F1–F7, anomali incelemesi, Mod B kartları, manifest.

Akış (``run_research``):
  1. Takım kimliği eşlemesi (ön-kayıtlı SHA ile karşılaştırılır), takım-maç tablosu, S0 soy kaydı (verilmezse
     kurulur; ~20 dk), sezon sezon genişleyen 9 hücreli kalibrasyon, araştırma çerçevesi.
  2. F1 Sorgu 1: kalibrasyon kapısı → 800 ham hipotez → olay düzeyi tekilleştirme → referans süreç (R tekrar, tam
     arama) → Westfall–Young adım adım maxT → aday seçimi (≤ 5) → parametre döneminde tek yönlü Holm → testte tek
     yönlü Holm + gösterge katsayısı ΔLL + yanlışlama listesi (7b) → statüler. Başarısızlar dahil bütün hipotezler
     kaydedilir.
  3. F2 Sorgu 2 (6 hipotez, aynı referans süreç), F3 S1/S2 (models), F4 tehlike (hazard), F5 A/B/C ek kontrolü,
     F6 varsayımsal ekonomik değer (1X2; İY/MS için ROI_UNAVAILABLE), F7 plasebo negatif kontrol.
  4. Anomali incelemesi (tahminden ayrı; takım/lig/hakem toplaması yok).
  5. Manifest (veri, kod, sözleşme, parametre, eşleme, satır kümesi özetleri; tohum; tekrar sayıları).

Hesaplama bütçesi sabittir: R (varsayılan 1000), plasebo tohum × tekrar (20 × 200), bootstrap 1000; açık uçlu
arama veya optimizasyon yoktur. Paralel çalıştırmada her referans tekrarı kendi tohumunu
(``SeedSequence(seed).spawn(R)[r]``) kullandığından sonuç işçi sayısından bağımsızdır.

Bu modül ana tahmin modellerini, karar motorunu veya mevcut kayıtları DEĞİŞTİRMEZ; yalnızca araştırma çıktısı yazar.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import multiprocessing as mp
import os
import platform
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from html import escape
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
import pandas as pd

from . import anomaly as A
from . import config as C
from . import hazard as HZ
from . import models as M
from . import null as N
from . import patterns as P
from .aliases import ALIAS_VERSION, AliasMap
from .frame import ResearchFrame, build_frame
from .s0 import S0_VARIANT, build_s0, calibrated_cells
from .timeline import build_team_matches

RESULT_VERSION = "dizi-sonuc-v1"
PERIOD_NAMES = ("kesif", "parametre", "test")

# Gerçek veride ilk örüntü sonucundan önce reports/experiments.jsonl'e yazılan ön-kayıt özetleri.
PREREGISTERED = {
    "sozlesme_sha256": "4599ddb2eb2dffa90ae608ad1557e0da21c0158553bc9e3f087fb2598ffe40bf",
    "parametre_ozeti": "fc12e4915484c78e1c33c7bb4c538205d3e9a247fa656cb59fd2f6e764d814a0",
    "esleme_sha256": "69f7a695315bbb9c4f16e467a1ea30e0ce65fe226ce88e1bb4f9fb55e07d940a",
}

# Sözleşmenin açık bıraktığı uygulama kararları. Gerçek veride ilk örüntü sonucundan ÖNCE ayrı bir deney kaydı
# olarak yazılır (``preregister_run_decisions``); özeti her manifestte bulunur.
RUN_DECISIONS = {
    "degerlendirme_maskesi": (
        "Her dönemde (keşif/parametre/test) Sorgu 1 ve Sorgu 2 maskesi = uygun ∧ dönem, ikiz-simetrik: maçın iki "
        "takım satırından biri uygun değilse ikisi de çıkar. Gerekçe: lig değişikliği sonrası S0 soğuk başlangıcı "
        "maçın iki tarafını da etkiler; ayna hipotezler (ör. RAKIP_SON3_MAGLUBIYET × GALIBIYET ≡ SON3_MAGLUBIYET × "
        "MAGLUBIYET) ancak böyle tam denk olur."),
    "tekillestirme": "Olay düzeyi imza aynı maskede; ayna kopyalar WY ailesinden çıkar ve temsilcinin sonucunu taşır.",
    "baglam_referansi": ("Çift seçim kuralında bağlam atomlarının tek başına O/E'si context_reference_conditions ile "
                         "hesaplanır; bunlar aileye girmez ve statü almaz (yalnızca 'S0 kalibrasyon tanılaması')."),
    "aday_parametre": "Parametre döneminde tek yönlü (keşif yönü) Holm, k = seçilen aday sayısı.",
    "aday_test": (
        "Testte tek yönlü Holm, k = parametreyi geçen aday sayısı. Gösterge katsayısı: S0 logit offset + sabit + "
        "gösterge (λ = 0) keşif + parametre (arındırılmış, label_known_at < 2019-07-01) satırlarında; karşılaştırma "
        "aynı satırlarda öğrenilen 'S0 + sabit' ile (sabitin yeniden kalibrasyonu ayrıştırılır); ham S0'a göre fark "
        "ayrıca raporlanır. Değerlendirme satırları: test maskesinde koşulun tanımlı olduğu satırlar. ΔLL lig-sezon "
        "kümeli bootstrap (1000)."),
    "yanlislama": "7b/1–5 hem parametre hem test döneminde geçmeli (katı yorum); 7b/5 için S0p = models.s0p_predict.",
    "plasebo": ("F7 başarısızsa (keşif çıkan tohum > 1) referans süreç güvenilmez sayılır: F1 ve F2 keşifleri "
                "INSUFFICIENT_EVIDENCE statüsüne indirilir (dondurulur)."),
    "plasebo_bagisci": ("Plasebo bağışçısı: aynı lig-sezon, farklı takım ve rakip olmayan; en yakın S0 galibiyet "
                        "ondalığı, sonra satırdan SONRA OLMAYAN en yakın tarih (aynı gün olabilir; aynı gün bağışçı "
                        "satırın takımı/rakibiyle oynamaz) — §4 zaman güvenliği."),
    "sozlesme_sabitleri": ("Sözleşme metnindeki sabitler modül sabiti olarak kullanılır (config_hash'e girmez): "
                           "z = 1,96; 7b/2 çıkarılan pay %1; 7b/3 sezon payı %60; eşleştirme S0 ondalığı 10; karşı örnek 20; "
                           "plasebo S0 ondalığı 10; bootstrap 1000; tehlike kırılganlık önseli 50, önceki 2 sezon."),
    "sorgu2_statu": (
        "Sorgu 2: WY anlamlı (p_adj < 0,05 ve MC aralığı 0,05'i içermiyor) hipotezler parametre ve test dönemlerinde "
        "tek yönlü Holm (k = WY-anlamlı sayısı) ile sınanır; ikisi de geçer ve testte oran aralığı 1'i dışlarsa "
        "OUT_OF_SAMPLE_SUPPORTED (7b listesi Sorgu 1 içindir; kartta belirtilir); WY anlamsız → INSUFFICIENT_EVIDENCE; "
        "WY anlamlı ama örneklem dışı geçmedi → NO_ADDED_VALUE."),
    "modeller": "F3–F6 kendi modüllerinin satır kuralını (uygun ∧ dönem; ortak küme kesişimi) kullanır.",
    "f3_yanlislama": (
        "F3 (S1/S2) ve F4 (tehlike) için 7b uyarlaması kendi modüllerindedir (models._falsification/_market_check, "
        "hazard._falsification/_market_check), her iki örneklem dışı dönemde: 1) bir lig/takım çıkarılınca ΔLL < 0 "
        "kalmalı; 2) en çok katkı veren %1 satır çıkarılınca ΔLL < 0 ve bootstrap üst sınırı < 0; 3) sezonların ≥ %60'ında "
        "iyileşme; 4) UYGULANAMAZ (koşul örüntüsüne özgü); 5) piyasa kontrolü: S1 için S0p offsetli S1 vs S0p, S2 için "
        "S0p + aynı komşu düzeltmesi, F4 için S0 sıcaklığı + piyasa logitleri ortak değişkenken kategori katkısı."),
    "s0p_tanimi": (
        "S0p (piyasa kontrolü; F1 7b/5, F3): hedef başına logit p = logit p0 + τ'·logit p0 + sabit + β1·logit(piyasa galip) "
        "+ β2·logit(piyasa mağlup) — S0'a serbest sıcaklık (1 + τ'), cezasız, dönem planıyla arındırılmış ve dondurulmuş. "
        "Sözleşmedeki 9 hücreli çarpan biçimi yerine hedef başına biçim; değişiklik models gözden geçirmesinde sentetik "
        "veride gösterilen zayıflık (S0 katsayısı 1'e sabit) nedeniyle, F1'in gerçek veride çalıştırılmasından önce."),
    "onceden_gorulen_aileler": (
        "Geliştirme sırasında bir alt ajan F3, F5 ve F6'yı gerçek veride (test dönemi dahil) hesapladı. Bu ailelerin "
        "test dönemi temiz sayılmaz: OUT_OF_SAMPLE_SUPPORTED en fazla EXPLORATORY olarak raporlanır. F1, F2, F4, F7 "
        "gerçek sonuçlarla S0'a göre hesaplanmadı (F1 uygulayıcısı yalnızca hız ölçümü için sahte bir S0 kullandı)."),
    "anomali": "Anomali taraması tüm dönemlerin uygun maçlarında; depoya yalnızca tür/durum/dönem sayıları yazılır, "
               "tekil maç kayıtları yalnızca yerel uygulama klasöründe tutulur.",
}


# ----------------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------------

def jsonable(obj):
    """numpy/pandas değerlerini JSON'a uygun Python türlerine çevirir (NaN/±sonsuz → None)."""
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return [jsonable(r) for r in obj.to_dict(orient="records")]
    if isinstance(obj, pd.Series):
        return jsonable(obj.to_list())
    if isinstance(obj, np.ndarray):
        return [jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return v if math.isfinite(v) else None
    if isinstance(obj, (pd.Timestamp, dt.datetime, dt.date)):
        return obj.isoformat()
    if obj is None or isinstance(obj, (str, int)):
        return obj
    return str(obj)


def _sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def data_sha256(matches: pd.DataFrame) -> str:
    """Maç tablosunun içerik özeti (satır sırası ve sütunlar dahil; indeks hariç)."""
    h = pd.util.hash_pandas_object(matches.reset_index(drop=True), index=False).to_numpy()
    cols = "|".join(map(str, matches.columns))
    return hashlib.sha256(h.astype("<u8").tobytes() + cols.encode()).hexdigest()


def run_decisions_sha256() -> str:
    return _sha_text(json.dumps(RUN_DECISIONS, sort_keys=True, ensure_ascii=False))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def contract_sha256() -> str | None:
    p = _repo_root() / "docs" / "DIZI_ARASTIRMA_SOZLESMESI.md"
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def git_state() -> dict:
    root = _repo_root()
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, timeout=10)
        return {"commit": head.stdout.strip() or None, "kirli": bool(dirty.stdout.strip())}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "kirli": None}


def code_sha256() -> str:
    """``sequences`` paketindeki kaynak dosyaların özeti (test dönemi açıldıktan sonra kod değişikliğini yakalar)."""
    h = hashlib.sha256()
    for f in sorted(Path(__file__).resolve().parent.glob("*.py")):
        h.update(f.name.encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def _read_experiments(path: Path | None) -> list[dict]:
    path = path or (_repo_root() / "reports" / "experiments.jsonl")
    if not Path(path).exists():
        return []
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def clean_test_status(manifest: dict, experiments: list[dict]) -> dict:
    """Test dönemi "temiz" mi? (sözleşme: test açıldıktan sonra değiştirilen tanım temiz test sayılmaz)

    Temiz değil: sözleşme/parametre/eşleme ön-kayıttan farklıysa veya test dönemi daha önce (F1 kaydı) farklı
    parametre, uygulama kararı ya da ``sequences`` kodu özetiyle açılmışsa.
    """
    reasons = []
    for k, ok in manifest.get("on_kayitla_uyum", {}).items():
        if not ok:
            reasons.append(f"{k} ön-kayıttan farklı")
    keys = (("parametre_ozeti", "parametre_ozeti"), ("kararlar_sha256", "uygulama_kararlari_sha256"),
            ("kod_sha256", "kod_sha256"))
    earlier = [r for r in experiments if str(r.get("asama", "")).startswith("dizi-arastirma F1")]
    for r in earlier:
        diff = [a for a, b in keys if r.get(a) is not None and r.get(a) != manifest.get(b)]
        if diff:
            reasons.append(f"test dönemi {r.get('zaman_utc')} tarihinde farklı tanımla açılmış ({', '.join(diff)})")
    return {"temiz": not reasons, "nedenler": reasons, "onceki_acilis": len(earlier)}


SEEN_FAMILIES = ("F3", "F5", "F6")  # RUN_DECISIONS['onceden_gorulen_aileler']


def _downgrade_seen(results: dict) -> None:
    """Önceden görülmüş ailelerde (F3/F5/F6) OUT_OF_SAMPLE_SUPPORTED → EXPLORATORY (gerekçesiyle)."""
    why = ("Test dönemi bu aile için temiz değil: geliştirme sırasında gerçek veride hesaplandı "
           "(RUN_DECISIONS['onceden_gorulen_aileler']).")
    for r in (results["aileler"].get("F3") or {}).get("holm", []):
        if r.get("statu") == "OUT_OF_SAMPLE_SUPPORTED":
            r["statu"], r["gerekce"] = "EXPLORATORY", why
    for rec in ((results["aileler"].get("F5") or {}).get("pazarlar") or {}).values():
        if rec.get("statu") == "OUT_OF_SAMPLE_SUPPORTED":
            rec["statu"], rec["gerekce"] = "EXPLORATORY", why


def _downgrade_unclean(results: dict, clean: dict) -> None:
    """Temiz olmayan test döneminde OUT_OF_SAMPLE_SUPPORTED statüleri EXPLORATORY'ye iner (kartta gerekçesiyle)."""
    if clean.get("temiz"):
        return
    why = "Test dönemi temiz değil: " + "; ".join(clean.get("nedenler", []))
    for fam in ("F1", "F2"):
        f = results["aileler"].get(fam)
        if not f:
            continue
        df = f.get("hipotezler")
        if isinstance(df, pd.DataFrame) and len(df):
            hit = df["statu"] == "OUT_OF_SAMPLE_SUPPORTED"
            df.loc[hit, "gerekce"] = why
            df.loc[hit, "statu"] = "EXPLORATORY"
            f["statu_sayilari"] = _status_counts(df.loc[df["tekil"], "statu"] if "tekil" in df else df["statu"])
        for c in f.get("adaylar", []) or []:
            if c.get("statu") == "OUT_OF_SAMPLE_SUPPORTED":
                c["statu"], c["gerekce"] = "EXPLORATORY", why
    for r in (results["aileler"].get("F3") or {}).get("holm", []):
        if r.get("statu") == "OUT_OF_SAMPLE_SUPPORTED":
            r["statu"], r["gerekce"] = "EXPLORATORY", why
    for v in ((results["aileler"].get("F4") or {}).get("events") or {}).values():
        if v.get("status") == "OUT_OF_SAMPLE_SUPPORTED":
            v["status"], v["status_reason"] = "EXPLORATORY", why


def period_masks(fr: ResearchFrame) -> dict[str, np.ndarray]:
    """Sorgu 1/2 değerlendirme maskeleri (RUN_DECISIONS['degerlendirme_maskesi'])."""
    per = np.asarray(fr.period, dtype=object)
    return {k: P.pair_symmetric(fr, np.asarray(fr.eligible, dtype=bool) & (per == k)) for k in PERIOD_NAMES}


def realised_cells(tm: pd.DataFrame, s0: pd.DataFrame) -> pd.Series:
    """S0 satırlarına hizalı gerçekleşen ham İY/MS hücresi (ev perspektifi; bilinmiyor −1)."""
    home = tm[tm["is_home"]].drop_duplicates("event_id").set_index("event_id")["raw_cell"]
    return pd.Series(home.reindex(s0["event_id"]).fillna(-1).astype(int).to_numpy(), index=s0.index)


# ----------------------------------------------------------------------------
# Paralel referans süreç
# ----------------------------------------------------------------------------

_SHARED: dict = {}


def _fork_ok(workers: int) -> bool:
    return workers > 1 and "fork" in mp.get_all_start_methods()


def _chunks(R: int, parts: int) -> list[range]:
    parts = max(1, min(R, parts))
    edges = np.linspace(0, R, parts + 1).round().astype(int)
    return [range(int(a), int(b)) for a, b in zip(edges[:-1], edges[1:]) if b > a]


def _null_job(job):
    kind, reps = job
    g = _SHARED
    if kind == "q1":
        return N.run_null(g["fr"], g["mask"], g["R"], g["seed"], prep=g["prep"], hyp_ids=g["ids"], reps=reps)
    if kind == "q2":
        return N.run_null_q2(g["fr"], g["mask"], g["R"], g["seed"], reps=reps)
    if kind == "placebo":
        return N.run_placebo(g["fr"], g["mask"], seeds=[reps], R=g["R_placebo"], hyp_ids=g["ids"])["seeds"][0]
    raise KeyError(kind)


def _run_jobs(jobs: list, workers: int, progress: Callable | None, label: str) -> list:
    out = []
    t0 = time.time()
    if not _fork_ok(workers):
        for k, job in enumerate(jobs):
            out.append(_null_job(job))
            if progress:
                progress(f"{label}: {k + 1}/{len(jobs)} parça ({time.time() - t0:.0f} sn)")
        return out
    ctx = mp.get_context("fork")
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
        for k, res in enumerate(ex.map(_null_job, jobs)):
            out.append(res)
            if progress:
                progress(f"{label}: {k + 1}/{len(jobs)} parça ({time.time() - t0:.0f} sn)")
    return out


def parallel_null_q1(fr, mask, R, seed, prep, ids, workers=1, progress=None) -> dict:
    _SHARED.clear()
    _SHARED.update(fr=fr, mask=mask, R=R, seed=seed, prep=prep, ids=ids)
    try:
        parts = _run_jobs([("q1", r) for r in _chunks(R, max(1, workers) * 4)], workers, progress, "F1 referans")
    finally:
        _SHARED.clear()
    return {"z": np.vstack([p["z"] for p in parts]), "supported": np.vstack([p["supported"] for p in parts]),
            "T": np.vstack([p["T"] for p in parts]), "hyp_ids": list(ids), "R": R}


def parallel_null_q2(fr, mask, R, seed, workers=1, progress=None) -> dict:
    _SHARED.clear()
    _SHARED.update(fr=fr, mask=mask, R=R, seed=seed)
    try:
        parts = _run_jobs([("q2", r) for r in _chunks(R, max(1, workers) * 4)], workers, progress, "F2 referans")
    finally:
        _SHARED.clear()
    return {"z": np.vstack([p["z"] for p in parts]), "supported": np.vstack([p["supported"] for p in parts]),
            "hyp_ids": parts[0]["hyp_ids"], "R": R}


def parallel_placebo(fr, mask, ids, seeds, R_placebo, workers=1, progress=None) -> dict:
    _SHARED.clear()
    _SHARED.update(fr=fr, mask=mask, ids=ids, R_placebo=R_placebo)
    try:
        out = _run_jobs([("placebo", int(s)) for s in seeds], workers, progress, "F7 plasebo")
    finally:
        _SHARED.clear()
    n_with = sum(1 for d in out if d["n_discoveries"] > 0)
    return {"seeds": out, "R": R_placebo, "n_seeds": len(out), "n_seeds_with_discovery": n_with,
            "passed": n_with <= C.PLACEBO_MAX_DISCOVERIES,
            "not": f"Plasebo başına R = {R_placebo} referans tekrarı; keşif = WY p_adj < {C.ALPHA}."}


# ----------------------------------------------------------------------------
# F1: Sorgu 1
# ----------------------------------------------------------------------------

def _cond_mask(fr, atoms: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    """(geçerli, koşul) — atomlardan biri tanımsızsa satır geçersizdir."""
    valid = np.ones(len(fr.tm), dtype=bool)
    cond = np.ones(len(fr.tm), dtype=bool)
    for a in atoms:
        v = np.asarray(fr.atoms[a], dtype=float)
        valid &= np.isfinite(v)
        cond &= np.nan_to_num(v, nan=0.0) == 1
    return valid, cond & valid


def indicator_dll(fr, target: str, atoms: Sequence[str], masks: dict, n_boot: int = 1000,
                  seed: int = C.SEED) -> dict:
    """Gösterge katsayısı (keşif + parametre, arındırılmış) → test ΔLL (S0 + sabit + gösterge) − (S0 + sabit)."""
    valid, cond = _cond_mask(fr, atoms)
    y = np.asarray(fr.y[target], dtype=float)
    p0 = np.asarray(fr.p0[target], dtype=float)
    base = valid & np.isfinite(y) & np.isfinite(p0)
    cut = M._period_start_day("test")
    train = base & (masks["kesif"] | masks["parametre"]) & (M._days(fr) + 1 < cut)
    test = base & masks["test"]
    out = {"n_egitim": int(train.sum()), "n_test": int(test.sum()), "n_test_kosul": int((test & cond).sum())}
    if train.sum() == 0 or test.sum() == 0 or (cond & train).sum() == 0:
        out["durum"] = "SATIR_YOK"
        return out
    X = cond.astype(float)[:, None]
    off = M._logit(p0)
    f1 = M.fit_offset_logistic(X[train], y[train], off[train], 0.0, names=["gosterge"])
    f0 = M.fit_offset_logistic(X[train], y[train], off[train], math.inf, names=["gosterge"])
    l1 = M._log_loss(y[test], f1.predict(X[test], off[test]))
    l0 = M._log_loss(y[test], f0.predict(X[test], off[test]))
    lr = M._log_loss(y[test], p0[test])
    d = M.cluster_bootstrap_diff(l1, l0, fr.cluster[test], n_boot, seed)
    d_raw = M.cluster_bootstrap_diff(l1, lr, fr.cluster[test], n_boot, seed)
    wk = M.cluster_bootstrap_diff(l1, l0, M._iso_weeks(fr, test), n_boot, seed)
    out.update({
        "durum": "OK", "uyum": f1.summary(), "uyum_sabit": f0.summary(),
        "gosterge_log_odds": float(f1.coef[0]) if len(f1.coef) else None,
        "egitim_son_tarih": str(pd.Timestamp(fr.tm["date"].to_numpy()[train].max()).date()),
        "ll_s0": float(lr.mean()), "ll_s0_sabit": float(l0.mean()), "ll_s0_gosterge": float(l1.mean()),
        "fark": d, "fark_ham_s0": {k: d_raw[k] for k in ("diff", "ci_lo", "ci_hi", "p_one_sided")},
        "iso_hafta": {k: wk[k] for k in ("ci_lo", "ci_hi", "p_one_sided", "n_clusters")},
        "satir_sha256": M.rows_sha256(fr, test),
    })
    return out


def _single_eval(fr, mask, target, name, atoms) -> dict:
    df = P.evaluate(fr, mask, conditions=[(name, tuple(atoms))], targets=(target,))
    return df.iloc[0].to_dict()


def _status_counts(statuses: Sequence[str]) -> dict:
    s = pd.Series(list(statuses), dtype=object)
    return {k: int(v) for k, v in s.value_counts().sort_index().items()}


def run_f1(fr, masks, R=C.N_NULL, seed=C.SEED, workers=1, progress=None, s0p: dict | None = None,
           n_boot: int = 1000) -> dict:
    disc = masks["kesif"]
    gate = P.calibration_gate(fr, disc)
    out = {"aile": "F1", "sorgu": "Sorgu 1 (maç öncesi)", "R": int(R), "tohum": int(seed),
           "kalibrasyon_kapisi": {"gecti": bool(gate.attrs.get("passed")), "tablo": gate}}
    conditions = P.build_conditions()
    if not gate.attrs.get("passed"):
        out["durum"] = "KALIBRASYON_KAPISI_GECMEDI"
        out["not"] = "Sözleşme §7: kapı geçmediği için arama yapılmadı; S0 kalibrasyon sorunu raporlanır."
        out["hipotez_ham"] = len(conditions) * len(C.TARGETS_Q1)
        out["hipotezler"] = []
        out["statu_sayilari"] = {}
        out["adaylar"] = []
        return out
    if progress:
        progress("F1: keşif döneminde 800 hipotez değerlendiriliyor")
    prep = P.prepare(fr, disc, conditions)
    obs = P.evaluate(fr, disc, conditions=conditions, prep=prep)
    dd = P.dedupe(fr, disc, conditions=conditions)
    ids = list(dd["unique"])
    dup = dict(dd["duplicate_of"])
    if progress:
        progress(f"F1: {dd['n_raw']} ham, {dd['n_unique']} tekil hipotez; referans süreç R={R}")
    t0 = time.time()
    null = parallel_null_q1(fr, disc, R, seed, prep, ids, workers=workers, progress=progress)
    t_null = time.time() - t0
    fam = obs.set_index("hyp_id").loc[ids]
    p_adj, lo, hi = N.westfall_young_stepdown(fam["z"].to_numpy(), fam["supported"].to_numpy(), null["z"],
                                              null["supported"])
    obs = obs.set_index("hyp_id")
    obs["tekil"] = [h not in dup for h in obs.index]
    obs["ayna_kopyasi"] = [dup.get(h) for h in obs.index]
    for col, vals in (("p_adj", p_adj), ("ci_lo", lo), ("ci_hi", hi)):
        s = pd.Series(vals, index=ids)
        obs[col] = [s.get(dup.get(h, h), np.nan) for h in obs.index]
    sup_ids = [h for h in ids if bool(fam.at[h, "supported"])]
    by = pd.Series(N.by_descriptive(fam.loc[sup_ids, "z"].to_numpy()), index=sup_ids, dtype=float)
    obs["p_by_tanimlayici"] = [by.get(dup.get(h, h), np.nan) for h in obs.index]
    obs = obs.reset_index()

    # Bağlam atomları tek başına (aile dışı; seçim kuralı ve S0 kalibrasyon tanılaması)
    ref = P.evaluate(fr, disc, conditions=P.context_reference_conditions())
    out["baglam_tanilama"] = ref[["hyp_id", "target", "condition", "n", "O", "E_adj", "E_raw", "lift", "lift_lo",
                                  "lift_hi", "z", "supported"]]

    uniq = obs[obs["tekil"]].copy()
    sig = uniq["supported"].astype(bool) & (uniq["p_adj"] < C.ALPHA) & (uniq["ci_hi"] < C.ALPHA)
    # Çift kuralı için tek atom oranları: bağlam referansı + ayna kopyası tekil hipotezler (temsilcileriyle aynı
    # istatistik; aday olamazlar, yalnızca karşılaştırma için).
    reference = pd.concat([ref, obs[~obs["tekil"]]], ignore_index=True)
    cands = P.select_candidates(uniq, reference=reference) if sig.any() else uniq.iloc[0:0].assign(
        direction=[], rank=[], lcb_abs_log_lift=[])
    out["cift_kurali_dogrulanamadi"] = list(cands.attrs.get("cift_kurali_dogrulanamadi", []))
    if progress:
        progress(f"F1: WY anlamlı {int(sig.sum())} hipotez, {len(cands)} aday")

    # Parametre ve test aşamaları
    cand_recs = []
    for _, c in cands.iterrows():
        cand_recs.append({"hyp_id": c["hyp_id"], "hedef": c["target"], "kosul": c["condition"],
                          "atomlar": list(c["atoms"]), "yon": int(c["direction"]), "sira": int(c["rank"]),
                          "kesif": {k: c[k] for k in ("n", "O", "E_adj", "lift", "lift_lo", "lift_hi", "z", "p_adj",
                                                       "ci_lo", "ci_hi")}})
    for rec in cand_recs:
        rec["parametre"] = _single_eval(fr, masks["parametre"], rec["hedef"], rec["kosul"], rec["atomlar"])
    if cand_recs:
        h = P.holm_one_sided([r["parametre"]["z"] for r in cand_recs], [r["yon"] for r in cand_recs])
        for k, rec in enumerate(cand_recs):
            rec["parametre"].update(p_tek=float(h["p_one"][k]), p_holm=float(h["p_holm"][k]),
                                    gecti=bool(h["reject"][k]))
    passed = [r for r in cand_recs if r["parametre"]["gecti"]]
    for rec in passed:
        rec["test"] = _single_eval(fr, masks["test"], rec["hedef"], rec["kosul"], rec["atomlar"])
        rec["gosterge"] = indicator_dll(fr, rec["hedef"], rec["atomlar"], masks, n_boot=n_boot, seed=seed)
    if passed:
        h = P.holm_one_sided([r["test"]["z"] for r in passed], [r["yon"] for r in passed])
        for k, rec in enumerate(passed):
            rec["test"].update(p_tek=float(h["p_one"][k]), p_holm=float(h["p_holm"][k]), gecti=bool(h["reject"][k]))
    for rec in cand_recs:
        mk = s0p.get(rec["hedef"]) if s0p else None
        rec["yanlislama"] = {}
        for per in ("parametre", "test") if "test" in rec else ("parametre",):
            rec["yanlislama"][per] = P.falsification(fr, rec["hedef"], (rec["kosul"], tuple(rec["atomlar"])),
                                                     masks[per], p0_market=mk)
        rec["mod_b"] = {per: P.mode_b_card(fr, rec["hedef"], (rec["kosul"], tuple(rec["atomlar"])), masks[per])
                        for per in PERIOD_NAMES}
        rec["statu"], rec["gerekce"] = _candidate_status(rec)

    # Statüler (tekil hipotezler; ayna kopyaları temsilcinin statüsünü taşır)
    cmap = {r["hyp_id"]: r for r in cand_recs}
    st, why = [], []
    by_id = obs.set_index("hyp_id")
    for _, r in obs.iterrows():
        h = r["ayna_kopyasi"] if isinstance(r["ayna_kopyasi"], str) else r["hyp_id"]
        rr = by_id.loc[h]
        if h in cmap:
            st.append(cmap[h]["statu"])
            why.append(cmap[h]["gerekce"])
        elif not bool(rr["supported"]):
            st.append("INSUFFICIENT_EVIDENCE")
            why.append(f"Destek yetersiz (n < {C.MIN_N} veya beklenen < {C.MIN_E:g}).")
        elif not (rr["p_adj"] < C.ALPHA and rr["ci_hi"] < C.ALPHA):
            st.append("INSUFFICIENT_EVIDENCE")
            why.append("Westfall–Young düzeltilmiş p ≥ 0,05 veya Monte Carlo aralığı 0,05'i içeriyor.")
        else:
            st.append("EXPLORATORY")
            why.append("Keşifte aile düzeltmesinden geçti; aday sınırı/çift kuralı nedeniyle örneklem dışı sınanmadı.")
    obs["statu"], obs["gerekce"] = st, why
    out.update({
        "durum": "TAMAM", "hipotez_ham": int(dd["n_raw"]), "hipotez_tekil": int(dd["n_unique"]),
        "ayna_kopyasi_sayisi": int(dd["n_duplicates"]), "bos_imzali": len(dd["empty"]),
        "desteklenen_tekil": int(fam["supported"].sum()), "wy_anlamli": int(sig.sum()),
        "referans_sure_sn": round(t_null, 1), "hipotezler": obs, "adaylar": cand_recs,
        "statu_sayilari": _status_counts(obs.loc[obs["tekil"], "statu"]),
        "satir_sha256": {k: M.rows_sha256(fr, m) for k, m in masks.items()},
        "satir_sayisi": {k: int(m.sum()) for k, m in masks.items()},
        "referans_ozeti": {"null_max_abs_z_medyan": float(np.nanmedian(np.nanmax(
            np.where(null["supported"], np.abs(null["z"]), np.nan), axis=1))) if R else None},
    })
    return out


def _candidate_status(rec: dict) -> tuple[str, str]:
    par = rec.get("parametre", {})
    if not par.get("gecti"):
        return "NO_ADDED_VALUE", "Parametre döneminde tek yönlü Holm geçmedi."
    te = rec.get("test", {})
    if not te.get("gecti"):
        return "NO_ADDED_VALUE", "Test döneminde tek yönlü Holm geçmedi."
    g = rec.get("gosterge", {})
    if g.get("durum") != "OK" or not (g["fark"]["ci_hi"] < 0):
        return "NO_ADDED_VALUE", "Testte S0 + gösterge log-kaybı S0 + sabitten anlamlı düşük değil."
    fz = rec.get("yanlislama", {})
    for per in ("parametre", "test"):
        f = fz.get(per, {})
        if not f.get("passed_1_4"):
            return "NO_ADDED_VALUE", f"Yanlışlama listesi (7b/1–4) {per} döneminde geçmedi."
        if f.get("checks", {}).get("5_piyasa", {}).get("passed") is not True:
            return "NO_ADDED_VALUE", f"Piyasa (S0p) kontrolünde etki kayboldu ({per}): piyasa/temel model bilgisi."
    return "OUT_OF_SAMPLE_SUPPORTED", ("Parametre + test Holm, test ΔLL üst sınırı < 0 ve 7b/1–5 geçti. Test dönemi "
                                       "koşullu örüntüler için ön-kayıtlı; S0 İY/MS kalibrasyonu test döneminde "
                                       "görülmüş (§5). Tamamen temiz kanıt yalnızca ileriye dönük takiptir.")


# ----------------------------------------------------------------------------
# F2: Sorgu 2
# ----------------------------------------------------------------------------

def run_f2(fr, masks, R=C.N_NULL, seed=C.SEED, workers=1, progress=None) -> dict:
    disc = masks["kesif"]
    obs = P.q2_evaluate(fr, disc)
    null = parallel_null_q2(fr, disc, R, seed + 2, workers=workers, progress=progress)
    order = [list(null["hyp_ids"]).index(h) for h in obs["hyp_id"]]
    p_adj, lo, hi = N.westfall_young_stepdown(obs["z"].to_numpy(dtype=float), obs["supported"].to_numpy(),
                                              null["z"][:, order], null["supported"][:, order])
    obs["p_adj"], obs["ci_lo"], obs["ci_hi"] = p_adj, lo, hi
    sig = (obs["supported"].astype(bool) & (obs["p_adj"] < C.ALPHA) & (obs["ci_hi"] < C.ALPHA)).to_numpy()
    obs["yon"] = np.sign(obs["z"].to_numpy(dtype=float))
    per_res = {}
    for per in ("parametre", "test"):
        d = P.q2_evaluate(fr, masks[per]).set_index("hyp_id").loc[obs["hyp_id"]]
        per_res[per] = d
    st, why = [], []
    sig_idx = np.where(sig)[0]
    holm = {}
    for per in ("parametre", "test"):
        if len(sig_idx):
            z = per_res[per]["z"].to_numpy(dtype=float)[sig_idx]
            holm[per] = P.holm_one_sided(z, obs["yon"].to_numpy()[sig_idx])
    for i, r in obs.iterrows():
        if not bool(r["supported"]) or not sig[i]:
            st.append("INSUFFICIENT_EVIDENCE")
            why.append("Westfall–Young düzeltilmiş p ≥ 0,05, MC aralığı 0,05'i içeriyor veya destek yok.")
            continue
        k = int(np.where(sig_idx == i)[0][0])
        ok_par = bool(holm["parametre"]["reject"][k])
        ok_te = bool(holm["test"]["reject"][k])
        te = per_res["test"].iloc[i]
        excl = (te["ratio_lo"] > 1) if r["yon"] > 0 else (te["ratio_hi"] < 1)
        if ok_par and ok_te and excl:
            st.append("OUT_OF_SAMPLE_SUPPORTED")
            why.append("Parametre ve test Holm geçti; test oran aralığı 1'i dışlıyor (7b listesi Sorgu 1 içindir).")
        else:
            st.append("NO_ADDED_VALUE")
            why.append("Keşifte anlamlı; örneklem dışı (parametre/test) doğrulanmadı.")
    obs["statu"], obs["gerekce"] = st, why
    return {"aile": "F2", "sorgu": "Sorgu 2 (olay sonrası)", "R": int(R), "hipotezler": obs,
            "parametre": per_res["parametre"].reset_index(), "test": per_res["test"].reset_index(),
            "holm": {k: {kk: vv for kk, vv in v.items()} for k, v in holm.items()},
            "statu_sayilari": _status_counts(st)}


# ----------------------------------------------------------------------------
# Kart (HTML) ve arayüz özeti
# ----------------------------------------------------------------------------

def _fmt(v, nd=3) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-" if v is None else escape(str(v))
    return "-" if not math.isfinite(f) else f"{f:.{nd}f}"


def pattern_card_html(f1: dict, f7: dict | None) -> str:
    """Örüntü doğrulama kartı (§13): tanım, dönemler, denenen alternatif sayısı, Mod B, yanlışlama, statü."""
    parts = ["<h3>Örüntü doğrulama — Sorgu 1 (maç öncesi)</h3>",
             f"<p>Denenen ham hipotez: <b>{f1.get('hipotez_ham', '-')}</b>, tekil: <b>{f1.get('hipotez_tekil', '-')}</b>"
             f" · referans tekrarı R = {f1.get('R', '-')} · keşif 2006/07–2012/13 · parametre 2013/14–2018/19 · "
             "test 2019/20–2025/26.</p>"]
    if f7:
        parts.append(f"<p>Plasebo negatif kontrol: {escape(str(f7.get('ozet', '-')))}</p>")
    cands = f1.get("adaylar", [])
    if not cands:
        parts.append("<p>Keşif döneminde aile bazlı hata kontrolünden (Westfall–Young) geçen örüntü yok. "
                     "Bu da geçerli bir sonuçtur: S0'ın bildiğinin ötesinde, ön-kayıtlı koşullarda tekrar eden bir "
                     "ilişki bulunamadı.</p>")
    for c in cands:
        mb = c.get("mod_b", {})
        parts.append(f"<h4>{escape(c['hedef'])} | {escape(c['kosul'])} — {escape(C.STATUS_TR.get(c['statu'], c['statu']))}"
                     f" (<code>{escape(c['statu'])}</code>)</h4><p>{escape(c['gerekce'])}</p>")
        rows = []
        for per in PERIOD_NAMES:
            b = mb.get(per, {})
            rows.append(f"<tr><td>{per}</td><td>{b.get('n_cond', '-')}</td><td>{b.get('hits', '-')}</td>"
                        f"<td>{b.get('misses', '-')}</td><td>{_fmt(b.get('rate_with'))}</td>"
                        f"<td>{_fmt(b.get('rate_without'))}</td><td>{_fmt(b.get('matched_base_rate'))}</td>"
                        f"<td>{_fmt(b.get('E_adj'), 1)}</td><td>{_fmt(b.get('lift'))} [{_fmt(b.get('lift_lo'))}, "
                        f"{_fmt(b.get('lift_hi'))}]</td></tr>")
        parts.append("<table border='1' cellspacing='0' cellpadding='3'><tr><th>Dönem</th><th>n koşul</th>"
                     "<th>İsabet</th><th>Iska</th><th>Koşullu oran</th><th>Koşulsuz oran</th><th>Eşleştirilmiş taban</th>"
                     "<th>S0 beklenen</th><th>O/E [%95]</th></tr>" + "".join(rows) + "</table>")
        fz = c.get("yanlislama", {})
        for per, f in fz.items():
            chk = f.get("checks", {})
            items = "".join(f"<li>{escape(k)}: {'geçti' if v.get('passed') else ('çalıştırılmadı' if v.get('passed') is None else 'geçmedi')}</li>"
                            for k, v in chk.items())
            parts.append(f"<p>Yanlışlama ({per}):</p><ul>{items}</ul>")
        g = c.get("gosterge")
        if g and g.get("durum") == "OK":
            parts.append(f"<p>Test ΔLL (S0+sabit+gösterge − S0+sabit): {_fmt(g['fark']['diff'], 5)} "
                         f"[{_fmt(g['fark']['ci_lo'], 5)}, {_fmt(g['fark']['ci_hi'], 5)}]</p>")
    parts.append("<p><i>Bulunan bir ilişki nedensellik veya manipülasyon kanıtı değildir; bulunamaması da "
                 "manipülasyon olmadığını kanıtlamaz. Gerçek oranlı test: İY/MS hedefleri için ROI_UNAVAILABLE.</i></p>")
    return "".join(parts)


def ui_summary(results: dict, anomalies: list[dict] | None) -> dict:
    """Arayüzün okuduğu özet (``dizi_arastirma/son_sonuclar.json``)."""
    f1 = results.get("aileler", {}).get("F1", {})
    f7 = results.get("aileler", {}).get("F7")
    hyps = pd.DataFrame(f1.get("hipotezler", []))
    pats = []
    if len(hyps):
        h = hyps[hyps["tekil"]] if "tekil" in hyps else hyps
        h = h.sort_values(["p_adj", "hyp_id"], na_position="last", kind="mergesort")
        for _, r in h.iterrows():
            pats.append({"hyp_id": r["hyp_id"], "hedef": r["target"], "kosul": r["condition"], "statu": r["statu"],
                         "lift": r["lift"], "lift_lo": r["lift_lo"], "lift_hi": r["lift_hi"], "p_adj": r["p_adj"],
                         "n": r["n"], "O": r["O"], "E_adj": r["E_adj"], "sorgu": r.get("sorgu")})
    out = {
        "surum": RESULT_VERSION, "manifest": results.get("manifest", {}),
        "hipotez_ham": f1.get("hipotez_ham"), "hipotez_tekil": f1.get("hipotez_tekil"), "R": f1.get("R"),
        "kalibrasyon_kapisi": "geçti" if f1.get("kalibrasyon_kapisi", {}).get("gecti") else "geçmedi",
        "oruntuler": pats, "oruntu_karti_html": pattern_card_html(f1, f7),
        "aileler": {k: {"ozet": v.get("ozet"), "statu_sayilari": v.get("statu_sayilari")}
                    for k, v in results.get("aileler", {}).items()},
        "anomaliler": [{k: r.get(k) for k in ("date", "league", "season", "htft", "s0_p_gerceklesen", "surprise_bits",
                                               "model_market_gap", "type", "status", "explained_by", "period")}
                       for r in (anomalies or [])],
        "anomali_ozeti": results.get("anomali_ozeti", {}),
        "benzer_diziler_notu": results.get("benzer_diziler_notu"),
    }
    return jsonable(out)


# ----------------------------------------------------------------------------
# Ana akış
# ----------------------------------------------------------------------------

def _family_summary(name: str, res: dict) -> str:
    if name == "F1":
        if res.get("durum") != "TAMAM":
            return str(res.get("durum"))
        return (f"{res['hipotez_ham']} ham / {res['hipotez_tekil']} tekil hipotez, {res['desteklenen_tekil']} destekli, "
                f"WY anlamlı {res['wy_anlamli']}, aday {len(res['adaylar'])}; statüler {res['statu_sayilari']}")
    if name == "F2":
        return f"6 hipotez; statüler {res['statu_sayilari']}"
    if name == "F3":
        return "; ".join(f"{r['hedef']}/{r['model']}: {r['statu']}" for r in res.get("holm", []))
    if name == "F4":
        return "; ".join(f"{e}: {v['status']}" for e, v in res.get("events", {}).items())
    if name == "F5":
        return "; ".join(f"{k}: {v.get('statu')}" for k, v in res.get("pazarlar", {}).items())
    if name == "F6":
        bits = []
        for per, rr in res.items():
            for t, v in rr.get("hedefler", {}).items():
                src = v.get("kaynaklar", {})
                bits.append(f"{per}/{t}: " + ", ".join(
                    f"{s}={_fmt(x.get('roi')) if not isinstance(x.get('roi'), str) else x.get('roi')}"
                    for s, x in src.items()))
        return "; ".join(bits) + " (varsayımsal)"
    if name == "F7":
        return (f"{res['n_seeds_with_discovery']}/{res['n_seeds']} tohumda WY keşfi (sınır "
                f"{C.PLACEBO_MAX_DISCOVERIES}) → {'GEÇTİ' if res['passed'] else 'GEÇMEDİ'}; plasebo başına R={res['R']}")
    return ""


def append_experiment(record: dict, path: Path | None = None) -> None:
    path = path or (_repo_root() / "reports" / "experiments.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(jsonable(record), ensure_ascii=False, sort_keys=False) + "\n")


def preregister_run_decisions(path: Path | None = None) -> dict:
    """Uygulama kararlarını gerçek veride ilk örüntü sonucundan ÖNCE deney kaydına yazar (bir kez)."""
    path = path or (_repo_root() / "reports" / "experiments.jsonl")
    sha = run_decisions_sha256()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if sha in line and "dizi-uygulama-kararlari" in line:
                return {"durum": "zaten_kayitli", "sha256": sha}
    rec = {"zaman_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "asama": "dizi-uygulama-kararlari (gercek veride ilk oruntu sonucundan ONCE)",
           "sozlesme": C.CONTRACT_VERSION, "parametre_ozeti": C.config_hash(), "kararlar_sha256": sha,
           "kararlar": RUN_DECISIONS, "kod_sha256": code_sha256(), "git": git_state()}
    append_experiment(rec, path)
    return {"durum": "kaydedildi", "sha256": sha}


def build_research_frame(matches: pd.DataFrame, s0: pd.DataFrame | None = None, progress=None,
                         alias_map: AliasMap | None = None) -> tuple[ResearchFrame, pd.DataFrame, dict]:
    """Eşleme → takım-maç tablosu → (S0) → kalibrasyon → çerçeve. Dönüş: (çerçeve, ham S0, bilgi)."""
    progress = progress or (lambda s: None)
    am = alias_map or AliasMap.from_matches(matches)
    progress("Takım-maç tablosu kuruluyor")
    tm = build_team_matches(matches, am)
    if s0 is None:
        progress("S0 soy kaydı kuruluyor (sezon başına walk-forward M10; uzun sürer)")
        s0 = build_s0(matches, alias_map=am, progress=progress)
    progress("S0 9 hücreli kalibrasyon (genişleyen pencere)")
    cal, params = calibrated_cells(s0, realised_cells(tm, s0))
    progress("Araştırma çerçevesi (atomlar, S1 özellikleri)")
    fr = build_frame(tm, cal, with_s1=True)
    fr.meta["s0_kalibre"] = cal
    info = {"esleme_surumu": ALIAS_VERSION, "esleme_sha256": am.sha256(),
            "esleme_on_kayitla_ayni": am.sha256() == PREREGISTERED["esleme_sha256"],
            "s0_varyant": S0_VARIANT, "s0_satir": int(len(s0)),
            "s0_model_ozetleri": sorted(set(map(str, s0["model_hash"]))) if "model_hash" in s0 else [],
            "s0_kalibrasyon": {str(k): v for k, v in params.items()},
            "cerceve": {k: v for k, v in fr.meta.items() if k != "s0_kalibre"}}
    return fr, s0, info


def run_research(matches: pd.DataFrame, out_dir: Path, s0: pd.DataFrame | None = None, R: int = C.N_NULL,
                 placebo_seeds: int = C.N_PLACEBO_SEEDS, R_placebo: int = C.N_NULL_PLACEBO, workers: int = 1,
                 families: Sequence[str] = ("F1", "F2", "F3", "F4", "F5", "F6", "F7"), seed: int = C.SEED,
                 n_boot: int = 1000, progress: Callable | None = None, record: bool = True,
                 reports_dir: Path | None = None, experiments_path: Path | None = None,
                 data_label: str = "") -> dict:
    """Ön-kayıtlı araştırmayı çalıştırır ve sonuçları ``out_dir`` (+ isteğe bağlı ``reports_dir``) altına yazar.

    ``record=True``: her aile sonucu (olumlu/olumsuz/sonuçsuz) ``experiments_path``'e eklenir.
    """
    progress = progress or (lambda s: None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    started = dt.datetime.now(dt.timezone.utc)
    families = list(families)
    if record:
        preregister_run_decisions(experiments_path)
    prior_experiments = _read_experiments(experiments_path)
    fr, s0, info = build_research_frame(matches, s0, progress)
    masks = period_masks(fr)
    manifest = {
        "surum": RESULT_VERSION, "zaman_utc": started.isoformat(timespec="seconds"), "saat_dilimi": "UTC",
        "sozlesme": C.CONTRACT_VERSION, "sozlesme_sha256": contract_sha256(),
        "parametre_ozeti": C.config_hash(), "uygulama_kararlari_sha256": run_decisions_sha256(),
        "on_kayit": PREREGISTERED,
        "on_kayitla_uyum": {"sozlesme": contract_sha256() == PREREGISTERED["sozlesme_sha256"],
                            "parametre": C.config_hash() == PREREGISTERED["parametre_ozeti"],
                            "esleme": info["esleme_on_kayitla_ayni"]},
        "veri_sha256": data_sha256(matches), "veri_etiketi": data_label, "mac_sayisi": int(len(matches)),
        "veri_tarih_araligi": [str(pd.Timestamp(matches["date"].min()).date()),
                               str(pd.Timestamp(matches["date"].max()).date())],
        "git": git_state(), "kod_sha256": code_sha256(), "python": platform.python_version(), "tohum": int(seed),
        "R": int(R),
        "plasebo": {"tohum_sayisi": int(placebo_seeds), "R": int(R_placebo)}, "bootstrap": int(n_boot),
        "isci": int(workers), "aileler": families, **{k: v for k, v in info.items() if k != "s0_kalibrasyon"},
        "satir_kumeleri": {k: {"n": int(m.sum()), "sha256": M.rows_sha256(fr, m)} for k, m in masks.items()},
        "hesaplama_butcesi": {"referans_tekrar": int(R), "plasebo": f"{placebo_seeds} × {R_placebo}",
                              "bootstrap": int(n_boot), "acik_uclu_arama": False, "harici_api_cagrisi": 0},
    }
    manifest["temiz_test"] = clean_test_status(manifest, prior_experiments)
    results: dict = {"manifest": manifest, "aileler": {}, "s0_kalibrasyon": info["s0_kalibrasyon"]}

    def done(name, res):
        results["aileler"][name] = res
        _downgrade_unclean(results, manifest["temiz_test"])
        _downgrade_seen(results)
        res["ozet"] = _family_summary(name, res)
        progress(f"{name}: {res['ozet']}")
        if record:
            append_experiment({"zaman_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                               "asama": f"dizi-arastirma {name}", "sozlesme": C.CONTRACT_VERSION,
                               "parametre_ozeti": C.config_hash(), "kararlar_sha256": run_decisions_sha256(),
                               "kod_sha256": manifest["kod_sha256"], "veri_sha256": manifest["veri_sha256"],
                               "temiz_test": manifest["temiz_test"]["temiz"],
                               "git": manifest["git"], "R": R, "tohum": seed, "ozet": res["ozet"],
                               "statu_sayilari": res.get("statu_sayilari")}, experiments_path)

    s0p = None
    fitted = None
    if "F1" in families or "F3" in families or "F6" in families:
        progress("S0p (piyasa kontrolü) uyumları")
        s0p = {t: M.s0p_predict(fr, t)[0] for t in C.TARGETS_Q1}
    if "F7" in families:
        # Plasebo F1'den önce: referans sürecin güvenilirliği keşiflere bakılmadan belirlenir.
        disc = masks["kesif"]
        dd = P.dedupe(fr, disc)
        progress(f"F7 plasebo: {placebo_seeds} tohum × R={R_placebo}")
        f7 = parallel_placebo(fr, disc, dd["unique"], [seed + 1000 + k for k in range(placebo_seeds)], R_placebo,
                              workers=workers, progress=progress)
        done("F7", f7)
    if "F1" in families:
        f1 = run_f1(fr, masks, R=R, seed=seed, workers=workers, progress=progress, s0p=s0p, n_boot=n_boot)
        if "F7" in results["aileler"] and not results["aileler"]["F7"]["passed"]:
            _freeze_discoveries(f1)
        done("F1", f1)
    if "F2" in families:
        f2 = run_f2(fr, masks, R=R, seed=seed, workers=workers, progress=progress)
        if "F7" in results["aileler"] and not results["aileler"]["F7"]["passed"]:
            _freeze_discoveries(f2)
        done("F2", f2)
    if "F3" in families or "F6" in families:
        progress("F3: S1 ve S2 uyumları (S2 tam kNN araması uzun sürer)")
        fitted = M.fit_models(fr)
    if "F3" in families:
        f3 = M.run_f3(fr, models=fitted, n_boot=n_boot)
        f3["statu_sayilari"] = _status_counts([r["statu"] for r in f3.get("holm", [])])
        done("F3", f3)
    if "F4" in families:
        progress("F4: olaylar arası süre ve tehlike modeli")
        done("F4", HZ.run_hazard_family(fr, n_boot=n_boot))
    if "F5" in families:
        progress("F5: A/B/C ek kontrolü")
        done("F5", M.abc_check(fr, s0, n_boot=n_boot))
    if "F6" in families:
        progress("F6: varsayımsal ekonomik değer")
        done("F6", {per: M.run_f6(fr, fitted, period=per, n_boot=n_boot) for per in ("parametre", "test")})
    progress("Anomali incelemesi (tahminden ayrı)")
    an_mask = np.asarray(fr.eligible, dtype=bool) & pd.notna(pd.Series(fr.period)).to_numpy()
    anomalies = A.flag_anomalies(fr, mask=an_mask)
    results["anomali_ozeti"] = A.anomaly_summary(anomalies)
    results["benzer_diziler_notu"] = (
        "Maç öncesi görünüm: yaklaşan maç için yalnızca karar anından önce bilinen koşullar ve geçmiş benzer örnekler "
        "(başarılı ve başarısız birlikte). Statü yalnızca bu dondurulmuş kayıttan okunur; EXPLORATORY ve "
        "INSUFFICIENT_EVIDENCE örüntüler olasılığı değiştirmez.")
    manifest["sure_sn"] = round(time.time() - t_start, 1)
    manifest["bitis_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    fr.meta["s0_kalibre"].to_pickle(out_dir / "s0_kalibre.pkl")  # maç öncesi görünüm için (yalnızca yerel)
    _write_outputs(results, anomalies, out_dir, reports_dir)
    return results


def _freeze_discoveries(fam: dict) -> None:
    df = fam.get("hipotezler")
    if isinstance(df, pd.DataFrame) and len(df):
        hit = df["statu"].isin(["EXPLORATORY", "NO_ADDED_VALUE", "OUT_OF_SAMPLE_SUPPORTED"])
        df.loc[hit, "gerekce"] = "Plasebo negatif kontrol geçmedi: referans süreç güvenilmez → keşif donduruldu."
        df.loc[hit, "statu"] = "INSUFFICIENT_EVIDENCE"
        fam["statu_sayilari"] = _status_counts(df["statu"])
    for c in fam.get("adaylar", []) or []:
        c["statu"], c["gerekce"] = "INSUFFICIENT_EVIDENCE", "Plasebo negatif kontrol geçmedi → keşif donduruldu."


def _write_outputs(results: dict, anomalies: list[dict], out_dir: Path, reports_dir: Path | None) -> None:
    full = jsonable(results)
    (out_dir / "sonuclar_tam.json").write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "manifest.json").write_text(json.dumps(full["manifest"], ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    (out_dir / "anomaliler.json").write_text(json.dumps(jsonable(anomalies), ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    f1 = results["aileler"].get("F1", {})
    if isinstance(f1.get("hipotezler"), pd.DataFrame):
        f1["hipotezler"].to_csv(out_dir / "f1_hipotezler.csv", index=False, encoding="utf-8")
    (out_dir / "son_sonuclar.json").write_text(json.dumps(ui_summary(results, anomalies), ensure_ascii=False,
                                                          indent=1), encoding="utf-8")
    if reports_dir is not None:
        reports_dir = Path(reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)
        # Depoya tekil maç anomali kaydı yazılmaz (yalnızca tür/durum/dönem sayıları; sonuclar_tam içinde).
        (reports_dir / "dizi_sonuclar.json").write_text(json.dumps(full, ensure_ascii=False, indent=1),
                                                        encoding="utf-8")
        if isinstance(f1.get("hipotezler"), pd.DataFrame):
            f1["hipotezler"].to_csv(reports_dir / "dizi_f1_hipotezler.csv", index=False, encoding="utf-8")


def load_or_build_s0(matches: pd.DataFrame, out_dir: Path, progress: Callable | None = None,
                     alias_map: AliasMap | None = None) -> pd.DataFrame:
    """S0 soy kaydını ``out_dir/s0_soy.pkl`` önbelleğinden okur; veri, eşleme veya varyant değiştiyse yeniden kurar."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    am = alias_map or AliasMap.from_matches(matches)
    key = {"veri_sha256": data_sha256(matches), "esleme_sha256": am.sha256(), "s0_varyant": S0_VARIANT}
    path, meta = out_dir / "s0_soy.pkl", out_dir / "s0_soy.json"
    if path.exists() and meta.exists():
        try:
            if json.loads(meta.read_text(encoding="utf-8")) == key:
                return pd.read_pickle(path)
        except (OSError, ValueError):
            pass
    s0 = build_s0(matches, alias_map=am, progress=progress)
    s0.to_pickle(path)
    meta.write_text(json.dumps(key), encoding="utf-8")
    return s0

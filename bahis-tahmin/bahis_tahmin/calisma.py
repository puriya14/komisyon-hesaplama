"""Kayıtlı araştırmalar ve karşılaştırmalı tarihsel analiz (S6-CALISMA-01).

GitHub tarihsel arşivinin (``archive``) üzerinde betimleyici bir çalışma alanı:

* Araştırma tanımı tipli ve sürümlüdür (``TANIM_SURUMU``): başlık, açıklama, kaynak görünümü (tek kaynak veya AÇIK
  birleştirilmiş görünüm), Grup 1 ve isteğe bağlı Grup 2 filtreleri, raporlanacak pazarlar ve etiketler. Filtre
  alanları açık izin listesiyle doğrulanır; bilinmeyen alan hata verir. SQL, Python ifadesi veya ``eval`` yoktur.
* Tanım değişince yeni revizyon eklenir; eski revizyon ve ona bağlı çalıştırmalar değişmez (SQLite tetikleyicileri
  UPDATE/DELETE işlemlerini reddeder). Kayıt bir araştırma tanımıdır; sonuçlar görülmeden kaydedildiğinin kanıtı
  (bilimsel ön-kayıt) değildir.
* Bir çalıştırmada iki grup AYNI arşiv yüklemesinden ve aynı ``ArchiveView``'dan hesaplanır; kaynak filtresi
  birleştirmeden önce uygulanır (``archive.view``). Grup hesapları ``archive.explore_view`` ve merkezi pazar kaydını
  (``archive.summary`` → ``goals.markets``) kullanır; yeni etiket formülü yoktur.
* Çalıştırma kaydı: araştırma kimliği ve revizyonu, gerçek çalıştırma zamanı, tam tanım, görünüm, kaynak commit'leri,
  içerik özeti (dosya yolu veya değiştirilme zamanı DEĞİL), ayrıştırıcı/eşleme/analiz sürümleri, grup olay kümesi
  özeti ve sayısı, toplu sonuçlar, uyarılar ve kod sürümü. Aynı veri ve tanımla hesap aynı ``sonuc_ozeti``'ni verir.
* Notlar serbest metindir; skorları, kaynak kimliğini, maç statüsünü veya model sonucunu değiştirmez ve hiçbir karar
  kuralını çalıştırmaz. Maça bağlı not mevcut olay kimliği ve görünümle doğrulanır; kart ``archive.event_card_for``
  ile açılır.
* Bütün sonuçlar ``DESCRIPTIVE_RESEARCH`` statüsündedir: olasılık, p-değeri, strateji başarısı veya bahis önerisi
  üretilmez. Özetler (SHA-256) içerik eşleşmesi denetimi içindir; bağımsız zaman damgası, saldırıya dayanıklı
  değişmezlik veya yedek değildir.

Çalışma alanı uygulama veri klasöründen ve arşiv klasöründen AYRI bir klasördedir (varsayılan ``<uygulama>-Calisma``,
``BAHIS_TAHMIN_CALISMA`` ile değiştirilebilir). Okuma işlemleri çalışma alanını oluşturmaz, ağ isteği yapmaz ve
hiçbir dosyaya yazmaz; kaydetme, çalıştırma ve not ekleme açıkça yazan işlemlerdir.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from . import archive as A
from .config import app_home_path
from .data.source_registry import archive_allowed

STATUS = "DESCRIPTIVE_RESEARCH"
TANIM_SURUMU = "calisma-tanim-v1"
ANALIZ_SURUMU = "calisma-analiz-v1"
SCHEMA_VERSION = 1
APP_TAG = "bahis-tahmin-calisma"
DB_NAME = "calisma.sqlite"
SELECTED_BY_OUTCOME = "GECMIS_SONUCA_GORE_SECILMIS_GRUP"
MARKETS = ("A", "B", "C", "IYMS")
OUTCOME_VALUES = ("tumu", "gerceklesti", "gerceklesmedi", "bilinmiyor")
DEF_KEYS = ("tanim_surumu", "baslik", "aciklama", "kaynak", "grup_1", "grup_2", "pazarlar", "etiketler")
GROUP_KEYS = ("lig", "sezonlar", "takim", "yer", "bas", "son", "sonuc")
OUTCOME_KEYS = ("A", "B", "C", "iy_ms")
LIMITS = {"baslik": 200, "aciklama": 4000, "etiket": 50, "etiket_sayisi": 20, "not": 4000, "takim": 100,
          "sezon_sayisi": 60}
NOTE_STATES = ("aktif", "arsivlendi")
PREREG_NOTE = ("Bu kayıt bir araştırma tanımıdır; sonuçlar görülmeden kaydedildiğinin kanıtı (bilimsel ön-kayıt) "
               "değildir. 'kayit_aninda_onceki_calistirma' bu revizyon kaydedilirken araştırmanın kaç kez "
               "çalıştırılmış olduğunu gösterir.")
HASH_NOTE = ("Özetler (SHA-256) içerik eşleşmesini denetlemek içindir; bağımsız zaman damgası, saldırıya dayanıklı "
             "değişmezlik veya yedek değildir.")
COMPARISON_NOTE = ("Fark yüzde puandır: 100 × (oran_grup_1 − oran_grup_2); göreli yüzde değişim değildir. Payda sıfırsa "
                   "oran ve fark null'dur. İstatistiksel test yapılmadı.")
OVERLAP_NOTE = "Gruplar ortak maç içeriyor; bağımsız örnekler değildir."
OUTCOME_NOTE = ("Bu grup geçmiş maç sonucuna göre seçildi; seçimde kullanılan pazarın gerçekleşme oranı seçimin doğal "
                "sonucudur, tahmin başarısı veya maç öncesi strateji değildir.")
NOTE_NOTE = ("Kullanıcı notudur; skoru, kaynak kimliğini, resmî maç statüsünü veya model sonucunu değiştirmez ve "
             "sistemin bir tespiti (ör. şike tespiti) sayılmaz.")
_CODE_FILES = ("calisma.py", "archive.py", "goals/markets.py", "data/teams.py", "data/parsers.py", "data/statsbomb.py",
               "sequences/timeline.py")

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS arastirma_revizyonlari (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        arastirma_id TEXT NOT NULL,
        revizyon INTEGER NOT NULL,
        olusturma_utc TEXT NOT NULL,
        tanim TEXT NOT NULL,
        tanim_ozeti TEXT NOT NULL,
        kayit_aninda_onceki_calistirma INTEGER NOT NULL,
        UNIQUE (arastirma_id, revizyon))""",
    """CREATE TABLE IF NOT EXISTS calistirmalar (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        calistirma_id TEXT UNIQUE NOT NULL,
        arastirma_id TEXT NOT NULL,
        revizyon INTEGER NOT NULL,
        calistirma_utc TEXT NOT NULL,
        durum TEXT NOT NULL,
        veri_ozeti TEXT NOT NULL,
        sonuc_ozeti TEXT NOT NULL,
        kayit TEXT NOT NULL,
        FOREIGN KEY (arastirma_id, revizyon) REFERENCES arastirma_revizyonlari (arastirma_id, revizyon))""",
    """CREATE TABLE IF NOT EXISTS calistirma_gruplari (
        calistirma_id TEXT NOT NULL REFERENCES calistirmalar (calistirma_id),
        grup INTEGER NOT NULL,
        olay_sayisi INTEGER NOT NULL,
        olay_ozeti TEXT NOT NULL,
        olaylar TEXT NOT NULL,
        PRIMARY KEY (calistirma_id, grup))""",
    """CREATE TABLE IF NOT EXISTS notlar (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        not_id TEXT NOT NULL,
        surum INTEGER NOT NULL,
        arastirma_id TEXT NOT NULL,
        olusturma_utc TEXT NOT NULL,
        metin TEXT NOT NULL,
        mac_kimligi TEXT,
        gorunum_kaynak TEXT,
        veri_ozeti TEXT,
        durum TEXT NOT NULL,
        UNIQUE (not_id, surum))""",
    *[f"CREATE TRIGGER IF NOT EXISTS {t}_degismez BEFORE UPDATE ON {t} BEGIN "
      f"SELECT RAISE(ABORT, 'Kayıt değiştirilemez; yeni sürüm eklenir'); END" for t in
      ("arastirma_revizyonlari", "calistirmalar", "calistirma_gruplari", "notlar", "meta")],
    *[f"CREATE TRIGGER IF NOT EXISTS {t}_silinmez BEFORE DELETE ON {t} BEGIN "
      f"SELECT RAISE(ABORT, 'Kayıt silinemez'); END" for t in
      ("arastirma_revizyonlari", "calistirmalar", "calistirma_gruplari", "notlar", "meta")],
)
TABLES = ("meta", "arastirma_revizyonlari", "calistirmalar", "calistirma_gruplari", "notlar")


class CalismaError(RuntimeError):
    """Çalışma alanı işlemi güvenli biçimde yapılamıyor (eksik/bozuk/kilitli dosya, eksik kayıt, arşiv sorunu)."""


class DogrulamaHatasi(CalismaError):
    """Tanım veya not doğrulanamadı (bilinmeyen alan, geçersiz değer, uzunluk sınırı)."""


class CakismaHatasi(CalismaError):
    """Eşzamanlı değişiklik: beklenen temel revizyon artık en son revizyon değil (sessiz üzerine yazma yok)."""


# ----------------------------------------------------------------------------
# Kanonik JSON ve özet
# ----------------------------------------------------------------------------

def _clean(o):
    """JSON'a güvenli değer: numpy/pandas türleri yerel türlere, NaN/Inf null'a; demetler listeye."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return f if math.isfinite(f) else None
    if o is None or o is pd.NaT or isinstance(o, str):
        return None if o is pd.NaT else o
    if isinstance(o, pd.Timestamp):
        return str(o.date()) if o == o.normalize() else o.isoformat()
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    return str(o)


def canon(o) -> str:
    """Sıralı anahtarlı, sonlu sayılı kanonik JSON (NaN/Infinity yazılmaz)."""
    return json.dumps(_clean(o), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def to_json(o, indent: int | None = 1) -> str:
    """Kullanıcıya gösterilen JSON: sonlu sayılar, null ve açık durumlar."""
    return json.dumps(_clean(o), ensure_ascii=False, sort_keys=False, indent=indent, allow_nan=False)


def _sha(o) -> str:
    return hashlib.sha256(canon(o).encode("utf-8")).hexdigest()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------------------------
# Tanım doğrulama (açık izin listesi)
# ----------------------------------------------------------------------------

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SEASON = re.compile(r"^(\d{4})(?:/(\d{2}))?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _text(name: str, v, limit: int, required: bool = False, strip: bool = False) -> str:
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise DogrulamaHatasi(f"{name}: metin olmalı")
    try:
        v.encode("utf-8")
    except UnicodeEncodeError as e:
        raise DogrulamaHatasi(f"{name}: geçerli UTF-8 metin değil") from e
    if _CTRL.search(v):
        raise DogrulamaHatasi(f"{name}: kontrol karakteri içeremez")
    if strip:
        v = v.strip()
    if required and not v.strip():
        raise DogrulamaHatasi(f"{name}: boş olamaz")
    if len(v) > limit:
        raise DogrulamaHatasi(f"{name}: en çok {limit} karakter olabilir ({len(v)})")
    return v


def _unknown(name: str, d: dict, allowed) -> None:
    extra = sorted(set(d) - set(allowed))
    if extra:
        raise DogrulamaHatasi(f"{name}: bilinmeyen alan(lar): {', '.join(extra)}; izinli alanlar: {', '.join(allowed)}")


def _season(v) -> str:
    s = _text("sezon", v, 7, required=True, strip=True)
    m = _SEASON.match(s)
    if not m or (m.group(2) is not None and (int(m.group(1)) + 1) % 100 != int(m.group(2))):
        raise DogrulamaHatasi(f"sezon: geçersiz değer '{s}' (ör. 2024/25 veya takvim yılı ligleri için 2024)")
    return s


def _date(name: str, v) -> str | None:
    if v in (None, ""):
        return None
    s = _text(name, v, 10, strip=True)
    try:
        if not _DATE.match(s):
            raise ValueError
        dt.date.fromisoformat(s)
    except ValueError as e:
        raise DogrulamaHatasi(f"{name}: tarih YYYY-AA-GG biçiminde olmalı ('{s}')") from e
    return s


def validate_group(g, name: str) -> dict:
    """Grup filtresi -> kanonik biçim (bütün anahtarlar; verilmeyenler null). Yalnızca izinli alanlar."""
    from .data.leagues import LEAGUES
    from .goals.markets import HTFT_KEYS

    if g is None:
        g = {}
    if not isinstance(g, dict):
        raise DogrulamaHatasi(f"{name}: alan-değer nesnesi olmalı")
    _unknown(name, g, GROUP_KEYS)
    out = {k: None for k in GROUP_KEYS}
    if g.get("lig") not in (None, ""):
        lig = _text(f"{name}.lig", g["lig"], 10, strip=True)
        if lig not in LEAGUES:
            raise DogrulamaHatasi(f"{name}.lig: bilinmeyen lig kodu '{lig}'")
        out["lig"] = lig
    if g.get("sezonlar") not in (None, [], ""):
        ss = g["sezonlar"]
        if isinstance(ss, str):
            ss = [ss]
        if not isinstance(ss, (list, tuple)):
            raise DogrulamaHatasi(f"{name}.sezonlar: sezon listesi olmalı")
        vals = sorted({_season(x) for x in ss})
        if len(vals) > LIMITS["sezon_sayisi"]:
            raise DogrulamaHatasi(f"{name}.sezonlar: en çok {LIMITS['sezon_sayisi']} sezon")
        out["sezonlar"] = vals
    if g.get("takim") not in (None, ""):
        out["takim"] = _text(f"{name}.takim", g["takim"], LIMITS["takim"], required=True, strip=True)
    if g.get("yer") not in (None, ""):
        if g["yer"] not in ("ev", "deplasman"):
            raise DogrulamaHatasi(f"{name}.yer: 'ev' veya 'deplasman' olmalı")
        if out["takim"] is None:
            raise DogrulamaHatasi(f"{name}.yer: yalnızca takım verildiğinde kullanılabilir")
        out["yer"] = g["yer"]
    out["bas"], out["son"] = _date(f"{name}.bas", g.get("bas")), _date(f"{name}.son", g.get("son"))
    if out["bas"] and out["son"] and out["bas"] > out["son"]:
        raise DogrulamaHatasi(f"{name}: başlangıç tarihi bitiş tarihinden sonra")
    sonuc = g.get("sonuc")
    if sonuc not in (None, {}):
        if not isinstance(sonuc, dict):
            raise DogrulamaHatasi(f"{name}.sonuc: alan-değer nesnesi olmalı")
        _unknown(f"{name}.sonuc", sonuc, OUTCOME_KEYS)
        res = {}
        for k in ("A", "B", "C"):
            if sonuc.get(k) is None:
                continue
            if sonuc[k] not in OUTCOME_VALUES:
                raise DogrulamaHatasi(f"{name}.sonuc.{k}: {', '.join(OUTCOME_VALUES)} değerlerinden biri olmalı")
            if sonuc[k] != "tumu":
                res[k] = sonuc[k]
        if sonuc.get("iy_ms") not in (None, []):
            codes = sonuc["iy_ms"]
            if isinstance(codes, str):
                codes = [codes]
            if not isinstance(codes, (list, tuple)) or any(c not in HTFT_KEYS for c in codes):
                raise DogrulamaHatasi(f"{name}.sonuc.iy_ms: merkezi kayıttaki kodlar olmalı ({', '.join(HTFT_KEYS)})")
            res["iy_ms"] = sorted(set(codes))
        out["sonuc"] = res or None
    return out


def validate_definition(d) -> dict:
    """Araştırma tanımı -> kanonik biçim (``TANIM_SURUMU``). Kaynak görünümü açıkça verilmelidir: tek kaynak
    (kısa ad veya kayıt anahtarı) ya da ``"birlesik"``."""
    if not isinstance(d, dict):
        raise DogrulamaHatasi("tanım: alan-değer nesnesi olmalı")
    _unknown("tanım", d, DEF_KEYS)
    if d.get("tanim_surumu") not in (None, TANIM_SURUMU):
        raise DogrulamaHatasi(f"tanım: desteklenmeyen tanım sürümü '{d.get('tanim_surumu')}' ({TANIM_SURUMU} bekleniyor)")
    if d.get("kaynak") in (None, ""):
        raise DogrulamaHatasi("kaynak: açıkça verilmeli — tek kaynak (openfootball, datasets, xgabora, hudl) veya "
                              "'birlesik'")
    try:
        key = A.resolve_source(d["kaynak"])
    except A.ArchiveError as e:
        raise DogrulamaHatasi(f"kaynak: {e}") from e
    pazarlar = d.get("pazarlar") or list(MARKETS)
    if isinstance(pazarlar, str):
        pazarlar = [p.strip() for p in pazarlar.split(",") if p.strip()]
    if not isinstance(pazarlar, (list, tuple)) or not pazarlar or any(p not in MARKETS for p in pazarlar):
        raise DogrulamaHatasi(f"pazarlar: {', '.join(MARKETS)} değerlerinden en az biri olmalı")
    etiketler = d.get("etiketler") or []
    if isinstance(etiketler, str):
        etiketler = [etiketler]
    if not isinstance(etiketler, (list, tuple)):
        raise DogrulamaHatasi("etiketler: metin listesi olmalı")
    tags = list(dict.fromkeys(_text("etiket", t, LIMITS["etiket"], required=True, strip=True) for t in etiketler))
    if len(tags) > LIMITS["etiket_sayisi"]:
        raise DogrulamaHatasi(f"etiketler: en çok {LIMITS['etiket_sayisi']} etiket")
    return {"tanim_surumu": TANIM_SURUMU,
            "baslik": _text("baslik", d.get("baslik"), LIMITS["baslik"], required=True, strip=True),
            "aciklama": _text("aciklama", d.get("aciklama"), LIMITS["aciklama"]),
            "gorunum": {"tur": A.VIEW_MERGED if key is None else A.VIEW_SINGLE, "kaynak": key},
            "grup_1": validate_group(d.get("grup_1"), "grup_1"),
            "grup_2": None if d.get("grup_2") is None else validate_group(d["grup_2"], "grup_2"),
            "pazarlar": [p for p in MARKETS if p in set(pazarlar)], "etiketler": tags}


def _definition_input(tanim: dict) -> dict:
    """Kanonik tanımı yeniden doğrulanabilir girdiye çevirir (revizyon için)."""
    g = tanim["gorunum"]
    return {"baslik": tanim["baslik"], "aciklama": tanim["aciklama"], "kaynak": g["kaynak"] or A.MERGED_VIEW,
            "grup_1": tanim["grup_1"], "grup_2": tanim["grup_2"], "pazarlar": tanim["pazarlar"],
            "etiketler": tanim["etiketler"]}


# ----------------------------------------------------------------------------
# Hesap (saf; depolama yok)
# ----------------------------------------------------------------------------

def _rows_digest(rows: pd.DataFrame) -> str:
    """Görünüm satırlarının içerik özeti (sıra bağımsız; iç blok numarası hariç bütün alanlar)."""
    cols = [c for c in A.ROW_COLUMNS if c != "blok"]
    keys = sorted(canon([rec[c] for c in cols]) for rec in rows.reindex(columns=cols).to_dict("records"))
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


def snapshot(archive: A.Archive, v: A.ArchiveView) -> dict:
    """Görünümün veri kimliği: kullanılan doğrulanmış blokların depo/commit/yol/dosya özeti/satır özeti/ayrıştırıcısı,
    doğrulanamayan bloklar ve görünüm satırlarının içerik özeti. Dosya yolu veya değiştirilme zamanı kimlik değildir."""
    in_view = ((lambda k: k == v.kaynak) if v.kaynak is not None
               else (lambda k: archive_allowed(str(k), "tarihsel_analiz")))
    rejected = {(r.get("kaynak"), r.get("yol"), r.get("blok")) for r in archive.rejected}
    blocks = [b for b in archive.blocks() if "satir_ozeti" in b and in_view(b.get("kaynak"))
              and (b.get("kaynak"), b.get("yol"), b.get("blok")) not in rejected]
    items = sorted([str(b.get(k)) for k in ("kaynak", "depo", "commit", "yol", "dosya_sha256", "satir_ozeti",
                                            "ayristirici")] for b in blocks)
    rej = sorted([str(r.get("kaynak")), str(r.get("yol")), str(r.get("neden"))] for r in archive.rejected
                 if in_view(r.get("kaynak")))
    rows_sha = _rows_digest(v.rows)
    core = {"arsiv_surumu": archive.catalog.get("arsiv"), "gorunum": v.kaynak or A.MERGED_VIEW, "bloklar": items,
            "dogrulanamayan": rej, "satir_ozeti": rows_sha}
    commits: dict = {}
    for b in blocks:
        commits.setdefault(b["kaynak"], set()).add(b.get("commit"))
    return {"veri_ozeti": _sha(core), "arsiv_surumu": archive.catalog.get("arsiv"), "satir_ozeti": rows_sha,
            "blok_sayisi": len(items), "dogrulanamayan_blok": len(rej), "analiz_kaynak_satiri": int(len(v.rows)),
            "kullanilan_kaynaklar": sorted(set(v.rows["kaynak"])) if len(v.rows) else [],
            "kaynak_commitleri": {k: sorted(str(c) for c in cs) for k, cs in sorted(commits.items())},
            "ayristiricilar": sorted({str(b.get("ayristirici")) for b in blocks if b.get("ayristirici")}),
            "not": HASH_NOTE}


def _git_head(base: Path) -> str | None:
    """Kaynak koddan çalışıyorsa git HEAD commit'i (yalnızca dosya okuma; alt süreç yok)."""
    try:
        for p in [base, *base.parents][:5]:
            g = p / ".git"
            if g.is_file():
                txt = g.read_text(encoding="utf-8").strip()
                if not txt.startswith("gitdir:"):
                    return None
                g = (p / txt.split(":", 1)[1].strip()).resolve()
            if not g.is_dir():
                continue
            head = (g / "HEAD").read_text(encoding="utf-8").strip()
            if re.fullmatch(r"[0-9a-f]{40}", head):
                return head
            if not head.startswith("ref:"):
                return None
            ref = head.split(":", 1)[1].strip()
            common = g
            if (g / "commondir").is_file():
                common = (g / (g / "commondir").read_text(encoding="utf-8").strip()).resolve()
            for root in (g, common):
                f = root / ref
                if f.is_file():
                    sha = f.read_text(encoding="utf-8").strip()
                    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None
            packed = common / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == ref and re.fullmatch(r"[0-9a-f]{40}", parts[0]):
                        return parts[0]
            return None
    except (OSError, UnicodeDecodeError):
        return None
    return None


def code_info() -> dict:
    """Kod sürümü: paket sürümü, (kaynaktan çalışıyorsa) git commit'i ve hesapta kullanılan modüllerin içerik özeti
    (satır sonları normalleştirilir; paketlenmiş uygulamada kaynak dosyalar yoksa null)."""
    from .data.teams import MATCHING_VERSION
    from .goals.markets import RULE_VERSION

    base = Path(__file__).resolve().parent
    h = hashlib.sha256()
    ok = True
    for f in _CODE_FILES:
        p = base / f
        if not p.is_file():
            ok = False
            break
        h.update(f.encode("utf-8") + b"\0" + p.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return {"paket_surumu": __version__, "git_commit": _git_head(base), "kod_ozeti": h.hexdigest() if ok else None,
            "tanim_surumu": TANIM_SURUMU, "analiz_surumu": ANALIZ_SURUMU, "arsiv_surumu": A.ARCHIVE_VERSION,
            "eslesme_surumu": MATCHING_VERSION, "pazar_kural_surumu": RULE_VERSION}


def _apply_outcome(lab: pd.DataFrame, sonuc: dict) -> pd.DataFrame:
    """Geçmiş sonuca göre inceleme filtresi: merkezi pazar etiketleri (A/B/C) ve İY/MS kodları üzerinde."""
    if lab.empty or not sonuc:
        return lab
    m = pd.Series(True, index=lab.index)
    for k in ("A", "B", "C"):
        want = sonuc.get(k)
        col = pd.to_numeric(lab[k], errors="coerce")
        if want == "gerceklesti":
            m &= col == 1.0
        elif want == "gerceklesmedi":
            m &= col == 0.0
        elif want == "bilinmiyor":
            m &= col.isna()
    if sonuc.get("iy_ms"):
        m &= lab["iy_ms"].isin(sonuc["iy_ms"])
    return lab[m]


def group_frame(archive: A.Archive, v: A.ArchiveView, g: dict) -> tuple[pd.DataFrame, list]:
    """Grup maç listesi: her sezon için ``archive.explore_view`` (liste ile aynı sorgu), sonra varsa sonuç filtresi.
    Döner: (pazar etiketli liste, sezon başına explore_view özetleri)."""
    labs, outs = [], []
    for s in (g.get("sezonlar") or [None]):
        lab, out = A.explore_view(archive, v, lig=g.get("lig"), sezon=s, takim=g.get("takim"), yer=g.get("yer"),
                                  bas=g.get("bas"), son=g.get("son"))
        labs.append(lab)
        outs.append(out)
    lab = labs[0] if len(labs) == 1 else pd.concat([x for x in labs if len(x)] or labs[:1], ignore_index=True)
    lab = _apply_outcome(lab, g.get("sonuc") or {})
    return lab.sort_values(["mac_kimligi"], kind="mergesort").reset_index(drop=True), outs


def group_result(archive: A.Archive, v: A.ArchiveView, g: dict, markets) -> tuple[dict, list]:
    """Bir grubun betimleyici sonucu (merkezi hesaplar) ve olay kimlikleri."""
    lab, outs = group_frame(archive, v, g)
    s = A.summary(lab)
    ids = sorted(set(lab["mac_kimligi"])) if len(lab) else []
    by_outcome = bool(g.get("sonuc"))
    conf = set(lab.loc[lab["durum"] == "CELISKI", "mac_kimligi"]) if len(lab) else set()
    kim = None if by_outcome else int(sum(o["kimlik_incelemesi_kaynak_satiri"] for o in outs))
    kim_unk = (None if by_outcome or not g.get("takim")
               else int(sum(o["kimlik_incelemesi_takima_indirgenemeyen"] or 0 for o in outs)))
    days = pd.to_datetime(lab["date"]) if len(lab) else pd.Series(dtype="datetime64[ns]")
    res = {"filtre": g, "olay_sayisi": len(ids), "olay_kumesi_ozeti": _sha(ids),
           "sezonlar": sorted({str(x) for x in lab["season"]}) if len(lab) else [],
           "tarih_araligi": [str(days.min().date()), str(days.max().date())] if len(lab) else None,
           "mac": s["mac"], "liste_satiri": s["liste_satiri"], "kaynak_satiri": s["kaynak_satiri"],
           "birlesik_gecerli": s["birlesik_gecerli"], "hedef_hesaplanmayan_satir": s["liste_satiri"] - s["birlesik_gecerli"],
           "ms_gecerli": s["ms_gecerli"], "iy_gecerli": s["iy_gecerli"], "iy_mantiksal_0_0": s["iy_mantiksal_0_0"],
           "celiskili": s["celiskili"],
           "celiski_kaynak_satiri": int(v.conflicts["mac_kimligi"].isin(conf).sum()) if len(v.conflicts) else 0,
           "incelemede": s["incelemede"], "incelemede_liste_satiri": s["incelemede_liste_satiri"],
           "kimlik_incelemesi_kaynak_satiri": kim, "kimlik_incelemesi_takima_indirgenemeyen": kim_unk,
           "alan_birlesimi_iceren_mac": s["alan_birlesimi_iceren_mac"],
           "dosya_duzeyi_karantina": {"toplam": int(sum(o["kaynak_karantinasi_kapsami"]["toplam"] for o in outs)),
                                      "not": A.QUARANTINE_NOTE},
           "pazarlar": {k: s["pazarlar"][k] for k in ("A", "B", "C") if k in markets},
           "iy_ms": {"gecerli": s["iy_ms_gecerli"], "dagilim": s["iy_ms"]} if "IYMS" in markets else None,
           "sonuca_gore_secildi": by_outcome, "aciklamalar": []}
    if by_outcome:
        res["aciklamalar"].append({"kod": SELECTED_BY_OUTCOME, "metin": OUTCOME_NOTE})
        res["aciklamalar"].append({"kod": "KIMLIK_INCELEMESI_SONUC_FILTRESINE_INDIRGENEMEZ",
                                   "metin": "Kimlik incelemesindeki kayıtların pazar sonucu bilinmediği için sonuç "
                                            "filtresine indirgenemez (null)."})
    for o in outs:
        if o.get("takim_gorunumde_yok"):
            res["aciklamalar"].append({"kod": "TAKIM_GORUNUMDE_YOK", "metin": o["takim_gorunumde_yok"]})
            break
    if not ids:
        res["aciklamalar"].append({"kod": "BOS_GRUP", "metin": "Grupta maç yok; oranlar hesaplanmadı (null)."})
    return res, ids


def compare(r1: dict, ids1: list, r2: dict, ids2: list, markets) -> dict:
    """İki grubun betimleyici karşılaştırması: oran farkı yüzde puan; ortak maçlar olay kimliğiyle."""
    from .goals.markets import HTFT_KEYS

    pz = {}
    for k in ("A", "B", "C"):
        if k not in markets:
            continue
        a, b = r1["pazarlar"][k], r2["pazarlar"][k]
        o1, o2 = a["gerceklesme_orani"], b["gerceklesme_orani"]
        pz[k] = {"ad": a["ad"], "oran_grup_1": o1, "oran_grup_2": o2, "gecerli_grup_1": a["gecerli"],
                 "gecerli_grup_2": b["gecerli"],
                 "fark_yuzde_puan": None if o1 is None or o2 is None else 100.0 * (o1 - o2)}
    iyms = None
    if "IYMS" in markets:
        n1, n2 = r1["iy_ms"]["gecerli"], r2["iy_ms"]["gecerli"]
        codes = {}
        for c in HTFT_KEYS:
            p1 = r1["iy_ms"]["dagilim"][c] / n1 if n1 else None
            p2 = r2["iy_ms"]["dagilim"][c] / n2 if n2 else None
            codes[c] = {"pay_grup_1": p1, "pay_grup_2": p2,
                        "fark_yuzde_puan": None if p1 is None or p2 is None else 100.0 * (p1 - p2)}
        iyms = {"gecerli_grup_1": n1, "gecerli_grup_2": n2, "kodlar": codes}
    s1, s2 = set(ids1), set(ids2)
    common = len(s1 & s2)
    return {"pazarlar": pz, "iy_ms": iyms,
            "ortusme": {"ortak": common, "yalniz_grup_1": len(s1 - s2), "yalniz_grup_2": len(s2 - s1),
                        "tam_ortusme": bool(s1) and s1 == s2, "bagimsiz_ornek_degil": common > 0,
                        "not": OVERLAP_NOTE if common else None},
            "birim": COMPARISON_NOTE, "istatistiksel_test": "YAPILMADI"}


def compute(archive: A.Archive, tanim: dict) -> dict:
    """Saf hesap: aynı arşiv yüklemesi ve aynı görünümden iki grup. Döner: tanım, görünüm, veri kimliği, sürümler,
    sonuç (+ ``sonuc_ozeti``) ve grup olay listeleri (``_olaylar``). Depolama yapmaz."""
    tanim = validate_definition(_definition_input(tanim)) if "gorunum" in tanim else validate_definition(tanim)
    v = A.view(archive, tanim["gorunum"]["kaynak"])
    snap = snapshot(archive, v)
    markets = tanim["pazarlar"]
    warnings = []
    if v.kapali:
        sonuc = {"durum": "KULLANIM_KAPSAMI_KAPALI", "statu": STATUS,
                 "metin": v.aciklama(), "grup_1": None, "grup_2": None, "karsilastirma": None, "uyarilar": []}
        events = {1: [], 2: []} if tanim["grup_2"] is not None else {1: []}
    else:
        r1, ids1 = group_result(archive, v, tanim["grup_1"], markets)
        r2, ids2 = (group_result(archive, v, tanim["grup_2"], markets) if tanim["grup_2"] is not None
                    else (None, None))
        comp = compare(r1, ids1, r2, ids2, markets) if r2 is not None else None
        if v.kaynak is None:
            warnings.append({"kod": "BIRLESTIRILMIS_GORUNUM", "metin": A.MERGED_NOTE})
        if any(r and r["sonuca_gore_secildi"] for r in (r1, r2)):
            warnings.append({"kod": SELECTED_BY_OUTCOME, "metin": OUTCOME_NOTE})
        if comp and comp["ortusme"]["ortak"]:
            warnings.append({"kod": "ORTUSEN_GRUPLAR", "metin": OVERLAP_NOTE})
        if snap["dogrulanamayan_blok"]:
            warnings.append({"kod": "DOGRULANAMAYAN_BLOK",
                             "metin": f"{snap['dogrulanamayan_blok']} blok köken doğrulamasından geçmedi; kullanılmadı."})
        sonuc = {"durum": "TAMAMLANDI", "statu": STATUS, "grup_1": r1, "grup_2": r2, "karsilastirma": comp,
                 "uyarilar": warnings}
        events = {1: ids1} if r2 is None else {1: ids1, 2: ids2}
    return {"statu": STATUS, "tanim": tanim,
            "gorunum": {"tur": v.tur, "kaynak": v.kaynak, "aciklama": v.aciklama(), "kullanim": A.USE_NOTE},
            "veri": snap, "surumler": code_info(), "sonuc": sonuc, "sonuc_ozeti": _sha(sonuc), "_olaylar": events}


# ----------------------------------------------------------------------------
# Çalışma alanı (SQLite; yalnızca eklemeli)
# ----------------------------------------------------------------------------

def workspace_home_path() -> Path:
    """Varsayılan çalışma alanı: uygulama klasörünün KARDEŞİ (``<uygulama>-Calisma``); ``BAHIS_TAHMIN_CALISMA`` ile
    değiştirilebilir."""
    env = os.environ.get("BAHIS_TAHMIN_CALISMA")
    if env:
        return Path(env)
    base = app_home_path()
    return base.with_name(base.name + "-Calisma")


def _check_location(path: Path, separate=()) -> Path:
    path = Path(path).expanduser().resolve()
    others = [("uygulama veri klasörü", app_home_path()), ("arşiv klasörü", A.archive_home_path())]
    others += [("verilen klasör", Path(x)) for x in separate if x not in (None, "")]
    for label, other in others:
        o = Path(other).expanduser().resolve()
        if path == o or o in path.parents or path in o.parents:
            raise CalismaError(f"Çalışma alanı {label} ile çakışıyor ({o}); ayrı bir klasör verin.")
    if path.exists() and not path.is_dir():
        raise CalismaError(f"{path} bir klasör değil.")
    return path


def _translate(e: sqlite3.Error, db: Path) -> CalismaError:
    msg = str(e).lower()
    if "locked" in msg or "busy" in msg:
        return CalismaError(f"Çalışma dosyası kilitli (başka bir işlem kullanıyor): {db}. Biraz sonra tekrar deneyin.")
    if "not a database" in msg or "malformed" in msg or "file is encrypted" in msg:
        return CalismaError(f"Çalışma dosyası bozuk veya SQLite dosyası değil: {db}. Dosya değiştirilmedi; üzerine "
                            "yazılmaz.")
    return CalismaError(f"Çalışma dosyası işlenemedi ({e}): {db}")


class CalismaAlani:
    """Çalışma alanı servisi (arayüzden bağımsız). ``ac`` salt okunur açar (oluşturmaz, yazmaz);
    ``olustur_veya_ac`` yazma için açar ve gerekirse oluşturur."""

    def __init__(self, folder: Path, conn: sqlite3.Connection, writable: bool):
        self.folder, self.conn, self.writable = folder, conn, writable
        self.db = folder / DB_NAME

    # ---------------------------------------------------------------- açma
    @classmethod
    def ac(cls, folder=None, timeout: float = 5.0) -> "CalismaAlani":
        folder = Path(folder if folder not in (None, "") else workspace_home_path()).expanduser().resolve()
        db = folder / DB_NAME
        if not db.is_file():
            raise CalismaError(f"Çalışma alanı yok: {db}. Önce bir araştırma oluşturun (calisma-olustur).")
        try:
            conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=timeout, isolation_level=None)
        except sqlite3.Error as e:
            raise _translate(e, db) from e
        self = cls(folder, conn, writable=False)
        self._check_schema()
        return self

    @classmethod
    def yazmak_icin_ac(cls, folder=None, timeout: float = 5.0, ayri=()) -> "CalismaAlani":
        """Var olan çalışma alanını yazmak için açar; yoksa OLUŞTURMAZ (hata)."""
        f = Path(folder if folder not in (None, "") else workspace_home_path()).expanduser().resolve()
        if not (f / DB_NAME).is_file():
            raise CalismaError(f"Çalışma alanı yok: {f / DB_NAME}. Önce bir araştırma oluşturun (calisma-olustur).")
        return cls.olustur_veya_ac(f, timeout, ayri)

    @classmethod
    def olustur_veya_ac(cls, folder=None, timeout: float = 5.0, ayri=()) -> "CalismaAlani":
        """Yazmak için açar; çalışma alanı yoksa oluşturur. ``ayri``: çalışma alanıyla çakışmaması gereken ek klasörler
        (ör. kullanılan arşiv klasörü). Var olan dosya bozuksa veya başka şemadaysa üzerine yazılmaz."""
        folder = _check_location(Path(folder if folder not in (None, "") else workspace_home_path()), ayri)
        folder.mkdir(parents=True, exist_ok=True)
        db = folder / DB_NAME
        try:
            with open(db, "xb"):  # yalnızca yoksa oluştur (var olan dosyaya dokunmaz)
                pass
        except FileExistsError:
            pass
        try:
            conn = sqlite3.connect(db, timeout=timeout, isolation_level=None)
        except sqlite3.Error as e:
            raise _translate(e, db) from e
        self = cls(folder, conn, writable=True)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            try:
                names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "meta" not in names:
                    if names - {"sqlite_sequence"}:
                        raise CalismaError(f"{db}: çalışma alanı olmayan bir SQLite dosyası (geçersiz şema); "
                                           "üzerine yazılmadı.")
                    for stmt in SCHEMA:
                        conn.execute(stmt)
                    conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)",
                                     [("uygulama", APP_TAG), ("sema_surumu", str(SCHEMA_VERSION)),
                                      ("olusturma_utc", _now())])
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.Error as e:
            conn.close()
            raise _translate(e, db) from e
        except CalismaError:
            conn.close()
            raise
        self._check_schema()
        return self

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _check_schema(self) -> None:
        try:
            names = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not set(TABLES) <= names:
                raise CalismaError(f"{self.db}: geçersiz çalışma alanı şeması (eksik tablo); dosya değiştirilmedi.")
            meta = dict(self.conn.execute("SELECT key, value FROM meta").fetchall())
        except sqlite3.Error as e:
            self.conn.close()
            raise _translate(e, self.db) from e
        if meta.get("uygulama") != APP_TAG:
            self.conn.close()
            raise CalismaError(f"{self.db}: bu bir Bahis Tahmin çalışma alanı dosyası değil; dosya değiştirilmedi.")
        if int(meta.get("sema_surumu", "0")) > SCHEMA_VERSION:
            self.conn.close()
            raise CalismaError(f"{self.db}: daha yeni bir uygulama sürümüyle oluşturulmuş (şema "
                               f"{meta.get('sema_surumu')}); bu sürüm açamaz.")

    @contextmanager
    def _tx(self):
        if not self.writable:
            raise CalismaError("Çalışma alanı salt okunur açıldı; yazma yapılamaz.")
        try:
            self.conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as e:
            raise _translate(e, self.db) from e
        try:
            yield
            self.conn.execute("COMMIT")
        except BaseException as e:
            self.conn.execute("ROLLBACK")
            if isinstance(e, sqlite3.Error):
                raise _translate(e, self.db) from e
            raise

    def _q(self, sql: str, args=()) -> list:
        try:
            return self.conn.execute(sql, args).fetchall()
        except sqlite3.Error as e:
            raise _translate(e, self.db) from e

    # ---------------------------------------------------------------- araştırmalar
    def _revision_row(self, arastirma_id: str, revizyon: int | None = None):
        if revizyon is None:
            rows = self._q("SELECT revizyon, olusturma_utc, tanim, tanim_ozeti, kayit_aninda_onceki_calistirma FROM "
                           "arastirma_revizyonlari WHERE arastirma_id=? ORDER BY revizyon DESC LIMIT 1", (arastirma_id,))
        else:
            rows = self._q("SELECT revizyon, olusturma_utc, tanim, tanim_ozeti, kayit_aninda_onceki_calistirma FROM "
                           "arastirma_revizyonlari WHERE arastirma_id=? AND revizyon=?", (arastirma_id, int(revizyon)))
        if not rows:
            raise CalismaError(f"Araştırma bulunamadı: {arastirma_id}" + (f" r{revizyon}" if revizyon else ""))
        rev, created, tanim, digest, runs = rows[0]
        return {"arastirma_id": arastirma_id, "revizyon": rev, "olusturma_utc": created, "tanim": json.loads(tanim),
                "tanim_ozeti": digest, "kayit_aninda_onceki_calistirma": runs, "kayit_turu": "KAYDEDILDI",
                "on_kayit_kaniti": "YOK", "aciklama": PREREG_NOTE}

    def arastirma_olustur(self, tanim: dict) -> dict:
        """Yeni araştırma (revizyon 1). Yazan işlem."""
        t = validate_definition(tanim)
        rid = "ar_" + uuid.uuid4().hex[:12]
        with self._tx():
            self.conn.execute("INSERT INTO arastirma_revizyonlari (arastirma_id, revizyon, olusturma_utc, tanim, "
                              "tanim_ozeti, kayit_aninda_onceki_calistirma) VALUES (?, 1, ?, ?, ?, 0)",
                              (rid, _now(), canon(t), _sha(t)))
        return self._revision_row(rid, 1)

    def arastirma_revize(self, arastirma_id: str, degisiklik: dict, temel_revizyon: int | None = None) -> dict:
        """Yeni revizyon: verilen alanlar en son revizyonun üzerine uygulanır (aynı işlem içinde okunur). Verilirse
        ``temel_revizyon`` en son revizyon olmalıdır; değilse ``CakismaHatasi`` (sessiz üzerine yazma yok). Eski
        revizyon ve çalıştırmaları değişmez. Yazan işlem."""
        if not isinstance(degisiklik, dict) or not degisiklik:
            raise DogrulamaHatasi("revizyon: en az bir değişen alan verilmeli")
        _unknown("revizyon", degisiklik, [k for k in DEF_KEYS if k != "tanim_surumu"])
        with self._tx():
            head = self._revision_row(arastirma_id)
            if temel_revizyon is not None and int(temel_revizyon) != head["revizyon"]:
                raise CakismaHatasi(f"{arastirma_id}: temel revizyon r{temel_revizyon} artık en son değil "
                                    f"(en son r{head['revizyon']}); değişiklik kaydedilmedi.")
            t = validate_definition({**_definition_input(head["tanim"]), **degisiklik})
            if _sha(t) == head["tanim_ozeti"]:
                raise DogrulamaHatasi("revizyon: tanım değişmedi; yeni revizyon oluşturulmadı")
            runs = self._q("SELECT COUNT(*) FROM calistirmalar WHERE arastirma_id=?", (arastirma_id,))[0][0]
            new = head["revizyon"] + 1
            self.conn.execute("INSERT INTO arastirma_revizyonlari (arastirma_id, revizyon, olusturma_utc, tanim, "
                              "tanim_ozeti, kayit_aninda_onceki_calistirma) VALUES (?, ?, ?, ?, ?, ?)",
                              (arastirma_id, new, _now(), canon(t), _sha(t), runs))
        return self._revision_row(arastirma_id, new)

    def arastirmalar(self) -> list[dict]:
        """Araştırma listesi (en son revizyon başlığıyla). Salt okunur."""
        rows = self._q("SELECT r.arastirma_id, r.revizyon, r.olusturma_utc, r.tanim FROM arastirma_revizyonlari r "
                       "JOIN (SELECT arastirma_id, MAX(revizyon) m FROM arastirma_revizyonlari GROUP BY arastirma_id) "
                       "h ON h.arastirma_id = r.arastirma_id AND h.m = r.revizyon ORDER BY r.seq")
        out = []
        for rid, rev, created, tanim in rows:
            t = json.loads(tanim)
            first = self._q("SELECT olusturma_utc FROM arastirma_revizyonlari WHERE arastirma_id=? AND revizyon=1",
                            (rid,))
            n_runs = self._q("SELECT COUNT(*) FROM calistirmalar WHERE arastirma_id=?", (rid,))[0][0]
            n_notes = self._q("SELECT COUNT(DISTINCT not_id) FROM notlar WHERE arastirma_id=?", (rid,))[0][0]
            out.append({"arastirma_id": rid, "baslik": t["baslik"], "son_revizyon": rev, "son_revizyon_utc": created,
                        "olusturma_utc": first[0][0] if first else created, "gorunum": t["gorunum"],
                        "etiketler": t["etiketler"], "calistirma": n_runs, "not": n_notes})
        return out

    def arastirma(self, arastirma_id: str, revizyon: int | None = None) -> dict:
        """Araştırma revizyonu + revizyon geçmişi, çalıştırma listesi (yalnızca kimlik/özet) ve notlar. Salt okunur."""
        rec = self._revision_row(arastirma_id, revizyon)
        revs = self._q("SELECT revizyon, olusturma_utc, tanim_ozeti, kayit_aninda_onceki_calistirma FROM "
                       "arastirma_revizyonlari WHERE arastirma_id=? ORDER BY revizyon", (arastirma_id,))
        rec["revizyonlar"] = [{"revizyon": a, "olusturma_utc": b, "tanim_ozeti": c,
                               "kayit_aninda_onceki_calistirma": d} for a, b, c, d in revs]
        rec["calistirmalar"] = self.calistirmalar(arastirma_id)
        rec["notlar"] = self.notlar(arastirma_id)
        return rec

    # ---------------------------------------------------------------- çalıştırma
    def calistir(self, archive: A.Archive, arastirma_id: str, revizyon: int | None = None) -> dict:
        """Araştırmayı aynı arşiv yüklemesi üzerinde hesaplar ve çalıştırma kaydını TEK işlemde ekler (yarım kayıt
        oluşmaz). Önceki çalıştırmaların veri sürümüyle karşılaştırma yazılır. Yazan işlem."""
        if not self.writable:
            raise CalismaError("Çalışma alanı salt okunur açıldı; çalıştırma kaydedilemez.")
        rev = self._revision_row(arastirma_id, revizyon)
        res = compute(archive, rev["tanim"])
        events = res.pop("_olaylar")
        run_id = "cr_" + uuid.uuid4().hex[:16]
        with self._tx():
            prev = self._q("SELECT veri_ozeti, calistirma_id FROM calistirmalar WHERE arastirma_id=? ORDER BY seq DESC "
                           "LIMIT 1", (arastirma_id,))
            if not prev:
                change = "ILK_CALISTIRMA"
            else:
                change = "AYNI" if prev[0][0] == res["veri"]["veri_ozeti"] else "DEGISTI"
            record = {"calistirma_id": run_id, "arastirma_id": arastirma_id, "revizyon": rev["revizyon"],
                      "calistirma_utc": _now(), **res,
                      "onceki_calistirmaya_gore_veri": {"durum": change,
                                                        "onceki_calistirma": prev[0][1] if prev else None,
                                                        "metin": ("Veri sürümü önceki çalıştırmadan farklı; önceki "
                                                                  "sonuç değiştirilmedi." if change == "DEGISTI"
                                                                  else None)}}
            self.conn.execute("INSERT INTO calistirmalar (calistirma_id, arastirma_id, revizyon, calistirma_utc, durum, "
                              "veri_ozeti, sonuc_ozeti, kayit) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                              (run_id, arastirma_id, rev["revizyon"], record["calistirma_utc"], res["sonuc"]["durum"],
                               res["veri"]["veri_ozeti"], res["sonuc_ozeti"], canon(record)))
            for grp, ids in sorted(events.items()):
                self._insert_group(run_id, grp, ids)
        return self.calistirma(run_id)

    def _insert_group(self, run_id: str, grp: int, ids: list) -> None:
        self.conn.execute("INSERT INTO calistirma_gruplari (calistirma_id, grup, olay_sayisi, olay_ozeti, olaylar) "
                          "VALUES (?, ?, ?, ?, ?)", (run_id, grp, len(ids), _sha(ids), canon(ids)))

    def calistirmalar(self, arastirma_id: str) -> list[dict]:
        rows = self._q("SELECT calistirma_id, revizyon, calistirma_utc, durum, veri_ozeti, sonuc_ozeti FROM calistirmalar "
                       "WHERE arastirma_id=? ORDER BY seq", (arastirma_id,))
        return [{"calistirma_id": a, "revizyon": b, "calistirma_utc": c, "durum": d, "veri_ozeti": e,
                 "sonuc_ozeti": f} for a, b, c, d, e, f in rows]

    def calistirma(self, calistirma_id: str, olaylar: bool = False) -> dict:
        """Saklı çalıştırma. GÜNCEL kullanım kapsamı uygulanır: kullanılan kaynaklardan biri artık tarihsel analize
        kapalıysa toplu sonuç ve olay listeleri gösterilmez. Salt okunur."""
        rows = self._q("SELECT kayit FROM calistirmalar WHERE calistirma_id=?", (calistirma_id,))
        if not rows:
            raise CalismaError(f"Çalıştırma bulunamadı: {calistirma_id}")
        rec = json.loads(rows[0][0])
        groups = self._q("SELECT grup, olay_sayisi, olay_ozeti, olaylar FROM calistirma_gruplari WHERE calistirma_id=? "
                         "ORDER BY grup", (calistirma_id,))
        rec["olay_kumeleri"] = {str(g): {"olay_sayisi": n, "olay_ozeti": h, **({"olaylar": json.loads(x)} if olaylar
                                                                                  else {})}
                                for g, n, h, x in groups}
        closed = self._closed_sources(rec)
        if closed:
            rec["sonuc"] = {"durum": "KULLANIM_KAPSAMI_KAPALI", "statu": STATUS, "kapali_kaynaklar": closed,
                            "metin": "Bu çalıştırmanın kullandığı kaynak(lar) şu anda tarihsel analize kapalı; saklı "
                                     "sonuç gösterilmez."}
            rec["olay_kumeleri"] = {g: {"olay_sayisi": None, "olay_ozeti": None} for g in rec["olay_kumeleri"]}
        return rec

    @staticmethod
    def _closed_sources(rec: dict) -> list:
        srcs = set(rec.get("veri", {}).get("kullanilan_kaynaklar") or [])
        if rec.get("gorunum", {}).get("kaynak"):
            srcs.add(rec["gorunum"]["kaynak"])
        return sorted(s for s in srcs if not archive_allowed(str(s), "tarihsel_analiz"))

    def dogrula(self, archive: A.Archive, calistirma_id: str) -> dict:
        """Saklı çalıştırmayı mevcut arşivle yeniden hesaplayıp karşılaştırır; YAZMAZ. Veri sürümü farklıysa eski veri
        yerine yeni veri kullanılmaz: sonuç 'yeniden hesaplanarak doğrulandı' sayılmaz."""
        rec = self.calistirma(calistirma_id)
        if rec["sonuc"].get("kapali_kaynaklar"):
            return {"calistirma_id": calistirma_id, "durum": "KULLANIM_KAPSAMI_KAPALI",
                    "kapali_kaynaklar": rec["sonuc"]["kapali_kaynaklar"], "yeniden_hesaplanarak_dogrulandi": False}
        cur = compute(archive, rec["tanim"])
        out = {"calistirma_id": calistirma_id, "sakli_veri_ozeti": rec["veri"]["veri_ozeti"],
               "guncel_veri_ozeti": cur["veri"]["veri_ozeti"], "sakli_sonuc_ozeti": rec["sonuc_ozeti"],
               "guncel_sonuc_ozeti": cur["sonuc_ozeti"]}
        if cur["veri"]["veri_ozeti"] != rec["veri"]["veri_ozeti"]:
            out.update({"durum": "VERI_SURUMU_DEGISTI", "yeniden_hesaplanarak_dogrulandi": False,
                        "metin": "Saklı çalıştırmanın veri sürümü mevcut arşivde yok; saklı sonuç okunabilir ama yeni "
                                 "veriyle yeniden hesaplanarak doğrulanamaz. Yeni veri eski verinin yerine kullanılmadı."})
        elif cur["sonuc_ozeti"] != rec["sonuc_ozeti"]:
            out.update({"durum": "SONUC_FARKLI", "yeniden_hesaplanarak_dogrulandi": False,
                        "metin": "Aynı veriyle hesap farklı sonuç verdi (kod/analiz sürümü değişmiş olabilir).",
                        "sakli_surumler": rec["surumler"], "guncel_surumler": cur["surumler"]})
        else:
            out.update({"durum": "DOGRULANDI", "yeniden_hesaplanarak_dogrulandi": True,
                        "metin": "Aynı veri sürümü ve tanımla yeniden hesaplanan sonuç saklı sonuçla aynı."})
        return out

    # ---------------------------------------------------------------- notlar
    def not_ekle(self, arastirma_id: str, metin: str, mac_kimligi: str | None = None,
                 archive: A.Archive | None = None, kaynak=None) -> dict:
        """Araştırmaya serbest metin notu; isteğe bağlı olarak arşivdeki bir maça (olay kimliği + görünüm) bağlanır.
        Maç, belirtilen görünümde (verilmezse araştırmanın görünümünde) yoksa not eklenmez. Yazan işlem."""
        if not self.writable:
            raise CalismaError("Çalışma alanı salt okunur açıldı; not eklenemez.")
        text = _text("not", metin, LIMITS["not"], required=True)
        head = self._revision_row(arastirma_id)
        link_view = link_hash = None
        if mac_kimligi not in (None, ""):
            if archive is None:
                raise CalismaError("Maça bağlı not için arşiv gerekli (--ev).")
            try:
                key = head["tanim"]["gorunum"]["kaynak"] if kaynak in (None, "") else A.resolve_source(kaynak)
            except A.ArchiveError as e:
                raise DogrulamaHatasi(f"kaynak: {e}") from e
            v = A.view(archive, key)
            if v.kapali or not len(v.merged) or mac_kimligi not in set(v.merged["mac_kimligi"]):
                raise CalismaError(f"Maç bu görünümde yok ({key or A.MERGED_VIEW}): {mac_kimligi}. Not eklenmedi; başka "
                                   "görünümün maçına bağlanmaz.")
            link_view = key or A.MERGED_VIEW
            link_hash = snapshot(archive, v)["veri_ozeti"]
        nid = "nt_" + uuid.uuid4().hex[:12]
        with self._tx():
            self.conn.execute("INSERT INTO notlar (not_id, surum, arastirma_id, olusturma_utc, metin, mac_kimligi, "
                              "gorunum_kaynak, veri_ozeti, durum) VALUES (?, 1, ?, ?, ?, ?, ?, ?, 'aktif')",
                              (nid, arastirma_id, _now(), text, mac_kimligi or None, link_view, link_hash))
        return self.not_oku(nid)

    def not_guncelle(self, not_id: str, metin: str | None = None, durum: str | None = None) -> dict:
        """Notun yeni sürümü (metin değişikliği veya arşivleme); önceki sürüm korunur. Fiziksel silme yoktur."""
        if not self.writable:
            raise CalismaError("Çalışma alanı salt okunur açıldı; not güncellenemez.")
        if metin is None and durum is None:
            raise DogrulamaHatasi("not: değişecek metin veya durum verilmeli")
        if durum is not None and durum not in NOTE_STATES:
            raise DogrulamaHatasi(f"not durumu: {', '.join(NOTE_STATES)} olmalı")
        text = None if metin is None else _text("not", metin, LIMITS["not"], required=True)
        with self._tx():
            cur = self._note_rows(not_id)[-1]
            self.conn.execute("INSERT INTO notlar (not_id, surum, arastirma_id, olusturma_utc, metin, mac_kimligi, "
                              "gorunum_kaynak, veri_ozeti, durum) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (not_id, cur["surum"] + 1, cur["arastirma_id"], _now(),
                               text if text is not None else cur["metin"], cur["mac_kimligi"], cur["gorunum_kaynak"],
                               cur["veri_ozeti"], durum or cur["durum"]))
        return self.not_oku(not_id)

    def _note_rows(self, not_id: str) -> list[dict]:
        rows = self._q("SELECT not_id, surum, arastirma_id, olusturma_utc, metin, mac_kimligi, gorunum_kaynak, "
                       "veri_ozeti, durum FROM notlar WHERE not_id=? ORDER BY surum", (not_id,))
        if not rows:
            raise CalismaError(f"Not bulunamadı: {not_id}")
        keys = ("not_id", "surum", "arastirma_id", "olusturma_utc", "metin", "mac_kimligi", "gorunum_kaynak",
                "veri_ozeti", "durum")
        return [dict(zip(keys, r)) for r in rows]

    def not_oku(self, not_id: str) -> dict:
        rows = self._note_rows(not_id)
        return {**rows[-1], "onceki_surumler": rows[:-1], "aciklama": NOTE_NOTE}

    def notlar(self, arastirma_id: str, arsivlenenler: bool = True) -> list[dict]:
        ids = [r[0] for r in self._q("SELECT not_id FROM notlar WHERE arastirma_id=? GROUP BY not_id ORDER BY MIN(seq)",
                                     (arastirma_id,))]
        out = [self.not_oku(i) for i in ids]
        return out if arsivlenenler else [n for n in out if n["durum"] == "aktif"]

    def not_karti(self, archive: A.Archive, not_id: str, takim: str) -> dict:
        """Maça bağlı notun olay kartı: mevcut ``archive.event_card_for`` ile, notun bağlandığı görünümde. Maç o görünümde
        artık yoksa kart üretilmez (başka görünüme geçilmez). Salt okunur."""
        n = self.not_oku(not_id)
        if not n["mac_kimligi"]:
            raise CalismaError(f"Not bir maça bağlı değil: {not_id}")
        v = A.view(archive, n["gorunum_kaynak"])
        try:
            card = A.event_card_for(archive, n["mac_kimligi"], takim, gorunum=v)
        except ValueError as e:  # ör. mevcut olay kartının belirsiz sıra kuralı
            raise CalismaError(f"Olay kartı oluşturulamadı: {e}") from e
        card["not"] = {"not_id": n["not_id"], "surum": n["surum"], "metin": n["metin"], "durum": n["durum"],
                       "baglanti_veri_ozeti": n["veri_ozeti"], "guncel_veri_ozeti": snapshot(archive, v)["veri_ozeti"],
                       "aciklama": NOTE_NOTE}
        return card

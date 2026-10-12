"""Araştırma Çalışma Alanı (S7-UI-01): kayıtlı araştırmalar, grup karşılaştırması ve çoklu olay matrisi.

Mevcut servislerin arayüzüdür; yeni hesap motoru yoktur:

* ``calisma.CalismaAlani``: araştırma oluşturma/revizyon, çalıştırma kaydı, saklı sonuç, doğrulama ve notlar;
* ``calisma.compute``: kaydetmeyen önizleme;
* ``olay_karsilastirma.olay_karsilastir``: bir takımın birden çok olayının önce/sonra matrisi;
* ``archive.load`` / ``archive.view`` / ``archive.explore_view``: salt okunur arşiv ve görünümler.

Kurallar:

* Sayfa açılınca ağ isteği, arşiv hazırlama, çalışma alanı oluşturma, kayıt veya eğitim yapılmaz. Arşiv ve çalışma
  alanı yalnızca düğmeyle açılır. Salt okunur açma ile yazma ayrıdır: "Yeni çalışma alanı oluştur", "Kaydet",
  "Yeni revizyon kaydet", "Çalıştır ve sonucu sakla" ve not düğmeleri yazan işlemlerdir.
* Bütün disk, arşiv ve hesap işleri ``AppController.run_job`` ile arka planda çalışır. Çalışma alanı (SQLite) her
  işte o iş parçacığında açılıp kapatılır; sayfa yalnızca yolları ve düz sözlükleri tutar. Form değerleri ana iş
  parçacığında okunup kopyalanır; arka plan işi arayüz nesnesine dokunmaz.
* Her okuma isteği bağlamını taşır (arşiv yüklemesi, görünüm, araştırma ve revizyon, takım, pencere). Sonuç
  geldiğinde bağlam değiştiyse eski sonuç gösterilmez. Tamamlanan yazma her zaman kayıtlara yansıtılır.
* Kullanıcı metni (başlık, not, takım, kaynak adı, hata) yalnızca düz metin olarak gösterilir; HTML yorumlanmaz.
* Bütün sonuçlar betimleyici geçmiş incelemedir (``DESCRIPTIVE_RESEARCH``): tahmin, olasılık, strateji veya bahis
  önerisi değildir.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path

import pandas as pd
import shiboken6
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ... import archive as A
from ... import calisma as C
from ... import olay_karsilastirma as O
from ...goals.markets import HTFT_KEYS, MARKETS, PRIMARY_YES, SHORT
from ...pilot import MARKER as PILOT_MARKER
from .. import theme
from ..widgets import DataFrameModel, make_table, section
from .base import Page

log = logging.getLogger(__name__)

PAGE_NOTE = "Geçmiş veri incelemesi; tahmin değildir."
MARKET_NAMES = {SHORT[k]: MARKETS[k].name_tr for k in PRIMARY_YES}
OUTCOME_CHOICES = (("Tümü", "tumu"), ("Gerçekleşti", "gerceklesti"), ("Gerçekleşmedi", "gerceklesmedi"),
                   ("Bilinmiyor", "bilinmiyor"))
SIDES = (("Ev + deplasman", None), ("Yalnızca ev", "ev"), ("Yalnızca deplasman", "deplasman"))
NO_DATA = "Veri yok"
DASH = "—"
VERIFY_TEXT = {
    "DOGRULANDI": "DOĞRULANDI — aynı veri sürümü ve tanımla yeniden hesaplanan sonuç saklı sonuçla aynı.",
    "VERI_SURUMU_DEGISTI": ("VERİ SÜRÜMÜ DEĞİŞTİ — saklı çalıştırmanın veri sürümü mevcut arşivde yok. Ekrandaki saklı "
                            "sonuç değiştirilmedi ve yeni veriyle yeniden hesaplanmadı; yeni veriyle sonuç için açıkça "
                            "yeni çalıştırma yapın."),
    "SONUC_FARKLI": ("SONUÇ FARKLI — aynı veriyle hesap farklı sonuç verdi (kod/analiz sürümü değişmiş olabilir). Saklı "
                     "sonuç değiştirilmedi."),
    "KULLANIM_KAPSAMI_KAPALI": ("KULLANIM KAPSAMI KAPALI — çalıştırmanın kullandığı kaynak şu anda tarihsel analize "
                                "kapalı; sonuç gösterilmez ve doğrulanmaz."),
}
STATE_SHORT = {
    "COMPLETE": "tam", "DATA_START": "veri başlangıcı", "COVERAGE_EXIT": "kapsam bitti", "GAP_GT_400D": "uzun boşluk",
    "RIGHT_CENSORED": "arşiv sonu", "INCOMPLETE_SEASON": "eksik sezon", "SEASON_SKIP": "sezon atlaması",
    "HT_MISSING": "İY skoru eksik", "POSSIBLE_AWARDED": "hükmen olabilir", "UST_TUR": "üst tur",
}
INVALID_LABELS = {**{k: v.rstrip(".") for k, v in O.INVALID_TEXT.items()},
                  "TAKIM_BU_MACTA_YOK_GRUPTA": "grupta seçilen takımın oynamadığı maç (sayıldı, tek tek listelenmez)"}
_FOCUS_STYLE = (f"QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus, "
                f"QTableView:focus, QListWidget:focus, QCheckBox:focus, QRadioButton:focus "
                f"{{ border: 1px solid {theme.ACCENT}; }}")


# ----------------------------------------------------------------------------
# Biçimlendirme (sayılar servisten gelir; burada yalnızca gösterim)
# ----------------------------------------------------------------------------

def fmt_rate(v) -> str:
    """Oran: payda sıfırsa (None) "Veri yok" — asla %0 değil."""
    return NO_DATA if v is None else f"%{100 * float(v):.1f}"


def fmt_pp(v) -> str:
    """Yüzde puan farkı (göreli yüzde değişim değil)."""
    return DASH if v is None else f"{float(v):+.1f} yp"


def fmt_n(v) -> str:
    return DASH if v is None else str(v)


def fmt_count(yes, valid) -> str:
    return DASH if valid is None else f"{yes} / {valid}"


def htft(code) -> str:
    return code.replace("HTFT_", "").replace("_", "/") if isinstance(code, str) else DASH


def raw_code(v) -> str | None:
    """Ham İY/MS kodu kısa biçimde (``HTFT_2_1`` → ``2/1``); yoksa None."""
    if not isinstance(v, str) or not v:
        return None
    return htft(v) if v.startswith("HTFT_") else v


def fmt_int(v) -> str:
    """Sayım: tam sayı olarak (eksikse —)."""
    try:
        return DASH if v is None or v != v else str(int(v))
    except (TypeError, ValueError):
        return str(v)


def label01(v) -> str:
    """Merkezi pazar etiketi: 1 evet, 0 hayır; eksik (None/NaN) bilinmiyor."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "bilinmiyor"
    return "evet" if f == 1.0 else "hayır" if f == 0.0 else "bilinmiyor"


def source_short(key) -> str:
    if key in (None, "", A.MERGED_VIEW):
        return "birleşik"
    return A.SOURCE_SHORT.get(key, str(key))


def short_hash(h) -> str:
    return str(h)[:12] if h else DASH


def group_text(g: dict | None) -> str:
    """Grup filtresinin düz metin özeti."""
    if g is None:
        return "yok"
    parts = [f"lig {g.get('lig') or 'tümü'}", f"sezon {', '.join(g.get('sezonlar') or []) or 'tümü'}",
             f"takım {g.get('takim') or 'tümü'}"]
    if g.get("yer"):
        parts.append(f"yalnızca {g['yer']}")
    if g.get("bas") or g.get("son"):
        parts.append(f"tarih {g.get('bas') or '…'} – {g.get('son') or '…'}")
    s = g.get("sonuc") or {}
    if s:
        sub = [f"{k}: {s[k]}" for k in ("A", "B", "C") if s.get(k)]
        if s.get("iy_ms"):
            sub.append("İY/MS " + ", ".join(htft(c) for c in s["iy_ms"]))
        parts.append("geçmiş sonuç filtresi (" + "; ".join(sub) + ")")
    return " · ".join(parts)


def definition_text(t: dict) -> str:
    g = t.get("gorunum") or {}
    return (f"Başlık: {t.get('baslik')}\nGörünüm: {source_short(g.get('kaynak'))}\nGrup 1: {group_text(t.get('grup_1'))}\n"
            f"Grup 2: {group_text(t.get('grup_2'))}\nPazarlar: {', '.join(t.get('pazarlar') or [])}\n"
            f"Etiketler: {', '.join(t.get('etiketler') or []) or '-'}")


def plain_label(text: str = "", kind: str | None = None, fill: bool = True) -> QLabel:
    """Düz metin etiketi (HTML yorumlanmaz). ``fill``: satırın genişliğini alır; boşluksuz uzun metin (ör. Windows
    klasör yolu) en küçük genişliği belirleyip sayfayı yatay taşırmaz."""
    lbl = QLabel(text)
    lbl.setTextFormat(Qt.PlainText)
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    if fill:
        lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    if kind:
        lbl.setObjectName(kind)
    return lbl


def _compact(tab: QWidget, keep=()) -> None:
    """Sekmedeki kısa tablolar boş alanla uzamaz; artan yükseklik sekmenin sonundaki esnemeye gider."""
    for v in tab.findChildren(QTableView):
        if v not in keep:
            v.setSizePolicy(v.sizePolicy().horizontalPolicy(), QSizePolicy.Preferred)
    tab.layout().addStretch(1)


def _set_kind(lbl: QLabel, kind: str) -> None:
    if lbl.objectName() != kind:
        lbl.setObjectName(kind)
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)


# ----------------------------------------------------------------------------
# Arka plan işleri: yalnızca düz veri alır ve döndürür (arayüz nesnesi yok). Beklenen hatalar sonuç olarak döner.
# ----------------------------------------------------------------------------

def _fail(e: Exception, kind: str | None = None) -> dict:
    if kind is None:
        kind = ("cakisma" if isinstance(e, C.CakismaHatasi) else "dogrulama" if isinstance(e, C.DogrulamaHatasi)
                else "hata")
    return {"ok": False, "kind": kind, "error": str(e)}


_EXPECTED = (C.CalismaError, A.ArchiveError, ValueError, OSError)


def _read_ws(path, fn):
    """Çalışma alanını BU iş parçacığında salt okunur açar, işi yapar ve kapatır."""
    ws = C.CalismaAlani.ac(path)
    try:
        return fn(ws)
    finally:
        ws.close()


def _write(path, ayri, fn, reload=None) -> dict:
    """Var olan çalışma alanını BU iş parçacığında yazmak için açar (oluşturmaz). Yazma tamamlanınca sonuç her zaman
    döner; sonraki yenileme okuması başarısız olsa bile yazma gizlenmez."""
    try:
        ws = C.CalismaAlani.yazmak_icin_ac(path, ayri=ayri)
    except _EXPECTED as e:
        return _fail(e)
    try:
        try:
            rec = fn(ws)
        except _EXPECTED as e:
            return _fail(e)
        out = {"ok": True, "yazildi": rec}
        if reload is not None:
            try:
                out.update(reload(ws, rec))
            except _EXPECTED as e:
                out["yenileme_hatasi"] = str(e)
        return out
    finally:
        ws.close()


def location_problem(p: Path) -> str | None:
    """Yeni çalışma alanı klasörü için ek güvenlik: arşiv/pilot klasörü (veya içi) olamaz; var olan klasör boş
    olmalıdır (başka verinin yanına veya üzerine kurulmaz)."""
    for q in [p, *p.parents]:
        for marker, label in ((A.MARKER, "arşiv"), (PILOT_MARKER, "pilot")):
            if (q / marker).is_file():
                return (f"Seçilen klasör bir {label} klasörü veya onun içinde ({q}); çalışma alanı ayrı bir klasörde "
                        "olmalı.")
    if p.exists():
        if not p.is_dir():
            return f"{p} bir klasör değil."
        if (p / C.DB_NAME).exists():
            return (f"Bu klasörde zaten bir çalışma alanı dosyası var ({p / C.DB_NAME}). Var olan alanı "
                    "'Çalışma alanını aç' ile açın; yeni alan oluşturma onun yerine geçmez.")
        if any(p.iterdir()):
            return f"Klasör boş değil ({p}); yeni çalışma alanı için boş veya henüz olmayan bir klasör seçin."
    return None


def job_open_archive(progress, *, path):
    progress(5, "Arşiv salt okunur açılıyor...")
    try:
        ar = A.load(path)
    except _EXPECTED as e:
        return _fail(e, "arsiv")
    views, info = {}, {}
    keys = [None, *A.SOURCE_KEYS]
    for i, key in enumerate(keys):
        progress(10 + int(85 * i / len(keys)), f"Görünüm hazırlanıyor: {source_short(key)}...")
        v = A.view(ar, key)
        views[key] = v
        m = v.merged
        info[key] = {"kapali": v.kapali, "aciklama": v.aciklama(), "mac": int(len(m)),
                     "ligler": sorted({str(x) for x in m["league"]}) if len(m) else [],
                     "sezonlar": sorted({str(x) for x in m["season"]}, reverse=True) if len(m) else [],
                     "takimlar": v.teams(), "veri": None if v.kapali else C.snapshot(ar, v)}
    cat = ar.catalog
    return {"ok": True, "archive": ar, "views": views, "info": info, "path": str(Path(path).expanduser().resolve()),
            "katalog": {"arsiv": cat.get("arsiv"), "olusturma_utc": cat.get("olusturma_utc"),
                        "bilgi_kesimi": cat.get("bilgi_kesimi")},
            "satir": int(len(ar.rows)), "dogrulanamayan": len(ar.rejected)}


def job_open_workspace(progress, *, path):
    progress(20, "Çalışma alanı salt okunur açılıyor...")
    try:
        return {"ok": True, **_read_ws(path, lambda ws: {"liste": ws.arastirmalar(), "klasor": str(ws.folder)})}
    except _EXPECTED as e:
        return _fail(e)


def job_create_workspace(progress, *, path, ayri):
    progress(20, "Yeni çalışma alanı oluşturuluyor...")
    p = Path(path).expanduser().resolve()
    problem = location_problem(p)
    if problem:
        return {"ok": False, "kind": "konum", "error": problem}
    try:
        ws = C.CalismaAlani.olustur_veya_ac(p, ayri=ayri)
    except _EXPECTED as e:
        return _fail(e)
    try:
        return {"ok": True, "liste": ws.arastirmalar(), "klasor": str(ws.folder)}
    finally:
        ws.close()


def job_load_research(progress, *, ws, rid):
    progress(20, "Araştırma okunuyor...")
    try:
        return {"ok": True, **_read_ws(ws, lambda w: {"kayit": w.arastirma(rid), "liste": w.arastirmalar()})}
    except _EXPECTED as e:
        return _fail(e)


def _reload_research(w, rec):
    rid = rec["arastirma_id"]
    return {"kayit": w.arastirma(rid), "liste": w.arastirmalar()}


def job_save_new(progress, *, ws, ayri, tanim):
    progress(30, "Araştırma kaydediliyor...")
    return _write(ws, ayri, lambda w: w.arastirma_olustur(tanim), _reload_research)


def job_revise(progress, *, ws, ayri, rid, degisiklik, temel):
    progress(30, "Yeni revizyon kaydediliyor...")
    return _write(ws, ayri, lambda w: w.arastirma_revize(rid, degisiklik, temel_revizyon=temel), _reload_research)


def job_preview(progress, *, archive, tanim):
    progress(20, "Önizleme hesaplanıyor (kaydedilmez)...")
    try:
        res = C.compute(archive, tanim)
    except _EXPECTED as e:
        return _fail(e)
    res["olay_sayilari"] = {str(k): len(v) for k, v in res.pop("_olaylar").items()}
    return {"ok": True, "sonuc": res}


def job_run(progress, *, ws, ayri, archive, rid, beklenen):
    progress(20, "Araştırma çalıştırılıyor ve sonuç saklanıyor...")

    def run(w):
        head = w.arastirma(rid)
        if head["revizyon"] != beklenen:  # araya başka revizyon girdiyse başka tanım sessizce kaydedilmez
            raise C.CakismaHatasi(f"Araştırmanın en son revizyonu r{head['revizyon']}, ekrandaki r{beklenen}. Çalıştırma "
                                  "yapılmadı; önce araştırmayı yeniden açın.")
        return w.calistir(archive, rid, revizyon=beklenen)

    return _write(ws, ayri, run, lambda w, rec: {"kayit": w.arastirma(rid), "liste": w.arastirmalar()})


def job_open_run(progress, *, ws, cid):
    progress(30, "Saklı sonuç okunuyor (yeniden hesaplanmaz)...")
    try:
        return {"ok": True, "kayit": _read_ws(ws, lambda w: w.calistirma(cid))}
    except _EXPECTED as e:
        return _fail(e)


def job_verify(progress, *, ws, archive, cid):
    progress(20, "Saklı sonuç mevcut arşivle doğrulanıyor (yazmaz)...")
    try:
        return {"ok": True, "dogrulama": _read_ws(ws, lambda w: w.dogrula(archive, cid))}
    except _EXPECTED as e:
        return _fail(e)


def job_stored_teams(progress, *, ws, cid, grup, views):
    progress(30, "Saklı grup olayları okunuyor...")
    try:
        rec = _read_ws(ws, lambda w: w.calistirma(cid, olaylar=True))
    except _EXPECTED as e:
        return _fail(e)
    key = rec["tanim"]["gorunum"]["kaynak"]
    out = {"ok": True, "kaynak": key, "takimlar": [], "ligler": [], "varsayilan": None,
           "kapali": rec["sonuc"].get("kapali_kaynaklar") or []}
    if out["kapali"]:
        return out
    kume = rec["olay_kumeleri"].get(str(grup))
    flt = rec["tanim"].get(f"grup_{grup}")
    if kume is None or flt is None:
        return {"ok": False, "kind": "dogrulama", "error": f"Bu çalıştırmada Grup {grup} yok."}
    ids = set(kume.get("olaylar") or [])
    v = views.get(key)
    if v is not None and len(v.merged):
        sub = v.merged[v.merged["mac_kimligi"].isin(ids)]
        out["takimlar"] = sorted(set(sub["home"]) | set(sub["away"]))
        out["ligler"] = sorted({str(x) for x in sub["league"]})
    out["varsayilan"] = flt.get("takim")
    out["olay_sayisi"] = len(ids)
    return out


def job_olay(progress, *, ws, archive, p):
    progress(20, "Çoklu olay karşılaştırması hesaplanıyor (salt okunur)...")
    common = {"lig": p["lig"], "once": p["once"], "sonra": p["sonra"], "limit": p["limit"], "offset": p["offset"]}
    try:
        if p["tur"] == "kayitli":
            res = _read_ws(ws, lambda w: O.olay_karsilastir(archive, p["takim"], alan=w, calistirma_id=p["cid"],
                                                             grup=p["grup"], **common))
        else:
            res = O.olay_karsilastir(archive, p["takim"], kaynak=p["kaynak"], olaylar=list(p["olaylar"]), **common)
    except _EXPECTED as e:
        return _fail(e)
    return {"ok": True, "sonuc": res}


def job_explicit_list(progress, *, archive, view, takim, sezon):
    progress(30, "Takımın maçları listeleniyor...")
    try:
        lab, _ = A.explore_view(archive, view, sezon=sezon, takim=takim)
    except _EXPECTED as e:
        return _fail(e)

    def score(h, a):
        return DASH if pd.isna(h) or pd.isna(a) else f"{int(h)}-{int(a)}"

    rows = [{"sec": "", "tarih": str(pd.Timestamp(r["date"]).date()), "lig": r["league"], "sezon": str(r["season"]),
             "ev": r["home"], "deplasman": r["away"], "iy": score(r["hthg"], r["htag"]),
             "ms": score(r["fthg"], r["ftag"]), "iy_ms": htft(r["iy_ms"]) if isinstance(r["iy_ms"], str) else DASH,
             "A": label01(r["A"]), "B": label01(r["B"]), "C": label01(r["C"]), "durum": r["durum"],
             "mac_kimligi": r["mac_kimligi"]}
            for _, r in lab.sort_values(["date", "mac_kimligi"], kind="mergesort").iterrows()]
    return {"ok": True, "satirlar": pd.DataFrame(rows, columns=PickModel.COLUMNS)}


def job_note_add(progress, *, ws, ayri, rid, metin, mac, archive, kaynak):
    progress(30, "Not ekleniyor...")
    return _write(ws, ayri, lambda w: w.not_ekle(rid, metin, mac_kimligi=mac, archive=archive if mac else None,
                                                 kaynak=kaynak if mac else None),
                  lambda w, rec: {"kayit": w.arastirma(rid), "liste": w.arastirmalar()})


def job_note_update(progress, *, ws, ayri, rid, nid, metin, durum):
    progress(30, "Notun yeni sürümü kaydediliyor...")
    return _write(ws, ayri, lambda w: w.not_guncelle(nid, metin=metin, durum=durum),
                  lambda w, rec: {"kayit": w.arastirma(rid), "liste": w.arastirmalar()})


def job_note_card(progress, *, ws, archive, nid, takim):
    progress(30, "Bağlı maçın olay kartı hazırlanıyor (salt okunur)...")
    try:
        return {"ok": True, "kart": _read_ws(ws, lambda w: w.not_karti(archive, nid, takim))}
    except _EXPECTED as e:
        return _fail(e)


# ----------------------------------------------------------------------------
# Tablo modelleri
# ----------------------------------------------------------------------------

class PickModel(DataFrameModel):
    """Açık olay listesi: seçim satır numarasıyla değil maç kimliğiyle tutulur (sıralama ve filtre seçimi değiştirmez)."""

    COLUMNS = ["sec", "tarih", "lig", "sezon", "ev", "deplasman", "iy", "ms", "iy_ms", "A", "B", "C", "durum",
               "mac_kimligi"]
    pickChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.checkable_col = "sec"
        self.picked: set[str] = set()
        self.headers = {"sec": "Seç", "tarih": "Tarih", "lig": "Lig", "sezon": "Sezon", "ev": "Ev sahibi",
                        "deplasman": "Deplasman", "iy": "İY", "ms": "MS", "iy_ms": "İY/MS (ham)", "A": "A", "B": "B",
                        "C": "C", "durum": "Durum", "mac_kimligi": "Maç kimliği"}

    def mac_id(self, row: int) -> str:
        return str(self._df.iat[row, self._df.columns.get_loc("mac_kimligi")])

    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and self._cols[index.column()] == "sec":
            if role == Qt.CheckStateRole:
                return Qt.Checked if self.mac_id(index.row()) in self.picked else Qt.Unchecked
            if role == Qt.DisplayRole:
                return ""
        return super().data(index, role)

    def setData(self, index, value, role=Qt.EditRole):
        if role == Qt.CheckStateRole and index.isValid() and self._cols[index.column()] == "sec":
            state = value if isinstance(value, Qt.CheckState) else Qt.CheckState(value)
            mid = self.mac_id(index.row())
            if state == Qt.Checked:
                self.picked.add(mid)
            else:
                self.picked.discard(mid)
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            self.pickChanged.emit()
            return True
        return False

    def clear_picked(self) -> None:
        self.picked = set()
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 0), [Qt.CheckStateRole])
        self.pickChanged.emit()


class MatrixModel(QAbstractTableModel):
    """Olay × konum matrisi (t−k … t0 … t+k). Hücre metni kısa; tam ayrıntı yan panelde. Eksik konum metinle yazılır."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.events: list = []
        self.columns: list = []

    def set_result(self, events: list, once: int, sonra: int) -> None:
        self.beginResetModel()
        self.events = list(events)
        self.columns = [f"t-{k}" for k in range(once, 0, -1)] + ["t0"] + [f"t+{k}" for k in range(1, sonra + 1)]
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self.events, self.columns = [], []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.events)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() or not self.columns else len(self.columns) + 1

    def cell(self, row: int, col: int):
        """(olay, konum sözlüğü) — konum sütunu değilse konum None."""
        e = self.events[row]
        if col == 0:
            return e, None
        key = self.columns[col - 1]
        return e, next((p for p in e["konumlar"] if p["konum"] == key), None)

    @staticmethod
    def cell_text(p: dict | None) -> str:
        if p is None:
            return ""
        if p["durum"] != "GOZLENDI":
            return f"KAYIT YOK · {STATE_SHORT.get(p.get('neden'), p.get('neden') or '?')}"
        day = p["tarih"][8:10] + "." + p["tarih"][5:7] + "." + p["tarih"][2:4]
        side = "E" if p["ev_sahibi"] else "D"
        mark = " · seçili olay" if p.get("secili_olay") and p["konum"] != "t0" else ""
        code = raw_code(p.get("iy_ms_ham")) or "İY/MS ?"
        flag = " · İY yok" if p.get("ilk_yari_skoru_yok") else ""
        return f"{day} · {p['rakip']} ({side}) · {code}{flag}{mark}"

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        e, p = self.cell(index.row(), index.column())
        t0 = index.column() > 0 and self.columns[index.column() - 1] == "t0"
        if role in (Qt.DisplayRole, Qt.AccessibleTextRole):
            if index.column() == 0:
                tp = e["takim_perspektifi"]
                return f"#{e['sira']} · {e['tarih']} · {'ev' if tp['ev_sahibi'] else 'deplasman'} · {e['sezon']}"
            return self.cell_text(p)
        if role == Qt.ToolTipRole and p is not None:
            return p.get("metin") or p.get("olay_kimligi")
        if role == Qt.BackgroundRole:
            if t0:
                return QBrush(QColor("#1f2a1f"))
            if p is not None and p["durum"] != "GOZLENDI":
                return QBrush(QColor("#2a2414"))
        if role == Qt.FontRole and t0:
            f = QFont()
            f.setBold(True)
            return f
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if section == 0:
                return "Olay"
            key = self.columns[section - 1]
            return "t0 (olay)" if key == "t0" else key.replace("-", "−")
        return None


def position_detail(e: dict, p: dict | None) -> str:
    """Seçili matris hücresinin tam ayrıntısı (düz metin)."""
    head = f"Olay #{e['sira']}: {e['olay_kimligi']} · {e['tarih']} · {e['lig']} {e['sezon']}"
    if p is None:
        tp = e["takim_perspektifi"]
        lines = [head, f"Takım perspektifi: {tp['yer']} · rakip {tp['rakip']} · ham İY/MS {raw_code(tp['iy_ms_ham']) or '?'} · "
                       f"takım İY/MS {tp['takim_iy'] or '?'}→{tp['takim_ms'] or '?'}"]
        for side in ("onceki", "sonraki"):
            w = e[side]
            lines.append(f"{'Önceki' if side == 'onceki' else 'Sonraki'} pencere ({w['pencere']}): {w['durum']} — "
                         f"{w['durum_aciklama']} · gözlenen {w['gozlenen_kayit']}/{w['istenen_konum']}, eksik konum "
                         f"{w['eksik_konum']}")
            for x in w.get("sonraki_kayit_yok") or []:
                lines.append(f"  Sonraki kayıt yok: {x['kod']} — {x['metin']}")
        lines.append(f"Kaynak: {e.get('kaynak')}")
        if e.get("alan_kokeni"):
            lines.append(f"Alan kökeni: {e['alan_kokeni']}")
        if e.get("baska_olayin_penceresinde"):
            lines.append(f"Bu olay {len(e['baska_olayin_penceresinde'])} başka seçili olayın penceresinde de var.")
        return "\n".join(lines)
    if p["durum"] != "GOZLENDI":
        return "\n".join([head, f"Konum {p['konum']}: KAYIT YOK (boş sonuç değildir)",
                          f"Neden: {p.get('neden')} — {p.get('metin')}"])
    lines = [head, f"Konum {p['konum']}: {p['olay_kimligi']}",
             f"Tarih {p['tarih']} · sezon {p['sezon']} · {p['yer']} · rakip {p['rakip']}"
             + (f" (kaynak adı: {p['rakip_kaynak_adi']})" if p.get("rakip_kaynak_adi") not in (None, p['rakip']) else ""),
             f"Ham İY/MS (ev sahibi-deplasman kodu): {raw_code(p['iy_ms_ham']) or 'bilinmiyor'}",
             f"Takım İY/MS: {p['takim_iy'] or '?'} → {p['takim_ms'] or '?'}"
             + (f" ({p['takim_iy_ms']})" if p.get("takim_iy_ms") else "")
             + " — ham kod ile takımın geri dönüşü aynı şey değildir",
             f"Takım skoru: İY {p['iy_skor_takim'] or 'yok'} · MS {p['ms_skor_takim'] or 'yok'}",
             f"Yarı golleri (atılan-yenilen): 1. yarı {fmt_n(p['ilk_yari_atilan'])}-{fmt_n(p['ilk_yari_yenilen'])} · "
             f"2. yarı {fmt_n(p['ikinci_yari_atilan'])}-{fmt_n(p['ikinci_yari_yenilen'])}",
             f"A ({MARKET_NAMES['A']}): {label01(p['A'])} · B ({MARKET_NAMES['B']}): {label01(p['B'])} · "
             f"C ({MARKET_NAMES['C']}): {label01(p['C'])}",
             f"Kaynak: {p['kaynak']}" + (f" · alan kökeni: {p['alan_kokeni']}" if p.get("alan_kokeni") else ""),
             f"Lig maçları arası gün: {fmt_n(p.get('lig_arasi_gun'))} · sezon tam: {'evet' if p['sezon_tam'] else 'hayır'}"
             f" · sezon atlaması: {'evet' if p['sezon_atlamasi'] else 'hayır'} · sıra: {p['sira_turu']}"]
    flags = [t for k, t in (("hukmen_olabilir", "hükmen olabilir (sonuç bilinmiyor sayılır)"),
                            ("ilk_yari_skoru_yok", "ilk yarı skoru yok (HT_MISSING)"), ("ust_tur", "üst tur maçı"))
             if p.get(k)]
    if flags:
        lines.append("İşaretler: " + "; ".join(flags))
    if p.get("secili_olay") and p["konum"] != "t0":
        lines.append("Bu maç seçili olaylardan biri (pencereler örtüşüyor).")
    if p.get("secim_filtresinde") is not None:
        lines.append(f"Grup filtresinde: {'evet' if p['secim_filtresinde'] else 'hayır'}")
    return "\n".join(lines)


def _frame(rows: list, cols: list) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=cols)


def market_frame(sonuc: dict) -> pd.DataFrame:
    """Pazar tablosu: değerler servisin grup sonucundan ve karşılaştırmasından; ham oranlar gizli sütunlarda."""
    g1, g2, comp = sonuc.get("grup_1"), sonuc.get("grup_2"), sonuc.get("karsilastirma")
    rows = []
    for k in ("A", "B", "C"):
        if g1 is None or k not in g1["pazarlar"]:
            continue
        a = g1["pazarlar"][k]
        row = {"pazar": f"{k} · {a['ad']}", "g1_sayi": fmt_count(a["evet"], a["gecerli"]),
               "g1_oran": fmt_rate(a["gerceklesme_orani"]), "g1_bilinmiyor": a["bilinmiyor"],
               "g2_sayi": DASH, "g2_oran": DASH, "g2_bilinmiyor": DASH, "fark": DASH, "not": "",
               "_k": k, "_g1_oran": a["gerceklesme_orani"], "_g1_evet": a["evet"], "_g1_gecerli": a["gecerli"],
               "_g2_oran": None, "_g2_evet": None, "_g2_gecerli": None, "_fark": None}
        notes = []
        if ((g1.get("filtre") or {}).get("sonuc") or {}).get(k):
            notes.append("Grup 1 bu pazara göre seçildi (oran seçimin sonucudur)")
        if g2 is not None:
            b = g2["pazarlar"][k]
            row.update({"g2_sayi": fmt_count(b["evet"], b["gecerli"]), "g2_oran": fmt_rate(b["gerceklesme_orani"]),
                        "g2_bilinmiyor": b["bilinmiyor"], "_g2_oran": b["gerceklesme_orani"], "_g2_evet": b["evet"],
                        "_g2_gecerli": b["gecerli"]})
            if comp is not None:
                d = comp["pazarlar"][k]["fark_yuzde_puan"]
                row.update({"fark": fmt_pp(d), "_fark": d})
            if ((g2.get("filtre") or {}).get("sonuc") or {}).get(k):
                notes.append("Grup 2 bu pazara göre seçildi")
        row["not"] = "; ".join(notes)
        rows.append(row)
    return _frame(rows, ["pazar", "g1_sayi", "g1_oran", "g1_bilinmiyor", "g2_sayi", "g2_oran", "g2_bilinmiyor", "fark",
                         "not", "_k", "_g1_oran", "_g1_evet", "_g1_gecerli", "_g2_oran", "_g2_evet", "_g2_gecerli",
                         "_fark"])


def htft_frame(sonuc: dict) -> pd.DataFrame:
    g1, g2, comp = sonuc.get("grup_1"), sonuc.get("grup_2"), sonuc.get("karsilastirma")
    if g1 is None or g1.get("iy_ms") is None:
        return _frame([], ["kod"])
    n1 = g1["iy_ms"]["gecerli"]
    n2 = g2["iy_ms"]["gecerli"] if g2 is not None else None
    rows = []
    for c in HTFT_KEYS:
        x1 = g1["iy_ms"]["dagilim"][c]
        p1 = x1 / n1 if n1 else None
        row = {"kod": htft(c), "g1_sayi": x1, "g1_pay": fmt_rate(p1), "g2_sayi": DASH, "g2_pay": DASH, "fark": DASH,
               "_kod": c, "_g1_pay": p1, "_g2_pay": None, "_fark": None}
        if g2 is not None:
            x2 = g2["iy_ms"]["dagilim"][c]
            p2 = x2 / n2 if n2 else None
            row.update({"g2_sayi": x2, "g2_pay": fmt_rate(p2), "_g2_pay": p2})
            if comp is not None and comp.get("iy_ms"):
                d = comp["iy_ms"]["kodlar"][c]["fark_yuzde_puan"]
                row.update({"fark": fmt_pp(d), "_fark": d})
        rows.append(row)
    return _frame(rows, ["kod", "g1_sayi", "g1_pay", "g2_sayi", "g2_pay", "fark", "_kod", "_g1_pay", "_g2_pay", "_fark"])


MARKET_HIDDEN = frozenset({"_k", "_g1_oran", "_g1_evet", "_g1_gecerli", "_g2_oran", "_g2_evet", "_g2_gecerli", "_fark"})
HTFT_HIDDEN = frozenset({"_kod", "_g1_pay", "_g2_pay", "_fark"})
QUALITY_ROWS = (("mac", "Benzersiz maç"), ("liste_satiri", "Liste satırı"), ("kaynak_satiri", "Kaynak satırı"),
                ("birlesik_gecerli", "Skoru doğrulanmış (geçerli) maç"), ("ms_gecerli", "MS geçerli"),
                ("iy_gecerli", "İY geçerli"), ("iy_mantiksal_0_0", "İY mantıksal 0-0 (işaretli)"),
                ("celiskili", "Çelişkili maç"), ("celiski_kaynak_satiri", "Çelişki kaynak satırı"),
                ("incelemede", "Tarih uyuşmazlığı (eşleşme)"),
                ("kimlik_incelemesi_kaynak_satiri", "Kimlik incelemesi kaynak satırı"),
                ("alan_birlesimi_iceren_mac", "Kaynaklar arası alan birleştirmesi içeren maç"))


def quality_frame(sonuc: dict) -> pd.DataFrame:
    g1, g2 = sonuc.get("grup_1"), sonuc.get("grup_2")
    rows = []
    for key, label in QUALITY_ROWS:
        rows.append({"olcu": label, "g1": fmt_n(g1.get(key)) if g1 else DASH,
                     "g2": fmt_n(g2.get(key)) if g2 else DASH})
    kar = [g.get("dosya_duzeyi_karantina", {}).get("toplam") if g else None for g in (g1, g2)]
    rows.append({"olcu": "Dosya düzeyi karantina (takım/tarihe indirgenemez)", "g1": fmt_n(kar[0]),
                 "g2": fmt_n(kar[1]) if g2 else DASH})
    return _frame(rows, ["olcu", "g1", "g2"])


def stats_row(label: str, s: dict | None) -> dict:
    if s is None:
        return {"blok": label}
    row = {"blok": label, "kayit": s["gozlenen_kayit"], "kullanilabilir": s["kullanilabilir_mac"],
           "bilinmeyen": s["sonucu_bilinmeyen_kayit"],
           "gbm": f"{s['takim_ms']['G']}-{s['takim_ms']['B']}-{s['takim_ms']['M']} (n={s['takim_ms']['gecerli']})"}
    for k in ("A", "B", "C"):
        m = s["pazarlar"][k]
        row[k] = f"{fmt_count(m['evet'], m['gecerli'])} ({fmt_rate(m['oran'])}; bilinmiyor {m['bilinmiyor']})"
    for key, name in (("gol", "gol"), ("ilk_yari_gol", "iy_gol"), ("ikinci_yari_gol", "iiy_gol")):
        g = s[key]
        row[name] = (NO_DATA if g["atilan"] is None else f"{g['atilan']}-{g['yenilen']} (n={g['gecerli_mac']})")
    return row


# ----------------------------------------------------------------------------
# Grup formu
# ----------------------------------------------------------------------------

class GroupForm(QWidget):
    """Bir grubun filtresi (lig, sezonlar, takım, ev/deplasman, tarih, geçmiş sonuç filtresi)."""

    changed = Signal()

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self._teams: list | None = None
        self._missing = ""
        lay = QGridLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setHorizontalSpacing(10)
        self.cb_league = QComboBox()
        self.cb_league.setAccessibleName(f"{name} lig")
        self.lst_seasons = QListWidget()
        self.lst_seasons.setObjectName("plain")
        self.lst_seasons.setAccessibleName(f"{name} sezonlar")
        self.lst_seasons.setMaximumHeight(110)
        self.lst_seasons.setMinimumWidth(120)
        self.cb_team = QComboBox()
        self.cb_team.setEditable(True)
        self.cb_team.setInsertPolicy(QComboBox.NoInsert)
        self.cb_team.setAccessibleName(f"{name} takım")
        self.cb_team.setMinimumWidth(180)
        self.cb_team.lineEdit().setPlaceholderText("Tümü (yazarak listede arayın)")
        comp = self.cb_team.completer()
        comp.setFilterMode(Qt.MatchContains)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setCompletionMode(QCompleter.PopupCompletion)
        self.cb_side = QComboBox()
        self.cb_side.setAccessibleName(f"{name} ev veya deplasman")
        for text, val in SIDES:
            self.cb_side.addItem(text, val)
        self.ed_from = QLineEdit()
        self.ed_from.setPlaceholderText("YYYY-AA-GG")
        self.ed_from.setAccessibleName(f"{name} başlangıç tarihi")
        self.ed_to = QLineEdit()
        self.ed_to.setPlaceholderText("YYYY-AA-GG")
        self.ed_to.setAccessibleName(f"{name} bitiş tarihi")
        self.cb_out = {}
        out_box = QGroupBox("Geçmiş sonuç filtresi (isteğe bağlı; seçilen grup sonuca göre işaretlenir)")
        ol = QGridLayout(out_box)
        for i, k in enumerate(("A", "B", "C")):
            cb = QComboBox()
            cb.setAccessibleName(f"{name} {k} sonuç filtresi")
            for text, val in OUTCOME_CHOICES:
                cb.addItem(text, val)
            cb.setToolTip(MARKET_NAMES[k])
            self.cb_out[k] = cb
            lbl = QLabel(f"{k}:")
            lbl.setBuddy(cb)
            lbl.setToolTip(MARKET_NAMES[k])
            ol.addWidget(lbl, 0, 2 * i)
            ol.addWidget(cb, 0, 2 * i + 1)
        ol.addWidget(plain_label("İY/MS ham kod (ev sahibi bakışı; takımın geri dönüşü değildir):", "muted"), 1, 0, 1, 6)
        self.chk_htft = {}
        hl = QGridLayout()
        for i, c in enumerate(HTFT_KEYS):
            chk = QCheckBox(htft(c))
            chk.setAccessibleName(f"{name} İY/MS {htft(c)}")
            self.chk_htft[c] = chk
            hl.addWidget(chk, i // 5, i % 5)
        ol.addLayout(hl, 2, 0, 1, 6)
        self.team_note = plain_label("", "muted")
        r = 0
        for text, w in (("Lig:", self.cb_league), ("Takım:", self.cb_team), ("Ev / deplasman:", self.cb_side),
                        ("Başlangıç tarihi:", self.ed_from), ("Bitiş tarihi:", self.ed_to)):
            lbl = QLabel(text)
            lbl.setBuddy(w)
            lay.addWidget(lbl, r, 0)
            lay.addWidget(w, r, 1)
            r += 1
        lay.addWidget(self.team_note, r, 0, 1, 2)
        sl = QLabel("Sezonlar (birden çok seçilebilir; boşsa tümü):")
        sl.setWordWrap(True)
        sl.setBuddy(self.lst_seasons)
        lay.addWidget(sl, 0, 2)
        lay.addWidget(self.lst_seasons, 1, 2, 4, 1)
        lay.addWidget(out_box, r + 1, 0, 1, 3)
        lay.setColumnStretch(1, 1)
        lay.setColumnStretch(2, 1)
        self.cb_league.currentIndexChanged.connect(self._emit)
        self.lst_seasons.itemChanged.connect(self._emit)
        self.cb_team.currentTextChanged.connect(self._team_changed)
        self.cb_side.currentIndexChanged.connect(self._emit)
        self.ed_from.textChanged.connect(self._emit)
        self.ed_to.textChanged.connect(self._emit)
        for cb in self.cb_out.values():
            cb.currentIndexChanged.connect(self._emit)
        for chk in self.chk_htft.values():
            chk.toggled.connect(self._emit)
        self._team_changed()

    def _emit(self, *a) -> None:
        self.changed.emit()

    def _team_changed(self, *a) -> None:
        self.cb_side.setEnabled(bool(self.cb_team.currentText().strip()))
        self._refresh_team_note()
        self.changed.emit()

    def _team_items(self) -> list:
        return [self.cb_team.itemText(i) for i in range(self.cb_team.count())]

    def team_error(self) -> str | None:
        t = self.cb_team.currentText().strip()
        if t and t not in self._team_items():
            return (f"{self.name}: takım listede yok ('{t}'). Yazdığınız metin yalnızca listede arar; benzer ad eşlemesi "
                    "yapılmaz — listeden seçin.")
        return None

    def _refresh_team_note(self) -> None:
        t = self.cb_team.currentText().strip()
        err = self.team_error()
        if err:
            self.team_note.setText(err)
        elif t and self._teams is not None and t not in self._teams:
            self.team_note.setText("Bu takım seçili görünümde yok; sessizce dönüştürülmedi. Görünümdeki adla seçin "
                                   "(tek kaynak görünümünde takım adları kaynağın kendi adlarıdır).")
        else:
            self.team_note.setText("")

    # ------------------------------------------------------------ seçenekler ve değer
    def set_options(self, leagues: list, seasons: list, teams: list | None) -> None:
        """Seçenekleri görünümden kurar; mevcut değerler korunur (görünümde yoksa açıkça işaretlenir)."""
        blockers = [self.cb_league, self.lst_seasons, self.cb_team]
        missing = " (görünümde yok)" if teams is not None else ""
        self._missing = missing
        for w in blockers:
            w.blockSignals(True)
        try:
            cur_league = self.cb_league.currentData()
            self.cb_league.clear()
            self.cb_league.addItem("Tümü", None)
            for lg in leagues:
                self.cb_league.addItem(lg, lg)
            if cur_league and cur_league not in leagues:
                self.cb_league.addItem(f"{cur_league}{missing}", cur_league)
            i = self.cb_league.findData(cur_league) if cur_league else 0
            self.cb_league.setCurrentIndex(max(i, 0))
            checked = self.seasons()
            self.lst_seasons.clear()
            for s in list(seasons) + [s for s in checked if s not in seasons]:
                it = QListWidgetItem(s if s in seasons else f"{s}{missing}")
                it.setData(Qt.UserRole, s)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if s in checked else Qt.Unchecked)
                self.lst_seasons.addItem(it)
            cur_team = self.cb_team.currentText().strip()
            self._teams = None if teams is None else list(teams)
            self.cb_team.clear()
            self.cb_team.addItem("")
            for t in (teams or []):
                self.cb_team.addItem(t)
            if cur_team and cur_team not in (teams or []):
                self.cb_team.addItem(cur_team)  # tanımdaki değer korunur; uyarı notta
            self.cb_team.setCurrentText(cur_team)
        finally:
            for w in blockers:
                w.blockSignals(False)
        self.cb_side.setEnabled(bool(self.cb_team.currentText().strip()))
        self._refresh_team_note()

    def seasons(self) -> list:
        out = []
        for i in range(self.lst_seasons.count()):
            it = self.lst_seasons.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def value(self) -> dict:
        team = self.cb_team.currentText().strip() or None
        sonuc = {k: cb.currentData() for k, cb in self.cb_out.items() if cb.currentData() != "tumu"}
        codes = [c for c, chk in self.chk_htft.items() if chk.isChecked()]
        if codes:
            sonuc["iy_ms"] = codes
        return {"lig": self.cb_league.currentData(), "sezonlar": self.seasons() or None, "takim": team,
                "yer": self.cb_side.currentData() if team else None,
                "bas": self.ed_from.text().strip() or None, "son": self.ed_to.text().strip() or None,
                "sonuc": sonuc or None}

    def set_value(self, g: dict | None) -> None:
        g = g or {}
        widgets = [self.cb_league, self.lst_seasons, self.cb_team, self.cb_side, self.ed_from, self.ed_to,
                   *self.cb_out.values(), *self.chk_htft.values()]
        for w in widgets:
            w.blockSignals(True)
        try:
            lg = g.get("lig")
            i = self.cb_league.findData(lg) if lg else 0
            if lg and i < 0:
                self.cb_league.addItem(f"{lg}{self._missing}", lg)
                i = self.cb_league.count() - 1
            self.cb_league.setCurrentIndex(max(i, 0))
            want = set(g.get("sezonlar") or [])
            have = set()
            for k in range(self.lst_seasons.count()):
                it = self.lst_seasons.item(k)
                s = it.data(Qt.UserRole)
                have.add(s)
                it.setCheckState(Qt.Checked if s in want else Qt.Unchecked)
            for s in sorted(want - have, reverse=True):
                it = QListWidgetItem(f"{s}{self._missing}")
                it.setData(Qt.UserRole, s)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked)
                self.lst_seasons.addItem(it)
            team = g.get("takim") or ""
            if team and team not in self._team_items():
                self.cb_team.addItem(team)
            self.cb_team.setCurrentText(team)
            j = self.cb_side.findData(g.get("yer"))
            self.cb_side.setCurrentIndex(max(j, 0))
            self.ed_from.setText(g.get("bas") or "")
            self.ed_to.setText(g.get("son") or "")
            s = g.get("sonuc") or {}
            for k, cb in self.cb_out.items():
                cb.setCurrentIndex(max(cb.findData(s.get(k) or "tumu"), 0))
            for c, chk in self.chk_htft.items():
                chk.setChecked(c in (s.get("iy_ms") or []))
        finally:
            for w in widgets:
                w.blockSignals(False)
        self.cb_side.setEnabled(bool(self.cb_team.currentText().strip()))
        self._refresh_team_note()


# ----------------------------------------------------------------------------
# Sayfa
# ----------------------------------------------------------------------------

class ResearchPage(Page):
    title = "Araştırma Çalışma Alanı"
    subtitle = ("Kayıtlı araştırmalar, iki grubun betimleyici karşılaştırması, çalıştırma geçmişi, notlar ve bir takımın "
                "birden çok olayının önce/sonra matrisi. " + PAGE_NOTE + " Olasılık, strateji başarısı veya bahis "
                "önerisi üretilmez.")

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.setStyleSheet(_FOCUS_STYLE)
        # Durum: yalnızca yollar, düz sözlükler ve salt okunur arşiv nesneleri (SQLite bağlantısı tutulmaz)
        self.archive = None
        self.views: dict = {}
        self.info: dict = {}
        self.archive_meta: dict = {}
        self.archive_path: str | None = None
        self.archive_gen = 0
        self.ws_path: str | None = None
        self.ws_gen = 0
        self._ws_created = False
        self.research_list: list = []
        self.rid: str | None = None
        self.rev: int | None = None
        self.rec: dict | None = None
        self._base: dict | None = None  # kaydedilmiş/yüklenmiş form (kirli değişiklik denetimi)
        self._after_save = None
        self._saving = False
        self._token = 0
        self._latest: dict = {}
        self.group_shown: dict | None = None  # {"tur": "onizleme"/"sakli", "sonuc": ..., "kayit": ...}
        self.olay_shown: dict | None = None  # {"p": istek, "sonuc": ...}
        self.link_match: tuple | None = None  # (maç kimliği, görünüm anahtarı veya None)
        self.card: dict | None = None
        self._build()
        self.ctl.busyChanged.connect(self._update_actions)
        self._new_draft_form()
        self._update_actions()

    # ================================================================== yerleşim
    def _build(self) -> None:
        b = self.body
        b.addWidget(plain_label(PAGE_NOTE + " Sonuçlar betimleyicidir (DESCRIPTIVE_RESEARCH).", "banner"))
        ctx = QGroupBox("Arşiv ve çalışma alanı (ayrı kavramlar)")
        g = QGridLayout(ctx)
        g.setHorizontalSpacing(8)
        self.ed_archive = QLineEdit(self._default_archive())
        self.ed_archive.setAccessibleName("Arşiv klasörü")
        btn_arch_browse = QPushButton("Gözat…")
        btn_arch_browse.setAccessibleName("Arşiv klasörünü seç")
        btn_arch_browse.clicked.connect(lambda: self._browse(self.ed_archive))
        self.btn_open_archive = QPushButton("Arşivi aç")
        self.btn_open_archive.setToolTip("Arşiv klasörünü salt okunur açar; indirme veya hazırlama yapmaz.")
        self.btn_open_archive.clicked.connect(self.open_archive)
        lbl = QLabel("Arşiv klasörü:")
        lbl.setBuddy(self.ed_archive)
        g.addWidget(lbl, 0, 0)
        g.addWidget(self.ed_archive, 0, 1)
        g.addWidget(btn_arch_browse, 0, 2)
        g.addWidget(self.btn_open_archive, 0, 3)
        self.lbl_archive = plain_label("Arşiv açılmadı.", "muted")
        g.addWidget(self.lbl_archive, 1, 0, 1, 4)
        self.btn_goto_data = QPushButton("Veri sayfasına git")
        self.btn_goto_data.setToolTip("Arşiv 'Veri' sayfasındaki 'GitHub Veri ve Arşiv' bölümünden hazırlanır.")
        self.btn_goto_data.clicked.connect(self._goto_data)
        self.btn_goto_data.hide()
        g.addWidget(self.btn_goto_data, 2, 3)
        self.ed_ws = QLineEdit(self._default_ws())
        self.ed_ws.setAccessibleName("Çalışma alanı klasörü")
        btn_ws_browse = QPushButton("Gözat…")
        btn_ws_browse.setAccessibleName("Çalışma alanı klasörünü seç")
        btn_ws_browse.clicked.connect(lambda: self._browse(self.ed_ws))
        lbl = QLabel("Çalışma alanı:")
        lbl.setBuddy(self.ed_ws)
        g.addWidget(lbl, 3, 0)
        g.addWidget(self.ed_ws, 3, 1)
        g.addWidget(btn_ws_browse, 3, 2)
        self.btn_open_ws = QPushButton("Çalışma alanını aç")
        self.btn_open_ws.setToolTip("Yalnızca var olan çalışma alanını salt okunur açar; yoksa oluşturmaz.")
        self.btn_open_ws.clicked.connect(self.open_workspace)
        g.addWidget(self.btn_open_ws, 3, 3)
        self.btn_create_ws = QPushButton("Yeni çalışma alanı oluştur")
        self.btn_create_ws.setToolTip("Yazan işlem: boş veya henüz olmayan klasörde yeni çalışma alanı dosyası oluşturur.")
        self.btn_create_ws.clicked.connect(self.create_workspace)
        g.addWidget(self.btn_create_ws, 4, 3)
        self.lbl_ws = plain_label("Çalışma alanı açılmadı.", "muted")
        g.addWidget(self.lbl_ws, 4, 0, 1, 3)
        self.cb_source = QComboBox()
        self.cb_source.setAccessibleName("Kaynak görünümü")
        self.cb_source.setToolTip("Araştırma tanımının görünümü: birleştirilmiş görünüm tek kaynak değildir; tek kaynak "
                                  "seçilirse yalnızca o kaynağın kayıtları kullanılır.")
        self.cb_source.addItem("Birleştirilmiş görünüm (tek kaynak değil)", A.MERGED_VIEW)
        for key in A.SOURCE_KEYS:
            closed = "" if C.archive_allowed(key, "tarihsel_analiz") else " — tarihsel analiz kapalı"
            self.cb_source.addItem(f"Yalnızca {source_short(key)}{closed}", key)
        self.cb_source.currentIndexChanged.connect(self._source_changed)
        lbl = QLabel("Kaynak görünümü:")
        lbl.setBuddy(self.cb_source)
        g.addWidget(lbl, 5, 0)
        g.addWidget(self.cb_source, 5, 1, 1, 3)
        self.lbl_data = plain_label("Veri sürümü: arşiv açılmadı.", "muted")
        g.addWidget(self.lbl_data, 6, 0, 1, 4)
        g.setColumnStretch(1, 1)
        b.addWidget(ctx)
        self.msg = plain_label("", "muted")
        self.msg.hide()
        b.addWidget(self.msg)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(False)
        self.tabs.addTab(self._build_tab_research(), "A · Araştırmalar ve tanım")
        self.tabs.addTab(self._build_tab_groups(), "B · Grup karşılaştırması")
        self.tabs.addTab(self._build_tab_events(), "C · Olay karşılaştırması")
        self.tabs.addTab(self._build_tab_notes(), "D · Notlar ve geçmiş")
        b.addWidget(self.tabs)
        b.addStretch(1)

    def _build_tab_research(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(section("Araştırmalar"))
        self.list_state = plain_label("Çalışma alanı açılmadı. Var olan alanı açın veya yeni bir alan oluşturun.",
                                      "muted")
        lay.addWidget(self.list_state)
        self.list_model = DataFrameModel()
        self.list_model.headers = {"baslik": "Başlık", "son_revizyon": "Son revizyon", "gorunum": "Görünüm",
                                   "calistirma": "Çalıştırma", "not": "Not", "olusturma_utc": "Oluşturma (UTC)"}
        self.list_model.hidden = {"arastirma_id"}
        self.list_view, self.list_proxy = make_table(self.list_model)
        self.list_view.setAccessibleName("Araştırma listesi")
        self.list_view.setMinimumHeight(150)
        self.list_view.doubleClicked.connect(lambda *_: self.open_selected_research())
        lay.addWidget(self.list_view)
        self.btn_new = QPushButton("Yeni araştırma")
        self.btn_new.setToolTip("Bellekte yeni bir taslak açar; 'Kaydet' ile kaydedilir.")
        self.btn_new.clicked.connect(self.new_research)
        self.btn_open_research = QPushButton("Seçili araştırmayı aç")
        self.btn_open_research.clicked.connect(self.open_selected_research)
        row = QHBoxLayout()
        row.addWidget(self.btn_new)
        row.addWidget(self.btn_open_research)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(section("Tanım (calisma-tanim-v1)"))
        self.lbl_draft = plain_label("", "muted")
        lay.addWidget(self.lbl_draft)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.ed_title = QLineEdit()
        self.ed_title.setMaxLength(C.LIMITS["baslik"])
        self.ed_title.setAccessibleName("Başlık")
        self.ed_desc = QPlainTextEdit()
        self.ed_desc.setAccessibleName("Açıklama")
        self.ed_desc.setMaximumHeight(70)
        self.ed_desc.setTabChangesFocus(True)
        self.ed_tags = QLineEdit()
        self.ed_tags.setPlaceholderText("virgülle ayırın")
        self.ed_tags.setAccessibleName("Etiketler")
        self.lbl_form_source = plain_label("", "muted")
        mk = QHBoxLayout()
        self.chk_markets = {}
        for k in C.MARKETS:
            chk = QCheckBox(k if k != "IYMS" else "İY/MS")
            chk.setToolTip(MARKET_NAMES.get(k, "İY/MS dağılımı (9 merkezi kod)"))
            chk.setChecked(True)
            chk.toggled.connect(self._form_changed)
            self.chk_markets[k] = chk
            mk.addWidget(chk)
        mk.addStretch(1)
        form.addRow("Başlık:", self.ed_title)
        form.addRow("Açıklama:", self.ed_desc)
        form.addRow("Etiketler:", self.ed_tags)
        form.addRow("Kaynak görünümü:", self.lbl_form_source)
        form.addRow("Pazarlar:", mk)
        lay.addLayout(form)
        self.group_tabs = QTabWidget()
        self.g1 = GroupForm("Grup 1")
        self.g2 = GroupForm("Grup 2")
        g2w = QWidget()
        g2l = QVBoxLayout(g2w)
        g2l.setContentsMargins(0, 0, 0, 0)
        self.chk_g2 = QCheckBox("Grup 2'yi kullan (karşılaştırma)")
        self.chk_g2.toggled.connect(self._g2_toggled)
        g2l.addWidget(self.chk_g2)
        g2l.addWidget(self.g2)
        self.group_tabs.addTab(self.g1, "Grup 1")
        self.group_tabs.addTab(g2w, "Grup 2 (isteğe bağlı)")
        lay.addWidget(self.group_tabs)
        self.lbl_form_error = plain_label("", "warn")
        self.lbl_form_error.hide()
        lay.addWidget(self.lbl_form_error)
        self.btn_save = QPushButton("Kaydet")
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(lambda: self.save())  # clicked(bool) 'after' parametresine geçmesin
        self.btn_discard = QPushButton("Değişiklikleri bırak")
        self.btn_discard.clicked.connect(self.discard_changes)
        self.btn_preview = QPushButton("Önizle (kaydetmez)")
        self.btn_preview.setToolTip("Formdaki tanımı mevcut arşivle hesaplar; hiçbir şey yazmaz.")
        self.btn_preview.clicked.connect(self.preview)
        self.btn_run = QPushButton("Çalıştır ve sonucu sakla")
        self.btn_run.setToolTip("Kayıtlı revizyonu çalıştırır ve çalıştırma kaydı ekler (yazan işlem).")
        self.btn_run.clicked.connect(self.run_saved)
        row = QHBoxLayout()
        for x in (self.btn_save, self.btn_discard, self.btn_preview, self.btn_run):
            row.addWidget(x)
        row.addStretch(1)
        lay.addLayout(row)
        for sig in (self.ed_title.textChanged, self.ed_desc.textChanged, self.ed_tags.textChanged, self.g1.changed,
                    self.g2.changed):
            sig.connect(self._form_changed)
        return w

    def _build_tab_groups(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.cb_run_b = QComboBox()
        self.cb_run_b.setAccessibleName("Saklı çalıştırma (grup karşılaştırması)")
        self.cb_run_b.setMinimumWidth(240)
        self.btn_open_run = QPushButton("Saklı sonucu aç")
        self.btn_open_run.setToolTip("Saklı sonucu okur; yeniden hesaplamaz.")
        self.btn_open_run.clicked.connect(lambda: self.open_run(self.cb_run_b.currentData()))
        self.btn_verify = QPushButton("Mevcut arşivle doğrula")
        self.btn_verify.setToolTip("Salt okunur: saklı sonucu mevcut arşivle yeniden hesaplayıp karşılaştırır; yazmaz.")
        self.btn_verify.clicked.connect(lambda: self.verify())
        lbl = QLabel("Saklı çalıştırma:")
        lbl.setBuddy(self.cb_run_b)
        row.addWidget(lbl)
        row.addWidget(self.cb_run_b, 1)
        row.addWidget(self.btn_open_run)
        row.addWidget(self.btn_verify)
        lay.addLayout(row)
        self.lbl_group_state = plain_label("Henüz sonuç yok: 'Önizle (kaydetmez)' veya 'Saklı sonucu aç'.", "muted")
        lay.addWidget(self.lbl_group_state)
        self.lbl_group_head = plain_label("", None)
        lay.addWidget(self.lbl_group_head)
        self.lbl_verify = plain_label("", "muted")
        self.lbl_verify.hide()
        lay.addWidget(self.lbl_verify)
        lay.addWidget(section("Pazarlar (Grup 1 / Grup 2)"))
        self.market_model = DataFrameModel()
        self.market_model.headers = {"pazar": "Pazar", "g1_sayi": "Grup 1 gerçekleşen / geçerli", "g1_oran": "Grup 1 oran",
                                     "g1_bilinmiyor": "Grup 1 bilinmiyor", "g2_sayi": "Grup 2 gerçekleşen / geçerli",
                                     "g2_oran": "Grup 2 oran", "g2_bilinmiyor": "Grup 2 bilinmiyor",
                                     "fark": "Fark (yüzde puan)", "not": "Not"}
        self.market_model.hidden = set(MARKET_HIDDEN)
        self.market_model.tooltips = {
            "g1_oran": lambda v, r: f"Kesin değer: {r['_g1_oran']!r}",
            "g2_oran": lambda v, r: f"Kesin değer: {r['_g2_oran']!r}",
            "fark": lambda v, r: f"Kesin değer (yüzde puan): {r['_fark']!r}. Göreli yüzde değişim değildir."}
        self.market_view, _ = make_table(self.market_model, sortable=False)
        self.market_view.setAccessibleName("Pazar karşılaştırma tablosu")
        self.market_view.setMinimumHeight(130)
        lay.addWidget(self.market_view)
        self.lbl_overlap = plain_label("", None)
        lay.addWidget(self.lbl_overlap)
        lay.addWidget(section("İY/MS dağılımı (ham kod, ev sahibi bakışı)"))
        self.lbl_htft_n = plain_label("", "muted")
        lay.addWidget(self.lbl_htft_n)
        self.htft_model = DataFrameModel()
        self.htft_model.headers = {"kod": "İY/MS (ham)", "g1_sayi": "Grup 1 sayı", "g1_pay": "Grup 1 pay",
                                   "g2_sayi": "Grup 2 sayı", "g2_pay": "Grup 2 pay", "fark": "Fark (yüzde puan)"}
        self.htft_model.hidden = set(HTFT_HIDDEN)
        self.htft_view, _ = make_table(self.htft_model, sortable=False)
        self.htft_view.setAccessibleName("İY/MS dağılımı tablosu")
        self.htft_view.setMinimumHeight(200)
        lay.addWidget(self.htft_view)
        lay.addWidget(section("Veri kalitesi (aynı kapsam)"))
        self.quality_model = DataFrameModel()
        self.quality_model.headers = {"olcu": "Ölçü", "g1": "Grup 1", "g2": "Grup 2"}
        self.quality_view, _ = make_table(self.quality_model, sortable=False)
        self.quality_view.setAccessibleName("Veri kalitesi tablosu")
        self.quality_view.setMinimumHeight(180)
        lay.addWidget(self.quality_view)
        self.lbl_group_notes = plain_label("", "muted")
        lay.addWidget(self.lbl_group_notes)
        self.btn_tech_b = QPushButton("Teknik ayrıntıları göster")
        self.btn_tech_b.setCheckable(True)
        self.tech_b = QPlainTextEdit()
        self.tech_b.setReadOnly(True)
        self.tech_b.setAccessibleName("Teknik ayrıntılar (grup karşılaştırması)")
        self.tech_b.setMaximumHeight(160)
        self.tech_b.hide()
        self.btn_tech_b.toggled.connect(self.tech_b.setVisible)
        lay.addWidget(self.btn_tech_b, 0, Qt.AlignLeft)
        lay.addWidget(self.tech_b)
        _compact(w)
        return w

    def _build_tab_events(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        mode = QHBoxLayout()
        self.rb_stored = QRadioButton("A · Saklı çalıştırmanın grubundan")
        self.rb_explicit = QRadioButton("B · Mevcut görünümün maç tablosundan açık seçim")
        self.rb_stored.setChecked(True)
        grp = QButtonGroup(w)
        grp.addButton(self.rb_stored)
        grp.addButton(self.rb_explicit)
        self.rb_stored.toggled.connect(self._mode_changed)
        mode.addWidget(self.rb_stored)
        mode.addWidget(self.rb_explicit)
        mode.addStretch(1)
        lay.addLayout(mode)
        # A: saklı çalıştırma
        self.box_stored = QGroupBox("Saklı çalıştırma → grup → takım")
        sg = QGridLayout(self.box_stored)
        self.cb_run_c = QComboBox()
        self.cb_run_c.setAccessibleName("Saklı çalıştırma (olay karşılaştırması)")
        self.cb_group_c = QComboBox()
        self.cb_group_c.setAccessibleName("Grup")
        self.cb_group_c.addItem("Grup 1", 1)
        self.cb_group_c.addItem("Grup 2", 2)
        self.btn_stored_teams = QPushButton("Grup takımlarını yükle")
        self.btn_stored_teams.clicked.connect(self.load_stored_teams)
        self.cb_team_stored = QComboBox()
        self.cb_team_stored.setAccessibleName("Takım (saklı grup)")
        self.cb_team_stored.setMinimumWidth(180)
        self.lbl_stored_info = plain_label("Önce bir araştırma açın ve saklı çalıştırma seçin.", "muted")
        for r, (text, wid) in enumerate((("Çalıştırma:", self.cb_run_c), ("Grup:", self.cb_group_c),
                                          ("Takım:", self.cb_team_stored))):
            lbl = QLabel(text)
            lbl.setBuddy(wid)
            sg.addWidget(lbl, r, 0)
            sg.addWidget(wid, r, 1)
        sg.addWidget(self.btn_stored_teams, 1, 2)
        sg.addWidget(self.lbl_stored_info, 3, 0, 1, 3)
        sg.setColumnStretch(1, 1)
        lay.addWidget(self.box_stored)
        self.cb_run_c.currentIndexChanged.connect(self._stored_sel_changed)
        self.cb_group_c.currentIndexChanged.connect(self._stored_sel_changed)
        self.cb_team_stored.currentIndexChanged.connect(self._olay_context_changed)
        # B: açık seçim
        self.box_explicit = QGroupBox("Açık olay listesi (mevcut görünüm; kimlik yazılmaz, tablodan seçilir)")
        eg = QVBoxLayout(self.box_explicit)
        er = QHBoxLayout()
        self.cb_team_explicit = QComboBox()
        self.cb_team_explicit.setEditable(True)
        self.cb_team_explicit.setInsertPolicy(QComboBox.NoInsert)
        self.cb_team_explicit.setAccessibleName("Takım (açık seçim)")
        self.cb_team_explicit.setMinimumWidth(180)
        comp = self.cb_team_explicit.completer()
        comp.setFilterMode(Qt.MatchContains)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setCompletionMode(QCompleter.PopupCompletion)
        self.cb_season_explicit = QComboBox()
        self.cb_season_explicit.setAccessibleName("Sezon filtresi (açık seçim)")
        self.btn_list = QPushButton("Maçları listele")
        self.btn_list.clicked.connect(self.list_explicit)
        lbl = QLabel("Takım:")
        lbl.setBuddy(self.cb_team_explicit)
        er.addWidget(lbl)
        er.addWidget(self.cb_team_explicit, 1)
        lbl = QLabel("Sezon:")
        lbl.setBuddy(self.cb_season_explicit)
        er.addWidget(lbl)
        er.addWidget(self.cb_season_explicit)
        er.addWidget(self.btn_list)
        eg.addLayout(er)
        er2 = QHBoxLayout()
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Listede ara (yalnızca görüntüyü süzer; seçim korunur)")
        self.ed_search.setAccessibleName("Maç listesinde ara")
        self.lbl_picked = plain_label("Seçili olay: 0", "muted", fill=False)
        self.btn_clear_pick = QPushButton("Seçimi temizle")
        self.btn_clear_pick.clicked.connect(self.clear_selection)
        er2.addWidget(self.ed_search, 1)
        er2.addWidget(self.lbl_picked)
        er2.addWidget(self.btn_clear_pick)
        eg.addLayout(er2)
        self.lbl_explicit_state = plain_label("Arşiv açılmadı.", "muted")
        eg.addWidget(self.lbl_explicit_state)
        self.pick_model = PickModel()
        self.pick_view, self.pick_proxy = make_table(self.pick_model)
        self.pick_view.setAccessibleName("Açık seçim maç tablosu")
        self.pick_view.setMinimumHeight(200)
        self.pick_model.pickChanged.connect(self._picked_changed)
        self.ed_search.textChanged.connect(self.pick_proxy.setFilterFixedString)
        self.pick_view.selectionModel().currentRowChanged.connect(self._pick_row_changed)
        eg.addWidget(self.pick_view)
        lay.addWidget(self.box_explicit)
        self.cb_team_explicit.currentTextChanged.connect(self._explicit_team_changed)
        self.cb_season_explicit.currentIndexChanged.connect(self._explicit_season_changed)
        # Seçenekler ve sayfalama
        opt = QHBoxLayout()
        self.cb_once = QComboBox()
        self.cb_once.setAccessibleName("Önceki pencere")
        for k in O.PRE_OPTIONS:
            self.cb_once.addItem(f"Önce {k}", k)
        self.cb_sonra = QComboBox()
        self.cb_sonra.setAccessibleName("Sonraki pencere")
        for k in O.POST_OPTIONS:
            self.cb_sonra.addItem(f"Sonra {k}", k)
        self.cb_sonra.setCurrentIndex(self.cb_sonra.findData(3))
        self.sp_limit = QSpinBox()
        self.sp_limit.setRange(1, O.MAX_LIMIT)
        self.sp_limit.setValue(O.DEFAULT_LIMIT)
        self.sp_limit.setAccessibleName("Sayfa boyutu")
        self.sp_limit.setPrefix("Sayfa ")
        self.cb_lig = QComboBox()
        self.cb_lig.setAccessibleName("Lig (olay karşılaştırması)")
        self.cb_lig.addItem("Lig: otomatik (tek lig)", None)
        for wid in (self.cb_once, self.cb_sonra, self.sp_limit, self.cb_lig):
            opt.addWidget(wid)
        opt.addStretch(1)
        lay.addLayout(opt)
        self.cb_once.currentIndexChanged.connect(self._window_changed)
        self.cb_sonra.currentIndexChanged.connect(self._window_changed)
        self.sp_limit.valueChanged.connect(self._window_changed)
        self.cb_lig.currentIndexChanged.connect(self._olay_context_changed)
        nav = QHBoxLayout()
        self.btn_compare = QPushButton("Karşılaştır")
        self.btn_compare.setObjectName("primary")
        self.btn_compare.clicked.connect(lambda: self.compare_events(0))
        self.btn_prev = QPushButton("◀ Önceki sayfa")
        self.btn_prev.clicked.connect(lambda: self._page(-1))
        self.btn_next = QPushButton("Sonraki sayfa ▶")
        self.btn_next.clicked.connect(lambda: self._page(1))
        self.lbl_page = plain_label("", "muted", fill=False)
        nav.addWidget(self.btn_compare)
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next)
        nav.addWidget(self.lbl_page, 1)
        lay.addLayout(nav)
        self.lbl_olay_state = plain_label("Henüz karşılaştırma yok.", "muted")
        lay.addWidget(self.lbl_olay_state)
        self.matrix = MatrixModel()
        self.matrix_view = QTableView()
        self.matrix_view.setModel(self.matrix)
        self.matrix_view.setAccessibleName("Olay önce/sonra matrisi")
        self.matrix_view.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.matrix_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.matrix_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.matrix_view.setWordWrap(False)
        self.matrix_view.verticalHeader().setVisible(False)
        self.matrix_view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.matrix_view.setMinimumHeight(220)
        self.matrix_view.selectionModel().currentChanged.connect(self._matrix_cell)
        self.matrix.modelReset.connect(self._matrix_reset)
        lay.addWidget(self.matrix_view)
        self.matrix_detail = QPlainTextEdit()
        self.matrix_detail.setReadOnly(True)
        self.matrix_detail.setAccessibleName("Seçili hücrenin ayrıntısı")
        self.matrix_detail.setPlaceholderText("Ayrıntı için matristen bir hücre seçin.")
        self.matrix_detail.setMaximumHeight(190)
        lay.addWidget(self.matrix_detail)
        self.lbl_summary = section("Bu sayfadaki olayların özeti")
        self.lbl_summary.setTextFormat(Qt.PlainText)
        self.lbl_summary.setWordWrap(True)
        lay.addWidget(self.lbl_summary)
        self.summary_model = DataFrameModel()
        self.summary_model.headers = {"blok": "Blok", "kayit": "Gözlenen kayıt (tekil)", "kullanilabilir": "Kullanılabilir",
                                      "bilinmeyen": "Sonucu bilinmeyen", "gbm": "Takım G-B-M", "A": "A", "B": "B",
                                      "C": "C", "gol": "Gol at-yen", "iy_gol": "1Y gol at-yen", "iiy_gol": "2Y gol at-yen"}
        self.summary_model.formatters = {k: fmt_int for k in ("kayit", "kullanilabilir", "bilinmeyen")}
        self.summary_view, _ = make_table(self.summary_model, sortable=False)
        self.summary_view.setAccessibleName("Bu sayfadaki olayların özeti")
        self.summary_view.setMinimumHeight(130)
        lay.addWidget(self.summary_view)
        self.lbl_windows = plain_label("", "muted")
        lay.addWidget(self.lbl_windows)
        lay.addWidget(section("Olay pencereleri"))
        self.win_model = DataFrameModel()
        self.win_model.headers = {"sira": "#", "olay": "Olay", "onceki": "Önceki pencere", "sonraki": "Sonraki pencere",
                                  "neden": "Sonraki kayıt yok nedeni", "ortusme": "Başka olayın penceresinde"}
        self.win_view, _ = make_table(self.win_model, sortable=False)
        self.win_view.setAccessibleName("Olay pencereleri tablosu")
        self.win_view.setMinimumHeight(150)
        lay.addWidget(self.win_view)
        lay.addWidget(section("Hesaplanmayan olaylar (sessizce atlanmaz)"))
        self.invalid_model = DataFrameModel()
        self.invalid_model.headers = {"olay_kimligi": "Olay", "neden": "Neden", "metin": "Açıklama"}
        self.invalid_view, _ = make_table(self.invalid_model, sortable=False)
        self.invalid_view.setAccessibleName("Hesaplanmayan olaylar")
        self.invalid_view.setMinimumHeight(90)
        lay.addWidget(self.invalid_view)
        self.lbl_invalid = plain_label("", "muted")
        lay.addWidget(self.lbl_invalid)
        lay.addWidget(section("Seçili olaylar arası aralık"))
        self.interval_model = DataFrameModel()
        self.interval_model.headers = {"olay_kimligi": "Olay", "onceki_secili_olay": "Önceki seçili olay",
                                       "takvim_gunu": "Takvim günü", "arsivde_gozlenen_kayit": "Arşivde gözlenen kayıt",
                                       "sureklilik_durumu": "Süreklilik", "isaretler": "İşaretler"}
        self.interval_model.formatters = {"takvim_gunu": fmt_int, "arsivde_gozlenen_kayit": fmt_int,
                                          "onceki_secili_olay": lambda v: v or DASH}
        self.interval_view, _ = make_table(self.interval_model, sortable=False)
        self.interval_view.setAccessibleName("Seçili olaylar arası aralık")
        self.interval_view.setMinimumHeight(110)
        lay.addWidget(self.interval_view)
        self.lbl_olay_notes = plain_label("", "muted")
        lay.addWidget(self.lbl_olay_notes)
        self.btn_tech_c = QPushButton("Teknik ayrıntıları göster")
        self.btn_tech_c.setCheckable(True)
        self.tech_c = QPlainTextEdit()
        self.tech_c.setReadOnly(True)
        self.tech_c.setAccessibleName("Teknik ayrıntılar (olay karşılaştırması)")
        self.tech_c.setMaximumHeight(160)
        self.tech_c.hide()
        self.btn_tech_c.toggled.connect(self.tech_c.setVisible)
        lay.addWidget(self.btn_tech_c, 0, Qt.AlignLeft)
        lay.addWidget(self.tech_c)
        self._mode_changed()
        _compact(w, keep=(self.matrix_view, self.pick_view))
        return w

    def _build_tab_notes(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.lbl_hist_state = plain_label("Önce bir araştırma açın.", "muted")
        lay.addWidget(self.lbl_hist_state)
        lay.addWidget(section("Revizyonlar"))
        self.rev_model = DataFrameModel()
        self.rev_model.headers = {"revizyon": "Revizyon", "olusturma_utc": "Kayıt (UTC)",
                                  "kayit_aninda_onceki_calistirma": "Kayıt anında önceki çalıştırma",
                                  "tanim_ozeti": "Tanım özeti"}
        self.rev_view, self.rev_proxy = make_table(self.rev_model)
        self.rev_view.setAccessibleName("Revizyon geçmişi")
        self.rev_view.setMinimumHeight(110)
        self.rev_view.selectionModel().currentRowChanged.connect(self._rev_selected)
        lay.addWidget(self.rev_view)
        self.rev_detail = QPlainTextEdit()
        self.rev_detail.setReadOnly(True)
        self.rev_detail.setAccessibleName("Seçili revizyonun tanımı")
        self.rev_detail.setPlaceholderText("Revizyon seçin (eski revizyonlar değiştirilemez; yalnızca görüntülenir).")
        self.rev_detail.setMaximumHeight(110)
        lay.addWidget(self.rev_detail)
        lay.addWidget(section("Çalıştırmalar"))
        self.run_model = DataFrameModel()
        self.run_model.headers = {"calistirma_utc": "Çalıştırma (UTC)", "revizyon": "Revizyon", "durum": "Durum",
                                  "veri": "Veri özeti", "sonuc": "Sonuç özeti"}
        self.run_model.hidden = {"calistirma_id"}
        self.run_view, self.run_proxy = make_table(self.run_model)
        self.run_view.setAccessibleName("Çalıştırma geçmişi")
        self.run_view.setMinimumHeight(110)
        lay.addWidget(self.run_view)
        row = QHBoxLayout()
        self.btn_hist_open = QPushButton("Saklı sonucu aç")
        self.btn_hist_open.clicked.connect(lambda: self.open_run(self._selected_run()))
        self.btn_hist_verify = QPushButton("Mevcut arşivle doğrula")
        self.btn_hist_verify.clicked.connect(self._hist_verify)
        self.btn_hist_olay = QPushButton("Olay karşılaştırmasında kullan")
        self.btn_hist_olay.clicked.connect(self._hist_use_in_events)
        for x in (self.btn_hist_open, self.btn_hist_verify, self.btn_hist_olay):
            row.addWidget(x)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(section("Notlar"))
        self.chk_archived = QCheckBox("Arşivlenen notları da göster")
        self.chk_archived.setChecked(True)
        self.chk_archived.toggled.connect(self._show_notes)
        lay.addWidget(self.chk_archived)
        self.note_model = DataFrameModel()
        self.note_model.headers = {"metin": "Not (ilk satır)", "surum": "Sürüm", "durum": "Durum",
                                   "mac_kimligi": "Bağlı maç", "gorunum_kaynak": "Görünüm", "olusturma_utc": "Son sürüm (UTC)"}
        self.note_model.hidden = {"not_id"}
        self.note_view, self.note_proxy = make_table(self.note_model)
        self.note_view.setAccessibleName("Notlar")
        self.note_view.setMinimumHeight(120)
        self.note_view.selectionModel().currentRowChanged.connect(self._note_selected)
        lay.addWidget(self.note_view)
        self.note_detail = QPlainTextEdit()
        self.note_detail.setReadOnly(True)
        self.note_detail.setAccessibleName("Seçili notun ayrıntısı ve önceki sürümleri")
        self.note_detail.setMaximumHeight(130)
        lay.addWidget(self.note_detail)
        lbl = QLabel("Not metni:")
        self.ed_note = QPlainTextEdit()
        self.ed_note.setAccessibleName("Not metni")
        self.ed_note.setTabChangesFocus(True)
        self.ed_note.setMaximumHeight(90)
        self.ed_note.setPlaceholderText(f"Düz metin (en çok {C.LIMITS['not']} karakter). Not skoru, modeli veya "
                                        "etiketleri değiştirmez.")
        lbl.setBuddy(self.ed_note)
        lay.addWidget(lbl)
        lay.addWidget(self.ed_note)
        self.lbl_link = plain_label("Bağlanacak maç: yok (Olay karşılaştırması sekmesinde bir matris hücresi veya açık "
                                    "listede bir maç seçin).", "muted")
        lay.addWidget(self.lbl_link)
        r1 = QHBoxLayout()
        self.btn_note_add = QPushButton("Araştırmaya not ekle")
        self.btn_note_add.clicked.connect(lambda: self.add_note(False))
        self.btn_note_match = QPushButton("Seçili maça bağlı not ekle")
        self.btn_note_match.clicked.connect(lambda: self.add_note(True))
        self.btn_note_load = QPushButton("Seçili notu düzenleyiciye al")
        self.btn_note_load.clicked.connect(self._note_to_editor)
        for x in (self.btn_note_add, self.btn_note_match, self.btn_note_load):
            r1.addWidget(x)
        r1.addStretch(1)
        lay.addLayout(r1)
        r2 = QHBoxLayout()
        self.btn_note_version = QPushButton("Seçili notun yeni sürümü")
        self.btn_note_version.setToolTip("Düzenleyicideki metinle yeni sürüm kaydeder; önceki sürüm korunur.")
        self.btn_note_version.clicked.connect(self.note_new_version)
        self.btn_note_archive = QPushButton("Seçili notu arşivle")
        self.btn_note_archive.setToolTip("Fiziksel silme yoktur: not 'arsivlendi' durumunda yeni sürüm olarak kalır.")
        self.btn_note_archive.clicked.connect(self.note_archive)
        self.cb_card_side = QComboBox()
        self.cb_card_side.setAccessibleName("Kart takımı")
        self.cb_card_side.addItem("Ev sahibi takım", "home")
        self.cb_card_side.addItem("Deplasman takımı", "away")
        self.btn_note_card = QPushButton("Bağlı maçın kartını aç")
        self.btn_note_card.clicked.connect(self.note_card)
        for x in (self.btn_note_version, self.btn_note_archive, self.cb_card_side, self.btn_note_card):
            r2.addWidget(x)
        r2.addStretch(1)
        lay.addLayout(r2)
        self.card_text = QPlainTextEdit()
        self.card_text.setReadOnly(True)
        self.card_text.setAccessibleName("Bağlı maçın olay kartı")
        self.card_text.setMaximumHeight(150)
        self.card_text.hide()
        lay.addWidget(self.card_text)
        self.card_model = DataFrameModel()
        self.card_model.hidden = {"row_id", "event_id", "team", "season", "league", "source", "time", "has_stats",
                                  "red_for", "red_against", "onceki_mac", "sonraki_mac", "saat_dilimi", "s0_guc",
                                  "s0_guc_rakip", "htft"}
        self.card_view, _ = make_table(self.card_model, sortable=False)
        self.card_view.setAccessibleName("Bağlı maçın pencereleri")
        self.card_view.setMinimumHeight(150)
        self.card_view.hide()
        lay.addWidget(self.card_view)
        _compact(w)
        return w

    # ================================================================== yardımcılar
    @staticmethod
    def _default_archive() -> str:
        try:
            return str(A.archive_home_path())
        except Exception:  # yalnızca öneri; yol çözülemezse boş
            return ""

    @staticmethod
    def _default_ws() -> str:
        try:
            return str(C.workspace_home_path())
        except Exception:
            return ""

    def _browse(self, edit: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "Klasör seç", edit.text().strip() or "")
        if d:
            edit.setText(d)

    def _goto_data(self) -> None:
        from .data import DataPage

        win = self.window()
        pages = getattr(win, "pages", None)
        if pages:
            for i, p in enumerate(pages):
                if isinstance(p, DataPage):
                    win.nav.setCurrentRow(i)
                    return

    @staticmethod
    def _ptext(lbl: QLabel, text: str) -> None:
        """Yol içerebilen etiket: metin ve aynı tam metin ipucu (dar pencerede kırpılan uzun yol okunabilir kalır)."""
        lbl.setText(text)
        lbl.setToolTip(text)

    def say(self, text: str, kind: str = "muted") -> None:
        """Sayfa içi ileti (düz metin): hata metni ve yollar HTML olarak yorumlanmaz."""
        self.msg.setText(text)
        self.msg.setToolTip(text)
        _set_kind(self.msg, kind)
        self.msg.setVisible(bool(text))

    def _separate(self) -> list:
        """Çalışma alanıyla çakışmaması gereken ek klasörler (açık veya yazılı arşiv yolu)."""
        out = []
        for p in (self.archive_path, self.ed_archive.text().strip()):
            if p and p not in out:
                out.append(p)
        return out

    def _start(self, channel: str, fn, done, label: str, critical: bool, ctx=None) -> bool:
        """Arka plan işi (tek görev yöneticisi: ``AppController``). ``done(istek, sonuç)`` ana iş parçacığında."""
        self._token += 1
        req = {"token": self._token, "kanal": channel, "ctx": ctx}

        def guarded(progress, fn=fn):
            try:
                return fn(progress)
            except Exception as e:  # beklenmeyen hata da sonuç olarak döner (düz metin gösterilir, geri çağrı çalışır)
                log.exception("Araştırma çalışma alanı işi başarısız: %s", channel)
                err = f"{type(e).__name__}: {e}"
                if critical:
                    err += (" Yazmanın tamamlanıp tamamlanmadığı doğrulanamadı; kayıtları yeniden açarak kontrol "
                            "edin.")
                return {"ok": False, "kind": "beklenmeyen", "error": err}

        guarded.job = fn  # (testler) işe giden düz veriler incelenebilir

        def deliver(res, req=req):
            if not shiboken6.isValid(self):  # pencere silindiyse geri çağrı hiçbir şeye dokunmaz
                return
            done(req, res)

        ok = self.ctl.run_job(guarded, deliver, label, critical=critical)
        if ok:
            self._latest[channel] = self._token
        else:
            self.say("Başka bir işlem sürüyor; bitmesini bekleyin. (İşlem başlatılmadı.)", "warn")
        return ok

    def _stale(self, req: dict, current_ctx) -> bool:
        return self._latest.get(req["kanal"]) != req["token"] or req["ctx"] != current_ctx

    # ================================================================== arşiv
    def open_archive(self) -> None:
        path = self.ed_archive.text().strip()
        if not path:
            self.say("Arşiv klasörü verilmedi.", "warn")
            return
        self._start("arsiv", functools.partial(job_open_archive, path=path), self._archive_done,
                    "Arşiv salt okunur açılıyor...", critical=False, ctx=path)

    def _archive_done(self, req, res) -> None:
        if not res["ok"]:
            self.btn_goto_data.show()
            self._ptext(self.lbl_archive, f"Arşiv açılamadı: {res['error']}\nYol: {req['ctx']}\nArşiv bu sayfada indirilmez veya "
                                     "hazırlanmaz; 'Veri' sayfasındaki 'GitHub Veri ve Arşiv' bölümünü kullanın.")
            _set_kind(self.lbl_archive, "warn")
            self.say(f"Arşiv açılamadı ({req['ctx']}): {res['error']}", "warn")
            return
        self.btn_goto_data.hide()
        old = {k: (v["veri"] or {}).get("veri_ozeti") for k, v in self.info.items()} if self.info else None
        self.archive, self.views, self.info = res["archive"], res["views"], res["info"]
        self.archive_path, self.archive_meta = res["path"], res["katalog"]
        self.archive_gen += 1
        m = self.archive_meta
        self._ptext(self.lbl_archive, f"Arşiv açık (salt okunur): {res['path']} · sürüm {m.get('arsiv') or '-'} · oluşturma "
                                 f"{m.get('olusturma_utc') or '-'} · bilgi kesimi {m.get('bilgi_kesimi') or '-'} · "
                                 f"{res['satir']} analiz kaynak satırı · kökeni doğrulanamayan {res['dogrulanamayan']} "
                                 "blok (kullanılmadı)")
        _set_kind(self.lbl_archive, "muted")
        key = self._source_key()
        new_ver = (self.info.get(key, {}).get("veri") or {}).get("veri_ozeti")
        if old is not None and old.get(key) != new_ver and self.pick_model.picked:
            n = len(self.pick_model.picked)
            self.pick_model.clear_picked()
            self.say(f"Görünümün veri sürümü değişti: açık seçimdeki {n} olay temizlendi (eski veriyle seçilmişti).",
                     "warn")
        else:
            self.say("Arşiv salt okunur açıldı.")
        self.pick_model.set_frame(pd.DataFrame(columns=PickModel.COLUMNS))  # liste yeni yüklemeden yeniden alınır
        self._clear_olay("Arşiv yeniden açıldı; karşılaştırmayı yeniden yapın.")
        if self.group_shown and self.group_shown["tur"] == "onizleme":  # önizleme önceki arşivle hesaplanmıştı
            self._clear_group("Arşiv yeniden açıldı; önizleme temizlendi (yeniden önizleyin).")
        self.lbl_verify.hide()  # doğrulama önceki arşive aitti
        self._apply_view_options()
        self._update_actions()

    def _source_key(self):
        d = self.cb_source.currentData()
        return None if d in (None, A.MERGED_VIEW) else d

    def _source_changed(self, *a) -> None:
        if self.pick_model.picked:
            n = len(self.pick_model.picked)
            self.pick_model.clear_picked()
            self.say(f"Kaynak görünümü değişti: açık seçimdeki {n} olay temizlendi (başka görünümün maçları).", "warn")
        self.pick_model.set_frame(pd.DataFrame(columns=PickModel.COLUMNS))
        if self.rb_explicit.isChecked():
            self._clear_olay("Kaynak görünümü değişti; karşılaştırmayı yeniden yapın.")
        self._apply_view_options()
        self._form_changed()

    def _apply_view_options(self) -> None:
        key = self._source_key()
        inf = self.info.get(key) if self.info else None
        self.lbl_form_source.setText(self.cb_source.currentText() + " (üstteki seçimden)")
        if inf is None:
            self.lbl_data.setText("Veri sürümü: arşiv açılmadı.")
            for gf in (self.g1, self.g2):
                gf.set_options([], [], None)
            self._set_explicit_options([], [])
            self.lbl_explicit_state.setText("Arşiv açılmadı.")
            self._update_lig_options([])
            return
        if inf["kapali"]:
            self.lbl_data.setText(f"Görünüm {source_short(key)}: {inf['aciklama']} Analiz düğmeleri bu kapsamı aşmaz.")
            self.lbl_explicit_state.setText("Kapalı kaynak: bu görünümde maç yok; olay karşılaştırması yapılamaz.")
        else:
            v = inf["veri"] or {}
            commits = "; ".join(f"{source_short(k)} {', '.join(c[:10] for c in cs)}"
                                for k, cs in (v.get("kaynak_commitleri") or {}).items())
            self.lbl_data.setText(f"Görünüm {source_short(key)}: {inf['mac']} maç · veri özeti "
                                  f"{short_hash(v.get('veri_ozeti'))} · {v.get('blok_sayisi', 0)} blok · commit {commits or '-'}")
            self.lbl_explicit_state.setText("Takım ve sezon seçip 'Maçları listele' ile tabloyu doldurun."
                                            if inf["mac"] else "Bu görünümde maç yok.")
        for gf in (self.g1, self.g2):
            gf.set_options(inf["ligler"], inf["sezonlar"], inf["takimlar"])
        self._set_explicit_options(inf["takimlar"], inf["sezonlar"])
        self._update_lig_options(inf["ligler"])

    def _set_explicit_options(self, teams: list, seasons: list) -> None:
        cur_t = self.cb_team_explicit.currentText()
        cur_s = self.cb_season_explicit.currentData()
        for w in (self.cb_team_explicit, self.cb_season_explicit):
            w.blockSignals(True)
        try:
            self.cb_team_explicit.clear()
            self.cb_team_explicit.addItem("")
            for t in teams:
                self.cb_team_explicit.addItem(t)
            self.cb_team_explicit.setCurrentText(cur_t if cur_t in teams else "")
            self.cb_season_explicit.clear()
            self.cb_season_explicit.addItem("Tüm sezonlar", None)
            for s in seasons:
                self.cb_season_explicit.addItem(s, s)
            i = self.cb_season_explicit.findData(cur_s) if cur_s else 0
            self.cb_season_explicit.setCurrentIndex(max(i, 0))
        finally:
            for w in (self.cb_team_explicit, self.cb_season_explicit):
                w.blockSignals(False)
        if cur_t and cur_t not in teams and self.pick_model.picked:
            n = len(self.pick_model.picked)
            self.pick_model.clear_picked()
            self.say(f"Takım '{cur_t}' bu görünümde yok: açık seçimdeki {n} olay temizlendi.", "warn")

    def _update_lig_options(self, leagues: list) -> None:
        cur = self.cb_lig.currentData()
        self.cb_lig.blockSignals(True)
        self.cb_lig.clear()
        self.cb_lig.addItem("Lig: otomatik (tek lig)", None)
        for lg in leagues:
            self.cb_lig.addItem(f"Lig: {lg}", lg)
        i = self.cb_lig.findData(cur) if cur else 0
        self.cb_lig.setCurrentIndex(max(i, 0))
        self.cb_lig.blockSignals(False)

    # ================================================================== çalışma alanı
    def open_workspace(self) -> None:
        path = self.ed_ws.text().strip()
        if not path:
            self.say("Çalışma alanı klasörü verilmedi.", "warn")
            return
        if not self._confirm_leave("Başka çalışma alanı açmak", self.open_workspace):
            return
        self._start("alan", functools.partial(job_open_workspace, path=path), self._ws_done,
                    "Çalışma alanı açılıyor...", critical=False, ctx={"path": path, "olustur": False})

    def create_workspace(self) -> None:
        path = self.ed_ws.text().strip()
        if not path:
            self.say("Çalışma alanı klasörü verilmedi.", "warn")
            return
        if not self._confirm_leave("Yeni çalışma alanı oluşturmak", self.create_workspace):
            return
        self._start("alan", functools.partial(job_create_workspace, path=path, ayri=self._separate()),
                    self._ws_done, "Yeni çalışma alanı oluşturuluyor...", critical=True,
                    ctx={"path": path, "olustur": True})

    def _ws_done(self, req, res) -> None:
        path, created = req["ctx"]["path"], req["ctx"]["olustur"]
        if not res["ok"]:
            what = "oluşturulamadı" if created else "açılamadı"
            self._ptext(self.lbl_ws, f"Çalışma alanı {what}: {res['error']}\nYol: {path}"
                                + (f"\nAçık çalışma alanı değişmedi: {self.ws_path}" if self.ws_path else ""))
            _set_kind(self.lbl_ws, "warn")
            self.say(f"Çalışma alanı {what} ({path}): {res['error']} Hiçbir dosyanın üzerine yazılmadı.", "warn")
            return
        self.ws_path = res["klasor"]
        self.ws_gen += 1
        self.research_list = res["liste"]
        self._set_research(None, None, None)
        self._new_draft_form()
        self._ws_created = created
        self.say("Yeni çalışma alanı oluşturuldu." if created else "Var olan çalışma alanı açıldı (salt okunur; yazan "
                                                                   "işlemler ayrıca açar).")
        self._show_list()
        self._update_actions()

    # ================================================================== araştırma listesi / taslak
    def _show_list(self) -> None:
        rows = [{"baslik": r["baslik"], "son_revizyon": r["son_revizyon"],
                 "gorunum": source_short((r.get("gorunum") or {}).get("kaynak")), "calistirma": r["calistirma"],
                 "not": r["not"], "olusturma_utc": r["olusturma_utc"], "arastirma_id": r["arastirma_id"]}
                for r in self.research_list]
        self.list_model.set_frame(_frame(rows, ["baslik", "son_revizyon", "gorunum", "calistirma", "not", "olusturma_utc",
                                                "arastirma_id"]))
        if self.ws_path is not None:
            self._ptext(self.lbl_ws, f"Çalışma alanı açık: {self.ws_path} · {len(rows)} araştırma"
                                + (" · bu oturumda oluşturuldu" if self._ws_created else ""))
            _set_kind(self.lbl_ws, "muted")
        if self.ws_path is None:
            self.list_state.setText("Çalışma alanı açılmadı. Var olan alanı açın veya yeni bir alan oluşturun.")
        elif not rows:
            self.list_state.setText("Bu çalışma alanında henüz araştırma yok. 'Yeni araştırma' ile başlayın.")
        else:
            self.list_state.setText(f"{len(rows)} araştırma. Açmak için seçip 'Seçili araştırmayı aç' (veya çift tık).")
        if self.rid:
            for r in range(self.list_model.rowCount()):
                if self.list_model.frame.iloc[r]["arastirma_id"] == self.rid:
                    self.list_view.selectRow(self.list_proxy.mapFromSource(self.list_model.index(r, 0)).row())
                    break

    def _selected_list_id(self) -> str | None:
        idx = self.list_view.selectionModel().currentIndex()
        if not idx.isValid():
            return None
        return str(self.list_model.frame.iloc[self.list_proxy.mapToSource(idx).row()]["arastirma_id"])

    def new_research(self) -> None:
        if not self._confirm_leave("Yeni araştırma açmak", self.new_research):
            return
        self._set_research(None, None, None)
        self._new_draft_form()
        self.say("Yeni taslak açıldı (bellekte; 'Kaydet' ile kaydedilir).")

    def open_selected_research(self) -> None:
        rid = self._selected_list_id()
        if rid is None:
            self.say("Önce listeden bir araştırma seçin.", "warn")
            return
        self.open_research(rid)

    def open_research(self, rid: str) -> None:
        if self.ws_path is None:
            self.say("Önce çalışma alanını açın.", "warn")
            return
        if not self._confirm_leave("Başka araştırma açmak", lambda: self.open_research(rid)):
            return
        self._start("arastirma", functools.partial(job_load_research, ws=self.ws_path, rid=rid), self._research_done,
                    "Araştırma okunuyor...", critical=False, ctx=(self.ws_gen, rid))

    def _research_done(self, req, res) -> None:
        if self._stale(req, (self.ws_gen, req["ctx"][1])) or req["ctx"][0] != self.ws_gen:
            self.say("Araştırma sonucu eski çalışma alanına ait; gösterilmedi.", "warn")
            return
        if not res["ok"]:
            self.say(f"Araştırma açılamadı: {res['error']}", "warn")
            return
        self.research_list = res["liste"]
        self._load_record(res["kayit"])
        self._show_list()
        self.say(f"Araştırma açıldı: r{self.rev} (en son revizyon).")

    def _load_record(self, rec: dict) -> None:
        self._set_research(rec["arastirma_id"], rec["revizyon"], rec)
        self._fill_form(rec["tanim"])

    def _set_research(self, rid, rev, rec) -> None:
        changed = rid != self.rid
        self.rid, self.rev, self.rec = rid, rev, rec
        if changed:
            self._clear_group("Araştırma değişti; sonuç temizlendi.")
            self._clear_olay("Araştırma değişti; karşılaştırma temizlendi.")
            self.cb_team_stored.clear()
            self.card = None
            self.card_text.hide()
            self.card_view.hide()
        self._show_history()

    def _fill_form(self, tanim: dict) -> None:
        widgets = [self.ed_title, self.ed_desc, self.ed_tags, self.cb_source, self.chk_g2, *self.chk_markets.values()]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.ed_title.setText(tanim.get("baslik") or "")
            self.ed_desc.setPlainText(tanim.get("aciklama") or "")
            self.ed_tags.setText(", ".join(tanim.get("etiketler") or []))
            key = (tanim.get("gorunum") or {}).get("kaynak")
            i = self.cb_source.findData(key if key else A.MERGED_VIEW)
            src_changed = i >= 0 and i != self.cb_source.currentIndex()
            self.cb_source.setCurrentIndex(max(i, 0))
            for k, chk in self.chk_markets.items():
                chk.setChecked(k in (tanim.get("pazarlar") or C.MARKETS))
            self.chk_g2.setChecked(tanim.get("grup_2") is not None)
        finally:
            for w in widgets:
                w.blockSignals(False)
        if src_changed:
            if self.pick_model.picked:
                self.pick_model.clear_picked()
                self.say("Kaynak görünümü değişti: açık seçim temizlendi.", "warn")
            self.pick_model.set_frame(pd.DataFrame(columns=PickModel.COLUMNS))
        self._apply_view_options()
        self.g1.set_value(tanim.get("grup_1"))
        self.g2.set_value(tanim.get("grup_2"))
        self.g2.setEnabled(self.chk_g2.isChecked())
        self._base = self.form_input()
        self._form_changed()

    def _new_draft_form(self) -> None:
        empty = {"baslik": "", "aciklama": "", "etiketler": [], "gorunum": {"kaynak": self._source_key()},
                 "grup_1": None, "grup_2": None, "pazarlar": list(C.MARKETS)}
        self._fill_form(empty)

    def _g2_toggled(self, on: bool) -> None:
        self.g2.setEnabled(on)
        self._form_changed()

    def form_input(self) -> dict:
        """Formun tanım girdisi (ana iş parçacığında okunur; işe kopya gider). Doğrulama servistedir."""
        return {"baslik": self.ed_title.text(), "aciklama": self.ed_desc.toPlainText(),
                "kaynak": self.cb_source.currentData() or A.MERGED_VIEW, "grup_1": self.g1.value(),
                "grup_2": self.g2.value() if self.chk_g2.isChecked() else None,
                "pazarlar": [k for k, chk in self.chk_markets.items() if chk.isChecked()],
                "etiketler": [t.strip() for t in self.ed_tags.text().split(",") if t.strip()]}

    def _form_canon(self) -> str:
        return C.canon(self.form_input())

    def _dirty_key(self, d: dict) -> str:
        # Henüz kaydedilmemiş yeni taslakta yalnızca kaynak seçimini değiştirmek kaybedilecek iş sayılmaz (kaynak
        # üstteki seçimdir; boş taslak zaten kaydedilemez). Kayıtlı araştırmada kaynak tanımın parçasıdır.
        return C.canon({**d, "kaynak": None} if self.rid is None else d)

    @property
    def dirty(self) -> bool:
        return self._base is not None and self._dirty_key(self.form_input()) != self._dirty_key(self._base)

    def form_error(self) -> str | None:
        for gf in ((self.g1, self.g2) if self.chk_g2.isChecked() else (self.g1,)):
            err = gf.team_error()
            if err:
                return err
        return None

    def _form_changed(self, *a) -> None:
        if self.rid is None:
            state = "Yeni taslak — kaydedilmedi." + (" Kaydedilmemiş değişiklik var." if self.dirty else "")
        else:
            title = (self.rec or {}).get("tanim", {}).get("baslik", "")
            state = (f"Açık araştırma: {title} · r{self.rev}" + (" · KAYDEDİLMEMİŞ DEĞİŞİKLİK VAR (yeni revizyon olarak "
                                                                  "kaydedilir; eski revizyon değişmez)" if self.dirty
                                                                  else " · kayıtlı"))
        self.lbl_draft.setText(state)
        _set_kind(self.lbl_draft, "warn" if self.dirty else "muted")
        err = self.form_error()
        self.lbl_form_error.setText(err or "")
        self.lbl_form_error.setVisible(bool(err))
        self.btn_save.setText("Kaydet" if self.rid is None else "Yeni revizyon kaydet")
        self._update_actions()

    def discard_changes(self) -> None:
        if self.rec is not None:
            self._fill_form(self.rec["tanim"])
        else:
            self._new_draft_form()
        self.say("Değişiklikler bırakıldı.")

    # ------------------------------------------------------------ kaydedilmemiş değişiklik sorusu
    def ask_unsaved(self, action: str) -> str:
        """'save' | 'discard' | 'cancel' (testlerde değiştirilebilir)."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Kaydedilmemiş değişiklik")
        box.setTextFormat(Qt.PlainText)
        box.setText(f"Taslakta kaydedilmemiş değişiklik var. {action} için ne yapılsın?")
        save = box.addButton("Kaydet", QMessageBox.AcceptRole)
        discard = box.addButton("Değişiklikleri bırak", QMessageBox.DestructiveRole)
        cancel = box.addButton("Vazgeç", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        return "save" if clicked is save else "discard" if clicked is discard else "cancel"

    def _confirm_leave(self, action: str, then) -> bool:
        """Taslak kirliyse sor. True: devam et. 'Kaydet' seçilirse kayıt başarıyla bitince ``then`` çalışır."""
        if not self.dirty:
            return True
        ans = self.ask_unsaved(action)
        if ans == "discard":
            self._base = self.form_input()  # değişiklikler açıkça bırakıldı
            return True
        if ans == "save":
            if self.save(after=then):
                self.say("Kaydediliyor; kayıt bitince işlem sürdürülecek.")
        return False

    def confirm_close(self) -> bool:
        """Ana pencere kapanırken: kirli taslak sessizce kaybolmaz."""
        if self._saving or not self.dirty:
            return True
        win = self.window()
        return self._confirm_leave("Pencereyi kapatmak", lambda: win.close() if shiboken6.isValid(win) else None)

    # ------------------------------------------------------------ kaydet / revizyon
    def save(self, after=None) -> bool:
        if self.ws_path is None:
            self.say("Önce bir çalışma alanı açın veya oluşturun.", "warn")
            return False
        err = self.form_error()
        if err:
            self.say(err, "warn")
            return False
        tanim = self.form_input()
        if self.rid is None:
            fn = functools.partial(job_save_new, ws=self.ws_path, ayri=self._separate(), tanim=tanim)
            label = "Araştırma kaydediliyor..."
        else:
            if not self.dirty:
                self.say("Değişiklik yok; yeni revizyon oluşturulmadı.")
                return False
            fn = functools.partial(job_revise, ws=self.ws_path, ayri=self._separate(), rid=self.rid,
                                   degisiklik=tanim, temel=self.rev)
            label = "Yeni revizyon kaydediliyor..."
        ok = self._start("kaydet", fn, self._save_done, label, critical=True,
                         ctx={"ws_gen": self.ws_gen, "canon": C.canon(tanim), "input": tanim, "rid": self.rid})
        if ok:
            self._saving = True
            self._after_save = after
        return ok

    def _save_done(self, req, res) -> None:
        self._saving = False
        after, self._after_save = self._after_save, None
        if not res["ok"]:
            kind = res.get("kind")
            prefix = ("Revizyon çakışması" if kind == "cakisma" else "Doğrulama hatası" if kind == "dogrulama"
                      else "Kaydedilemedi")
            self.say(f"{prefix}: {res['error']} Taslak korunuyor; hiçbir kayıt değiştirilmedi.", "warn")
            return
        rec = res.get("kayit")
        written = res["yazildi"]
        if "liste" in res:
            self.research_list = res["liste"]
        same_form = self._form_canon() == req["ctx"]["canon"]
        if rec is None:  # yazma tamamlandı, yenileme okuması başarısız: yazılan kayıt yine de temel alınır
            rec = {**written, "revizyonlar": [], "calistirmalar": [], "notlar": []}
        self._set_research(rec["arastirma_id"], rec["revizyon"], rec)
        if same_form:
            self._fill_form(rec["tanim"])
        else:  # kayıt sırasında form değişti: yazılan form temel alınır, sonraki düzenlemeler kirli kalır
            self._base = req["ctx"]["input"]
            self._form_changed()
        self._show_list()
        msg = f"Kaydedildi: r{written['revizyon']} ({written['arastirma_id']})."
        if res.get("yenileme_hatasi"):
            msg += f" Kayıt yazıldı ama liste yenilenemedi: {res['yenileme_hatasi']}"
        self.say(msg, "warn" if res.get("yenileme_hatasi") else "muted")
        if after is not None:
            after()

    # ------------------------------------------------------------ önizleme / çalıştırma
    def _need_archive(self) -> bool:
        if self.archive is None:
            self.say("Önce arşivi açın (salt okunur). Arşiv yoksa 'Veri' sayfasından hazırlanır.", "warn")
            return False
        return True

    def preview(self) -> None:
        if not self._need_archive():
            return
        err = self.form_error()
        if err:
            self.say(err, "warn")
            return
        tanim = self.form_input()
        self._start("grup", functools.partial(job_preview, archive=self.archive, tanim=tanim), self._preview_done,
                    "Önizleme hesaplanıyor...", critical=False, ctx=(self.archive_gen, C.canon(tanim)))

    def _preview_done(self, req, res) -> None:
        if self._stale(req, (self.archive_gen, self._form_canon())):
            self.say("Önizleme sonucu gösterilmedi: istek sırasında form veya arşiv değişti. Yeniden önizleyin.", "warn")
            return
        if not res["ok"]:
            self.say(f"Önizleme yapılamadı: {res['error']}", "warn")
            return
        self._show_group({"tur": "onizleme", "sonuc": res["sonuc"]})
        self.tabs.setCurrentIndex(1)
        self.say("Önizleme gösteriliyor (kaydedilmedi).")

    def run_saved(self) -> None:
        if self.ws_path is None or self.rid is None:
            self.say("Önce araştırmayı kaydedin veya açın; çalıştırma kayıtlı revizyonu kullanır.", "warn")
            return
        if self.dirty:
            self.say(f"Kaydedilmemiş değişiklik var. Çalıştırma yalnızca kayıtlı tanımla yapılır (şu an r{self.rev}); "
                     "önce kaydedin veya değişiklikleri bırakın.", "warn")
            return
        if not self._need_archive():
            return
        self._start("calistir", functools.partial(job_run, ws=self.ws_path, ayri=self._separate(), archive=self.archive,
                                                  rid=self.rid, beklenen=self.rev),
                    self._run_done, f"Çalıştırılıyor (r{self.rev})...", critical=True,
                    ctx={"rid": self.rid, "rev": self.rev, "ws_gen": self.ws_gen})

    def _run_done(self, req, res) -> None:
        if not res["ok"]:
            self.say(f"Çalıştırma kaydedilmedi: {res['error']}", "warn")
            return
        run = res["yazildi"]
        if "liste" in res:
            self.research_list = res["liste"]
            self._show_list()
        if res.get("kayit") is not None and self.rid == req["ctx"]["rid"]:
            self.rec = res["kayit"]
            self._show_history()
        if self.rid == req["ctx"]["rid"]:
            self._show_group({"tur": "sakli", "kayit": run, "sonuc": run["sonuc"]})
            self.tabs.setCurrentIndex(1)
        self.say(f"Çalıştırma saklandı: {run['calistirma_id']} (r{run['revizyon']}, {run['calistirma_utc']})."
                 + (f" Liste yenilenemedi: {res['yenileme_hatasi']}" if res.get("yenileme_hatasi") else ""))

    # ------------------------------------------------------------ saklı sonuç / doğrulama
    def open_run(self, cid) -> None:
        if not cid or self.ws_path is None:
            self.say("Saklı çalıştırma seçilmedi.", "warn")
            return
        self._start("grup", functools.partial(job_open_run, ws=self.ws_path, cid=cid), self._open_run_done,
                    "Saklı sonuç okunuyor...", critical=False, ctx=(self.ws_gen, self.rid, cid))

    def _open_run_done(self, req, res) -> None:
        if self._stale(req, (self.ws_gen, self.rid, req["ctx"][2])):
            self.say("Saklı sonuç başka araştırmaya ait; gösterilmedi.", "warn")
            return
        if not res["ok"]:
            self.say(f"Saklı sonuç okunamadı: {res['error']}", "warn")
            return
        rec = res["kayit"]
        self._show_group({"tur": "sakli", "kayit": rec, "sonuc": rec["sonuc"]})
        self.tabs.setCurrentIndex(1)
        self.say("Saklı sonuç gösteriliyor (yeniden hesaplanmadı).")

    def verify(self, cid=None) -> None:
        gs = self.group_shown
        cid = cid or (gs["kayit"]["calistirma_id"] if gs and gs["tur"] == "sakli" else None)
        if not cid:
            self.say("Doğrulama için önce saklı sonucu açın.", "warn")
            return
        if not self._need_archive():
            return
        self._start("dogrula", functools.partial(job_verify, ws=self.ws_path, archive=self.archive, cid=cid),
                    self._verify_done, "Doğrulanıyor (salt okunur)...", critical=False,
                    ctx=(self.ws_gen, self.archive_gen, cid))

    def _verify_done(self, req, res) -> None:
        shown = self.group_shown["kayit"]["calistirma_id"] if self.group_shown and self.group_shown["tur"] == "sakli" \
            else None
        if self._stale(req, (self.ws_gen, self.archive_gen, shown)):
            self.say("Doğrulama sonucu gösterilen saklı sonuca ait değil; gösterilmedi.", "warn")
            return
        if not res["ok"]:
            self.say(f"Doğrulanamadı: {res['error']}", "warn")
            return
        d = res["dogrulama"]
        text = VERIFY_TEXT.get(d["durum"], d["durum"])
        if d.get("sakli_veri_ozeti"):
            text += (f"\nSaklı veri özeti {short_hash(d['sakli_veri_ozeti'])} · güncel {short_hash(d.get('guncel_veri_ozeti'))}"
                     f" · saklı sonuç özeti {short_hash(d.get('sakli_sonuc_ozeti'))} · güncel "
                     f"{short_hash(d.get('guncel_sonuc_ozeti'))}")
        self.lbl_verify.setText(text)
        self.lbl_verify.setProperty("durum", d["durum"])
        _set_kind(self.lbl_verify, "banner" if d["durum"] == "DOGRULANDI" else "warn")
        self.lbl_verify.show()
        self.say(f"Doğrulama: {d['durum']} (hiçbir şey yazılmadı).")

    # ------------------------------------------------------------ grup sonucu gösterimi
    def _clear_group(self, why: str = "") -> None:
        self.group_shown = None
        for m in (self.market_model, self.htft_model, self.quality_model):
            m.set_frame(pd.DataFrame())
        self.lbl_group_head.setText("")
        self.lbl_overlap.setText("")
        self.lbl_htft_n.setText("")
        self.lbl_group_notes.setText("")
        self.lbl_verify.hide()
        self.tech_b.setPlainText("")
        self.lbl_group_state.setText(why or "Henüz sonuç yok: 'Önizle (kaydetmez)' veya 'Saklı sonucu aç'.")
        self.lbl_group_state.show()

    def _show_group(self, shown: dict) -> None:
        self._clear_group()
        self.group_shown = shown
        sonuc = shown["sonuc"]
        if shown["tur"] == "onizleme":
            res = sonuc
            t = res["tanim"]
            head = [f"ÖNİZLEME — kaydedilmedi. Tanım: formdaki (kaydedilmemiş olabilir) · görünüm "
                    f"{source_short(res['gorunum']['kaynak'])} · veri özeti {short_hash(res['veri']['veri_ozeti'])}"]
            sonuc = res["sonuc"]
            tech = {"veri": res["veri"], "surumler": res["surumler"], "sonuc_ozeti": res["sonuc_ozeti"],
                    "olay_sayilari": res.get("olay_sayilari")}
        else:
            rec = shown["kayit"]
            t = rec["tanim"]
            head = [f"SAKLI SONUÇ — yeniden hesaplanmadı. Araştırma {t['baslik']} · r{rec['revizyon']} · çalıştırma "
                    f"{rec['calistirma_utc']} · görünüm {source_short(rec['gorunum']['kaynak'])} · veri özeti "
                    f"{short_hash(rec['veri']['veri_ozeti'])}"]
            prev = rec.get("onceki_calistirmaya_gore_veri") or {}
            if prev.get("durum") == "DEGISTI":
                head.append("Veri sürümü önceki çalıştırmadan farklı; önceki sonuç değiştirilmedi.")
            tech = {"calistirma_id": rec["calistirma_id"], "arastirma_id": rec["arastirma_id"],
                    "veri": rec.get("veri"), "surumler": rec.get("surumler"), "sonuc_ozeti": rec.get("sonuc_ozeti"),
                    "olay_kumeleri": rec.get("olay_kumeleri")}
        head.append("Tanım: Grup 1: " + group_text(t.get("grup_1")) + " | Grup 2: " + group_text(t.get("grup_2")))
        self.lbl_group_head.setText("\n".join(head))
        self.tech_b.setPlainText(C.to_json(tech, indent=1))
        if sonuc.get("durum") == "KULLANIM_KAPSAMI_KAPALI":
            self.lbl_group_state.setText("KULLANIM KAPSAMI KAPALI: " + (sonuc.get("metin") or "")
                                         + " Sonuç gösterilmez; analiz düğmeleri bu kapsamı aşmaz.")
            _set_kind(self.lbl_group_state, "warn")
            return
        _set_kind(self.lbl_group_state, "muted")
        self.lbl_group_state.hide()
        g1, g2, comp = sonuc.get("grup_1"), sonuc.get("grup_2"), sonuc.get("karsilastirma")
        no_g2 = g2 is None  # Grup 2 yoksa sütunları gizlenir (değerler çerçevede kalır)
        self.market_model.hidden = MARKET_HIDDEN | ({"g2_sayi", "g2_oran", "g2_bilinmiyor", "fark"} if no_g2 else set())
        self.htft_model.hidden = HTFT_HIDDEN | ({"g2_sayi", "g2_pay", "fark"} if no_g2 else set())
        self.quality_model.hidden = {"g2"} if no_g2 else set()
        self.market_model.set_frame(market_frame(sonuc))
        self.htft_model.set_frame(htft_frame(sonuc))
        self.quality_model.set_frame(quality_frame(sonuc))
        if g1 and g1.get("iy_ms"):
            self.lbl_htft_n.setText(f"Geçerli İY/MS: Grup 1 n={g1['iy_ms']['gecerli']}"
                                    + (f" · Grup 2 n={g2['iy_ms']['gecerli']}" if g2 and g2.get("iy_ms") else "")
                                    + ". Ham kod ev sahibi bakışıdır; 2/1 takımın geri dönüşü anlamına gelmez.")
        if comp:
            o = comp["ortusme"]
            txt = (f"Ortak maç: {o['ortak']} · yalnız Grup 1: {o['yalniz_grup_1']} · yalnız Grup 2: {o['yalniz_grup_2']}")
            if o["ortak"]:
                txt += "\nGruplarda ortak maç var; bağımsız örnekler değildir."
            self.lbl_overlap.setText(txt)
            _set_kind(self.lbl_overlap, "warn" if o["ortak"] else "muted")
        notes = []
        for name, g in (("Grup 1", g1), ("Grup 2", g2)):
            if g is None:
                continue
            if g.get("sonuca_gore_secildi"):
                notes.append(f"{name} geçmiş sonuca göre seçildi: {C.OUTCOME_NOTE}")
            for a in g.get("aciklamalar") or []:
                if a["kod"] != C.SELECTED_BY_OUTCOME:
                    notes.append(f"{name}: {a['metin']}")
            notes.append(f"{name} kapsamı: {g['olay_sayisi']} olay · sezonlar {', '.join(g['sezonlar']) or '-'} · tarih "
                         f"{' – '.join(g['tarih_araligi']) if g.get('tarih_araligi') else '-'}")
        for w in sonuc.get("uyarilar") or []:
            if w["kod"] not in (C.SELECTED_BY_OUTCOME, "ORTUSEN_GRUPLAR"):
                notes.append(w["metin"])
        if comp:
            notes.append(comp["birim"])
        notes.append(A.QUARANTINE_NOTE)
        self.lbl_group_notes.setText("\n".join(dict.fromkeys(notes)))

    # ------------------------------------------------------------ geçmiş ve notlar
    def _show_history(self) -> None:
        rec = self.rec
        if rec is None:
            self.rev_model.set_frame(pd.DataFrame())
            self.run_model.set_frame(pd.DataFrame())
            self.note_model.set_frame(pd.DataFrame())
            self.note_detail.setPlainText("")
            self.rev_detail.setPlainText("")
            self.lbl_hist_state.setText("Önce bir araştırma açın veya kaydedin.")
            self._fill_run_combos([])
            return
        self.lbl_hist_state.setText(f"{rec['tanim']['baslik']} · {len(rec['revizyonlar'])} revizyon · "
                                    f"{len(rec['calistirmalar'])} çalıştırma · {len(rec['notlar'])} not. "
                                    + C.PREREG_NOTE)
        self.rev_model.set_frame(_frame([{**r, "tanim_ozeti": short_hash(r["tanim_ozeti"])} for r in rec["revizyonlar"]],
                                        ["revizyon", "olusturma_utc", "kayit_aninda_onceki_calistirma", "tanim_ozeti"]))
        runs = rec["calistirmalar"]
        self.run_model.set_frame(_frame([{"calistirma_utc": r["calistirma_utc"], "revizyon": r["revizyon"],
                                          "durum": r["durum"], "veri": short_hash(r["veri_ozeti"]),
                                          "sonuc": short_hash(r["sonuc_ozeti"]), "calistirma_id": r["calistirma_id"]}
                                         for r in runs],
                                        ["calistirma_utc", "revizyon", "durum", "veri", "sonuc", "calistirma_id"]))
        self._fill_run_combos(runs)
        self._show_notes()

    def _fill_run_combos(self, runs: list) -> None:
        before = self.cb_run_c.currentData()
        for cb in (self.cb_run_b, self.cb_run_c):
            cur = cb.currentData()
            cb.blockSignals(True)
            cb.clear()
            for r in reversed(runs):
                cb.addItem(f"r{r['revizyon']} · {r['calistirma_utc']} · {r['durum']} · veri "
                           f"{short_hash(r['veri_ozeti'])[:8]}", r["calistirma_id"])
            i = cb.findData(cur) if cur else 0
            cb.setCurrentIndex(max(i, 0) if cb.count() else -1)
            cb.blockSignals(False)
        if self.cb_run_c.currentData() != before:  # yalnızca seçim gerçekten değiştiyse olay seçimi sıfırlanır
            self._stored_sel_changed()
        else:
            self._update_actions()

    def _show_notes(self, *a) -> None:
        notes = (self.rec or {}).get("notlar") or []
        if not self.chk_archived.isChecked():
            notes = [n for n in notes if n["durum"] == "aktif"]
        self.note_model.set_frame(_frame([{"metin": (n["metin"].splitlines() or [""])[0][:80], "surum": n["surum"],
                                           "durum": n["durum"], "mac_kimligi": n["mac_kimligi"] or "",
                                           "gorunum_kaynak": source_short(n["gorunum_kaynak"]) if n["mac_kimligi"] else "",
                                           "olusturma_utc": n["olusturma_utc"], "not_id": n["not_id"]} for n in notes],
                                         ["metin", "surum", "durum", "mac_kimligi", "gorunum_kaynak", "olusturma_utc",
                                          "not_id"]))
        self.note_detail.setPlainText("")

    def _selected_note(self) -> dict | None:
        idx = self.note_view.selectionModel().currentIndex()
        if not idx.isValid() or self.rec is None:
            return None
        nid = self.note_model.frame.iloc[self.note_proxy.mapToSource(idx).row()]["not_id"]
        return next((n for n in self.rec["notlar"] if n["not_id"] == nid), None)

    def _note_selected(self, *a) -> None:
        n = self._selected_note()
        if n is None:
            self.note_detail.setPlainText("")
            return
        lines = [f"Not {n['not_id']} · sürüm {n['surum']} · {n['durum']} · {n['olusturma_utc']}",
                 f"Bağlı maç: {n['mac_kimligi'] or 'yok'}" + (f" · görünüm {source_short(n['gorunum_kaynak'])} · bağlantı "
                                                                f"veri özeti {short_hash(n['veri_ozeti'])}"
                                                                if n["mac_kimligi"] else ""),
                 "", n["metin"], ""]
        for old in reversed(n.get("onceki_surumler") or []):
            lines += [f"— Önceki sürüm {old['surum']} ({old['durum']}, {old['olusturma_utc']}):", old["metin"]]
        lines += ["", C.NOTE_NOTE]
        self.note_detail.setPlainText("\n".join(lines))

    def _selected_run(self) -> str | None:
        idx = self.run_view.selectionModel().currentIndex()
        if not idx.isValid():
            return None
        return str(self.run_model.frame.iloc[self.run_proxy.mapToSource(idx).row()]["calistirma_id"])

    def _rev_selected(self, *a) -> None:
        idx = self.rev_view.selectionModel().currentIndex()
        if not idx.isValid() or self.rec is None:
            self.rev_detail.setPlainText("")
            return
        rev = int(self.rev_model.frame.iloc[self.rev_proxy.mapToSource(idx).row()]["revizyon"])
        if rev == self.rec["revizyon"]:
            self.rev_detail.setPlainText(f"r{rev} (en son)\n" + definition_text(self.rec["tanim"]))
        else:
            self.rev_detail.setPlainText(f"r{rev}: eski revizyon değiştirilemez. Tanımını görmek için bu revizyonla "
                                         "yapılmış saklı çalıştırmayı açın (çalıştırma kaydı tam tanımı içerir).")

    def _hist_verify(self) -> None:
        cid = self._selected_run()
        if not cid:
            self.say("Önce çalıştırma listesinden bir satır seçin.", "warn")
            return
        gs = self.group_shown
        if not (gs and gs["tur"] == "sakli" and gs["kayit"]["calistirma_id"] == cid):
            self.say("Doğrulama gösterilen saklı sonuç için yapılır: önce 'Saklı sonucu aç'.", "warn")
            return
        self.verify(cid)

    def _hist_use_in_events(self) -> None:
        cid = self._selected_run()
        if not cid:
            self.say("Önce çalıştırma listesinden bir satır seçin.", "warn")
            return
        self.rb_stored.setChecked(True)
        i = self.cb_run_c.findData(cid)
        if i >= 0:
            self.cb_run_c.setCurrentIndex(i)
        self.tabs.setCurrentIndex(2)

    def _note_to_editor(self) -> None:
        n = self._selected_note()
        if n is None:
            self.say("Önce bir not seçin.", "warn")
            return
        self.ed_note.setPlainText(n["metin"])

    def _note_ws_ok(self) -> bool:
        if self.ws_path is None or self.rid is None:
            self.say("Not eklemek için önce araştırmayı kaydedin veya açın.", "warn")
            return False
        return True

    def add_note(self, linked: bool) -> None:
        if not self._note_ws_ok():
            return
        text = self.ed_note.toPlainText()
        mac = kaynak = None
        if linked:
            if self.link_match is None:
                self.say("Bağlanacak maç seçilmedi (Olay karşılaştırması sekmesinde bir hücre veya maç seçin).", "warn")
                return
            if not self._need_archive():
                return
            mac, key = self.link_match
            kaynak = key if key else A.MERGED_VIEW
        self._start("not", functools.partial(job_note_add, ws=self.ws_path, ayri=self._separate(), rid=self.rid,
                                             metin=text, mac=mac, archive=self.archive if mac else None, kaynak=kaynak),
                    self._note_done, "Not ekleniyor...", critical=True, ctx={"rid": self.rid, "metin": text})

    def note_new_version(self) -> None:
        n = self._selected_note()
        if n is None or not self._note_ws_ok():
            if n is None:
                self.say("Önce bir not seçin.", "warn")
            return
        text = self.ed_note.toPlainText()
        self._start("not", functools.partial(job_note_update, ws=self.ws_path, ayri=self._separate(), rid=self.rid,
                                             nid=n["not_id"], metin=text, durum=None),
                    self._note_done, "Notun yeni sürümü...", critical=True, ctx={"rid": self.rid, "metin": text})

    def note_archive(self) -> None:
        n = self._selected_note()
        if n is None or not self._note_ws_ok():
            if n is None:
                self.say("Önce bir not seçin.", "warn")
            return
        self._start("not", functools.partial(job_note_update, ws=self.ws_path, ayri=self._separate(), rid=self.rid,
                                             nid=n["not_id"], metin=None, durum="arsivlendi"),
                    self._note_done, "Not arşivleniyor...", critical=True, ctx={"rid": self.rid, "metin": None})

    def _note_done(self, req, res) -> None:
        if not res["ok"]:
            self.say(f"Not kaydedilmedi: {res['error']} Düzenleyicideki metin korunuyor.", "warn")
            return
        if res.get("kayit") is not None and self.rid == req["ctx"]["rid"]:
            self.rec = res["kayit"]
            self._show_history()
        if "liste" in res:
            self.research_list = res["liste"]
            self._show_list()
        if req["ctx"]["metin"] is not None and self.ed_note.toPlainText() == req["ctx"]["metin"]:
            self.ed_note.setPlainText("")
        n = res["yazildi"]
        self.say(f"Not kaydedildi: {n['not_id']} sürüm {n['surum']} ({n['durum']}). Not skoru veya modeli değiştirmez."
                 + (f" Liste yenilenemedi: {res['yenileme_hatasi']}" if res.get("yenileme_hatasi") else ""))

    def note_card(self) -> None:
        n = self._selected_note()
        if n is None or not n.get("mac_kimligi"):
            self.say("Önce maça bağlı bir not seçin.", "warn")
            return
        if self.ws_path is None or not self._need_archive():
            return
        parts = str(n["mac_kimligi"]).split("|", 3)
        if len(parts) != 4:
            self.say("Maç kimliği çözülemedi.", "warn")
            return
        team = parts[2] if self.cb_card_side.currentData() == "home" else parts[3]
        self._start("kart", functools.partial(job_note_card, ws=self.ws_path, archive=self.archive, nid=n["not_id"],
                                              takim=team),
                    self._card_done, "Olay kartı hazırlanıyor...", critical=False,
                    ctx=(self.ws_gen, self.archive_gen, self.rid))

    def _card_done(self, req, res) -> None:
        if self._stale(req, (self.ws_gen, self.archive_gen, self.rid)):
            self.say("Kart sonucu eski seçime ait; gösterilmedi.", "warn")
            return
        if not res["ok"]:
            self.say(f"Olay kartı açılamadı: {res['error']}", "warn")
            return
        from .sequences import card_window

        card = self.card = res["kart"]
        k, e, g, nt = card["kimlik"], card["EVENT_OUTCOME"], card["gorunum"], card["not"]
        lines = [f"{k['takim']} ({'ev' if k['ev_sahibi'] else 'deplasman'}) – {k['rakip']} · {k['tarih']} · {k['lig']} "
                 f"{k['sezon']}",
                 f"İY (ev-dep) {e['iy_ev_dep']} · MS (ev-dep) {e['ms_ev_dep']} · ham İY/MS {raw_code(e['iy_ms_ham']) or 'bilinmiyor'}"
                 f" · takım {e['takim_iy'] or '?'}→{e['takim_ms'] or '?'}",
                 f"Görünüm: {source_short(g.get('kaynak'))} · pencere maçı {g.get('pencere_maci')} · {g.get('pencere_kapsami')}",
                 f"Not bağlantısı veri özeti {short_hash(nt['baglanti_veri_ozeti'])} · güncel {short_hash(nt['guncel_veri_ozeti'])}"
                 + (" — VERİ SÜRÜMÜ DEĞİŞTİ (kart güncel veriyle)" if nt["baglanti_veri_ozeti"] != nt["guncel_veri_ozeti"]
                    else ""),
                 "Geçmiş incelemedir; maç öncesi ekranına taşınmaz."]
        self.card_text.setPlainText("\n".join(lines))
        self.card_text.show()
        frames = []
        for key in ("PRE_EVENT", "POST_EVENT", "RAKIP_PRE_EVENT"):
            _, df = card_window(card, key)
            if not df.empty:
                df.insert(0, "blok", key)
                frames.append(df)
        self.card_model.set_frame(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
        self.card_view.show()
        self.say("Bağlı maçın kartı notun görünümünde açıldı (salt okunur).")

    # ================================================================== olay karşılaştırması
    def _mode_changed(self, *a) -> None:
        stored = self.rb_stored.isChecked()
        self.box_stored.setVisible(stored)
        self.box_explicit.setVisible(not stored)
        self._clear_olay("Seçim yolu değişti; karşılaştırmayı yeniden yapın.")
        self._update_actions()

    def _stored_sel_changed(self, *a) -> None:
        self.cb_team_stored.blockSignals(True)
        self.cb_team_stored.clear()
        self.cb_team_stored.blockSignals(False)
        cid = self.cb_run_c.currentData()
        self.lbl_stored_info.setText("Önce bir araştırma açın ve saklı çalıştırma seçin." if not cid else
                                     "Takım listesi için 'Grup takımlarını yükle'.")
        if self.rb_stored.isChecked():
            self._clear_olay("Çalıştırma veya grup değişti; karşılaştırma temizlendi.")
        self._update_actions()

    def load_stored_teams(self) -> None:
        cid = self.cb_run_c.currentData()
        if not cid or self.ws_path is None:
            self.say("Saklı çalıştırma seçilmedi.", "warn")
            return
        if not self._need_archive():
            return
        grup = self.cb_group_c.currentData()
        self._start("takimlar", functools.partial(job_stored_teams, ws=self.ws_path, cid=cid, grup=grup,
                                                  views=self.views),
                    self._stored_teams_done, "Grup takımları...", critical=False,
                    ctx=(self.ws_gen, self.archive_gen, cid, grup))

    def _stored_teams_done(self, req, res) -> None:
        if self._stale(req, (self.ws_gen, self.archive_gen, self.cb_run_c.currentData(), self.cb_group_c.currentData())):
            self.say("Takım listesi eski seçime ait; gösterilmedi.", "warn")
            return
        if not res["ok"]:
            self.lbl_stored_info.setText(f"Takımlar yüklenemedi: {res['error']}")
            return
        if res["kapali"]:
            self.lbl_stored_info.setText("KULLANIM KAPSAMI KAPALI: çalıştırmanın kaynağı ("
                                         + ", ".join(res["kapali"]) + ") tarihsel analize kapalı; olay gösterilmez.")
            return
        self.cb_team_stored.blockSignals(True)
        self.cb_team_stored.clear()
        for t in res["takimlar"]:
            self.cb_team_stored.addItem(t, t)
        if res["varsayilan"]:
            i = self.cb_team_stored.findData(res["varsayilan"])
            if i >= 0:
                self.cb_team_stored.setCurrentIndex(i)
        self.cb_team_stored.blockSignals(False)
        self.lbl_stored_info.setText(f"Görünüm {source_short(res['kaynak'])} · grup olayı {res.get('olay_sayisi', 0)} · "
                                     f"takım {len(res['takimlar'])} · lig {', '.join(res['ligler']) or '-'}. Saklı "
                                     "çalıştırmanın kendi görünümü ve olay kümesi kullanılır.")
        self._update_lig_options(res["ligler"] if len(res["ligler"]) > 1 else [])
        self._update_actions()

    def _explicit_team_changed(self, *a) -> None:
        if self.pick_model.picked:
            n = len(self.pick_model.picked)
            self.pick_model.clear_picked()
            self.say(f"Takım değişti: açık seçimdeki {n} olay temizlendi (başka takımın maçları).", "warn")
        self.pick_model.set_frame(pd.DataFrame(columns=PickModel.COLUMNS))
        self._clear_olay("Takım değişti; karşılaştırma temizlendi.")
        self._update_actions()

    def _explicit_season_changed(self, *a) -> None:
        self.pick_model.set_frame(pd.DataFrame(columns=PickModel.COLUMNS))
        self.lbl_explicit_state.setText("Sezon filtresi değişti: 'Maçları listele' ile tabloyu yenileyin (seçim korunur).")

    def list_explicit(self) -> None:
        if not self._need_archive():
            return
        key = self._source_key()
        inf = self.info.get(key) or {}
        if inf.get("kapali"):
            self.lbl_explicit_state.setText("Kapalı kaynak: bu görünümde maç yok; olay karşılaştırması yapılamaz.")
            return
        team = self.cb_team_explicit.currentText().strip()
        if not team or team not in (inf.get("takimlar") or []):
            self.say("Takımı listeden seçin (yazılan metin yalnızca listede arar).", "warn")
            return
        season = self.cb_season_explicit.currentData()
        self._start("liste", functools.partial(job_explicit_list, archive=self.archive, view=self.views[key],
                                               takim=team, sezon=season),
                    self._explicit_list_done, "Maçlar listeleniyor...", critical=False,
                    ctx=(self.archive_gen, key, team, season))

    def _explicit_list_done(self, req, res) -> None:
        cur = (self.archive_gen, self._source_key(), self.cb_team_explicit.currentText().strip(),
               self.cb_season_explicit.currentData())
        if self._stale(req, cur):
            self.say("Maç listesi eski seçime ait; gösterilmedi.", "warn")
            return
        if not res["ok"]:
            self.lbl_explicit_state.setText(f"Liste alınamadı: {res['error']}")
            return
        df = res["satirlar"]
        self.pick_model.set_frame(df)
        self.lbl_explicit_state.setText(f"{len(df)} maç listelendi. Olay olarak işaretlemek için 'Seç' kutusunu kullanın."
                                        if len(df) else "Eşleşen maç yok.")
        self._picked_changed()

    def clear_selection(self) -> None:
        n = len(self.pick_model.picked)
        self.pick_model.clear_picked()
        self.say(f"Açık seçim temizlendi ({n} olay).")

    def _picked_changed(self) -> None:
        picked = self.pick_model.picked
        shown = set(self.pick_model.frame["mac_kimligi"]) if len(self.pick_model.frame) else set()
        hidden = len(picked - shown)
        self.lbl_picked.setText(f"Seçili olay: {len(picked)}" + (f" ({hidden} tanesi bu listede görünmüyor)" if hidden
                                                                 else ""))
        if self.rb_explicit.isChecked() and self.olay_shown is not None \
                and set(self.olay_shown["p"].get("olaylar") or ()) != picked:
            self._clear_olay("Olay seçimi değişti; karşılaştırmayı yeniden yapın.")
        self._update_actions()

    def _pick_row_changed(self, cur, prev) -> None:
        if not cur.isValid():
            return
        mid = self.pick_model.mac_id(self.pick_proxy.mapToSource(cur).row())
        self._set_link(mid, self._source_key())

    def _set_link(self, mid: str, key) -> None:
        self.link_match = (mid, key)
        self.lbl_link.setText(f"Bağlanacak maç: {mid} · görünüm {source_short(key)}")

    def _olay_params(self, offset: int) -> dict | None:
        """Ana iş parçacığında okunan ve işe kopya giden istek parametreleri."""
        p = {"once": self.cb_once.currentData(), "sonra": self.cb_sonra.currentData(), "limit": self.sp_limit.value(),
             "offset": offset, "lig": self.cb_lig.currentData(), "archive_gen": self.archive_gen}
        if self.rb_stored.isChecked():
            p.update({"tur": "kayitli", "cid": self.cb_run_c.currentData(), "grup": self.cb_group_c.currentData(),
                      "takim": self.cb_team_stored.currentData(), "ws_gen": self.ws_gen})
            if not p["cid"] or not p["takim"]:
                return None
        else:
            p.update({"tur": "acik", "kaynak": self.cb_source.currentData() or A.MERGED_VIEW,
                      "takim": self.cb_team_explicit.currentText().strip(),
                      "olaylar": tuple(sorted(self.pick_model.picked))})
            if not p["takim"] or not p["olaylar"]:
                return None
        return p

    @staticmethod
    def _olay_ctx(p: dict | None):
        return None if p is None else {k: v for k, v in p.items() if k != "offset"}

    def compare_events(self, offset: int = 0) -> None:
        if not self._need_archive():
            return
        p = self._olay_params(offset)
        if p is None:
            self.say("Önce takım ve olay seçin (saklı yolda çalıştırma/grup/takım; açık yolda tablodan olaylar).", "warn")
            return
        # Kapalı kaynakta da istek servise gider: kapsam korumasına servis karar verir (arayüz atlatmaz)
        self._start("olay", functools.partial(job_olay, ws=self.ws_path, archive=self.archive, p=dict(p)),
                    self._olay_done, "Olay karşılaştırması...", critical=False, ctx=self._olay_ctx(p))

    def _page(self, direction: int) -> None:
        if self.olay_shown is None:
            return
        pg = self.olay_shown["sonuc"].get("sayfalama") or {}
        if direction > 0:
            nxt = pg.get("sonraki_offset")
            if nxt is None:
                return
        else:
            nxt = max(0, int(pg.get("offset", 0)) - int(pg.get("limit", O.DEFAULT_LIMIT)))
        cur = self._olay_params(nxt)
        if self._olay_ctx(cur) != self._olay_ctx(self.olay_shown["p"]):
            self.say("Seçim veya pencere değişti; önce yeniden karşılaştırın.", "warn")
            return
        self.compare_events(nxt)

    def _olay_done(self, req, res) -> None:
        current = self._olay_ctx(self._olay_params(0))
        if self._stale(req, current):
            self.say("Karşılaştırma sonucu gösterilmedi: istek sırasında kaynak, takım, olay seçimi veya pencere değişti. "
                     "Yeniden karşılaştırın.", "warn")
            return
        if not res["ok"]:
            self._clear_olay(f"Karşılaştırma yapılamadı: {res['error']}")
            _set_kind(self.lbl_olay_state, "warn")
            self.say(f"Olay karşılaştırması yapılamadı: {res['error']}", "warn")
            return
        p = dict(req["ctx"], offset=res["sonuc"].get("sayfalama", {}).get("offset", 0))
        self._show_olay({"p": p, "sonuc": res["sonuc"]})

    def _window_changed(self, *a) -> None:
        if self.olay_shown is not None:
            self._clear_olay("Pencere veya sayfa seçeneği değişti; olay seçimi korunuyor. Yeniden karşılaştırın.")
        self._update_actions()

    def _olay_context_changed(self, *a) -> None:
        if self.olay_shown is not None:
            self._clear_olay("Seçim değişti; karşılaştırma temizlendi.")
        self._update_actions()

    def _clear_olay(self, why: str = "") -> None:
        self.olay_shown = None
        if not hasattr(self, "matrix"):
            return
        self.matrix.clear()
        for m in (self.summary_model, self.win_model, self.invalid_model, self.interval_model):
            m.set_frame(pd.DataFrame())
        self.matrix_detail.setPlainText("")
        self.lbl_summary.setText("Bu sayfadaki olayların özeti")
        self.lbl_windows.setText("")
        self.lbl_invalid.setText("")
        self.lbl_olay_notes.setText("")
        self.lbl_page.setText("")
        self.tech_c.setPlainText("")
        self.lbl_olay_state.setText(why or "Henüz karşılaştırma yok.")
        _set_kind(self.lbl_olay_state, "muted")
        self._update_actions()

    def _show_olay(self, shown: dict) -> None:
        self._clear_olay()
        self.olay_shown = shown
        r = shown["sonuc"]
        durum = r.get("durum")
        sel = r.get("secim") or {}
        head = (f"Durum: {durum} · seçim yolu {'saklı çalıştırma grubu' if sel.get('tur') == O.MODE_STORED else 'açık liste'}"
                f" · görünüm {source_short((r.get('gorunum') or {}).get('kaynak'))}")
        if sel.get("tur") == O.MODE_STORED:
            head += f" · çalıştırma {sel.get('calistirma_id')} (r{sel.get('revizyon')}, Grup {sel.get('grup')})"
        if durum != "TAMAMLANDI":
            self.lbl_olay_state.setText(head + "\n" + (r.get("metin") or ""))
            _set_kind(self.lbl_olay_state, "warn")
            self.tech_c.setPlainText(C.to_json({k: r.get(k) for k in ("secim", "durum", "sakli_veri_ozeti",
                                                                       "guncel_veri_ozeti", "kapali_kaynaklar")}))
            return
        pg = r["sayfalama"]
        opts = r["secenekler"]
        events = r["olaylar"]
        self.matrix.set_result(events, opts["once"], opts["sonra"])
        self.lbl_olay_state.setText(head + f" · takım {r['takim']['ad']} · lig {r['takim'].get('lig') or '-'}")
        start = pg["offset"] + 1 if pg["bu_sayfada"] else 0
        self.lbl_page.setText(f"Olay {start}–{pg['offset'] + pg['bu_sayfada']} / toplam aday {pg['toplam_aday']} "
                              f"(sayfa boyutu {pg['limit']}, en çok {O.MAX_LIMIT})")
        t = r["toplu"]
        self.lbl_summary.setText(f"Bu sayfadaki olayların özeti ({t['olay_sayisi']} olay; toplam aday "
                                 f"{pg['toplam_aday']}) — bütün adayların özeti değildir")
        self.summary_model.set_frame(_frame([stats_row(f"Önceki {opts['once']} (tekil kayıt)", t["onceki"]),
                                             stats_row("Olaylar (t0)", t["olaylar"]),
                                             stats_row(f"Sonraki {opts['sonra']} (tekil kayıt)", t["sonraki"])],
                                            ["blok", "kayit", "kullanilabilir", "bilinmeyen", "gbm", "A", "B", "C",
                                             "gol", "iy_gol", "iiy_gol"]))
        st = t["pencere_durumlari"]

        def states(d):
            return ", ".join(f"{STATE_SHORT.get(k, k)} ({k}): {n}" for k, n in d.items()) or "-"

        self.lbl_windows.setText(f"Tam önceki pencere {t['tam_onceki_pencere']}/{t['olay_sayisi']} · tam sonraki pencere "
                                 f"{t['tam_sonraki_pencere']}/{t['olay_sayisi']}\nÖnceki pencere durumları: "
                                 f"{states(st['onceki'])}\nSonraki pencere durumları: {states(st['sonraki'])}\n"
                                 f"{t['not']}")
        rows = []
        for e in events:
            w1, w2 = e["onceki"], e["sonraki"]
            rows.append({"sira": e["sira"], "olay": f"{e['tarih']} · {e['takim_perspektifi']['rakip']} "
                                                    f"({e['takim_perspektifi']['yer']})",
                         "onceki": f"{w1['gozlenen_kayit']}/{w1['istenen_konum']} · {w1['durum']} — {w1['durum_aciklama']}",
                         "sonraki": f"{w2['gozlenen_kayit']}/{w2['istenen_konum']} · {w2['durum']} — {w2['durum_aciklama']}",
                         "neden": "; ".join(x["metin"] for x in w2.get("sonraki_kayit_yok") or []),
                         "ortusme": len(e.get("baska_olayin_penceresinde") or [])})
        self.win_model.set_frame(_frame(rows, ["sira", "olay", "onceki", "sonraki", "neden", "ortusme"]))
        self.invalid_model.set_frame(_frame([{k: x.get(k) for k in ("olay_kimligi", "neden", "metin")}
                                             for x in r["gecersiz_olaylar"]], ["olay_kimligi", "neden", "metin"]))
        oz = r.get("gecersiz_ozeti") or {}
        parts = [f"{INVALID_LABELS.get(k, k)} ({k}): {n}" for k, n in oz.items()]
        self.lbl_invalid.setText(("Hesaplanmayan olay özeti: " + ", ".join(parts)) if parts else
                                 "Hesaplanmayan olay yok.")
        self.interval_model.set_frame(_frame([{**{k: x.get(k) for k in ("olay_kimligi", "onceki_secili_olay",
                                                                          "takvim_gunu", "arsivde_gozlenen_kayit",
                                                                          "sureklilik_durumu")},
                                               "isaretler": "; ".join(f["metin"] for f in x.get("isaretler") or [])}
                                              for x in r.get(O.INTERVAL_KEY) or []],
                                             ["olay_kimligi", "onceki_secili_olay", "takvim_gunu",
                                              "arsivde_gozlenen_kayit", "sureklilik_durumu", "isaretler"]))
        o = r["ortusme"]
        notes = [f"Pencerelerde benzersiz maç {o['benzersiz_mac']} (önceki {o['onceki_benzersiz']}, sonraki "
                 f"{o['sonraki_benzersiz']}, ikisinde ortak {o['onceki_ve_sonraki_ortak']}); birden çok pencerede "
                 f"{o['birden_fazla_pencerede_mac']} maç. {o['not']}"]
        notes += [w["metin"] for w in r.get("uyarilar") or []]
        notes += [a["metin"] for a in r.get("aciklamalar") or []]
        pk = r.get("pencere_kapsami") or {}
        if pk.get("not"):
            notes.append(pk["not"])
        self.lbl_olay_notes.setText("\n".join(dict.fromkeys(notes)))
        self.tech_c.setPlainText(C.to_json({k: r.get(k) for k in ("secim", "veri", "sayfalama", "takim",
                                                                   "kimlik_incelemesi", "pencere_kapsami", "surumler",
                                                                   "sonuc_ozeti")}))
        if not events:
            self.lbl_olay_state.setText(head + "\nBu sayfada hesaplanan olay yok (eşleşen olay yok veya bütün olaylar "
                                               "geçersiz; nedenler aşağıda).")
        self._update_actions()

    def _matrix_reset(self) -> None:
        self.matrix_view.resizeColumnsToContents()

    def _matrix_cell(self, cur, prev) -> None:
        if not cur.isValid() or not self.matrix.events:
            return
        e, p = self.matrix.cell(cur.row(), cur.column())
        self.matrix_detail.setPlainText(position_detail(e, p))
        if p is not None and p.get("durum") == "GOZLENDI":
            key = (self.olay_shown or {}).get("sonuc", {}).get("gorunum", {}).get("kaynak")
            self._set_link(p["olay_kimligi"], key)

    # ================================================================== düğme durumları
    def _update_actions(self, *a) -> None:
        if not hasattr(self, "btn_note_card"):
            return
        busy = self.ctl.busy
        has_ar, has_ws, has_r = self.archive is not None, self.ws_path is not None, self.rid is not None
        dirty = self.dirty
        err = self.form_error() is not None
        stored_shown = bool(self.group_shown and self.group_shown["tur"] == "sakli")
        for btn, on in ((self.btn_open_archive, True), (self.btn_open_ws, True), (self.btn_create_ws, True),
                        (self.btn_new, has_ws), (self.btn_open_research, has_ws and bool(self.research_list)),
                        (self.btn_save, has_ws and not err and (self.rid is None or dirty)),
                        (self.btn_discard, dirty), (self.btn_preview, has_ar and not err),
                        (self.btn_run, has_ar and has_r and not dirty),
                        (self.btn_open_run, has_ws and self.cb_run_b.count() > 0),
                        (self.btn_verify, has_ar and stored_shown),
                        (self.btn_stored_teams, has_ar and has_ws and self.cb_run_c.count() > 0),
                        (self.btn_list, has_ar), (self.btn_clear_pick, bool(self.pick_model.picked)),
                        (self.btn_compare, has_ar and self._olay_params(0) is not None),
                        (self.btn_prev, self.olay_shown is not None
                         and (self.olay_shown["sonuc"].get("sayfalama") or {}).get("offset", 0) > 0),
                        (self.btn_next, self.olay_shown is not None
                         and (self.olay_shown["sonuc"].get("sayfalama") or {}).get("sonraki_offset") is not None),
                        (self.btn_hist_open, has_ws and self.run_model.rowCount() > 0),
                        (self.btn_hist_verify, has_ar and self.run_model.rowCount() > 0),
                        (self.btn_hist_olay, self.run_model.rowCount() > 0),
                        (self.btn_note_add, has_ws and has_r), (self.btn_note_match, has_ws and has_r and has_ar),
                        (self.btn_note_load, self.note_model.rowCount() > 0),
                        (self.btn_note_version, has_ws and has_r and self.note_model.rowCount() > 0),
                        (self.btn_note_archive, has_ws and has_r and self.note_model.rowCount() > 0),
                        (self.btn_note_card, has_ws and has_ar and self.note_model.rowCount() > 0)):
            btn.setEnabled(bool(on) and not busy)
        self.list_view.setEnabled(not busy)

    # ================================================================== sayfa
    def on_show(self) -> None:
        """Açılışta hiçbir şey okunmaz veya yazılmaz (yalnızca ortak gün denetimi)."""
        super().on_show()

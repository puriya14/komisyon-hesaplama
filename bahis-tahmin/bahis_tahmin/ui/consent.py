"""Veri kaynağı kullanım koşulları onayı ve kişisel kullanım beyanı. Onay verilmeden geçmiş maç verisi indirilmez;
beyan verilmeden (lisans belgesi doğrulanamayan kaynağın verisiyle) model eğitilmez ve tahmin gösterilmez."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from ..data.source_registry import DECLARABLE, IMPLEMENTED, SOURCES


class ConsentDialog(QDialog):
    """Onay gerektiren her kaynak için koşul özeti, indirme onayı ve (VERI-01) ayrı kişisel kullanım beyanı."""

    def __init__(self, consent: dict, parent=None, declarations: dict | None = None):
        super().__init__(parent)
        declarations = declarations or {}
        self.setWindowTitle("Veri kaynakları: kullanım koşulları")
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Uygulama geçmiş maç verisini aşağıdaki kaynaklardan <b>sizin bilgisayarınıza</b> indirir. Bu kaynakların "
            "yeniden kullanım ve model eğitimi koşulları lisans belgesiyle doğrulanamadı.<br>"
            "<b>1. kutu</b> yalnızca verilerin bilgisayarınıza indirilmesini onaylar.<br>"
            "<b>2. kutu (kişisel kullanım beyanı)</b> verileri yalnızca kendi kişisel ve ticari olmayan analiziniz, bu "
            "bilgisayarda model eğitimi ve tahminleriniz için kullanacağınızı beyan eder. Beyan olmadan uygulama bu "
            "verilerle model eğitmez ve tahmin göstermez. Beyan ticari kullanım veya yeniden dağıtım hakkı vermez; "
            "kaynağın koşulları geçerlidir ve sorumluluk size aittir. "
            "Onay ve beyanı bu pencereden (Veri sayfası) istediğiniz zaman geri alabilirsiniz."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        lay.addWidget(intro)
        self.boxes: dict[str, QCheckBox] = {}
        self.decl_boxes: dict[str, QCheckBox] = {}
        for key in IMPLEMENTED:
            s = SOURCES[key]
            if not s.requires_consent:
                continue
            info = QLabel(
                f"<b>{s.name}</b> — <a href='{s.terms_url}'>koşullar</a><br>{s.license_summary}<br>"
                f"<i>Model eğitimi:</i> {s.model_training} · <i>Ticari kullanım:</i> {s.commercial_use}"
            )
            info.setWordWrap(True)
            info.setTextFormat(Qt.RichText)
            info.setOpenExternalLinks(True)
            lay.addWidget(info)
            box = QCheckBox(f"1. {s.name} koşullarını okudum; verilerin bu bilgisayara indirilmesini onaylıyorum.")
            box.setChecked(key in consent)
            self.boxes[key] = box
            lay.addWidget(box)
            if key in DECLARABLE:
                decl = QCheckBox(
                    f"2. Kişisel kullanım beyanı: {s.name} verilerini yalnızca kişisel ve ticari olmayan amaçla (kendi "
                    "analizim, bu bilgisayarda model eğitimi ve tahmin) kullanacağımı, paylaşmayacağımı ve yeniden "
                    "dağıtmayacağımı beyan ederim.")
                decl.setStyleSheet("margin-left: 22px;")
                decl.setChecked(key in consent and key in declarations)
                self.decl_boxes[key] = decl
                lay.addWidget(decl)
                box.toggled.connect(lambda on, d=decl: self._sync(d, on))
                self._sync(decl, box.isChecked())
        free = [SOURCES[k].name for k in IMPLEMENTED if not SOURCES[k].requires_consent]
        note = QLabel(f"Onay gerektirmeyen (açık lisanslı) kaynaklar: {', '.join(free)} — yalnızca fikstür yedeği.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    @staticmethod
    def _sync(decl: QCheckBox, download_ok: bool) -> None:
        """Beyan yalnızca indirme onayı işaretliyken verilebilir; onay kaldırılınca beyan da kalkar."""
        if not download_ok:
            decl.setChecked(False)
        decl.setEnabled(download_ok)
        decl.setToolTip("" if download_ok else "Önce indirme onayını (1. kutu) işaretleyin.")

    def selected(self) -> list[str]:
        return [k for k, b in self.boxes.items() if b.isChecked()]

    def declared(self) -> list[str]:
        return [k for k, b in self.decl_boxes.items() if b.isChecked() and self.boxes[k].isChecked()]


def ask_consent(controller, parent=None) -> bool:
    """Diyaloğu gösterir, onayları ve beyanları kaydeder/geri alır. Geçmiş verisi için en az bir onay varsa True."""
    s = controller.settings
    dlg = ConsentDialog(s.source_consent, parent, s.kisisel_kullanim)
    if dlg.exec() != QDialog.Accepted:
        return False
    apply_consent(controller, dlg.selected(), dlg.declared(), list(dlg.boxes))
    return not controller.needs_consent()


def ask_consent_before_update(controller, parent=None) -> bool:
    """Güncellemeden önce pencere. Güncelleme yapılmayacaksa (Vazgeç veya geçmiş veri onayı yok) ama beyanlar
    değiştiyse tahminler yeni haklarla hemen yeniden değerlendirilir (güncelleme yapılacaksa bunu güncelleme yapar)."""
    before = dict(controller.settings.declarations())
    ok = ask_consent(controller, parent)
    if not ok and controller.settings.declarations() != before:
        controller.declarations_changed(added=False)
    return ok


NOT_UPDATED_TEXT = ("Onay penceresi kaydedilmedi veya geçmiş veri kaynağı onaylanmadı; veri indirilmedi. Tahmin için "
                    "kaynak onayı ve kişisel kullanım beyanı gerekir.")


def apply_consent(controller, chosen, declared, keys) -> bool:
    """Penceredeki seçimleri uygular. Beyan değiştiyse True (tahminler yeniden değerlendirilmeli)."""
    s = controller.settings
    chosen, declared = set(chosen), set(declared)
    before = set(s.declarations())
    for key in keys:
        if key in chosen and key not in s.source_consent:
            controller.record_consent([key])
        elif key not in chosen and key in s.source_consent:
            controller.revoke_consent(key)
    for key in keys:
        if key in declared and key not in s.kisisel_kullanim:
            controller.record_declaration([key])
        elif key not in declared and key in s.kisisel_kullanim:
            controller.revoke_declaration(key)
    controller.mark_consent_reviewed()
    return set(s.declarations()) != before

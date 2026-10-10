"""Veri kaynağı kullanım koşulları onayı. Onay verilmeden geçmiş maç verisi indirilmez."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from ..data.source_registry import IMPLEMENTED, SOURCES


class ConsentDialog(QDialog):
    """Onay gerektiren her kaynak için koşul özeti ve ayrı onay kutusu gösterir."""

    def __init__(self, consent: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Veri kaynakları: kullanım koşulları")
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Uygulama geçmiş maç verisini aşağıdaki kaynaklardan <b>sizin bilgisayarınıza</b> indirir. Bu kaynakların "
            "yeniden kullanım ve model eğitimi koşulları açıkça doğrulanamadı. Koşulları kaynağın sitesinde okuyup "
            "verileri yalnızca kişisel, ticari olmayan analiz için kullanmayı kabul ediyorsanız ilgili kutuyu işaretleyin. "
            "Onay vermediğiniz kaynaktan veri indirilmez; onayı Veri sayfasından geri alabilirsiniz."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        lay.addWidget(intro)
        self.boxes: dict[str, QCheckBox] = {}
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
            box = QCheckBox(f"{s.name} koşullarını okudum; kişisel ve ticari olmayan kullanım için onaylıyorum.")
            box.setChecked(key in consent)
            self.boxes[key] = box
            lay.addWidget(box)
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

    def selected(self) -> list[str]:
        return [k for k, b in self.boxes.items() if b.isChecked()]


def ask_consent(controller, parent=None) -> bool:
    """Diyaloğu gösterir, onayları kaydeder/geri alır. Geçmiş verisi için en az bir onay varsa True."""
    dlg = ConsentDialog(controller.settings.source_consent, parent)
    if dlg.exec() != QDialog.Accepted:
        return False
    chosen = set(dlg.selected())
    for key in dlg.boxes:
        if key in chosen and key not in controller.settings.source_consent:
            controller.record_consent([key])
        elif key not in chosen and key in controller.settings.source_consent:
            controller.revoke_consent(key)
    return not controller.needs_consent()

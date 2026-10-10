"""assets/icon.ico ve assets/icon.png dosyalarını üretir (bir kez çalıştırmak yeterli)."""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen  # noqa: E402

SIZES = [16, 24, 32, 48, 64, 128, 256]


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256.0
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#0e1217"))
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 52 * s, 52 * s)
    # Yükselen sütunlar (veri) - mavi tonlar
    bars = [(48, 150, 70), (98, 120, 100), (148, 80, 140)]
    for x, top, h in bars:
        p.setBrush(QColor("#3987e5"))
        p.drawRoundedRect(QRectF(x * s, top * s, 36 * s, (220 - top) * s), 8 * s, 8 * s)
    # Yeşil trend çizgisi ve top
    pen = QPen(QColor("#22c55e"), max(1.5, 14 * s))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    path = QPainterPath(QPointF(40 * s, 130 * s))
    path.lineTo(110 * s, 92 * s)
    path.lineTo(150 * s, 112 * s)
    path.lineTo(200 * s, 58 * s)
    p.drawPath(path)
    p.setPen(QPen(QColor("#0e1217"), max(1.0, 6 * s)))
    p.setBrush(QColor("#f0efec"))
    p.drawEllipse(QPointF(200 * s, 58 * s), 26 * s, 26 * s)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def main() -> None:
    QGuiApplication(sys.argv)
    out = Path(__file__).resolve().parents[1] / "assets"
    out.mkdir(exist_ok=True)
    blobs = [png_bytes(render(sz)) for sz in SIZES]
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries = b""
    for sz, blob in zip(SIZES, blobs):
        dim = 0 if sz >= 256 else sz
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    (out / "icon.ico").write_bytes(header + entries + b"".join(blobs))
    render(256).save(str(out / "icon.png"))
    print("ok", out / "icon.ico")


if __name__ == "__main__":
    main()

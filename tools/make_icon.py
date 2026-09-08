"""Package the generated artwork as a multi-resolution Windows ICO."""
from pathlib import Path
import struct
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

root = Path(__file__).resolve().parents[1]
source = QImage(str(root / 'assets/subtitle-avatar.png'))
if source.isNull():
    raise SystemExit('Cannot load avatar artwork')
sizes = [16, 24, 32, 48, 64, 128, 256]
images = []
for size in sizes:
    scaled = source.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    assert scaled.save(buffer, 'PNG')
    images.append(bytes(buffer.data()))
offset = 6 + 16 * len(sizes)
headers = []
for size, data in zip(sizes, images):
    headers.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
    offset += len(data)
(root / 'assets/subtitle-avatar.ico').write_bytes(
    struct.pack('<HHH', 0, 1, len(sizes)) + b''.join(headers) + b''.join(images))
print('Created ICO with 7 resolutions')

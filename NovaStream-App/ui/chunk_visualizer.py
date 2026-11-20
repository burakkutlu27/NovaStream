"""
NovaStream Çoklu Bağlantı (Chunk) Blok Görselleştirici
Her bir paralel iş parçacığının indirdiği bayt bloklarını teknik hassasiyetle çizen bileşen.
"""

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QFont
from PyQt6.QtWidgets import QWidget


class ChunkVisualizer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []
        self.setMinimumHeight(84)

    def set_segments(self, segments_data):
        self.segments = segments_data or []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Dış çerçeve
        bg_rect = QRectF(0, 0, w, h)
        painter.setBrush(QColor(22, 24, 29))
        painter.setPen(QPen(QColor(35, 37, 43), 1))
        painter.drawRoundedRect(bg_rect, 4, 4)

        if not self.segments:
            painter.setPen(QColor(108, 114, 125))
            font = QFont("Monospace")
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, "Tek Kanallı İndirme veya Akış Modu")
            return

        num_segs = len(self.segments)
        padding = 6
        avail_w = w - (2 * padding)
        avail_h = h - (2 * padding)

        if num_segs <= 8:
            cols = num_segs
            rows = 1
        elif num_segs <= 16:
            cols = 8
            rows = 2
        else:
            cols = 8
            rows = (num_segs + 7) // 8

        gap_x = 3
        gap_y = 4
        cell_w = (avail_w - (gap_x * (cols - 1))) / cols
        cell_h = (avail_h - (gap_y * (rows - 1))) / rows

        font = QFont("Monospace")
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)

        for i, seg in enumerate(self.segments):
            r = i // cols
            c = i % cols

            x = padding + c * (cell_w + gap_x)
            y = padding + r * (cell_h + gap_y)

            cell_rect = QRectF(x, y, cell_w, cell_h)

            # Hücre arka planı
            painter.setBrush(QColor(31, 33, 39))
            painter.setPen(QPen(QColor(42, 45, 53), 1))
            painter.drawRoundedRect(cell_rect, 2, 2)

            # Doluluk çubuğu
            pct = seg.get("percent", 0.0) / 100.0
            pct = max(0.0, min(1.0, pct))
            fill_w = cell_w * pct

            if fill_w > 0:
                fill_rect = QRectF(x, y, fill_w, cell_h)
                painter.setBrush(QBrush(QColor(37, 99, 235)))  # Solid Cobalt Blue
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(fill_rect, 2, 2)

            # Metin
            painter.setPen(QColor(228, 230, 235))
            label = f"{i + 1}:{int(seg.get('percent', 0))}%"
            painter.drawText(cell_rect, Qt.AlignmentFlag.AlignCenter, label)

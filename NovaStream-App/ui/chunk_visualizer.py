"""
NovaStream bağlantı haritası: parçalı HTTP indirmesinde her bağlantının ilerlemesini çizer.
Renkler ui/theme.py token'larından gelir.
"""

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QBrush, QPen
from PyQt6.QtWidgets import QWidget

from ui import theme


class ChunkVisualizer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []
        self.setMinimumHeight(72)

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
        painter.setBrush(theme.color("surface"))
        painter.setPen(QPen(theme.color("border"), 1))
        painter.drawRoundedRect(bg_rect.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        if not self.segments:
            painter.setPen(theme.color("text3"))
            painter.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, "Tek bağlantılı indirme")
            return

        num_segs = len(self.segments)
        padding = 8
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

        font = painter.font()
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.5))
        painter.setFont(font)

        for i, seg in enumerate(self.segments):
            r = i // cols
            c = i % cols

            x = padding + c * (cell_w + gap_x)
            y = padding + r * (cell_h + gap_y)

            cell_rect = QRectF(x, y, cell_w, cell_h)

            # Hücre arka planı
            painter.setBrush(theme.color("track"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(cell_rect, 3, 3)

            # Doluluk çubuğu
            pct = seg.get("percent", 0.0) / 100.0
            pct = max(0.0, min(1.0, pct))
            fill_w = cell_w * pct

            label = f"{int(seg.get('percent', 0))} %"
            painter.setPen(theme.color("text"))
            painter.drawText(cell_rect, Qt.AlignmentFlag.AlignCenter, label)

            # Dolgunun üstüne düşen kısım vurgu rengine uygun metin rengiyle yeniden çizilir;
            # tek renk metin, dolu ve boş zeminin birinde okunaksız kalıyordu
            if fill_w > 0:
                fill_rect = QRectF(x, y, fill_w, cell_h)
                painter.save()
                painter.setClipRect(fill_rect)
                painter.setBrush(QBrush(theme.color("accent")))
                painter.drawRoundedRect(fill_rect, 3, 3)
                painter.setPen(theme.color("on_accent"))
                painter.drawText(cell_rect, Qt.AlignmentFlag.AlignCenter, label)
                painter.restore()
                painter.setPen(Qt.PenStyle.NoPen)

"""
NovaStream indirme ayrıntı penceresi: canlı ilerleme, aşama, hata nedeni ve bağlantı haritası.
"""

import os
import subprocess
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QFrame
)
from core.engine import format_bytes, format_duration
from ui import theme
from ui.chunk_visualizer import ChunkVisualizer
from ui.display import STATUS_LABELS, eta_text, split_stage_speed


def _label(text="", role=None):
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    return lbl


class ProgressDialog(QDialog):
    def __init__(self, task, queue_manager, parent=None):
        super().__init__(parent)
        self.task = task
        self.queue_manager = queue_manager
        self.setWindowTitle(f"İndiriliyor: {task.filename}")
        self.setMinimumWidth(560)
        self.init_ui()
        self.update_data(task)
        theme.notifier().changed.connect(self._refresh_icons)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(24, 22, 24, 20)

        self.title_lbl = _label(self.task.filename, "title")
        self.title_lbl.setWordWrap(True)
        layout.addWidget(self.title_lbl)

        # Durum noktası + durum/aşama metni
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.status_dot = QLabel()
        self.status_lbl = _label("", "muted")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_lbl)
        status_row.addStretch()
        layout.addLayout(status_row)
        layout.addSpacing(10)

        # Büyük yüzde + boyut
        hero_row = QHBoxLayout()
        self.pct_lbl = _label("", "hero")
        self.size_lbl = _label("", "muted")
        hero_row.addWidget(self.pct_lbl)
        hero_row.addStretch()
        hero_row.addWidget(self.size_lbl, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(hero_row)

        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setTextVisible(False)
        self.prog_bar.setProperty("size", "large")
        layout.addWidget(self.prog_bar)
        layout.addSpacing(10)

        # Hız · Kalan · Süre: başlık küçük ve sönük, değer okunaklı
        meta_row = QHBoxLayout()
        meta_row.setSpacing(28)
        self.speed_val = self._meta(meta_row, "Hız")
        self.eta_val = self._meta(meta_row, "Kalan")
        self.elapsed_val = self._meta(meta_row, "Süre")
        meta_row.addStretch()
        layout.addLayout(meta_row)

        # Bağlantı haritası: yalnızca parçalı HTTP indirmelerinde anlamlı (video/HLS'de parça bilgisi yok)
        self.conn_caption = _label("Bağlantılar", "caption")
        self.visualizer = ChunkVisualizer(self)
        layout.addSpacing(12)
        layout.addWidget(self.conn_caption)
        layout.addWidget(self.visualizer)

        # Hata nedeni
        self.error_frame = QFrame()
        self.error_frame.setProperty("role", "error-box")
        err_layout = QVBoxLayout(self.error_frame)
        err_layout.setContentsMargins(12, 10, 12, 10)
        err_layout.setSpacing(4)
        err_layout.addWidget(_label("Hata nedeni", "danger"))
        self.error_lbl = QLabel()
        self.error_lbl.setWordWrap(True)
        self.error_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        err_layout.addWidget(self.error_lbl)
        layout.addSpacing(8)
        layout.addWidget(self.error_frame)

        layout.addSpacing(14)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        self.pause_resume_btn = QPushButton()
        self.pause_resume_btn.clicked.connect(self.toggle_pause_resume)
        self.open_file_btn = QPushButton("Dosyayı aç")
        self.open_file_btn.clicked.connect(self.open_file)
        self.open_folder_btn = QPushButton("Klasörü aç")
        self.open_folder_btn.clicked.connect(self.open_folder)
        self.close_btn = QPushButton("Kapat")
        self.close_btn.setProperty("class", "tool-btn")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.pause_resume_btn)
        btn_layout.addWidget(self.open_file_btn)
        btn_layout.addWidget(self.open_folder_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)
        self._refresh_icons()

    @staticmethod
    def _meta(row, caption):
        box = QVBoxLayout()
        box.setSpacing(2)
        box.addWidget(_label(caption, "caption"))
        value = QLabel("–")
        box.addWidget(value)
        row.addLayout(box)
        return value

    def _refresh_icons(self):
        self.open_file_btn.setIcon(theme.icon("file-text.svg"))
        self.open_folder_btn.setIcon(theme.icon("folder.svg"))
        self._set_pause_button()
        self.status_dot.setPixmap(theme.status_dot(self.task.status).pixmap(10, 10))

    def _set_pause_button(self):
        if self.task.status == "error":
            text, icon = "Tekrar dene", "play.svg"
        elif self.task.status == "downloading":
            text, icon = "Duraklat", "pause.svg"
        elif self.task.status == "completed":
            text, icon = "Tamamlandı", "check.svg"
        else:
            text, icon = "Devam et", "play.svg"
        self.pause_resume_btn.setText(text)
        self.pause_resume_btn.setIcon(theme.icon(icon))
        self.pause_resume_btn.setEnabled(self.task.status != "completed")

    def _size_text(self):
        t = self.task
        if t.total_bytes > 0 and t.status != "completed":
            return f"{format_bytes(t.downloaded_bytes)} / {format_bytes(t.total_bytes)}"
        if t.total_bytes > 0:
            return format_bytes(t.total_bytes)
        return format_bytes(t.downloaded_bytes) if t.downloaded_bytes else ""

    def update_data(self, task):
        if task.id != self.task.id:
            return
        prev_status = self.task.status
        self.task = task
        self.title_lbl.setText(task.filename)

        # Aşama/hız ayrımı tablo ile aynı kuralla (ör. "Ses 1/2 · TR")
        active = task.status == "downloading"
        stage, speed = split_stage_speed(task.speed) if active else ("", "")
        status_text = STATUS_LABELS.get(task.status, task.status.capitalize())
        if active and stage:
            status_text = f"{status_text} · {stage}"
        self.status_lbl.setText(status_text)
        if prev_status != task.status or self.status_dot.pixmap().isNull():
            self.status_dot.setPixmap(theme.status_dot(task.status).pixmap(10, 10))

        self.pct_lbl.setText(f"{int(task.percent)} %")
        self.size_lbl.setText(self._size_text())
        self.prog_bar.setValue(int(task.percent))
        if self.prog_bar.property("state") != task.status:
            self.prog_bar.setProperty("state", task.status)
            theme.repolish(self.prog_bar)

        self.speed_val.setText(speed or "–")
        self.eta_val.setText(eta_text(task) or "–")
        elapsed = format_duration(task.elapsed())
        self.elapsed_val.setText("–" if elapsed == "-" else elapsed)

        has_segments = bool(task.segments_data) and not (task.is_stream or task.is_youtube)
        self.conn_caption.setVisible(has_segments)
        self.visualizer.setVisible(has_segments)
        if has_segments:
            self.visualizer.set_segments(task.segments_data)

        is_error = task.status == "error"
        self.error_frame.setVisible(is_error)
        if is_error:
            self.error_lbl.setText(task.error_message or "İndirme başlatılamadı veya sunucu bağlantıyı reddetti.")

        if prev_status != task.status:
            self._set_pause_button()
        self.open_file_btn.setEnabled(task.status == "completed")

    def toggle_pause_resume(self):
        if self.task.status == "downloading":
            self.queue_manager.pause_task(self.task.id)
        else:
            self.error_frame.setVisible(False)
            self.queue_manager.resume_task(self.task.id)
        self._set_pause_button()

    def open_file(self):
        path = self.task.target_path
        if path and os.path.exists(path):
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.run(["xdg-open", path], check=False)

    def open_folder(self):
        dest = self.task.destination_dir
        if dest and os.path.exists(dest):
            if sys.platform == "win32":
                os.startfile(dest)
            else:
                subprocess.run(["xdg-open", dest], check=False)

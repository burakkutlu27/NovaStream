"""
NovaStream İndirme Detay ve Canlı İlerleme Penceresi (IDM Tarzı Durum Penceresi)
"""

import os
import subprocess
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QFrame
)
from core.engine import format_bytes
from ui.chunk_visualizer import ChunkVisualizer

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.path.join(APP_DIR, "assets", "icons")


class ProgressDialog(QDialog):
    def __init__(self, task, queue_manager, parent=None):
        super().__init__(parent)
        self.task = task
        self.queue_manager = queue_manager
        self.setWindowTitle(f"İndiriliyor: {task.filename}")
        self.setMinimumWidth(560)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)

        # Dosya Başlığı
        self.title_lbl = QLabel(self.task.filename)
        self.title_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #f0f3f6;")
        self.title_lbl.setWordWrap(True)
        layout.addWidget(self.title_lbl)

        # Durum ve Hız Bilgileri
        info_layout = QHBoxLayout()
        self.status_lbl = QLabel(f"Durum: {self.task.status.capitalize()}")
        self.status_lbl.setStyleSheet("color: #3b82f6; font-weight: 600;")

        self.speed_lbl = QLabel(f"Hız: {self.task.speed}")
        self.speed_lbl.setStyleSheet("color: #10b981; font-weight: 600;")

        self.eta_lbl = QLabel(f"Kalan: {self.task.eta}")
        self.eta_lbl.setStyleSheet("color: #8b949e;")

        info_layout.addWidget(self.status_lbl)
        info_layout.addStretch()
        info_layout.addWidget(self.speed_lbl)
        info_layout.addWidget(self.eta_lbl)
        layout.addLayout(info_layout)

        # Ana İlerleme Çubuğu
        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(int(self.task.percent))
        layout.addWidget(self.prog_bar)

        # Boyut Metni
        self.size_lbl = QLabel(self._get_size_str())
        self.size_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self.size_lbl)

        # IDM Bağlantı Görselleştirici (Chunk Bars)
        conn_lbl = QLabel("Bağlantı Kanalları:")
        conn_lbl.setStyleSheet("color: #8b949e; font-size: 11px; font-weight: 600;")
        layout.addWidget(conn_lbl)
        self.visualizer = ChunkVisualizer(self)
        self.visualizer.set_segments(self.task.segments_data)
        layout.addWidget(self.visualizer)

        # Hata Detayı Paneli (Yalnızca hata durumunda görünür)
        self.error_frame = QFrame()
        self.error_frame.setStyleSheet(
            "background-color: #221518; border: 1px solid #7f1d1d; border-radius: 4px; padding: 6px 10px;"
        )
        err_layout = QVBoxLayout(self.error_frame)
        err_layout.setContentsMargins(4, 4, 4, 4)
        err_layout.setSpacing(4)

        err_title = QLabel("Hata Nedeni:")
        err_title.setStyleSheet("color: #f87171; font-weight: 700; font-size: 11px;")
        err_layout.addWidget(err_title)

        self.error_lbl = QLabel(self.task.error_message or "İndirme başlatılamadı.")
        self.error_lbl.setStyleSheet("color: #fca5a5; font-size: 11px; line-height: 1.35;")
        self.error_lbl.setWordWrap(True)
        self.error_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        err_layout.addWidget(self.error_lbl)

        layout.addWidget(self.error_frame)
        self.error_frame.setVisible(self.task.status == "error")

        # Butonlar
        btn_layout = QHBoxLayout()

        self.pause_resume_btn = QPushButton("Duraklat" if self.task.status == "downloading" else "Devam Et")
        self.pause_resume_btn.setIcon(QIcon(os.path.join(ICON_DIR, "pause.svg" if self.task.status == "downloading" else "play.svg")))
        self.pause_resume_btn.setProperty("class", "tool-btn")
        self.pause_resume_btn.clicked.connect(self.toggle_pause_resume)

        self.open_file_btn = QPushButton("Dosyayı Aç")
        self.open_file_btn.setIcon(QIcon(os.path.join(ICON_DIR, "file-text.svg")))
        self.open_file_btn.setProperty("class", "tool-btn")
        self.open_file_btn.clicked.connect(self.open_file)
        self.open_file_btn.setEnabled(self.task.status == "completed")

        self.open_folder_btn = QPushButton("Klasörü Aç")
        self.open_folder_btn.setIcon(QIcon(os.path.join(ICON_DIR, "folder.svg")))
        self.open_folder_btn.setProperty("class", "tool-btn")
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

    def _get_size_str(self):
        dl = format_bytes(self.task.downloaded_bytes)
        tot = format_bytes(self.task.total_bytes) if self.task.total_bytes > 0 else "Bilinmiyor"
        return f"İndirilen: {dl} / {tot} ({self.task.percent:.1f}%)"

    def update_data(self, task):
        if task.id != self.task.id:
            return
        self.task = task
        self.title_lbl.setText(task.filename)

        if task.status == "error":
            self.status_lbl.setText("Durum: Hata")
            self.status_lbl.setStyleSheet("color: #ef4444; font-weight: 600;")
            self.speed_lbl.setText("Hız: 0 B/s")
            self.speed_lbl.setStyleSheet("color: #8b949e; font-weight: 600;")
            self.error_lbl.setText(task.error_message or "İndirme başlatılamadı veya sunucu bağlantıyı reddetti.")
            self.error_frame.setVisible(True)
            self.pause_resume_btn.setText("Tekrar Dene")
            self.pause_resume_btn.setIcon(QIcon(os.path.join(ICON_DIR, "play.svg")))
        else:
            self.error_frame.setVisible(False)
            status_map = {
                "downloading": ("Durum: İndiriliyor", "#3b82f6"),
                "completed": ("Durum: Tamamlandı", "#10b981"),
                "paused": ("Durum: Duraklatıldı", "#f59e0b"),
                "queued": ("Durum: Kuyrukta", "#8b949e")
            }
            lbl_text, lbl_color = status_map.get(task.status, (f"Durum: {task.status.capitalize()}", "#3b82f6"))
            self.status_lbl.setText(lbl_text)
            self.status_lbl.setStyleSheet(f"color: {lbl_color}; font-weight: 600;")

            self.speed_lbl.setText(f"Hız: {task.speed}")
            self.speed_lbl.setStyleSheet("color: #10b981; font-weight: 600;")
            self.pause_resume_btn.setText("Duraklat" if task.status == "downloading" else "Devam Et")
            self.pause_resume_btn.setIcon(QIcon(os.path.join(ICON_DIR, "pause.svg" if task.status == "downloading" else "play.svg")))

        self.eta_lbl.setText(f"Kalan Süre: {task.eta}")
        self.prog_bar.setValue(int(task.percent))
        self.size_lbl.setText(self._get_size_str())
        self.visualizer.set_segments(task.segments_data)
        self.open_file_btn.setEnabled(task.status == "completed")

    def toggle_pause_resume(self):
        if self.task.status == "downloading":
            self.queue_manager.pause_task(self.task.id)
            self.pause_resume_btn.setText("Devam Et")
            self.pause_resume_btn.setIcon(QIcon(os.path.join(ICON_DIR, "play.svg")))
        else:
            self.error_frame.setVisible(False)
            self.queue_manager.resume_task(self.task.id)
            self.pause_resume_btn.setText("Duraklat")
            self.pause_resume_btn.setIcon(QIcon(os.path.join(ICON_DIR, "pause.svg")))

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

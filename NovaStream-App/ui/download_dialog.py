"""
NovaStream İndirme Onay ve Detay Penceresi (IDM Tarzı Yeni İndirme Modalı)
"""

import os
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QFrame
)
from core.engine import get_default_download_dir
from core.queue_manager import categorize_file, QUALITY_CHOICES

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.path.join(APP_DIR, "assets", "icons")


class DownloadDialog(QDialog):
    # (url, title, dest_dir, auto_start, category, is_stream, is_youtube)
    download_requested = pyqtSignal(dict)

    def __init__(self, download_info=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NovaStream - İndirme Başlat")
        self.setFixedWidth(540)
        self.setModal(True)

        self.info = download_info or {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Başlık ve Bilgi Kartı
        header_lbl = QLabel("Yeni İndirme Ekle")
        header_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #f0f3f6;")
        layout.addWidget(header_lbl)

        # URL
        layout.addWidget(QLabel("İndirme Adresi (URL):"))
        self.url_input = QLineEdit(self.info.get("url", ""))
        self.url_input.setPlaceholderText("https://...")
        self.url_input.textChanged.connect(self.on_url_changed)
        layout.addWidget(self.url_input)

        # Dosya Adı
        layout.addWidget(QLabel("Dosya Adı:"))
        self.filename_input = QLineEdit(self.info.get("title", ""))
        self.filename_input.setPlaceholderText("Boş bırakılırsa otomatik (videolarda video başlığı)")
        layout.addWidget(self.filename_input)

        # Kayıt Yeri
        layout.addWidget(QLabel("Kaydedilecek Klasör:"))
        dir_layout = QHBoxLayout()
        default_dir = self.info.get("destination_dir") or self.info.get("default_dir") or get_default_download_dir()
        self.dir_input = QLineEdit(default_dir)
        self.dir_btn = QPushButton("Gözat...")
        self.dir_btn.setIcon(QIcon(os.path.join(ICON_DIR, "folder.svg")))
        self.dir_btn.setProperty("class", "tool-btn")
        self.dir_btn.clicked.connect(self.browse_dir)
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(self.dir_btn)
        layout.addLayout(dir_layout)

        # Kategori
        cat_layout = QHBoxLayout()
        cat_layout.addWidget(QLabel("Kategori:"))
        self.cat_combo = QComboBox()
        self.cat_combo.addItems(["Videos", "Music", "Compressed", "Documents", "Programs", "Others"])
        cat = self.info.get("category") or categorize_file(self.filename_input.text(), self.info.get("isStream", False))
        idx = self.cat_combo.findText(cat)
        if idx >= 0:
            self.cat_combo.setCurrentIndex(idx)
        cat_layout.addWidget(self.cat_combo)
        layout.addLayout(cat_layout)

        # Video kalitesi (YouTube / akış / video siteleri)
        self.quality_row = QHBoxLayout()
        self.quality_row.addWidget(QLabel("Video Kalitesi:"))
        self.quality_combo = QComboBox()
        for key, label in QUALITY_CHOICES:
            self.quality_combo.addItem(label, key)
        q_idx = self.quality_combo.findData(self.info.get("quality") or self.info.get("default_quality") or "best")
        self.quality_combo.setCurrentIndex(max(0, q_idx))
        self.quality_row.addWidget(self.quality_combo)
        layout.addLayout(self.quality_row)
        self._update_quality_visibility(self.url_input.text())
        if self.url_input.text() and not self.filename_input.text():
            self.on_url_changed(self.url_input.text())

        # Çizgi
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2b303c;")
        layout.addWidget(sep)

        # Butonlar
        btn_layout = QHBoxLayout()
        self.later_btn = QPushButton("Daha Sonra İndir")
        self.later_btn.setIcon(QIcon(os.path.join(ICON_DIR, "clock.svg")))
        self.later_btn.setProperty("class", "tool-btn")
        self.later_btn.clicked.connect(lambda: self.confirm_download(auto_start=False))

        self.start_btn = QPushButton("Şimdi İndir")
        self.start_btn.setIcon(QIcon(os.path.join(ICON_DIR, "download.svg")))
        self.start_btn.setProperty("class", "tool-btn-primary")
        self.start_btn.clicked.connect(lambda: self.confirm_download(auto_start=True))

        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setProperty("class", "tool-btn")
        self.cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(self.later_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.start_btn)
        layout.addLayout(btn_layout)

    @staticmethod
    def is_video_url(text):
        t = (text or "").lower()
        return any(d in t for d in ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "x.com/",
                                     "twitter.com", "vimeo.com", "dailymotion.com", "twitch.tv",
                                     ".m3u8", ".mpd"))

    def _update_quality_visibility(self, text):
        show = bool(self.info.get("isStream") or self.info.get("isYouTube") or self.is_video_url(text))
        self.quality_combo.setVisible(show)
        for i in range(self.quality_row.count()):
            w = self.quality_row.itemAt(i).widget()
            if w:
                w.setVisible(show)

    def on_url_changed(self, text):
        if hasattr(self, "quality_combo"):
            self._update_quality_visibility(text)
        if self.is_video_url(text):
            return  # video sitelerinde ad, boş bırakılırsa videonun kendi başlığından alınır
        if not self.filename_input.text() or self.filename_input.text() == "Dosya":
            name = os.path.basename(text.split("?")[0].rstrip("/"))
            if name:
                self.filename_input.setText(name)
                cat = categorize_file(name)
                idx = self.cat_combo.findText(cat)
                if idx >= 0:
                    self.cat_combo.setCurrentIndex(idx)

    def browse_dir(self):
        chosen = QFileDialog.getExistingDirectory(self, "Kayıt Klasörü Seç", self.dir_input.text())
        if chosen:
            self.dir_input.setText(chosen)

    def confirm_download(self, auto_start=True):
        url = self.url_input.text().strip()
        if not url:
            return

        is_video = bool(self.info.get("isStream") or self.info.get("isYouTube") or self.is_video_url(url))
        is_youtube = bool(self.info.get("isYouTube")) or any(d in url.lower() for d in ("youtube.com", "youtu.be"))
        payload = {
            "url": url,
            "title": self.filename_input.text().strip(),
            "quality": self.quality_combo.currentData() if is_video else None,
            "destination_dir": self.dir_input.text().strip() or get_default_download_dir(),
            "category": self.cat_combo.currentText(),
            "auto_start": auto_start,
            "is_stream": is_video and not is_youtube,
            "is_youtube": is_youtube,
            "referer": self.info.get("referer")
        }
        self.download_requested.emit(payload)
        self.accept()

"""
NovaStream yeni indirme penceresi (adres, ad, klasör, kategori, video kalitesi).
"""

import os
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QFrame, QCheckBox
)
from core.engine import get_default_download_dir
from core.queue_manager import categorize_file, QUALITY_CHOICES
from ui import theme
from ui.display import CATEGORY_LABELS


def _caption(text):
    lbl = QLabel(text)
    lbl.setProperty("role", "muted")
    return lbl


class DownloadDialog(QDialog):
    # (url, title, dest_dir, auto_start, category, is_stream, is_youtube)
    download_requested = pyqtSignal(dict)

    def __init__(self, download_info=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NovaStream - Yeni indirme")
        self.setFixedWidth(540)
        self.setModal(True)

        self.info = download_info or {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(24, 22, 24, 20)

        header_lbl = QLabel("Yeni indirme")
        header_lbl.setProperty("role", "title")
        layout.addWidget(header_lbl)
        layout.addSpacing(10)

        # URL
        layout.addWidget(_caption("Adres"))
        self.url_input = QLineEdit(self.info.get("url", ""))
        self.url_input.setPlaceholderText("https://...")
        self.url_input.textChanged.connect(self.on_url_changed)
        layout.addWidget(self.url_input)
        layout.addSpacing(8)

        layout.addWidget(_caption("Dosya adı"))
        self.filename_input = QLineEdit(self.info.get("title", ""))
        self.filename_input.setPlaceholderText("Boş bırakılırsa otomatik (videolarda video başlığı)")
        layout.addWidget(self.filename_input)
        layout.addSpacing(8)

        layout.addWidget(_caption("Kaydedilecek klasör"))
        dir_layout = QHBoxLayout()
        default_dir = self.info.get("destination_dir") or self.info.get("default_dir") or get_default_download_dir()
        self.dir_input = QLineEdit(default_dir)
        self.dir_btn = QPushButton("Gözat")
        self.dir_btn.setIcon(theme.icon("folder.svg"))
        self.dir_btn.clicked.connect(self.browse_dir)
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(self.dir_btn)
        layout.addLayout(dir_layout)
        layout.addSpacing(8)

        cat_layout = QHBoxLayout()
        cat_layout.addWidget(_caption("Kategori"))
        cat_layout.addStretch()
        self.cat_combo = QComboBox()
        self.cat_combo.setMinimumWidth(220)
        for key, label in CATEGORY_LABELS.items():
            self.cat_combo.addItem(label, key)
        cat = self.info.get("category") or categorize_file(self.filename_input.text(), self.info.get("isStream", False))
        idx = self.cat_combo.findData(cat)
        if idx >= 0:
            self.cat_combo.setCurrentIndex(idx)
        cat_layout.addWidget(self.cat_combo)
        layout.addLayout(cat_layout)

        # Video kalitesi (YouTube / akış / video siteleri)
        self.quality_row = QHBoxLayout()
        self.quality_row.addWidget(_caption("Video kalitesi"))
        self.quality_row.addStretch()
        self.quality_combo = QComboBox()
        self.quality_combo.setMinimumWidth(220)
        for key, label in QUALITY_CHOICES:
            self.quality_combo.addItem(label, key)
        q_idx = self.quality_combo.findData(self.info.get("quality") or self.info.get("default_quality") or "best")
        self.quality_combo.setCurrentIndex(max(0, q_idx))
        self.quality_row.addWidget(self.quality_combo)
        layout.addLayout(self.quality_row)

        self.sub_chk = QCheckBox("Altyazıları da indir (TR/EN, SRT)")
        self.sub_chk.setChecked(bool(self.info.get("download_subtitles", self.info.get("default_subtitles", False))))
        layout.addWidget(self.sub_chk)

        self._update_quality_visibility(self.url_input.text())
        if self.url_input.text() and not self.filename_input.text():
            self.on_url_changed(self.url_input.text())

        layout.addSpacing(12)
        sep = QFrame()
        sep.setProperty("role", "separator")
        layout.addWidget(sep)
        layout.addSpacing(8)

        # Butonlar
        btn_layout = QHBoxLayout()
        self.later_btn = QPushButton("Sonra indir")
        self.later_btn.setIcon(theme.icon("clock.svg"))
        self.later_btn.setProperty("class", "tool-btn")
        self.later_btn.clicked.connect(lambda: self.confirm_download(auto_start=False))

        self.start_btn = QPushButton("Şimdi indir")
        self.start_btn.setIcon(theme.icon("download.svg", "on_accent"))
        self.start_btn.setDefault(True)
        self.start_btn.setProperty("class", "tool-btn-primary")
        self.start_btn.clicked.connect(lambda: self.confirm_download(auto_start=True))

        self.cancel_btn = QPushButton("İptal")
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
        if hasattr(self, "sub_chk"):
            self.sub_chk.setVisible(show)
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
                idx = self.cat_combo.findData(cat)
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
            "download_subtitles": bool(self.sub_chk.isChecked()) if is_video else False,
            "destination_dir": self.dir_input.text().strip() or get_default_download_dir(),
            "category": self.cat_combo.currentData(),
            "auto_start": auto_start,
            "is_stream": is_video and not is_youtube,
            "is_youtube": is_youtube,
            "referer": self.info.get("referer")
        }
        self.download_requested.emit(payload)
        self.accept()

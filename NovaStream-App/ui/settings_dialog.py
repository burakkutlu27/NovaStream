"""
NovaStream Ayarlar Penceresi
Buradaki her seçenek settings.json'a kaydedilir ve uygulama tarafından kullanılır.
"""

import os
import sys
import subprocess

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QCheckBox, QComboBox, QFileDialog
)
from core.engine import get_default_download_dir
from core.queue_manager import LOG_DIR, QUALITY_CHOICES

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.path.join(APP_DIR, "assets", "icons")

COOKIE_CHOICES = [
    ("", "Kullanma (önerilen)"),
    ("chrome", "Chrome"),
    ("firefox", "Firefox"),
    ("brave", "Brave"),
    ("edge", "Edge"),
    ("chromium", "Chromium"),
]


class SettingsDialog(QDialog):
    def __init__(self, queue_manager, parent=None, on_update_ytdlp=None):
        super().__init__(parent)
        self.queue_manager = queue_manager
        self.on_update_ytdlp = on_update_ytdlp
        self.setWindowTitle("NovaStream - Ayarlar")
        self.setFixedWidth(520)
        self.init_ui()

    def _row(self, layout, label, widget):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addStretch()
        row.addWidget(widget)
        layout.addLayout(row)

    def init_ui(self):
        s = self.queue_manager.settings
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("İndirme ve Motor Ayarları")
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #f0f3f6;")
        layout.addWidget(title)

        layout.addWidget(QLabel("Varsayılan İndirme Klasörü:"))
        dir_layout = QHBoxLayout()
        self.dir_input = QLineEdit(s.get("download_dir") or get_default_download_dir())
        self.dir_btn = QPushButton("Gözat...")
        self.dir_btn.setIcon(QIcon(os.path.join(ICON_DIR, "folder.svg")))
        self.dir_btn.setProperty("class", "tool-btn")
        self.dir_btn.clicked.connect(self.browse_dir)
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(self.dir_btn)
        layout.addLayout(dir_layout)

        self.conn_spin = QSpinBox()
        self.conn_spin.setRange(1, 32)
        self.conn_spin.setValue(self.queue_manager.default_connections)
        self._row(layout, "Dosya başına bağlantı sayısı (1-32):", self.conn_spin)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 10)
        self.limit_spin.setValue(self.queue_manager.max_concurrent)
        self._row(layout, "Aynı anda en fazla indirme (1-10):", self.limit_spin)

        self.quality_combo = QComboBox()
        for key, label in QUALITY_CHOICES:
            self.quality_combo.addItem(label, key)
        idx = self.quality_combo.findData(s.get("default_quality", "best"))
        self.quality_combo.setCurrentIndex(max(0, idx))
        self._row(layout, "Varsayılan video kalitesi:", self.quality_combo)

        self.yt_cookie_combo = QComboBox()
        for key, label in COOKIE_CHOICES:
            self.yt_cookie_combo.addItem(label, key)
        idx = self.yt_cookie_combo.findData(s.get("cookie_browser", ""))
        self.yt_cookie_combo.setCurrentIndex(max(0, idx))
        self._row(layout, "YouTube oturum çerezi (yaş sınırlı videolar):", self.yt_cookie_combo)
        if sys.platform == "win32":
            note = QLabel("Not: Windows'ta Chrome/Edge açıkken çerezleri okunamaz; Firefox önerilir.")
            note.setStyleSheet("color: #94a3b8; font-size: 11px;")
            layout.addWidget(note)

        self.confirm_chk = QCheckBox("Tarayıcı eklentisinden gelen indirmeler için onay penceresi göster")
        self.confirm_chk.setChecked(bool(s.get("confirm_extension_downloads")))
        layout.addWidget(self.confirm_chk)

        self.clipboard_chk = QCheckBox("Panoya kopyalanan indirme linklerini yakala ve sor")
        self.clipboard_chk.setChecked(bool(s.get("clipboard_monitor")))
        layout.addWidget(self.clipboard_chk)

        self.tray_chk = QCheckBox("Pencere kapatılınca sistem tepsisinde çalışmaya devam et")
        self.tray_chk.setChecked(bool(s.get("minimize_to_tray", True)))
        layout.addWidget(self.tray_chk)

        tools = QHBoxLayout()
        self.update_btn = QPushButton("yt-dlp'yi şimdi güncelle")
        self.update_btn.setProperty("class", "tool-btn")
        self.update_btn.clicked.connect(self._update_clicked)
        self.update_btn.setEnabled(self.on_update_ytdlp is not None)
        self.logs_btn = QPushButton("Log klasörünü aç")
        self.logs_btn.setProperty("class", "tool-btn")
        self.logs_btn.clicked.connect(self.open_logs)
        tools.addWidget(self.update_btn)
        tools.addWidget(self.logs_btn)
        tools.addStretch()
        layout.addLayout(tools)

        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Kaydet")
        self.save_btn.setProperty("class", "tool-btn-primary")
        self.save_btn.clicked.connect(self.save)
        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setProperty("class", "tool-btn")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

    def _update_clicked(self):
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Güncelleniyor (arka planda)...")
        self.on_update_ytdlp()

    def browse_dir(self):
        chosen = QFileDialog.getExistingDirectory(self, "Klasör Seç", self.dir_input.text())
        if chosen:
            self.dir_input.setText(chosen)

    def open_logs(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(LOG_DIR)
        else:
            subprocess.Popen(["xdg-open", LOG_DIR])

    def save(self):
        s = self.queue_manager.settings
        chosen_dir = self.dir_input.text().strip()
        s["download_dir"] = "" if chosen_dir == get_default_download_dir() else chosen_dir
        self.queue_manager.default_connections = self.conn_spin.value()
        self.queue_manager.max_concurrent = self.limit_spin.value()
        s["default_quality"] = self.quality_combo.currentData()
        s["cookie_browser"] = self.yt_cookie_combo.currentData()
        s["confirm_extension_downloads"] = self.confirm_chk.isChecked()
        s["clipboard_monitor"] = self.clipboard_chk.isChecked()
        s["minimize_to_tray"] = self.tray_chk.isChecked()
        self.queue_manager.save_settings()
        self.accept()

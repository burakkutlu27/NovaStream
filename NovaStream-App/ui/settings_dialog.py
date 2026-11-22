"""
NovaStream Ayarlar Penceresi
Buradaki her seçenek settings.json'a kaydedilir ve uygulama tarafından kullanılır.
"""

import os
import sys
import subprocess

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QCheckBox, QComboBox, QFileDialog,
    QTextEdit
)
from core.browser_setup import (
    auto_install_extensions,
    detect_browsers,
    open_browser_extensions_page,
    reveal_path_in_file_manager,
)
from core.engine import get_default_download_dir
from core.queue_manager import LOG_DIR, QUALITY_CHOICES
from ui import theme

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

THEME_CHOICES = [
    ("system", "Sistem ayarını izle"),
    ("dark", "Koyu"),
    ("light", "Açık"),
]


def _label(text, role):
    lbl = QLabel(text)
    lbl.setProperty("role", role)
    return lbl

COOKIE_CHOICES = [
    ("", "Kullanma (önerilen)"),
    ("chrome", "Chrome"),
    ("firefox", "Firefox"),
    ("brave", "Brave"),
    ("edge", "Edge"),
    ("chromium", "Chromium"),
]


class BrowserSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NovaStream - Tarayıcı eklentisi")
        self.setMinimumWidth(560)
        self.browser_dir = self._resolve_browser_dir()
        self.browsers = detect_browsers()
        self.result = auto_install_extensions(self.browser_dir, browsers=self.browsers)
        self.init_ui()

    @staticmethod
    def _resolve_browser_dir():
        installed_dir = os.path.join(APP_DIR, "browser")
        if os.path.isdir(installed_dir):
            return installed_dir
        dev_dir = os.path.join(os.path.dirname(APP_DIR), "extension")
        return dev_dir if os.path.isdir(dev_dir) else installed_dir

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(24, 22, 24, 20)

        layout.addWidget(_label("Tarayıcı algılama ve eklenti kurulumu", "title"))

        summary_lines = [
            f"Native Messaging köprüsü kaydedildi ({len(self.result['native_registered'])} konum)."
        ]
        if self.result["browsers"]:
            summary_lines.append("\nAlgılanan Tarayıcılar:")
            for b in self.result["browsers"]:
                summary_lines.append(f"• {b['name']}: {b['detail']}")
        else:
            summary_lines.append("\nOtomatik algılanan tarayıcı bulunamadı; aşağıdaki konumları manuel seçebilirsiniz.")

        chrome_path = self._chrome_path()
        firefox_path = self._firefox_manifest_path()
        pkg_dir = self.result["packages"].get("packages_dir") or ""
        summary_lines.append("\nManuel Seçim Konumları (Tarayıcı izin vermediğinde):")
        summary_lines.append(f"• Chrome / Edge / Brave / Opera / Vivaldi klasörü:\n  {chrome_path}")
        summary_lines.append(f"• Firefox dosyası (about:debugging → Geçici Eklenti Yükle):\n  {firefox_path}")
        if pkg_dir:
            summary_lines.append(f"• Paketli eklentiler (.zip / .xpi):\n  {pkg_dir}")

        box = QTextEdit()
        box.setReadOnly(True)
        box.setPlainText("\n".join(summary_lines))
        box.setMinimumHeight(210)
        layout.addWidget(box)

        btn_row1 = QHBoxLayout()
        btn_chrome_dir = QPushButton("Chrome/Edge/Brave klasörünü göster")
        btn_chrome_dir.clicked.connect(lambda: reveal_path_in_file_manager(self._chrome_path()))
        btn_row1.addWidget(btn_chrome_dir)

        btn_ff_file = QPushButton("Firefox dosyasını göster")
        btn_ff_file.clicked.connect(lambda: reveal_path_in_file_manager(self._firefox_manifest_path()))
        btn_row1.addWidget(btn_ff_file)
        layout.addLayout(btn_row1)

        if self.browsers:
            btn_row2 = QHBoxLayout()
            for b in self.browsers[:4]:
                btn = QPushButton(f"{b['name']} uzantıları")
                btn.setProperty("class", "tool-btn")
                btn.clicked.connect(lambda _chk=False, info=b: open_browser_extensions_page(info))
                btn_row2.addWidget(btn)
            btn_row2.addStretch()
            layout.addLayout(btn_row2)

        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("Kapat")
        btn_close.setProperty("class", "tool-btn-primary")
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

    def _chrome_path(self):
        return os.path.join(self.browser_dir, "chrome")

    def _firefox_manifest_path(self):
        return os.path.join(self.browser_dir, "firefox", "manifest.json")


class SettingsDialog(QDialog):
    def __init__(self, queue_manager, parent=None, on_update_ytdlp=None):
        super().__init__(parent)
        self.queue_manager = queue_manager
        self.on_update_ytdlp = on_update_ytdlp
        self.setWindowTitle("NovaStream - Ayarlar")
        self.setFixedWidth(560)
        self.init_ui()

    def _row(self, layout, label, widget):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addStretch()
        widget.setMinimumWidth(180)
        row.addWidget(widget)
        layout.addLayout(row)

    @staticmethod
    def _section(layout, text, first=False):
        if not first:
            layout.addSpacing(10)
            sep = QFrame()
            sep.setProperty("role", "separator")
            layout.addWidget(sep)
        layout.addWidget(_label(text, "section"))

    def init_ui(self):
        s = self.queue_manager.settings
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(24, 22, 24, 20)

        layout.addWidget(_label("Ayarlar", "title"))
        layout.addSpacing(4)

        self._section(layout, "İndirme", first=True)
        layout.addWidget(_label("Varsayılan indirme klasörü", "muted"))
        dir_layout = QHBoxLayout()
        self.dir_input = QLineEdit(s.get("download_dir") or get_default_download_dir())
        self.dir_btn = QPushButton("Gözat")
        self.dir_btn.setIcon(theme.icon("folder.svg"))
        self.dir_btn.clicked.connect(self.browse_dir)
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(self.dir_btn)
        layout.addLayout(dir_layout)

        self.conn_spin = QSpinBox()
        self.conn_spin.setRange(1, 32)
        self.conn_spin.setValue(self.queue_manager.default_connections)
        self._row(layout, "Dosya başına bağlantı (1–32)", self.conn_spin)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 10)
        self.limit_spin.setValue(self.queue_manager.max_concurrent)
        self._row(layout, "Aynı anda en fazla indirme (1–10)", self.limit_spin)

        self._section(layout, "Video")

        self.quality_combo = QComboBox()
        for key, label in QUALITY_CHOICES:
            self.quality_combo.addItem(label, key)
        idx = self.quality_combo.findData(s.get("default_quality", "best"))
        self.quality_combo.setCurrentIndex(max(0, idx))
        self._row(layout, "Varsayılan kalite", self.quality_combo)

        self.sub_chk = QCheckBox("Altyazıları da indir (SRT)")
        self.sub_chk.setChecked(bool(s.get("download_subtitles")))
        layout.addWidget(self.sub_chk)

        self.sub_langs_input = QLineEdit(s.get("subtitle_langs") or "tr,en")
        self.sub_langs_input.setPlaceholderText("tr,en")
        self._row(layout, "Altyazı dilleri", self.sub_langs_input)

        self.yt_cookie_combo = QComboBox()
        for key, label in COOKIE_CHOICES:
            self.yt_cookie_combo.addItem(label, key)
        idx = self.yt_cookie_combo.findData(s.get("cookie_browser", ""))
        self.yt_cookie_combo.setCurrentIndex(max(0, idx))
        self._row(layout, "YouTube çerezi (yaş sınırlı videolar)", self.yt_cookie_combo)
        if sys.platform == "win32":
            layout.addWidget(_label("Windows'ta Chrome/Edge açıkken çerezleri okunamaz; Firefox önerilir.", "caption"))

        self._section(layout, "Tarayıcı ve sistem")

        self.confirm_chk = QCheckBox("Eklentiden gelen indirmeler için onay sor")
        self.confirm_chk.setChecked(bool(s.get("confirm_extension_downloads")))
        layout.addWidget(self.confirm_chk)

        self.clipboard_chk = QCheckBox("Panoya kopyalanan indirme linklerini yakala")
        self.clipboard_chk.setChecked(bool(s.get("clipboard_monitor")))
        layout.addWidget(self.clipboard_chk)

        self.tray_chk = QCheckBox("Pencere kapanınca sistem tepsisinde çalışmaya devam et")
        self.tray_chk.setChecked(bool(s.get("minimize_to_tray", True)))
        layout.addWidget(self.tray_chk)

        self._section(layout, "Görünüm")
        self.theme_combo = QComboBox()
        for key, label in THEME_CHOICES:
            self.theme_combo.addItem(label, key)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(s.get("theme", "system"))))
        self._row(layout, "Tema", self.theme_combo)

        self._section(layout, "Bakım")
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.update_btn = QPushButton("yt-dlp'yi güncelle")
        self.update_btn.clicked.connect(self._update_clicked)
        self.update_btn.setEnabled(self.on_update_ytdlp is not None)
        self.browser_setup_btn = QPushButton("Tarayıcı eklentisini kur")
        self.browser_setup_btn.clicked.connect(self.open_browser_setup)
        self.logs_btn = QPushButton("Kayıtları aç")
        self.logs_btn.setToolTip(LOG_DIR)
        self.logs_btn.clicked.connect(self.open_logs)
        tools.addWidget(self.update_btn)
        tools.addWidget(self.browser_setup_btn)
        tools.addWidget(self.logs_btn)
        tools.addStretch()
        layout.addLayout(tools)
        layout.addSpacing(16)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        self.save_btn = QPushButton("Kaydet")
        self.save_btn.setProperty("class", "tool-btn-primary")
        self.save_btn.clicked.connect(self.save)
        self.save_btn.setDefault(True)
        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

    def _update_clicked(self):
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Güncelleniyor (arka planda)...")
        self.on_update_ytdlp()

    def open_browser_setup(self):
        dlg = BrowserSetupDialog(parent=self)
        dlg.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        dlg.exec()

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
        s["download_subtitles"] = self.sub_chk.isChecked()
        s["subtitle_langs"] = self.sub_langs_input.text().strip() or "tr,en"
        s["cookie_browser"] = self.yt_cookie_combo.currentData()
        s["confirm_extension_downloads"] = self.confirm_chk.isChecked()
        s["clipboard_monitor"] = self.clipboard_chk.isChecked()
        s["minimize_to_tray"] = self.tray_chk.isChecked()
        new_theme = self.theme_combo.currentData()
        theme_changed = new_theme != s.get("theme", "system")
        s["theme"] = new_theme
        self.queue_manager.save_settings()
        if theme_changed:
            app = QApplication.instance()
            if app is not None:
                theme.apply(app, new_theme)
        self.accept()

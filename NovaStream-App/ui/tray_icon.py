"""
NovaStream Sistem Tepsisi (Tray Icon) ve Masaüstü Bildirimleri
"""

import os
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from core.bridge_server import APP_VERSION


class NovaTrayIcon(QSystemTrayIcon):
    def __init__(self, main_window, parent=None):
        icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "icon48.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        super().__init__(icon, parent)

        self.main_window = main_window
        self.setToolTip(f"NovaStream İndirme Yöneticisi v{APP_VERSION}")
        self.init_menu()

        self.activated.connect(self.on_activated)

    def init_menu(self):
        icons_dir = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")
        def get_ic(name):
            p = os.path.join(icons_dir, name)
            return QIcon(p) if os.path.exists(p) else QIcon()

        menu = QMenu()

        show_action = QAction("NovaStream'i Göster", self)
        show_action.triggered.connect(self.main_window.show_and_raise)
        menu.addAction(show_action)

        menu.addSeparator()

        add_action = QAction(get_ic("plus.svg"), "Yeni İndirme Ekle...", self)
        add_action.triggered.connect(self.main_window.open_add_download_dialog)
        menu.addAction(add_action)

        pause_all_action = QAction(get_ic("pause.svg"), "Tümünü Duraklat", self)
        pause_all_action.triggered.connect(self.main_window.queue_manager.pause_all)
        menu.addAction(pause_all_action)

        resume_all_action = QAction(get_ic("play.svg"), "Tümünü Devam Ettir", self)
        resume_all_action.triggered.connect(self.main_window.queue_manager.resume_all)
        menu.addAction(resume_all_action)

        menu.addSeparator()

        settings_action = QAction(get_ic("settings.svg"), "Ayarlar", self)
        settings_action.triggered.connect(self.main_window.open_settings_dialog)
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("Çıkış", self)
        quit_action.triggered.connect(self.main_window.really_quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def on_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.main_window.isVisible():
                self.main_window.hide()
            else:
                self.main_window.show_and_raise()

    def notify(self, title, message, is_error=False):
        icon = QSystemTrayIcon.MessageIcon.Critical if is_error else QSystemTrayIcon.MessageIcon.Information
        self.showMessage(title, message, icon, 4000)

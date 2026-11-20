"""
NovaStream Ana Kullanıcı Arayüzü (PyQt6 MainWindow)
IDM tarzı modern koyu dashboard, kategori kenar çubuğu, araç çubuğu ve indirme tablosu.
"""

import os
import subprocess
import sys
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QAction, QColor
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QListWidget,
    QListWidgetItem, QLabel, QPushButton, QProgressBar,
    QMessageBox, QMenu, QApplication
)

from core.bridge_server import normalize_cookie_text
from core.engine import format_bytes, format_speed
from core.updater import maybe_auto_update, update_components
from ui.download_dialog import DownloadDialog
from ui.progress_dialog import ProgressDialog
from ui.settings_dialog import SettingsDialog
from ui.tray_icon import NovaTrayIcon


ICONS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")

def get_icon(name):
    path = os.path.join(ICONS_DIR, name)
    return QIcon(path) if os.path.exists(path) else QIcon()


class MainWindow(QMainWindow):
    # Köprü sunucusu (HTTP thread) -> GUI thread aktarımı için sinyal
    external_download_signal = pyqtSignal(dict)
    show_signal = pyqtSignal()
    notify_signal = pyqtSignal(str, str)

    def __init__(self, queue_manager, bridge_server):
        super().__init__()
        self.queue_manager = queue_manager
        self.bridge_server = bridge_server

        self.setWindowTitle("NovaStream - İndirme Yöneticisi")
        self.resize(1060, 620)
        self.setMinimumSize(840, 480)

        icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "icon48.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.current_filter = "All"
        self.progress_dialogs = {}  # task_id -> ProgressDialog
        self.last_clipboard_url = ""

        self.init_ui()
        self.init_tray()
        self.init_clipboard_monitor()

        # UI güncelleme zamanlayıcısı (500ms)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_table_data)
        self.timer.start(500)

        # Köprü sunucusundan yeni indirme geldiğinde UI'da modal aç.
        # İstek HTTP iş parçacığından gelir; sinyal ile GUI iş parçacığına aktarılır
        # (başka thread'den QTimer.singleShot hiçbir zaman tetiklenmez).
        self.external_download_signal.connect(self._show_external_download_dialog)
        self.bridge_server.on_new_download_request = self.external_download_signal.emit
        self.show_signal.connect(self.show_and_raise)
        self.bridge_server.on_show_request = self.show_signal.emit
        self.notify_signal.connect(lambda t, m: self.tray.notify(t, m))
        self._update_bridge_status()

        # Haftalık yt-dlp/Deno güncellemesi (arka planda)
        QTimer.singleShot(5000, lambda: maybe_auto_update(self.queue_manager))

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Üst Araç Çubuğu (Toolbar)
        toolbar = QWidget()
        toolbar.setObjectName("ToolbarWidget")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(10, 6, 10, 6)
        tb_layout.setSpacing(6)

        self.btn_add = QPushButton("İndirme Ekle")
        self.btn_add.setIcon(get_icon("plus.svg"))
        self.btn_add.setProperty("class", "tool-btn-primary")
        self.btn_add.clicked.connect(self.open_add_download_dialog)
        tb_layout.addWidget(self.btn_add)

        self.btn_resume = QPushButton("Devam Et")
        self.btn_resume.setIcon(get_icon("play.svg"))
        self.btn_resume.setProperty("class", "tool-btn")
        self.btn_resume.clicked.connect(self.action_resume_selected)
        tb_layout.addWidget(self.btn_resume)

        self.btn_pause = QPushButton("Duraklat")
        self.btn_pause.setIcon(get_icon("pause.svg"))
        self.btn_pause.setProperty("class", "tool-btn")
        self.btn_pause.clicked.connect(self.action_pause_selected)
        tb_layout.addWidget(self.btn_pause)

        self.btn_delete = QPushButton("Sil")
        self.btn_delete.setIcon(get_icon("trash.svg"))
        self.btn_delete.setProperty("class", "tool-btn")
        self.btn_delete.clicked.connect(self.action_delete_selected)
        tb_layout.addWidget(self.btn_delete)

        tb_layout.addStretch()

        self.btn_open_folder = QPushButton("İndirilenler")
        self.btn_open_folder.setIcon(get_icon("folder.svg"))
        self.btn_open_folder.setProperty("class", "tool-btn")
        self.btn_open_folder.clicked.connect(self.open_downloads_dir)
        tb_layout.addWidget(self.btn_open_folder)

        self.btn_settings = QPushButton("Ayarlar")
        self.btn_settings.setIcon(get_icon("settings.svg"))
        self.btn_settings.setProperty("class", "tool-btn")
        self.btn_settings.clicked.connect(self.open_settings_dialog)
        tb_layout.addWidget(self.btn_settings)

        main_layout.addWidget(toolbar)

        # 2. Orta Alan (Sidebar + Tablo)
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Sol Kenar Çubuğu (Kategoriler)
        sidebar = QWidget()
        sidebar.setObjectName("SidebarWidget")
        sidebar.setFixedWidth(180)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 6, 0, 6)
        sb_layout.setSpacing(2)

        lbl_cats = QLabel("İNDİRMELER")
        lbl_cats.setObjectName("SidebarTitle")
        sb_layout.addWidget(lbl_cats)

        self.cat_list = QListWidget()
        self.cat_list.setObjectName("CategoryList")
        categories = [
            ("Tüm İndirmeler", "All", "layers.svg"),
            ("İndiriliyor", "Downloading", "activity.svg"),
            ("Duraklatıldı", "Paused", "pause.svg"),
            ("Tamamlandı", "Completed", "check.svg"),
            ("Hatalı", "Error", "alert-circle.svg"),
            ("Videolar", "Videos", "video.svg"),
            ("Müzik", "Music", "music.svg"),
            ("Sıkıştırılmış", "Compressed", "archive.svg"),
            ("Belgeler", "Documents", "file-text.svg"),
            ("Programlar", "Programs", "box.svg"),
            ("Diğer", "Others", "file-text.svg")
        ]
        for label, key, icon_name in categories:
            item = QListWidgetItem(get_icon(icon_name), label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.cat_list.addItem(item)

        self.cat_list.setCurrentRow(0)
        self.cat_list.itemClicked.connect(self.on_category_changed)
        sb_layout.addWidget(self.cat_list)
        content_layout.addWidget(sidebar)

        # Sağ Alan (Tablo)
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Dosya Adı", "Boyut", "İlerleme", "Hız", "Kalan Süre", "Durum", "Kategori", "Tarih"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)  # Yüksek bilgi yoğunluğu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.doubleClicked.connect(self.on_row_double_clicked)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Dosya adı
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 130)  # İlerleme
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)

        content_layout.addWidget(self.table)
        main_layout.addWidget(content_widget)

        # 3. Alt Durum Çubuğu (Status Bar)
        self.status_bar = self.statusBar()
        self.status_lbl_speed = QLabel("Toplam Hız: 0.0 B/s")
        self.status_lbl_bridge = QLabel("")

        self.status_bar.addWidget(self.status_lbl_speed)
        self.status_bar.addPermanentWidget(self.status_lbl_bridge)

    def _update_bridge_status(self):
        if self.bridge_server.running:
            self.status_lbl_bridge.setText(f"Tarayıcı Köprüsü Aktif (Port {self.bridge_server.port})")
            self.status_lbl_bridge.setStyleSheet("color: #10b981; font-weight: 600;")
        else:
            self.status_lbl_bridge.setText(f"Tarayıcı Köprüsü Kapalı: {self.bridge_server.error or 'başlatılamadı'}")
            self.status_lbl_bridge.setStyleSheet("color: #f87171; font-weight: 600;")

    def init_tray(self):
        self.tray = NovaTrayIcon(self)
        self.tray.show()

    def init_clipboard_monitor(self):
        clipboard = QApplication.clipboard()
        clipboard.dataChanged.connect(self.check_clipboard)

    def check_clipboard(self):
        if not self.queue_manager.settings.get("clipboard_monitor"):
            return
        text = QApplication.clipboard().text().strip()
        if not text or text == self.last_clipboard_url:
            return

        # URL format kontrolü
        if text.startswith("http://") or text.startswith("https://"):
            valid_exts = (".mp4", ".mkv", ".webm", ".ts", ".m3u8", ".zip", ".rar", ".7z", ".iso", ".exe", ".pdf")
            is_media = any(text.lower().split("?")[0].endswith(ext) for ext in valid_exts)
            is_video_platform = any(domain in text.lower() for domain in ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "x.com", "twitter.com"))

            if is_media or is_video_platform:
                self.last_clipboard_url = text
                # IDM tarzı bildirim ve diyalog teklifi
                dialog = DownloadDialog(download_info=self._dialog_defaults({
                    "url": text,
                    "title": "",
                    "isStream": is_video_platform
                }), parent=self)
                dialog.download_requested.connect(self.on_download_requested)
                dialog.show()

    def on_category_changed(self, item):
        self.current_filter = item.data(Qt.ItemDataRole.UserRole)
        self.refresh_table_data(force=True)

    def get_filtered_tasks(self):
        all_tasks = self.queue_manager.snapshot()
        if self.current_filter == "All":
            return all_tasks
        elif self.current_filter == "Downloading":
            return [t for t in all_tasks if t.status == "downloading"]
        elif self.current_filter == "Paused":
            return [t for t in all_tasks if t.status == "paused"]
        elif self.current_filter == "Completed":
            return [t for t in all_tasks if t.status == "completed"]
        elif self.current_filter == "Error":
            return [t for t in all_tasks if t.status == "error"]
        else:
            return [t for t in all_tasks if t.category == self.current_filter]

    def refresh_table_data(self, force=False):
        tasks = self.get_filtered_tasks()

        if self.table.rowCount() != len(tasks) or force:
            self.table.setRowCount(len(tasks))

        for row, t in enumerate(tasks):
            # 0: Dosya Adı
            item_name = self.table.item(row, 0)
            if not item_name:
                item_name = QTableWidgetItem(t.filename)
                self.table.setItem(row, 0, item_name)
            else:
                item_name.setText(t.filename)
            item_name.setData(Qt.ItemDataRole.UserRole, t.id)

            # 1: Boyut
            tot_str = format_bytes(t.total_bytes) if t.total_bytes > 0 else (format_bytes(t.downloaded_bytes) if t.downloaded_bytes > 0 else "-")
            self._set_cell(row, 1, tot_str)

            # 2: İlerleme Çubuğu
            prog_widget = self.table.cellWidget(row, 2)
            if not isinstance(prog_widget, QProgressBar):
                prog_widget = QProgressBar()
                prog_widget.setRange(0, 100)
                self.table.setCellWidget(row, 2, prog_widget)
            prog_widget.setValue(int(t.percent))

            # 3: Hız
            self._set_cell(row, 3, t.speed)

            # 4: Kalan Süre
            self._set_cell(row, 4, t.eta)

            # 5: Durum
            status_tr = {
                "downloading": "İndiriliyor",
                "completed": "Tamamlandı",
                "paused": "Duraklatıldı",
                "queued": "Kuyrukta",
                "error": "Hata"
            }.get(t.status, t.status.capitalize())
            status_item = self._set_cell(row, 5, status_tr)
            if status_item:
                if t.status == "error":
                    status_item.setForeground(QColor("#f87171"))
                    if t.error_message:
                        status_item.setToolTip(f"Hata Nedeni: {t.error_message}")
                else:
                    status_item.setForeground(QColor("#e4e6eb"))
                    status_item.setToolTip("")

            # 6: Kategori
            self._set_cell(row, 6, t.category)

            # 7: Tarih
            self._set_cell(row, 7, t.created_at)

            # İlerleme penceresi açıksa güncelle
            if t.id in self.progress_dialogs:
                self.progress_dialogs[t.id].update_data(t)

        # Durum çubuğu: tüm aktif indirmelerin toplam hızı
        active = [t for t in self.queue_manager.snapshot() if t.status == "downloading"]
        total_bps = sum(getattr(t, "speed_bps", 0.0) or 0.0 for t in active)
        self.status_lbl_speed.setText(f"Toplam Hız: {format_speed(total_bps)} ({len(active)} indirme)")

    def _set_cell(self, row, col, text):
        item = self.table.item(row, col)
        if not item:
            item = QTableWidgetItem(text)
            self.table.setItem(row, col, item)
        else:
            item.setText(text)
        return item

    def get_selected_task_id_and_task(self):
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 0)
            if item:
                tid = item.data(Qt.ItemDataRole.UserRole)
                task = self.queue_manager.tasks.get(tid)
                return tid, task
        return None, None

    def get_selected_task(self):
        _, task = self.get_selected_task_id_and_task()
        return task

    def on_row_double_clicked(self):
        task = self.get_selected_task()
        if task:
            self.open_progress_dialog(task)

    def open_progress_dialog(self, task):
        dlg = self.progress_dialogs.get(task.id)
        if not dlg or not dlg.isVisible():
            dlg = ProgressDialog(task, self.queue_manager, parent=self)
            self.progress_dialogs[task.id] = dlg
            dlg.show()
        else:
            dlg.raise_()
            dlg.activateWindow()

    def show_context_menu(self, pos):
        tid, task = self.get_selected_task_id_and_task()
        if not tid:
            return

        menu = QMenu(self)

        if task:
            if task.status == "downloading":
                act_pause = QAction(get_icon("pause.svg"), "Duraklat", self)
                act_pause.triggered.connect(lambda: self.queue_manager.pause_task(task.id))
                menu.addAction(act_pause)
            elif task.status in ("paused", "error", "queued"):
                act_resume = QAction(get_icon("play.svg"), "Devam Et", self)
                act_resume.triggered.connect(lambda: self.queue_manager.resume_task(task.id))
                menu.addAction(act_resume)

            menu.addSeparator()

            act_details = QAction(get_icon("activity.svg"), "Detaylar ve Bağlantı Haritası...", self)
            act_details.triggered.connect(lambda: self.open_progress_dialog(task))
            menu.addAction(act_details)

            if task.status == "completed" and task.target_path and os.path.exists(task.target_path):
                act_open = QAction(get_icon("file-text.svg"), "Dosyayı Aç", self)
                act_open.triggered.connect(lambda: self.open_path(task.target_path))
                menu.addAction(act_open)

                act_show = QAction(get_icon("folder.svg"), "Klasörde Göster", self)
                act_show.triggered.connect(lambda: self.open_path(os.path.dirname(task.target_path)))
                menu.addAction(act_show)

            menu.addSeparator()

            act_copy_url = QAction("URL'yi Kopyala", self)
            act_copy_url.triggered.connect(lambda: QApplication.clipboard().setText(task.url))
            menu.addAction(act_copy_url)

            menu.addSeparator()

        act_del_list = QAction("Listeden Kaldır", self)
        act_del_list.triggered.connect(lambda: self.delete_task(tid, delete_file=False))
        menu.addAction(act_del_list)

        act_del_file = QAction("Dosyayla Birlikte Sil", self)
        act_del_file.triggered.connect(self.action_delete_selected)  # onay sorar
        menu.addAction(act_del_file)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def delete_task(self, task_id, delete_file=False):
        removed = self.queue_manager.remove_task(task_id, delete_file=delete_file)
        if not removed:
            row = self.table.currentRow()
            tasks = self.get_filtered_tasks()
            if 0 <= row < len(tasks):
                self.queue_manager.remove_task(tasks[row].id, delete_file=delete_file)
        self.refresh_table_data(force=True)

    def action_resume_selected(self):
        task = self.get_selected_task()
        if task:
            self.queue_manager.resume_task(task.id)

    def action_pause_selected(self):
        task = self.get_selected_task()
        if task:
            self.queue_manager.pause_task(task.id)

    def action_delete_selected(self):
        tid, task = self.get_selected_task_id_and_task()
        if not tid:
            return

        filename = task.filename if task else "Seçili indirme"

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("İndirmeyi Sil")
        msg_box.setText(f"'{filename}' silinsin mi?")
        msg_box.setInformativeText("İndirilen dosyayı diskten de kalıcı olarak silmek istiyor musunuz?")

        btn_delete_both = msg_box.addButton("Dosyayla Birlikte Sil", QMessageBox.ButtonRole.DestructiveRole)
        btn_remove_only = msg_box.addButton("Yalnızca Listeden Kaldır", QMessageBox.ButtonRole.ActionRole)
        btn_cancel = msg_box.addButton("İptal", QMessageBox.ButtonRole.RejectRole)

        btn_delete_both.setStyleSheet(
            "background-color: #991b1b; color: #fef2f2; border: 1px solid #dc2626; border-radius: 4px; padding: 6px 14px; font-weight: 600;"
        )
        btn_remove_only.setStyleSheet(
            "background-color: #222631; color: #f0f3f6; border: 1px solid #2e3444; border-radius: 4px; padding: 6px 14px; font-weight: 600;"
        )
        btn_cancel.setStyleSheet(
            "background-color: #1b1e27; color: #94a3b8; border: 1px solid #272c38; border-radius: 4px; padding: 6px 14px; font-weight: 600;"
        )
        msg_box.setDefaultButton(btn_cancel)

        msg_box.exec()
        clicked = msg_box.clickedButton()
        if clicked == btn_delete_both:
            self.delete_task(tid, delete_file=True)
        elif clicked == btn_remove_only:
            self.delete_task(tid, delete_file=False)

    def open_add_download_dialog(self):
        clipboard_text = QApplication.clipboard().text().strip()
        initial_url = clipboard_text if (clipboard_text.startswith("http://") or clipboard_text.startswith("https://")) else ""

        dialog = DownloadDialog(download_info=self._dialog_defaults({"url": initial_url}), parent=self)
        dialog.download_requested.connect(self.on_download_requested)
        dialog.exec()

    def _dialog_defaults(self, info):
        info = dict(info)
        info.setdefault("default_dir", self.queue_manager.download_dir())
        info.setdefault("default_quality", self.queue_manager.settings.get("default_quality", "best"))
        return info

    def handle_external_download_request(self, data):
        """Chrome/Firefox eklentisinden köprüye indirme isteği geldiğinde çağrılır (her thread'den güvenli)."""
        self.external_download_signal.emit(data)

    def _show_external_download_dialog(self, data):
        self.show_and_raise()
        dialog = DownloadDialog(download_info=self._dialog_defaults(data), parent=self)
        cookie_text = normalize_cookie_text(data.get("cookies"))
        dialog.download_requested.connect(lambda p: self.on_download_requested(p, cookie_text=cookie_text))
        dialog.exec()

    def on_download_requested(self, payload, cookie_text=None):
        task = self.queue_manager.add_task(
            url=payload["url"],
            title=payload["title"] or None,
            destination_dir=payload["destination_dir"],
            is_stream=payload.get("is_stream", False),
            is_youtube=payload.get("is_youtube", False),
            referer=payload.get("referer"),
            auto_start=payload.get("auto_start", True),
            quality=payload.get("quality"),
            cookie_text=cookie_text
        )
        self.refresh_table_data(force=True)
        self.tray.notify("NovaStream", f"İndirme başladı:\n{task.filename}")

    def open_downloads_dir(self):
        self.open_path(self.queue_manager.download_dir())

    def open_settings_dialog(self):
        dlg = SettingsDialog(self.queue_manager, parent=self, on_update_ytdlp=self.update_ytdlp_now)
        dlg.exec()

    def update_ytdlp_now(self):
        def _done(ok, msg):
            if ok:
                import time as _t
                self.queue_manager.settings["last_ytdlp_update"] = _t.time()
                self.queue_manager.save_settings()
            self.notify_signal.emit("NovaStream", "yt-dlp güncellendi." if ok else f"Güncelleme başarısız: {msg[:120]}")
        update_components(_done)

    def open_path(self, path):
        if not path or not os.path.exists(path):
            return
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.run(["xdg-open", path], check=False)

    def show_and_raise(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        # Sistem tepsisine küçült
        if self.tray.isVisible() and self.queue_manager.settings.get("minimize_to_tray", True):
            self.hide()
            self.tray.notify("NovaStream", "NovaStream arka planda sistem tepsisinde çalışıyor.")
            event.ignore()
        else:
            event.accept()
            self.really_quit()

    def really_quit(self):
        self.queue_manager.shutdown()
        self.tray.hide()
        QApplication.quit()

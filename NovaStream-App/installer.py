#!/usr/bin/env python3
"""
NovaStream Kurulum Sihirbazı (Linux & Windows)
Modern, IDM tarzı çift tıklanabilir grafiksel kurulum programı.
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.request

# Gömülü Python (._pth) betik klasörünü sys.path'e eklemez; elle ekle
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QStackedWidget, QWidget, QLineEdit, QFileDialog,
    QCheckBox, QProgressBar, QMessageBox
)

from ui.styles import MAIN_STYLESHEET

APP_DIR = os.path.dirname(os.path.abspath(__file__))
IS_WINDOWS = sys.platform == "win32"


def get_default_install_dir():
    if IS_WINDOWS:
        local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(local_app_data, "NovaStream")
    return os.path.expanduser("~/.local/share/NovaStream")


SOURCE_ROOT = os.path.dirname(APP_DIR)            # NovaStream/ (eklenti klasörlerinin bulunduğu yer)
CHROME_SRC = os.path.join(SOURCE_ROOT, "NovaStream-v2")
FIREFOX_SRC = os.path.join(SOURCE_ROOT, "NovaStream-Firefox")
EXT_DIR_NAME = "OpenVideoDownloader-Extension"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def app_is_running():
    try:
        with urllib.request.urlopen("http://127.0.0.1:9191/api/ping", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def stop_runtime_processes(runtime_dir):
    """Windows: kurulu gömülü Python'u kullanan süreçleri (uygulama, tarayıcının native host'u) kapatır."""
    if not IS_WINDOWS or not os.path.isdir(runtime_dir):
        return
    ps = ("$d = [IO.Path]::GetFullPath($env:NS_RT).TrimEnd('\\') + '\\'; "
          "Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($d, [StringComparison]::OrdinalIgnoreCase) "
          "-and $_.Id -ne [int]$env:NS_SELF } | Stop-Process -Force -ErrorAction SilentlyContinue")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       env=dict(os.environ, NS_RT=runtime_dir, NS_SELF=str(os.getpid())),
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
    except Exception:
        pass


def mirror_tree(src, dst):
    """src'yi dst'ye eşitler: yalnız değişen dosyaları kopyalar, fazlalıkları siler.
    Klasörü önce silmediği için yarıda kalsa bile çalışma ortamı bozulmaz."""
    wanted = set()
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel = os.path.relpath(root, src)
        troot = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(troot, exist_ok=True)
        wanted.add(os.path.normcase(os.path.abspath(troot)))
        for name in files:
            s_path, d_path = os.path.join(root, name), os.path.join(troot, name)
            wanted.add(os.path.normcase(os.path.abspath(d_path)))
            st = os.stat(s_path)
            if os.path.exists(d_path):
                dt = os.stat(d_path)
                if dt.st_size == st.st_size and int(dt.st_mtime) == int(st.st_mtime):
                    continue
            try:
                shutil.copy2(s_path, d_path)
            except PermissionError:
                raise RuntimeError(f"{d_path} kullanımda. Tarayıcıyı ve NovaStream'i kapatıp kurulumu tekrar çalıştırın.")
    for root, dirs, files in os.walk(dst, topdown=False):
        for name in files:
            path = os.path.join(root, name)
            if os.path.normcase(os.path.abspath(path)) not in wanted:
                try:
                    os.remove(path)
                except OSError:
                    pass
        if os.path.normcase(os.path.abspath(root)) not in wanted:
            try:
                os.rmdir(root)
            except OSError:
                pass


def target_python(target_dir, windowed=False):
    """Kurulum klasöründeki Python: önce gömülü çalışma ortamı (runtime), sonra venv."""
    if IS_WINDOWS:
        exe = "pythonw.exe" if windowed else "python.exe"
        for cand in (os.path.join(target_dir, "runtime", exe), os.path.join(target_dir, "venv", "Scripts", exe)):
            if os.path.exists(cand):
                return cand
    else:
        cand = os.path.join(target_dir, "venv", "bin", "python3")
        if os.path.exists(cand):
            return cand
    return None


class InstallWorker(QThread):
    progress_changed = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, target_dir, options):
        super().__init__()
        self.target_dir = target_dir
        self.options = options  # desktop_shortcut, menu_shortcut, browser_integration

    def _run(self, cmd, **kw):
        kw.setdefault("check", True)
        if IS_WINDOWS:
            kw.setdefault("creationflags", NO_WINDOW)
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, **kw)

    def run(self):
        try:
            if app_is_running():
                raise RuntimeError("NovaStream şu anda açık. Lütfen sistem tepsisinden 'Çıkış' ile kapatıp kurulumu tekrar başlatın.")

            self.progress_changed.emit(5, "Hedef klasör hazırlanıyor...")
            os.makedirs(self.target_dir, exist_ok=True)

            # 1. Uygulama dosyaları
            self.progress_changed.emit(15, "NovaStream dosyaları kopyalanıyor...")
            for d in ("core", "ui", "assets"):
                src, dst = os.path.join(APP_DIR, d), os.path.join(self.target_dir, d)
                if os.path.exists(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
            for f in ("main.py", "requirements.txt", "run_linux.sh", "run_windows.bat", "README.md"):
                src = os.path.join(APP_DIR, f)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(self.target_dir, f))

            # 2. Tarayıcı entegrasyonu dosyaları (native host + eklenti klasörleri) tek yerde
            self.progress_changed.emit(25, "Tarayıcı eklentisi dosyaları kopyalanıyor...")
            browser_dir = os.path.join(self.target_dir, "browser")
            os.makedirs(browser_dir, exist_ok=True)
            for f in ("native_host.py", "native_host.bat", "native_host.sh"):
                src = os.path.join(CHROME_SRC, f)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(browser_dir, f))
            for src_root, name in ((CHROME_SRC, "chrome"), (FIREFOX_SRC, "firefox")):
                src = os.path.join(src_root, EXT_DIR_NAME)
                dst = os.path.join(browser_dir, name)
                if os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)

            # 3. Python çalışma ortamı: gömülü (Windows) veya venv
            self.progress_changed.emit(35, "Python çalışma ortamı hazırlanıyor (birkaç dakika sürebilir)...")
            self._prepare_python()

            # 4. yt-dlp / Deno / FFmpeg
            self.progress_changed.emit(65, "yt-dlp ve FFmpeg kontrol ediliyor...")
            self._ensure_dependencies()

            if not IS_WINDOWS:
                for f in ("run_linux.sh", "main.py", os.path.join("browser", "native_host.sh"), os.path.join("browser", "native_host.py")):
                    p = os.path.join(self.target_dir, f)
                    if os.path.exists(p):
                        os.chmod(p, 0o755)

            # 5. Kısayollar
            self.progress_changed.emit(85, "Kısayollar oluşturuluyor...")
            self._create_shortcuts()

            # 6. Tarayıcı köprüsü kaydı
            if self.options.get("browser_integration"):
                self.progress_changed.emit(95, "Tarayıcı köprüleri (Chrome, Edge, Brave, Firefox) kaydediliyor...")
                sys.path.insert(0, os.path.join(self.target_dir))
                from core.native_messaging import register
                register(browser_dir)

            self.progress_changed.emit(100, "Kurulum tamamlandı!")
            self.finished_signal.emit(True, browser_dir)
        except subprocess.CalledProcessError as e:
            self.finished_signal.emit(False, f"Komut başarısız oldu ({e.returncode}): {' '.join(map(str, e.cmd))[:300]}")
        except Exception as e:
            self.finished_signal.emit(False, str(e))

    def _prepare_python(self):
        req = os.path.join(self.target_dir, "requirements.txt")
        bundled_runtime = os.path.join(APP_DIR, "runtime")
        if IS_WINDOWS and os.path.exists(os.path.join(bundled_runtime, "python.exe")):
            dst = os.path.join(self.target_dir, "runtime")
            if os.path.normcase(os.path.abspath(dst)) != os.path.normcase(os.path.abspath(bundled_runtime)):
                self.progress_changed.emit(40, "Gömülü Python kopyalanıyor...")
                # Tarayıcının açık tuttuğu native host ya da açık uygulama python.exe'yi kilitler.
                stop_runtime_processes(dst)
                mirror_tree(bundled_runtime, dst)
            # Eski venv kurulumundan kalan klasör karışıklık yaratmasın
            old_venv = os.path.join(self.target_dir, "venv")
            if os.path.isdir(old_venv):
                shutil.rmtree(old_venv, ignore_errors=True)
            return

        venv_dir = os.path.join(self.target_dir, "venv")
        if not target_python(self.target_dir):
            self._run([sys.executable, "-m", "venv", venv_dir])
        py = target_python(self.target_dir)
        self.progress_changed.emit(45, "Kütüphaneler kuruluyor / güncelleniyor...")
        self._run([py, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-U", "-r", req])

    def _ensure_dependencies(self):
        py = target_python(self.target_dir)
        if py:
            probe = self._run([py, "-c", "import yt_dlp"], check=False, capture_output=True)
            if probe.returncode != 0:
                self.progress_changed.emit(68, "yt-dlp kuruluyor...")
                self._run([py, "-m", "pip", "install", "--quiet", "-U", "yt-dlp[default]", "deno"], check=False)

        if shutil.which("ffmpeg"):
            return
        if IS_WINDOWS:
            pkgs = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
            if os.path.isdir(pkgs) and any(n.startswith("Gyan.FFmpeg") for n in os.listdir(pkgs)):
                return
            if shutil.which("winget"):
                self.progress_changed.emit(72, "FFmpeg kuruluyor (birkaç dakika sürebilir)...")
                self._run(["winget", "install", "--id", "Gyan.FFmpeg", "-e", "--silent",
                           "--accept-package-agreements", "--accept-source-agreements",
                           "--disable-interactivity"], check=False)
        else:
            for mgr in (["pkexec", "apt-get", "install", "-y", "ffmpeg"],
                        ["pkexec", "dnf", "install", "-y", "ffmpeg"],
                        ["pkexec", "pacman", "-S", "--noconfirm", "ffmpeg"]):
                if shutil.which(mgr[1]) and shutil.which("pkexec"):
                    self.progress_changed.emit(72, "FFmpeg kuruluyor...")
                    self._run(mgr, check=False)
                    break

    def _create_shortcuts(self):
        if IS_WINDOWS:
            target_bat = os.path.join(self.target_dir, "run_windows.bat")
            icon_ico = os.path.join(self.target_dir, "assets", "icon.ico")
            places = []
            if self.options.get("desktop_shortcut"):
                places.append("[Environment]::GetFolderPath('Desktop')")
            if self.options.get("menu_shortcut"):
                places.append("[Environment]::GetFolderPath('Programs')")
            pyw = target_python(self.target_dir, windowed=True)
            main_py = os.path.join(self.target_dir, "main.py")
            # pythonw.exe'yi doğrudan açan kısayol: açılışta konsol penceresi yanıp sönmez
            target, args = (pyw, f'"{main_py}"') if pyw else (target_bat, "")
            def q(x):  # PowerShell tek tırnak kaçışı
                return str(x).replace("'", "''")
            for place in places:
                ps = (
                    "$ws = New-Object -ComObject WScript.Shell; "
                    f"$s = $ws.CreateShortcut({place} + '\\NovaStream.lnk'); "
                    f"$s.TargetPath = '{q(target)}'; "
                    f"$s.Arguments = '{q(args)}'; "
                    f"$s.WorkingDirectory = '{q(self.target_dir)}'; "
                    f"$s.IconLocation = '{q(icon_ico)}'; "
                    "$s.Save()"
                )
                self._run(["powershell", "-NoProfile", "-Command", ps], check=False)
            return

        exec_path = os.path.join(self.target_dir, "run_linux.sh")
        icon_png = os.path.join(self.target_dir, "assets", "icon128.png")
        desktop_content = (
            "[Desktop Entry]\nVersion=1.0\nType=Application\nName=NovaStream\nGenericName=Download Manager\n"
            "Comment=Modern, yüksek hızlı ve çok kanallı indirme yöneticisi\n"
            f"Exec=\"{exec_path}\" %U\nIcon={icon_png}\nTerminal=false\nCategories=Network;FileTransfer;\n"
            "StartupNotify=true\n"
        )
        if self.options.get("menu_shortcut"):
            menu_dir = os.path.expanduser("~/.local/share/applications")
            os.makedirs(menu_dir, exist_ok=True)
            desktop_file = os.path.join(menu_dir, "novastream.desktop")
            with open(desktop_file, "w", encoding="utf-8") as f:
                f.write(desktop_content)
            os.chmod(desktop_file, 0o755)
            if shutil.which("update-desktop-database"):
                self._run(["update-desktop-database", menu_dir], check=False)
        if self.options.get("desktop_shortcut"):
            desk = None
            if shutil.which("xdg-user-dir"):
                r = self._run(["xdg-user-dir", "DESKTOP"], check=False, capture_output=True, text=True)
                desk = (r.stdout or "").strip() or None
            for df in [desk, os.path.expanduser("~/Masaüstü"), os.path.expanduser("~/Desktop")]:
                if df and os.path.isdir(df):
                    desk_file = os.path.join(df, "NovaStream.desktop")
                    with open(desk_file, "w", encoding="utf-8") as f:
                        f.write(desktop_content)
                    os.chmod(desk_file, 0o755)
                    break
        bin_dir = os.path.expanduser("~/.local/bin")
        if os.path.isdir(bin_dir):
            link_path = os.path.join(bin_dir, "novastream")
            try:
                if os.path.lexists(link_path):
                    os.remove(link_path)
                os.symlink(exec_path, link_path)
            except OSError:
                pass


class InstallerWizard(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NovaStream - Kurulum Sihirbazı")
        self.resize(580, 420)
        self.setFixedSize(580, 420)

        icon_path = os.path.join(APP_DIR, "assets", "icon48.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.setStyleSheet(MAIN_STYLESHEET)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Üst Başlık Banner
        header = QWidget()
        header.setStyleSheet("background-color: #0f172a; border-bottom: 1px solid #1e293b;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(20, 14, 20, 14)

        logo_lbl = QLabel()
        logo_path = os.path.join(APP_DIR, "assets", "icon48.png")
        if os.path.exists(logo_path):
            logo_lbl.setPixmap(QPixmap(logo_path).scaled(42, 42, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        h_layout.addWidget(logo_lbl)

        title_box = QVBoxLayout()
        t1 = QLabel("NovaStream İndirme Yöneticisi")
        t1.setStyleSheet("font-size: 16px; font-weight: 800; color: #38bdf8;")
        t2 = QLabel("Kurulum Sihirbazı (Linux & Windows)")
        t2.setStyleSheet("font-size: 11px; color: #94a3b8;")
        title_box.addWidget(t1)
        title_box.addWidget(t2)
        h_layout.addLayout(title_box)
        h_layout.addStretch()

        layout.addWidget(header)

        # Çok Sayfalı Alan (QStackedWidget)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self.page_welcome = self.create_page_welcome()
        self.page_options = self.create_page_options()
        self.page_progress = self.create_page_progress()
        self.page_finish = self.create_page_finish()

        self.stack.addWidget(self.page_welcome)   # 0
        self.stack.addWidget(self.page_options)   # 1
        self.stack.addWidget(self.page_progress)  # 2
        self.stack.addWidget(self.page_finish)    # 3

        # Alt Buton Çubuğu
        footer = QWidget()
        footer.setStyleSheet("background-color: #0f172a; border-top: 1px solid #1e293b;")
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(20, 12, 20, 12)

        self.btn_back = QPushButton("← Geri")
        self.btn_back.setProperty("class", "tool-btn")
        self.btn_back.clicked.connect(self.go_back)
        self.btn_back.setVisible(False)

        self.btn_next = QPushButton("İleri →")
        self.btn_next.setProperty("class", "tool-btn-primary")
        self.btn_next.clicked.connect(self.go_next)

        self.btn_cancel = QPushButton("İptal")
        self.btn_cancel.setProperty("class", "tool-btn")
        self.btn_cancel.clicked.connect(self.reject)

        f_layout.addWidget(self.btn_back)
        f_layout.addStretch()
        f_layout.addWidget(self.btn_cancel)
        f_layout.addWidget(self.btn_next)

        layout.addWidget(footer)

    def create_page_welcome(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(24, 20, 24, 20)
        l.setSpacing(12)

        lbl = QLabel("NovaStream Kurulumuna Hoş Geldiniz")
        lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        l.addWidget(lbl)

        desc = QLabel(
            "Bu sihirbaz, NovaStream İndirme Yöneticisi'ni bilgisayarınıza kuracak,\n"
            "masaüstü kısayollarını hazırlayacak ve Chrome ile Firefox tarayıcı\n"
            "entegrasyonlarını otomatik olarak yapılandıracaktır.\n\n"
            "• 16 Kanallı Turbo Dinamik İndirme Motoru (IDM Hızında)\n"
            "• YouTube 4K/8K ve HLS Medya Yakalama\n"
            "• Modern Koyu Arayüz ve Sistem Tepsisi Bildirimleri\n\n"
            "Devam etmek için 'İleri' butonuna tıklayın."
        )
        desc.setStyleSheet("color: #cbd5e1; font-size: 13px; line-height: 1.5;")
        l.addWidget(desc)
        l.addStretch()
        return w

    def create_page_options(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(24, 16, 24, 16)
        l.setSpacing(10)

        lbl = QLabel("Kurulum Ayarları")
        lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #f8fafc;")
        l.addWidget(lbl)

        l.addWidget(QLabel("Kurulum Dizini:"))
        dir_box = QHBoxLayout()
        self.dir_input = QLineEdit(get_default_install_dir())
        self.dir_btn = QPushButton("Gözat...")
        self.dir_btn.setProperty("class", "tool-btn")
        self.dir_btn.clicked.connect(self.browse_dir)
        dir_box.addWidget(self.dir_input)
        dir_box.addWidget(self.dir_btn)
        l.addLayout(dir_box)

        l.addSpacing(6)
        l.addWidget(QLabel("Ek Seçenekler:"))

        self.chk_desktop = QCheckBox("Masaüstüne NovaStream kısayolu oluştur")
        self.chk_desktop.setChecked(True)
        l.addWidget(self.chk_desktop)

        self.chk_menu = QCheckBox("Uygulama / Başlat menüsüne kısayol ekle")
        self.chk_menu.setChecked(True)
        l.addWidget(self.chk_menu)

        self.chk_browser = QCheckBox("Chrome, Firefox ve Brave tarayıcı köprülerini otomatik kaydet")
        self.chk_browser.setChecked(True)
        l.addWidget(self.chk_browser)

        l.addStretch()
        return w

    def create_page_progress(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(24, 30, 24, 30)
        l.setSpacing(14)

        lbl = QLabel("NovaStream Kuruluyor...")
        lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        l.addWidget(lbl)

        self.status_lbl = QLabel("Dosyalar kopyalanıyor...")
        self.status_lbl.setStyleSheet("color: #38bdf8;")
        l.addWidget(self.status_lbl)

        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        l.addWidget(self.prog_bar)

        l.addStretch()
        return w

    def create_page_finish(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(24, 30, 24, 30)
        l.setSpacing(14)

        header_layout = QHBoxLayout()
        check_icon_path = os.path.join(APP_DIR, "assets", "icons", "check.svg")
        if os.path.exists(check_icon_path):
            icon_lbl = QLabel()
            icon_lbl.setPixmap(QIcon(check_icon_path).pixmap(24, 24))
            header_layout.addWidget(icon_lbl)

        lbl = QLabel("Kurulum Başarıyla Tamamlandı")
        lbl.setStyleSheet("font-size: 17px; font-weight: 700; color: #10b981;")
        header_layout.addWidget(lbl)
        header_layout.addStretch()
        l.addLayout(header_layout)

        self.finish_desc = QLabel("NovaStream bilgisayarınıza başarıyla kuruldu.")
        self.finish_desc.setWordWrap(True)
        self.finish_desc.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.finish_desc.setStyleSheet("color: #cbd5e1; font-size: 13px; line-height: 1.5;")
        l.addWidget(self.finish_desc)

        self.chk_launch = QCheckBox("NovaStream'i Şimdi Başlat")
        self.chk_launch.setChecked(True)
        l.addWidget(self.chk_launch)

        l.addStretch()
        return w

    def browse_dir(self):
        chosen = QFileDialog.getExistingDirectory(self, "Kurulum Klasörü Seç", self.dir_input.text())
        if chosen:
            self.dir_input.setText(os.path.join(chosen, "NovaStream"))

    def go_next(self):
        idx = self.stack.currentIndex()
        if idx == 0:
            self.stack.setCurrentIndex(1)
            self.btn_back.setVisible(True)
            self.btn_next.setText("Kurulumu Başlat")
        elif idx == 1:
            self.stack.setCurrentIndex(2)
            self.btn_back.setVisible(False)
            self.btn_next.setVisible(False)
            self.btn_cancel.setVisible(False)
            self.start_installation()
        elif idx == 3:
            # Bitir
            if self.chk_launch.isChecked():
                self.launch_installed_app()
            self.accept()

    def go_back(self):
        idx = self.stack.currentIndex()
        if idx == 1:
            self.stack.setCurrentIndex(0)
            self.btn_back.setVisible(False)
            self.btn_next.setText("İleri →")

    def start_installation(self):
        target_dir = self.dir_input.text().strip()
        options = {
            "desktop_shortcut": self.chk_desktop.isChecked(),
            "menu_shortcut": self.chk_menu.isChecked(),
            "browser_integration": self.chk_browser.isChecked()
        }

        self.worker = InstallWorker(target_dir, options)
        self.worker.progress_changed.connect(self.on_progress)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, percent, text):
        self.prog_bar.setValue(percent)
        self.status_lbl.setText(text)

    def on_finished(self, success, message):
        if success:
            browser_dir = message
            self.finish_desc.setText(
                "NovaStream bilgisayarınıza başarıyla kuruldu.\n\n"
                "Tarayıcı eklentisini bu klasörlerden yükleyin (bir kez):\n"
                f"• Chrome / Edge / Brave: {os.path.join(browser_dir, 'chrome')}\n"
                "   (Uzantılar → Geliştirici modu → Paketlenmemiş öğe yükle)\n"
                f"• Firefox: {os.path.join(browser_dir, 'firefox', 'manifest.json')}\n"
                "   (about:debugging → Bu Firefox → Geçici eklenti yükle)"
            )
            self.stack.setCurrentIndex(3)
            self.btn_next.setVisible(True)
            self.btn_next.setText("Bitir")
            self.btn_cancel.setVisible(False)
        else:
            QMessageBox.critical(self, "Kurulum Hatası", f"Kurulum sırasında bir hata oluştu:\n{message}")
            self.reject()

    def launch_installed_app(self):
        target_dir = self.dir_input.text().strip()
        if IS_WINDOWS:
            pyw = target_python(target_dir, windowed=True)
            if pyw:
                subprocess.Popen([pyw, os.path.join(target_dir, "main.py")], cwd=target_dir,
                                 creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            else:
                bat = os.path.join(target_dir, "run_windows.bat")
                if os.path.exists(bat):
                    os.startfile(bat)
        else:
            sh = os.path.join(target_dir, "run_linux.sh")
            if os.path.exists(sh):
                subprocess.Popen([sh], start_new_session=True)


def run_silent(argv):
    """Pencere açmadan kurulum: installer.py --silent [--dir KLASÖR] [--no-shortcuts] [--no-browser]"""
    target = get_default_install_dir()
    if "--dir" in argv:
        target = argv[argv.index("--dir") + 1]
    options = {
        "desktop_shortcut": "--no-shortcuts" not in argv,
        "menu_shortcut": "--no-shortcuts" not in argv,
        "browser_integration": "--no-browser" not in argv,
    }
    worker = InstallWorker(target, options)
    result = {}
    worker.progress_changed.connect(lambda p, t: print(f"[{p:3d}%] {t}", flush=True))
    worker.finished_signal.connect(lambda ok, msg: result.update(ok=ok, msg=msg))
    worker.run()  # aynı iş parçacığında, senkron
    print(("[OK] " if result.get("ok") else "[HATA] ") + str(result.get("msg")), flush=True)
    return 0 if result.get("ok") else 1


def main():
    if "--silent" in sys.argv:
        sys.exit(run_silent(sys.argv))
    app = QApplication(sys.argv)
    wizard = InstallerWizard()
    wizard.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

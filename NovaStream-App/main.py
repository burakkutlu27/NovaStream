#!/usr/bin/env python3
"""
NovaStream Desktop - Ana Giriş Noktası
Linux ve Windows için IDM benzeri bağımsız indirme yöneticisi.
"""

import logging
import logging.handlers
import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


def _extend_path():
    """
    Uygulamanın kendi Python klasörünü (yt-dlp, deno) ve sonradan kurulan araçları (ffmpeg) PATH'e ekler.
    Windows'ta kullanıcı/sistem PATH'i kayıt defterinden yeniden okunur; böylece winget ile yeni kurulan
    araçlar bilgisayar yeniden başlatılmadan bulunur.
    """
    py_dir = os.path.dirname(sys.executable)
    parts = [py_dir, os.path.join(py_dir, "Scripts"), os.path.join(py_dir, "bin")]
    if sys.platform == "win32":
        try:
            import winreg
            for root, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
                try:
                    with winreg.OpenKey(root, key) as k:
                        parts.append(os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]))
                except OSError:
                    pass
        except Exception:
            pass
    parts = [p for p in parts if p]
    os.environ["PATH"] = os.pathsep.join(parts + [os.environ.get("PATH", "")])


def _setup_logging():
    from core.queue_manager import LOG_DIR
    os.makedirs(LOG_DIR, exist_ok=True)
    handlers = [logging.handlers.RotatingFileHandler(os.path.join(LOG_DIR, "novastream.log"),
                                                     maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")]
    if sys.stderr is not None:  # pythonw altında konsol yok
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        handlers=handlers, force=True)

    def _excepthook(exc_type, exc, tb):
        logging.critical("Yakalanmamış hata", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = _excepthook


_extend_path()
_setup_logging()

from PyQt6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from core.bridge_server import BridgeServer  # noqa: E402
from core.queue_manager import QueueManager  # noqa: E402
from ui import theme  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

INSTANCE_KEY = "NovaStream-" + (os.environ.get("USERNAME") or os.environ.get("USER") or "user")


def _forward_to_running_instance(argv):
    """Uygulama zaten açıksa ona 'göster' (ve varsa link) mesajı gönderir. Gönderildiyse True."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if not sock.waitForConnected(500):
        return False
    msg = "show"
    if len(argv) > 1 and argv[1].startswith("http"):
        msg = "url " + argv[1]
    sock.write(msg.encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def main():
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

    app = QApplication(sys.argv)
    app.setApplicationName("NovaStream")
    app.setApplicationDisplayName("NovaStream Download Manager")
    app.setOrganizationName("NovaStream")
    app.setQuitOnLastWindowClosed(False)

    # Tek örnek: ikinci açılış mevcut pencereyi öne getirir
    if _forward_to_running_instance(sys.argv):
        logging.info("NovaStream zaten çalışıyor; mevcut pencere öne getirildi.")
        return 0
    QLocalServer.removeServer(INSTANCE_KEY)  # çökmeden kalan eski soket
    instance_server = QLocalServer()
    instance_server.listen(INSTANCE_KEY)

    queue_manager = QueueManager()
    # Tema ayarı settings.json'da; pencere oluşturulmadan önce uygulanmalı
    theme.apply(app, queue_manager.settings.get("theme", "system"))
    bridge_server = BridgeServer(queue_manager=queue_manager)
    bridge_server.start()

    window = MainWindow(queue_manager=queue_manager, bridge_server=bridge_server)

    def _on_instance_message():
        conn = instance_server.nextPendingConnection()
        if not conn:
            return

        def _read():
            data = bytes(conn.readAll()).decode("utf-8", "replace").strip()
            window.show_and_raise()
            if data.startswith("url "):
                window.handle_external_download_request({"url": data[4:], "title": ""})
        if conn.bytesAvailable():
            _read()
        else:
            conn.readyRead.connect(_read)

    instance_server.newConnection.connect(_on_instance_message)

    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        window.handle_external_download_request({"url": sys.argv[1], "title": ""})

    window.show()
    exit_code = app.exec()

    bridge_server.stop()
    instance_server.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

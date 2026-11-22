"""
NovaStream Local Bridge Server
Chrome ve Firefox eklentilerinden gelen indirme isteklerini dinleyen yerel API sunucusu (127.0.0.1:9191).

Güvenlik: Tarayıcıdaki sıradan web sayfaları bu sunucuya istek gönderemez.
- Origin başlığı taşıyan istekler yalnızca eklenti kaynaklarından (chrome-extension://, moz-extension://) kabul edilir.
- CORS başlıkları yalnızca bu kaynaklara verilir; "*" kullanılmaz.
- Origin başlığı olmayan istekler (yerel araçlar, native host) kabul edilir; tarayıcılar web sayfası isteklerinde
  Origin'i her zaman gönderir ve sayfalar bu başlığı taklit edemez.
"""

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.engine import choose_target_path, sanitize_filename

PORT = 9191
APP_VERSION = "2.6.0"
ALLOWED_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://", "extension://", "safari-web-extension://")
MAX_BODY = 5 * 1024 * 1024


def origin_allowed(origin):
    if not origin:
        return True
    return origin.startswith(ALLOWED_ORIGIN_PREFIXES)



def normalize_cookie_text(text):
    """Eklentinin gönderdiği Netscape biçimli çerezleri (ör. üyelere özel videolar için) doğrular."""
    if not isinstance(text, str) or not text.strip() or len(text) > 512 * 1024:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("# Netscape HTTP Cookie File"):
        text = "# Netscape HTTP Cookie File\n" + text
    return text if text.endswith("\n") else text + "\n"

class BridgeRequestHandler(BaseHTTPRequestHandler):
    server_version = "NovaStreamBridge/" + APP_VERSION

    # ------------------------------------------------------------------ yardımcılar
    @property
    def bridge(self):
        return self.server.bridge

    def _origin(self):
        return self.headers.get("Origin", "")

    def _check_origin(self):
        origin = self._origin()
        if origin_allowed(origin):
            return True
        logging.warning(f"Köprü: izin verilmeyen kaynaktan istek reddedildi: {origin}")
        self._json(403, {"error": "forbidden"}, cors=False)
        return False

    def _cors(self):
        origin = self._origin()
        if origin and origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            # Chrome Private/Local Network Access ön kontrolü
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _json(self, code, obj, cors=True):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        if cors:
            self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0 or length > MAX_BODY:
            raise ValueError("Geçersiz istek boyutu")
        if "json" not in (self.headers.get("Content-Type") or "").lower():
            raise ValueError("Content-Type application/json olmalı")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # ------------------------------------------------------------------ uç noktalar
    def do_OPTIONS(self):
        if not origin_allowed(self._origin()):
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._check_origin():
            return
        qm = self.bridge.queue_manager
        if self.path == "/api/ping":
            self._json(200, {"status": "ok", "app": "NovaStream Desktop", "version": APP_VERSION})
        elif self.path == "/api/tasks":
            tasks = [t.to_dict() for t in qm.snapshot()] if qm else []
            self._json(200, {"tasks": tasks})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._check_origin():
            return
        try:
            data = self._read_json()
        except Exception as e:
            self._json(400, {"error": str(e)})
            return
        try:
            if self.path == "/api/download":
                self._handle_download(data)
            elif self.path == "/api/save_subtitle":
                self._handle_save_subtitle(data)
            elif self.path == "/api/task_progress":
                self._handle_progress(data)
            elif self.path == "/api/control":
                self._handle_control(data)
            elif self.path == "/api/show":
                if self.bridge.on_show_request:
                    self.bridge.on_show_request()
                self._json(200, {"success": True})
            else:
                self._json(404, {"error": "not found"})
        except Exception as e:
            logging.exception("Köprü isteği işlenemedi")
            self._json(500, {"error": str(e)})

    def _handle_download(self, data):
        url = (data.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            self._json(400, {"error": "Geçerli bir http(s) adresi gerekli"})
            return
        qm = self.bridge.queue_manager
        confirm = bool(qm and qm.settings.get("confirm_extension_downloads"))
        callback = self.bridge.on_new_download_request
        if confirm and callback:
            callback(data)
            self._json(200, {"success": True, "id": "pending_dialog", "desktop": True})
            return
        task = qm.add_task(
            url=url,
            title=data.get("title") or "video",
            is_stream=bool(data.get("isStream", False)),
            is_youtube=bool(data.get("isYouTube", False)),
            referer=data.get("referer"),
            quality=data.get("quality"),
            audio_lang=data.get("audioLang"),
            audio_name=data.get("audioName"),
            download_subtitles=bool(data.get("downloadSubtitles", qm.settings.get("download_subtitles", False))),
            auto_start=bool(data.get("autoStart", True)),
            cookie_text=self._cookie_text(data)
        )
        self._json(200, {"success": True, "id": task.id, "desktop": True})

    def _handle_save_subtitle(self, data):
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            self._json(400, {"error": "Geçerli altyazı içeriği gerekli"})
            return
        qm = self.bridge.queue_manager
        dest_dir = qm.download_dir() if qm else os.path.expanduser("~/Downloads")
        os.makedirs(dest_dir, exist_ok=True)
        raw_name = sanitize_filename(data.get("filename") or "altyazi.srt", fallback="altyazi.srt")
        base, ext = os.path.splitext(raw_name)
        if ext.lower() not in (".srt", ".vtt", ".ass", ".ssa"):
            raw_name = f"{base or 'altyazi'}.srt"
        target_path = choose_target_path(dest_dir, raw_name)
        with open(target_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        self._json(200, {
            "success": True,
            "filename": os.path.basename(target_path),
            "path": target_path
        })

    @staticmethod
    def _cookie_text(data):
        return normalize_cookie_text(data.get("cookies"))

    def _handle_control(self, data):
        """Eklentiden duraklat / devam / iptal."""
        qm = self.bridge.queue_manager
        task_id = data.get("id")
        action = data.get("action")
        task = qm.get_task(task_id) if (qm and task_id) else None
        if not task:
            self._json(404, {"error": "görev bulunamadı"})
            return
        if action == "pause":
            qm.pause_task(task_id)
        elif action == "resume":
            qm.resume_task(task_id)
        elif action == "cancel":
            qm.remove_task(task_id, delete_file=False)
        else:
            self._json(400, {"error": "geçersiz işlem"})
            return
        current = qm.get_task(task_id)
        self._json(200, {"success": True, "status": current.status if current else "removed"})

    def _handle_progress(self, data):
        """Eklentinin kendi yaptığı indirmeleri (tarayıcı ağı + native host) uygulama listesinde gösterir."""
        qm = self.bridge.queue_manager
        task_id = data.get("id")
        if not qm or not task_id:
            self._json(400, {"error": "id gerekli"})
            return
        from core.queue_manager import categorize_file
        title = data.get("filename") or data.get("title")
        task = qm.get_task(task_id)
        if not task:
            task = qm.add_task(url=data.get("url", ""), title=title or "video.mp4", task_id=task_id,
                               auto_start=False, external=True)
        elif title and title != task.filename:
            task.title = task.filename = title
            task.category = categorize_file(title, is_stream=True)

        status = data.get("status")
        pct = data.get("percent")
        if pct is not None:
            try:
                new_pct = float(pct)
                if status == "downloading" and task.status == "downloading" and task.percent < 100.0 and new_pct < task.percent:
                    new_pct = task.percent
                task.percent = new_pct
            except (TypeError, ValueError):
                pass
        if data.get("speedMb") is not None:
            task.speed = str(data["speedMb"])
        if data.get("eta") is not None:
            task.eta = str(data["eta"])

        if data.get("error") or status == "error":
            task.status = "error"
            task.error_message = data.get("error") or "Tarayıcı indirmesi başarısız oldu"
            task.speed = "Hata"
        elif status == "completed" or data.get("success") is True:
            task.status = "completed"
            task.percent = 100.0
            task.speed = "Tamamlandı"
            task.eta = ""
            target = os.path.join(task.destination_dir, task.filename)
            if os.path.isfile(target):
                task.target_path = target
                try:
                    task.total_bytes = task.downloaded_bytes = os.path.getsize(target)
                except OSError:
                    pass
        elif status == "downloading":
            task.status = "downloading"

        if task.status in ("completed", "error"):
            qm.save_history()
        qm._notify(task)
        self._json(200, {"success": True})

    def log_message(self, format, *args):
        pass


class BridgeServer:
    def __init__(self, queue_manager, on_new_download_request=None, port=PORT):
        self.queue_manager = queue_manager
        self.on_new_download_request = on_new_download_request  # her istekte okunur (sonradan bağlanabilir)
        self.on_show_request = None
        self.port = port
        self.server = None
        self.thread = None
        self.running = False
        self.error = None

    def start(self):
        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", self.port), BridgeRequestHandler)
            self.server.daemon_threads = True
            self.server.bridge = self
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.running = True
            logging.info(f"NovaStream Bridge Server 127.0.0.1:{self.port} adresinde başlatıldı.")
            return True
        except OSError as e:
            self.error = str(e)
            self.running = False
            logging.error(f"Bridge Server başlatılamadı: {e}")
            return False

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.running = False

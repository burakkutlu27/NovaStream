"""
NovaStream Queue & Task Manager
İndirme kuyruğu, eşzamanlı limitler, kategori ayrıştırma, ayarlar ve durum kalıcılığı.

Tüm görev listesi değişiklikleri tek bir kilit (self.lock) altında yapılır; köprü sunucusu,
indirme iş parçacıkları ve arayüz aynı anda erişebilir.
"""

import json
import logging
import os
import shutil
import sys
import threading
import time
import uuid

from core.engine import SegmentedDownloader, get_default_download_dir
from core.stream_handler import StreamDownloader

if sys.platform == "win32":
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming"), "NovaStream")
else:
    CONFIG_DIR = os.path.expanduser("~/.config/novastream")
HISTORY_FILE = os.path.join(CONFIG_DIR, "downloads_history.json")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
LOG_DIR = os.path.join(CONFIG_DIR, "logs")
COOKIE_DIR = os.path.join(CONFIG_DIR, "cookies")

EXT_CATEGORIES = {
    "Videos": ["mp4", "mkv", "webm", "avi", "mov", "flv", "wmv", "m4v", "ts", "m3u8", "mpd"],
    "Music": ["mp3", "m4a", "flac", "wav", "aac", "ogg", "wma", "opus"],
    "Compressed": ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "dmg"],
    "Documents": ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "epub", "csv"],
    "Programs": ["exe", "msi", "deb", "rpm", "appimage", "apk", "pkg", "sh"]
}

QUALITY_CHOICES = [
    ("best", "En iyi kalite"),
    ("2160", "4K (2160p)"),
    ("1080", "1080p"),
    ("720", "720p"),
    ("480", "480p"),
    ("audio", "Yalnızca ses (MP3)"),
]

DEFAULT_SETTINGS = {
    "max_concurrent": 3,
    "default_connections": 16,
    "download_dir": "",                 # boş = sistemin İndirilenler klasörü
    "cookie_browser": "" if sys.platform == "win32" else "chrome",  # "" = çerez kullanma
    "clipboard_monitor": False,
    "minimize_to_tray": True,
    "confirm_extension_downloads": False,
    "default_quality": "best",
    "last_ytdlp_update": 0,
}


def categorize_file(filename, is_stream=False):
    if is_stream:
        return "Videos"
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    for cat, exts in EXT_CATEGORIES.items():
        if ext in exts:
            return cat
    return "Others"


class DownloadTask:
    def __init__(
        self,
        url,
        title=None,
        destination_dir=None,
        is_stream=False,
        is_youtube=False,
        referer=None,
        headers=None,
        cookies=None,
        task_id=None,
        category=None,
        quality="best",
        external=False
    ):
        self.id = task_id or str(uuid.uuid4())
        self.url = url
        self.title = title or "Dosya"
        self.destination_dir = destination_dir or get_default_download_dir()
        self.is_stream = is_stream
        self.is_youtube = is_youtube
        self.referer = referer
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.quality = quality or "best"
        self.external = external  # indirmeyi tarayıcı eklentisi yapıyor; uygulama yalnızca izliyor

        self.filename = title or "download"
        self.target_path = None
        self.category = category or ("Videos" if is_stream else "Others")

        self.status = "queued"  # queued, downloading, paused, completed, error
        self.percent = 0.0
        self.speed = "0.0 B/s"
        self.eta = "--:--"
        self.speed_bps = 0.0
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self.error_message = None
        self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")

        self.downloader = None
        self.segments_data = []
        self.cookie_text = None   # eklentiden gelen çerezler; yalnızca bellekte, geçmişe yazılmaz
        self.cookie_file = None

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "filename": self.filename,
            "destination_dir": self.destination_dir,
            "target_path": self.target_path,
            "category": self.category,
            "is_stream": self.is_stream,
            "is_youtube": self.is_youtube,
            "referer": self.referer,
            "quality": self.quality,
            "external": self.external,
            "status": self.status,
            "percent": self.percent,
            "total_bytes": self.total_bytes,
            "downloaded_bytes": self.downloaded_bytes,
            "created_at": self.created_at,
            "error_message": self.error_message,
            "speed": self.speed,
            "eta": self.eta
        }


class QueueManager:
    def __init__(self, on_task_updated=None, on_task_finished=None):
        self.on_task_updated = on_task_updated
        self.on_task_finished = on_task_finished

        self.lock = threading.RLock()
        self.tasks = {}  # id -> DownloadTask
        self.settings = dict(DEFAULT_SETTINGS)

        os.makedirs(CONFIG_DIR, exist_ok=True)
        shutil.rmtree(COOKIE_DIR, ignore_errors=True)  # önceki oturumdan kalan çerez dosyaları
        self.load_settings()
        self.load_history()

    # ------------------------------------------------------------------ ayarlar
    @property
    def max_concurrent(self):
        return int(self.settings.get("max_concurrent", 3))

    @max_concurrent.setter
    def max_concurrent(self, value):
        self.settings["max_concurrent"] = int(value)

    @property
    def default_connections(self):
        return int(self.settings.get("default_connections", 16))

    @default_connections.setter
    def default_connections(self, value):
        self.settings["default_connections"] = int(value)

    def download_dir(self):
        d = self.settings.get("download_dir") or ""
        if d and os.path.isdir(d):
            return d
        return get_default_download_dir()

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                for k in DEFAULT_SETTINGS:
                    if k in stored:
                        self.settings[k] = stored[k]
            except Exception as e:
                logging.warning(f"Ayarlar okunamadı: {e}")

    def save_settings(self):
        try:
            tmp = SETTINGS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            os.replace(tmp, SETTINGS_FILE)
        except Exception as e:
            logging.error(f"Ayarlar kaydedilemedi: {e}")
        self.check_queue()

    # ------------------------------------------------------------------ geçmiş
    def load_history(self):
        if not os.path.exists(HISTORY_FILE):
            return
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                t = DownloadTask(
                    url=item.get("url", ""),
                    title=item.get("title"),
                    destination_dir=item.get("destination_dir"),
                    is_stream=item.get("is_stream", False),
                    is_youtube=item.get("is_youtube", False),
                    referer=item.get("referer"),
                    task_id=item["id"],
                    category=item.get("category"),
                    quality=item.get("quality", "best"),
                    external=item.get("external", False)
                )
                t.filename = item.get("filename", item.get("title"))
                t.target_path = item.get("target_path")
                status = item.get("status")
                t.status = status if status in ("completed", "error") else "paused"
                t.error_message = item.get("error_message")
                t.percent = item.get("percent", 0.0)
                t.total_bytes = item.get("total_bytes", 0)
                t.downloaded_bytes = item.get("downloaded_bytes", 0)
                t.created_at = item.get("created_at", "")
                t.speed = "Tamamlandı" if t.status == "completed" else ("Hata" if t.status == "error" else "Duraklatıldı")
                self.tasks[t.id] = t
        except Exception as e:
            logging.error(f"Geçmiş yükleme hatası: {e}")

    def save_history(self):
        try:
            with self.lock:
                records = [t.to_dict() for t in self.tasks.values()]
            tmp = HISTORY_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
            os.replace(tmp, HISTORY_FILE)
        except Exception as e:
            logging.error(f"Geçmiş kaydetme hatası: {e}")

    # ------------------------------------------------------------------ erişim
    def snapshot(self):
        """Arayüz için görevlerin kopya listesi (başka thread değiştirirken güvenli)."""
        with self.lock:
            return list(self.tasks.values())

    def get_task(self, task_id):
        with self.lock:
            return self.tasks.get(task_id)

    def _notify(self, task):
        if self.on_task_updated:
            try:
                self.on_task_updated(task)
            except Exception:
                logging.exception("on_task_updated hatası")

    # ------------------------------------------------------------------ ekleme
    def add_task(
        self,
        url,
        title=None,
        destination_dir=None,
        is_stream=False,
        is_youtube=False,
        referer=None,
        auto_start=True,
        task_id=None,
        quality=None,
        external=False,
        cookie_text=None
    ):
        with self.lock:
            if task_id and task_id in self.tasks:
                task = self.tasks[task_id]
                if title and (not task.filename or task.filename in ("Tarayıcı İndirmesi", "video.mp4", "download")):
                    task.title = title
                    task.filename = title
                    task.category = categorize_file(task.title, is_stream=is_stream)
                self.save_history()
                return task

            task = DownloadTask(
                url=url,
                title=title,
                destination_dir=destination_dir or self.download_dir(),
                is_stream=is_stream,
                is_youtube=is_youtube,
                referer=referer,
                task_id=task_id,
                quality=quality or self.settings.get("default_quality", "best"),
                external=external
            )
            task.category = categorize_file(task.title, is_stream=is_stream or is_youtube)
            if cookie_text:
                task.cookie_text = cookie_text
            if not title:
                task.filename = url  # gerçek ad indirme başlayınca belli olur
            if not auto_start:
                task.status = "paused" if not external else "downloading"
            self.tasks[task.id] = task
        self.save_history()
        self._notify(task)
        if auto_start:
            self.check_queue()
        return task

    # ------------------------------------------------------------------ kuyruk
    def check_queue(self):
        """Kuyrukta bekleyenleri boş yer varsa başlatır."""
        with self.lock:
            active = sum(1 for t in self.tasks.values() if t.status == "downloading" and not t.external)
            slots = self.max_concurrent - active
            to_start = []
            for t in self.tasks.values():
                if slots <= 0:
                    break
                if t.status == "queued":
                    to_start.append(t)
                    slots -= 1
            for t in to_start:
                self._start_locked(t)

    def start_task(self, task_id):
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            return self._start_locked(task)

    def _start_locked(self, task):
        if not task.url:
            task.status = "error"
            task.error_message = "Bu indirme tarayıcıda yapıldı; adresi bilinmediği için yeniden başlatılamıyor."
            self._notify(task)
            return False

        task.status = "downloading"
        task.error_message = None
        holder = {}

        def is_current():
            return task.downloader is holder.get("d")

        def _on_prog(p):
            if not is_current():
                return
            new_pct = p.get("percent", task.percent)
            # yt-dlp devam ederken (görüntü/ses parçaları) yüzdeyi baştan sayabiliyor; geri gitmesin
            if (task.is_stream or task.is_youtube) and new_pct < task.percent:
                new_pct = task.percent
            task.percent = new_pct
            task.speed = p.get("speed_formatted", task.speed)
            task.speed_bps = p.get("speed_bps", 0.0) or 0.0
            task.eta = p.get("eta_formatted", task.eta)
            if p.get("downloaded_bytes") is not None:
                task.downloaded_bytes = p["downloaded_bytes"]
            if p.get("total_bytes"):
                task.total_bytes = p["total_bytes"]
            if p.get("filename"):
                task.filename = p["filename"]
                task.category = categorize_file(task.filename, is_stream=task.is_stream or task.is_youtube)
            if p.get("target_path"):
                task.target_path = p["target_path"]
            if "segments" in p:
                task.segments_data = p["segments"]
            self._notify(task)

        def _on_done(path):
            if not is_current():
                return
            with self.lock:
                task.status = "completed"
                task.percent = 100.0
                task.speed = "Tamamlandı"
                task.speed_bps = 0.0
                task.eta = ""
                task.target_path = path
                self._drop_cookie_file(task)
                task.filename = os.path.basename(path)
                task.category = categorize_file(task.filename, is_stream=task.is_stream or task.is_youtube)
                try:
                    task.total_bytes = task.downloaded_bytes = os.path.getsize(path)
                except OSError:
                    pass
            self.save_history()
            self._notify(task)
            if self.on_task_finished:
                self.on_task_finished(task, True)
            self.check_queue()

        def _on_err(err):
            if not is_current():
                return
            with self.lock:
                task.status = "error"
                task.error_message = str(err)
                self._drop_cookie_file(task)
                task.speed = "Hata"
                task.speed_bps = 0.0
            self.save_history()
            self._notify(task)
            if self.on_task_finished:
                self.on_task_finished(task, False)
            self.check_queue()

        if task.is_stream or task.is_youtube:
            downloader = StreamDownloader(
                url=task.url,
                destination_dir=task.destination_dir,
                custom_title=None if task.title in ("Dosya", "download", "video", "") else task.title,
                referer=task.referer,
                is_youtube=task.is_youtube,
                browser_cookies=self.settings.get("cookie_browser") or None,
                cookie_file=self._write_cookie_file(task),
                quality=task.quality,
                on_progress=_on_prog,
                on_completed=_on_done,
                on_error=_on_err
            )
        else:
            task_headers = dict(task.headers or {})
            if task.referer:
                task_headers.setdefault("Referer", task.referer)
                try:
                    import urllib.parse
                    parsed = urllib.parse.urlparse(task.referer)
                    if parsed.scheme and parsed.netloc:
                        task_headers.setdefault("Origin", f"{parsed.scheme}://{parsed.netloc}")
                except Exception:
                    pass
            downloader = SegmentedDownloader(
                url=task.url,
                destination_dir=task.destination_dir,
                custom_filename=task.title if task.title not in ("Dosya", "download") else None,
                num_connections=self.default_connections,
                headers=task_headers,
                cookies=task.cookies,
                on_progress=_on_prog,
                on_completed=_on_done,
                on_error=_on_err
            )

        holder["d"] = downloader
        task.downloader = downloader
        self._notify(task)
        downloader.start()
        return True

    # ------------------------------------------------------------------ kontrol
    def pause_task(self, task_id):
        with self.lock:
            task = self.tasks.get(task_id)
            if not task or task.external:
                return
            if task.status == "queued":
                task.status = "paused"
            elif task.status == "downloading" and task.downloader:
                d = task.downloader
                if isinstance(d, SegmentedDownloader):
                    d.pause()
                else:
                    # yt-dlp: süreci durdur, .part dosyası kalır; devamda kaldığı yerden sürer
                    task.downloader = None
                    d.cancel(delete_partial=False)
                task.status = "paused"
            else:
                return
            task.speed = "Duraklatıldı"
            task.speed_bps = 0.0
        self.save_history()
        self._notify(task)
        self.check_queue()

    def resume_task(self, task_id):
        with self.lock:
            task = self.tasks.get(task_id)
            if not task or task.external or task.status not in ("paused", "error", "queued"):
                return
            d = task.downloader
            if task.status == "paused" and isinstance(d, SegmentedDownloader) and d.is_paused and d.is_running:
                active = sum(1 for t in self.tasks.values() if t.status == "downloading" and not t.external)
                if active < self.max_concurrent:
                    d.resume()
                    task.status = "downloading"
                else:
                    task.status = "queued"
            else:
                if d is not None:
                    task.downloader = None
                    try:
                        d.cancel(delete_partial=False)
                    except Exception:
                        pass
                task.status = "queued"
                task.error_message = None
        self._notify(task)
        self.check_queue()

    def remove_task(self, task_id, delete_file=False):
        with self.lock:
            task = self.tasks.pop(task_id, None)
            if not task:
                return False
        if task.downloader:
            d = task.downloader
            task.downloader = None
            try:
                d.cancel(delete_partial=True)
            except Exception:
                logging.exception("İptal hatası")
        self._drop_cookie_file(task, forget=True)
        if delete_file and task.status == "completed":
            target = task.target_path or os.path.join(task.destination_dir, task.filename)
            if target and os.path.isfile(target):
                try:
                    os.remove(target)
                except Exception as e:
                    logging.warning(f"Dosya silinemedi: {e}")
        self.save_history()
        self.check_queue()
        return True

    # ------------------------------------------------------------------ çerezler
    def _write_cookie_file(self, task):
        """Eklentinin gönderdiği çerezleri yalnızca kullanıcının okuyabileceği geçici bir dosyaya yazar."""
        if not task.cookie_text:
            return None
        try:
            os.makedirs(COOKIE_DIR, exist_ok=True)
            path = os.path.join(COOKIE_DIR, f"{task.id}.txt")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(task.cookie_text)
            task.cookie_file = path
            return path
        except Exception:
            logging.exception("Çerez dosyası yazılamadı")
            return None

    def _drop_cookie_file(self, task, forget=False):
        if task.cookie_file:
            try:
                os.remove(task.cookie_file)
            except OSError:
                pass
            task.cookie_file = None
        if forget or task.status == "completed":
            task.cookie_text = None

    def pause_all(self):
        for t in self.snapshot():
            if t.status in ("downloading", "queued"):
                self.pause_task(t.id)

    def resume_all(self):
        for t in self.snapshot():
            if t.status == "paused":
                self.resume_task(t.id)

    def shutdown(self):
        """Uygulama kapanırken yarım indirmeleri güvenle durdurur (dosyalar korunur)."""
        for t in self.snapshot():
            d = t.downloader
            if d is None:
                continue
            try:
                if isinstance(d, SegmentedDownloader):
                    d.pause()
                    d.cancel(delete_partial=False)
                else:
                    d.cancel(delete_partial=False)
            except Exception:
                pass
            if t.status == "downloading":
                t.status = "paused"
            self._drop_cookie_file(t, forget=True)
        self.save_history()

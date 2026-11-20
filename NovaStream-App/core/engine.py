"""
NovaStream Turbo Segmented Download Engine
IDM benzeri çok kanallı (multi-connection 8-32 thread) dinamik parçalı indirme motoru.
"""

import ctypes
import email.utils
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
import requests

CHUNK_BUFFER_SIZE = 64 * 1024  # 64 KB I/O buffer


def get_default_download_dir():
    if sys.platform == "win32":
        user_prof = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        win_dir = os.path.join(user_prof, "Downloads")
        os.makedirs(win_dir, exist_ok=True)
        return win_dir
    tr_dir = os.path.expanduser("~/İndirilenler")
    if os.path.exists(tr_dir):
        return tr_dir
    en_dir = os.path.expanduser("~/Downloads")
    os.makedirs(en_dir, exist_ok=True)
    return en_dir


def sanitize_filename(name, fallback="download"):
    if not name:
        return fallback
    clean = re.sub(r'[\\/*?:"<>|]', "_", name).strip()
    return clean[:120] if clean else fallback


def format_bytes(num_bytes):
    if not num_bytes or num_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    val = float(num_bytes)
    while val >= 1024.0 and i < len(units) - 1:
        val /= 1024.0
        i += 1
    return f"{val:.1f} {units[i]}"


def format_speed(bytes_per_sec):
    return f"{format_bytes(bytes_per_sec)}/s"


def format_eta(seconds):
    if seconds is None or seconds < 0 or seconds > 86400 * 7:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h} sa {m:02d} dk {s:02d} sn"
    return f"{m:02d} dk {s:02d} sn"


PART_SUFFIX = ".nspart"
META_SUFFIX = ".nspart.meta"
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


class DownloadError(Exception):
    pass


class _RateLimitError(DownloadError):
    def __init__(self, code, wait_s):
        super().__init__(f"HTTP {code}")
        self.wait_s = wait_s


def _parse_retry_after(val, default_s=5.0):
    if not val:
        return default_s
    s = str(val).strip()
    if s.isdigit():
        return max(1.0, min(60.0, float(s)))
    try:
        dt = email.utils.parsedate_to_datetime(s)
        delta = dt.timestamp() - time.time()
        return max(1.0, min(60.0, delta))
    except Exception:
        return default_s


def _hide_dir_windows(path):
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)
    except Exception:
        pass


def _nearest_existing_parent(path):
    cur = os.path.abspath(path)
    while cur and not os.path.exists(cur):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return cur


def _same_drive_or_device(path_a, path_b):
    if sys.platform == "win32":
        da = os.path.splitdrive(os.path.abspath(path_a))[0].lower()
        db = os.path.splitdrive(os.path.abspath(path_b))[0].lower()
        return bool(da and db and da == db)
    try:
        pa = _nearest_existing_parent(path_a)
        pb = _nearest_existing_parent(path_b)
        return os.stat(pa).st_dev == os.stat(pb).st_dev
    except OSError:
        return False


def get_temp_root(destination_dir=None, create=True):
    """
    İndirilenler klasörünü ara dosyalardan (.part, .ytdl, .nspart) temiz tutmak için
    aynı sürücüdeki uygulama geçici kökünü döndürür; farklı bir sürücüye kaydediliyorsa
    hedef klasörde gizli '.novastream_temp' alt klasörü kullanır.
    """
    dest = os.path.abspath(destination_dir or get_default_download_dir())
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        preferred = os.path.join(base, "NovaStream", "temp")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
        preferred = os.path.join(base, "novastream", "temp")

    if _same_drive_or_device(dest, preferred):
        if create:
            os.makedirs(preferred, exist_ok=True)
        return preferred

    fallback = os.path.join(dest, ".novastream_temp")
    if create:
        os.makedirs(fallback, exist_ok=True)
        _hide_dir_windows(fallback)
    return fallback


def temp_key_for(*parts):
    joined = "|".join(str(p or "") for p in parts)
    return hashlib.sha256(joined.encode("utf-8", errors="replace")).hexdigest()[:16]


def atomic_move(src, dst):
    try:
        os.replace(src, dst)
    except OSError:
        shutil.move(src, dst)


def cleanup_old_temp_entries(temp_root, max_age_hours=72):
    if not temp_root or not os.path.isdir(temp_root):
        return
    cutoff = time.time() - max_age_hours * 3600
    try:
        for name in os.listdir(temp_root):
            path = os.path.join(temp_root, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        os.remove(path)
            except OSError:
                pass
    except OSError:
        pass


def _numbered_name(path, n):
    if n == 0:
        return path
    base, ext = os.path.splitext(path)
    return f"{base} ({n}){ext}"


def _active_temp_targets(directory):
    targets = {}
    temp_root = get_temp_root(directory, create=False)
    if not os.path.isdir(temp_root):
        return targets
    try:
        names = os.listdir(temp_root)
    except OSError:
        return targets
    for name in names:
        if not (name.startswith("seg_") and name.endswith(META_SUFFIX)):
            continue
        meta_file = os.path.join(temp_root, name)
        part_file = meta_file[: -len(META_SUFFIX)] + PART_SUFFIX
        if not os.path.exists(part_file):
            continue
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            tp = data.get("target_path")
            if tp:
                targets[os.path.normcase(os.path.abspath(tp))] = data.get("source_url")
        except Exception:
            pass
    return targets


def choose_target_path(directory, filename, url=None):
    """
    Hedef dosya yolunu seçer:
    - Aynı URL için yarım kalmış bir indirme (.nspart.meta) varsa onu sürdürür.
    - Aksi halde mevcut hiçbir dosyanın üzerine yazmayan benzersiz bir ad üretir: "ad (1).ext".
    """
    first = os.path.join(directory, filename)
    active_targets = _active_temp_targets(directory)
    for n in range(0, 1000):
        cand = _numbered_name(first, n)
        meta = cand + META_SUFFIX
        if url and os.path.exists(meta) and os.path.exists(cand + PART_SUFFIX) and not os.path.exists(cand):
            try:
                with open(meta, "r", encoding="utf-8") as f:
                    if json.load(f).get("source_url") == url:
                        return cand
            except Exception:
                pass
        cand_key = os.path.normcase(os.path.abspath(cand))
        if cand_key in active_targets:
            if url and active_targets[cand_key] == url and not os.path.exists(cand):
                return cand
            continue
        if not os.path.exists(cand) and not os.path.exists(cand + PART_SUFFIX):
            return cand
    raise DownloadError("Uygun dosya adı bulunamadı")


class SegmentedDownloader:
    """
    HTTP Range istekleri ile dosyayı paralel parçalara bölerek indirir.

    Güvenlik kuralları:
    - Veri önce "<ad>.nspart" dosyasına yazılır; yalnızca indirme tamamlanınca asıl ada taşınır.
    - Var olan hiçbir dosyanın üzerine yazılmaz (benzersiz ad seçilir).
    - cancel() yalnızca yarım dosyayı siler; tamamlanmış dosyaya asla dokunmaz.
    - 4xx/5xx yanıtları ve tekrar eden bağlantı hataları on_error ile bildirilir.
    """

    def __init__(
        self,
        url,
        destination_dir=None,
        custom_filename=None,
        num_connections=16,
        headers=None,
        cookies=None,
        on_progress=None,
        on_completed=None,
        on_error=None,
        max_retries=6
    ):
        self.url = url
        self.source_url = url
        self.destination_dir = destination_dir or get_default_download_dir()
        self.custom_filename = custom_filename
        self.num_connections = max(1, min(32, int(num_connections or 1)))
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.max_retries = max_retries

        self.on_progress = on_progress
        self.on_completed = on_completed
        self.on_error = on_error

        self.total_size = 0          # 0 = bilinmiyor
        self.supports_range = False
        self.filename = None
        self.target_path = None      # tamamlandığında oluşacak asıl dosya
        self.part_path = None
        self.meta_path = None

        self.segments = []
        self.segments_lock = threading.Lock()

        self.is_paused = False
        self.is_cancelled = False
        self.is_running = False
        self.is_finished = False
        self._failed = False

        self._pause_event = threading.Event()
        self._pause_event.set()

        self.current_speed = 0.0
        self.eta_seconds = None
        self._rate_limit_until = 0.0
        self._effective_connections = self.num_connections

    # ------------------------------------------------------------------ yardımcılar
    def _req_headers(self):
        h = dict(self.headers)
        h.setdefault("User-Agent", DEFAULT_UA)
        return h

    def _fail(self, message):
        if self._failed or self.is_cancelled:
            return
        self._failed = True
        self.is_running = False
        self._save_meta()
        logging.error(f"İndirme hatası ({self.url}): {message}")
        if self.on_error:
            self.on_error(message)

    # ------------------------------------------------------------------ inceleme
    def inspect_url(self):
        """Boyut, dosya adı ve Range desteğini belirler. Hata durumunda DownloadError fırlatır."""
        headers = self._req_headers()
        head = None
        try:
            head = requests.head(self.url, headers=headers, cookies=self.cookies, allow_redirects=True, timeout=12)
        except requests.RequestException:
            head = None

        probe_headers = dict(headers)
        probe_headers["Range"] = "bytes=0-0"
        probe = None
        for attempt in range(4):
            probe = requests.get(self.url, headers=probe_headers, cookies=self.cookies, stream=True,
                                 allow_redirects=True, timeout=15)
            if probe.status_code in (429, 503) and attempt < 3:
                wait_s = min(5.0, _parse_retry_after(probe.headers.get("Retry-After"), 1.5 * (attempt + 1)))
                probe.close()
                self._effective_connections = max(1, self._effective_connections // 2)
                time.sleep(wait_s)
                continue
            break
        try:
            if probe.status_code >= 400:
                raise DownloadError(f"Sunucu hata döndürdü: HTTP {probe.status_code}")
            self.url = probe.url  # yönlendirme sonrası adres

            cr = probe.headers.get("Content-Range", "")
            if probe.status_code == 206 and "/" in cr:
                total_str = cr.split("/")[-1].strip()
                self.total_size = int(total_str) if total_str.isdigit() else 0
                self.supports_range = self.total_size > 0
            else:
                # Sunucu Range'i yok saydı: tek parça indir
                cl = probe.headers.get("Content-Length") or (head.headers.get("Content-Length") if head is not None and head.status_code < 400 else None)
                self.total_size = int(cl) if cl and cl.isdigit() else 0
                self.supports_range = False

            # Dosya adı
            if self.custom_filename:
                fname = self.custom_filename
            else:
                fname = None
                cd = probe.headers.get("Content-Disposition", "") or (head.headers.get("Content-Disposition", "") if head is not None else "")
                if cd and "filename" in cd:
                    match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", cd, re.IGNORECASE)
                    if match:
                        fname = urllib.parse.unquote(match.group(1))
                if not fname:
                    fname = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(self.url).path))
            self.filename = sanitize_filename(fname, fallback="download.bin")
        finally:
            probe.close()

        os.makedirs(self.destination_dir, exist_ok=True)
        self.target_path = choose_target_path(self.destination_dir, self.filename, self.source_url)
        self.filename = os.path.basename(self.target_path)
        temp_root = get_temp_root(self.destination_dir, create=True)
        stem = f"seg_{temp_key_for(os.path.abspath(self.destination_dir), self.source_url, self.filename)}"
        self.part_path = os.path.join(temp_root, stem + PART_SUFFIX)
        self.meta_path = os.path.join(temp_root, stem + META_SUFFIX)
        return True

    # ------------------------------------------------------------------ parçalar
    def _init_segments(self):
        if os.path.exists(self.meta_path) and os.path.exists(self.part_path):
            try:
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("source_url") == self.source_url and meta.get("total_size") == self.total_size and self.total_size > 0:
                    self.segments = meta.get("segments", [])
                    for s in self.segments:
                        s["running"] = False
                        s["errors"] = 0
                        s["retry_at"] = 0
                    logging.info(f"Yarım kalan indirme sürdürülüyor: {self.filename}")
                    return
            except Exception as e:
                logging.warning(f"Meta okunamadı, baştan başlanıyor: {e}")

        self.segments = []
        if self.supports_range and self.total_size > 1024 * 1024:
            count = self.num_connections
            part = self.total_size // count
            for i in range(count):
                start = i * part
                end = (start + part - 1) if i < count - 1 else self.total_size - 1
                self.segments.append(self._new_seg(i, start, end))
        else:
            end = self.total_size - 1 if self.total_size > 0 else -1  # -1: bilinmeyen boyut
            self.segments.append(self._new_seg(0, 0, end))

        with open(self.part_path, "wb") as f:
            if self.total_size > 0:
                f.truncate(self.total_size)
        self._save_meta()

    @staticmethod
    def _new_seg(seg_id, start, end):
        return {"id": seg_id, "start": start, "end": end, "downloaded": 0,
                "done": False, "running": False, "errors": 0, "retry_at": 0}

    @staticmethod
    def _seg_total(seg):
        return seg["end"] - seg["start"] + 1 if seg["end"] >= 0 else 0

    def _seg_complete(self, seg):
        if seg["done"]:
            return True
        return seg["end"] >= 0 and seg["downloaded"] >= self._seg_total(seg)

    def _save_meta(self):
        if not self.meta_path or self.is_cancelled or self.is_finished:
            return
        try:
            with self.segments_lock:
                meta = {
                    "source_url": self.source_url,
                    "url": self.url,
                    "total_size": self.total_size,
                    "filename": self.filename,
                    "target_path": os.path.abspath(self.target_path) if self.target_path else "",
                    "segments": [{k: s[k] for k in ("id", "start", "end", "downloaded", "done")} for s in self.segments],
                    "updated_at": time.time()
                }
            tmp = self.meta_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(meta, f)
            os.replace(tmp, self.meta_path)
        except Exception:
            pass

    # ------------------------------------------------------------------ kontrol
    def start(self):
        """İndirmeyi arka planda başlatır; ağ incelemesi de arka planda yapılır (arayüz donmaz)."""
        self.is_running = True
        self.is_paused = False
        self.is_cancelled = False
        self._failed = False
        self._pause_event.set()
        threading.Thread(target=self._bootstrap, daemon=True).start()
        return True

    def _bootstrap(self):
        try:
            if not self.part_path:
                self.inspect_url()
            self._init_segments()
        except DownloadError as e:
            self._fail(str(e))
            return
        except requests.RequestException as e:
            self._fail(f"Bağlantı hatası: {e}")
            return
        except OSError as e:
            self._fail(f"Disk hatası: {e}")
            return
        self._run_download()

    def pause(self):
        self.is_paused = True
        self._pause_event.clear()
        self._save_meta()

    def resume(self):
        if self.is_paused:
            self.is_paused = False
            self._pause_event.set()

    def cancel(self, delete_partial=True):
        """İndirmeyi durdurur. Yalnızca yarım dosyayı (.nspart) siler, tamamlanmış dosyaya dokunmaz."""
        self.is_cancelled = True
        self.is_running = False
        self._pause_event.set()
        if self.is_finished or not delete_partial:
            return
        time.sleep(0.3)
        for p in (self.part_path, self.meta_path):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    # ------------------------------------------------------------------ indirme
    def _worker(self, seg):
        headers = self._req_headers()
        with self.segments_lock:
            offset = seg["start"] + seg["downloaded"]
            end = seg["end"]
        if end >= 0 and offset > end:
            seg["done"] = True
            return
        ranged = self.supports_range and end >= 0
        if ranged:
            headers["Range"] = f"bytes={offset}-{end}"
        elif seg["downloaded"] > 0:
            # Range yok: baştan indirmek zorundayız
            with self.segments_lock:
                seg["downloaded"] = 0
            offset = seg["start"]

        try:
            wait = self._rate_limit_until - time.time()
            if wait > 0:
                time.sleep(min(wait, 10.0))
            if self.is_cancelled or self._failed:
                return
            with requests.get(self.url, headers=headers, cookies=self.cookies, stream=True, timeout=20) as res:
                if res.status_code in (429, 503):
                    wait_s = _parse_retry_after(
                        res.headers.get("Retry-After"),
                        min(2 ** (seg["errors"] + 1), 30)
                    )
                    raise _RateLimitError(res.status_code, wait_s)
                if res.status_code >= 400:
                    raise DownloadError(f"HTTP {res.status_code}")
                if ranged and res.status_code != 206:
                    raise DownloadError("Sunucu parçalı isteği yok saydı (Range desteklenmiyor)")
                with open(self.part_path, "r+b") as fp:
                    fp.seek(offset)
                    for chunk in res.iter_content(chunk_size=CHUNK_BUFFER_SIZE):
                        if self.is_cancelled or self._failed:
                            return
                        self._pause_event.wait()
                        if not chunk:
                            continue
                        with self.segments_lock:
                            cur_end = seg["end"]   # bölünmüş olabilir: güncel sınırı oku
                            if cur_end >= 0:
                                remaining = cur_end - (seg["start"] + seg["downloaded"]) + 1
                                if remaining <= 0:
                                    break
                                if len(chunk) > remaining:
                                    chunk = chunk[:remaining]
                        fp.write(chunk)
                        with self.segments_lock:
                            seg["downloaded"] += len(chunk)
            with self.segments_lock:
                if seg["end"] < 0:
                    # Boyutu bilinmeyen tek parça: akış bitti = tamamlandı
                    seg["done"] = True
                    seg["end"] = seg["start"] + seg["downloaded"] - 1
                    self.total_size = seg["downloaded"]
                elif seg["downloaded"] >= self._seg_total(seg):
                    seg["done"] = True
                else:
                    raise DownloadError("Bağlantı erken kapandı")
                seg["errors"] = 0
        except (_RateLimitError, DownloadError, requests.RequestException, OSError) as e:
            if isinstance(e, _RateLimitError):
                with self.segments_lock:
                    seg["errors"] += 1
                    self._rate_limit_until = max(self._rate_limit_until, time.time() + e.wait_s)
                    self._effective_connections = max(1, self._effective_connections // 2)
                    seg["retry_at"] = self._rate_limit_until
                    errors = seg["errors"]
                limit = max(self.max_retries, 8)
                logging.warning(
                    f"Parça #{seg['id']} hız sınırı ({e}): {e.wait_s:.1f}s bekleniyor, "
                    f"bağlantı={self._effective_connections} ({errors}/{limit})"
                )
                if errors > limit:
                    self._fail(f"Parça #{seg['id']} indirilemedi: {e}")
            else:
                with self.segments_lock:
                    seg["errors"] += 1
                    seg["retry_at"] = time.time() + min(2 ** seg["errors"], 30)
                    errors = seg["errors"]
                logging.warning(f"Parça #{seg['id']} hatası ({errors}/{self.max_retries}): {e}")
                fatal = isinstance(e, DownloadError) and str(e).startswith("HTTP 4") and not str(e).startswith("HTTP 429")
                if errors > self.max_retries or (fatal and errors >= 2):
                    self._fail(f"Parça #{seg['id']} indirilemedi: {e}")

    def _worker_wrapper(self, seg):
        try:
            self._worker(seg)
        finally:
            seg["running"] = False

    def _split_for_idle_workers(self):
        """Boşta bağlantı varsa, en çok işi kalan parçayı ikiye bölüp yarısını boşta olana verir."""
        if not self.supports_range:
            return
        running = sum(1 for s in self.segments if s["running"])
        idle = self._effective_connections - running - sum(1 for s in self.segments if not s["running"] and not self._seg_complete(s))
        while idle > 0 and len(self.segments) < 64:
            biggest, best = None, 0
            for s in self.segments:
                if s["running"] and not self._seg_complete(s):
                    rem = s["end"] - (s["start"] + s["downloaded"]) + 1
                    if rem > best:
                        best, biggest = rem, s
            if not biggest or best < 4 * 1024 * 1024:
                return
            cur = biggest["start"] + biggest["downloaded"]
            mid = cur + best // 2
            new_seg = self._new_seg(len(self.segments), mid, biggest["end"])
            biggest["end"] = mid - 1
            self.segments.append(new_seg)
            idle -= 1

    def _run_download(self):
        threading.Thread(target=self._monitor_progress, daemon=True).start()
        with ThreadPoolExecutor(max_workers=self.num_connections) as executor:
            while self.is_running and not self.is_cancelled and not self._failed:
                self._pause_event.wait()
                now = time.time()
                with self.segments_lock:
                    if all(self._seg_complete(s) for s in self.segments):
                        break
                    if now < self._rate_limit_until:
                        to_start = []
                    else:
                        self._split_for_idle_workers()
                        running = sum(1 for s in self.segments if s["running"])
                        slots = max(0, self._effective_connections - running)
                        candidates = [s for s in self.segments
                                      if not s["running"] and not self._seg_complete(s) and s["retry_at"] <= now]
                        to_start = candidates[:slots]
                        for s in to_start:
                            s["running"] = True
                for s in to_start:
                    executor.submit(self._worker_wrapper, s)
                time.sleep(0.3)

        if self.is_cancelled or self._failed:
            return
        self.is_running = False
        try:
            final = self.target_path
            if os.path.exists(final):
                final = choose_target_path(self.destination_dir, os.path.basename(self.target_path))
            atomic_move(self.part_path, final)
            self.target_path = final
            self.filename = os.path.basename(final)
            if os.path.exists(self.meta_path):
                os.remove(self.meta_path)
        except OSError as e:
            self._failed = False
            self._fail(f"Dosya tamamlanamadı: {e}")
            return
        self.is_finished = True
        logging.info(f"İndirme tamamlandı: {self.target_path}")
        if self.on_completed:
            self.on_completed(self.target_path)

    def _monitor_progress(self):
        last_time = time.time()
        last_bytes = None
        save_counter = 0
        while self.is_running and not self.is_cancelled and not self._failed:
            time.sleep(0.4)
            if not self.is_running or self.is_cancelled or self._failed:
                break
            now = time.time()
            with self.segments_lock:
                current = sum(s["downloaded"] for s in self.segments)
                chunk_progress = [
                    {"id": s["id"],
                     "percent": (s["downloaded"] / self._seg_total(s) * 100) if self._seg_total(s) > 0 else 0,
                     "downloaded": s["downloaded"], "total": self._seg_total(s)}
                    for s in self.segments
                ]
            if last_bytes is None:
                last_bytes = current
            dt = now - last_time
            if dt >= 0.4:
                self.current_speed = 0.0 if self.is_paused else max(0.0, (current - last_bytes) / dt)
                last_bytes, last_time = current, now
                if self.total_size > 0 and self.current_speed > 0:
                    self.eta_seconds = max(0, self.total_size - current) / self.current_speed
                else:
                    self.eta_seconds = None
            pct = min(100.0, current / self.total_size * 100) if self.total_size > 0 else 0.0
            if self.on_progress:
                self.on_progress({
                    "url": self.url,
                    "filename": self.filename,
                    "target_path": self.target_path,
                    "downloaded_bytes": current,
                    "total_bytes": self.total_size,
                    "percent": pct,
                    "speed_bps": self.current_speed,
                    "speed_formatted": format_speed(self.current_speed),
                    "eta_seconds": self.eta_seconds,
                    "eta_formatted": format_eta(self.eta_seconds),
                    "is_paused": self.is_paused,
                    "segments": chunk_progress
                })
            save_counter += 1
            if save_counter >= 5:
                self._save_meta()
                save_counter = 0

"""
NovaStream Stream & Video Downloader (yt-dlp & FFmpeg Wrapper)
YouTube, HLS (.m3u8), DASH (.mpd) ve sosyal medya videolarını yt-dlp ile indirir.

- Kalite seçimi (en iyi / 2160p / 1080p / 720p / 480p / yalnızca ses)
- Duraklatma = süreci durdurma; devam ettirince yt-dlp .part dosyasından sürdürür
- Aynı adlı mevcut bir dosyanın üzerine yazmaz
- Tarayıcı çerezi okunamazsa çerezsiz bir kez daha dener
"""

import glob
import importlib.util
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse

from core.engine import format_bytes, format_eta, format_speed, get_default_download_dir

MEDIA_EXTS = ("mp4", "mkv", "webm", "mp3", "m4a", "opus", "ogg", "mov")
PROGRESS_PREFIX = "NSPROG"
FILE_PREFIX = "NSFILE:"


def find_binary(name):
    """Sistem PATH, uygulamanın Python klasörü veya bilinen konumlardan çalıştırılabilir dosyayı bulur."""
    bin_path = shutil.which(name)
    if bin_path:
        return bin_path
    venv_dir = os.path.dirname(sys.executable)
    for cand in (name, name + ".exe"):
        for d in (venv_dir, os.path.join(venv_dir, "Scripts")):
            cand_path = os.path.join(d, cand)
            if os.path.exists(cand_path):
                return cand_path
    for p in (f"/usr/bin/{name}", f"/usr/local/bin/{name}", os.path.expanduser(f"~/.local/bin/{name}")):
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


def ytdlp_command():
    """yt-dlp'yi mümkünse aynı Python ile modül olarak çalıştırır (Windows .exe başlatıcısı askıda kalabiliyor)."""
    if not getattr(sys, "frozen", False) and importlib.util.find_spec("yt_dlp"):
        py = sys.executable
        if os.path.basename(py).lower() == "pythonw.exe":
            cand = os.path.join(os.path.dirname(py), "python.exe")
            if os.path.exists(cand):
                py = cand
        return [py, "-m", "yt_dlp"]
    return [find_binary("yt-dlp") or "yt-dlp"]


def format_selector(quality, has_ffmpeg):
    """Kalite seçimine göre yt-dlp -f ifadesi ve ek argümanlar."""
    q = (quality or "best").lower()
    if q == "audio":
        if has_ffmpeg:
            return "ba/b", ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
        return "ba[ext=m4a]/ba/b", []
    if q.isdigit():
        h = int(q)
        if has_ffmpeg:
            return f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b", []
        return f"b[height<={h}]/b", []
    return ("bv*+ba/b" if has_ffmpeg else "b"), []


def safe_title(title):
    clean = re.sub(r'[\\/*?:"<>|\r\n\t]', "_", title or "video").strip().strip(".")
    for ext in MEDIA_EXTS:
        if clean.lower().endswith("." + ext):
            clean = clean[: -(len(ext) + 1)]
            break
    return clean[:150] or "video"


def choose_output_base(directory, title):
    """
    Var olan bir dosyanın üzerine yazmayan bir dosya adı tabanı seçer: "ad", "ad (1)", ...
    Seçilen ad için yarım kalmış bir yt-dlp indirmesi (.part) varsa yt-dlp onu kendiliğinden sürdürür.
    """
    base = safe_title(title)
    for n in range(0, 1000):
        cand = base if n == 0 else f"{base} ({n})"
        pattern = os.path.join(glob.escape(directory), glob.escape(cand))
        if not any(glob.glob(f"{pattern}.{ext}") for ext in MEDIA_EXTS):
            return cand
    return base


class StreamDownloader:
    """yt-dlp ve FFmpeg ile video/akış indirici."""

    def __init__(
        self,
        url,
        destination_dir=None,
        custom_title=None,
        referer=None,
        is_youtube=False,
        browser_cookies=None,
        cookie_file=None,
        quality="best",
        on_progress=None,
        on_completed=None,
        on_error=None
    ):
        self.url = url
        self.destination_dir = destination_dir or get_default_download_dir()
        self.custom_title = custom_title  # None/boş = videonun kendi başlığı
        self.referer = referer
        self.is_youtube = is_youtube
        self.browser_cookies = browser_cookies
        self.cookie_file = cookie_file  # eklentinin gönderdiği tarayıcı çerezleri (Netscape biçimi)
        self.quality = quality or "best"

        self.on_progress = on_progress
        self.on_completed = on_completed
        self.on_error = on_error

        self.process = None
        self.is_cancelled = False
        # YouTube'da HLS manifestini atla: indirilen DASH biçimleri için gereksiz ve
        # her indirmede ayrı bir sunucuya bağlantı (yavaş ağlarda birkaç saniye) demek.
        self.skip_hls = bool(is_youtube)
        self.target_path = None
        self.output_base = None
        self.created_files = set()  # yt-dlp'nin bu oturumda yazmaya başladığı dosyalar

        self.ffmpeg_bin = find_binary("ffmpeg")

    # ------------------------------------------------------------------ kontrol
    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def cancel(self, delete_partial=True):
        """Süreci (ve alt süreçlerini) durdurur. delete_partial=True ise yarım .part dosyalarını siler."""
        self.is_cancelled = True
        proc = self.process
        if proc and proc.poll() is None:
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        if delete_partial:
            time.sleep(0.3)
            leftovers = set()
            for f in self.created_files:
                leftovers.update(glob.glob(glob.escape(f) + "*"))
            if self.output_base:
                pattern = os.path.join(glob.escape(self.destination_dir), glob.escape(self.output_base))
                # choose_output_base bitmiş dosyası olmayan bir ad seçtiği için bu adla başlayan
                # her şey bu indirmenin yarım/ara dosyasıdır (.part, .ytdl, .f396.mp4, .temp.mp4 ...)
                leftovers.update(glob.glob(pattern + ".*"))
            for p in leftovers:
                try:
                    os.remove(p)
                except Exception:
                    pass

    # ------------------------------------------------------------------ çalıştırma
    def _build_cmd(self, use_cookies):
        fmt, extra = format_selector(self.quality, bool(self.ffmpeg_bin))
        if self.output_base:
            out_template = os.path.join(self.destination_dir, f"{self.output_base}.%(ext)s")
        else:
            # Başlık verilmediyse videonun kendi başlığı + kimliği (benzersiz)
            out_template = os.path.join(self.destination_dir, "%(title).150B [%(id)s].%(ext)s")
        cmd = ytdlp_command() + [
            "-f", fmt,
            "--no-playlist",
            "--newline",
            "--progress",  # --print sessiz moda geçirir; ilerlemeyi yine de yazdır
            "--no-overwrites",
            "--continue",
            "-N", "8",
            "--http-chunk-size", "10M",
            "--retries", "10",
            "--fragment-retries", "10",
            "-o", out_template,
            "--progress-template",
            f"download:{PROGRESS_PREFIX} %(progress.downloaded_bytes)s %(progress.total_bytes)s "
            f"%(progress.total_bytes_estimate)s %(progress.speed)s %(progress.eta)s",
            "--no-simulate",
            "--print", f"after_move:{FILE_PREFIX}%(filepath)s",
        ] + extra
        if self.quality != "audio":
            cmd += ["--merge-output-format", "mp4"]
        if self.ffmpeg_bin:
            cmd += ["--ffmpeg-location", self.ffmpeg_bin]
            if self.quality != "audio":
                cmd += ["--remux-video", "mp4"]
        if self.referer:
            cmd += ["--referer", self.referer]
            try:
                parsed = urllib.parse.urlparse(self.referer)
                if parsed.scheme and parsed.netloc:
                    cmd += ["--add-header", f"Origin:{parsed.scheme}://{parsed.netloc}"]
            except Exception:
                pass
        if self.skip_hls:
            cmd += ["--extractor-args", "youtube:skip=hls"]
        if use_cookies:
            if self.cookie_file:
                cmd += ["--cookies", self.cookie_file]
            elif self.browser_cookies:
                cmd += ["--cookies-from-browser", self.browser_cookies]
        cmd.append(self.url)
        return cmd

    def _emit(self, **kw):
        if self.on_progress:
            data = {"url": self.url, "filename": os.path.basename(self.target_path) if self.target_path else (self.custom_title or ""),
                    "target_path": self.target_path, "is_stream": True}
            data.update(kw)
            self.on_progress(data)

    def _execute(self, use_cookies):
        """yt-dlp'yi bir kez çalıştırır. (dönüş kodu, hata satırları, son dosya) döndürür."""
        cmd = self._build_cmd(use_cookies)
        popen_kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, bufsize=1, encoding="utf-8", errors="replace",
                        env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"))
        if sys.platform == "win32":
            popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            popen_kw["start_new_session"] = True
        self.process = subprocess.Popen(cmd, **popen_kw)

        error_lines, tail = [], []
        final_path = None
        done_bytes = 0          # biten dosyaların (görüntü/ses) toplam boyutu
        last_dl = 0
        for raw in self.process.stdout:
            if self.is_cancelled:
                break
            line = raw.strip()
            if not line:
                continue
            tail = (tail + [line])[-6:]
            if line.startswith(FILE_PREFIX):
                final_path = line[len(FILE_PREFIX):].strip()
                continue
            if line.startswith("[download] Destination:"):
                self.created_files.add(line.split(":", 1)[1].strip())
            if line.startswith(PROGRESS_PREFIX):
                parts = line.split()[1:]
                vals = [None if p in ("NA", "None") else p for p in parts] + [None] * 5
                try:
                    dl = float(vals[0] or 0)
                    total = float(vals[1] or vals[2] or 0)
                    speed = float(vals[3]) if vals[3] else 0.0
                    eta = float(vals[4]) if vals[4] else None
                except ValueError:
                    continue
                if dl < last_dl:          # yeni bir parça (ör. görüntüden sese geçiş)
                    done_bytes += last_dl
                last_dl = dl
                overall_dl = done_bytes + dl
                overall_total = done_bytes + total if total else 0
                pct = min(99.0, overall_dl / overall_total * 100) if overall_total else 0.0
                self._emit(percent=pct, speed_bps=speed, speed_formatted=format_speed(speed),
                           eta_formatted=format_eta(eta), downloaded_bytes=int(overall_dl),
                           total_bytes=int(overall_total), total_formatted=format_bytes(overall_total))
                continue
            low = line.lower()
            if "error:" in low:
                error_lines.append(line)
            elif "[merger]" in low or "merging formats" in low or "[extractaudio]" in low:
                self._emit(percent=99.0, speed_formatted="Birleştiriliyor", eta_formatted="Son işlem", speed_bps=0.0)
            elif line.startswith("[youtube]") or line.startswith("[info]") or "Downloading webpage" in line:
                self._emit(percent=0.0, speed_formatted="Akış çözümleniyor...", eta_formatted="", speed_bps=0.0)
        self.process.wait()
        return self.process.returncode, (error_lines or tail), final_path

    def _run(self):
        try:
            os.makedirs(self.destination_dir, exist_ok=True)
            self.output_base = choose_output_base(self.destination_dir, self.custom_title) if self.custom_title else None
            self._emit(percent=0.0, speed_formatted="Bağlanıyor...", eta_formatted="", speed_bps=0.0)

            use_cookies = bool(self.cookie_file) or bool(self.is_youtube and self.browser_cookies)
            code, errors, final_path = self._execute(use_cookies)
            if (code != 0 and use_cookies and not self.cookie_file and not self.is_cancelled
                    and any("cookie" in e.lower() for e in errors)):
                logging.warning("Tarayıcı çerezi okunamadı; çerezsiz yeniden deneniyor.")
                code, errors, final_path = self._execute(False)

            if (code != 0 and self.skip_hls and not self.is_cancelled
                    and any(k in e.lower() for e in errors for k in ("format", "live", "m3u8", "hls"))):
                # Canlı yayın vb. yalnız HLS ile inebilir: manifestle yeniden dene
                logging.info("HLS atlanarak indirilemedi; HLS ile yeniden deneniyor.")
                self.skip_hls = False
                code, errors, final_path = self._execute(use_cookies)

            if self.is_cancelled:
                return
            if code == 0:
                if (not final_path or not os.path.exists(final_path)) and self.output_base:
                    pattern = os.path.join(glob.escape(self.destination_dir), glob.escape(self.output_base))
                    found = [p for ext in MEDIA_EXTS for p in glob.glob(f"{pattern}.{ext}")]
                    final_path = found[0] if found else final_path
                self.target_path = final_path
                if self.on_completed:
                    self.on_completed(final_path)
                return

            if (".m3u8" in self.url.lower() or ".mpd" in self.url.lower()) and not self.is_youtube and self.ffmpeg_bin:
                logging.info("yt-dlp akışı indiremedi, FFmpeg ile doğrudan deneniyor...")
                ok, _ = self._download_via_ffmpeg()
                if ok:
                    return
            if self.on_error:
                self.on_error("\n".join(errors[-3:]) or f"yt-dlp hata kodu: {code}")
        except Exception as e:
            logging.exception("StreamDownloader hatası")
            if self.on_error:
                self.on_error(str(e))

    def _download_via_ffmpeg(self):
        """yt-dlp'nin çözemediği HLS/DASH akışlarını doğrudan FFmpeg ile indirir."""
        target_path = os.path.join(self.destination_dir, f"{self.output_base or safe_title(None)}.mp4")
        headers_str = "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36\r\n"
        if self.referer:
            headers_str += f"Referer: {self.referer}\r\n"
        cmd = [self.ffmpeg_bin, "-y", "-headers", headers_str, "-i", self.url, "-c", "copy",
               "-bsf:a", "aac_adtstoasc", target_path]
        try:
            self.process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for raw in self.process.stdout:
                if self.is_cancelled:
                    break
                line = raw.strip()
                if "time=" in line and "speed=" in line:
                    sp = re.search(r"speed=\s*([\d\.]+x)", line)
                    tm = re.search(r"time=(\d+:\d+:\d+)", line)
                    self._emit(percent=50.0, speed_formatted=f"FFmpeg: {sp.group(1) if sp else ''}",
                               eta_formatted=f"İşlenen: {tm.group(1) if tm else ''}", speed_bps=0.0)
            self.process.wait()
            if self.is_cancelled:
                return False, "İptal edildi"
            if self.process.returncode == 0 and os.path.exists(target_path):
                self.target_path = target_path
                if self.on_completed:
                    self.on_completed(target_path)
                return True, ""
            return False, f"FFmpeg çıkış kodu: {self.process.returncode}"
        except Exception as e:
            return False, str(e)

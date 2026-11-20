#!/usr/bin/python3
"""
NovaStream Native Messaging Host
1. Chrome'un kendi ağ yığınından (DoH / VPN / Cookies) indirilen akış parçalarını
   sırayla diske yazar ve FFmpeg ile tek parça MP4'e dönüştürür (sıfır RAM yükü).
2. YouTube videolarını Chrome oturum çerezleriyle (--cookies-from-browser chrome)
   orijinal kalitede indirir ve canlı ilerlemeyi eklentiye aktarır.
"""

import base64
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time

if sys.platform == "win32":
    try:
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    except Exception:
        pass
    try:
        import winreg
        _parts = [os.path.dirname(sys.executable)]
        for _root, _key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(_root, _key) as _k:
                    _parts.append(os.path.expandvars(winreg.QueryValueEx(_k, "Path")[0]))
            except OSError:
                pass
        os.environ["PATH"] = os.pathsep.join(_parts + [os.environ.get("PATH", "")])
    except Exception:
        pass
    user_prof = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    DOWNLOAD_DIR = os.path.join(user_prof, "Downloads")
else:
    DOWNLOAD_DIR = os.path.expanduser("~/İndirilenler")
    if not os.path.exists(DOWNLOAD_DIR):
        DOWNLOAD_DIR = os.path.expanduser("~/Downloads")

_py_dir = os.path.dirname(sys.executable)
os.environ["PATH"] = os.pathsep.join([_py_dir, os.path.join(_py_dir, "Scripts"), os.path.join(_py_dir, "bin"),
                                      os.environ.get("PATH", "")])

LOG_PATH = os.path.join(tempfile.gettempdir(), "novastream_native.log")
TMP_PREFIX = ".novastream_tmp_"
FILE_PREFIX = "NSFILE:"
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

DL_PATTERN = re.compile(
    r"\[download\]\s+(\d+(?:\.\d+)?)%\s+of\s+~?\s*([\d\.]+\w+)(?:\s+at\s+([\w\.\/]+))?(?:\s+ETA\s+([\w:]+))?"
)

write_lock = threading.Lock()
open_files = {}  # job_id -> {"temp_path": str, "final_path": str, "fp": file}


def get_unique_filepath(directory, filename):
    base, ext = os.path.splitext(filename)
    if not ext:
        ext = ".mp4"
    candidate = os.path.join(directory, f"{base}{ext}")
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}_{counter}{ext}")
        counter += 1
    return candidate


def send_notification(title, message):
    if sys.platform == "win32":
        return
    try:
        subprocess.run(["notify-send", title, message, "-i", "video-x-generic"], check=False, stdin=subprocess.DEVNULL)
    except Exception:
        pass


def send_message(message_content):
    try:
        encoded_content = json.dumps(message_content).encode("utf-8")
        encoded_length = struct.pack("@I", len(encoded_content))
        with write_lock:
            sys.stdout.buffer.write(encoded_length)
            sys.stdout.buffer.write(encoded_content)
            sys.stdout.buffer.flush()
    except Exception as e:
        logging.error(f"send_message error: {e}")


def read_message():
    try:
        raw_length = sys.stdin.buffer.read(4)
        if len(raw_length) < 4:
            return None
        message_length = struct.unpack("@I", raw_length)[0]
        data = bytearray()
        while len(data) < message_length:
            chunk = sys.stdin.buffer.read(min(message_length - len(data), 65536))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) < message_length:
            logging.error(f"Eksik mesaj alındı: beklenen {message_length}, okunan {len(data)}")
            return None
        message = data.decode("utf-8")
        return json.loads(message)
    except Exception as e:
        logging.error(f"read_message error: {e}")
        return None


def cleanup_stale_temp_files(max_age_hours=6):
    """Önceki oturumlardan kalan yarım geçici dosyaları siler."""
    try:
        now = time.time()
        for name in os.listdir(DOWNLOAD_DIR):
            if name.startswith(TMP_PREFIX):
                path = os.path.join(DOWNLOAD_DIR, name)
                if now - os.path.getmtime(path) > max_age_hours * 3600:
                    os.remove(path)
                    logging.info(f"Eski geçici dosya silindi: {name}")
    except Exception as e:
        logging.warning(f"Geçici dosya temizliği: {e}")


def abort_open_files():
    """Tarayıcı bağlantısı koptuğunda yarım kalan dosyaları kapatıp siler."""
    for job_id in list(open_files.keys()):
        handle_file_abort({"id": job_id})


def handle_file_open(msg):
    job_id = msg.get("id")
    raw_title = msg.get("title") or msg.get("filename") or "video.mp4"
    safe_name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", raw_title).strip().strip(".")
    if not safe_name:
        safe_name = "video"
    base, ext = os.path.splitext(safe_name)
    if not ext:
        ext = ".mp4"
    final_path = get_unique_filepath(DOWNLOAD_DIR, f"{base}{ext}")
    temp_ext = ".mp4" if msg.get("isFmp4") else (".ts" if msg.get("isTs") else ext)
    temp_path = os.path.join(DOWNLOAD_DIR, f"{TMP_PREFIX}{job_id}{temp_ext}")

    fp = open(temp_path, "wb")
    open_files[job_id] = {
        "temp_path": temp_path,
        "final_path": final_path,
        "fp": fp,
        "title": os.path.basename(final_path),
    }
    logging.info(f"FILE_OPEN {job_id}: {temp_path} -> {final_path}")
    send_message({"type": "FILE_OPENED", "id": job_id})


def handle_file_chunk(msg):
    job_id = msg.get("id")
    info = open_files.get(job_id)
    if not info:
        return
    data_b64 = msg.get("data", "")
    if data_b64:
        info["fp"].write(base64.b64decode(data_b64))


def handle_file_abort(msg):
    job_id = msg.get("id")
    info = open_files.pop(job_id, None)
    if info:
        try:
            info["fp"].close()
        except Exception:
            pass
        if os.path.exists(info["temp_path"]):
            os.remove(info["temp_path"])


def finalize_file_thread(job_id, info):
    temp_path = info["temp_path"]
    final_path = info["final_path"]
    title = info["title"]

    try:
        info["fp"].close()
        send_message({
            "type": "PROGRESS",
            "id": job_id,
            "percent": 99,
            "speedMb": "MP4 Optimize Ediliyor...",
            "mbTotal": "",
            "eta": "Son işlem"
        })

        # FFmpeg ile kayıpsız remux (-c copy) -> VLC ve tüm oynatıcılar için kusursuz MP4
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            for p in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "C:\\ffmpeg\\bin\\ffmpeg.exe"]:
                if os.path.exists(p):
                    ffmpeg_bin = p
                    break
        if not ffmpeg_bin:
            ffmpeg_bin = "ffmpeg"

        ffmpeg_cmd = [
            ffmpeg_bin,
            "-y",
            "-i", temp_path,
            "-c", "copy"
        ]
        if final_path.lower().endswith(".mp4"):
            ffmpeg_cmd.extend(["-movflags", "+faststart"])
        ffmpeg_cmd.append(final_path)
        res = subprocess.run(ffmpeg_cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) if (shutil.which(ffmpeg_bin) or os.path.exists(ffmpeg_bin)) else subprocess.CompletedProcess(ffmpeg_cmd, 1, "", "ffmpeg bulunamadi")

        if res.returncode == 0 and os.path.exists(final_path) and os.path.getsize(final_path) > 0:
            os.remove(temp_path)
            logging.info(f"Remux success: {final_path}")
        else:
            logging.warning(f"Remux fallback ({res.returncode}): {res.stderr[-300:]}")
            # Fallback: doğrudan dosyayı taşı
            shutil.move(temp_path, final_path)

        send_message({
            "type": "COMPLETE",
            "id": job_id,
            "success": True,
            "filename": title
        })
        send_notification("NovaStream", f"Video İndirilenler klasörüne kaydedildi:\n{title}")
    except Exception as e:
        logging.error(f"finalize_file_thread error: {e}")
        send_message({
            "type": "COMPLETE",
            "id": job_id,
            "success": False,
            "error": str(e)
        })


def handle_file_finish(msg):
    job_id = msg.get("id")
    info = open_files.pop(job_id, None)
    if not info:
        return
    threading.Thread(target=finalize_file_thread, args=(job_id, info), daemon=True).start()


def run_ytdlp(url, title, job_id, referer=None, is_youtube=False, cookies=None):
    send_notification("NovaStream", f"İndirme başladı:\n{title}")
    logging.info(f"Starting yt-dlp job={job_id} is_youtube={is_youtube} url={url}")

    send_message({
        "type": "PROGRESS",
        "id": job_id,
        "percent": 2,
        "speedMb": "Bağlantı Kuruluyor...",
        "mbTotal": "",
        "eta": ""
    })

    ytdlp_bin = shutil.which("yt-dlp") or shutil.which("yt-dlp", path=os.path.dirname(sys.executable))
    if not ytdlp_bin:
        for p in ["/usr/bin/yt-dlp", "/usr/local/bin/yt-dlp", "C:\\yt-dlp\\yt-dlp.exe"]:
            if os.path.exists(p):
                ytdlp_bin = p
                break
    if not ytdlp_bin:
        ytdlp_bin = "yt-dlp"

    # Windows'ta yt-dlp.exe başlatıcısı native host altında asılı kalabiliyor;
    # mümkünse aynı Python ile modül olarak çalıştır.
    import importlib.util
    if importlib.util.find_spec("yt_dlp"):
        ytdlp_cmd = [sys.executable, "-m", "yt_dlp"]
    else:
        ytdlp_cmd = [ytdlp_bin]

    if title:
        base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title).strip().strip(".")
        base = re.sub(r"\.(mp4|mkv|webm|mp3|m4a)$", "", base, flags=re.IGNORECASE) or "video"
        out_template = os.path.join(DOWNLOAD_DIR, base + ".%(ext)s")
    else:
        out_template = os.path.join(DOWNLOAD_DIR, "%(title).150B [%(id)s].%(ext)s")

    # Eklentinin gönderdiği tarayıcı çerezleri (üyelere özel / giriş gerektiren videolar)
    cookie_file = None
    if isinstance(cookies, str) and cookies.strip() and len(cookies) <= 512 * 1024:
        try:
            import tempfile
            fd, cookie_file = tempfile.mkstemp(prefix="novastream_cookies_", suffix=".txt")
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                text = cookies.replace("\r\n", "\n")
                if not text.startswith("# Netscape HTTP Cookie File"):
                    f.write("# Netscape HTTP Cookie File\n")
                f.write(text if text.endswith("\n") else text + "\n")
        except Exception:
            logging.exception("Çerez dosyası yazılamadı")
            cookie_file = None

    def build_cmd(use_cookies):
        cmd = ytdlp_cmd + [
            "-f", "bv*+ba/b" if shutil.which("ffmpeg") else "b",
            "--merge-output-format", "mp4",
            "--no-playlist",
            "--newline",
            "--progress",
            "--no-overwrites",
            "-N", "8",
            "--http-chunk-size", "10M",
            "--no-simulate",
            "--print", "after_move:" + FILE_PREFIX + "%(filepath)s",
            "-o", out_template
        ]
        if referer:
            cmd.extend(["--referer", referer])
        if cookie_file:
            cmd.extend(["--cookies", cookie_file])
        elif use_cookies:
            cmd.extend(["--cookies-from-browser", "chrome"])
        cmd.append(url)
        return cmd

    def execute(use_cookies):
        last_error = ""
        final_path = None
        process = subprocess.Popen(
            build_cmd(use_cookies),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1, encoding="utf-8", errors="replace",
            env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(FILE_PREFIX):
                final_path = line[len(FILE_PREFIX):].strip()
                continue
            if "ERROR:" in line:
                last_error = line
                logging.error(f"yt-dlp error line: {line}")
            match = DL_PATTERN.search(line)
            if match:
                pct_str, size_str, speed_str, eta_str = match.groups()
                send_message({
                    "type": "PROGRESS", "id": job_id, "percent": int(float(pct_str)),
                    "speedMb": speed_str or "Aktarılıyor", "mbTotal": size_str,
                    "eta": f"ETA {eta_str}" if eta_str else ""
                })
            elif "[youtube]" in line or "Downloading webpage" in line or "[info]" in line:
                send_message({"type": "PROGRESS", "id": job_id, "percent": 5,
                              "speedMb": "Video Akışı Çözümleniyor...", "mbTotal": "", "eta": ""})
            elif "[Merger]" in line or "Merging formats" in line:
                send_message({"type": "PROGRESS", "id": job_id, "percent": 99,
                              "speedMb": "Ses + Video Birleştiriliyor", "mbTotal": "", "eta": "Son işlem"})
        process.wait()
        return process.returncode, last_error, final_path

    try:
        use_cookies = bool(is_youtube and sys.platform != "win32")
        code, last_error_line, final_path = execute(use_cookies)
        if code != 0 and use_cookies and not cookie_file and "cookie" in last_error_line.lower():
            logging.warning("Chrome çerezi okunamadı; çerezsiz yeniden deneniyor.")
            code, last_error_line, final_path = execute(False)

        if code == 0:
            filename = os.path.basename(final_path) if final_path else (f"{title}.mp4" if title else "video.mp4")
            send_message({"type": "COMPLETE", "id": job_id, "success": True, "filename": filename})
            send_notification("NovaStream", f"Video İndirilenler klasörüne kaydedildi:\n{filename}")
        else:
            err_msg = last_error_line or f"yt-dlp hata verdi (kod {code})"
            send_message({"type": "COMPLETE", "id": job_id, "success": False, "error": err_msg[:140]})
            send_notification("NovaStream", f"İndirme başarısız:\n{err_msg[:120]}")
    except Exception as e:
        logging.exception("run_ytdlp exception")
        send_message({"type": "COMPLETE", "id": job_id, "success": False, "error": str(e)})
    finally:
        if cookie_file:
            try:
                os.remove(cookie_file)
            except OSError:
                pass


def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    logging.info("NovaStream native_host started.")
    cleanup_stale_temp_files()
    while True:
        msg = read_message()
        if msg is None:
            abort_open_files()
            break

        action = msg.get("action", "YTDLP")

        if action in ("FILE_OPEN", "START_STREAM_FILE"):
            handle_file_open(msg)
        elif action == "FILE_CHUNK":
            handle_file_chunk(msg)
        elif action in ("FILE_FINISH", "FINISH_STREAM_FILE"):
            handle_file_finish(msg)
        elif action == "FILE_ABORT":
            handle_file_abort(msg)
        else:
            url = msg.get("url")
            title = msg.get("title") or ""
            job_id = msg.get("id", "job")
            referer = msg.get("referer")
            is_youtube = bool(msg.get("isYouTube", False))

            if url:
                threading.Thread(
                    target=run_ytdlp,
                    args=(url, title, job_id, referer, is_youtube, msg.get("cookies")),
                    daemon=True
                ).start()
            else:
                send_message({"type": "ERROR", "message": "URL eksik"})


if __name__ == "__main__":
    main()

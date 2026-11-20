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

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
for _cand in (_PARENT, os.path.join(_PARENT, "NovaStream-App")):
    if os.path.isdir(os.path.join(_cand, "core")) and _cand not in sys.path:
        sys.path.insert(0, _cand)
        break

try:
    from core.engine import (
        atomic_move,
        cleanup_old_temp_entries,
        get_temp_root,
    )
except Exception:
    def get_temp_root(destination_dir=None, create=True):
        base = os.path.join(tempfile.gettempdir(), "novastream_temp")
        if create:
            os.makedirs(base, exist_ok=True)
        return base

    def atomic_move(src, dst):
        try:
            os.replace(src, dst)
        except OSError:
            shutil.move(src, dst)

    def cleanup_old_temp_entries(temp_root, max_age_hours=72):
        pass

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


def _find_tool(name):
    """Sistem PATH veya gömülü runtime/bin içinden aracı (ffmpeg, yt-dlp) bulur."""
    found = shutil.which(name)
    if found:
        return found
    py_dir = os.path.dirname(sys.executable)
    parent = os.path.dirname(py_dir)
    search_dirs = [
        py_dir,
        os.path.join(py_dir, "Scripts"),
        os.path.join(py_dir, "bin"),
        os.path.join(parent, "bin"),
        os.path.join(parent, "runtime", "bin"),
    ]
    for cand in (name, name + ".exe"):
        for d in search_dirs:
            p = os.path.join(d, cand)
            if os.path.exists(p):
                return p
    for p in (f"/usr/bin/{name}", f"/usr/local/bin/{name}", f"C:\\ffmpeg\\bin\\{name}.exe", f"C:\\yt-dlp\\{name}.exe"):
        if os.path.exists(p):
            return p
    return None


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
        temp_root = get_temp_root(DOWNLOAD_DIR, create=False)
        cleanup_old_temp_entries(temp_root, max_age_hours=max_age_hours)
        for directory in (DOWNLOAD_DIR, temp_root):
            if not directory or not os.path.isdir(directory):
                continue
            for name in os.listdir(directory):
                if name.startswith(TMP_PREFIX):
                    path = os.path.join(directory, name)
                    if now - os.path.getmtime(path) > max_age_hours * 3600:
                        os.remove(path)
                        logging.info(f"Eski geçici dosya silindi: {name}")
    except Exception as e:
        logging.warning(f"Geçici dosya temizliği: {e}")


def abort_open_files():
    """Tarayıcı bağlantısı koptuğunda yarım kalan dosyaları kapatıp siler."""
    for job_id in list(open_files.keys()):
        handle_file_abort({"id": job_id})


def strip_media_exts(name):
    return re.sub(r"(?:\.(?:mp4|mkv|webm|mov|mp3|m4a|ts|m3u8|mpd))+$", "", name or "", flags=re.IGNORECASE).strip()


def handle_file_open(msg):
    job_id = msg.get("id")
    raw_title = msg.get("title") or msg.get("filename") or "video.mp4"
    safe_name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", raw_title).strip().strip(".")
    if not safe_name:
        safe_name = "video"
    base, ext = os.path.splitext(safe_name)
    if not ext:
        ext = ".mp4"
    base = strip_media_exts(base) or base
    final_path = get_unique_filepath(DOWNLOAD_DIR, f"{base}{ext}")
    temp_ext = ".mp4" if msg.get("isFmp4") else (".ts" if msg.get("isTs") else ext)
    temp_root = get_temp_root(DOWNLOAD_DIR, create=True)
    temp_path = os.path.join(temp_root, f"{TMP_PREFIX}{job_id}{temp_ext}")

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
    remux_temp = os.path.join(os.path.dirname(temp_path), f"{TMP_PREFIX}{job_id}_remux{os.path.splitext(final_path)[1] or '.mp4'}")

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
        ffmpeg_bin = _find_tool("ffmpeg")

        ffmpeg_cmd = [
            ffmpeg_bin or "ffmpeg",
            "-y",
            "-i", temp_path,
            "-c", "copy"
        ]
        if final_path.lower().endswith(".mp4"):
            ffmpeg_cmd.extend(["-movflags", "+faststart"])
        ffmpeg_cmd.append(remux_temp)
        res = (
            subprocess.run(ffmpeg_cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if ffmpeg_bin
            else subprocess.CompletedProcess(ffmpeg_cmd, 1, "", "ffmpeg bulunamadi")
        )

        if res.returncode == 0 and os.path.exists(remux_temp) and os.path.getsize(remux_temp) > 0:
            atomic_move(remux_temp, final_path)
            if os.path.exists(temp_path):
                os.remove(temp_path)
            logging.info(f"Remux success: {final_path}")
        else:
            if os.path.exists(remux_temp):
                try:
                    os.remove(remux_temp)
                except OSError:
                    pass
            logging.warning(f"Remux fallback ({res.returncode}): {res.stderr[-300:]}")
            # Fallback: doğrudan dosyayı taşı
            atomic_move(temp_path, final_path)

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


def _audio_selector(has_ffmpeg, audio_lang=None, audio_name=None):
    if not has_ffmpeg:
        return "b", []
    lang = re.sub(r"[\[\](),/+'\"\\\r\n\t]", "", str(audio_lang or "")).strip().lower()
    name = re.sub(r"[\[\](),/+'\"\\\r\n\t]", "", str(audio_name or "")).strip()
    if not lang and not name:
        return "bv*+ba/b", []
    if lang == "all":
        return "bv*+mergeall[vcodec=none]/bv*+ba/b", ["--audio-multistreams"]
    cands = []
    if lang:
        cands.append(f"bv*+ba[language^={lang}]")
    if name:
        cands.extend([f"bv*+ba[format_note*={name}]", f"bv*+ba[format_id*={name}]"])
    if lang:
        cands.append(f"bv*+mergeall[vcodec=none][language^={lang}]")
    if name:
        cands.extend([f"bv*+mergeall[vcodec=none][format_note*={name}]", f"bv*+mergeall[vcodec=none][format_id*={name}]"])
    cands.extend(["bv*+ba", "b"])
    seen = []
    for c in cands:
        if c not in seen:
            seen.append(c)
    return "/".join(seen), ["--audio-multistreams"]


def run_ytdlp(url, title, job_id, referer=None, is_youtube=False, cookies=None, audio_lang=None, audio_name=None):
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

    ytdlp_bin = _find_tool("yt-dlp") or "yt-dlp"
    ffmpeg_bin = _find_tool("ffmpeg")

    # Eklentinin gönderdiği tarayıcı çerezleri (üyelere özel / giriş gerektiren videolar)
    cookie_file = None
    if isinstance(cookies, str) and cookies.strip() and len(cookies) <= 512 * 1024:
        try:
            fd, cookie_file = tempfile.mkstemp(prefix="novastream_cookies_", suffix=".txt")
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                text = cookies.replace("\r\n", "\n")
                if not text.startswith("# Netscape HTTP Cookie File"):
                    f.write("# Netscape HTTP Cookie File\n")
                f.write(text if text.endswith("\n") else text + "\n")
        except Exception:
            logging.exception("Çerez dosyası yazılamadı")
            cookie_file = None

    job_temp_dir = None
    cleanup_job_temp = False

    try:
        cleanup_old_temp_entries(get_temp_root(DOWNLOAD_DIR, create=False))

        # Windows'ta yt-dlp.exe başlatıcısı native host altında asılı kalabiliyor;
        # mümkünse aynı Python ile modül olarak çalıştır.
        import importlib.util
        if importlib.util.find_spec("yt_dlp"):
            ytdlp_cmd = [sys.executable, "-m", "yt_dlp"]
        else:
            ytdlp_cmd = [ytdlp_bin]

        if title:
            base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title).strip().strip(".")
            base = strip_media_exts(base) or "video"
            out_template = base + ".%(ext)s"
        else:
            out_template = "%(title).150B [%(id)s].%(ext)s"

        safe_job = re.sub(r"[^A-Za-z0-9_-]", "_", str(job_id))[:48] or "job"
        job_temp_dir = os.path.join(get_temp_root(DOWNLOAD_DIR, create=True), f"nh_{safe_job}")
        os.makedirs(job_temp_dir, exist_ok=True)

        def build_cmd(use_cookies):
            fmt_expr, extra_flags = _audio_selector(bool(ffmpeg_bin), audio_lang=audio_lang, audio_name=audio_name)
            cmd = ytdlp_cmd + [
                "-f", fmt_expr,
                "--merge-output-format", "mp4",
                "--no-playlist",
                "--no-quiet",
                "--newline",
                "--progress",
                "--no-overwrites",
                "-N", "8" if is_youtube else "10",
                "--buffer-size", "64K",
                "--no-resize-buffer",
                "--retries", "10",
                "--fragment-retries", "10",
                "--retry-sleep", "http:exp=1:20",
                "--retry-sleep", "fragment:exp=1:20",
                "-P", f"home:{DOWNLOAD_DIR}",
                "-P", f"temp:{job_temp_dir}",
                "--no-simulate",
                "--print", "after_move:" + FILE_PREFIX + "%(filepath)s",
                "-o", out_template
            ] + extra_flags
            if is_youtube:
                cmd.extend(["--http-chunk-size", "10M"])
            if ffmpeg_bin:
                cmd.extend(["--ffmpeg-location", ffmpeg_bin])
            if referer:
                cmd.extend(["--referer", referer])
                try:
                    import urllib.parse
                    parsed = urllib.parse.urlparse(referer)
                    if parsed.scheme and parsed.netloc:
                        cmd.extend(["--add-header", f"Origin:{parsed.scheme}://{parsed.netloc}"])
                except Exception:
                    pass
            if cookie_file:
                cmd.extend(["--cookies", cookie_file])
            elif use_cookies:
                cmd.extend(["--cookies-from-browser", "chrome"])
            cmd.append(url)
            return cmd

        def execute(use_cookies):
            last_error = ""
            final_path = None
            num_streams = 1
            stream_idx = -1
            max_pct = 2
            last_raw_pct = 0.0
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
                m_fmt = re.search(r"Downloading\s+\d+\s+format\(s\):\s*(\S+)", line)
                if m_fmt:
                    num_streams = max(1, m_fmt.group(1).count("+") + 1)
                if line.startswith("[download] Destination:"):
                    stream_idx += 1
                    last_raw_pct = 0.0
                match = DL_PATTERN.search(line)
                if match:
                    pct_str, size_str, speed_str, eta_str = match.groups()
                    raw_pct = float(pct_str)
                    if raw_pct + 5.0 < last_raw_pct:
                        stream_idx = 1 if stream_idx < 0 else (stream_idx + 1)
                    last_raw_pct = raw_pct
                    frac = min(1.0, max(0.0, raw_pct / 100.0))
                    if num_streams <= 1:
                        pct = min(99, int(frac * 99))
                    elif num_streams == 2:
                        pct = int(frac * 85) if stream_idx <= 0 else int(85 + frac * 13)
                    else:
                        if stream_idx <= 0:
                            pct = int(frac * 78)
                        else:
                            pos = (min(stream_idx, num_streams - 1) - 1 + frac) / max(1, num_streams - 1)
                            pct = int(78 + pos * 20)
                    max_pct = max(max_pct, pct)
                    speed_label = speed_str or "Aktarılıyor"
                    if num_streams >= 2 and stream_idx >= 1:
                        if num_streams == 2:
                            speed_label = f"Ses: {speed_label}"
                        else:
                            speed_label = f"Ses {min(stream_idx, num_streams - 1)}/{num_streams - 1}: {speed_label}"
                    send_message({
                        "type": "PROGRESS", "id": job_id, "percent": max_pct,
                        "speedMb": speed_label, "mbTotal": size_str,
                        "eta": f"ETA {eta_str}" if eta_str else ""
                    })
                elif "[youtube]" in line or "Downloading webpage" in line or "[info]" in line:
                    send_message({"type": "PROGRESS", "id": job_id, "percent": max(max_pct, 5),
                                  "speedMb": "Video Akışı Çözümleniyor...", "mbTotal": "", "eta": ""})
                elif "[Merger]" in line or "Merging formats" in line:
                    max_pct = max(max_pct, 99)
                    send_message({"type": "PROGRESS", "id": job_id, "percent": max_pct,
                                  "speedMb": "Ses + Video Birleştiriliyor", "mbTotal": "", "eta": "Son işlem"})
            process.wait()
            return process.returncode, last_error, final_path

        use_cookies = bool(is_youtube and sys.platform != "win32")
        code, last_error_line, final_path = execute(use_cookies)
        if code != 0 and use_cookies and not cookie_file and "cookie" in last_error_line.lower():
            logging.warning("Chrome çerezi okunamadı; çerezsiz yeniden deneniyor.")
            code, last_error_line, final_path = execute(False)

        if code == 0:
            cleanup_job_temp = True
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
        if cleanup_job_temp and job_temp_dir and os.path.isdir(job_temp_dir):
            shutil.rmtree(job_temp_dir, ignore_errors=True)
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
                    args=(url, title, job_id, referer, is_youtube, msg.get("cookies"), msg.get("audioLang"), msg.get("audioName")),
                    daemon=True
                ).start()
            else:
                send_message({"type": "ERROR", "message": "URL eksik"})


if __name__ == "__main__":
    main()

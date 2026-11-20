"""
NovaStream bileşen güncelleyici.
YouTube sık değiştiği için yt-dlp'nin güncel kalması gerekir. Haftada bir (veya kullanıcı isteyince)
uygulamanın kendi Python ortamına yt-dlp[default] ve Deno (YouTube için JavaScript çalışma ortamı) kurulur/güncellenir.
"""

import logging
import os
import subprocess
import sys
import threading
import time

UPDATE_INTERVAL = 7 * 24 * 3600
PACKAGES = ["yt-dlp[default]", "deno"]


def _python_for_pip():
    if getattr(sys, "frozen", False):
        return None  # derlenmiş .exe: pip yok
    py = sys.executable
    if os.path.basename(py).lower() == "pythonw.exe":
        cand = os.path.join(os.path.dirname(py), "python.exe")
        if os.path.exists(cand):
            py = cand
    return py


def update_components(on_done=None):
    """Arka planda pip ile günceller. on_done(success: bool, message: str)."""
    def _run():
        py = _python_for_pip()
        if not py:
            msg = "Derlenmiş sürümde otomatik güncelleme yok."
            if on_done:
                on_done(False, msg)
            return
        cmd = [py, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-U"] + PACKAGES
        kw = dict(stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if sys.platform == "win32":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            res = subprocess.run(cmd, timeout=900, **kw)
            ok = res.returncode == 0
            msg = "yt-dlp ve Deno güncel." if ok else (res.stderr or res.stdout)[-400:]
        except Exception as e:
            ok, msg = False, str(e)
        (logging.info if ok else logging.warning)(f"Bileşen güncellemesi: {msg}")
        if on_done:
            on_done(ok, msg)

    threading.Thread(target=_run, daemon=True).start()


def maybe_auto_update(queue_manager, on_done=None):
    """Son güncellemeden bu yana bir hafta geçtiyse arka planda günceller."""
    last = float(queue_manager.settings.get("last_ytdlp_update") or 0)
    if time.time() - last < UPDATE_INTERVAL:
        return False

    def _done(ok, msg):
        if ok:
            queue_manager.settings["last_ytdlp_update"] = time.time()
            queue_manager.save_settings()
        if on_done:
            on_done(ok, msg)

    update_components(_done)
    return True

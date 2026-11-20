import json
import time
import urllib.error
import urllib.request

import pytest

from conftest import wait_for
from core.bridge_server import BridgeServer
from core.queue_manager import QueueManager


@pytest.fixture(scope="module")
def bridge():
    qm = QueueManager()
    b = BridgeServer(qm, port=0)
    # port=0: işletim sistemi boş port seçer
    assert b.start()
    b.port = b.server.server_address[1]
    yield b
    b.stop()


def call(bridge, path, body=None, origin=None, ctype="application/json"):
    headers = {}
    if origin:
        headers["Origin"] = origin
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = ctype
    req = urllib.request.Request(f"http://127.0.0.1:{bridge.port}{path}", data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), dict(e.headers)


def test_web_sitesi_reddedilir(bridge):
    assert call(bridge, "/api/download", {"url": "https://x/y.exe"}, origin="https://kotu.example")[0] == 403
    assert call(bridge, "/api/tasks", origin="https://kotu.example")[0] == 403
    assert call(bridge, "/api/download", {"url": "https://x/y.exe"}, origin="https://kotu.example", ctype="text/plain")[0] == 403


def test_eklenti_kabul_edilir_ve_indirir(bridge, server):
    code, body, headers = call(bridge, "/api/download", {"url": server + "/range/e.bin", "title": "e.bin"},
                               origin="chrome-extension://abcdefghijklmnop")
    assert code == 200 and body["success"] and body["desktop"]
    assert headers.get("Access-Control-Allow-Origin") == "chrome-extension://abcdefghijklmnop"
    task = bridge.queue_manager.get_task(body["id"])
    assert wait_for(lambda: task.status == "completed", 30)


def test_gecersiz_adres(bridge):
    assert call(bridge, "/api/download", {"url": "file:///etc/passwd"}, origin="moz-extension://x")[0] == 400


def test_onay_ayari_acikken_pencereye_yonlendirir(bridge):
    seen = []
    bridge.on_new_download_request = seen.append
    bridge.queue_manager.settings["confirm_extension_downloads"] = True
    try:
        code, body, _ = call(bridge, "/api/download", {"url": "https://example.com/v.mp4"}, origin="chrome-extension://a")
        assert code == 200 and body["id"] == "pending_dialog" and seen
    finally:
        bridge.queue_manager.settings["confirm_extension_downloads"] = False
        bridge.on_new_download_request = None


def test_eklenti_ilerlemesi_listede_gorunur(bridge):
    call(bridge, "/api/task_progress", {"id": "ext-1", "filename": "Türkçe Başlık.mp4", "percent": 40,
                                        "status": "downloading"}, origin="chrome-extension://a")
    t = bridge.queue_manager.get_task("ext-1")
    assert t.external and t.status == "downloading" and t.filename == "Türkçe Başlık.mp4"
    call(bridge, "/api/task_progress", {"id": "ext-1", "status": "completed"}, origin="chrome-extension://a")
    time.sleep(0.1)
    assert t.status == "completed"


def test_eklentiden_duraklat_devam_iptal(bridge, server, tmp_path):
    ext = "chrome-extension://abcdefghijklmnop"
    bridge.queue_manager.default_connections = 2
    code, body, _ = call(bridge, "/api/download", {"url": server + "/range/slow/k.bin", "title": "k.bin"}, origin=ext)
    task = bridge.queue_manager.get_task(body["id"])
    task.destination_dir = str(tmp_path)
    assert wait_for(lambda: task.downloaded_bytes > 0, 20)
    code, body2, _ = call(bridge, "/api/control", {"id": task.id, "action": "pause"}, origin=ext)
    assert code == 200 and body2["status"] == "paused"
    code, body2, _ = call(bridge, "/api/control", {"id": task.id, "action": "resume"}, origin=ext)
    assert code == 200 and body2["status"] in ("downloading", "queued")
    code, body2, _ = call(bridge, "/api/control", {"id": task.id, "action": "cancel"}, origin=ext)
    assert code == 200 and body2["status"] == "removed"
    assert bridge.queue_manager.get_task(task.id) is None
    assert call(bridge, "/api/control", {"id": task.id, "action": "pause"}, origin=ext)[0] == 404
    assert call(bridge, "/api/control", {"id": "x", "action": "pause"}, origin="https://kotu.example")[0] == 403


def test_cerezler_dosyaya_yazilir_ve_ytdlpye_verilir(tmp_path):
    import os
    import sys
    from core.bridge_server import normalize_cookie_text
    from core.stream_handler import StreamDownloader

    text = normalize_cookie_text(".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\r\n")
    assert text.startswith("# Netscape HTTP Cookie File\n") and "\r" not in text
    assert normalize_cookie_text("") is None and normalize_cookie_text(123) is None

    qm = QueueManager()
    t = qm.add_task(url="https://www.youtube.com/watch?v=x", title="v", is_youtube=True,
                    auto_start=False, cookie_text=text, destination_dir=str(tmp_path))
    path = qm._write_cookie_file(t)
    assert open(path, encoding="utf-8").read() == text
    if sys.platform != "win32":
        assert (os.stat(path).st_mode & 0o777) == 0o600
    sd = StreamDownloader(t.url, destination_dir=str(tmp_path), is_youtube=True, cookie_file=path)
    cmd = sd._build_cmd(True)
    assert cmd[cmd.index("--cookies") + 1] == path and "--cookies-from-browser" not in cmd
    qm.remove_task(t.id)
    assert not os.path.exists(path) and t.cookie_text is None
    assert "cookie" not in json.dumps(t.to_dict()).lower()

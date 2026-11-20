import json
import os
import struct
import sys
import zipfile

from conftest import ROOT, wait_for
from core.bridge_server import BridgeServer
from core.browser_setup import build_extension_packages, detect_browsers
from core.engine import SegmentedDownloader
from core.queue_manager import QueueManager
from core.stream_handler import StreamDownloader, format_selector, safe_title


def test_429_rate_limit_backoff_recovers(server, tmp_path, data):
    res = {}
    d = SegmentedDownloader(
        server + "/ratelimit/rl1.bin",
        str(tmp_path),
        num_connections=4,
        on_completed=lambda p: res.update(done=p),
        on_error=lambda e: res.update(err=e),
    )
    d.start()
    assert wait_for(lambda: res, 30)
    assert "done" in res and "err" not in res
    assert open(res["done"], "rb").read() == data
    assert d._effective_connections < 4


def test_queue_batch_operations_and_subtitles(server, tmp_path):
    qm = QueueManager()
    t1 = qm.add_task(url=server + "/range/slow/b1.bin", title="b1.bin", destination_dir=str(tmp_path), download_subtitles=True)
    t2 = qm.add_task(url=server + "/range/slow/b2.bin", title="b2.bin", destination_dir=str(tmp_path), download_subtitles=True)
    t3 = qm.add_task(url=server + "/range/slow/b3.bin", title="b3.bin", destination_dir=str(tmp_path), auto_start=False)
    assert t1.download_subtitles is True and t1.to_dict()["download_subtitles"] is True
    assert wait_for(lambda: t1.downloaded_bytes > 0 or t1.status == "completed", 20)

    qm.pause_tasks([t1.id, t2.id])
    assert t1.status == "paused" and t2.status == "paused"

    qm.resume_tasks([t1.id, t2.id, t3.id])
    assert t3.status in ("queued", "downloading", "completed")

    removed = qm.remove_tasks([t1.id, t2.id, t3.id], delete_file=False)
    assert removed == 3
    assert qm.get_task(t1.id) is None and qm.get_task(t2.id) is None and qm.get_task(t3.id) is None


def test_stream_downloader_429_and_subtitle_flags(tmp_path):
    sd_hls = StreamDownloader(
        "https://cdn.example.com/master.m3u8",
        destination_dir=str(tmp_path),
        is_youtube=False,
        download_subtitles=True,
        subtitle_langs="tr,en",
    )
    cmd_hls = sd_hls._build_cmd(False)
    assert cmd_hls[cmd_hls.index("-N") + 1] == "10"
    assert "--retry-sleep" in cmd_hls
    assert "--write-subs" in cmd_hls
    assert cmd_hls[cmd_hls.index("--sub-langs") + 1] == "tr,en"

    sd_yt = StreamDownloader("https://www.youtube.com/watch?v=abc", destination_dir=str(tmp_path), is_youtube=True)
    cmd_yt = sd_yt._build_cmd(False)
    assert cmd_yt[cmd_yt.index("-N") + 1] == "8"
    assert "--write-subs" not in cmd_yt


def test_dual_audio_hls_selection_and_safe_title():
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    assert safe_title("İz Peşinde [720p HD].mp4.mp4") == "İz Peşinde [720p HD]"

    master_codec = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Turkish",LANGUAGE="tr",DEFAULT=YES,AUTOSELECT=YES,URI="audio_tr.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="English",LANGUAGE="en",DEFAULT=NO,AUTOSELECT=YES,URI="audio_en.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2",AUDIO="audio"
video_720.m3u8
"""
    master_nolang = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Turkce",DEFAULT=YES,URI="audio_tr.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Orijinal",DEFAULT=NO,URI="audio_en.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2",AUDIO="audio"
video_720.m3u8
"""
    master_nocodec = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Turkish",LANGUAGE="tr",DEFAULT=YES,AUTOSELECT=YES,URI="audio_tr.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="English",LANGUAGE="en",DEFAULT=NO,AUTOSELECT=YES,URI="audio_en.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720,AUDIO="audio"
video_720.m3u8
"""
    media = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n#EXTINF:6.0,\nseg0.ts\n#EXT-X-ENDLIST\n"

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/codec.txt":
                body = master_codec.encode()
            elif self.path == "/nolang.txt":
                body = master_nolang.encode()
            elif self.path == "/nocodec.txt":
                body = master_nocodec.encode()
            else:
                body = media.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        def pick(path, lang, name):
            sel, extra = format_selector("720", True, audio_lang=lang, audio_name=name)
            return subprocess.check_output(
                [sys.executable, "-m", "yt_dlp", "-s", "--print", "%(format_id)s", "-f", sel] + extra + [base + path],
                text=True,
            ).strip()

        assert pick("/codec.txt", "en", "English") == "2500+audio-English"
        assert pick("/codec.txt", "tr", "Turkish") == "2500+audio-Turkish"
        assert pick("/codec.txt", "all", "") == "2500+audio-Turkish+audio-English"

        assert pick("/nolang.txt", "", "Orijinal") == "2500+audio-Orijinal"
        assert pick("/nolang.txt", "", "Turkce") == "2500+audio-Turkce"

        assert pick("/nocodec.txt", "en", "English") == "2500+audio-English"
        assert pick("/nocodec.txt", "tr", "Turkish") == "2500+audio-Turkish"
        assert pick("/nocodec.txt", "all", "") == "2500+audio-Turkish+audio-English"
    finally:
        srv.shutdown()


def test_bridge_save_subtitle_and_security(tmp_path):
    import urllib.error
    import urllib.request

    qm = QueueManager()
    qm.settings["download_dir"] = str(tmp_path)
    bridge = BridgeServer(qm, port=0)
    assert bridge.start()
    port = bridge.server.server_address[1]

    def post(path, body, origin):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Origin": origin, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        code_bad, _ = post("/api/save_subtitle", {"filename": "film.tr.srt", "content": "1\n00:00:01,000 --> 00:00:02,000\nSelam\n"}, "https://evil.example")
        assert code_bad == 403

        code1, body1 = post("/api/save_subtitle", {"filename": "film.tr.srt", "content": "1\n00:00:01,000 --> 00:00:02,000\nSelam\n"}, "chrome-extension://abcdefghijklmnop")
        assert code1 == 200 and body1["success"] and body1["filename"] == "film.tr.srt"
        assert os.path.isfile(tmp_path / "film.tr.srt")

        code2, body2 = post("/api/save_subtitle", {"filename": "film.tr.srt", "content": "1\n00:00:01,000 --> 00:00:02,000\nSelam 2\n"}, "moz-extension://x")
        assert code2 == 200 and body2["filename"] == "film.tr (1).srt"
    finally:
        bridge.stop()


def test_browser_setup_and_extension_packager(tmp_path):
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from tools.package_extensions import package_all

    key_path = tmp_path / "test_key.pem"
    out_dir = tmp_path / "ext_dist"
    summary = package_all(str(out_dir), key_path=str(key_path), with_id_name=True)

    zip_path = out_dir / summary["files"]["chrome_zip"]["filename"]
    crx_path = out_dir / summary["files"]["chrome_crx"]["filename"]
    xpi_path = out_dir / summary["files"]["firefox_xpi"]["filename"]
    id_xpi = out_dir / "novastream@downloader.local.xpi"

    assert zip_path.is_file() and crx_path.is_file() and xpi_path.is_file() and id_xpi.is_file()
    assert (out_dir / "packages_manifest.json").is_file()

    # CRX3 ikili başlık ve iç zip doğrulaması
    raw = crx_path.read_bytes()
    assert raw[:4] == b"Cr24"
    ver, hdr_len = struct.unpack("<II", raw[4:12])
    assert ver == 3 and hdr_len > 0
    inner_zip_path = tmp_path / "inner.zip"
    inner_zip_path.write_bytes(raw[12 + hdr_len:])
    with zipfile.ZipFile(inner_zip_path, "r") as zf:
        mf = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert "key" not in mf, "mismatched manifest key must be stripped inside CRX3 zip"

    # browser_setup.build_extension_packages ve detect_browsers
    bdir = tmp_path / "browser"
    (bdir / "chrome").mkdir(parents=True)
    (bdir / "chrome" / "manifest.json").write_text('{"name":"x","version":"2.5.0","manifest_version":3}', encoding="utf-8")
    (bdir / "firefox").mkdir(parents=True)
    (bdir / "firefox" / "manifest.json").write_text('{"name":"x","version":"2.5.0","manifest_version":3}', encoding="utf-8")
    pkg = build_extension_packages(str(bdir))
    assert os.path.isfile(pkg["chrome_zip"]) and os.path.isfile(pkg["firefox_xpi"])
    assert isinstance(detect_browsers(), list)


def test_mainwindow_multiselect_and_select_all(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QTableWidget
    from core.bridge_server import BridgeServer
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    qm = QueueManager()
    qm.tasks.clear()
    qm.save_history()
    bridge = BridgeServer(qm, port=0)
    win = MainWindow(qm, bridge)
    try:
        t1 = qm.add_task("https://example.com/1.bin", title="1.bin", destination_dir=str(tmp_path), auto_start=False)
        t2 = qm.add_task("https://example.com/2.bin", title="2.bin", destination_dir=str(tmp_path), auto_start=False)
        t3 = qm.add_task("https://example.com/3.bin", title="3.bin", destination_dir=str(tmp_path), auto_start=False)
        win.refresh_table_data(force=True)

        assert win.table.columnCount() == 9
        assert win.table.selectionMode() == QTableWidget.SelectionMode.ExtendedSelection
        assert win.table.rowCount() == 3

        # Tek onay kutusu seçimi refresh_table_data sonrasında korunmalı
        win.table.item(1, 0).setCheckState(Qt.CheckState.Checked)
        assert win.get_selected_task_ids() == [t2.id]
        win.refresh_table_data()
        assert win.table.item(1, 0).checkState() == Qt.CheckState.Checked
        assert win.get_selected_task_ids() == [t2.id]

        # Tümünü Seç -> 3 öğe, tekrar -> 0 öğe
        win.toggle_select_all()
        assert win.get_selected_task_ids() == [t1.id, t2.id, t3.id]
        win.toggle_select_all()
        assert win.get_selected_task_ids() == []

        # Çoklu silme
        win.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        win.table.item(2, 0).setCheckState(Qt.CheckState.Checked)
        win.delete_tasks(win.get_selected_task_ids(), delete_file=False)
        assert win.table.rowCount() == 1
        assert qm.get_task(t1.id) is None and qm.get_task(t3.id) is None
        assert qm.get_task(t2.id) is not None
    finally:
        win.timer.stop()
        win.close()
        app.processEvents()


def test_ytdlp_dual_audio_labels_and_clean_downloads(tmp_path):
    import subprocess
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from core.stream_handler import find_binary

    ff = find_binary("ffmpeg")
    if not ff:
        import pytest
        pytest.skip("FFmpeg kurulu değil")

    media_dir = tmp_path / "srv"
    media_dir.mkdir()
    # Gerçek MPEG-TS görüntü ve iki ayrı dilde AAC ses segmenti üret (H.264 + AAC)
    v_ts = media_dir / "v.ts"
    tr_ts = media_dir / "tr.ts"
    en_ts = media_dir / "en.ts"
    subprocess.run(
        [ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
         "-c:v", "libx264", "-t", "1", "-f", "mpegts", str(v_ts)],
        check=True,
    )
    subprocess.run(
        [ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "aac", "-f", "mpegts", str(tr_ts)],
        check=True,
    )
    subprocess.run(
        [ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=1",
         "-c:a", "aac", "-f", "mpegts", str(en_ts)],
        check=True,
    )
    v_bytes = v_ts.read_bytes()
    tr_bytes = tr_ts.read_bytes()
    en_bytes = en_ts.read_bytes()

    master_txt = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Turkish",LANGUAGE="tr",DEFAULT=YES,AUTOSELECT=YES,URI="aud_tr.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="English",LANGUAGE="en",DEFAULT=NO,AUTOSELECT=YES,URI="aud_en.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=1500000,RESOLUTION=640x360,CODECS="avc1.64001f,mp4a.40.2",AUDIO="audio"
vid.m3u8
"""
    def make_media(prefix):
        return (
            "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n"
            f"#EXTINF:1.0,\n{prefix}_0.ts\n#EXTINF:1.0,\n{prefix}_1.ts\n#EXT-X-ENDLIST\n"
        )

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/master.txt":
                body = master_txt.encode()
            elif self.path == "/vid.m3u8":
                body = make_media("v").encode()
            elif self.path == "/aud_tr.m3u8":
                body = make_media("tr").encode()
            elif self.path == "/aud_en.m3u8":
                body = make_media("en").encode()
            elif self.path.startswith("/v_"):
                body = v_bytes
            elif self.path.startswith("/tr_"):
                body = tr_bytes
            elif self.path.startswith("/en_"):
                body = en_bytes
            else:
                self.send_response(404); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        out_dir = tmp_path / "Downloads_Dual"
        out_dir.mkdir()
        events = []
        dest_snapshots = []

        def on_prog(d):
            events.append(d)
            dest_snapshots.append(list(os.listdir(out_dir)))

        res = {}
        sd = StreamDownloader(
            base + "/master.txt",
            destination_dir=str(out_dir),
            custom_title="Ornek Film [720p HD].mp4",
            quality="720",
            audio_lang="all",
            on_progress=on_prog,
            on_completed=lambda p: res.update(done=p),
            on_error=lambda e: res.update(err=e),
        )
        sd.start()
        assert wait_for(lambda: res, 30)
        assert "done" in res and "err" not in res
        assert os.path.isfile(res["done"])
        assert os.listdir(out_dir) == ["Ornek Film [720p HD].mp4"]
        assert all(
            not any(n.endswith((".part", ".ts", ".ytdl", ".nspart")) for n in snap)
            for snap in dest_snapshots
        )
        pcts = [e["percent"] for e in events]
        assert pcts == sorted(pcts)
        assert any("Ses" in (e.get("speed_formatted") or "") for e in events)
        assert any("Birleştiriliyor" in (e.get("speed_formatted") or "") for e in events)

        probe = subprocess.run([ff, "-i", res["done"]], capture_output=True, text=True)
        info = probe.stderr
        assert "Video: h264" in info
        assert info.count("Audio: aac") == 2

        # Tek dil (İngilizce) seçimi yalnızca 1 ses kanalı vermeli
        out_en = tmp_path / "Downloads_En"
        out_en.mkdir()
        res_en = {}
        sd_en = StreamDownloader(
            base + "/master.txt",
            destination_dir=str(out_en),
            custom_title="Tek Ses Film.mp4",
            quality="720",
            audio_lang="en",
            audio_name="English",
            on_completed=lambda p: res_en.update(done=p),
            on_error=lambda e: res_en.update(err=e),
        )
        sd_en.start()
        assert wait_for(lambda: res_en, 30)
        assert "done" in res_en
        info_en = subprocess.run([ff, "-i", res_en["done"]], capture_output=True, text=True).stderr
        assert "Video: h264" in info_en
        assert info_en.count("Audio: aac") == 1
    finally:
        srv.shutdown()


def test_segmented_and_stream_temp_dir_isolation(server, tmp_path, data):
    dest = tmp_path / "CleanDownloads"
    dest.mkdir()
    observed_files = []
    res = {}
    d = SegmentedDownloader(
        server + "/range/slow/isolated.bin",
        str(dest),
        "isolated.bin",
        num_connections=4,
        on_progress=lambda p: observed_files.append(list(os.listdir(dest))),
        on_completed=lambda p: res.update(done=p),
        on_error=lambda e: res.update(err=e),
    )
    d.start()
    assert wait_for(lambda: res, 30)
    assert "done" in res
    assert os.listdir(dest) == ["isolated.bin"]
    assert open(res["done"], "rb").read() == data
    assert all(snap == [] for snap in observed_files)

    sd_hls = StreamDownloader("https://cdn.example.com/master.m3u8", destination_dir=str(dest), is_youtube=False)
    cmd_hls = sd_hls._build_cmd(False)
    assert "--no-quiet" in cmd_hls
    assert f"home:{dest}" in cmd_hls
    assert any(arg.startswith("temp:") for arg in cmd_hls)
    assert "--buffer-size" in cmd_hls
    assert "--http-chunk-size" not in cmd_hls

    sd_yt = StreamDownloader("https://www.youtube.com/watch?v=abc", destination_dir=str(dest), is_youtube=True)
    cmd_yt = sd_yt._build_cmd(False)
    assert "--no-quiet" in cmd_yt
    assert "--http-chunk-size" in cmd_yt


def test_bridge_progress_monotonic():
    import urllib.request
    qm = QueueManager()
    qm.tasks.clear()
    b = BridgeServer(qm, port=0)
    assert b.start()
    port = b.server.server_address[1]
    try:
        def post(payload):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/task_progress",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Origin": "chrome-extension://abcdefghijklmnop", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status

        assert post({"id": "ext-mono", "filename": "film.mp4", "percent": 82, "status": "downloading"}) == 200
        assert post({"id": "ext-mono", "filename": "film.mp4", "percent": 5, "status": "downloading"}) == 200
        t = qm.get_task("ext-mono")
        assert t.percent == 82.0
    finally:
        b.stop()

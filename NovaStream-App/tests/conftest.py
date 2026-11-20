"""
Testler için ortak hazırlık: yalıtılmış ev klasörü ve parçalı (Range) indirmeyi destekleyen yerel test sunucusu.
Ağ erişimi gerekmez.
"""
import os
import re
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

_HOME = tempfile.mkdtemp(prefix="novastream-test-home-")
for var in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
    os.environ[var] = _HOME
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(APP_DIR)
sys.path.insert(0, APP_DIR)

DATA = os.urandom(6_000_000)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _range(self, ignore_range=False, slow=False, head=False):
        rng = self.headers.get("Range")
        if rng and not ignore_range:
            a, b = re.match(r"bytes=(\d+)-(\d*)", rng).groups()
            a, b = int(a), int(b) if b else len(DATA) - 1
            body = DATA[a:b + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(DATA)}")
        else:
            body = DATA
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        if head:
            return
        for i in range(0, len(body), 65536):
            try:
                self.wfile.write(body[i:i + 65536])
            except OSError:
                return
            if slow:
                time.sleep(0.03)

    def do_HEAD(self):
        if self.path.startswith(("/range", "/norange")):
            self._range(head=True)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_GET(self):
        if self.path.startswith("/range"):
            self._range(slow="slow" in self.path)
        elif self.path.startswith("/norange"):
            self._range(ignore_range=True)
        elif self.path.startswith("/chunked"):
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for _ in range(5):
                d = b"y" * 10000
                self.wfile.write(b"%x\r\n" % len(d) + d + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture(scope="session")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def data():
    return DATA


def wait_for(cond, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False

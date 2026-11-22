import base64
import json
import os
import struct
import subprocess
import sys

from conftest import ROOT

HOST = os.path.join(ROOT, "extension", "native_host.py")


def test_parca_yazma_ve_baglanti_kopunca_temizlik(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    p = subprocess.Popen([sys.executable, HOST], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)

    def send(m):
        b = json.dumps(m).encode()
        p.stdin.write(struct.pack("@I", len(b)) + b)
        p.stdin.flush()

    def recv():
        n = struct.unpack("@I", p.stdout.read(4))[0]
        return json.loads(p.stdout.read(n))

    send({"action": "FILE_OPEN", "id": "j1", "title": "Türkçe İsim.mp4"})
    assert recv()["type"] == "FILE_OPENED"
    send({"action": "FILE_CHUNK", "id": "j1", "data": base64.b64encode(b"x" * 1000).decode()})
    send({"action": "FILE_FINISH", "id": "j1"})
    msgs = [recv(), recv()]
    done = [m for m in msgs if m["type"] == "COMPLETE"][0]
    assert done["success"] and done["filename"] == "Türkçe İsim.mp4"

    send({"action": "FILE_OPEN", "id": "j2", "title": "yarim.mp4"})
    recv()
    p.stdin.close()
    p.wait(10)
    downloads = os.listdir(os.path.join(tmp_path, "Downloads"))
    assert "Türkçe İsim.mp4" in downloads
    assert not any(n.startswith(".novastream_tmp_") for n in downloads)

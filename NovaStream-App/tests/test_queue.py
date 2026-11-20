import os
import time

from conftest import wait_for
from core.queue_manager import QueueManager


def test_listeden_kaldir_dosyayi_silmez(server, tmp_path):
    qm = QueueManager()
    t = qm.add_task(url=server + "/range/q.bin", title="q.bin", destination_dir=str(tmp_path))
    assert wait_for(lambda: t.status == "completed", 30)
    qm.remove_task(t.id, delete_file=False)
    time.sleep(0.5)
    assert os.path.exists(t.target_path)


def test_dosyayla_birlikte_sil(server, tmp_path):
    qm = QueueManager()
    t = qm.add_task(url=server + "/range/q2.bin", title="q2.bin", destination_dir=str(tmp_path))
    assert wait_for(lambda: t.status == "completed", 30)
    qm.remove_task(t.id, delete_file=True)
    assert not os.path.exists(t.target_path)


def test_duraklat_devam(server, tmp_path, data):
    qm = QueueManager()
    qm.default_connections = 2
    t = qm.add_task(url=server + "/range/slow/p.bin", title="p.bin", destination_dir=str(tmp_path))
    assert wait_for(lambda: t.downloaded_bytes > 0, 20)
    qm.pause_task(t.id)
    assert t.status == "paused"
    qm.resume_task(t.id)
    assert wait_for(lambda: t.status == "completed", 60)
    assert open(t.target_path, "rb").read() == data


def test_esszamanli_sinir(server, tmp_path):
    qm = QueueManager()
    qm.max_concurrent = 1
    qm.default_connections = 2
    a = qm.add_task(url=server + "/range/slow/c1.bin", title="c1.bin", destination_dir=str(tmp_path))
    b = qm.add_task(url=server + "/range/slow/c2.bin", title="c2.bin", destination_dir=str(tmp_path))
    assert a.status == "downloading" and b.status == "queued"
    assert wait_for(lambda: b.status in ("downloading", "completed"), 60)
    assert wait_for(lambda: b.status == "completed", 60)

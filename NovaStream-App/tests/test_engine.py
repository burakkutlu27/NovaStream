import os
import time

from conftest import wait_for
from core.engine import SegmentedDownloader


def run(url, dest, name=None, conns=8):
    res = {}
    d = SegmentedDownloader(url, str(dest), name, num_connections=conns,
                            on_completed=lambda p: res.update(done=p), on_error=lambda e: res.update(err=e))
    d.start()
    assert wait_for(lambda: res, 60)
    return d, res


def test_parcali_indirme_dogru_veri(server, tmp_path, data):
    _, res = run(server + "/range/a.bin", tmp_path)
    assert open(res["done"], "rb").read() == data


def test_range_desteklemeyen_sunucu(server, tmp_path, data):
    _, res = run(server + "/norange/b.bin", tmp_path)
    assert open(res["done"], "rb").read() == data


def test_boyutu_bilinmeyen_dosya_tam_iner(server, tmp_path):
    _, res = run(server + "/chunked/c.bin", tmp_path)
    assert os.path.getsize(res["done"]) == 50000


def test_404_hata_olarak_bildirilir(server, tmp_path):
    _, res = run(server + "/yok.bin", tmp_path)
    assert "404" in res["err"]
    assert os.listdir(tmp_path) == []


def test_ayni_adli_dosyanin_uzerine_yazmaz(server, tmp_path):
    (tmp_path / "onemli.txt").write_text("kullanıcı verisi", encoding="utf-8")
    _, res = run(server + "/range/a.bin", tmp_path, name="onemli.txt")
    assert os.path.basename(res["done"]) == "onemli (1).txt"
    assert (tmp_path / "onemli.txt").read_text(encoding="utf-8") == "kullanıcı verisi"


def test_tamamlanmis_dosya_iptalde_silinmez(server, tmp_path):
    d, res = run(server + "/range/a.bin", tmp_path)
    d.cancel()
    assert os.path.exists(res["done"])


def test_duraklat_devam_ve_iptal(server, tmp_path, data):
    res = {}
    d = SegmentedDownloader(server + "/range/slow/s.bin", str(tmp_path), None, num_connections=4,
                            on_completed=lambda p: res.update(done=p))
    d.start()
    assert wait_for(lambda: d.part_path and sum(s["downloaded"] for s in d.segments) > 0, 20)
    d.pause()
    time.sleep(0.8)
    b1 = sum(s["downloaded"] for s in d.segments)
    time.sleep(0.8)
    assert sum(s["downloaded"] for s in d.segments) == b1
    assert os.path.exists(d.part_path) and not os.path.exists(d.target_path)
    d.resume()
    assert wait_for(lambda: res, 60)
    assert open(res["done"], "rb").read() == data

    d2 = SegmentedDownloader(server + "/range/slow/t.bin", str(tmp_path), None, num_connections=4)
    d2.start()
    assert wait_for(lambda: d2.part_path and os.path.exists(d2.part_path), 20)
    part = d2.part_path
    d2.cancel()
    time.sleep(0.5)
    assert not os.path.exists(part)

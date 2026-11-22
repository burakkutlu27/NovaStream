import importlib.util
import os
import time

import pytest

from conftest import wait_for
from core.stream_handler import StreamDownloader, format_selector

pytestmark = pytest.mark.skipif(importlib.util.find_spec("yt_dlp") is None, reason="yt-dlp kurulu değil")


def make(server, dest, res, title="Benim Video.mp4", path="/range/slow/vid.mp4"):
    s = StreamDownloader(server + path, str(dest), title,
                         on_progress=lambda p: res.setdefault("prog", []).append(p),
                         on_completed=lambda p: res.update(done=p), on_error=lambda e: res.update(err=e))
    s.ffmpeg_bin = None  # test verisi gerçek video değil
    return s


def test_kalite_secimi():
    assert format_selector("1080", True)[0].startswith("bv*[height<=1080]")
    assert format_selector("audio", True)[1][:2] == ["-x", "--audio-format"]
    assert format_selector("best", False)[0] == "b"


def test_ilerleme_duraklatma_devam_ve_ad_korumasi(server, tmp_path, data):
    (tmp_path / "Benim Video.mp4").write_text("eski", encoding="utf-8")
    r = {}
    s = make(server, tmp_path, r)
    s.start()
    assert wait_for(lambda: any(p.get("downloaded_bytes") for p in r.get("prog", [])), 30)
    s.cancel(delete_partial=False)
    time.sleep(0.5)
    r2 = {}
    s2 = make(server, tmp_path, r2)
    s2.start()
    assert wait_for(lambda: "done" in r2 or "err" in r2, 90)
    assert os.path.basename(r2["done"]) == "Benim Video (1).mp4"
    assert open(r2["done"], "rb").read() == data
    assert (tmp_path / "Benim Video.mp4").read_text(encoding="utf-8") == "eski"


def test_404_hata(server, tmp_path):
    r = {}
    s = make(server, tmp_path, r, title="yok", path="/yok.mp4")
    s.start()
    assert wait_for(lambda: "err" in r or "done" in r, 60)
    assert "404" in r["err"]


def test_iptal_ara_dosyalari_siler_baskasina_dokunmaz(tmp_path):
    from core.stream_handler import StreamDownloader
    for n in ["Bunny.f396.mp4", "Bunny.f251.webm.part", "Bunny.f251.webm.ytdl", "Bunny (1).mp4.part", "Baska.mp4"]:
        (tmp_path / n).write_bytes(b"x")
    s = StreamDownloader("https://youtube.com/watch?v=x", destination_dir=str(tmp_path), is_youtube=True)
    s.output_base = "Bunny"
    s.cancel(delete_partial=True)
    assert sorted(os.listdir(tmp_path)) == ["Baska.mp4", "Bunny (1).mp4.part"]


def test_akis_olcumu_parca_sayisini_dogru_akisa_yazar():
    # yt-dlp "Total fragments" satırını bir sonraki akışın "Destination" satırından ÖNCE yazar
    from core.stream_handler import StreamStats

    now = [0.0]
    st = StreamStats(clock=lambda: now[0])
    lines = [
        "[hlsnative] Total fragments: 300",
        "[download] Destination: film.f1.mp4",
        "[download] Got error: HTTP Error 429: Too Many Requests. Retrying fragment 5 (1/10)...",
    ]
    for ln in lines:
        st.feed(ln)
    st.progress(5_000_000, "avc1", "none", None)
    now[0] = 10.0
    st.feed("[hlsnative] Total fragments: 280")
    st.feed("[download] Destination: film.f2.mp4")
    st.progress(200_000, "none", None, "tr")
    now[0] = 40.0
    video, ses = st.finish()

    assert video["fragments"] == 300 and ses["fragments"] == 280
    assert video["kind"] == "video" and video["http429"] == 1 and video["seconds"] == 10.0
    assert ses["kind"] == "ses" and ses["lang"] == "tr" and ses["retries"] == 0 and ses["seconds"] == 30.0
    assert "ses (tr)" in st.summary()

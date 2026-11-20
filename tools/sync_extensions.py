#!/usr/bin/env python3
"""
Tek kaynaktan iki tarayıcı paketi üretir.

Kaynak: NovaStream-v2/ (Chrome/Edge/Brave eklentisi + native host)
Üretilen: NovaStream-Firefox/ (aynı JS/HTML/CSS + Firefox manifest'i + aynı native host)

Eklentide bir şeyi değiştirdikten sonra çalıştırın:  python tools/sync_extensions.py
"""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "NovaStream-v2")
DST = os.path.join(ROOT, "NovaStream-Firefox")
EXT = "OpenVideoDownloader-Extension"
GECKO_ID = "novastream@downloader.local"


def firefox_manifest(chrome_manifest):
    m = dict(chrome_manifest)
    m.pop("key", None)  # Chrome'a özel sabit kimlik anahtarı
    bg = dict(m.get("background", {}))
    if "service_worker" in bg:
        bg["scripts"] = [bg.pop("service_worker")]
    m["background"] = bg
    ordered = {}
    for k in ("manifest_version", "name", "version", "description"):
        ordered[k] = m.pop(k)
    ordered["browser_specific_settings"] = {"gecko": {"id": GECKO_ID, "strict_min_version": "115.0"}}
    ordered.update(m)
    return ordered


def main():
    src_ext, dst_ext = os.path.join(SRC, EXT), os.path.join(DST, EXT)
    if os.path.isdir(dst_ext):
        shutil.rmtree(dst_ext)
    shutil.copytree(src_ext, dst_ext, ignore=shutil.ignore_patterns("manifest.json"))
    with open(os.path.join(src_ext, "manifest.json"), encoding="utf-8") as f:
        chrome = json.load(f)
    with open(os.path.join(dst_ext, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(firefox_manifest(chrome), f, ensure_ascii=False, indent=2)
        f.write("\n")
    for name in ("native_host.py", "native_host.bat", "native_host.sh"):
        shutil.copy2(os.path.join(SRC, name), os.path.join(DST, name))
    print(f"Firefox paketi güncellendi: {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
NovaStream Tarayıcı Algılama, Paketleme ve Otomatik Eklenti Kurulum Yardımcısı.

- Windows ve Linux'ta yüklü Chrome, Edge, Brave, Opera, Vivaldi, Chromium,
  Firefox, Firefox Developer Edition, LibreWolf ve Waterfox tarayıcılarını algılar.
- Saf Python zipfile ile Chrome/Edge/Brave (.zip) ve Firefox (.xpi) paketleri üretir.
- Native Messaging köprüsünü tüm desteklenen tarayıcılara kaydeder.
- Gecko profillerini bulup .xpi paketini profilin extensions/ klasörüne yerleştirir;
  imza zorunluluğu olan standart tarayıcılarda tek tıkla eklenti sayfası ve klasör açma sunar.
"""

import configparser
import json
import os
import shutil
import subprocess
import sys
import webbrowser
import zipfile

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from core.native_messaging import FIREFOX_EXTENSION_ID, register  # noqa: E402

IS_WINDOWS = sys.platform == "win32"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _existing_dirs(candidates):
    found = []
    for p in candidates:
        if not p:
            continue
        exp = os.path.expandvars(os.path.expanduser(p))
        if os.path.isdir(exp) and exp not in found:
            found.append(exp)
    return found


def _find_exe(win_paths, linux_bins):
    if IS_WINDOWS:
        for p in win_paths:
            exp = os.path.expandvars(p)
            if os.path.isfile(exp):
                return exp
        for name in linux_bins:
            found = shutil.which(name)
            if found:
                return found
    else:
        for name in linux_bins:
            found = shutil.which(name)
            if found:
                return found
    return None


def _gecko_profiles(base_dirs):
    """Gecko tabanlı tarayıcıların profil klasörlerini profiles.ini + tarama ile bulur."""
    profiles = []
    for base in base_dirs:
        ini_path = os.path.join(base, "profiles.ini")
        if os.path.isfile(ini_path):
            cp = configparser.RawConfigParser()
            try:
                cp.read(ini_path, encoding="utf-8")
                for sec in cp.sections():
                    if not cp.has_option(sec, "Path"):
                        continue
                    rel = cp.getboolean(sec, "IsRelative", fallback=True)
                    raw_p = cp.get(sec, "Path")
                    p_dir = os.path.join(base, raw_p) if rel else raw_p
                    p_dir = os.path.normpath(p_dir)
                    if os.path.isdir(p_dir) and p_dir not in profiles:
                        profiles.append(p_dir)
            except Exception:
                pass
        prof_root = os.path.join(base, "Profiles")
        if os.path.isdir(prof_root):
            for entry in os.listdir(prof_root):
                cand = os.path.join(prof_root, entry)
                if os.path.isdir(cand) and cand not in profiles:
                    profiles.append(cand)
        for entry in os.listdir(base):
            if ".default" in entry:
                cand = os.path.join(base, entry)
                if os.path.isdir(cand) and cand not in profiles:
                    profiles.append(cand)
    return profiles


def detect_browsers():
    """Sistemde kurulu tarayıcıları ve profil klasörlerini listeler."""
    specs = []
    if IS_WINDOWS:
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))
        roaming = os.environ.get("APPDATA", os.path.expanduser(r"~\AppData\Roaming"))

        specs = [
            {
                "id": "chrome", "name": "Google Chrome", "family": "chromium",
                "extensions_url": "chrome://extensions", "supports_auto_unsigned": False,
                "win_exes": [
                    os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
                    os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
                    os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
                ],
                "bins": ["chrome"],
                "data_dirs": [os.path.join(local, r"Google\Chrome\User Data")],
            },
            {
                "id": "edge", "name": "Microsoft Edge", "family": "chromium",
                "extensions_url": "edge://extensions", "supports_auto_unsigned": False,
                "win_exes": [
                    os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"),
                    os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
                ],
                "bins": ["msedge"],
                "data_dirs": [os.path.join(local, r"Microsoft\Edge\User Data")],
            },
            {
                "id": "brave", "name": "Brave", "family": "chromium",
                "extensions_url": "brave://extensions", "supports_auto_unsigned": False,
                "win_exes": [
                    os.path.join(pf, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
                    os.path.join(pf86, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
                    os.path.join(local, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
                ],
                "bins": ["brave"],
                "data_dirs": [os.path.join(local, r"BraveSoftware\Brave-Browser\User Data")],
            },
            {
                "id": "opera", "name": "Opera / Opera GX", "family": "chromium",
                "extensions_url": "opera://extensions", "supports_auto_unsigned": False,
                "win_exes": [
                    os.path.join(local, r"Programs\Opera\opera.exe"),
                    os.path.join(local, r"Programs\Opera GX\opera.exe"),
                    os.path.join(pf, r"Opera\opera.exe"),
                ],
                "bins": ["opera"],
                "data_dirs": [
                    os.path.join(roaming, r"Opera Software\Opera Stable"),
                    os.path.join(roaming, r"Opera Software\Opera GX Stable"),
                ],
            },
            {
                "id": "vivaldi", "name": "Vivaldi", "family": "chromium",
                "extensions_url": "vivaldi://extensions", "supports_auto_unsigned": False,
                "win_exes": [
                    os.path.join(local, r"Vivaldi\Application\vivaldi.exe"),
                    os.path.join(pf, r"Vivaldi\Application\vivaldi.exe"),
                ],
                "bins": ["vivaldi"],
                "data_dirs": [os.path.join(local, r"Vivaldi\User Data")],
            },
            {
                "id": "chromium", "name": "Chromium", "family": "chromium",
                "extensions_url": "chrome://extensions", "supports_auto_unsigned": False,
                "win_exes": [os.path.join(local, r"Chromium\Application\chrome.exe")],
                "bins": ["chromium"],
                "data_dirs": [os.path.join(local, r"Chromium\User Data")],
            },
            {
                "id": "firefox", "name": "Mozilla Firefox", "family": "gecko",
                "extensions_url": "about:debugging#/runtime/this-firefox", "supports_auto_unsigned": False,
                "win_exes": [
                    os.path.join(pf, r"Mozilla Firefox\firefox.exe"),
                    os.path.join(pf86, r"Mozilla Firefox\firefox.exe"),
                ],
                "bins": ["firefox"],
                "data_dirs": [os.path.join(roaming, r"Mozilla\Firefox")],
            },
            {
                "id": "firefox-dev", "name": "Firefox Developer Edition", "family": "gecko",
                "extensions_url": "about:addons", "supports_auto_unsigned": True,
                "win_exes": [
                    os.path.join(pf, r"Firefox Developer Edition\firefox.exe"),
                    os.path.join(pf86, r"Firefox Developer Edition\firefox.exe"),
                ],
                "bins": [],
                "data_dirs": [os.path.join(roaming, r"Mozilla\Firefox")],
            },
            {
                "id": "librewolf", "name": "LibreWolf", "family": "gecko",
                "extensions_url": "about:addons", "supports_auto_unsigned": True,
                "win_exes": [os.path.join(pf, r"LibreWolf\librewolf.exe")],
                "bins": ["librewolf"],
                "data_dirs": [os.path.join(roaming, r"librewolf")],
            },
            {
                "id": "waterfox", "name": "Waterfox", "family": "gecko",
                "extensions_url": "about:addons", "supports_auto_unsigned": True,
                "win_exes": [os.path.join(pf, r"Waterfox\waterfox.exe")],
                "bins": ["waterfox"],
                "data_dirs": [os.path.join(roaming, r"Waterfox")],
            },
        ]
    else:
        specs = [
            {
                "id": "chrome", "name": "Google Chrome", "family": "chromium",
                "extensions_url": "chrome://extensions", "supports_auto_unsigned": False,
                "win_exes": [], "bins": ["google-chrome", "google-chrome-stable"],
                "data_dirs": ["~/.config/google-chrome"],
                "ext_drop_dirs": ["~/.config/google-chrome/External Extensions"],
            },
            {
                "id": "chromium", "name": "Chromium", "family": "chromium",
                "extensions_url": "chrome://extensions", "supports_auto_unsigned": False,
                "win_exes": [], "bins": ["chromium", "chromium-browser"],
                "data_dirs": ["~/.config/chromium"],
                "ext_drop_dirs": ["~/.config/chromium/External Extensions"],
            },
            {
                "id": "brave", "name": "Brave", "family": "chromium",
                "extensions_url": "brave://extensions", "supports_auto_unsigned": False,
                "win_exes": [], "bins": ["brave-browser", "brave"],
                "data_dirs": ["~/.config/BraveSoftware/Brave-Browser"],
                "ext_drop_dirs": ["~/.config/BraveSoftware/Brave-Browser/External Extensions"],
            },
            {
                "id": "edge", "name": "Microsoft Edge", "family": "chromium",
                "extensions_url": "edge://extensions", "supports_auto_unsigned": False,
                "win_exes": [], "bins": ["microsoft-edge", "microsoft-edge-stable"],
                "data_dirs": ["~/.config/microsoft-edge"],
                "ext_drop_dirs": ["~/.config/microsoft-edge/External Extensions"],
            },
            {
                "id": "vivaldi", "name": "Vivaldi", "family": "chromium",
                "extensions_url": "vivaldi://extensions", "supports_auto_unsigned": False,
                "win_exes": [], "bins": ["vivaldi", "vivaldi-stable"],
                "data_dirs": ["~/.config/vivaldi"],
                "ext_drop_dirs": ["~/.config/vivaldi/External Extensions"],
            },
            {
                "id": "opera", "name": "Opera", "family": "chromium",
                "extensions_url": "opera://extensions", "supports_auto_unsigned": False,
                "win_exes": [], "bins": ["opera"],
                "data_dirs": ["~/.config/opera"],
                "ext_drop_dirs": ["~/.config/opera/External Extensions"],
            },
            {
                "id": "firefox", "name": "Mozilla Firefox", "family": "gecko",
                "extensions_url": "about:debugging#/runtime/this-firefox", "supports_auto_unsigned": False,
                "win_exes": [], "bins": ["firefox"],
                "data_dirs": ["~/.mozilla/firefox"],
            },
            {
                "id": "librewolf", "name": "LibreWolf", "family": "gecko",
                "extensions_url": "about:addons", "supports_auto_unsigned": True,
                "win_exes": [], "bins": ["librewolf"],
                "data_dirs": ["~/.librewolf"],
            },
            {
                "id": "waterfox", "name": "Waterfox", "family": "gecko",
                "extensions_url": "about:addons", "supports_auto_unsigned": True,
                "win_exes": [], "bins": ["waterfox"],
                "data_dirs": ["~/.waterfox"],
            },
        ]

    detected = []
    for sp in specs:
        exe = _find_exe(sp["win_exes"], sp["bins"])
        data_dirs = _existing_dirs(sp["data_dirs"])
        installed = bool(exe or data_dirs)
        if not installed:
            continue
        profiles = _gecko_profiles(data_dirs) if sp["family"] == "gecko" else data_dirs
        detected.append({
            "id": sp["id"],
            "name": sp["name"],
            "family": sp["family"],
            "installed": True,
            "executable": exe,
            "data_dirs": data_dirs,
            "profile_dirs": profiles,
            "extensions_url": sp["extensions_url"],
            "supports_auto_unsigned": sp["supports_auto_unsigned"],
            "ext_drop_dirs": [os.path.expanduser(d) for d in sp.get("ext_drop_dirs", [])],
        })
    return detected


def _zip_dir(src_dir, dst_zip):
    os.makedirs(os.path.dirname(dst_zip), exist_ok=True)
    with zipfile.ZipFile(dst_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for name in sorted(files):
                full = os.path.join(root, name)
                rel = os.path.relpath(full, src_dir).replace("\\", "/")
                zf.write(full, rel)
    return dst_zip


def build_extension_packages(browser_dir):
    """browser_dir altındaki chrome/ ve firefox/ klasörlerinden .zip ve .xpi paketleri üretir."""
    browser_dir = os.path.abspath(browser_dir)
    pkg_dir = os.path.join(browser_dir, "packages")
    os.makedirs(pkg_dir, exist_ok=True)

    result = {"packages_dir": pkg_dir, "chrome_zip": None, "firefox_xpi": None, "chrome_crx": None}

    chrome_dir = os.path.join(browser_dir, "chrome")
    if os.path.isdir(chrome_dir):
        chrome_zip = os.path.join(pkg_dir, "NovaStream-Chrome-Edge-Brave.zip")
        _zip_dir(chrome_dir, chrome_zip)
        result["chrome_zip"] = chrome_zip

    firefox_dir = os.path.join(browser_dir, "firefox")
    if os.path.isdir(firefox_dir):
        firefox_xpi = os.path.join(pkg_dir, f"{FIREFOX_EXTENSION_ID}.xpi")
        _zip_dir(firefox_dir, firefox_xpi)
        result["firefox_xpi"] = firefox_xpi

    for entry in os.listdir(pkg_dir):
        if entry.lower().endswith(".crx"):
            result["chrome_crx"] = os.path.join(pkg_dir, entry)
            break

    return result


def _read_crx_manifest_info(pkg_dir):
    mf_path = os.path.join(pkg_dir, "packages_manifest.json")
    if not os.path.isfile(mf_path):
        return {}
    try:
        with open(mf_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def auto_install_extensions(browser_dir, browsers=None):
    """
    Native Messaging kaydını yapar, paketleri hazırlar ve desteklenen tarayıcı profillerine
    otomatik kurulum / hazırlık gerçekleştirir.
    """
    browser_dir = os.path.abspath(browser_dir)
    if browsers is None:
        browsers = detect_browsers()

    packages = build_extension_packages(browser_dir)
    crx_info = _read_crx_manifest_info(packages["packages_dir"])
    extra_ids = [crx_info["crx_extension_id"]] if crx_info.get("crx_extension_id") else None

    native_registered = register(browser_dir, extra_chrome_ids=extra_ids)

    chrome_dir = os.path.join(browser_dir, "chrome")
    firefox_manifest = os.path.join(browser_dir, "firefox", "manifest.json")
    firefox_xpi = packages.get("firefox_xpi")
    chrome_crx = packages.get("chrome_crx")

    browser_results = []
    for b in browsers:
        entry = {
            "id": b["id"],
            "name": b["name"],
            "family": b["family"],
            "extensions_url": b["extensions_url"],
            "status": "manual_needed",
            "detail": "",
        }
        if b["family"] == "gecko":
            copied_to = []
            if firefox_xpi and os.path.isfile(firefox_xpi):
                for pdir in b.get("profile_dirs", []):
                    ext_dir = os.path.join(pdir, "extensions")
                    try:
                        os.makedirs(ext_dir, exist_ok=True)
                        dst = os.path.join(ext_dir, f"{FIREFOX_EXTENSION_ID}.xpi")
                        shutil.copy2(firefox_xpi, dst)
                        copied_to.append(dst)
                    except OSError:
                        pass
            if copied_to and b["supports_auto_unsigned"]:
                entry["status"] = "installed"
                entry["detail"] = f"{len(copied_to)} profil klasörüne (.xpi) otomatik kopyalandı."
            elif copied_to:
                entry["status"] = "staged_unsigned"
                entry["detail"] = (
                    f".xpi profil klasörüne kopyalandı; standart Firefox imza kontrolü nedeniyle "
                    f"about:debugging üzerinden {firefox_manifest} dosyasını seçin."
                )
            else:
                entry["status"] = "manual_needed"
                entry["detail"] = f"about:debugging üzerinden {firefox_manifest} dosyasını yükleyin."
        else:
            crx_id = crx_info.get("crx_extension_id")
            crx_version = crx_info.get("version") or "2.6.0"
            if not IS_WINDOWS and chrome_crx and crx_id and b.get("ext_drop_dirs"):
                placed = []
                for drop_dir in b["ext_drop_dirs"]:
                    try:
                        os.makedirs(drop_dir, exist_ok=True)
                        ext_json = os.path.join(drop_dir, f"{crx_id}.json")
                        with open(ext_json, "w", encoding="utf-8", newline="\n") as f:
                            json.dump({"external_crx": chrome_crx, "external_version": crx_version}, f, indent=2)
                            f.write("\n")
                        placed.append(ext_json)
                    except OSError:
                        pass
                if placed:
                    entry["status"] = "installed"
                    entry["detail"] = "External Extensions (.crx) tanımı yazıldı."
                else:
                    entry["status"] = "ready_unpacked"
                    entry["detail"] = f"Geliştirici modu → Paketlenmemiş öğe yükle → {chrome_dir}"
            else:
                entry["status"] = "ready_unpacked"
                entry["detail"] = (
                    f"Tarayıcı güvenlik politikası gereği {b['extensions_url']} sayfasından "
                    f"'{chrome_dir}' klasörünü bir kez seçin (köprü otomatik kaydedildi)."
                )
        browser_results.append(entry)

    return {
        "native_registered": native_registered,
        "packages": packages,
        "browsers": browser_results,
    }


def open_browser_extensions_page(browser_info):
    """Algılanan tarayıcının eklenti yönetim sayfasını açar."""
    url = browser_info.get("extensions_url") or "chrome://extensions"
    exe = browser_info.get("executable")
    try:
        if exe and os.path.isfile(exe):
            kw = {}
            if IS_WINDOWS:
                kw["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | NO_WINDOW
            else:
                kw["start_new_session"] = True
            subprocess.Popen([exe, url], **kw)
            return True
    except Exception:
        pass
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def reveal_path_in_file_manager(path):
    """Dosya veya klasörü işletim sistemi dosya yöneticisinde gösterir."""
    if not path or not os.path.exists(path):
        return False
    abs_path = os.path.abspath(path)
    try:
        if IS_WINDOWS:
            if os.path.isfile(abs_path):
                subprocess.Popen(["explorer", "/select,", abs_path])
            else:
                os.startfile(abs_path)
        else:
            target = abs_path if os.path.isdir(abs_path) else os.path.dirname(abs_path)
            subprocess.Popen(["xdg-open", target])
        return True
    except Exception:
        return False


if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(APP_DIR), "extension"
    )
    res = auto_install_extensions(target_dir)
    print(json.dumps(res, ensure_ascii=False, indent=2))

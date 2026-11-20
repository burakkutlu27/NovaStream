r"""
Tarayıcı eklentisi <-> native host kaydı (Chrome, Edge, Brave, Chromium, Firefox; Windows ve Linux).

Kurulum sihirbazı bu modülü kullanır. Kayıt, native host başlatıcısının bulunduğu klasörü gösterir:
  Windows: <klasör>\native_host.bat   (kayıt defteri: HKCU\Software\<tarayıcı>\NativeMessagingHosts)
  Linux:   <klasör>/native_host.sh     (~/.config/<tarayıcı>/NativeMessagingHosts, ~/.mozilla/native-messaging-hosts)
"""

import json
import os
import sys

HOST_NAME = "com.novastream.downloader"
FIREFOX_EXTENSION_ID = "novastream@downloader.local"

# Sabit Chrome eklenti kimliği (manifest.json içindeki "key" alanından türetilir)
CHROME_EXTENSION_ID = "phbdcgdmpmgacehbfkkjbmjofdhhhohg"
# Eski sürümlerin (anahtarsız, klasör yoluna bağlı) kimlikleri: geriye dönük uyumluluk
LEGACY_CHROME_IDS = [
    "nkdhdooopfbfackbbamoaiaogelococa", "nldpfodpihebkchikhopmehfhliickch",
    "ifljainiddhmiajejfmpogndchkjaolk", "jgmlpbhmcnohgifheaecmjmgppninnln",
    "dhnlfkhiemiemdkdeihpblcphkpianam", "eeijgmhipanjpppeljdnkfnajohokfgf",
    "ldcddpgdjbpbaicegpngijidfnojmbae", "bhfjhhjifjkdbinicmddmebmhomkfbho",
    "galdolaodgagolmncbonaaojfneboopo",
]

WINDOWS_CHROMIUM_KEYS = [
    r"Software\Google\Chrome\NativeMessagingHosts",
    r"Software\Microsoft\Edge\NativeMessagingHosts",
    r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
    r"Software\Chromium\NativeMessagingHosts",
]
WINDOWS_FIREFOX_KEY = r"Software\Mozilla\NativeMessagingHosts"

LINUX_CHROMIUM_DIRS = [
    "~/.config/google-chrome/NativeMessagingHosts",
    "~/.config/chromium/NativeMessagingHosts",
    "~/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts",
    "~/.config/microsoft-edge/NativeMessagingHosts",
]
LINUX_FIREFOX_DIR = "~/.mozilla/native-messaging-hosts"


def chrome_manifest(launcher):
    return {
        "name": HOST_NAME,
        "description": "NovaStream Native Downloader Host",
        "path": launcher,
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{i}/" for i in [CHROME_EXTENSION_ID] + LEGACY_CHROME_IDS],
    }


def firefox_manifest(launcher):
    return {
        "name": HOST_NAME,
        "description": "NovaStream Native Downloader Host for Firefox",
        "path": launcher,
        "type": "stdio",
        "allowed_extensions": [FIREFOX_EXTENSION_ID],
    }


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def register(host_dir):
    """host_dir: native_host.py ve başlatıcısının bulunduğu klasör. Kaydedilen konumların listesini döndürür."""
    host_dir = os.path.abspath(host_dir)
    done = []
    if sys.platform == "win32":
        import winreg
        launcher = os.path.join(host_dir, "native_host.bat")
        chrome_json = os.path.join(host_dir, HOST_NAME + ".chrome.json")
        firefox_json = os.path.join(host_dir, HOST_NAME + ".firefox.json")
        _write_json(chrome_json, chrome_manifest(launcher))
        _write_json(firefox_json, firefox_manifest(launcher))
        for base, manifest in [(k, chrome_json) for k in WINDOWS_CHROMIUM_KEYS] + [(WINDOWS_FIREFOX_KEY, firefox_json)]:
            key_path = base + "\\" + HOST_NAME
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, manifest)
            done.append("HKCU\\" + key_path)
    else:
        launcher = os.path.join(host_dir, "native_host.sh")
        for p in (launcher, os.path.join(host_dir, "native_host.py")):
            if os.path.exists(p):
                os.chmod(p, 0o755)
        for d in LINUX_CHROMIUM_DIRS:
            d = os.path.expanduser(d)
            if os.path.isdir(os.path.dirname(d)):
                target = os.path.join(d, HOST_NAME + ".json")
                _write_json(target, chrome_manifest(launcher))
                done.append(target)
        ff = os.path.join(os.path.expanduser(LINUX_FIREFOX_DIR), HOST_NAME + ".json")
        _write_json(ff, firefox_manifest(launcher))
        done.append(ff)
    return done


def unregister():
    if sys.platform == "win32":
        import winreg
        for base in WINDOWS_CHROMIUM_KEYS + [WINDOWS_FIREFOX_KEY]:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base + "\\" + HOST_NAME)
            except OSError:
                pass
    else:
        for d in LINUX_CHROMIUM_DIRS + [LINUX_FIREFOX_DIR]:
            p = os.path.join(os.path.expanduser(d), HOST_NAME + ".json")
            if os.path.exists(p):
                os.remove(p)


if __name__ == "__main__":
    # Kaynak klasörden (kurulumsuz) çalıştırmak için: python native_messaging.py <native_host klasörü>
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "NovaStream-v2")
    for line in register(target):
        print("[OK]", line)

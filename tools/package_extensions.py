#!/usr/bin/env python3
"""
NovaStream Tarayıcı Eklentisi Paketleyici (.zip, .crx CRX3, .xpi)

Kullanım:
    python tools/package_extensions.py [--out dist/extensions] [--key path/to/key.pem] [--with-id-name]

- Önce tools/sync_extensions.py ile NovaStream-Firefox kopyasını senkronize eder.
- Chrome / Edge / Brave / Opera / Vivaldi için:
    * NovaStream-Chrome-Edge-Brave-v<ver>.zip
    * NovaStream-Chrome-Edge-Brave-v<ver>.crx (geçerli CRX3 protobuf + RSA-2048 imzalı)
- Firefox / LibreWolf / Waterfox için:
    * NovaStream-Firefox-v<ver>.xpi
    * (--with-id-name verilirse) novastream@downloader.local.xpi
- packages_manifest.json özet dosyasını yazar (sürüm, SHA-256, CRX eklenti kimliği).
"""

import argparse
import base64
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools import sync_extensions  # noqa: E402

CHROME_EXT_DIR = os.path.join(ROOT, "NovaStream-v2", "OpenVideoDownloader-Extension")
FIREFOX_EXT_DIR = os.path.join(ROOT, "NovaStream-Firefox", "OpenVideoDownloader-Extension")
DEFAULT_KEY_PATH = os.path.join(ROOT, ".novastream_ext_key.pem")
GECKO_ID = "novastream@downloader.local"


def _encode_varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _pb_bytes(field_number, data):
    tag = (field_number << 3) | 2
    return _encode_varint(tag) + _encode_varint(len(data)) + data


def _crx_id_from_spki(spki_der):
    digest = hashlib.sha256(spki_der).digest()[:16]
    return "".join(chr(ord("a") + ((b >> shift) & 0x0F)) for b in digest for shift in (4, 0))


def _find_openssl():
    found = shutil.which("openssl")
    if found:
        return found
    for cand in (
        r"C:\Program Files\Git\usr\bin\openssl.exe",
        r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
        "/usr/bin/openssl",
    ):
        if os.path.isfile(cand):
            return cand
    return None


def _load_or_create_rsa_backend(key_path):
    """
    RSA-2048 anahtarını yükler/üretir ve (spki_der_bytes, sign_fn) döndürür.
    Desteklenen arka uçlar: pycryptodomex -> cryptography -> openssl CLI.
    """
    try:
        from Cryptodome.Hash import SHA256
        from Cryptodome.PublicKey import RSA
        from Cryptodome.Signature import pkcs1_15

        if os.path.isfile(key_path):
            with open(key_path, "rb") as f:
                key = RSA.import_key(f.read())
        else:
            key = RSA.generate(2048)
            os.makedirs(os.path.dirname(os.path.abspath(key_path)), exist_ok=True)
            with open(key_path, "wb") as f:
                f.write(key.export_key("PEM"))
        spki_der = key.public_key().export_key("DER")

        def sign_fn(payload):
            h = SHA256.new(payload)
            return pkcs1_15.new(key).sign(h)

        return spki_der, sign_fn
    except ImportError:
        pass

    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        if os.path.isfile(key_path):
            with open(key_path, "rb") as f:
                key = serialization.load_pem_private_key(f.read(), password=None)
        else:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            os.makedirs(os.path.dirname(os.path.abspath(key_path)), exist_ok=True)
            with open(key_path, "wb") as f:
                f.write(
                    key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )
        spki_der = key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        def sign_fn(payload):
            return key.sign(payload, padding.PKCS1v15(), hashes.SHA256())

        return spki_der, sign_fn
    except ImportError:
        pass

    openssl = _find_openssl()
    if not openssl:
        raise RuntimeError(
            "CRX3 imzalamak için pycryptodomex, cryptography veya openssl bulunamadı."
        )

    if not os.path.isfile(key_path):
        os.makedirs(os.path.dirname(os.path.abspath(key_path)), exist_ok=True)
        subprocess.run([openssl, "genrsa", "-out", key_path, "2048"], check=True, capture_output=True)

    spki_res = subprocess.run(
        [openssl, "rsa", "-in", key_path, "-pubout", "-outform", "DER"],
        check=True,
        capture_output=True,
    )
    spki_der = spki_res.stdout

    def sign_fn(payload):
        res = subprocess.run(
            [openssl, "dgst", "-sha256", "-sign", key_path],
            input=payload,
            check=True,
            capture_output=True,
        )
        return res.stdout

    return spki_der, sign_fn


def _zip_extension_bytes(src_dir, strip_manifest_key=False, spki_b64=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for name in sorted(files):
                full = os.path.join(root, name)
                rel = os.path.relpath(full, src_dir).replace("\\", "/")
                if rel == "manifest.json" and strip_manifest_key:
                    with open(full, "r", encoding="utf-8") as mf:
                        data = json.load(mf)
                    if data.get("key") and data.get("key") != spki_b64:
                        data.pop("key", None)
                    zf.writestr(rel, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
                else:
                    zf.write(full, rel)
    return buf.getvalue()


def build_crx3(src_dir, out_crx_path, key_path=DEFAULT_KEY_PATH):
    """Spec-uyumlu CRX3 paketi oluşturur ve (out_crx_path, extension_id) döndürür."""
    spki_der, sign_fn = _load_or_create_rsa_backend(key_path)
    spki_b64 = base64.b64encode(spki_der).decode("ascii")
    zip_bytes = _zip_extension_bytes(src_dir, strip_manifest_key=True, spki_b64=spki_b64)

    crx_id_raw = hashlib.sha256(spki_der).digest()[:16]
    signed_header_data = _pb_bytes(1, crx_id_raw)  # SignedData.crx_id

    signed_input = (
        b"CRX3 SignedData\x00"
        + struct.pack("<I", len(signed_header_data))
        + signed_header_data
        + zip_bytes
    )
    signature = sign_fn(signed_input)

    proof = _pb_bytes(1, spki_der) + _pb_bytes(2, signature)
    crx_header = _pb_bytes(2, proof) + _pb_bytes(10000, signed_header_data)

    crx_bytes = b"Cr24" + struct.pack("<II", 3, len(crx_header)) + crx_header + zip_bytes
    os.makedirs(os.path.dirname(os.path.abspath(out_crx_path)), exist_ok=True)
    with open(out_crx_path, "wb") as f:
        f.write(crx_bytes)

    return out_crx_path, _crx_id_from_spki(spki_der)


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def package_all(out_dir, key_path=DEFAULT_KEY_PATH, with_id_name=False):
    sync_extensions.main()
    with open(os.path.join(CHROME_EXT_DIR, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    version = manifest.get("version", "2.5.0")

    os.makedirs(out_dir, exist_ok=True)

    chrome_zip_name = f"NovaStream-Chrome-Edge-Brave-v{version}.zip"
    chrome_crx_name = f"NovaStream-Chrome-Edge-Brave-v{version}.crx"
    firefox_xpi_name = f"NovaStream-Firefox-v{version}.xpi"

    chrome_zip_path = os.path.join(out_dir, chrome_zip_name)
    chrome_crx_path = os.path.join(out_dir, chrome_crx_name)
    firefox_xpi_path = os.path.join(out_dir, firefox_xpi_name)

    with open(chrome_zip_path, "wb") as f:
        f.write(_zip_extension_bytes(CHROME_EXT_DIR, strip_manifest_key=False))

    _, crx_id = build_crx3(CHROME_EXT_DIR, chrome_crx_path, key_path=key_path)

    with open(firefox_xpi_path, "wb") as f:
        f.write(_zip_extension_bytes(FIREFOX_EXT_DIR, strip_manifest_key=False))

    if with_id_name:
        shutil.copy2(firefox_xpi_path, os.path.join(out_dir, f"{GECKO_ID}.xpi"))

    summary = {
        "version": version,
        "crx_extension_id": crx_id,
        "gecko_id": GECKO_ID,
        "files": {
            "chrome_zip": {"filename": chrome_zip_name, "sha256": _sha256_file(chrome_zip_path)},
            "chrome_crx": {"filename": chrome_crx_name, "sha256": _sha256_file(chrome_crx_path)},
            "firefox_xpi": {"filename": firefox_xpi_name, "sha256": _sha256_file(firefox_xpi_path)},
        },
    }
    manifest_out = os.path.join(out_dir, "packages_manifest.json")
    with open(manifest_out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="NovaStream eklentilerini paketler (.zip, .crx, .xpi).")
    parser.add_argument("--out", default=os.path.join(ROOT, "dist", "extensions"), help="Çıktı klasörü")
    parser.add_argument("--key", default=DEFAULT_KEY_PATH, help="CRX3 RSA-2048 PEM anahtar dosyası")
    parser.add_argument("--with-id-name", action="store_true", help="Firefox eklentisini Gecko ID adıyla da kopyala")
    args = parser.parse_args(argv)

    summary = package_all(os.path.abspath(args.out), key_path=os.path.abspath(args.key), with_id_name=args.with_id_name)
    print(f"[OK] Paketler oluşturuldu (v{summary['version']}, CRX ID={summary['crx_extension_id']}): {args.out}")
    for info in summary["files"].values():
        print(f"  - {info['filename']} ({info['sha256'][:12]}...)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

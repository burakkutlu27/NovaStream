#!/usr/bin/env bash
# NovaStream'i KURMADAN, bu klasörden çalıştırırken tarayıcı köprüsünü kaydeder (geliştirici kullanımı).
# Normal kullanımda kurulum sihirbazı (run_installer.sh) kaydı kendisi yapar.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "$SCRIPT_DIR/NovaStream-v2/native_host.sh" "$SCRIPT_DIR/NovaStream-v2/native_host.py"
PY="$SCRIPT_DIR/NovaStream-App/venv/bin/python3"
[ -x "$PY" ] || PY=python3
"$PY" "$SCRIPT_DIR/NovaStream-App/core/native_messaging.py" "$SCRIPT_DIR/NovaStream-v2"

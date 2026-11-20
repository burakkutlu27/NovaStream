#!/usr/bin/env bash
# NovaStream Desktop - Linux Başlatıcı
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "[*] Sanal ortam (venv) oluşturuluyor..."
    python3 -m venv "$SCRIPT_DIR/venv"
    "$VENV_PYTHON" -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
fi
exec "$VENV_PYTHON" "$SCRIPT_DIR/main.py" "$@"

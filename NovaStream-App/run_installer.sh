#!/usr/bin/env bash
# NovaStream Kurulum Başlatıcı (Linux)
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "[*] Python sanal ortamı kuruluyor..."
    python3 -m venv "$SCRIPT_DIR/venv"
fi
"$VENV_PYTHON" -m pip install --quiet -U -r "$SCRIPT_DIR/requirements.txt"
exec "$VENV_PYTHON" "$SCRIPT_DIR/installer.py" "$@"

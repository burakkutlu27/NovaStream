#!/usr/bin/env sh
# NovaStream native host başlatıcısı (Linux): uygulamanın kendi Python ortamını kullanır (yt-dlp, deno orada)
H="$(cd "$(dirname "$0")" && pwd)"
for P in "$H/../venv/bin/python3" "$H/../NovaStream-App/venv/bin/python3"; do
  if [ -x "$P" ]; then exec "$P" -u "$H/native_host.py" "$@"; fi
done
exec python3 -u "$H/native_host.py" "$@"

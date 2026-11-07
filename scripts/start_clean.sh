#!/usr/bin/env bash
# Portu temizle ve Native Knowledge Flow'u yeniden başlat.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

HOST="${AIRA_DEV_HOST:-127.0.0.1}"
PORT="${AIRA_DEV_PORT:-${FLASK_RUN_PORT:-5000}}"

echo "==> Hedef: http://${HOST}:${PORT}"

pids="$(
  ss -tlnp 2>/dev/null | awk -v p=":${PORT}" '
    $0 ~ p {
      if (match($0, /pid=[0-9]+/)) {
        pid = substr($0, RSTART + 4, RLENGTH - 4)
        print pid
      }
    }
  ' | sort -u
)"

if [[ -n "${pids}" ]]; then
  echo "==> Port ${PORT} dolu; süreçler kapatılıyor: ${pids}"
  # shellcheck disable=SC2086
  kill ${pids} 2>/dev/null || true
  sleep 1
  # shellcheck disable=SC2086
  kill -9 ${pids} 2>/dev/null || true
  sleep 0.5
else
  echo "==> Port ${PORT} boş"
fi

echo "==> Uygulama başlıyor…"
exec python app.py

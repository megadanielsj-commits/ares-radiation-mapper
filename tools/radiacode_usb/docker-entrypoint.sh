#!/usr/bin/env bash
set -Eeuo pipefail

mode="${1:-}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "$mode" in
  record)
    session="usb-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    exec python -u /app/tools/radiacode_usb/reader.py \
      --output "/app/resultados/$session" "$@"
    ;;
  dashboard)
    exec python -u /app/tools/radiacode_usb/launch.py \
      --host 0.0.0.0 --no-browser "$@"
    ;;
  *)
    printf 'Modo inválido: %s (use record ou dashboard)\n' "$mode" >&2
    exit 2
    ;;
esac

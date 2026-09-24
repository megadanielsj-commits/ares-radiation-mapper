#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv-radiacode/bin/python ]]; then
  echo 'Execute primeiro: bash 02_preparar_ambiente.sh' >&2
  exit 2
fi
mkdir -p resultados
session_name="usb-$(date -u +%Y%m%dT%H%M%SZ)-$$"
.venv-radiacode/bin/python -u tools/radiacode_usb/reader.py \
  --output "resultados/$session_name" --seconds 60 "$@" \
  2>&1 | tee "resultados/$session_name-terminal.txt"


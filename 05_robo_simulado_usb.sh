#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv-radiacode/bin/python ]]; then
  echo 'Execute primeiro: bash 02_preparar_ambiente.sh' >&2
  exit 2
fi
exec .venv-radiacode/bin/python -u tools/radiacode_usb/launch.py "$@"


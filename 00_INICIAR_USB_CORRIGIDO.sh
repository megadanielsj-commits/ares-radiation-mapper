#!/usr/bin/env bash
set -Eeuo pipefail

package_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd -- "$package_dir"
if [[ ! -x .venv-radiacode/bin/python ]] || \
   ! .venv-radiacode/bin/python -c 'import radiacode, ares_mapper' >/dev/null 2>&1; then
  echo 'Preparando o ambiente USB desta versão...'
  bash 02_preparar_ambiente.sh
fi
exec bash 05_robo_simulado_usb.sh

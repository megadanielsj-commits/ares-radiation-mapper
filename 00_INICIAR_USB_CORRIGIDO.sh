#!/usr/bin/env bash
set -Eeuo pipefail

package_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
app_relative=src/ares_mapper/web/static/app.js

# Reuse the already working USB installation when it is available under HOME.
# Only the dashboard file needs updating; the detector reader stays untouched.
while IFS= read -r -d '' launcher; do
  existing_dir=${launcher%/*}
  if [[ "${existing_dir##*/}" != ARES_Radiacode_USB ||
        "$existing_dir" == "$package_dir" ||
        ! -f "$existing_dir/$app_relative" ]]; then
    continue
  fi
  existing_python="$existing_dir/.venv-radiacode/bin/python"
  if [[ ! -x "$existing_python" ]]; then
    continue
  fi
  if ! "$existing_python" -c 'import radiacode, ares_mapper' >/dev/null 2>&1; then
    continue
  fi
  cp -- "$package_dir/$app_relative" "$existing_dir/$app_relative"
  echo "Painel atualizado na instalação existente: $existing_dir"
  cd -- "$existing_dir"
  exec bash 05_robo_simulado_usb.sh
done < <(find "$HOME" -maxdepth 6 -type f -name 05_robo_simulado_usb.sh -print0 2>/dev/null)

echo 'Instalação anterior não encontrada. Preparando a pasta nova...'
cd -- "$package_dir"
if [[ ! -x .venv-radiacode/bin/python ]] || \
   ! .venv-radiacode/bin/python -c 'import radiacode, ares_mapper' >/dev/null 2>&1; then
  bash 02_preparar_ambiente.sh
fi
exec bash 05_robo_simulado_usb.sh

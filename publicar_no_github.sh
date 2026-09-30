#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
bundle="${1:-$PWD/ARES_Radiacode_ENSAIO_GITHUB.bundle}"
[[ -f "$bundle" ]] || { echo "Não encontrei o bundle: $bundle" >&2; exit 2; }
bundle="$(realpath -- "$bundle")"
folder="$HOME/ares-radiacode-ensaio-github-$(date +%Y%m%d-%H%M%S)"
git clone https://github.com/megadanielsj-commits/ares-radiation-mapper.git "$folder"
cd -- "$folder"
git bundle verify "$bundle"
git fetch "$bundle" \
  feat/radiacode-independent:feat/radiacode-independent \
  feat/radiacode-ceia-test:feat/radiacode-ceia-test
# No force push, no merge into main, no change to ares-wifi.
git push --atomic origin feat/radiacode-independent feat/radiacode-ceia-test
echo 'Código enviado nas duas branches:'
echo 'https://github.com/megadanielsj-commits/ares-radiation-mapper/tree/feat/radiacode-independent'
echo 'https://github.com/megadanielsj-commits/ares-radiation-mapper/tree/feat/radiacode-ceia-test'

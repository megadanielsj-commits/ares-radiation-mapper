#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

# This mode uses the ARES simulator and does not connect to a USB detector.
if [[ ! -x .venv-radiacode/bin/ares-map ]]; then
  python_bin=${ARES_PYTHON:-python3}
  "$python_bin" -c 'import sys; assert (3, 10) <= sys.version_info[:2] < (3, 13), "Use Python 3.10–3.12"'
  "$python_bin" -m venv .venv-radiacode
  .venv-radiacode/bin/python -m pip install -e .
fi

echo 'FONTE SIMULADA + GO2 VIRTUAL | nenhum detector USB será aberto'
echo 'No navegador: configure X, Y e taxa da fonte; clique Iniciar; mova com as setas.'
exec .venv-radiacode/bin/ares-map run \
  --scenario config/scenarios/static_source.yaml \
  --host 127.0.0.1 --port 8000 "$@"

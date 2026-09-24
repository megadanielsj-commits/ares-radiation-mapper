#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
if [[ $(id -u) -eq 0 ]]; then
  echo 'Execute como seu usuário normal: bash 02_preparar_ambiente.sh' >&2
  exit 2
fi
if ! command -v lsusb >/dev/null || ! lsusb -d 0483:f123 | grep -q .; then
  echo 'Primeiro conecte o detector e rode 01_diagnostico_usb.sh.' >&2
  echo 'O ID 0483:f123 ainda não foi confirmado. Envie o diagnóstico.' >&2
  exit 3
fi
if command -v apt-get >/dev/null; then
  sudo apt-get update
  sudo apt-get install -y python3-venv python3-pip libusb-1.0-0 usbutils
else
  echo 'Instale Python 3.10–3.12, venv/pip, libusb e usbutils pelo gerenciador da sua distribuição.'
fi
if [[ -n ${ARES_PYTHON:-} ]]; then
  py="$ARES_PYTHON"
elif /usr/bin/python3 -c 'import sys; assert (3,10) <= sys.version_info[:2] < (3,13)' 2>/dev/null; then
  py=/usr/bin/python3
else
  py=python3
fi
"$py" -c 'import sys; assert (3,10) <= sys.version_info[:2] < (3,13), "ARES requer Python 3.10, 3.11 ou 3.12"'
"$py" -m venv .venv-radiacode
.venv-radiacode/bin/python -m pip install --upgrade pip
.venv-radiacode/bin/python -m pip install -r requirements-usb.txt
.venv-radiacode/bin/python -m pip install -e .
.venv-radiacode/bin/python -m pip check
mkdir -p resultados
.venv-radiacode/bin/python -m pip freeze > resultados/versoes-instaladas.txt
.venv-radiacode/bin/python -c 'from radiacode import RadiaCode; import ares_mapper; print("Ambiente instalado. Próximo: bash 03_permissao_usb.sh")'


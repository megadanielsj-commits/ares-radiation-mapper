#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
if [[ $(id -u) -eq 0 ]]; then
  echo 'Execute este script como seu usuário normal, sem sudo na chamada.' >&2
  exit 2
fi
if ! lsusb -d 0483:f123 | grep -q .; then
  echo 'ID USB 0483:f123 não encontrado. Execute o diagnóstico.' >&2
  exit 3
fi
usb_user=$(id -un)
if [[ ! $usb_user =~ ^[a-zA-Z0-9_.-]+$ ]]; then
  echo 'Nome de usuário não suportado pela regra automática.' >&2
  exit 2
fi
usb_rule=$(mktemp)
trap 'rm -f "$usb_rule"' EXIT
printf 'SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="f123", OWNER="%s", MODE="0600", TAG+="uaccess"\n' "$usb_user" > "$usb_rule"
sudo install -m 0644 "$usb_rule" /etc/udev/rules.d/70-ares-radiacode-usb.rules
sudo udevadm control --reload-rules
echo 'Permissão configurada apenas para este dispositivo e usuário.'
echo 'DESCONECTE e RECONECTE o cabo USB. Depois: bash 04_teste_usb.sh'


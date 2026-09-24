#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p resultados
report="resultados/diagnostico-$(date -u +%Y%m%dT%H%M%SZ).txt"
{
  echo 'ARES — diagnóstico USB Radiacode (somente leitura)'
  date -u --iso-8601=seconds
  cat /etc/os-release
  uname -srmo
  python3 --version
  id
  echo 'Dispositivos USB:'
  if command -v lsusb >/dev/null; then
    lsusb
    lsusb -t
    echo 'Identificador esperado pela biblioteca (0483:f123):'
    lsusb -d 0483:f123 || true
  else
    echo 'lsusb ausente. Em Ubuntu/Debian: sudo apt install usbutils'
  fi
  echo 'Interfaces seriais existentes (não exigidas pelo Radiacode):'
  ls -l /dev/ttyUSB* /dev/ttyACM* /dev/serial/by-id/* 2>/dev/null || true
  echo 'Eventos recentes do kernel:'
  dmesg --ctime 2>&1 | tail -n 45
  echo 'Fim do diagnóstico.'
} 2>&1 | tee "$report"
echo "Relatório: $report"
echo 'Se o ID 0483:f123 não apareceu, envie o relatório antes de prosseguir.'


#!/usr/bin/env bash
set -Eeuo pipefail
ARES_PACKAGE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ARES_CONSOLE_BUNDLE="$ARES_PACKAGE_ROOT/ARES_Console_Operacao_GITHUB.bundle"
test -f "$ARES_CONSOLE_BUNDLE" || { echo 'Bundle não encontrado na pasta do pacote.' >&2; exit 2; }
ARES_GITHUB_CHECKOUT="$HOME/ares-console-github-$(date +%Y%m%d-%H%M%S)"
git clone https://github.com/megadanielsj-commits/ares-radiation-mapper.git "$ARES_GITHUB_CHECKOUT"
cd "$ARES_GITHUB_CHECKOUT"
git fetch "$ARES_CONSOLE_BUNDLE" feat/operator-console:feat/operator-console
git switch feat/operator-console
git push -u origin feat/operator-console
echo 'Console publicado na branch feat/operator-console.'
echo 'https://github.com/megadanielsj-commits/ares-radiation-mapper/tree/feat/operator-console'

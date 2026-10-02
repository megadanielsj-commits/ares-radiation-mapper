#!/usr/bin/env bash
set -Eeuo pipefail
ARES_PACKAGE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ARES_CONSOLE_BUNDLE="$ARES_PACKAGE_ROOT/ARES_Console_Oficial_1.0.2_GITHUB.bundle"
test -f "$ARES_CONSOLE_BUNDLE" || { echo 'Bundle não encontrado na pasta do pacote.' >&2; exit 2; }
ARES_GITHUB_CHECKOUT="$HOME/ares-console-github-$(date +%Y%m%d-%H%M%S)"
git clone https://github.com/megadanielsj-commits/ares-radiation-mapper.git "$ARES_GITHUB_CHECKOUT"
cd "$ARES_GITHUB_CHECKOUT"
ARES_RELEASE_BRANCH='release/ares-console-1.0.2'
git bundle verify "$ARES_CONSOLE_BUNDLE"
git fetch "$ARES_CONSOLE_BUNDLE" "$ARES_RELEASE_BRANCH:$ARES_RELEASE_BRANCH"
git switch "$ARES_RELEASE_BRANCH"
git push -u origin "$ARES_RELEASE_BRANCH"
echo 'ARES Console 1.0.2 publicado na branch release/ares-console-1.0.2.'
echo 'https://github.com/megadanielsj-commits/ares-radiation-mapper/tree/release/ares-console-1.0.2'
echo 'Para revisão e inclusão na branch principal, abra o pull request:'
echo 'https://github.com/megadanielsj-commits/ares-radiation-mapper/compare/main...release/ares-console-1.0.2?expand=1'

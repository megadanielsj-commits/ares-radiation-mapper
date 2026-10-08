#!/usr/bin/env bash
set -Eeuo pipefail
if [[ $# -ne 0 ]]; then
  echo 'Uso: bash PUBLICAR_CONSOLE_GITHUB.sh' >&2
  exit 2
fi
ARES_PACKAGE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ARES_CONSOLE_BUNDLE="$ARES_PACKAGE_ROOT/ARES_Console_Oficial_1.0.2_GITHUB.bundle"
test -f "$ARES_CONSOLE_BUNDLE" || { echo 'Bundle não encontrado na pasta do pacote.' >&2; exit 2; }
ARES_RELEASE_BRANCH='release/ares-console-1.0.2'
ARES_GITHUB_CHECKOUT="$HOME/ares-console-gradiente-github-$(date +%Y%m%d-%H%M%S)-$$"
git clone --branch "$ARES_RELEASE_BRANCH" --single-branch \
  https://github.com/megadanielsj-commits/ares-radiation-mapper.git "$ARES_GITHUB_CHECKOUT"
cd "$ARES_GITHUB_CHECKOUT"
git bundle verify "$ARES_CONSOLE_BUNDLE"
git fetch "$ARES_CONSOLE_BUNDLE" "$ARES_RELEASE_BRANCH"
git merge --ff-only FETCH_HEAD
git push -u origin "HEAD:refs/heads/$ARES_RELEASE_BRANCH"
echo "Revisão publicada: $(git rev-parse HEAD)"
echo 'Versão com edição do gradiente na branch release/ares-console-1.0.2.'
echo 'https://github.com/megadanielsj-commits/ares-radiation-mapper/tree/release/ares-console-1.0.2'
echo 'Confira o resultado do GitHub Actions antes de usar a revisão.'

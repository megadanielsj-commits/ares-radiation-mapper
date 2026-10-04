#!/usr/bin/env bash
set -Eeuo pipefail
ARES_ARCHIVE_OLD=false
case "${1:-}" in
  '') ;;
  --arquivar-antigas) ARES_ARCHIVE_OLD=true ;;
  *) echo 'Uso: bash PUBLICAR_CONSOLE_GITHUB.sh [--arquivar-antigas]' >&2; exit 2 ;;
esac
ARES_PACKAGE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ARES_CONSOLE_BUNDLE="$ARES_PACKAGE_ROOT/ARES_Console_Oficial_1.0.2_GITHUB.bundle"
test -f "$ARES_CONSOLE_BUNDLE" || { echo 'Bundle não encontrado na pasta do pacote.' >&2; exit 2; }
ARES_GITHUB_CHECKOUT="$HOME/ares-console-github-$(date +%Y%m%d-%H%M%S)-$$"
git clone https://github.com/megadanielsj-commits/ares-radiation-mapper.git "$ARES_GITHUB_CHECKOUT"
cd "$ARES_GITHUB_CHECKOUT"
ARES_RELEASE_BRANCH='release/ares-console-1.0.2'
git bundle verify "$ARES_CONSOLE_BUNDLE"
git fetch "$ARES_CONSOLE_BUNDLE" "$ARES_RELEASE_BRANCH:$ARES_RELEASE_BRANCH"
git switch "$ARES_RELEASE_BRANCH"
ARES_PUSH_REFS=("$ARES_RELEASE_BRANCH")
ARES_PUSH_LEASES=()
if $ARES_ARCHIVE_OLD; then
  for ARES_OLD_BRANCH in feat/radiacode-independent feat/radiacode-go2-wifi; do
    if ! ARES_OLD_SHA="$(git rev-parse --verify "refs/remotes/origin/$ARES_OLD_BRANCH" 2>/dev/null)"; then
      echo "Branch já ausente: $ARES_OLD_BRANCH"
      continue
    fi
    ARES_ARCHIVE_TAG="archive/${ARES_OLD_BRANCH#feat/}-20261004"
    ARES_EXISTING_TAG="$(git ls-remote --tags origin "refs/tags/$ARES_ARCHIVE_TAG" | awk '{print $1}')"
    if test -n "$ARES_EXISTING_TAG" && test "$ARES_EXISTING_TAG" != "$ARES_OLD_SHA"; then
      echo "Tag de arquivo já aponta para outra revisão: $ARES_ARCHIVE_TAG. Nenhuma publicação foi feita." >&2
      exit 2
    fi
    ARES_PUSH_REFS+=("$ARES_OLD_SHA:refs/tags/$ARES_ARCHIVE_TAG" ":refs/heads/$ARES_OLD_BRANCH")
    ARES_PUSH_LEASES+=("--force-with-lease=refs/heads/$ARES_OLD_BRANCH:$ARES_OLD_SHA")
    echo "Arquivar histórico em $ARES_ARCHIVE_TAG e retirar a branch $ARES_OLD_BRANCH"
  done
fi
# The release update is a normal fast-forward. Leases guard only old branch
# deletion; atomic push keeps their history tags and deletion in one transaction.
git push --atomic "${ARES_PUSH_LEASES[@]}" -u origin "${ARES_PUSH_REFS[@]}"
echo 'ARES Console 1.0.2 consolidado na branch release/ares-console-1.0.2.'
echo 'main e ares-wifi foram preservadas. Os registros de campo não foram enviados.'
echo 'https://github.com/megadanielsj-commits/ares-radiation-mapper/tree/release/ares-console-1.0.2'
echo 'Confira Actions e abra a revisão para inclusão na branch principal:'
echo 'https://github.com/megadanielsj-commits/ares-radiation-mapper/compare/main...release/ares-console-1.0.2?expand=1'

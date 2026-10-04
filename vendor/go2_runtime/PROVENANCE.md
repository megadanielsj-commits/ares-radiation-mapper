# Runtime de entradas Go2/Radiacode

O núcleo deriva do trabalho do Werik na branch `ares-wifi`, revisão pública
`84f9148d1da6b7b3aa84b177b09a30d2631ecb8f`:
https://github.com/megadanielsj-commits/ares-radiation-mapper/tree/84f9148d1da6b7b3aa84b177b09a30d2631ecb8f

O driver Go2, `_compat`, interfaces de robô/radiação, sincronizador, teleoperação
com watchdog e cliente FS-5000 são idênticos àquela revisão. A adaptação adiciona
`ClienteRadiacode`, taxa/dose opcionais, metadados e exportações. A camada do
console publica o mapa aprovado sobre o mesmo fluxo de entradas/sincronização.
Não se afirma que todo o orquestrador/modelo/persistência seja idêntico ao
original sem Radiacode: as diferenças aditivas estão na auditoria.

A árvore completa usada pelo console foi publicada em `8c9a4280ebcf085ddf7cde3b2809750968bb10d2`,
no caminho `vendor/go2_runtime/src/ares`, e é a referência reproduzível da cópia:
https://github.com/megadanielsj-commits/ares-radiation-mapper/tree/8c9a4280ebcf085ddf7cde3b2809750968bb10d2/vendor/go2_runtime/src/ares

A preparação anterior mencionava a revisão local `4048f7c`; ela não é uma
referência recuperável no clone atual do GitHub. Esta consolidação usa a árvore
publicada acima e conserva o runtime byte a byte. Os hashes do núcleo são
conferidos junto ao mapa por `tools/operator_console/check_map_lock.py`.

A operação está em `LEIA_PRIMEIRO_CONSOLE.md`; a comparação e as condições do
ensaio estão em `CHECKUP_20261004.md` e `ROTEIRO_ENSAIO_GO2.md`.

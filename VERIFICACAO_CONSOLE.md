# Verificação do console ARES — 02/10/2026

Versão candidata para validação da interface unificada no computador de operação.

- 116 testes Python da base e do console passaram, sem falhas ou testes ignorados.
- Depois dos ajustes finais de prontidão USB, os 14 testes do console e da
  simulação clássica foram repetidos e passaram.
- 8 testes JavaScript passaram, incluindo cores, coordenadas do raster, unidade
  CPS e separação entre contagens e dose integrada.
- 56 arquivos do mapa original e do runtime de entradas têm hashes conferidos.
- `src/ares_mapper` e o cenário da simulação original não têm diferenças em
  relação à revisão v4 `f606248`.
- O runtime `vendor/go2_runtime/src/ares` coincide com a revisão Go2 `4048f7c`;
  o serviço USB coincide com a preparação independente `8321641`.
- Testes exercitam os quatro modos, troca após salvar, aquisição com contagens
  independentes da dose, perda de USB, controle de uma única sessão, watchdog,
  parada, WebSocket, exportação e odometria inicial diferente de 0,0.
- Imports dos drivers Radiacode e Go2 foram conferidos, usando a compatibilidade
  original do driver Go2 para dependências opcionais de áudio.

As entradas reais dos testes automatizados são substitutos controlados dos
contratos de hardware. Eles não validam rádio Wi-Fi, USB físico, unidade de dose,
offset do suporte, atraso instrumental ou movimentação do Go2. O ensaio com
hardware continua necessário.

O Dockerfile e o workflow de construção e inicialização foram preparados. Não
há Docker Engine disponível neste ambiente para executar a imagem; a primeira
construção e o teste USB precisam ocorrer no computador de operação.

A inspeção visual completa no navegador não pôde ser realizada neste ambiente,
pois o navegador remoto não alcança o servidor local. O HTML, os recursos, os
contratos do renderer e a preservação do desenho do mapa foram verificados em
testes. A nova disposição dos painéis precisa da confirmação do operador.

Essa alteração foi criada em `feat/operator-console`. Não foi enviada ao GitHub
e não substituiu as branches usadas na preparação do ensaio físico.

# Verificação do console ARES v3 — 02/10/2026

Esta revisão aplica somente os ajustes de interface solicitados e a correção da
estimativa ao permanecer sobre a fonte. A v2 foi confirmada pelo operador com
simulação completa e Radiacode real conectado ao USB com robô simulado.

- 116 testes Python existentes passaram; quatro casos adicionais exercitam
  permanência sobre a fonte e na posição 7,66 / 5,69 m, com leituras exatas e
  ruído de 2%. Outros dois casos verificam a distinção entre picos próximos e
  locais realmente distintos, totalizando 122 casos aprovados.
- Os casos de regressão percorrem 118 posições e permanecem por mais 550
  leituras. Conferem a estabilidade do campo, a localização estimada, a retenção
  da geometria, a posição do máximo do mapa, a quantidade de amostras, a integral
  da dose e a retomada do movimento.
- Dez testes JavaScript passaram, incluindo paleta, posicionamento do raster,
  unidade CPS, contagem da missão e duas casas decimais sem arredondar os dados.
- A correção alcança somente `inference/identifiability.py` e
  `inference/particle_filter.py`: o histórico de geometria registra posições
  independentes e a injeção de partículas do prior ocorre com deslocamento,
  sem suspender as atualizações de probabilidade durante a permanência.
  O diagnóstico de múltiplos picos exige separação em metros de pelo menos
  uma célula de observação; pequenas oscilações dentro da mesma localização
  não revogam o campo. Hipóteses em locais distintos continuam sendo rejeitadas
  como ambíguas.
- Dos 56 arquivos protegidos, 54 mantêm os hashes da v2. Os outros dois são
  explicitamente registrados como correção autorizada no `map.lock.json`, com
  seus hashes de referência e atualizados. A verificação continua obrigatória
  na construção da imagem Docker.
- A seção HTML do mapa e o JavaScript original permanecem idênticos à v4.
  Desenho, interpolação, transformação numérica de cores e escala não foram
  substituídos. Os wrappers mudam apenas a apresentação das unidades e rótulos.
- O runtime do Werik, a aquisição USB independente, o sincronizador, a persistência
  e o controle do Go2 não foram modificados.
- No Chrome 145, o painel ficou à esquerda em 1920×1080, 1536×864, 1366×768 e
  1024×768. Também foi verificada a tela de 390×844. Não houve overflow horizontal
  da página ou contagem de medições fora da seção. O canvas em Full HD continua
  com 1542×908 pixels.
- Foram exercitados no navegador: menu superior de modos, configuração da fonte
  pela seção recolhível, duração, cancelamento, início, bloqueio das entradas
  durante a missão, movimento por teclado, ampliação/restauração, parada e exportação.
- As três combinações mistas/reais foram exercitadas no navegador com substitutos
  dos contratos de hardware. A fonte aparece somente com radiação simulada.
  Não houve erros JavaScript; a dose real continua separada das contagens CPS.
- `ruff check src tests` passou. A tipagem dos dois módulos alterados passou.
  A verificação global `mypy src` reporta 49 erros no arquivo de terceiro
  `adapters/fs5000/vendor/fs5000.py`; a mesma verificação da v2, sem alterações,
  reporta exatamente esses 49 erros nesse arquivo. Esse código ficou preservado
  nesta revisão, que não corrige nem declara aprovado esse check global.
- A imagem recebe o tag `20261002-r3`. Não há Docker Engine neste ambiente:
  a imagem será construída no computador de operação pelo iniciador.

Os testes com substitutos não validam o USB físico, rádio Wi-Fi, unidade de dose,
offset, latência ou movimentação do Go2. A v3 foi verificada com o servidor Python
e os recursos que compõem a imagem; o novo teste físico é realizado pelo operador.

A revisão fica em `feat/operator-console`, no bundle incluído no ZIP. Não foi
enviada ao GitHub nem substitui automaticamente as branches do ensaio físico.

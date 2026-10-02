# Verificação do console ARES v2 — 02/10/2026

Revisão visual do console unificado. O operador confirmou a simulação completa
e o modo Radiacode USB real com robô simulado na v1; a v2 preserva esses pipelines.

- 116 testes Python da base e do console passaram, sem falhas ou testes ignorados.
- 9 testes JavaScript passaram, incluindo escala de cores, coordenadas do raster,
  unidade CPS, separação entre contagens e dose, e o contador de amostras da missão.
- Os 56 arquivos protegidos têm os mesmos hashes da v1. A seção HTML do mapa
  continua idêntica à v4. O renderer original não foi editado nem substituído.
- `src/ares_mapper` e o cenário da simulação original não têm diferenças em
  relação à revisão v4 `f606248`.
- O runtime `vendor/go2_runtime/src/ares` coincide com a revisão Go2 `4048f7c`;
  o serviço USB coincide com a preparação independente `8321641`.
- O servidor do console e seus pipelines de aquisição, sincronização, persistência
  e controle não foram alterados nesta revisão.
- A contagem exibida não depende do limite de 5.000 pontos do desenho e não
  retrocede ao receber uma atualização anterior da mesma missão. Reinicia em
  uma nova missão e ignora amostras de uma missão anterior.
- Chrome 145 foi usado para inspeção de screenshots em 1920×1080, 1536×864,
  1366×768, 1024×768 e 390×844. A contagem fica dentro da seção de telemetria,
  sem corte ou sobreposição, e não há overflow horizontal da página.
- A área do canvas em Full HD tem 1542×908 pixels. A ampliação recolhe a coluna
  lateral, mantendo a proporção espacial pelo renderer original.
- Foram exercitados no navegador: preparar missão, cancelar ajustes não aplicados,
  iniciar, mover pelo teclado, ampliar/restaurar, interromper e encerrar a missão.
- As três combinações mistas/reais foram exercitadas também no navegador, com
  substitutos dos contratos de hardware. Não houve erros JavaScript.
- A logo original foi preservada; inversão e composição por CSS exibem o símbolo
  branco sobre o fundo escuro. Nenhum gerador de imagem recriou a marca.
- A imagem Docker recebe o tag `20261002-r2`, para não reutilizar o layout v1.

Os substitutos dos testes não validam rádio Wi-Fi, USB físico, unidade de dose,
offset do suporte, atraso instrumental ou movimentação do Go2. O ensaio com
hardware continua necessário. O relato de USB real do operador refere-se à v1.

O Dockerfile e o workflow de construção e inicialização foram preservados. Não
há Docker Engine disponível neste ambiente; a imagem r2 deve ser construída
no computador de operação pelo iniciador. O layout foi testado com o mesmo
servidor Python e os recursos que compõem essa imagem.

Essa alteração está em `feat/operator-console`. Não foi enviada ao GitHub
e não substituiu as branches usadas na preparação do ensaio físico.

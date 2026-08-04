# Changelog

## 0.4.10 — 2026-08-04

- corrige a falha imediata do modo `simulation` dentro da imagem Docker em
  Python 3.10;
- captura corretamente os tempos de espera normais do `asyncio` em todas as
  versões de Python suportadas;
- testa o projeto no GitHub Actions com Python 3.10 e 3.12;
- adiciona um teste real do contêiner que inicia a missão e confirma que ela
  permanece em estado `RUNNING`.

## 0.4.9 — 2026-08-04

- reduz a operação pública a dois modos explícitos: `simulation` e `hardware`;
- exige Go2 e FS-5000 juntos no modo real e rejeita configurações parciais;
- remove o perfil distribuído de FS-5000 real com pose simulada;
- adiciona `ares-map start` com seleção de modo e configuração por variáveis de
  ambiente ou opções de linha de comando;
- substitui o Dockerfile mínimo por imagens separadas de simulação e hardware;
- instala no contêiner real o SDK2 Python oficial da Unitree em revisão fixa;
- adiciona Docker Compose com rede do host para DDS e acesso à porta USB;
- adiciona o iniciador `./ares`, que valida Docker, interface do Go2 e porta do
  FS-5000 antes de executar;
- adiciona `.env.example`, `.dockerignore`, licença MIT e integração contínua
  para testes, lint, tipagem e construção da imagem de simulação;
- reorganiza o README para uso direto no GitHub e execução reproduzível.

## 0.4.8 — 2026-07-30

- formaliza as dimensões oficiais do Unitree Go2 em pé: 0,70 × 0,31 × 0,40 m;
- mantém a pegada física de 0,70 × 0,31 m no sistema de coordenadas do mapa;
- adiciona um avatar proporcional com comprimento visual mínimo de 30 px quando
  a extensão do mapa tornaria a pegada real pequena demais para acompanhar;
- desenha a pegada exata dentro do avatar ampliado, separando precisão espacial
  de legibilidade operacional;
- suaviza apenas a animação da pose, inclusive na passagem de +π para −π, sem
  alterar a pose bruta usada na sincronização, reconstrução ou armazenamento;
- adiciona `fs5000_manual.example.yaml`, perfil de laboratório de 10 × 8 m com
  FS-5000 real, pose manual e sem ruído artificial de odometria;
- preserva integralmente a aquisição do FS-5000, o estimador probabilístico, a
  escala cromática e os limites da V0.4.7.

## 0.4.7 — 2026-07-30

- restaura a paleta contínua da V0.4.4: azul-escuro, azul, verde, amarelo,
  laranja e vermelho;
- volta a dimensionar as cores pela faixa logarítmica da missão, mantendo-a
  fixa após o início para não recolorir medições anteriores;
- reserva o vermelho para a região relativamente mais intensa, evitando que
  toda taxa acima de 25 µSv/h apareça na mesma família cromática;
- mantém os níveis do público e do IOE como referências informativas no cursor,
  separados da cor usada para representar a geometria do campo;
- restaura uma barra compacta de taxa estimada e devolve espaço útil ao mapa;
- preserva a entrada em mSv/h, a fonte padrão de 10 mSv/h, o teto de 10 Sv/h e
  todas as correções físicas e probabilísticas da V0.4.6.

## 0.4.6 — 2026-07-30

- incorpora à escala os níveis de dose efetiva da CNEN NN 3.01 para indivíduo
  do público e indivíduo ocupacionalmente exposto;
- mantém o verde em 0,114155 µSv/h, equivalente a 1 mSv/ano para o público em
  exposição contínua durante 8.760 h;
- adota 2.000 h/ano para converter os marcos anuais do IOE em referências de
  taxa: registro em 0,5 µSv/h, investigação em 3 µSv/h, limite em 10 µSv/h e
  teto de 50 mSv em um ano em 25 µSv/h;
- aquece progressivamente as cores de verde para amarelo, laranja e vermelho a
  cada marco regulatório;
- mantém toda a faixa acima de 25 µSv/h na família vermelha, com gradação
  logarítmica até 10 Sv/h para preservar a geometria de fontes fortes;
- identifica no cursor a faixa regulatória correspondente a cada ponto;
- aplica os mesmos marcos, cores e rótulos ao Canvas e às exportações HTML/PNG;
- preserva a entrada em mSv/h, o padrão de 10 mSv/h, o máximo de 10 Sv/h e toda
  a reconstrução validada na V0.4.5.

## 0.4.5 — 2026-07-30

- muda a entrada operacional da fonte para mSv/h, com valor inicial de
  10 mSv/h a 1 m;
- define 10 Sv/h (10.000 mSv/h) como intensidade máxima configurável a 1 m;
- adota uma escala cromática radiológica absoluta, idêntica entre missões;
- posiciona o verde exatamente em 0,114155 µSv/h, taxa média contínua
  equivalente a 1 mSv em 365 dias;
- comprime toda a faixa abaixo da referência pública em 6% da barra e distribui
  as taxas superiores logaritmicamente entre verde, amarelo, laranja e vermelho;
- calcula as cores sobre a contribuição acima do fundo, pois o limite anual do
  público exclui a radiação natural normal do local;
- mostra taxas e doses com unidade automática em µSv, mSv ou Sv, mantendo a
  entrada da fonte em mSv/h;
- aplica a mesma escala aos mapas Canvas e às exportações HTML/PNG;
- preserva integralmente a reconstrução, a compensação temporal e os controles
  validados na V0.4.4.

## 0.4.4 — 2026-07-29

- amplia a entrada da simulação até 100 Sv/h
  (100.000.000 µSv/h a 1 m) e ajusta automaticamente a faixa inferencial;
- associa cada leitura à posição temporal efetiva da resposta de primeira ordem
  do detector, removendo a defasagem espacial durante o movimento;
- propaga a dispersão temporal da resposta na verossimilhança sem transformar
  essa incerteza em células maiores no mapa;
- incorpora incerteza proporcional à taxa observada na fusão espacial;
- reduz a correção residual máxima de ±50% para ±20% e aplica ponderação pela
  confiança estatística da leitura;
- substitui a troca instantânea pelo campo global por uma transição de seis
  medições, com suavização determinística dos parâmetros;
- conserva temporariamente o último campo estável e o retira gradualmente quando
  a identificabilidade se perde, evitando piscar entre mapa local e global;
- usa escala logarítmica fixa no Canvas e nas exportações HTML/PNG;
- valida o percurso do vídeo com erro final de 0,145 m, nenhum pico remoto,
  p95 máximo de alteração visual de 7,1% da escala e renderização p95 abaixo de
  250 ms;
- valida numericamente o detector até 1.600.000.000 µSv/h no ponto de máxima
  resposta do cenário de 100 Sv/h.

## 0.4.3 — 2026-07-29

- substitui a média espacial de campos \(1/r^2\) por um campo central robusto e
  coerente, impedindo que partículas exploratórias criem fontes fantasmas;
- usa o mesmo conjunto posterior determinístico em todas as células e mantém o
  mapa idêntico quando nenhuma nova medição chega;
- exige cinco atualizações estáveis para liberar o campo global e o remove
  imediatamente se o posterior voltar a ser não identificável;
- limita a correção residual local a ±50% do campo físico, eliminando cavidades
  escuras e novos máximos artificiais;
- evita construir a quadtree global enquanto somente o gradiente medido está
  visível;
- recalibra o refinamento do cenário manual para manter p95 de renderização em
  aproximadamente 206 ms no percurso de 100.000 µSv/h;
- valida o percurso observado no vídeo com fonte em \((5,5)\): 28 mapas globais,
  todos com máximo em \((5,5)\), sem picos remotos.

## 0.4.2 — 2026-07-29

- reduz a célula de observação de 1,0 m para 0,25 m;
- reduz o suporte de cada medição de 2,5 m para 0,75 m;
- aplica taper compacto, fazendo a influência chegar suavemente a zero;
- impede que células grandes da quadtree ampliem a correção residual até 6 m;
- preserva áreas antigas quando uma nova leitura ocorre fora do suporte local;
- fixa a escala de cores durante a missão para não recolorir o histórico;
- adapta a faixa de intensidade do filtro à ordem de grandeza informada na
  simulação, inclusive para fontes acima de 1.000 µSv/h a 1 m.

## 0.4.1 — 2026-07-29

- redesenha o painel em duas colunas para preencher adequadamente 1920 × 1080;
- amplia campos, botões, telemetria e textos operacionais;
- substitui Plotly no navegador por um mapa Canvas leve e responsivo;
- incorpora CSS e JavaScript ao HTML servido e desabilita o cache da página;
- impede a combinação de HTML novo com recursos estáticos antigos;
- mantém fonte, Go2, caminho, escala radiológica, coordenadas e gradiente visíveis
  desde a abertura do painel.

## 0.4.0 — 2026-07-29

- Interface reduzida a coordenadas da fonte, taxa a 1 m, botão de início, taxa
  atual, dose acumulada, número de medições e mapa.
- Remoção de camadas, toggles, controles redundantes e painéis de diagnóstico da
  tela operacional.
- Configuração atômica da fonte, substituindo keyframes antigos e garantindo que
  as coordenadas informadas sejam a verdade usada pelo simulador.
- Fonte configurada sempre marcada no mapa para verificação visual.
- Simulação manual em `dose_direct`, sem zeros e saltos causados pela
  extrapolação de um único segundo de contagens.
- Gradiente local limitado aos dados antes da identificabilidade; áreas sem
  suporte permanecem desconhecidas.
- Modelo físico global liberado somente após três atualizações estáveis.
- Dose acumulada exibida pela integral de todas as janelas percorridas.
- Layout fixo em uma viewport de 1920 × 1080 com zoom de 100%.

## 0.3.0 — 2026-07-29

- Fusão de cada leitura com toda a trajetória observada do detector na janela.
- Hipóteses separadas de fundo e fonte com filtro de partículas regularizado.
- Verossimilhanças Student-t, Poisson e negativo-binomial sem duplicar canais.
- Regiões de credibilidade, probabilidade de existência e diagnóstico de
  identificabilidade.
- Quadtree persistente, mapa posterior, incerteza e correção residual local.
- Camadas independentes de cobertura, exposição e probabilidade de fonte.
- Dose acumulada usada para auditoria e recuperação fraca de pacotes ausentes.
- Modos simulados, reais, mistos e replay sob os mesmos contratos.
- Adaptadores funcionais opcionais para FS-5000 serial e Unitree SDK2.
- Validação Monte Carlo, métricas de desempenho e exportações probabilísticas.

## 0.2.0 — 2026-07-29

- Interface compacta para 1920 × 1080 sem reduzir o zoom do navegador.
- Go2 representado em escala por um retângulo de 0,70 × 0,31 m.
- Controle manual contínuo pelas setas, com pose simulada a 20 Hz.
- Posicionamento da fonte diretamente no mapa e taxa configurável em µSv/h a 1 m.
- FS-5000 completo simulado a 1 Hz: DR, D, CPS, CPM, AVG, DT, S e W.
- Medições integradas ao longo do trecho percorrido durante a janela de um segundo.
- Localização robusta de uma fonte pontual e fusão híbrida entre modelo físico e
  correções residuais.
- Pesos por contagem, integração, permanência, incerteza de pose, sincronização e
  coerência da dose acumulada.
- Contrato ampliado para os campos oficiais de `SportModeState` e IMU do Go2.

## 0.1.0 — 2026-07-28

- Primeira versão totalmente simulada do ARES Radiation Mapper.
- Simulação de trajetória, odometria, campo radiológico e detector.
- Sincronização temporal, transformação extrínseca e mapas IDW com máscara de cobertura.
- Dashboard local, API, WebSocket, replay, SQLite e exportações.
- Contratos e stubs para FS-5000 e Unitree Go2.

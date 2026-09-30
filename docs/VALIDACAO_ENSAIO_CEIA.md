# Validação da preparação Radiacode + CEIA — 30/09/2026

## Resultado

O código está preparado para testar Radiacode USB com robô simulado e depois
com o Go2 físico na arquitetura do Werik. A integração em software passou;
a combinação dos dois equipamentos físicos ainda requer o ensaio de bancada.
As imagens Docker foram definidas, mas não foram construídas neste ambiente,
que não disponibiliza Docker Engine. O comando `bash ensaio preparar` faz
essa construção no computador do ensaio. Há workflows para verificar as
imagens após a publicação no GitHub.

## Revisões consultadas

- `ares-wifi`: `84f9148d1da6b7b3aa84b177b09a30d2631ecb8f`, conferida no remoto.
- Radiacode publicado antes desta preparação:
  `3d26201887b8b85fa333fe9aabed7fdfdc5eee47`, conferido no remoto.
- ZIPs fornecidos dos quickstarts `FS_5000_quickstart` e `go2_wifi_quickstart`.
  Esses projetos privados foram analisados a partir dos arquivos recebidos;
  não foi afirmada a existência de novas revisões privadas.

## O que foi preservado

Os arquivos `src/ares/sincronizacao.py`, `src/ares/teleop.py`,
`src/ares/robo/go2.py` e `src/ares/radiacao/fs5000.py` na adaptação CEIA são
idênticos aos do commit `84f9148`. A aplicação anterior em `src/ares_mapper`
permanece idêntica à revisão `3d26201`. Não há merge automático na branch
`ares-wifi` nem na `main`.

## Testes executados

| Verificação | Resultado |
|---|---|
| Quickstart FS-5000 recebido, sem alterações | 111 passaram |
| Testes Python do projeto anterior, incluindo leitor, painel e serviço novo | 95 passaram |
| Teste JavaScript de desenho do Go2 no painel anterior | 1 passou |
| Testes da estrutura CEIA, incluindo seleção Radiacode, aquisição sem calibração e retomada WS | 206 passaram |
| Lint do projeto anterior (`ruff check src tests`) | Passou |
| Tipos do projeto anterior (`mypy src`) | Passou, 76 arquivos |
| Sintaxe dos scripts e JavaScript CEIA | Passou |
| Leitura das definições Compose com parser YAML | Passou; não equivale a executar Docker |
| Reprodução completa: JSONL → WS → cliente CEIA → sincronizador → missão → CSV/JSON | Passou |

A reprodução completa usou trechos reais de RawData com timestamps novos e
posição simulada. Na última execução foram gravadas 8 amostras posicionadas, 35 poses e 8 leituras,
com movimento por teleop simulado, retomada em nova sessão e exportação
automática dos arquivos também conferida. O relatório
identificou `hardware_test=false` e `robot_physical_test=false`.

Também foram testados dados repetidos, registros incompletos, dados antigos,
recebimento em lote, fila de assinante lento, timeout do leitor, desconexão,
reinício do processo USB e encerramento do serviço. Testes injetados não são
considerados validação de USB físico.

## Conferência dos dados reais já enviados

| Arquivo recebido | RawData | Contagens de 1 s reconstruídas | Registros brutos descartados por continuidade/formato |
|---|---:|---:|---:|
| `Radiacode_1h_20260929.tar.gz` | 7.200 | 3.600 | 0 |
| `Radiacode_CEIA_teste.tar.gz` | 264 | 132 | 0 |

Esses arquivos demonstram aquisição real prévia e permitem conferir a
interpretação dos registros. Não demonstram posição do Go2 físico nem a
conversão absoluta de dose. O CPS fracionário de RealTimeData é mantido no
registro original; a integração CEIA recebe a contagem inteira de RawData.

## Condições para declarar sucesso no laboratório

1. As imagens devem ser construídas sem erro antes da conexão ao Wi-Fi do Go2.
2. USB real + robô simulado deve salvar uma missão com amostras e exportação.
3. No Go2 físico, ambos devem permanecer conectados, com movimento controlável
   e amostras `x,y,cps,ts` aumentando sem atraso progressivo.
4. Interromper/reconectar o USB deve indicar desconexão e retomada sem atribuir
   contagens antigas à posição atual.
5. A latência e o offset devem ser conferidos na montagem física.

A calibração do fator CPS por µSv/h é necessária antes de usar a estimativa da
fonte do CEIA como resultado radiométrico. Ela não impede o ensaio de aquisição
posicionada. Dose acumulada não convertida permanece ausente, sem virar zero.

# Validação da preparação Radiacode + Go2 — 30/09/2026

## Resultado e correção do pacote

A aquisição independente e a integração em software estão preparadas para
testar USB real com robô simulado, seguida de Go2 físico no laboratório.
A combinação dos dois equipamentos físicos ainda precisa desse ensaio.

A falha de abertura da página foi reproduzida: o wheel da aplicação Go2 não
incluía `ares/servidor/static/index.html` e `app.js`. A instalação usada no
Docker encerrava com `RuntimeError: Directory .../ares/servidor/static does
not exist`, embora o contêiner tivesse sido anunciado como iniciado.

A declaração de package-data foi corrigida. Um wheel novo foi construído e
instalado em uma pasta isolada; dessa instalação, HTML, JavaScript, API e
robô simulado foram verificados por HTTP. O pipeline completo de contagens
também foi executado usando o pacote instalado. A ausência do Go2 físico
não impede o modo `usb-simulado`.

O Dockerfile executa a mesma verificação durante a construção. O iniciador
aguarda healthchecks e respostas HTTP antes de anunciar o painel como pronto,
verifica o estado USB separadamente e salva logs quando a inicialização falha.
Os nomes de arquivos, serviços e documentação usam termos técnicos.

As imagens Docker não foram construídas neste ambiente, que não possui
Docker Engine. `bash ensaio preparar` constrói e verifica as duas imagens
no computador do ensaio; workflows incluem essa verificação no GitHub.

## Referências e preservação

- `ares-wifi`: revisão `84f9148d1da6b7b3aa84b177b09a30d2631ecb8f`.
- Radiacode publicado anteriormente: revisão
  `3d26201887b8b85fa333fe9aabed7fdfdc5eee47`.
- Quickstarts `FS_5000_quickstart` e `go2_wifi_quickstart` fornecidos em ZIP.

Sincronizador, teleoperação, driver Go2 e cliente FS-5000 são idênticos aos
da revisão original: `src/ares/sincronizacao.py`, `src/ares/teleop.py`,
`src/ares/robo/go2.py` e `src/ares/radiacao/fs5000.py`. O código executável
do painel anterior, em `src/ares_mapper`, foi preservado; a documentação
nesse diretório usa a nomenclatura técnica atual.

Não foi feito merge nas branches `main` ou `ares-wifi`.

## Verificações

| Verificação | Resultado |
|---|---|
| Quickstart FS-5000 recebido, sem alterações, na preparação anterior | 111 testes passaram |
| Testes Python do projeto independente, incluindo USB, serviço e prontidão | 102 testes passaram |
| Teste JavaScript do desenho do Go2 no painel anterior | 1 passou |
| Testes Python da estrutura Go2/WebRTC, incluindo Radiacode | 208 testes passaram |
| Lint e tipos do projeto independente | Passaram; mypy verificou 76 arquivos |
| Sintaxe dos scripts, JavaScript e definições YAML | Passou |
| Wheel instalado: HTML, JavaScript, API e robô simulado | Passou |
| Imports Go2/WebRTC e câmera através da camada de compatibilidade original | Passou, sem conexão física |
| JSONL → WS → aplicação instalada → sincronizador → missão → CSV/JSON | Passou |
| Seleção de modo real com driver Go2 e fonte USB independente | Passou em software, sem equipamentos físicos |

A reprodução completa usou trechos reais de RawData com timestamps novos,
ritmo acelerado e posição simulada. Foram gravadas 7 amostras posicionadas,
20 poses e 7 leituras. Movimento por teleop simulado, retomada em nova sessão
USB e exportação CSV/JSON foram verificados. O relatório indica
`installed_package_test=true`, `hardware_test=false` e
`robot_physical_test=false`.

Também foram conferidos dados repetidos, incompletos, antigos, recebimento
em lote, filas limitadas para consumidores lentos, interrupção e reinício
do leitor, reconexão WebSocket e encerramento dos serviços. Os testes de
prontidão distinguem conexão HTTP recusada, arquivos ausentes, simulação
não inicializada, USB não confirmado e Go2 físico ainda desconectado.

## Capturas reais já recebidas

| Captura | RawData | Contagens reconstruídas de 1 s | Descartes por continuidade/formato |
|---|---:|---:|---:|
| Captura USB de uma hora, de 29/09/2026 | 7.200 | 3.600 | 0 |
| Captura USB de curta duração, de 30/09/2026 | 264 | 132 | 0 |

Esses arquivos demonstram a aquisição USB real anterior e permitem conferir
o formato dos registros. Não validam a pose do Go2 físico nem a conversão
absoluta de dose. O CPS de RealTimeData permanece no registro independente;
a integração posicionada usa a contagem inteira obtida de RawData.

## Confirmação no computador e no laboratório

1. Construir as imagens e passar a verificação de instalação com `preparar`.
2. Testar USB real + posição simulada, salvar missão e conferir a exportação.
3. No Go2 físico, confirmar pose, controle e contagens atuais, com aumento
   das amostras `x,y,cps,ts` sem atraso progressivo.
4. Desconectar e reconectar o USB, conferindo estado e retomada sem atribuir
   contagens antigas à posição atual.
5. Conferir latência e offset na montagem física.

A calibração específica CPS por µSv/h é necessária antes de usar a estimativa
da fonte como resultado radiométrico. Ela não impede o teste de aquisição
posicionada. Dose acumulada sem conversão validada permanece ausente.

## Consolidação v3 — painel aprovado

O modo Radiacode da aplicação Go2/WebRTC agora serve o estilo e o desenho
do Go2 do painel aprovado. Um adaptador de apresentação usa diretamente
`/api/estado`, `/api/missao/*`, `/ws` e `/ws/comando`. Não são emulados
endpoints antigos nem transferida a sincronização para o navegador.
O perfil padrão FS-5000 mantém a interface original dessa branch.

Quatro testes JavaScript adicionais verificam o desenho do Go2, ausência
de pose inventada, timestamp/contagem/posição sem alteração, deduplicação
visual, parada ao perder foco, reconexão sem repetir teclas e leituras antigas.
O teste HTTP do modo Radiacode verifica o painel e todos os seus arquivos.
Dois testes de porta distinguem TIME_WAIT de um processo em LISTEN.
A aquisição USB e a gravação permanecem independentes da interface.

## Revisão v4

A revisão após os e-mails do GitHub identificou as falhas de importação e
de agendamento do teste concorrente, além de uma falha real de seleção de
sessão após reconexão. Foram corrigidas sem alterar os arquivos centrais do
Werik. Veja [REVISAO_INTEGRACAO_20260930.md](REVISAO_INTEGRACAO_20260930.md)
para a comparação, os erros exatos e os limites da validação física.

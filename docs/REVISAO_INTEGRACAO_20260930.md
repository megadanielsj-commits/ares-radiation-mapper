# Revisão Radiacode USB + Go2/WebRTC — 30/09/2026

## Resultado

A arquitetura é compatível com a estrutura do Werik e está preparada para
um ensaio com USB real e Go2 físico. A revisão identificou e corrigiu três
pontos antes do ensaio: importação do leitor nos testes, coordenação de um
teste concorrente herdado e seleção de uma nova sessão USB durante reconexão.
O painel e o desenho do robô da versão aprovada foram mantidos.

## Comparação com a estrutura original

Referência: `ares-wifi`, commit `84f9148d1da6b7b3aa84b177b09a30d2631ecb8f`.

| Aspecto | Estrutura original | Adaptação Radiacode |
|---|---|---|
| Acesso ao detector | Serviço FS-5000 independente; ARES cliente WS | Leitor libusb em processo independente; serviço WS na porta 1098 |
| Contrato | snapshot, estado, leitura | Mesmo envelope; identidade/seq. de sessão Radiacode |
| Sincronização | Histórico de poses e interpolação em ts − latência | Mesmo arquivo, sem alteração |
| Controle do Go2 | WebRTC/LocalAP, watchdog e limites | Mesmos arquivos, sem alteração; network_mode: host |
| Campo usado no posicionamento | CPS da exposição de 1 segundo | Dois bins RawData consecutivos, contagem inteira nominal de 1 segundo |
| Taxa de dose | DR suavizado para exibição | Conversão provisória para exibição; não determina a posição |
| Calibração | Coeficiente específico do FS-5000 | Não reutilizado; estimativa calibrada depende de coeficiente Radiacode |
| Gravação | Missões SQLite, CSV/JSON | Mesmo formato posicionado; JSON também inclui metadados, poses e leituras |
| Interface | REST/WS do backend original | Visual antigo aprovado, adaptador de apresentação usando essas rotas |

O sincronizador, a teleoperação, o driver Go2, o cliente FS-5000 e o
estimador (`src/ares/estimativa.py`) são idênticos ao commit de referência.
A alteração no teste do estimador coordena a primeira leitura intermediária
com `threading.Event`; preserva as comparações entre resultados concorrentes
e sequenciais. O algoritmo não foi alterado.

## E-mails do GitHub Actions

Execuções analisadas na publicação v3:

- [CI independente](https://github.com/megadanielsj-commits/ares-radiation-mapper/actions/runs/36773814316): importação de `tools`/`counts` falhou ao coletar `test_usb_kit.py`.
- [CI Go2](https://github.com/megadanielsj-commits/ares-radiation-mapper/actions/runs/36773812925): o resultado final do estimador era igual ao sequencial, mas nenhuma thread registrou estado intermediário a tempo.

O leitor agora resolve `counts.py` pelo seu caminho local, em todas as formas
de execução. O CI usa `python -m pytest` e preserva as duas versões Python
mesmo se uma falhar. O teste concorrente garante uma leitura intermediária
por evento, sem depender do agendamento das threads. Foram mantidas todas
as verificações de consistência.

Cada workflow agora publica as falhas reais do pytest nas anotações do check,
usando o relatório JUnit. Isso torna o próximo diagnóstico visível sem
limitar o resumo a “exit code 1/2”. Os avisos sobre Node/Ubuntu vistos nas
imagens não foram a causa dos erros apresentados.

## Reconexão

Foi reproduzido o seguinte caso: o WS cai, o processo USB reinicia e muda
`aparelho_id`, e o consumidor perde o evento que desconectou o aparelho antigo.
O snapshot completo passa a substituir a lista antiga somente no cliente
Radiacode. O cliente escolhe a sessão nova e aceita as contagens atuais.
O cliente FS-5000 original permaneceu sem alterações. O teste de reconexão
WS agora usa identidades diferentes a cada sessão, como o serviço real.

## Verificação executada

- 102 testes Python do módulo independente passaram, inclusive usando o
  comando de entrada `pytest` que reproduzia a falha de importação.
- 209 testes Go2 passaram no ambiente de trabalho e em uma instalação nova,
  com as dependências e o pacote instalados conforme o CI.
- Teste concorrente corrigido e sete testes Radiacode passaram novamente.
- Quatro testes JavaScript do adaptador e um do painel independente passaram.
- Wheel instalado: HTML, JS, CSS, API, robô simulado e imports do SDK/câmera passaram.
- Replay externo JSONL → WS → sincronizador original → missão → CSV/JSON passou;
  a retomada de uma nova sessão USB foi conferida.
- Lint, tipos, sintaxe dos iniciadores e YAML passaram.

A execução Docker no computador foi confirmada pelo usuário para v3. Este
ambiente não possui Docker Engine; a construção da v4 deve ser feita por
`bash ensaio preparar` no computador, incluindo suas verificações instaladas.
A nova publicação ainda precisa concluir os checks do GitHub com sucesso.
Não foi feita publicação automática nesta revisão.

## Prontidão para o ensaio físico

O modo `usb-robo` está configurado para o driver original e não inicia missão
nem movimento automaticamente. Antes de executá-lo, encerrar o controlador
anterior e qualquer outra sessão WebRTC, conectar ao Wi-Fi do Go2 e ao USB.
Primeiro confirmar pose e contagens atuais; depois iniciar uma missão curta,
conferir movimentação, parar, exportar e testar desconexão/reconexão USB.
A leitura USB + pose simulada já foi confirmada pelo usuário. A pose real,
a latência efetiva (inicialmente 0,5 s), o offset da montagem e a calibração
radiométrica continuam dependentes dos equipamentos físicos.

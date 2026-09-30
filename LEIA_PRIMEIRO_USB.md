# ARES — primeiro teste USB do Radiacode 110

## Executar o pacote corrigido com um comando

Se preferir Docker Engine + Compose no Linux, use o repositório Git na branch
`feat/radiacode-independent`. No host, confirme o USB com
`bash 01_diagnostico_usb.sh`, configure a permissão com
`bash 03_permissao_usb.sh` e reconecte o detector. Depois:

```bash
./ares radiacode-usb          # somente detector, 60 segundos
./ares radiacode-dashboard    # detector real com Go2 virtual
./ares fonte-simulada         # fonte simulada, sem detector
```

O Docker instala as dependências na imagem; nesse caminho não é necessário
executar `02_preparar_ambiente.sh` no host. Os arquivos ficam em `resultados/`.
Execute somente um dos modos USB por vez. O modo Docker USB depende da
passagem do detector conectado à mesma máquina Linux que executa o Docker.

O script `00_INICIAR_USB_CORRIGIDO.sh` prepara o ambiente USB desta versão,
quando necessário, e inicia o teste com Go2 virtual. Ele grava resultados nesta
pasta, separadamente de instalações anteriores. Encerre qualquer teste anterior
com `Ctrl+C` antes de executá-lo.

```bash
bash 00_INICIAR_USB_CORRIGIDO.sh
```

Pacote preparado em 24/09/2026. Base: `ares-radiation-mapper`, commit
`fcf4377be8ccfd86f7d56343c58b0fc342fd3cdc` (main, v0.4.10).
Biblioteca do detector: `radiacode==0.4.0`.

## O que está pronto

- Diagnóstico do Linux e da enumeração USB.
- Instalação em ambiente Python separado, sem Docker.
- Permissão USB específica para `0483:f123` e o usuário que executa o script.
- Leitor independente: terminal, CSV, JSONL, registros brutos e espectros.
- Painel original do ARES com Go2 virtual controlado pelas setas e radiação USB real.
- Testes de software para conversão explícita, CPS fracionário, ausência de dados,
  desconexão, linhas parciais, timestamps e integração com o robô virtual.

O equipamento não esteve conectado ao ambiente de desenvolvimento. A comunicação
com o seu 110, seu firmware e as unidades exibidas precisam ser confirmadas no teste
abaixo. Não houve alteração no repositório remoto nem na branch da integração Go2.

## Preparação

Use um computador com Linux e um cabo USB que transmita dados. Ubuntu/Debian
com Python 3.10, 3.11 ou 3.12 é o caminho automatizado; a primeira instalação precisa
de internet e permissão sudo para pacotes do sistema/udev. Os testes seguintes
rodam como usuário normal e não precisam de internet.

1. Extraia o ZIP em uma **nova pasta**. Não copie por cima do seu ARES atual.
2. Abra a pasta extraída do pacote no gerenciador de arquivos e escolha **Abrir no terminal**.
3. Ligue o Radiacode, conecte por USB direto ao computador e feche outros programas
   que possam estar lendo o detector, inclusive a conexão do aplicativo no celular.

O Linux deste teste é o seu computador físico. Em VM/WSL, a passagem USB precisa
ser configurada antes; envie o diagnóstico se o aparelho não aparecer.

## 1. Identificar o USB

```bash
bash 01_diagnostico_usb.sh
```

Procure `0483:f123` na listagem. Esse é o ID esperado pelo transporte da biblioteca.
O Radiacode não precisa aparecer como `/dev/ttyUSB0`.

Se `lsusb` estiver ausente em Ubuntu/Debian:

```bash
sudo apt install usbutils
bash 01_diagnostico_usb.sh
```

Se o ID esperado não aparecer, pare nesta etapa e envie o arquivo
`resultados/diagnostico-....txt`. Troque cabo/porta e compare a saída com o detector
desconectado e conectado. Se quiser registrar a conexão ao vivo:

```bash
sudo dmesg --follow
```

Reconecte o cabo e encerre o acompanhamento com `Ctrl+C`.
Não há instalação de CH341 nem configuração de baud rate para este teste.

## 2. Instalar o ambiente

Somente após confirmar o identificador:

```bash
bash 02_preparar_ambiente.sh
```

O script instala libusb e ferramentas do sistema em Ubuntu/Debian, cria
`.venv-radiacode`, instala a biblioteca fixada em 0.4.0 e o ARES incluído no pacote.
As versões resolvidas ficam em `resultados/versoes-instaladas.txt`.

Se o Python padrão for 3.13 ou superior e você já tiver outro compatível:

```bash
ARES_PYTHON=/caminho/para/python3.12 bash 02_preparar_ambiente.sh
```

Não instale os pacotes com `sudo pip`. Não é necessário ativar manualmente o venv:
os comandos do pacote usam o interpretador correto.

## 3. Liberar o USB

```bash
bash 03_permissao_usb.sh
```

Depois, **desconecte e reconecte o cabo USB**. A regra é restrita ao dispositivo e
ao seu usuário. Não execute o próprio script com sudo; ele pede sudo apenas para
gravar a regra e recarregar o udev.

## 4. Primeiro teste real: 60 segundos

```bash
bash 04_teste_usb.sh
```

O terminal deve identificar número de série/firmware e depois mostrar:

```text
PRIMEIRA LEITURA REAL RECEBIDA. CPM* = 60 × CPS.
```

Cada linha informa horário UTC, sequência, taxa convertida, CPS, CPM derivado e
taxa bruta. Ao terminar, deve aparecer `Fim: completed` com número de leituras
maior que zero. A frequência é determinada pelo aparelho; não exigimos exatamente
60 leituras em 60 segundos.

**Compare a taxa convertida com o visor em µSv/h.** A conversão usada pelos
exemplos da biblioteca é `dose_rate_raw × 10000`. Nós a registramos explicitamente
e mantemos `dose_conversion_verified=false`: a biblioteca documenta unidades
escaladas do protocolo e recomenda conversão consciente da configuração.
Não presuma calibração validada apenas porque a comunicação funcionou. Se o visor
estiver em nSv/h, compare depois de dividir o valor do visor por 1000. Se estiver
em R/h, envie a unidade e os valores antes de interpretar a taxa em Sv/h.

Critério inicial de sucesso: receber RealTimeData do detector e gravar leituras
reais. O acordo de unidades com o visor é uma verificação separada. Flutuações e
janelas de média podem impedir coincidência exata entre duas leituras instantâneas.

Os espectros são consultados a cada 15 segundos. Se houver problema nessa parte,
teste a aquisição escalar isolada:

```bash
bash 04_teste_usb.sh --spectrum-interval 0
```

Para coletar por cinco minutos:

```bash
bash 04_teste_usb.sh --seconds 300
```

Confira `summary.json` na pasta dessa execução: `state=completed` e
`fresh_measurements>0` indicam que chegaram registros novos. Se o aparelho
continuar devolvendo apenas a mesma leitura, o leitor grava as repetições com
`is_duplicate=true` e termina com erro após o tempo sem leitura nova. Compare
os horários e as taxas com o visor; essa revisão exige o detector físico.

## 5. Radiacode real com o robô simulado

Espere o teste anterior terminar para liberar o detector e execute:

```bash
bash 05_robo_simulado_usb.sh
```

O programa espera a primeira leitura USB real e só então inicia o painel.
Abra **http://127.0.0.1:8000** caso o navegador não abra automaticamente.

- A missão começa automaticamente.
- Clique na área do mapa e use as **setas**: cima/baixo movem, esquerda/direita giram.
- CPS, taxa e idade da última leitura aparecem no painel.
- A inscrição **Radiação real · Go2 virtual** identifica o modo do teste.
- Se passarem 5 segundos sem dado recente, a taxa deixa de ser mostrada como atual.
- `Ctrl+C` no terminal encerra os dois processos e preserva os registros gravados.
- O teste tem duração máxima padrão de 1 hora. Pode ser menor com `--duration 300`.
- Se a porta 8000 estiver ocupada, use `bash 05_robo_simulado_usb.sh --port 8001`.

**As coordenadas são fictícias.** Mover o robô na tela não muda a radiação física
no detector. As cores e os pontos servem para validar a chegada dos dados e o
funcionamento da interface. Este teste não valida localização de fontes nem
sincronização espacial real. O programa não se conecta ao Go2 físico.

O painel mostra “Dose integrada no teste”, uma integral aproximada das taxas
recebidas. Ela não é a dose acumulada interna do detector. A dose acumulada interna
é preservada em unidades brutas nos arquivos até validarmos sua conversão.

## Onde encontrar os dados

Tudo fica dentro da pasta **resultados**, em uma subpasta nova para cada execução.
O teste do mapa cria também uma subpasta `detector` e outra `missions`.

| Arquivo | Conteúdo |
|---|---|
| `session.json` | Série, firmware, biblioteca, configuração, calibração e convenções de tempo/unidades |
| `readings.csv` | Leituras Realtime em tabela; campos indisponíveis ficam vazios |
| `readings.jsonl` | Mesmas leituras com tipos preservados, unidades, timestamps e flags |
| `raw_records.jsonl` | Todos os registros decodificados retornados pela biblioteca, incluindo RawData, RareData e eventos |
| `spectra.jsonl` | Contagens por canal, energia em keV, coeficientes e duração de cada espectro |
| `events.jsonl` | Falhas de consulta de espectro |
| `summary.json` | Estado final, total de registros, medições novas e duração |
| `error.txt` | Exceção completa, se houver falha |
| `dashboard.log` | Log do painel, no teste com Go2 virtual |

`raw_records.jsonl` contém registros decodificados, não uma captura byte a byte
do USB. Os snapshots de espectro são acumulados; **não devem ser somados**.
O comprimento do vetor determina a quantidade real de canais, sem fixar 1024.

## Como a separação evita a espera pelo robô

O processo `reader.py` acessa o USB e grava os arquivos imediatamente. O processo
do ARES lê o JSONL em paralelo. O consumidor do mapa não pode atrasar as chamadas
USB, pois não participa do processo de aquisição. Se o painel encerrar sozinho,
o lançador informa o erro e mantém o leitor rodando até `Ctrl+C` ou fim do teste.
Se o leitor falhar, o lançador encerra o painel. Não há substituição automática
por dados simulados e não há reconexão silenciosa nesta versão.

O ARES aceita apenas registros novos da mesma sessão para esse modo. Registros
atrasados em mais de 5 segundos podem ser descartados **da visualização**, mas
continuam preservados no arquivo original do leitor. O mapa não é o registro
autoritativo da aquisição. Não use pausa/aceleração temporal no teste USB;
esses comandos são bloqueados, porque o detector físico continua em tempo real.

Timestamps salvos:

- `received_utc_ns`: horário UTC do computador no retorno da consulta;
- `received_monotonic_ns`: tempo monotônico do mesmo computador, útil entre processos;
- `device_record_time_utc`: tempo decodificado pela biblioteca a partir da base
  temporal do computador e do deslocamento do detector; não é um relógio independente validado.

Todos os registros retornados pela mesma consulta podem compartilhar o timestamp
de recebimento. O tempo de cada registro fica preservado separadamente. Intervalos
e incertezas usados no mapa são provisórios, destinados à visualização virtual.

## Se falhar

| Mensagem/sintoma | Ação |
|---|---|
| Não aparece `0483:f123` | Envie diagnóstico; confira cabo de dados, porta e passagem USB da VM |
| `NoBackendError` | Falta libusb; execute o passo 2 |
| `Permission denied` / acesso negado | Execute o passo 3 e reconecte o cabo |
| `DeviceNotFound` | Confira se o detector permanece enumerado e ligado |
| Outro leitor já usando o detector | Encerre o outro teste/aplicativo antes de iniciar |
| Firmware incompatível / pacote desconhecido | Envie `session.json`, `error.txt`, firmware e logs; não ignore a checagem automaticamente |
| Sem `RealTimeData` por 20 s | Envie `raw_records.jsonl`; pode haver outros registros, mas não confirmamos leitura ao vivo |
| Taxa difere muito do visor | Envie uma foto com a unidade visível e algumas linhas do CSV |
| Mapa não abre, mas terminal lê | Envie `dashboard.log`; os dados do detector continuam sendo gravados |

Para analisar o primeiro teste, envie **diagnóstico, session.json, summary.json e
readings.csv**; em caso de erro, acrescente `error.txt`/`dashboard.log`.

## Operações realizadas no equipamento

A conexão da biblioteca inicia a sessão de comunicação e ajusta a referência de
tempo do dispositivo. Este pacote não chama os comandos de zerar dose/espectro,
alterar calibração, alarmes, firmware ou configuração de exibição. As consultas de
configuração, identificação, medições e espectro usam a API existente da biblioteca.

## Fontes e rastreabilidade

- Fabricante: https://www.radiacode.com/knowledge/developer-resources-for-radiacode
- Biblioteca: https://github.com/cdump/radiacode
- Release fixada: https://pypi.org/project/radiacode/0.4.0/
- Notas de unidades: https://github.com/cdump/radiacode/blob/master/docs/guides/measurements.md
- Exemplo da escala: https://github.com/cdump/radiacode/blob/master/src/radiacode/examples/radiacode-exporter.py
- ARES: https://github.com/megadanielsj-commits/ares-radiation-mapper

O README original do ARES está incluído para referência. Para este teste use os
scripts numerados acima, pois os iniciadores originais têm outros modos de operação.

## Versão com fonte simulada

Para observar um gradiente conhecido, encerre primeiro o teste USB (`Ctrl+C`) e
execute, na mesma pasta:

```bash
bash 06_FONTE_SIMULADA.sh
```

Esse modo não acessa o Radiacode. O painel mostra a fonte configurada, o Go2
virtual e medições geradas pelo modelo do ARES. Escolha X, Y e a taxa da fonte
**em mSv/h a 1 metro**, clique em **Iniciar mapeamento** e mova o Go2 pelas setas.
Os resultados ficam em `data/missions/`. Os pontos e as cores nesse modo são
sintéticos; compare com a execução USB somente como teste da interface.

Para voltar à aquisição real, encerre a simulação (`Ctrl+C`) e execute
`bash 05_robo_simulado_usb.sh`. Os dois modos devem ser executados um por vez
quando usam a porta 8000.

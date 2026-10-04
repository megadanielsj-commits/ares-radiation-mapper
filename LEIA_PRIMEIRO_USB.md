# Radiacode 110 — diagnóstico e aquisição independente

A operação com mapa usa exclusivamente `bash ares-console iniciar`, na porta
8001, e o modo **Robô simulado** ou **Equipamentos reais**. O leitor e o serviço
USB continuam independentes do robô. Estes comandos são para diagnóstico ou
coleta sem console, com os leitores anteriores encerrados.

## Reconhecimento e permissão

Conecte o Radiacode com cabo de dados e execute:

```bash
bash 01_diagnostico_usb.sh
```

O transporte de `radiacode==0.4.0` espera o identificador `0483:f123` em `lsusb`.
Não exige `/dev/ttyUSB0`, CH341 ou baud rate. Se o ID não aparecer, compare
conexão/desconexão e confira cabo/porta antes de prosseguir. O diagnóstico fica
em `resultados/diagnostico-*.txt`.

Se houver erro de permissão no computador de operação:

```bash
bash 03_permissao_usb.sh
```

Execute como usuário normal. O script pede sudo para instalar a regra udev
restrita ao detector e ao seu usuário. **Reconecte o cabo** depois da instalação.
As permissões já configuradas nos testes anteriores podem ser reutilizadas.

## Leitura sem mapa, fora do Docker

Ubuntu/Debian com Python 3.10–3.12. Depois de confirmar o USB, prepare o ambiente
local e colete 60 segundos:

```bash
bash 02_preparar_ambiente.sh
bash 04_teste_usb.sh
```

Para coletar uma hora, no mesmo ambiente:

```bash
bash 04_teste_usb.sh --seconds 3600
```

O leitor termina sozinho, escreve o resumo e informa o caminho dos arquivos.
Conserve a pasta de sessão: `session.json`, `readings.csv`, `readings.jsonl`,
`raw_records.jsonl`, `counts_1s.jsonl` quando disponível e espectros.
Este ambiente local é para aquisição independente; o console usa Python 3.12
na imagem Docker. Não é necessário preparar esse venv para operar o console.

## Semântica e diagnóstico de dose

`readings.jsonl` preserva o CPS fracionário/suavizado do aparelho.
`counts_1s.jsonl` preserva a contagem reconstruída dos bins brutos de 1 s para a
integração. CPM é derivado, 60 × CPS. Os canais não são intercambiáveis.

Taxa ausente não vira zero ou CPS convertido. Na configuração conhecida, o SDK
usa canal bruto `R/h` com fator 10.000 para obter µSv/h. A unidade de visor/alarmes
em `get_alarm_limits()` não substitui a unidade do canal. A correspondência com
o visor deve ser conferida no ensaio. A dose histórica do detector permanece em
unidade bruta até validação; a integral da missão é outra grandeza.

O serviço verifica os timestamps próprios da taxa e da contagem. Consulte
[CONTRATO_USB_WEBSOCKET.md](docs/CONTRATO_USB_WEBSOCKET.md) e
[RADIACODE_110.md](docs/RADIACODE_110.md). Não execute dois leitores USB ao mesmo
tempo; encerre pelo iniciador de cada um antes de mudar para o console.

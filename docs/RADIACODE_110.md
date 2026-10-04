# Radiacode 110 — módulo de aquisição

O módulo acessa o detector por `radiacode==0.4.0`/libusb, em processo próprio.
Não importa o robô ou a teleoperação. O console oficial tem um único iniciador,
`bash ares-console iniciar`, e seleciona os quatro modos na interface.

| Componente | Entrada | Saída |
|---|---|---|
| `reader.py` | Detector USB | Registros brutos, medidas, contagens de 1 s e espectros |
| `counts.py` | Bins RawData consecutivos | Contagem nominal de 1 s, sem arredondar CPS suavizado |
| `service.py` | Novas linhas de `counts_1s.jsonl` | WebSocket local `ws://127.0.0.1:1098/ws` |
| `ClienteRadiacode` | WebSocket | `Leitura` no contrato do runtime de integração |
| Orquestrador/sincronizador | Leitura e pose Go2 | Amostras posicionadas, SQLite e mapa aprovado |

Os arquivos são gravados antes da publicação. Consumidores lentos não bloqueiam
a leitura USB; a publicação descarta eventos antigos e informa indisponibilidade
quando os dados deixam de ser recentes. Reconexão cria uma sessão identificável.

## Campos e unidades

- `readings.csv`/`readings.jsonl`: CPS suavizado/fracionário, taxa bruta e convertida,
  erros fornecidos pelo SDK, recebimento UTC/monotônico e status disponíveis.
- `raw_records.jsonl`: tipos, tempos e campos originais dos registros do SDK.
- `counts_1s.jsonl`: CPS inteiro reconstruído de dois bins, CPM derivado, sequência,
  sessão e metadados/timestamps próprios do canal de dose.
- `spectra.jsonl`: snapshots de contagens por canal e energias pela calibração
  fornecida pelo detector, quando disponíveis.
- `session.json`: identificação, firmware, configuração, unidades e convenção
  de conversão. Os números não são arredondados para exibição.

O mapa real usa a taxa reportada em µSv/h. Não calibra CPS em dose e não reutiliza
o fator do FS-5000. A interface escolhe prefixos SI somente para os rótulos.
A dose da missão integra taxas dos intervalos posicionados aceitos e não é o
acumulado histórico do detector. A conversão da unidade bruta continua marcada
como provisória até conferência física documentada com o visor.

## Executar sem robô

Veja [LEIA_PRIMEIRO_USB.md](../LEIA_PRIMEIRO_USB.md) para diagnóstico, permissão
e coleta isolada de 60 segundos ou uma hora. Para um serviço USB isolado com
as dependências já instaladas:

```bash
python tools/radiacode_usb/service.py --output resultados/usb-independente
```

O serviço abre 1098 e supervisiona o processo leitor; não inicia missão ou
movimento. Não o execute em paralelo ao modo USB do console, que já o inicia.
O Dockerfile desse serviço permanece para instalação independente sem interface.

Detalhes de tempo, filas, ausência de taxa e eventos estão em
[CONTRATO_USB_WEBSOCKET.md](CONTRATO_USB_WEBSOCKET.md). O ensaio conjunto está em
[ROTEIRO_ENSAIO_GO2.md](../ROTEIRO_ENSAIO_GO2.md).

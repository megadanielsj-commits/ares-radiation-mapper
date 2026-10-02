# Verificação do ARES Console 1.0.1 — 02/10/2026

Revisão dos dois defeitos da 1.0.0: taxa USB ausente no modo Robô simulado e
arredondamento visual que zerava valores pequenos. O mapa, o gradiente, a paleta,
o layout e os algoritmos aprovados continuam intactos. O pacote está preparado
para confirmação no USB do operador e para o ensaio conjunto de 08/10/2026.

## Evidência e reprodução antes da alteração

Foram examinados `session.json` e registros dos arquivos fornecidos anteriormente
`Radiacode_1h_20260929.tar.gz` e `Radiacode_CEIA_teste.tar.gz`. Não foi recebido
um `service.log` da execução problemática atual da 1.0.0; esse arquivo não é
apresentado como evidência disponível. A reprodução foi feita em software,
renovando timestamps de recebimento apenas para testar o transporte, sem tratar
registros de setembro como leituras atuais do USB.

- O canal `GRP_RealTimeData/CHN_DoseRate` declarou unidade bruta `R/h` e
  `ScaledUnit=1`. O SDK 0.4.0 e o firmware 4.14 constavam nas sessões.
- `get_alarm_limits().dose_unit` retornou `R`: unidade do visor/alarmes.
- Um registro real arquivado continha taxa bruta `1.2651909855776466e-05`.
  O leitor já gerava `dose_rate_uSv_h=0.12651909855776466` pelo fator do SDK.
- O bridge da 1.0.0 vetava qualquer unidade de visor diferente de `Sv`.
  Na reprodução, CPS 13/CPM 780 chegavam ao WebSocket com `dr_usvh=null`.
- A regressão visual mostrou dose positiva `0.000035144194043823516` µSv
  formatada como `0,00`. A simulação completa foi executada no navegador antes
  da alteração; os testes dos dois defeitos falharam na versão antiga.

## Correção e fluxo verificado

| Trecho | Verificação |
|---|---|
| SDK → `reader.py` | Identifica a unidade do canal bruto separadamente de `get_alarm_limits()`. Conserva bruto, fator e metadados. |
| Leitor → CSV/JSONL | Dose e CPS suavizado fracionário sobrevivem à serialização sem arredondamento. Contagens de `RawData` continuam inteiras. |
| `counts_1s.jsonl` → `service.py` | Valida unidade/escala, correspondência com bruto e timestamps próprios da taxa, sem usar CPS para produzir dose. |
| Serviço → WebSocket → `Leitura` | Taxa convertida permanece numericamente igual; CPS 13/CPM 780 atravessam como canais separados. |
| `Leitura` → runtime/mapa | Taxa reportada alimenta amostras e integral. Taxa ausente não alimenta o mapa. |
| Runtime → interface | Formata rótulos somente. `0.12651909855776466` µSv/h aparece como `1,27E-1 µSv/h` e `1,27E-4 mSv/h` na legenda. |

A conversão já existente segue a convenção do exportador primário do SDK 0.4.0:
`dose_rate × 10000` em µSv/h para o canal bruto conhecido `R/h`. É uma conversão
provisória do canal de dose, não uma calibração CPS→dose. Continua marcada
`dose_conversion_verified=false` até comparação física com o visor. Unidade de
visor `R` ou consulta de alarmes indisponível não bloqueia esse canal conhecido.
Unidade bruta desconhecida, dose inválida ou timestamp antigo mantém contagens
e registros, mas produz dose indisponível, com motivo em diagnóstico/log.

A apresentação usa duas casas quando o erro relativo do rótulo é no máximo 0,5%;
caso contrário, usa notação científica com duas casas na mantissa. Essa escolha
não modifica dados brutos, arquivos, mensagens ou cálculos. Um zero reportado
permanece zero; valor ausente não vira zero.

## Preservação das referências

| Referência | Resultado |
|---|---|
| Console 1.0.0, `fcc87377c6b6eb67198b8c0b629e57382857f697` | Runtime, servidor, CSS e mapa idênticos. HTML muda somente a versão do cache de CSS/JS. |
| Mapa aprovado, `a84b972f9d27bb3f2bc7dc32a3bb4e9581f25d08` | 56 hashes e `map.lock.json` iguais, incluindo os dois arquivos da correção de permanência. |
| Runtime adaptado, `4048f7c8b4ffe2cc0f604a8bae1b89d4763aa4f2` | Os 30 arquivos versionados em `vendor/go2_runtime/src/ares` são idênticos. |
| Integração original, `ares-wifi`, `84f9148d1da6b7b3aa84b177b09a30d2631ecb8f` | Driver Go2, sincronizador, teleop, persistência e watchdog preservados. |
| SDK `cdump/radiacode` 0.4.0, `3e9a2aaec60aa1da06834310c5fb660133e734d3` | Configuração/unidades e exportador comparados com o código primário local dessa versão. |

O leitor USB continua em processo independente. Filas limitadas, reconexão,
worker ordenado, sincronização temporal e controle do robô não foram modificados.
A dose acumulada da missão continua sendo a integral dos intervalos posicionados
aceitos, separada da dose acumulada do aparelho.

## Resultados dos testes

- **144 testes Python do pacote passaram** em Python 3.12.14: canal de dose,
  CSV/JSONL, WebSocket, decoder, mapa, exportação, quatro modos, ausência/retorno
  de dose, unidade desconhecida, taxa antiga e robô parado.
- **209 testes do runtime de referência passaram**, executados contra o runtime
  vendorizado com substitutos de hardware.
- **12 testes JavaScript passaram**: 11 do console/mapa e 1 do painel USB.
- Ruff, mypy (76 módulos), hashes protegidos, imports do build, sintaxe Bash e
  `git diff --check` passaram.
- Chrome: simulação completa em cinco larguras, configuração, fonte, teclado,
  ampliação, parada e exportação. Os outros três modos passaram com robô virtual
  como substituto de Go2. Nos modos com dose reportada, registros compatíveis
  com o SDK passaram pelo serviço e **WebSocket local real** até a interface.
  Nenhum erro JavaScript foi registrado.
- Taxa `0.12651909855776466` µSv/h, CPS 13/CPM 780 e dose acumulada positiva
  foram conferidos nos modos USB por contrato. CSV de missão e JSON bruto
  conservaram a taxa completa. Esses resultados não são um teste USB físico.

O resumo está em `validation/console_1.0.1.json`. Testes e fixtures estão no pacote.

```bash
python -m pip install -e '.[dev,fs5000,radiacode-usb]'
PYTHONPATH=src:vendor/go2_runtime/src python -m pytest tests tools/operator_console/test_console.py tools/operator_console/test_stationary_map.py tools/source_simulation/test_demo.py
node --test tools/operator_console/console.test.cjs tests/radiacode/dashboard_usb.test.cjs
python -m tools.operator_console.check_map_lock
ruff check src tests
mypy src
bash -n ares-console PUBLICAR_CONSOLE_GITHUB.sh
```

## Validação física e publicação

Não há Go2/Radiacode físicos nem Docker Engine neste ambiente. A imagem
`ares-operator-console:1.0.1` **não foi construída aqui**. O iniciador constrói
essa imagem no computador do operador, evitando reutilizar a imagem 1.0.0.
CI Python 3.10/3.12 e builds Docker devem ser confirmados após publicação.
O pacote não foi enviado ao GitHub por esta execução.

Repita Robô simulado com USB real nesta revisão e compare a taxa com o visor.
Os testes de protocolo não validam instalação USB, rádio, firmware/AES do Go2,
média interna da taxa, latência, offset ou precisão radiométrica da reconstrução.
O padrão do Werik permanece; confira os parâmetros no ensaio conjunto.
Veja [PUBLICACAO_E_TESTE.md](PUBLICACAO_E_TESTE.md).

Referências primárias do SDK consultadas no checkout local 0.4.0:
https://github.com/cdump/radiacode/blob/0.4.0/docs/guides/measurements.md
https://github.com/cdump/radiacode/blob/0.4.0/src/radiacode/examples/radiacode-exporter.py

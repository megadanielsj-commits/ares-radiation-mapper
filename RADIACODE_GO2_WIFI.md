# Radiacode 110 na estrutura ares-wifi

Esta branch parte de `ares-wifi` no commit
`84f9148d1da6b7b3aa84b177b09a30d2631ecb8f`. Ela adiciona seleção do Radiacode
sem alterar sincronizador, teleop, driver Go2 WebRTC ou cliente FS-5000.
O leitor USB está fora desta aplicação, na branch
[feat/radiacode-independent](https://github.com/megadanielsj-commits/ares-radiation-mapper/tree/feat/radiacode-independent).

## Executar

No ZIP de ensaio, o iniciador na pasta principal prepara as duas imagens e
oferece `bash ensaio usb-simulado` e `bash ensaio usb-robo`. O painel ARES
usa a porta 8001 e a entrada Radiacode usa `ws://127.0.0.1:1098/ws`.
O painel anterior do usuário continua separado, sem substituição.

Para executar esta aplicação diretamente com o serviço USB já ligado:

```bash
ARES_FONTE_RADIACAO=radiacode ARES_MODO=simulacao ARES_PORTA=8001 python -m ares
```

Para pose real, altere `ARES_MODO=real`, usando o ambiente do Werik e a rede
Wi-Fi do Go2. Sem `ARES_FONTE_RADIACAO`, continuam os defaults originais:
radiação simulada no modo simulação e FS-5000 no modo real.

## Aquisição sem calibração

Sem `ARES_RADIACODE_CPS_POR_USVH`, é possível iniciar missão, gravar posição,
contagem e timestamp e exportar CSV/JSON. O estimador e o mapa calibrado ficam
aguardando calibração. O coeficiente 2,6 do FS-5000 não é usado pelo Radiacode.
Com coeficiente específico medido, o estimador original pode ser habilitado
pela variável `ARES_RADIACODE_CPS_POR_USVH`.

A contagem vem de RawData em exposições nominais de um segundo. CPM é
`60 * cps`. A dose acumulada em µSv é ausente e a conversão da taxa de dose
é identificada como provisória. Os metadados ficam salvos desde a criação
da missão e são incluídos no JSON. O JSON da missão Radiacode inclui também
as poses e leituras individuais; o CSV posicionado mantém o formato ARES.

O timestamp de leitura é o recebimento no computador. O sincronizador conserva
a interpolação em `ts - latencia_leitura_s`, com 0,5 s inicialmente. Valide o
atraso e o offset com os equipamentos físicos. Campos da biblioteca baseados
no tempo do detector não são usados como relógio UTC absoluto.

## Validação desta preparação

Os 207 testes Python passaram, incluindo os testes originais e seis testes do
Radiacode. A aplicação instalada a partir do wheel também serviu o HTML,
o JavaScript e a API, com o robô simulado ativo. O fluxo externo JSONL/WS/API
com posição e teleop simulados passou usando essa instalação. O ensaio Go2
físico + Radiacode e a construção Docker no computador do laboratório ainda
precisam ser feitos. `Dockerfile.go2-wifi` usa as
versões diretas de dependências dos testes; `Dockerfile` e os perfis Docker
originais continuam disponíveis para o FS-5000.

O wheel inclui os arquivos de `ares/servidor/static`. A construção da imagem
executa `tools/check_installed_app.py` para conferir a instalação efetivamente
usada em runtime, sem conectar um robô ou detector físico. O iniciador do
pacote espera a página, o JavaScript e a API responderem antes de anunciar
o endereço como disponível. O estado USB é verificado separadamente.

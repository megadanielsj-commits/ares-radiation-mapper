# ARES Radiation Mapper V0.4.10 — FS-5000 e Radiacode 110

O ARES combina a posição do Unitree Go2 com as leituras do FS-5000 e gera, em
tempo real, o percurso do robô, o gradiente radiológico do ambiente e a região
provável da fonte. A interface é acessada pelo navegador em
`http://127.0.0.1:8000`.

## Radiacode na estrutura do CEIA

O ensaio com USB independente e entrada WebSocket compatível com o sistema
`ares-wifi` está preparado em [LEIA_PRIMEIRO_ENSAIO_CEIA.md](LEIA_PRIMEIRO_ENSAIO_CEIA.md).
Use `bash ensaio preparar`, depois `bash ensaio usb-simulado` para verificar USB
real com posição simulada. O painel anterior continua no comando abaixo.
A adaptação CEIA está na branch `feat/radiacode-ceia-test`, incluída no pacote
de ensaio e no bundle; o código original do Werik está em `ares-wifi`.

## Modos de execução

O iniciador oferece os seguintes modos. Os testes do Radiacode não comandam o
Go2 físico:

| Comando | Posição | Radiação |
|---|---|---|
| `./ares simulation` | Go2 simulado | FS-5000 simulado |
| `./ares hardware` | Unitree Go2 real | FS-5000 real |
| `./ares fonte-simulada` | Go2 virtual | Fonte e detector simulados |
| `./ares radiacode-usb` | Sem robô | Radiacode real por USB, 60 segundos |
| `./ares radiacode-dashboard` | Go2 virtual | Radiacode real por USB |

O comando `./ares hardware` continua verificando Go2 e FS-5000 juntos.
Os testes independentes do Go2 e do Radiacode têm iniciadores próprios.
Os três últimos modos também podem ser iniciados com Docker Compose.

## Requisitos

- Docker Engine;
- plugin Docker Compose;
- navegador moderno;
- para o modo real: computador Ubuntu ligado ao Go2 e FS-5000 conectado por USB.

O modo real usa Python 3.10 e uma revisão fixa do
[`unitree_sdk2_python`](https://github.com/unitreerobotics/unitree_sdk2_python),
instalados automaticamente durante a construção da imagem.

## 1. Rodar a simulação

Na raiz do repositório:

```bash
./ares simulation
```

Abra [http://127.0.0.1:8000](http://127.0.0.1:8000), informe a posição e a
intensidade da fonte, clique em **Iniciar** e mova o Go2 simulado pelas setas do
teclado.

### Fonte simulada sem Docker

Com Python 3.10–3.12, também é possível iniciar o Go2 virtual com uma fonte
radiológica simulada pelo próprio ARES:

```bash
bash 06_FONTE_SIMULADA.sh
```

Esse script prepara seu ambiente local na primeira execução, abre o painel
em `http://127.0.0.1:8000` e não acessa nenhum detector USB. Escolha posição
X/Y e intensidade em mSv/h a 1 metro, clique em **Iniciar mapeamento** e use
as setas do teclado. Encerre com `Ctrl+C`.

### Radiacode 110 por USB, independente da odometria

Para registrar dados reais no Linux ou visualizá-los com o Go2 virtual:

```bash
bash 04_teste_usb.sh
bash 05_robo_simulado_usb.sh
```

Antes da primeira execução, siga [`LEIA_PRIMEIRO_USB.md`](LEIA_PRIMEIRO_USB.md).
O leitor USB grava CSV/JSONL em `resultados/` em um processo separado do
painel e do Go2. O teste do mapa usa **posição virtual**, e a conversão da
taxa de dose ainda precisa ser confrontada com o visor. Consulte a
[documentação do módulo](docs/RADIACODE_110.md) para formatos e limites.

### Radiacode com Docker no Linux

Na primeira vez, conecte o detector, rode `bash 01_diagnostico_usb.sh` e
`bash 03_permissao_usb.sh` no computador (fora do contêiner). Reconecte o cabo
após configurar a permissão. Feche o aplicativo ou outro leitor que esteja
utilizando o USB. O Docker Engine com o plugin Compose deve estar instalado.

```bash
./ares radiacode-usb          # grava leituras por 60 s em resultados/
./ares radiacode-dashboard    # USB real + Go2 virtual em http://127.0.0.1:8000
./ares fonte-simulada         # fonte + detector simulados; dispensa USB
```

Execute um modo de cada vez e termine o painel com `Ctrl+C`. O Docker entrega
`/dev/bus/usb` ao contêiner; o script usa o usuário atual para preservar a
permissão dos arquivos em `resultados/`. O leitor USB continua em um processo
separado do painel. Essa configuração foi preparada para Docker Engine em Linux;
nenhum contêiner conecta automaticamente um USB de outra máquina ou de um
servidor remoto. A montagem e o acesso ao USB precisam ser confirmados no
computador que receberá o detector.

## 2. Rodar com Go2 e FS-5000

Primeiro crie a configuração local:

```bash
cp .env.example .env
```

Descubra a interface conectada ao Go2 e a porta do detector:

```bash
ip -br link
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

Edite `.env`:

```dotenv
ARES_NETWORK_INTERFACE=enp2s0
FS5000_DEVICE=/dev/ttyUSB0
```

Depois conecte os dois equipamentos e execute:

```bash
./ares hardware
```

O perfil real:

- compartilha a rede do computador com o contêiner para o DDS do Go2;
- entrega `/dev/ttyUSB0` ao contêiner para ler o FS-5000;
- recebe `rt/sportmodestate` pelo SDK2;
- inicia a aquisição automaticamente;
- salva as missões em `data/missions/`.

Abra [http://127.0.0.1:8000](http://127.0.0.1:8000). Para encerrar qualquer
modo, pressione `Ctrl+C` no terminal.

### Teleop do Go2 real pela interface

No modo real (`./ares hardware` ou `./ares-go2-only`), as setas do teclado na
interface comandam o Go2 físico: `↑/↓` avançam/recuam, `←/→` giram. Soltar a
tecla, tirar o foco da janela ou parar a missão envia `StopMove`. O robô deve
ser levantado antes pelo controle oficial (ARES não faz bring-up). **Garanta
área livre e mantenha o controle oficial à mão para parada de emergência: a
primeira tecla move o robô de verdade.**

## Comandos Docker equivalentes

O script `./ares` é apenas um iniciador com verificações e mensagens claras. Os
comandos equivalentes são:

```bash
docker compose --profile simulation up --build simulation
docker compose --profile hardware up --build hardware
docker compose --profile fonte-simulada up --build fonte-simulada
# Para os dois perfis USB, prefira ./ares: ele ajusta UID/GID e cria resultados/.
```

## Execução local para desenvolvimento

Requer Python 3.10 a 3.12:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,fs5000,radiacode-usb]"
```

Simulação:

```bash
ares-map start --mode simulation
```

Hardware, após instalar o SDK2 oficial:

```bash
ares-map start \
  --mode hardware \
  --network-interface enp2s0 \
  --serial-port /dev/ttyUSB0
```

O comando avançado `ares-map run --scenario ARQUIVO.yaml` continua disponível
para desenvolvimento, replay e validação, mas não faz parte da operação normal.

## Testes

```bash
pytest
node --test tests/radiacode/dashboard_usb.test.cjs
ruff check src tests
mypy src
```

O workflow em `.github/workflows/ci.yml` executa esses testes e também constrói
as imagens de simulação e hardware a cada `push` ou `pull request`.

## Preparar a integração no GitHub

```bash
git switch feat/radiacode-independent
git push -u origin feat/radiacode-independent
```

Abra um pull request com base em `feat/go2-real-teleop` e comparação com
`feat/radiacode-independent`. Essa branch conserva a teleop do CEIA; os
scripts Radiacode não iniciam a odometria do robô físico. Arquivos de
`resultados/` e o ambiente `.venv-radiacode/` ficam fora do Git.

## Estrutura principal

```text
src/ares_mapper/       aplicação, adaptadores, mapa e estimador
config/                 cenários de simulação e perfil Go2 + FS-5000
tests/                  testes unitários e de integração
Dockerfile              imagens de simulação e hardware
compose.yaml            acesso à rede e aos detectores USB
ares                    iniciador de cada modo
.env.example            configuração local do hardware
```

## Dimensões do Go2

O mapa usa a pegada física do Go2 em pé: `0,70 × 0,31 m`, conforme as
[especificações oficiais](https://www.unitree.com/go2). Em mapas amplos, somente
o avatar recebe um tamanho mínimo na tela; a pose usada nas medições e na
inferência não é alterada.

## Limites atuais

O ARES é software experimental e não substitui um instrumento dosimétrico
certificado. A precisão depende da calibração do detector, da posição física do
FS-5000 no robô, dos timestamps e da qualidade da localização do Go2. O modelo
atual considera uma fonte pontual estática em ambiente 2D simples.

Documentação técnica adicional está em [`docs/`](docs/).

# ARES Radiation Mapper V0.4.10

O ARES combina a posição do Unitree Go2 com as leituras do FS-5000 e gera, em
tempo real, o percurso do robô, o gradiente radiológico do ambiente e a região
provável da fonte. A interface é acessada pelo navegador em
`http://127.0.0.1:8000`.

## Modos de execução

O iniciador público oferece somente dois modos completos:

| Comando | Posição | Radiação |
|---|---|---|
| `./ares simulation` | Go2 simulado | FS-5000 simulado |
| `./ares hardware` | Unitree Go2 real | FS-5000 real |

Não existe modo operacional com apenas um dos dois equipamentos reais. No modo
`hardware`, Go2 e FS-5000 são verificados e iniciados juntos.

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
```

## Execução local para desenvolvimento

Requer Python 3.10 a 3.12:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,fs5000]"
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
ruff check src tests
mypy src
```

O workflow em `.github/workflows/ci.yml` executa esses testes e também constrói
as imagens de simulação e hardware a cada `push` ou `pull request`.

## Publicar em um repositório novo

```bash
git init
git add .
git commit -m "Initial ARES Radiation Mapper release"
git branch -M main
git remote add origin URL_DO_REPOSITORIO
git push -u origin main
```

## Estrutura principal

```text
src/ares_mapper/       aplicação, adaptadores, mapa e estimador
config/                 cenários de simulação e perfil Go2 + FS-5000
tests/                  testes unitários e de integração
Dockerfile              imagens de simulação e hardware
compose.yaml            acesso à rede e ao USB
ares                    troca simples entre os dois modos
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

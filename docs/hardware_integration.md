# Integração com FS-5000 e Unitree Go2

As fronteiras de hardware estão implementadas, mas precisam de calibração e
ensaio físico antes de uso radiológico.

## FS-5000

O parser já reconhece:

```text
DR:0.18uSv/h;D:0.26uSv;CPS:0001;CPM:000033;AVG:0.23uSv/h;DT:0000000;S:0.00uSv;W:0
```

`FS5000SerialSource` usa `115200 baud`, pode localizar CH341 por VID/PID, inicia
somente a leitura contínua e registra UTC mais monotônico imediatamente ao
receber cada pacote. Comandos que alteram alarmes ou dose acumulada ficam
proibidos.

Instalação:

```bash
pip install -e ".[fs5000]"
ares-map inspect-fs5000 --port auto
```

## Go2

A primeira rota usa SDK2 e `rt/sportmodestate`. `position[3]` será tratado
como odometria local até que origem, reset e deriva sejam medidos. Quaternion e RPY
devem ser validados contra uma orientação conhecida.

No MuJoCo, a configuração esperada é interface `lo` e domínio DDS `1`. No robô
real, domínio `0` e a interface de rede conectada ao Go2.

Quando o SLAM estiver disponível, a fonte preferida passa a ser `map -> base`, para
que o mapa radiológico não herde a deriva da odometria.

Execução local completa, sempre com Go2 e FS-5000 juntos:

```bash
ares-map start \
  --mode hardware \
  --network-interface enp2s0 \
  --serial-port /dev/ttyUSB0
```

Para a execução reproduzível via Docker, configure `.env` e use
`./ares hardware`, conforme o README.

O processo falha de forma explícita se `unitree_sdk2py`, a interface DDS ou a
porta serial não estiverem disponíveis. A V0.3 não tenta substituir uma entrada
real ausente por dados simulados silenciosamente.

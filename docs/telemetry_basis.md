# Base de telemetria simulada

## FS-5000

O fluxo USB observado com o firmware original é iniciado pelo comando contínuo
`0x0E 0x01`, em serial a `115200 baud`. Cada pacote ASCII contém:

| Campo | Interpretação usada |
|---|---|
| `DR` | taxa de dose instantânea indicada, em µSv/h |
| `D` | dose acumulada desde o último reset, em µSv |
| `CPS` | contagens por segundo |
| `CPM` | contagens por minuto |
| `AVG` | taxa de dose média indicada, em µSv/h |
| `DT` | tempo da medição temporizada, em segundos |
| `S` | dose da medição temporizada, em µSv |
| `W` | estado de alarme |

Os registros reais disponíveis e o exemplo do código de aquisição apresentam uma
atualização aproximadamente a cada segundo. A simulação, portanto, publica a 1 Hz.

Referências:

- <https://gist.github.com/brookst/bdbede3a8d40eb8940a5b53e7ca1f6ce>
- <https://bosean.net/FS-5000-Nuclear-Radiation-Detector-2.html>

## Unitree Go2

O contrato oficial `SportModeState` contém:

```text
stamp | error_code | imu_state | mode | progress | gait_type |
foot_raise_height | position[3] | body_height | velocity[3] |
yaw_speed | range_obstacle[4] | foot_force[4] |
foot_position_body[12] | foot_speed_body[12]
```

O `IMUState` contém quaternion, giroscópio, acelerômetro, RPY e temperatura.

O exemplo oficial mostra mensagens consecutivas separadas por cerca de 50 ms.
Por isso a simulação usa 20 Hz para pose e movimento. Essa taxa é uma inferência
do exemplo, não uma garantia de firmware; na integração real deverá ser medida com
`ros2 topic hz /sportmodestate`.

As dimensões usadas para desenhar o retângulo são as dimensões oficiais em pé:
`0,70 × 0,31 m`.

Referências:

- <https://github.com/unitreerobotics/unitree_ros2>
- <https://github.com/unitreerobotics/unitree_ros2/blob/master/cyclonedds_ws/src/unitree/unitree_go/msg/SportModeState.msg>
- <https://github.com/unitreerobotics/unitree_ros2/blob/master/cyclonedds_ws/src/unitree/unitree_go/msg/IMUState.msg>
- <https://www.unitree.com/go2>
- <https://github.com/unitreerobotics/unitree_mujoco>

## Uso no mapa

Nem todo campo deve alterar diretamente a taxa de dose estimada. A V0.3 utiliza:

- posição e orientação para calcular a posição física do detector;
- 20 poses por segundo para reconstruir o trecho atravessado durante cada leitura;
- velocidade e permanência para estimar o espalhamento espacial da janela;
- qualidade da pose e sincronização como peso;
- exatamente um entre DR, CPS/Poisson ou CPS/negativo-binomial como observação
  primária de cada janela;
- CPM e AVG como validação e telemetria, sem duplicar a evidência primária;
- D como fechamento integral e, após perda de pacotes, recuperação fraca somente
  do trecho ausente;
- AVG, DT, S e W como telemetria e verificações de consistência.

Modo, marcha, IMU, obstáculos e dados dos pés permanecem registrados no contrato.
Eles não recebem peso radiológico arbitrário; poderão contribuir quando houver um
modelo explícito relacionando esses dados à qualidade da pose, vibração, geometria
ou sombreamento do detector.

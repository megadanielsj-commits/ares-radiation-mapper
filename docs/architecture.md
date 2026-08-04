# Arquitetura

O ARES Radiation Mapper é um monólito modular. Todas as partes executam no mesmo
processo, mas se comunicam por contratos tipados.

A V0.3 é um reconstrutor probabilístico completo que combina modelo físico, dados
observados, trajetória durante a janela de integração e incerteza. A visão
completa está em
[`final_system_vision.md`](final_system_vision.md).

## Fluxo principal

1. `PoseSource` produz poses observadas.
2. `RadiationSource` produz leituras radiológicas observadas.
3. `TemporalSynchronizer` reconstrói as duas fronteiras e todas as poses da
   janela radiológica.
4. `TrajectoryIntegrator` transforma o caminho da base na trajetória física do
   detector e calcula os pesos de quadratura.
5. `RegularizedParticleFilter` atualiza separadamente `H0` e `H1`.
6. `AdaptiveFieldReconstructor` propaga o posterior, atualiza a quadtree e soma
   somente resíduos com suporte local.
7. `MissionStore` persiste dados brutos, observações, posteriores, mapas e
   eventos.
8. FastAPI expõe REST, WebSocket e o painel local.

`SimulationClock` fornece uma linha do tempo controlável. Todos os timestamps
internos são inteiros em nanossegundos.

## Substituição por hardware

Simulação e hardware implementam as mesmas interfaces. O mapeamento não importa
dependências do FS-5000, Unitree ou ROS.

```text
Simulação:  SimulatedPoseSource + SimulatedRadiationSource
MuJoCo:     UnitreeSdk2PoseSource + SimulatedRadiationSource
Híbrida:    SimulatedPoseSource + FS5000SerialSource
Real:       UnitreeSdk2PoseSource + FS5000SerialSource
Com SLAM:   Ros2TfPoseSource + FS5000SerialSource
```

A aquisição, a atualização posterior e a reconstrução do mapa são workers
separados. A fila do mapa tem tamanho 1; um render antigo pode ser substituído,
mas uma observação radiológica nunca é descartada para atualizar a tela.

## Estado da missão

`READY -> RUNNING <-> PAUSED -> STOPPING -> COMPLETED`

Falhas impeditivas levam a `FAULT`. Pausar congela apenas o relógio simulado.

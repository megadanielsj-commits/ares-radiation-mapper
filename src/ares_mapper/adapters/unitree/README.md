# Adaptadores Unitree Go2

O adaptador SDK2 é funcional e carregado opcionalmente. O pacote principal não
instala SDK2 nem ROS 2.

Ordem prevista:

1. `UnitreeSdk2PoseSource`: `rt/sportmodestate`, inicialmente em `odom`;
2. o mesmo adaptador com Unitree MuJoCo: interface `lo`, domínio DDS `1`;
3. Go2 real: interface de rede conectada ao Go2, domínio DDS `0`;
4. `UnitreeRos2SportModePoseSource`;
5. `Ros2TfPoseSource` para a transformação corrigida `map -> base`.

Antes da integração física, devem ser confirmados a ordem do quaternion, a origem,
o reset e a deriva de `position[3]`.

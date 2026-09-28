"""Testes do sincronizador de pose x leitura."""
import math

import pytest

from ares.modelos import Leitura, Pose
from ares.sincronizacao import Sincronizador


def _leitura(ts, dr_usvh=0.1, cpm=100, cps=2, dose_usv=0.001, detector_id="fs5000-1"):
    return Leitura(
        ts=ts, dr_usvh=dr_usvh, cpm=cpm, cps=cps, dose_usv=dose_usv, detector_id=detector_id
    )


def test_interpola_posicao_no_meio_de_duas_poses():
    sinc = Sincronizador(latencia_s=0.5, lacuna_max_s=1.0)
    sinc.adicionar_pose(Pose(ts=0.0, x=0.0, y=0.0, yaw=0.0))
    sinc.adicionar_pose(Pose(ts=2.0, x=2.0, y=0.0, yaw=0.0))
    sinc.adicionar_leitura(_leitura(ts=1.5, dr_usvh=0.5, cpm=200))

    amostras = sinc.drenar()

    assert len(amostras) == 1
    amostra = amostras[0]
    assert amostra.x == pytest.approx(1.0)
    assert amostra.y == pytest.approx(0.0)
    assert amostra.dr_usvh == 0.5
    assert amostra.cpm == 200
    assert amostra.lacuna_pose_s == pytest.approx(1.0)
    assert sinc.descartadas == 0
    assert sinc.pendentes == 0


def test_interpola_yaw_pelo_caminho_mais_curto_atravessando_pi():
    # o caminho mais curto entre 3.0 rad e -3.0 rad passa por pi (não por 0);
    # o yaw interpolado no meio deve ficar perto de pi, e isso se reflete no
    # offset do detector rotacionado (verificado indiretamente via posição).
    sinc = Sincronizador(offset_detector=(1.0, 0.0), latencia_s=0.5, lacuna_max_s=1.0)
    sinc.adicionar_pose(Pose(ts=0.0, x=0.0, y=0.0, yaw=3.0))
    sinc.adicionar_pose(Pose(ts=2.0, x=0.0, y=0.0, yaw=-3.0))
    sinc.adicionar_leitura(_leitura(ts=1.5))

    amostras = sinc.drenar()

    assert len(amostras) == 1
    # yaw médio ~ pi -> offset (1, 0) rotacionado vira ~ (-1, 0)
    assert amostras[0].x == pytest.approx(-1.0, abs=1e-3)
    assert amostras[0].y == pytest.approx(0.0, abs=1e-3)


def test_offset_detector_rotacionado_pelo_yaw():
    sinc = Sincronizador(offset_detector=(1.0, 0.0), latencia_s=0.5, lacuna_max_s=1.0)
    sinc.adicionar_pose(Pose(ts=0.0, x=5.0, y=5.0, yaw=math.pi / 2))
    sinc.adicionar_pose(Pose(ts=2.0, x=5.0, y=5.0, yaw=math.pi / 2))
    sinc.adicionar_leitura(_leitura(ts=1.5))

    amostras = sinc.drenar()

    assert len(amostras) == 1
    assert amostras[0].x == pytest.approx(5.0, abs=1e-9)
    assert amostras[0].y == pytest.approx(6.0, abs=1e-9)


def test_leitura_mais_nova_fica_pendente_e_sai_quando_chega_pose():
    sinc = Sincronizador(latencia_s=0.5, lacuna_max_s=1.0)
    sinc.adicionar_pose(Pose(ts=0.0, x=0.0, y=0.0, yaw=0.0))
    sinc.adicionar_leitura(_leitura(ts=0.6))  # t efetivo = 0.1, > última pose (0.0)

    amostras = sinc.drenar()
    assert amostras == []
    assert sinc.pendentes == 1
    assert sinc.descartadas == 0

    sinc.adicionar_pose(Pose(ts=0.3, x=1.0, y=0.0, yaw=0.0))
    amostras = sinc.drenar()

    assert len(amostras) == 1
    assert amostras[0].x == pytest.approx(1.0 / 3.0)
    assert sinc.pendentes == 0
    assert sinc.descartadas == 0


def test_lacuna_grande_descarta_leitura():
    sinc = Sincronizador(latencia_s=0.5, lacuna_max_s=0.5)
    sinc.adicionar_pose(Pose(ts=0.0, x=0.0, y=0.0, yaw=0.0))
    sinc.adicionar_pose(Pose(ts=10.0, x=0.0, y=0.0, yaw=0.0))
    sinc.adicionar_leitura(_leitura(ts=5.5))  # t efetivo = 5.0, lacuna = 5.0

    amostras = sinc.drenar()

    assert amostras == []
    assert sinc.descartadas == 1
    assert sinc.pendentes == 0


def test_poda_historico_descarta_leitura_antiga_apos_poda():
    sinc = Sincronizador(latencia_s=0.5, lacuna_max_s=10.0, historico_s=1.0)
    sinc.adicionar_pose(Pose(ts=0.0, x=0.0, y=0.0, yaw=0.0))
    sinc.adicionar_pose(Pose(ts=0.5, x=0.0, y=0.0, yaw=0.0))
    # esta pose empurra o limite de poda para 1.0 (2.0 - historico_s),
    # descartando as poses anteriores (ts=0.0 e ts=0.5)
    sinc.adicionar_pose(Pose(ts=2.0, x=0.0, y=0.0, yaw=0.0))

    sinc.adicionar_leitura(_leitura(ts=1.0))  # t efetivo = 0.5, sem pose "antes" após poda

    amostras = sinc.drenar()

    assert amostras == []
    assert sinc.descartadas == 1


def test_adicionar_pose_ignora_ts_nao_crescente():
    sinc = Sincronizador(latencia_s=0.0)
    sinc.adicionar_pose(Pose(ts=1.0, x=1.0, y=0.0, yaw=0.0))
    sinc.adicionar_pose(Pose(ts=1.0, x=99.0, y=99.0, yaw=0.0))
    sinc.adicionar_pose(Pose(ts=0.5, x=-5.0, y=-5.0, yaw=0.0))
    sinc.adicionar_pose(Pose(ts=2.0, x=3.0, y=0.0, yaw=0.0))

    sinc.adicionar_leitura(_leitura(ts=1.5))
    amostras = sinc.drenar()

    assert len(amostras) == 1
    assert amostras[0].x == pytest.approx(2.0)


def test_pendentes_sao_limitadas_quando_robo_desconecta_sem_poses():
    # detector a 1 Hz por ~1000s sem nenhuma pose chegando (robô desconectado):
    # a fila de pendentes não pode crescer sem limite.
    sinc = Sincronizador(latencia_s=0.0, historico_s=30.0)

    for i in range(1000):
        sinc.adicionar_leitura(_leitura(ts=float(i)))

    assert sinc.pendentes <= 31
    assert sinc.descartadas >= 969
    assert sinc.pendentes + sinc.descartadas == 1000


def test_max_pendentes_limita_fila_mesmo_dentro_do_historico():
    sinc = Sincronizador(latencia_s=0.0, historico_s=1000.0, max_pendentes=5)

    for i in range(10):
        sinc.adicionar_leitura(_leitura(ts=float(i)))

    assert sinc.pendentes == 5
    assert sinc.descartadas == 5


def test_empate_exato_no_timestamp_da_pose_usa_posicao_da_pose_sem_lacuna():
    sinc = Sincronizador(latencia_s=0.0, lacuna_max_s=1.0)
    sinc.adicionar_pose(Pose(ts=0.0, x=0.0, y=0.0, yaw=0.0))
    sinc.adicionar_pose(Pose(ts=1.0, x=7.0, y=3.0, yaw=0.0))
    sinc.adicionar_pose(Pose(ts=2.0, x=20.0, y=20.0, yaw=0.0))
    sinc.adicionar_leitura(_leitura(ts=1.0))  # t efetivo == ts da pose do meio

    amostras = sinc.drenar()

    assert len(amostras) == 1
    assert amostras[0].x == pytest.approx(7.0)
    assert amostras[0].y == pytest.approx(3.0)
    assert amostras[0].lacuna_pose_s == pytest.approx(0.0)

"""Testes dos modelos de dados centrais (Pose, Leitura, Amostra)."""
import dataclasses

import pytest

from ares.modelos import Amostra, Leitura, Pose


def test_pose_campos_e_imutavel():
    pose = Pose(ts=1.0, x=0.5, y=-0.3, yaw=1.57)

    assert pose.ts == 1.0
    assert pose.x == 0.5
    assert pose.y == -0.3
    assert pose.yaw == 1.57

    with pytest.raises(dataclasses.FrozenInstanceError):
        pose.x = 1.0


def test_leitura_campos_e_imutavel():
    leitura = Leitura(
        ts=10.0,
        dr_usvh=0.12,
        cpm=340,
        cps=6,
        dose_usv=0.002,
        detector_id="fs5000-1",
    )

    assert leitura.ts == 10.0
    assert leitura.dr_usvh == 0.12
    assert leitura.cpm == 340
    assert leitura.cps == 6
    assert leitura.dose_usv == 0.002
    assert leitura.detector_id == "fs5000-1"

    with pytest.raises(dataclasses.FrozenInstanceError):
        leitura.cpm = 0


def test_amostra_campos_e_imutavel():
    amostra = Amostra(
        ts=10.0,
        x=1.2,
        y=3.4,
        dr_usvh=0.12,
        cpm=340,
        lacuna_pose_s=0.05,
    )

    assert amostra.ts == 10.0
    assert amostra.x == 1.2
    assert amostra.y == 3.4
    assert amostra.dr_usvh == 0.12
    assert amostra.cpm == 340
    assert amostra.lacuna_pose_s == 0.05

    with pytest.raises(dataclasses.FrozenInstanceError):
        amostra.dr_usvh = 0.0

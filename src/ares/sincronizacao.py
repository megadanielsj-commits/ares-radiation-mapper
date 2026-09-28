"""Sincronização de leituras do detector com a pose (odometria) do robô."""
import math
from typing import List, Optional, Tuple

from .modelos import Amostra, Leitura, Pose


def _diferenca_angular(destino: float, origem: float) -> float:
    """Menor diferença angular (em rad) de `origem` até `destino`, em (-pi, pi]."""
    return (destino - origem + math.pi) % (2 * math.pi) - math.pi


class Sincronizador:
    """Combina poses do robô com leituras do detector em amostras posicionadas.

    Poses são recebidas em ordem crescente de tempo (poses com `ts` menor ou
    igual à última recebida são ignoradas). Leituras são enfileiradas e só
    viram `Amostra` quando existem poses antes e depois do instante efetivo
    da leitura (`ts - latencia_s`).
    """

    def __init__(
        self,
        offset_detector: Tuple[float, float] = (0.0, 0.0),
        latencia_s: float = 0.5,
        lacuna_max_s: float = 0.5,
        historico_s: float = 30.0,
    ) -> None:
        self._offset = offset_detector
        self._latencia_s = latencia_s
        self._lacuna_max_s = lacuna_max_s
        self._historico_s = historico_s
        self._poses: List[Pose] = []
        self._pendentes: List[Leitura] = []
        self.descartadas = 0

    def adicionar_pose(self, pose: Pose) -> None:
        if self._poses and pose.ts <= self._poses[-1].ts:
            return
        self._poses.append(pose)
        limite = pose.ts - self._historico_s
        while len(self._poses) > 1 and self._poses[0].ts < limite:
            self._poses.pop(0)

    def adicionar_leitura(self, leitura: Leitura) -> None:
        self._pendentes.append(leitura)

    @property
    def pendentes(self) -> int:
        return len(self._pendentes)

    def drenar(self) -> List[Amostra]:
        amostras: List[Amostra] = []
        restantes: List[Leitura] = []

        for leitura in self._pendentes:
            t = leitura.ts - self._latencia_s
            amostra = self._processar(leitura, t)
            if amostra is _PENDENTE:
                restantes.append(leitura)
            elif amostra is _DESCARTADA:
                self.descartadas += 1
            else:
                amostras.append(amostra)

        self._pendentes = restantes
        return amostras

    def _processar(self, leitura: Leitura, t: float):
        poses = self._poses
        if not poses:
            return _PENDENTE

        if t > poses[-1].ts:
            return _PENDENTE

        antes: Optional[Pose] = None
        depois: Optional[Pose] = None
        for pose in poses:
            if pose.ts <= t:
                antes = pose
            if pose.ts >= t:
                depois = pose
                break

        if antes is None or depois is None:
            # sem pose anterior a `t` (fora do histórico retido)
            return _DESCARTADA

        lacuna = max(t - antes.ts, depois.ts - t)
        if lacuna > self._lacuna_max_s:
            return _DESCARTADA

        if antes.ts == depois.ts:
            fracao = 0.0
        else:
            fracao = (t - antes.ts) / (depois.ts - antes.ts)

        x = antes.x + fracao * (depois.x - antes.x)
        y = antes.y + fracao * (depois.y - antes.y)
        dyaw = _diferenca_angular(depois.yaw, antes.yaw)
        yaw = antes.yaw + fracao * dyaw

        dx, dy = self._offset
        cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
        rx = dx * cos_yaw - dy * sin_yaw
        ry = dx * sin_yaw + dy * cos_yaw

        return Amostra(
            ts=leitura.ts,
            x=x + rx,
            y=y + ry,
            dr_usvh=leitura.dr_usvh,
            cpm=leitura.cpm,
            lacuna_pose_s=lacuna,
        )


class _Sentinela:
    __slots__ = ()


_PENDENTE = _Sentinela()
_DESCARTADA = _Sentinela()

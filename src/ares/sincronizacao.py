"""Sincronização de leituras do detector com a pose (odometria) do robô."""
import bisect
import math
from collections import deque
from typing import Deque, List, Optional, Tuple

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

    Leituras pendentes são limitadas para não crescer sem limite quando o
    robô fica desconectado (sem poses chegando) enquanto o detector continua
    enviando leituras: uma leitura pendente é descartada quando fica mais
    velha que `historico_s` em relação à leitura mais nova já recebida, e a
    fila também tem um teto rígido de `max_pendentes` (descartando as mais
    antigas quando excedido).
    """

    def __init__(
        self,
        offset_detector: Tuple[float, float] = (0.0, 0.0),
        latencia_s: float = 0.5,
        lacuna_max_s: float = 0.5,
        historico_s: float = 30.0,
        max_pendentes: int = 600,
    ) -> None:
        self._offset = offset_detector
        self._latencia_s = latencia_s
        self._lacuna_max_s = lacuna_max_s
        self._historico_s = historico_s
        self._max_pendentes = max_pendentes
        self._poses: List[Pose] = []
        self._poses_ts: List[float] = []
        self._pendentes: Deque[Leitura] = deque()
        self._newest_leitura_ts: Optional[float] = None
        self.descartadas = 0

    def adicionar_pose(self, pose: Pose) -> None:
        if self._poses and pose.ts <= self._poses[-1].ts:
            return
        self._poses.append(pose)
        self._poses_ts.append(pose.ts)
        limite = pose.ts - self._historico_s
        while len(self._poses) > 1 and self._poses[0].ts < limite:
            self._poses.pop(0)
            self._poses_ts.pop(0)

    def adicionar_leitura(self, leitura: Leitura) -> None:
        self._pendentes.append(leitura)
        if self._newest_leitura_ts is None or leitura.ts > self._newest_leitura_ts:
            self._newest_leitura_ts = leitura.ts

        limite = self._newest_leitura_ts - self._historico_s
        while self._pendentes and self._pendentes[0].ts < limite:
            self._pendentes.popleft()
            self.descartadas += 1

        while len(self._pendentes) > self._max_pendentes:
            self._pendentes.popleft()
            self.descartadas += 1

    @property
    def pendentes(self) -> int:
        return len(self._pendentes)

    def drenar(self) -> List[Amostra]:
        amostras: List[Amostra] = []
        restantes: Deque[Leitura] = deque()

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
        poses_ts = self._poses_ts
        if not poses:
            return _PENDENTE

        if t > poses_ts[-1]:
            return _PENDENTE

        # idx_antes: índice da última pose com ts <= t (bisect_right conta
        # também um empate exato, então -1 aponta pra ela mesma).
        idx_antes = bisect.bisect_right(poses_ts, t) - 1
        # idx_depois: índice da primeira pose com ts >= t.
        idx_depois = bisect.bisect_left(poses_ts, t)

        antes: Optional[Pose] = poses[idx_antes] if idx_antes >= 0 else None
        depois: Optional[Pose] = poses[idx_depois] if idx_depois < len(poses) else None

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
            cps=leitura.cps,
            lacuna_pose_s=lacuna,
        )


class _Sentinela:
    __slots__ = ()


_PENDENTE = _Sentinela()
_DESCARTADA = _Sentinela()

"""Robô simulado: integra cinemática simples e publica pose periodicamente."""
import asyncio
import logging
import math
import time
from typing import Callable, List, Optional

from ..modelos import Pose

logger = logging.getLogger(__name__)


class RoboSimulado:
    """Robô cinemático simples (implementa o Protocol `Robo`).

    Mantém x, y, yaw no referencial `odom`. `mover` só guarda as velocidades
    (já limitadas); um laço interno a `frequencia_hz` integra a cinemática
    (vx, vy no referencial do robô, vyaw) e publica a `Pose` resultante a cada
    passo. Começa em pé, na origem.
    """

    def __init__(
        self,
        vx_max: float = 0.5,
        vy_max: float = 0.3,
        vyaw_max: float = 1.0,
        frequencia_hz: float = 20.0,
    ) -> None:
        self._vx_max = vx_max
        self._vy_max = vy_max
        self._vyaw_max = vyaw_max
        self._dt = 1.0 / frequencia_hz

        self.x = 0.0
        self.y = 0.0
        self.yaw = 0.0
        self.em_pe = True

        self._vx = 0.0
        self._vy = 0.0
        self._vyaw = 0.0

        self._assinantes: List[Callable[[Pose], None]] = []
        self._tarefa: Optional[asyncio.Task] = None
        self._erro: Optional[str] = None

    async def iniciar(self) -> None:
        if self._tarefa is None:
            self._tarefa = asyncio.create_task(self._laco())

    async def encerrar(self) -> None:
        await self.parar_movimento()
        tarefa, self._tarefa = self._tarefa, None
        if tarefa is not None:
            tarefa.cancel()
            try:
                await tarefa
            except asyncio.CancelledError:
                pass

    def assinar_pose(self, cb: Callable[[Pose], None]) -> None:
        self._assinantes.append(cb)

    async def mover(self, vx: float, vy: float, vyaw: float) -> None:
        self._vx = _limitar(vx, self._vx_max)
        self._vy = _limitar(vy, self._vy_max)
        self._vyaw = _limitar(vyaw, self._vyaw_max)

    async def parar_movimento(self) -> None:
        self._vx = 0.0
        self._vy = 0.0
        self._vyaw = 0.0

    async def levantar(self) -> None:
        self.em_pe = True

    async def deitar(self) -> None:
        self.em_pe = False
        await self.parar_movimento()

    def estado(self) -> dict:
        return {"conectado": True, "erro": self._erro, "em_pe": self.em_pe}

    async def _laco(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._dt)
                if self.em_pe:
                    self._integrar()
                self._publicar(Pose(ts=time.time(), x=self.x, y=self.y, yaw=self.yaw))
        except asyncio.CancelledError:
            raise

    def _integrar(self) -> None:
        cos_yaw = math.cos(self.yaw)
        sin_yaw = math.sin(self.yaw)
        self.x += (self._vx * cos_yaw - self._vy * sin_yaw) * self._dt
        self.y += (self._vx * sin_yaw + self._vy * cos_yaw) * self._dt
        self.yaw += self._vyaw * self._dt

    def _publicar(self, pose: Pose) -> None:
        for cb in list(self._assinantes):
            try:
                cb(pose)
            except Exception:
                logger.exception("erro num assinante de pose")


def _limitar(valor: float, maximo: float) -> float:
    return max(-maximo, min(maximo, valor))

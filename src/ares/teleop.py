"""Controlador de teleoperação: velocidade com heartbeat, watchdog e limites.

O navegador manda a velocidade desejada continuamente (heartbeat ≥ 5 Hz);
`definir` só guarda o valor (já saturado) e marca a hora do último heartbeat.
Um laço interno, a `hz`, publica `mover` enquanto a velocidade for diferente
de zero e chama `parar_movimento` uma única vez na transição para zero (seja
por `definir(0, 0, 0)`, por `parar()` ou pelo watchdog ao vencer `watchdog_s`
sem heartbeat). Erros do robô ficam em `ultimo_erro` e não derrubam o laço —
segurança física: sem heartbeat fresco o robô para, sempre.
"""
import asyncio
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)


def _limitar(valor: float, maximo: float) -> float:
    return max(-maximo, min(maximo, valor))


class Teleop:
    """Controla um `Robo` (real ou simulado) com watchdog de velocidade."""

    def __init__(
        self,
        robo,
        vx_max: float,
        vy_max: float,
        vyaw_max: float,
        watchdog_s: float = 0.5,
        hz: float = 5.0,
    ) -> None:
        self.robo = robo
        self._vx_max = vx_max
        self._vy_max = vy_max
        self._vyaw_max = vyaw_max
        self._watchdog_s = watchdog_s
        self._hz = hz

        self._vx = 0.0
        self._vy = 0.0
        self._vyaw = 0.0
        self._ultimo_heartbeat = 0.0
        self._movendo = False

        self.ultimo_erro: Optional[str] = None
        self._tarefa: Optional[asyncio.Task] = None

    def definir(self, vx: float, vy: float, vyaw: float) -> None:
        """Define a velocidade desejada (já saturada) e marca o heartbeat."""
        self._vx = _limitar(vx, self._vx_max)
        self._vy = _limitar(vy, self._vy_max)
        self._vyaw = _limitar(vyaw, self._vyaw_max)
        self._ultimo_heartbeat = time.time()

    async def parar(self) -> None:
        """PARAR imediato: zera a velocidade e manda `parar_movimento` na hora."""
        self._vx = 0.0
        self._vy = 0.0
        self._vyaw = 0.0
        await self._parar_movimento_uma_vez()

    async def iniciar(self) -> None:
        """Sobe o laço de teleop (chamar de novo enquanto roda não faz nada)."""
        if self._tarefa is not None and not self._tarefa.done():
            return
        self._tarefa = asyncio.create_task(self._laco())

    async def encerrar(self) -> None:
        """Cancela o laço e garante que o robô fique parado."""
        if self._tarefa is not None:
            self._tarefa.cancel()
            try:
                await self._tarefa
            except asyncio.CancelledError:
                pass
            self._tarefa = None
        await self.parar()

    # ------------------------------------------------------------------ laço
    async def _laco(self) -> None:
        try:
            while True:
                await asyncio.sleep(1.0 / self._hz)
                if (time.time() - self._ultimo_heartbeat) >= self._watchdog_s:
                    self._vx = 0.0
                    self._vy = 0.0
                    self._vyaw = 0.0

                ativo = bool(self._vx or self._vy or self._vyaw)
                if ativo:
                    try:
                        await self.robo.mover(self._vx, self._vy, self._vyaw)
                    except Exception as e:
                        self.ultimo_erro = str(e)
                        log.exception("erro ao mover o robô")
                    self._movendo = True
                elif self._movendo:
                    await self._parar_movimento_uma_vez()
        except asyncio.CancelledError:
            raise

    async def _parar_movimento_uma_vez(self) -> None:
        try:
            await self.robo.parar_movimento()
        except Exception as e:
            self.ultimo_erro = str(e)
            log.exception("erro ao parar o robô")
        self._movendo = False

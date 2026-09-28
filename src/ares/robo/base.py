"""Interface (Protocol) que todo robô — simulado ou real — deve implementar."""
from typing import Callable, Protocol

from ..modelos import Pose


class Robo(Protocol):
    """Robô teleoperável que publica sua pose no referencial `odom`."""

    async def iniciar(self) -> None:
        """Prepara o robô (conecta, inicia laços internos)."""
        ...

    async def encerrar(self) -> None:
        """Manda parar (StopMove, se possível) e fecha tudo."""
        ...

    def assinar_pose(self, cb: Callable[[Pose], None]) -> None:
        """Registra um callback chamado a cada nova `Pose` publicada."""
        ...

    async def mover(self, vx: float, vy: float, vyaw: float) -> None:
        """Define as velocidades desejadas (referencial do robô)."""
        ...

    async def parar_movimento(self) -> None:
        """Zera as velocidades imediatamente."""
        ...

    async def levantar(self) -> None:
        """Coloca o robô em pé."""
        ...

    async def deitar(self) -> None:
        """Deita o robô."""
        ...

    def estado(self) -> dict:
        """Estado atual: `{"conectado": bool, "erro": str | None, ...}`."""
        ...

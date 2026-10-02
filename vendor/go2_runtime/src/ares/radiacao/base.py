"""Interface (Protocol) que toda fonte de leituras de radiação deve implementar."""
from typing import Callable, Protocol

from ..modelos import Leitura


class FonteRadiacao(Protocol):
    """Fonte de leituras do detector (simulada ou o serviço real do FS-5000)."""

    async def iniciar(self) -> None:
        """Prepara a fonte (conecta, inicia laços internos)."""
        ...

    async def encerrar(self) -> None:
        """Encerra tudo (fecha conexões, cancela tarefas)."""
        ...

    def assinar(self, cb: Callable[[Leitura], None]) -> None:
        """Registra um callback chamado a cada nova `Leitura` publicada."""
        ...

    def estado(self) -> dict:
        """Estado atual: `{"conectado": bool, "erro": str | None, "detector_id": str | None}`."""
        ...

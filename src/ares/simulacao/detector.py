"""Detector simulado: amostra o campo de radiação e publica leituras periódicas."""
import asyncio
import logging
import time
from collections import deque
from typing import Callable, Deque, List, Optional, Tuple

import numpy as np

from ..modelos import Leitura
from .campo import CampoRadiacao

logger = logging.getLogger(__name__)


class DetectorSimulado:
    """Detector simulado (implementa o Protocol `FonteRadiacao`).

    A cada `periodo_s`, sorteia uma contagem Poisson com taxa esperada
    `campo.taxa(x, y) * cps_por_usvh` para o período, usando a posição
    corrente devolvida por `posicao_detector()` (ou pula o período se ela for
    `None`, ex.: pose do robô ainda não chegou). Mantém uma janela móvel das
    últimas contagens (tamanho `janela_s / periodo_s`) para estimar a taxa de
    dose (`dr_usvh`) e as contagens por minuto (`cpm`), e acumula a dose
    total (`dose_usv`).
    """

    def __init__(
        self,
        campo: CampoRadiacao,
        posicao_detector: Callable[[], Optional[Tuple[float, float]]],
        periodo_s: float = 1.0,
        cps_por_usvh: float = 2.6,
        janela_s: float = 5.0,
        semente: Optional[int] = None,
        detector_id: str = "sim-1",
    ) -> None:
        self._campo = campo
        self._posicao_detector = posicao_detector
        self._periodo_s = periodo_s
        self._cps_por_usvh = cps_por_usvh
        self._janela_s = janela_s
        self._detector_id = detector_id

        self._rng = np.random.default_rng(semente)
        n_janela = max(1, round(janela_s / periodo_s))
        self._janela: Deque[int] = deque(maxlen=n_janela)
        self._dose_usv = 0.0

        self._assinantes: List[Callable[[Leitura], None]] = []
        self._tarefa: Optional[asyncio.Task] = None
        self._erro: Optional[str] = None

    async def iniciar(self) -> None:
        if self._tarefa is None:
            self._tarefa = asyncio.create_task(self._laco())

    async def encerrar(self) -> None:
        tarefa, self._tarefa = self._tarefa, None
        if tarefa is not None:
            tarefa.cancel()
            try:
                await tarefa
            except asyncio.CancelledError:
                pass

    def assinar(self, cb: Callable[[Leitura], None]) -> None:
        self._assinantes.append(cb)

    def estado(self) -> dict:
        return {
            "conectado": True,
            "erro": self._erro,
            "detector_id": self._detector_id,
        }

    async def _laco(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._periodo_s)
                self._amostrar()
        except asyncio.CancelledError:
            raise

    def _amostrar(self) -> None:
        posicao = self._posicao_detector()
        if posicao is None:
            return

        x, y = posicao
        taxa_usvh = self._campo.taxa(x, y)
        media_contagem = max(0.0, taxa_usvh * self._cps_por_usvh * self._periodo_s)
        contagem = int(self._rng.poisson(media_contagem))
        self._janela.append(contagem)

        contagens_janela = sum(self._janela)
        dr_usvh = contagens_janela / (self._janela_s * self._cps_por_usvh)
        cps = round(contagem / self._periodo_s)
        cpm = round(dr_usvh * self._cps_por_usvh * 60.0)
        self._dose_usv += (contagem / self._cps_por_usvh) * (self._periodo_s / 3600.0)

        leitura = Leitura(
            ts=time.time(),
            dr_usvh=dr_usvh,
            cpm=cpm,
            cps=cps,
            dose_usv=self._dose_usv,
            detector_id=self._detector_id,
        )
        self._publicar(leitura)

    def _publicar(self, leitura: Leitura) -> None:
        for cb in list(self._assinantes):
            try:
                cb(leitura)
            except Exception:
                logger.exception("erro num assinante de leitura")

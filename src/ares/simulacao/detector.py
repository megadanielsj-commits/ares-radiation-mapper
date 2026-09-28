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
    """Detector simulado (implementa o Protocol `FonteRadiacao`) que imita o FS-5000.

    A cada `periodo_s`, usando a posição corrente devolvida por
    `posicao_detector()` (ou pulando o período se ela for `None`, ex.: pose do
    robô ainda não chegou):

    - `cps`: contagem Poisson independente de 1 s com média
      `campo.taxa(x, y) * cps_por_usvh`. É sempre uma contagem de 1 s, mesmo
      com `periodo_s` ≠ 1 (períodos curtos só aceleram os testes);
    - `dr_usvh`: média móvel das últimas `janela_s / periodo_s` contagens
      dividida por `cps_por_usvh` — suave e atrasada como o DR do aparelho
      real (média de ~30 s, autocorrelação alta entre leituras seguidas);
    - `cpm`: `round(dr_usvh * cps_por_usvh * 60)`, isto é, a mesma média
      móvel expressa em contagens por minuto;
    - `dose_usv`: acumulada com `cps * periodo_s / (cps_por_usvh * 3600)`,
      cuja média é `taxa * periodo_s / 3600` (independe do período).
    """

    def __init__(
        self,
        campo: CampoRadiacao,
        posicao_detector: Callable[[], Optional[Tuple[float, float]]],
        periodo_s: float = 1.0,
        cps_por_usvh: float = 2.6,
        janela_s: float = 30.0,
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
        media_cps = max(0.0, taxa_usvh * self._cps_por_usvh)
        cps = int(self._rng.poisson(media_cps))
        self._janela.append(cps)

        dr_usvh = sum(self._janela) / (len(self._janela) * self._cps_por_usvh)
        cpm = round(dr_usvh * self._cps_por_usvh * 60.0)
        self._dose_usv += cps * self._periodo_s / (self._cps_por_usvh * 3600.0)

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

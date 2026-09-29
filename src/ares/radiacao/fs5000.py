"""Cliente do serviço FS-5000 (WS local): fonte de radiação real (implementa `FonteRadiacao`).

Conecta em `url` (padrão `ws://127.0.0.1:1096/ws`), lê o snapshot inicial e os
eventos publicados pelo serviço (`estado`, `leitura`), escolhe o aparelho
(o configurado, senão o primeiro que estiver `conectado`, trocando se ele
desconectar e houver outro conectado) e converte os eventos `leitura` do
aparelho escolhido em `Leitura`. Reconecta sozinho com backoff exponencial.
Não manda nada além do handshake da conexão (sem header Origin).
"""
import asyncio
import json
import logging
from typing import Callable, Optional

from websockets.asyncio.client import connect

from ..modelos import Leitura

log = logging.getLogger(__name__)

BACKOFF_MIN_S = 1.0
BACKOFF_MAX_S = 10.0


class ClienteFS5000:
    """Fonte de radiação real: cliente do WS do serviço `FS_5000_quickstart`."""

    def __init__(
        self,
        url: str = "ws://127.0.0.1:1096/ws",
        aparelho: Optional[str] = None,
        backoff_min: float = BACKOFF_MIN_S,
        backoff_max: float = BACKOFF_MAX_S,
    ) -> None:
        self._url = url
        self._aparelho_configurado = aparelho
        self._backoff_min = backoff_min
        self._backoff_max = backoff_max

        self._callbacks: list[Callable[[Leitura], None]] = []
        self._tarefa: Optional[asyncio.Task] = None

        self._conectado = False
        self._erro: Optional[str] = None
        self._aparelho_id: Optional[str] = aparelho
        self._estados_aparelhos: dict[str, str] = {}

        self.eventos_invalidos = 0

    # ------------------------------------------------------------------ API pública
    def assinar(self, cb: Callable[[Leitura], None]) -> None:
        """Registra um callback chamado a cada nova `Leitura` publicada."""
        self._callbacks.append(cb)

    def estado(self) -> dict:
        """`{"conectado": bool, "erro": str | None, "detector_id": str | None}`.

        `conectado` exige o WS aberto E o aparelho escolhido com `estado=="conectado"`.
        """
        aparelho_conectado = (
            self._aparelho_id is not None
            and self._estados_aparelhos.get(self._aparelho_id) == "conectado"
        )
        return {
            "conectado": self._conectado and aparelho_conectado,
            "erro": self._erro,
            "detector_id": self._aparelho_id,
        }

    async def iniciar(self) -> None:
        """Inicia a tarefa de fundo que conecta e reconecta ao serviço.

        Chamar de novo enquanto a tarefa já está rodando não faz nada (evita
        vazar tarefas órfãs).
        """
        if self._tarefa is not None and not self._tarefa.done():
            return
        self._tarefa = asyncio.create_task(self._laco())

    async def encerrar(self) -> None:
        """Cancela e aguarda a tarefa de fundo."""
        if self._tarefa is not None:
            self._tarefa.cancel()
            try:
                await self._tarefa
            except asyncio.CancelledError:
                pass
            self._tarefa = None
        self._conectado = False

    # ------------------------------------------------------------------ laço de conexão
    async def _laco(self) -> None:
        espera = self._backoff_min
        while True:
            recebeu_mensagem_valida = False
            try:
                async with connect(self._url) as ws:
                    self._conectado = True
                    self._erro = None
                    recebeu_mensagem_valida = await self._sessao(ws)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._erro = str(e)
                log.warning("conexão com o FS-5000 caiu: %s", e)
            self._conectado = False
            await asyncio.sleep(espera)
            # só reseta o backoff se a sessão chegou a receber algo válido do
            # servidor (snapshot ou evento); senão um servidor que aceita e
            # fecha na hora causaria um loop de reconexão sem espera real.
            if recebeu_mensagem_valida:
                espera = self._backoff_min
            else:
                espera = min(espera * 2, self._backoff_max)

    async def _sessao(self, ws) -> bool:
        """Processa mensagens da sessão. Retorna se alguma foi válida (snapshot/evento)."""
        recebeu_mensagem_valida = False
        async for mensagem in ws:
            try:
                evento = json.loads(mensagem)
                if not isinstance(evento, dict):
                    raise ValueError("evento não é um objeto")
            except (ValueError, TypeError):
                self.eventos_invalidos += 1
                continue
            recebeu_mensagem_valida = True
            try:
                self._processar_evento(evento)
            except Exception:
                self.eventos_invalidos += 1
                log.exception(
                    "erro ao processar evento do FS-5000; sessão mantida"
                )
        return recebeu_mensagem_valida

    # ------------------------------------------------------------------ processamento
    def _processar_evento(self, evento: dict) -> None:
        tipo = evento.get("tipo")
        if tipo == "snapshot":
            for aparelho in evento.get("dados") or []:
                self._registrar_estado_aparelho(aparelho)
            self._escolher_aparelho()
        elif tipo == "estado":
            aparelho = evento.get("dados")
            if isinstance(aparelho, dict):
                self._registrar_estado_aparelho(aparelho)
                self._escolher_aparelho()
            else:
                self.eventos_invalidos += 1
        elif tipo == "leitura":
            self._processar_leitura(evento)
        # "alarme" e tipos desconhecidos são ignorados (não são erro de protocolo).

    def _registrar_estado_aparelho(self, aparelho: dict) -> None:
        id_ = aparelho.get("id")
        if id_ is None:
            self.eventos_invalidos += 1
            return
        self._estados_aparelhos[id_] = aparelho.get("estado")

    def _escolher_aparelho(self) -> None:
        if self._aparelho_configurado is not None:
            self._aparelho_id = self._aparelho_configurado
            return

        atual_conectado = (
            self._aparelho_id is not None
            and self._estados_aparelhos.get(self._aparelho_id) == "conectado"
        )
        if atual_conectado:
            return

        for id_, est in self._estados_aparelhos.items():
            if est == "conectado":
                self._aparelho_id = id_
                return
        # nenhum conectado: mantém o id atual (o estado() já refletirá desconectado)

    def _processar_leitura(self, evento: dict) -> None:
        aparelho_id = evento.get("aparelho_id")
        if aparelho_id is None or aparelho_id != self._aparelho_id:
            return
        dados = evento.get("dados")
        if not isinstance(dados, dict):
            self.eventos_invalidos += 1
            return
        try:
            leitura = Leitura(
                ts=dados["ts"],
                dr_usvh=dados["dr_usvh"],
                cpm=dados["cpm"],
                cps=dados["cps"],
                dose_usv=dados["dose_usv"],
                detector_id=aparelho_id,
            )
        except (KeyError, TypeError):
            self.eventos_invalidos += 1
            return

        for cb in list(self._callbacks):
            try:
                cb(leitura)
            except Exception:
                log.exception("callback de leitura do FS-5000 lançou uma exceção")

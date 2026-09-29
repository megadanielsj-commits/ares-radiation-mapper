"""Robô real: Go2 EDU pela wifi do robô, via WebRTC (implementa `Robo`).

Fina camada sobre `unitree_webrtc_connect`, portada dos helpers já validados
no hardware real em `go2_wifi_quickstart` (`conectar_ap`/`assinar_estado`/
`enviar_comando`). O driver é importado preguiçosamente (só dentro da função
de conexão padrão) para que este módulo, a simulação e os testes funcionem
mesmo sem ele instalado.

Conexão: `iniciar()` sobe uma tarefa de fundo que conecta e, se cair ou
falhar, tenta de novo com backoff exponencial (até `backoff_max`) — nunca
levanta exceção por o robô estar inacessível; `estado()` reflete o erro
atual. Pose: cada mensagem de `rt/lf/sportmodestate` vira uma `Pose` a partir
de `position` (x, y) e do yaw de `imu_state.rpy[2]` (ou, na falta dele, do
quaternion `imu_state.quaternion` [w, x, y, z]). Comandos: publicados em
`rt/api/sport/request` com o `api_id` de `SPORT_CMD`.
"""
import asyncio
import logging
import math
import time
from typing import Callable, List, Optional

from ..modelos import Pose

log = logging.getLogger(__name__)

TOPICO_ESTADO = "rt/lf/sportmodestate"
TOPICO_COMANDO = "rt/api/sport/request"

BACKOFF_MIN_S = 1.0
BACKOFF_MAX_S = 10.0
INTERVALO_VERIFICACAO_S = 0.2

_ESTADOS_DESCONECTADOS = ("disconnected", "failed", "closed")


def _sport_cmd_padrao() -> dict:
    """Carrega `SPORT_CMD` do driver real (import preguiçoso)."""
    from . import _compat  # noqa: F401  -> injeta stubs ANTES de importar o driver
    from unitree_webrtc_connect.constants import SPORT_CMD

    return SPORT_CMD


async def _conectar_padrao(aes_128_key: Optional[str]):
    """Conecta no robô em modo AP, como `conectar_ap` do `go2_wifi_quickstart`."""
    from . import _compat  # noqa: F401
    from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod

    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalAP, aes_128_key=aes_128_key)
    await conn.connect()
    return conn


class Go2WebRTC:
    """Robô real (Go2 EDU) teleoperável pela wifi via WebRTC (implementa `Robo`)."""

    def __init__(
        self,
        aes_128_key: Optional[str] = None,
        conectar: Optional[Callable] = None,
        sport_cmd: Optional[dict] = None,
        backoff_min: float = BACKOFF_MIN_S,
        backoff_max: float = BACKOFF_MAX_S,
        intervalo_verificacao_s: float = INTERVALO_VERIFICACAO_S,
    ) -> None:
        self._aes_128_key = aes_128_key
        self._conectar = conectar or (lambda: _conectar_padrao(self._aes_128_key))
        self._sport_cmd = sport_cmd
        self._backoff_min = backoff_min
        self._backoff_max = backoff_max
        self._intervalo_verificacao_s = intervalo_verificacao_s

        self._conn = None
        self._tarefa: Optional[asyncio.Task] = None

        self._conectado = False
        self._erro: Optional[str] = None
        self._body_height: Optional[float] = None
        self._mode: Optional[int] = None

        self._callbacks: List[Callable[[Pose], None]] = []

    # ------------------------------------------------------------------ API pública
    async def iniciar(self) -> None:
        """Sobe a tarefa de fundo que conecta e reconecta (nunca levanta)."""
        if self._tarefa is not None and not self._tarefa.done():
            return
        self._tarefa = asyncio.create_task(self._laco())

    async def encerrar(self) -> None:
        """Cancela a tarefa de fundo, manda StopMove (se conectado) e desconecta."""
        if self._tarefa is not None:
            self._tarefa.cancel()
            try:
                await self._tarefa
            except asyncio.CancelledError:
                pass
            self._tarefa = None

        if self._conectado and self._conn is not None:
            try:
                await self._enviar_comando("StopMove")
            except Exception:
                log.exception("erro ao mandar StopMove no encerramento do robô")

        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await conn.disconnect()
            except Exception:
                log.exception("erro ao desconectar do robô")

        self._conectado = False

    def assinar_pose(self, cb: Callable[[Pose], None]) -> None:
        self._callbacks.append(cb)

    async def mover(self, vx: float, vy: float, vyaw: float) -> None:
        await self._enviar_comando("Move", {"x": vx, "y": vy, "z": vyaw})

    async def parar_movimento(self) -> None:
        await self._enviar_comando("StopMove")

    async def levantar(self) -> None:
        await self._enviar_comando("StandUp")
        await self._enviar_comando("BalanceStand")

    async def deitar(self) -> None:
        await self._enviar_comando("StandDown")

    def estado(self) -> dict:
        return {
            "conectado": self._conectado,
            "erro": self._erro,
            "body_height": self._body_height,
            "mode": self._mode,
        }

    # ------------------------------------------------------------------ laço de conexão
    async def _laco(self) -> None:
        espera = self._backoff_min
        while True:
            try:
                conn = await self._conectar()
                self._conn = conn
                self._conectado = True
                self._erro = None
                espera = self._backoff_min
                self._assinar_estado(conn)
                await self._aguardar_desconexao(conn)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._erro = str(e)
                log.warning("conexão com o robô falhou/caiu: %s", e)
            self._conectado = False
            self._conn = None
            await asyncio.sleep(espera)
            espera = min(espera * 2, self._backoff_max)

    def _assinar_estado(self, conn) -> None:
        try:
            conn.datachannel.pub_sub.subscribe(TOPICO_ESTADO, self._ao_receber_estado)
        except Exception:
            log.exception("erro ao assinar o estado do robô")

    async def _aguardar_desconexao(self, conn) -> None:
        """Espera até a conexão cair (sinal do driver, se disponível)."""
        while True:
            await asyncio.sleep(self._intervalo_verificacao_s)
            pc = getattr(conn, "pc", None)
            estado_pc = getattr(pc, "connectionState", None) if pc is not None else None
            if estado_pc in _ESTADOS_DESCONECTADOS:
                return

    # ------------------------------------------------------------------ estado/pose
    def _ao_receber_estado(self, msg) -> None:
        try:
            dados = msg.get("data", msg) if isinstance(msg, dict) else msg
            if not isinstance(dados, dict):
                return
            if "body_height" in dados:
                self._body_height = dados.get("body_height")
            if "mode" in dados:
                self._mode = dados.get("mode")
            pose = self._extrair_pose(dados)
            if pose is not None:
                self._publicar_pose(pose)
        except Exception:
            log.exception("erro ao processar mensagem de estado do robô")

    def _extrair_pose(self, dados: dict) -> Optional[Pose]:
        posicao = dados.get("position")
        if not isinstance(posicao, (list, tuple)) or len(posicao) < 2:
            return None
        yaw = self._extrair_yaw(dados)
        if yaw is None:
            return None
        return Pose(ts=time.time(), x=posicao[0], y=posicao[1], yaw=yaw)

    @staticmethod
    def _extrair_yaw(dados: dict) -> Optional[float]:
        imu = dados.get("imu_state")
        if not isinstance(imu, dict):
            return None
        rpy = imu.get("rpy")
        if isinstance(rpy, (list, tuple)) and len(rpy) >= 3:
            return rpy[2]
        quat = imu.get("quaternion")
        if isinstance(quat, (list, tuple)) and len(quat) == 4:
            w, x, y, z = quat
            seno_cosseno = 2.0 * (w * z + x * y)
            cosseno_cosseno = 1.0 - 2.0 * (y * y + z * z)
            return math.atan2(seno_cosseno, cosseno_cosseno)
        return None

    def _publicar_pose(self, pose: Pose) -> None:
        for cb in list(self._callbacks):
            try:
                cb(pose)
            except Exception:
                log.exception("erro num assinante de pose")

    # ------------------------------------------------------------------ comandos
    def _obter_sport_cmd(self) -> dict:
        if self._sport_cmd is None:
            self._sport_cmd = _sport_cmd_padrao()
        return self._sport_cmd

    async def _enviar_comando(self, nome: str, parametro: Optional[dict] = None):
        if not self._conectado or self._conn is None:
            raise RuntimeError("robô não conectado")
        sport_cmd = self._obter_sport_cmd()
        opts = {"api_id": sport_cmd[nome]}
        if parametro is not None:
            opts["parameter"] = parametro
        return await self._conn.datachannel.pub_sub.publish_request_new(TOPICO_COMANDO, opts)

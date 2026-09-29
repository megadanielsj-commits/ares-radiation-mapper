"""Robô real: Go2 EDU pela wifi do robô, via WebRTC (implementa `Robo`).

Fina camada sobre `unitree_webrtc_connect`, portada dos helpers já validados
no hardware real em `go2_wifi_quickstart` (`conectar_ap`/`assinar_estado`/
`enviar_comando`). O driver é importado preguiçosamente (só dentro da função
de conexão padrão) para que este módulo, a simulação e os testes funcionem
mesmo sem ele instalado.

Conexão: `iniciar()` sobe uma tarefa de fundo que conecta e, se cair ou
falhar, tenta de novo com backoff exponencial (até `backoff_max`) — nunca
levanta exceção por o robô estar inacessível; `estado()` reflete o erro
atual. O backoff só volta ao mínimo quando a conexão prova que está viva de
verdade: na primeira mensagem de estado recebida, não no `connect()` (uma
conexão que "sobe" mas nunca fala nunca reseta o backoff, então as
tentativas de reconexão se afastam cada vez mais). Queda: o `aiortc` só
passa a `failed`/`closed` depois de ~30 s sem consentimento ICE (não existe
estado `disconnected` no `RTCPeerConnection`), então a queda é detectada
principalmente por estado parado: sem mensagem de `rt/lf/sportmodestate` há
`estado_expira_s`, a conexão é dada como caída. Antes de fechá-la, um último
StopMove é tentado (tempo limite curto, `TEMPO_LIMITE_STOPMOVE_PARADA_S`) —
o robô pode estar em movimento e essa é a única chance de pará-lo antes do
enlace cair de vez; depois a conexão é fechada (com tempo limite) e refeita.
Toda conexão que falha ou cai é fechada antes de tentar de novo, para não
vazar peer connections. As mensagens de estado são associadas à conexão que
as gerou; uma mensagem tardia de uma conexão antiga (já substituída) é
ignorada, mesmo que a assinatura no `pub_sub` dela ainda exista.

Comandos têm tempo limite (`tempo_limite_comando_s`): num enlace caído a
resposta de `publish_request_new` pode nunca chegar, e quem chamou recebe
`TimeoutError` em vez de ficar preso. Pose: cada mensagem de `rt/lf/sportmodestate` vira uma `Pose` a partir
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
TEMPO_LIMITE_COMANDO_S = 1.0
TEMPO_LIMITE_DESCONEXAO_S = 2.0
ESTADO_EXPIRA_S = 2.0
PAUSA_LEVANTAR_S = 0.1
TEMPO_LIMITE_STOPMOVE_PARADA_S = 0.3

# `connectionState` do `RTCPeerConnection` do aiortc 1.x: new, connecting,
# connected, failed, closed (não há "disconnected").
_ESTADOS_DESCONECTADOS = ("failed", "closed")


def _sport_cmd_padrao() -> dict:
    """Carrega `SPORT_CMD` do driver real (import preguiçoso)."""
    from . import _compat  # noqa: F401  -> injeta stubs ANTES de importar o driver
    from unitree_webrtc_connect.constants import SPORT_CMD

    return SPORT_CMD


async def _fechar_conexao(conn, tempo_limite_s: float) -> None:
    """`conn.disconnect()` com tempo limite; erros só vão para o log."""
    try:
        await asyncio.wait_for(conn.disconnect(), timeout=tempo_limite_s)
    except asyncio.TimeoutError:
        log.warning("desconexão do robô passou de %.1f s; conexão abandonada", tempo_limite_s)
    except Exception:
        log.exception("erro ao desconectar do robô")


async def _abrir_conexao(conn, tempo_limite_desconexao_s: float = TEMPO_LIMITE_DESCONEXAO_S):
    """`conn.connect()`; se falhar ou for cancelado no meio, fecha o que já foi montado."""
    try:
        await conn.connect()
    except BaseException:
        await _fechar_conexao(conn, tempo_limite_desconexao_s)
        raise
    return conn


async def _conectar_padrao(aes_128_key: Optional[str], tempo_limite_desconexao_s: float):
    """Conecta no robô em modo AP, como `conectar_ap` do `go2_wifi_quickstart`."""
    from . import _compat  # noqa: F401
    from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod

    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalAP, aes_128_key=aes_128_key)
    return await _abrir_conexao(conn, tempo_limite_desconexao_s)


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
        tempo_limite_comando_s: float = TEMPO_LIMITE_COMANDO_S,
        tempo_limite_desconexao_s: float = TEMPO_LIMITE_DESCONEXAO_S,
        estado_expira_s: float = ESTADO_EXPIRA_S,
    ) -> None:
        self._aes_128_key = aes_128_key
        self._conectar = conectar or (
            lambda: _conectar_padrao(self._aes_128_key, self._tempo_limite_desconexao_s)
        )
        self._sport_cmd = sport_cmd
        self._backoff_min = backoff_min
        self._backoff_max = backoff_max
        self._intervalo_verificacao_s = intervalo_verificacao_s
        self._tempo_limite_comando_s = tempo_limite_comando_s
        self._tempo_limite_desconexao_s = tempo_limite_desconexao_s
        self._estado_expira_s = estado_expira_s

        self._conn = None
        self._tarefa: Optional[asyncio.Task] = None

        self._conectado = False
        self._erro: Optional[str] = None
        self._body_height: Optional[float] = None
        self._mode: Optional[int] = None
        self._ultimo_estado = 0.0  # time.monotonic() da última mensagem de estado
        self._primeiro_estado_recebido = False  # da conexão atual
        self._espera = self._backoff_min  # backoff atual entre tentativas de conexão

        self._callbacks: List[Callable[[Pose], None]] = []

    # ------------------------------------------------------------------ API pública
    async def iniciar(self) -> None:
        """Sobe a tarefa de fundo que conecta e reconecta (nunca levanta)."""
        if self._tarefa is not None and not self._tarefa.done():
            return
        self._tarefa = asyncio.create_task(self._laco())

    async def encerrar(self) -> None:
        """Cancela a tarefa de fundo, manda StopMove (se conectado) e desconecta.

        Cada passo tem tempo limite (StopMove: `tempo_limite_comando_s`;
        desconexão: `tempo_limite_desconexao_s`) e a desconexão é sempre
        tentada, mesmo se o StopMove falhar ou não tiver resposta.
        """
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

        self._conectado = False
        conn, self._conn = self._conn, None
        if conn is not None:
            await _fechar_conexao(conn, self._tempo_limite_desconexao_s)

    def assinar_pose(self, cb: Callable[[Pose], None]) -> None:
        self._callbacks.append(cb)

    async def mover(self, vx: float, vy: float, vyaw: float) -> None:
        await self._enviar_comando("Move", {"x": vx, "y": vy, "z": vyaw})

    async def parar_movimento(self) -> None:
        await self._enviar_comando("StopMove")

    async def levantar(self) -> None:
        await self._enviar_comando("StandUp")
        await asyncio.sleep(PAUSA_LEVANTAR_S)
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
        self._espera = self._backoff_min
        while True:
            conn = None
            self._primeiro_estado_recebido = False
            try:
                conn = await self._conectar()
                self._conn = conn
                self._ultimo_estado = time.monotonic()  # carência até o 1º estado
                self._conectado = True
                self._erro = None
                self._assinar_estado(conn)
                motivo, parado = await self._aguardar_desconexao(conn)
                self._erro = motivo
                log.warning("conexão com o robô caiu: %s", motivo)
                if parado:
                    await self._tentar_parar_antes_de_fechar(conn)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._erro = str(e)
                log.warning("conexão com o robô falhou/caiu: %s", e)
            self._conectado = False
            if conn is not None:
                # fecha a conexão antiga antes de reconectar; `self._conn` só é
                # limpo depois, para que `encerrar()` a feche se cancelar no meio
                await _fechar_conexao(conn, self._tempo_limite_desconexao_s)
                self._conn = None
            await asyncio.sleep(self._espera)
            self._espera = min(self._espera * 2, self._backoff_max)

    def _assinar_estado(self, conn) -> None:
        def _callback(msg, conn=conn) -> None:
            # ignora mensagens de uma conexão antiga já substituída
            if conn is self._conn:
                self._ao_receber_estado(msg)

        try:
            conn.datachannel.pub_sub.subscribe(TOPICO_ESTADO, _callback)
        except Exception:
            log.exception("erro ao assinar o estado do robô")

    async def _tentar_parar_antes_de_fechar(self, conn) -> None:
        """Última tentativa de StopMove antes de abandonar uma conexão parada.

        Tempo limite curto e próprio (`TEMPO_LIMITE_STOPMOVE_PARADA_S`): o
        robô já está sem estado há um tempo, então não vale a pena esperar
        muito por uma resposta que pode nunca vir.
        """
        if conn is not self._conn:
            return
        try:
            await asyncio.wait_for(
                self._enviar_comando("StopMove"), timeout=TEMPO_LIMITE_STOPMOVE_PARADA_S
            )
        except Exception:
            log.warning("StopMove antes de fechar conexão parada falhou ou sem resposta")

    async def _aguardar_desconexao(self, conn) -> tuple:
        """Espera até a conexão cair; devolve `(motivo, parado)`.

        Dois sinais: `pc.connectionState` em failed/closed (lento no aiortc,
        `parado=False`) e estado parado — nenhuma mensagem de `TOPICO_ESTADO`
        há `estado_expira_s` (o robô publica a dezenas de Hz; `parado=True`).
        """
        while True:
            await asyncio.sleep(self._intervalo_verificacao_s)
            pc = getattr(conn, "pc", None)
            estado_pc = getattr(pc, "connectionState", None) if pc is not None else None
            if estado_pc in _ESTADOS_DESCONECTADOS:
                return f"conexão WebRTC {estado_pc}", False
            parado_ha = time.monotonic() - self._ultimo_estado
            if parado_ha >= self._estado_expira_s:
                return f"sem estado do robô há {parado_ha:.1f} s", True

    # ------------------------------------------------------------------ estado/pose
    def _ao_receber_estado(self, msg) -> None:
        self._ultimo_estado = time.monotonic()
        if not self._primeiro_estado_recebido:
            # só agora a conexão provou que está viva: reseta o backoff
            self._primeiro_estado_recebido = True
            self._espera = self._backoff_min
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
        """Publica o comando e espera a resposta por até `tempo_limite_comando_s`.

        Levanta `RuntimeError` se não houver conexão e `TimeoutError` se a
        resposta não chegar no prazo (enlace caído: o future do driver nunca
        resolve).
        """
        if not self._conectado or self._conn is None:
            raise RuntimeError("robô não conectado")
        sport_cmd = self._obter_sport_cmd()
        opts = {"api_id": sport_cmd[nome]}
        if parametro is not None:
            opts["parameter"] = parametro
        pub_sub = self._conn.datachannel.pub_sub
        try:
            return await asyncio.wait_for(
                pub_sub.publish_request_new(TOPICO_COMANDO, opts),
                timeout=self._tempo_limite_comando_s,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"comando {nome} sem resposta em {self._tempo_limite_comando_s:.1f} s"
            ) from None

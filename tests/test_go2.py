"""Testes do adaptador real do robô (Go2 via WebRTC), sem tocar hardware.

Usa uma conexão falsa que imita `conn.datachannel.pub_sub.subscribe(topico, cb)`
e `await conn.datachannel.pub_sub.publish_request_new(topico, payload)`, mais
`connect()`/`disconnect()`.
"""
import asyncio
import math
import time

import pytest

from ares.robo.go2 import Go2WebRTC, _abrir_conexao

SPORT_CMD = {
    "Damp": 1001,
    "BalanceStand": 1002,
    "StopMove": 1003,
    "StandUp": 1004,
    "StandDown": 1005,
    "Move": 1008,
}

BACKOFF_MIN = 0.02
BACKOFF_MAX = 0.05
POLL = 0.01


class PubSubFalso:
    def __init__(self):
        self.assinantes = {}
        self.publicacoes = []
        self.instantes = []
        self.falhar_proximas = 0
        self.travar = False
        self.eventos = None  # lista compartilhada com a conexão (ordem dos eventos)

    def subscribe(self, topico, cb):
        self.assinantes.setdefault(topico, []).append(cb)

    async def publish_request_new(self, topico, payload):
        if self.eventos is not None:
            self.eventos.append(("publish", payload.get("api_id")))
        if self.travar:
            # enlace caído: a resposta nunca chega e o future nunca resolve
            await asyncio.Event().wait()
        if self.falhar_proximas > 0:
            self.falhar_proximas -= 1
            raise RuntimeError("publish falhou")
        self.publicacoes.append((topico, payload))
        self.instantes.append(time.monotonic())
        return {"ok": True}

    def emitir_estado(self, dados):
        for cb in self.assinantes.get("rt/lf/sportmodestate", []):
            cb(dados)


class DataChannelFalso:
    def __init__(self):
        self.pub_sub = PubSubFalso()


class ConexaoFalsa:
    def __init__(self):
        self.datachannel = DataChannelFalso()
        self.desconectada = False
        self.eventos = []
        self.datachannel.pub_sub.eventos = self.eventos

    async def disconnect(self):
        self.eventos.append(("disconnect", None))
        self.desconectada = True


class PeerFalso:
    def __init__(self, estado="connected"):
        self.connectionState = estado


def _conectar_ok(conexoes):
    async def conectar():
        conn = ConexaoFalsa()
        conexoes.append(conn)
        return conn

    return conectar


def _conectar_falha_n_vezes(n, conexoes):
    contador = {"n": 0}

    async def conectar():
        if contador["n"] < n:
            contador["n"] += 1
            raise RuntimeError("robô inacessível")
        conn = ConexaoFalsa()
        conexoes.append(conn)
        return conn

    return conectar


async def _esperar(condicao, tentativas=200, intervalo=0.01):
    for _ in range(tentativas):
        if condicao():
            return True
        await asyncio.sleep(intervalo)
    return condicao()


# --- parsing de pose --------------------------------------------------------


def test_pose_parse_com_rpy():
    async def cenario():
        conexoes = []
        recebidas = []
        robo = Go2WebRTC(
            conectar=_conectar_ok(conexoes),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
        )
        robo.assinar_pose(recebidas.append)
        await robo.iniciar()
        try:
            assert await _esperar(lambda: len(conexoes) == 1)
            conexoes[0].datachannel.pub_sub.emitir_estado(
                {
                    "data": {
                        "position": [1.5, -2.5, 0.0],
                        "imu_state": {"rpy": [0.0, 0.0, 0.7]},
                        "body_height": 0.32,
                        "mode": 1,
                    }
                }
            )
            assert await _esperar(lambda: len(recebidas) == 1)
        finally:
            await robo.encerrar()
        return recebidas, robo.estado()

    recebidas, estado = asyncio.run(cenario())
    assert len(recebidas) == 1
    pose = recebidas[0]
    assert pose.x == pytest.approx(1.5)
    assert pose.y == pytest.approx(-2.5)
    assert pose.yaw == pytest.approx(0.7)
    assert estado["body_height"] == pytest.approx(0.32)
    assert estado["mode"] == 1


def test_pose_parse_com_fallback_quaternion():
    async def cenario():
        conexoes = []
        recebidas = []
        robo = Go2WebRTC(
            conectar=_conectar_ok(conexoes),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
        )
        robo.assinar_pose(recebidas.append)
        await robo.iniciar()
        try:
            assert await _esperar(lambda: len(conexoes) == 1)
            # quaternion de uma rotação pura de +90 graus (pi/2) em yaw
            meio = math.pi / 4
            quat = [math.cos(meio), 0.0, 0.0, math.sin(meio)]
            conexoes[0].datachannel.pub_sub.emitir_estado(
                {"data": {"position": [0.0, 0.0, 0.0], "imu_state": {"quaternion": quat}}}
            )
            assert await _esperar(lambda: len(recebidas) == 1)
        finally:
            await robo.encerrar()
        return recebidas

    recebidas = asyncio.run(cenario())
    assert len(recebidas) == 1
    assert recebidas[0].yaw == pytest.approx(math.pi / 2)


def test_estado_malformado_nao_derruba_e_callback_com_excecao_e_contido():
    async def cenario():
        conexoes = []

        def quebra(_pose):
            raise RuntimeError("assinante ruim")

        recebidas = []
        robo = Go2WebRTC(
            conectar=_conectar_ok(conexoes),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
        )
        robo.assinar_pose(quebra)
        robo.assinar_pose(recebidas.append)
        await robo.iniciar()
        try:
            assert await _esperar(lambda: len(conexoes) == 1)
            # mensagem sem "position" -> deve ser ignorada sem derrubar nada
            conexoes[0].datachannel.pub_sub.emitir_estado({"data": {"mode": 0}})
            conexoes[0].datachannel.pub_sub.emitir_estado(
                {"data": {"position": [1.0, 1.0, 0.0], "imu_state": {"rpy": [0, 0, 0.1]}}}
            )
            assert await _esperar(lambda: len(recebidas) == 1)
            assert robo.estado()["conectado"] is True
        finally:
            await robo.encerrar()
        return recebidas

    recebidas = asyncio.run(cenario())
    assert len(recebidas) == 1


# --- comandos ----------------------------------------------------------------


def test_comandos_publicam_api_id_certo():
    async def cenario():
        conexoes = []
        robo = Go2WebRTC(
            conectar=_conectar_ok(conexoes),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
        )
        await robo.iniciar()
        try:
            assert await _esperar(lambda: len(conexoes) == 1)
            await robo.mover(0.3, 0.0, 0.1)
            await robo.parar_movimento()
            await robo.levantar()
            await robo.deitar()
        finally:
            await robo.encerrar()
        pub_sub = conexoes[0].datachannel.pub_sub
        return pub_sub.publicacoes, pub_sub.instantes

    publicacoes, instantes = asyncio.run(cenario())
    topico, payload = publicacoes[0]
    assert topico == "rt/api/sport/request"
    assert payload == {"api_id": 1008, "parameter": {"x": 0.3, "y": 0.0, "z": 0.1}}

    assert publicacoes[1][1] == {"api_id": 1003}
    assert publicacoes[2][1] == {"api_id": 1004}
    assert publicacoes[3][1] == {"api_id": 1002}
    # levantar(): StandUp, espera 0,1 s, BalanceStand (como o servidor validado)
    assert instantes[3] - instantes[2] >= 0.09
    assert publicacoes[4][1] == {"api_id": 1005}
    # StopMove no encerrar() (a conexão continuava ativa)
    assert publicacoes[-1][1] == {"api_id": 1003}


def test_comando_sem_conexao_levanta_runtime_error():
    async def cenario():
        robo = Go2WebRTC(sport_cmd=SPORT_CMD)
        with pytest.raises(RuntimeError, match="robô não conectado"):
            await robo.mover(0.1, 0.0, 0.0)

    asyncio.run(cenario())


def test_parar_movimento_sem_conexao_levanta_runtime_error():
    async def cenario():
        robo = Go2WebRTC(sport_cmd=SPORT_CMD)
        with pytest.raises(RuntimeError, match="robô não conectado"):
            await robo.parar_movimento()

    asyncio.run(cenario())


def test_comando_sem_resposta_levanta_timeout_dentro_do_limite():
    async def cenario():
        conexoes = []
        robo = Go2WebRTC(
            conectar=_conectar_ok(conexoes),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
            tempo_limite_comando_s=0.1,
            tempo_limite_desconexao_s=0.1,
        )
        await robo.iniciar()
        try:
            assert await _esperar(lambda: len(conexoes) == 1)
            conexoes[0].datachannel.pub_sub.travar = True
            inicio = time.monotonic()
            with pytest.raises(TimeoutError):
                await robo.mover(0.2, 0.0, 0.0)
            return time.monotonic() - inicio
        finally:
            await robo.encerrar()

    duracao = asyncio.run(cenario())
    assert duracao < 0.5


# --- conexão: retry/backoff --------------------------------------------------


def test_conexao_que_falha_registra_erro_e_tenta_de_novo():
    async def cenario():
        conexoes = []
        robo = Go2WebRTC(
            conectar=_conectar_falha_n_vezes(2, conexoes),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
        )
        await robo.iniciar()
        try:
            assert await _esperar(lambda: robo.estado()["erro"] is not None)
            assert robo.estado()["conectado"] is False
            assert await _esperar(lambda: robo.estado()["conectado"] is True)
        finally:
            await robo.encerrar()
        return robo.estado()

    estado = asyncio.run(cenario())
    assert estado["conectado"] is False  # após encerrar()


def test_iniciar_nunca_levanta_se_robo_inacancavel():
    async def cenario():
        robo = Go2WebRTC(
            conectar=_conectar_falha_n_vezes(10_000, []),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
        )
        await robo.iniciar()  # não deve levantar mesmo estando inacessível
        try:
            assert await _esperar(lambda: robo.estado()["erro"] is not None)
            assert robo.estado()["conectado"] is False
        finally:
            await robo.encerrar()

    asyncio.run(cenario())  # não deve levantar


def test_estado_parado_marca_desconectado_fecha_e_reconecta():
    async def cenario():
        conexoes = []
        robo = Go2WebRTC(
            conectar=_conectar_ok(conexoes),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
            intervalo_verificacao_s=POLL,
            estado_expira_s=0.15,
            tempo_limite_comando_s=0.1,
            tempo_limite_desconexao_s=0.1,
        )
        await robo.iniciar()
        try:
            assert await _esperar(lambda: len(conexoes) == 1)
            # a conexão falsa nunca manda estado -> deve expirar
            assert await _esperar(lambda: robo.estado()["conectado"] is False)
            erro = robo.estado()["erro"]
            assert await _esperar(lambda: len(conexoes) >= 2)
        finally:
            await robo.encerrar()
        return conexoes, erro

    conexoes, erro = asyncio.run(cenario())
    assert "sem estado do robô há" in erro
    assert conexoes[0].desconectada is True  # conexão antiga fechada antes de reconectar


def test_backoff_so_reseta_no_primeiro_estado_nao_no_connect():
    async def cenario():
        instantes_conexao = []

        async def conectar():
            instantes_conexao.append(time.monotonic())
            return ConexaoFalsa()

        robo = Go2WebRTC(
            conectar=conectar,
            sport_cmd=SPORT_CMD,
            backoff_min=0.03,
            backoff_max=1.0,
            intervalo_verificacao_s=POLL,
            estado_expira_s=0.05,
            tempo_limite_comando_s=0.05,
            tempo_limite_desconexao_s=0.05,
        )
        await robo.iniciar()
        try:
            # a conexão falsa nunca manda estado -> nunca prova que está viva
            assert await _esperar(lambda: len(instantes_conexao) >= 4)
        finally:
            await robo.encerrar()
        return instantes_conexao

    instantes = asyncio.run(cenario())
    lacunas = [b - a for a, b in zip(instantes, instantes[1:])]
    # sem nunca receber estado, o backoff cresce a cada reconexão (não volta
    # ao mínimo só por ter conectado)
    assert lacunas[1] > lacunas[0] * 1.3
    assert lacunas[2] > lacunas[1] * 1.3


def test_estado_parado_tenta_stopmove_antes_de_fechar():
    async def cenario():
        conexoes = []
        robo = Go2WebRTC(
            conectar=_conectar_ok(conexoes),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
            intervalo_verificacao_s=POLL,
            estado_expira_s=0.1,
            tempo_limite_comando_s=0.05,
            tempo_limite_desconexao_s=0.05,
        )
        await robo.iniciar()
        try:
            assert await _esperar(lambda: len(conexoes) == 1)
            # a conexão falsa nunca manda estado -> deve expirar
            assert await _esperar(lambda: len(conexoes) >= 2)
        finally:
            await robo.encerrar()
        return conexoes

    conexoes = asyncio.run(cenario())
    eventos = conexoes[0].eventos
    assert ("publish", 1003) in eventos  # StopMove tentado
    # StopMove antes de desconectar, não depois
    assert eventos.index(("publish", 1003)) < eventos.index(("disconnect", None))


def test_estado_de_conexao_antiga_e_ignorado():
    async def cenario():
        conexoes = []
        recebidas = []
        robo = Go2WebRTC(
            conectar=_conectar_ok(conexoes),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
            intervalo_verificacao_s=POLL,
            estado_expira_s=0.1,
            tempo_limite_comando_s=0.05,
            tempo_limite_desconexao_s=0.05,
        )
        robo.assinar_pose(recebidas.append)
        await robo.iniciar()
        try:
            assert await _esperar(lambda: len(conexoes) == 1)
            conexao_antiga = conexoes[0]
            assert await _esperar(lambda: len(conexoes) >= 2)
            # mensagem tardia da conexão antiga: a assinatura dela ainda existe,
            # mas a conexão já foi substituída
            conexao_antiga.datachannel.pub_sub.emitir_estado(
                {"data": {"position": [9.0, 9.0, 0.0], "imu_state": {"rpy": [0.0, 0.0, 0.0]}}}
            )
            await asyncio.sleep(0.02)
        finally:
            await robo.encerrar()
        return recebidas

    recebidas = asyncio.run(cenario())
    assert recebidas == []


def test_estado_chegando_mantem_a_conexao():
    async def cenario():
        conexoes = []
        robo = Go2WebRTC(
            conectar=_conectar_ok(conexoes),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
            intervalo_verificacao_s=POLL,
            estado_expira_s=0.15,
        )
        await robo.iniciar()
        try:
            assert await _esperar(lambda: len(conexoes) == 1)
            for _ in range(20):
                conexoes[0].datachannel.pub_sub.emitir_estado({"data": {"mode": 1}})
                await asyncio.sleep(0.02)
            conectado = robo.estado()["conectado"]
        finally:
            await robo.encerrar()
        return conexoes, conectado

    conexoes, conectado = asyncio.run(cenario())
    assert conectado is True
    assert len(conexoes) == 1


def test_peer_connection_failed_fecha_e_reconecta():
    async def cenario():
        conexoes = []
        conectar_base = _conectar_ok(conexoes)

        async def conectar():
            conn = await conectar_base()
            conn.pc = PeerFalso()
            return conn

        robo = Go2WebRTC(
            conectar=conectar,
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
            intervalo_verificacao_s=POLL,
            tempo_limite_desconexao_s=0.1,
        )
        await robo.iniciar()
        try:
            assert await _esperar(lambda: len(conexoes) == 1)
            conexoes[0].pc.connectionState = "failed"
            assert await _esperar(lambda: len(conexoes) >= 2)
        finally:
            await robo.encerrar()
        return conexoes

    conexoes = asyncio.run(cenario())
    assert conexoes[0].desconectada is True


# --- conexão padrão: limpeza de conexões meio montadas ----------------------


class ConexaoQueFalha:
    def __init__(self, travar=False):
        self.desconectada = False
        self._travar = travar

    async def connect(self):
        # simula setup parcial (peer connection criada) e depois falha/trava
        self.pc = object()
        if self._travar:
            await asyncio.Event().wait()
        raise RuntimeError("falha no meio do handshake")

    async def disconnect(self):
        self.desconectada = True


def test_connect_que_falha_desconecta_a_conexao_parcial():
    async def cenario():
        conn = ConexaoQueFalha()
        with pytest.raises(RuntimeError, match="handshake"):
            await _abrir_conexao(conn, tempo_limite_desconexao_s=0.1)
        return conn

    conn = asyncio.run(cenario())
    assert conn.desconectada is True


def test_cancelar_durante_connect_fecha_a_conexao_parcial():
    async def cenario():
        conn = ConexaoQueFalha(travar=True)
        tarefa = asyncio.create_task(_abrir_conexao(conn, tempo_limite_desconexao_s=0.1))
        await asyncio.sleep(0.05)
        tarefa.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarefa
        return conn

    conn = asyncio.run(cenario())
    assert conn.desconectada is True


def test_encerrar_durante_tentativa_de_conexao_nao_trava():
    async def cenario():
        conns = []

        async def conectar():
            conn = ConexaoQueFalha(travar=True)
            conns.append(conn)
            return await _abrir_conexao(conn, tempo_limite_desconexao_s=0.1)

        robo = Go2WebRTC(conectar=conectar, sport_cmd=SPORT_CMD)
        await robo.iniciar()
        assert await _esperar(lambda: len(conns) == 1)
        inicio = time.monotonic()
        await robo.encerrar()
        return conns, time.monotonic() - inicio

    conns, duracao = asyncio.run(cenario())
    assert conns[0].desconectada is True
    assert duracao < 0.5


# --- encerrar / ciclo de vida -------------------------------------------------


def test_encerrar_manda_stopmove_e_desconecta():
    async def cenario():
        conexoes = []
        robo = Go2WebRTC(
            conectar=_conectar_ok(conexoes),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
        )
        await robo.iniciar()
        assert await _esperar(lambda: len(conexoes) == 1)
        await robo.encerrar()
        return conexoes[0]

    conn = asyncio.run(cenario())
    assert conn.desconectada is True
    assert ("rt/api/sport/request", {"api_id": 1003}) in conn.datachannel.pub_sub.publicacoes


def test_encerrar_com_publish_que_nunca_resolve_termina_e_desconecta():
    async def cenario():
        conexoes = []
        robo = Go2WebRTC(
            conectar=_conectar_ok(conexoes),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
            tempo_limite_comando_s=0.1,
            tempo_limite_desconexao_s=0.1,
        )
        await robo.iniciar()
        assert await _esperar(lambda: len(conexoes) == 1)
        conexoes[0].datachannel.pub_sub.travar = True
        inicio = time.monotonic()
        await robo.encerrar()
        return conexoes[0], time.monotonic() - inicio

    conn, duracao = asyncio.run(cenario())
    assert duracao < 0.5
    assert conn.desconectada is True
    # StopMove tentado ANTES de desconectar
    assert conn.eventos == [("publish", 1003), ("disconnect", None)]


def test_encerrar_com_disconnect_que_trava_termina_dentro_do_limite():
    async def cenario():
        conexoes = []
        conectar_base = _conectar_ok(conexoes)

        async def conectar():
            conn = await conectar_base()

            async def disconnect_travado():
                conn.eventos.append(("disconnect", None))
                await asyncio.Event().wait()

            conn.disconnect = disconnect_travado
            return conn

        robo = Go2WebRTC(
            conectar=conectar,
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
            tempo_limite_comando_s=0.1,
            tempo_limite_desconexao_s=0.1,
        )
        await robo.iniciar()
        assert await _esperar(lambda: len(conexoes) == 1)
        inicio = time.monotonic()
        await robo.encerrar()
        return conexoes[0], time.monotonic() - inicio

    conn, duracao = asyncio.run(cenario())
    assert duracao < 0.5
    assert conn.eventos == [("publish", 1003), ("disconnect", None)]


def test_encerrar_sem_nunca_ter_conectado_nao_levanta():
    async def cenario():
        robo = Go2WebRTC(
            conectar=_conectar_falha_n_vezes(10_000, []),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
        )
        await robo.iniciar()
        await robo.encerrar()  # não deve levantar nem publicar nada

    asyncio.run(cenario())  # não deve levantar


def test_iniciar_duas_vezes_nao_vaza_tarefas():
    async def cenario():
        conexoes = []
        robo = Go2WebRTC(
            conectar=_conectar_ok(conexoes),
            sport_cmd=SPORT_CMD,
            backoff_min=BACKOFF_MIN,
            backoff_max=BACKOFF_MAX,
        )
        await robo.iniciar()
        tarefa1 = robo._tarefa
        await robo.iniciar()
        tarefa2 = robo._tarefa
        await robo.encerrar()
        return tarefa1, tarefa2

    tarefa1, tarefa2 = asyncio.run(cenario())
    assert tarefa1 is tarefa2

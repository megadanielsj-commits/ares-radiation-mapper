"""Testes do adaptador real do robô (Go2 via WebRTC), sem tocar hardware.

Usa uma conexão falsa que imita `conn.datachannel.pub_sub.subscribe(topico, cb)`
e `await conn.datachannel.pub_sub.publish_request_new(topico, payload)`, mais
`connect()`/`disconnect()`.
"""
import asyncio
import math

import pytest

from ares.robo.go2 import Go2WebRTC

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
        self.falhar_proximas = 0

    def subscribe(self, topico, cb):
        self.assinantes.setdefault(topico, []).append(cb)

    async def publish_request_new(self, topico, payload):
        if self.falhar_proximas > 0:
            self.falhar_proximas -= 1
            raise RuntimeError("publish falhou")
        self.publicacoes.append((topico, payload))
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

    async def disconnect(self):
        self.desconectada = True


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
        return conexoes[0].datachannel.pub_sub.publicacoes

    publicacoes = asyncio.run(cenario())
    topico, payload = publicacoes[0]
    assert topico == "rt/api/sport/request"
    assert payload == {"api_id": 1008, "parameter": {"x": 0.3, "y": 0.0, "z": 0.1}}

    assert publicacoes[1][1] == {"api_id": 1003}
    assert publicacoes[2][1] == {"api_id": 1004}
    assert publicacoes[3][1] == {"api_id": 1002}
    assert publicacoes[4][1] == {"api_id": 1005}
    # StopMove no encerrar() (a conexão continuava ativa)
    assert publicacoes[-1][1] == {"api_id": 1003}


def test_comando_sem_conexao_levanta_runtime_error():
    async def cenario():
        robo = Go2WebRTC(sport_cmd=SPORT_CMD)
        with pytest.raises(RuntimeError, match="robô não conectado"):
            await robo.mover(0.1, 0.0, 0.0)

    asyncio.run(cenario())


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

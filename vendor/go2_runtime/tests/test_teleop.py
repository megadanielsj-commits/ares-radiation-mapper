"""Testes do controlador de teleoperação (watchdog, saturação, StopMove único)."""
import asyncio
import logging
import time
from typing import List, Optional

import pytest

from ares.simulacao.robo import RoboSimulado
from ares.teleop import Teleop

HZ = 20.0
WATCHDOG_S = 0.1


class RoboFalso:
    """Robô falso que registra chamadas de `mover`/`parar_movimento`."""

    def __init__(
        self,
        falhar_mover: bool = False,
        travar_mover: bool = False,
        falhar_paradas: int = 0,
    ) -> None:
        self.movimentos: List[tuple] = []
        self.instantes_movimentos: List[float] = []
        self.paradas = 0  # paradas bem-sucedidas
        self.tentativas_parada = 0
        self.instantes_paradas: List[float] = []  # instante de cada tentativa
        self.chamadas_mover = 0
        self.em_pe = True
        self._falhar_mover = falhar_mover
        self._travar_mover = travar_mover
        self._falhar_paradas = falhar_paradas

    async def iniciar(self) -> None:
        pass

    async def encerrar(self) -> None:
        pass

    def assinar_pose(self, cb) -> None:
        pass

    async def mover(self, vx, vy, vyaw) -> None:
        self.chamadas_mover += 1
        if self._travar_mover:
            await asyncio.Event().wait()  # enlace caído: nunca responde
        if self._falhar_mover:
            raise RuntimeError("robô com defeito")
        self.movimentos.append((vx, vy, vyaw))
        self.instantes_movimentos.append(time.monotonic())

    async def parar_movimento(self) -> None:
        self.tentativas_parada += 1
        self.instantes_paradas.append(time.monotonic())
        if self._falhar_paradas > 0:
            self._falhar_paradas -= 1
            raise RuntimeError("StopMove falhou")
        self.paradas += 1

    async def levantar(self) -> None:
        self.em_pe = True

    async def deitar(self) -> None:
        self.em_pe = False

    def estado(self) -> dict:
        return {"conectado": True, "erro": None}


async def _esperar(condicao, tentativas=100, intervalo=0.02):
    for _ in range(tentativas):
        if condicao():
            return True
        await asyncio.sleep(intervalo)
    return condicao()


# --- saturação -----------------------------------------------------------


def test_definir_satura_nos_limites():
    async def cenario():
        robo = RoboFalso()
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=WATCHDOG_S, hz=HZ)
        teleop.definir(10.0, -10.0, 100.0)
        await teleop.iniciar()
        try:
            assert await _esperar(lambda: len(robo.movimentos) >= 1)
        finally:
            await teleop.encerrar()
        return robo.movimentos

    movimentos = asyncio.run(cenario())
    vx, vy, vyaw = movimentos[0]
    assert vx == pytest.approx(0.5)
    assert vy == pytest.approx(-0.3)
    assert vyaw == pytest.approx(1.0)


# --- watchdog e StopMove único --------------------------------------------


def test_watchdog_para_o_robo_quando_heartbeat_para():
    async def cenario():
        robo = RoboFalso()
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=WATCHDOG_S, hz=HZ)
        await teleop.iniciar()
        paradas_pelo_watchdog = None
        try:
            teleop.definir(0.3, 0.0, 0.0)
            assert await _esperar(lambda: len(robo.movimentos) >= 1)
            # sem novos heartbeats -> watchdog deve zerar e parar (uma vez só)
            assert await _esperar(lambda: robo.paradas >= 1, tentativas=100, intervalo=0.02)
            # espera mais alguns ciclos parado: não deve repetir o StopMove
            await asyncio.sleep(5.0 / HZ)
            paradas_pelo_watchdog = robo.paradas
        finally:
            await teleop.encerrar()
        return paradas_pelo_watchdog

    paradas_pelo_watchdog = asyncio.run(cenario())
    assert paradas_pelo_watchdog == 1  # StopMove único, não repetido a cada ciclo


def test_stopmove_e_unico_na_transicao_nao_e_repetido_enquanto_parado():
    async def cenario():
        robo = RoboFalso()
        # watchdog folgado: só queremos observar a transição por `definir(0,0,0)`
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=1.0, hz=HZ)
        await teleop.iniciar()
        paradas_na_transicao = None
        try:
            teleop.definir(0.2, 0.0, 0.0)
            assert await _esperar(lambda: len(robo.movimentos) >= 2)
            teleop.definir(0.0, 0.0, 0.0)
            assert await _esperar(lambda: robo.paradas >= 1)
            # fica parado por vários ciclos: parar_movimento não deve repetir
            await asyncio.sleep(5.0 / HZ)
            paradas_na_transicao = robo.paradas
        finally:
            await teleop.encerrar()
        return paradas_na_transicao

    paradas_na_transicao = asyncio.run(cenario())
    assert paradas_na_transicao == 1


def test_movimento_continuo_manda_mover_em_cada_ciclo():
    async def cenario():
        robo = RoboFalso()
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=1.0, hz=HZ)
        await teleop.iniciar()
        try:
            teleop.definir(0.2, 0.0, 0.0)
            # heartbeats continuados evitam o watchdog
            for _ in range(6):
                await asyncio.sleep(1.0 / HZ)
                teleop.definir(0.2, 0.0, 0.0)
        finally:
            await teleop.encerrar()
        return robo

    robo = asyncio.run(cenario())
    assert len(robo.movimentos) >= 4


# --- parar() e encerrar() imediatos ---------------------------------------


def test_parar_e_imediato():
    async def cenario():
        robo = RoboFalso()
        # watchdog longo: a parada só pode vir de parar()
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=10.0, hz=HZ)
        await teleop.iniciar()
        try:
            teleop.definir(0.3, 0.0, 0.0)
            assert await _esperar(lambda: len(robo.movimentos) >= 2)
            assert robo.paradas == 0
            await teleop.parar()
            paradas_logo_apos = robo.paradas  # sem esperar ciclo do laço
            movimentos_na_parada = len(robo.movimentos)
            await asyncio.sleep(5.0 / HZ)
            assert len(robo.movimentos) == movimentos_na_parada  # nada de Move depois
            paradas_depois = robo.paradas
        finally:
            await teleop.encerrar()
        return paradas_logo_apos, paradas_depois

    paradas_logo_apos, paradas_depois = asyncio.run(cenario())
    assert paradas_logo_apos == 1
    assert paradas_depois == 1


def test_encerrar_para_o_robo():
    async def cenario():
        robo = RoboFalso()
        # watchdog longo: a parada só pode vir de encerrar()
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=10.0, hz=HZ)
        await teleop.iniciar()
        teleop.definir(0.3, 0.0, 0.0)
        assert await _esperar(lambda: len(robo.movimentos) >= 1)
        paradas_antes = robo.paradas
        await teleop.encerrar()
        return robo, paradas_antes

    robo, paradas_antes = asyncio.run(cenario())
    assert paradas_antes == 0
    assert robo.paradas == 1


def test_encerrar_com_robo_travado_termina_dentro_do_limite():
    async def cenario():
        robo = RoboFalso(travar_mover=True)
        teleop = Teleop(
            robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=10.0, hz=HZ, tempo_limite_s=0.2
        )
        await teleop.iniciar()
        teleop.definir(0.3, 0.0, 0.0)
        assert await _esperar(lambda: robo.chamadas_mover >= 1)
        inicio = time.monotonic()
        await teleop.encerrar()
        return robo, time.monotonic() - inicio

    robo, duracao = asyncio.run(cenario())
    assert duracao < 0.5
    assert robo.paradas == 1


def test_parar_com_stopmove_lento_nao_perde_para_move_concorrente():
    """StopMove lento (parar()) + Move concorrente (definir()) intercalado:
    o último comando que o robô recebe tem que ser um StopMove, não o Move
    que entrou no meio (regressão da corrida em `_tentar_parar`)."""

    async def cenario():
        robo = RoboFalso()
        liberar = asyncio.Event()
        parada_original = robo.parar_movimento
        parar_chamado = asyncio.Event()

        async def parar_lento():
            parar_chamado.set()
            await liberar.wait()
            await parada_original()

        robo.parar_movimento = parar_lento

        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=WATCHDOG_S, hz=HZ)
        await teleop.iniciar()
        try:
            teleop.definir(0.2, 0.0, 0.0)
            assert await _esperar(lambda: len(robo.movimentos) >= 1)

            tarefa_parar = asyncio.create_task(teleop.parar())
            await parar_chamado.wait()  # StopMove lento em voo

            # Move concorrente entra enquanto o StopMove ainda não respondeu
            chamadas_antes = robo.chamadas_mover
            teleop.definir(0.2, 0.0, 0.0)
            assert await _esperar(lambda: robo.chamadas_mover > chamadas_antes)

            liberar.set()
            await tarefa_parar

            # sem mais heartbeats, o watchdog vence e o laço manda outro
            # StopMove: o Move concorrente não pode ser o último comando
            assert await _esperar(lambda: robo.paradas >= 2, tentativas=100, intervalo=0.02)
        finally:
            await teleop.encerrar()
        return robo

    robo = asyncio.run(cenario())
    assert robo.paradas >= 2
    assert robo.instantes_paradas[-1] > robo.instantes_movimentos[-1]


def test_laco_que_termina_sozinho_registra_erro(monkeypatch, caplog):
    async def cenario():
        robo = RoboFalso()
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=WATCHDOG_S, hz=HZ)
        await teleop.iniciar()
        assert await _esperar(lambda: teleop._tarefa is not None)

        def heartbeat_com_falha(_agora):
            raise RuntimeError("falha inesperada no laço")

        # só o método interno do teleop quebra; o relógio do asyncio (usado
        # para agendar o próprio laço) continua intacto
        monkeypatch.setattr(teleop, "_heartbeat_expirado", heartbeat_com_falha)
        assert await _esperar(lambda: teleop._tarefa.done())
        return teleop

    with caplog.at_level(logging.ERROR, logger="ares.teleop"):
        teleop = asyncio.run(cenario())
    assert teleop.ultimo_erro is not None
    assert any("laço de teleop encerrou sozinho" in r.getMessage() for r in caplog.records)


# --- enlace travado, StopMove com falha e relógio -------------------------


def test_mover_travado_nao_impede_o_watchdog():
    tempo_limite = 0.2

    async def cenario():
        robo = RoboFalso(travar_mover=True)
        teleop = Teleop(
            robo,
            vx_max=0.5,
            vy_max=0.3,
            vyaw_max=1.0,
            watchdog_s=WATCHDOG_S,
            hz=HZ,
            tempo_limite_s=tempo_limite,
        )
        await teleop.iniciar()
        try:
            teleop.definir(0.3, 0.0, 0.0)
            inicio = time.monotonic()
            # o Move travado não atrasa mais o StopMove: o laço não espera a
            # resposta dele, só cancela essa espera na transição para zero
            limite = WATCHDOG_S + 0.15
            assert await _esperar(lambda: robo.tentativas_parada >= 1, tentativas=100, intervalo=0.01)
            latencia = robo.instantes_paradas[0] - inicio
            assert latencia < limite
            # o laço continua vivo: novo comando -> nova tentativa de mover
            chamadas = robo.chamadas_mover
            teleop.definir(0.3, 0.0, 0.0)
            assert await _esperar(lambda: robo.chamadas_mover > chamadas)
            assert not teleop._tarefa.done()
        finally:
            await teleop.encerrar()

    asyncio.run(cenario())


def test_stopmove_com_falha_e_repetido_ate_dar_certo(caplog):
    async def cenario():
        robo = RoboFalso(falhar_paradas=3)
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=WATCHDOG_S, hz=HZ)
        await teleop.iniciar()
        try:
            teleop.definir(0.3, 0.0, 0.0)
            assert await _esperar(lambda: len(robo.movimentos) >= 1)
            assert await _esperar(lambda: robo.paradas >= 1, tentativas=100, intervalo=0.02)
            erro_apos_sucesso = teleop.ultimo_erro
            await asyncio.sleep(5.0 / HZ)
        finally:
            # confere antes de encerrar() (que manda o seu próprio StopMove)
            tentativas = robo.tentativas_parada
            paradas = robo.paradas
            await teleop.encerrar()
        return robo, tentativas, paradas, erro_apos_sucesso

    with caplog.at_level(logging.WARNING, logger="ares.teleop"):
        robo, tentativas, paradas, erro_apos_sucesso = asyncio.run(cenario())
    assert tentativas == 4  # 3 falhas + 1 sucesso, depois não repete
    assert paradas == 1
    assert erro_apos_sucesso is None  # erro limpo após o sucesso
    # nenhum Move depois da primeira tentativa de parada
    assert all(t < robo.instantes_paradas[0] for t in robo.instantes_movimentos)
    # log com vazão limitada: só a primeira falha em menos de 5 s
    falhas_logadas = [r for r in caplog.records if "erro ao parar" in r.getMessage()]
    assert len(falhas_logadas) == 1


def test_relogio_de_parede_voltando_nao_mantem_o_robo_andando(monkeypatch):
    estado = {"t": 1_000_000.0}

    def relogio_voltando():
        # relógio de parede andando para trás (ajuste de NTP, por exemplo)
        estado["t"] -= 10.0
        return estado["t"]

    monkeypatch.setattr(time, "time", relogio_voltando)

    async def cenario():
        robo = RoboFalso()
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=WATCHDOG_S, hz=HZ)
        await teleop.iniciar()
        try:
            teleop.definir(0.3, 0.0, 0.0)
            parou = await _esperar(lambda: robo.paradas >= 1, tentativas=50, intervalo=0.02)
        finally:
            await teleop.encerrar()
        return parou

    assert asyncio.run(cenario()) is True


# --- robustez a erros e vazamento de tarefas -------------------------------


def test_erros_do_robo_nao_derrubam_o_laco():
    async def cenario():
        robo = RoboFalso(falhar_mover=True)
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=1.0, hz=HZ)
        await teleop.iniciar()
        try:
            teleop.definir(0.3, 0.0, 0.0)
            assert await _esperar(lambda: teleop.ultimo_erro is not None)
            # o laço continua vivo mesmo após o erro
            await asyncio.sleep(3.0 / HZ)
            assert not teleop._tarefa.done()
            erro = teleop.ultimo_erro
        finally:
            await teleop.encerrar()
        return erro

    erro = asyncio.run(cenario())
    assert erro is not None


def test_iniciar_duas_vezes_nao_vaza_tarefas():
    async def cenario():
        robo = RoboFalso()
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=WATCHDOG_S, hz=HZ)
        await teleop.iniciar()
        tarefa1 = teleop._tarefa
        await teleop.iniciar()
        tarefa2 = teleop._tarefa
        await teleop.encerrar()
        return tarefa1, tarefa2

    tarefa1, tarefa2 = asyncio.run(cenario())
    assert tarefa1 is tarefa2


# --- integração com RoboSimulado ------------------------------------------


def test_teleop_funciona_com_robo_simulado():
    async def cenario():
        robo = RoboSimulado(vx_max=0.5, vy_max=0.3, vyaw_max=1.0, frequencia_hz=20.0)
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=WATCHDOG_S, hz=HZ)
        await robo.iniciar()
        await teleop.iniciar()
        try:
            teleop.definir(0.3, 0.0, 0.0)
            await asyncio.sleep(0.25)
            x_andando = robo.x
            # solta o heartbeat: watchdog deve zerar a velocidade
            await asyncio.sleep(0.4)
            x_parado_1 = robo.x
            await asyncio.sleep(0.15)
            x_parado_2 = robo.x
        finally:
            await teleop.encerrar()
            await robo.encerrar()
        return x_andando, x_parado_1, x_parado_2

    x_andando, x_parado_1, x_parado_2 = asyncio.run(cenario())
    assert x_andando > 0.0
    assert x_parado_2 == pytest.approx(x_parado_1, abs=1e-9)

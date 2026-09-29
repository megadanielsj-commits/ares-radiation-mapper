"""Testes do controlador de teleoperação (watchdog, saturação, StopMove único)."""
import asyncio
import time
from typing import List, Optional

import pytest

from ares.simulacao.robo import RoboSimulado
from ares.teleop import Teleop

HZ = 20.0
WATCHDOG_S = 0.1


class RoboFalso:
    """Robô falso que registra chamadas de `mover`/`parar_movimento`."""

    def __init__(self, falhar_mover: bool = False) -> None:
        self.movimentos: List[tuple] = []
        self.paradas = 0
        self.em_pe = True
        self._falhar_mover = falhar_mover

    async def iniciar(self) -> None:
        pass

    async def encerrar(self) -> None:
        pass

    def assinar_pose(self, cb) -> None:
        pass

    async def mover(self, vx, vy, vyaw) -> None:
        if self._falhar_mover:
            raise RuntimeError("robô com defeito")
        self.movimentos.append((vx, vy, vyaw))

    async def parar_movimento(self) -> None:
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
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=WATCHDOG_S, hz=HZ)
        teleop.definir(0.3, 0.0, 0.0)
        await teleop.parar()
        return robo

    robo = asyncio.run(cenario())
    assert robo.paradas == 1


def test_encerrar_para_o_robo():
    async def cenario():
        robo = RoboFalso()
        teleop = Teleop(robo, vx_max=0.5, vy_max=0.3, vyaw_max=1.0, watchdog_s=WATCHDOG_S, hz=HZ)
        await teleop.iniciar()
        teleop.definir(0.3, 0.0, 0.0)
        await asyncio.sleep(2.0 / HZ)
        await teleop.encerrar()
        return robo

    robo = asyncio.run(cenario())
    assert robo.paradas >= 1


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
        finally:
            await teleop.encerrar()
        return teleop

    teleop = asyncio.run(cenario())
    assert teleop.ultimo_erro is not None


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

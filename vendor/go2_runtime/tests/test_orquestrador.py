import asyncio
import contextlib
import math
import time
import warnings

import pytest

from ares.config import Config
from ares.missao import RepositorioMissoes
from ares.orquestrador import FONTE_PADRAO, Orquestrador, criar_orquestrador


class RadiacaoDesligada:
    def __init__(self):
        self.encerrada = False

    async def iniciar(self):
        pass

    async def encerrar(self):
        self.encerrada = True

    def assinar(self, cb):
        pass

    def estado(self):
        return {"conectado": False, "erro": "sem serviço", "detector_id": None}


def _config(tmp_path, **kw):
    base = dict(
        dados=str(tmp_path / "dados"),
        lado_area_m=12.0,
        latencia_leitura_s=0.001,
        vx_max=8.0,
        vy_max=8.0,
        vyaw_max=1.0,
    )
    base.update(kw)
    return Config(**base)


def _rapido(cfg, **kw):
    return criar_orquestrador(
        cfg,
        frequencia_robo_hz=50.0,
        periodo_detector_s=0.05,
        semente=7,
        periodo_publicacao_s=0.2,
        periodo_estado_s=0.05,
        **kw,
    )


async def _esperar(cond, limite_s=5.0):
    fim = time.monotonic() + limite_s
    while not cond():
        if time.monotonic() > fim:
            raise AssertionError("condição não atingida")
        await asyncio.sleep(0.01)


async def _ir_para(orq, x, y, v=8.0):
    """Leva o robô simulado até (x, y) só com comandos de teleop (heartbeat)."""
    robo, teleop = orq.robo, orq.teleop
    while True:
        dx, dy = x - robo.x, y - robo.y
        d = math.hypot(dx, dy)
        if d < 0.1:
            break
        f = min(v, d / 0.05) / d
        teleop.definir(dx * f, dy * f, 0.0)  # yaw fica 0: vx/vy = x/y do odom
        await asyncio.sleep(0.02)
    await teleop.parar()


def _tipos(fila):
    tipos = set()
    while not fila.empty():
        tipos.add(fila.get_nowait()["tipo"])
    return tipos


def test_zigue_zague_converge_para_a_fonte_padrao(tmp_path):
    async def cenario():
        orq = _rapido(_config(tmp_path))
        fila = orq.assinar()
        await orq.iniciar()
        try:
            await _esperar(lambda: orq.ultima_pose is not None)
            info = await orq.iniciar_missao("zz")
            assert info["centro"] == pytest.approx([0.0, 0.0], abs=0.05)
            for yl in (0.5, 2.5, 4.5):
                await _ir_para(orq, 0.0, yl)
                await _ir_para(orq, 6.0, yl)
            fim = await orq.encerrar_missao()
            snap = orq.snapshot()
        finally:
            await orq.encerrar()
        return fila, fim, snap

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fila, fim, snap = asyncio.run(cenario())

    r = fim["resultado"]
    assert fim["n_amostras"] > 50 and r["n"] == fim["n_amostras"]
    fx, fy, _ = FONTE_PADRAO
    assert math.hypot(r["x_map"] - fx, r["y_map"] - fy) < 1.5
    assert r["p_fonte"] is not None and r["p_fonte"] > 0.9
    for chave in ("s_no_limite", "b_no_limite", "fonte_na_borda", "missao_id"):
        assert chave in r
    assert {"pose", "leitura", "amostra", "estimativa", "mapa", "estado"} <= _tipos(fila)
    assert snap["missao"] is None and snap["resultado"]["missao_id"] == fim["id"]
    assert snap["fonte_sim"] == {"x": 4.0, "y": 3.0, "s": 2.0}

    repo = RepositorioMissoes(tmp_path / "dados")
    try:
        m = repo.obter(fim["id"])
        assert m["encerrada"] is not None and m["n_amostras"] == fim["n_amostras"]
        assert m["resultado"]["x_map"] == r["x_map"]
        assert m["fonte_sim"] == {"x": 4.0, "y": 3.0, "s": 2.0}
    finally:
        repo.fechar()


def test_eventos_de_pose_limitados_a_10hz(tmp_path):
    async def cenario():
        orq = _rapido(_config(tmp_path))
        fila = orq.assinar()
        await orq.iniciar()
        await asyncio.sleep(1.0)
        await orq.encerrar()
        return [e for e in _drenar(fila) if e["tipo"] == "pose"]

    poses = asyncio.run(cenario())
    assert 5 <= len(poses) <= 11


def _drenar(fila):
    out = []
    while not fila.empty():
        out.append(fila.get_nowait())
    return out


def test_iniciar_missao_sem_radiacao_levanta(tmp_path):
    async def cenario():
        from ares.simulacao.robo import RoboSimulado

        cfg = _config(tmp_path)
        robo, rad = RoboSimulado(), RadiacaoDesligada()
        orq = Orquestrador(cfg, robo, rad, RepositorioMissoes(cfg.dados))
        fila = orq.assinar()
        await orq.iniciar()
        try:
            await _esperar(lambda: orq.ultima_pose is not None)
            with pytest.raises(RuntimeError, match="radiação"):
                await orq.iniciar_missao()
            with pytest.raises(RuntimeError):
                await orq.encerrar_missao()
            eventos = _drenar(fila)
        finally:
            await orq.encerrar()
        return eventos, rad

    eventos, rad = asyncio.run(cenario())
    estados = [e["dados"] for e in eventos if e["tipo"] == "estado"]
    assert estados and estados[0]["radiacao"]["conectado"] is False
    assert estados[0]["robo"]["conectado"] is True
    assert rad.encerrada


def test_encerrar_missao_para_o_robo(tmp_path):
    """`encerrar_missao` deve parar o robô (via teleop) antes de terminar."""

    async def cenario():
        orq = _rapido(_config(tmp_path))
        robo, teleop = orq.robo, orq.teleop
        await orq.iniciar()
        try:
            await _esperar(lambda: orq.ultima_pose is not None)
            await orq.iniciar_missao()

            async def _manter_heartbeat():
                while True:
                    teleop.definir(5.0, 0.0, 0.0)
                    await asyncio.sleep(0.02)

            heartbeat = asyncio.create_task(_manter_heartbeat())
            try:
                await _esperar(lambda: robo._vx != 0.0)
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
                # sem watchdog (0,5 s por padrão) ainda por vir: se o robô
                # já estiver parado aqui, foi por causa do `encerrar_missao`.
                await orq.encerrar_missao()
                assert robo._vx == 0.0 and robo._vy == 0.0 and robo._vyaw == 0.0
            finally:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
        finally:
            await orq.encerrar()

    asyncio.run(cenario())


def test_fonte_simulada_e_modo_real(tmp_path):
    async def cenario():
        orq = _rapido(_config(tmp_path))
        await orq.iniciar()
        try:
            assert orq.definir_fonte_simulada(-2, 1, 5) == {"x": -2.0, "y": 1.0, "s": 5.0}
            assert orq.campo.fonte == (-2.0, 1.0, 5.0)
            with pytest.raises(ValueError):
                orq.definir_fonte_simulada(0, 0, -1)
            with pytest.raises(ValueError):
                orq.definir_fonte_simulada(float("nan"), 0, 1)
        finally:
            await orq.encerrar()

    asyncio.run(cenario())

    real = criar_orquestrador(_config(tmp_path, modo="real"))
    try:
        with pytest.raises(ValueError):
            real.definir_fonte_simulada(1, 1, 1)
        assert type(real.robo).__name__ == "Go2WebRTC"
        assert type(real.radiacao).__name__ == "ClienteFS5000"
    finally:
        real.repositorio.fechar()


def test_encerrar_salva_missao_ativa(tmp_path):
    async def cenario():
        orq = _rapido(_config(tmp_path))
        await orq.iniciar()
        await _esperar(lambda: orq.ultima_pose is not None)
        info = await orq.iniciar_missao()
        with pytest.raises(RuntimeError, match="ativa"):
            await orq.iniciar_missao()
        await asyncio.sleep(0.3)
        await orq.encerrar()
        return info["id"]

    mid = asyncio.run(cenario())
    repo = RepositorioMissoes(tmp_path / "dados")
    try:
        assert repo.obter(mid)["encerrada"] is not None
    finally:
        repo.fechar()

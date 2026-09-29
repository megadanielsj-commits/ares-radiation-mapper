import csv
import io
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ares.config import Config
from ares.orquestrador import criar_orquestrador
from ares.servidor.app import criar_app


def _esperar(cond, limite_s=5.0):
    fim = time.monotonic() + limite_s
    while not cond():
        if time.monotonic() > fim:
            raise AssertionError("condição não atingida")
        time.sleep(0.02)


@pytest.fixture
def cliente(tmp_path):
    cfg = Config(dados=str(tmp_path / "dados"), lado_area_m=6.0, latencia_leitura_s=0.01)
    orq = criar_orquestrador(
        cfg,
        frequencia_robo_hz=50.0,
        periodo_detector_s=0.05,
        semente=1,
        periodo_publicacao_s=0.1,
        periodo_estado_s=0.05,
    )
    with TestClient(criar_app(orq, orq.teleop)) as c:
        c.orq = orq
        _esperar(lambda: orq.ultima_pose is not None)
        yield c


def test_painel_e_estado(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "ARES" in r.text
    assert cliente.get("/static/index.html").status_code == 200
    e = cliente.get("/api/estado").json()
    assert e["modo"] == "simulacao"
    assert e["robo"]["conectado"] and e["radiacao"]["conectado"]
    assert e["missao"] is None and e["fonte_sim"] == {"x": 4.0, "y": 3.0, "s": 2.0}
    assert "teleop" in e and "pose" in e
    assert cliente.get("/camera.mjpg").status_code == 404


def test_seguranca_host_e_origem(cliente):
    assert cliente.get("/api/estado", headers={"host": "evil.com"}).status_code == 400
    r = cliente.post("/api/robo/parar", headers={"origin": "http://evil.com"})
    assert r.status_code == 403
    ok = cliente.post("/api/robo/parar", headers={"origin": "http://localhost:8000"})
    assert ok.status_code == 200
    with pytest.raises(WebSocketDisconnect) as exc:
        with cliente.websocket_connect("/ws", headers={"origin": "http://evil.com"}) as ws:
            ws.receive_json()
    assert exc.value.code == 1008
    with pytest.raises(WebSocketDisconnect) as exc:
        with cliente.websocket_connect("/ws/comando", headers={"origin": "http://evil.com"}) as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_missao_completa_e_exportacao(cliente):
    assert cliente.post("/api/missao/encerrar").status_code == 409
    r = cliente.post("/api/missao/iniciar", json={"nome": "teste"})
    assert r.status_code == 200
    mid = r.json()["id"]
    assert cliente.post("/api/missao/iniciar").status_code == 409
    _esperar(lambda: cliente.get("/api/estado").json()["missao"]["n_amostras"] >= 3)
    fim = cliente.post("/api/missao/encerrar")
    assert fim.status_code == 200 and fim.json()["resultado"]["n"] >= 3

    lista = cliente.get("/api/missoes").json()
    assert lista[0]["id"] == mid and lista[0]["nome"] == "teste"
    assert cliente.get(f"/api/missoes/{mid}").json()["resultado"] is not None
    assert cliente.get("/api/missoes/999").status_code == 404
    csv_r = cliente.get(f"/api/missoes/{mid}/amostras.csv")
    assert csv_r.status_code == 200 and csv_r.headers["content-type"].startswith("text/csv")
    assert len(list(csv.DictReader(io.StringIO(csv_r.text)))) >= 3
    j = cliente.get(f"/api/missoes/{mid}.json").json()
    assert j["missao"]["id"] == mid and len(j["amostras"]) >= 3
    assert cliente.get("/api/missoes/999.json").status_code == 404
    assert cliente.get("/api/missoes/999/amostras.csv").status_code == 404


def test_iniciar_missao_sem_corpo(cliente):
    assert cliente.post("/api/missao/iniciar").status_code == 200
    assert cliente.post("/api/missao/encerrar").status_code == 200


def test_fonte_simulada(cliente):
    r = cliente.post("/api/simulacao/fonte", json={"x": 1, "y": -1, "s": 3})
    assert r.status_code == 200 and r.json() == {"x": 1.0, "y": -1.0, "s": 3.0}
    assert cliente.orq.campo.fonte == (1.0, -1.0, 3.0)
    assert cliente.post("/api/simulacao/fonte", json={"x": 1, "y": 1, "s": -1}).status_code == 400
    assert cliente.post("/api/simulacao/fonte", json={"x": 1}).status_code == 422


def test_camera_gerador_mjpeg_produz_quadros_ate_desconectar():
    """`_gerador_mjpeg` só para quando o cliente desconecta (stream contínuo)."""
    import asyncio

    from ares.servidor.app import _gerador_mjpeg

    async def cenario():
        quadros = iter([b"\xff\xd8um", None, b"\xff\xd8dois"])
        voltas = {"n": 0}

        def obter_quadro():
            return next(quadros, None)

        async def desconectado():
            voltas["n"] += 1
            return voltas["n"] > 3  # desconecta depois da 3ª volta do laço

        saida = b"".join(
            [pedaco async for pedaco in _gerador_mjpeg(obter_quadro, desconectado, 0.0)]
        )
        return saida

    saida = asyncio.run(cenario())
    assert saida.count(b"Content-Type: image/jpeg") == 2  # o quadro None foi pulado
    assert b"\xff\xd8um" in saida and b"\xff\xd8dois" in saida
    assert saida.startswith(b"--quadroares")


def test_acoes_do_robo(cliente):
    robo = cliente.orq.robo
    assert cliente.post("/api/robo/deitar").status_code == 200 and not robo.em_pe
    assert cliente.post("/api/robo/levantar").status_code == 200 and robo.em_pe
    assert cliente.post("/api/robo/pular").status_code == 404


def test_ws_snapshot_e_eventos(cliente):
    with cliente.websocket_connect("/ws") as ws:
        primeiro = ws.receive_json()
        assert primeiro["tipo"] == "snapshot" and primeiro["dados"]["modo"] == "simulacao"
        tipos = {ws.receive_json()["tipo"] for _ in range(20)}
        assert {"pose", "leitura"} <= tipos


def test_ws_comando_move_e_fechar_para(cliente):
    robo = cliente.orq.robo
    x0 = robo.x
    with cliente.websocket_connect("/ws/comando") as ws:
        ws.send_text("não é json")
        ws.send_json({"vx": "abc"})
        for _ in range(10):
            ws.send_json({"vx": 0.5, "vy": 0, "vyaw": 0})
            time.sleep(0.05)
        _esperar(lambda: robo.x > x0 + 0.05)
        assert robo._vx == pytest.approx(0.5)
    _esperar(lambda: robo._vx == 0.0 and not cliente.orq.teleop._movendo, 2.0)
    x1 = robo.x
    time.sleep(0.1)
    assert robo.x == pytest.approx(x1)


def test_modo_real_rejeita_fonte(tmp_path):
    orq = criar_orquestrador(Config(modo="real", dados=str(tmp_path)))
    app = criar_app(orq, orq.teleop)
    try:
        # sem lifespan: nada conecta; só a rota
        c = TestClient(app)
        assert c.post("/api/simulacao/fonte", json={"x": 1, "y": 1, "s": 1}).status_code == 400
        assert c.post("/api/missao/iniciar").status_code == 409
        assert c.post("/api/robo/levantar").status_code == 409
    finally:
        orq.repositorio.fechar()


def test_main_le_ambiente_e_argumentos(tmp_path, monkeypatch, capsys):
    import ares.__main__ as principal

    chamadas = {}
    monkeypatch.setenv("ARES_DADOS", str(tmp_path))
    monkeypatch.setenv("ARES_PORTA", "8100")
    monkeypatch.setattr(principal.uvicorn, "run", lambda app, **kw: chamadas.update(kw, app=app))
    criados = []
    original = principal.criar_orquestrador
    monkeypatch.setattr(principal, "criar_orquestrador", lambda cfg: criados.append(original(cfg)) or criados[-1])
    principal.main(["--porta", "8123"])
    try:
        assert chamadas["port"] == 8123 and chamadas["host"] == "127.0.0.1"
        assert criados[0].config.modo == "simulacao" and criados[0].config.dados == str(tmp_path)
        assert "http://localhost:8123" in capsys.readouterr().out
    finally:
        criados[0].repositorio.fechar()

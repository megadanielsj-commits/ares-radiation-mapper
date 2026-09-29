"""API REST e WebSockets do ARES (painel, missão, simulação, robô e teleop).

Segurança igual ao serviço do FS-5000: só Host localhost/127.0.0.1 (e
`testserver` do TestClient); Origin, se presente, só localhost/127.0.0.1 —
POST com outra origem → 403 e WebSocket → fechamento 1008.

Teleop: `WS /ws/comando` recebe `{vx, vy, vyaw}` (heartbeat ≥ 5 Hz) e repassa
a `teleop.definir`; ao fechar ou cair a conexão, `teleop.parar()`.
"""
import contextlib
import math
import pathlib
import re
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

ESTATICO = pathlib.Path(__file__).parent / "static"
HOSTS_CONFIAVEIS = ["localhost", "127.0.0.1", "testserver"]  # "testserver": TestClient
_ORIGEM_LOCAL = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")
ACOES_ROBO = ("levantar", "deitar", "parar")


def origem_permitida(origin: Optional[str]) -> bool:
    """Sem Origin (curl, TestClient) é permitido; com Origin, só localhost/127.0.0.1."""
    return origin is None or bool(_ORIGEM_LOCAL.match(origin))


class PedidoMissao(BaseModel):
    nome: Optional[str] = None


class FonteSimulada(BaseModel):
    x: float
    y: float
    s: float


def _velocidade(msg) -> Optional[tuple]:
    try:
        v = tuple(float(msg.get(k, 0.0)) for k in ("vx", "vy", "vyaw"))
    except (AttributeError, TypeError, ValueError):
        return None
    return v if all(math.isfinite(x) for x in v) else None


def criar_app(orquestrador, teleop) -> FastAPI:
    orq = orquestrador
    repo = orq.repositorio

    @contextlib.asynccontextmanager
    async def ciclo(_app):
        await orq.iniciar()
        await teleop.iniciar()
        try:
            yield
        finally:
            await teleop.encerrar()
            await orq.encerrar()

    app = FastAPI(title="ARES", lifespan=ciclo)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=HOSTS_CONFIAVEIS)

    @app.middleware("http")
    async def restringir_origem(request, chamar_proximo):
        if request.method == "POST" and not origem_permitida(request.headers.get("origin")):
            return Response(status_code=403, content="origem não permitida")
        return await chamar_proximo(request)

    def estado() -> dict:
        return dict(orq.snapshot(), teleop={"erro": teleop.ultimo_erro})

    @app.get("/api/estado")
    def api_estado():
        return estado()

    # ------------------------------------------------------------------ missão
    @app.post("/api/missao/iniciar")
    async def iniciar_missao(corpo: Optional[PedidoMissao] = None):
        try:
            return await orq.iniciar_missao(corpo.nome if corpo else None)
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/missao/encerrar")
    async def encerrar_missao():
        try:
            return await orq.encerrar_missao()
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/missoes")
    def missoes():
        return repo.listar()

    @app.get("/api/missoes/{id_:int}.json")
    def missao_json(id_: int):
        try:
            return repo.exportar_json(id_)
        except KeyError:
            raise HTTPException(404, f"missão {id_} não encontrada")

    @app.get("/api/missoes/{id_:int}/amostras.csv")
    def missao_csv(id_: int):
        try:
            texto = repo.exportar_csv(id_)
        except KeyError:
            raise HTTPException(404, f"missão {id_} não encontrada")
        return Response(
            texto,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="ares_missao_{id_}.csv"'},
        )

    @app.get("/api/missoes/{id_:int}")
    def missao(id_: int):
        m = repo.obter(id_)
        if m is None:
            raise HTTPException(404, f"missão {id_} não encontrada")
        return m

    # ------------------------------------------------------------------ simulação e robô
    @app.post("/api/simulacao/fonte")
    def fonte_simulada(corpo: FonteSimulada):
        try:
            return orq.definir_fonte_simulada(corpo.x, corpo.y, corpo.s)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/robo/{acao}")
    async def robo(acao: str):
        if acao not in ACOES_ROBO:
            raise HTTPException(404, f"ação deve ser uma de {ACOES_ROBO}")
        await teleop.parar()
        try:
            if acao == "levantar":
                await orq.robo.levantar()
            elif acao == "deitar":
                await orq.robo.deitar()
        except (RuntimeError, TimeoutError) as e:
            raise HTTPException(409, str(e))
        return {"ok": True}

    @app.get("/camera.mjpg")
    def camera():
        # o driver atual do Go2 não expõe o vídeo; sem câmera → 404
        raise HTTPException(404, "câmera indisponível")

    # ------------------------------------------------------------------ WebSockets
    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        if not origem_permitida(sock.headers.get("origin")):
            await sock.close(code=1008)
            return
        await sock.accept()
        fila = orq.assinar()
        try:
            await sock.send_json({"tipo": "snapshot", "dados": estado()})
            while True:
                await sock.send_json(await fila.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            orq.cancelar(fila)

    @app.websocket("/ws/comando")
    async def ws_comando(sock: WebSocket):
        if not origem_permitida(sock.headers.get("origin")):
            await sock.close(code=1008)
            return
        await sock.accept()
        try:
            while True:
                try:
                    msg = await sock.receive_json()
                except ValueError:
                    continue
                v = _velocidade(msg)
                if v is not None:
                    teleop.definir(*v)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await teleop.parar()

    app.mount("/static", StaticFiles(directory=ESTATICO), name="static")

    @app.get("/")
    def painel():
        return FileResponse(ESTATICO / "index.html")

    return app

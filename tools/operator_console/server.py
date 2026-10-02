"""Local-only unified ARES console with explicit simulation input selection."""
import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
import os
import re

from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

from ares_mapper.api.app import create_app as classic_app
from tools.operator_console.runtime import ConsoleRuntime, ROOT, Setup, MODES

ASSETS = Path(__file__).parent / "static"
ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")


class Control(BaseModel):
    client: str
    linear_m_s: float = 0
    yaw_rate_rad_s: float = 0


class Enable(BaseModel):
    client: str
    acknowledge_physical_robot: bool = False


def create_app(data=None, factories=None, manage_usb=True):
    runtime = ConsoleRuntime(data or os.getenv("ARES_DADOS", ROOT/"resultados/console"), factories, manage_usb)
    app = classic_app(runtime)
    app.state.console = runtime
    closing = asyncio.Event()

    @asynccontextmanager
    async def lifespan(_app):
        await runtime.open()
        try:
            yield
        finally:
            closing.set()
            await runtime.close()

    app.router.lifespan_context = lifespan
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            if origin and not ORIGIN.fullmatch(origin):
                from fastapi.responses import Response
                return Response("Origem não permitida", status_code=403)
            if request.url.path.startswith("/api/v1/"):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Use os controles do console ARES."}, status_code=409)
        return await call_next(request)

    # Replace only the page. The original simulator page and all its files are retained.
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) not in ("/", "/api/v1/ws/telemetry")]
    app.mount("/console-static", StaticFiles(directory=ASSETS), name="console-static")

    @app.get("/", response_class=HTMLResponse)
    async def page():
        root = ROOT/"src/ares_mapper/web"
        text = (ASSETS/"index.html").read_text(encoding="utf-8")
        text = text.replace("{{CLASSIC_CSS}}", (root/"static/styles.css").read_text())
        text = text.replace("{{CLASSIC_JS}}", (root/"static/app.js").read_text())
        return HTMLResponse(text, headers={"Cache-Control": "no-store"})

    @app.get("/api/console/state")
    async def state():
        return runtime.snapshot()

    @app.websocket("/api/v1/ws/telemetry")
    async def telemetry(websocket: WebSocket):
        origin = websocket.headers.get("origin")
        if origin and not ORIGIN.fullmatch(origin):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        disconnected = asyncio.Event()
        async def receive():
            try:
                while True:
                    await websocket.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                disconnected.set()
        receiver = asyncio.create_task(receive())
        try:
            await websocket.send_json({"type":"mission_state", "payload":runtime.status()})
            async with runtime.event_bus.subscribe() as queue:
                while not closing.is_set() and not disconnected.is_set():
                    try:
                        event = await asyncio.wait_for(queue.get(), .5)
                    except asyncio.TimeoutError:
                        continue
                    await asyncio.wait_for(websocket.send_json(event), 2)
        except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
            pass
        finally:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            with suppress(Exception):
                await websocket.close()

    @app.post("/api/console/configure")
    async def configure(body: Setup):
        try:
            return await runtime.configure(body)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/console/start")
    async def start():
        try:
            mission = await runtime.start()
            return {"mission_id": mission, "state": runtime.state.value}
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/console/stop")
    async def stop():
        await runtime.stop()
        return runtime.snapshot()

    @app.post("/api/console/brake")
    async def brake():
        await runtime.brake()
        return {"stopped": True}

    @app.post("/api/console/enable-control")
    async def enable(body: Enable):
        if runtime.state.value != "RUNNING":
            raise HTTPException(409, "Inicie a missão antes de habilitar o controle.")
        if MODES[runtime.mode]["robot"] == "real" and not body.acknowledge_physical_robot:
            raise HTTPException(409, "Confirme no console que o controle moverá o Go2 real.")
        if runtime.control_enabled and runtime.operator != body.client:
            raise HTTPException(409, "Outra sessão está controlando o robô.")
        runtime.operator, runtime.control_enabled = body.client, True
        return {"enabled": True}

    @app.post("/api/console/control")
    async def control(body: Control):
        try:
            await runtime.command(body.linear_m_s, body.yaw_rate_rad_s, body.client)
            return {"accepted": True}
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/console/export")
    async def export():
        directory = runtime.mission_directory
        if directory is None:
            raise HTTPException(404, "Nenhuma missão registrada.")
        if runtime.state.value in ("RUNNING", "STOPPING", "PAUSED"):
            raise HTTPException(409, "Encerre e salve a missão para baixar os dados.")
        import io
        import zipfile
        from fastapi.responses import Response
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(directory))
        return Response(buffer.getvalue(), media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="ARES_{runtime.mission_id}.zip"'})

    return app


if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8001, log_level="info")

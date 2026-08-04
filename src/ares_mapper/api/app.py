"""FastAPI application factory and local dashboard assets."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ares_mapper.api.routes import router as api_router
from ares_mapper.api.websocket import router as websocket_router
from ares_mapper.core.mission_controller import MissionController
from ares_mapper.version import __version__


def create_app(
    controller: MissionController,
    *,
    scenario_directory: Path | None = None,
    auto_start: bool = False,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if auto_start and app.state.controller.state.value == "READY":
            await app.state.controller.start()
        try:
            yield
        finally:
            active_controller = app.state.controller
            if active_controller.state.value in {"RUNNING", "PAUSED"}:
                await active_controller.stop("server_shutdown")

    app = FastAPI(
        title="ARES Radiation Mapper",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.controller = controller
    app.state.scenario_directory = (scenario_directory or Path("config/scenarios")).resolve()
    package_root = Path(__file__).resolve().parents[1]
    web_root = package_root / "web"
    dashboard_html = (
        (web_root / "templates" / "index.html")
        .read_text(encoding="utf-8")
        .replace(
            "{{INLINE_STYLES}}",
            (web_root / "static" / "styles.css").read_text(encoding="utf-8"),
        )
        .replace(
            "{{INLINE_APP}}",
            (web_root / "static" / "app.js").read_text(encoding="utf-8"),
        )
        .replace("{{VERSION}}", __version__)
    )
    app.mount(
        "/static",
        StaticFiles(directory=web_root / "static"),
        name="static",
    )
    app.include_router(api_router)
    app.include_router(websocket_router)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(
            dashboard_html,
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
            },
        )

    return app

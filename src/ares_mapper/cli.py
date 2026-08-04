"""Command-line interface for operation, headless simulation and replay."""

from __future__ import annotations

import asyncio
import json
import threading
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from ares_mapper.api.app import create_app
from ares_mapper.config import ScenarioConfig, load_scenario
from ares_mapper.core.mission_controller import MissionController
from ares_mapper.runtime import RuntimeMode, load_runtime_scenario
from ares_mapper.validation.monte_carlo import run_reference_validation

app = typer.Typer(
    name="ares-map",
    help="ARES Radiation Mapper — simulação, operação, replay e exportação.",
    no_args_is_help=True,
)


def _open_browser_later(url: str) -> None:
    timer = threading.Timer(1.2, lambda: webbrowser.open(url))
    timer.daemon = True
    timer.start()


def _serve_dashboard(
    config: ScenarioConfig,
    scenario: Path,
    *,
    host: str | None,
    port: int | None,
    open_browser: bool,
    auto_start: bool,
) -> None:
    bind_host = host or config.application.bind_host
    bind_port = port or config.application.bind_port
    controller = MissionController(config)
    fastapi_app = create_app(
        controller,
        scenario_directory=scenario.resolve().parent,
        auto_start=auto_start,
    )
    if open_browser:
        browser_host = "127.0.0.1" if bind_host == "0.0.0.0" else bind_host
        _open_browser_later(f"http://{browser_host}:{bind_port}")
    uvicorn.run(fastapi_app, host=bind_host, port=bind_port, log_level="info")


@app.command()
def start(
    mode: Annotated[
        RuntimeMode,
        typer.Option(
            "--mode",
            envvar="ARES_MODE",
            help="simulation ou hardware (Go2 + FS-5000).",
        ),
    ] = RuntimeMode.SIMULATION,
    network_interface: Annotated[
        str | None,
        typer.Option(
            "--network-interface",
            envvar="ARES_NETWORK_INTERFACE",
            help="Interface de rede conectada ao Go2; exigida em hardware.",
        ),
    ] = None,
    serial_port: Annotated[
        str,
        typer.Option(
            "--serial-port",
            envvar="ARES_SERIAL_PORT",
            help="Porta serial do FS-5000; usada somente em hardware.",
        ),
    ] = "auto",
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port", min=1, max=65535)] = None,
    open_browser: Annotated[bool, typer.Option("--open-browser/--no-open-browser")] = True,
) -> None:
    """Start ARES in simulation or complete hardware mode."""

    try:
        scenario, config = load_runtime_scenario(
            mode,
            network_interface=network_interface,
            serial_port=serial_port,
        )
    except ValueError as exc:
        typer.echo(f"Erro de configuração: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"ARES mode: {mode.value}")
    _serve_dashboard(
        config,
        scenario,
        host=host,
        port=port,
        open_browser=open_browser,
        auto_start=mode is RuntimeMode.HARDWARE,
    )


@app.command()
def run(
    scenario: Annotated[
        Path,
        typer.Option("--scenario", "-s", exists=True, dir_okay=False, readable=True),
    ] = Path("config/scenarios/static_source.yaml"),
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port", min=1, max=65535)] = None,
    open_browser: Annotated[bool, typer.Option("--open-browser/--no-open-browser")] = True,
    auto_start: Annotated[bool, typer.Option("--auto-start/--manual-start")] = False,
) -> None:
    """Serve the local operator dashboard."""
    config = load_scenario(scenario)
    _serve_dashboard(
        config,
        scenario,
        host=host,
        port=port,
        open_browser=open_browser,
        auto_start=auto_start,
    )


@app.command()
def simulate(
    scenario: Annotated[
        Path,
        typer.Option("--scenario", "-s", exists=True, dir_okay=False, readable=True),
    ] = Path("config/scenarios/static_source.yaml"),
    speed: Annotated[float, typer.Option("--speed", min=0.1, max=500)] = 100.0,
    duration: Annotated[float | None, typer.Option("--duration", min=0.1)] = None,
    output: Annotated[Path | None, typer.Option("--output", file_okay=False)] = None,
) -> None:
    """Run a complete deterministic mission without opening the dashboard."""

    async def execute() -> None:
        config = load_scenario(scenario)
        config.mission.simulation_speed = speed
        if duration is not None:
            config.mission.duration_s = duration
        if output is not None:
            config.application.data_directory = output
        controller = MissionController(config)
        mission_id = await controller.start()
        await controller.wait_until_complete()
        typer.echo(
            json.dumps(
                {
                    "mission_id": mission_id,
                    "state": controller.state.value,
                    "directory": str(controller.mission_directory),
                    "counts": controller.status()["counts"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    asyncio.run(execute())


@app.command()
def replay(
    mission_directory: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=False, readable=True),
    ],
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8000,
    open_browser: Annotated[bool, typer.Option("--open-browser/--no-open-browser")] = True,
) -> None:
    """Open a recorded mission in the same dashboard."""
    controller = asyncio.run(MissionController.from_mission(mission_directory))
    fastapi_app = create_app(controller, scenario_directory=Path("config/scenarios"))
    if open_browser:
        _open_browser_later(f"http://{host}:{port}")
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


@app.command()
def export(
    mission_directory: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=False, readable=True),
    ],
) -> None:
    """Regenerate every export for an existing mission."""

    async def execute() -> None:
        controller = await MissionController.from_mission(mission_directory)
        paths = await controller.export()
        for path in paths:
            typer.echo(path)

    asyncio.run(execute())


@app.command("validate-scenario")
def validate_scenario(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Validate YAML and print its configuration hash."""
    config = load_scenario(scenario)
    typer.echo(f"Válido: {config.mission.name}")
    typer.echo(f"SHA-256: {config.configuration_hash()}")


@app.command("inspect-fs5000")
def inspect_fs5000(
    port: Annotated[str, typer.Option("--port")] = "auto",
) -> None:
    """Show the serial configuration used by the live FS-5000 adapter."""
    typer.echo(
        "Adaptador FS-5000 disponível em modo somente leitura.\n"
        f"Porta: {port}; serial: 115200 8N1; comando contínuo: AA 05 0E 01 BE 55.\n"
        "Use detector.source_type=fs5000_serial e instale o extra fs5000."
    )


@app.command("inspect-unitree")
def inspect_unitree(
    interface: Annotated[str, typer.Option("--interface")] = "enp3s0",
    domain_id: Annotated[int, typer.Option("--domain-id", min=0)] = 0,
) -> None:
    """Show the Unitree SDK2 configuration used by the live pose adapter."""
    typer.echo(
        "Adaptador Unitree SportModeState disponível quando unitree_sdk2py estiver "
        "instalado e o tópico DDS estiver acessível.\n"
        f"Configuração: interface={interface}, domain_id={domain_id}, "
        "tópico=rt/sportmodestate."
    )


@app.command("validate-v03")
def validate_v03(
    scenario: Annotated[
        Path,
        typer.Option("--scenario", "-s", exists=True, dir_okay=False, readable=True),
    ] = Path("config/scenarios/probabilistic_reference.yaml"),
    source_trials: Annotated[int, typer.Option("--source-trials", min=1)] = 100,
    background_trials: Annotated[int, typer.Option("--background-trials", min=1)] = 100,
    output: Annotated[Path | None, typer.Option("--output", dir_okay=False)] = None,
) -> None:
    """Run the V0.3 Monte Carlo acceptance scenario and background control."""

    config = load_scenario(scenario)
    report = run_reference_validation(
        config,
        source_trials=source_trials,
        background_trials=background_trials,
    )
    payload = report.as_dict()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    typer.echo(rendered)
    if not report.passed:
        raise typer.Exit(code=1)

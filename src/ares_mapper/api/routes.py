"""REST routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ares_mapper.api.schemas import (
    ExportRequest,
    FaultRequest,
    ManualControlRequest,
    SimpleSimulationStartRequest,
    SourcePatch,
    SpeedPatch,
    StepRequest,
    TrajectoryPatch,
)
from ares_mapper.config import ScenarioConfig, load_scenario
from ares_mapper.core.mission_controller import MissionController
from ares_mapper.domain.enums import MissionState

router = APIRouter(prefix="/api/v1")


def controller_for(request: Request) -> MissionController:
    return request.app.state.controller


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    return controller_for(request).status()


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    return controller_for(request).health()


@router.get("/scenario")
async def scenario(request: Request) -> dict[str, Any]:
    return controller_for(request).scenario.model_dump(mode="json")


@router.put("/scenario")
async def replace_scenario(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    controller = controller_for(request)
    if controller.state in {
        MissionState.RUNNING,
        MissionState.PAUSED,
        MissionState.STOPPING,
    }:
        raise HTTPException(409, "stop the active mission before replacing the scenario")
    validated = ScenarioConfig.model_validate(payload)
    request.app.state.controller = MissionController(validated)
    return validated.model_dump(mode="json")


@router.get("/scenarios")
async def scenarios(request: Request) -> dict[str, Any]:
    directory: Path = request.app.state.scenario_directory
    items = []
    if directory.exists():
        for path in sorted(directory.glob("*.yaml")):
            try:
                config = load_scenario(path)
                items.append(
                    {
                        "filename": path.name,
                        "name": config.mission.name,
                        "duration_s": config.mission.duration_s,
                        "temporal_mode": config.mapping.temporal_mode,
                    }
                )
            except Exception:
                continue
    return {"items": items}


@router.post("/scenarios/{filename}/load")
async def load_named_scenario(filename: str, request: Request) -> dict[str, Any]:
    controller = controller_for(request)
    if controller.state in {
        MissionState.RUNNING,
        MissionState.PAUSED,
        MissionState.STOPPING,
    }:
        raise HTTPException(409, "stop the active mission before loading another scenario")
    safe_name = Path(filename).name
    path: Path = request.app.state.scenario_directory / safe_name
    if path.suffix != ".yaml" or not path.exists():
        raise HTTPException(404, "scenario not found")
    new_controller = MissionController(load_scenario(path))
    request.app.state.controller = new_controller
    return new_controller.scenario.model_dump(mode="json")


@router.patch("/scenario/sources/{source_id}")
async def patch_source(source_id: str, patch: SourcePatch, request: Request) -> dict[str, Any]:
    try:
        event = await controller_for(request).update_source(
            source_id, patch.model_dump(exclude_none=True)
        )
    except KeyError as exc:
        raise HTTPException(404, f"source not found: {source_id}") from exc
    return event.model_dump(mode="json")


@router.patch("/scenario/trajectory")
async def patch_trajectory(patch: TrajectoryPatch, request: Request) -> dict[str, Any]:
    event = await controller_for(request).update_trajectory(patch.model_dump(exclude_none=True))
    return event.model_dump(mode="json")


@router.post("/mission/start")
async def start_mission(request: Request) -> dict[str, Any]:
    try:
        mission_id = await controller_for(request).start()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"mission_id": mission_id, "state": "RUNNING"}


@router.post("/simulation/start")
async def start_simple_simulation(
    body: SimpleSimulationStartRequest,
    request: Request,
) -> dict[str, Any]:
    """Atomically configure and start the minimal manual simulation."""

    controller = controller_for(request)
    if controller.state in {MissionState.RUNNING, MissionState.PAUSED}:
        await controller.stop(reason="operator_restart")
    try:
        source = controller.configure_static_simulation_source(
            x_m=body.x_m,
            y_m=body.y_m,
            dose_rate_at_1m_uSv_h=body.dose_rate_at_1m_uSv_h,
        )
        mission_id = await controller.start()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "mission_id": mission_id,
        "state": "RUNNING",
        "source": source,
    }


@router.post("/mission/pause")
async def pause_mission(request: Request) -> dict[str, Any]:
    try:
        await controller_for(request).pause()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return controller_for(request).status()


@router.post("/mission/resume")
async def resume_mission(request: Request) -> dict[str, Any]:
    try:
        await controller_for(request).resume()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return controller_for(request).status()


@router.post("/mission/step")
async def step_mission(body: StepRequest, request: Request) -> dict[str, Any]:
    try:
        time_ns = await controller_for(request).step(body.delta_s)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"simulation_time_ns": time_ns}


@router.post("/mission/speed")
async def mission_speed(body: SpeedPatch, request: Request) -> dict[str, Any]:
    await controller_for(request).set_speed(body.speed)
    return controller_for(request).status()


@router.post("/mission/control")
async def mission_control(body: ManualControlRequest, request: Request) -> dict[str, Any]:
    try:
        event = await controller_for(request).manual_control(
            body.linear_m_s,
            body.yaw_rate_rad_s,
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return event.model_dump(mode="json")


@router.post("/mission/stop")
async def stop_mission(request: Request) -> dict[str, Any]:
    await controller_for(request).stop()
    return controller_for(request).status()


@router.post("/mission/fault")
async def inject_fault(body: FaultRequest, request: Request) -> dict[str, Any]:
    try:
        event = await controller_for(request).inject_fault(body.target, body.fault)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return event.model_dump(mode="json")


@router.get("/mission/{mission_id}")
async def mission_metadata(mission_id: str, request: Request) -> dict[str, Any]:
    controller = controller_for(request)
    if controller.mission_id != mission_id:
        raise HTTPException(404, "mission not loaded")
    return controller.status()


@router.get("/mission/{mission_id}/samples")
async def mission_samples(
    mission_id: str,
    request: Request,
    kind: str = Query(default="mapped"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, Any]:
    controller = controller_for(request)
    if controller.mission_id != mission_id:
        raise HTTPException(404, "mission not loaded")
    try:
        rows = await controller.samples(kind, offset, limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"items": rows, "offset": offset, "limit": limit}


@router.get("/samples")
async def current_samples(
    request: Request,
    kind: str = Query(default="mapped"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, Any]:
    try:
        rows = await controller_for(request).samples(kind, offset, limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"items": rows, "offset": offset, "limit": limit}


@router.get("/map/latest")
async def latest_map(request: Request) -> dict[str, Any]:
    controller = controller_for(request)
    if controller.latest_map is None:
        if controller.map_service is None:
            raise HTTPException(404, "map is not available")
        controller.latest_map = controller.map_service.predict(controller.current_time_ns)
    return controller.latest_map.model_dump(mode="json")


@router.get("/posterior/latest")
async def latest_posterior(request: Request) -> dict[str, Any]:
    posterior = controller_for(request).latest_posterior
    if posterior is None:
        raise HTTPException(404, "source posterior is not available")
    return posterior.model_dump(mode="json")


@router.get("/exposure")
async def exposure(request: Request) -> dict[str, Any]:
    controller = controller_for(request)
    if controller.latest_map is None or controller.latest_map.exposure is None:
        raise HTTPException(404, "mission exposure is not available")
    return controller.latest_map.exposure.model_dump(mode="json")


@router.get("/map/at/{time_ns}")
async def map_at(time_ns: int, request: Request) -> dict[str, Any]:
    try:
        prediction = await controller_for(request).map_at(time_ns)
    except RuntimeError as exc:
        raise HTTPException(404, str(exc)) from exc
    return prediction.model_dump(mode="json")


@router.post("/export")
async def export_mission(body: ExportRequest, request: Request) -> dict[str, Any]:
    del body
    try:
        paths = await controller_for(request).export()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"files": [str(path) for path in paths]}

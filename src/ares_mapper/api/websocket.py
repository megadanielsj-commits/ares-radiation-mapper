"""Live WebSocket telemetry endpoint."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/api/v1/ws/telemetry")
async def telemetry(websocket: WebSocket) -> None:
    await websocket.accept()
    controller = websocket.app.state.controller
    await websocket.send_json(
        {
            "schema_version": "1.0",
            "type": "mission_state",
            "payload": controller.status(),
        }
    )
    try:
        async with controller.event_bus.subscribe() as queue:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
    except WebSocketDisconnect:
        return

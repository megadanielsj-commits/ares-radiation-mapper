"""In-process telemetry fan-out for the API and dashboard."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from pydantic import BaseModel


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    async def publish(self, event_type: str, payload: BaseModel | dict[str, Any]) -> None:
        data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        envelope = {"schema_version": "1.0", "type": event_type, "payload": data}
        for queue in tuple(self._subscribers):
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(envelope)

    @asynccontextmanager
    async def subscribe(
        self, max_queue_size: int = 128
    ) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue_size)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

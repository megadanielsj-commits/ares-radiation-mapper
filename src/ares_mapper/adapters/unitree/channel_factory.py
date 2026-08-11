"""Process-wide single-shot init for the Unitree DDS channel factory.

``ChannelFactoryInitialize`` may only run once per process. Both the read-only
pose subscriber and the sport commander need it, so they share this helper.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

_lock = asyncio.Lock()
_initialized: tuple[int, str] | None = None


def _default_initializer(domain_id: int, network_interface: str) -> None:
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize

    ChannelFactoryInitialize(domain_id, network_interface)


async def ensure_channel_factory(
    domain_id: int,
    network_interface: str,
    *,
    initializer: Callable[[int, str], None] | None = None,
) -> None:
    """Initialize the DDS channel factory once; later calls are no-ops.

    Raises RuntimeError if called again with different parameters.
    """

    global _initialized
    async with _lock:
        if _initialized is not None:
            if _initialized != (domain_id, network_interface):
                raise RuntimeError(
                    "channel factory already initialized with "
                    f"{_initialized}, cannot re-init with "
                    f"{(domain_id, network_interface)}"
                )
            return
        init = initializer or _default_initializer
        await asyncio.to_thread(init, domain_id, network_interface)
        _initialized = (domain_id, network_interface)


def _reset_for_tests() -> None:
    global _initialized
    _initialized = None

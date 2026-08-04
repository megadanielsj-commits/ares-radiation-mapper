"""Repository facade reserved for alternative persistence backends."""

from ares_mapper.storage.database import MissionStore

__all__ = ["MissionStore"]

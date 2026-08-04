"""ROS 2 SportModeState adapter boundary."""

from ares_mapper.adapters.unitree.sdk2_source import UnitreeSdk2PoseSource


class UnitreeRos2SportModePoseSource(UnitreeSdk2PoseSource):
    """Backward-compatible name for the SDK2 DDS SportModeState transport."""

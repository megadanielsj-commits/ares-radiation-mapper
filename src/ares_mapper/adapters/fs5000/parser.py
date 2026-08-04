"""Pure parser for captured FS-5000 packets and ASCII payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass

PAYLOAD_PATTERN = re.compile(
    r"^DR:(?P<dr>\d+(?:\.\d+)?)uSv/h;"
    r"D:(?P<dose>\d+(?:\.\d+)?)uSv;"
    r"CPS:(?P<cps>\d+);"
    r"CPM:(?P<cpm>\d+);"
    r"AVG:(?P<avg>\d+(?:\.\d+)?)uSv/h;"
    r"DT:(?P<dt>\d+);"
    r"S:(?P<timed>\d+(?:\.\d+)?)uSv;"
    r"W:(?P<alarm>\d+)$"
)


@dataclass(frozen=True, slots=True)
class FS5000Payload:
    dose_rate_uSv_h: float
    cumulative_dose_uSv: float
    cps: int
    cpm: int
    average_dose_rate_uSv_h: float
    timer_s: int
    timed_dose_uSv: float
    alarm: bool
    raw_payload: str


def parse_payload(payload: str | bytes) -> FS5000Payload:
    text = payload.decode("ascii") if isinstance(payload, bytes) else payload
    text = text.strip().replace("μ", "u").replace("µ", "u")
    match = PAYLOAD_PATTERN.fullmatch(text)
    if match is None:
        raise ValueError(f"invalid FS-5000 payload: {text!r}")
    values = match.groupdict()
    return FS5000Payload(
        dose_rate_uSv_h=float(values["dr"]),
        cumulative_dose_uSv=float(values["dose"]),
        cps=int(values["cps"]),
        cpm=int(values["cpm"]),
        average_dose_rate_uSv_h=float(values["avg"]),
        timer_s=int(values["dt"]),
        timed_dose_uSv=float(values["timed"]),
        alarm=bool(int(values["alarm"])),
        raw_payload=text,
    )


def checksum(data: bytes) -> int:
    return sum(data) % 256


def frame_command(payload: bytes) -> bytes:
    framed = b"\xaa" + bytes([len(payload) + 3]) + payload
    return framed + bytes([checksum(framed)]) + b"\x55"


def parse_frame(frame: bytes) -> bytes:
    if len(frame) < 5:
        raise ValueError("FS-5000 frame is too short")
    if frame[0] != 0xAA or frame[-1] != 0x55:
        raise ValueError("invalid FS-5000 frame markers")
    if frame[1] != len(frame) - 1:
        raise ValueError("invalid FS-5000 frame length")
    expected = checksum(frame[:-2])
    if frame[-2] != expected:
        raise ValueError(f"invalid FS-5000 checksum: {frame[-2]:02x} != {expected:02x}")
    return frame[2:-2]

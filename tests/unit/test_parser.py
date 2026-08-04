import pytest

from ares_mapper.adapters.fs5000.parser import (
    frame_command,
    parse_frame,
    parse_payload,
)


def test_parse_real_payload_shape() -> None:
    parsed = parse_payload(
        "DR:0.18uSv/h;D:0.26uSv;CPS:0001;CPM:000033;AVG:0.23uSv/h;DT:0000000;S:0.00uSv;W:0"
    )
    assert parsed.dose_rate_uSv_h == 0.18
    assert parsed.cpm == 33
    assert parsed.alarm is False


def test_command_framing_round_trip() -> None:
    payload = b"\x0e\x01"
    assert parse_frame(frame_command(payload)) == payload


def test_bad_payload_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_payload("DR:not-a-number")

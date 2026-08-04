import pytest

from ares_mapper.core.health import mark_sample
from ares_mapper.domain.models import SourceHealth


def test_mark_sample_tracks_observed_cadence() -> None:
    health = SourceHealth(source_id="source")
    mark_sample(health, 100_000_000, 1)
    mark_sample(health, 150_000_000, 2)
    mark_sample(health, 200_000_000, 3)

    assert health.received_count == 3
    assert health.observed_rate_hz == pytest.approx(20.0)

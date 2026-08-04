import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from ares_mapper.fusion.trajectory import quadrature_weights
from ares_mapper.inference.particle_filter import normalize_log_weights
from ares_mapper.mapping.idw import interpolate


@given(
    st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
)
def test_idw_between_two_positive_values(first: float, second: float) -> None:
    result = interpolate(
        np.asarray([[0.5, 0.0]]),
        np.asarray([[0.0, 0.0], [1.0, 0.0]]),
        np.asarray([first, second]),
        np.asarray([0, 0]),
        at_time_ns=0,
        power=2,
        epsilon_m=0.02,
        influence_radius_m=2,
        maximum_neighbors=2,
    )[0]
    assert min(first, second) <= result <= max(first, second)


@given(
    st.lists(
        st.floats(
            min_value=-1e6,
            max_value=1e6,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=1,
        max_size=128,
    )
)
def test_normalized_particle_weights_are_finite(values: list[float]) -> None:
    normalized, _ = normalize_log_weights(np.asarray(values, dtype=float))
    assert np.isfinite(normalized).all()
    assert np.sum(np.exp(normalized)) == pytest.approx(1.0)


@given(
    st.lists(
        st.integers(min_value=1, max_value=1_000_000),
        min_size=1,
        max_size=64,
    )
)
def test_quadrature_weights_sum_to_elapsed_time(deltas_ns: list[int]) -> None:
    times = np.cumsum(np.asarray([0, *deltas_ns], dtype=np.int64)).tolist()
    weights = quadrature_weights(times)
    assert all(weight >= 0 for weight in weights)
    assert sum(weights) == pytest.approx((times[-1] - times[0]) / 1e9)

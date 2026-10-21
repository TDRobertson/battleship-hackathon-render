import random

import pytest

pytest.importorskip("hypothesis")

from hypothesis import given
from hypothesis import strategies as st

from core.models import Outcome, PublicShotResult
from sdk.observation import ObservationState
from sdk.targeting import (
    available_shots,
    choose_random,
    contiguous_runs,
    hit_neighbors,
    line_extensions,
    orthogonal_neighbors,
    unresolved_hits,
)


@given(row=st.integers(0, 9), col=st.integers(0, 9))
def test_orthogonal_neighbors_contract(row, col):
    shape = (10, 10)

    result = orthogonal_neighbors((row, col), shape)

    assert len(result) == len(set(result))
    assert all(0 <= r < shape[0] and 0 <= c < shape[1] for r, c in result)
    assert all(abs(row - r) + abs(col - c) == 1 for r, c in result)


def test_unresolved_hits_and_available_shots_contract():
    state = ObservationState()
    state.apply_result(PublicShotResult((1, 1), Outcome.HIT))
    state.apply_result(PublicShotResult((2, 2), Outcome.MISS))
    snapshot = state.snapshot()

    assert unresolved_hits(snapshot) == [(1, 1)]
    assert (1, 1) not in available_shots(snapshot)
    assert (2, 2) not in available_shots(snapshot)
    assert (0, 0) in available_shots(snapshot)


def test_candidate_generators_return_unique_available_cells():
    state = ObservationState()
    state.apply_result(PublicShotResult((5, 5), Outcome.HIT))
    state.apply_result(PublicShotResult((5, 6), Outcome.HIT))
    snapshot = state.snapshot()
    available = set(available_shots(snapshot))

    for candidates in (hit_neighbors(snapshot), line_extensions(snapshot)):
        assert len(candidates) == len(set(candidates))
        assert set(candidates).issubset(available)


def test_choose_random_contract_and_empty_error():
    candidates = [(0, 0), (0, 0), (1, 1)]

    assert choose_random(candidates, random.Random(2)) in {(0, 0), (1, 1)}
    with pytest.raises(RuntimeError):
        choose_random([], random.Random(1))


def test_contiguous_runs_contract():
    assert contiguous_runs([]) == []
    assert contiguous_runs([1, 2, 3, 5, 7, 8]) == [[1, 2, 3], [5], [7, 8]]

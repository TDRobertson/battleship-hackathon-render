import pytest

pytest.importorskip("hypothesis")

from hypothesis import given
from hypothesis import strategies as st

from core.models import Outcome, PublicShotResult, ShipPlacement
from core.rules import official_rules
from sdk.observation import ObservationState
from sdk.summary import known_cells, remaining_ship_lengths, shot_count, unknown_cells
from sdk.validation import fleet_errors, is_legal_fleet, is_legal_shot, shot_errors


@given(row=st.integers(0, 9), col=st.integers(0, 9))
def test_known_and_unknown_cells_partition_board(row, col):
    state = ObservationState()
    state.apply_result(PublicShotResult((row, col), Outcome.MISS))
    snapshot = state.snapshot()
    known = known_cells(snapshot)
    unknown = unknown_cells(snapshot)

    assert known.isdisjoint(unknown)
    assert len(known | unknown) == 100
    assert shot_count(snapshot) == len(known)


def test_remaining_ship_lengths_contract_after_sunk_ship():
    rules = official_rules()
    state = ObservationState(rules)

    assert remaining_ship_lengths(rules, state.snapshot()) == list(rules.fleet)


def test_fleet_validation_wrapper_matches_error_list():
    rules = official_rules()
    legal = [
        ShipPlacement(0, 0, 0, "horizontal"),
        ShipPlacement(1, 1, 0, "horizontal"),
        ShipPlacement(2, 2, 0, "horizontal"),
        ShipPlacement(3, 3, 0, "horizontal"),
        ShipPlacement(4, 4, 0, "horizontal"),
    ]
    illegal = legal[:-1]

    assert fleet_errors(rules, legal) == []
    assert is_legal_fleet(rules, legal)
    assert fleet_errors(rules, illegal)
    assert not is_legal_fleet(rules, illegal)


def test_shot_validation_wrapper_matches_error_list():
    rules = official_rules()
    state = ObservationState(rules)
    state.apply_result(PublicShotResult((4, 4), Outcome.MISS))
    snapshot = state.snapshot()

    assert shot_errors(rules, snapshot, (0, 0)) == []
    assert is_legal_shot(rules, snapshot, (0, 0))
    assert shot_errors(rules, snapshot, (4, 4))
    assert not is_legal_shot(rules, snapshot, (4, 4))
    assert shot_errors(rules, snapshot, (-1, 0))
    assert shot_errors(rules, snapshot, (1.5, 0))

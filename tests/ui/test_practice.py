import pytest

from core.models import Outcome
from core.rules import official_rules
from sdk.observation import ObservationState
from ui.practice import PracticeTarget, practice_fire


def test_practice_fire_records_miss_and_rejects_repeat():
    target = PracticeTarget({0: ((0, 0), (0, 1))})
    observation = ObservationState(official_rules())

    result = practice_fire(target, observation, (9, 9))

    assert result.outcome is Outcome.MISS
    assert observation.snapshot().misses[9, 9] == 1
    with pytest.raises(ValueError):
        practice_fire(target, observation, (9, 9))


def test_practice_fire_turns_last_ship_cell_into_sunk_result():
    target = PracticeTarget({0: ((0, 0), (0, 1))})
    observation = ObservationState(official_rules())

    first = practice_fire(target, observation, (0, 0))
    second = practice_fire(target, observation, (0, 1))

    snapshot = observation.snapshot()
    assert first.outcome is Outcome.HIT
    assert second.outcome is Outcome.SUNK
    assert second.sunk_ship is not None
    assert snapshot.hits[0, 0] == 0
    assert snapshot.sunk[0, 0] == 1
    assert snapshot.sunk[0, 1] == 1
    assert target.all_sunk

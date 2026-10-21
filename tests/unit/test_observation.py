import numpy as np
import pytest

from core.models import Outcome, PublicShotResult, SunkShip
from sdk.observation import ObservationState, VersionGap
from sdk.protocol import shot_result_message


def test_sinking_moves_all_cells_from_hits_to_sunk():
    obs = ObservationState()
    obs.apply_result(PublicShotResult((4, 4), Outcome.HIT))
    obs.apply_result(PublicShotResult((4, 5), Outcome.HIT))
    obs.apply_result(PublicShotResult((4, 6), Outcome.SUNK, SunkShip(3, ((4, 4), (4, 5), (4, 6)))))
    assert obs.hits[4, 4] == 0
    assert obs.hits[4, 5] == 0
    assert obs.sunk[4, 4] == 1
    assert obs.sunk[4, 6] == 1
    assert obs.ships_alive[3] == 0
    assert np.all(obs.misses + obs.hits + obs.sunk <= 1)


def test_snapshots_are_independent():
    obs = ObservationState()
    before = obs.snapshot()
    obs.apply_result(PublicShotResult((0, 0), Outcome.MISS))
    assert before.misses[0, 0] == 0


def test_duplicate_gap_and_snapshot_rules():
    obs = ObservationState()
    msg = shot_result_message("m", "a1", 1, PublicShotResult((0, 0), Outcome.MISS))
    obs.apply_update(msg)
    assert obs.version == 1
    assert obs.apply_update({**msg, "observation_version": 1}) is None
    with pytest.raises(VersionGap):
        obs.apply_update({**msg, "observation_version": 3, "shot": [0, 1]})
    newer = obs.snapshot()
    older = ObservationState().snapshot()
    obs.replace_from_snapshot(older)
    assert obs.version == newer.version

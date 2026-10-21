import pytest

from core.models import Outcome, PublicShotResult, SunkShip
from sdk.protocol import result_from_message, shot_result_message
from sdk.replay import ReplayLog


def test_shot_result_protocol_round_trip_without_sunk_ship():
    result = PublicShotResult((3, 4), Outcome.HIT)

    message = shot_result_message("match", "action", 7, result)

    assert result_from_message(message) == result


def test_shot_result_protocol_round_trip_with_sunk_ship():
    result = PublicShotResult((3, 4), Outcome.SUNK, SunkShip(2, ((3, 2), (3, 3), (3, 4))))

    message = shot_result_message("match", "action", 7, result)

    assert result_from_message(message) == result


def test_protocol_rejects_unsupported_version_and_message_type():
    message = shot_result_message("match", "action", 1, PublicShotResult((0, 0), Outcome.MISS))

    with pytest.raises(ValueError):
        result_from_message({**message, "protocol_version": 999})
    with pytest.raises(ValueError):
        result_from_message({**message, "type": "other"})


def test_replay_log_json_round_trip():
    replay = ReplayLog(
        rules={"rows": 10, "cols": 10},
        software_version="test",
        actions=[{"type": "shot", "coord": [1, 2]}],
        timing=[{"player": "A", "remaining": 119.5}],
        termination={"winner": "A", "reason": "all ships sunk"},
        private={"debug": True},
    )

    assert ReplayLog.from_json(replay.to_json()) == replay

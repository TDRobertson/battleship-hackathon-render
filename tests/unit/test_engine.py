import pytest

from core.engine import GameEngine, InvalidAction
from core.models import Outcome, Phase, Player, ShipPlacement


def fleet():
    return [
        ShipPlacement(0, 0, 0, "horizontal"),
        ShipPlacement(1, 1, 0, "horizontal"),
        ShipPlacement(2, 2, 0, "horizontal"),
        ShipPlacement(3, 3, 0, "horizontal"),
        ShipPlacement(4, 4, 0, "horizontal"),
    ]


def other_fleet():
    return [
        ShipPlacement(0, 5, 0, "horizontal"),
        ShipPlacement(1, 6, 0, "horizontal"),
        ShipPlacement(2, 7, 0, "horizontal"),
        ShipPlacement(3, 8, 0, "horizontal"),
        ShipPlacement(4, 9, 0, "horizontal"),
    ]


def test_both_fleets_required_before_battle():
    engine = GameEngine()
    engine.place_fleet(Player.A, fleet())
    assert engine.phase is Phase.PLACEMENT
    engine.place_fleet(Player.B, other_fleet())
    assert engine.phase is Phase.BATTLE


def test_invalid_placement_is_atomic():
    engine = GameEngine()
    bad = fleet()
    bad[1] = ShipPlacement(1, 0, 0, "vertical")
    with pytest.raises(InvalidAction):
        engine.place_fleet(Player.A, bad)
    assert engine.fleet_cells(Player.A) == {}


def test_negative_shot_rejected_before_indexing():
    engine = GameEngine()
    engine.place_fleet(Player.A, fleet())
    engine.place_fleet(Player.B, other_fleet())
    with pytest.raises(InvalidAction):
        engine.fire(Player.A, -1, 0)


def test_hit_sunk_and_turn_order():
    engine = GameEngine()
    engine.place_fleet(Player.A, fleet())
    engine.place_fleet(Player.B, other_fleet())
    assert engine.fire(Player.A, 5, 0).outcome is Outcome.HIT
    assert engine.active_player is Player.B
    assert engine.fire(Player.B, 0, 9).outcome is Outcome.MISS
    assert engine.active_player is Player.A
    for col in [1, 2, 3, 4]:
        result = engine.fire(Player.A, 5, col)
        if col < 4:
            assert result.outcome is Outcome.HIT
            engine.fire(Player.B, 1, col + 5)
    assert result.outcome is Outcome.SUNK
    assert result.sunk_ship.slot == 0


def test_repeated_shot_is_illegal_loss_candidate():
    engine = GameEngine()
    engine.place_fleet(Player.A, fleet())
    engine.place_fleet(Player.B, other_fleet())
    engine.fire(Player.A, 9, 9)
    engine.fire(Player.B, 0, 9)
    with pytest.raises(InvalidAction):
        engine.fire(Player.A, 9, 9)

from bots.hunt_target import HuntTargetBot
from core.engine import GameEngine
from core.models import Outcome, Player, PublicShotResult
from sdk.observation import ObservationState
from core.rules import official_rules


def test_placement_is_reproducible_and_valid():
    rules = official_rules()
    a = HuntTargetBot.seeded(7).place_ships(rules, 120)
    b = HuntTargetBot.seeded(7).place_ships(rules, 120)
    assert a == b
    engine = GameEngine(rules)
    engine.place_fleet(Player.A, a)
    assert set(engine.fleet_cells(Player.A)) == set(rules.slots)


def test_hunt_returns_available_coordinate():
    obs = ObservationState().snapshot()
    shot = HuntTargetBot.seeded(1).choose_shot(obs, 120)
    assert obs.available_shots()[shot]


def test_single_hit_targets_orthogonal_neighbor():
    state = ObservationState()
    state.apply_result(PublicShotResult((5, 5), Outcome.HIT))
    shot = HuntTargetBot.seeded(1).choose_shot(state.snapshot(), 120)
    assert shot in {(4, 5), (6, 5), (5, 4), (5, 6)}


def test_collinear_hits_prefer_extension():
    state = ObservationState()
    state.apply_result(PublicShotResult((5, 5), Outcome.HIT))
    state.apply_result(PublicShotResult((5, 6), Outcome.HIT))
    shot = HuntTargetBot.seeded(1).choose_shot(state.snapshot(), 120)
    assert shot in {(5, 4), (5, 7)}


def test_hunt_target_candidate_strategy_prefers_lines_then_neighbors_then_hunt():
    bot = HuntTargetBot.seeded(1)
    empty = ObservationState().snapshot()
    assert len(bot._candidates(empty)) == 100

    single_hit = ObservationState()
    single_hit.apply_result(PublicShotResult((5, 5), Outcome.HIT))
    assert set(bot._candidates(single_hit.snapshot())) == {(4, 5), (5, 4), (5, 6), (6, 5)}

    line_hit = ObservationState()
    line_hit.apply_result(PublicShotResult((5, 5), Outcome.HIT))
    line_hit.apply_result(PublicShotResult((5, 6), Outcome.HIT))
    assert set(bot._candidates(line_hit.snapshot())) == {(5, 4), (5, 7)}

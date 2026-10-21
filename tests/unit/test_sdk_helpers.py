import random

from core.models import Outcome, PublicShotResult, ShipPlacement
from core.rules import official_rules
from sdk.board import center_distance, checkerboard_cells, diagonal_band_cells, edge_cells, in_bounds, manhattan, neighbors
from sdk.neural import (
    PlacementObservation,
    RewardScheme,
    action_to_coord,
    coord_to_action,
    default_placement_encoder,
    default_observation_encoder,
    legal_placement_action_mask,
    outcome_reward,
    placement_action_to_placement,
    placement_to_action,
    sample_action,
    with_ship_slot_placed_channels,
    with_ship_slot_alive_channels,
)
from sdk.observation import ObservationState
from sdk.placement import (
    fleet_cells,
    fleet_from_specs,
    legal_ship_placements,
    mirror_fleet_horizontal,
    mirror_fleet_vertical,
    placement,
    random_legal_fleet,
    rotate_fleet_180,
    ship_cells,
)
from sdk.summary import has_unresolved_hits, known_cells, remaining_ship_lengths, shot_count, unknown_cells
from sdk.targeting import available_shots, hit_neighbors, line_extensions
from sdk.validation import fleet_errors, is_legal_shot, shot_errors


def test_legal_ship_placements_respect_bounds_and_overlap():
    rules = official_rules()
    occupied = {(0, 0), (0, 1)}
    placements = legal_ship_placements(rules, slot=4, occupied=occupied)
    assert ShipPlacement(4, 0, 0, "horizontal") not in placements
    assert ShipPlacement(4, 0, 2, "horizontal") in placements
    assert all(set(ship_cells(rules, placement)).isdisjoint(occupied) for placement in placements)


def test_random_legal_fleet_is_reproducible():
    rules = official_rules()
    assert random_legal_fleet(rules, random.Random(10)) == random_legal_fleet(rules, random.Random(10))


def test_board_helpers_are_neutral_coordinate_tools():
    rules = official_rules()

    assert in_bounds(rules, (0, 0))
    assert not in_bounds(rules, (-1, 0))
    assert manhattan((0, 0), (3, 4)) == 7
    assert set(neighbors(rules, (0, 0), diagonals=True)) == {(0, 1), (1, 0), (1, 1)}
    assert (0, 0) in checkerboard_cells(rules)
    assert (0, 5) in edge_cells(rules)
    assert center_distance(rules, (4, 4)) == 1.0


def test_diagonal_band_cells_support_spacing_and_offsets():
    rules = official_rules()

    every_third = diagonal_band_cells(rules, spacing=3, offset=0)
    shifted = diagonal_band_cells(rules, spacing=3, offset=1)

    assert (0, 0) in every_third
    assert (0, 1) not in every_third
    assert (0, 2) not in every_third
    assert (0, 3) in every_third
    assert all((row + col) % 3 == 0 for row, col in every_third)
    assert all((row + col + 1) % 3 == 0 for row, col in shifted)
    assert set(every_third).isdisjoint(shifted)


def test_checkerboard_cells_matches_diagonal_bands_with_spacing_two():
    rules = official_rules()

    assert checkerboard_cells(rules, offset=0) == diagonal_band_cells(rules, spacing=2, offset=0)
    assert checkerboard_cells(rules, offset=1) == diagonal_band_cells(rules, spacing=2, offset=1)


def test_diagonal_band_cells_reject_invalid_spacing():
    rules = official_rules()

    try:
        diagonal_band_cells(rules, spacing=0)
    except ValueError as exc:
        assert "spacing" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_placement_construction_and_transform_helpers():
    rules = official_rules()
    fleet = fleet_from_specs(
        rules,
        [
            (0, 0, 0, "horizontal"),
            (1, 2, 0, "vertical"),
        ],
    )

    assert fleet[0] == placement(0, 0, 0, "horizontal")
    assert fleet_cells(rules, fleet)[0] == ((0, 0), (0, 1), (0, 2), (0, 3), (0, 4))
    assert mirror_fleet_horizontal(rules, [fleet[0]]) == [ShipPlacement(0, 0, 5, "horizontal")]
    assert mirror_fleet_vertical(rules, [fleet[1]]) == [ShipPlacement(1, 4, 0, "vertical")]
    assert rotate_fleet_180(rules, [fleet[0]]) == [ShipPlacement(0, 9, 5, "horizontal")]


def test_targeting_helpers_return_only_available_cells():
    state = ObservationState()
    state.apply_result(PublicShotResult((5, 5), Outcome.HIT))
    state.apply_result(PublicShotResult((5, 6), Outcome.HIT))
    state.apply_result(PublicShotResult((5, 4), Outcome.MISS))
    snapshot = state.snapshot()

    assert line_extensions(snapshot) == [(5, 7)]
    assert (5, 4) not in available_shots(snapshot)
    assert set(hit_neighbors(snapshot)).issubset(set(available_shots(snapshot)))


def test_observation_summary_helpers():
    rules = official_rules()
    state = ObservationState(rules)
    state.apply_result(PublicShotResult((5, 5), Outcome.HIT))
    snapshot = state.snapshot()

    assert shot_count(snapshot) == 1
    assert remaining_ship_lengths(rules, snapshot) == [5, 4, 3, 3, 2]
    assert known_cells(snapshot) == {(5, 5)}
    assert (0, 0) in unknown_cells(snapshot)
    assert has_unresolved_hits(snapshot)


def test_validation_helpers_explain_illegal_actions():
    rules = official_rules()
    overlapping = [
        ShipPlacement(0, 0, 0, "horizontal"),
        ShipPlacement(1, 0, 0, "vertical"),
    ]
    assert fleet_errors(rules, overlapping)

    state = ObservationState(rules)
    state.apply_result(PublicShotResult((5, 5), Outcome.MISS))
    assert shot_errors(rules, state.snapshot(), (5, 5)) == ["shot has already been taken"]
    assert is_legal_shot(rules, state.snapshot(), (0, 0))


def test_neural_observation_encoder_can_add_ship_alive_channels():
    rules = official_rules()
    state = ObservationState(rules)
    state.apply_result(PublicShotResult((5, 5), Outcome.HIT))
    encoder = with_ship_slot_alive_channels(default_observation_encoder(), rules)

    channels = encoder.encode(state.snapshot(), rules)

    assert channels.shape == (12, rules.rows, rules.cols)
    assert encoder.names[-1] == "ship_4_alive"


def test_neural_placement_encoder_and_action_mask():
    rules = official_rules()
    placed = [placement(0, 0, 0, "horizontal")]
    observation = PlacementObservation.from_placements(rules, placed, next_slot=4)
    encoder = with_ship_slot_placed_channels(default_placement_encoder(), rules)
    legal = placement(4, 2, 2, "horizontal")
    overlapping = placement(4, 0, 0, "horizontal")

    channels = encoder.encode(observation, rules)
    mask = legal_placement_action_mask(rules, observation, slot=4)

    assert channels.shape == (9, rules.rows, rules.cols)
    assert encoder.names[:4] == ("occupied", "available", "next_ship_length", "fraction_done")
    assert channels[0, 0, 0] == 1.0
    assert mask[placement_to_action(legal, rules)]
    assert not mask[placement_to_action(overlapping, rules)]
    assert placement_action_to_placement(placement_to_action(legal, rules), rules, 4) == legal


def test_neural_action_and_reward_helpers():
    rules = official_rules()
    assert action_to_coord(coord_to_action((3, 4), rules), rules) == (3, 4)
    assert sample_action([0.0, 1.0], random.Random(1)) == 1

    miss = PublicShotResult((0, 0), Outcome.MISS)
    sunk = PublicShotResult((0, 1), Outcome.SUNK)
    scheme = RewardScheme(miss=-0.2, hit=0.5, sunk=2.0, win=5.0)

    assert outcome_reward(miss, False, scheme) == -0.2
    assert outcome_reward(sunk, True, scheme) == 7.0

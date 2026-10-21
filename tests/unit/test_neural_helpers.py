import random

import numpy as np
import pytest

pytest.importorskip("hypothesis")

from hypothesis import given
from hypothesis import strategies as st

from core.models import Outcome, PublicShotResult
from core.rules import official_rules
from sdk.neural import (
    ObservationEncoder,
    PlacementEncoder,
    PlacementObservation,
    RewardScheme,
    action_to_coord,
    available_mask,
    coord_to_action,
    default_placement_encoder,
    default_observation_encoder,
    greedy_action,
    legal_placement_action_mask,
    outcome_reward,
    placement_action_options,
    placement_action_to_placement,
    placement_to_action,
    sample_action,
    ship_alive_length_channel,
    ship_slot_alive_channel,
    with_ship_slot_placed_channels,
    with_ship_slot_alive_channels,
)
from sdk.observation import ObservationState
from sdk.placement import placement


def test_default_observation_encoder_contract():
    rules = official_rules()
    state = ObservationState(rules)
    state.apply_result(PublicShotResult((5, 5), Outcome.HIT))
    encoder = default_observation_encoder(include_ship_alive=True)

    channels = encoder.encode(state.snapshot(), rules)

    assert encoder.channel_count == len(encoder.names)
    assert channels.shape == (encoder.channel_count, rules.rows, rules.cols)


def test_observation_encoder_rejects_name_mismatch():
    with pytest.raises(ValueError):
        ObservationEncoder((), ("extra",))


def test_placement_encoder_rejects_name_mismatch():
    with pytest.raises(ValueError):
        PlacementEncoder((), ("extra",))


def test_ship_alive_channels_contract():
    rules = official_rules()
    state = ObservationState(rules)
    encoder = with_ship_slot_alive_channels(default_observation_encoder(), rules)
    snapshot = state.snapshot()

    channels = encoder.encode(snapshot, rules)

    assert channels.shape[0] == 7 + len(rules.fleet)
    assert np.all(ship_alive_length_channel(snapshot, rules) == 1.0)
    assert np.all(ship_slot_alive_channel(0)(snapshot, rules) == 1.0)


def test_default_placement_encoder_contract():
    rules = official_rules()
    placed = [placement(0, 0, 0, "horizontal")]
    observation = PlacementObservation.from_placements(rules, placed, next_slot=1)
    encoder = default_placement_encoder()

    channels = encoder.encode(observation, rules)

    assert encoder.names == ("occupied", "available", "next_ship_length", "fraction_done")
    assert channels.shape == (encoder.channel_count, rules.rows, rules.cols)
    assert channels[0, 0, 0] == 1.0
    assert channels[1, 0, 0] == 0.0
    assert channels[2, 0, 0] == rules.ship_length(1) / max(rules.fleet)
    assert channels[3, 0, 0] == 1 / len(rules.fleet)


def test_placement_slot_channels_and_action_mask_contract():
    rules = official_rules()
    placed = [placement(0, 0, 0, "horizontal")]
    observation = PlacementObservation.from_placements(rules, placed, next_slot=4)
    encoder = with_ship_slot_placed_channels(default_placement_encoder(), rules)

    channels = encoder.encode(observation, rules)
    mask = legal_placement_action_mask(rules, observation, slot=4)
    options = placement_action_options(rules, slot=4)
    overlapping = placement(4, 0, 0, "horizontal")
    legal = placement(4, 2, 2, "horizontal")

    assert channels.shape[0] == 4 + len(rules.fleet)
    assert encoder.names[-1] == "ship_4_placed"
    assert mask.dtype == bool
    assert len(mask) == len(options)
    assert not mask[placement_to_action(overlapping, rules)]
    assert mask[placement_to_action(legal, rules)]
    assert placement_action_to_placement(placement_to_action(legal, rules), rules, slot=4) == legal


@given(row=st.integers(0, 9), col=st.integers(0, 9))
def test_action_conversion_round_trip(row, col):
    rules = official_rules()

    assert action_to_coord(coord_to_action((row, col), rules), rules) == (row, col)


def test_available_mask_matches_observation():
    state = ObservationState()
    state.apply_result(PublicShotResult((0, 0), Outcome.MISS))

    assert np.array_equal(available_mask(state.snapshot()), state.snapshot().available_shots())


def test_greedy_action_respects_mask_and_rejects_empty_mask():
    scores = np.array([[1.0, 100.0], [2.0, 3.0]])
    mask = np.array([[True, False], [True, True]])

    assert greedy_action(scores, mask) == 3
    with pytest.raises(RuntimeError):
        greedy_action(scores, np.zeros_like(mask, dtype=bool))


def test_sample_action_returns_positive_probability_index_and_rejects_empty_distribution():
    assert sample_action(np.array([0.0, 0.0, 1.0]), random.Random(1)) == 2
    with pytest.raises(RuntimeError):
        sample_action(np.array([0.0, 0.0]), random.Random(1))


def test_outcome_reward_contract():
    scheme = RewardScheme(miss=-0.1, hit=0.3, sunk=2.0, win=5.0)

    assert outcome_reward(PublicShotResult((0, 0), Outcome.MISS), False, scheme) == -0.1
    assert outcome_reward(PublicShotResult((0, 0), Outcome.HIT), False, scheme) == 0.3
    assert outcome_reward(PublicShotResult((0, 0), Outcome.SUNK), True, scheme) == 7.0

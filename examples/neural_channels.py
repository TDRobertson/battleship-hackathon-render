from __future__ import annotations

from sdk.neural import (
    ObservationEncoder,
    PlacementObservation,
    available_channel,
    default_placement_encoder,
    hits_channel,
    legal_placement_action_mask,
    misses_channel,
    with_ship_slot_alive_channels,
    with_ship_slot_placed_channels,
)


def compact_shooting_encoder():
    """A small shooting observation: misses, hits, and legal target cells."""

    return ObservationEncoder(
        channels=(misses_channel, hits_channel, available_channel),
        names=("misses", "hits", "available"),
    )


def shooting_encoder_with_ship_flags(rules):
    """Add one constant channel for each ship slot still alive."""

    return with_ship_slot_alive_channels(compact_shooting_encoder(), rules)


def placement_inputs_for_slot(rules, placed_so_far, slot):
    """Build placement-stage channels and a legal action mask for one ship."""

    observation = PlacementObservation.from_placements(rules, placed_so_far, next_slot=slot)
    encoder = with_ship_slot_placed_channels(default_placement_encoder(), rules)
    channels = encoder.encode(observation, rules)
    mask = legal_placement_action_mask(rules, observation, slot)
    return channels, mask

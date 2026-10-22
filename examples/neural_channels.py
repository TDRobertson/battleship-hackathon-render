"""Example: build neural-network inputs without committing to a model.

The SDK deliberately stops at observation tensors and legal-action masks. It
does not choose a neural architecture, optimizer, replay buffer, or training
loop for you. These helpers show the small pieces a model-facing bot or
training script usually needs before it hands data to PyTorch, JAX, or another
library.
"""

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
    """Return a minimal shooting encoder.

    The default encoder includes more tactical helper channels. This compact
    version keeps only public shot history and legal actions, which is useful
    when you want to test whether extra engineered channels actually help.
    """

    return ObservationEncoder(
        channels=(misses_channel, hits_channel, available_channel),
        names=("misses", "hits", "available"),
    )


def shooting_encoder_with_ship_flags(rules):
    """Add one constant channel for each ship slot still alive.

    For the official fleet this appends `ship_0_alive` through `ship_4_alive`.
    Each channel is either all 1.0 or all 0.0, so the model can know which
    specific ship slots remain without learning that from the `sunk` mask.
    """

    return with_ship_slot_alive_channels(compact_shooting_encoder(), rules)


def placement_inputs_for_slot(rules, placed_so_far, slot):
    """Build placement-stage channels and a legal action mask for one ship.

    `placed_so_far` is the partial fleet your placement policy has already
    chosen. The returned `channels` array is shaped `(channels, rows, cols)`.
    The returned `mask` is a flat Boolean vector over every possible placement
    action for `slot`; illegal overlapping placements are marked `False`.
    """

    observation = PlacementObservation.from_placements(rules, placed_so_far, next_slot=slot)
    encoder = with_ship_slot_placed_channels(default_placement_encoder(), rules)
    channels = encoder.encode(observation, rules)
    mask = legal_placement_action_mask(rules, observation, slot)
    return channels, mask

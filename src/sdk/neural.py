from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from core.models import Coord, Outcome, PublicShotResult, ShipPlacement
from core.rules import Rules
from sdk.observation import ObservationSnapshot
from sdk.placement import legal_ship_placements, ship_cells
from sdk.targeting import hit_neighbors, line_extensions


ChannelBuilder = Callable[[ObservationSnapshot, Rules], np.ndarray]
PlacementChannelBuilder = Callable[["PlacementObservation", Rules], np.ndarray]


@dataclass(frozen=True, slots=True)
class ObservationEncoder:
    """Build neural-network input planes from a public observation.

    Channel order is intentionally explicit so participants can add, remove, or
    reorder channels while keeping the model construction easy to understand.
    """

    channels: tuple[ChannelBuilder, ...]
    names: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.channels) != len(self.names):
            raise ValueError("channels and names must have the same length")

    @property
    def channel_count(self) -> int:
        return len(self.channels)

    def encode(self, observation: ObservationSnapshot, rules: Rules) -> np.ndarray:
        planes = [builder(observation, rules).astype(float, copy=False) for builder in self.channels]
        return np.stack(planes)


@dataclass(frozen=True, slots=True)
class PlacementObservation:
    """Public information available while building your own fleet."""

    occupied: np.ndarray
    placed_slots: np.ndarray
    next_slot: int | None = None

    @classmethod
    def empty(cls, rules: Rules, next_slot: int | None = None) -> "PlacementObservation":
        return cls(
            np.zeros((rules.rows, rules.cols), dtype=np.uint8),
            np.zeros((len(rules.fleet),), dtype=np.uint8),
            next_slot,
        )

    @classmethod
    def from_placements(
        cls,
        rules: Rules,
        placements: list[ShipPlacement],
        next_slot: int | None = None,
    ) -> "PlacementObservation":
        occupied = np.zeros((rules.rows, rules.cols), dtype=np.uint8)
        placed_slots = np.zeros((len(rules.fleet),), dtype=np.uint8)
        for placement in placements:
            placed_slots[placement.slot] = 1
            for row, col in ship_cells(rules, placement):
                occupied[row, col] = 1
        return cls(occupied, placed_slots, next_slot)

    def available_cells(self) -> np.ndarray:
        return self.occupied == 0


@dataclass(frozen=True, slots=True)
class PlacementEncoder:
    """Build neural-network input planes for ship-placement decisions."""

    channels: tuple[PlacementChannelBuilder, ...]
    names: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.channels) != len(self.names):
            raise ValueError("channels and names must have the same length")

    @property
    def channel_count(self) -> int:
        return len(self.channels)

    def encode(self, observation: PlacementObservation, rules: Rules) -> np.ndarray:
        planes = [builder(observation, rules).astype(float, copy=False) for builder in self.channels]
        return np.stack(planes)


def default_observation_encoder(include_ship_alive: bool = False) -> ObservationEncoder:
    channels: list[ChannelBuilder] = [
        misses_channel,
        hits_channel,
        sunk_channel,
        available_channel,
        hit_neighbors_channel,
        line_extensions_channel,
        parity_channel,
    ]
    names = ["misses", "hits", "sunk", "available", "hit_neighbors", "line_extensions", "parity"]
    if include_ship_alive:
        channels.append(ship_alive_length_channel)
        names.append("ship_alive_lengths")
    return ObservationEncoder(tuple(channels), tuple(names))


def default_placement_encoder() -> PlacementEncoder:
    channels: list[PlacementChannelBuilder] = [
        placement_occupied_channel,
        placement_available_channel,
        placement_next_ship_length_channel,
        placement_fraction_done_channel,
    ]
    names = ["occupied", "available", "next_ship_length", "fraction_done"]
    return PlacementEncoder(tuple(channels), tuple(names))


def misses_channel(observation: ObservationSnapshot, rules: Rules) -> np.ndarray:
    del rules
    return observation.misses


def hits_channel(observation: ObservationSnapshot, rules: Rules) -> np.ndarray:
    del rules
    return observation.hits


def sunk_channel(observation: ObservationSnapshot, rules: Rules) -> np.ndarray:
    del rules
    return observation.sunk


def available_channel(observation: ObservationSnapshot, rules: Rules) -> np.ndarray:
    del rules
    return observation.available_shots()


def hit_neighbors_channel(observation: ObservationSnapshot, rules: Rules) -> np.ndarray:
    channel = np.zeros((rules.rows, rules.cols), dtype=float)
    for coord in hit_neighbors(observation):
        channel[coord] = 1.0
    return channel


def line_extensions_channel(observation: ObservationSnapshot, rules: Rules) -> np.ndarray:
    channel = np.zeros((rules.rows, rules.cols), dtype=float)
    for coord in line_extensions(observation):
        channel[coord] = 1.0
    return channel


def parity_channel(observation: ObservationSnapshot, rules: Rules) -> np.ndarray:
    smallest_alive = min((rules.ship_length(slot) for slot, alive in enumerate(observation.ships_alive) if alive), default=2)
    return np.fromfunction(lambda row, col: ((row + col) % max(2, smallest_alive) == 0), (rules.rows, rules.cols))


def ship_alive_length_channel(observation: ObservationSnapshot, rules: Rules) -> np.ndarray:
    total = sum(rules.fleet)
    remaining = sum(rules.ship_length(slot) for slot, alive in enumerate(observation.ships_alive) if alive)
    value = remaining / total if total else 0.0
    return np.full((rules.rows, rules.cols), value, dtype=float)


def ship_slot_alive_channel(slot: int) -> ChannelBuilder:
    """Return one constant board plane for whether a specific ship is unsunk."""

    def channel(observation: ObservationSnapshot, rules: Rules) -> np.ndarray:
        del rules
        value = float(bool(observation.ships_alive[slot]))
        return np.full(observation.misses.shape, value, dtype=float)

    return channel


def with_ship_slot_alive_channels(encoder: ObservationEncoder, rules: Rules) -> ObservationEncoder:
    channels = list(encoder.channels)
    names = list(encoder.names)
    for slot in rules.slots:
        channels.append(ship_slot_alive_channel(slot))
        names.append(f"ship_{slot}_alive")
    return ObservationEncoder(tuple(channels), tuple(names))


def placement_occupied_channel(observation: PlacementObservation, rules: Rules) -> np.ndarray:
    del rules
    return observation.occupied


def placement_available_channel(observation: PlacementObservation, rules: Rules) -> np.ndarray:
    del rules
    return observation.available_cells()


def placement_next_ship_length_channel(observation: PlacementObservation, rules: Rules) -> np.ndarray:
    length = rules.ship_length(observation.next_slot) if observation.next_slot is not None else 0
    value = length / max(rules.fleet) if rules.fleet else 0.0
    return np.full((rules.rows, rules.cols), value, dtype=float)


def placement_fraction_done_channel(observation: PlacementObservation, rules: Rules) -> np.ndarray:
    value = float(np.sum(observation.placed_slots)) / len(rules.fleet) if rules.fleet else 0.0
    return np.full((rules.rows, rules.cols), value, dtype=float)


def placement_slot_placed_channel(slot: int) -> PlacementChannelBuilder:
    """Return one constant board plane for whether a ship slot has been placed."""

    def channel(observation: PlacementObservation, rules: Rules) -> np.ndarray:
        del rules
        value = float(bool(observation.placed_slots[slot]))
        return np.full(observation.occupied.shape, value, dtype=float)

    return channel


def with_ship_slot_placed_channels(encoder: PlacementEncoder, rules: Rules) -> PlacementEncoder:
    channels = list(encoder.channels)
    names = list(encoder.names)
    for slot in rules.slots:
        channels.append(placement_slot_placed_channel(slot))
        names.append(f"ship_{slot}_placed")
    return PlacementEncoder(tuple(channels), tuple(names))


def available_mask(observation: ObservationSnapshot) -> np.ndarray:
    return observation.available_shots().astype(bool)


def action_to_coord(action: int, rules: Rules) -> Coord:
    row, col = divmod(int(action), rules.cols)
    return (row, col)


def coord_to_action(coord: Coord, rules: Rules) -> int:
    row, col = coord
    return int(row * rules.cols + col)


def placement_action_options(rules: Rules, slot: int) -> list[ShipPlacement]:
    """Return the fixed action list for placing one ship slot on an empty board."""

    return legal_ship_placements(rules, slot)


def legal_placement_action_mask(rules: Rules, observation: PlacementObservation, slot: int) -> np.ndarray:
    occupied = {
        (row, col)
        for row in range(rules.rows)
        for col in range(rules.cols)
        if observation.occupied[row, col]
    }
    legal = set(legal_ship_placements(rules, slot, occupied))
    return np.array([option in legal for option in placement_action_options(rules, slot)], dtype=bool)


def placement_action_to_placement(action: int, rules: Rules, slot: int) -> ShipPlacement:
    options = placement_action_options(rules, slot)
    return options[int(action)]


def placement_to_action(placement: ShipPlacement, rules: Rules) -> int:
    options = placement_action_options(rules, placement.slot)
    return options.index(placement)


def sample_action(probabilities: np.ndarray, rng: random.Random) -> int:
    """Sample a flat action index from a probability vector."""
    probabilities = np.asarray(probabilities)
    threshold = rng.random()
    running = 0.0
    for index, probability in enumerate(probabilities):
        running += float(probability)
        if running >= threshold:
            return index
    nonzero = np.nonzero(probabilities > 0)[0]
    if len(nonzero) == 0:
        raise RuntimeError("cannot sample from an empty distribution")
    return int(nonzero[-1])


def greedy_action(scores: np.ndarray, mask: np.ndarray) -> int:
    """Return the highest-scoring flat action among legal cells."""
    if not np.any(mask):
        raise RuntimeError("no legal actions available")
    masked = np.where(mask, scores, -np.inf)
    return int(np.argmax(masked))


@dataclass(frozen=True, slots=True)
class RewardScheme:
    miss: float = -1.0
    hit: float = 1.0
    sunk: float = 1.0
    win: float = 0.0


class RewardFunction(Protocol):
    def __call__(self, result: PublicShotResult, won: bool) -> float:
        ...


def outcome_reward(result: PublicShotResult, won: bool, scheme: RewardScheme = RewardScheme()) -> float:
    if result.outcome is Outcome.MISS:
        reward = scheme.miss
    elif result.outcome is Outcome.HIT:
        reward = scheme.hit
    elif result.outcome is Outcome.SUNK:
        reward = scheme.sunk
    else:
        reward = 0.0
    if won:
        reward += scheme.win
    return reward


def to_torch_observation(channels: np.ndarray):
    try:
        import torch
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional rl extra.
        raise RuntimeError("Torch tensors require PyTorch. Install the optional RL dependencies with: pip install -e .[rl]") from exc
    return torch.tensor(channels, dtype=torch.float32).unsqueeze(0)


def to_torch_mask(mask: np.ndarray):
    try:
        import torch
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional rl extra.
        raise RuntimeError("Torch tensors require PyTorch. Install the optional RL dependencies with: pip install -e .[rl]") from exc
    return torch.tensor(mask, dtype=torch.bool)

from __future__ import annotations

import numpy as np

from core.models import Coord
from core.rules import Rules
from sdk.observation import ObservationSnapshot
from sdk.targeting import unresolved_hits


def shot_count(observation: ObservationSnapshot) -> int:
    return int(np.count_nonzero(~observation.available_shots()))


def remaining_ship_lengths(rules: Rules, observation: ObservationSnapshot) -> list[int]:
    return [rules.ship_length(slot) for slot, alive in enumerate(observation.ships_alive) if alive]


def known_cells(observation: ObservationSnapshot) -> set[Coord]:
    return {tuple(map(int, coord)) for coord in np.argwhere(~observation.available_shots())}


def unknown_cells(observation: ObservationSnapshot) -> set[Coord]:
    return {tuple(map(int, coord)) for coord in np.argwhere(observation.available_shots())}


def has_unresolved_hits(observation: ObservationSnapshot) -> bool:
    return bool(unresolved_hits(observation))

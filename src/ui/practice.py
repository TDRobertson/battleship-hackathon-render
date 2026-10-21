from __future__ import annotations

import random
from dataclasses import dataclass, field

from core.models import Coord, Outcome, PublicShotResult, SunkShip
from core.rules import Rules
from sdk.observation import ObservationState
from sdk.placement import fleet_cells, random_legal_fleet


@dataclass(slots=True)
class PracticeTarget:
    """Random fleet and hit bookkeeping for solo target practice."""

    fleet_cells: dict[int, tuple[Coord, ...]]
    hits_by_slot: dict[int, set[Coord]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for slot in self.fleet_cells:
            self.hits_by_slot.setdefault(slot, set())

    @property
    def all_sunk(self) -> bool:
        return all(set(cells) == self.hits_by_slot[slot] for slot, cells in self.fleet_cells.items())


def new_practice_target(rules: Rules, rng: random.Random) -> PracticeTarget:
    return PracticeTarget(fleet_cells(rules, random_legal_fleet(rules, rng)))


def practice_fire(target: PracticeTarget, observation: ObservationState, coord: Coord) -> PublicShotResult:
    """Apply one human shot to a practice target and return the public result."""

    if not observation.snapshot().available_shots()[coord]:
        raise ValueError("shot has already been taken")
    for slot, cells in target.fleet_cells.items():
        if coord not in cells:
            continue
        target.hits_by_slot[slot].add(coord)
        if target.hits_by_slot[slot] == set(cells):
            result = PublicShotResult(coord, Outcome.SUNK, SunkShip(slot, cells))
        else:
            result = PublicShotResult(coord, Outcome.HIT)
        observation.apply_result(result)
        return result

    result = PublicShotResult(coord, Outcome.MISS)
    observation.apply_result(result)
    return result

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence

from core.models import Coord, ShipPlacement
from core.rules import Orientation, Rules


PlacementSpec = tuple[int, int, int, Orientation]


def placement(slot: int, row: int, col: int, orientation: Orientation) -> ShipPlacement:
    return ShipPlacement(slot, row, col, orientation)


def ship_cells(rules: Rules, placement: ShipPlacement) -> tuple[Coord, ...]:
    length = rules.ship_length(placement.slot)
    cells = []
    for i in range(length):
        row = placement.row + (i if placement.orientation == "vertical" else 0)
        col = placement.col + (i if placement.orientation == "horizontal" else 0)
        if row < 0 or col < 0 or row >= rules.rows or col >= rules.cols:
            raise ValueError("ship is out of bounds")
        cells.append((row, col))
    return tuple(cells)


def legal_ship_placements(rules: Rules, slot: int, occupied: set[Coord] | None = None) -> list[ShipPlacement]:
    occupied = occupied or set()
    placements = []
    for row in range(rules.rows):
        for col in range(rules.cols):
            for orientation in ("horizontal", "vertical"):
                placement = ShipPlacement(slot, row, col, orientation)
                try:
                    cells = set(ship_cells(rules, placement))
                except ValueError:
                    continue
                if occupied.isdisjoint(cells):
                    placements.append(placement)
    return placements


def random_legal_fleet(rules: Rules, rng: random.Random) -> list[ShipPlacement]:
    slots = sorted(rules.slots, key=rules.ship_length, reverse=True)
    placements: list[ShipPlacement] = []
    if not _place_remaining(rules, slots, rng, placements, set()):
        raise RuntimeError("could not place fleet")
    return placements


def fleet_from_specs(rules: Rules, specs: Iterable[PlacementSpec]) -> list[ShipPlacement]:
    del rules
    return [placement(slot, row, col, orientation) for slot, row, col, orientation in specs]


def fleet_cells(rules: Rules, placements: Sequence[ShipPlacement]) -> dict[int, tuple[Coord, ...]]:
    return {placement.slot: ship_cells(rules, placement) for placement in placements}


def randomize_fleet_order(placements: Sequence[ShipPlacement], rng: random.Random) -> list[ShipPlacement]:
    shuffled = list(placements)
    rng.shuffle(shuffled)
    return shuffled


def mirror_fleet_horizontal(rules: Rules, placements: Sequence[ShipPlacement]) -> list[ShipPlacement]:
    return [
        ShipPlacement(p.slot, p.row, rules.cols - p.col - (rules.ship_length(p.slot) if p.orientation == "horizontal" else 1), p.orientation)
        for p in placements
    ]


def mirror_fleet_vertical(rules: Rules, placements: Sequence[ShipPlacement]) -> list[ShipPlacement]:
    return [
        ShipPlacement(p.slot, rules.rows - p.row - (rules.ship_length(p.slot) if p.orientation == "vertical" else 1), p.col, p.orientation)
        for p in placements
    ]


def rotate_fleet_180(rules: Rules, placements: Sequence[ShipPlacement]) -> list[ShipPlacement]:
    return mirror_fleet_vertical(rules, mirror_fleet_horizontal(rules, placements))


def _place_remaining(
    rules: Rules,
    slots: list[int],
    rng: random.Random,
    placements: list[ShipPlacement],
    occupied: set[Coord],
) -> bool:
    if not slots:
        return True

    slot = slots[0]
    candidates = legal_ship_placements(rules, slot, occupied)
    rng.shuffle(candidates)
    for placement in candidates:
        cells = set(ship_cells(rules, placement))
        placements.append(placement)
        occupied.update(cells)
        if _place_remaining(rules, slots[1:], rng, placements, occupied):
            return True
        placements.pop()
        occupied.difference_update(cells)
    return False

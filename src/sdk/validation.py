from __future__ import annotations

from core.models import Coord, ShipPlacement
from core.rules import Rules
from sdk.observation import ObservationSnapshot
from sdk.placement import ship_cells


def fleet_errors(rules: Rules, placements: list[ShipPlacement]) -> list[str]:
    """Return human-readable legality errors for a proposed fleet."""
    errors: list[str] = []
    slots = [placement.slot for placement in placements]
    required = set(rules.slots)
    if set(slots) != required or len(slots) != len(required):
        errors.append("fleet must contain every ship slot exactly once")

    occupied: dict[Coord, int] = {}
    for placement in placements:
        if placement.orientation not in ("horizontal", "vertical"):
            errors.append(f"slot {placement.slot}: orientation must be horizontal or vertical")
            continue
        try:
            cells = ship_cells(rules, placement)
        except ValueError as exc:
            errors.append(f"slot {placement.slot}: {exc}")
            continue
        for cell in cells:
            if cell in occupied:
                errors.append(f"slot {placement.slot}: overlaps slot {occupied[cell]} at {cell}")
            else:
                occupied[cell] = placement.slot
    return errors


def shot_errors(rules: Rules, observation: ObservationSnapshot, shot: Coord) -> list[str]:
    """Return human-readable legality errors for a proposed shot."""
    row, col = shot
    if not isinstance(row, int) or not isinstance(col, int):
        return ["shot coordinates must be integers"]
    if row < 0 or col < 0 or row >= rules.rows or col >= rules.cols:
        return ["shot is out of bounds"]
    if not bool(observation.available_shots()[row, col]):
        return ["shot has already been taken"]
    return []


def is_legal_fleet(rules: Rules, placements: list[ShipPlacement]) -> bool:
    return not fleet_errors(rules, placements)


def is_legal_shot(rules: Rules, observation: ObservationSnapshot, shot: Coord) -> bool:
    return not shot_errors(rules, observation, shot)

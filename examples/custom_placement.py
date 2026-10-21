from __future__ import annotations

import random

from core.models import ShipPlacement
from core.rules import Rules
from sdk.placement import fleet_from_specs, mirror_fleet_horizontal, random_legal_fleet, rotate_fleet_180
from sdk.validation import fleet_errors


def placement_portfolio(rules: Rules) -> list[list[ShipPlacement]]:
    """Return a few legal layouts your bot can choose from."""

    base = fleet_from_specs(
        rules,
        [
            (0, 0, 0, "horizontal"),
            (1, 2, 2, "vertical"),
            (2, 5, 0, "horizontal"),
            (3, 7, 4, "vertical"),
            (4, 9, 7, "horizontal"),
        ],
    )
    return [
        base,
        mirror_fleet_horizontal(rules, base),
        rotate_fleet_180(rules, base),
    ]


def choose_placement(rules: Rules, rng: random.Random) -> list[ShipPlacement]:
    legal_layouts = [fleet for fleet in placement_portfolio(rules) if not fleet_errors(rules, fleet)]
    if not legal_layouts:
        return random_legal_fleet(rules, rng)
    return rng.choice(legal_layouts)

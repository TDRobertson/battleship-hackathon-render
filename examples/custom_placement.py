"""Example: choose from a small portfolio of hand-written fleet layouts.

Battleship bots do not have to place ships randomly. A common first upgrade is
to maintain a few known-good layouts and randomly choose among them. This keeps
your fleet legal while avoiding the easiest-to-exploit habit: using one fixed
layout every game.

The official fleet slots have lengths `[5, 4, 3, 3, 2]`, so slot 0 is the
length-5 ship, slot 1 is length 4, slots 2 and 3 are length 3, and slot 4 is
length 2.
"""

from __future__ import annotations

import random

from core.models import ShipPlacement
from core.rules import Rules
from sdk.placement import (
    fleet_from_specs,
    mirror_fleet_horizontal,
    random_legal_fleet,
    rotate_fleet_180,
)
from sdk.validation import fleet_errors


def placement_portfolio(rules: Rules) -> list[list[ShipPlacement]]:
    """Return a few layouts your bot can choose from.

    Each tuple passed to `fleet_from_specs` is shaped:

        (slot, starting_row, starting_col, orientation)

    The transforms produce related layouts without writing every coordinate by
    hand. This is useful when you want variety while preserving the general
    structure of a placement idea.
    """

    base = fleet_from_specs(
        rules,
        [
            # Slot 0: length 5, across the top edge.
            (0, 0, 0, "horizontal"),
            # Slot 1: length 4, vertical in the upper-middle board.
            (1, 2, 2, "vertical"),
            # Slot 2: length 3, horizontal on the left side.
            (2, 5, 0, "horizontal"),
            # Slot 3: length 3, vertical on the right-middle board.
            (3, 7, 4, "vertical"),
            # Slot 4: length 2, horizontal near the bottom edge.
            (4, 9, 7, "horizontal"),
        ],
    )
    return [
        base,
        # Mirror across the horizontal axis: top rows become bottom rows.
        mirror_fleet_horizontal(rules, base),
        # Rotate 180 degrees: a quick way to create a distant variant.
        rotate_fleet_180(rules, base),
    ]


def choose_placement(rules: Rules, rng: random.Random) -> list[ShipPlacement]:
    """Choose one legal layout from the portfolio.

    Validation makes this snippet safer to edit. If you change the hand-written
    coordinates and accidentally create an illegal fleet, the bot falls back to
    a random legal placement instead of forfeiting immediately.
    """

    legal_layouts = [
        fleet
        for fleet in placement_portfolio(rules)
        if not fleet_errors(rules, fleet)
    ]
    if not legal_layouts:
        return random_legal_fleet(rules, rng)
    return rng.choice(legal_layouts)

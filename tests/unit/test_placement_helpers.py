import random

import pytest

pytest.importorskip("hypothesis")

from hypothesis import given
from hypothesis import strategies as st

from core.models import ShipPlacement
from core.rules import Rules, official_rules
from sdk.placement import (
    legal_ship_placements,
    mirror_fleet_horizontal,
    mirror_fleet_vertical,
    random_legal_fleet,
    randomize_fleet_order,
    rotate_fleet_180,
    ship_cells,
)
from sdk.validation import fleet_errors


@given(
    rows=st.integers(1, 12),
    cols=st.integers(1, 12),
    length=st.integers(1, 6),
    orientation=st.sampled_from(["horizontal", "vertical"]),
)
def test_ship_cells_contract_for_in_bounds_placements(rows, cols, length, orientation):
    rules = Rules(rows=rows, cols=cols, fleet=(length,))
    max_row = rows - length if orientation == "vertical" else rows - 1
    max_col = cols - length if orientation == "horizontal" else cols - 1
    if max_row < 0 or max_col < 0:
        return
    placement = ShipPlacement(0, max_row, max_col, orientation)

    cells = ship_cells(rules, placement)

    assert len(cells) == length
    assert all(0 <= row < rows and 0 <= col < cols for row, col in cells)
    if orientation == "horizontal":
        assert {row for row, _ in cells} == {max_row}
        assert [col for _, col in cells] == list(range(max_col, max_col + length))
    else:
        assert {col for _, col in cells} == {max_col}
        assert [row for row, _ in cells] == list(range(max_row, max_row + length))


def test_ship_cells_rejects_out_of_bounds_placement():
    rules = Rules(rows=3, cols=3, fleet=(4,))

    with pytest.raises(ValueError):
        ship_cells(rules, ShipPlacement(0, 0, 0, "horizontal"))


@given(rows=st.integers(2, 8), cols=st.integers(2, 8), length=st.integers(1, 4))
def test_legal_ship_placements_contract(rows, cols, length):
    rules = Rules(rows=rows, cols=cols, fleet=(length,))
    occupied = {(0, 0)}

    placements = legal_ship_placements(rules, 0, occupied)

    assert all(placement.slot == 0 for placement in placements)
    for placement in placements:
        cells = set(ship_cells(rules, placement))
        assert occupied.isdisjoint(cells)
        assert all(0 <= row < rows and 0 <= col < cols for row, col in cells)


def test_random_legal_fleet_contract_and_reproducibility():
    rules = official_rules()
    fleet = random_legal_fleet(rules, random.Random(99))
    repeat = random_legal_fleet(rules, random.Random(99))

    assert fleet == repeat
    assert not fleet_errors(rules, fleet)


def test_randomize_fleet_order_preserves_members_and_uses_rng():
    fleet = [
        ShipPlacement(0, 0, 0, "horizontal"),
        ShipPlacement(1, 1, 0, "horizontal"),
        ShipPlacement(2, 2, 0, "horizontal"),
    ]

    shuffled = randomize_fleet_order(fleet, random.Random(1))

    assert sorted(shuffled, key=lambda p: p.slot) == fleet
    assert fleet == [
        ShipPlacement(0, 0, 0, "horizontal"),
        ShipPlacement(1, 1, 0, "horizontal"),
        ShipPlacement(2, 2, 0, "horizontal"),
    ]


def test_fleet_transforms_preserve_legal_fleets():
    rules = official_rules()
    fleet = random_legal_fleet(rules, random.Random(12))

    assert not fleet_errors(rules, mirror_fleet_horizontal(rules, fleet))
    assert not fleet_errors(rules, mirror_fleet_vertical(rules, fleet))
    assert rotate_fleet_180(rules, fleet) == mirror_fleet_vertical(rules, mirror_fleet_horizontal(rules, fleet))
    assert not fleet_errors(rules, rotate_fleet_180(rules, fleet))

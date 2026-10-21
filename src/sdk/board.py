from __future__ import annotations

from core.models import Coord
from core.rules import Rules


def in_bounds(rules: Rules, coord: Coord) -> bool:
    row, col = coord
    return 0 <= row < rules.rows and 0 <= col < rules.cols


def all_cells(rules: Rules) -> list[Coord]:
    return [(row, col) for row in range(rules.rows) for col in range(rules.cols)]


def neighbors(rules: Rules, coord: Coord, diagonals: bool = False) -> list[Coord]:
    row, col = coord
    offsets = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    if diagonals:
        offsets.extend([(-1, -1), (-1, 1), (1, -1), (1, 1)])
    return [(row + dr, col + dc) for dr, dc in offsets if in_bounds(rules, (row + dr, col + dc))]


def manhattan(a: Coord, b: Coord) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def center_distance(rules: Rules, coord: Coord) -> float:
    center_row = (rules.rows - 1) / 2
    center_col = (rules.cols - 1) / 2
    return abs(coord[0] - center_row) + abs(coord[1] - center_col)


def diagonal_band_cells(rules: Rules, spacing: int = 2, offset: int = 0) -> list[Coord]:
    """Return diagonal bands selected by `(row + col + offset) % spacing == 0`."""
    if spacing <= 0:
        raise ValueError("spacing must be positive")
    return [coord for coord in all_cells(rules) if (coord[0] + coord[1] + offset) % spacing == 0]


def checkerboard_cells(rules: Rules, offset: int = 0) -> list[Coord]:
    return diagonal_band_cells(rules, spacing=2, offset=offset)


def edge_cells(rules: Rules) -> list[Coord]:
    return [
        coord
        for coord in all_cells(rules)
        if coord[0] in (0, rules.rows - 1) or coord[1] in (0, rules.cols - 1)
    ]

import pytest

pytest.importorskip("hypothesis")

from hypothesis import given
from hypothesis import strategies as st

from core.rules import Rules
from sdk.board import all_cells, checkerboard_cells, diagonal_band_cells, in_bounds, neighbors


@given(rows=st.integers(1, 12), cols=st.integers(1, 12))
def test_all_cells_contract(rows, cols):
    rules = Rules(rows=rows, cols=cols)
    cells = all_cells(rules)

    assert len(cells) == rows * cols
    assert len(set(cells)) == len(cells)
    assert all(in_bounds(rules, coord) for coord in cells)


@given(rows=st.integers(1, 12), cols=st.integers(1, 12), row=st.integers(-3, 15), col=st.integers(-3, 15))
def test_in_bounds_contract(rows, cols, row, col):
    rules = Rules(rows=rows, cols=cols)

    assert in_bounds(rules, (row, col)) is (0 <= row < rows and 0 <= col < cols)


@given(rows=st.integers(1, 12), cols=st.integers(1, 12), diagonals=st.booleans())
def test_neighbors_contract(rows, cols, diagonals):
    rules = Rules(rows=rows, cols=cols)
    coord = (rows // 2, cols // 2)

    result = neighbors(rules, coord, diagonals)

    assert len(result) == len(set(result))
    assert coord not in result
    assert all(in_bounds(rules, neighbor) for neighbor in result)
    if diagonals:
        assert all(abs(coord[0] - r) <= 1 and abs(coord[1] - c) <= 1 for r, c in result)
    else:
        assert all(abs(coord[0] - r) + abs(coord[1] - c) == 1 for r, c in result)


@given(
    rows=st.integers(1, 12),
    cols=st.integers(1, 12),
    spacing=st.integers(1, 8),
    offset=st.integers(-20, 20),
)
def test_diagonal_band_cells_contract(rows, cols, spacing, offset):
    rules = Rules(rows=rows, cols=cols)
    expected = [
        (row, col)
        for row in range(rows)
        for col in range(cols)
        if (row + col + offset) % spacing == 0
    ]

    assert diagonal_band_cells(rules, spacing, offset) == expected


@given(rows=st.integers(1, 12), cols=st.integers(1, 12), offset=st.integers(-20, 20))
def test_checkerboard_cells_contract(rows, cols, offset):
    rules = Rules(rows=rows, cols=cols)

    assert checkerboard_cells(rules, offset) == diagonal_band_cells(rules, 2, offset)

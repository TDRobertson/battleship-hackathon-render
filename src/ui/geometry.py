from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BoardGeometry:
    x: int
    y: int
    cell: int
    rows: int = 10
    cols: int = 10

    @property
    def size(self) -> int:
        return self.cell * self.rows

    def pixel_to_cell(self, pos: tuple[int, int]) -> tuple[int, int] | None:
        px, py = pos
        if px < self.x or py < self.y:
            return None
        col = (px - self.x) // self.cell
        row = (py - self.y) // self.cell
        if 0 <= row < self.rows and 0 <= col < self.cols:
            return int(row), int(col)
        return None

    def cell_rect(self, row: int, col: int) -> tuple[int, int, int, int]:
        return (self.x + col * self.cell, self.y + row * self.cell, self.cell, self.cell)

from __future__ import annotations

from dataclasses import dataclass, field

from core.engine import GameEngine
from core.models import Player, ShipPlacement
from sdk.observation import ObservationState, result_to_public
from core.rules import Rules, official_rules


@dataclass
class PlacementController:
    rules: Rules = field(default_factory=official_rules)
    selected_slot: int = 0
    orientation: str = "horizontal"
    placements: list[ShipPlacement] = field(default_factory=list)

    def remaining_slots(self) -> list[int]:
        used = {p.slot for p in self.placements}
        return [slot for slot in self.rules.slots if slot not in used]

    def select_next(self) -> None:
        remaining = self.remaining_slots()
        self.selected_slot = remaining[0] if remaining else self.selected_slot

    def rotate(self) -> None:
        self.orientation = "vertical" if self.orientation == "horizontal" else "horizontal"

    def preview(self, row: int, col: int) -> tuple[list[tuple[int, int]], bool]:
        if self.complete():
            return [], False
        placement = ShipPlacement(self.selected_slot, row, col, self.orientation)  # type: ignore[arg-type]
        try:
            cells = self.cells_for(placement)
            occupied = {cell for p in self.placements for cell in self.cells_for(p)}
            return list(cells), occupied.isdisjoint(cells)
        except Exception:
            return [], False

    def place(self, row: int, col: int) -> bool:
        if self.complete():
            return False
        cells, ok = self.preview(row, col)
        if not ok:
            return False
        self.placements.append(ShipPlacement(self.selected_slot, row, col, self.orientation))  # type: ignore[arg-type]
        self.select_next()
        return True

    def undo(self) -> None:
        if self.placements:
            removed = self.placements.pop()
            self.selected_slot = removed.slot

    def reset(self) -> None:
        self.placements.clear()
        self.selected_slot = 0
        self.orientation = "horizontal"

    def complete(self) -> bool:
        return {p.slot for p in self.placements} == set(self.rules.slots)

    def cells_for(self, placement: ShipPlacement) -> tuple[tuple[int, int], ...]:
        length = self.rules.ship_length(placement.slot)
        cells = []
        for i in range(length):
            row = placement.row + (i if placement.orientation == "vertical" else 0)
            col = placement.col + (i if placement.orientation == "horizontal" else 0)
            if row < 0 or col < 0 or row >= self.rules.rows or col >= self.rules.cols:
                raise ValueError("out of bounds")
            cells.append((row, col))
        return tuple(cells)


@dataclass
class BattleController:
    engine: GameEngine
    human_obs: ObservationState
    pending_shot: bool = False

    def can_fire(self, row: int, col: int) -> bool:
        if self.pending_shot or self.engine.active_player is not Player.A:
            return False
        return bool(self.human_obs.snapshot().available_shots()[row, col])

    def human_fire(self, row: int, col: int):
        if not self.can_fire(row, col):
            return None
        self.pending_shot = True
        try:
            result = self.engine.fire(Player.A, row, col)
            self.human_obs.apply_result(result_to_public(result))
            return result
        finally:
            self.pending_shot = False

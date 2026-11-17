from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Orientation = Literal["horizontal", "vertical"]


@dataclass(frozen=True, slots=True)
class Rules:
    rows: int = 10
    cols: int = 10
    fleet: tuple[int, ...] = (5, 4, 3, 3, 2)
    thinking_seconds: float = 0.5
    protocol_version: int = 1
    placement_seconds: float = 5.0

    def ship_length(self, slot: int) -> int:
        if slot < 0 or slot >= len(self.fleet):
            raise ValueError(f"unknown ship slot {slot}")
        return self.fleet[slot]

    @property
    def slots(self) -> range:
        return range(len(self.fleet))


def official_rules() -> Rules:
    return Rules()

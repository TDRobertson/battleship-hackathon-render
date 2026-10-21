from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.rules import Orientation

Coord = tuple[int, int]


class Player(str, Enum):
    A = "A"
    B = "B"

    @property
    def opponent(self) -> "Player":
        return Player.B if self is Player.A else Player.A


class Phase(str, Enum):
    PLACEMENT = "placement"
    BATTLE = "battle"
    GAME_OVER = "game_over"


class Outcome(str, Enum):
    MISS = "miss"
    HIT = "hit"
    SUNK = "sunk"


@dataclass(frozen=True, slots=True)
class ShipPlacement:
    slot: int
    row: int
    col: int
    orientation: Orientation


@dataclass(frozen=True, slots=True)
class SunkShip:
    slot: int
    cells: tuple[Coord, ...]


@dataclass(frozen=True, slots=True)
class ShotResult:
    player: Player
    shot: Coord
    outcome: Outcome
    sunk_ship: SunkShip | None = None


@dataclass(frozen=True, slots=True)
class PublicShotResult:
    shot: Coord
    outcome: Outcome
    sunk_ship: SunkShip | None = None


@dataclass(frozen=True, slots=True)
class Termination:
    winner: Player
    reason: str

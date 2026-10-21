from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from core.models import Player


Monotonic = Callable[[], float]


@dataclass
class MatchClocks:
    initial: float = 120.0
    monotonic: Monotonic = time.monotonic

    def __post_init__(self) -> None:
        self.remaining = {Player.A: float(self.initial), Player.B: float(self.initial)}
        self._charging: Player | None = None
        self._started_at: float | None = None

    def start(self, player: Player) -> float:
        if self._charging is not None:
            raise RuntimeError("clock already charging")
        self._charging = player
        self._started_at = self.monotonic()
        return self.deadline(player)

    def stop(self, player: Player) -> float:
        if self._charging is not player or self._started_at is None:
            raise RuntimeError("clock is not charging for player")
        now = self.monotonic()
        elapsed = now - self._started_at
        self._charging = None
        self._started_at = None
        self.remaining[player] -= elapsed
        return self.remaining[player]

    def deadline(self, player: Player) -> float:
        if self._charging is player and self._started_at is not None:
            return self._started_at + self.remaining[player]
        return self.monotonic() + self.remaining[player]

    def is_timed_out(self, player: Player) -> bool:
        if self._charging is player and self._started_at is not None:
            return self.monotonic() >= self._started_at + self.remaining[player]
        return self.remaining[player] <= 0


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Callable

from core.models import Player


Monotonic = Callable[[], float]
ACTION_TIMEOUT_SECONDS = 0.5
PLACEMENT_TIMEOUT_SECONDS = 5.0
MINIMUM_MOVE_SECONDS = 0.5


def wait_for_minimum_move(started_at: float, minimum: float = MINIMUM_MOVE_SECONDS,
                          monotonic: Monotonic = time.monotonic,
                          sleep: Callable[[float], None] = time.sleep) -> None:
    remaining = minimum - (monotonic() - started_at)
    if remaining > 0:
        sleep(remaining)


class ActionTimeout(TimeoutError):
    """An agent did not complete an action before its deadline."""


def call_with_timeout(action: Callable[[], object], timeout: float = ACTION_TIMEOUT_SECONDS) -> object:
    """Return an in-process bot action, or stop waiting when its deadline expires."""
    finished = threading.Event()
    outcome: list[tuple[bool, object, float]] = []
    started = time.monotonic()

    def invoke() -> None:
        try:
            outcome.append((True, action(), time.monotonic()))
        except BaseException as exc:
            outcome.append((False, exc, time.monotonic()))
        finally:
            finished.set()

    threading.Thread(target=invoke, daemon=True).start()
    if not finished.wait(timeout) or outcome[0][2] - started > timeout:
        raise ActionTimeout(f"bot exceeded the {timeout:g}s action limit")
    succeeded, result, _ = outcome[0]
    if not succeeded:
        if isinstance(result, Exception):
            raise result
        raise RuntimeError(f"bot terminated its action: {result}")
    return result


@dataclass
class MoveTiming:
    count: int = 0
    total: float = 0.0
    maximum: float = 0.0

    def record(self, elapsed: float) -> None:
        self.count += 1
        self.total += elapsed
        self.maximum = max(self.maximum, elapsed)

    def add(self, other: MoveTiming) -> None:
        self.count += other.count
        self.total += other.total
        self.maximum = max(self.maximum, other.maximum)


@dataclass
class MatchClocks:
    """Legacy clock utility retained for callers; matches use per-action limits."""

    initial: float = 60.0
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

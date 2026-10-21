from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from core.models import Outcome, PublicShotResult
from core.rules import Rules, official_rules


class VersionGap(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ObservationSnapshot:
    misses: np.ndarray
    hits: np.ndarray
    sunk: np.ndarray
    ships_alive: np.ndarray
    version: int = 0

    def available_shots(self) -> np.ndarray:
        return (self.misses | self.hits | self.sunk) == 0

    def board_channels(self) -> np.ndarray:
        return np.stack([self.misses, self.hits, self.sunk]).astype(np.uint8, copy=True)

    def fleet_flags(self) -> np.ndarray:
        return self.ships_alive.astype(np.uint8, copy=True)


class ObservationState:
    def __init__(self, rules: Rules | None = None) -> None:
        self.rules = rules or official_rules()
        shape = (self.rules.rows, self.rules.cols)
        self.misses = np.zeros(shape, dtype=np.uint8)
        self.hits = np.zeros(shape, dtype=np.uint8)
        self.sunk = np.zeros(shape, dtype=np.uint8)
        self.ships_alive = np.ones((len(self.rules.fleet),), dtype=np.uint8)
        self.version = 0

    def snapshot(self) -> ObservationSnapshot:
        return ObservationSnapshot(
            self.misses.copy(),
            self.hits.copy(),
            self.sunk.copy(),
            self.ships_alive.copy(),
            self.version,
        )

    def apply_result(self, result: PublicShotResult) -> ObservationSnapshot:
        row, col = result.shot
        self.version += 1
        if result.outcome is Outcome.MISS:
            self.misses[row, col] = 1
        elif result.outcome is Outcome.HIT:
            self.hits[row, col] = 1
        elif result.outcome is Outcome.SUNK:
            if result.sunk_ship is None:
                raise ValueError("sunk result requires sunk_ship")
            for r, c in result.sunk_ship.cells:
                self.hits[r, c] = 0
                self.sunk[r, c] = 1
            self.ships_alive[result.sunk_ship.slot] = 0
        self._assert_invariants()
        return self.snapshot()

    def apply_update(self, message: dict) -> ObservationSnapshot | None:
        incoming = int(message["observation_version"])
        if incoming == self.version:
            return None
        if incoming != self.version + 1:
            raise VersionGap(f"expected version {self.version + 1}, got {incoming}")
        from sdk.protocol import result_from_message

        result = result_from_message(message)
        return self.apply_result(result)

    def replace_from_snapshot(self, snapshot: ObservationSnapshot) -> None:
        if snapshot.version < self.version:
            return
        self.misses = snapshot.misses.astype(np.uint8, copy=True)
        self.hits = snapshot.hits.astype(np.uint8, copy=True)
        self.sunk = snapshot.sunk.astype(np.uint8, copy=True)
        self.ships_alive = snapshot.ships_alive.astype(np.uint8, copy=True)
        self.version = snapshot.version
        self._assert_invariants()

    def to_lists(self) -> dict:
        return {
            "misses": self.misses.tolist(),
            "hits": self.hits.tolist(),
            "sunk": self.sunk.tolist(),
            "ships_alive": self.ships_alive.tolist(),
            "version": self.version,
        }

    @classmethod
    def from_lists(cls, payload: dict, rules: Rules | None = None) -> "ObservationState":
        state = cls(rules)
        state.misses = np.array(payload["misses"], dtype=np.uint8)
        state.hits = np.array(payload["hits"], dtype=np.uint8)
        state.sunk = np.array(payload["sunk"], dtype=np.uint8)
        state.ships_alive = np.array(payload["ships_alive"], dtype=np.uint8)
        state.version = int(payload["version"])
        state._assert_invariants()
        return state

    def _assert_invariants(self) -> None:
        if not np.all(self.misses + self.hits + self.sunk <= 1):
            raise AssertionError("observation masks overlap")


def result_to_public(result) -> PublicShotResult:
    return PublicShotResult(result.shot, result.outcome, result.sunk_ship)

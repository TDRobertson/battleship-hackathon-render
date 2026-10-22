"""Example: a complete, importable bot with documented decisions.

Run it from the project root with:

    battleship simulate --bot-a examples.complete_bot:DocumentedExampleBot --bot-b hunt-target --games 20

This is still intentionally simple. It demonstrates the shape of an `Agent`
implementation and a few safe SDK helpers, not a tournament-winning strategy.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from agent import Agent
from core.models import Coord, ShipPlacement
from core.rules import Rules
from sdk.board import checkerboard_cells, center_distance
from sdk.observation import ObservationSnapshot
from sdk.placement import random_legal_fleet
from sdk.scoring import choose_best_score
from sdk.targeting import available_shots, hit_neighbors, line_extensions


@dataclass
class DocumentedExampleBot(Agent):
    """A small bot that combines target mode, checkerboard hunting, and scoring."""

    rng: random.Random
    rules: Rules | None = field(default=None, init=False)

    @classmethod
    def seeded(cls, seed: int | None = None) -> "DocumentedExampleBot":
        """Factory used by the runtime so simulations are reproducible."""

        return cls(random.Random(seed))

    def place_ships(self, rules: Rules, time_remaining: float) -> list[ShipPlacement]:
        """Place a legal random fleet.

        Placement is deliberately boring in this example so the shooting logic
        is easier to study. See `examples/custom_placement.py` for a portfolio
        approach.
        """

        del time_remaining
        self.rules = rules
        return random_legal_fleet(rules, self.rng)

    def choose_shot(self, observation: ObservationSnapshot, time_remaining: float) -> Coord:
        """Choose one legal target coordinate from the public observation."""

        del time_remaining
        rules = self.rules
        if rules is None:
            raise RuntimeError("place_ships must run before choose_shot")
        candidates = self._candidate_pool(rules, observation)
        scores = self._score_candidates(rules, candidates)
        return choose_best_score(scores, self.rng)

    def _candidate_pool(self, rules: Rules, observation: ObservationSnapshot) -> list[Coord]:
        """Choose the tactical mode before scoring.

        The bot first tries to finish known hits. If there are no unresolved
        hits, it hunts on a checkerboard. Checkerboard hunting is a classic
        Battleship idea because every ship has length at least 2, so a ship
        cannot hide entirely on the skipped parity forever.
        """

        target_mode = line_extensions(observation) or hit_neighbors(observation)
        if target_mode:
            return target_mode

        available = set(available_shots(observation))
        checkerboard = [coord for coord in checkerboard_cells(rules) if coord in available]
        return checkerboard or list(available)

    def _score_candidates(self, rules: Rules, candidates: list[Coord]) -> dict[Coord, float]:
        """Prefer central cells while hunting, but keep target-mode candidates valid."""

        return {coord: -center_distance(rules, coord) for coord in candidates}


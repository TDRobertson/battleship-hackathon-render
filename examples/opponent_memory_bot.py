"""Example: use persistent per-opponent memory without assuming keys exist.

Run several games so the memory has time to accumulate:

    battleship simulate --bot-a examples.opponent_memory_bot:MemoryExampleBot --bot-b hunt-target --games 20

Memory is stored by bot/opponent pair under `results/memory` by default. Delete
that directory or pass `--reset-memory` when you want a clean experiment.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from agent import Agent, MatchContext, MatchEnd
from core.models import Coord, PublicShotResult, ShipPlacement
from core.rules import Rules
from sdk.observation import ObservationSnapshot
from sdk.placement import fleet_from_specs, random_legal_fleet
from sdk.targeting import available_shots, choose_random, hit_neighbors, line_extensions
from sdk.validation import fleet_errors


@dataclass
class MemoryExampleBot(Agent):
    """A legal bot that records and reacts to simple opponent-shot stats."""

    rng: random.Random
    memory: dict = field(default_factory=dict)
    placement_mode: str = "default"

    @classmethod
    def seeded(cls, seed: int | None = None) -> "MemoryExampleBot":
        return cls(random.Random(seed))

    def start_match(self, context: MatchContext) -> None:
        """Read opponent memory before placement.

        The first match against an opponent starts with an empty dictionary, so
        every read uses `.get(...)` defaults. The runner later writes automatic
        stats under `memory["_stats"]`.
        """

        self.memory = context.memory
        stats = self.memory.get("_stats", {})
        games = int(stats.get("games", 0))
        center_rate = float(stats.get("opponent_center_rate", 0.0))

        # Wait for a few games before trusting the observed tendency. If this
        # opponent often shoots center cells, try an edge-heavy layout.
        self.placement_mode = "edge" if games >= 3 and center_rate > 0.20 else "default"

    def place_ships(self, rules: Rules, time_remaining: float) -> list[ShipPlacement]:
        del time_remaining
        layout = self._layout_for_mode(rules, self.placement_mode)
        if fleet_errors(rules, layout):
            layout = random_legal_fleet(rules, self.rng)
            self.placement_mode = "random-fallback"

        # The runner records per-layout games, wins, losses, and average
        # opponent shots when this key is present.
        self.memory["current_layout"] = self.placement_mode
        return layout

    def choose_shot(self, observation: ObservationSnapshot, time_remaining: float) -> Coord:
        del time_remaining
        candidates = line_extensions(observation) or hit_neighbors(observation) or available_shots(observation)
        return choose_random(candidates, self.rng)

    def observe_opponent_shot(self, result: PublicShotResult, time_remaining: float) -> None:
        """Store a tiny custom note in addition to the runner's automatic stats."""

        del time_remaining
        self.memory["last_opponent_shot_seen_by_bot"] = result.shot

    def end_match(self, result: MatchEnd) -> None:
        """Store a custom end-of-match flag.

        The runner saves memory after this hook returns.
        """

        self.memory["last_match_won"] = result.won

    def _layout_for_mode(self, rules: Rules, mode: str) -> list[ShipPlacement]:
        if mode == "edge":
            return fleet_from_specs(
                rules,
                [
                    (0, 0, 0, "horizontal"),
                    (1, 9, 0, "horizontal"),
                    (2, 2, 0, "vertical"),
                    (3, 0, 7, "vertical"),
                    (4, 8, 8, "horizontal"),
                ],
            )
        return random_legal_fleet(rules, self.rng)


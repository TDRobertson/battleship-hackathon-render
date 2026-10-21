from __future__ import annotations

import random
from dataclasses import dataclass

from agent import Agent
from core.models import Coord, ShipPlacement
from core.rules import Rules
from sdk.observation import ObservationSnapshot
from sdk.placement import random_legal_fleet
from sdk.targeting import available_shots, choose_random, hit_neighbors, line_extensions


@dataclass
class HuntTargetBot(Agent):
    rng: random.Random

    @classmethod
    def seeded(cls, seed: int | None = None) -> "HuntTargetBot":
        return cls(random.Random(seed))

    def place_ships(self, rules: Rules, time_remaining: float) -> list[ShipPlacement]:
        return random_legal_fleet(rules, self.rng)

    def choose_shot(self, observation: ObservationSnapshot, time_remaining: float) -> Coord:
        return choose_random(self._candidates(observation), self.rng)

    def _candidates(self, observation: ObservationSnapshot) -> list[Coord]:
        return line_extensions(observation) or hit_neighbors(observation) or available_shots(observation)

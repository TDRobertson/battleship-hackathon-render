from __future__ import annotations

import random
from dataclasses import dataclass

from agent import Agent
from core.models import Coord, ShipPlacement
from core.rules import Rules
from sdk.observation import ObservationSnapshot
from sdk.placement import random_legal_fleet
from sdk.targeting import available_shots, choose_random


@dataclass
class RandomStarterBot(Agent):
    """Smallest possible legal bot.

    Copy this when you want a blank slate and plan to invent most of the
    strategy yourself.
    """

    rng: random.Random

    @classmethod
    def seeded(cls, seed: int | None = None) -> "RandomStarterBot":
        return cls(random.Random(seed))

    def place_ships(self, rules: Rules, time_remaining: float) -> list[ShipPlacement]:
        return random_legal_fleet(rules, self.rng)

    def choose_shot(self, observation: ObservationSnapshot, time_remaining: float) -> Coord:
        return choose_random(available_shots(observation), self.rng)

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import Coord, ShipPlacement
from sdk.observation import ObservationSnapshot
from core.rules import Rules


class Agent(ABC):
    """Base class for all Battleship bots.

    Keep one agent instance alive for a full match if the bot needs internal
    state. Implementations must return only legal placements and shots; the
    engine remains authoritative and treats illegal actions as forfeits.
    """

    @abstractmethod
    def place_ships(self, rules: Rules, time_remaining: float) -> list[ShipPlacement]:
        """Return a complete legal fleet placement for the given rules."""
        raise NotImplementedError

    @abstractmethod
    def choose_shot(self, observation: ObservationSnapshot, time_remaining: float) -> Coord:
        """Return the next target coordinate using only the public observation."""
        raise NotImplementedError

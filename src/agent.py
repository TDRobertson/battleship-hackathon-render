from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.models import Coord, Player, PublicShotResult, ShipPlacement
from sdk.observation import ObservationSnapshot
from core.rules import Rules


@dataclass(slots=True)
class MatchContext:
    """Information and mutable memory available for one match."""

    match_id: str
    player: Player
    bot_name: str
    opponent_name: str
    memory: dict


@dataclass(frozen=True, slots=True)
class MatchEnd:
    """End-of-match summary passed to optional bot lifecycle hooks."""

    won: bool
    winner: Player
    reason: str
    turns: int


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

    def start_match(self, context: MatchContext) -> None:
        """Optional hook called before placement.

        Adaptive bots can read and write ``context.memory``. The runner loads it
        before the match and saves it after the match when persistent memory is
        enabled.
        """

    def observe_opponent_shot(self, result: PublicShotResult, time_remaining: float) -> None:
        """Optional hook called after the opponent fires at this bot's fleet."""

    def end_match(self, result: MatchEnd) -> None:
        """Optional hook called after the match winner is known."""

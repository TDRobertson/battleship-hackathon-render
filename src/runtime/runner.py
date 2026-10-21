from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from agent import Agent
from runtime.clocks import MatchClocks, Monotonic
from core.engine import GameEngine, InvalidAction
from core.models import Player
from sdk.observation import ObservationState, result_to_public
from core.rules import Rules, official_rules


@dataclass
class MatchReport:
    winner: Player
    reason: str
    turns: int
    remaining: dict[Player, float]
    match_id: str


@dataclass
class LocalRunner:
    rules: Rules = field(default_factory=official_rules)
    monotonic: Monotonic | None = None

    def run(self, agent_a: Agent, agent_b: Agent, match_id: str | None = None) -> MatchReport:
        engine = GameEngine(self.rules)
        clocks = MatchClocks(self.rules.thinking_seconds, self.monotonic) if self.monotonic else MatchClocks(self.rules.thinking_seconds)
        agents = {Player.A: agent_a, Player.B: agent_b}
        observations = {Player.A: ObservationState(self.rules), Player.B: ObservationState(self.rules)}
        match_id = match_id or str(uuid4())

        for player in (Player.A, Player.B):
            try:
                clocks.start(player)
                placements = agents[player].place_ships(self.rules, clocks.remaining[player])
                remaining = clocks.stop(player)
                if remaining <= 0:
                    engine.forfeit(player, "timeout during placement")
                    break
                engine.place_fleet(player, placements)
            except InvalidAction as exc:
                if clocks._charging is player:
                    clocks.stop(player)
                engine.forfeit(player, f"illegal placement: {exc}")
                break
            except Exception as exc:
                if clocks._charging is player:
                    try:
                        clocks.stop(player)
                    except Exception:
                        pass
                engine.forfeit(player, f"bot failure during placement: {exc}")
                break

        turns = 0
        while engine.winner is None:
            player = engine.active_player
            try:
                clocks.start(player)
                shot = agents[player].choose_shot(observations[player].snapshot(), clocks.remaining[player])
                remaining = clocks.stop(player)
                if remaining <= 0:
                    engine.forfeit(player, "timeout")
                    break
                result = engine.fire(player, int(shot[0]), int(shot[1]))
                observations[player].apply_result(result_to_public(result))
                turns += 1
            except InvalidAction as exc:
                if clocks._charging is player:
                    clocks.stop(player)
                engine.forfeit(player, f"illegal action: {exc}")
            except Exception as exc:
                if clocks._charging is player:
                    try:
                        clocks.stop(player)
                    except Exception:
                        pass
                engine.forfeit(player, f"bot failure: {exc}")

        assert engine.winner is not None
        return MatchReport(engine.winner, engine.termination_reason or "ended", turns, dict(clocks.remaining), match_id)

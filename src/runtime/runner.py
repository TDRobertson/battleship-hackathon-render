from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from agent import Agent, MatchContext, MatchEnd
from runtime.clocks import MatchClocks, Monotonic
from core.engine import GameEngine, InvalidAction
from core.models import Player
from sdk.memory import MemorySession, OpponentStatsTracker, load_memory_session
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
    memory_dir: str | Path | None = None

    def run(
        self,
        agent_a: Agent,
        agent_b: Agent,
        match_id: str | None = None,
        bot_a_name: str = "A",
        bot_b_name: str = "B",
    ) -> MatchReport:
        engine = GameEngine(self.rules)
        clocks = MatchClocks(self.rules.thinking_seconds, self.monotonic) if self.monotonic else MatchClocks(self.rules.thinking_seconds)
        agents = {Player.A: agent_a, Player.B: agent_b}
        bot_names = {Player.A: bot_a_name, Player.B: bot_b_name}
        observations = {Player.A: ObservationState(self.rules), Player.B: ObservationState(self.rules)}
        match_id = match_id or str(uuid4())
        memory_sessions = {
            Player.A: load_memory_session(self.memory_dir, bot_a_name, bot_b_name),
            Player.B: load_memory_session(self.memory_dir, bot_b_name, bot_a_name),
        }
        trackers = {
            player: OpponentStatsTracker(self.rules, player, memory_sessions[player].memory, [])
            for player in (Player.A, Player.B)
        }

        for player in (Player.A, Player.B):
            try:
                context = MatchContext(
                    match_id=match_id,
                    player=player,
                    bot_name=bot_names[player],
                    opponent_name=bot_names[player.opponent],
                    memory=memory_sessions[player].memory,
                )
                agents[player].start_match(context)
            except Exception as exc:
                engine.forfeit(player, f"bot failure during start_match: {exc}")
                break

        for player in (Player.A, Player.B):
            if engine.winner is not None:
                break
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
                public_result = result_to_public(result)
                observations[player].apply_result(public_result)
                defender = player.opponent
                trackers[defender].observe(public_result)
                try:
                    agents[defender].observe_opponent_shot(public_result, clocks.remaining[defender])
                except Exception as exc:
                    if engine.winner is None:
                        engine.forfeit(defender, f"bot failure during observe_opponent_shot: {exc}")
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
        report = MatchReport(engine.winner, engine.termination_reason or "ended", turns, dict(clocks.remaining), match_id)
        for player in (Player.A, Player.B):
            won = report.winner is player
            trackers[player].finish(won, turns)
            _call_end_match(agents[player], MatchEnd(won, report.winner, report.reason, turns))
            _save_memory(memory_sessions[player])
        return report


def _call_end_match(agent: Agent, result: MatchEnd) -> None:
    try:
        agent.end_match(result)
    except Exception:
        return


def _save_memory(session: MemorySession) -> None:
    try:
        session.save()
    except Exception:
        return

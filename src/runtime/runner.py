from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from uuid import uuid4
from typing import Callable

from agent import Agent, MatchContext, MatchEnd
from runtime.clocks import ACTION_TIMEOUT_SECONDS, PLACEMENT_TIMEOUT_SECONDS, ActionTimeout, Monotonic, MoveTiming, call_with_timeout, wait_for_minimum_move
from core.engine import GameEngine, InvalidAction
from core.models import Player, ShotResult
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
    move_timing: dict[Player, MoveTiming] = field(default_factory=lambda: {player: MoveTiming() for player in Player})


@dataclass
class LocalRunner:
    rules: Rules = field(default_factory=official_rules)
    monotonic: Monotonic | None = None
    memory_dir: str | Path | None = None
    on_shot: Callable[[ShotResult], None] | None = None
    on_placement: Callable[[Player, dict[int, tuple[tuple[int, int], ...]]], None] | None = None
    minimum_move_seconds: float = 0.0
    sleep: Callable[[float], None] | None = None
    agents_enforce_timeouts: bool = False

    def run(
        self,
        agent_a: Agent,
        agent_b: Agent,
        match_id: str | None = None,
        bot_a_name: str = "A",
        bot_b_name: str = "B",
        memory_a_name: str | None = None,
        memory_b_name: str | None = None,
    ) -> MatchReport:
        engine = GameEngine(self.rules)
        monotonic = self.monotonic or time.monotonic
        action_limit = min(ACTION_TIMEOUT_SECONDS, self.rules.thinking_seconds)
        placement_limit = min(PLACEMENT_TIMEOUT_SECONDS, self.rules.placement_seconds)
        remaining = {Player.A: action_limit, Player.B: action_limit}
        abandoned: set[Player] = set()
        agents = {Player.A: agent_a, Player.B: agent_b}
        bot_names = {Player.A: bot_a_name, Player.B: bot_b_name}
        observations = {Player.A: ObservationState(self.rules), Player.B: ObservationState(self.rules)}
        match_id = match_id or str(uuid4())
        memory_names = {Player.A: memory_a_name or bot_a_name, Player.B: memory_b_name or bot_b_name}
        memory_sessions = {
            Player.A: load_memory_session(self.memory_dir, memory_names[Player.A], memory_names[Player.B]),
            Player.B: load_memory_session(self.memory_dir, memory_names[Player.B], memory_names[Player.A]),
        }
        trackers = {
            player: OpponentStatsTracker(self.rules, player, memory_sessions[player].memory, [])
            for player in (Player.A, Player.B)
        }

        def timed_action(player: Player, action: Callable[[], object], limit: float) -> object:
            try:
                if self.agents_enforce_timeouts:
                    return action()
                return call_with_timeout(action, limit)
            except ActionTimeout:
                if not self.agents_enforce_timeouts:
                    abandoned.add(player)
                raise

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
                started = monotonic()
                try:
                    placements = timed_action(player, lambda: agents[player].place_ships(self.rules, placement_limit), placement_limit)
                finally:
                    elapsed = monotonic() - started
                    remaining[player] = max(0.0, placement_limit - elapsed)
                if self.monotonic is not None and elapsed > placement_limit and not self.agents_enforce_timeouts:
                    engine.forfeit(player, "timeout during placement")
                    break
                engine.place_fleet(player, placements)
                if self.on_placement is not None:
                    try:
                        self.on_placement(player, engine.fleet_cells(player))
                    except Exception:
                        pass  # A spectator must never affect a match.
            except ActionTimeout as exc:
                remaining[player] = 0.0
                engine.forfeit(player, f"timeout during placement: {exc}")
                break
            except InvalidAction as exc:
                engine.forfeit(player, f"illegal placement: {exc}")
                break
            except Exception as exc:
                engine.forfeit(player, f"bot failure during placement: {exc}")
                break

        turns = 0
        move_timing = {player: MoveTiming() for player in (Player.A, Player.B)}
        while engine.winner is None:
            player = engine.active_player
            try:
                move_started = monotonic()
                snapshot = observations[player].snapshot()
                started = monotonic()
                try:
                    shot = timed_action(player, lambda: agents[player].choose_shot(snapshot, action_limit), action_limit)
                finally:
                    elapsed = monotonic() - started
                    remaining[player] = max(0.0, action_limit - elapsed)
                    move_timing[player].record(elapsed)
                if self.monotonic is not None and elapsed > action_limit and not self.agents_enforce_timeouts:
                    engine.forfeit(player, "timeout")
                    break
                wait_for_minimum_move(
                    move_started,
                    self.minimum_move_seconds,
                    monotonic,
                    self.sleep or time.sleep,
                )
                result = engine.fire(player, int(shot[0]), int(shot[1]))
                public_result = result_to_public(result)
                observations[player].apply_result(public_result)
                defender = player.opponent
                trackers[defender].observe(public_result)
                try:
                    agents[defender].observe_opponent_shot(public_result, action_limit)
                except Exception as exc:
                    if engine.winner is None:
                        engine.forfeit(defender, f"bot failure during observe_opponent_shot: {exc}")
                turns += 1
                if self.on_shot is not None:
                    try:
                        self.on_shot(result)
                    except Exception:
                        pass  # A spectator must never affect a match.
            except ActionTimeout as exc:
                remaining[player] = 0.0
                engine.forfeit(player, f"timeout during shot: {exc}")
            except InvalidAction as exc:
                engine.forfeit(player, f"illegal action: {exc}")
            except Exception as exc:
                engine.forfeit(player, f"bot failure: {exc}")

        assert engine.winner is not None
        report = MatchReport(engine.winner, engine.termination_reason or "ended", turns, remaining, match_id, move_timing)
        for player in (Player.A, Player.B):
            if player in abandoned:
                continue
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

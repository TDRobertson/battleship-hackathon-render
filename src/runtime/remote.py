from __future__ import annotations

import json
import hashlib
import os
import random
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from agent import Agent, MatchContext, MatchEnd
from core.models import Coord, Player, PublicShotResult, ShipPlacement, ShotResult
from core.rules import Rules, official_rules
from runtime.bot_loading import build_bot
from runtime.clocks import ACTION_TIMEOUT_SECONDS, PLACEMENT_TIMEOUT_SECONDS, MINIMUM_MOVE_SECONDS, ActionTimeout
from runtime.runner import LocalRunner
from sdk.observation import ObservationSnapshot, ObservationState
from runtime.worker import _public_result_from_payload


class RemoteError(RuntimeError):
    pass


REMOTE_ACTION_SECONDS = ACTION_TIMEOUT_SECONDS
REMOTE_LIFECYCLE_SECONDS = 30.0
REMOTE_MINIMUM_MOVE_SECONDS = MINIMUM_MOVE_SECONDS
TOURNAMENT_RECONNECT_SECONDS = 30.0
TOURNAMENT_MAX_GAMES = 5
TOURNAMENT_WINS_NEEDED = 3


class RemoteSeriesStopped(RemoteError):
    def __init__(self, reports: list[dict] | None = None, reason: str = "match stopped") -> None:
        super().__init__(reason)
        self.reason = reason
        self.reports = reports if reports is not None else []


def _series_finished(series: dict) -> bool:
    target = series.get("wins_needed")
    return max(series["a_wins"], series["b_wins"]) >= target if target is not None else series["completed"] >= series["games"]


@dataclass(slots=True)
class RemoteBotSession:
    bot_id: str
    name: str
    token: str
    tasks: list[dict] = field(default_factory=list)
    responses: dict[str, tuple[float, dict]] = field(default_factory=dict)
    pending_actions: set[str] = field(default_factory=set)
    last_seen: float = field(default_factory=time.monotonic)
    heartbeat_enabled: bool = False
    online: bool = True
    ready: bool = True
    connection_id: str | None = None
    disconnected: bool = False


@dataclass(slots=True)
class RemoteHubState:
    action_timeout: float = PLACEMENT_TIMEOUT_SECONDS
    disconnect_timeout: float = 15.0
    bots: dict[str, RemoteBotSession] = field(default_factory=dict)
    matches: dict[str, dict] = field(default_factory=dict)
    completed_matches: list[str] = field(default_factory=list)
    ongoing_series: dict[str, dict] = field(default_factory=dict)
    tournaments: dict[str, dict] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)
    hide_ships: bool = False
    changed: threading.Condition = field(init=False)

    def __post_init__(self) -> None:
        self.changed = threading.Condition(self.lock)

    def start_series(self, bot_a_id: str, bot_b_id: str, games: int, exclusive: bool = False,
                     tournament_id: str | None = None, pair_id: str | None = None,
                     wins_needed: int | None = None) -> str:
        series_id = uuid4().hex
        with self.lock:
            self.expire_offline()
            for bot_id in (bot_a_id, bot_b_id):
                bot = self._require_bot(bot_id)
                if not bot.online and tournament_id is None:
                    raise RemoteError(f"remote bot {bot.name!r} is offline")
                if not bot.ready and tournament_id is None:
                    raise RemoteError(f"remote bot {bot.name!r} is unresponsive")
                if any(bot_id in (series["bot_a_id"], series["bot_b_id"]) and
                       (exclusive or series.get("exclusive", False))
                       for series in self.ongoing_series.values()):
                    raise RemoteError(f"remote bot {bot.name!r} is already in a series")
            if tournament_id is not None:
                _, pair = self._tournament_pair(tournament_id, str(pair_id))
                if pair["status"] != "waiting" or (pair["bot_a"], pair["bot_b"]) != (bot_a_id, bot_b_id):
                    raise RemoteError("tournament pairing cannot be started")
                pair["status"] = "playing"
                pair["series_id"] = series_id
            self.ongoing_series[series_id] = {
                "series_id": series_id,
                "bot_a": self._require_bot(bot_a_id).name,
                "bot_b": self._require_bot(bot_b_id).name,
                "bot_a_id": bot_a_id, "bot_b_id": bot_b_id,
                "games": games, "completed": 0, "a_wins": 0, "b_wins": 0,
                "wins_needed": wins_needed,
                "game": 0, "match_id": None, "turns": 0, "stopping": False, "stop_reason": None,
                "stop_after_current": None, "timed_out_bot_id": None,
                "exclusive": exclusive,
                "tournament_id": tournament_id, "pair_id": pair_id,
                "interrupted_bots": [],
            }
        return series_id

    def end_series(self, series_id: str, reason: str | None = None) -> None:
        with self.lock:
            series = self.ongoing_series.pop(series_id, None)
            if series and series["tournament_id"] is not None:
                tournament, pair = self._tournament_pair(series["tournament_id"], series["pair_id"])
                if _series_finished(series) and not series["stopping"] and reason is None:
                    winner = series["bot_a_id"] if series["a_wins"] > series["b_wins"] else series["bot_b_id"]
                    loser = series["bot_b_id"] if winner == series["bot_a_id"] else series["bot_a_id"]
                    pair.update(status="finished", winner=winner, loser=loser, advancement_pending=True)
                else:
                    pair.update(status="stopped", reason=reason or series["stop_reason"] or series["stop_after_current"] or "series interrupted")

    def list_series(self) -> list[dict]:
        with self.lock:
            return [dict(series) for series in self.ongoing_series.values()]

    def create_tournament(self, entrants: dict[str, str], seed: int) -> str:
        tournament_id = uuid4().hex
        with self.lock:
            self.tournaments[tournament_id] = {
                "id": tournament_id, "seed": seed, "status": "running", "wave": 0,
                "phase": "winners", "finalist_id": None, "disqualifications": [],
                "entrants": {bot_id: {"id": bot_id, "name": name, "losses": 0, "disconnects": {"winners": 0, "losers": 0}} for bot_id, name in entrants.items()},
                "pairings": [], "byes": [], "waiting": None, "champion_id": None, "reason": None,
            }
        return tournament_id

    def update_tournament(self, tournament_id: str, event: dict) -> None:
        with self.lock:
            tournament = self.tournaments.get(tournament_id)
            if tournament is None:
                raise RemoteError("unknown tournament")
            kind = event["type"]
            if kind == "wave":
                tournament["wave"] = int(event["wave"])
                if "phase" in event:
                    tournament["phase"] = str(event["phase"])
                    tournament["finalist_id"] = event.get("finalist_id")
            elif kind == "entrant":
                bot_id = str(event["bot_id"])
                tournament["entrants"][bot_id] = {"id": bot_id, "name": str(event["name"]), "losses": 0, "disconnects": {"winners": 0, "losers": 0}}
            elif kind == "pair":
                a, b = str(event["bot_a"]), str(event["bot_b"])
                if a not in tournament["entrants"] or b not in tournament["entrants"]:
                    raise RemoteError("unknown tournament entrant")
                tournament["pairings"].append({
                    "id": str(event["pair_id"]), "wave": int(event["wave"]), "bracket": str(event["bracket"]),
                    "final_reset": bool(event.get("final_reset")), "bot_a": a, "bot_b": b,
                    "a_losses_before": tournament["entrants"][a]["losses"], "b_losses_before": tournament["entrants"][b]["losses"],
                    "status": "waiting", "games": TOURNAMENT_MAX_GAMES, "completed": 0, "a_wins": 0, "b_wins": 0,
                    "winner": None, "loser": None, "reason": None, "rounds": [],
                })
            elif kind == "bye":
                tournament["byes"].append({"wave": int(event["wave"]), "bracket": str(event["bracket"]), "bot_id": str(event["bot_id"]), "advancement_pending": True})
            elif kind == "waiting":
                tournament["waiting"] = {"bot_id": str(event["bot_id"]), "bracket": str(event["bracket"])} if event.get("bot_id") else None
            elif kind == "break":
                tournament["break_until"] = (time.time() + float(event["seconds"])) if "seconds" in event else event.get("until")
            elif kind == "decision":
                _, pair = self._tournament_pair(tournament_id, str(event["pair_id"]))
                pair.update(winner=event.get("winner"), loser=event.get("loser"), advancement_pending=False,
                            decision_reason=event.get("reason"))
                for bot_id, losses in event["losses"].items():
                    tournament["entrants"][bot_id]["losses"] = int(losses)
            elif kind == "bye_decision":
                bot_id = str(event["bot_id"])
                tournament["entrants"][bot_id]["losses"] = int(event["losses"])
                for bye in reversed(tournament["byes"]):
                    if bye["bot_id"] == bot_id and bye["wave"] == event["wave"]:
                        bye.update(reason=event.get("reason"), advancement_pending=False)
                        break
            elif kind == "disqualification":
                bot_id = str(event["bot_id"])
                tournament["entrants"][bot_id]["losses"] = int(event["losses"])
                tournament["disqualifications"].append({"wave": int(event["wave"]), "bot_id": bot_id, "bracket": str(event["bracket"]),
                                                          "reason": str(event["reason"])})
                if tournament["finalist_id"] == bot_id:
                    tournament["finalist_id"] = None
            elif kind == "pair_error":
                _, pair = self._tournament_pair(tournament_id, str(event["pair_id"]))
                if pair["status"] != "finished":
                    pair.update(status="stopped", reason=str(event["reason"]))
            elif kind == "finish":
                tournament.update(status=str(event["status"]), champion_id=event.get("champion_id"), reason=event.get("reason"))
            else:
                raise RemoteError("unknown tournament event")

    def _tournament_pair(self, tournament_id: str, pair_id: str) -> tuple[dict, dict]:
        tournament = self.tournaments.get(tournament_id)
        if tournament is None:
            raise RemoteError("unknown tournament")
        pair = next((item for item in tournament["pairings"] if item["id"] == pair_id), None)
        if pair is None:
            raise RemoteError("unknown tournament pairing")
        return tournament, pair

    def spectator_tournaments(self) -> list[dict]:
        with self.lock:
            return json.loads(json.dumps(list(reversed(self.tournaments.values()))))

    def _record_disconnect(self, bot_id: str) -> None:
        bot = self.bots[bot_id]
        if bot.disconnected:
            return
        bot.disconnected = True
        for tournament in self.tournaments.values():
            entrant = tournament["entrants"].get(bot_id)
            if tournament["status"] == "running" and entrant and entrant["losses"] < 2:
                bracket = "winners" if entrant["losses"] == 0 else "losers"
                entrant["disconnects"][bracket] += 1
        for series in self.ongoing_series.values():
            if series["tournament_id"] is not None and bot_id in (series["bot_a_id"], series["bot_b_id"]):
                if series["match_id"] and series["completed"] < series["game"]:
                    if bot_id not in series["interrupted_bots"]:
                        series["interrupted_bots"].append(bot_id)

    def wait_for_tournament_player(self, series_id: str, bot_id: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self.changed:
            series = self.ongoing_series[series_id]
            _, pair = self._tournament_pair(series["tournament_id"], series["pair_id"])
            pair.update(status="reconnecting", reconnecting_bot=bot_id, reconnect_until=time.time() + timeout)
            try:
                while True:
                    if series["stopping"]:
                        raise RemoteSeriesStopped(reason=series["stop_reason"])
                    bot = self.bots.get(bot_id)
                    if bot and bot.online and bot.ready:
                        return True
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    self.changed.wait(min(remaining, 0.25))
            finally:
                pair.update(status="playing", reconnecting_bot=None, reconnect_until=None)

    def stop_series(self, match_or_series_id: str) -> dict:
        with self.changed:
            series = self.ongoing_series.get(match_or_series_id)
            if series is None:
                matches = [s for s in self.ongoing_series.values() if s["match_id"] == match_or_series_id]
                if len(matches) > 1:
                    raise RemoteError("multiple ongoing series have this match id; use series id")
                if not matches:
                    raise RemoteError("unknown ongoing match or series id")
                series = matches[0]
            if _series_finished(series):
                raise RemoteError("match series has already finished")
            series["stopping"] = True
            series["stop_reason"] = "match stopped"
            self.changed.notify_all()
            return {"series_id": series["series_id"]}

    def unregister(self, bot_id: str) -> dict:
        with self.changed:
            bot = self._require_bot(bot_id)
            del self.bots[bot_id]
            stopped = []
            for series in self.ongoing_series.values():
                if bot_id in (series["bot_a_id"], series["bot_b_id"]) and not _series_finished(series):
                    series["stopping"] = True
                    series["stop_reason"] = f"player {bot.name!r} was unregistered"
                    stopped.append(series["series_id"])
            self.changed.notify_all()
            return {"bot_id": bot_id, "name": bot.name, "stopped_series": stopped}

    def start_spectating(
        self, match_id: str, bot_a: str, bot_b: str, rules: Rules,
        series_id: str | None = None, game: int = 1, flipped: bool = False,
    ) -> str:
        spectator_id = uuid4().hex
        with self.lock:
            if series_id is not None and self.ongoing_series[series_id]["stopping"]:
                raise RemoteSeriesStopped(reason=self.ongoing_series[series_id]["stop_reason"])
            if series_id is not None and _series_finished(self.ongoing_series[series_id]):
                raise RemoteError("match series has already finished")
            if series_id is not None and game > 1 and self.ongoing_series[series_id]["stop_after_current"]:
                raise RemoteSeriesStopped(reason=self.ongoing_series[series_id]["stop_after_current"])
            self.matches[spectator_id] = {
                "id": spectator_id, "match_id": match_id, "bot_a": bot_a, "bot_b": bot_b,
                "rows": rules.rows, "cols": rules.cols, "shots": [], "status": "playing",
                "_fleets": {}, "_series_id": series_id, "_flipped": flipped,
            }
            if series_id is not None:
                series = self.ongoing_series[series_id]
                series.update(game=game, match_id=match_id, turns=0)
                if series["tournament_id"] is not None:
                    _, pair = self._tournament_pair(series["tournament_id"], series["pair_id"])
                    self.matches[spectator_id].update(tournament_id=series["tournament_id"], pair_id=series["pair_id"], game=game)
                    pair["rounds"].append({"id": spectator_id, "game": game, "status": "playing", "winner": None})
        return spectator_id

    def record_placement(self, spectator_id: str, player: Player, fleet: dict[int, tuple[Coord, ...]]) -> None:
        with self.lock:
            self.matches[spectator_id]["_fleets"][player.value] = [list(cell) for cells in fleet.values() for cell in cells]

    def record_shot(self, spectator_id: str, result: ShotResult) -> None:
        shot = {
            "player": result.player.value, "row": result.shot[0], "col": result.shot[1],
            "outcome": result.outcome.value,
            "sunk_cells": list(result.sunk_ship.cells) if result.sunk_ship else [],
        }
        with self.lock:
            match = self.matches[spectator_id]
            match["shots"].append(shot)
            if match["_series_id"] is not None:
                self.ongoing_series[match["_series_id"]]["turns"] += 1

    def finish_spectating(self, spectator_id: str, winner: str | None, reason: str) -> str | None:
        with self.lock:
            match = self.matches[spectator_id]
            series = self.ongoing_series.get(match["_series_id"])
            stopped = bool(series and series["stopping"])
            match.update(status="stopped" if stopped else "finished",
                         winner=None if stopped else winner,
                         reason=series["stop_reason"] if stopped else reason)
            if series and not stopped and winner in ("A", "B"):
                series["completed"] += 1
                series["a_wins" if (winner == "A") != match["_flipped"] else "b_wins"] += 1
            if series and series["tournament_id"] is not None:
                _, pair = self._tournament_pair(series["tournament_id"], series["pair_id"])
                pair.update(completed=series["completed"], a_wins=series["a_wins"], b_wins=series["b_wins"])
                winner_bot = None
                if not stopped and winner in ("A", "B"):
                    winner_bot = series["bot_a_id"] if (winner == "A") != match["_flipped"] else series["bot_b_id"]
                pair["rounds"][-1].update(status=match["status"], winner=winner_bot)
            self.completed_matches.append(spectator_id)
            if len(self.completed_matches) > 50:
                expired_id = self.completed_matches.pop(0)
                if "tournament_id" not in self.matches[expired_id]:
                    del self.matches[expired_id]
            return series["stop_reason"] if stopped else None

    def spectator_matches(self, pair_id: str | None = None, recent_only: bool = False) -> list[dict]:
        with self.lock:
            # Copy while locked so JSON serialization cannot race with updates.
            matches = []
            for match in reversed(self.matches.values()):
                if pair_id is not None and match.get("pair_id") != pair_id:
                    continue
                if recent_only and match["status"] != "playing" and match["id"] not in self.completed_matches:
                    continue
                public = {key: value for key, value in match.items() if not key.startswith("_")}
                public["live_ships_visible"] = not self.hide_ships
                if not self.hide_ships or match["status"] != "playing":
                    public["fleets"] = match["_fleets"]
                matches.append(public)
            return json.loads(json.dumps(matches))

    def register(self, name: str, heartbeat: bool = False) -> dict:
        bot_id = uuid4().hex
        token = uuid4().hex
        connection_id = uuid4().hex if heartbeat else None
        with self.changed:
            self.bots[bot_id] = RemoteBotSession(
                bot_id, name.strip() or bot_id, token,
                heartbeat_enabled=heartbeat, connection_id=connection_id,
            )
            self.changed.notify_all()
            return {"bot_id": bot_id, "token": token, "name": self.bots[bot_id].name, "connection_id": connection_id}

    def resume(self, bot_id: str, token: str) -> dict:
        with self.changed:
            bot = self._require_bot(bot_id, token)
            if bot.online:
                self._record_disconnect(bot_id)
            self._stop_bot_series(bot_id, f"player {bot.name!r} reconnected")
            bot.connection_id = uuid4().hex
            bot.heartbeat_enabled = True
            bot.last_seen = time.monotonic()
            bot.online = True
            bot.ready = True
            bot.disconnected = False
            self.changed.notify_all()
            return {"bot_id": bot_id, "token": token, "name": bot.name, "connection_id": bot.connection_id}

    def heartbeat(self, bot_id: str, token: str, connection_id: str) -> None:
        with self.changed:
            bot = self._require_connection(bot_id, token, connection_id)
            self.expire_offline()
            bot.last_seen = time.monotonic()
            bot.online = True
            bot.disconnected = False
            self.changed.notify_all()

    def _stop_bot_series(self, bot_id: str, reason: str) -> None:
        for series in self.ongoing_series.values():
            if bot_id in (series["bot_a_id"], series["bot_b_id"]) and not _series_finished(series):
                if series["tournament_id"] is not None:
                    continue
                # Preserve a forfeit already decided by the action deadline.
                if series["timed_out_bot_id"] == bot_id:
                    continue
                if not series["stopping"]:
                    series["stopping"] = True
                    series["stop_reason"] = reason

    def _mark_action_timeout(self, bot: RemoteBotSession, series_id: str | None, mark_unresponsive: bool = True) -> None:
        if mark_unresponsive:
            bot.ready = False
        reason = f"player {bot.name!r} is unresponsive after an action timeout"
        for current_id, series in self.ongoing_series.items():
            if bot.bot_id not in (series["bot_a_id"], series["bot_b_id"]) or _series_finished(series):
                continue
            if current_id == series_id:
                if series["tournament_id"] is None:
                    series["stop_after_current"] = reason
                series["timed_out_bot_id"] = bot.bot_id
            elif not series["stopping"]:
                series["stopping"] = True
                series["stop_reason"] = reason
        self.changed.notify_all()

    def expire_offline(self) -> None:
        now = time.monotonic()
        with self.changed:
            expired = False
            for bot in self.bots.values():
                if bot.heartbeat_enabled and bot.online and now - bot.last_seen >= self.disconnect_timeout:
                    bot.online = False
                    self._record_disconnect(bot.bot_id)
                    self._stop_bot_series(bot.bot_id, f"player {bot.name!r} disconnected")
                    expired = True
            if expired:
                self.changed.notify_all()

    def list_bots(self) -> list[dict]:
        now = time.monotonic()
        with self.lock:
            return [
                {
                    "bot_id": bot.bot_id,
                    "name": bot.name,
                    "queued": len(bot.tasks),
                    "seconds_since_seen": round(now - bot.last_seen, 3),
                    "status": ("offline" if not bot.online else "unresponsive" if not bot.ready
                               else "online" if bot.heartbeat_enabled else "legacy"),
                }
                for bot in self.bots.values()
            ]

    def poll(self, bot_id: str, token: str, timeout: float, connection_id: str | None = None) -> dict | None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self.changed:
            bot = self._require_connection(bot_id, token, connection_id)
            bot.ready = True
            self.changed.notify_all()
            if not bot.heartbeat_enabled:
                bot.last_seen = time.monotonic()
            while True:
                while bot.tasks:
                    task = bot.tasks.pop(0)
                    task_series_id = task.get("series_id")
                    if task_series_id is None or (
                        task_series_id in self.ongoing_series and not self.ongoing_series[task_series_id]["stopping"]
                    ):
                        return task
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.changed.wait(remaining)
                bot = self._require_connection(bot_id, token, connection_id)

    def respond(self, bot_id: str, token: str, response: dict, connection_id: str | None = None) -> None:
        received_at = time.monotonic()
        action_id = str(response.get("action_id", ""))
        if not action_id:
            raise RemoteError("response is missing action_id")
        with self.changed:
            bot = self._require_connection(bot_id, token, connection_id)
            if not bot.heartbeat_enabled:
                bot.last_seen = time.monotonic()
            if action_id in bot.pending_actions:
                bot.responses.setdefault(action_id, (received_at, response))
                self.changed.notify_all()

    def request_action(self, bot_id: str, task: dict, timeout: float) -> dict:
        action_id = str(task["action_id"])
        series_id = task.get("series_id")
        deadline = time.monotonic() + max(0.0, timeout)
        interruption_deadline_set = False
        with self.changed:
            bot = self._require_bot(bot_id)
            original_connection_id = bot.connection_id
            bot.pending_actions.add(action_id)
            bot.tasks.append(task)
            self.changed.notify_all()
            try:
                while True:
                    if series_id is not None and self.ongoing_series[series_id]["stopping"]:
                        raise RemoteSeriesStopped(reason=self.ongoing_series[series_id]["stop_reason"])
                    if bot_id not in self.bots:
                        raise RemoteError("remote bot was unregistered")
                    interrupted = series_id is not None and bot_id in self.ongoing_series[series_id]["interrupted_bots"]
                    if interrupted and not interruption_deadline_set:
                        deadline = min(deadline, time.monotonic() + REMOTE_ACTION_SECONDS)
                        interruption_deadline_set = True
                    if not interrupted and action_id in bot.responses:
                        received_at, response = bot.responses.pop(action_id)
                        if received_at > deadline:
                            self._mark_action_timeout(bot, series_id)
                            raise ActionTimeout(f"remote bot {bot.name!r} exceeded its {timeout:g}s action limit")
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        recovered = interrupted and (bot.connection_id != original_connection_id or action_id in bot.responses)
                        self._mark_action_timeout(bot, series_id, mark_unresponsive=not recovered)
                        raise ActionTimeout(f"remote bot {bot.name!r} exceeded its {timeout:g}s action limit")
                    self.changed.wait(remaining)
            finally:
                bot.pending_actions.discard(action_id)
                bot.responses.pop(action_id, None)
                bot.tasks[:] = [queued for queued in bot.tasks if queued.get("action_id") != action_id]
        if not response.get("ok"):
            raise RemoteError(str(response.get("error", "remote bot error")))
        return response

    def resolve_bot(self, label: str) -> str:
        with self.lock:
            if label in self.bots:
                return label
            matches = [bot.bot_id for bot in self.bots.values() if bot.name == label]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise RemoteError(f"unknown remote bot {label!r}")
        raise RemoteError(f"multiple remote bots are named {label!r}; use bot_id")

    def _require_bot(self, bot_id: str, token: str | None = None) -> RemoteBotSession:
        bot = self.bots.get(bot_id)
        if bot is None:
            raise RemoteError("unknown bot_id")
        if token is not None and token != bot.token:
            raise RemoteError("invalid token")
        return bot

    def _require_connection(self, bot_id: str, token: str, connection_id: str | None) -> RemoteBotSession:
        bot = self._require_bot(bot_id, token)
        if bot.connection_id is not None and connection_id != bot.connection_id:
            raise RemoteError("session replaced")
        return bot


@dataclass
class RemoteServerAgent(Agent):
    state: RemoteHubState
    bot_id: str
    match_id: str
    player: Player
    rules: Rules = field(default_factory=official_rules)
    series_id: str | None = None
    lifecycle: bool = False
    context: MatchContext | None = None

    def start_match(self, context: MatchContext) -> None:
        if self.lifecycle:
            self.context = context
            self._request({"type": "start_match", "context": asdict(context)}, self.rules.thinking_seconds)

    def observe_opponent_shot(self, result: PublicShotResult, time_remaining: float) -> None:
        if self.lifecycle:
            self._request({"type": "observe_opponent_shot", "result": asdict(result)}, time_remaining)

    def end_match(self, result: MatchEnd) -> None:
        if self.lifecycle and self.context is not None:
            with self.state.lock:
                series = self.state.ongoing_series.get(self.series_id)
                bot = self.state.bots.get(self.bot_id)
                if series and series["tournament_id"] is not None and (
                    not bot or not bot.online or not bot.ready or self.bot_id in series["interrupted_bots"]
                ):
                    return
            self._request({"type": "end_match", "result": asdict(result), "memory": self.context.memory}, self.rules.thinking_seconds)

    def place_ships(self, rules: Rules, time_remaining: float) -> list[ShipPlacement]:
        response = self._request(
            {
                "type": "place_ships",
                "rules": _rules_to_payload(rules),
                "time_remaining": time_remaining,
            },
            time_remaining,
        )
        return [
            ShipPlacement(int(p["slot"]), int(p["row"]), int(p["col"]), p["orientation"])
            for p in response["placements"]
        ]

    def choose_shot(self, observation: ObservationSnapshot, time_remaining: float) -> Coord:
        state = ObservationState(self.rules)
        state.replace_from_snapshot(observation)
        response = self._request(
            {
                "type": "choose_shot",
                "rules": _rules_to_payload(self.rules),
                "time_remaining": time_remaining,
                "observation": state.to_lists(),
            },
            time_remaining,
        )
        row, col = response["shot"]
        return int(row), int(col)

    def _request(self, payload: dict, time_remaining: float) -> dict:
        payload = dict(payload)
        payload["action_id"] = uuid4().hex
        payload["match_id"] = self.match_id
        payload["player"] = self.player.value
        payload["series_id"] = self.series_id
        is_move = payload["type"] in ("place_ships", "choose_shot")
        cap = PLACEMENT_TIMEOUT_SECONDS if payload["type"] == "place_ships" else REMOTE_ACTION_SECONDS
        timeout = max(0.0, min(cap, self.state.action_timeout, float(time_remaining))) if is_move else REMOTE_LIFECYCLE_SECONDS
        payload["time_remaining"] = timeout if is_move else float(time_remaining)
        response = self.state.request_action(self.bot_id, payload, timeout)
        if self.context is not None and isinstance(response.get("memory"), dict):
            self.context.memory.clear()
            self.context.memory.update(response["memory"])
        return response


class RemoteBotClient:
    def __init__(
        self,
        server_url: str,
        bot_spec: str,
        name: str,
        seed: int | None = None,
        poll_timeout: float = 20.0,
        session_file: str | Path | None = None,
        heartbeat_interval: float = 5.0,
    ) -> None:
        if heartbeat_interval <= 0:
            raise ValueError("heartbeat interval must be positive")
        self.server_url = server_url.rstrip("/")
        self.bot_spec = bot_spec
        self.name = name.strip()
        if not self.name:
            raise ValueError("remote player name cannot be empty")
        self.seed = seed
        self.poll_timeout = poll_timeout
        self.session_file = Path(session_file).expanduser() if session_file is not None else None
        self.heartbeat_interval = heartbeat_interval
        self.bot_id: str | None = None
        self.token: str | None = None
        self.connection_id: str | None = None
        self.bot: Agent | None = None
        self.match_id: str | None = None
        self.context: MatchContext | None = None

    def register(self) -> dict:
        credentials = _read_session(self.session_file, self.server_url, self.name) if self.session_file else None
        payload = None
        if credentials is not None:
            try:
                payload = _post_json(self.server_url, "/api/resume", credentials)
                payload["resumed"] = True
            except RemoteError as exc:
                if str(exc) != "unknown bot_id":
                    raise
        if payload is None:
            payload = _post_json(self.server_url, "/api/register", {"name": self.name, "heartbeat": True})
            payload["resumed"] = False
        self.bot_id = str(payload["bot_id"])
        self.token = str(payload["token"])
        self.connection_id = str(payload["connection_id"])
        self.name = str(payload["name"])
        if self.session_file:
            _write_session(self.session_file, self.server_url, self.name, self.bot_id, self.token)
        return payload

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        if self.bot_id is None or self.token is None:
            self.register()
        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, args=(heartbeat_stop,), daemon=True)
        heartbeat_thread.start()
        try:
            while not heartbeat_stop.is_set() and (stop_event is None or not stop_event.is_set()):
                try:
                    task = self.poll_once()
                    if task is not None:
                        self.respond_to(task)
                except RemoteError as exc:
                    if str(exc) in ("unknown bot_id", "session replaced", "invalid token"):
                        if stop_event is None or not stop_event.is_set():
                            print(f"remote bot {self.name}: {exc}", flush=True)
                        break
                    if stop_event is not None and stop_event.is_set():
                        break
                    time.sleep(0.25)
                except (OSError, urllib.error.URLError):
                    if stop_event is not None and stop_event.is_set():
                        break
                    time.sleep(0.25)
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=2)

    def _heartbeat_loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                _post_json(self.server_url, "/api/heartbeat", self._credentials(), timeout=2.0)
            except RemoteError as exc:
                if str(exc) in ("unknown bot_id", "session replaced", "invalid token"):
                    stop.set()
                    break
            except (OSError, urllib.error.URLError):
                pass
            stop.wait(self.heartbeat_interval)

    def _credentials(self) -> dict:
        self._require_registered()
        return {"bot_id": self.bot_id, "token": self.token, "connection_id": self.connection_id}

    def poll_once(self) -> dict | None:
        self._require_registered()
        payload = _post_json(
            self.server_url,
            "/api/poll",
            {**self._credentials(), "timeout": self.poll_timeout},
            timeout=self.poll_timeout + 5.0,
        )
        return payload.get("task")

    def respond_to(self, task: dict) -> None:
        self._require_registered()
        try:
            response = self._handle_task(task)
        except Exception as exc:
            response = {"ok": False, "error": str(exc), "action_id": task.get("action_id")}
        _post_json(
            self.server_url,
            "/api/respond",
            {**self._credentials(), "response": response},
        )

    def _handle_task(self, task: dict) -> dict:
        action_id = task.get("action_id")
        rules = _rules_from_payload(task.get("rules", {}))
        if task.get("type") == "start_match":
            payload = task["context"]
            bot = self._bot_for_match(str(task["match_id"]))
            self.context = MatchContext(str(payload["match_id"]), Player(payload["player"]), str(payload["bot_name"]), str(payload["opponent_name"]), dict(payload["memory"]))
            bot.start_match(self.context)
            return {"ok": True, "action_id": action_id, "memory": self.context.memory}
        if task.get("type") == "observe_opponent_shot":
            bot = self._bot_for_match(str(task["match_id"]))
            bot.observe_opponent_shot(_public_result_from_payload(task["result"]), float(task["time_remaining"]))
            return {"ok": True, "action_id": action_id, "memory": self.context.memory}
        if task.get("type") == "end_match":
            bot = self._bot_for_match(str(task["match_id"]))
            assert self.context is not None
            self.context.memory.clear()
            self.context.memory.update(task["memory"])
            result = task["result"]
            bot.end_match(MatchEnd(bool(result["won"]), Player(result["winner"]), str(result["reason"]), int(result["turns"])))
            return {"ok": True, "action_id": action_id, "memory": self.context.memory}
        if task.get("type") == "place_ships":
            bot = self._bot_for_match(str(task.get("match_id", "")))
            placements = bot.place_ships(rules, float(task["time_remaining"]))
            response = {"ok": True, "action_id": action_id, "placements": [asdict(p) for p in placements]}
            if self.context is not None:
                response["memory"] = self.context.memory
            return response
        if task.get("type") == "choose_shot":
            bot = self._bot_for_match(str(task.get("match_id", "")))
            observation = ObservationState.from_lists(task["observation"], rules).snapshot()
            shot = bot.choose_shot(observation, float(task["time_remaining"]))
            response = {"ok": True, "action_id": action_id, "shot": [int(shot[0]), int(shot[1])]}
            if self.context is not None:
                response["memory"] = self.context.memory
            return response
        return {"ok": False, "action_id": action_id, "error": "unknown task type"}

    def _bot_for_match(self, match_id: str) -> Agent:
        if self.bot is None or match_id != self.match_id:
            self.match_id = match_id
            self.context = None
            self.bot = build_bot(self.bot_spec, _match_seed(self.seed, match_id))
        return self.bot

    def _require_registered(self) -> None:
        if self.bot_id is None or self.token is None:
            raise RemoteError("client is not registered")


def default_session_file(server_url: str, name: str) -> Path:
    identity = json.dumps([server_url.rstrip("/"), name], ensure_ascii=False).encode("utf-8")
    key = hashlib.sha256(identity).hexdigest()
    return Path.home() / ".battleship" / "remote-sessions" / f"{key}.json"


def _read_session(path: Path, server_url: str, name: str) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise RemoteError(f"cannot read remote session file {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("server") != server_url or data.get("name") != name:
        raise RemoteError(f"remote session file {path} belongs to a different server or player")
    if not isinstance(data.get("bot_id"), str) or not isinstance(data.get("token"), str):
        raise RemoteError(f"remote session file {path} is invalid")
    return {"bot_id": data["bot_id"], "token": data["token"]}


def _write_session(path: Path, server_url: str, name: str, bot_id: str, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".session-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"server": server_url, "name": name, "bot_id": bot_id, "token": token}, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create_remote_server(
    host: str = "0.0.0.0", port: int = 8765, action_timeout: float = PLACEMENT_TIMEOUT_SECONDS,
    disconnect_timeout: float = 15.0, hide_ships: bool = False,
) -> ThreadingHTTPServer:
    if disconnect_timeout <= 0:
        raise ValueError("disconnect timeout must be positive")
    state = RemoteHubState(action_timeout=action_timeout, disconnect_timeout=disconnect_timeout, hide_ships=hide_ships)

    class Handler(RemoteRequestHandler):
        hub_state = state

    class RemoteHTTPServer(ThreadingHTTPServer):
        def server_close(self) -> None:
            self.expiry_stop.set()
            self.expiry_thread.join(timeout=2)
            super().server_close()

    server = RemoteHTTPServer((host, port), Handler)
    server.hub_state = state  # type: ignore[attr-defined]
    server.expiry_stop = threading.Event()

    def expire_sessions() -> None:
        while not server.expiry_stop.wait(min(1.0, disconnect_timeout / 4)):
            state.expire_offline()

    server.expiry_thread = threading.Thread(target=expire_sessions, daemon=True)
    server.expiry_thread.start()
    return server


class RemoteRequestHandler(BaseHTTPRequestHandler):
    hub_state: RemoteHubState

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/":
            self._write_html(files("ui").joinpath("spectator.html").read_bytes())
        elif parsed.path == "/api/spectator/matches":
            pair_id = parse_qs(parsed.query).get("pair_id", [None])[0]
            self._write_json({"ok": True, "matches": self.hub_state.spectator_matches(pair_id=pair_id, recent_only=pair_id is None)})
        elif parsed.path == "/api/spectator/tournaments":
            self._write_json({"ok": True, "tournaments": self.hub_state.spectator_tournaments(), "server_time": time.time()})
        elif self.path == "/health":
            self._write_json({"ok": True})
        elif self.path == "/api/bots":
            self._write_json({"ok": True, "bots": self.hub_state.list_bots()})
        elif self.path == "/api/matches/ongoing":
            self._write_json({"ok": True, "matches": self.hub_state.list_series()})
        else:
            self._write_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/api/register":
                response = {"ok": True, **self.hub_state.register(str(payload.get("name", "")), bool(payload.get("heartbeat", False)))}
            elif self.path == "/api/resume":
                response = {"ok": True, **self.hub_state.resume(str(payload["bot_id"]), str(payload["token"]))}
            elif self.path == "/api/heartbeat":
                self.hub_state.heartbeat(str(payload["bot_id"]), str(payload["token"]), str(payload["connection_id"]))
                response = {"ok": True}
            elif self.path == "/api/poll":
                task = self.hub_state.poll(str(payload["bot_id"]), str(payload["token"]), float(payload.get("timeout", 20.0)), payload.get("connection_id"))
                response = {"ok": True, "task": task}
            elif self.path == "/api/respond":
                self.hub_state.respond(str(payload["bot_id"]), str(payload["token"]), dict(payload["response"]), payload.get("connection_id"))
                response = {"ok": True}
            elif self.path == "/api/matches":
                try:
                    response = {"ok": True, "reports": _run_remote_matches(self.hub_state, payload), "stopped": False}
                except RemoteSeriesStopped as exc:
                    response = {"ok": True, "reports": exc.reports, "stopped": True, "stop_reason": exc.reason}
            elif self.path == "/api/tournaments":
                tournament_id = self.hub_state.create_tournament(dict(payload["entrants"]), int(payload["seed"]))
                response = {"ok": True, "tournament_id": tournament_id}
            elif self.path == "/api/tournaments/update":
                self.hub_state.update_tournament(str(payload["tournament_id"]), dict(payload["event"]))
                response = {"ok": True}
            elif self.path == "/api/matches/stop":
                response = {"ok": True, **self.hub_state.stop_series(str(payload["id"]))}
            elif self.path == "/api/bots/unregister":
                response = {"ok": True, **self.hub_state.unregister(str(payload["id"]))}
            else:
                self._write_json({"ok": False, "error": "not found"}, status=404)
                return
            self._write_json(response)
        except Exception as exc:
            self._write_json({"ok": False, "error": str(exc)}, status=400)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length) if length else b"{}"
        return json.loads(data.decode("utf-8"))

    def _write_html(self, data: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _write_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_remote_server(host: str = "0.0.0.0", port: int = 8765, action_timeout: float = PLACEMENT_TIMEOUT_SECONDS,
                      disconnect_timeout: float = 15.0, hide_ships: bool = False) -> None:
    server = create_remote_server(host, port, action_timeout, disconnect_timeout, hide_ships)
    print(f"remote server listening on http://{host}:{server.server_port}", flush=True)
    print(f"watch matches on this laptop at http://localhost:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def run_remote_client(
    server_url: str, bot_spec: str, name: str, seed: int | None = None, poll_timeout: float = 20.0,
    session_file: str | Path | None = None, heartbeat_interval: float = 5.0,
) -> None:
    session_file = session_file or default_session_file(server_url, name)
    client = RemoteBotClient(server_url, bot_spec, name, seed, poll_timeout, session_file, heartbeat_interval)
    registration = client.register()
    verb = "reconnected" if registration["resumed"] else "registered"
    print(f"{verb} {registration['name']} as {registration['bot_id']}", flush=True)
    try:
        client.run_forever()
    except KeyboardInterrupt:
        pass


def list_remote_bots(server_url: str) -> list[dict]:
    return _get_json(server_url.rstrip("/"), "/api/bots")["bots"]


def list_ongoing_remote_matches(server_url: str) -> list[dict]:
    return _get_json(server_url.rstrip("/"), "/api/matches/ongoing")["matches"]


def stop_remote_match(server_url: str, match_id: str) -> dict:
    return _post_json(server_url.rstrip("/"), "/api/matches/stop", {"id": match_id})


def unregister_remote_bot(server_url: str, bot_id: str) -> dict:
    return _post_json(server_url.rstrip("/"), "/api/bots/unregister", {"id": bot_id})


def run_remote_match_request(server_url: str, bot_a: str, bot_b: str, games: int, seed: int) -> dict:
    payload = {"bot_a": bot_a, "bot_b": bot_b, "games": games, "seed": seed}
    return _post_json(server_url.rstrip("/"), "/api/matches", payload, timeout=None)


def run_remote_tournament_series(server_url: str, bot_a: str, bot_b: str, seed: int, memory_dir: str,
                                 tournament_id: str | None = None, pair_id: str | None = None) -> dict:
    return _post_json(server_url.rstrip("/"), "/api/matches", {
        "bot_a": bot_a, "bot_b": bot_b, "games": TOURNAMENT_MAX_GAMES, "seed": seed, "best_of": True,
        "random_first": True, "memory_dir": memory_dir, "lifecycle": True,
        "tournament_id": tournament_id, "pair_id": pair_id,
    }, timeout=None)


def create_remote_tournament(server_url: str, entrants: dict[str, str], seed: int) -> str:
    return _post_json(server_url.rstrip("/"), "/api/tournaments", {"entrants": entrants, "seed": seed})["tournament_id"]


def update_remote_tournament(server_url: str, tournament_id: str, event: dict) -> None:
    _post_json(server_url.rstrip("/"), "/api/tournaments/update", {"tournament_id": tournament_id, "event": event})


def get_remote_tournament(server_url: str, tournament_id: str) -> dict:
    tournaments = _get_json(server_url.rstrip("/"), "/api/spectator/tournaments")["tournaments"]
    tournament = next((item for item in tournaments if item["id"] == tournament_id), None)
    if tournament is None:
        raise RemoteError("unknown tournament")
    return tournament


def run_remote_matches(server_url: str, bot_a: str, bot_b: str, games: int, seed: int) -> list[dict]:
    return run_remote_match_request(server_url, bot_a, bot_b, games, seed)["reports"]


def _run_remote_matches(state: RemoteHubState, payload: dict) -> list[dict]:
    rules = official_rules()
    rng = random.Random(int(payload.get("seed", 123)))
    games = TOURNAMENT_MAX_GAMES if payload.get("tournament_id") is not None else max(1, int(payload.get("games", 1)))
    bot_a_id = state.resolve_bot(str(payload["bot_a"]))
    bot_b_id = state.resolve_bot(str(payload["bot_b"]))
    wins_needed = games // 2 + 1 if payload.get("best_of") or payload.get("tournament_id") is not None else None
    series_id = state.start_series(bot_a_id, bot_b_id, games, exclusive=bool(payload.get("lifecycle")),
                                   tournament_id=payload.get("tournament_id"), pair_id=payload.get("pair_id"),
                                   wins_needed=wins_needed)
    reason = None
    try:
        return _run_remote_series(state, payload, rules, rng, games, bot_a_id, bot_b_id, series_id)
    except Exception as exc:
        reason = str(exc)
        raise
    finally:
        state.end_series(series_id, reason)


def _run_remote_series(
    state: RemoteHubState, payload: dict, rules: Rules, rng: random.Random, games: int,
    bot_a_id: str, bot_b_id: str, series_id: str,
) -> list[dict]:
    reports = []
    with state.lock:
        series = state.ongoing_series[series_id]
        name_a, name_b = series["bot_a"], series["bot_b"]
    forfeit_bot_id = None
    if payload.get("tournament_id") is not None:
        for bot_id, other_id in ((bot_a_id, bot_b_id), (bot_b_id, bot_a_id)):
            with state.lock:
                bot = state.bots.get(bot_id)
                available = bool(bot and bot.online and bot.ready)
            if not available and not state.wait_for_tournament_player(series_id, bot_id, TOURNAMENT_RECONNECT_SECONDS):
                with state.lock:
                    other = state.bots.get(other_id)
                    if other is None or not other.online or not other.ready:
                        raise RemoteSeriesStopped(reports, "both players are unavailable")
                forfeit_bot_id = bot_id
                break
    for game in range(games):
        with state.lock:
            if _series_finished(state.ongoing_series[series_id]):
                break
        match_id = f"remote-{game}-{rng.randrange(2**32):08x}"
        flipped = bool(payload.get("random_first") and rng.randrange(2))
        first_id, second_id = (bot_b_id, bot_a_id) if flipped else (bot_a_id, bot_b_id)
        lifecycle = bool(payload.get("lifecycle"))
        agent_a = RemoteServerAgent(state, first_id, match_id, Player.A, rules, series_id, lifecycle)
        agent_b = RemoteServerAgent(state, second_id, match_id, Player.B, rules, series_id, lifecycle)
        first_name, second_name = (name_b, name_a) if flipped else (name_a, name_b)
        try:
            spectator_id = state.start_spectating(
                match_id, first_name if lifecycle else str(payload["bot_a"]),
                second_name if lifecycle else str(payload["bot_b"]), rules, series_id, game + 1, flipped
            )
        except RemoteSeriesStopped as exc:
            raise RemoteSeriesStopped(reports, exc.reason) from None
        if forfeit_bot_id is not None:
            winner = Player.B if first_id == forfeit_bot_id else Player.A
            reason = f"player {name_a if forfeit_bot_id == bot_a_id else name_b!r} did not reconnect within 30 seconds"
            stop_reason = state.finish_spectating(spectator_id, winner.value, reason)
            if stop_reason:
                raise RemoteSeriesStopped(reports, stop_reason)
            reports.append({"match_id": match_id, "game": game, "bot_a": first_id, "bot_b": second_id,
                            "winner": winner.value, "winner_bot": second_id if winner is Player.B else first_id,
                            "reason": reason, "turns": 0, "a_remaining": rules.thinking_seconds,
                            "b_remaining": rules.thinking_seconds})
            continue
        try:
            report = LocalRunner(
                rules,
                minimum_move_seconds=REMOTE_MINIMUM_MOVE_SECONDS,
                agents_enforce_timeouts=True,
                memory_dir=payload.get("memory_dir") if lifecycle else None,
                on_shot=lambda result: state.record_shot(spectator_id, result),
                on_placement=lambda player, fleet: state.record_placement(spectator_id, player, fleet),
            ).run(
                agent_a, agent_b, match_id=match_id,
                bot_a_name=first_name if lifecycle else "A", bot_b_name=second_name if lifecycle else "B",
                memory_a_name=first_id if lifecycle else None, memory_b_name=second_id if lifecycle else None,
            )
        except Exception as exc:
            stop_reason = state.finish_spectating(spectator_id, None, f"match failed: {exc}")
            if stop_reason:
                raise RemoteSeriesStopped(reports, stop_reason) from None
            raise
        stop_reason = state.finish_spectating(spectator_id, report.winner.value, report.reason)
        if stop_reason:
            raise RemoteSeriesStopped(reports, stop_reason)
        if report.reason != "all ships sunk":
            print(
                f"{match_id}: winner={report.winner.value} reason={report.reason} turns={report.turns}",
                flush=True,
            )
        reports.append(
            {
                "match_id": report.match_id,
                "game": game,
                "bot_a": first_id if lifecycle else payload["bot_a"],
                "bot_b": second_id if lifecycle else payload["bot_b"],
                "winner": report.winner.value,
                "winner_bot": (first_id if report.winner is Player.A else second_id) if lifecycle else (payload["bot_a"] if report.winner is Player.A else payload["bot_b"]),
                "reason": report.reason,
                "turns": report.turns,
                "a_remaining": round(report.remaining[Player.A], 6),
                "b_remaining": round(report.remaining[Player.B], 6),
            }
        )
        if lifecycle and payload.get("tournament_id") is not None and game + 1 < games and not _series_finished(series):
            with state.lock:
                series = state.ongoing_series[series_id]
                affected = [bot_id for bot_id in (bot_a_id, bot_b_id)
                            if bot_id in series["interrupted_bots"] or bot_id == series["timed_out_bot_id"]
                            or bot_id not in state.bots or not state.bots[bot_id].online or not state.bots[bot_id].ready]
            for bot_id in affected:
                try:
                    returned = state.wait_for_tournament_player(series_id, bot_id, TOURNAMENT_RECONNECT_SECONDS)
                except RemoteSeriesStopped as exc:
                    raise RemoteSeriesStopped(reports, exc.reason) from None
                if not returned:
                    other_id = bot_b_id if bot_id == bot_a_id else bot_a_id
                    with state.lock:
                        other = state.bots.get(other_id)
                        if other is None or not other.online or not other.ready:
                            raise RemoteSeriesStopped(reports, "both players are unavailable")
                    forfeit_bot_id = bot_id
                    break
            with state.lock:
                series["interrupted_bots"].clear()
                series["timed_out_bot_id"] = None
    return reports


def _post_json(server_url: str, path: str, payload: dict, timeout: float | None = 30.0) -> dict:
    request = urllib.request.Request(
        server_url + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        result = json.loads(exc.read().decode("utf-8"))
    if not result.get("ok"):
        raise RemoteError(str(result.get("error", "remote request failed")))
    return result


def _get_json(server_url: str, path: str, timeout: float = 30.0) -> dict:
    with urllib.request.urlopen(server_url + path, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RemoteError(str(result.get("error", "remote request failed")))
    return result


def _rules_to_payload(rules: Rules) -> dict:
    return {
        "rows": rules.rows,
        "cols": rules.cols,
        "fleet": list(rules.fleet),
        "thinking_seconds": rules.thinking_seconds,
        "placement_seconds": rules.placement_seconds,
        "protocol_version": rules.protocol_version,
    }


def _rules_from_payload(payload: dict) -> Rules:
    if not payload:
        return official_rules()
    return Rules(
        rows=int(payload.get("rows", 10)),
        cols=int(payload.get("cols", 10)),
        fleet=tuple(int(length) for length in payload.get("fleet", (5, 4, 3, 3, 2))),
        thinking_seconds=float(payload.get("thinking_seconds", official_rules().thinking_seconds)),
        protocol_version=int(payload.get("protocol_version", 1)),
        placement_seconds=float(payload.get("placement_seconds", official_rules().placement_seconds)),
    )


def _match_seed(seed: int | None, match_id: str) -> int | None:
    if seed is None:
        return None
    checksum = zlib.crc32(match_id.encode("utf-8"))
    return (int(seed) ^ checksum) & 0xFFFFFFFF

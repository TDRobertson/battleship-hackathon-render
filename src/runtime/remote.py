from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

from agent import Agent
from core.models import Coord, Player, ShipPlacement
from core.rules import Rules, official_rules
from runtime.bot_loading import build_bot
from runtime.runner import LocalRunner
from sdk.observation import ObservationSnapshot, ObservationState


class RemoteError(RuntimeError):
    pass


@dataclass(slots=True)
class RemoteBotSession:
    bot_id: str
    name: str
    token: str
    tasks: list[dict] = field(default_factory=list)
    responses: dict[str, dict] = field(default_factory=dict)
    last_seen: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class RemoteHubState:
    action_timeout: float = 130.0
    bots: dict[str, RemoteBotSession] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)
    changed: threading.Condition = field(init=False)

    def __post_init__(self) -> None:
        self.changed = threading.Condition(self.lock)

    def register(self, name: str) -> dict:
        bot_id = uuid4().hex
        token = uuid4().hex
        with self.changed:
            self.bots[bot_id] = RemoteBotSession(bot_id, name.strip() or bot_id, token)
            self.changed.notify_all()
        return {"bot_id": bot_id, "token": token, "name": self.bots[bot_id].name}

    def list_bots(self) -> list[dict]:
        now = time.monotonic()
        with self.lock:
            return [
                {
                    "bot_id": bot.bot_id,
                    "name": bot.name,
                    "queued": len(bot.tasks),
                    "seconds_since_seen": round(now - bot.last_seen, 3),
                }
                for bot in self.bots.values()
            ]

    def poll(self, bot_id: str, token: str, timeout: float) -> dict | None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self.changed:
            bot = self._require_bot(bot_id, token)
            bot.last_seen = time.monotonic()
            while not bot.tasks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.changed.wait(remaining)
                bot = self._require_bot(bot_id, token)
                bot.last_seen = time.monotonic()
            return bot.tasks.pop(0)

    def respond(self, bot_id: str, token: str, response: dict) -> None:
        action_id = str(response.get("action_id", ""))
        if not action_id:
            raise RemoteError("response is missing action_id")
        with self.changed:
            bot = self._require_bot(bot_id, token)
            bot.last_seen = time.monotonic()
            bot.responses[action_id] = response
            self.changed.notify_all()

    def request_action(self, bot_id: str, task: dict, timeout: float) -> dict:
        action_id = str(task["action_id"])
        deadline = time.monotonic() + max(0.0, timeout)
        with self.changed:
            bot = self._require_bot(bot_id)
            bot.tasks.append(task)
            self.changed.notify_all()
            while action_id not in bot.responses:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RemoteError(f"timed out waiting for remote bot {bot.name!r}")
                self.changed.wait(remaining)
            response = bot.responses.pop(action_id)
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


@dataclass
class RemoteServerAgent(Agent):
    state: RemoteHubState
    bot_id: str
    match_id: str
    player: Player
    rules: Rules = field(default_factory=official_rules)

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
        timeout = min(self.state.action_timeout, max(1.0, float(time_remaining) + 2.0))
        return self.state.request_action(self.bot_id, payload, timeout)


class RemoteBotClient:
    def __init__(
        self,
        server_url: str,
        bot_spec: str,
        name: str,
        seed: int | None = None,
        poll_timeout: float = 20.0,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.bot_spec = bot_spec
        self.name = name
        self.seed = seed
        self.poll_timeout = poll_timeout
        self.bot_id: str | None = None
        self.token: str | None = None
        self.bot: Agent | None = None
        self.match_id: str | None = None

    def register(self) -> dict:
        payload = _post_json(self.server_url, "/api/register", {"name": self.name})
        self.bot_id = str(payload["bot_id"])
        self.token = str(payload["token"])
        self.name = str(payload["name"])
        return payload

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        if self.bot_id is None or self.token is None:
            self.register()
        while stop_event is None or not stop_event.is_set():
            try:
                task = self.poll_once()
            except (OSError, RemoteError, urllib.error.URLError):
                if stop_event is not None and stop_event.is_set():
                    break
                time.sleep(0.25)
                continue
            if task is not None:
                self.respond_to(task)

    def poll_once(self) -> dict | None:
        self._require_registered()
        payload = _post_json(
            self.server_url,
            "/api/poll",
            {"bot_id": self.bot_id, "token": self.token, "timeout": self.poll_timeout},
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
            {"bot_id": self.bot_id, "token": self.token, "response": response},
        )

    def _handle_task(self, task: dict) -> dict:
        action_id = task.get("action_id")
        rules = _rules_from_payload(task.get("rules", {}))
        if task.get("type") == "place_ships":
            bot = self._bot_for_match(str(task.get("match_id", "")))
            placements = bot.place_ships(rules, float(task["time_remaining"]))
            return {"ok": True, "action_id": action_id, "placements": [asdict(p) for p in placements]}
        if task.get("type") == "choose_shot":
            bot = self._bot_for_match(str(task.get("match_id", "")))
            observation = ObservationState.from_lists(task["observation"], rules).snapshot()
            shot = bot.choose_shot(observation, float(task["time_remaining"]))
            return {"ok": True, "action_id": action_id, "shot": [int(shot[0]), int(shot[1])]}
        return {"ok": False, "action_id": action_id, "error": "unknown task type"}

    def _bot_for_match(self, match_id: str) -> Agent:
        if self.bot is None or match_id != self.match_id:
            self.match_id = match_id
            self.bot = build_bot(self.bot_spec, _match_seed(self.seed, match_id))
        return self.bot

    def _require_registered(self) -> None:
        if self.bot_id is None or self.token is None:
            raise RemoteError("client is not registered")


def create_remote_server(host: str = "0.0.0.0", port: int = 8765, action_timeout: float = 130.0) -> ThreadingHTTPServer:
    state = RemoteHubState(action_timeout=action_timeout)

    class Handler(RemoteRequestHandler):
        hub_state = state

    server = ThreadingHTTPServer((host, port), Handler)
    server.hub_state = state  # type: ignore[attr-defined]
    return server


class RemoteRequestHandler(BaseHTTPRequestHandler):
    hub_state: RemoteHubState

    def do_GET(self) -> None:
        if self.path == "/health":
            self._write_json({"ok": True})
        elif self.path == "/api/bots":
            self._write_json({"ok": True, "bots": self.hub_state.list_bots()})
        else:
            self._write_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/api/register":
                response = {"ok": True, **self.hub_state.register(str(payload.get("name", "")))}
            elif self.path == "/api/poll":
                task = self.hub_state.poll(str(payload["bot_id"]), str(payload["token"]), float(payload.get("timeout", 20.0)))
                response = {"ok": True, "task": task}
            elif self.path == "/api/respond":
                self.hub_state.respond(str(payload["bot_id"]), str(payload["token"]), dict(payload["response"]))
                response = {"ok": True}
            elif self.path == "/api/matches":
                response = {"ok": True, "reports": _run_remote_matches(self.hub_state, payload)}
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

    def _write_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_remote_server(host: str = "0.0.0.0", port: int = 8765, action_timeout: float = 130.0) -> None:
    server = create_remote_server(host, port, action_timeout)
    print(f"remote server listening on http://{host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def run_remote_client(server_url: str, bot_spec: str, name: str, seed: int | None = None, poll_timeout: float = 20.0) -> None:
    client = RemoteBotClient(server_url, bot_spec, name, seed, poll_timeout)
    registration = client.register()
    print(f"registered {registration['name']} as {registration['bot_id']}", flush=True)
    try:
        client.run_forever()
    except KeyboardInterrupt:
        pass


def list_remote_bots(server_url: str) -> list[dict]:
    return _get_json(server_url.rstrip("/"), "/api/bots")["bots"]


def run_remote_matches(server_url: str, bot_a: str, bot_b: str, games: int, seed: int) -> list[dict]:
    payload = {"bot_a": bot_a, "bot_b": bot_b, "games": games, "seed": seed}
    return _post_json(server_url.rstrip("/"), "/api/matches", payload, timeout=None)["reports"]


def _run_remote_matches(state: RemoteHubState, payload: dict) -> list[dict]:
    rules = official_rules()
    rng = random.Random(int(payload.get("seed", 123)))
    games = max(1, int(payload.get("games", 1)))
    bot_a_id = state.resolve_bot(str(payload["bot_a"]))
    bot_b_id = state.resolve_bot(str(payload["bot_b"]))
    reports = []
    for game in range(games):
        match_id = f"remote-{game}-{rng.randrange(2**32):08x}"
        agent_a = RemoteServerAgent(state, bot_a_id, match_id, Player.A, rules)
        agent_b = RemoteServerAgent(state, bot_b_id, match_id, Player.B, rules)
        report = LocalRunner(rules).run(agent_a, agent_b, match_id=match_id)
        reports.append(
            {
                "match_id": report.match_id,
                "game": game,
                "bot_a": payload["bot_a"],
                "bot_b": payload["bot_b"],
                "winner": report.winner.value,
                "winner_bot": payload["bot_a"] if report.winner is Player.A else payload["bot_b"],
                "reason": report.reason,
                "turns": report.turns,
                "a_remaining": round(report.remaining[Player.A], 6),
                "b_remaining": round(report.remaining[Player.B], 6),
            }
        )
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
        "protocol_version": rules.protocol_version,
    }


def _rules_from_payload(payload: dict) -> Rules:
    if not payload:
        return official_rules()
    return Rules(
        rows=int(payload.get("rows", 10)),
        cols=int(payload.get("cols", 10)),
        fleet=tuple(int(length) for length in payload.get("fleet", (5, 4, 3, 3, 2))),
        thinking_seconds=float(payload.get("thinking_seconds", 120.0)),
        protocol_version=int(payload.get("protocol_version", 1)),
    )


def _match_seed(seed: int | None, match_id: str) -> int | None:
    if seed is None:
        return None
    checksum = zlib.crc32(match_id.encode("utf-8"))
    return (int(seed) ^ checksum) & 0xFFFFFFFF

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from agent import MatchContext, MatchEnd
from core.models import Outcome, Player, PublicShotResult, SunkShip
from sdk.observation import ObservationState
from core.rules import Rules
from runtime.bot_loading import build_bot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m runtime.worker")
    parser.add_argument("--bot", default="starter")
    parser.add_argument("--seed", type=int, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    bot = build_bot(args.bot, args.seed)
    rules = Rules()
    context: MatchContext | None = None
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if message["type"] == "start_match":
                payload = message["context"]
                context = MatchContext(
                    match_id=str(payload["match_id"]),
                    player=Player(str(payload["player"])),
                    bot_name=str(payload["bot_name"]),
                    opponent_name=str(payload["opponent_name"]),
                    memory=dict(payload.get("memory", {})),
                )
                bot.start_match(context)
                response = {"ok": True, "action_id": message.get("action_id"), "memory": context.memory}
            elif message["type"] == "place_ships":
                placements = bot.place_ships(rules, float(message["time_remaining"]))
                response = {"ok": True, "placements": [asdict(p) for p in placements], "action_id": message.get("action_id")}
            elif message["type"] == "choose_shot":
                obs = ObservationState.from_lists(message["observation"], rules).snapshot()
                shot = bot.choose_shot(obs, float(message["time_remaining"]))
                response = {"ok": True, "shot": list(shot), "action_id": message.get("action_id")}
            elif message["type"] == "observe_opponent_shot":
                bot.observe_opponent_shot(_public_result_from_payload(message["result"]), float(message["time_remaining"]))
                response = {"ok": True, "action_id": message.get("action_id")}
            elif message["type"] == "end_match":
                result = message["result"]
                if context is not None and isinstance(message.get("memory"), dict):
                    context.memory.clear()
                    context.memory.update(message["memory"])
                bot.end_match(
                    MatchEnd(
                        won=bool(result["won"]),
                        winner=Player(str(result["winner"])),
                        reason=str(result["reason"]),
                        turns=int(result["turns"]),
                    )
                )
                response = {"ok": True, "action_id": message.get("action_id")}
            else:
                response = {"ok": False, "error": "unknown message type"}
            if context is not None and response.get("ok"):
                response["memory"] = context.memory
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        print(json.dumps(response, default=str), flush=True)
    return 0


def _public_result_from_payload(payload: dict) -> PublicShotResult:
    sunk_payload = payload.get("sunk_ship")
    sunk_ship = None
    if sunk_payload is not None:
        sunk_ship = SunkShip(
            int(sunk_payload["slot"]),
            tuple((int(row), int(col)) for row, col in sunk_payload["cells"]),
        )
    row, col = payload["shot"]
    return PublicShotResult((int(row), int(col)), Outcome(str(payload["outcome"])), sunk_ship)


if __name__ == "__main__":
    raise SystemExit(main())

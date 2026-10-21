from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

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
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if message["type"] == "place_ships":
                placements = bot.place_ships(rules, float(message["time_remaining"]))
                response = {"ok": True, "placements": [asdict(p) for p in placements], "action_id": message.get("action_id")}
            elif message["type"] == "choose_shot":
                obs = ObservationState.from_lists(message["observation"], rules).snapshot()
                shot = bot.choose_shot(obs, float(message["time_remaining"]))
                response = {"ok": True, "shot": list(shot), "action_id": message.get("action_id")}
            else:
                response = {"ok": False, "error": "unknown message type"}
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        print(json.dumps(response), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

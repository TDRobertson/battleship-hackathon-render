"""Record one Battleship match to a replay JSON file for the 3D viewer.

Run from the repository root:

    python scripts/export_replay.py --bot-a hunt-target --bot-b hunt-target --seed 7
    python scripts/export_replay.py --bot-a max_bot:MaxAgent --bot-b arush_bot:ArushAgent \
        --name-a Max --name-b Arush --out viewer/replay.json

Bot specs work exactly as in `battleship simulate`: a built-in name or
`module:Class`. The match runs in-process through the normal LocalRunner, so
the engine stays authoritative; this script only listens to its spectator hooks.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))  # so bot files dropped in the repo root import

from core.models import Player, ShotResult  # noqa: E402
from core.rules import official_rules  # noqa: E402
from runtime.bot_loading import build_bot  # noqa: E402
from runtime.runner import LocalRunner  # noqa: E402


def record_match(bot_a: str, bot_b: str, seed: int, name_a: str, name_b: str) -> dict:
    rules = official_rules()
    rng = random.Random(seed)
    seed_a, seed_b = rng.randrange(2**32), rng.randrange(2**32)
    placements: dict[str, list[dict]] = {}
    shots: list[dict] = []

    def on_placement(player: Player, fleet: dict[int, tuple[tuple[int, int], ...]]) -> None:
        placements[player.value] = [
            {"slot": slot, "length": len(cells), "cells": [list(cell) for cell in cells]}
            for slot, cells in sorted(fleet.items())
        ]

    def on_shot(result: ShotResult) -> None:
        shots.append({
            "turn": len(shots) + 1,
            "player": result.player.value,
            "row": result.shot[0],
            "col": result.shot[1],
            "outcome": result.outcome.value,
            "sunk": None if result.sunk_ship is None else {
                "slot": result.sunk_ship.slot,
                "cells": [list(cell) for cell in result.sunk_ship.cells],
            },
        })

    runner = LocalRunner(rules=rules, on_shot=on_shot, on_placement=on_placement)
    report = runner.run(
        build_bot(bot_a, seed_a), build_bot(bot_b, seed_b),
        match_id=f"replay-{seed}", bot_a_name=name_a, bot_b_name=name_b,
    )
    return {
        "version": 1,
        "seed": seed,
        "rules": {"rows": rules.rows, "cols": rules.cols, "fleet": list(rules.fleet)},
        "players": {"A": {"name": name_a, "bot": bot_a}, "B": {"name": name_b, "bot": bot_b}},
        "placements": placements,
        "shots": shots,
        "winner": report.winner.value,
        "reason": report.reason,
        "turns": report.turns,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record one match as a replay JSON for the 3D viewer.")
    parser.add_argument("--bot-a", default="hunt-target")
    parser.add_argument("--bot-b", default="hunt-target")
    parser.add_argument("--name-a", default=None, help="display name for player A (defaults to the bot spec)")
    parser.add_argument("--name-b", default=None, help="display name for player B (defaults to the bot spec)")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", default="viewer/replay.json")
    args = parser.parse_args(argv)

    replay = record_match(args.bot_a, args.bot_b, args.seed, args.name_a or args.bot_a, args.name_b or args.bot_b)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(replay)
    out.write_text(payload, encoding="utf-8")
    # The viewer loads this sibling .js file so it also works when opened straight from disk.
    out.with_suffix(".js").write_text(f"window.REPLAY = {payload};\n", encoding="utf-8")
    winner = replay["players"][replay["winner"]]["name"]
    print(f"{out}: {replay['turns']} shots, winner {winner} ({replay['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Record one Battleship match to a replay JSON file for the 3D viewer.

Run from the repository root:

    python scripts/export_replay.py --bot-a hunt-target --bot-b hunt-target --seed 7
    python scripts/export_replay.py --bot-a max_bot:MaxAgent --bot-b arush_bot:ArushAgent \
        --name-a Max --name-b Arush --out viewer/replay.json

Bot specs work exactly as in `battleship simulate`: a built-in name or
`module:Class`. The match runs in-process through the normal LocalRunner, so
the engine stays authoritative; this script only listens to its spectator hooks.

"AI view" heatmaps
------------------
Each shot is saved with a heatmap of where the shooting bot expects ships, which
the viewer can overlay on the enemy grid. There are two sources:

* The bot's own scores. If a bot defines `debug_heatmap()` returning a
  rows x cols array of scores for the decision it just made (any scale, higher
  means more likely to shoot there), that is recorded. A neural-network bot can
  return its output map here.
* An estimate. Otherwise the kit's fleet-sampling helper computes, from exactly
  what that bot has observed so far, how likely each untried cell is to hold a
  ship. This is what a careful player would believe, not necessarily how the bot
  reasons.

Use --search N to play N seeds and keep the closest finish.
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

import numpy as np  # noqa: E402

from agent import Agent  # noqa: E402
from core.models import Player, ShotResult  # noqa: E402
from core.rules import official_rules  # noqa: E402
from runtime.bot_loading import build_bot  # noqa: E402
from runtime.runner import LocalRunner  # noqa: E402
from sdk.inference import occupancy_heatmap  # noqa: E402


class Recorder(Agent):
    """Wraps a bot to note what it saw before each shot, without changing its decisions.

    Only cheap bookkeeping happens inside the bot's timed turn; the heatmaps are
    worked out after the match so they cannot cause a timeout.
    """

    def __init__(self, inner: Agent) -> None:
        self.inner = inner
        self.seen: list = []      # observation before each shot
        self.own: list = []       # the bot's own scores for that shot, if it offers them

    def place_ships(self, rules, time_remaining):
        return self.inner.place_ships(rules, time_remaining)

    def choose_shot(self, observation, time_remaining):
        shot = self.inner.choose_shot(observation, time_remaining)
        self.seen.append(observation)
        scores = None
        hook = getattr(self.inner, "debug_heatmap", None)
        if callable(hook):
            try:
                scores = np.array(hook(), dtype=float)
            except Exception:
                scores = None
        self.own.append(scores)
        return shot

    def start_match(self, context):
        return self.inner.start_match(context)

    def observe_opponent_shot(self, result, time_remaining):
        return self.inner.observe_opponent_shot(result, time_remaining)

    def end_match(self, result):
        return self.inner.end_match(result)


def _digits(values: np.ndarray, open_cells: np.ndarray) -> str:
    """Scale scores over the cells still open to 0-9 and pack them row by row."""
    scores = np.where(open_cells, values, np.nan)
    if not np.isfinite(scores).any():
        return "0" * values.size
    low, high = np.nanmin(scores), np.nanmax(scores)
    span = high - low
    scaled = np.zeros(values.shape) if span <= 0 else (scores - low) / span
    scaled = np.where(open_cells, scaled, 0.0)
    return "".join(str(int(round(v * 9))) for v in scaled.flatten())


def heatmaps(rules, recorder: Recorder, seed: int) -> tuple[list[str], str]:
    """Return one packed heatmap per shot for a bot, and where the heatmaps came from."""
    shape = (rules.rows, rules.cols)
    from_bot = bool(recorder.own) and all(s is not None and s.shape == shape for s in recorder.own)
    packed = []
    for index, observation in enumerate(recorder.seen):
        open_cells = observation.available_shots()
        if from_bot:
            values = recorder.own[index]
        else:
            values = occupancy_heatmap(rules, observation, max_samples=400, rng=random.Random(seed * 1000 + index), time_limit=0.5)
        packed.append(_digits(np.asarray(values, dtype=float), open_cells))
    return packed, "bot" if from_bot else "estimate"


def record_match(bot_a: str, bot_b: str, seed: int, name_a: str, name_b: str, heat: bool = True) -> dict:
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

    runner = LocalRunner(rules=rules, on_shot=on_shot, on_placement=on_placement, memory_dir=None)
    recorders = {"A": Recorder(build_bot(bot_a, seed_a)), "B": Recorder(build_bot(bot_b, seed_b))}
    report = runner.run(
        recorders["A"], recorders["B"],
        match_id=f"replay-{seed}", bot_a_name=name_a, bot_b_name=name_b,
    )
    heat_source = None
    if heat:
        heat_source = {}
        per_player = {}
        for player, recorder in recorders.items():
            per_player[player], heat_source[player] = heatmaps(rules, recorder, seed)
        taken = {"A": 0, "B": 0}
        for shot in shots:
            maps = per_player[shot["player"]]
            if taken[shot["player"]] < len(maps):
                shot["heat"] = maps[taken[shot["player"]]]
            taken[shot["player"]] += 1
    return {
        "version": 2,
        "heat_source": heat_source,
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
    parser.add_argument("--search", type=int, default=1, metavar="N",
                        help="play N seeds starting at --seed and keep the closest finish")
    parser.add_argument("--no-heat", action="store_true", help="skip the AI-view heatmaps")
    args = parser.parse_args(argv)

    name_a, name_b = args.name_a or args.bot_a, args.name_b or args.bot_b
    seed = args.seed
    if args.search > 1:
        # Closest finish: the loser came nearest to sinking the winner's whole fleet.
        def margin(candidate: dict) -> int:
            loser = "B" if candidate["winner"] == "A" else "A"
            landed = sum(1 for shot in candidate["shots"] if shot["player"] == loser and shot["outcome"] != "miss")
            return sum(candidate["rules"]["fleet"]) - landed
        seed = min(range(args.seed, args.seed + args.search),
                   key=lambda s: margin(record_match(args.bot_a, args.bot_b, s, name_a, name_b, heat=False)))
        print(f"closest finish of {args.search} games: seed {seed}")
    replay = record_match(args.bot_a, args.bot_b, seed, name_a, name_b, heat=not args.no_heat)
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

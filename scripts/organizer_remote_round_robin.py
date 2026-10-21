from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run remote matches for every ordered bot pairing.")
    parser.add_argument("--server", required=True, help="remote server URL, such as http://192.168.1.20:8765")
    parser.add_argument("--bots-file", default="examples/bots.txt")
    parser.add_argument("--games", type=int, default=3, help="games per ordered pairing")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--results-dir", default="results/remote_round_robin")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bots = _read_bots(Path(args.bots_file))
    if len(bots) < 2:
        raise SystemExit("remote round robin requires at least two bots")

    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for bot_a in bots:
        for bot_b in bots:
            if bot_a == bot_b:
                continue
            csv_path = results_dir / f"{_safe_name(bot_a)}__vs__{_safe_name(bot_b)}.csv"
            command = [
                sys.executable,
                "-m",
                "app.cli",
                "remote-match",
                "--server",
                args.server,
                "--bot-a",
                bot_a,
                "--bot-b",
                bot_b,
                "--games",
                str(args.games),
                "--seed",
                str(args.seed),
                "--csv",
                str(csv_path),
            ]
            print(" ".join(command), flush=True)
            failures += subprocess.call(command) != 0
    return 1 if failures else 0


def _read_bots(path: Path) -> list[str]:
    bots = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            bots.append(stripped)
    return bots


def _safe_name(name: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in name)


if __name__ == "__main__":
    raise SystemExit(main())

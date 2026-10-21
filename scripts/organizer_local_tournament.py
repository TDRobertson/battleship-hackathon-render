from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local round-robin tournament.")
    parser.add_argument("--bots-file", default="examples/bots.txt")
    parser.add_argument("--games", type=int, default=10, help="games per ordered pairing")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--csv", default="results/local_tournament.csv")
    parser.add_argument("--no-process", action="store_true", help="run bots in-process instead of worker subprocesses")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "app.cli",
        "tournament",
        "--bots-file",
        args.bots_file,
        "--games",
        str(args.games),
        "--seed",
        str(args.seed),
        "--csv",
        args.csv,
    ]
    if not args.no_process:
        command.append("--process")
    print(" ".join(command), flush=True)
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())

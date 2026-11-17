from __future__ import annotations

import argparse
import subprocess
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the LAN remote-match server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--action-timeout", type=float, default=5.0)
    parser.add_argument("--disconnect-timeout", type=float, default=15.0)
    parser.add_argument("--hide-ships", action="store_true", help="hide unhit ships from spectators during games")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = [
        sys.executable,
        "-m",
        "app.cli",
        "remote-server",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--action-timeout",
        str(args.action_timeout),
        "--disconnect-timeout",
        str(args.disconnect_timeout),
    ]
    if args.hide_ships:
        command.append("--hide-ships")
    print(" ".join(command), flush=True)
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())

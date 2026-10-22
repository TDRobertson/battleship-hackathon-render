from __future__ import annotations

import argparse
import csv
import random
import shutil
from statistics import mean
from pathlib import Path

from core.models import Player
from runtime.bot_loading import available_bot_specs, build_bot
from runtime.process_agent import ProcessAgent
from runtime.remote import list_remote_bots, run_remote_client, run_remote_matches, run_remote_server
from runtime.runner import LocalRunner, MatchReport
from core.rules import official_rules
from sdk.observation import ObservationState
from ui.practice import new_practice_target, practice_fire


def simulate(args: argparse.Namespace) -> int:
    memory_dir = _prepare_memory_dir(args)
    rng = random.Random(args.seed)
    wins = {"A": 0, "B": 0}
    rows = []
    for index in range(args.games):
        seed_a = rng.randrange(2**32)
        seed_b = rng.randrange(2**32)
        report = _run_match(args.bot_a, args.bot_b, seed_a, seed_b, f"sim-{index}", args.process, memory_dir)
        wins[report.winner.value] += 1
        rows.append(_report_row(report, args.bot_a, args.bot_b, index, memory_dir=memory_dir))
        if args.verbose:
            print(f"{report.match_id}: winner={report.winner.value} reason={report.reason} turns={report.turns}")
    print(f"games={args.games} A={wins['A']} B={wins['B']} seed={args.seed}")
    if args.csv:
        _write_csv(Path(args.csv), rows)
    return 0


def tournament(args: argparse.Namespace) -> int:
    memory_dir = _prepare_memory_dir(args)
    bots = _tournament_bots(args)
    if len(bots) < 2:
        raise SystemExit("tournament requires at least two bots")

    rng = random.Random(args.seed)
    rows = []
    wins = {bot: 0 for bot in bots}
    games_played = {bot: 0 for bot in bots}
    match_index = 0
    for bot_a in bots:
        for bot_b in bots:
            if bot_a == bot_b and not args.include_mirrors:
                continue
            for game in range(args.games):
                seed_a = rng.randrange(2**32)
                seed_b = rng.randrange(2**32)
                report = _run_match(bot_a, bot_b, seed_a, seed_b, f"tournament-{match_index}", args.process, memory_dir)
                winner_spec = bot_a if report.winner is Player.A else bot_b
                wins[winner_spec] += 1
                games_played[bot_a] += 1
                games_played[bot_b] += 1
                rows.append(_report_row(report, bot_a, bot_b, game, pairing_id=match_index, memory_dir=memory_dir))
                match_index += 1

    for bot in sorted(bots, key=lambda spec: (-wins[spec], spec)):
        print(f"{bot}: wins={wins[bot]} games={games_played[bot]}")
    if args.csv:
        _write_csv(Path(args.csv), rows)
    return 0


def play(args: argparse.Namespace) -> int:
    from ui.pygame_app import run_app

    run_app(seed=args.seed, bot_name=args.bot, solo=args.solo)
    return 0


def benchmark(args: argparse.Namespace) -> int:
    bots = list(args.bot or [])
    if not bots:
        raise SystemExit("benchmark requires at least one --bot")

    rng = random.Random(args.seed)
    target_seeds = [rng.randrange(2**32) for _ in range(args.games)]
    rows = []

    for bot_index, bot_spec in enumerate(bots):
        shot_counts = []
        for game, target_seed in enumerate(target_seeds):
            bot_seed = _benchmark_bot_seed(args.seed, bot_index, game)
            shots = _run_target_benchmark_game(bot_spec, bot_seed, target_seed)
            shot_counts.append(shots)
            rows.append(
                {
                    "bot": bot_spec,
                    "game": game,
                    "shots": shots,
                    "bot_seed": bot_seed,
                    "target_seed": target_seed,
                }
            )
            if args.verbose:
                print(f"{bot_spec} game={game} shots={shots} target_seed={target_seed}")
        print(
            f"{bot_spec}: games={args.games} avg_shots={mean(shot_counts):.2f} "
            f"min={min(shot_counts)} max={max(shot_counts)} seed={args.seed}"
        )

    if args.csv:
        _write_csv(Path(args.csv), rows)
    return 0


def remote_server(args: argparse.Namespace) -> int:
    run_remote_server(args.host, args.port, args.action_timeout)
    return 0


def remote_client(args: argparse.Namespace) -> int:
    run_remote_client(args.server, args.bot, args.name, args.seed, args.poll_timeout)
    return 0


def remote_list(args: argparse.Namespace) -> int:
    bots = list_remote_bots(args.server)
    if not bots:
        print("no remote bots connected")
        return 0
    for bot in bots:
        print(
            f"{bot['name']} id={bot['bot_id']} queued={bot['queued']} "
            f"last_seen={bot['seconds_since_seen']}s"
        )
    return 0


def remote_match(args: argparse.Namespace) -> int:
    reports = run_remote_matches(args.server, args.bot_a, args.bot_b, args.games, args.seed)
    wins = {args.bot_a: 0, args.bot_b: 0}
    for report in reports:
        wins[report["winner_bot"]] = wins.get(report["winner_bot"], 0) + 1
        if args.verbose:
            print(
                f"{report['match_id']}: winner={report['winner']} "
                f"winner_bot={report['winner_bot']} reason={report['reason']} turns={report['turns']}"
            )
    print(f"games={len(reports)} {args.bot_a}={wins.get(args.bot_a, 0)} {args.bot_b}={wins.get(args.bot_b, 0)} seed={args.seed}")
    if args.csv:
        _write_csv(Path(args.csv), reports)
    return 0


def _run_match(
    bot_a_spec: str,
    bot_b_spec: str,
    seed_a: int,
    seed_b: int,
    match_id: str,
    process: bool,
    memory_dir: Path | None = None,
) -> MatchReport:
    if process:
        with ProcessAgent(seed_a, bot_a_spec) as bot_a, ProcessAgent(seed_b, bot_b_spec) as bot_b:
            return LocalRunner(official_rules(), memory_dir=memory_dir).run(
                bot_a,
                bot_b,
                match_id=match_id,
                bot_a_name=bot_a_spec,
                bot_b_name=bot_b_spec,
            )
    bot_a = build_bot(bot_a_spec, seed_a)
    bot_b = build_bot(bot_b_spec, seed_b)
    return LocalRunner(official_rules(), memory_dir=memory_dir).run(
        bot_a,
        bot_b,
        match_id=match_id,
        bot_a_name=bot_a_spec,
        bot_b_name=bot_b_spec,
    )


def _run_target_benchmark_game(bot_spec: str, bot_seed: int, target_seed: int) -> int:
    rules = official_rules()
    bot = build_bot(bot_spec, bot_seed)
    bot.place_ships(rules, rules.thinking_seconds)
    target = new_practice_target(rules, random.Random(target_seed))
    observation = ObservationState(rules)
    shots = 0
    max_shots = rules.rows * rules.cols
    while not target.all_sunk and shots < max_shots:
        snapshot = observation.snapshot()
        shot = bot.choose_shot(snapshot, rules.thinking_seconds)
        row, col = int(shot[0]), int(shot[1])
        if not snapshot.available_shots()[row, col]:
            raise RuntimeError(f"{bot_spec} chose illegal benchmark shot {(row, col)}")
        practice_fire(target, observation, (row, col))
        shots += 1
    if not target.all_sunk:
        raise RuntimeError(f"{bot_spec} did not sink the target fleet in {max_shots} shots")
    return shots


def _benchmark_bot_seed(seed: int, bot_index: int, game: int) -> int:
    mixed = int(seed) ^ (int(bot_index) * 0x9E3779B1) ^ (int(game) * 0x85EBCA6B)
    rng = random.Random(mixed & 0xFFFFFFFF)
    return rng.randrange(2**32)


def _report_row(
    report: MatchReport,
    bot_a: str,
    bot_b: str,
    game: int,
    pairing_id: int | None = None,
    memory_dir: Path | None = None,
) -> dict:
    row = {
        "match_id": report.match_id,
        "pairing_id": "" if pairing_id is None else pairing_id,
        "game": game,
        "bot_a": bot_a,
        "bot_b": bot_b,
        "winner": report.winner.value,
        "winner_bot": bot_a if report.winner is Player.A else bot_b,
        "reason": report.reason,
        "turns": report.turns,
        "a_remaining": round(report.remaining[Player.A], 6),
        "b_remaining": round(report.remaining[Player.B], 6),
    }
    if memory_dir is not None:
        row["memory_dir"] = str(memory_dir)
    return row


def _prepare_memory_dir(args: argparse.Namespace) -> Path | None:
    if not getattr(args, "memory", True):
        return None
    memory_dir = getattr(args, "memory_dir", None)
    path = Path(memory_dir or "results/memory")
    if getattr(args, "reset_memory", False) and path.exists():
        resolved = path.resolve()
        if not path.is_dir():
            raise SystemExit(f"--reset-memory requires a directory: {path}")
        if resolved == Path(resolved.anchor):
            raise SystemExit(f"refusing to reset filesystem root: {path}")
        shutil.rmtree(path)
    return path


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _tournament_bots(args: argparse.Namespace) -> list[str]:
    bots = list(args.bot or [])
    if args.bots_file:
        for line in Path(args.bots_file).read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                bots.append(stripped)
    return bots


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="battleship")
    sub = parser.add_subparsers(dest="command", required=True)
    sim = sub.add_parser("simulate")
    sim.add_argument("--games", type=int, default=1)
    sim.add_argument("--seed", type=int, default=123)
    sim.add_argument("--verbose", action="store_true")
    sim.add_argument("--process", action="store_true", help="run bots through worker subprocesses")
    sim.add_argument("--csv", default=None, help="write per-game match results to CSV")
    sim.add_argument("--memory", action=argparse.BooleanOptionalAction, default=True, help="load and save per-bot opponent memory")
    sim.add_argument("--memory-dir", default=None, help="memory directory; default: results/memory")
    sim.add_argument("--reset-memory", action="store_true", help="clear --memory-dir before running")
    sim.add_argument("--bot-a", default="starter", help=f"built-in bot or module:Class path. Built-ins: {available_bot_specs()}")
    sim.add_argument("--bot-b", default="starter", help=f"built-in bot or module:Class path. Built-ins: {available_bot_specs()}")
    sim.set_defaults(func=simulate)
    tour = sub.add_parser("tournament")
    tour.add_argument("--bot", action="append", help="built-in bot or module:Class path; repeat for each entrant")
    tour.add_argument("--bots-file", default=None, help="file with one bot spec per line")
    tour.add_argument("--games", type=int, default=10, help="games per ordered pairing")
    tour.add_argument("--seed", type=int, default=123)
    tour.add_argument("--process", action="store_true", help="run bots through worker subprocesses")
    tour.add_argument("--csv", default=None, help="write per-game match results to CSV")
    tour.add_argument("--memory", action=argparse.BooleanOptionalAction, default=True, help="load and save per-bot opponent memory")
    tour.add_argument("--memory-dir", default=None, help="memory directory; default: results/memory")
    tour.add_argument("--reset-memory", action="store_true", help="clear --memory-dir before running")
    tour.add_argument("--include-mirrors", action="store_true", help="also run bots against themselves")
    tour.set_defaults(func=tournament)
    bench = sub.add_parser("benchmark")
    bench.add_argument("--bot", action="append", help="built-in bot or module:Class path; repeat for each bot")
    bench.add_argument("--games", type=int, default=100, help="random target fleets per bot")
    bench.add_argument("--seed", type=int, default=123)
    bench.add_argument("--verbose", action="store_true")
    bench.add_argument("--csv", default=None, help="write per-game shot counts to CSV")
    bench.set_defaults(func=benchmark)
    server = sub.add_parser("remote-server")
    server.add_argument("--host", default="0.0.0.0", help="interface to bind; use 0.0.0.0 for LAN")
    server.add_argument("--port", type=int, default=8765)
    server.add_argument("--action-timeout", type=float, default=130.0, help="seconds to wait for one remote bot action")
    server.set_defaults(func=remote_server)
    client = sub.add_parser("remote-client")
    client.add_argument("--server", required=True, help="remote server URL, such as http://192.168.1.20:8765")
    client.add_argument("--bot", default="starter", help=f"built-in bot or module:Class path. Built-ins: {available_bot_specs()}")
    client.add_argument("--name", required=True, help="display name shown to the host")
    client.add_argument("--seed", type=int, default=None)
    client.add_argument("--poll-timeout", type=float, default=20.0)
    client.set_defaults(func=remote_client)
    remote_ls = sub.add_parser("remote-list")
    remote_ls.add_argument("--server", required=True)
    remote_ls.set_defaults(func=remote_list)
    remote = sub.add_parser("remote-match")
    remote.add_argument("--server", required=True)
    remote.add_argument("--bot-a", required=True, help="remote bot name or id")
    remote.add_argument("--bot-b", required=True, help="remote bot name or id")
    remote.add_argument("--games", type=int, default=1)
    remote.add_argument("--seed", type=int, default=123)
    remote.add_argument("--verbose", action="store_true")
    remote.add_argument("--csv", default=None, help="write per-game remote match results to CSV")
    remote.set_defaults(func=remote_match)
    p = sub.add_parser("play")
    p.add_argument("--seed", type=int, default=123)
    p.add_argument("--bot", default="starter", help=f"built-in bot or module:Class path. Built-ins: {available_bot_specs()}")
    p.add_argument("--solo", action="store_true", help="practice by firing at a random hidden fleet with no opponent")
    p.set_defaults(func=play)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

import shutil
import pytest
from pathlib import Path
from uuid import uuid4

from app.cli import main
from core.models import Player
from runtime.clocks import MoveTiming
from runtime.runner import MatchReport

pytestmark = pytest.mark.usefixtures("unpaced_matches")


def test_simulate_writes_csv():
    path = _output_path("sim")
    try:
        assert main(["simulate", "--games", "1", "--bot-a", "starter-random", "--bot-b", "starter-random", "--csv", str(path), "--no-memory"]) == 0

        text = path.read_text()
        assert "match_id,pairing_id,game,bot_a,bot_b,winner,winner_bot,reason,turns,a_remaining,b_remaining" in text
        assert "starter-random" in text
    finally:
        _cleanup(path)


def test_tournament_writes_csv():
    path = _output_path("tournament")
    try:
        assert main(
            [
                "tournament",
                "--bot",
                "starter-random",
                "--bot",
                "hunt-target",
                "--games",
                "1",
                "--csv",
                str(path),
                "--no-memory",
            ]
        ) == 0

        text = path.read_text()
        assert "starter-random" in text
        assert "hunt-target" in text
    finally:
        _cleanup(path)


def test_benchmark_writes_average_shot_counts(capsys):
    path = _output_path("benchmark")
    try:
        assert main(["benchmark", "--bot", "starter-random", "--games", "2", "--seed", "7", "--csv", str(path)]) == 0

        output = capsys.readouterr().out
        text = path.read_text()
        assert "starter-random: games=2 avg_shots=" in output
        assert "avg_move_time=" in output and "max_move_time=" in output
        assert "bot,game,shots,bot_seed,target_seed" in text
        assert "starter-random" in text
    finally:
        _cleanup(path)


def test_simulate_aggregates_move_times_by_side_and_handles_no_moves(monkeypatch, capsys):
    reports = iter([
        MatchReport(Player.A, "ended", 1, {Player.A: 59, Player.B: 60}, "one",
                    {Player.A: MoveTiming(1, 1, 1), Player.B: MoveTiming()}),
        MatchReport(Player.B, "ended", 3, {Player.A: 55, Player.B: 60}, "two",
                    {Player.A: MoveTiming(2, 5, 3), Player.B: MoveTiming()}),
    ])
    monkeypatch.setattr("app.cli._run_match", lambda *args: next(reports))
    assert main(["simulate", "--games", "2", "--no-memory"]) == 0
    output = capsys.readouterr().out
    assert "avg_move_time=2.000000s max_move_time=3.000000s moves=3" in output
    assert "avg_move_time=n/a max_move_time=n/a moves=0" in output


@pytest.mark.parametrize("verbose", [False, True])
@pytest.mark.parametrize("reason,winner,loser", [
    ("timeout during placement: bot exceeded the 5s action limit", Player.B, "A (alice)"),
    ("timeout during shot: bot exceeded the 0.5s action limit", Player.A, "B (bob)"),
])
def test_simulate_reports_timeouts_with_or_without_verbose(monkeypatch, capsys, verbose, reason, winner, loser):
    report = MatchReport(winner, reason, 0, {Player.A: 0, Player.B: 0}, "sim-0")
    monkeypatch.setattr("app.cli._run_match", lambda *args: report)
    args = ["simulate", "--games", "1", "--bot-a", "alice", "--bot-b", "bob", "--no-memory"]
    if verbose:
        args.append("--verbose")
    assert main(args) == 0
    output = capsys.readouterr().out
    assert output.count("sim-0:") == 1
    assert reason in output and f"timed_out={loser}" in output


def test_simulate_keeps_normal_results_quiet_without_verbose(monkeypatch, capsys):
    report = MatchReport(Player.A, "all ships sunk", 1, {Player.A: 0, Player.B: 0}, "sim-0")
    monkeypatch.setattr("app.cli._run_match", lambda *args: report)
    assert main(["simulate", "--games", "1", "--no-memory"]) == 0
    assert "sim-0:" not in capsys.readouterr().out


def test_benchmark_times_bot_shots_and_aggregates_by_move(monkeypatch, capsys):
    import app.cli as cli
    from bots.hunt_target import HuntTargetBot
    from runtime.clocks import FakeClock

    fake = FakeClock()
    bot = HuntTargetBot.seeded(1)
    choose_shot = bot.choose_shot

    def timed_shot(observation, remaining):
        fake.advance(0.25)
        return choose_shot(observation, remaining)

    monkeypatch.setattr(bot, "choose_shot", timed_shot)
    monkeypatch.setattr(cli, "build_bot", lambda *args: bot)
    monkeypatch.setattr(cli.time, "monotonic", fake)
    shots, timing = cli._run_target_benchmark_game("test", 1, 2)
    assert timing.count == shots
    assert timing.total == shots * 0.25
    assert timing.maximum == 0.25

    games = iter([(2, MoveTiming(2, 3, 2)), (1, MoveTiming(1, 3, 3))])
    monkeypatch.setattr(cli, "_run_target_benchmark_game", lambda *args: next(games))
    assert main(["benchmark", "--games", "2", "--bot", "test"]) == 0
    assert "avg_move_time=2.000000s max_move_time=3.000000s moves=3" in capsys.readouterr().out


def test_simulate_uses_memory_by_default():
    memory_dir = Path(".test-output") / f"default-memory-{uuid4().hex}"
    try:
        assert (
            main(
                [
                    "simulate",
                    "--games",
                    "1",
                    "--bot-a",
                    "starter-random",
                    "--bot-b",
                    "hunt-target",
                    "--memory-dir",
                    str(memory_dir),
                ]
            )
            == 0
        )
        assert (memory_dir / "starter-random" / "hunt-target.json").exists()
        assert (memory_dir / "hunt-target" / "starter-random.json").exists()
    finally:
        shutil.rmtree(memory_dir, ignore_errors=True)
        try:
            memory_dir.parent.rmdir()
        except OSError:
            pass


def test_play_supports_solo_flag(monkeypatch):
    calls = []

    def fake_run_app(**kwargs):
        calls.append(kwargs)

    import ui.pygame_app

    monkeypatch.setattr(ui.pygame_app, "run_app", fake_run_app)

    assert main(["play", "--solo", "--seed", "7"]) == 0
    assert calls == [
        {
            "seed": 7,
            "bot_name": "starter",
            "solo": True,
        }
    ]


def _output_path(name: str) -> Path:
    output_dir = Path(".test-output")
    output_dir.mkdir(exist_ok=True)
    return output_dir / f"{name}-{uuid4().hex}.csv"


def _cleanup(path: Path) -> None:
    path.unlink(missing_ok=True)
    try:
        path.parent.rmdir()
    except OSError:
        pass


def test_remote_match_reports_forfeit_without_verbose(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.run_remote_match_request", lambda *args: {"reports": [{
        "match_id": "test", "winner": "A", "winner_bot": "alice",
        "reason": "bot failure during placement: player B failed", "turns": 0,
    }]})
    assert main(["remote-match", "--server", "http://localhost:8765", "--bot-a", "alice", "--bot-b", "bob"]) == 0
    assert "bot failure during placement: player B failed" in capsys.readouterr().out


def test_remote_matches_displays_progress_and_empty_list(monkeypatch, capsys):
    match = {
        "series_id": "series-1", "bot_a": "alice", "bot_b": "bob", "completed": 2, "games": 5,
        "a_wins": 1, "b_wins": 1, "game": 3, "turns": 12, "match_id": "match-3",
    }
    monkeypatch.setattr("app.cli.list_ongoing_remote_matches", lambda server: [match])
    assert main(["remote-matches", "--server", "http://localhost:8765"]) == 0
    output = capsys.readouterr().out
    assert "alice (A) vs bob (B)" in output
    assert "completed=2/5" in output and "wins A=1 B=1" in output
    assert "game=3/5 turn=12 match=match-3" in output and "series=series-1" in output
    monkeypatch.setattr("app.cli.list_ongoing_remote_matches", lambda server: [])
    assert main(["remote-matches", "--server", "http://localhost:8765"]) == 0
    assert "no ongoing remote matches" in capsys.readouterr().out


def test_remote_admin_commands_report_missing_ids(monkeypatch, capsys):
    from runtime.remote import RemoteError

    def fail(*args):
        raise RemoteError("unknown id")

    monkeypatch.setattr("app.cli.stop_remote_match", fail)
    monkeypatch.setattr("app.cli.unregister_remote_bot", fail)
    assert main(["remote-stop", "--server", "http://localhost:8765", "--id", "bad"]) == 1
    assert "unknown id" in capsys.readouterr().out
    assert main(["remote-unregister", "--server", "http://localhost:8765", "--id", "bad"]) == 1
    assert "unknown id" in capsys.readouterr().out


def test_remote_match_reports_stopped_series(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.run_remote_match_request", lambda *args: {"reports": [], "stopped": True})
    assert main(["remote-match", "--server", "http://localhost:8765", "--bot-a", "alice", "--bot-b", "bob"]) == 0
    assert "remote match series stopped" in capsys.readouterr().out


def test_remote_match_reports_unavailable_player(monkeypatch, capsys):
    from runtime.remote import RemoteError

    def unavailable(*args):
        raise RemoteError("remote bot 'bob' is unresponsive")

    monkeypatch.setattr("app.cli.run_remote_match_request", unavailable)
    assert main(["remote-match", "--server", "http://localhost:8765", "--bot-a", "alice", "--bot-b", "bob"]) == 1
    assert "bob' is unresponsive" in capsys.readouterr().out


def test_remote_tournament_cli_keeps_local_tournament_options(monkeypatch, capsys):
    calls = []
    def run(*args):
        calls.append(args)
        return {"champion": "alice", "champion_id": "a", "reports": []}
    monkeypatch.setattr("app.cli.run_tournament", run)
    assert main(["tournament", "--server", "http://localhost:8765", "--seed", "8", "--wait-seconds", "0"]) == 0
    assert calls == [("http://localhost:8765", 8, 0, "results/memory")]
    assert "champion: alice" in capsys.readouterr().out
    assert main(["tournament", "--server", "http://localhost:8765", "--games", "5"]) == 0
    with pytest.raises(SystemExit, match="best-of-5"):
        main(["tournament", "--server", "http://localhost:8765", "--games", "7"])


def test_demo_tournament_invokes_existing_remote_tournament(monkeypatch):
    calls = []

    def fake_demo(port, seed, start, hide_ships=False):
        calls.append((port, seed, hide_ships))
        return start("http://127.0.0.1:9000", seed, "/tmp/demo-memory")

    def fake_tournament(server, seed, wait_seconds, memory_dir):
        calls.append((server, seed, wait_seconds, memory_dir))
        return {"champion": "bot", "champion_id": "id", "reports": []}

    monkeypatch.setattr("app.cli.run_demo", fake_demo)
    monkeypatch.setattr("app.cli.run_tournament", fake_tournament)
    assert main(["demo-tournament", "--port", "9000", "--seed", "42", "--wait-seconds", "2", "--hide-ships"]) == 0
    assert calls == [(9000, 42, True), ("http://127.0.0.1:9000", 42, 2.0, "/tmp/demo-memory")]
    with pytest.raises(SystemExit, match="non-negative"):
        main(["demo-tournament", "--wait-seconds", "-1"])


def test_simulate_runs_without_visual_move_delay(monkeypatch):
    minimums = []
    monkeypatch.setattr("runtime.runner.wait_for_minimum_move", lambda started, minimum, monotonic, sleep: minimums.append(minimum))
    assert main(["simulate", "--games", "1", "--bot-a", "starter", "--bot-b", "hunt-target", "--no-memory"]) == 0
    assert minimums and all(value == 0 for value in minimums)


def test_remote_server_ship_visibility_flag(monkeypatch):
    calls = []
    monkeypatch.setattr("app.cli.run_remote_server", lambda *args: calls.append(args))
    assert main(["remote-server", "--host", "127.0.0.1", "--port", "9000", "--hide-ships"]) == 0
    assert calls == [("127.0.0.1", 9000, 5.0, 15.0, True)]
    assert main(["remote-server"]) == 0
    assert calls[-1][-1] is False


def test_organizer_server_forwards_hide_ships_flag(monkeypatch):
    import scripts.organizer_remote_server as organizer

    commands = []
    monkeypatch.setattr(organizer.subprocess, "call", lambda command: commands.append(command) or 0)
    assert organizer.main(["--hide-ships"]) == 0
    assert "--hide-ships" in commands[0]
    assert organizer.main([]) == 0
    assert "--hide-ships" not in commands[1]

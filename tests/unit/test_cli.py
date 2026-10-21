from pathlib import Path
from uuid import uuid4

from app.cli import main


def test_simulate_writes_csv():
    path = _output_path("sim")
    try:
        assert main(["simulate", "--games", "1", "--bot-a", "starter-random", "--bot-b", "starter-random", "--csv", str(path)]) == 0

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
        assert "bot,game,shots,bot_seed,target_seed" in text
        assert "starter-random" in text
    finally:
        _cleanup(path)


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

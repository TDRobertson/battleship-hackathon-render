import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from app.cli import main
from runtime.process_agent import ProcessAgent
from core.rules import official_rules

pytestmark = pytest.mark.usefixtures("unpaced_matches")


def test_process_agent_starts_places_and_cleans_up():
    pytest.importorskip("numpy")
    agent = ProcessAgent(seed=123)
    try:
        placements = agent.place_ships(official_rules(), 120)
        assert {p.slot for p in placements} == set(official_rules().slots)
    finally:
        agent.close()
    assert agent.process.poll() is not None


def test_process_simulate_writes_memory_files():
    pytest.importorskip("numpy")
    memory_dir = Path(".test-output") / f"process-memory-{uuid4().hex}"
    try:
        assert (
            main(
                [
                    "simulate",
                    "--games",
                    "1",
                    "--process",
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


def test_process_bot_exceeding_placement_limit_forfeits_and_worker_is_stopped(tmp_path, monkeypatch):
    import os
    import time

    from bots.hunt_target import HuntTargetBot
    from core.models import Player
    from runtime.runner import LocalRunner

    (tmp_path / "slow_process_bot.py").write_text('''
import time
from agent import Agent
class SlowBot(Agent):
    def place_ships(self, rules, time_remaining):
        time.sleep(10)
        return []
    def choose_shot(self, observation, time_remaining):
        return (0, 0)
''')
    monkeypatch.setenv("PYTHONPATH", str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    with ProcessAgent(bot_spec="slow_process_bot:SlowBot") as agent:
        started = time.monotonic()
        report = LocalRunner().run(agent, HuntTargetBot.seeded(1))
        assert 4.8 <= time.monotonic() - started < 7
        assert report.winner is Player.B and "timeout during placement" in report.reason
    assert agent.process.poll() is not None

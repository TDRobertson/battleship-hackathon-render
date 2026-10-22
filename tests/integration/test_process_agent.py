import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from app.cli import main
from runtime.process_agent import ProcessAgent
from core.rules import official_rules


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

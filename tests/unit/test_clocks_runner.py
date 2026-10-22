import shutil
from pathlib import Path
from uuid import uuid4

from agent import Agent
from bots.hunt_target import HuntTargetBot
from runtime.clocks import FakeClock, MatchClocks
from core.models import Coord, Player, PublicShotResult, ShipPlacement
from runtime.runner import LocalRunner
from sdk.placement import random_legal_fleet
from sdk.observation import ObservationSnapshot
from sdk.memory import memory_path


def test_clock_charges_only_active_player():
    fake = FakeClock()
    clocks = MatchClocks(120, fake)
    clocks.start(Player.A)
    fake.advance(2)
    clocks.stop(Player.A)
    assert clocks.remaining[Player.A] == 118
    assert clocks.remaining[Player.B] == 120


def test_exact_deadline_times_out():
    fake = FakeClock()
    clocks = MatchClocks(5, fake)
    clocks.start(Player.A)
    fake.advance(5)
    assert clocks.is_timed_out(Player.A)


def test_seeded_bot_match_finishes():
    report = LocalRunner().run(HuntTargetBot.seeded(1), HuntTargetBot.seeded(2), "test")
    assert report.winner in {Player.A, Player.B}
    assert report.turns > 0


class MemoryProbeBot(Agent):
    def __init__(self):
        import random

        self.rng = random.Random(1)
        self.memory = {}
        self.observed = 0

    def start_match(self, context):
        self.memory = context.memory
        self.memory["starts"] = self.memory.get("starts", 0) + 1

    def place_ships(self, rules, time_remaining) -> list[ShipPlacement]:
        self.memory["current_layout"] = "probe-layout"
        return random_legal_fleet(rules, self.rng)

    def choose_shot(self, observation: ObservationSnapshot, time_remaining: float) -> Coord:
        row, col = next(zip(*observation.available_shots().nonzero()))
        return int(row), int(col)

    def observe_opponent_shot(self, result: PublicShotResult, time_remaining: float) -> None:
        self.observed += 1
        self.memory["opponent_shots_seen_by_bot"] = self.observed

    def end_match(self, result) -> None:
        self.memory["ended"] = True


def test_runner_persists_opponent_memory_and_stats():
    memory_dir = Path(".test-output") / f"memory-{uuid4().hex}"
    try:
        runner = LocalRunner(memory_dir=memory_dir)
        bot_a = MemoryProbeBot()
        bot_b = HuntTargetBot.seeded(2)

        report = runner.run(bot_a, bot_b, "memory-test", bot_a_name="probe", bot_b_name="hunt")

        path = memory_path(memory_dir, "probe", "hunt")
        assert path.exists()
        text = path.read_text()
        assert '"starts": 1' in text
        assert '"ended": true' in text
        assert '"games": 1' in text
        assert '"probe-layout"' in text
        assert bot_a.observed > 0
        assert report.winner in {Player.A, Player.B}
    finally:
        shutil.rmtree(memory_dir, ignore_errors=True)
        try:
            memory_dir.parent.rmdir()
        except OSError:
            pass

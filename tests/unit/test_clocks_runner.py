import shutil
import pytest
from pathlib import Path
from uuid import uuid4

from agent import Agent
from bots.hunt_target import HuntTargetBot
from runtime.clocks import FakeClock, MatchClocks, MoveTiming
from core.models import Coord, Player, PublicShotResult, ShipPlacement
from runtime.runner import LocalRunner
from sdk.placement import random_legal_fleet
from sdk.observation import ObservationSnapshot
from sdk.memory import memory_path

pytestmark = pytest.mark.usefixtures("unpaced_matches")


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


def test_default_clock_is_sixty_seconds():
    assert MatchClocks().remaining == {Player.A: 60, Player.B: 60}


def test_seeded_bot_match_finishes():
    report = LocalRunner().run(HuntTargetBot.seeded(1), HuntTargetBot.seeded(2), "test")
    assert report.winner in {Player.A, Player.B}
    assert report.turns > 0


def test_runner_records_shot_time_including_failed_attempts():
    fake = FakeClock()

    class TimedBot(MemoryProbeBot):
        def __init__(self, fail=False):
            super().__init__()
            self.calls = 0
            self.fail = fail

        def place_ships(self, rules, time_remaining):
            fake.advance(0.04)
            return super().place_ships(rules, time_remaining)

        def choose_shot(self, observation, time_remaining):
            self.calls += 1
            fake.advance(self.calls / 10)
            if self.fail and self.calls == 3:
                raise ValueError("failed shot")
            return super().choose_shot(observation, time_remaining)

    report = LocalRunner(monotonic=fake).run(TimedBot(fail=True), TimedBot())
    assert report.reason == "bot failure: failed shot"
    assert report.move_timing[Player.A].count == 3
    assert report.move_timing[Player.A].total == pytest.approx(0.6)
    assert report.move_timing[Player.A].maximum == pytest.approx(0.3)
    assert report.move_timing[Player.B].count == 2
    assert report.move_timing[Player.B].total == pytest.approx(0.3)
    assert report.move_timing[Player.B].maximum == pytest.approx(0.2)
    assert report.remaining[Player.A] == pytest.approx(0.2)


def test_runner_records_timed_out_shot():
    fake = FakeClock()

    class SlowBot(MemoryProbeBot):
        def choose_shot(self, observation, time_remaining):
            fake.advance(60)
            return super().choose_shot(observation, time_remaining)

    report = LocalRunner(monotonic=fake).run(SlowBot(), MemoryProbeBot())
    assert report.winner is Player.B
    assert report.reason == "timeout"
    assert report.move_timing[Player.A] == MoveTiming(1, 60, 60)
    assert report.move_timing[Player.B].count == 0


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


def test_runner_paces_fast_moves_without_charging_player_clocks():
    from core.rules import Rules
    from runtime.clocks import MINIMUM_MOVE_SECONDS

    assert MINIMUM_MOVE_SECONDS == 0.5
    fake = FakeClock()
    sleeps, shot_times = [], []

    class PacedBot(Agent):
        def __init__(self, durations):
            self.durations = iter(durations)
            self.shots = iter([(0, 0), (1, 1)])

        def place_ships(self, rules, time_remaining):
            return [ShipPlacement(0, 1, 1, "horizontal")]

        def choose_shot(self, observation, time_remaining):
            fake.advance(next(self.durations))
            return next(self.shots)

    def sleep(seconds):
        sleeps.append(seconds)
        fake.advance(seconds)

    report = LocalRunner(
        Rules(rows=2, cols=2, fleet=(1,)), monotonic=fake,
        minimum_move_seconds=MINIMUM_MOVE_SECONDS, sleep=sleep,
        on_shot=lambda result: shot_times.append(fake()),
    ).run(PacedBot([0.05, 0.0]), PacedBot([0.4]))

    assert report.winner is Player.A and report.turns == 3
    assert shot_times == pytest.approx([0.5, 1.0, 1.5])
    assert sleeps == pytest.approx([0.45, 0.1, 0.5])
    assert report.remaining[Player.A] == pytest.approx(0.5)
    assert report.remaining[Player.B] == pytest.approx(0.1)
    assert report.move_timing[Player.A].total == pytest.approx(0.05)
    assert report.move_timing[Player.B].total == pytest.approx(0.4)


def test_each_move_gets_a_fresh_half_second_without_a_total_game_clock():
    from core.rules import Rules

    fake = FakeClock()
    received = []

    class LongGameBot(Agent):
        def __init__(self):
            self.shots = iter((row, col) for row in range(10) for col in range(10))

        def place_ships(self, rules, time_remaining):
            received.append(time_remaining)
            return [ShipPlacement(0, 9, 9, "horizontal")]

        def choose_shot(self, observation, time_remaining):
            received.append(time_remaining)
            fake.advance(0.4)
            return next(self.shots)

    report = LocalRunner(Rules(fleet=(1,)), monotonic=fake).run(LongGameBot(), LongGameBot())
    assert report.winner is Player.A and report.turns == 199
    assert fake() > 60
    assert received[:2] == [5.0, 5.0]
    assert all(limit == 0.5 for limit in received[2:])


@pytest.mark.parametrize("action,deadline", [("placement", 5.0), ("shot", 0.5)])
def test_local_action_over_deadline_forfeits_without_waiting_for_bot(action, deadline):
    import threading
    import time

    release = threading.Event()

    class BlockingBot(MemoryProbeBot):
        def place_ships(self, rules, time_remaining):
            if action == "placement":
                release.wait(10)
            return super().place_ships(rules, time_remaining)

        def choose_shot(self, observation, time_remaining):
            if action == "shot":
                release.wait(10)
            return super().choose_shot(observation, time_remaining)

    try:
        started = time.monotonic()
        report = LocalRunner().run(BlockingBot(), MemoryProbeBot())
        elapsed = time.monotonic() - started
        assert deadline - 0.1 <= elapsed < deadline + 1.5
        assert report.winner is Player.B and "timeout" in report.reason
    finally:
        release.set()


def test_simulation_runner_does_not_apply_visual_move_delay():
    from core.rules import Rules

    class FastBot(Agent):
        def place_ships(self, rules, time_remaining):
            return [ShipPlacement(0, 1, 1, "horizontal")]

        def choose_shot(self, observation, time_remaining):
            return (1, 1)

    def no_sleep(seconds):
        raise AssertionError("simulation unexpectedly applied a visual delay")

    report = LocalRunner(Rules(rows=2, cols=2, fleet=(1,)), sleep=no_sleep).run(FastBot(), FastBot())
    assert report.winner is Player.A and report.turns == 1


@pytest.mark.parametrize("elapsed,reason", [(0.8, "all ships sunk"), (5.0, "all ships sunk"), (5.01, "timeout during placement")])
def test_placement_uses_five_second_limit_without_extending_shots(elapsed, reason):
    from core.rules import Rules

    fake = FakeClock()
    received = []

    class Bot(Agent):
        def __init__(self, slow):
            self.slow = slow

        def place_ships(self, rules, time_remaining):
            received.append(("placement", time_remaining))
            if self.slow:
                fake.advance(elapsed)
            return [ShipPlacement(0, 1, 1, "horizontal")]

        def choose_shot(self, observation, time_remaining):
            received.append(("shot", time_remaining))
            return (1, 1)

    report = LocalRunner(Rules(rows=2, cols=2, fleet=(1,)), monotonic=fake).run(Bot(True), Bot(False))
    assert report.reason == reason
    assert received[0] == ("placement", 5.0)
    if reason == "all ships sunk":
        assert received[-1] == ("shot", 0.5)


def test_local_move_at_exact_half_second_is_accepted():
    from core.rules import Rules

    fake = FakeClock()
    class BoundaryBot(Agent):
        def place_ships(self, rules, time_remaining):
            return [ShipPlacement(0, 1, 1, "horizontal")]

        def choose_shot(self, observation, time_remaining):
            fake.advance(0.5)
            return (1, 1)

    report = LocalRunner(Rules(rows=2, cols=2, fleet=(1,)), monotonic=fake).run(BoundaryBot(), BoundaryBot())
    assert report.winner is Player.A and report.reason == "all ships sunk"

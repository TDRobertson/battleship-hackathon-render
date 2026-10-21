from bots.hunt_target import HuntTargetBot
from runtime.clocks import FakeClock, MatchClocks
from core.models import Player
from runtime.runner import LocalRunner


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

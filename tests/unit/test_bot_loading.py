from bots.starter_random import RandomStarterBot
from core.rules import official_rules
from runtime.bot_loading import build_bot


def test_build_builtin_starter_bot():
    bot = build_bot("starter", seed=7)

    assert isinstance(bot, RandomStarterBot)
    assert bot.place_ships(official_rules(), 120)

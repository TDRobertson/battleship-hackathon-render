from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

from agent import Agent
from bots.hunt_target import HuntTargetBot
from bots.starter_random import RandomStarterBot


BotFactory = Callable[[int | None], Agent]


BUILTIN_BOTS: dict[str, BotFactory] = {
    "starter": RandomStarterBot.seeded,
    "starter-random": RandomStarterBot.seeded,
    "hunt-target": HuntTargetBot.seeded,
}


def available_bot_specs() -> str:
    return ", ".join(sorted(BUILTIN_BOTS))


def build_bot(spec: str, seed: int | None = None) -> Agent:
    """Create a bot from a built-in name or a ``module:attribute`` path."""

    if spec in BUILTIN_BOTS:
        return BUILTIN_BOTS[spec](seed)

    target = _load_attribute(spec)
    if hasattr(target, "seeded"):
        bot = target.seeded(seed)
    else:
        bot = target(seed) if seed is not None else target()
    if not isinstance(bot, Agent):
        raise TypeError(f"{spec!r} did not create an Agent")
    return bot


def _load_attribute(spec: str) -> Any:
    if ":" in spec:
        module_name, attribute = spec.split(":", 1)
    else:
        module_name, _, attribute = spec.rpartition(".")
    if not module_name or not attribute:
        raise ValueError(
            f"unknown bot {spec!r}; use one of {available_bot_specs()} or an import path like my_bot:MyBot"
        )
    module = importlib.import_module(module_name)
    return getattr(module, attribute)

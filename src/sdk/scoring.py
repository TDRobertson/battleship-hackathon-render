from __future__ import annotations

import random

from core.models import Coord
from core.rules import Rules
from sdk.inference import Fleet, hypothesis_reduction_scores


def choose_best_score(scores: dict[Coord, float], rng: random.Random) -> Coord:
    """Choose randomly among the highest-scoring coordinates."""

    if not scores:
        raise RuntimeError("no legal shots available")
    best = max(scores.values())
    choices = [coord for coord, score in scores.items() if score == best]
    return rng.choice(sorted(choices))


def information_scores(
    rules: Rules,
    fleets: list[Fleet],
    candidates: list[Coord],
) -> dict[Coord, float]:
    """Return expected hypothesis-pool split information for each candidate shot."""

    return hypothesis_reduction_scores(rules, fleets, candidates, assumed_outcome=None)

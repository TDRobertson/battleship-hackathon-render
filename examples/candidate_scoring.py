"""Example: turn legal shot candidates into scored shot choices.

This file is intentionally not a full bot. It shows one common pattern for a
`choose_shot` method:

1. Build a candidate pool of legal shots.
2. Score each candidate with a simple formula.
3. Use the SDK tie-breaker to choose among the best scores.

Copy these functions into a bot when you want to keep the candidate-generation
logic separate from the scoring formula.
"""

from __future__ import annotations

import random

from core.models import Coord
from core.rules import Rules
from sdk.board import center_distance
from sdk.scoring import choose_best_score
from sdk.targeting import available_shots, hit_neighbors, line_extensions


def candidate_pool(observation) -> list[Coord]:
    """Pick which legal cells to consider before scoring them.

    The order here is the strategy:

    - If there is a visible run of hits, try the cells beyond the run.
    - Otherwise, if there are unresolved hits, try their neighbors.
    - Otherwise, hunt anywhere that has not already been fired at.

    Each helper returns only legal, unshot cells. Empty lists are falsey in
    Python, so the `or` chain naturally falls through to the next option.
    """

    return line_extensions(observation) or hit_neighbors(observation) or available_shots(observation)


def score_candidates(rules: Rules, candidates: list[Coord]) -> dict[Coord, float]:
    """Assign a numeric score to each candidate coordinate.

    This example prefers cells near the center of the board by negating the
    distance from center: smaller distances become larger scores. Replace this
    formula with any signal you want to test, such as parity, heatmaps, or an
    opponent-specific pattern.
    """

    return {coord: -center_distance(rules, coord) for coord in candidates}


def choose_scored_shot(rules: Rules, observation, rng: random.Random) -> Coord:
    """Choose the best-scoring shot, breaking ties randomly."""

    candidates = candidate_pool(observation)
    scores = score_candidates(rules, candidates)
    return choose_best_score(scores, rng)

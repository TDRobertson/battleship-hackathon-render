from __future__ import annotations

import random

from core.models import Coord
from core.rules import Rules
from sdk.board import center_distance
from sdk.scoring import choose_best_score
from sdk.targeting import available_shots, hit_neighbors, line_extensions


def candidate_pool(observation) -> list[Coord]:
    """Pick which legal cells to consider before scoring them."""

    return line_extensions(observation) or hit_neighbors(observation) or available_shots(observation)


def score_candidates(rules: Rules, candidates: list[Coord]) -> dict[Coord, float]:
    """Example scoring shape. Replace the formula with your own idea."""

    return {coord: -center_distance(rules, coord) for coord in candidates}


def choose_scored_shot(rules: Rules, observation, rng: random.Random) -> Coord:
    candidates = candidate_pool(observation)
    scores = score_candidates(rules, candidates)
    return choose_best_score(scores, rng)

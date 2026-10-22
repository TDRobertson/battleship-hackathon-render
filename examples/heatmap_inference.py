"""Example: use fleet samples to score shots by probability and information.

The inference helpers generate fleets that are consistent with the public
observation. You can turn those fleets into an occupancy heatmap, expected
information scores, or both. The helper still does not decide your strategy:
you choose how to combine the signals.
"""

from __future__ import annotations

import random

from core.models import Coord
from core.rules import Rules
from sdk.inference import FleetSamplePool, hypothesis_reduction_scores, occupancy_from_fleets
from sdk.observation import ObservationSnapshot
from sdk.scoring import choose_best_score
from sdk.targeting import available_shots


class HeatmapShooter:
    """Reusable state for a bot that wants approximate probability estimates."""

    def __init__(self, rules: Rules, rng: random.Random, max_samples: int = 300) -> None:
        self.rng = rng
        self.pool = FleetSamplePool(rules, max_samples=max_samples, rng=rng, time_limit=0.25)

    def choose_shot(self, observation: ObservationSnapshot) -> Coord:
        """Score every legal shot with a blend of hit probability and information."""

        candidates = available_shots(observation)
        fleets = self.pool.update(observation)
        heat = occupancy_from_fleets(self.pool.rules, fleets)
        information = hypothesis_reduction_scores(self.pool.rules, fleets, candidates)

        scores = {}
        for row, col in candidates:
            # `heat[row, col]` estimates the chance that the shot hits an alive
            # ship, so it is a 0.0-to-1.0 probability-like value.
            #
            # `information[(row, col)]` is different: it estimates how much the
            # shot result would narrow or split the sampled fleet pool. It is an
            # entropy-reduction score, not a probability, so it can be larger
            # than 1.0 and should mainly be compared with other information
            # scores from this same observation.
            #
            # The weights below only put the two scales into one combined score;
            # they are example numbers, not part of the rules or SDK contract.
            scores[(row, col)] = (2.0 * heat[row, col]) + (0.1 * information[(row, col)])

        return choose_best_score(scores, self.rng)


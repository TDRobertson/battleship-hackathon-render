from __future__ import annotations

import random
from collections.abc import Iterable

import numpy as np

from core.models import Coord
from sdk.observation import ObservationSnapshot


def available_shots(observation: ObservationSnapshot) -> list[Coord]:
    """Return every unshot target-board coordinate."""
    return [tuple(map(int, coord)) for coord in np.argwhere(observation.available_shots())]


def unresolved_hits(observation: ObservationSnapshot) -> list[Coord]:
    """Return hit cells belonging to ships that have not sunk yet."""
    return [tuple(map(int, coord)) for coord in np.argwhere(observation.hits == 1)]


def orthogonal_neighbors(coord: Coord, shape: tuple[int, int]) -> list[Coord]:
    """Return in-bounds up/down/left/right neighbors for a coordinate."""
    row, col = coord
    candidates = [(row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)]
    return [(r, c) for r, c in candidates if 0 <= r < shape[0] and 0 <= c < shape[1]]


def hit_neighbors(observation: ObservationSnapshot) -> list[Coord]:
    """Return available orthogonal neighbors of unresolved hits."""
    available = observation.available_shots()
    candidates = []
    for hit in unresolved_hits(observation):
        candidates.extend(coord for coord in orthogonal_neighbors(hit, available.shape) if available[coord])
    return sorted(set(candidates))


def line_extensions(observation: ObservationSnapshot) -> list[Coord]:
    """Return available cells beyond contiguous horizontal or vertical hit runs."""
    hits = observation.hits
    available = observation.available_shots()
    candidates: list[Coord] = []
    rows, cols = hits.shape

    for row in range(rows):
        for run in contiguous_runs([col for col in range(cols) if hits[row, col]]):
            if len(run) >= 2:
                candidates.extend(_available([(row, run[0] - 1), (row, run[-1] + 1)], available))

    for col in range(cols):
        for run in contiguous_runs([row for row in range(rows) if hits[row, col]]):
            if len(run) >= 2:
                candidates.extend(_available([(run[0] - 1, col), (run[-1] + 1, col)], available))

    return sorted(set(candidates))


def choose_random(candidates: Iterable[Coord], rng: random.Random) -> Coord:
    """Choose uniformly from unique candidate coordinates."""
    choices = sorted(set(candidates))
    if not choices:
        raise RuntimeError("no legal shots available")
    return rng.choice(choices)


def contiguous_runs(values: list[int]) -> list[list[int]]:
    """Group sorted integers into contiguous runs."""
    if not values:
        return []
    runs = [[values[0]]]
    for value in values[1:]:
        if value == runs[-1][-1] + 1:
            runs[-1].append(value)
        else:
            runs.append([value])
    return runs


def _available(coords: list[Coord], available: np.ndarray) -> list[Coord]:
    return [
        (row, col)
        for row, col in coords
        if 0 <= row < available.shape[0] and 0 <= col < available.shape[1] and bool(available[row, col])
    ]

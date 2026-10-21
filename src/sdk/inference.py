from __future__ import annotations

import random
import time
import zlib
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from core.models import Coord, Outcome, ShipPlacement
from core.rules import Rules
from sdk.observation import ObservationSnapshot
from sdk.placement import legal_ship_placements, ship_cells


Fleet = tuple[ShipPlacement, ...]


@dataclass(frozen=True, slots=True)
class _PlacementOption:
    placement: ShipPlacement
    mask: int
    cells: tuple[Coord, ...]


@dataclass(frozen=True, slots=True)
class _FleetSamplingContext:
    rules: Rules
    slots: tuple[int, ...]
    required_mask: int
    forbidden_mask: int
    placements_by_slot: dict[int, list[_PlacementOption]]


@dataclass(slots=True)
class FleetSamplePool:
    """Maintain a reusable sample of fleets across observation updates.

    The pool stores alive-ship fleet hypotheses that are consistent with the
    latest public observation. Calling `update()` filters out disproven fleets
    and samples replacement fleets until `max_samples` or the time limit is reached.
    """

    rules: Rules
    max_samples: int = 500
    time_limit: float = 1.0
    rng: random.Random = field(default_factory=random.Random)
    fleets: list[Fleet] = field(default_factory=list)
    retained: int = 0
    refilled: int = 0
    discarded: int = 0
    shortfall: int = 0

    def update(self, observation: ObservationSnapshot) -> list[Fleet]:
        target = max(0, int(self.max_samples))
        if target == 0:
            self.fleets.clear()
            self.retained = 0
            self.refilled = 0
            self.discarded = 0
            self.shortfall = 0
            return self.fleets

        previous_count = len(self.fleets)
        retained_fleets = filter_possible_fleets(self.rules, observation, self.fleets)
        if len(retained_fleets) > target:
            retained_fleets = random_subset(retained_fleets, target, self.rng)

        self.fleets, self.refilled = refill_possible_fleets(
            self.rules,
            observation,
            retained_fleets,
            max_samples=target,
            rng=self.rng,
            time_limit=self.time_limit,
        )
        self.retained = len(retained_fleets)
        self.discarded = max(0, previous_count - self.retained)
        self.shortfall = max(0, target - len(self.fleets))
        return self.fleets

    def occupancy_heatmap(self, observation: ObservationSnapshot) -> np.ndarray:
        return occupancy_from_fleets(self.rules, self.update(observation))


def possible_fleets(
    rules: Rules,
    observation: ObservationSnapshot,
    max_fleets: int = 300,
    rng: random.Random | None = None,
) -> list[tuple[ShipPlacement, ...]]:
    """Return legal alive-ship fleets consistent with public shot results.

    The full set is often too large to enumerate, so results are capped by
    `max_fleets`. When no RNG is supplied, the cap uses a deterministic shuffle
    derived from the observation instead of row-major placement order. This
    keeps exploratory helpers from accidentally treating the top-left board
    region as more likely just because it appears first in enumeration.
    """
    context = _fleet_sampling_context(rules, observation)
    shuffle_rng = rng or _stable_observation_rng(observation)
    placements_by_slot = {slot: list(placements) for slot, placements in context.placements_by_slot.items()}
    for placements in placements_by_slot.values():
        shuffle_rng.shuffle(placements)

    fleets: list[tuple[ShipPlacement, ...]] = []
    _collect_fleets(context, list(context.slots), placements_by_slot, context.required_mask, 0, [], fleets, max_fleets)
    return fleets


def sample_possible_fleets(
    rules: Rules,
    observation: ObservationSnapshot,
    max_samples: int = 500,
    rng: random.Random | None = None,
    time_limit: float = 1.0,
) -> list[Fleet]:
    """Sample up to `max_samples` legal alive-ship fleets.

    The sampler returns early when `time_limit` seconds elapse. This keeps
    interactive tools responsive late in games, when legal replacement fleets
    can become difficult to find.
    """

    target = max(0, int(max_samples))
    if target == 0:
        return []
    context = _fleet_sampling_context(rules, observation)
    deadline = _sampling_deadline(time_limit)
    sample_rng = rng or _stable_observation_rng(observation)
    return _sample_possible_fleets_from_context(context, target, sample_rng, deadline, set())


def _sample_possible_fleets_from_context(
    context: _FleetSamplingContext,
    target: int,
    rng: random.Random,
    deadline: float | None,
    exclude: set[Fleet],
) -> list[Fleet]:
    fleets: list[Fleet] = []
    attempts = 0
    max_attempts = max(100, target * 30)
    while len(fleets) < target and attempts < max_attempts and not _deadline_elapsed(deadline):
        attempts += 1
        fleet = _sample_fleet(context, list(context.slots), 0, [], rng, deadline)
        if fleet is not None and fleet not in exclude:
            exclude.add(fleet)
            fleets.append(fleet)
    return fleets


def filter_possible_fleets(
    rules: Rules,
    observation: ObservationSnapshot,
    fleets: list[Fleet],
) -> list[Fleet]:
    """Keep fleet hypotheses that remain legal for the latest observation."""

    retained = []
    seen = set()
    for fleet in fleets:
        normalized = normalize_alive_fleet(rules, observation, fleet)
        if normalized is None:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        retained.append(normalized)
    return retained


def refill_possible_fleets(
    rules: Rules,
    observation: ObservationSnapshot,
    fleets: list[Fleet],
    max_samples: int = 500,
    rng: random.Random | None = None,
    time_limit: float = 1.0,
) -> tuple[list[Fleet], int]:
    """Return `fleets` plus new legal fleets up to `max_samples`.

    If replacements cannot be sampled before `time_limit`, the helper returns
    the legal fleets it has. Callers should treat `max_samples` as a ceiling,
    not a guaranteed count.
    """

    target = max(0, int(max_samples))
    if len(fleets) >= target:
        return fleets[:target], 0
    needed = target - len(fleets)
    context = _fleet_sampling_context(rules, observation)
    sample_rng = rng or _stable_observation_rng(observation)
    replacements = _sample_possible_fleets_from_context(
        context,
        needed,
        sample_rng,
        _sampling_deadline(time_limit),
        set(fleets),
    )
    return fleets + replacements, len(replacements)


def occupancy_heatmap(
    rules: Rules,
    observation: ObservationSnapshot,
    max_samples: int = 500,
    rng: random.Random | None = None,
    time_limit: float = 1.0,
) -> np.ndarray:
    """Estimate alive-ship occupancy probability from possible fleets.

    The helper samples complete fleets that are legal and consistent with the
    public observation, then counts how often each cell is occupied. Higher
    `max_samples` values are slower but usually less noisy. The helper does not
    decide which probability is strategically best to shoot at; bots choose how
    to use the returned board.
    """
    return occupancy_from_fleets(rules, sample_possible_fleets(rules, observation, max_samples, rng, time_limit))


def occupancy_from_fleets(rules: Rules, fleets: list[Fleet]) -> np.ndarray:
    """Return cell occupancy frequencies for a list of alive-ship fleets."""

    heat = np.zeros((rules.rows, rules.cols), dtype=float)
    for fleet in fleets:
        for placement in fleet:
            for coord in ship_cells(rules, placement):
                heat[coord] += 1.0
    if fleets:
        heat /= len(fleets)
    return heat


def hypothesis_reduction_scores(
    rules: Rules,
    fleets: list[Fleet],
    candidates: list[Coord],
    assumed_outcome: Outcome | str | None = None,
) -> dict[Coord, float]:
    """Score shots by how much they split and clarify a fleet sample pool.

    The score is the drop in total marginal occupancy entropy across the board
    after splitting sampled fleets into hit and miss branches. With no assumed
    outcome, the score is the hit/miss probability-weighted expected entropy
    reduction. With `assumed_outcome="hit"` or `"miss"`, it returns the entropy
    reduction for that single branch.
    """

    if not fleets:
        return {coord: 0.0 for coord in candidates}
    prior_counts, cooccurrence = _fleet_cooccurrence_counts(rules, fleets)
    prior_entropy = _counts_entropy(prior_counts, len(fleets))
    return {
        coord: _split_information_score_from_counts(
            rules,
            prior_counts,
            cooccurrence,
            coord,
            len(fleets),
            prior_entropy,
            assumed_outcome,
        )
        for coord in candidates
    }


def fleet_pool_entropy(rules: Rules, fleets: list[Fleet]) -> float:
    """Return total marginal occupancy entropy for sampled fleet hypotheses."""

    counts, _cooccurrence = _fleet_cooccurrence_counts(rules, fleets)
    return _counts_entropy(counts, len(fleets))


def occupancy_entropy(occupancy: np.ndarray) -> float:
    """Return summed binary entropy across an occupancy probability map."""

    probabilities = occupancy.astype(float, copy=False)
    middle = probabilities[(probabilities > 0.0) & (probabilities < 1.0)]
    if middle.size == 0:
        return 0.0
    entropy = -(middle * np.log2(middle) + (1.0 - middle) * np.log2(1.0 - middle))
    return float(np.sum(entropy))


def normalize_alive_fleet(
    rules: Rules,
    observation: ObservationSnapshot,
    fleet: Fleet,
) -> Fleet | None:
    """Return the alive portion of a fleet if it matches the observation."""

    misses = _coords_where(observation.misses)
    sunk = _coords_where(observation.sunk)
    required_hits = _coords_where(observation.hits)
    alive_slots = {slot for slot, alive in enumerate(observation.ships_alive) if alive}
    placements_by_slot: dict[int, ShipPlacement] = {}
    for placement in fleet:
        if placement.slot in placements_by_slot:
            return None
        placements_by_slot[placement.slot] = placement

    alive_placements: list[ShipPlacement] = []
    occupied: set[Coord] = set()
    for placement in placements_by_slot.values():
        try:
            cells = set(ship_cells(rules, placement))
        except ValueError:
            return None
        if placement.slot in alive_slots:
            if not cells.isdisjoint(misses | sunk):
                return None
            if not occupied.isdisjoint(cells):
                return None
            alive_placements.append(placement)
            occupied.update(cells)
        elif not cells.issubset(sunk):
            return None

    if {placement.slot for placement in alive_placements} != alive_slots:
        return None
    if not required_hits.issubset(occupied):
        return None
    return tuple(sorted(alive_placements, key=lambda placement: placement.slot))


def random_subset(fleets: list[Fleet], samples: int, rng: random.Random) -> list[Fleet]:
    """Return up to `samples` fleets without changing the input list."""

    subset = list(fleets)
    rng.shuffle(subset)
    return subset[: max(0, int(samples))]


def _split_information_score_from_counts(
    rules: Rules,
    prior_counts: np.ndarray,
    cooccurrence: np.ndarray,
    coord: Coord,
    total: int,
    prior_entropy: float,
    assumed_outcome: Outcome | str | None,
) -> float:
    index = _coord_index(rules, coord)
    hit_total = int(prior_counts[index])
    miss_total = total - hit_total
    hit_counts = cooccurrence[index]
    miss_counts = prior_counts - hit_counts

    if assumed_outcome is None:
        p_hit = hit_total / total
        p_miss = miss_total / total
        hit_entropy = _counts_entropy(hit_counts, hit_total) if hit_total else 0.0
        miss_entropy = _counts_entropy(miss_counts, miss_total) if miss_total else 0.0
        expected_entropy = p_hit * hit_entropy + p_miss * miss_entropy
        return max(0.0, prior_entropy - expected_entropy)

    outcome = assumed_outcome.value if isinstance(assumed_outcome, Outcome) else str(assumed_outcome).lower()
    if outcome in (Outcome.HIT.value, Outcome.SUNK.value):
        return 0.0 if not hit_total else prior_entropy - _counts_entropy(hit_counts, hit_total)
    if outcome == Outcome.MISS.value:
        return 0.0 if not miss_total else prior_entropy - _counts_entropy(miss_counts, miss_total)
    raise ValueError("assumed_outcome must be None, 'hit', 'miss', or 'sunk'")


def _collect_fleets(
    context: _FleetSamplingContext,
    slots: list[int],
    placements_by_slot: dict[int, list[_PlacementOption]],
    required_mask: int,
    occupied_mask: int,
    chosen: list[ShipPlacement],
    fleets: list[tuple[ShipPlacement, ...]],
    max_fleets: int,
) -> None:
    if len(fleets) >= max_fleets:
        return
    if not slots:
        if required_mask & ~occupied_mask == 0:
            fleets.append(tuple(chosen))
        return

    remaining_slots = slots[1:]
    for placement in placements_by_slot[slots[0]]:
        if occupied_mask & placement.mask:
            continue
        next_occupied = occupied_mask | placement.mask
        if not _hits_can_still_be_covered(context, required_mask & ~next_occupied, next_occupied, remaining_slots):
            continue
        chosen.append(placement.placement)
        _collect_fleets(context, remaining_slots, placements_by_slot, required_mask, next_occupied, chosen, fleets, max_fleets)
        chosen.pop()
        if len(fleets) >= max_fleets:
            return


def _hits_can_still_be_covered(
    context: _FleetSamplingContext,
    hits_mask: int,
    occupied_mask: int,
    slots: list[int],
) -> bool:
    if hits_mask == 0:
        return True
    coverable = 0
    for slot in slots:
        for placement in context.placements_by_slot[slot]:
            if occupied_mask & placement.mask:
                continue
            coverable |= placement.mask
            if hits_mask & ~coverable == 0:
                return True
    return False


def _sample_fleet(
    context: _FleetSamplingContext,
    slots: list[int],
    occupied_mask: int,
    chosen: list[ShipPlacement],
    rng: random.Random,
    deadline: float | None,
) -> Fleet | None:
    if _deadline_elapsed(deadline):
        return None
    if not slots:
        return tuple(sorted(chosen, key=lambda placement: placement.slot)) if context.required_mask & ~occupied_mask == 0 else None

    slot, candidates = _sampling_step(context, slots, occupied_mask, rng)
    rng.shuffle(candidates)
    remaining_slots = [remaining_slot for remaining_slot in slots if remaining_slot != slot]
    for placement in candidates:
        if _deadline_elapsed(deadline):
            return None
        if occupied_mask & placement.mask:
            continue
        next_occupied = occupied_mask | placement.mask
        if not _hits_can_still_be_covered(context, context.required_mask & ~next_occupied, next_occupied, remaining_slots):
            continue
        chosen.append(placement.placement)
        fleet = _sample_fleet(context, remaining_slots, next_occupied, chosen, rng, deadline)
        chosen.pop()
        if fleet is not None:
            return fleet
    return None


def _fleet_sampling_context(rules: Rules, observation: ObservationSnapshot) -> _FleetSamplingContext:
    forbidden_mask = _mask_where(rules, observation.misses) | _mask_where(rules, observation.sunk)
    required_mask = _mask_where(rules, observation.hits)
    slots = tuple(sorted((slot for slot, alive in enumerate(observation.ships_alive) if alive), key=rules.ship_length, reverse=True))
    placements_by_slot = {slot: _legal_placement_options(rules, slot, forbidden_mask) for slot in slots}
    return _FleetSamplingContext(rules, slots, required_mask, forbidden_mask, placements_by_slot)


def _legal_placement_options(rules: Rules, slot: int, forbidden_mask: int) -> list[_PlacementOption]:
    return [option for option in _all_placement_options(rules, slot) if forbidden_mask & option.mask == 0]


@lru_cache(maxsize=128)
def _all_placement_options(rules: Rules, slot: int) -> tuple[_PlacementOption, ...]:
    options = []
    for placement in legal_ship_placements(rules, slot):
        cells = ship_cells(rules, placement)
        options.append(_PlacementOption(placement, _cells_mask(rules, cells), cells))
    return tuple(options)


def _most_constrained_slot(context: _FleetSamplingContext, slots: list[int], occupied_mask: int) -> int:
    best_slot = slots[0]
    best_count: int | None = None
    for slot in slots:
        count = 0
        for placement in context.placements_by_slot[slot]:
            if occupied_mask & placement.mask == 0:
                count += 1
        if best_count is None or count < best_count:
            best_slot = slot
            best_count = count
    return best_slot


def _sampling_step(
    context: _FleetSamplingContext,
    slots: list[int],
    occupied_mask: int,
    rng: random.Random,
) -> tuple[int, list[_PlacementOption]]:
    uncovered_hits = context.required_mask & ~occupied_mask
    if uncovered_hits:
        anchored = _anchored_sampling_step(context, slots, occupied_mask, uncovered_hits, rng)
        if anchored is not None:
            return anchored

    slot = _most_constrained_slot(context, slots, occupied_mask)
    return slot, [placement for placement in context.placements_by_slot[slot] if occupied_mask & placement.mask == 0]


def _anchored_sampling_step(
    context: _FleetSamplingContext,
    slots: list[int],
    occupied_mask: int,
    uncovered_hits: int,
    rng: random.Random,
) -> tuple[int, list[_PlacementOption]] | None:
    anchor = _random_mask_bit(uncovered_hits, rng)
    options_by_slot: list[tuple[int, list[_PlacementOption]]] = []
    for slot in slots:
        options = [
            placement
            for placement in context.placements_by_slot[slot]
            if placement.mask & anchor and occupied_mask & placement.mask == 0
        ]
        if options:
            options_by_slot.append((slot, options))
    if not options_by_slot:
        return None
    return rng.choice(options_by_slot)


def _random_mask_bit(mask: int, rng: random.Random) -> int:
    bits = []
    remaining = mask
    while remaining:
        bit = remaining & -remaining
        bits.append(bit)
        remaining ^= bit
    return rng.choice(bits)


def _fleet_cooccurrence_counts(rules: Rules, fleets: list[Fleet]) -> tuple[np.ndarray, np.ndarray]:
    cell_count = rules.rows * rules.cols
    counts = np.zeros(cell_count, dtype=np.int32)
    cooccurrence = np.zeros((cell_count, cell_count), dtype=np.int32)
    for fleet in fleets:
        indices = _fleet_cell_indices(rules, fleet)
        if not indices:
            continue
        index_array = np.array(indices, dtype=np.intp)
        counts[index_array] += 1
        cooccurrence[np.ix_(index_array, index_array)] += 1
    return counts, cooccurrence


def _counts_entropy(counts: np.ndarray, total: int) -> float:
    if total <= 0:
        return 0.0
    probabilities = counts.astype(float, copy=False) / float(total)
    middle = probabilities[(probabilities > 0.0) & (probabilities < 1.0)]
    if middle.size == 0:
        return 0.0
    entropy = -(middle * np.log2(middle) + (1.0 - middle) * np.log2(1.0 - middle))
    return float(np.sum(entropy))


def _fleet_cell_indices(rules: Rules, fleet: Fleet) -> list[int]:
    seen: set[int] = set()
    indices: list[int] = []
    for placement in fleet:
        for coord in ship_cells(rules, placement):
            index = _coord_index(rules, coord)
            if index not in seen:
                seen.add(index)
                indices.append(index)
    return indices


def _cells_mask(rules: Rules, cells: tuple[Coord, ...]) -> int:
    mask = 0
    for coord in cells:
        mask |= 1 << _coord_index(rules, coord)
    return mask


def _mask_where(rules: Rules, mask: np.ndarray) -> int:
    value = 0
    for row, col in np.argwhere(mask == 1):
        value |= 1 << _coord_index(rules, (int(row), int(col)))
    return value


def _coord_index(rules: Rules, coord: Coord) -> int:
    row, col = coord
    return int(row) * rules.cols + int(col)


def _coords_where(mask: np.ndarray) -> set[Coord]:
    return {tuple(map(int, coord)) for coord in np.argwhere(mask == 1)}


def _sampling_deadline(time_limit: float | None) -> float | None:
    if time_limit is None:
        return None
    if time_limit <= 0:
        return time.monotonic()
    return time.monotonic() + float(time_limit)


def _deadline_elapsed(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _stable_observation_rng(observation: ObservationSnapshot) -> random.Random:
    checksum = 0
    for array in (observation.misses, observation.hits, observation.sunk, observation.ships_alive):
        checksum = zlib.crc32(np.ascontiguousarray(array).tobytes(), checksum)
    checksum = zlib.crc32(int(observation.version).to_bytes(8, "little", signed=False), checksum)
    return random.Random(checksum)

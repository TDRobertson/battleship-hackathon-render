from __future__ import annotations

from dataclasses import dataclass
import zlib

import numpy as np

from core.models import Coord
from core.rules import Rules
from sdk.board import diagonal_band_cells
from sdk.inference import FleetSamplePool, hypothesis_reduction_scores, occupancy_from_fleets, sample_possible_fleets
from sdk.neural import default_observation_encoder, with_ship_slot_alive_channels
from sdk.observation import ObservationSnapshot
from sdk.targeting import hit_neighbors, line_extensions, unresolved_hits


DEBUG_LAYERS = (
    "none",
    "occupancy",
    "information",
    "diagonal",
    "available",
    "hits",
    "hit_neighbors",
    "line_extensions",
    "neural",
)

DEBUG_FOCUSES = ("human-target", "bot-target")


@dataclass(slots=True)
class DebugSettings:
    """Mutable state for the battle-screen helper visualizer."""

    enabled: bool = True
    layer_index: int = 1
    focus_index: int = 0
    diagonal_spacing: int = 2
    diagonal_offset: int = 0
    max_samples: int = 500
    neural_channel: int = 0
    selected_cell: Coord | None = None

    @property
    def layer(self) -> str:
        return DEBUG_LAYERS[self.layer_index % len(DEBUG_LAYERS)]

    @property
    def focus(self) -> str:
        return DEBUG_FOCUSES[self.focus_index % len(DEBUG_FOCUSES)]

    def next_layer(self) -> None:
        self.layer_index = (self.layer_index + 1) % len(DEBUG_LAYERS)

    def previous_layer(self) -> None:
        self.layer_index = (self.layer_index - 1) % len(DEBUG_LAYERS)

    def next_focus(self) -> None:
        self.focus_index = (self.focus_index + 1) % len(DEBUG_FOCUSES)

    def adjust_spacing(self, delta: int) -> None:
        self.diagonal_spacing = max(1, self.diagonal_spacing + delta)
        self.diagonal_offset %= self.diagonal_spacing

    def adjust_offset(self, delta: int) -> None:
        self.diagonal_offset = (self.diagonal_offset + delta) % self.diagonal_spacing

    def adjust_samples(self, delta: int) -> None:
        self.max_samples = max(25, self.max_samples + delta)

    def next_neural_channel(self, rules: Rules) -> None:
        self.neural_channel = (self.neural_channel + 1) % len(neural_channel_names(rules))


@dataclass(frozen=True, slots=True)
class DebugLayerResult:
    title: str
    values: np.ndarray
    style: str
    details: tuple[str, ...] = ()

    @property
    def maximum(self) -> float:
        if self.values.size == 0:
            return 0.0
        return float(np.max(self.values))


@dataclass(slots=True)
class DebugLayerCache:
    """Cache expensive helper overlays between board or setting changes."""

    key: tuple | None = None
    result: DebugLayerResult | None = None
    fleet_pool: FleetSamplePool | None = None

    def get(self, rules: Rules, observation: ObservationSnapshot, settings: DebugSettings) -> DebugLayerResult:
        key = debug_layer_key(observation, settings)
        if self.key != key or self.result is None:
            self.key = key
            if settings.layer in ("occupancy", "information"):
                if self.fleet_pool is None or self.fleet_pool.rules != rules:
                    self.fleet_pool = FleetSamplePool(rules)
                self.fleet_pool.max_samples = settings.max_samples
            self.result = build_debug_layer(rules, observation, settings, self.fleet_pool)
        return self.result

    def clear(self) -> None:
        self.key = None
        self.result = None
        self.fleet_pool = None


def debug_layer_key(observation: ObservationSnapshot, settings: DebugSettings) -> tuple:
    return (
        int(observation.version),
        _observation_checksum(observation),
        settings.enabled,
        settings.layer_index,
        settings.diagonal_spacing,
        settings.diagonal_offset,
        settings.max_samples,
        settings.neural_channel,
    )


def build_debug_layer(
    rules: Rules,
    observation: ObservationSnapshot,
    settings: DebugSettings,
    fleet_pool: FleetSamplePool | None = None,
) -> DebugLayerResult:
    """Return the board-shaped data for one debug helper layer."""

    layer = settings.layer
    empty = np.zeros((rules.rows, rules.cols), dtype=float)
    if not settings.enabled or layer == "none":
        return DebugLayerResult("No helper overlay", empty, "none")
    if layer == "occupancy":
        if fleet_pool is None:
            fleets = sample_possible_fleets(rules, observation, max_samples=settings.max_samples)
            heat = occupancy_from_fleets(rules, fleets)
            details = _sample_details(settings.max_samples, len(fleets), len(fleets))
        else:
            heat = fleet_pool.occupancy_heatmap(observation)
            details = _sample_details(settings.max_samples, len(fleet_pool.fleets), len(fleet_pool.fleets)) + (
                f"retained: {fleet_pool.retained}",
                f"refilled: {fleet_pool.refilled}",
                f"shortfall: {fleet_pool.shortfall}",
            )
        return DebugLayerResult(
            "Occupancy heatmap",
            heat,
            "heat",
            details,
        )
    if layer == "information":
        if fleet_pool is None:
            fleets = sample_possible_fleets(rules, observation, max_samples=settings.max_samples)
            details = _sample_details(settings.max_samples, len(fleets), len(fleets)) + (
                "score: expected split information",
            )
        else:
            fleets = fleet_pool.update(observation)
            details = _sample_details(settings.max_samples, len(fleets), len(fleets)) + (
                f"retained: {fleet_pool.retained}",
                f"refilled: {fleet_pool.refilled}",
                f"shortfall: {fleet_pool.shortfall}",
                "score: expected split information",
            )
        candidates = [tuple(map(int, coord)) for coord in np.argwhere(observation.available_shots())]
        scores = hypothesis_reduction_scores(rules, fleets, candidates)
        values = empty.copy()
        for coord, score in scores.items():
            values[coord] = score
        return DebugLayerResult("Expected split information", values, "heat", details)
    if layer == "diagonal":
        values = empty.copy()
        for coord in diagonal_band_cells(rules, settings.diagonal_spacing, settings.diagonal_offset):
            values[coord] = 1.0
        return DebugLayerResult(
            "Diagonal bands",
            values,
            "mask",
            (f"spacing: {settings.diagonal_spacing}", f"offset: {settings.diagonal_offset}"),
        )
    if layer == "available":
        return DebugLayerResult("Available shots", observation.available_shots().astype(float), "mask")
    if layer == "hits":
        values = empty.copy()
        values += observation.hits.astype(float)
        values += observation.sunk.astype(float)
        return DebugLayerResult("Known hits and sunk cells", values, "mask")
    if layer == "hit_neighbors":
        values = _mask(rules, hit_neighbors(observation))
        return DebugLayerResult("Available neighbors of unresolved hits", values, "mask")
    if layer == "line_extensions":
        values = _mask(rules, line_extensions(observation))
        return DebugLayerResult("Line extensions from hit runs", values, "mask")
    if layer == "neural":
        encoder = with_ship_slot_alive_channels(default_observation_encoder(include_ship_alive=True), rules)
        channel_index = settings.neural_channel % encoder.channel_count
        channels = encoder.encode(observation, rules)
        return DebugLayerResult(
            f"Neural channel: {encoder.names[channel_index]}",
            channels[channel_index],
            "heat",
            (f"channel {channel_index + 1} / {encoder.channel_count}",),
        )
    raise ValueError(f"unknown debug layer: {layer}")


def neural_channel_names(rules: Rules) -> tuple[str, ...]:
    encoder = with_ship_slot_alive_channels(default_observation_encoder(include_ship_alive=True), rules)
    return encoder.names


def selected_cell_details(
    rules: Rules,
    observation: ObservationSnapshot,
    layer_result: DebugLayerResult,
    selected_cell: Coord | None,
) -> tuple[str, ...]:
    if selected_cell is None:
        return ("Click a debug board cell to inspect it.",)
    row, col = selected_cell
    if not (0 <= row < rules.rows and 0 <= col < rules.cols):
        return ("Selected cell is outside the board.",)
    state = "available"
    if observation.misses[row, col]:
        state = "miss"
    elif observation.hits[row, col]:
        state = "unresolved hit"
    elif observation.sunk[row, col]:
        state = "sunk"
    return (
        f"cell: ({row}, {col})",
        f"state: {state}",
        f"{layer_result.title}: {layer_result.values[row, col]:.3f}",
        f"unresolved hits: {len(unresolved_hits(observation))}",
    )


def _mask(rules: Rules, coords: list[Coord]) -> np.ndarray:
    values = np.zeros((rules.rows, rules.cols), dtype=float)
    for coord in coords:
        values[coord] = 1.0
    return values


def _sample_details(max_samples: int, occupancy_samples: int, information_samples: int) -> tuple[str, ...]:
    return (
        f"max samples: {max_samples}",
        f"occupancy used: {occupancy_samples}",
        f"information used: {information_samples}",
    )


def _observation_checksum(observation: ObservationSnapshot) -> int:
    checksum = 0
    for array in (observation.misses, observation.hits, observation.sunk, observation.ships_alive):
        checksum = zlib.crc32(np.ascontiguousarray(array).tobytes(), checksum)
    return checksum

import numpy as np

from core.models import Outcome, PublicShotResult
from core.rules import official_rules
from sdk.observation import ObservationState
from ui.debug_tools import DebugLayerCache, DebugSettings, build_debug_layer, neural_channel_names, selected_cell_details


def test_diagonal_debug_layer_uses_spacing_and_offset():
    rules = official_rules()
    state = ObservationState(rules)
    settings = DebugSettings(layer_index=3, diagonal_spacing=3, diagonal_offset=1)

    layer = build_debug_layer(rules, state.snapshot(), settings)

    assert layer.title == "Diagonal bands"
    assert layer.values[0, 2] == 1.0
    assert layer.values[0, 0] == 0.0
    assert layer.style == "mask"


def test_targeting_debug_layers_show_available_candidates_only():
    rules = official_rules()
    state = ObservationState(rules)
    state.apply_result(PublicShotResult((5, 5), Outcome.HIT))
    state.apply_result(PublicShotResult((5, 6), Outcome.HIT))
    state.apply_result(PublicShotResult((5, 4), Outcome.MISS))
    settings = DebugSettings(layer_index=7)

    layer = build_debug_layer(rules, state.snapshot(), settings)

    assert layer.title == "Line extensions from hit runs"
    assert layer.values[5, 7] == 1.0
    assert layer.values[5, 4] == 0.0


def test_neural_debug_layer_matches_named_encoder_channel():
    rules = official_rules()
    state = ObservationState(rules)
    state.apply_result(PublicShotResult((0, 0), Outcome.MISS))
    names = neural_channel_names(rules)
    settings = DebugSettings(layer_index=8, neural_channel=names.index("misses"))

    layer = build_debug_layer(rules, state.snapshot(), settings)

    assert layer.title == "Neural channel: misses"
    assert layer.values[0, 0] == 1.0
    assert layer.values[0, 1] == 0.0


def test_occupancy_debug_layer_returns_board_shaped_heat_values():
    rules = official_rules()
    state = ObservationState(rules)
    settings = DebugSettings(layer_index=1, max_samples=25)

    layer = build_debug_layer(rules, state.snapshot(), settings)

    assert layer.values.shape == (rules.rows, rules.cols)
    assert np.all(layer.values >= 0.0)
    assert np.all(layer.values <= len(rules.fleet))
    assert layer.style == "heat"
    assert "max samples: 25" in layer.details
    assert "occupancy used: 25" in layer.details
    assert "information used: 25" in layer.details


def test_information_debug_layer_shows_expected_split_information():
    rules = official_rules()
    state = ObservationState(rules)
    settings = DebugSettings(layer_index=2, max_samples=25)

    layer = build_debug_layer(rules, state.snapshot(), settings)

    assert layer.title == "Expected split information"
    assert layer.values.shape == (rules.rows, rules.cols)
    assert np.all(layer.values >= 0.0)
    assert layer.style == "heat"
    assert "max samples: 25" in layer.details
    assert "occupancy used: 25" in layer.details
    assert "information used: 25" in layer.details


def test_selected_cell_details_include_cell_state_and_layer_value():
    rules = official_rules()
    state = ObservationState(rules)
    state.apply_result(PublicShotResult((2, 3), Outcome.MISS))
    settings = DebugSettings(layer_index=4, selected_cell=(2, 3))
    layer = build_debug_layer(rules, state.snapshot(), settings)

    details = selected_cell_details(rules, state.snapshot(), layer, settings.selected_cell)

    assert "cell: (2, 3)" in details
    assert "state: miss" in details
    assert any("Available shots: 0.000" == line for line in details)


def test_debug_layer_cache_reuses_result_until_observation_or_settings_change():
    rules = official_rules()
    state = ObservationState(rules)
    settings = DebugSettings(layer_index=1, max_samples=25)
    cache = DebugLayerCache()

    first = cache.get(rules, state.snapshot(), settings)
    second = cache.get(rules, state.snapshot(), settings)

    assert second is first
    settings.selected_cell = (0, 0)
    assert cache.get(rules, state.snapshot(), settings) is first

    settings.max_samples = 50
    changed_by_settings = cache.get(rules, state.snapshot(), settings)
    assert changed_by_settings is not first

    state.apply_result(PublicShotResult((0, 0), Outcome.MISS))
    changed_by_observation = cache.get(rules, state.snapshot(), settings)
    assert changed_by_observation is not changed_by_settings

import numpy as np
import pytest

from core.models import Player
from ui.controller import PlacementController
from ui.geometry import BoardGeometry
from ui.pygame_app import _button_action, _best_marker_enabled, _placement_buttons, _practice_buttons, _toggle_theme
from ui.rendering import DARK_THEME, LIGHT_THEME, highest_value_cell, wrap_text


def test_pixel_to_grid_boundaries():
    geom = BoardGeometry(10, 20, 30)
    assert geom.pixel_to_cell((10, 20)) == (0, 0)
    assert geom.pixel_to_cell((309, 319)) == (9, 9)
    assert geom.pixel_to_cell((310, 20)) is None
    assert geom.pixel_to_cell((9, 20)) is None


def test_placement_preview_and_confirm():
    controller = PlacementController()
    cells, ok = controller.preview(0, 0)
    assert ok
    assert len(cells) == 5
    assert controller.place(0, 0)
    controller.rotate()
    assert not controller.place(0, 0)
    rows = {1: 1, 2: 2, 3: 3, 4: 4}
    while not controller.complete():
        slot = controller.remaining_slots()[0]
        controller.selected_slot = slot
        controller.orientation = "horizontal"
        assert controller.place(rows[slot], 0)
    assert controller.complete()


def test_complete_fleet_rejects_more_placements():
    controller = PlacementController()
    for slot, row in enumerate([0, 1, 2, 3, 4]):
        controller.selected_slot = slot
        controller.orientation = "horizontal"
        assert controller.place(row, 0)

    assert controller.complete()
    count = len(controller.placements)
    assert not controller.place(6, 0)
    assert len(controller.placements) == count


def test_ui_button_action_respects_disabled_buttons():
    assert _button_action((70, 620), _placement_buttons(ready=False)) is None
    assert _button_action((70, 620), _placement_buttons(ready=True)) == "confirm"
    assert _button_action((330, 685), _practice_buttons(reveal=False)) == "theme"
    assert _button_action((10, 10), _practice_buttons(reveal=False)) is None


def test_theme_toggle_round_trips():
    assert _toggle_theme(LIGHT_THEME) is DARK_THEME
    assert _toggle_theme(DARK_THEME) is LIGHT_THEME


def test_highest_value_cell_returns_first_positive_maximum():
    values = np.array([[0.0, 2.0], [2.0, 1.0]])

    assert highest_value_cell(values) == (0, 1)
    assert highest_value_cell(np.zeros((2, 2))) is None


def test_highest_value_cell_respects_eligible_mask():
    values = np.array([[9.0, 2.0], [4.0, 1.0]])
    available = np.array([[False, True], [True, True]])

    assert highest_value_cell(values, available) == (1, 0)
    assert highest_value_cell(values, np.zeros((2, 2), dtype=bool)) is None


def test_best_marker_is_only_enabled_for_probability_layers():
    assert _best_marker_enabled("occupancy")
    assert _best_marker_enabled("information")
    assert not _best_marker_enabled("neural")
    assert not _best_marker_enabled("diagonal")


def test_wrap_text_splits_long_unspaced_words():
    pygame = pytest.importorskip("pygame")
    pygame.font.init()
    max_width = 80

    lines = wrap_text(pygame, "examples.complete_bot:DocumentedExampleBot", 22, max_width)
    font = pygame.font.Font(None, 22)

    assert len(lines) > 1
    assert all(font.size(line)[0] <= max_width for line in lines)

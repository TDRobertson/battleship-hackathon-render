from __future__ import annotations

from datetime import datetime
from pathlib import Path
import random
import time
import traceback

from core.engine import GameEngine, InvalidAction
from core.models import Player
from runtime.bot_loading import build_bot
from sdk.observation import ObservationState, result_to_public
from core.rules import official_rules
from ui.controller import PlacementController
from ui.debug_tools import DebugLayerCache, DebugSettings, neural_channel_names, selected_cell_details
from ui.geometry import BoardGeometry
from ui.practice import new_practice_target, practice_fire
from ui.rendering import (
    DARK_THEME,
    LIGHT_THEME,
    UiTheme,
    draw_board,
    draw_debug_overlay,
    draw_own_board,
    draw_revealed_target_board,
    draw_target_observation,
    draw_text,
    draw_text_lines,
    wrap_text,
)


def run_app(
    seed: int = 123,
    bot_name: str = "starter",
    solo: bool = False,
) -> None:
    if solo:
        return run_practice_app(seed)

    try:
        import pygame
    except ImportError as exc:
        raise SystemExit("Install the UI extra first: pip install -e .[ui]") from exc

    pygame.init()
    screen = pygame.display.set_mode((1180, 760))
    pygame.display.set_caption("Battleship AI")
    clock = pygame.time.Clock()
    _log_ui(f"started seed={seed} bot={bot_name}")

    rules = official_rules()
    engine = GameEngine(rules)
    bot = build_bot(bot_name, seed)
    placement = PlacementController(rules)
    human_obs = ObservationState(rules)
    bot_obs = ObservationState(rules)
    bot_placements = bot.place_ships(rules, rules.thinking_seconds)
    bot_shots: dict[tuple[int, int], str] = {}
    screen_name = "placement"
    message = "Place your fleet"
    bot_remaining = rules.thinking_seconds
    last_tick = time.monotonic()
    debug = DebugSettings()
    debug_cache = DebugLayerCache()
    theme = LIGHT_THEME

    place_geom = BoardGeometry(60, 120, 42)
    own_geom = BoardGeometry(40, 135, 36)
    target_geom = BoardGeometry(460, 135, 36)
    debug_panel = (850, 88, 295, 640)

    running = True
    try:
        while running:
            now = time.monotonic()
            dt = now - last_tick
            last_tick = now
            if screen_name == "battle":
                if engine.active_player is Player.B and engine.winner is None:
                    bot_remaining = max(0.0, bot_remaining - dt)
                    if bot_remaining <= 0:
                        engine.forfeit(Player.B, "timeout")
                    else:
                        try:
                            shot = bot.choose_shot(bot_obs.snapshot(), bot_remaining)
                            result = engine.fire(Player.B, int(shot[0]), int(shot[1]))
                            bot_obs.apply_result(result_to_public(result))
                            bot_shots[result.shot] = result.outcome.value
                            message = f"Bot: {result.shot} {result.outcome.value}"
                        except Exception as exc:
                            engine.forfeit(Player.B, f"bot failure: {exc}")
                if engine.winner is not None:
                    screen_name = "gameover"

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    _log_ui("received pygame QUIT event")
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_q:
                        _log_ui("quit via Q")
                        running = False
                    if event.key == pygame.K_t:
                        theme = _toggle_theme(theme)
                    if screen_name == "battle":
                        if event.key == pygame.K_d:
                            debug.enabled = not debug.enabled
                        if event.key == pygame.K_TAB:
                            debug.next_focus()
                        if event.key == pygame.K_RIGHT:
                            debug.next_layer()
                        if event.key == pygame.K_LEFT:
                            debug.previous_layer()
                        if event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                            debug.adjust_spacing(1)
                        if event.key in (pygame.K_MINUS, pygame.K_UNDERSCORE):
                            debug.adjust_spacing(-1)
                        if event.key == pygame.K_PERIOD:
                            debug.adjust_offset(1)
                        if event.key == pygame.K_COMMA:
                            debug.adjust_offset(-1)
                        if event.key == pygame.K_PAGEUP:
                            debug.adjust_samples(100)
                        if event.key == pygame.K_PAGEDOWN:
                            debug.adjust_samples(-100)
                        if event.key == pygame.K_c:
                            debug.next_neural_channel(rules)
                    if screen_name == "placement" and event.key == pygame.K_r:
                        placement.rotate()
                    if screen_name == "placement" and event.key == pygame.K_u:
                        placement.undo()
                    if screen_name == "gameover" and event.key == pygame.K_RETURN:
                        _log_ui("restart via Enter")
                        return run_app(seed, bot_name)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    pos = event.pos
                    if screen_name == "placement":
                        cell = place_geom.pixel_to_cell(pos)
                        if cell:
                            placement.place(*cell)
                        else:
                            action = _button_action(pos, _placement_buttons(placement.complete()))
                            if action == "rotate":
                                placement.rotate()
                            elif action == "undo":
                                placement.undo()
                            elif action == "reset":
                                placement.reset()
                            elif action == "theme":
                                theme = _toggle_theme(theme)
                            elif action == "quit":
                                running = False
                            elif action == "confirm" and placement.complete():
                                try:
                                    engine.place_fleet(Player.A, placement.placements)
                                    engine.place_fleet(Player.B, bot_placements)
                                    screen_name = "battle"
                                    message = "Your turn"
                                except InvalidAction as exc:
                                    message = str(exc)
                    elif screen_name == "battle":
                        action = _button_action(pos, _battle_buttons())
                        if action == "theme":
                            theme = _toggle_theme(theme)
                            continue
                        if action == "quit":
                            running = False
                            continue
                        if _handle_debug_button(pos, debug, rules, debug_panel):
                            continue
                        debug_cell = _debug_cell_from_click(pos, debug, own_geom, target_geom)
                        if debug_cell is not None:
                            debug.selected_cell = debug_cell
                        if engine.active_player is not Player.A:
                            continue
                        cell = target_geom.pixel_to_cell(pos)
                        if cell and human_obs.snapshot().available_shots()[cell]:
                            try:
                                result = engine.fire(Player.A, *cell)
                                human_obs.apply_result(result_to_public(result))
                                message = f"You: {result.shot} {result.outcome.value}"
                            except InvalidAction as exc:
                                message = str(exc)
                        if engine.winner is not None:
                            screen_name = "gameover"

            screen.fill(theme.background)
            if screen_name == "placement":
                draw_text(pygame, screen, "Place Fleet", (60, 40), 44, theme.text)
                draw_text(pygame, screen, "Untimed", (780, 46), 30, theme.text)
                draw_text(pygame, screen, f"Bot: {bot_name}", (560, 46), 30, theme.text)
                draw_text(pygame, screen, "Hotkeys: R rotate, U undo, T theme, Q quit", (560, 92), 22, theme.subtle_text)
                draw_board(pygame, screen, place_geom, theme=theme)
                for p in placement.placements:
                    for row, col in placement.cells_for(p):
                        pygame.draw.rect(screen, theme.ship, place_geom.cell_rect(row, col))
                mouse_cell = place_geom.pixel_to_cell(pygame.mouse.get_pos())
                if mouse_cell and not placement.complete():
                    cells, ok = placement.preview(*mouse_cell)
                    for row, col in cells:
                        pygame.draw.rect(screen, theme.valid if ok else theme.invalid, place_geom.cell_rect(row, col), 4)
                draw_text(pygame, screen, f"Slot {placement.selected_slot} length {rules.ship_length(placement.selected_slot)}", (560, 140), 30, theme.text)
                draw_text(pygame, screen, f"Orientation {placement.orientation}", (560, 180), 26, theme.text)
                draw_text(pygame, screen, f"Remaining {placement.remaining_slots()}", (560, 220), 26, theme.text)
                for button in _placement_buttons(placement.complete()):
                    _button(pygame, screen, *button, theme=theme)
                _draw_wrapped_message(pygame, screen, message, (560, 300), 520, theme)
            elif screen_name == "battle":
                focus_obs = bot_obs.snapshot() if debug.focus == "bot-target" else human_obs.snapshot()
                layer = debug_cache.get(rules, focus_obs, debug)
                debug_geom = own_geom if debug.focus == "bot-target" else target_geom
                draw_text(pygame, screen, "Own Board", (40, 80), 32, theme.text)
                draw_text(pygame, screen, "Target Board", (460, 80), 32, theme.text)
                draw_text(pygame, screen, "You Untimed", (40, 40), 26, theme.text)
                draw_text(pygame, screen, f"Bot {bot_remaining:05.1f}s", (200, 40), 26, theme.text)
                draw_text(pygame, screen, f"Active {engine.active_player.value}", (360, 40), 26, theme.text)
                for button in _battle_buttons():
                    _button(pygame, screen, *button, theme=theme)
                draw_own_board(pygame, screen, own_geom, engine.fleet_cells(Player.A), bot_shots, theme)
                draw_target_observation(pygame, screen, target_geom, human_obs.snapshot(), theme)
                draw_debug_overlay(
                    pygame,
                    screen,
                    debug_geom,
                    layer.values,
                    layer.style,
                    debug.selected_cell if debug.enabled else None,
                    theme,
                    show_best_marker=_best_marker_enabled(debug.layer),
                    best_marker_mask=focus_obs.available_shots(),
                )
                draw_text(pygame, screen, f"Enemy ships alive {human_obs.ships_alive.tolist()}", (460, 515), 24, theme.text)
                _draw_wrapped_message(pygame, screen, message, (40, 515), 380, theme)
                _draw_debug_panel(pygame, screen, debug_panel, debug, rules, focus_obs, layer, theme)
            elif screen_name == "gameover":
                winner = engine.winner.value if engine.winner else "?"
                draw_text(pygame, screen, "Own Board", (40, 80), 32, theme.text)
                draw_text(pygame, screen, "Enemy Board", (460, 80), 32, theme.text)
                draw_text(pygame, screen, f"Winner: {winner}", (40, 40), 36, theme.hit)
                draw_text(pygame, screen, engine.termination_reason or "ended", (220, 48), 24, theme.text)
                draw_own_board(pygame, screen, own_geom, engine.fleet_cells(Player.A), bot_shots, theme)
                draw_revealed_target_board(pygame, screen, target_geom, engine.fleet_cells(Player.B), human_obs.snapshot(), theme)
                draw_text(pygame, screen, "Enter restarts. T theme. Q quits.", (40, 540), 26, theme.text)
            pygame.display.flip()
            clock.tick(30)
    except Exception:
        _log_ui("crash\n" + traceback.format_exc())
        raise
    finally:
        _log_ui("pygame quit")
        pygame.quit()


def run_practice_app(seed: int = 123) -> None:
    try:
        import pygame
    except ImportError as exc:
        raise SystemExit("Install the UI extra first: pip install -e .[ui]") from exc

    pygame.init()
    screen = pygame.display.set_mode((940, 760))
    pygame.display.set_caption("Battleship Target Practice")
    clock = pygame.time.Clock()
    _log_ui(f"started target practice seed={seed}")

    rules = official_rules()
    rng = random.Random(seed)
    target = new_practice_target(rules, rng)
    observation = ObservationState(rules)
    debug = DebugSettings()
    debug_cache = DebugLayerCache()
    theme = LIGHT_THEME
    debug.focus_index = 0
    debug_panel = (610, 88, 295, 640)
    target_geom = BoardGeometry(90, 135, 42)
    reveal = False
    message = "Target practice"

    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    _log_ui("received pygame QUIT event")
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_q:
                        _log_ui("quit via Q")
                        running = False
                    elif event.key == pygame.K_t:
                        theme = _toggle_theme(theme)
                    elif event.key == pygame.K_r:
                        target = new_practice_target(rules, rng)
                        observation = ObservationState(rules)
                        debug.selected_cell = None
                        debug_cache.clear()
                        message = "New random target"
                    elif event.key == pygame.K_v:
                        reveal = not reveal
                    elif event.key == pygame.K_d:
                        debug.enabled = not debug.enabled
                    elif event.key == pygame.K_RIGHT:
                        debug.next_layer()
                    elif event.key == pygame.K_LEFT:
                        debug.previous_layer()
                    elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                        debug.adjust_spacing(1)
                    elif event.key in (pygame.K_MINUS, pygame.K_UNDERSCORE):
                        debug.adjust_spacing(-1)
                    elif event.key == pygame.K_PERIOD:
                        debug.adjust_offset(1)
                    elif event.key == pygame.K_COMMA:
                        debug.adjust_offset(-1)
                    elif event.key == pygame.K_PAGEUP:
                        debug.adjust_samples(100)
                    elif event.key == pygame.K_PAGEDOWN:
                        debug.adjust_samples(-100)
                    elif event.key == pygame.K_c:
                        debug.next_neural_channel(rules)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    pos = event.pos
                    action = _button_action(pos, _practice_buttons(reveal))
                    if action == "reveal":
                        reveal = not reveal
                        continue
                    if action == "reset":
                        target = new_practice_target(rules, rng)
                        observation = ObservationState(rules)
                        debug.selected_cell = None
                        debug_cache.clear()
                        message = "New random target"
                        continue
                    if action == "theme":
                        theme = _toggle_theme(theme)
                        continue
                    if action == "quit":
                        running = False
                        continue
                    if _handle_debug_button(pos, debug, rules, debug_panel):
                        continue
                    cell = target_geom.pixel_to_cell(pos)
                    if cell is not None:
                        debug.selected_cell = cell
                        if observation.snapshot().available_shots()[cell]:
                            try:
                                result = practice_fire(target, observation, cell)
                                message = f"Shot {result.shot}: {result.outcome.value}"
                                if target.all_sunk:
                                    message = f"{message}. Fleet sunk. Press R for a new target."
                            except ValueError as exc:
                                message = str(exc)

            snapshot = observation.snapshot()
            layer = debug_cache.get(rules, snapshot, debug)
            screen.fill(theme.background)
            draw_text(pygame, screen, "Target Practice", (90, 40), 42, theme.text)
            draw_text(pygame, screen, f"Seed {seed}", (360, 48), 24, theme.text)
            draw_text(pygame, screen, "Hotkeys: V reveal, R reset, D debug, T theme, Q quit", (90, 92), 22, theme.subtle_text)
            for button in _practice_buttons(reveal):
                _button(pygame, screen, *button, theme=theme)
            if reveal:
                draw_revealed_target_board(pygame, screen, target_geom, target.fleet_cells, snapshot, theme)
            else:
                draw_target_observation(pygame, screen, target_geom, snapshot, theme)
            draw_debug_overlay(
                pygame,
                screen,
                target_geom,
                layer.values,
                layer.style,
                debug.selected_cell if debug.enabled else None,
                theme,
                show_best_marker=_best_marker_enabled(debug.layer),
                best_marker_mask=snapshot.available_shots(),
            )
            _draw_wrapped_message(pygame, screen, message, (90, 580), 480, theme)
            draw_text(pygame, screen, f"Ships alive {snapshot.ships_alive.tolist()}", (90, 626), 24, theme.text)
            _draw_debug_panel(pygame, screen, debug_panel, debug, rules, snapshot, layer, theme)
            pygame.display.flip()
            clock.tick(30)
    except Exception:
        _log_ui("practice crash\n" + traceback.format_exc())
        raise
    finally:
        _log_ui("pygame quit")
        pygame.quit()


def _button(
    pygame,
    screen,
    rect,
    label: str,
    action: str | None = None,
    enabled: bool = True,
    active: bool = False,
    theme: UiTheme = LIGHT_THEME,
) -> None:
    mouse_pos = pygame.mouse.get_pos()
    if not enabled:
        color = theme.button_disabled
    elif active:
        color = theme.button_active
    elif _contains(rect, mouse_pos):
        color = theme.button_hover
    else:
        color = theme.button
    pygame.draw.rect(screen, color, rect, border_radius=6)
    pygame.draw.rect(screen, theme.border, rect, 1, border_radius=6)

    font = pygame.font.Font(None, 22)
    text = font.render(label, True, theme.text if enabled else theme.subtle_text)
    text_rect = text.get_rect(center=(rect[0] + rect[2] // 2, rect[1] + rect[3] // 2))
    screen.blit(text, text_rect)


def _draw_debug_panel(pygame, screen, rect, debug: DebugSettings, rules, observation, layer, theme: UiTheme) -> None:
    x, y, w, h = rect
    pygame.draw.rect(screen, theme.panel, rect, border_radius=8)
    pygame.draw.rect(screen, theme.border, rect, 1, border_radius=8)
    draw_text(pygame, screen, "Debug Helpers", (x + 14, y + 14), 30, theme.text)
    status = "on" if debug.enabled else "off"
    draw_text_lines(
        pygame,
        screen,
        (
            f"status: {status}",
            f"focus: {debug.focus}",
            f"layer: {debug.layer}",
            f"max value: {layer.maximum:.3f}",
        ),
        (x + 14, y + 52),
        20,
        theme.text,
        22,
    )
    for button in _debug_buttons(rect, debug):
        _button(pygame, screen, *button, theme=theme)
    y2 = y + 324
    neural_name = neural_channel_names(rules)[debug.neural_channel % len(neural_channel_names(rules))]
    control_lines = _debug_control_lines(debug, neural_name, layer.details)
    _draw_wrapped_lines(pygame, screen, control_lines, (x + 14, y2), w - 28, 17, theme.text, max_lines=7)
    details = selected_cell_details(rules, observation, layer, debug.selected_cell)
    _draw_wrapped_lines(pygame, screen, details, (x + 14, y + 552), w - 28, 17, theme.text, max_lines=4)
    draw_text_lines(
        pygame,
        screen,
        ("Keys: D debug, T theme, Tab focus", "Arrows layer, C channel", "+/- spacing, </> offset"),
        (x + 14, y + h - 68),
        17,
        theme.subtle_text,
        20,
    )


def _debug_control_lines(debug: DebugSettings, neural_name: str, layer_details: tuple[str, ...]) -> tuple[str, ...]:
    if debug.layer == "diagonal":
        return (
            f"spacing: {debug.diagonal_spacing}",
            f"offset: {debug.diagonal_offset}",
        ) + layer_details
    if debug.layer == "neural":
        return (f"neural: {neural_name}",) + layer_details
    return layer_details


def _best_marker_enabled(layer: str) -> bool:
    return layer in ("occupancy", "information")


def _debug_buttons(panel_rect, debug: DebugSettings | None = None) -> list[tuple[tuple[int, int, int, int], str, str, bool, bool]]:
    x, y, _, _ = panel_rect
    debug_active = bool(debug and debug.enabled)
    return [
        ((x + 12, y + 146, 88, 32), "Layer <", "layer-prev", True, False),
        ((x + 104, y + 146, 88, 32), "Layer >", "layer-next", True, False),
        ((x + 196, y + 146, 88, 32), "Focus", "focus", True, False),
        ((x + 12, y + 184, 88, 32), "Debug", "debug", True, debug_active),
        ((x + 104, y + 184, 88, 32), "Space -", "spacing-down", True, False),
        ((x + 196, y + 184, 88, 32), "Space +", "spacing-up", True, False),
        ((x + 12, y + 222, 88, 32), "Offset -", "offset-down", True, False),
        ((x + 104, y + 222, 88, 32), "Offset +", "offset-up", True, False),
        ((x + 196, y + 222, 88, 32), "Channel", "channel", True, False),
        ((x + 12, y + 260, 134, 32), "Samples -", "samples-down", True, False),
        ((x + 152, y + 260, 132, 32), "Samples +", "samples-up", True, False),
    ]


def _handle_debug_button(pos, debug: DebugSettings, rules, panel_rect) -> bool:
    action = _button_action(pos, _debug_buttons(panel_rect, debug))
    if action is None:
        return False
    if action == "layer-prev":
        debug.previous_layer()
    elif action == "layer-next":
        debug.next_layer()
    elif action == "focus":
        debug.next_focus()
    elif action == "debug":
        debug.enabled = not debug.enabled
    elif action == "spacing-down":
        debug.adjust_spacing(-1)
    elif action == "spacing-up":
        debug.adjust_spacing(1)
    elif action == "offset-down":
        debug.adjust_offset(-1)
    elif action == "offset-up":
        debug.adjust_offset(1)
    elif action == "channel":
        debug.next_neural_channel(rules)
    elif action == "samples-down":
        debug.adjust_samples(-100)
    elif action == "samples-up":
        debug.adjust_samples(100)
    return True


def _placement_buttons(ready: bool) -> list[tuple[tuple[int, int, int, int], str, str, bool, bool]]:
    return [
        ((60, 560, 118, 38), "Rotate", "rotate", True, False),
        ((190, 560, 118, 38), "Undo", "undo", True, False),
        ((320, 560, 118, 38), "Reset", "reset", True, False),
        ((60, 610, 178, 40), "Confirm", "confirm", ready, ready),
        ((250, 610, 118, 40), "Theme", "theme", True, False),
        ((380, 610, 118, 40), "Quit", "quit", True, False),
    ]


def _battle_buttons() -> list[tuple[tuple[int, int, int, int], str, str, bool, bool]]:
    return [
        ((660, 38, 86, 34), "Theme", "theme", True, False),
        ((756, 38, 70, 34), "Quit", "quit", True, False),
    ]


def _practice_buttons(reveal: bool) -> list[tuple[tuple[int, int, int, int], str, str, bool, bool]]:
    return [
        ((90, 675, 104, 38), "Reveal", "reveal", True, reveal),
        ((206, 675, 104, 38), "Reset", "reset", True, False),
        ((322, 675, 104, 38), "Theme", "theme", True, False),
        ((438, 675, 82, 38), "Quit", "quit", True, False),
    ]


def _button_action(pos, buttons) -> str | None:
    for rect, _label, action, enabled, _active in buttons:
        if _contains(rect, pos):
            return action if enabled else None
    return None


def _draw_wrapped_message(pygame, screen, message: str, pos: tuple[int, int], width: int, theme: UiTheme) -> None:
    _draw_wrapped_lines(pygame, screen, (message,), pos, width, 22, theme.text, max_lines=2)


def _draw_wrapped_lines(
    pygame,
    screen,
    lines,
    pos: tuple[int, int],
    width: int,
    size: int,
    color,
    max_lines: int,
) -> None:
    rendered: list[str] = []
    for line in lines:
        rendered.extend(wrap_text(pygame, str(line), size, width))
    if len(rendered) > max_lines:
        rendered = rendered[: max_lines - 1] + ["..."]
    draw_text_lines(pygame, screen, tuple(rendered), pos, size, color, int(size * 1.18))


def _toggle_theme(theme: UiTheme) -> UiTheme:
    return DARK_THEME if theme.name == "light" else LIGHT_THEME


def _debug_cell_from_click(pos, debug: DebugSettings, own_geom: BoardGeometry, target_geom: BoardGeometry):
    geom = own_geom if debug.focus == "bot-target" else target_geom
    return geom.pixel_to_cell(pos)


def _contains(rect, pos) -> bool:
    x, y, w, h = rect
    return x <= pos[0] <= x + w and y <= pos[1] <= y + h


def _log_ui(message: str) -> None:
    try:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with (log_dir / "ui.log").open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")
    except OSError:
        pass



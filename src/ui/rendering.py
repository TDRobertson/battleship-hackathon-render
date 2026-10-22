from __future__ import annotations

from dataclasses import dataclass

from sdk.observation import ObservationSnapshot
from ui.geometry import BoardGeometry

WHITE = (244, 247, 250)
INK = (24, 32, 43)
GRID = (132, 146, 166)
WATER = (157, 205, 226)
SHIP = (90, 103, 118)
MISS = (236, 240, 244)
HIT = (220, 71, 71)
SUNK = (98, 38, 38)
VALID = (78, 171, 112)
INVALID = (215, 78, 78)
DEBUG_LOW = (247, 230, 111)
DEBUG_HIGH = (206, 60, 82)
DEBUG_MASK = (54, 126, 197)
DEBUG_SELECTED = (20, 24, 31)


@dataclass(frozen=True, slots=True)
class UiTheme:
    name: str
    background: tuple[int, int, int]
    panel: tuple[int, int, int]
    panel_alt: tuple[int, int, int]
    text: tuple[int, int, int]
    subtle_text: tuple[int, int, int]
    border: tuple[int, int, int]
    water: tuple[int, int, int]
    ship: tuple[int, int, int]
    miss: tuple[int, int, int]
    hit: tuple[int, int, int]
    sunk: tuple[int, int, int]
    valid: tuple[int, int, int]
    invalid: tuple[int, int, int]
    button: tuple[int, int, int]
    button_hover: tuple[int, int, int]
    button_disabled: tuple[int, int, int]
    button_active: tuple[int, int, int]
    debug_low: tuple[int, int, int]
    debug_high: tuple[int, int, int]
    debug_mask: tuple[int, int, int]
    debug_selected: tuple[int, int, int]


LIGHT_THEME = UiTheme(
    name="light",
    background=WHITE,
    panel=(230, 235, 240),
    panel_alt=(218, 225, 233),
    text=INK,
    subtle_text=(82, 96, 112),
    border=GRID,
    water=WATER,
    ship=SHIP,
    miss=MISS,
    hit=HIT,
    sunk=SUNK,
    valid=VALID,
    invalid=INVALID,
    button=(238, 242, 246),
    button_hover=(248, 250, 252),
    button_disabled=(200, 204, 208),
    button_active=(186, 214, 239),
    debug_low=DEBUG_LOW,
    debug_high=DEBUG_HIGH,
    debug_mask=DEBUG_MASK,
    debug_selected=DEBUG_SELECTED,
)

DARK_THEME = UiTheme(
    name="dark",
    background=(21, 26, 34),
    panel=(34, 43, 55),
    panel_alt=(45, 56, 70),
    text=(235, 241, 247),
    subtle_text=(174, 186, 200),
    border=(92, 109, 128),
    water=(35, 92, 122),
    ship=(128, 142, 157),
    miss=(221, 226, 232),
    hit=(239, 92, 92),
    sunk=(151, 54, 54),
    valid=(87, 190, 128),
    invalid=(236, 98, 98),
    button=(51, 63, 78),
    button_hover=(63, 78, 96),
    button_disabled=(62, 68, 77),
    button_active=(50, 98, 137),
    debug_low=(255, 218, 91),
    debug_high=(255, 92, 123),
    debug_mask=(88, 161, 236),
    debug_selected=(248, 250, 252),
)


def draw_board(pygame, surface, geom: BoardGeometry, fill=None, theme: UiTheme = LIGHT_THEME) -> None:
    fill = theme.water if fill is None else fill
    pygame.draw.rect(surface, fill, (geom.x, geom.y, geom.size, geom.size))
    draw_grid(pygame, surface, geom, theme)


def draw_grid(pygame, surface, geom: BoardGeometry, theme: UiTheme = LIGHT_THEME) -> None:
    for i in range(geom.rows + 1):
        y = geom.y + i * geom.cell
        x = geom.x + i * geom.cell
        pygame.draw.line(surface, theme.border, (geom.x, y), (geom.x + geom.size, y), 1)
        pygame.draw.line(surface, theme.border, (x, geom.y), (x, geom.y + geom.size), 1)


def draw_debug_overlay(
    pygame,
    surface,
    geom: BoardGeometry,
    values,
    style: str,
    selected_cell: tuple[int, int] | None = None,
    theme: UiTheme = LIGHT_THEME,
    show_best_marker: bool = False,
    best_marker_mask=None,
) -> None:
    if style == "none":
        return
    max_value = float(values.max()) if getattr(values, "size", 0) else 0.0
    font = pygame.font.Font(None, max(14, geom.cell // 3))
    for row in range(geom.rows):
        for col in range(geom.cols):
            value = float(values[row, col])
            if value <= 0.0:
                continue
            rect = geom.cell_rect(row, col)
            alpha = 105 if style == "mask" else int(45 + 165 * min(1.0, value / max(max_value, 1e-9)))
            color = theme.debug_mask if style == "mask" else _blend(theme.debug_low, theme.debug_high, min(1.0, value / max(max_value, 1e-9)))
            overlay = pygame.Surface((geom.cell, geom.cell), pygame.SRCALPHA)
            overlay.fill((*color, alpha))
            surface.blit(overlay, rect[:2])
            if style == "heat" and geom.cell >= 32:
                label = f"{value:.2f}" if value < 10 else f"{value:.0f}"
                text = font.render(label, True, theme.text)
                surface.blit(text, (rect[0] + 3, rect[1] + 3))
    if selected_cell is not None:
        pygame.draw.rect(surface, theme.debug_selected, geom.cell_rect(*selected_cell), 3)
    if show_best_marker:
        best_cell = highest_value_cell(values, best_marker_mask)
        if best_cell is not None:
            _draw_best_marker(pygame, surface, geom.cell_rect(*best_cell), theme)
    draw_grid(pygame, surface, geom, theme)


def draw_target_observation(pygame, surface, geom: BoardGeometry, obs: ObservationSnapshot, theme: UiTheme = LIGHT_THEME) -> None:
    draw_board(pygame, surface, geom, theme=theme)
    for row in range(geom.rows):
        for col in range(geom.cols):
            rect = geom.cell_rect(row, col)
            if obs.misses[row, col]:
                pygame.draw.circle(surface, theme.miss, (rect[0] + geom.cell // 2, rect[1] + geom.cell // 2), geom.cell // 5)
            elif obs.hits[row, col]:
                pygame.draw.rect(surface, theme.hit, rect)
            elif obs.sunk[row, col]:
                pygame.draw.rect(surface, theme.sunk, rect)
    draw_grid(pygame, surface, geom, theme)


def draw_own_board(pygame, surface, geom: BoardGeometry, fleet_cells, incoming_shots, theme: UiTheme = LIGHT_THEME) -> None:
    draw_board(pygame, surface, geom, theme=theme)
    for cells in fleet_cells.values():
        for row, col in cells:
            pygame.draw.rect(surface, theme.ship, geom.cell_rect(row, col))
    for (row, col), outcome in incoming_shots.items():
        color = theme.miss if outcome == "miss" else theme.hit
        pygame.draw.circle(surface, color, (geom.x + col * geom.cell + geom.cell // 2, geom.y + row * geom.cell + geom.cell // 2), geom.cell // 4)
        pygame.draw.circle(surface, theme.border, (geom.x + col * geom.cell + geom.cell // 2, geom.y + row * geom.cell + geom.cell // 2), geom.cell // 4, 1)
    draw_grid(pygame, surface, geom, theme)


def draw_revealed_target_board(pygame, surface, geom: BoardGeometry, fleet_cells, obs: ObservationSnapshot, theme: UiTheme = LIGHT_THEME) -> None:
    draw_board(pygame, surface, geom, theme=theme)
    for cells in fleet_cells.values():
        for row, col in cells:
            pygame.draw.rect(surface, theme.ship, geom.cell_rect(row, col))
    for row in range(geom.rows):
        for col in range(geom.cols):
            rect = geom.cell_rect(row, col)
            if obs.misses[row, col]:
                pygame.draw.circle(surface, theme.miss, (rect[0] + geom.cell // 2, rect[1] + geom.cell // 2), geom.cell // 5)
                pygame.draw.circle(surface, theme.border, (rect[0] + geom.cell // 2, rect[1] + geom.cell // 2), geom.cell // 5, 1)
            elif obs.hits[row, col]:
                pygame.draw.rect(surface, theme.hit, rect)
            elif obs.sunk[row, col]:
                pygame.draw.rect(surface, theme.sunk, rect)
    draw_grid(pygame, surface, geom, theme)


def draw_text(pygame, surface, text: str, pos: tuple[int, int], size: int = 24, color=INK) -> None:
    font = pygame.font.Font(None, size)
    surface.blit(font.render(text, True, color), pos)


def draw_text_lines(
    pygame,
    surface,
    lines: list[str] | tuple[str, ...],
    pos: tuple[int, int],
    size: int = 22,
    color=INK,
    line_height: int | None = None,
) -> None:
    y = pos[1]
    step = line_height or int(size * 1.15)
    for line in lines:
        draw_text(pygame, surface, line, (pos[0], y), size, color)
        y += step


def wrap_text(pygame, text: str, size: int, max_width: int) -> list[str]:
    font = pygame.font.Font(None, size)
    words: list[str] = []
    for raw_word in str(text).split():
        words.extend(_split_long_word(font, raw_word, max_width))
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if font.size(candidate)[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _split_long_word(font, word: str, max_width: int) -> list[str]:
    if font.size(word)[0] <= max_width:
        return [word]
    chunks: list[str] = []
    current = ""
    for char in word:
        candidate = current + char
        if current and font.size(candidate)[0] > max_width:
            chunks.append(current)
            current = char
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def highest_value_cell(values, eligible_mask=None) -> tuple[int, int] | None:
    if getattr(values, "size", 0) == 0:
        return None
    if eligible_mask is None:
        eligible_values = values
    else:
        eligible_values = values.copy()
        eligible_values[~eligible_mask.astype(bool)] = 0.0
    max_value = float(eligible_values.max())
    if max_value <= 0.0:
        return None
    coords = (eligible_values == max_value).nonzero()
    if len(coords[0]) == 0:
        return None
    return int(coords[0][0]), int(coords[1][0])


def _draw_best_marker(pygame, surface, rect: tuple[int, int, int, int], theme: UiTheme) -> None:
    x, y, w, h = rect
    center = (round(x + w / 2), round(y + h / 2))
    radius = max(5, round(min(w, h) * 0.18))
    pygame.draw.circle(surface, theme.debug_selected, center, radius)
    pygame.draw.circle(surface, theme.border, center, radius, 2)


def _blend(low: tuple[int, int, int], high: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a + (b - a) * t) for a, b in zip(low, high))

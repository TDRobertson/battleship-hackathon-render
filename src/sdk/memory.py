from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.models import Coord, Player, PublicShotResult
from core.rules import Rules


_MAX_RECENT_SHOTS = 500
_MAX_OPENING_SHOTS = 100


@dataclass(slots=True)
class MemorySession:
    """A loaded per-bot/per-opponent memory document."""

    path: Path | None
    memory: dict[str, Any]

    def save(self) -> None:
        if self.path is None:
            return
        save_memory(self.path, self.memory)


@dataclass(slots=True)
class OpponentStatsTracker:
    """Collect opponent-shot features during one match."""

    rules: Rules
    player: Player
    memory: dict[str, Any]
    opponent_shots: list[Coord]

    def observe(self, result: PublicShotResult) -> None:
        self.opponent_shots.append(result.shot)

    def finish(self, won: bool, turns: int) -> None:
        stats = self.memory.setdefault("_stats", {})
        stats["games"] = int(stats.get("games", 0)) + 1
        stats["wins"] = int(stats.get("wins", 0)) + int(won)
        stats["losses"] = int(stats.get("losses", 0)) + int(not won)
        stats["turns_total"] = int(stats.get("turns_total", 0)) + int(turns)
        stats["avg_turns"] = stats["turns_total"] / stats["games"]
        stats["opponent_shots_last_game"] = [list(shot) for shot in self.opponent_shots]
        stats["opponent_shots_observed"] = int(stats.get("opponent_shots_observed", 0)) + len(self.opponent_shots)

        recent = list(stats.get("opponent_recent_shots", []))
        recent.extend([list(shot) for shot in self.opponent_shots])
        stats["opponent_recent_shots"] = recent[-_MAX_RECENT_SHOTS:]

        if self.opponent_shots:
            openings = list(stats.get("opponent_opening_shots", []))
            openings.append(list(self.opponent_shots[0]))
            stats["opponent_opening_shots"] = openings[-_MAX_OPENING_SHOTS:]

        self._finish_geometry_stats(stats)
        self._finish_layout_stats(stats, won)

    def _finish_geometry_stats(self, stats: dict[str, Any]) -> None:
        center = int(stats.get("opponent_center_shots", 0))
        edge = int(stats.get("opponent_edge_shots", 0))
        corner = int(stats.get("opponent_corner_shots", 0))
        parity_first_20 = int(stats.get("opponent_parity_shots_first_20", 0))
        first_20 = int(stats.get("opponent_shots_first_20", 0))

        for index, shot in enumerate(self.opponent_shots):
            if is_center_cell(self.rules, shot):
                center += 1
            if is_edge_cell(self.rules, shot):
                edge += 1
            if is_corner_cell(self.rules, shot):
                corner += 1
            if index < 20:
                first_20 += 1
                if is_parity_cell(shot):
                    parity_first_20 += 1

        total = int(stats.get("opponent_shots_observed", 0))
        stats["opponent_center_shots"] = center
        stats["opponent_edge_shots"] = edge
        stats["opponent_corner_shots"] = corner
        stats["opponent_parity_shots_first_20"] = parity_first_20
        stats["opponent_shots_first_20"] = first_20
        stats["opponent_center_rate"] = center / total if total else 0.0
        stats["opponent_edge_rate"] = edge / total if total else 0.0
        stats["opponent_corner_rate"] = corner / total if total else 0.0
        stats["opponent_parity_rate_first_20"] = parity_first_20 / first_20 if first_20 else 0.0

    def _finish_layout_stats(self, stats: dict[str, Any], won: bool) -> None:
        layout_name = self.memory.get("current_layout") or self.memory.get("_current_layout")
        if not layout_name:
            return
        layouts = stats.setdefault("layouts", {})
        layout = layouts.setdefault(str(layout_name), {})
        layout["games"] = int(layout.get("games", 0)) + 1
        layout["wins"] = int(layout.get("wins", 0)) + int(won)
        layout["losses"] = int(layout.get("losses", 0)) + int(not won)
        layout["opponent_shots_total"] = int(layout.get("opponent_shots_total", 0)) + len(self.opponent_shots)
        layout["avg_opponent_shots"] = layout["opponent_shots_total"] / layout["games"]


def load_memory_session(memory_dir: str | Path | None, bot_name: str, opponent_name: str) -> MemorySession:
    if memory_dir is None:
        return MemorySession(None, {})
    path = memory_path(memory_dir, bot_name, opponent_name)
    return MemorySession(path, load_memory(path))


def memory_path(memory_dir: str | Path, bot_name: str, opponent_name: str) -> Path:
    return Path(memory_dir) / sanitize_name(bot_name) / f"{sanitize_name(opponent_name)}.json"


def load_memory(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_memory(path: str | Path, memory: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(_jsonable(memory), indent=2, sort_keys=True))
    tmp_path.replace(path)


def sanitize_name(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name)).strip("._")
    return sanitized or "bot"


def is_center_cell(rules: Rules, coord: Coord) -> bool:
    row, col = coord
    center_rows = {(rules.rows - 1) // 2, rules.rows // 2}
    center_cols = {(rules.cols - 1) // 2, rules.cols // 2}
    return row in center_rows and col in center_cols


def is_edge_cell(rules: Rules, coord: Coord) -> bool:
    row, col = coord
    return row in (0, rules.rows - 1) or col in (0, rules.cols - 1)


def is_corner_cell(rules: Rules, coord: Coord) -> bool:
    row, col = coord
    return row in (0, rules.rows - 1) and col in (0, rules.cols - 1)


def is_parity_cell(coord: Coord) -> bool:
    row, col = coord
    return (row + col) % 2 == 0


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)

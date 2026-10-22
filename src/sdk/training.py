from __future__ import annotations

import csv
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any


@dataclass(frozen=True, slots=True)
class MetricRecord:
    run: str
    step: int
    name: str
    value: float
    phase: str = "train"
    episode: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricHistory:
    records: list[MetricRecord] = field(default_factory=list)

    def log(
        self,
        name: str,
        value: float,
        step: int,
        phase: str = "train",
        run: str = "default",
        episode: int | None = None,
        **metadata: Any,
    ) -> None:
        self.records.append(MetricRecord(run, int(step), name, float(value), phase, episode, dict(metadata)))

    def log_many(
        self,
        metrics: dict[str, float],
        step: int,
        phase: str = "train",
        run: str = "default",
        episode: int | None = None,
        **metadata: Any,
    ) -> None:
        for name, value in metrics.items():
            self.log(name, value, step, phase=phase, run=run, episode=episode, **metadata)

    def series(self, name: str, phase: str | None = None, run: str | None = None) -> list[tuple[int, float]]:
        records = [
            record
            for record in self.records
            if record.name == name and (phase is None or record.phase == phase) and (run is None or record.run == run)
        ]
        return [(record.step, record.value) for record in sorted(records, key=lambda item: item.step)]

    def values(self, name: str, phase: str | None = None, run: str | None = None) -> list[float]:
        return [value for _, value in self.series(name, phase=phase, run=run)]

    def metric_names(self) -> list[str]:
        return sorted({record.name for record in self.records})

    def phases(self) -> list[str]:
        return sorted({record.phase for record in self.records})

    def runs(self) -> list[str]:
        return sorted({record.run for record in self.records})

    def save_csv(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata_keys = sorted({key for record in self.records for key in record.metadata})
        with path.open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["run", "step", "episode", "phase", "name", "value", *metadata_keys])
            writer.writeheader()
            for record in self.records:
                row = {
                    "run": record.run,
                    "step": record.step,
                    "episode": "" if record.episode is None else record.episode,
                    "phase": record.phase,
                    "name": record.name,
                    "value": record.value,
                }
                row.update(record.metadata)
                writer.writerow(row)

    @classmethod
    def load_csv(cls, path: str | Path) -> "MetricHistory":
        history = cls()
        with Path(path).open(newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                metadata = {
                    key: value
                    for key, value in row.items()
                    if key not in {"run", "step", "episode", "phase", "name", "value"} and value not in ("", None)
                }
                episode = int(row["episode"]) if row.get("episode") not in ("", None) else None
                history.log(
                    row["name"],
                    float(row["value"]),
                    int(row["step"]),
                    phase=row.get("phase") or "train",
                    run=row.get("run") or "default",
                    episode=episode,
                    **metadata,
                )
        return history


def moving_average(values: list[float], window: int) -> list[float]:
    if window <= 0:
        raise ValueError("window must be positive")
    return [mean(values[max(0, index - window + 1) : index + 1]) for index in range(len(values))]


def load_metrics_csv(path: str | Path) -> MetricHistory:
    return MetricHistory.load_csv(path)


def save_metric_plot(
    history: MetricHistory,
    path: str | Path,
    metrics: list[str] | None = None,
    phases: list[str] | None = None,
    run: str | None = None,
    window: int = 10,
) -> None:
    plt = _pyplot()
    metrics = metrics or history.metric_names()
    phases = phases or history.phases()
    figure, axes = plt.subplots(max(1, len(metrics)), 1, figsize=(8, max(3, 2.6 * len(metrics))), constrained_layout=True)
    if len(metrics) == 1:
        axes = [axes]
    for axis, metric in zip(axes, metrics):
        for phase in phases:
            series = history.series(metric, phase=phase, run=run)
            if not series:
                continue
            steps = [step for step, _ in series]
            values = [value for _, value in series]
            axis.plot(steps, values, alpha=0.35, label=f"{phase} raw")
            if len(values) > 1:
                axis.plot(steps, moving_average(values, window), label=f"{phase} {window}-step mean")
        axis.set_title(metric)
        axis.set_xlabel("step")
        axis.legend(loc="best")
    figure.savefig(path)
    plt.close(figure)


def save_comparison_plot(
    histories: dict[str, MetricHistory],
    path: str | Path,
    metric: str,
    phase: str = "train",
    window: int = 10,
) -> None:
    plt = _pyplot()
    figure, axis = plt.subplots(1, 1, figsize=(8, 4), constrained_layout=True)
    for label, history in histories.items():
        values = history.values(metric, phase=phase)
        if not values:
            continue
        steps = [step for step, _ in history.series(metric, phase=phase)]
        axis.plot(steps, moving_average(values, window), label=label)
    axis.set_title(f"{metric} comparison")
    axis.set_xlabel("step")
    axis.legend(loc="best")
    figure.savefig(path)
    plt.close(figure)


def match_history_from_csv(path: str | Path) -> MetricHistory:
    history = MetricHistory()
    totals: dict[str, int] = defaultdict(int)
    wins: dict[str, int] = defaultdict(int)
    with Path(path).open(newline="") as file:
        reader = csv.DictReader(file)
        for index, row in enumerate(reader):
            bot_a = row["bot_a"]
            bot_b = row["bot_b"]
            winner = row["winner_bot"]
            turns = float(row["turns"])
            history.log("turns", turns, step=index, phase="match", run="matches", bot_a=bot_a, bot_b=bot_b, winner=winner)
            for bot in (bot_a, bot_b):
                totals[bot] += 1
                if bot == winner:
                    wins[bot] += 1
                history.log("win_rate", wins[bot] / totals[bot], step=totals[bot], phase="match", run=bot)
    return history


def save_match_summary_plot(csv_path: str | Path, path: str | Path, window: int = 10) -> None:
    history = match_history_from_csv(csv_path)
    save_comparison_plot({run: history for run in history.runs() if run != "matches"}, path, "win_rate", phase="match", window=window)


def _pyplot():
    cache_dir = Path(".matplotlib-cache").resolve()
    cache_dir.mkdir(exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional plotting dependency.
        raise RuntimeError("Plots require matplotlib. Install the optional ML dependencies with: pip install -e .[ml]") from exc
    return plt

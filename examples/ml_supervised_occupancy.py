"""Example: supervised learning against occupancy-map labels.

This file shows the mechanics of training a small parameterized model from
helper-generated labels. The label is the SDK occupancy heatmap for a public
observation: a board-shaped array where each cell stores how often sampled
legal fleets contain an alive ship there.

Run from the project root after installing the optional ML dependencies:

    pip install -e ".[dev,ui,ml]"
    python examples/ml_supervised_occupancy.py

The model, data generator, and training settings are intentionally small so the
example is easy to read. They are reference scaffolding, not an answer key.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np

from core.rules import Rules, official_rules
from sdk.inference import occupancy_heatmap
from sdk.neural import default_observation_encoder
from sdk.observation import ObservationState
from sdk.training import MetricHistory, save_metric_plot
from sdk.targeting import available_shots
from ui.practice import new_practice_target, practice_fire


def _torch():
    try:
        import torch
        from torch import nn
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "This example requires the optional ML dependencies: pip install -e .[ml]"
        ) from exc
    return torch, nn


def build_occupancy_model(channel_count: int):
    """Return a tiny convolutional model that predicts one board-shaped map."""

    _torch_module, nn = _torch()
    return nn.Sequential(
        nn.Conv2d(channel_count, 32, kernel_size=3, padding=1),
        nn.ReLU(),
        nn.Conv2d(32, 32, kernel_size=3, padding=1),
        nn.ReLU(),
        nn.Conv2d(32, 1, kernel_size=1),
    )


def random_observation(rules: Rules, rng: random.Random, max_shots: int = 25):
    """Create a public observation by firing random legal shots at a target."""

    target = new_practice_target(rules, rng)
    observation = ObservationState(rules)
    shot_count = rng.randrange(max_shots + 1)
    for _ in range(shot_count):
        if target.all_sunk:
            break
        candidates = available_shots(observation.snapshot())
        practice_fire(target, observation, rng.choice(candidates))
    return observation.snapshot()


def supervised_batch(
    rules: Rules,
    rng: random.Random,
    batch_size: int,
    max_shots: int = 25,
    max_label_samples: int = 150,
):
    """Build one batch of input tensors and occupancy-map labels."""

    torch, _nn = _torch()
    encoder = default_observation_encoder(include_ship_alive=True)
    inputs = []
    labels = []
    for _ in range(batch_size):
        snapshot = random_observation(rules, rng, max_shots=max_shots)
        channels = encoder.encode(snapshot, rules)
        label = occupancy_heatmap(
            rules,
            snapshot,
            max_samples=max_label_samples,
            rng=rng,
            time_limit=0.10,
        )
        inputs.append(channels)
        labels.append(label)

    x = torch.tensor(np.stack(inputs), dtype=torch.float32)
    y = torch.tensor(np.stack(labels)[:, None, :, :], dtype=torch.float32)
    return x, y


def train_supervised_occupancy(
    steps: int = 50,
    batch_size: int = 8,
    seed: int = 123,
) -> tuple[object, MetricHistory]:
    """Train a small model to approximate `occupancy_heatmap(...)` labels."""

    torch, nn = _torch()
    rules = official_rules()
    rng = random.Random(seed)
    encoder = default_observation_encoder(include_ship_alive=True)
    model = build_occupancy_model(encoder.channel_count)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()
    history = MetricHistory()

    for step in range(steps):
        x, y = supervised_batch(rules, rng, batch_size)
        prediction = torch.sigmoid(model(x))
        loss = loss_fn(prediction, y)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        history.log("mse", float(loss.detach()), step=step, phase="train", run="occupancy")

    return model, history


def main() -> int:
    """Run a tiny training job and write metrics and a progress plot."""

    _model, history = train_supervised_occupancy()
    csv_path = Path("results/ml_supervised_occupancy_metrics.csv")
    plot_path = Path("results/ml_supervised_occupancy_metrics.png")
    history.save_csv(csv_path)
    save_metric_plot(history, plot_path, metrics=["mse"], window=5)
    print(f"wrote {csv_path}")
    print(f"wrote {plot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


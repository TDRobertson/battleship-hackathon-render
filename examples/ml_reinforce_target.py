"""Example: reinforcement learning loop for solo target practice.

This file demonstrates the mechanics of a parameterized policy trained from
episode rewards. The environment is the same hidden-fleet target practice used
by `battleship play --solo`: the policy sees only public observation channels
and chooses among legal shot cells.

Run from the project root after installing the optional ML dependencies:

    pip install -e ".[dev,ui,ml]"
    python examples/ml_reinforce_target.py

The loop is deliberately compact. It shows how to connect SDK encoders,
legal-action masks, rewards, and metric logging without prescribing a
competition strategy.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np

from core.rules import Rules, official_rules
from sdk.neural import (
    RewardScheme,
    action_to_coord,
    available_mask,
    default_observation_encoder,
    outcome_reward,
)
from sdk.observation import ObservationState
from sdk.training import MetricHistory, save_metric_plot
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


def build_policy_model(channel_count: int, action_count: int):
    """Return a tiny policy network that outputs one logit per board cell."""

    _torch_module, nn = _torch()
    return nn.Sequential(
        nn.Flatten(),
        nn.Linear(channel_count * action_count, 128),
        nn.ReLU(),
        nn.Linear(128, action_count),
    )


def encoded_observation_tensor(rules: Rules, observation, encoder):
    """Convert an observation snapshot to a single model input tensor."""

    torch, _nn = _torch()
    channels = encoder.encode(observation, rules)
    return torch.tensor(channels[None, :, :, :], dtype=torch.float32)


def masked_policy_distribution(model, x, legal_mask):
    """Build a categorical distribution over legal actions only."""

    torch, _nn = _torch()
    logits = model(x).squeeze(0)
    mask = torch.tensor(legal_mask.reshape(-1), dtype=torch.bool)
    masked_logits = torch.where(mask, logits, torch.tensor(-1e9, dtype=logits.dtype))
    return torch.distributions.Categorical(logits=masked_logits)


def discounted_returns(rewards: list[float], discount: float):
    """Return normalized discounted returns for one episode."""

    torch, _nn = _torch()
    running = 0.0
    values = []
    for reward in reversed(rewards):
        running = float(reward) + discount * running
        values.append(running)
    returns = torch.tensor(list(reversed(values)), dtype=torch.float32)
    if len(returns) > 1:
        returns = (returns - returns.mean()) / (returns.std() + 1e-6)
    return returns


def run_episode(rules: Rules, model, rng: random.Random, discount: float = 0.98):
    """Run one target-practice episode and return a policy-gradient loss."""

    torch, _nn = _torch()
    encoder = default_observation_encoder(include_ship_alive=True)
    target = new_practice_target(rules, rng)
    observation = ObservationState(rules)
    log_probs = []
    rewards = []
    max_steps = rules.rows * rules.cols

    for _step in range(max_steps):
        snapshot = observation.snapshot()
        x = encoded_observation_tensor(rules, snapshot, encoder)
        distribution = masked_policy_distribution(model, x, available_mask(snapshot))
        action = distribution.sample()
        coord = action_to_coord(int(action.item()), rules)
        result = practice_fire(target, observation, coord)
        reward = outcome_reward(
            result,
            won=target.all_sunk,
            scheme=RewardScheme(miss=-0.02, hit=0.10, sunk=0.30, win=1.0),
        )
        log_probs.append(distribution.log_prob(action))
        rewards.append(reward)
        if target.all_sunk:
            break

    returns = discounted_returns(rewards, discount)
    log_prob_tensor = torch.stack(log_probs)
    loss = -(log_prob_tensor * returns).sum()
    return loss, len(rewards), float(np.sum(rewards))


def train_reinforce_target(
    episodes: int = 50,
    seed: int = 123,
) -> tuple[object, MetricHistory]:
    """Train a small policy with REINFORCE on target-practice episodes."""

    torch, _nn = _torch()
    rules = official_rules()
    rng = random.Random(seed)
    encoder = default_observation_encoder(include_ship_alive=True)
    action_count = rules.rows * rules.cols
    model = build_policy_model(encoder.channel_count, action_count)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    history = MetricHistory()

    for episode in range(episodes):
        loss, length, total_reward = run_episode(rules, model, rng)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        history.log_many(
            {"loss": float(loss.detach()), "episode_length": length, "episode_reward": total_reward},
            step=episode,
            phase="train",
            run="reinforce-target",
            episode=episode,
        )

    return model, history


def main() -> int:
    """Run a tiny policy-gradient job and write metrics and progress plots."""

    _model, history = train_reinforce_target()
    csv_path = Path("results/ml_reinforce_target_metrics.csv")
    plot_path = Path("results/ml_reinforce_target_metrics.png")
    history.save_csv(csv_path)
    save_metric_plot(
        history,
        plot_path,
        metrics=["loss", "episode_length", "episode_reward"],
        window=5,
    )
    print(f"wrote {csv_path}")
    print(f"wrote {plot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


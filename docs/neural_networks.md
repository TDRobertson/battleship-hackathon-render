# Neural Networks

Battleship has two different learning problems:

- **Placement**: choose where your own fleet starts.
- **Shooting**: choose the next target from public shot history.

Train them separately unless you have a strong reason not to. They have
different observations, action spaces, and rewards.

## Placement Observation

Placement happens before shots are fired. The only game information is the
rules and the partial fleet your bot has already placed.

```python
from sdk.neural import (
    PlacementObservation,
    default_placement_encoder,
    legal_placement_action_mask,
)


slot = 0
obs = PlacementObservation.empty(rules, next_slot=slot)
encoder = default_placement_encoder()
channels = encoder.encode(obs, rules)
mask = legal_placement_action_mask(rules, obs, slot)
```

Default placement channels:

- `occupied`: cells already used by ships you placed.
- `available`: cells not occupied yet.
- `next_ship_length`: constant plane for the current ship length.
- `fraction_done`: constant plane for how much of the fleet is placed.

Placement actions are legal placements for one ship slot. A simple placement
network can pick one ship at a time: slot 0, then slot 1, and so on.

## Shooting Observation

Shooting happens during the game. The bot sees only public target-board
information.

```python
from sdk.neural import default_observation_encoder, available_mask


encoder = default_observation_encoder(include_ship_alive=True)
channels = encoder.encode(observation, rules)
mask = available_mask(observation)
```

Default shooting channels:

- `misses`, `hits`, `sunk`
- `available`
- `hit_neighbors`
- `line_extensions`
- `parity`
- optional `ship_alive_lengths` channel when `include_ship_alive=True`

Shooting actions are board cells. Use `coord_to_action` and `action_to_coord`
to convert between `(row, col)` and flat action indices.

## Change Channels

Add or remove channels by constructing an encoder directly.

```python
from sdk.neural import ObservationEncoder, misses_channel, hits_channel, available_channel


encoder = ObservationEncoder(
    channels=(misses_channel, hits_channel, available_channel),
    names=("misses", "hits", "available"),
)
```

For per-ship channels:

```python
from sdk.neural import (
    default_observation_encoder,
    default_placement_encoder,
    with_ship_slot_alive_channels,
    with_ship_slot_placed_channels,
)


shooting_encoder = with_ship_slot_alive_channels(default_observation_encoder(), rules)
placement_encoder = with_ship_slot_placed_channels(default_placement_encoder(), rules)
```

`with_ship_slot_alive_channels(...)` adds one shooting channel per ship slot,
named `ship_0_alive` through `ship_4_alive` for the official fleet.

## Rewards

Shooting rewards can start with outcome rewards:

```python
from sdk.neural import RewardScheme, outcome_reward


scheme = RewardScheme(miss=-0.1, hit=0.3, sunk=1.0, win=3.0)
reward = outcome_reward(result, won, scheme)
```

Placement rewards usually come later, after an opponent attacks your fleet.
Common simple choices:

- `+1` if the fleet wins the match.
- Number of opponent shots survived before losing.
- Negative reward for ships sunk very early.

Keep reward functions small at first. Change one number at a time.

## Self-Play

Self-play means training against saved older versions of your own bot.

Minimal loop:

1. Train the current bot for a few games.
2. Save a snapshot of its model weights.
3. Keep a small pool of old snapshots.
4. For each new training game, choose a random old snapshot as the opponent.
5. Occasionally evaluate against `starter-random`, `hunt-target`, and any fixed
   bots your team has written.

Do not train only against the latest version of yourself. A random pool of older
opponents usually avoids brittle habits better.

## Suggested Split

- Placement model input: `PlacementObservation`.
- Placement model output: one legal placement action for the current ship slot.
- Shooting model input: `ObservationSnapshot`.
- Shooting model output: one legal target cell.

This keeps placement creativity and shot-selection tactics independent enough
to experiment quickly.

## Reference Examples

Runnable machine-learning reference loops live in `examples/`:

- `examples/ml_supervised_occupancy.py`: supervised training against SDK
  occupancy-map labels.
- `examples/ml_reinforce_target.py`: a small policy-gradient loop for solo
  target practice.

These examples show how to connect SDK tensors, legal-action masks, losses,
rewards, and metric logging. They are starting scaffolds rather than strategy
recommendations.

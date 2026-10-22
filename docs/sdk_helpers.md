# SDK Helpers

The SDK is a neutral toolbox. Helpers answer questions like "which shots are
still legal?" or "which fleets are consistent with what I know?" They do not
decide which legal move is best. Put strategic choices in your bot.

## Common Helpers

Most first bots only need these:

```python
from sdk.placement import random_legal_fleet
from sdk.targeting import available_shots, hit_neighbors, line_extensions, choose_random
from sdk.validation import fleet_errors, shot_errors
```

- `random_legal_fleet(rules, rng)`: get legal placement working immediately.
- `available_shots(observation)`: all legal shots.
- `hit_neighbors(observation)`: available cells next to unresolved hits.
- `line_extensions(observation)`: available cells beyond a run of hits.
- `choose_random(candidates, rng)`: random choice with duplicate cleanup.
- `fleet_errors(...)` / `shot_errors(...)`: plain-language debugging.

For probability-style bots, start with:

```python
from sdk.inference import FleetSamplePool, hypothesis_reduction_scores
```

The rest of this file is a reference. Skim the headings first.

## Board

`sdk.board.in_bounds(rules, coord)`

Returns whether a coordinate is on the board.

`sdk.board.all_cells(rules)`

Returns every coordinate on the board.

`sdk.board.neighbors(rules, coord, diagonals=False)`

Returns in-bounds neighboring coordinates. Set `diagonals=True` to include
diagonal neighbors.

`sdk.board.manhattan(a, b)`

Returns Manhattan distance between two coordinates.

`sdk.board.center_distance(rules, coord)`

Returns Manhattan distance from a coordinate to the board center.

`sdk.board.checkerboard_cells(rules, offset=0)`

Returns one parity color of the board.

`sdk.board.edge_cells(rules)`

Returns all cells on the board edge.

## Placement

`sdk.placement.placement(slot, row, col, orientation)`

Short constructor for `ShipPlacement`.

`sdk.placement.ship_cells(rules, placement)`

Returns the cells occupied by one ship placement. Raises `ValueError` if the
ship is out of bounds.

`sdk.placement.legal_ship_placements(rules, slot, occupied=None)`

Returns every legal placement for one ship slot, optionally excluding placements
that overlap `occupied` cells.

`sdk.placement.random_legal_fleet(rules, rng)`

Returns one complete legal fleet using randomized backtracking. This is a
convenience baseline for getting a bot running; it is reproducible with the same
seed, but it is not a uniform sample over all legal fleets.

`sdk.placement.fleet_from_specs(rules, specs)`

Builds placements from tuples shaped `(slot, row, col, orientation)`.

`sdk.placement.fleet_cells(rules, placements)`

Returns the occupied cells for each ship slot.

`sdk.placement.mirror_fleet_horizontal(...)`, `mirror_fleet_vertical(...)`, and
`rotate_fleet_180(...)`

Return transformed copies of a fleet. These are useful for quickly testing
families of placement layouts.

## Targeting

`sdk.targeting.available_shots(observation)`

Returns every unshot target-board coordinate.

`sdk.targeting.unresolved_hits(observation)`

Returns hit cells that belong to ships that have not sunk yet. When a ship
sinks, its cells move from `hits` to `sunk`.

`sdk.targeting.orthogonal_neighbors(coord, shape)`

Returns in-bounds up/down/left/right neighbors for one coordinate.

`sdk.targeting.hit_neighbors(observation)`

Returns available orthogonal neighbors of unresolved hits. Your bot decides
whether those candidates are important.

`sdk.targeting.line_extensions(observation)`

Returns available cells immediately beyond either end of contiguous horizontal
or vertical runs of unresolved hits.

Example: if `(5, 5)` and `(5, 6)` are unresolved hits, line extensions are
`(5, 4)` and `(5, 7)`, unless one has already been fired at or is out of bounds.

This is a geometric candidate set, not proof of ship identity. Touching ships
are legal, so adjacent hits can belong to different ships.

`sdk.targeting.choose_random(candidates, rng)`

Chooses uniformly from unique candidate coordinates and raises an error if the
candidate list is empty.

## Observation Summary

`sdk.summary.shot_count(observation)`

Returns how many shots have been taken on the target board.

`sdk.summary.remaining_ship_lengths(rules, observation)`

Returns the lengths of ships that have not sunk yet.

`sdk.summary.known_cells(observation)` and `sdk.summary.unknown_cells(observation)`

Return sets of shot and unshot coordinates.

`sdk.summary.has_unresolved_hits(observation)`

Returns whether there are hit cells that have not been resolved into a sunk ship.

## Inference

`sdk.inference.possible_fleets(rules, observation, max_fleets=300, rng=None)`

Returns complete alive-ship fleets that are consistent with known misses, sunk
cells, and unresolved hits. Results are capped by `max_fleets` because the full
set can be large early in the game.

`sdk.inference.occupancy_heatmap(rules, observation, max_samples=500, rng=None, time_limit=1.0)`

Returns a board-shaped array estimating how often each cell is occupied across
sampled possible fleets. Increase `max_samples` for a slower but usually less
noisy estimate, or decrease it when speed matters more. The helper stops after
`time_limit` seconds and uses whatever legal fleets it found, so `max_samples`
is a ceiling rather than a guaranteed count. Sampling avoids the top-left bias
that would come from using only the first capped fleets in row-major
enumeration. A bot can use this as one signal, ignore it, combine it with
another signal, or deliberately shoot low-probability cells.

Occupancy values are probability-like numbers from `0.0` to `1.0`. A value of
`0.30` means about 30 percent of the sampled legal fleets contain an alive ship
at that cell.

`sdk.inference.sample_possible_fleets(rules, observation, max_samples=500, rng=None, time_limit=1.0)`

Returns up to `max_samples` complete alive-ship fleets that are consistent with
known misses, sunk cells, and unresolved hits. This is useful for approximate
probability estimates and visualizations. Timeout-limited calls may return fewer
than `max_samples`.

`sdk.inference.filter_possible_fleets(rules, observation, fleets)`

Takes an existing list of fleet hypotheses and returns only the fleets that are
still legal under the latest observation. If a ship has sunk, matching old
full-fleet hypotheses are normalized down to their still-alive ships.

`sdk.inference.refill_possible_fleets(rules, observation, fleets, max_samples=500, rng=None, time_limit=1.0)`

Tops a filtered fleet list back up toward `max_samples` by generating
replacement legal fleets. If the timeout expires, it returns the legal fleets it
has. It returns `(fleets, refilled_count)`.

`sdk.inference.occupancy_from_fleets(rules, fleets)`

Converts a list of legal fleet hypotheses into a board-shaped occupancy
heatmap. This is the final step in the incremental pipeline.

`sdk.inference.FleetSamplePool(rules, max_samples=500, rng=None, time_limit=1.0)`

Keeps a reusable pool of sampled fleet hypotheses. Call
`pool.occupancy_heatmap(observation)` after each shot. The pool filters out
fleets disproved by the latest observation, keeps still-valid fleets, and only
samples replacements for the missing hypotheses. The pool treats `max_samples`
as a ceiling and returns early after `time_limit` seconds. This is much faster
for interactive tools and stateful bots than rebuilding every sample after every
shot.

Useful inspection fields:

- `pool.retained`: sampled fleets that survived the latest observation update.
- `pool.refilled`: replacement fleets generated during the latest update.
- `pool.discarded`: old sampled fleets disproved by the latest observation.
- `pool.shortfall`: how many samples below `max_samples` the latest update
  stopped.

`sdk.inference.hypothesis_reduction_scores(rules, fleets, candidates, assumed_outcome=None)`

Scores candidate shots by splitting sampled fleets into hit and miss branches,
then measuring how much total marginal occupancy entropy would drop across the
board. With `assumed_outcome="hit"` or `"miss"`, the score uses that branch
only. With the default `None`, it returns the hit/miss probability-weighted
expected entropy reduction. This is useful for bots that want to seek
information without hard-coding a particular targeting strategy.

Information scores are not hit probabilities and are not limited to `0.0` to
`1.0`. They are expected uncertainty-reduction scores: larger values mean the
shot result would, on average, rule out or separate more of the remaining fleet
hypotheses. The units are entropy-like and are most useful when compared with
other candidate cells from the same observation.

Occupancy and information answer different questions:

- Occupancy asks: "How often is a ship in this cell?"
- Information asks: "How much would the answer at this cell clarify the rest of
  the board?"

Because those questions differ, the highest-occupancy cell and the
highest-information cell do not have to be the same cell.

`sdk.inference.fleet_pool_entropy(rules, fleets)` and `sdk.inference.occupancy_entropy(occupancy)`

Return the total marginal occupancy entropy behind the information score. These
are math/inspection helpers; deciding whether to maximize them, minimize them,
or combine them with hit probability is still bot strategy.

## Scoring Glue

`sdk.scoring.choose_best_score(scores, rng)`

Chooses randomly among the highest-scoring coordinates in a dictionary shaped
`{(row, col): score}`. This helper breaks ties only; your bot still decides what
the scores mean.

`sdk.scoring.information_scores(rules, fleets, candidates)`

Small wrapper around `sdk.inference.hypothesis_reduction_scores` for bots or
experiments that want expected split-information scores.

## Opponent Memory

During `simulate` and `tournament`, the runner gives each bot a mutable
per-opponent memory dictionary through optional lifecycle hooks. Memory is
enabled by default and stored under `results/memory`; use `--no-memory` to
disable it or `--memory-dir path` to choose a separate store.

```python
def start_match(self, context):
    self.memory = context.memory
    self.stats = self.memory.get("_stats", {})


def observe_opponent_shot(self, result, time_remaining):
    self.memory["last_opponent_shot"] = result.shot
```

The runner loads and saves the dictionary automatically. It also maintains
`memory["_stats"]` with fields such as `games`, `wins`, `losses`,
`opponent_recent_shots`, `opponent_opening_shots`, `opponent_center_rate`,
`opponent_edge_rate`, `opponent_corner_rate`, and
`opponent_parity_rate_first_20`.

If a bot sets `memory["current_layout"]` before or during placement, the runner
tracks that layout under `memory["_stats"]["layouts"]` with games, wins, losses,
and average opponent shots.

For cold-start pitfalls and safer adaptation patterns, see
`docs/opponent_memory.md`.

## Validation

`sdk.validation.fleet_errors(rules, placements)`

Returns a list of plain-language errors for a proposed fleet. An empty list means
the fleet is legal.

`sdk.validation.shot_errors(rules, observation, shot)`

Returns a list of plain-language errors for a proposed shot. An empty list means
the shot is legal.

`sdk.validation.is_legal_fleet(...)` and `sdk.validation.is_legal_shot(...)`

Boolean wrappers around the error-reporting helpers.

## Neural Networks

For a short task-focused guide, including separate placement and shooting
observations, see `docs/neural_networks.md`.

`sdk.neural.default_observation_encoder(include_ship_alive=False)`

Returns an `ObservationEncoder` with practical starter channels: misses,
unresolved hits, sunk cells, available shots, hit neighbors, line extensions,
and parity. Set `include_ship_alive=True` to add one constant channel
describing the fraction of total ship length still unsunk.

`sdk.neural.with_ship_slot_alive_channels(encoder, rules)`

Returns a new encoder with one extra constant board channel per ship slot. For
the official fleet, this adds channels named `ship_0_alive` through
`ship_4_alive`. These channels let participants test whether the model benefits
from knowing which specific ships are still unsunk.

`encoder.encode(observation, rules)`

Returns a NumPy array shaped `(channels, rows, cols)`. You can build your own
encoder by passing channel functions to `sdk.neural.ObservationEncoder`.

`sdk.neural.available_mask(observation)`

Returns a Boolean board mask for legal actions.

`sdk.neural.sample_action(probabilities, rng)` and `sdk.neural.greedy_action(scores, mask)`

Return flat action indices. Use `action_to_coord(action, rules)` and
`coord_to_action(coord, rules)` to convert between flat neural-network actions
and Battleship coordinates.

`sdk.neural.RewardScheme` and `sdk.neural.outcome_reward(result, won, scheme)`

Provide a simple configurable reward baseline for participants who write their
own learning loop.

`sdk.neural.PlacementObservation`

Represents the placement stage: occupied cells, which ship slots have already
been placed, and the optional next slot being placed.

`sdk.neural.default_placement_encoder()`

Returns a `PlacementEncoder` with placement-stage channels: occupied cells,
available cells, next ship length, and fraction of the fleet already placed.

`sdk.neural.legal_placement_action_mask(rules, placement_observation, slot)`

Returns a Boolean mask over legal placements for one ship slot. Use
`placement_action_to_placement(...)` and `placement_to_action(...)` to convert
between flat placement actions and `ShipPlacement` objects.

`sdk.neural.with_ship_slot_placed_channels(encoder, rules)`

Adds one constant channel per ship slot showing whether that slot has already
been placed.

The repository intentionally does not ship a complete neural-network bot. The
helpers cover the boring glue: observation tensors, legal-action masks,
coordinate/action conversion, reward arithmetic, metric logging, and plotting.
Participants still choose the model, data, training loop, opponent mix, and
ship-placement policy.

## Training

`sdk.training.MetricHistory`

Stores arbitrary numeric metrics for supervised learning, reinforcement
learning, and evaluation runs. Each record has a metric `name`, numeric `value`,
`step`, `phase`, `run`, optional `episode`, and optional metadata.

Example:

```python
from sdk.training import MetricHistory


history = MetricHistory()
history.log_many({"loss": 0.42, "accuracy": 0.81}, step=10, phase="train", run="supervised")
history.log("episode_reward", 3.0, step=2, phase="train", run="ml", episode=2)
history.save_csv("metrics.csv")
```

`history.series(name, phase=None, run=None)` and `history.values(...)`

Return metric series for analysis or custom plots.

`sdk.training.load_metrics_csv(path)`

Loads a CSV written by `MetricHistory.save_csv`.

`sdk.training.save_metric_plot(history, path, metrics=None, phases=None, run=None, window=10)`

Writes one or more metric curves. This works for supervised metrics such as
`loss`, `accuracy`, and `validation_loss`, and reinforcement-learning metrics such as
`episode_reward`, `episode_length`, `entropy`, and `win_rate`.

`sdk.training.save_comparison_plot(histories, path, metric, phase="train", window=10)`

Plots the same metric across multiple runs.

`sdk.training.match_history_from_csv(path)`

Converts CSV output from `battleship simulate --csv` or
`battleship tournament --csv` into a `MetricHistory` with match `turns` and
per-bot rolling `win_rate`.

`sdk.training.save_match_summary_plot(csv_path, path, window=10)`

Writes a quick rolling win-rate summary from a match/tournament CSV. Plotting
requires the optional `ml` dependencies because that extra installs matplotlib.

`sdk.training.moving_average(values, window)`

Returns a trailing moving average for smoothing noisy training curves.

## GUI Debugging

`battleship play --bot ...` includes a helper visualizer in the battle screen.
It reuses SDK helpers directly and displays their board-shaped outputs without
choosing a shot for you. Use it to inspect whether a bot seems to be reacting to
the same signals you expected.

Useful overlays include:

- occupancy heatmaps from `sdk.inference.occupancy_heatmap`
- expected split information from `sdk.inference.hypothesis_reduction_scores`
- diagonal bands with adjustable spacing and offset
- available-shot masks
- unresolved-hit neighbor candidates
- line-extension candidates
- neural observation channels from `sdk.neural.ObservationEncoder`

Switch the focus to `bot-target` to overlay helper output on your own board from
the bot's public observation. This is the easiest way to debug whether a bundled
or custom bot appears to be following a heatmap, parity pattern, or target-mode
candidate set.

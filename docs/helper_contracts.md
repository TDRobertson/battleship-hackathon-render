# Helper Contracts

These contracts describe what SDK helpers must do independently of their current
implementation. Tests should trace back to these behaviors instead of copying
the production code.

## Board Helpers

`all_cells(rules)`

- Returns every `(row, col)` coordinate on the board.
- Returns each coordinate exactly once.
- Every returned coordinate is in bounds.
- The result length is `rules.rows * rules.cols`.

`in_bounds(rules, coord)`

- Returns true exactly when `0 <= row < rules.rows` and `0 <= col < rules.cols`.

`neighbors(rules, coord, diagonals=False)`

- Returns only in-bounds cells.
- With `diagonals=False`, every neighbor has Manhattan distance 1.
- With `diagonals=True`, every neighbor differs by at most 1 row and 1 column,
  excluding the original cell.

`diagonal_band_cells(rules, spacing, offset)`

- `spacing` must be positive.
- Returns only in-bounds cells.
- Includes a coordinate exactly when `(row + col + offset) % spacing == 0`.
- `checkerboard_cells(rules, offset)` is equivalent to `spacing=2`.

## Placement Helpers

`ship_cells(rules, placement)`

- Returns exactly `rules.ship_length(placement.slot)` cells.
- Horizontal placements keep row fixed and increase column by 1.
- Vertical placements keep column fixed and increase row by 1.
- Raises `ValueError` if any ship cell would be out of bounds.

`legal_ship_placements(rules, slot, occupied)`

- Returns only placements whose cells are in bounds.
- Returns only placements that do not overlap `occupied`.
- Every returned placement has the requested slot.

`random_legal_fleet(rules, rng)`

- Returns every ship slot exactly once.
- Returned ships do not overlap.
- The same random seed reproduces the same result.

Fleet transform helpers

- Horizontal mirror preserves rows and ship orientations.
- Vertical mirror preserves columns and ship orientations.
- A transformed legal fleet remains legal when the source fleet is legal.
- A 180-degree rotation is equivalent to horizontal mirror followed by vertical
  mirror.

## Targeting Helpers

`available_shots(observation)`

- Returns exactly the target-board cells that are not marked miss, hit, or sunk.

`unresolved_hits(observation)`

- Returns exactly the cells marked as hits.

`orthogonal_neighbors(coord, shape)`

- Returns only in-bounds cells.
- Every returned cell has Manhattan distance 1 from `coord`.

`hit_neighbors(observation)` and `line_extensions(observation)`

- Return only available cells.
- Return unique coordinates.
- Do not mutate the observation.

`choose_random(candidates, rng)`

- Returns one of the unique candidate coordinates.
- Raises an error when candidates is empty.

## Summary Helpers

`known_cells(observation)` and `unknown_cells(observation)`

- Partition the board.
- Neither set overlaps the other.
- The union is every board cell.

`shot_count(observation)`

- Equals the number of known cells.

`remaining_ship_lengths(rules, observation)`

- Returns `rules.ship_length(slot)` for every alive slot.

## Validation Helpers

`fleet_errors(rules, placements)`

- Returns an empty list for legal fleets.
- Reports missing, duplicate, overlapping, out-of-bounds, or invalid-orientation
  placements.

`shot_errors(rules, observation, shot)`

- Returns an empty list for legal shots.
- Reports non-integer, out-of-bounds, and repeated shots.

Boolean validation wrappers

- `is_legal_fleet(...)` is true exactly when `fleet_errors(...)` is empty.
- `is_legal_shot(...)` is true exactly when `shot_errors(...)` is empty.

## Neural Helpers

Observation encoders

- `encoder.channel_count == len(encoder.names)`.
- `encoder.encode(observation, rules)` returns shape `(channels, rows, cols)`.
- Channel functions should not mutate the observation.

Placement encoders

- `PlacementObservation.empty(rules)` has no occupied cells or placed slots.
- `PlacementObservation.from_placements(...)` marks exactly the placed ship
  cells and slots.
- `PlacementEncoder.encode(observation, rules)` returns shape
  `(channels, rows, cols)`.
- `legal_placement_action_mask(...)` marks only placements that do not overlap
  already occupied cells.

Action helpers

- `coord_to_action` and `action_to_coord` are inverses for in-bounds cells.
- `available_mask(observation)` matches `observation.available_shots()`.
- `greedy_action(scores, mask)` never returns a masked-out action.
- `sample_action(probabilities, rng)` returns an index with positive probability.

Reward helpers

- Miss, hit, and sunk outcomes map to their configured reward values.
- Winning adds the configured win bonus.

## Protocol And Replay

Protocol messages

- `shot_result_message` and `result_from_message` round-trip public shot results.
- Unsupported protocol versions and message types are rejected.

Replay logs

- `ReplayLog.to_json()` and `ReplayLog.from_json()` round-trip the replay data.

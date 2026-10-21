# Tutorial: Build A Simple Bot

This is the 30-minute path from "it runs" to "it has a strategy." Start from
the smallest legal bot, then change placement, candidate shots, and scoring.

## 1. Copy The Starter

Windows PowerShell:

```powershell
Copy-Item src\bots\starter_random.py my_bot.py
```

macOS/Linux:

```sh
cp src/bots/starter_random.py my_bot.py
```

Run it once:

```console
battleship simulate --bot-a my_bot:RandomStarterBot --bot-b hunt-target --games 3 --verbose
```

The import path means "load `RandomStarterBot` from `my_bot.py`." If you rename
the class, update the command too.

There are only two built-in bot files on purpose:

- `src/bots/starter_random.py`: blank slate that places and shoots randomly.
- `src/bots/hunt_target.py`: compact reference that follows unresolved hits.

## 2. Understand The Two Hooks

The engine calls two methods:

```python
def place_ships(self, rules, time_remaining):
    ...

def choose_shot(self, observation, time_remaining):
    ...
```

`place_ships` returns all ship placements. `choose_shot` returns one `(row, col)`
target coordinate. The engine validates both.

Inside `choose_shot`, `observation` has:

- `misses`, `hits`, and `sunk`: 10 by 10 NumPy masks.
- `ships_alive`: one flag per ship slot.
- `available_shots()`: a 10 by 10 Boolean mask of legal targets.

## 3. Start With Legal Placement

The starter uses:

```python
return random_legal_fleet(rules, self.rng)
```

That is a legal baseline, not a winning placement strategy. Experiments to try:

- Put the length-5 ship near an edge.
- Spread ships across different rows and columns.
- Randomly choose from a few hand-written layouts.
- Avoid repeating the same layout in every match.

Use `sdk.validation.fleet_errors(rules, placements)` while debugging. It returns
plain-language errors instead of ending a match.

## 4. Choose Candidate Shots

Targeting helpers return facts or candidate sets; your bot decides how to use
them.

```python
line_extensions(observation)  # cells beyond a row/column of unresolved hits
hit_neighbors(observation)    # orthogonal neighbors of unresolved hits
available_shots(observation)  # every unshot cell
```

The `hunt-target` reference strategy is:

```python
return line_extensions(observation) or hit_neighbors(observation) or available_shots(observation)
```

Good first experiments:

- Reverse the priority order.
- Use a checkerboard pattern while hunting.
- Prefer the center early in the game.
- After a hit, keep shooting nearby until the ship sinks.

## 5. Rank Or Score Candidates

Once your bot has candidates, you can score them however you like:

```python
scores = {}
for row, col in candidates:
    scores[(row, col)] = row + col
```

Then choose the highest score, lowest score, random among the top five, or
anything else. Strategic scoring belongs in your bot, not in the SDK.

## 6. Try More Helper Signals

The richer helpers live in `sdk`, not in ready-made bots. That means everyone
can use the same building blocks without inheriting the same strategy.

```python
from sdk.board import center_distance
from sdk.inference import FleetSamplePool, hypothesis_reduction_scores
from sdk.targeting import available_shots


pool = FleetSamplePool(rules, max_samples=200, rng=self.rng)
fleets = pool.update(observation)
heat = pool.occupancy_heatmap(observation)
info = hypothesis_reduction_scores(rules, fleets, available_shots(observation))
```

Ideas you can implement quickly:

- Score each available cell by `-center_distance(rules, coord)`.
- Hunt on diagonal bands until you have an unresolved hit.
- Use `heat[row, col]` as one feature in your own scoring formula.
- Use information scores early, then switch to hit probability late.
- Randomly choose among the top few scores instead of always taking the maximum.

For neural-network and plotting helpers, see `docs/sdk_helpers.md`.
For small copyable snippets, see `examples/`.

## 7. Compare Changes

Run enough games that randomness has a chance to even out:

```console
battleship simulate --bot-a my_bot:RandomStarterBot --bot-b starter --games 100 --seed 123
```

Change one idea at a time. Keep the seed while testing so you can compare before
and after behavior.

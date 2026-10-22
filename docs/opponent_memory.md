# Opponent Memory

Bots can adapt to repeated opponents by using a persistent per-opponent memory
dictionary. The runner loads this dictionary before each match and saves it
afterward.

Memory is enabled by default for `simulate` and `tournament`:

```console
battleship simulate --games 100 --bot-a my_bot:MyAgent --bot-b hunt-target
battleship tournament --process --games 50 --bot my_bot:MyAgent --bot hunt-target
```

Use `--no-memory` when every match should be independent:

```console
battleship simulate --games 100 --bot-a my_bot:MyAgent --bot-b hunt-target --no-memory
```

Use `--memory-dir` to keep experiments separate:

```console
battleship simulate --games 100 --memory-dir results/memory-test-a --bot-a my_bot:MyAgent --bot-b hunt-target
```

Use `--reset-memory` to clear the chosen memory directory before a run:

```console
battleship tournament --memory-dir results/memory-finals --reset-memory --bot my_bot:MyAgent --bot hunt-target
```

## Basic Pattern

Add optional lifecycle hooks to your bot. Existing bots that only implement
`place_ships` and `choose_shot` still work.

```python
def start_match(self, context):
    self.memory = context.memory
    self.stats = self.memory.get("_stats", {})


def observe_opponent_shot(self, result, time_remaining):
    self.memory["last_opponent_shot"] = result.shot


def end_match(self, result):
    self.memory["last_match_won"] = result.won
```

The most useful automatic data lives under `memory["_stats"]`:

- `games`, `wins`, `losses`
- `opponent_recent_shots`
- `opponent_opening_shots`
- `opponent_center_rate`
- `opponent_edge_rate`
- `opponent_corner_rate`
- `opponent_parity_rate_first_20`
- `layouts`, if your bot sets `memory["current_layout"]`

## First Match Problems

When your bot sees an opponent for the first time, its memory for that opponent
is empty. That can cause a few common bugs:

- Missing keys: `memory["_stats"]`, `opponent_center_rate`, or your own custom
  keys may not exist yet.
- Noisy conclusions: one opening shot or one game is not enough evidence to
  identify a reliable opponent style.
- Bad defaults: a bot may accidentally treat missing data as strong evidence,
  such as assuming an opponent never shoots edges because no edge shots have
  been recorded yet.
- Division by zero: rates based on `games` or shot counts need a fallback when
  the count is zero.
- Overfitting early: switching to a specialized layout after one game can make
  the bot worse against opponents with random or mixed behavior.
- Stale experiments: if you reuse the same memory directory while changing your
  bot, old custom keys may no longer mean what your new code expects.

Code as if every key is optional.

```python
def start_match(self, context):
    self.memory = context.memory
    stats = self.memory.get("_stats", {})
    games = stats.get("games", 0)

    if games >= 3 and stats.get("opponent_center_rate", 0.0) > 0.25:
        self.placement_mode = "avoid_center"
    else:
        self.placement_mode = "default"
```

## Safer Adaptation

Prefer gradual adaptation at first. Good rules of thumb:

- Require a minimum number of games before trusting a tendency.
- Blend memory with a baseline strategy instead of replacing the baseline.
- Store your own schema version if you write custom nested data.
- Keep a default behavior that is legal and reasonable against unknown
  opponents.
- Use `--reset-memory` when comparing major bot rewrites.

Example with a custom schema version:

```python
def start_match(self, context):
    self.memory = context.memory
    if self.memory.get("schema_version") != 1:
        self.memory.clear()
        self.memory["schema_version"] = 1

    self.stats = self.memory.get("_stats", {})
```

## Placement Layout Stats

If your bot chooses among named layouts, set `memory["current_layout"]` before
returning placements. The runner will record how that layout performed against
the current opponent.

```python
def place_ships(self, rules, time_remaining):
    stats = self.memory.get("_stats", {})
    layouts = stats.get("layouts", {})

    best = max(
        layouts,
        key=lambda name: layouts[name].get("avg_opponent_shots", 0),
        default="balanced",
    )

    self.memory["current_layout"] = best
    return self.layouts[best]
```

Be careful on the first few games: if `layouts` is empty, choose a reasonable
default or randomize among legal layouts.

## What Memory Does Not Show

Memory only contains public match information and values your bot writes. It
does not reveal hidden ship locations, private opponent code, or future moves.
The automatic opponent-shot stats are based on shots fired at your own fleet
after they happen.

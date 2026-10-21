# Running Bots

## Simulate One Or More Games

```console
battleship simulate --games 20 --bot-a starter --bot-b hunt-target --seed 123
```

Add `--verbose` to print every match result:

```console
battleship simulate --games 5 --bot-a my_bot:MyAgent --bot-b hunt-target --verbose
```

Write match results to CSV:

```console
battleship simulate --games 100 --bot-a my_bot:MyAgent --bot-b starter --csv results.csv
```

You can plot rolling win rates from a match CSV:

```python
from sdk.training import save_match_summary_plot


save_match_summary_plot("results.csv", "results.png")
```

## Play As A Human

```console
battleship play --bot my_bot:MyAgent
```

The human player is untimed. The bot still uses the official match clock.
During placement, use the buttons or `R` to rotate, `U` to undo, `T` to switch
theme, and `Q` to quit.

For no-opponent target practice, fire at a random fleet with ships hidden by
default:

```console
battleship play --solo
```

Use the on-screen buttons or keyboard shortcuts. `V` toggles whether the random
target ships are visible, `R` resets to a new random target, `T` switches between
light and dark mode, and `Q` quits.

The play screen also includes a helper visualizer for debugging strategies.
During battle, use the panel on the right, the top buttons, or these shortcuts:

- `D`: toggle helper overlays.
- `T`: switch between light and dark mode.
- `Q`: quit the UI.
- `Tab`: switch the debug focus between your target board and the bot's view of
  your fleet.
- `Left` / `Right`: cycle helper layers.
- `+` / `-`: change diagonal-band spacing.
- `,` / `.`: shift the diagonal-band offset.
- `PageUp` / `PageDown`: change the maximum fleet sample count used by
  occupancy and information overlays.
- `C`: cycle neural-network observation channels.

Available layers include occupancy heatmaps, expected split information,
diagonal bands, available-shot masks, known hits, hit-neighbor candidates, line
extensions, and neural observation channels. Click a board cell while the debug
panel is open to inspect the selected helper value and public cell state.

## Compare Bots

Use the same seed when comparing two versions:

```console
battleship simulate --games 100 --seed 2026 --bot-a my_bot:MyAgent --bot-b starter
```

Swap sides too. Player A always moves first, so a fair local comparison usually
runs both directions:

```console
battleship simulate --games 100 --seed 2026 --bot-a my_bot:MyAgent --bot-b hunt-target
battleship simulate --games 100 --seed 2026 --bot-a hunt-target --bot-b my_bot:MyAgent
```

## Benchmark Shots To Sink

To measure how many shots a bot needs to sink randomly placed fleets without an
opponent, use `benchmark`:

```console
battleship benchmark --games 100 --seed 2026 --bot starter-random --bot hunt-target --bot my_bot:MyAgent
```

Each bot faces the same sequence of random target fleets. The command prints the
average, minimum, and maximum shot count for each bot. Write per-game results to
CSV for later analysis:

```console
battleship benchmark --games 100 --seed 2026 --bot hunt-target --bot my_bot:MyAgent --csv shot-benchmark.csv
```

## Run Bots In Subprocesses

The subprocess mode is closer to a competition harness because each bot runs in
a worker process:

```console
battleship simulate --process --games 20 --bot-a my_bot:MyAgent --bot-b starter
```

Use this before submitting a bot. It catches import problems and serialization
problems that in-process matches may hide.

## Local Competition Format

A simple round-robin can be run with the `tournament` command:

```console
battleship tournament --process --games 50 --seed 1 --csv tournament.csv --bot alice_bot:MyAgent --bot bob_bot:MyAgent --bot starter
```

For a longer bot list, make a text file with one bot spec per line:

```text
alice_bot:MyAgent
bob_bot:MyAgent
starter
hunt-target
```

Then run:

```console
battleship tournament --process --games 50 --bots-file bots.txt --csv tournament.csv
```

There is also a small organizer wrapper with practical defaults:

```console
python scripts/organizer_local_tournament.py --bots-file examples/bots.txt --games 20
```

Recommended event settings:

- Use `--process`.
- Use the same `--games` and `--seed` for every pairing.
- The tournament command runs both player orders by default.
- Score by total wins across all pairings.
- Keep stderr logs for debugging, but judge by legal match results.

## Remote LAN Matches

For matches where competitors run bots on their own machines and connect to a
host over the LAN, see `docs/remote_play.md`.

The short version is:

```console
battleship remote-server --host 0.0.0.0 --port 8765
battleship remote-client --server http://HOST:8765 --name alice --bot my_bot:MyAgent
battleship remote-match --server http://HOST:8765 --bot-a alice --bot-b bob --games 5
```

Organizer wrappers:

```console
python scripts/organizer_remote_server.py --port 8765
python scripts/organizer_remote_round_robin.py --server http://HOST:8765 --bots-file examples/bots.txt
```

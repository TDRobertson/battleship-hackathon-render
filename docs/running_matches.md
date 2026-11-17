# Running Bots

## Simulate One Or More Games

```console
battleship simulate --games 20 --bot-a starter --bot-b hunt-target --seed 123
```

The summary reports `avg_move_time` and `max_move_time` in seconds for each
side, across all shot decisions in the run. The average is weighted by the
number of moves; `n/a` means the side made no shot decisions. The timing includes
failed or timed-out shot attempts, but excludes placement. With `--process`, it
includes communication with the worker process. Placement has a 5-second limit,
and each shot has a fresh 0.5-second limit; there is no cumulative game clock. Simulations and local
round-robin tournaments run without the visual move delay. `--process` also
isolates bots so a timed-out action can be terminated; in-process simulation
stops waiting for a timed-out bot but cannot forcibly stop its code.
For compatibility, CSV `a_remaining` and `b_remaining` fields remain present;
they report the unused portion of each player's most recent action limit, not a
game-wide balance. The bot `time_remaining` argument describes the current action's
limit. The rules fields `placement_seconds` and `thinking_seconds` give the
placement and shot limits respectively.

Timeouts are printed for each affected game, including the bot that timed out,
even without `--verbose`. Add `--verbose` to print every match result:

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

The human player is untimed. The bot has 5 seconds for placement and 0.5 seconds
per shot; graphical moves are displayed at least 0.5 seconds apart without charging
the display delay to the bot.
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

`simulate` uses persistent per-opponent memory by default, stored under
`results/memory`. Add `--no-memory` when you want each match to be independent,
or `--memory-dir path/to/memory` when you want a separate memory store for a
specific experiment.

## Benchmark Shots To Sink

To measure how many shots a bot needs to sink randomly placed fleets without an
opponent, use `benchmark`:

```console
battleship benchmark --games 100 --seed 2026 --bot starter-random --bot hunt-target --bot my_bot:MyAgent
```

Each bot faces the same sequence of random target fleets. The command prints the
average, minimum, and maximum shot count for each bot, plus average and maximum
shot decision time in seconds across all moves. Placement is excluded from those
statistics. Benchmark is target practice, with no cumulative game clock, but it
enforces the 5-second placement limit and 0.5-second shot limit. A timed-out action
stops the benchmark with an error. Write per-game shot counts to CSV for later
analysis:

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

A simple local round-robin can be run with the `tournament` command. For the
remote double-elimination format, see [Remote LAN Matches](remote_play.md):

```console
battleship tournament --process --games 50 --seed 1 --csv tournament.csv --bot alice_bot:MyAgent --bot bob_bot:MyAgent --bot starter
```

Bots remember repeated opponents by default, using `results/memory`. Use
`--memory-dir` to choose a different memory store:

```console
battleship tournament --process --games 50 --memory-dir results/memory --bot alice_bot:MyAgent --bot bob_bot:MyAgent --bot starter
```

The runner loads a mutable per-opponent memory dictionary before each match,
saves it afterward, and automatically maintains `memory["_stats"]` with common
opponent tendencies such as games, wins, recent opponent shots, opening shots,
center/edge/corner rates, and early parity rate. Add `--no-memory` to disable
memory, or use `--reset-memory` when you want a fresh run. See
`docs/opponent_memory.md` for bot-author guidance, including what to do when a
bot sees a new opponent with empty memory.

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

Start the server on the host laptop, then open `http://localhost:8765/` there
to watch live games and replays:

```console
battleship remote-server --host 0.0.0.0 --port 8765
```

Each competitor starts a client using the host's LAN address. For example, run
these on the two competitors' machines:

```console
battleship remote-client --server http://HOST:8765 --name alice --bot my_bot:MyAgent
battleship remote-client --server http://HOST:8765 --name bob --bot hunt-target
```

From the host or another machine on the LAN:

```console
battleship remote-list --server http://HOST:8765
battleship remote-match --server http://HOST:8765 --bot-a alice --bot-b bob --games 5
```

In another terminal, `battleship remote-matches --server http://HOST:8765`
shows current games and wins. `remote-stop` stops a series by ID, and
`remote-unregister` removes a player by ID. Each remote placement must complete
within 5 seconds and each shot within 0.5 seconds, including network time; heartbeats independently
mark disconnected clients offline after 15 seconds by default. See
[Remote LAN Matches](remote_play.md) for reconnection, timeout behavior, and
all command examples.

Organizer wrappers:

```console
python scripts/organizer_remote_server.py --port 8765
python scripts/organizer_remote_round_robin.py --server http://HOST:8765 --bots-file remote-players.txt
```

For the remote round robin, the bots file must contain registered player names
or IDs, one per line.

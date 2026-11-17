# Remote LAN Matches

Competitors run bots on their own machines while a host runs the authoritative
match server. Use this setup on a trusted LAN; see the safety notes below.

## Start the server and watch games

On the host laptop:

```console
battleship remote-server --host 0.0.0.0 --port 8765
```

Open **http://localhost:8765/** on the laptop to watch. Anyone on the LAN can
also open the host's address, such as `http://192.168.1.20:8765/`, if the
network and host firewall allow access. The dashboard has no login; anyone who
can reach the server can view it.

Each board shows one player's shots at the other player's fleet. Misses are
marked with a dot, hits with a cross, and sunk ships turn dark red. Coordinates
on the dashboard use row letters and one-based column numbers; bot coordinates
use zero-based `(row, col)` values. Validated ship placements are visible to
spectators during and after each game; a fleet that was never successfully
placed is absent. Anyone who can access the dashboard can see these positions.
To hide unhit ships during games, start the server with:

```console
battleship remote-server --host 0.0.0.0 --port 8765 --hide-ships
```

With `--hide-ships`, placements are revealed after a game finishes or is stopped.
The flag changes spectator visibility only; bot observations remain unchanged.
Each spectator can use **Hide ships** or **Show ships** to change their own
view, including during replay. This preference is saved in that browser and does
not affect other spectators. It cannot reveal ships withheld by the host;
previously fired shots and sunk ships remain visible when ships are hidden.

Use the match selector to choose a game, **Live** to follow its latest turn,
**Replay** to play it from the start at one shot every 0.5 seconds, and the turn
slider to scrub. The viewer checks for updates every 0.5 seconds and displays
newly received shots one at a time; after a slow connection it may briefly lag
behind. **Live** jumps to the latest shot. Live moves take at least 0.5 seconds
each; if a bot decides faster, the server waits for the remainder after its
decision. This display delay does not count toward the bot's action timeout.
The server retains the last 50 finished or stopped games plus active games in memory.
Tournament games are also retained so every pairing remains replayable. This
history disappears when the server restarts. Replay does not slow down matches.

## Connect and reconnect players

Each competitor runs an updated client from their own checkout:

```console
battleship remote-client --server http://192.168.1.20:8765 --name alice --bot my_bot:MyAgent
```

Built-in bots work too:

```console
battleship remote-client --server http://192.168.1.20:8765 --name bob --bot hunt-target
```

The client stays running and waits for match actions. Stop it with `Ctrl+C`.

The client saves its player ID and secret token in
`~/.battleship/remote-sessions/`, using one file per server URL and player
name. The file is created with owner-only permissions; keep it private. Run the
same command on the same machine to reconnect as the same player. The URL and
name must match the saved session. Use `--session-file PATH` to choose a separate
file, for example when running two players with the same name on one machine.

The server keeps registrations in memory. After a server restart or explicit
unregistration, the next client start creates a new registration and updates its
saved credentials. A second client using the same credentials replaces the first.
An individual `remote-match` series stops because a restarted bot cannot restore
its old in-memory game state. Tournament games use the reconnection policy below;
an interrupted game cannot be resumed.

## Check player availability

From any machine that can reach the host:

```console
battleship remote-list --server http://192.168.1.20:8765
```

The output includes each player's ID, status, queued actions, and time since last
seen. Use IDs when names are duplicated. Status means:

- `online`: the updated client is connected and can be selected for a match.
- `unresponsive`: an action timed out; the player cannot enter a new match until
  the client polls for work again or reconnects. A heartbeat alone does not clear
  this status.
- `offline`: the client missed its heartbeat deadline and cannot enter a new
  match. Its registration remains available for reconnection.
- `legacy`: an older client that does not send heartbeats. Update these clients;
  the server cannot automatically detect their disconnects using heartbeats.

Updated clients send a heartbeat every **5 seconds**, including while the bot
is thinking. After **15 seconds** without one, the server marks the player
offline and stops affected individual series. An interrupted individual game
has no winner unless an action timeout already decided the forfeit. Completed
results are retained. A returning heartbeat restores the connection; after a
timeout, the client must also poll again or resume its session before it becomes
available.

The server's `--disconnect-timeout` and client's `--heartbeat-interval` can
adjust these intervals. Allow room for network delays, and restart the server
and clients after updating their code. Legacy clients should also be restarted
with the updated code; use `remote-unregister` to remove stale registrations.

## Run and inspect matches

### Double-elimination tournament

To try the dashboard locally with nine `hunt-target` bots, run:

```console
battleship demo-tournament
```

Open the URL printed by the command to watch the tournament. It starts a server
bound to `127.0.0.1`, so its dashboard is accessible only from that machine. It
connects nine clients, then runs the same best-of-five double-elimination
tournament described below. The dashboard stays available after the champion is
decided; press `Ctrl+C` to stop the demo. The server chooses a free port by
default; use `--port 8765` to choose one. Add `--hide-ships` to hide ships during
the demo. The demo includes 30-second breaks between waves. Demo memory is
temporary.

With the server and clients running, start a tournament from any machine that
can reach the server:

```console
battleship tournament --server http://192.168.1.20:8765 --seed 2026 --csv tournament.csv
```

The tournament enters every player whose status is `online` at the start.
Offline, unresponsive, and legacy clients are excluded. If a selected player is
already playing another series, the tournament waits for that series to finish.
Independent pairings run concurrently. A player leaves the tournament after two
series losses. The winners bracket plays until its finalist is determined;
players with one loss wait until then before starting the losers bracket. The
winners finalist then waits for the losers-bracket finalist. If the undefeated
finalist loses the final, a second final decides the champion.

Each pairing is best of five: the first player to win three games wins the
series, so a pairing can finish after three, four, or five games. The player
moving first is randomized for each game using the tournament seed. Per-opponent
memory and bot lifecycle hooks are enabled for each game.
Memory is stored on the **server** under `results/memory`, keyed by player IDs
so players with identical names remain distinct. `--memory-dir` selects a
different server-side directory. Update both server and clients before running
a tournament.

When an undefeated player has no opponent in a bracket wave, the tournament
waits for an additional online player. It waits at least five seconds and while
other pairings in that wave are still running; then the player advances with a
bye. Use `--wait-seconds 15` to change the minimum wait. New players enter only
when they fill such an open slot, before the winners finalist is determined.
At least two players must participate.

If a player disconnects during a game, that game is forfeited at its action
deadline. The server waits up to **30 seconds** for the player to reconnect
before the next game. This is separate from the 15-second heartbeat deadline.
If they do not return, subsequent games in that pairing are recorded as
forfeits until a player reaches three wins. If the game already decided the
pairing, there is no wait between games; the normal wave break begins after all
pairings finish. A timeout can also temporarily mark an online bot
unresponsive; it can continue once it polls again. A reconnecting player must
resume the same saved session.

After all pairings in a wave finish, there is a **30-second break** before
advancement is decided and the next wave begins. If the pairing's winner is still
unavailable at the end of the break, the opponent advances instead. Three
disconnects in one bracket disqualify a player from further pairings in that
bracket: they drop to the losers bracket or, if already there, are eliminated. The current pairing is
completed first, and the disconnect count starts fresh in the losers bracket.
The server counts a missed heartbeat deadline or replacement of an active
session as a disconnect; a slow action with continuing heartbeats alone does not
count. If both opponents are unavailable, the tournament stops for organizer
attention. It also stops if no eligible winners-bracket finalist remains.

The command prints each pairing and the champion, and `--csv` writes game
results after successful completion. Match progress remains visible through the
dashboard and `remote-matches`. The dashboard shows both brackets, finals, live
series scores, byes, and advancement. Select a pairing to follow its current
round, use the round selector to replay an earlier game, or choose **All recent
matches** to return to the ordinary match view. Brackets and tournament games
remain available until the server restarts. If a series is manually stopped or a
player is unregistered, the tournament stops without declaring a champion. Fix
the problem and start a new tournament; there is no automatic resume.
`remote-match` and the existing local round-robin form of `tournament` retain
their existing behavior.

### Individual series

Start a series of games between registered player names or IDs:

```console
battleship remote-match --server http://192.168.1.20:8765 --bot-a alice --bot-b bob --games 5 --seed 2026 --verbose
```

Player A moves first in each game. The command waits for the series to finish
and prints a summary. `--verbose` prints every game's result; forfeits are
printed even without it. Run this command in a separate terminal if you want to
issue other organizer commands while it runs.

List ongoing series from another terminal:

```console
battleship remote-matches --server http://192.168.1.20:8765
```

Each line identifies the players, completed and total games, wins for A and B,
the current game and turn, the current `match` ID, and a `series` ID. Wins count
completed games in that `remote-match` invocation, including forfeits. Finished
series disappear from this list. The series ID distinguishes simultaneous series
between the same players.

Write completed game results to CSV:

```console
battleship remote-match --server http://192.168.1.20:8765 --bot-a alice --bot-b bob --games 20 --csv remote-results.csv
```

If a series stops early, the initiating command reports the stop and writes any
completed game results, including a timeout forfeit, to the CSV. An interrupted
game without a winner is not a completed result. If there are no completed
games, the command does not write a CSV file.

## Move timeouts and forfeits

Each remote placement has at most **5 seconds** and each shot **0.5 seconds**,
measured by the server from requesting the action until receiving the response, including queue and
network time. Exceeding the limit forfeits that game, even if the client is
still online. There is no cumulative game clock. Existing bot method signatures
are unchanged: `time_remaining` gives the current action limit, normally 5 seconds
for placement or 0.5 seconds for a shot, and is shorter if the server uses a
shorter `--action-timeout`. The official rules' `placement_seconds` and
`thinking_seconds` fields remain 5 and 0.5 respectively with a shorter server limit.

After an action timeout, the player is immediately marked `unresponsive`. In an
individual remote match, the forfeit counts but the rest of that series stops.
In a tournament pairing, the timeout loses only the current game; the player can
continue the pairing after becoming available, subject to the reconnection rules
above. Other ongoing series involving that player also stop without awarding
their interrupted games.
Late responses are ignored. This prevents a disconnected player from receiving
another loss while the server waits for the 15-second heartbeat deadline. Once the client
finishes its previous action and polls again, or reconnects, it can be selected
for new games; if heartbeats have expired, the connection must also recover.

The server's existing `--action-timeout` option can set a shorter limit for
both actions; placement is capped at 5 seconds and shots at 0.5 seconds even
when a larger value is configured. Its default is 5 seconds. The per-action limit is separate from the
heartbeat deadline. Tournament lifecycle hooks have a separate 30-second
server watchdog; the placement and shot limits apply only to those decisions.

Illegal placements, illegal shots, crashes, and timeouts also forfeit. If a game
ends before any shots, check the reason for a placement failure or timeout. The
dashboard, server console, and initiating command show forfeiture reasons.

## Stop a series or unregister a player

Use the `series` ID from `remote-matches` to stop an ongoing series. An
unambiguous current `match` ID also works:

```console
battleship remote-stop --server http://192.168.1.20:8765 --id SERIES_ID
```

The command requests a stop for the whole series, including remaining games.
The interrupted game is marked stopped with no winner; completed results remain
available to the initiating command. If multiple ongoing series have the same
current match ID, use the series ID.

Unregister a player using the ID from `remote-list`:

```console
battleship remote-unregister --server http://192.168.1.20:8765 --id PLAYER_ID
```

This removes the registration and stops ongoing series involving the player.
The server stops waiting immediately, although a bot already computing may keep
running until it finishes the action. Restart its client to register again.

## Organizer scripts

The server wrapper accepts the same timeout settings:

```console
python scripts/organizer_remote_server.py --port 8765 --disconnect-timeout 15 --action-timeout 5
```

For a round robin, create a file with one **registered remote player name or
ID** per line, for example `alice` and `bob`, then run:

```console
python scripts/organizer_remote_round_robin.py --server http://192.168.1.20:8765 --bots-file remote-players.txt
```

The wrapper runs every ordered pairing and writes results in
`results/remote_round_robin` by default. Check its output and CSVs for stopped
or partial series; the wrapper continues to the next pairing after a stopped
series, and later pairings can fail if a player is unavailable.

## How it works and LAN safety

Clients register or resume with a token, send heartbeats independently, and
long-poll for `place_ships` and `choose_shot` tasks. The server runs the rules
engine and records public shots for the dashboard. See `docs/agent_protocol.md`
for the HTTP endpoints.

The server is intended for a trusted LAN. It does not provide TLS, user
accounts, rate limiting, or sandboxing for hostile traffic. Anyone able to
reach it can view the dashboard and invoke match and organizer endpoints,
including starting or stopping series and unregistering players. Tokens and
other traffic sent over plain HTTP are not encrypted.

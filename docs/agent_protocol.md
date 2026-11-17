# Agent Protocol

Local process agents use newline-delimited JSON on standard input/output.
Standard error is reserved for diagnostic logs.

Transport messages are JSON-compatible. Incremental shot-result messages include
`protocol_version`, `match_id`, `action_id`, `observation_version`, `type`,
`shot`, `outcome`, and optional `sunk_ship` data.

`observation_version` belongs to one player's target-board observation and is
independent from `protocol_version`.

## Remote LAN transport

Remote matches use HTTP long-polling. The server runs the authoritative rules
engine; clients run their bots and return placements and shots.

1. A client calls `POST /api/register` with its name and heartbeat support, or
   `POST /api/resume` with its saved `bot_id` and token. The response provides a
   connection ID. Resuming replaces the previous connection and stops an active
   individual series; tournament series follow the reconnection policy below.
2. The client sends `POST /api/heartbeat` with its ID, token, and connection ID
   independently of bot actions. The defaults are one heartbeat every 5 seconds
   and an offline threshold of 15 seconds. Old clients without heartbeat support
   are shown as `legacy` and do not get automatic heartbeat-based expiry.
3. The client long-polls `POST /api/poll` with those credentials. The server
   returns no task or a `place_ships` / `choose_shot` task with an `action_id`.
4. The client sends `POST /api/respond` with its credentials and the matching
   `action_id`. Responses arriving after a timeout or stop are ignored.
5. The organizer starts a series with `POST /api/matches`. The response waits
   for the series and contains `reports` and `stopped`; a stopped series also
   contains `stop_reason`. Completed reports are retained when a series stops.

For double-elimination tournaments, updated clients also handle `start_match`,
`observe_opponent_shot`, and `end_match` tasks. These carry the normal bot
lifecycle data and synchronize mutable opponent memory with the server. The
server randomizes the first player per game and stores memory by player ID.
Tournament series reserve both players until the series ends. After an action
timeout or disconnect they wait up to 30 seconds for recovery before the next
game; if recovery fails, games are forfeited until the series is decided. Each
pairing is best of five and ends when a player wins three games. A 30-second
break follows each tournament wave before advancement is finalized. The losers
bracket starts only after the winners-bracket finalist has been decided.

Remote placements have a 5-second server-side limit, and shot decisions have a
0.5-second limit, including queue and network time. The existing `time_remaining` field reports
the per-action limit; there is no cumulative game clock. The tournament
`start_match`, `observe_opponent_shot`, and `end_match` lifecycle hooks have a
separate 30-second server watchdog. A placement or shot timeout forfeits the current game and
marks the player unresponsive; remaining games in an individual series stop. Other ongoing
series involving that player stop without awarding their interrupted games. A new
individual match cannot start with an offline or unresponsive player. An authenticated
poll or a resumed session clears the unresponsive state; heartbeat recovery is
also required if the player is offline.

The server also provides:

- `GET /api/bots`: registered players and their status.
- `GET /api/matches/ongoing`: active series, including game progress and wins.
- `GET /api/spectator/matches`: recent game histories, shots, and validated
  placements. The server's `--hide-ships` option withholds fleets during active
  games; placements are included after games end or stop. This setting does not
  alter bot observations.
- `GET /api/spectator/tournaments`: live and completed tournaments, bracket
  phase and finalist, pairings, series scores, advancement, and round IDs. Use
  `GET /api/spectator/matches?pair_id=PAIR_ID` for all games in one pairing;
  tournament replays are retained until the server restarts.
- `POST /api/matches/stop`: stop a series using an `id` containing its series ID
  or an unambiguous current match ID.
- `POST /api/bots/unregister`: unregister the player whose ID is in `id` and
  stop affected series.
- `GET /health`: server health check; `GET /` serves the browser dashboard.

The organizer endpoints have no authentication and HTTP traffic is not
encrypted. Use the server on a trusted LAN. The command-line wrappers, session
files, replay controls, and configuration are documented in
[Remote LAN Matches](remote_play.md).

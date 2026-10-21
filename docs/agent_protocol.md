# Agent Protocol

Local process agents use newline-delimited JSON on standard input/output.
Standard error is reserved for diagnostic logs.

Transport messages are JSON-compatible. Incremental shot-result messages include
`protocol_version`, `match_id`, `action_id`, `observation_version`, `type`,
`shot`, `outcome`, and optional `sunk_ship` data.

`observation_version` belongs to one player's target-board observation and is
independent from `protocol_version`.

## Remote LAN Transport

Remote LAN matches use the same `Agent` concepts over HTTP long-polling. The
server is authoritative; remote clients only answer action requests.

Typical flow:

1. Client registers with `POST /api/register`.
2. Client long-polls `POST /api/poll`.
3. Server returns either no task or a `place_ships` / `choose_shot` task.
4. Client sends `POST /api/respond` with the matching `action_id`.
5. Host starts games with `battleship remote-match`, which calls
   `POST /api/matches`.

The command-line wrappers are documented in `docs/remote_play.md`.

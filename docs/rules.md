# Rules

The official preset uses a 10 by 10 board, zero-based `(row, col)` coordinates,
and fleet slots with lengths `[5, 4, 3, 3, 2]`.

Ships may touch orthogonally or diagonally, but may not overlap. Turns alternate
after every accepted shot. There is no extra turn after a hit. Repeated shots are
illegal. Sinking feedback reveals the sunk slot and all cells occupied by that
ship. A player wins by sinking every opposing ship.

Each bot has up to 5 seconds for placement and 0.5 seconds for each shot;
there is no cumulative game clock. A timeout or illegal submitted action is an
immediate loss of the current game, not necessarily the pairing. Remote action deadlines include network time. See
[Remote LAN Matches](remote_play.md) for disconnects and series handling.

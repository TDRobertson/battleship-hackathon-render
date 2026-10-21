# Rules

The official preset uses a 10 by 10 board, zero-based `(row, col)` coordinates,
and fleet slots with lengths `[5, 4, 3, 3, 2]`.

Ships may touch orthogonally or diagonally, but may not overlap. Turns alternate
after every accepted shot. There is no extra turn after a hit. Repeated shots are
illegal. Sinking feedback reveals the sunk slot and all cells occupied by that
ship. A player wins by sinking every opposing ship.

Each player has 120 seconds total for placement and firing decisions. A timeout
or illegal submitted action is an immediate loss.

from __future__ import annotations

from dataclasses import dataclass, field

from core.models import Coord, Outcome, Phase, Player, ShipPlacement, ShotResult, SunkShip, Termination
from core.rules import Rules, official_rules


class InvalidAction(ValueError):
    pass


@dataclass(slots=True)
class ShipState:
    slot: int
    cells: tuple[Coord, ...]
    hits: set[Coord] = field(default_factory=set)

    @property
    def sunk(self) -> bool:
        return len(self.hits) == len(self.cells)


class GameEngine:
    def __init__(self, rules: Rules | None = None) -> None:
        self.rules = rules or official_rules()
        self.phase = Phase.PLACEMENT
        self.active_player = Player.A
        self.winner: Player | None = None
        self.termination_reason: str | None = None
        self._fleets: dict[Player, dict[int, ShipState]] = {Player.A: {}, Player.B: {}}
        self._occupied: dict[Player, dict[Coord, int]] = {Player.A: {}, Player.B: {}}
        self._shots: dict[Player, set[Coord]] = {Player.A: set(), Player.B: set()}
        self.events: list[ShotResult | Termination] = []

    def place_fleet(self, player: Player, placements: list[ShipPlacement]) -> None:
        self._ensure_mutable()
        if self.phase is not Phase.PLACEMENT:
            raise InvalidAction("placement phase is over")
        if self._fleets[player]:
            raise InvalidAction("fleet already placed")
        fleet, occupied = self._validate_fleet(placements)
        self._fleets[player] = fleet
        self._occupied[player] = occupied
        if self._fleets[Player.A] and self._fleets[Player.B]:
            self.phase = Phase.BATTLE
            self.active_player = Player.A

    def fire(self, player: Player, row: int, col: int) -> ShotResult:
        self._ensure_mutable()
        if self.phase is not Phase.BATTLE:
            raise InvalidAction("cannot fire before battle phase")
        if player is not self.active_player:
            raise InvalidAction("not active player")
        coord = self._validate_coord(row, col)
        if coord in self._shots[player]:
            raise InvalidAction("repeated shot")

        self._shots[player].add(coord)
        defender = player.opponent
        hit_slot = self._occupied[defender].get(coord)
        if hit_slot is None:
            result = ShotResult(player, coord, Outcome.MISS)
        else:
            ship = self._fleets[defender][hit_slot]
            ship.hits.add(coord)
            if ship.sunk:
                sunk = SunkShip(ship.slot, ship.cells)
                result = ShotResult(player, coord, Outcome.SUNK, sunk)
                if all(s.sunk for s in self._fleets[defender].values()):
                    self._end(player, "all ships sunk")
            else:
                result = ShotResult(player, coord, Outcome.HIT)

        self.events.append(result)
        if self.phase is Phase.BATTLE:
            self.active_player = defender
        return result

    def forfeit(self, loser: Player, reason: str) -> None:
        self._ensure_mutable()
        self._end(loser.opponent, reason)

    def public_result_for(self, result: ShotResult, recipient: Player) -> ShotResult:
        # Both players learn the same public firing result. Ordinary hits do not
        # expose ship identity; sunk results intentionally reveal the slot/cells.
        return result

    def fleet_cells(self, player: Player) -> dict[int, tuple[Coord, ...]]:
        return {slot: ship.cells for slot, ship in self._fleets[player].items()}

    def shots_by(self, player: Player) -> frozenset[Coord]:
        return frozenset(self._shots[player])

    def ship_hits(self, player: Player) -> dict[int, frozenset[Coord]]:
        return {slot: frozenset(ship.hits) for slot, ship in self._fleets[player].items()}

    def _end(self, winner: Player, reason: str) -> None:
        self.phase = Phase.GAME_OVER
        self.winner = winner
        self.termination_reason = reason
        self.events.append(Termination(winner, reason))

    def _ensure_mutable(self) -> None:
        if self.phase is Phase.GAME_OVER:
            raise InvalidAction("match has ended")

    def _validate_fleet(self, placements: list[ShipPlacement]) -> tuple[dict[int, ShipState], dict[Coord, int]]:
        slots = [p.slot for p in placements]
        required = set(self.rules.slots)
        if set(slots) != required or len(slots) != len(required):
            raise InvalidAction("fleet must contain every slot exactly once")

        occupied: dict[Coord, int] = {}
        fleet: dict[int, ShipState] = {}
        for placement in placements:
            cells = self.cells_for_placement(placement)
            for cell in cells:
                if cell in occupied:
                    raise InvalidAction("ships may not overlap")
                occupied[cell] = placement.slot
            fleet[placement.slot] = ShipState(placement.slot, cells)
        return fleet, occupied

    def cells_for_placement(self, placement: ShipPlacement) -> tuple[Coord, ...]:
        if placement.orientation not in ("horizontal", "vertical"):
            raise InvalidAction("invalid orientation")
        length = self.rules.ship_length(placement.slot)
        cells = []
        for i in range(length):
            row = placement.row + (i if placement.orientation == "vertical" else 0)
            col = placement.col + (i if placement.orientation == "horizontal" else 0)
            cells.append(self._validate_coord(row, col))
        return tuple(cells)

    def _validate_coord(self, row: int, col: int) -> Coord:
        if not isinstance(row, int) or not isinstance(col, int):
            raise InvalidAction("coordinates must be integers")
        if row < 0 or col < 0 or row >= self.rules.rows or col >= self.rules.cols:
            raise InvalidAction("coordinate out of bounds")
        return (row, col)

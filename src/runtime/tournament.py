from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from runtime.remote import (
    RemoteError, TOURNAMENT_MAX_GAMES, TOURNAMENT_WINS_NEEDED, create_remote_tournament, get_remote_tournament, list_ongoing_remote_matches, list_remote_bots,
    run_remote_tournament_series, update_remote_tournament,
)

BREAK_SECONDS = 30.0


def run_tournament(server: str, seed: int, wait_seconds: float, memory_dir: str) -> dict:
    """Run bracket waves, admitting new players when an undefeated player has a bye."""
    if wait_seconds < 0:
        raise RemoteError("--wait-seconds must be non-negative")
    rng = random.Random(seed)
    entrants = {bot["bot_id"]: bot["name"] for bot in list_remote_bots(server) if bot["status"] == "online"}
    if not entrants:
        raise RemoteError("no online players connected")
    tournament_id = create_remote_tournament(server, entrants, seed)

    def publish(event: dict) -> None:
        update_remote_tournament(server, tournament_id, event)

    def play_pair(a: str, b: str, pair_id: str, series_seed: int) -> dict:
        try:
            # Wait for independent series before reserving either player.
            while True:
                bots = {bot["bot_id"]: bot for bot in list_remote_bots(server)}
                for bot_id in (a, b):
                    if bot_id not in bots:
                        raise RemoteError(f"player {entrants[bot_id]!r} was unregistered")
                busy = {match[key] for match in list_ongoing_remote_matches(server) for key in ("bot_a_id", "bot_b_id")}
                if a not in busy and b not in busy:
                    break
                time.sleep(0.2)
            return run_remote_tournament_series(server, a, b, series_seed, memory_dir, tournament_id, pair_id)
        except Exception as exc:
            publish({"type": "pair_error", "pair_id": pair_id, "reason": str(exc)})
            raise

    try:
        losses = {bot_id: 0 for bot_id in entrants}
        reports, pairings = [], []
        wave = 0
        finalist_determined = False
        with ThreadPoolExecutor() as pool:
            while True:
                wave += 1
                undefeated = [bot for bot in losses if losses[bot] == 0]
                defeated = [bot for bot in losses if losses[bot] == 1]
                if not undefeated and not finalist_determined:
                    raise RemoteError("the winners bracket has no eligible finalist")
                winners_open = len(undefeated) > 1 or (len(undefeated) == 1 and not defeated)
                if not winners_open and undefeated:
                    finalist_determined = True
                phase = "winners" if winners_open else "losers" if len(defeated) >= 2 else "final"
                publish({"type": "wave", "wave": wave, "phase": phase,
                         "finalist_id": undefeated[0] if not winners_open and undefeated else None})
                final_reset = not undefeated and len(defeated) == 2
                rng.shuffle(undefeated)
                rng.shuffle(defeated)
                deadline = time.monotonic() + wait_seconds
                futures = []

                def start_pair(a: str, b: str, bracket: str) -> None:
                    pair_id = uuid4().hex
                    publish({"type": "pair", "pair_id": pair_id, "wave": wave, "bracket": bracket,
                             "bot_a": a, "bot_b": b, "final_reset": final_reset and bracket == "losers"})
                    print(f"{bracket}: {entrants[a]} vs {entrants[b]}", flush=True)
                    future = pool.submit(play_pair, a, b, pair_id, rng.randrange(2**32))
                    futures.append((a, b, bracket, pair_id, future))

                active_groups = (("winners", undefeated),) if winners_open else (("losers", defeated),)
                for bracket, group in active_groups:
                    while len(group) >= 2:
                        start_pair(group.pop(), group.pop(), bracket)

                if winners_open and undefeated:
                    publish({"type": "waiting", "bot_id": undefeated[0], "bracket": "winners"})
                    while time.monotonic() < deadline or any(not future.done() for _, _, _, _, future in futures):
                        newcomers = [bot for bot in list_remote_bots(server)
                                     if bot["status"] == "online" and bot["bot_id"] not in entrants]
                        if newcomers:
                            newcomer = newcomers[0]
                            bot_id = newcomer["bot_id"]
                            entrants[bot_id] = newcomer["name"]
                            losses[bot_id] = 0
                            publish({"type": "entrant", "bot_id": bot_id, "name": newcomer["name"]})
                            publish({"type": "waiting", "bot_id": None})
                            start_pair(undefeated.pop(), bot_id, "winners")
                            break
                        time.sleep(0.2)
                    publish({"type": "waiting", "bot_id": None})

                if not futures:
                    if undefeated and defeated:
                        start_pair(undefeated.pop(), defeated.pop(), "final")
                    elif len(losses) == 1:
                        raise RemoteError("tournament requires at least two online players")
                    else:
                        champion = next((bot for bot in losses if losses[bot] < 2), None)
                        if champion is None:
                            raise RemoteError("tournament has no eligible players")
                        publish({"type": "finish", "status": "finished", "champion_id": champion})
                        return {"champion_id": champion, "champion": entrants[champion], "reports": reports, "pairings": pairings}

                for bracket, group in active_groups:
                    for bot_id in group:
                        publish({"type": "bye", "wave": wave, "bracket": bracket, "bot_id": bot_id})

                wave_results = []
                for a, b, bracket, pair_id, future in futures:
                    result = future.result()
                    games = result["reports"]
                    wins_a = sum(game["winner_bot"] == a for game in games)
                    wins_b = sum(game["winner_bot"] == b for game in games)
                    if (result.get("stopped") or len(games) > TOURNAMENT_MAX_GAMES or wins_a + wins_b != len(games)
                            or max(wins_a, wins_b) != TOURNAMENT_WINS_NEEDED
                            or not games or games[-1]["winner_bot"] != (a if wins_a > wins_b else b)):
                        raise RemoteError(f"series {entrants[a]} vs {entrants[b]} stopped: {result.get('stop_reason', 'incomplete series')}")
                    winner, loser = (a, b) if wins_a > wins_b else (b, a)
                    reports.extend(games)
                    wave_results.append((a, b, bracket, pair_id, winner, loser))
                    print(f"{entrants[winner]} wins {max(wins_a, wins_b)}-{min(wins_a, wins_b)}; advancement pending", flush=True)

                # No next pairing starts until the entire wave and its break finish.
                publish({"type": "break", "until": time.time() + BREAK_SECONDS, "seconds": BREAK_SECONDS})
                print(f"All pairings finished. Break: {BREAK_SECONDS:g} seconds.", flush=True)
                deadline = time.monotonic() + BREAK_SECONDS
                next_status_check = time.monotonic()
                while time.monotonic() < deadline:
                    if time.monotonic() >= next_status_check:
                        if get_remote_tournament(server, tournament_id).get("status", "running") != "running":
                            raise RemoteError("tournament was stopped during the break")
                        next_status_check = time.monotonic() + 1.0
                    time.sleep(min(0.2, max(0, deadline - time.monotonic())))
                snapshot = get_remote_tournament(server, tournament_id)
                availability = {bot["bot_id"]: bot["status"] == "online" for bot in list_remote_bots(server)}
                for a, b, bracket, pair_id, winner, loser in wave_results:
                    forced = {bot_id for bot_id in (a, b)
                              if snapshot["entrants"][bot_id]["disconnects"]["winners" if losses[bot_id] == 0 else "losers"] >= 3}
                    reason = None
                    if winner in forced or not availability.get(winner, False):
                        reason = "three disconnects in this bracket" if winner in forced else "winner did not reconnect before the break ended"
                        if loser not in forced and availability.get(loser, False):
                            winner, loser = loser, winner
                        elif loser in forced:
                            winner, loser = None, None
                            reason = "both players reached the disconnect limit"
                        else:
                            raise RemoteError("both players are unavailable after the break")
                    for bot_id in (a, b):
                        if bot_id != winner:
                            losses[bot_id] = min(2, losses[bot_id] + 1)
                    publish({"type": "decision", "pair_id": pair_id, "winner": winner, "loser": loser,
                             "reason": reason, "losses": {a: losses[a], b: losses[b]}})
                    pairings.append({"bracket": bracket, "bot_a": a, "bot_b": b, "winner": winner, "loser": loser})
                    if winner:
                        print(f"{entrants[winner]} advances" + (f" ({reason})" if reason else ""), flush=True)
                    else:
                        print(f"Neither player advances in this bracket: {reason}", flush=True)
                for bracket, group in active_groups:
                    for bot_id in group:
                        reason = None
                        if snapshot["entrants"][bot_id]["disconnects"][bracket] >= 3:
                            losses[bot_id] = min(2, losses[bot_id] + 1)
                            reason = "three disconnects in this bracket"
                        publish({"type": "bye_decision", "wave": wave, "bot_id": bot_id,
                                 "losses": losses[bot_id], "reason": reason})
                # Players waiting for the other bracket are not taking a bye;
                # enforce the disconnect limit before their next pairing.
                idle_group = defeated if winners_open else undefeated
                for bot_id in idle_group:
                    bracket = "winners" if losses[bot_id] == 0 else "losers"
                    if snapshot["entrants"][bot_id]["disconnects"][bracket] >= 3:
                        losses[bot_id] = min(2, losses[bot_id] + 1)
                        publish({"type": "disqualification", "wave": wave, "bot_id": bot_id,
                                 "bracket": bracket, "losses": losses[bot_id], "reason": "three disconnects in this bracket"})
                publish({"type": "break", "until": None})
                remaining = [bot for bot, count in losses.items() if count < 2]
                if len(remaining) == 1:
                    champion = remaining[0]
                    publish({"type": "finish", "status": "finished", "champion_id": champion})
                    return {"champion_id": champion, "champion": entrants[champion], "reports": reports, "pairings": pairings}
    except BaseException as exc:
        try:
            publish({"type": "finish", "status": "stopped", "reason": str(exc) or "tournament interrupted"})
        except Exception:
            pass
        raise

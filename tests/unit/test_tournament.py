import threading
from collections import Counter, defaultdict

import pytest

from runtime import tournament
from runtime.remote import RemoteError


def _bot(name):
    return {"bot_id": name, "name": name, "status": "online"}


@pytest.fixture(autouse=True)
def tournament_events(monkeypatch, request):
    monkeypatch.setattr(tournament, "create_remote_tournament", lambda *args: "tournament")
    monkeypatch.setattr(tournament, "update_remote_tournament", lambda *args: None)
    monkeypatch.setattr(tournament, "get_remote_tournament", lambda *args: {
        "entrants": defaultdict(lambda: {"disconnects": {"winners": 0, "losers": 0}})
    })
    if request.node.name != "test_thirty_second_break_precedes_losers_bracket":
        monkeypatch.setattr(tournament, "BREAK_SECONDS", 0)


def _run(monkeypatch, players, outcomes, wait=0):
    monkeypatch.setattr(tournament, "list_remote_bots", lambda server: players)
    monkeypatch.setattr(tournament, "list_ongoing_remote_matches", lambda server: [])
    calls = []
    lock = threading.Lock()

    def series(server, a, b, seed, memory_dir, tournament_id, pair_id):
        with lock:
            calls.append((a, b, seed, memory_dir))
            winner = outcomes(a, b)
        return {"reports": [{"winner_bot": winner} for _ in range(3)], "stopped": False}

    monkeypatch.setattr(tournament, "run_remote_tournament_series", series)
    return tournament.run_tournament("server", 9, wait, "memory"), calls


def test_double_elimination_and_final_reset(monkeypatch):
    count = Counter()
    first_winner = []

    def outcome(a, b):
        count[frozenset((a, b))] += 1
        # With two entrants, the undefeated player's first loss forces a reset.
        if not first_winner:
            first_winner.append(a)
        return next(player for player in (a, b) if player != first_winner[0]) if count[frozenset((a, b))] == 2 else first_winner[0]

    result, calls = _run(monkeypatch, [_bot("alice"), _bot("bob")], outcome)
    assert len(calls) == 3
    assert [item["bracket"] for item in result["pairings"]] == ["winners", "final", "losers"]
    losses = Counter(item["loser"] for item in result["pairings"])
    assert losses[result["champion_id"]] == 1
    assert sorted(losses.values()) == [1, 2]
    assert len(result["reports"]) == 9


@pytest.mark.parametrize("size", [3, 4, 5, 8])
def test_every_player_is_eliminated_after_two_losses(monkeypatch, size):
    players = [_bot(str(i)) for i in range(size)]
    result, calls = _run(monkeypatch, players, lambda a, b: min(a, b))
    losses = Counter(item["loser"] for item in result["pairings"])
    assert all(losses[bot["bot_id"]] == 2 for bot in players if bot["bot_id"] != result["champion_id"])
    assert losses[result["champion_id"]] < 2
    assert len(calls) in (2 * size - 2, 2 * size - 1)


def test_new_online_player_fills_bye(monkeypatch):
    players = [_bot("alice"), _bot("bob"), _bot("carol")]
    polling = 0
    def bots(server):
        nonlocal polling
        polling += 1
        if polling >= 3:
            return players + [_bot("dave"), {**_bot("offline"), "status": "offline"}]
        return players
    monkeypatch.setattr(tournament, "list_remote_bots", bots)
    monkeypatch.setattr(tournament, "list_ongoing_remote_matches", lambda server: [])
    monkeypatch.setattr(tournament, "run_remote_tournament_series", lambda server, a, b, seed, memory, tournament_id, pair_id: {"reports": [{"winner_bot": a}] * 3})
    result = tournament.run_tournament("server", 1, 0.05, "memory")
    ids = {p[k] for p in result["pairings"] for k in ("bot_a", "bot_b")}
    assert ids == {"alice", "bob", "carol", "dave"}


def test_stopped_series_cannot_crown_champion(monkeypatch):
    monkeypatch.setattr(tournament, "list_remote_bots", lambda server: [_bot("alice"), _bot("bob")])
    monkeypatch.setattr(tournament, "list_ongoing_remote_matches", lambda server: [])
    monkeypatch.setattr(tournament, "run_remote_tournament_series", lambda *args: {"reports": [], "stopped": True, "stop_reason": "disconnected"})
    with pytest.raises(RemoteError, match="disconnected"):
        tournament.run_tournament("server", 1, 0, "memory")


def test_tournament_publishes_waves_byes_and_champion(monkeypatch):
    events = []
    monkeypatch.setattr(tournament, "update_remote_tournament", lambda server, tournament_id, event: events.append(event))
    result, _ = _run(monkeypatch, [_bot("a"), _bot("b"), _bot("c")], lambda a, b: min(a, b))
    assert events[0] == {"type": "wave", "wave": 1, "phase": "winners", "finalist_id": None}
    assert any(event["type"] == "bye" and event["bracket"] == "winners" for event in events)
    assert len([event for event in events if event["type"] == "pair"]) == len(result["pairings"])
    assert events[-1] == {"type": "finish", "status": "finished", "champion_id": result["champion_id"]}


def test_disconnected_pair_winner_is_replaced_after_break(monkeypatch):
    bots = [_bot("a"), _bot("b")]
    offline = set()
    events = []
    monkeypatch.setattr(tournament, "list_remote_bots", lambda server: [
        {**bot, "status": "offline" if bot["bot_id"] in offline else "online"} for bot in bots
    ])
    monkeypatch.setattr(tournament, "list_ongoing_remote_matches", lambda server: [])
    monkeypatch.setattr(tournament, "update_remote_tournament", lambda server, tournament_id, event: events.append(event))
    def series(server, a, b, seed, memory_dir, tournament_id, pair_id):
        if not offline:
            offline.add(a)
            return {"reports": [{"winner_bot": bot} for bot in (a, b, a, b, a)]}
        else:
            winner = b if a in offline else a
        return {"reports": [{"winner_bot": winner}] * 3}
    monkeypatch.setattr(tournament, "run_remote_tournament_series", series)
    result = tournament.run_tournament("server", 9, 0, "memory")
    first = next(event for event in events if event["type"] == "decision")
    assert first["winner"] not in offline and first["loser"] in offline
    assert "did not reconnect" in first["reason"]
    assert result["champion_id"] == first["winner"]


def test_three_disconnects_move_pair_winner_to_losers_bracket(monkeypatch):
    events, flagged = [], set()
    monkeypatch.setattr(tournament, "update_remote_tournament", lambda server, tournament_id, event: events.append(event))
    def get_tournament(*args):
        entrants = defaultdict(lambda: {"disconnects": {"winners": 0, "losers": 0}})
        for bot_id in flagged:
            entrants[bot_id]["disconnects"]["winners"] = 3
        return {"entrants": entrants}
    monkeypatch.setattr(tournament, "get_remote_tournament", get_tournament)
    def winner(a, b):
        if not flagged:
            flagged.add(a)
            return a
        return b if a in flagged else a
    result, _ = _run(monkeypatch, [_bot("a"), _bot("b")], winner)
    first = next(event for event in events if event["type"] == "decision")
    assert first["loser"] in flagged and first["losses"][first["loser"]] == 1
    assert "three disconnects" in first["reason"]
    assert result["champion_id"] == first["winner"]


def test_break_starts_after_all_pairings_and_delays_next_wave(monkeypatch):
    import time

    events, finished = [], []
    lock = threading.Lock()
    monkeypatch.setattr(tournament, "BREAK_SECONDS", 0.1)
    monkeypatch.setattr(tournament, "update_remote_tournament", lambda server, tournament_id, event: events.append((time.monotonic(), event)))
    def winner(a, b):
        with lock:
            finished.append(time.monotonic())
        return min(a, b)
    _run(monkeypatch, [_bot(str(i)) for i in range(4)], winner)
    wave2 = next(timestamp for timestamp, event in events if event["type"] == "wave" and event["wave"] == 2)
    break_start = next(timestamp for timestamp, event in events if event["type"] == "break" and event["until"] is not None)
    assert break_start >= max(finished[:2])
    assert wave2 - break_start >= 0.09


def test_three_disconnects_in_losers_bracket_eliminate_player(monkeypatch):
    events = []
    monkeypatch.setattr(tournament, "update_remote_tournament", lambda server, tournament_id, event: events.append(event))
    def get_tournament(*args):
        entrants = defaultdict(lambda: {"disconnects": {"winners": 0, "losers": 0}})
        if any(event["type"] == "decision" for event in events):
            entrants["b"]["disconnects"]["losers"] = 3
        return {"entrants": entrants}
    monkeypatch.setattr(tournament, "get_remote_tournament", get_tournament)
    matches = Counter()
    def winner(a, b):
        matches["played"] += 1
        return "a" if matches["played"] == 1 else "b"
    result, _ = _run(monkeypatch, [_bot("a"), _bot("b")], winner)
    decision = [event for event in events if event["type"] == "decision"][-1]
    assert decision["winner"] == "a" and decision["loser"] == "b"
    assert decision["losses"]["b"] == 2
    assert result["champion_id"] == "a"


@pytest.mark.parametrize("size", [3, 5, 8, 9])
def test_losers_bracket_waits_for_winners_finalist(monkeypatch, size):
    events = []
    monkeypatch.setattr(tournament, "update_remote_tournament", lambda server, tournament_id, event: events.append(event))
    result, _ = _run(monkeypatch, [_bot(str(i)) for i in range(size)], lambda a, b: min(a, b))
    scheduled = [event for event in events if event["type"] == "pair"]
    winner_pairs = [event for event in scheduled if event["bracket"] == "winners"]
    loser_pairs = [event for event in scheduled if event["bracket"] == "losers"]
    assert len(winner_pairs) == size - 1
    assert max(pair["wave"] for pair in winner_pairs) < min(pair["wave"] for pair in loser_pairs)
    first_loser_wave = min(pair["wave"] for pair in loser_pairs)
    phase = next(event for event in events if event["type"] == "wave" and event["wave"] == first_loser_wave)
    last_winner_decision = next(index for index, event in enumerate(events)
                                if event["type"] == "decision" and event["pair_id"] == winner_pairs[-1]["pair_id"])
    first_loser_pair = next(index for index, event in enumerate(events)
                            if event["type"] == "pair" and event["bracket"] == "losers")
    assert last_winner_decision < first_loser_pair
    last_winner = next(pair for pair in result["pairings"] if pair["bracket"] == "winners" and
                       pair["bot_a"] == winner_pairs[-1]["bot_a"] and pair["bot_b"] == winner_pairs[-1]["bot_b"])
    assert phase["finalist_id"] == last_winner["winner"]
    assert not any(event["type"] == "bye" and event["bracket"] == "losers" and event["wave"] < first_loser_wave for event in events)


def test_newcomers_do_not_change_winners_finalist_after_losers_start(monkeypatch):
    events = []
    players = [_bot(str(i)) for i in range(4)]
    def update(server, tournament_id, event):
        events.append(event)
    def bots(server):
        if any(event["type"] == "wave" and event["phase"] == "losers" for event in events):
            return players + [_bot("late")]
        return players
    monkeypatch.setattr(tournament, "update_remote_tournament", update)
    monkeypatch.setattr(tournament, "list_remote_bots", bots)
    monkeypatch.setattr(tournament, "list_ongoing_remote_matches", lambda server: [])
    monkeypatch.setattr(tournament, "run_remote_tournament_series", lambda server, a, b, seed, memory, tournament_id, pair_id: {"reports": [{"winner_bot": a}] * 3})
    result = tournament.run_tournament("server", 1, 0.01, "memory")
    assert all("late" not in (pair["bot_a"], pair["bot_b"]) for pair in result["pairings"])
    assert not any(event["type"] == "entrant" and event["bot_id"] == "late" for event in events)


def test_waiting_losers_bracket_player_with_three_disconnects_is_eliminated(monkeypatch):
    events = []
    monkeypatch.setattr(tournament, "update_remote_tournament", lambda server, tournament_id, event: events.append(event))
    def snapshot(*args):
        entrants = defaultdict(lambda: {"disconnects": {"winners": 0, "losers": 0}})
        decisions = [event for event in events if event["type"] == "decision"]
        if decisions:
            entrants[decisions[0]["loser"]]["disconnects"]["losers"] = 3
        return {"entrants": entrants}
    monkeypatch.setattr(tournament, "get_remote_tournament", snapshot)
    result, _ = _run(monkeypatch, [_bot(str(i)) for i in range(4)], lambda a, b: min(a, b))
    penalty = next(event for event in events if event["type"] == "disqualification")
    assert penalty["bracket"] == "losers" and penalty["losses"] == 2
    assert not any(penalty["bot_id"] in (pair["bot_a"], pair["bot_b"]) for pair in result["pairings"] if pair["bracket"] in ("losers", "final"))


def test_no_losers_matches_when_winners_bracket_has_no_eligible_finalist(monkeypatch):
    events = []
    monkeypatch.setattr(tournament, "update_remote_tournament", lambda server, tournament_id, event: events.append(event))
    monkeypatch.setattr(tournament, "get_remote_tournament", lambda *args: {
        "entrants": defaultdict(lambda: {"disconnects": {"winners": 3, "losers": 0}})
    })
    with pytest.raises(RemoteError, match="no eligible finalist"):
        _run(monkeypatch, [_bot("a"), _bot("b")], lambda a, b: a)
    assert not any(event["type"] == "pair" and event["bracket"] == "losers" for event in events)


def test_finalist_can_drop_to_losers_after_bracket_has_started(monkeypatch):
    events = []
    monkeypatch.setattr(tournament, "update_remote_tournament", lambda server, tournament_id, event: events.append(event))
    def snapshot(*args):
        entrants = defaultdict(lambda: {"disconnects": {"winners": 0, "losers": 0}})
        if any(event["type"] == "wave" and event["phase"] == "losers" for event in events):
            entrants["0"]["disconnects"]["winners"] = 3
        return {"entrants": entrants}
    monkeypatch.setattr(tournament, "get_remote_tournament", snapshot)
    result, _ = _run(monkeypatch, [_bot(str(i)) for i in range(4)], lambda a, b: min(a, b))
    penalty = next(event for event in events if event["type"] == "disqualification")
    assert penalty["bot_id"] == "0" and penalty["bracket"] == "winners" and penalty["losses"] == 1
    assert any(pair["bracket"] == "losers" and "0" in (pair["bot_a"], pair["bot_b"]) for pair in result["pairings"])


def test_thirty_second_break_precedes_losers_bracket(monkeypatch):
    from runtime.clocks import FakeClock

    clock = FakeClock()
    events = []
    assert tournament.BREAK_SECONDS == 30.0
    monkeypatch.setattr(tournament.time, "monotonic", clock)
    monkeypatch.setattr(tournament.time, "sleep", clock.advance)
    monkeypatch.setattr(tournament, "update_remote_tournament", lambda server, tournament_id, event: events.append(event))
    _run(monkeypatch, [_bot(str(i)) for i in range(4)], lambda a, b: min(a, b))
    breaks = [event for event in events if event["type"] == "break" and event["until"] is not None]
    assert breaks and all(event["seconds"] == 30.0 for event in breaks)
    losers_phase = next(index for index, event in enumerate(events) if event["type"] == "wave" and event["phase"] == "losers")
    last_winners_pair = max(index for index, event in enumerate(events) if event["type"] == "pair" and event["bracket"] == "winners")
    assert any(event["type"] == "break" and event.get("seconds") == 30.0 for event in events[last_winners_pair:losers_phase])

import threading
import urllib.request
import pytest

from runtime.demo import run_demo
from runtime.remote import list_remote_bots, run_remote_tournament_series
from sdk.memory import load_memory_session

pytestmark = pytest.mark.usefixtures("unpaced_matches")


@pytest.mark.parametrize("hide_ships", [False, True])
def test_demo_connects_nine_hunt_target_clients_and_keeps_server_running(hide_ships):
    stop, finished = threading.Event(), threading.Event()
    captured, errors = {}, []

    def start(server, seed, memory_dir):
        try:
            bots = list_remote_bots(server)
            assert len(bots) == 9
            assert {bot["name"] for bot in bots} == {f"Hunt Target {index}" for index in range(1, 10)}
            assert all(bot["status"] == "online" for bot in bots)
            a, b = bots[0]["bot_id"], bots[1]["bot_id"]
            result = run_remote_tournament_series(server, a, b, seed, memory_dir)
            assert not result["stopped"] and 3 <= len(result["reports"]) <= 5
            assert all(report["reason"] == "all ships sunk" and report["turns"] > 0 for report in result["reports"])
            assert load_memory_session(memory_dir, a, b).memory["_stats"]["games"] == len(result["reports"])
            import json
            with urllib.request.urlopen(server + "/api/spectator/matches") as response:
                matches = json.load(response)["matches"]
            assert matches and all(match["live_ships_visible"] is (not hide_ships) for match in matches)
            captured["server"] = server
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()
        return int(bool(errors))

    thread = threading.Thread(target=lambda: run_demo(0, 17, start, stop, hide_ships), daemon=True)
    thread.start()
    try:
        assert finished.wait(60), "demo series did not finish"
        assert not errors
        # The dashboard remains reachable after the demo tournament returns.
        with urllib.request.urlopen(captured["server"] + "/") as response:
            assert b"Remote matches" in response.read()
    finally:
        stop.set()
        thread.join(timeout=15)
    assert not thread.is_alive()


def test_demo_stops_active_tournament_and_cleans_up():
    import json
    import time

    from runtime.remote import RemoteError
    from runtime.tournament import run_tournament

    stop, started = threading.Event(), threading.Event()
    captured = {}

    def start(server, seed, memory_dir):
        captured["server"] = server
        started.set()
        try:
            run_tournament(server, seed, 0, memory_dir)
        except RemoteError:
            return 1
        return 0

    thread = threading.Thread(target=lambda: run_demo(0, 18, start, stop), daemon=True)
    thread.start()
    try:
        assert started.wait(10)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with urllib.request.urlopen(captured["server"] + "/api/spectator/tournaments") as response:
                tournaments = json.load(response)["tournaments"]
            if tournaments and any(pair["status"] == "playing" for pair in tournaments[0]["pairings"]):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("demo tournament did not start")
    finally:
        stop.set()
        thread.join(timeout=15)
    assert not thread.is_alive()
    try:
        urllib.request.urlopen(captured["server"] + "/health", timeout=1)
    except OSError:
        pass
    else:
        raise AssertionError("demo server remained open after stopping")


def test_demo_can_stop_during_tournament_break(monkeypatch):
    import json
    import time

    from runtime.remote import RemoteError
    from runtime.tournament import run_tournament

    monkeypatch.setattr("runtime.tournament.run_remote_tournament_series", lambda server, a, b, seed, memory, tournament_id, pair_id: {"reports": [{"winner_bot": a}] * 3})
    stop, started = threading.Event(), threading.Event()
    captured = {}
    def start(server, seed, memory):
        captured["server"] = server
        started.set()
        try:
            run_tournament(server, seed, 0, memory)
        except RemoteError:
            return 1
        return 0
    thread = threading.Thread(target=lambda: run_demo(0, 3, start, stop), daemon=True)
    thread.start()
    try:
        assert started.wait(10)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with urllib.request.urlopen(captured["server"] + "/api/spectator/tournaments") as response:
                tournaments = json.load(response)["tournaments"]
            if tournaments and tournaments[0].get("break_until"):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("demo did not enter its break")
    finally:
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive()

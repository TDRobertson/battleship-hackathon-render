import json
import threading
import urllib.request
from unittest.mock import patch

from core.models import Player
from core.rules import official_rules
from sdk.placement import random_legal_fleet
import random
import pytest
from runtime.remote import RemoteBotClient, RemoteHubState, RemoteServerAgent, _run_remote_matches, create_remote_server, list_ongoing_remote_matches, list_remote_bots, run_remote_match_request, run_remote_matches

pytestmark = pytest.mark.usefixtures("unpaced_matches")


def test_remote_server_runs_match_between_lan_clients():
    server = create_remote_server("127.0.0.1", 0, action_timeout=10.0)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    stop = threading.Event()
    clients = [
        RemoteBotClient(url, "starter-random", "alice", seed=1, poll_timeout=0.2),
        RemoteBotClient(url, "starter-random", "bob", seed=2, poll_timeout=0.2),
    ]
    client_threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    try:
        for thread in client_threads:
            thread.start()

        _wait_for_bots(url, 2)
        reports = run_remote_matches(url, "alice", "bob", games=1, seed=7)

        assert len(reports) == 1
        assert reports[0]["winner_bot"] in {"alice", "bob"}
        assert reports[0]["turns"] > 0
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in client_threads:
            thread.join(timeout=1.0)
        server_thread.join(timeout=1.0)


def _wait_for_bots(url: str, count: int) -> None:
    for _ in range(50):
        if len(list_remote_bots(url)) >= count:
            return
        threading.Event().wait(0.05)
    raise AssertionError("remote bots did not register")


def test_remote_placement_can_load_for_over_half_second_before_play():
    import time

    class SlowLoadingClient(RemoteBotClient):
        def _handle_task(self, task):
            if task.get("type") == "place_ships":
                assert task["time_remaining"] == 5.0
                time.sleep(0.8)
            return super()._handle_task(task)

    server = create_remote_server("127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop = threading.Event()
    clients = [SlowLoadingClient(url, "hunt-target", "alice", poll_timeout=0.1),
               RemoteBotClient(url, "hunt-target", "bob", poll_timeout=0.1)]
    threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    try:
        for thread in threads:
            thread.start()
        _wait_for_bots(url, 2)
        result = run_remote_match_request(url, "alice", "bob", 1, 7)
        assert not result["stopped"]
        assert result["reports"][0]["reason"] == "all ships sunk"
        assert result["reports"][0]["turns"] > 0
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in threads:
            thread.join(timeout=1)
        server_thread.join(timeout=1)


@pytest.mark.parametrize("hide_ships", [False, True])
def test_spectator_sees_live_shots_and_finished_match(hide_ships):
    shot_tasks = []
    class PausedClient(RemoteBotClient):
        def _handle_task(self, task):
            if task.get("type") == "choose_shot":
                shot_tasks.append(task)
                waiting.set()
                assert release.wait(5)
            return super()._handle_task(task)

    server = create_remote_server("127.0.0.1", 0, action_timeout=10.0, hide_ships=hide_ships)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop, waiting, release = threading.Event(), threading.Event(), threading.Event()
    clients = [
        RemoteBotClient(url, "starter-random", "alice", seed=1, poll_timeout=0.1),
        PausedClient(url, "starter-random", "bob", seed=2, poll_timeout=0.1),
    ]
    client_threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    result = []
    match_thread = None
    try:
        for thread in client_threads:
            thread.start()
        _wait_for_bots(url, 2)
        match_thread = threading.Thread(target=lambda: result.extend(run_remote_matches(url, "alice", "bob", 1, 7)))
        match_thread.start()
        assert waiting.wait(5)
        with urllib.request.urlopen(url + "/") as response:
            assert b"Remote matches" in response.read()
        with urllib.request.urlopen(url + "/api/spectator/matches") as response:
            match = json.load(response)["matches"][0]
        assert match["status"] == "playing"
        assert match["bot_a"] == "alice" and match["bot_b"] == "bob"
        assert match["live_ships_visible"] is (not hide_ships)
        assert "_fleets" not in match
        if hide_ships:
            assert "fleets" not in match
        else:
            assert set(match["fleets"]) == {"A", "B"}
            assert all(len(cells) == sum(official_rules().fleet) for cells in match["fleets"].values())
        assert "fleets" not in shot_tasks[0]
        assert set(shot_tasks[0]["observation"]) == {"misses", "hits", "sunk", "ships_alive", "version"}
        ongoing = list_ongoing_remote_matches(url)
        assert len(ongoing) == 1
        assert ongoing[0]["game"] == 1 and ongoing[0]["turns"] == 1
        assert ongoing[0]["completed"] == 0
        assert ongoing[0]["a_wins"] == ongoing[0]["b_wins"] == 0
        assert len(match["shots"]) == 1
        assert match["shots"][0]["player"] == "A"
        assert set(match["shots"][0]) == {"player", "row", "col", "outcome", "sunk_cells"}
        release.set()
        match_thread.join(timeout=10)
        assert not match_thread.is_alive()
        with urllib.request.urlopen(url + "/api/spectator/matches") as response:
            match = json.load(response)["matches"][0]
        assert match["status"] == "finished"
        assert match["winner"] == result[0]["winner"]
        assert len(match["shots"]) == result[0]["turns"]
        assert match["reason"] == result[0]["reason"]
        assert list_ongoing_remote_matches(url) == []
        assert set(match["fleets"]) == {"A", "B"}
        assert all(len(cells) == sum(official_rules().fleet) for cells in match["fleets"].values())
        assert match["shots"][0]["outcome"] in {"hit", "miss", "sunk"}
    finally:
        release.set()
        if match_thread:
            match_thread.join(timeout=10)
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in client_threads:
            thread.join(timeout=1)
        server_thread.join(timeout=1)


def test_spectator_reports_placement_forfeit():
    state = RemoteHubState()
    state.register("alice")
    state.register("bob")
    with patch.object(RemoteServerAgent, "place_ships", side_effect=RuntimeError("failed to place")):
        reports = _run_remote_matches(state, {"bot_a": "alice", "bot_b": "bob"})
    match = state.spectator_matches()[0]
    assert match["status"] == "finished"
    assert match["shots"] == []
    assert match["winner"] == "B" == reports[0]["winner"]
    assert "failed to place" in match["reason"]


def test_spectator_history_keeps_active_matches_and_last_50_finished():
    state = RemoteHubState()
    active = state.start_spectating("active", "alice", "bob", official_rules())
    for index in range(51):
        match = state.start_spectating(str(index), "alice", "bob", official_rules())
        state.finish_spectating(match, "A", "all ships sunk")
    matches = state.spectator_matches()
    assert len(matches) == 51
    assert any(match["id"] == active and match["status"] == "playing" for match in matches)
    assert not any(match["match_id"] == "0" for match in matches)


def test_player_b_placement_failure_ends_match_before_shots():
    state = RemoteHubState()
    state.register("alice")
    state.register("bob")

    def place(agent, rules, time_remaining):
        if agent.player is Player.B:
            raise RuntimeError("placement failed on player B")
        return random_legal_fleet(rules, random.Random(7))

    with patch.object(RemoteServerAgent, "place_ships", place):
        report = _run_remote_matches(state, {"bot_a": "alice", "bot_b": "bob"})[0]
    match = state.spectator_matches()[0]
    assert report["winner"] == "A"
    assert report["turns"] == 0
    assert "placement failed on player B" in report["reason"]
    assert match["shots"] == []
    assert len(match["fleets"]["A"]) == sum(official_rules().fleet)
    assert "B" not in match["fleets"]


@pytest.mark.parametrize("stop_early", [False, True])
def test_ongoing_series_reports_wins_from_completed_games(capsys, stop_early):
    class PausedSecondGame(RemoteBotClient):
        placements = 0

        def _handle_task(self, task):
            if task.get("type") == "place_ships":
                self.placements += 1
                if self.placements == 2:
                    waiting.set()
                    assert release.wait(10)
            return super()._handle_task(task)

    server = create_remote_server("127.0.0.1", 0, action_timeout=15.0)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop, waiting, release = threading.Event(), threading.Event(), threading.Event()
    clients = [
        RemoteBotClient(url, "starter-random", "alice", seed=1, poll_timeout=0.1),
        PausedSecondGame(url, "starter-random", "bob", seed=2, poll_timeout=0.1),
    ]
    client_threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    results = []
    match_thread = None
    try:
        for thread in client_threads:
            thread.start()
        _wait_for_bots(url, 2)
        match_thread = threading.Thread(target=lambda: results.append(run_remote_match_request(url, "alice", "bob", 2, 7)))
        match_thread.start()
        assert waiting.wait(10)
        ongoing = list_ongoing_remote_matches(url)
        assert len(ongoing) == 1
        series = ongoing[0]
        assert (series["bot_a"], series["bot_b"]) == ("alice", "bob")
        assert (series["completed"], series["games"], series["game"], series["turns"]) == (1, 2, 2, 0)
        previous = next(match for match in server.hub_state.spectator_matches() if match["status"] == "finished")
        assert series["a_wins"] == int(previous["winner"] == "A")
        assert series["b_wins"] == int(previous["winner"] == "B")
        from app.cli import main
        assert main(["remote-matches", "--server", url]) == 0
        output = capsys.readouterr().out
        assert "alice (A) vs bob (B)" in output
        assert "completed=1/2" in output and "game=2/2 turn=0" in output
        assert f"wins A={series['a_wins']} B={series['b_wins']}" in output
        if stop_early:
            assert main(["remote-stop", "--server", url, "--id", series["series_id"]]) == 0
            match_thread.join(timeout=3)
            assert not match_thread.is_alive()
            assert results[0]["stopped"] is True
            assert len(results[0]["reports"]) == 1
            assert results[0]["reports"][0]["winner"] == previous["winner"]
            release.set()
        else:
            release.set()
            match_thread.join(timeout=10)
            assert not match_thread.is_alive()
            assert results[0]["stopped"] is False
            assert len(results[0]["reports"]) == 2
        assert list_ongoing_remote_matches(url) == []
    finally:
        release.set()
        if match_thread:
            match_thread.join(timeout=10)
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in client_threads:
            thread.join(timeout=1)
        server_thread.join(timeout=1)


def test_series_are_independent_and_forfeits_count_as_wins():
    state = RemoteHubState()
    alice = state.register("alice")["bot_id"]
    bob = state.register("bob")["bot_id"]
    first = state.start_series(alice, bob, 2)
    second = state.start_series(alice, bob, 3)
    match = state.start_spectating("one", "alice", "bob", official_rules(), first)
    state.finish_spectating(match, "B", "illegal placement")
    series = {item["series_id"]: item for item in state.list_series()}
    assert (series[first]["completed"], series[first]["a_wins"], series[first]["b_wins"]) == (1, 0, 1)
    assert (series[second]["completed"], series[second]["a_wins"], series[second]["b_wins"]) == (0, 0, 0)
    state.end_series(first)
    assert [item["series_id"] for item in state.list_series()] == [second]


@pytest.mark.parametrize("operation", ["stop_series", "stop_match", "unregister"])
def test_stop_or_unregister_interrupts_waiting_match(operation, capsys):
    from app.cli import main

    class PausedClient(RemoteBotClient):
        def _handle_task(self, task):
            if task.get("type") == "choose_shot":
                waiting.set()
                assert release.wait(10)
            return super()._handle_task(task)

        def respond_to(self, task):
            try:
                return super().respond_to(task)
            finally:
                if task.get("type") == "choose_shot":
                    responded.set()

    server = create_remote_server("127.0.0.1", 0, action_timeout=30.0)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop, waiting, release, responded = threading.Event(), threading.Event(), threading.Event(), threading.Event()
    clients = [
        RemoteBotClient(url, "starter-random", "alice", seed=1, poll_timeout=0.1),
        PausedClient(url, "starter-random", "bob", seed=2, poll_timeout=0.1),
    ]
    client_threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    results = []
    match_thread = None
    try:
        for thread in client_threads:
            thread.start()
        _wait_for_bots(url, 2)
        match_thread = threading.Thread(target=lambda: results.append(run_remote_match_request(url, "alice", "bob", 2, 7)))
        match_thread.start()
        assert waiting.wait(5)
        series = list_ongoing_remote_matches(url)[0]
        if operation == "unregister":
            assert main(["remote-unregister", "--server", url, "--id", clients[1].bot_id]) == 0
            assert "unregistered bob" in capsys.readouterr().out
            assert [bot["name"] for bot in list_remote_bots(url)] == ["alice"]
        else:
            chosen_id = series["series_id"] if operation == "stop_series" else series["match_id"]
            assert main(["remote-stop", "--server", url, "--id", chosen_id]) == 0
            assert "stop requested" in capsys.readouterr().out
        # The match ends while the bot is still blocked on its action.
        match_thread.join(timeout=3)
        assert not match_thread.is_alive()
        assert results[0]["stopped"] is True and results[0]["reports"] == []
        assert list_ongoing_remote_matches(url) == []
        match = server.hub_state.spectator_matches()[0]
        assert match["status"] == "stopped" and match["winner"] is None
        assert match["reason"] == ("player 'bob' was unregistered" if operation == "unregister" else "match stopped")
        release.set()
        assert responded.wait(3)
        if operation == "unregister":
            client_threads[1].join(timeout=3)
            assert not client_threads[1].is_alive()
        else:
            # A late response from the stopped action is ignored; the bot stays registered.
            with server.hub_state.lock:
                bot = server.hub_state.bots[clients[1].bot_id]
                assert not bot.pending_actions and not bot.responses
            assert client_threads[1].is_alive()
            assert len(list_remote_bots(url)) == 2
    finally:
        release.set()
        if match_thread:
            match_thread.join(timeout=5)
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in client_threads:
            thread.join(timeout=1)
        server_thread.join(timeout=1)


def test_ambiguous_match_id_cannot_stop_wrong_series():
    from runtime.remote import RemoteError

    state = RemoteHubState()
    alice = state.register("alice")["bot_id"]
    bob = state.register("bob")["bot_id"]
    first = state.start_series(alice, bob, 1)
    second = state.start_series(alice, bob, 1)
    state.start_spectating("same-match-id", "alice", "bob", official_rules(), first)
    state.start_spectating("same-match-id", "alice", "bob", official_rules(), second)
    with pytest.raises(RemoteError, match="multiple ongoing series"):
        state.stop_series("same-match-id")
    assert not any(series["stopping"] for series in state.list_series())
    state.stop_series(first)
    assert {s["series_id"]: s["stopping"] for s in state.list_series()} == {first: True, second: False}


def test_stopping_removes_queued_action_and_ignores_late_response():
    from runtime.remote import RemoteSeriesStopped

    state = RemoteHubState()
    alice = state.register("alice")
    bob = state.register("bob")
    series = state.start_series(alice["bot_id"], bob["bot_id"], 1)
    errors = []

    def request():
        try:
            state.request_action(alice["bot_id"], {"action_id": "action", "series_id": series}, 30)
        except RemoteSeriesStopped as exc:
            errors.append(exc)

    thread = threading.Thread(target=request)
    thread.start()
    try:
        with state.changed:
            assert state.changed.wait_for(lambda: bool(state.bots[alice["bot_id"]].tasks), timeout=3)
        state.stop_series(series)
        thread.join(timeout=3)
        assert not thread.is_alive() and len(errors) == 1
        state.respond(alice["bot_id"], alice["token"], {"action_id": "action", "ok": True})
        bot = state.bots[alice["bot_id"]]
        assert not bot.tasks and not bot.responses and not bot.pending_actions
    finally:
        state.stop_series(series)
        thread.join(timeout=3)


def test_unregister_only_stops_series_involving_player():
    state = RemoteHubState()
    alice = state.register("alice")["bot_id"]
    bob = state.register("bob")["bot_id"]
    charlie = state.register("charlie")["bot_id"]
    affected = state.start_series(alice, bob, 1)
    unaffected = state.start_series(alice, charlie, 1)
    result = state.unregister(bob)
    assert result["stopped_series"] == [affected]
    assert {s["series_id"]: s["stopping"] for s in state.list_series()} == {affected: True, unaffected: False}


def test_heartbeat_disconnect_stops_match_and_saved_identity_reconnects(tmp_path):
    from runtime.remote import RemoteError, _post_json

    waiting, release, allow_heartbeat = threading.Event(), threading.Event(), threading.Event()
    allow_heartbeat.set()

    class DisconnectableClient(RemoteBotClient):
        def _handle_task(self, task):
            if task.get("type") == "choose_shot":
                waiting.set()
                assert release.wait(10)
            return super()._handle_task(task)

        def _heartbeat_loop(self, stop):
            while not stop.is_set():
                if allow_heartbeat.is_set():
                    try:
                        _post_json(self.server_url, "/api/heartbeat", self._credentials(), timeout=1)
                    except RemoteError:
                        stop.set()
                        break
                    except OSError:
                        pass
                stop.wait(0.02)

    server = create_remote_server("127.0.0.1", 0, action_timeout=30, disconnect_timeout=0.1)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop = threading.Event()
    session_file = tmp_path / "bob.json"
    clients = [
        RemoteBotClient(url, "starter-random", "alice", seed=1, poll_timeout=0.1, heartbeat_interval=0.02),
        DisconnectableClient(url, "starter-random", "bob", seed=2, poll_timeout=0.1,
                             session_file=session_file, heartbeat_interval=0.02),
    ]
    client_threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    match_thread = None
    reconnected_thread = None
    results = []
    try:
        for thread in client_threads:
            thread.start()
        _wait_for_bots(url, 2)
        for _ in range(100):
            if session_file.exists():
                break
            threading.Event().wait(0.02)
        original_id = clients[1].bot_id
        assert session_file.stat().st_mode & 0o777 == 0o600
        match_thread = threading.Thread(target=lambda: results.append(run_remote_match_request(url, "alice", "bob", 1, 7)))
        match_thread.start()
        assert waiting.wait(5)
        # A slow bot remains online while its independent heartbeat continues.
        threading.Event().wait(0.15)
        assert match_thread.is_alive()
        assert next(bot for bot in list_remote_bots(url) if bot["name"] == "bob")["status"] == "online"
        allow_heartbeat.clear()
        match_thread.join(timeout=3)
        assert not match_thread.is_alive()
        assert results[0]["stopped"] and results[0]["reports"] == []
        assert "bob" in results[0]["stop_reason"] and "disconnected" in results[0]["stop_reason"]
        assert next(bot for bot in list_remote_bots(url) if bot["name"] == "bob")["status"] == "offline"
        match = server.hub_state.spectator_matches()[0]
        assert match["status"] == "stopped" and match["winner"] is None
        with pytest.raises(RemoteError, match="offline"):
            run_remote_matches(url, "alice", "bob", 1, 8)

        replacement = RemoteBotClient(url, "starter-random", "bob", seed=2, poll_timeout=0.1,
                                      session_file=session_file, heartbeat_interval=0.05)
        registration = replacement.register()
        assert registration["resumed"] and registration["bot_id"] == original_id
        assert len(list_remote_bots(url)) == 2
        assert next(bot for bot in list_remote_bots(url) if bot["name"] == "bob")["status"] == "online"
        reconnected_thread = threading.Thread(target=replacement.run_forever, args=(stop,), daemon=True)
        reconnected_thread.start()
        allow_heartbeat.set()
        release.set()
        client_threads[1].join(timeout=3)
        assert not client_threads[1].is_alive()
        reports = run_remote_matches(url, "alice", "bob", 1, 8)
        assert len(reports) == 1 and reports[0]["turns"] > 0
    finally:
        release.set()
        allow_heartbeat.set()
        if match_thread:
            match_thread.join(timeout=5)
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in client_threads:
            thread.join(timeout=1)
        if reconnected_thread:
            reconnected_thread.join(timeout=1)
        server_thread.join(timeout=1)


def test_saved_session_validates_identity_and_does_not_replace_bad_tokens(tmp_path):
    from runtime.remote import RemoteError

    server = create_remote_server("127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    session_file = tmp_path / "session.json"
    try:
        first = RemoteBotClient(url, "starter-random", "alice", session_file=session_file)
        registration = first.register()
        second = RemoteBotClient(url, "starter-random", "alice", session_file=session_file)
        resumed = second.register()
        assert resumed["resumed"] and resumed["bot_id"] == registration["bot_id"]
        with pytest.raises(RemoteError, match="session replaced"):
            first.poll_once()
        with pytest.raises(RemoteError, match="different server or player"):
            RemoteBotClient(url, "starter-random", "other", session_file=session_file).register()
        data = json.loads(session_file.read_text())
        data["token"] = "invalid"
        session_file.write_text(json.dumps(data))
        with pytest.raises(RemoteError, match="invalid token"):
            RemoteBotClient(url, "starter-random", "alice", session_file=session_file).register()
        assert len(list_remote_bots(url)) == 1
        data["token"] = registration["token"]
        session_file.write_text(json.dumps(data))
        server.hub_state.unregister(registration["bot_id"])
        fresh = RemoteBotClient(url, "starter-random", "alice", session_file=session_file).register()
        assert not fresh["resumed"] and fresh["bot_id"] != registration["bot_id"]
        assert json.loads(session_file.read_text())["bot_id"] == fresh["bot_id"]
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1)


def test_resuming_replaces_connection_and_stops_old_series():
    from runtime.remote import RemoteError

    state = RemoteHubState()
    alice = state.register("alice", heartbeat=True)
    bob = state.register("bob", heartbeat=True)
    series_id = state.start_series(alice["bot_id"], bob["bot_id"], 1)
    resumed = state.resume(bob["bot_id"], bob["token"])
    assert resumed["connection_id"] != bob["connection_id"]
    series = state.list_series()[0]
    assert series["series_id"] == series_id and series["stopping"]
    assert "reconnected" in series["stop_reason"]
    with pytest.raises(RemoteError, match="session replaced"):
        state.heartbeat(bob["bot_id"], bob["token"], bob["connection_id"])
    state.heartbeat(bob["bot_id"], bob["token"], resumed["connection_id"])


def test_legacy_clients_are_not_expired_without_heartbeats():
    state = RemoteHubState(disconnect_timeout=1)
    legacy = state.register("legacy")
    modern = state.register("modern", heartbeat=True)
    with state.lock:
        state.bots[legacy["bot_id"]].last_seen -= 2
        state.bots[modern["bot_id"]].last_seen -= 2
    state.expire_offline()
    statuses = {bot["name"]: bot["status"] for bot in state.list_bots()}
    assert statuses == {"legacy": "legacy", "modern": "offline"}


def test_late_heartbeat_stops_series_before_marking_player_online():
    state = RemoteHubState(disconnect_timeout=1)
    alice = state.register("alice", heartbeat=True)
    bob = state.register("bob", heartbeat=True)
    state.start_series(alice["bot_id"], bob["bot_id"], 1)
    with state.lock:
        state.bots[bob["bot_id"]].last_seen -= 2
    state.heartbeat(bob["bot_id"], bob["token"], bob["connection_id"])
    series = state.list_series()[0]
    assert series["stopping"] and "disconnected" in series["stop_reason"]
    assert next(bot for bot in state.list_bots() if bot["name"] == "bob")["status"] == "online"


@pytest.mark.parametrize(
    ("slow_action", "slow_player", "action_timeout"),
    [
        ("place_ships", "alice", 0.25),
        ("place_ships", "bob", 0.25),
        ("choose_shot", "alice", 0.25),
        ("choose_shot", "bob", 0.25),
        ("place_ships", "alice", 130.0),
        # A larger configured server timeout must still enforce the half-second cap.
        ("choose_shot", "bob", 130.0),
    ],
)
def test_slow_remote_action_forfeits_while_player_stays_online(slow_action, slow_player, action_timeout):
    waiting, release, responded = threading.Event(), threading.Event(), threading.Event()
    received_limits = []

    class SlowClient(RemoteBotClient):
        def _handle_task(self, task):
            if task.get("type") == slow_action:
                received_limits.append(task["time_remaining"])
                waiting.set()
                assert release.wait(10)
            return super()._handle_task(task)

        def respond_to(self, task):
            try:
                return super().respond_to(task)
            finally:
                if task.get("type") == slow_action:
                    responded.set()

    server = create_remote_server("127.0.0.1", 0, action_timeout=action_timeout, disconnect_timeout=15)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop = threading.Event()
    clients = [
        (SlowClient if name == slow_player else RemoteBotClient)(
            url, "starter-random", name, seed=index, poll_timeout=0.1, heartbeat_interval=0.05
        )
        for index, name in enumerate(("alice", "bob"), 1)
    ]
    client_threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    match_thread = None
    results = []
    try:
        for thread in client_threads:
            thread.start()
        _wait_for_bots(url, 2)
        match_thread = threading.Thread(target=lambda: results.append(run_remote_match_request(url, "alice", "bob", 1, 7)))
        match_thread.start()
        assert waiting.wait(5)
        match_thread.join(timeout=7)
        assert not match_thread.is_alive()
        assert not results[0]["stopped"]
        report = results[0]["reports"][0]
        assert report["winner_bot"] == ("bob" if slow_player == "alice" else "alice")
        assert f"timeout during {'placement' if slow_action == 'place_ships' else 'shot'}" in report["reason"]
        assert received_limits == [min(action_timeout, 5.0 if slow_action == "place_ships" else 0.5)]
        assert next(bot for bot in list_remote_bots(url) if bot["name"] == slow_player)["status"] == "unresponsive"
        snapshot = server.hub_state.spectator_matches()[0]
        assert snapshot["status"] == "finished" and snapshot["winner"] == report["winner"]
        release.set()
        assert responded.wait(3)
        for _ in range(100):
            if next(bot for bot in list_remote_bots(url) if bot["name"] == slow_player)["status"] == "online":
                break
            threading.Event().wait(0.02)
        assert next(bot for bot in list_remote_bots(url) if bot["name"] == slow_player)["status"] == "online"
        with server.hub_state.lock:
            bot = server.hub_state.bots[next(client.bot_id for client in clients if client.name == slow_player)]
            assert not bot.pending_actions and not bot.responses
    finally:
        release.set()
        if match_thread:
            match_thread.join(timeout=8)
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in client_threads:
            thread.join(timeout=1)
        server_thread.join(timeout=1)


@pytest.mark.parametrize("late", [False, True])
def test_action_deadline_uses_response_arrival_time(late):
    from runtime.clocks import ActionTimeout

    state = RemoteHubState()
    alice = state.register("alice")
    results, errors = [], []

    def request():
        try:
            results.append(state.request_action(alice["bot_id"], {"action_id": "test"}, 0.2))
        except ActionTimeout as exc:
            errors.append(exc)

    thread = threading.Thread(target=request)
    thread.start()
    try:
        with state.changed:
            assert state.changed.wait_for(lambda: bool(state.bots[alice["bot_id"]].tasks), timeout=3)
            if late:
                threading.Event().wait(0.3)
            state.respond(alice["bot_id"], alice["token"], {"action_id": "test", "ok": True})
            if not late:
                threading.Event().wait(0.3)
        thread.join(timeout=2)
        assert not thread.is_alive()
        if late:
            assert len(errors) == 1 and not results
        else:
            assert results == [{"action_id": "test", "ok": True}] and not errors
    finally:
        thread.join(timeout=2)


def test_timed_out_player_cannot_lose_a_second_game_before_going_offline():
    from runtime.remote import RemoteError, _post_json

    waiting, release, allow_heartbeat = threading.Event(), threading.Event(), threading.Event()
    allow_heartbeat.set()

    class DisconnectingClient(RemoteBotClient):
        def _handle_task(self, task):
            if task.get("type") == "place_ships":
                waiting.set()
                assert release.wait(10)
            return super()._handle_task(task)

        def _heartbeat_loop(self, stop):
            while not stop.is_set():
                if allow_heartbeat.is_set():
                    try:
                        _post_json(self.server_url, "/api/heartbeat", self._credentials(), timeout=1)
                    except (RemoteError, OSError):
                        pass
                stop.wait(0.05)

    server = create_remote_server("127.0.0.1", 0, action_timeout=0.25, disconnect_timeout=1.5)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop = threading.Event()
    clients = [
        RemoteBotClient(url, "starter-random", "alice", seed=1, poll_timeout=0.1, heartbeat_interval=0.05),
        DisconnectingClient(url, "starter-random", "bob", seed=2, poll_timeout=0.1, heartbeat_interval=0.05),
    ]
    client_threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    match_thread = None
    results = []
    try:
        for thread in client_threads:
            thread.start()
        _wait_for_bots(url, 2)
        match_thread = threading.Thread(target=lambda: results.append(run_remote_match_request(url, "alice", "bob", 3, 7)))
        match_thread.start()
        assert waiting.wait(5)
        allow_heartbeat.clear()
        match_thread.join(timeout=3)
        assert not match_thread.is_alive()
        assert results[0]["stopped"] and len(results[0]["reports"]) == 1
        assert results[0]["reports"][0]["winner_bot"] == "alice"
        assert "unresponsive" in results[0]["stop_reason"]
        assert len(server.hub_state.spectator_matches()) == 1
        assert next(bot for bot in list_remote_bots(url) if bot["name"] == "bob")["status"] == "unresponsive"
        with pytest.raises(RemoteError, match="unresponsive"):
            run_remote_matches(url, "alice", "bob", 1, 8)
        for _ in range(150):
            if next(bot for bot in list_remote_bots(url) if bot["name"] == "bob")["status"] == "offline":
                break
            threading.Event().wait(0.02)
        assert next(bot for bot in list_remote_bots(url) if bot["name"] == "bob")["status"] == "offline"
        with pytest.raises(RemoteError, match="offline"):
            run_remote_matches(url, "alice", "bob", 1, 8)
        allow_heartbeat.set()
        release.set()
        for _ in range(150):
            if next(bot for bot in list_remote_bots(url) if bot["name"] == "bob")["status"] == "online":
                break
            threading.Event().wait(0.02)
        assert next(bot for bot in list_remote_bots(url) if bot["name"] == "bob")["status"] == "online"
    finally:
        release.set()
        allow_heartbeat.set()
        if match_thread:
            match_thread.join(timeout=5)
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in client_threads:
            thread.join(timeout=1)
        server_thread.join(timeout=1)


def test_action_timeout_stops_other_concurrent_series_without_a_second_forfeit():
    from runtime.clocks import ActionTimeout
    from runtime.remote import RemoteSeriesStopped

    state = RemoteHubState()
    alice = state.register("alice")["bot_id"]
    bob = state.register("bob")["bot_id"]
    carol = state.register("carol")["bot_id"]
    first = state.start_series(alice, bob, 1)
    other = state.start_series(carol, bob, 1)
    first_match = state.start_spectating("first", "alice", "bob", official_rules(), first)
    other_match = state.start_spectating("other", "carol", "bob", official_rules(), other)
    errors = []

    def request(series_id, timeout):
        try:
            state.request_action(bob, {"action_id": series_id, "series_id": series_id}, timeout)
        except (ActionTimeout, RemoteSeriesStopped) as exc:
            errors.append((series_id, exc))

    threads = [threading.Thread(target=request, args=(first, 0.3)), threading.Thread(target=request, args=(other, 3))]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=4)
        assert not any(thread.is_alive() for thread in threads)
        failures = dict(errors)
        assert isinstance(failures[first], ActionTimeout)
        assert isinstance(failures[other], RemoteSeriesStopped)
        assert state.finish_spectating(first_match, "A", "timeout") is None
        assert "unresponsive" in state.finish_spectating(other_match, "A", "timeout")
        snapshots = {match["match_id"]: match for match in state.spectator_matches()}
        assert snapshots["first"]["status"] == "finished" and snapshots["first"]["winner"] == "A"
        assert snapshots["other"]["status"] == "stopped" and snapshots["other"]["winner"] is None
    finally:
        with state.changed:
            for series_id in (first, other):
                series = state.ongoing_series[series_id]
                series["stopping"] = True
                series["stop_reason"] = "test cleanup"
            state.changed.notify_all()
        for thread in threads:
            thread.join(timeout=1)
        for series_id in (first, other):
            state.end_series(series_id)


def test_heartbeat_expiry_after_action_timeout_preserves_first_forfeit():
    from runtime.remote import RemoteSeriesStopped

    state = RemoteHubState(disconnect_timeout=1)
    alice = state.register("alice", heartbeat=True)["bot_id"]
    bob = state.register("bob", heartbeat=True)["bot_id"]
    series = state.start_series(alice, bob, 2)
    match = state.start_spectating("first", "alice", "bob", official_rules(), series)
    with state.changed:
        state._mark_action_timeout(state.bots[bob], series)
        state.bots[bob].last_seen -= 2
    state.expire_offline()
    assert state.finish_spectating(match, "A", "timeout") is None
    assert state.spectator_matches()[0]["winner"] == "A"
    with pytest.raises(RemoteSeriesStopped, match="unresponsive"):
        state.start_spectating("second", "alice", "bob", official_rules(), series, 2)


def test_series_stops_after_forfeit_even_if_player_returns_immediately():
    from runtime.remote import RemoteSeriesStopped

    state = RemoteHubState()
    alice = state.register("alice", heartbeat=True)
    bob = state.register("bob", heartbeat=True)
    series = state.start_series(alice["bot_id"], bob["bot_id"], 2)
    match = state.start_spectating("first", "alice", "bob", official_rules(), series)
    with state.changed:
        state._mark_action_timeout(state.bots[bob["bot_id"]], series)
    assert state.finish_spectating(match, "A", "timeout") is None
    assert state.poll(bob["bot_id"], bob["token"], 0, bob["connection_id"]) is None
    assert next(bot for bot in state.list_bots() if bot["name"] == "bob")["status"] == "online"
    with pytest.raises(RemoteSeriesStopped, match="unresponsive"):
        state.start_spectating("second", "alice", "bob", official_rules(), series, 2)
    assert state.start_series(alice["bot_id"], bob["bot_id"], 1)


def test_poll_does_not_deliver_actions_from_stopped_series():
    state = RemoteHubState()
    alice = state.register("alice")
    bob = state.register("bob")
    series = state.start_series(alice["bot_id"], bob["bot_id"], 1)
    with state.changed:
        state.bots[bob["bot_id"]].tasks.append({"action_id": "stale", "series_id": series})
    state.stop_series(series)
    assert state.poll(bob["bot_id"], bob["token"], 0) is None


@pytest.mark.parametrize("series_seed, expected_games", [(1, 3), (0, 4), (7, 5)])
def test_tournament_series_randomizes_first_player_and_persists_bot_memory(tmp_path, monkeypatch, series_seed, expected_games):
    from agent import Agent
    from runtime.remote import run_remote_tournament_series
    from sdk.memory import load_memory_session

    seen = []

    class MemoryBot(Agent):
        def start_match(self, context):
            self.memory = context.memory
            seen.append((context.bot_name, context.opponent_name, self.memory.get("finished", 0)))

        def place_ships(self, rules, time_remaining):
            self.memory["placed"] = self.memory.get("placed", 0) + 1
            return []  # The first player forfeits, making the result seed-dependent.

        def choose_shot(self, observation, time_remaining):
            return (0, 0)

        def end_match(self, result):
            self.memory["finished"] = self.memory.get("finished", 0) + 1

    monkeypatch.setattr("runtime.remote.build_bot", lambda *args: MemoryBot())
    server = create_remote_server("127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop = threading.Event()
    clients = [RemoteBotClient(url, "memory", name, poll_timeout=0.1) for name in ("alice", "bob")]
    threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    try:
        for thread in threads:
            thread.start()
        _wait_for_bots(url, 2)
        registered = {bot["name"]: bot["bot_id"] for bot in list_remote_bots(url)}
        a, b = registered["alice"], registered["bob"]
        result = run_remote_tournament_series(url, a, b, series_seed, str(tmp_path))
        assert not result["stopped"]
        assert len(result["reports"]) == expected_games
        if expected_games > 3:
            assert {game["bot_a"] for game in result["reports"]} == {a, b}
        assert max(sum(game["winner_bot"] == player for game in result["reports"]) for player in (a, b)) == 3
        assert {entry[:2] for entry in seen} == {("alice", "bob"), ("bob", "alice")}
        for own, opponent in ((a, b), (b, a)):
            memory = load_memory_session(tmp_path, own, opponent).memory
            assert memory["finished"] == expected_games
            assert memory["_stats"]["games"] == expected_games
        for name in ("alice", "bob"):
            assert [count for bot, _, count in seen if bot == name] == list(range(expected_games))
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in threads:
            thread.join(timeout=1)
        server_thread.join(timeout=1)


def test_tournament_series_reserves_players_without_changing_regular_series():
    from runtime.remote import RemoteError

    state = RemoteHubState()
    alice = state.register("alice")["bot_id"]
    bob = state.register("bob")["bot_id"]
    carol = state.register("carol")["bot_id"]
    first = state.start_series(alice, bob, 1)
    second = state.start_series(alice, carol, 1)
    with pytest.raises(RemoteError, match="already in a series"):
        state.start_series(alice, carol, 5, exclusive=True)
    state.end_series(first)
    state.end_series(second)
    reserved = state.start_series(alice, bob, 5, exclusive=True)
    with pytest.raises(RemoteError, match="already in a series"):
        state.start_series(alice, carol, 1)
    state.end_series(reserved)
    assert state.start_series(alice, carol, 1)


def test_tournament_client_forwards_opponent_shots_and_end_memory(monkeypatch):
    from agent import Agent

    class MemoryBot(Agent):
        def start_match(self, context):
            self.memory = context.memory

        def place_ships(self, rules, time_remaining):
            return []

        def choose_shot(self, observation, time_remaining):
            return (0, 0)

        def observe_opponent_shot(self, result, time_remaining):
            self.memory["shot"] = list(result.shot)
            self.memory["outcome"] = result.outcome.value

        def end_match(self, result):
            self.memory["won"] = result.won

    monkeypatch.setattr("runtime.remote.build_bot", lambda *args: MemoryBot())
    client = RemoteBotClient("http://localhost", "memory", "alice")
    client._handle_task({"type": "start_match", "match_id": "game", "context": {
        "match_id": "game", "player": "A", "bot_name": "alice", "opponent_name": "bob", "memory": {"old": 1},
    }})
    response = client._handle_task({"type": "observe_opponent_shot", "match_id": "game", "time_remaining": 1,
                                    "result": {"shot": [2, 3], "outcome": "miss", "sunk_ship": None}})
    assert response["memory"]["shot"] == [2, 3]
    response = client._handle_task({"type": "end_match", "match_id": "game",
                                    "memory": {**response["memory"], "_stats": {"games": 1}},
                                    "result": {"won": True, "winner": "A", "reason": "test", "turns": 1}})
    assert response["memory"] == {"old": 1, "shot": [2, 3], "outcome": "miss", "_stats": {"games": 1}, "won": True}


def test_tournament_spectator_tracks_scores_advancement_and_retains_replays():
    state = RemoteHubState()
    a = state.register("alice")["bot_id"]
    b = state.register("bob")["bot_id"]
    tournament_id = state.create_tournament({a: "alice", b: "bob"}, 17)
    state.update_tournament(tournament_id, {"type": "wave", "wave": 1})
    state.update_tournament(tournament_id, {"type": "pair", "pair_id": "pair-1", "wave": 1,
                                             "bracket": "winners", "bot_a": a, "bot_b": b})
    series_id = state.start_series(a, b, 5, exclusive=True, tournament_id=tournament_id, pair_id="pair-1", wins_needed=3)
    for game in range(1, 6):
        # The first player's identity changes. Winner A wins exactly three games.
        flipped = game % 2 == 0
        match_id = state.start_spectating(f"game-{game}", "alice", "bob", official_rules(), series_id, game, flipped)
        if game == 1:
            live = state.spectator_tournaments()[0]["pairings"][0]
            assert live["status"] == "playing"
            assert live["rounds"] == [{"id": match_id, "game": 1, "status": "playing", "winner": None}]
        state.finish_spectating(match_id, "A", "all ships sunk")
    pair = state.spectator_tournaments()[0]["pairings"][0]
    assert (pair["a_wins"], pair["b_wins"], pair["completed"]) == (3, 2, 5)
    assert [round_["winner"] for round_ in pair["rounds"]] == [a, b, a, b, a]
    state.end_series(series_id)
    tournament = state.spectator_tournaments()[0]
    pair = tournament["pairings"][0]
    assert (pair["status"], pair["winner"], pair["loser"]) == ("finished", a, b)
    assert pair["advancement_pending"] and tournament["entrants"][b]["losses"] == 0
    for index in range(55):
        game = state.start_spectating(f"other-{index}", "x", "y", official_rules())
        state.finish_spectating(game, "A", "all ships sunk")
    retained = state.spectator_matches(pair_id="pair-1")
    assert len(retained) == 5
    assert {match["game"] for match in retained} == set(range(1, 6))
    assert len(state.spectator_matches(recent_only=True)) == 50


def test_tournament_dashboard_api_shows_live_pair_and_finished_replays(tmp_path, monkeypatch):
    from agent import Agent
    from runtime.tournament import run_tournament

    monkeypatch.setattr("runtime.tournament.BREAK_SECONDS", 0)

    paused, release = threading.Event(), threading.Event()
    starts = {"alice": 0}

    class FastBot(Agent):
        def __init__(self, name):
            self.name = name

        def start_match(self, context):
            if self.name == "alice":
                starts["alice"] += 1
                if starts["alice"] == 3:
                    paused.set()
                    assert release.wait(4)

        def place_ships(self, rules, time_remaining):
            return []

        def choose_shot(self, observation, time_remaining):
            return (0, 0)

    monkeypatch.setattr("runtime.remote.build_bot", lambda spec, seed: FastBot(spec))
    server = create_remote_server("127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop = threading.Event()
    clients = [RemoteBotClient(url, name, name, poll_timeout=0.1) for name in ("alice", "bob", "carol", "dave")]
    client_threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    results, errors = [], []
    def run():
        try:
            results.append(run_tournament(url, 9, 0, str(tmp_path)))
        except Exception as exc:
            errors.append(exc)
    thread = None
    try:
        for client_thread in client_threads:
            client_thread.start()
        _wait_for_bots(url, 4)
        thread = threading.Thread(target=run)
        thread.start()
        assert paused.wait(10)
        with urllib.request.urlopen(url + "/api/spectator/tournaments") as response:
            snapshot = json.load(response)
        assert isinstance(snapshot["server_time"], float)
        tournament = snapshot["tournaments"][0]
        pairs = tournament["pairings"]
        alice_id = clients[0].bot_id
        pair = next(pair for pair in pairs if alice_id in (pair["bot_a"], pair["bot_b"]))
        assert tournament["status"] == "running" and tournament["wave"] == 1
        assert pair["status"] == "playing" and pair["completed"] == 2
        assert pair["a_wins"] + pair["b_wins"] == 2
        assert len(pair["rounds"]) == 3 and pair["rounds"][-1]["status"] == "playing"
        other = next(item for item in pairs if item["id"] != pair["id"])
        for _ in range(100):
            with urllib.request.urlopen(url + "/api/spectator/tournaments") as response:
                tournament = json.load(response)["tournaments"][0]
            other = next(item for item in tournament["pairings"] if item["id"] == other["id"])
            if other["status"] == "finished":
                break
            threading.Event().wait(0.02)
        assert other["status"] == "finished" and other["winner"] and 3 <= other["completed"] <= 5
        assert tournament["wave"] == 1 and len(tournament["pairings"]) == 2
        with urllib.request.urlopen(url + "/api/spectator/matches?pair_id=" + pair["id"]) as response:
            matches = json.load(response)["matches"]
        assert len(matches) == 3 and matches[0]["status"] == "playing"
        assert all(match["pair_id"] == pair["id"] for match in matches)
        release.set()
        thread.join(timeout=30)
        assert not thread.is_alive() and not errors and results
        with urllib.request.urlopen(url + "/api/spectator/tournaments") as response:
            finished = json.load(response)["tournaments"][0]
        assert finished["status"] == "finished" and finished["champion_id"] == results[0]["champion_id"]
        assert {pair["bracket"] for pair in finished["pairings"]} >= {"winners", "losers", "final"}
        assert max(pair["wave"] for pair in finished["pairings"] if pair["bracket"] == "winners") < min(
            pair["wave"] for pair in finished["pairings"] if pair["bracket"] == "losers"
        )
        assert all(pair["status"] == "finished" and 3 <= len(pair["rounds"]) <= 5 for pair in finished["pairings"])
        with urllib.request.urlopen(url + "/api/spectator/matches?pair_id=" + pair["id"]) as response:
            assert 3 <= len(json.load(response)["matches"]) <= 5
    finally:
        release.set()
        if thread:
            thread.join(timeout=30)
        stop.set()
        server.shutdown()
        server.server_close()
        for client_thread in client_threads:
            client_thread.join(timeout=1)
        server_thread.join(timeout=1)


@pytest.mark.parametrize("returns", [True, False])
def test_tournament_waits_after_timeout_and_forfeits_only_if_player_does_not_return(tmp_path, monkeypatch, returns):
    from runtime.remote import run_remote_tournament_series

    monkeypatch.setattr("runtime.remote.TOURNAMENT_RECONNECT_SECONDS", 0.4)
    entered, release, waiting = threading.Event(), threading.Event(), threading.Event()

    class DelayedClient(RemoteBotClient):
        delayed = False
        def _handle_task(self, task):
            if task.get("type") == "place_ships" and not self.delayed:
                self.delayed = True
                entered.set()
                assert release.wait(5)
            return super()._handle_task(task)

    server = create_remote_server("127.0.0.1", 0, action_timeout=0.2)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop = threading.Event()
    clients = [DelayedClient(url, "hunt-target", "alice", poll_timeout=0.05),
               RemoteBotClient(url, "hunt-target", "bob", poll_timeout=0.05)]
    threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    result, errors = [], []
    match_thread = None
    try:
        for thread in threads:
            thread.start()
        _wait_for_bots(url, 2)
        ids = {bot["name"]: bot["bot_id"] for bot in list_remote_bots(url)}
        a, b = ids["alice"], ids["bob"]
        tournament_id = server.hub_state.create_tournament({a: "alice", b: "bob"}, 1)
        server.hub_state.update_tournament(tournament_id, {"type": "pair", "pair_id": "pair", "wave": 1,
                                                            "bracket": "winners", "bot_a": a, "bot_b": b})
        def play():
            try:
                result.append(run_remote_tournament_series(url, a, b, 5, str(tmp_path), tournament_id, "pair"))
            except Exception as exc:
                errors.append(exc)
        match_thread = threading.Thread(target=play)
        match_thread.start()
        assert entered.wait(5)
        for _ in range(200):
            if server.hub_state.spectator_tournaments()[0]["pairings"][0]["status"] == "reconnecting":
                waiting.set()
                break
            threading.Event().wait(0.01)
        assert waiting.is_set()
        if returns:
            release.set()
        match_thread.join(timeout=25)
        assert not match_thread.is_alive() and not errors
        reports = result[0]["reports"]
        assert 3 <= len(reports) <= 5 and not result[0]["stopped"]
        assert reports[0]["winner_bot"] == b
        forfeits = [report for report in reports if "did not reconnect" in report["reason"]]
        if returns:
            assert not forfeits
            assert all(report["turns"] > 0 for report in reports[1:])
        else:
            assert len(forfeits) == 2
            assert all(report["winner_bot"] == b and report["turns"] == 0 for report in forfeits)
        assert len(server.hub_state.spectator_matches(pair_id="pair")) == len(reports)
    finally:
        release.set()
        if match_thread:
            match_thread.join(timeout=5)
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in threads:
            thread.join(timeout=1)
        server_thread.join(timeout=1)


def test_tournament_player_can_win_pair_after_half_second_timeout(tmp_path, monkeypatch):
    from runtime.remote import run_remote_tournament_series

    monkeypatch.setattr("runtime.remote.TOURNAMENT_RECONNECT_SECONDS", 2.0)
    entered, release = threading.Event(), threading.Event()

    class DelayedClient(RemoteBotClient):
        delayed = False

        def _handle_task(self, task):
            if task.get("type") == "place_ships" and not self.delayed:
                self.delayed = True
                entered.set()
                assert release.wait(5)
            return super()._handle_task(task)

    class LaterForfeitsClient(RemoteBotClient):
        game = 0

        def _handle_task(self, task):
            if task.get("type") == "start_match":
                self.game += 1
            if task.get("type") == "place_ships" and self.game > 1:
                return {"ok": True, "action_id": task["action_id"], "placements": []}
            return super()._handle_task(task)

    server = create_remote_server("127.0.0.1", 0, action_timeout=0.5)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop = threading.Event()
    clients = [DelayedClient(url, "hunt-target", "alice", poll_timeout=0.05),
               LaterForfeitsClient(url, "hunt-target", "bob", poll_timeout=0.05)]
    threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    result, errors = [], []
    match_thread = None
    try:
        for thread in threads:
            thread.start()
        _wait_for_bots(url, 2)
        ids = {bot["name"]: bot["bot_id"] for bot in list_remote_bots(url)}
        a, b = ids["alice"], ids["bob"]
        tournament_id = server.hub_state.create_tournament({a: "alice", b: "bob"}, 1)
        server.hub_state.update_tournament(tournament_id, {"type": "pair", "pair_id": "pair", "wave": 1,
                                                            "bracket": "winners", "bot_a": a, "bot_b": b})

        def play():
            try:
                result.append(run_remote_tournament_series(url, a, b, 5, str(tmp_path), tournament_id, "pair"))
            except Exception as exc:
                errors.append(exc)

        match_thread = threading.Thread(target=play)
        match_thread.start()
        assert entered.wait(5)
        for _ in range(300):
            pair = server.hub_state.spectator_tournaments()[0]["pairings"][0]
            if pair["status"] == "reconnecting":
                break
            threading.Event().wait(0.01)
        assert pair["status"] == "reconnecting"
        assert pair["a_wins"] == 0 and pair["b_wins"] == 1
        release.set()
        match_thread.join(timeout=10)
        assert not match_thread.is_alive() and not errors
        assert not result[0]["stopped"]
        assert [report["winner_bot"] for report in result[0]["reports"]] == [b, a, a, a]
        pair = server.hub_state.spectator_tournaments()[0]["pairings"][0]
        assert pair["status"] == "finished" and pair["winner"] == a
        assert pair["a_wins"] == 3 and pair["b_wins"] == 1
        assert len(server.hub_state.spectator_matches(pair_id="pair")) == 4
    finally:
        release.set()
        if match_thread:
            match_thread.join(timeout=5)
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in threads:
            thread.join(timeout=1)
        server_thread.join(timeout=1)


def test_tournament_counts_distinct_disconnects_by_bracket():
    state = RemoteHubState(disconnect_timeout=1)
    alice = state.register("alice", heartbeat=True)
    bob = state.register("bob", heartbeat=True)
    tournament_id = state.create_tournament({alice["bot_id"]: "alice", bob["bot_id"]: "bob"}, 1)
    for _ in range(3):
        with state.lock:
            state.bots[alice["bot_id"]].last_seen = 0
        state.expire_offline()
        state.resume(alice["bot_id"], alice["token"])
    entrant = state.spectator_tournaments()[0]["entrants"][alice["bot_id"]]
    assert entrant["disconnects"] == {"winners": 3, "losers": 0}
    with state.lock:
        state.tournaments[tournament_id]["entrants"][alice["bot_id"]]["losses"] = 1
        state.bots[alice["bot_id"]].last_seen = 0
    state.expire_offline()
    assert state.spectator_tournaments()[0]["entrants"][alice["bot_id"]]["disconnects"] == {"winners": 3, "losers": 1}


def test_reconnect_during_tournament_round_preserves_forfeit_and_new_session_readiness():
    from runtime.clocks import ActionTimeout

    state = RemoteHubState(disconnect_timeout=1)
    alice = state.register("alice", heartbeat=True)
    bob = state.register("bob", heartbeat=True)
    a, b = alice["bot_id"], bob["bot_id"]
    tournament_id = state.create_tournament({a: "alice", b: "bob"}, 1)
    state.update_tournament(tournament_id, {"type": "pair", "pair_id": "p", "wave": 1,
                                             "bracket": "winners", "bot_a": a, "bot_b": b})
    series = state.start_series(a, b, 5, exclusive=True, tournament_id=tournament_id, pair_id="p", wins_needed=3)
    state.start_spectating("game", "alice", "bob", official_rules(), series, 1)
    errors = []
    def request():
        try:
            state.request_action(a, {"action_id": "action", "series_id": series}, 0.2)
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=request)
    thread.start()
    try:
        for _ in range(100):
            with state.lock:
                if state.bots[a].pending_actions:
                    state.bots[a].last_seen = 0
                    break
            threading.Event().wait(0.005)
        state.expire_offline()
        assert not state.list_series()[0]["stopping"]
        state.resume(a, alice["token"])
        thread.join(timeout=2)
        assert len(errors) == 1 and isinstance(errors[0], ActionTimeout)
        assert state.wait_for_tournament_player(series, a, 0) is True
        assert state.spectator_tournaments()[0]["entrants"][a]["disconnects"]["winners"] == 1
    finally:
        thread.join(timeout=2)
        state.end_series(series)


def test_reconnect_before_heartbeat_expiry_still_counts_during_tournament():
    state = RemoteHubState()
    alice = state.register("alice", heartbeat=True)
    bob = state.register("bob", heartbeat=True)
    a, b = alice["bot_id"], bob["bot_id"]
    tournament_id = state.create_tournament({a: "alice", b: "bob"}, 1)
    state.update_tournament(tournament_id, {"type": "pair", "pair_id": "p", "wave": 1,
                                             "bracket": "winners", "bot_a": a, "bot_b": b})
    series = state.start_series(a, b, 5, exclusive=True, tournament_id=tournament_id, pair_id="p", wins_needed=3)
    match = state.start_spectating("game", "alice", "bob", official_rules(), series, 1)
    state.finish_spectating(match, "B", "timeout")
    state.resume(a, alice["token"])
    entrant = state.spectator_tournaments()[0]["entrants"][a]
    assert entrant["disconnects"]["winners"] == 1
    assert state.ongoing_series[series]["interrupted_bots"] == []
    state.end_series(series)


def test_disconnected_tournament_client_resumes_same_session_before_next_game(tmp_path, monkeypatch):
    from runtime.remote import run_remote_tournament_series

    monkeypatch.setattr("runtime.remote.TOURNAMENT_RECONNECT_SECONDS", 2.0)
    entered, release = threading.Event(), threading.Event()

    class DisconnectedClient(RemoteBotClient):
        def _heartbeat_loop(self, stop):
            from runtime.remote import _post_json
            while not stop.is_set() and not old_stop.is_set():
                _post_json(self.server_url, "/api/heartbeat", self._credentials())
                stop.wait(self.heartbeat_interval)

        def _handle_task(self, task):
            if task.get("type") == "place_ships":
                entered.set()
                assert release.wait(6)
            return super()._handle_task(task)

    server = create_remote_server("127.0.0.1", 0, action_timeout=2, disconnect_timeout=1)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    old_stop, stop = threading.Event(), threading.Event()
    session = tmp_path / "alice-session.json"
    old = DisconnectedClient(url, "hunt-target", "alice", poll_timeout=0.05, session_file=session, heartbeat_interval=0.1)
    bob = RemoteBotClient(url, "hunt-target", "bob", poll_timeout=0.05, heartbeat_interval=0.1)
    old_thread = threading.Thread(target=old.run_forever, args=(old_stop,), daemon=True)
    bob_thread = threading.Thread(target=bob.run_forever, args=(stop,), daemon=True)
    new_thread = None
    match_thread = None
    result, errors = [], []
    try:
        old_thread.start()
        bob_thread.start()
        _wait_for_bots(url, 2)
        ids = {bot["name"]: bot["bot_id"] for bot in list_remote_bots(url)}
        a, b = ids["alice"], ids["bob"]
        tournament_id = server.hub_state.create_tournament({a: "alice", b: "bob"}, 1)
        server.hub_state.update_tournament(tournament_id, {"type": "pair", "pair_id": "p", "wave": 1,
                                                            "bracket": "winners", "bot_a": a, "bot_b": b})
        def play():
            try:
                result.append(run_remote_tournament_series(url, a, b, 5, str(tmp_path), tournament_id, "p"))
            except Exception as exc:
                errors.append(exc)
        match_thread = threading.Thread(target=play)
        match_thread.start()
        assert entered.wait(5)
        old_stop.set()
        for _ in range(200):
            if next(bot for bot in list_remote_bots(url) if bot["bot_id"] == a)["status"] == "offline":
                break
            threading.Event().wait(0.01)
        else:
            raise AssertionError("client did not become offline")
        replacement = RemoteBotClient(url, "hunt-target", "alice", poll_timeout=0.05,
                                      session_file=session, heartbeat_interval=0.1)
        new_thread = threading.Thread(target=replacement.run_forever, args=(stop,), daemon=True)
        new_thread.start()
        for _ in range(200):
            if replacement.bot_id:
                break
            threading.Event().wait(0.01)
        assert replacement.bot_id == a
        release.set()
        match_thread.join(timeout=25)
        assert not match_thread.is_alive() and not errors
        assert 3 <= len(result[0]["reports"]) <= 5 and not result[0]["stopped"]
        assert result[0]["reports"][0]["winner_bot"] == b
        assert all(report["turns"] > 0 for report in result[0]["reports"][1:])
        assert server.hub_state.spectator_tournaments()[0]["entrants"][a]["disconnects"]["winners"] == 1
    finally:
        release.set()
        if match_thread:
            match_thread.join(timeout=5)
        old_stop.set()
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in (old_thread, bob_thread, new_thread):
            if thread:
                thread.join(timeout=1)
        server_thread.join(timeout=1)


def test_tournament_break_deadline_uses_server_clock(monkeypatch):
    state = RemoteHubState()
    tournament_id = state.create_tournament({"alice": "alice"}, 1)
    monkeypatch.setattr("runtime.remote.time.time", lambda: 1000.0)
    state.update_tournament(tournament_id, {"type": "break", "until": 123.0, "seconds": 60})
    assert state.spectator_tournaments()[0]["break_until"] == 1060.0
    state.update_tournament(tournament_id, {"type": "break", "until": None})
    assert state.spectator_tournaments()[0]["break_until"] is None


def test_tournament_snapshot_exposes_bracket_phase_and_waiting_player_disqualification():
    state = RemoteHubState()
    tournament_id = state.create_tournament({"a": "alice", "b": "bob"}, 1)
    state.update_tournament(tournament_id, {"type": "wave", "wave": 3, "phase": "losers", "finalist_id": "a"})
    snapshot = state.spectator_tournaments()[0]
    assert snapshot["phase"] == "losers" and snapshot["finalist_id"] == "a"
    state.update_tournament(tournament_id, {"type": "disqualification", "wave": 3, "bot_id": "a",
                                             "bracket": "winners", "losses": 1,
                                             "reason": "three disconnects in this bracket"})
    snapshot = state.spectator_tournaments()[0]
    assert snapshot["entrants"]["a"]["losses"] == 1 and snapshot["finalist_id"] is None
    assert snapshot["disqualifications"][0]["bot_id"] == "a"


def test_best_of_five_clinch_finishes_pair_and_blocks_extra_games():
    from runtime.remote import RemoteError

    state = RemoteHubState()
    a = state.register("alice")["bot_id"]
    b = state.register("bob")["bot_id"]
    tournament_id = state.create_tournament({a: "alice", b: "bob"}, 1)
    state.update_tournament(tournament_id, {"type": "pair", "pair_id": "p", "wave": 1,
                                             "bracket": "winners", "bot_a": a, "bot_b": b})
    series = state.start_series(a, b, 5, exclusive=True, tournament_id=tournament_id, pair_id="p", wins_needed=3)
    for game in range(1, 4):
        match = state.start_spectating(f"game-{game}", "alice", "bob", official_rules(), series, game)
        state.finish_spectating(match, "A", "all ships sunk")
    with pytest.raises(RemoteError, match="already finished"):
        state.start_spectating("game-4", "alice", "bob", official_rules(), series, 4)
    with pytest.raises(RemoteError, match="already finished"):
        state.stop_series(series)
    state.end_series(series)
    pair = state.spectator_tournaments()[0]["pairings"][0]
    assert (pair["status"], pair["winner"], pair["completed"], pair["games"]) == ("finished", a, 3, 5)


def test_regular_remote_match_still_plays_requested_games_after_three_wins(monkeypatch):
    from agent import Agent

    class ForfeitBot(Agent):
        def place_ships(self, rules, time_remaining):
            return []

        def choose_shot(self, observation, time_remaining):
            return (0, 0)

    monkeypatch.setattr("runtime.remote.build_bot", lambda *args: ForfeitBot())
    server = create_remote_server("127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop = threading.Event()
    clients = [RemoteBotClient(url, "forfeit", name, poll_timeout=0.1) for name in ("alice", "bob")]
    threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    try:
        for thread in threads:
            thread.start()
        _wait_for_bots(url, 2)
        reports = run_remote_matches(url, "alice", "bob", games=5, seed=1)
        assert len(reports) == 5 and all(report["winner_bot"] == "bob" for report in reports)
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in threads:
            thread.join(timeout=1)
        server_thread.join(timeout=1)


def test_tournament_does_not_wait_for_reconnect_after_clinching_game(tmp_path, monkeypatch):
    from runtime.remote import run_remote_tournament_series

    monkeypatch.setattr("runtime.remote.TOURNAMENT_RECONNECT_SECONDS", 5.0)
    entered, release = threading.Event(), threading.Event()

    class ForfeitThenDelay(RemoteBotClient):
        placements = 0
        def _handle_task(self, task):
            if task.get("type") == "place_ships":
                self.placements += 1
                if self.placements < 3:
                    return {"ok": True, "action_id": task["action_id"], "placements": []}
                entered.set()
                assert release.wait(5)
            return super()._handle_task(task)

    server = create_remote_server("127.0.0.1", 0, action_timeout=0.2)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop = threading.Event()
    clients = [ForfeitThenDelay(url, "hunt-target", "alice", poll_timeout=0.05),
               RemoteBotClient(url, "hunt-target", "bob", poll_timeout=0.05)]
    threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    result, errors = [], []
    match_thread = None
    try:
        for thread in threads:
            thread.start()
        _wait_for_bots(url, 2)
        ids = {bot["name"]: bot["bot_id"] for bot in list_remote_bots(url)}
        a, b = ids["alice"], ids["bob"]
        tournament_id = server.hub_state.create_tournament({a: "alice", b: "bob"}, 1)
        server.hub_state.update_tournament(tournament_id, {"type": "pair", "pair_id": "p", "wave": 1,
                                                            "bracket": "winners", "bot_a": a, "bot_b": b})
        def play():
            try:
                result.append(run_remote_tournament_series(url, a, b, 5, str(tmp_path), tournament_id, "p"))
            except Exception as exc:
                errors.append(exc)
        match_thread = threading.Thread(target=play)
        match_thread.start()
        assert entered.wait(5)
        match_thread.join(timeout=2)
        assert not match_thread.is_alive() and not errors
        assert len(result[0]["reports"]) == 3 and all(report["winner_bot"] == b for report in result[0]["reports"])
        pair = server.hub_state.spectator_tournaments()[0]["pairings"][0]
        assert pair["status"] == "finished" and pair["completed"] == 3
    finally:
        release.set()
        if match_thread:
            match_thread.join(timeout=5)
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in threads:
            thread.join(timeout=1)
        server_thread.join(timeout=1)


def test_tournament_server_enforces_best_of_five_for_match_requests(monkeypatch):
    from runtime.clocks import MoveTiming
    from runtime.runner import MatchReport

    class FixedWinnerRunner:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, agent_a, agent_b, match_id, **kwargs):
            return MatchReport(Player.A, "all ships sunk", 1, {Player.A: 60, Player.B: 60}, match_id,
                               {Player.A: MoveTiming(), Player.B: MoveTiming()})

    monkeypatch.setattr("runtime.remote.LocalRunner", FixedWinnerRunner)
    state = RemoteHubState()
    a = state.register("alice")["bot_id"]
    b = state.register("bob")["bot_id"]
    tournament_id = state.create_tournament({a: "alice", b: "bob"}, 1)
    state.update_tournament(tournament_id, {"type": "pair", "pair_id": "p", "wave": 1,
                                             "bracket": "winners", "bot_a": a, "bot_b": b})
    reports = _run_remote_matches(state, {"bot_a": a, "bot_b": b, "games": 7,
                                           "tournament_id": tournament_id, "pair_id": "p"})
    assert len(reports) == 3
    pair = state.spectator_tournaments()[0]["pairings"][0]
    assert (pair["status"], pair["games"], pair["completed"], pair["winner"]) == ("finished", 5, 3, a)


def test_remote_live_shots_are_paced_without_slowing_bot_actions(monkeypatch):
    import time
    from agent import Agent
    from core.models import ShipPlacement
    from core.rules import Rules

    class FastBot(Agent):
        def __init__(self):
            self.shots = iter([(0, 0), (1, 1)])

        def place_ships(self, rules, time_remaining):
            return [ShipPlacement(0, 1, 1, "horizontal")]

        def choose_shot(self, observation, time_remaining):
            return next(self.shots)

    timestamps = []
    original_record = RemoteHubState.record_shot
    def record(state, spectator_id, result):
        timestamps.append(time.monotonic())
        return original_record(state, spectator_id, result)

    from runtime.clocks import MINIMUM_MOVE_SECONDS
    monkeypatch.setattr("runtime.remote.REMOTE_MINIMUM_MOVE_SECONDS", MINIMUM_MOVE_SECONDS)
    monkeypatch.setattr("runtime.remote.official_rules", lambda: Rules(rows=2, cols=2, fleet=(1,)))
    monkeypatch.setattr("runtime.remote.build_bot", lambda *args: FastBot())
    monkeypatch.setattr(RemoteHubState, "record_shot", record)
    server = create_remote_server("127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop = threading.Event()
    clients = [RemoteBotClient(url, "fast", name, poll_timeout=0.1) for name in ("alice", "bob")]
    threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    try:
        for thread in threads:
            thread.start()
        _wait_for_bots(url, 2)
        reports = run_remote_matches(url, "alice", "bob", 1, 1)
        assert reports[0]["turns"] == 3 and len(timestamps) == 3
        assert all(later - earlier >= 0.49 for earlier, later in zip(timestamps, timestamps[1:]))
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in threads:
            thread.join(timeout=1)
        server_thread.join(timeout=1)


def test_remote_deadline_keeps_lifecycle_hooks_separate_from_placement_and_shots(monkeypatch):
    from agent import MatchContext

    requests = []
    def request(state, bot_id, task, timeout):
        requests.append((task["type"], timeout, task["time_remaining"]))
        if task["type"] == "place_ships":
            return {"ok": True, "placements": []}
        if task["type"] == "choose_shot":
            return {"ok": True, "shot": [0, 0]}
        return {"ok": True, "memory": {}}

    monkeypatch.setattr(RemoteHubState, "request_action", request)
    state = RemoteHubState(action_timeout=5)
    bot_id = state.register("alice")["bot_id"]
    agent = RemoteServerAgent(state, bot_id, "game", Player.A, lifecycle=True)
    agent.start_match(MatchContext("game", Player.A, "alice", "bob", {}))
    agent.place_ships(official_rules(), 5.0)
    from sdk.observation import ObservationState
    agent.choose_shot(ObservationState(official_rules()).snapshot(), 0.5)
    assert requests == [("start_match", 30.0, 0.5), ("place_ships", 5.0, 5.0), ("choose_shot", 0.5, 0.5)]


def test_slow_lifecycle_hook_does_not_consume_move_deadline(tmp_path, monkeypatch):
    import time
    from agent import Agent
    from runtime.remote import run_remote_tournament_series

    slept = threading.Event()
    class SlowStartBot(Agent):
        def start_match(self, context):
            if not slept.is_set():
                slept.set()
                time.sleep(1.1)

        def place_ships(self, rules, time_remaining):
            return []

        def choose_shot(self, observation, time_remaining):
            return (0, 0)

    monkeypatch.setattr("runtime.remote.build_bot", lambda *args: SlowStartBot())
    server = create_remote_server("127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop = threading.Event()
    clients = [RemoteBotClient(url, "slow-start", name, poll_timeout=0.1) for name in ("alice", "bob")]
    threads = [threading.Thread(target=client.run_forever, args=(stop,), daemon=True) for client in clients]
    try:
        for thread in threads:
            thread.start()
        _wait_for_bots(url, 2)
        ids = {bot["name"]: bot["bot_id"] for bot in list_remote_bots(url)}
        result = run_remote_tournament_series(url, ids["alice"], ids["bob"], 1, str(tmp_path))
        assert slept.is_set() and not result["stopped"]
        assert len(result["reports"]) == 3
        assert all("illegal placement" in report["reason"] for report in result["reports"])
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in threads:
            thread.join(timeout=1)
        server_thread.join(timeout=1)


def test_remote_action_response_at_exact_half_second_is_accepted(monkeypatch):
    from runtime.clocks import FakeClock

    state = RemoteHubState()
    alice = state.register("alice")
    clock = FakeClock(100.0)
    monkeypatch.setattr("runtime.remote.time.monotonic", clock)
    results = []
    thread = threading.Thread(target=lambda: results.append(state.request_action(alice["bot_id"], {"action_id": "test"}, 0.5)))
    thread.start()
    try:
        with state.changed:
            assert state.changed.wait_for(lambda: bool(state.bots[alice["bot_id"]].tasks), timeout=3)
            clock.advance(0.5)
            state.respond(alice["bot_id"], alice["token"], {"action_id": "test", "ok": True})
        thread.join(timeout=2)
        assert results == [{"action_id": "test", "ok": True}]
    finally:
        thread.join(timeout=2)


@pytest.mark.parametrize("hide_ships", [False, True])
def test_spectator_visibility_handles_partial_placements_and_finished_games(hide_ships):
    state = RemoteHubState(hide_ships=hide_ships)
    match_id = state.start_spectating("partial", "alice", "bob", official_rules())
    fleet = {slot: tuple((slot, col) for col in range(length)) for slot, length in enumerate(official_rules().fleet)}
    expected = {"A": [list(cell) for cells in fleet.values() for cell in cells]}
    state.record_placement(match_id, Player.A, fleet)
    live = state.spectator_matches()[0]
    if hide_ships:
        assert "fleets" not in live
    else:
        assert live["fleets"] == expected
        live["fleets"]["A"].clear()
        assert len(state.spectator_matches()[0]["fleets"]["A"]) == sum(official_rules().fleet)
    state.finish_spectating(match_id, "A", "test")
    assert state.spectator_matches()[0]["fleets"] == expected

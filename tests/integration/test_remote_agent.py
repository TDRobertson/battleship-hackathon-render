import threading

from runtime.remote import RemoteBotClient, create_remote_server, list_remote_bots, run_remote_matches


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

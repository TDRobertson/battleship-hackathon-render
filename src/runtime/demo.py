from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable

from runtime.remote import RemoteBotClient, RemoteError, create_remote_server


def run_demo(port: int, seed: int, start_tournament: Callable[[str, int, str], int],
             stop_event: threading.Event | None = None, hide_ships: bool = False) -> int:
    """Start an isolated LAN server and nine real local clients for a demo."""
    stop = stop_event if stop_event is not None else threading.Event()
    server = create_remote_server("127.0.0.1", port, hide_ships=hide_ships)
    url = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    clients: list[RemoteBotClient] = []
    client_threads: list[threading.Thread] = []
    tournament_thread: threading.Thread | None = None
    result = [0]
    server_thread.start()
    try:
        print(f"Watch the demo at {url}/", flush=True)
        with tempfile.TemporaryDirectory(prefix="battleship-demo-memory-") as memory_dir:
            for index in range(9):
                client = RemoteBotClient(url, "hunt-target", f"Hunt Target {index + 1}",
                                         seed=seed + index, poll_timeout=0.5)
                client.register()
                clients.append(client)
            for client in clients:
                thread = threading.Thread(target=client.run_forever, args=(stop,), daemon=True)
                thread.start()
                client_threads.append(thread)
            print("Nine hunt-target players connected; starting the tournament.", flush=True)

            def run() -> None:
                try:
                    result[0] = start_tournament(url, seed, memory_dir)
                except Exception as exc:
                    result[0] = 1
                    print(f"Demo tournament failed: {exc}", flush=True)
                if not stop.is_set():
                    status = "finished" if result[0] == 0 else "stopped"
                    print(f"Demo tournament {status}; the dashboard remains available. Press Ctrl+C to stop.", flush=True)

            tournament_thread = threading.Thread(target=run, daemon=True)
            tournament_thread.start()
            try:
                while not stop.wait(0.5):
                    pass
            except KeyboardInterrupt:
                print("Stopping demo server.", flush=True)
            finally:
                stop.set()
                with server.hub_state.lock:
                    for tournament in server.hub_state.tournaments.values():
                        if tournament["status"] == "running":
                            tournament.update(status="stopped", reason="demo stopped")
                # Unregistering wakes any active series and prevents the
                # coordinator from starting another pairing during shutdown.
                for client in clients:
                    if client.bot_id:
                        try:
                            server.hub_state.unregister(client.bot_id)
                        except RemoteError:
                            pass
                if tournament_thread:
                    tournament_thread.join(timeout=10)
                for thread in client_threads:
                    thread.join(timeout=2)
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
    return result[0]

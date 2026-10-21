from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import TextIO
from uuid import uuid4

from agent import Agent
from core.models import Coord, ShipPlacement
from sdk.observation import ObservationSnapshot, ObservationState
from core.rules import Rules


class WorkerFailure(RuntimeError):
    pass


@dataclass
class ProcessAgent(Agent):
    seed: int | None = None
    bot_spec: str = "starter"
    timeout_grace: float = 0.2

    def __post_init__(self) -> None:
        args = [sys.executable, "-m", "runtime.worker", "--bot", self.bot_spec]
        if self.seed is not None:
            args.extend(["--seed", str(self.seed)])
        self.process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._stderr: list[str] = []
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def place_ships(self, rules: Rules, time_remaining: float) -> list[ShipPlacement]:
        response = self._request(
            {
                "type": "place_ships",
                "action_id": str(uuid4()),
                "time_remaining": time_remaining,
            }
        )
        return [
            ShipPlacement(int(p["slot"]), int(p["row"]), int(p["col"]), p["orientation"])
            for p in response["placements"]
        ]

    def choose_shot(self, observation: ObservationSnapshot, time_remaining: float) -> Coord:
        state = ObservationState()
        state.replace_from_snapshot(observation)
        response = self._request(
            {
                "type": "choose_shot",
                "action_id": str(uuid4()),
                "time_remaining": time_remaining,
                "observation": state.to_lists(),
            }
        )
        row, col = response["shot"]
        return int(row), int(col)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=self.timeout_grace)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=self.timeout_grace)

    def _request(self, message: dict) -> dict:
        if self.process.poll() is not None:
            raise WorkerFailure(f"worker exited with code {self.process.returncode}")
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise WorkerFailure("worker produced no response")
        response = json.loads(line)
        if not response.get("ok"):
            raise WorkerFailure(response.get("error", "worker error"))
        return response

    def _drain_stderr(self) -> None:
        stderr: TextIO | None = self.process.stderr
        if stderr is None:
            return
        for line in stderr:
            if sum(len(item) for item in self._stderr) < 8192:
                self._stderr.append(line.rstrip())

    def __enter__(self) -> "ProcessAgent":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

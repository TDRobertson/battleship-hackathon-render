from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class ReplayLog:
    rules: dict
    software_version: str
    actions: list[dict] = field(default_factory=list)
    timing: list[dict] = field(default_factory=list)
    termination: dict | None = None
    private: dict | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "ReplayLog":
        payload = json.loads(text)
        return cls(**payload)

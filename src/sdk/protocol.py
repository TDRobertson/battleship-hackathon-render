from __future__ import annotations

from core.models import Outcome, PublicShotResult, SunkShip

PROTOCOL_VERSION = 1


def shot_result_message(match_id: str, action_id: str, observation_version: int, result: PublicShotResult) -> dict:
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "match_id": match_id,
        "action_id": action_id,
        "observation_version": observation_version,
        "type": "shot_result",
        "shot": list(result.shot),
        "outcome": result.outcome.value,
    }
    if result.sunk_ship is not None:
        payload["sunk_ship"] = {
            "slot": result.sunk_ship.slot,
            "cells": [list(cell) for cell in result.sunk_ship.cells],
        }
    return payload


def result_from_message(message: dict) -> PublicShotResult:
    if message.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("unsupported protocol version")
    if message.get("type") != "shot_result":
        raise ValueError("unsupported message type")
    sunk = None
    if "sunk_ship" in message:
        raw = message["sunk_ship"]
        sunk = SunkShip(int(raw["slot"]), tuple((int(r), int(c)) for r, c in raw["cells"]))
    return PublicShotResult(
        tuple(message["shot"]),
        Outcome(message["outcome"]),
        sunk,
    )


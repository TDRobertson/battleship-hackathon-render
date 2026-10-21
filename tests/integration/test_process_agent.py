import pytest

from runtime.process_agent import ProcessAgent
from core.rules import official_rules


def test_process_agent_starts_places_and_cleans_up():
    pytest.importorskip("numpy")
    agent = ProcessAgent(seed=123)
    try:
        placements = agent.place_ships(official_rules(), 120)
        assert {p.slot for p in placements} == set(official_rules().slots)
    finally:
        agent.close()
    assert agent.process.poll() is not None

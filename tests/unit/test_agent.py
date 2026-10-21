import pytest

from agent import Agent
from bots.hunt_target import HuntTargetBot


def test_agent_base_class_requires_methods():
    with pytest.raises(TypeError):
        Agent()


def test_reference_bot_implements_agent_base_class():
    assert isinstance(HuntTargetBot.seeded(1), Agent)

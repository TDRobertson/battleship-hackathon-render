import pytest


@pytest.fixture
def unpaced_matches(monkeypatch):
    """Keep selected remote match tests fast; timing tests enable pacing explicitly."""
    monkeypatch.setattr("runtime.remote.REMOTE_MINIMUM_MOVE_SECONDS", 0.0)

from core.rules import official_rules
from runtime.remote import _rules_from_payload, _rules_to_payload


def test_official_rules_defaults():
    rules = official_rules()
    assert (rules.rows, rules.cols) == (10, 10)
    assert rules.fleet == (5, 4, 3, 3, 2)
    assert rules.thinking_seconds == 0.5
    assert rules.placement_seconds == 5.0


def test_remote_rules_default_to_official_clock_and_preserve_explicit_clock():
    assert _rules_from_payload({"rows": 10}).thinking_seconds == 0.5
    assert _rules_from_payload({"thinking_seconds": 30}).thinking_seconds == 30.0
    assert _rules_to_payload(official_rules())["thinking_seconds"] == 0.5
    assert _rules_from_payload({"rows": 10}).placement_seconds == 5.0
    assert _rules_from_payload({"placement_seconds": 3}).placement_seconds == 3.0
    assert _rules_to_payload(official_rules())["placement_seconds"] == 5.0

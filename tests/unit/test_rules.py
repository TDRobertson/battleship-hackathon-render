from core.rules import official_rules


def test_official_rules_defaults():
    rules = official_rules()
    assert (rules.rows, rules.cols) == (10, 10)
    assert rules.fleet == (5, 4, 3, 3, 2)
    assert rules.thinking_seconds == 120.0

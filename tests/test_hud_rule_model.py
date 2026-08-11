from core.hud.rule_model import (
    get_default_hud_rules,
    has_runtime_enabled_rules,
    normalize_hud_rules,
)


def test_default_rules_shape():
    rules = get_default_hud_rules("balanced_default")
    assert rules["version"] == 1
    assert "key_rules" in rules
    assert len(rules["key_rules"]) == 9
    assert "kill" in rules["event_rules"]
    assert "bomb_planted" in rules["state_rules"]


def test_normalize_rules_clamps_invalid_values():
    rules = normalize_hud_rules(
        {
            "version": "x",
            "default_color": 999,
            "key_rules": {"1": {"enabled": "true", "color": 88}},
            "event_rules": {
                "kill": {
                    "enabled": True,
                    "effect": "unknown",
                    "main": 200,
                    "alt": -5,
                    "duration_ms": -10,
                    "interval_ms": 1,
                }
            },
        },
        profile="balanced_default",
    )
    assert rules["default_color"] in range(0, 11)
    assert rules["key_rules"]["1"]["enabled"] is True
    assert rules["key_rules"]["1"]["color"] == -1
    assert rules["event_rules"]["kill"]["effect"] == "solid"
    assert rules["event_rules"]["kill"]["duration_ms"] >= 0
    assert rules["event_rules"]["kill"]["interval_ms"] >= 50


def test_runtime_rule_enable_detection():
    rules = get_default_hud_rules("balanced_default")
    assert has_runtime_enabled_rules(rules) is True

    for key in rules["event_rules"]:
        rules["event_rules"][key]["enabled"] = False
    for key in rules["state_rules"]:
        rules["state_rules"][key]["enabled"] = False
    assert has_runtime_enabled_rules(rules) is False


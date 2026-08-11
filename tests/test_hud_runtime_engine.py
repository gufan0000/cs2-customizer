from core.hud.runtime_engine import RuntimeHudEngine
from core.hud.rule_model import get_default_hud_rules


def _gsi_payload(health=100, round_kills=0, round_killhs=0, phase="live", team="ct", weapon="weapon_ak47"):
    return {
        "provider": {"steamid": "123"},
        "round": {"phase": phase, "win_team": ""},
        "bomb": {"state": ""},
        "player": {
            "steamid": "123",
            "activity": "playing",
            "team": team,
            "state": {
                "health": health,
                "round_kills": round_kills,
                "round_killhs": round_killhs,
            },
            "weapons": {
                "weapon_0": {"name": weapon, "state": "active"},
            },
        },
    }


def test_kill_flash_flow_then_fallback_to_default():
    rules = get_default_hud_rules("balanced_default")
    # 只保留 kill 规则，便于确定性验证
    for key in rules["event_rules"]:
        rules["event_rules"][key]["enabled"] = False
    for key in rules["state_rules"]:
        rules["state_rules"][key]["enabled"] = False
    rules["event_rules"]["kill"]["enabled"] = True
    rules["event_rules"]["kill"]["effect"] = "flash"
    rules["event_rules"]["kill"]["main"] = 8
    rules["event_rules"]["kill"]["alt"] = 7
    rules["event_rules"]["kill"]["duration_ms"] = 500
    rules["event_rules"]["kill"]["flash_ms"] = 100
    rules["default_color"] = 0

    engine = RuntimeHudEngine(rules)

    out0 = engine.evaluate(_gsi_payload(round_kills=0), now=1.0)
    assert out0.color == 0

    out1 = engine.evaluate(_gsi_payload(round_kills=1), now=1.1)
    # flash 初段应先显示副色
    assert out1.color == 7

    out2 = engine.evaluate(_gsi_payload(round_kills=1), now=1.25)
    assert out2.color == 8

    out3 = engine.evaluate(_gsi_payload(round_kills=1), now=1.8)
    assert out3.color == 0


def test_death_priority_over_low_health():
    rules = get_default_hud_rules("balanced_default")
    for key in rules["state_rules"]:
        rules["state_rules"][key]["enabled"] = False
    rules["event_rules"]["low_health"]["enabled"] = True
    rules["event_rules"]["low_health"]["threshold"] = 50
    rules["event_rules"]["low_health"]["effect"] = "solid"
    rules["event_rules"]["low_health"]["main"] = 6
    rules["event_rules"]["death"]["enabled"] = True
    rules["event_rules"]["death"]["effect"] = "solid"
    rules["event_rules"]["death"]["main"] = 5
    rules["event_rules"]["death"]["duration_ms"] = 900

    engine = RuntimeHudEngine(rules)

    out0 = engine.evaluate(_gsi_payload(health=30), now=2.0)
    assert out0.color == 6

    out1 = engine.evaluate(_gsi_payload(health=0), now=2.1)
    assert out1.color == 5


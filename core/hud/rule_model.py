"""
HUD unified rule model utilities.
"""

from __future__ import annotations

from copy import deepcopy


HUD_RULES_VERSION = 1
HUD_COLORS = {
    0: ("默认", "#4A90D9"),
    1: ("白色", "#FFFFFF"),
    2: ("浅蓝", "#7EC8E3"),
    3: ("深蓝", "#2E5090"),
    4: ("紫色", "#9B59B6"),
    5: ("红色", "#E74C3C"),
    6: ("橙色", "#E67E22"),
    7: ("黄色", "#F1C40F"),
    8: ("绿色", "#2ECC71"),
    9: ("青色", "#1ABC9C"),
    10: ("粉色", "#E91E8F"),
}

HUD_EFFECTS = {"solid", "flash", "blink", "pulse"}
HUD_RUNTIME_REFRESH_KEYS = {"w", "a", "s", "d"}
HUD_SYNC_MODES = {"safe"}

HUD_EVENT_KEYS = (
    "kill",
    "headshot_kill",
    "multi_kill",
    "death",
    "low_health",
)
HUD_STATE_KEYS = (
    "bomb_planted",
    "round_win",
    "round_lose",
    "weapon_rifle",
    "weapon_sniper",
    "weapon_pistol",
    "weapon_knife",
    "round_live",
    "round_start",
)

HUD_PRIORITIES = {
    "manual_key": 900,
    "death": 850,
    "multi_kill": 830,
    "headshot_kill": 820,
    "kill": 800,
    "bomb_planted": 700,
    "low_health": 650,
    "round_win": 600,
    "round_lose": 600,
    "weapon_rifle": 500,
    "weapon_sniper": 500,
    "weapon_pistol": 500,
    "weapon_knife": 500,
    "round_live": 400,
    "round_start": 400,
    "default": 100,
}

HUD_PROFILES = ("balanced_default", "competitive_simple", "flashy", "kill_only", "tactical")


def _to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "on"}:
            return True
        if v in {"0", "false", "no", "off"}:
            return False
    return default


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_profile(profile):
    if isinstance(profile, str) and profile in HUD_PROFILES:
        return profile
    return "balanced_default"


def is_valid_hud_color(color):
    return isinstance(color, int) and color in HUD_COLORS


def normalize_hud_color(color, allow_disabled=False, default=0):
    if allow_disabled and color == -1:
        return -1
    c = _to_int(color, default)
    if c not in HUD_COLORS:
        return default
    return c


def normalize_effect(effect, default="solid"):
    if isinstance(effect, str) and effect in HUD_EFFECTS:
        return effect
    return default


def normalize_runtime_refresh_key(key):
    if not isinstance(key, str):
        return "w"
    normalized = key.strip().lower()
    if normalized in HUD_RUNTIME_REFRESH_KEYS:
        return normalized
    return "w"


def normalize_sync_mode(mode):
    if isinstance(mode, str) and mode in HUD_SYNC_MODES:
        return mode
    return "safe"


def _build_key_rules():
    rules = {}
    for i in range(1, 10):
        rules[str(i)] = {"enabled": False, "color": -1}
    return rules


def _balanced_profile():
    return {
        "version": HUD_RULES_VERSION,
        "default_color": 0,
        "key_rules": _build_key_rules(),
        "event_rules": {
            "kill": {
                "enabled": True,
                "effect": "flash",
                "main": 8,
                "alt": 7,
                "duration_ms": 500,
                "flash_ms": 120,
                "interval_ms": 200,
                "duty_cycle": 0.5,
                "priority": HUD_PRIORITIES["kill"],
            },
            "headshot_kill": {
                "enabled": True,
                "effect": "flash",
                "main": 7,
                "alt": 1,
                "duration_ms": 450,
                "flash_ms": 150,
                "interval_ms": 200,
                "duty_cycle": 0.5,
                "priority": HUD_PRIORITIES["headshot_kill"],
            },
            "multi_kill": {
                "enabled": True,
                "effect": "pulse",
                "main": 6,
                "alt": 5,
                "duration_ms": 1200,
                "flash_ms": 0,
                "interval_ms": 180,
                "duty_cycle": 0.55,
                "priority": HUD_PRIORITIES["multi_kill"],
            },
            "death": {
                "enabled": True,
                "effect": "solid",
                "main": 5,
                "alt": -1,
                "duration_ms": 900,
                "flash_ms": 0,
                "interval_ms": 250,
                "duty_cycle": 0.5,
                "priority": HUD_PRIORITIES["death"],
            },
            "low_health": {
                "enabled": True,
                "effect": "blink",
                "main": 5,
                "alt": 6,
                "duration_ms": 0,
                "flash_ms": 0,
                "interval_ms": 250,
                "duty_cycle": 0.5,
                "priority": HUD_PRIORITIES["low_health"],
                "threshold": 20,
            },
        },
        "state_rules": {
            "bomb_planted": {
                "enabled": True,
                "effect": "pulse",
                "main": 6,
                "alt": 5,
                "duration_ms": 0,
                "flash_ms": 0,
                "interval_ms": 220,
                "duty_cycle": 0.5,
                "priority": HUD_PRIORITIES["bomb_planted"],
            },
            "round_win": {
                "enabled": False,
                "effect": "solid",
                "main": 8,
                "alt": -1,
                "duration_ms": 2500,
                "flash_ms": 0,
                "interval_ms": 250,
                "duty_cycle": 0.5,
                "priority": HUD_PRIORITIES["round_win"],
            },
            "round_lose": {
                "enabled": False,
                "effect": "solid",
                "main": 5,
                "alt": -1,
                "duration_ms": 2500,
                "flash_ms": 0,
                "interval_ms": 250,
                "duty_cycle": 0.5,
                "priority": HUD_PRIORITIES["round_lose"],
            },
            "weapon_rifle": {
                "enabled": False,
                "effect": "solid",
                "main": 8,
                "alt": -1,
                "duration_ms": 0,
                "flash_ms": 0,
                "interval_ms": 250,
                "duty_cycle": 0.5,
                "priority": HUD_PRIORITIES["weapon_rifle"],
            },
            "weapon_sniper": {
                "enabled": False,
                "effect": "solid",
                "main": 3,
                "alt": -1,
                "duration_ms": 0,
                "flash_ms": 0,
                "interval_ms": 250,
                "duty_cycle": 0.5,
                "priority": HUD_PRIORITIES["weapon_sniper"],
            },
            "weapon_pistol": {
                "enabled": False,
                "effect": "solid",
                "main": 9,
                "alt": -1,
                "duration_ms": 0,
                "flash_ms": 0,
                "interval_ms": 250,
                "duty_cycle": 0.5,
                "priority": HUD_PRIORITIES["weapon_pistol"],
            },
            "weapon_knife": {
                "enabled": False,
                "effect": "solid",
                "main": 1,
                "alt": -1,
                "duration_ms": 0,
                "flash_ms": 0,
                "interval_ms": 250,
                "duty_cycle": 0.5,
                "priority": HUD_PRIORITIES["weapon_knife"],
            },
            "round_live": {
                "enabled": False,
                "effect": "solid",
                "main": 0,
                "alt": -1,
                "duration_ms": 0,
                "flash_ms": 0,
                "interval_ms": 250,
                "duty_cycle": 0.5,
                "priority": HUD_PRIORITIES["round_live"],
            },
            "round_start": {
                "enabled": False,
                "effect": "solid",
                "main": 2,
                "alt": -1,
                "duration_ms": 0,
                "flash_ms": 0,
                "interval_ms": 250,
                "duty_cycle": 0.5,
                "priority": HUD_PRIORITIES["round_start"],
            },
        },
    }


def _competitive_profile():
    cfg = _balanced_profile()
    cfg["event_rules"]["kill"].update({"effect": "solid", "duration_ms": 350, "alt": -1})
    cfg["event_rules"]["headshot_kill"].update({"effect": "solid", "duration_ms": 350, "main": 7, "alt": -1})
    cfg["event_rules"]["multi_kill"].update({"effect": "solid", "duration_ms": 600, "main": 6, "alt": -1})
    cfg["event_rules"]["low_health"].update({"effect": "solid", "alt": -1})
    cfg["state_rules"]["bomb_planted"].update({"effect": "solid", "alt": -1})
    return cfg


def _flashy_profile():
    cfg = _balanced_profile()
    cfg["event_rules"]["kill"].update({"effect": "flash", "flash_ms": 180, "duration_ms": 650})
    cfg["event_rules"]["headshot_kill"].update({"effect": "blink", "interval_ms": 120, "duration_ms": 700})
    cfg["event_rules"]["multi_kill"].update({"effect": "pulse", "interval_ms": 130, "duration_ms": 1500})
    cfg["event_rules"]["low_health"].update({"effect": "blink", "interval_ms": 160})
    cfg["state_rules"]["bomb_planted"].update({"effect": "pulse", "interval_ms": 140})
    cfg["state_rules"]["round_win"]["enabled"] = True
    cfg["state_rules"]["round_lose"]["enabled"] = True
    return cfg


def _kill_only_profile():
    cfg = _balanced_profile()
    # 只保留击杀相关事件
    cfg["event_rules"]["kill"].update({"enabled": True, "effect": "flash", "main": 8, "alt": 7, "duration_ms": 400})
    cfg["event_rules"]["headshot_kill"].update({"enabled": True, "effect": "flash", "main": 7, "alt": 1, "duration_ms": 500})
    cfg["event_rules"]["multi_kill"].update({"enabled": True, "effect": "pulse", "main": 6, "alt": 5, "duration_ms": 1000})
    cfg["event_rules"]["death"].update({"enabled": False})
    cfg["event_rules"]["low_health"].update({"enabled": False})
    for key in cfg["state_rules"]:
        cfg["state_rules"][key]["enabled"] = False
    return cfg


def _tactical_profile():
    cfg = _balanced_profile()
    # 侧重战术信息：低血量、炸弹、回合状态
    cfg["event_rules"]["kill"].update({"enabled": True, "effect": "solid", "main": 8, "duration_ms": 300, "alt": -1})
    cfg["event_rules"]["headshot_kill"].update({"enabled": False})
    cfg["event_rules"]["multi_kill"].update({"enabled": False})
    cfg["event_rules"]["death"].update({"enabled": True, "effect": "solid", "main": 5, "duration_ms": 1500, "alt": -1})
    cfg["event_rules"]["low_health"].update({"enabled": True, "effect": "blink", "main": 5, "alt": 6, "interval_ms": 200, "threshold": 30})
    cfg["state_rules"]["bomb_planted"].update({"enabled": True, "effect": "pulse", "main": 6, "alt": 5, "interval_ms": 180})
    cfg["state_rules"]["round_win"].update({"enabled": True, "effect": "solid", "main": 8, "duration_ms": 2000})
    cfg["state_rules"]["round_lose"].update({"enabled": True, "effect": "solid", "main": 5, "duration_ms": 2000})
    return cfg


def get_default_hud_rules(profile="balanced_default"):
    profile = normalize_profile(profile)
    if profile == "competitive_simple":
        return _competitive_profile()
    if profile == "flashy":
        return _flashy_profile()
    if profile == "kill_only":
        return _kill_only_profile()
    if profile == "tactical":
        return _tactical_profile()
    return _balanced_profile()


def _normalize_key_rules(key_rules):
    normalized = _build_key_rules()
    if not isinstance(key_rules, dict):
        return normalized
    for key, entry in key_rules.items():
        key_str = str(key)
        if key_str not in normalized:
            continue
        if isinstance(entry, dict):
            enabled = _to_bool(entry.get("enabled", False), False)
            color = normalize_hud_color(entry.get("color", -1), allow_disabled=True, default=-1)
        else:
            enabled = _to_bool(entry, False)
            color = -1
        normalized[key_str] = {"enabled": enabled, "color": color}
    return normalized


def _normalize_runtime_rule(rule, key, default_rule):
    if not isinstance(rule, dict):
        rule = {}
    base = deepcopy(default_rule)
    base["enabled"] = _to_bool(rule.get("enabled", base.get("enabled", False)), base.get("enabled", False))
    base["effect"] = normalize_effect(rule.get("effect", base.get("effect", "solid")))
    base["main"] = normalize_hud_color(rule.get("main", base.get("main", 0)), allow_disabled=True, default=base.get("main", 0))
    base["alt"] = normalize_hud_color(rule.get("alt", base.get("alt", -1)), allow_disabled=True, default=base.get("alt", -1))
    base["duration_ms"] = max(0, _to_int(rule.get("duration_ms", base.get("duration_ms", 0)), base.get("duration_ms", 0)))
    base["flash_ms"] = max(0, _to_int(rule.get("flash_ms", base.get("flash_ms", 120)), base.get("flash_ms", 120)))
    base["interval_ms"] = max(50, _to_int(rule.get("interval_ms", base.get("interval_ms", 250)), base.get("interval_ms", 250)))
    duty_cycle = _to_float(rule.get("duty_cycle", base.get("duty_cycle", 0.5)), base.get("duty_cycle", 0.5))
    base["duty_cycle"] = min(0.95, max(0.05, duty_cycle))
    base["priority"] = _to_int(rule.get("priority", base.get("priority", HUD_PRIORITIES.get(key, 100))), base.get("priority", HUD_PRIORITIES.get(key, 100)))
    if key == "low_health":
        base["threshold"] = min(100, max(1, _to_int(rule.get("threshold", base.get("threshold", 20)), base.get("threshold", 20))))
    return base


def normalize_hud_rules(rules, profile="balanced_default"):
    defaults = get_default_hud_rules(profile)
    if not isinstance(rules, dict):
        return defaults

    normalized = deepcopy(defaults)
    normalized["version"] = _to_int(rules.get("version", HUD_RULES_VERSION), HUD_RULES_VERSION)
    normalized["default_color"] = normalize_hud_color(rules.get("default_color", defaults["default_color"]), allow_disabled=True, default=defaults["default_color"])
    normalized["key_rules"] = _normalize_key_rules(rules.get("key_rules", {}))

    incoming_event_rules = rules.get("event_rules", {})
    if isinstance(incoming_event_rules, dict):
        for key in HUD_EVENT_KEYS:
            normalized["event_rules"][key] = _normalize_runtime_rule(
                incoming_event_rules.get(key, {}),
                key,
                defaults["event_rules"][key],
            )

    incoming_state_rules = rules.get("state_rules", {})
    if isinstance(incoming_state_rules, dict):
        for key in HUD_STATE_KEYS:
            normalized["state_rules"][key] = _normalize_runtime_rule(
                incoming_state_rules.get(key, {}),
                key,
                defaults["state_rules"][key],
            )

    return normalized


def has_runtime_enabled_rules(rules):
    normalized = normalize_hud_rules(rules)
    for entry in normalized["event_rules"].values():
        if entry.get("enabled", False) and entry.get("main", -1) >= 0:
            return True
    for entry in normalized["state_rules"].values():
        if entry.get("enabled", False) and entry.get("main", -1) >= 0:
            return True
    return False


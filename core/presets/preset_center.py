# SPDX-License-Identifier: GPL-3.0-or-later
"""Preset bundle export/import/apply (schema v1)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List

from config import config
from core.utils.logger import get_logger

_logger = get_logger("PresetCenter")

SCHEMA_NAME = "cs2customizer_preset_bundle"
# v2(2026-06-12,R2-1):新增 crosshair / flash / viewmodel / magnifier 四个纯配置类型。
# 兼容性:v1 文件可被 v2 正常校验与应用(类型子集);v2 文件在旧版会被拒(版本号不符),符合预期。
SCHEMA_VERSION = 2
_COMPAT_VERSIONS = {1, 2}
SUPPORTED_TYPES = {
    "hud_rules", "screen_effects", "special_sound",
    "crosshair", "flash", "viewmodel", "magnifier",
}


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class ApplyResult:
    ok: bool
    applied_types: List[str] = field(default_factory=list)
    changed_keys: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    # QA-013: 应用前的"自动快照"失败时，调用方**得有个地方知道**。
    # 原来那个 `except Exception: pass` 连日志都不记，apply 照样返回 ok=True，
    # UI 照样弹「已应用，可在配置快照页回滚」—— 用户信了这句话去回滚，
    # 才发现根本没有还原点。
    warnings: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _hud_payload() -> Dict[str, object]:
    return {
        "hud_rules_enabled": bool(getattr(config, "hud_rules_enabled", True)),
        "hud_rules_profile": getattr(config, "hud_rules_profile", "balanced_default"),
        "hud_rules": getattr(config, "hud_rules", {}),
        "hud_runtime_sync_mode": getattr(config, "hud_runtime_sync_mode", "safe"),
        "hud_runtime_refresh_key": getattr(config, "hud_runtime_refresh_key", "f10"),
        "hud_keymap_enabled": getattr(config, "hud_keymap_enabled", {}),
    }


def _screen_effects_payload() -> Dict[str, object]:
    return {
        "screen_effects_enabled": bool(getattr(config, "screen_effects_enabled", False)),
        "screen_edge_flash_enabled": bool(getattr(config, "screen_edge_flash_enabled", False)),
        "screen_effects_preset": getattr(config, "screen_effects_preset", "impact_sparks"),
        "screen_effects_play_mode": getattr(config, "screen_effects_play_mode", "streak"),
    }


def _special_sound_payload() -> Dict[str, object]:
    return {
        "grenade_sound_enabled": bool(getattr(config, "grenade_sound_enabled", False)),
        "grenade_sound_styles": dict(getattr(config, "grenade_sound_styles", {}) or {}),
        "c4_sound_enabled": bool(getattr(config, "c4_sound_enabled", False)),
        "c4_sound_style": getattr(config, "c4_sound_style", "0"),
        "health_warning_enabled": bool(getattr(config, "health_warning_enabled", False)),
        "health_warning_style": getattr(config, "health_warning_style", "0"),
        "health_warning_threshold": int(getattr(config, "health_warning_threshold", 20)),
        "round_sound_enabled": bool(getattr(config, "round_sound_enabled", False)),
        "round_start_style": getattr(config, "round_start_style", "0"),
        "round_action_style": getattr(config, "round_action_style", "0"),
        "round_win_style": getattr(config, "round_win_style", "0"),
        "round_lose_style": getattr(config, "round_lose_style", "0"),
        "round_mvp_style": getattr(config, "round_mvp_style", "0"),
    }


def _config_keys_payload(keys) -> Dict[str, object]:
    """按 key 列表打包 config 当前值(dict/list 做浅拷贝防引用泄漏)。"""
    out: Dict[str, object] = {}
    for key in keys:
        value = getattr(config, key, None)
        if isinstance(value, dict):
            value = dict(value)
        elif isinstance(value, list):
            value = list(value)
        out[key] = value
    return out


# v2 纯配置类型:key 面取证见 .build/_cfgfields.txt(2026-06-12)
_CROSSHAIR_KEYS = (
    "crosshair_enabled", "crosshair_style", "crosshair_color", "crosshair_size",
    "crosshair_thickness", "crosshair_animation", "crosshair_kill_effect",
    "crosshair_reset_enabled", "crosshair_custom_data",
    # 2.2.4 补齐的样式参数。漏登记的表现是"切预设后间隙/描边保持上一套的值"，
    # 而且**不报错**——预设看起来切了、准星却是两套配置的混合体。
    "crosshair_gap", "crosshair_outline", "crosshair_dot",
    "crosshair_alpha", "crosshair_color_custom",
    # 回正的开火键设置跟着 crosshair_reset_enabled 走：预设里带了开关却不带
    # 键位，切预设后会用别人的开关配自己的键，而且不报错。
    "crosshair_reset_attack_key",
    "crosshair_reset_secondary_enabled", "crosshair_reset_secondary_key",
)
_FLASH_KEYS = (
    "flash_enabled", "flash_style", "flash_bg_color", "flash_max_opacity",
    "flash_fade_in_enabled", "flash_fade_out_enabled", "flash_style_params",
    "flash_image_style", "flash_image_opacity", "flash_image_position",
    "flash_image_size", "flash_image_rotation",
    "flash_audio_enabled", "flash_audio_style", "flash_audio_volume",
    "flash_audio_rotation", "flash_audio_auto_stop",
)
_VIEWMODEL_KEYS = (
    "viewmodel_presets", "viewmodel_cycle_key",
    "viewmodel_auto_switch_enabled", "viewmodel_auto_switch_interval",
    "viewmodel_auto_switch_key",
)
_MAGNIFIER_KEYS = ("magnifier_enabled", "magnifier")

# 导入白名单：每种类型只允许写这些 config 键。分享包 payload 是外来数据，
# 无白名单时任意键都会被 setattr 进真实 config（如恶意包改写 csgo_dir/热键）
_HUD_KEYS = (
    "hud_rules_enabled", "hud_rules_profile", "hud_rules",
    "hud_runtime_sync_mode", "hud_runtime_refresh_key", "hud_keymap_enabled",
)
_SCREEN_EFFECTS_KEYS = (
    "screen_effects_enabled", "screen_edge_flash_enabled",
    "screen_effects_preset", "screen_effects_play_mode",
)
_SPECIAL_SOUND_KEYS = (
    "grenade_sound_enabled", "grenade_sound_styles", "c4_sound_enabled", "c4_sound_style",
    "health_warning_enabled", "health_warning_style", "health_warning_threshold",
    "round_sound_enabled", "round_start_style", "round_action_style",
    "round_win_style", "round_lose_style", "round_mvp_style",
)
_TYPE_ALLOWED_KEYS = {
    "hud_rules": frozenset(_HUD_KEYS),
    "screen_effects": frozenset(_SCREEN_EFFECTS_KEYS),
    "special_sound": frozenset(_SPECIAL_SOUND_KEYS),
    "crosshair": frozenset(_CROSSHAIR_KEYS),
    "flash": frozenset(_FLASH_KEYS),
    "viewmodel": frozenset(_VIEWMODEL_KEYS),
    "magnifier": frozenset(_MAGNIFIER_KEYS),
}

_TYPE_BUILDERS = {
    "hud_rules": lambda: _hud_payload(),
    "screen_effects": lambda: _screen_effects_payload(),
    "special_sound": lambda: _special_sound_payload(),
    "crosshair": lambda: _config_keys_payload(_CROSSHAIR_KEYS),
    "flash": lambda: _config_keys_payload(_FLASH_KEYS),
    "viewmodel": lambda: _config_keys_payload(_VIEWMODEL_KEYS),
    "magnifier": lambda: _config_keys_payload(_MAGNIFIER_KEYS),
}


def export_bundle(selected_types: List[str]) -> Dict[str, object]:
    items = []
    for preset_type in selected_types:
        builder = _TYPE_BUILDERS.get(preset_type)
        if builder is not None:
            items.append({"type": preset_type, "payload": builder()})

    return {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "items": items,
    }


def validate_bundle(bundle: Dict[str, object]) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(bundle, dict):
        return ValidationResult(ok=False, errors=["bundle must be a dict"])

    if bundle.get("schema") != SCHEMA_NAME:
        errors.append(f"invalid schema: {bundle.get('schema')}")
    if int(bundle.get("schema_version", 0) or 0) not in _COMPAT_VERSIONS:
        errors.append(f"unsupported schema_version: {bundle.get('schema_version')}")

    items = bundle.get("items")
    if not isinstance(items, list):
        errors.append("items must be a list")
        return ValidationResult(ok=False, errors=errors, warnings=warnings)

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"items[{idx}] must be object")
            continue
        preset_type = str(item.get("type", ""))
        payload = item.get("payload")
        if preset_type not in SUPPORTED_TYPES:
            errors.append(f"items[{idx}] unsupported type: {preset_type}")
        if not isinstance(payload, dict):
            errors.append(f"items[{idx}] payload must be object")
            continue
        if not payload:
            warnings.append(f"items[{idx}] payload is empty")

    return ValidationResult(ok=(len(errors) == 0), errors=errors, warnings=warnings)


def _apply_payload(payload: Dict[str, object], *, replace: bool, changed_keys: List[str]):
    for key, value in payload.items():
        current = getattr(config, key, None)
        if isinstance(current, dict):
            if replace:
                setattr(config, key, dict(value if isinstance(value, dict) else {}))
            else:
                if isinstance(value, dict):
                    merged = dict(current)
                    merged.update(value)
                    setattr(config, key, merged)
                else:
                    setattr(config, key, value)
        else:
            setattr(config, key, value)
        changed_keys.append(key)


def apply_bundle(bundle: Dict[str, object], mode: str = "merge") -> ApplyResult:
    validation = validate_bundle(bundle)
    if not validation.ok:
        return ApplyResult(ok=False, errors=list(validation.errors))

    replace = str(mode or "merge").lower() == "replace"
    applied_types: List[str] = []
    changed_keys: List[str] = []
    warnings: List[str] = []

    if bool(getattr(config, "config_snapshot_auto_before_risky_ops", True)):
        # QA-013: create 和 prune **必须分开兜**。
        # create 失败 = 还原点根本不存在 → 要告诉用户，别再承诺"可以回滚"。
        # prune 失败 = 还原点是**在**的，只是旧快照没清干净 → 记日志就够，
        #   报「无法回滚」是假警报，用户被骗一次就再也不信这个提示，比不提示更糟。
        from core.config_snapshot_manager import create_snapshot, prune_snapshots

        snapshot_ok = False
        try:
            create_snapshot(f"preset_apply_{'replace' if replace else 'merge'}")
            snapshot_ok = True
        except Exception as exc:
            _logger.warning("应用预设前的自动快照建立失败：%s", exc, exc_info=True)
            warnings.append("未能建立应用前快照，此次应用无法回滚到之前的配置")
        if snapshot_ok:
            try:
                prune_snapshots(int(getattr(config, "config_snapshot_max_keep", 20) or 20))
            except Exception as exc:
                _logger.warning("快照清理失败（还原点已建立，不影响回滚）：%s", exc)

    for item in bundle.get("items", []) or []:
        preset_type = str(item.get("type", ""))
        payload = item.get("payload", {})
        if preset_type not in SUPPORTED_TYPES or not isinstance(payload, dict):
            continue
        allowed = _TYPE_ALLOWED_KEYS.get(preset_type, frozenset())
        filtered = {k: v for k, v in payload.items() if k in allowed}
        _apply_payload(filtered, replace=replace, changed_keys=changed_keys)
        applied_types.append(preset_type)

    if hasattr(config, "save_config_now"):
        config.save_config_now()
    else:
        config.save_config()

    # UP-035: 配置被整体改写了,广播出去让已打开的页面重读。
    # 不广播的后果不是"界面没刷新"这么轻——已打开的页面还显示旧值,
    # 用户随手动一下控件就用旧值 save_config(),把刚应用的整套预设冲掉。
    try:
        from core.config_reload_bus import notify

        notify("preset_apply", changed_keys)
    except Exception:
        pass

    return ApplyResult(ok=True, applied_types=applied_types, changed_keys=changed_keys,
                       warnings=warnings)

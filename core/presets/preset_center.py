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


#: 类别 id → 玩家看得懂的名字。**全仓唯一一份。**
#:
#: ⭐⭐ 批 40 之前有**两份**，而且不一致：这一份原来住在
#: `share_file.describe()` 里（写「HUD **颜色规则**」），页面的
#: `_TYPE_CHECKBOX_SPEC` 里那一份写「HUD 规则」。
#: ⚠ 批 38 刚在这一页上统一过一次同物两名（勾选框「HUD 规则」vs 摘要「HUD」），
#:   **而第三份躲过了那一轮** —— 因为它只出现在**导入确认对话框**里，
#:   那是一个要按下按钮之后才存在的画面，任何一张截图都拍不到它。
#: ⭐⭐⭐ **同一个词的第三份副本，藏在一个截图拍不到的地方**
#:   —— 台账那条「外审的盲区」再添一个实例（代码 / 时间轴 / 键盘 / 记账）。
TYPE_LABELS: Dict[str, str] = {
    "hud_rules": "HUD 规则",
    "screen_effects": "屏幕特效",
    "special_sound": "特殊音效",
    "crosshair": "准心",
    "flash": "自定闪光",
    "viewmodel": "局内视角",
    "magnifier": "开镜放大",
}


def _count(value: object) -> int:
    return len(value) if isinstance(value, (list, dict, tuple)) else 0


def _switch(payload: Dict[str, object], key: str) -> str:
    value = payload.get(key)
    if value is None:
        return ""
    return "开着" if value else "关着"


def _summarize_payload(preset_type: str, payload: Dict[str, object]) -> str:
    """一句人话，说清这一类里大概装了什么。

    ⛔ **只说三种东西**：开着还是关着、数得出来的个数、带单位的数字。
    ⚠ **一律不印引擎 id**（`impact_sparks` / `flicker` / `"0"`）——
      要把它们变成人话就得再抄一份「id → 中文名」的表，而这个模块的头两行
      刚刚记下了抄那种表的代价。⭐ **宁可少说一句，也不要为了说得好看
      而在第二个地方复述一份会漂的知识。**
    """
    parts: List[str] = []
    if preset_type == "hud_rules":
        parts.append(_switch(payload, "hud_rules_enabled"))
        rules = payload.get("hud_rules")
        if isinstance(rules, dict):
            # ⚠⚠ RN-487（批 40 补刀）：这里原来数的是 `key_rules` 的**槽位数**，
            #   而 `_build_key_rules()` 恒建 "1"~"9" 九项、`_normalize_key_rules`
            #   只覆盖不新增 ⇒ 这一行对**所有人、所有预设**永远是「9 条按键颜色规则」。
            #   实测全新配置：槽位 9 个，`enabled=True` 的 **0 个**。
            # ⭐⭐ 而 HUD 页对同一份数据显示的是「数字键 · 0 项」——
            #   **同一份数据，两处各说各的，其中一处恒定。**
            #   这张卡是本批为了「让人读得懂里面有什么」才加的，
            #   ⇒ 它的第一行不能是一句对谁都一样的话。
            enabled = sum(
                1 for v in (rules.get("key_rules") or {}).values()
                if isinstance(v, dict) and v.get("enabled")
            ) if isinstance(rules.get("key_rules"), dict) else 0
            parts.append(f"{enabled} 条按键颜色规则开着" if enabled else "没有开着的按键颜色规则")
    elif preset_type == "screen_effects":
        parts.append(_switch(payload, "screen_effects_enabled"))
        if payload.get("screen_edge_flash_enabled"):
            parts.append("含边缘闪光")
    elif preset_type == "special_sound":
        threshold = payload.get("health_warning_threshold")
        for key, name in (("grenade_sound_enabled", "投掷物"),
                          ("c4_sound_enabled", "C4"),
                          ("health_warning_enabled", "血量警告"),
                          ("round_sound_enabled", "回合")):
            if key not in payload:
                continue
            tail = ""
            # ⚠ 那个阈值第一版是**单独一段**（「血量警告 开 · 回合 关 · 血量低于 20% 时提醒」）
            #   —— 它被「回合 关」隔开，读起来像是在说回合。⭐ 一个修饰语离开它修饰的东西，
            #   就会去修饰它旁边那个（批 38「标签失去邻居就变含糊」的同一件事，换到一行字里）。
            if (key == "health_warning_enabled" and payload[key]
                    and isinstance(threshold, (int, float))):
                tail = f"（低于 {threshold}%）"
            parts.append(f"{name} {'开' if payload[key] else '关'}{tail}")
    elif preset_type == "crosshair":
        parts.append(_switch(payload, "crosshair_enabled"))
        for key, name in (("crosshair_size", "大小"), ("crosshair_thickness", "粗细")):
            if isinstance(payload.get(key), (int, float)):
                parts.append(f"{name} {payload[key]}")
    elif preset_type == "flash":
        parts.append(_switch(payload, "flash_enabled"))
        if payload.get("flash_audio_enabled"):
            parts.append("带音效")
    elif preset_type == "viewmodel":
        parts.append(f"{_count(payload.get('viewmodel_presets'))} 套视角预设")
        key = payload.get("viewmodel_cycle_key")
        if isinstance(key, str) and key:
            parts.append(f"轮换键 {key}")
    elif preset_type == "magnifier":
        parts.append(_switch(payload, "magnifier_enabled"))
        detail = payload.get("magnifier")
        if isinstance(detail, dict) and isinstance(detail.get("zoom_factor"), (int, float)):
            parts.append(f"放大 {detail['zoom_factor']} 倍")

    # ⛔ 这里原来是 `… if isinstance(payload, dict) else "内容无法识别"` ——
    #   而唯一的调用方 `describe_bundle` 已经把非 dict 的 payload 换成了 `{}`，
    #   ⇒ 那个 else 分支**结构上走不到**。一个走不到的兜底分支只会让人以为兜住了。
    parts.append(f"共 {len(payload)} 个设置项")
    return " · ".join(p for p in parts if p)


def mode_affects_result(bundle: Dict[str, object]) -> List[tuple]:
    """这份包里，「合并」和「覆盖」会得出不同结果的 (类别, 键) —— 空表示两者等价。

    ⭐⭐⭐ 这条知识只有一个来源：`_apply_payload` **只对现有值是 dict 的键**
      区分两种模式（replace 整个换掉，merge 逐键并上去）；其余键两种模式
      都是同一句 `setattr(config, key, value)`。
    ⚠ 端到端实测（造包 → 复位 → 两种模式各跑一遍 → 逐键深比对）：
      **64 个键里只有 5 个**结果不同，而 7 类里有 3 类一个都没有。
    ⇒ 所以「要合并还是覆盖」不是一个该无条件问的问题；
      ⭐ **一个在多数场景里什么都不改的选择，不该摆在所有人的必经之路上**
      （RN-415「改不动任何像素的就必须禁用」的同族）。
    """
    hits: List[tuple] = []
    for item in (bundle or {}).get("items", []) or []:
        preset_type = str(item.get("type", ""))
        payload = item.get("payload", {})
        if preset_type not in SUPPORTED_TYPES or not isinstance(payload, dict):
            continue
        allowed = _TYPE_ALLOWED_KEYS.get(preset_type, frozenset())
        for key in payload:
            if key in allowed and isinstance(getattr(config, key, None), dict):
                hits.append((preset_type, key))
    return hits


def describe_bundle(bundle: Dict[str, object]) -> List[tuple]:
    """把一份预设包翻成 [(类别名, 这一类里有什么)]，**给人看的**。

    ⭐⭐⭐ 这是批 40 的主刀之一（RN-476）。改前那一屏摆的是
    **8767 个字符 / 329 行**的原始 JSON（`{"schema": "cs2customizer_preset_bundle", …`），
    而那张卡的副标题逐字承诺它是给人「快速确认内容范围」用的。
    ⚠ 外审 12 发问「你说得出这一套里有哪几类、每一类大概是什么吗」——
      **12/12 答「说不出」**，其中 8 发是在那个 JSON 框**完整可见**的整页图上答的，
      10/12 的「读自」栏填的是「无」。
    ⇒ ⭐⭐ **它不是「看着累」，是它承诺的那件事它一件都没做到** ——
      一个把全部信息都摆出来的控件，可以同时是一个什么都没说的控件。

    ⚠ 返回**结构**而不是拼好的字符串：调用方有两个（预览卡、导入确认框），
      它们的排版不一样。⭐ 让每个调用方自己排版，但**别让它们各自决定说什么**。
    """
    items = bundle.get("items") if isinstance(bundle, dict) else None
    if not isinstance(items, list):
        return []
    out: List[tuple] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        preset_type = item.get("type")
        payload = item.get("payload")
        label = TYPE_LABELS.get(preset_type, str(preset_type))
        out.append((label, _summarize_payload(
            preset_type, payload if isinstance(payload, dict) else {})))
    return out


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

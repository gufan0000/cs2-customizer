# -*- coding: utf-8 -*-
"""按地图自动切换预设(R2-4,2026-06-12)。

规则存储在 config.map_preset_rules: {map_name: {"bundle": <bundle>, "saved_at": ts}}。
bundle = preset_center.export_bundle 产物(几 KB 配置 JSON,直接进 config 落盘)。

GSI 地图变化 → MapPresetHandler.process_data → apply_rule_for_map:
- 同图去重(回合内 GSI 每秒推流,不能反复 apply)
- 应用路径与预设中心"应用当前预设"完全一致(merge 模式,
  preset_center 会先建配置快照,可回滚)
- 只在 config.map_preset_enabled=True 时生效
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from config import config

from .preset_center import apply_bundle, export_bundle, validate_bundle


def _rules() -> Dict[str, Dict]:
    rules = getattr(config, "map_preset_rules", None)
    if not isinstance(rules, dict):
        rules = {}
        config.map_preset_rules = rules
    return rules


def list_rules() -> List[str]:
    return sorted(_rules().keys())


def save_rule(map_name: str, selected_types: List[str]) -> bool:
    """把当前配置按所选范围存为 map_name 的预设。"""
    name = _normalize_map(map_name)
    if not name or not selected_types:
        return False
    bundle = export_bundle(selected_types)
    if not bundle.get("items"):
        return False
    _rules()[name] = {"bundle": bundle, "saved_at": int(time.time())}
    config.save_config()
    return True


def delete_rule(map_name: str) -> bool:
    name = _normalize_map(map_name)
    if name in _rules():
        del _rules()[name]
        config.save_config()
        return True
    return False


def get_rule(map_name: str) -> Optional[Dict]:
    return _rules().get(_normalize_map(map_name))


def _normalize_map(map_name) -> str:
    """GSI 给的是 'de_dust2' 这类;留宽容:去空白、转小写。"""
    return str(map_name or "").strip().lower()


class MapPresetApplier:
    """供 GSI handler 调用的去重应用器。"""

    def __init__(self):
        self._last_applied_map = None

    def on_map(self, map_name) -> bool:
        """收到地图名;若需要则应用,返回是否真的应用了。"""
        if not bool(getattr(config, "map_preset_enabled", False)):
            return False
        name = _normalize_map(map_name)
        if not name or name == self._last_applied_map:
            return False
        rule = _rules().get(name)
        # 无论有没有规则都记住当前图,离图回图才会重新触发
        self._last_applied_map = name
        if not rule:
            return False
        bundle = rule.get("bundle")
        if not isinstance(bundle, dict) or not validate_bundle(bundle).ok:
            return False
        result = apply_bundle(bundle, mode="merge")
        return bool(result.ok)

    def reset(self):
        self._last_applied_map = None


class MapPresetHandler:
    """GSI 处理器:从 payload 抽地图名,转交 applier。"""

    def __init__(self):
        self.applier = MapPresetApplier()

    def process_data(self, data):
        try:
            map_info = (data or {}).get("map") or {}
            name = map_info.get("name")
            if name:
                applied = self.applier.on_map(name)
                if applied:
                    from core.utils.logger import get_logger

                    get_logger("MapPreset").info(f"已按地图自动应用预设: {name}")
                    try:
                        from ui_osd import notify_osd  # R2-3: 游戏内可见反馈

                        notify_osd(f"已套用 {name} 预设")
                    except Exception:
                        pass
        except Exception:
            # GSI 流水线绝不能因预设功能中断
            pass

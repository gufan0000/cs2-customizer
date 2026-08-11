# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""内置精选预设包(R2-2,2026-06-12)。

给新用户"一分钟获得完整体验"的开箱包。三个包全部只引用随软件分发的
内置样式/资源(style id 取证自 config 默认值与各页样式表),零外部素材、
零版权风险。应用走 preset_center.apply_bundle(自动快照,可回滚)。

后续扩展:外置 .cs2customizer 精选包放官网,经 R2-1 安检导入——机制已就绪,
素材按"自录/授权/CC0"红线另行立项(规划决策点②)。
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from .preset_center import SCHEMA_NAME, SCHEMA_VERSION

# (id, 名称, 一句话说明, bundle)
_PACKS: List[Tuple[str, str, str, Dict]] = [
    (
        "clean_alerts",
        "纯净提示",
        "只开回合/血量等关键提示音,不动准心与视觉——适合想保持原版手感的玩家。",
        {
            "schema": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "items": [
                {
                    "type": "special_sound",
                    "payload": {
                        "round_sound_enabled": True,
                        "round_start_style": "0",
                        "round_win_style": "0",
                        "round_lose_style": "0",
                        "health_warning_enabled": True,
                        "health_warning_style": "0",
                        "health_warning_threshold": 25,
                        "grenade_sound_enabled": False,
                        "c4_sound_enabled": True,
                        "c4_sound_style": "0",
                    },
                },
            ],
        },
    ),
    (
        "esports_minimal",
        "电竞极简",
        "小点准心+击杀联动,关闭花哨特效——比赛味儿的最小干扰方案。",
        {
            "schema": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "items": [
                {
                    "type": "crosshair",
                    "payload": {
                        "crosshair_enabled": True,
                        "crosshair_style": "dot",
                        "crosshair_color": "green",
                        "crosshair_size": 8,
                        "crosshair_thickness": 2,
                        "crosshair_animation": "none",
                        "crosshair_kill_effect": "none",
                    },
                },
                {
                    "type": "screen_effects",
                    "payload": {
                        "screen_effects_enabled": False,
                        "screen_edge_flash_enabled": False,
                    },
                },
            ],
        },
    ),
    (
        "full_experience",
        "全功能体验",
        "准心联动+屏幕特效+HUD 规则全开——一次看到 CS2 Customizer 的完整能力。",
        {
            "schema": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "items": [
                {
                    "type": "crosshair",
                    "payload": {
                        "crosshair_enabled": True,
                        "crosshair_style": "dot",
                        "crosshair_color": "red",
                        "crosshair_size": 11,
                        "crosshair_thickness": 3,
                        "crosshair_animation": "rotate",
                        "crosshair_kill_effect": "shake",
                    },
                },
                {
                    "type": "screen_effects",
                    "payload": {
                        "screen_effects_enabled": True,
                        "screen_effects_preset": "impact_sparks",
                        "screen_effects_play_mode": "streak",
                    },
                },
                {
                    "type": "hud_rules",
                    "payload": {
                        "hud_rules_enabled": True,
                        "hud_rules_profile": "balanced_default",
                    },
                },
            ],
        },
    ),
]


def list_packs() -> List[Tuple[str, str, str]]:
    """[(id, 名称, 说明)]"""
    return [(pid, name, desc) for pid, name, desc, _bundle in _PACKS]


def get_pack_bundle(pack_id: str) -> Dict:
    for pid, _name, _desc, bundle in _PACKS:
        if pid == pack_id:
            return bundle
    raise KeyError(f"unknown starter pack: {pack_id}")

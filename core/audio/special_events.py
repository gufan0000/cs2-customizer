# SPDX-License-Identifier: GPL-3.0-or-later
"""特殊音效的事件表——**全仓唯一一份**。

## 为什么要有这张表

在此之前，"回合有哪几种事件"这件事被抄在 6 个地方：

  1. `pages/special_sound_page.ROUND_TYPE_META`（中文名 + config 字段）
  2. `core/audio/audio_manager.ROUND_TYPES`
  3. `core/audio/audio_manager.scan_round_sound_styles()` 里 5 行硬编码扫描
  4. `core/audio/audio_resource_health` 里的 `(round_type, config_key)` 元组
  5. `config.py` 的默认值 / load / save 三处
  6. `gsi_handler_special` 里 5 个几乎逐字复制的 `_play_round_*` 方法

加一个事件要同时改这 6 处，漏一处的表现还各不相同：漏 3 是下拉框永远为空、
漏 4 是资源体检查不到、漏 6 是配了也不响 —— **没有一处会报错**。

这正是打包版本号那次学到的东西：与其加判据盯着 N 处字面量同步，不如让它们
只剩一处、其余全部派生，判据数量会跟着降，且剩下的那条守的是"确实没有第二处"。

## 兼容性硬约束（改这张表前先读）

- `config_attr` 是**用户 config.json 里已经存在的键名**，改名等于把用户的设置
  清空。新事件才可以自由取名。
- `subdir` 对应用户 `resources/audio/` 下**已经存在的目录名**，改名等于用户
  导入的素材全部失联。
- C4 三个事件共用同一个风格目录（`c4_sounds/<风格>/`），靠 `filename_tokens`
  在目录里挑文件。这是刻意的：老用户的 C4 素材就摊在那个目录下，如果改成
  `c4_sounds/planted/<风格>/` 这种分层，他们已导入的素材会全部找不到。
- 挑不到文件时**不做回落**。宁可不响也不能拿"安放"的音效去当"拆除"的用——
  那会让老用户在拆包时突然听到一声本该在下包时响的音效，比没有更糟。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class SoundEvent:
    """一个特殊音效事件的全部信息。"""

    key: str
    """内部标识，也是音效键里的那一段（如 round-<style>-**start**）。"""

    label: str
    """UI 上的中文名。"""

    config_attr: str
    """config 上的样式字段名。**已存在的键不许改**。"""

    group: str
    """归组，决定它出现在页面的哪个页签：round / c4 / health。"""

    category: str
    """资源分类，对应 core/resource_catalog 的 ResourceSpec 名。"""

    subdir: str = ""
    """风格目录在 category 目录下的子目录；空串表示风格目录直接摊在根下。"""

    priority: int = 55
    """音频策略层优先级。"""

    fade: bool = True
    """是否用淡入淡出播放。"""

    filename_tokens: Tuple[str, ...] = ()
    """在风格目录里挑文件时优先匹配的词。空元组表示"按 key 找同名文件"。"""

    default_style: str = "0"

    since: str = ""
    """哪一版加进来的。空表示 2.2.3 之前就有。"""

    aliases: Tuple[str, ...] = field(default_factory=tuple)
    """这个事件历史上用过的其它 key，用于兼容老音效键。"""


#: ⚠ 顺序即 UI 上的显示顺序。
#: 前五个（start/action/win/lose/mvp）是 2.2.3 之前就有的，它们的 config_attr
#: 和 subdir 都是**存量用户配置和素材目录里已经存在的字面量，不许改**。
SOUND_EVENTS: Tuple[SoundEvent, ...] = (
    # ── 回合 ──────────────────────────────────────────────────────────
    SoundEvent(
        key="start", label="回合开始", config_attr="round_start_style",
        group="round", category="round_sounds", subdir="start", priority=55,
    ),
    SoundEvent(
        key="action", label="行动开始", config_attr="round_action_style",
        group="round", category="round_sounds", subdir="action", priority=60,
    ),
    SoundEvent(
        key="win", label="回合胜利", config_attr="round_win_style",
        group="round", category="round_sounds", subdir="win", priority=88,
    ),
    SoundEvent(
        key="lose", label="回合失败", config_attr="round_lose_style",
        group="round", category="round_sounds", subdir="lose", priority=88,
    ),
    SoundEvent(
        key="mvp", label="MVP", config_attr="round_mvp_style",
        group="round", category="round_sounds", subdir="mvp", priority=90,
    ),
    # ── 比赛级（2.2.4 新增）────────────────────────────────────────────
    # 与回合级分开的理由：一整局只响一次，音量和长度的取舍完全不同，
    # 用户往往想给它们配更长的素材。
    SoundEvent(
        key="match_start", label="比赛开始", config_attr="round_match_start_style",
        group="round", category="round_sounds", subdir="match_start",
        priority=70, since="2.2.4",
    ),
    SoundEvent(
        key="match_end", label="比赛结束", config_attr="round_match_end_style",
        group="round", category="round_sounds", subdir="match_end",
        priority=92, since="2.2.4",
    ),
    SoundEvent(
        key="halftime", label="半场交换", config_attr="round_halftime_style",
        group="round", category="round_sounds", subdir="halftime",
        priority=70, since="2.2.4",
    ),
    # ── C4 ────────────────────────────────────────────────────────────
    # 三个事件共用 c4_sounds/<风格>/ 这一个目录，靠文件名关键词区分。
    # 分层目录会让老用户已导入的素材全部失联，见模块 docstring。
    SoundEvent(
        key="planted", label="C4 安放", config_attr="c4_sound_style",
        group="c4", category="c4_sounds", subdir="", priority=80, fade=False,
        filename_tokens=("planted", "install", "bomb", "下包", "安放"),
    ),
    SoundEvent(
        key="defused", label="C4 拆除", config_attr="c4_defused_style",
        group="c4", category="c4_sounds", subdir="", priority=85, fade=False,
        filename_tokens=("defused", "defuse", "拆除", "拆包"),
        since="2.2.4",
    ),
    SoundEvent(
        key="exploded", label="C4 爆炸", config_attr="c4_exploded_style",
        group="c4", category="c4_sounds", subdir="", priority=85, fade=False,
        filename_tokens=("exploded", "explode", "boom", "爆炸"),
        since="2.2.4",
    ),
    # ── 血量 ──────────────────────────────────────────────────────────
    SoundEvent(
        key="warning", label="低血量警告", config_attr="health_warning_style",
        group="health", category="health_warning", subdir="", priority=70, fade=False,
    ),
)

#: 按 key 索引。注意 key 只在组内唯一（C4 的 "planted" 和回合的 "start" 不冲突），
#: 所以对外一律用 (group, key) 或 config_attr 定位。
EVENTS_BY_ATTR = {e.config_attr: e for e in SOUND_EVENTS}


def events_in_group(group: str) -> Tuple[SoundEvent, ...]:
    return tuple(e for e in SOUND_EVENTS if e.group == group)


def get_event(group: str, key: str) -> Optional[SoundEvent]:
    for event in SOUND_EVENTS:
        if event.group == group and (event.key == key or key in event.aliases):
            return event
    return None


def round_event_keys() -> Tuple[str, ...]:
    """回合组的 key 列表。

    `AudioManager.ROUND_TYPES` 从这里派生——那个常量原本是手写的第二份清单。
    """
    return tuple(e.key for e in events_in_group("round"))


def config_defaults() -> dict:
    """所有事件的样式字段默认值，供 config.py 与页面兜底使用。"""
    return {e.config_attr: e.default_style for e in SOUND_EVENTS}


def styles_attr(event: SoundEvent) -> str:
    """这个事件的可选风格列表挂在 AudioManager 的哪个属性上。

    C4 三个事件共用一个风格目录，所以也共用一份风格列表。
    """
    if event.group == "round":
        return f"round_{event.key}_styles"
    if event.group == "c4":
        return "c4_sound_styles"
    return "health_warning_styles"


def sound_key(event: SoundEvent, style: str) -> str:
    """播放时用的音效键。存量键格式不许变（用户的预载清单按它走）。"""
    if event.group == "round":
        return f"round-{event.key}-{style}"
    if event.group == "c4":
        return f"c4-{event.key}-{style}"
    return f"health-warning-{style}"


def style_dir_parts(event: SoundEvent, style: str):
    """风格目录相对 `resources/audio/` 的路径片段。

    C4 三个事件共用同一个风格目录，所以这里对它们返回的是同一个路径——
    区分靠 `filename_tokens`，不靠目录。
    """
    parts = [event.category]
    if event.subdir:
        parts.append(event.subdir)
    parts.append(str(style))
    return parts

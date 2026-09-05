# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""音频事件回放的**措辞**：把内部记号翻成用户看得懂的话（RN-508，批 48）。

## 缺陷

`audio_replay` 那一页把内部记号直接摆在屏幕上：三个筛选框的提示语是
`play/drop/preempt/load`、`kill/headshot/c4/...`、「按 key 子串过滤」，
表格里的「动作 / 事件 / 通道 / 原因」列也是原样的蛇形英文，结果列是 `OK` / `FAIL`。

⚠⚠ **而其中一条提示语给的例子一行都匹配不上。** `event_type` 的实际取值是
`kill_voice` / `load` / `round_sounds` / `health_warning` / `default` 这一类，
筛选做的是**精确比较**（`event.event_type.lower() != event_type`）——
照着提示语输入 `kill` 或 `c4`，返回的永远是 0 条。
⭐⭐⭐ **它不只是没翻译，它给的还是一组匹配不上的例子** ——
而「筛选不出东西」看起来完全像是「本来就没有这种事件」，不像是提示语错了。
⇒ 动作与事件都改成**下拉**：动作是闭集，事件从**当前真有的记录**里生成。
   用户不必知道拼写，也不可能选到一个匹配不上的值。

## 分母

`ACTION_LABELS` 的分母由 `tests/test_replay_page_speaks_user_language.py` 从
`_record_timeline_event(action=...)` 的字面实参扫出来 —— 代码里新加一种动作，
这里漏翻就当场红。
⚠ `event_type` / `channel_type` / `reason` **不是闭集**（有 `decision.reason`、
`resolved_event_type` 这些运行时值），所以它们只做「认识就翻、不认识原样交出去」，
判据只钉「不许假装认识」。
"""

from __future__ import annotations

from typing import Dict

#: 动作：闭集（`_record_timeline_event(action=...)` 的全部字面值）。
ACTION_LABELS: Dict[str, str] = {
    "play": "播放",
    "preempt": "抢占播放",
    "drop": "丢弃",
    "load": "载入",
    "forward": "转发到语音",
}

#: 事件/通道：**开集**，只翻认识的。
EVENT_LABELS: Dict[str, str] = {
    "kill_voice": "击杀语音",
    "kill_sound": "击杀音效",
    "round_sounds": "回合音效",
    "health_warning": "低血量提醒",
    "c4_sounds": "C4 音效",
    "death": "死亡音效",
    "switch_weapons": "换枪音效",
    "reload_sounds": "换弹音效",
    "grenade_sounds": "投掷物音效",
    "gun_sound": "枪声",
    "load": "载入",
    "default": "其它",
}

#: 原因：**开集**（还有 `load_failed:<异常>` / `play_failed:<异常>` 这种带尾巴的）。
REASON_LABELS: Dict[str, str] = {
    "played": "已播放",
    "loaded": "已载入",
    "not_loaded": "还没载入",
    "audio_not_loaded": "音频没载入",
    "file_missing": "找不到文件",
    "mixer_unavailable": "音频设备不可用",
    "channel_idle": "通道空闲",
    "preempt_disabled": "没开抢占",
    "busy_no_active_metadata_drop": "通道忙且拿不到当前曲目信息，丢弃",
    "busy_no_active_metadata_preempt": "通道忙且拿不到当前曲目信息，抢占",
}

#: 带尾巴的原因前缀（`load_failed:FileNotFoundError...`）。
_REASON_PREFIXES = (
    ("load_failed:", "载入失败"),
    ("play_failed:", "播放失败"),
)


#: 后台任务的类型：闭集（`_submit_task(...)` 的全部字面值）。
TASK_TYPE_LABELS: Dict[str, str] = {
    "reload_audio": "重新载入音频",
    "import_refresh": "刷新导入的资源",
}

#: 后台任务是**谁发起的**：闭集（`submit_*_task(...)` 的全部字面实参）。
#: ⚠ 这一栏原来在表格里叫「原因」，摆的是 `audio_import_wizard_manual` 这种内部名。
TASK_SOURCE_LABELS: Dict[str, str] = {
    "audio_import_wizard": "资源导入向导（自动）",
    "audio_import_wizard_manual": "资源导入向导（手动触发）",
    "basic_reload_audio": "基础设置页",
    "reload_audio": "重新载入音频",
    "import_refresh": "刷新导入的资源",
}


def label_task_type(value: str) -> str:
    return TASK_TYPE_LABELS.get(str(value or ""), str(value or ""))


def label_task_source(value: str) -> str:
    return TASK_SOURCE_LABELS.get(str(value or ""), str(value or ""))


def label_action(value: str) -> str:
    """动作 → 中文。认不出来就原样交出去，**不假装认识**。"""
    return ACTION_LABELS.get(str(value or ""), str(value or ""))


def label_event(value: str) -> str:
    return EVENT_LABELS.get(str(value or ""), str(value or ""))


def label_reason(value: str) -> str:
    text = str(value or "")
    if text in REASON_LABELS:
        return REASON_LABELS[text]
    for prefix, human in _REASON_PREFIXES:
        if text.startswith(prefix):
            detail = text[len(prefix):].strip()
            return f"{human}：{detail}" if detail else human
    return text


def label_result(success: bool) -> str:
    return "成功" if success else "没成"

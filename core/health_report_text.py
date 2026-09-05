# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""体检报告的**措辞**：把内部实现的词翻成用户看得懂的话，并抹掉本机用户名。

## 为什么单独一个模块（RN-508，2026-09-05 批 48）

外审四轮 24 发 ×3 收敛到同一族：`audio_health` 的体检报告是**整块英文日志 +
本机绝对路径**（`ok: False` / `missing_directories: 17` /
`C:\\Users\\<用户名>\\AppData\\...`，6/6 三轮稳定）。
⭐⭐⭐ 这不是「说错了」（RN-410 那族），是**没翻译** —— 屏幕上摆的是给写代码的人看的词。

⚠ 还有一面是**隐私**：那份报告可以「导出报告」发给别人排查，
而它逐字带着 `C:\\Users\\<你的 Windows 用户名>\\...`。
⇒ 路径一律先过 `shorten_path()`（把用户目录换成 `%LOCALAPPDATA%` 这种环境变量名），
明细行再按根目录取相对路径 —— **既短又不带人名，诊断价值一点没少**。

## 为什么把词表放在这里而不是散在两个 health 模块里

`core/resource_health.py` 与 `core/audio/audio_resource_health.py` 各渲染一半报告，
而它们用的是同一套词。散着写就是同一份词表的两个副本，改一处漏一处。
⭐ 事件类的中文名**不在这里再抄一份** —— 走 `SOUND_EVENTS` 那个既有真源
（`config_attr` → `label`），那本来就是「这个配置项在界面上叫什么」的答案。
"""

from __future__ import annotations

import os
from typing import Dict

#: 用户目录一律换成环境变量名。**顺序有意义**：先长后短，
#: 否则 `%USERPROFILE%` 会把 `%LOCALAPPDATA%` 的前缀先吃掉。
_ENV_PREFIXES = ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "PROGRAMDATA", "TEMP")


def shorten_path(path: str) -> str:
    """把本机用户目录换成 `%环境变量%`，其余原样。

    ⭐ 这是**隐私面**，不只是好看：这份报告有一颗「导出报告」按钮，
    导出的东西是给别人看的。
    """
    if not path:
        return ""
    text = str(path)
    candidates = []
    for name in _ENV_PREFIXES:
        value = os.environ.get(name, "")
        if value:
            candidates.append((os.path.normpath(value), f"%{name}%"))
    # 长的先替换：`%LOCALAPPDATA%` 是 `%USERPROFILE%` 的子路径
    for value, token in sorted(candidates, key=lambda kv: -len(kv[0])):
        normalized = os.path.normpath(text)
        if normalized.lower().startswith(value.lower()):
            return token + normalized[len(value):]
    return text


def relative_path(path: str, root: str) -> str:
    """明细行只写「相对存放位置的那一段」—— 位置在小节抬头已经写过一次了。

    落在根目录外面的（理论上不该有）退回 `shorten_path`，**不静默丢掉**。
    """
    if not path:
        return ""
    if not root:
        return shorten_path(path)
    a, b = os.path.normpath(str(path)), os.path.normpath(str(root))
    if a.lower().startswith(b.lower()):
        rel = a[len(b):].lstrip("\\/")
        return rel or "（根目录本身）"
    return shorten_path(path)


#: 报告里会出现的**静态**配置项名 → 用户在界面上看到的名字。
#: ⚠ 分母由 `tests/test_health_report_speaks_user_language.py` 盯着：
#:   代码里 `_make_issue(...)` 用到的每一个基名都必须在这里或在 `SOUND_EVENTS` 里
#:   找得到中文，漏一个当场红。
CONFIG_KEY_LABELS: Dict[str, str] = {
    "crosshair_custom_data": "自定义准心图片",
    "death_sound_style": "死亡音效风格",
    "flash_audio_style": "闪光弹音效风格",
    "flash_image_style": "闪光弹图片风格",
    "kill_icon_style": "击杀图标风格",
    "grenade_sound_styles": "投掷物音效风格",
    "weapon_switch_sounds": "换枪音效风格",
    "weapon_reload_sounds": "换弹音效风格",
}

#: 出问题的原因（闭集，由同一条判据盯着分母）。
REASON_LABELS: Dict[str, str] = {
    "style directory missing": "这个风格的目录不在了",
    "style directory has no supported audio files": "这个风格的目录是空的（里面没有能用的音频）",
    "style directory has no supported image files": "这个风格的目录是空的（里面没有能用的图片）",
    "style file not found": "找不到这个风格对应的文件",
    "style assets missing": "这个风格缺素材",
    "custom crosshair data missing": "自定义准心没有素材",
}


#: 资源目录名 → 它装的是什么。
#: ⚠⚠ 这一张是**改完复跑**逼出来的（外审 5/6 仍报「报告里是英文目录列表」）：
#: 第一版我把小节名、汇总键、原因全翻了，**唯独漏了被列出来的那些条目本身** ——
#: 而缺失目录清单恰恰是这份报告里最长、最显眼的一段（`· switch_weapons`、`· crosshair`）。
#: ⭐⭐ **翻译了容器，没翻译内容** —— 而用户读的是内容。
#: ⛔ 中文后面**保留原目录名**：用户要照着去建那个文件夹的话，需要的是真名字。
DIR_LABELS: Dict[str, str] = {
    # 音效（`REQUIRED_AUDIO_DIRS`）
    "kill_sounds": "击杀音效",
    "kill_voices": "击杀语音",
    "weapon_kill_sounds": "按武器分的击杀音效",
    "weapon_kill_voices": "按武器分的击杀语音",
    "death": "死亡音效",
    "switch_weapons": "换枪音效",
    "reload_sounds": "换弹音效",
    "grenade_sounds": "投掷物音效",
    "c4_sounds": "C4 音效",
    "health_warning": "低血量提醒",
    "round_sounds": "回合音效",
    "gun_sounds": "枪声",
    # 画面（`resource_health.required_dirs`）
    "kill_icons": "击杀图标",
    "flash_images": "闪光弹图片",
    "flash_audio": "闪光弹音效",
    "utility_guides": "道具图鉴",
    "crosshair": "准心图片",
}


def label_dir(rel: str) -> str:
    """`switch_weapons` → `换枪音效（switch_weapons）`。

    只认**第一段**：`round_sounds\\start\\经典` 里有意义的是 `round_sounds`，
    后面那两段是风格名，本来就是用户自己起的。
    """
    text = str(rel or "")
    if not text:
        return ""
    head = text.replace("/", "\\").split("\\")[0]
    name = DIR_LABELS.get(head)
    return f"{name}（{text}）" if name else text


def _event_labels() -> Dict[str, str]:
    """事件类配置项的中文名 —— **走 `SOUND_EVENTS`，不在本模块再抄一份**。"""
    try:
        from core.audio.special_events import SOUND_EVENTS
    except Exception:
        return {}
    return {e.config_attr: e.label for e in SOUND_EVENTS}


def label_for_key(key: str) -> str:
    """配置项名 → 用户能认出来的说法。认不出来就**原样交出去**，不假装认识。"""
    if not key:
        return ""
    base, _, sub = str(key).partition(".")
    name = CONFIG_KEY_LABELS.get(base) or _event_labels().get(base)
    if not name:
        return str(key)
    return f"{name} · {sub}" if sub else name


def label_for_reason(reason: str) -> str:
    return REASON_LABELS.get(str(reason or ""), str(reason or ""))

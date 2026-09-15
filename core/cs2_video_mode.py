# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-434：读一下 CS2 现在是不是**独占全屏**。

RN-429 只做了「说」不做「查」，留了三个未解问题（选哪份 `cs2_video.txt` /
映射没文档 / 读不到说什么）。批 72 一个都没答完 —— 答不完 ——
而是换了个不需要答完就能成立的形状：

⭐⭐⭐ **检测只许加强警告，永不许撤销或削弱它。**
读到独占全屏 ⇒ 说得具体；**其余一切**（无边框 / 窗口化 / 读不到 / 几份不一致 /
认不出的值）⇒ **原样输出通用那句话**。因为代价的方向和直觉相反：
误判成「无边框」会把那句本来正确的警告**撤掉**（玩家配完进游戏一片空白），
误判成「独占全屏」只是多一句「去改成无边框」—— 那正是他本该在的档。
⇒ 映射推错的最坏后果是多一句多余的话，不是少一句救命的话。

⚠ 这份读数来自机器状态（同 `account` RN-472 / `audio_health` RN-146）：
不钉住，同一份代码在两台机器上出的字就不一样。钉在
`_audit_neutralize.enable_audit_mode()` 与 `tests/conftest.py`。
⭐ 而钉法本身刚在 RN-571 上摔过 —— **钉 = 把它推到那个状态，不是「碰巧就是」**
⇒ 环境变量是唯一入口，设了就一个文件都不读。

叙事、三份读数实测与裁定全文见 `CS2 Customizer_翻新工程/档案/X_只许加强不许撤销.md`。
"""
from __future__ import annotations

import glob
import os
import re

#: 独占全屏 —— 覆盖层在这一档下一个像素都画不出来。
MODE_EXCLUSIVE = "exclusive"
#: 无边框窗口化 —— 官方推荐档，覆盖层画得上去。
MODE_BORDERLESS = "borderless"
#: 有边框窗口 —— 覆盖层同样画得上去。
MODE_WINDOWED = "windowed"

#: 钉档用的环境变量。**设了就只认它**，一个文件都不读（见模块头 ⚠ 那一段）。
MODE_ENV = "CS2C_CS2_DISPLAY_MODE"

#: 显式写出来的「不知道」。⚠ **它和「没设」不等价**（原注释写「等价」，是假的）：
#:   设 `unknown` ⇒ 立刻回 `None`、一个文件都不读；没设 ⇒ 去扫这台机器的 Steam 目录。
#:   本机实测：没设 → `borderless`、设 `unknown` → `None`。工装钉档要的正是前一条路。

_VALID = (MODE_EXCLUSIVE, MODE_BORDERLESS, MODE_WINDOWED)

_SETTINGS_GLOB = os.path.join("userdata", "*", "730", "local", "cfg", "cs2_video.txt")


def _value_of(text: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s+"([^"]*)"', text)
    return match.group(1).strip() if match else None


def _mode_of(text: str) -> str | None:
    """把一份 `cs2_video.txt` 的正文映射成一档。读不出两个键就返回 None。

    ⚠ 这个映射没有文档（模块头 ②）。它只被允许决定「要不要把警告说得更具体」，
    不被允许决定「要不要警告」。
    """
    full = _value_of(text, "setting.fullscreen")
    noborder = _value_of(text, "setting.nowindowborder")
    if full is None or noborder is None:
        return None
    if full == "1":
        return MODE_BORDERLESS if noborder == "1" else MODE_EXCLUSIVE
    return MODE_BORDERLESS if noborder == "1" else MODE_WINDOWED


def _readings(steam_root: str) -> list[str]:
    # ⚠ `escape` 不是讲究：`D:/Games [SSD]/Steam` 里 `[SSD]` 会被当成**字符类**，
    #   匹配整个落空。失败方向安全（回 None ⇒ 通用提示），但**静默**。
    modes: list[str] = []
    for path in sorted(glob.glob(os.path.join(glob.escape(steam_root),
                                              _SETTINGS_GLOB))):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                text = handle.read()
        except OSError:
            continue
        mode = _mode_of(text)
        if mode is not None:
            modes.append(mode)
    return modes


def detect_display_mode() -> str | None:
    """现在的显示模式；**任何一点不确定都返回 None**。

    None 的含义是「不知道」，调用方必须据此**原样输出通用提示**，
    不许把 None 读成「没问题」。
    """
    pinned = os.environ.get(MODE_ENV, "").strip().lower()
    if pinned:
        return pinned if pinned in _VALID else None

    try:
        from cfg_utils import get_steam_path_windows

        steam_root = get_steam_path_windows()
    except Exception:                                   # 读机器状态永不许拖垮建页
        return None
    if not steam_root:
        return None

    modes = _readings(steam_root)
    if not modes or len(set(modes)) != 1:               # 没读到 / 几个账号不一致
        return None
    return modes[0]


def overlay_is_invisible_now() -> bool:
    """⭐ **只有这一档为真时才允许把话说得更具体。** 其余一切都走通用提示。"""
    return detect_display_mode() == MODE_EXCLUSIVE

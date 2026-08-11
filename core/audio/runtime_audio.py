# SPDX-License-Identifier: GPL-3.0-or-later
"""Unified runtime audio entrypoint.

UP-055：本模块此前在顶层 `from core.audio.audio_manager import ...`，
于是任何 `from core.audio.runtime_audio import get_runtime_audio_manager`
（哪怕只是为了拿到函数名、还没调用）都会立刻把 pygame 拉起来。
改为在函数内导入——真正要管理器时才付这笔钱。
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # 仅供类型标注，运行时不导入
    from core.audio.audio_manager import AudioManager

_MANAGER_MODULE = "core.audio.audio_manager"


def get_runtime_audio_manager() -> "AudioManager":
    """Return the single runtime audio manager instance."""
    from core.audio.audio_manager import get_audio_manager

    return get_audio_manager()


def get_legacy_audio_manager() -> "AudioManager":
    """Compatibility alias: returns the same runtime singleton."""
    return get_runtime_audio_manager()


def peek_runtime_audio_manager() -> Optional["AudioManager"]:
    """返回**已存在**的运行时管理器；从未创建过则返回 None，且绝不创建。

    退出清理专用。退出时若直接调 `get_runtime_audio_manager()`，会在
    "本次运行从头到尾没播过一个音"的情况下，为了执行 cleanup 反而把
    pygame + numpy + pkg_resources 整套拉起来——把退出拖慢，纯赔。

    先查 `sys.modules` 而不是直接 import：模块没被加载过就说明这个进程
    从没碰过音频子系统，自然无可清理。
    """
    module = sys.modules.get(_MANAGER_MODULE)
    if module is None:
        return None
    return getattr(module, "_audio_manager_instance", None)

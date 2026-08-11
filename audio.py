# SPDX-License-Identifier: GPL-3.0-or-later
"""Compatibility shell for legacy `audio.py` imports.

All runtime behavior is served by `core.audio.audio_manager.AudioManager`.
"""

from __future__ import annotations

from core.audio.audio_manager import AudioManager
from core.audio.runtime_audio import get_legacy_audio_manager, get_runtime_audio_manager
from core.utils.logger import get_logger

_logger = get_logger("AudioCompat")
_warned: set[str] = set()


def _warn_once(token: str, message: str):
    if token in _warned:
        return
    _warned.add(token)
    _logger.warning(f"[AudioCompat][DEPRECATED] {message}")


def get_audio_manager() -> AudioManager:
    _warn_once("audio.get_audio_manager", "audio.get_audio_manager() is deprecated; use core.audio.runtime_audio.get_runtime_audio_manager().")
    return get_runtime_audio_manager()


def __getattr__(name: str):
    # audio_manager 惰性获取：模块级直接实例化会让任何 `import audio`
    # 在导入期就初始化 pygame mixer 并扫描资源目录（副作用+过早初始化）
    if name == "audio_manager":
        return get_legacy_audio_manager()
    if name == "AudioManager":
        _warn_once("audio.AudioManager", "audio.AudioManager is deprecated; import from core.audio.audio_manager instead.")
        return AudioManager
    manager = get_legacy_audio_manager()
    if hasattr(manager, name):
        _warn_once(f"audio.attr.{name}", f"audio.{name} is deprecated; use runtime audio manager instance directly.")
        return getattr(manager, name)
    raise AttributeError(f"module 'audio' has no attribute '{name}'")

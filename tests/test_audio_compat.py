# SPDX-License-Identifier: GPL-3.0-or-later
"""Compatibility tests for legacy audio.py shell."""

import audio
from core.audio.runtime_audio import get_runtime_audio_manager


def test_legacy_audio_module_returns_runtime_singleton():
    runtime_mgr = get_runtime_audio_manager()
    assert audio.audio_manager is runtime_mgr
    assert audio.get_audio_manager() is runtime_mgr


def test_legacy_audio_module_forwards_runtime_attributes():
    runtime_mgr = get_runtime_audio_manager()
    legacy_play = audio.play_sound
    runtime_play = runtime_mgr.play_sound

    assert callable(legacy_play)
    assert legacy_play.__func__ is runtime_play.__func__

# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 120（对标补课唯一追的深度差距）：视频直接变击杀图标。

以前拖 mp4 进来只得到一句「先用在线工具或 ffmpeg 转成 WebP / GIF 再拖进来」——
「去装个 ffmpeg、命令行敲对参数」正是 KI-2 说要消灭的门槛。现在走 Qt 自带的 FFmpeg 后端。

素材：`tests/fixtures/testsrc_1500ms_20fps.mp4` —— ffmpeg `testsrc` 合成的测试图案（1.5 秒、160x120、20fps、8KB），
无版权。⚠ CI 上没有 ffmpeg，不能在判据里现生成。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.kill_icon_video import MAX_FRAMES, MAX_SECONDS, MIN_FPS, plan_sampling, sample_times_us

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "testsrc_1500ms_20fps.mp4"


# ──────────────────────────── 闸门在解码之前 ────────────────────────────

def test_a_short_clip_is_taken_whole_at_its_rate():
    seconds, fps, warnings = plan_sampling(1.5, 20)
    assert (seconds, fps, warnings) == (1.5, 20, [])


def test_a_long_clip_is_cut_to_the_first_seconds():
    seconds, fps, warnings = plan_sampling(60.0, 30)
    assert seconds <= MAX_SECONDS and seconds * fps <= MAX_FRAMES
    assert any("只取开头" in w for w in warnings), "截了却没说"


def test_too_many_frames_lowers_the_rate_before_decoding():
    """10 秒 @120fps = 1200 帧 —— 要在解码之前就挡下来，不是解到一半把内存吃光。
    先降帧率保住整段（10 秒 @60），不是直接砍成 5 秒。"""
    seconds, fps, warnings = plan_sampling(10.0, 120)
    assert (seconds, fps) == (10.0, MAX_FRAMES // 10), (seconds, fps)
    assert any("帧率从 120 降到" in w for w in warnings), warnings


def test_a_rate_too_low_to_animate_cuts_the_clip_instead():
    seconds, fps, warnings = plan_sampling(10.0, 30, max_frames=60)
    assert fps == MIN_FPS and seconds * fps <= 60 and any("还装不下" in w for w in warnings), (seconds, fps)


def test_the_target_rate_follows_the_source_up_to_the_cap():
    from core.kill_icon_video import DEFAULT_FPS, target_fps
    assert (target_fps(20.0), target_fps(59.94), target_fps(None)) == (20, DEFAULT_FPS, DEFAULT_FPS)


def test_sample_times_are_evenly_spaced():
    times = sample_times_us(1.0, 10)
    assert len(times) == 10 and times[1] - times[0] == 100_000


# ──────────────────────────── 真解一段视频 ────────────────────────────

@pytest.fixture(scope="module")
def qt():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_decoding_never_makes_a_sound(qt):
    """§3：解码是「播放」出来的 —— 输出不静音，导入一段视频就会从用户音箱里响一遍。"""
    from core.kill_icon_video import _player
    player, _sink = _player()
    assert player.audioOutput() is not None and player.audioOutput().isMuted()


def test_the_fixture_video_decodes_into_frames(qt):
    from core.kill_icon_video import read_video_frames
    frames, fps, warnings = read_video_frames(str(FIXTURE), fps=20)
    assert fps == 20 and 25 <= len(frames) <= 30, (len(frames), fps, warnings)
    assert frames[0].mode == "RGBA" and frames[0].size == (160, 120)
    assert frames[0].tobytes() != frames[-1].tobytes(), "每一帧都一样 —— testsrc 是会动的"


def test_a_higher_target_rate_holds_frames_through_the_last_one(qt):
    """20fps 源取 30fps：1.5 秒应是 45 帧。只比帧的起点会漏掉片尾那一个时刻（实测 44）。"""
    from core.kill_icon_video import read_video_frames
    frames, fps, _ = read_video_frames(str(FIXTURE), fps=30)
    assert (len(frames), fps) == (45, 30)


def test_a_video_is_probed_without_decoding_and_is_no_longer_refused(qt):
    """探测取的是**源**帧率（不是默认 30）—— 否则 20fps 的片子被拉成 30 帧/秒、图集白大一半。"""
    from core.kill_icon_import import probe_source
    probe = probe_source(str(FIXTURE))
    assert (probe.kind, probe.fps, probe.frame_count) == ("video", 20, 30), probe


def test_a_broken_video_is_refused_in_plain_words(qt, tmp_path):
    from core.kill_icon_import import KillIconImportError, probe_source
    broken = tmp_path / "坏的.mp4"
    broken.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"not really a video" * 50)
    with pytest.raises(KillIconImportError, match="打不开"):
        probe_source(str(broken))


def test_a_dropped_video_ends_up_as_a_sprite_sheet_in_the_library(qt, tmp_path):
    """端到端：视频 → convert_to_style → 风格库里的图集 + JSON（运行时格式）。"""
    from core.kill_icon_import import convert_to_style

    class _RM:
        def get_kill_icon_sprite_sheet_paths(self, style_name, kills, variant=""):
            d = tmp_path / "kill_icons" / style_name
            return str(d / f"{kills}{variant}.png"), str(d / f"{kills}{variant}.json")

        def get_kill_icon_legacy_frames_dir(self, style_name, kills):
            return None

        def get_kill_icon_metadata_path(self, style_name, kills):
            return str(tmp_path / "kill_icons" / style_name / f"{kills}.json")

    result = convert_to_style(str(FIXTURE), "视频", 1, resource_manager=_RM())
    meta = json.loads((tmp_path / "kill_icons" / "视频" / "1.json").read_text(encoding="utf-8"))
    assert os.path.getsize(tmp_path / "kill_icons" / "视频" / "1.png") > 0
    assert 25 <= meta["frames"] <= 30 and meta["fps"] == 20, meta
    assert result.get("frames") == meta["frames"] and result.get("kind") == "video"


def test_the_video_extensions_are_accepted_at_every_door():
    from widgets.kill_icon_level_grid import DROP_EXTENSIONS
    import inspect
    import pages.kill_icon_page as page
    assert ".mp4" in DROP_EXTENSIONS and ".webm" in DROP_EXTENSIONS, "拖不进来"
    assert "*.mp4" in inspect.getsource(page.KillIconPage._choose_file_to_import), "选文件对话框里看不见视频"
    import dialogs.kill_icon_workshop as workshop
    import dialogs.sprite_sheet_maker as maker
    from dialogs.kill_icon_import_wizard import KIND_LABELS
    assert "*.mp4" in inspect.getsource(workshop) and "*.mp4" in inspect.getsource(maker), "工坊 / 图集制作器的门没开"
    assert KIND_LABELS.get("video") == "视频", "向导说「我认出了素材」而不是「视频」"
    import widgets.kill_icon_level_grid as grid
    assert "WebP / 视频 / PNG" in inspect.getsource(grid), \
        "门开了、门牌上没写 —— 用户看着空格子上的「GIF / WebP / PNG」不会想到能拖视频"
    assert "图片或视频拖到这一页" in inspect.getsource(page.KillIconPage), "页上的导入说明没提视频"
    import widgets.kill_icon_style_strip as strip
    assert "zip / 图片 / 视频" in inspect.getsource(strip), "风格条上的「＋ 导入」卡还写着 zip / 动图 / 图片"


def test_the_release_build_keeps_qt_multimedia():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "build_tools"))
    import build_release
    assert "PySide6.QtMultimedia" not in build_release.EXCLUDES, "打包又把视频解码后端剔掉了 —— 源码里能用、装好的版本用不了"
    assert "core.kill_icon_video" in build_release.CRITICAL_ARCHIVE_MODULES

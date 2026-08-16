# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import os

from PySide6.QtWidgets import QApplication

import kill_icon_player
from pages.kill_icon_page import KillIconPage
from resource_manager import ResourceManager


def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _patch_appdata(monkeypatch, tmp_path):
    def _resolver(relative_path):
        normalized = relative_path.replace("/", os.sep).replace("\\", os.sep)
        return str(tmp_path / normalized)

    monkeypatch.setattr(ResourceManager, "get_app_data_path", staticmethod(_resolver))


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"test")


def test_resource_manager_lists_legacy_kill_icon_style(monkeypatch, tmp_path):
    _patch_appdata(monkeypatch, tmp_path)
    _touch(tmp_path / "resources" / "kill_icons" / "默认" / "1" / "frame-001.png")

    styles = ResourceManager.list_kill_icon_styles()

    assert styles == ["默认"]
    assert ResourceManager.has_kill_icon_level_assets("默认", 1) is True


def test_resource_manager_falls_back_to_old_kill_directories(monkeypatch, tmp_path):
    _patch_appdata(monkeypatch, tmp_path)
    _touch(tmp_path / "resources" / "kill1-1" / "frame-001.png")

    styles = ResourceManager.list_kill_icon_styles()

    assert styles == ["默认"]


def test_kill_icon_page_scans_legacy_style(monkeypatch, tmp_path):
    qapp()
    _patch_appdata(monkeypatch, tmp_path)
    _touch(tmp_path / "resources" / "kill_icons" / "默认" / "1" / "frame-001.png")

    page = KillIconPage()

    assert "默认" in page.available_icon_styles
    # KI-7：风格下拉换成了看得见的卡片条——名字是用户/图标包作者起的，
    # 下拉框里换之前根本不知道会换成什么样。
    assert list(page.style_strip.cards) == ["默认"]


def test_kill_icon_player_load_style_reports_legacy_assets(monkeypatch, tmp_path):
    """`load_style` 的返回值是"这个风格有没有可用素材"——设置页据此决定是否劝用户去做资源。

    KI-1 后装载本身挪到了后台线程（解码 + 预缩放要几百毫秒，不能占主线程），
    但**返回值必须还是同步的**：调用方 `pages/kill_icon_page` 拿它当条件用，
    改成异步会让那段判断永远走 False 分支。
    """
    _patch_appdata(monkeypatch, tmp_path)
    _touch(tmp_path / "resources" / "kill_icons" / "默认" / "1" / "frame-001.png")

    player = kill_icon_player.KillIconPlayer.__new__(kill_icon_player.KillIconPlayer)
    player.current_style = None
    player.animations = {}
    player._catalog = {}
    # KI-6：缓存归哪个风格是单独记的——`current_style` 在 load_style 里同步就改了，
    # 缓存却要等后台装载完，两者不分开会拿上一个风格的数当这一个的答案。
    player._catalog_style = None
    started = []
    player._start_load = lambda style: started.append(style)

    loaded = kill_icon_player.KillIconPlayer.load_style(player, "默认")

    assert loaded is True
    assert started == ["默认"]
    assert kill_icon_player.KillIconPlayer.load_style(player, "不存在的风格") is False


def test_kill_icon_player_update_fps_creates_metadata_for_legacy_style(monkeypatch, tmp_path):
    _patch_appdata(monkeypatch, tmp_path)
    _touch(tmp_path / "resources" / "kill_icons" / "默认" / "1" / "frame-001.png")

    player = kill_icon_player.KillIconPlayer.__new__(kill_icon_player.KillIconPlayer)
    player.current_style = "默认"
    player.animations = {1: {"fps": 30}}
    player._catalog = {}
    # KI-6：缓存归哪个风格是单独记的——`current_style` 在 load_style 里同步就改了，
    # 缓存却要等后台装载完，两者不分开会拿上一个风格的数当这一个的答案。
    # 这个用例模拟的是"缓存里装的就是默认风格"，所以两者一致。
    player._catalog_style = "默认"

    saved = kill_icon_player.KillIconPlayer.update_fps_for_style(player, "默认", 1, 36)

    metadata = json.loads((tmp_path / "resources" / "kill_icons" / "默认" / "1.json").read_text(encoding="utf-8"))
    fps = kill_icon_player.KillIconPlayer.get_style_fps(player, "默认", 1)

    assert saved is True
    assert metadata["fps"] == 36
    assert fps == 36
    assert player.animations[1]["fps"] == 36


def test_kill_icon_player_counts_frames_for_the_duration_control(monkeypatch, tmp_path):
    """设置页的"展示时长"控件要靠帧数换算帧率，所以帧数得数得出来。

    两种存量格式都要数得对：图集看 JSON 的 `frames`，老的逐帧目录数文件。
    数不出来（返回 0）时页面会退回按帧率显示，不会算出 0 秒这种鬼值。
    """
    _patch_appdata(monkeypatch, tmp_path)
    style_dir = tmp_path / "resources" / "kill_icons" / "默认"
    _touch(style_dir / "2.png")
    (style_dir / "2.json").write_text(
        json.dumps({"frame_width": 10, "frame_height": 10, "frames": 24, "fps": 30}),
        encoding="utf-8",
    )
    for index in range(3):
        _touch(style_dir / "1" / f"frame-{index:03d}.png")

    player = kill_icon_player.KillIconPlayer.__new__(kill_icon_player.KillIconPlayer)
    player.current_style = None
    player._catalog = {}
    # KI-6：缓存归哪个风格是单独记的——`current_style` 在 load_style 里同步就改了，
    # 缓存却要等后台装载完，两者不分开会拿上一个风格的数当这一个的答案。
    player._catalog_style = None

    assert kill_icon_player.KillIconPlayer.get_style_frame_count(player, "默认", 2) == 24
    assert kill_icon_player.KillIconPlayer.get_style_frame_count(player, "默认", 1) == 3
    assert kill_icon_player.KillIconPlayer.get_style_frame_count(player, "默认", 5) == 0

# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import os
import threading
from types import SimpleNamespace

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
    assert page.style_combo.count() == 1


def test_kill_icon_player_load_style_supports_legacy_frames(monkeypatch, tmp_path):
    _patch_appdata(monkeypatch, tmp_path)
    _touch(tmp_path / "resources" / "kill_icons" / "默认" / "1" / "frame-001.png")

    metadata_path = tmp_path / "resources" / "kill_icons" / "默认" / "1.json"
    metadata_path.write_text(json.dumps({"fps": 42}, ensure_ascii=False), encoding="utf-8")

    player = kill_icon_player.KillIconPlayer.__new__(kill_icon_player.KillIconPlayer)
    player.current_style = None
    player.animations = {}
    player._ensure_worker_started = lambda: True
    sent_commands = []
    player._send_command = lambda cmd: sent_commands.append(cmd)

    loaded = kill_icon_player.KillIconPlayer.load_style(player, "默认")

    assert loaded is True
    assert player.animations[1]["fps"] == 42
    assert sent_commands == [("load_style", "默认")]


def test_kill_icon_player_update_fps_creates_metadata_for_legacy_style(monkeypatch, tmp_path):
    _patch_appdata(monkeypatch, tmp_path)
    _touch(tmp_path / "resources" / "kill_icons" / "默认" / "1" / "frame-001.png")

    player = kill_icon_player.KillIconPlayer.__new__(kill_icon_player.KillIconPlayer)
    player.current_style = "默认"
    player.animations = {1: {"fps": 30}}

    saved = kill_icon_player.KillIconPlayer.update_fps_for_style(player, "默认", 1, 36)

    metadata = json.loads((tmp_path / "resources" / "kill_icons" / "默认" / "1.json").read_text(encoding="utf-8"))
    fps = kill_icon_player.KillIconPlayer.get_style_fps(player, "默认", 1)

    assert saved is True
    assert metadata["fps"] == 36
    assert fps == 36
    assert player.animations[1]["fps"] == 36


def test_kill_icon_player_buffers_commands_until_worker_ready():
    player = kill_icon_player.KillIconPlayer.__new__(kill_icon_player.KillIconPlayer)
    player.worker_ready = False
    player.command_queue = None
    player._command_lock = threading.Lock()
    player._pending_commands = []

    kill_icon_player.KillIconPlayer._send_command(player, ("load_style", "默认"))

    sent = []
    player.worker_ready = True
    player.command_queue = SimpleNamespace(put=lambda cmd: sent.append(cmd))
    kill_icon_player.KillIconPlayer._flush_pending_commands(player)

    assert sent == [("load_style", "默认")]
    assert player._pending_commands == []

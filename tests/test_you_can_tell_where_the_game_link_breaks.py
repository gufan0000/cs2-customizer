# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 116：「软件没反应」时自己看得出断在哪一环（对标补课：上游的「四盏灯」）。

以前首页只报「GSI · 运行中」—— 意思是**处理线程活着**，和 CS2 有没有推数据无关。
`gsi_server.py` 自己写下过那个事故形状：「音效 / 闪光 / HUD 全无反应，而状态条显示运行中」。

⭐ 判据都是**同一段代码要产出不同结果**：收到包 / 没收到、配置在 / 不在 / 端口旧、游戏开 / 没开。
"""
from __future__ import annotations

import logging
import os
import types

import pytest

import cfg_utils
import gsi_server
from core.runtime import process_power
from core.runtime.system_status_service import (
    GSI_FRESH_S, GSI_LINK_TEXT, check_gsi_cfg, collect_gsi_status, gsi_link_state)


# ──────────────────────────── 服务端：CS2 到底推没推 ────────────────────────────

@pytest.fixture()
def fresh_stats(monkeypatch):
    monkeypatch.setattr(gsi_server, "_receive_stats",
                        {"posts": 0, "last_post": None, "parse_errors": 0, "dropped": 0})
    yield
    while not gsi_server.data_queue.empty():
        gsi_server.data_queue.get_nowait()


def test_posts_are_counted_and_garbage_is_counted_separately(fresh_stats):
    assert gsi_server.get_receive_stats()["last_post_age_s"] is None, "还没收过包就不该有「最近」"
    client = gsi_server.flask_app.test_client()
    client.post("/", json={"provider": {"steamid": "1"}})
    client.post("/", data="{不是 json", content_type="application/json")
    stats = gsi_server.get_receive_stats()
    assert stats["posts"] == 1 and stats["parse_errors"] == 1, stats
    assert stats["last_post_age_s"] is not None and stats["last_post_age_s"] < 5


def test_the_status_carries_the_receive_counters(fresh_stats):
    client = gsi_server.flask_app.test_client()
    client.post("/", json={"provider": {"steamid": "1"}})
    srv = types.SimpleNamespace(_running=True, flask_thread=None, startup_error="", handlers=[])
    status = collect_gsi_status(types.SimpleNamespace(gsi_server=srv))
    assert status["posts"] == 1 and "last_post_age_s" in status and "port" in status


# ──────────────────────────── 断在哪一环 ────────────────────────────

RUN = {"running": True, "startup_error": ""}


@pytest.mark.parametrize("gsi, cfg, game, want", [
    ({"running": True, "startup_error": "端口全被占"}, {"status": "ok"}, True, "failed"),
    ({"running": False, "startup_error": ""}, {"status": "ok"}, True, "stopped"),
    (dict(RUN, last_post_age_s=3.0), {"status": "missing"}, True, "connected"),   # 数据在来 ⇒ 别的不用看
    (dict(RUN, last_post_age_s=None), {"status": "missing"}, True, "cfg_missing"),
    (dict(RUN, last_post_age_s=None), {"status": "not_configured"}, False, "cfg_missing"),
    (dict(RUN, last_post_age_s=None), {"status": "port_mismatch"}, True, "cfg_port"),
    (dict(RUN, last_post_age_s=GSI_FRESH_S + 5), {"status": "ok"}, True, "silent"),
    (dict(RUN, last_post_age_s=None), {"status": "ok"}, False, "no_game"),
    (dict(RUN, last_post_age_s=None), {"status": "ok"}, None, "no_game"),   # 判断不出游戏在不在 ⇒ 不报警
])
def test_the_first_broken_link_is_named(gsi, cfg, game, want):
    assert gsi_link_state(gsi, cfg, game) == want


def test_the_silent_state_names_the_proxy_trap():
    """「服务在听、配置装了、CS2 开着却没推」—— 上游 README 点名的系统代理坑，全仓以前零命中。"""
    fix = GSI_LINK_TEXT["silent"][2]
    assert "代理" in fix and "127.0.0.1" in fix and "重启" in fix


def test_every_badge_word_is_as_wide_as_the_old_one():
    """徽章是「GSI · X」，原来的 X 是三个字的「运行中」—— 换词不许把徽章撑宽挤到换行。"""
    for state, (word, _, _) in GSI_LINK_TEXT.items():
        if state != "failed":                       # 「启动失败」是既有的四字词
            assert len(word) == 3, (state, word)


def _cfg_dir(tmp_path, port=None):
    cfg = tmp_path / "game" / "csgo" / "cfg"
    cfg.mkdir(parents=True)
    if port is not None:
        (cfg / "gamestate_integration_cs2customizer.cfg").write_text(
            cfg_utils.CFG_TEMPLATE.format(port=port), encoding="utf-8")
    return str(tmp_path)


def test_the_game_side_config_is_checked_for_existence_and_port(tmp_path):
    assert check_gsi_cfg("", 3000)["status"] == "not_configured"
    assert check_gsi_cfg(_cfg_dir(tmp_path / "a"), 3000)["status"] == "missing"
    assert check_gsi_cfg(_cfg_dir(tmp_path / "b", 3000), 3000)["status"] == "ok"
    stale = check_gsi_cfg(_cfg_dir(tmp_path / "c", 3000), 3004)
    assert stale["status"] == "port_mismatch" and stale["port"] == 3000


# ──────────────────────────── 首页 / 关于页 ────────────────────────────

def test_the_home_badge_follows_the_link_state(monkeypatch):
    from PySide6.QtWidgets import QApplication, QLabel

    import gui_widget
    from core.utils.logger import get_logger
    from pages.audio_status_badge import create_badge_label

    QApplication.instance() or QApplication([])
    dummy = types.SimpleNamespace(
        system_status_label=QLabel(), basic_status_badge_label=create_badge_label(),
        basic_gsi_badge=QLabel(), basic_audio_badge=QLabel(), basic_config_badge=QLabel(),
        logger=get_logger("B116"))
    dummy._set_badge_label_state = (
        lambda label, text, tone="info": gui_widget.MainWindow._set_badge_label_state(dummy, label, text, tone))
    dummy._update_basic_status_summary_label = (
        lambda: gui_widget.MainWindow._update_basic_status_summary_label(dummy))
    seen = {}
    for link, audio_ok in (("connected", True), ("silent", True), ("cfg_missing", True), ("silent", False)):
        monkeypatch.setattr(gui_widget, "collect_runtime_status", lambda _mw, link=link, ok=audio_ok: types.SimpleNamespace(
            gsi={"running": True}, audio_health={"ok": ok, "missing_directories": 0 if ok else 3},
            config_dirty=False, last_error="", level="ok" if ok else "warn", gsi_link=link))
        gui_widget.MainWindow._refresh_system_status_strip(dummy)
        seen[(link, audio_ok)] = (dummy.basic_gsi_badge.text(), dummy.system_status_label.text())
    assert seen[("connected", True)][0] == "GSI · 已连接"
    assert seen[("silent", True)][0] == "GSI · 没收到" and "代理" in seen[("silent", True)][1]
    assert seen[("cfg_missing", True)][0] == "GSI · 未装好" and "CS2 目录" in seen[("cfg_missing", True)][1]
    # 联动断了比缺音频更根本：两件同时发生时，那一句先说联动
    assert "代理" in seen[("silent", False)][1], seen[("silent", False)]


def test_the_diagnostics_line_tells_support_whether_cs2_is_pushing(fresh_stats):
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    from pages.about_page import AboutPage

    QApplication.instance() or QApplication([])
    host = QWidget()
    host.gsi_server = types.SimpleNamespace(_running=True, flask_thread=None, startup_error="", handlers=[])
    page = AboutPage()
    QVBoxLayout(host).addWidget(page)
    line = next(ln for ln in page._collect_diagnostics().splitlines() if ln.startswith("GSI:"))
    for word in ("收包 0", "最近 从未", "解析失败 0", "丢包 0", "游戏内配置", "CS2 进程"):
        assert word in line, (word, line)
    host.deleteLater()


# ──────────────────────────── 调试模式不再是死开关 ────────────────────────────

def test_the_debug_mode_actually_turns_on_debug_file_logging(monkeypatch):
    from config import config
    from core.utils.logger import get_logger
    from logging.handlers import RotatingFileHandler
    from pages.advanced_page import AdvancedPage

    monkeypatch.setattr(config, "save_config", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(config, "debug_mode", False, raising=False)
    monkeypatch.setattr(config, "debug_file_log", False, raising=False)
    handlers = [h for h in get_logger().logger.handlers if isinstance(h, RotatingFileHandler)]
    before = [h.level for h in handlers]
    try:
        AdvancedPage._apply_debug_logging(True)
        assert config.debug_file_log is True
        assert handlers and all(h.level == logging.DEBUG for h in handlers), "开了调试模式，文件日志还是 INFO"
        AdvancedPage._apply_debug_logging(False)
        assert config.debug_file_log is False and all(h.level == logging.INFO for h in handlers)
    finally:
        for h, lv in zip(handlers, before):
            h.setLevel(lv)


def test_the_special_handler_debug_dumps_follow_the_same_switch(monkeypatch):
    import gsi_handler_special
    from config import config

    h = gsi_handler_special.GSIHandlerSpecial()
    monkeypatch.setattr(config, "debug_mode", True, raising=False)
    assert h.debug_mode is True
    monkeypatch.setattr(config, "debug_mode", False, raising=False)
    assert h.debug_mode is False


# ──────────────────────────── 端口占用者 / CS2 目录 / EcoQoS ────────────────────────────

NETSTAT = """
活动连接

  协议  本地地址          外部地址        状态           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1016
  TCP    127.0.0.1:3000         0.0.0.0:0              LISTENING       4242
  TCP    127.0.0.1:30001        0.0.0.0:0              LISTENING       77
"""


def test_the_port_owner_is_named(monkeypatch):
    assert gsi_server._listening_pid(NETSTAT, 3000) == 4242
    assert gsi_server._listening_pid(NETSTAT, 3001) is None, "30001 不是 3001"
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw.get("creationflags")))
        out = NETSTAT if cmd[0] == "netstat" else '"SomeTool.exe","4242","Console","1","12,345 K"\n'
        return types.SimpleNamespace(stdout=out)

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert gsi_server.describe_port_owner(3000) == "SomeTool.exe（PID 4242）"
    assert all(flags for _, flags in calls), "查占用者时会闪黑窗（没带 CREATE_NO_WINDOW）"


def test_the_cs2_folder_is_found_by_what_steam_recorded(monkeypatch, tmp_path):
    """装在改过名的目录里：只有 appmanifest_730.acf 知道它叫什么。"""
    lib = tmp_path / "SteamLibrary"
    (lib / "steamapps" / "common" / "CS2 我自己改的名").mkdir(parents=True)
    (lib / "steamapps" / "appmanifest_730.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"730"\n\t"installdir"\t\t"CS2 我自己改的名"\n}\n', encoding="utf-8")
    monkeypatch.setattr(cfg_utils, "get_steam_path_windows", lambda: str(lib))
    monkeypatch.setattr(cfg_utils, "_iter_steam_library_paths", lambda root: iter([str(lib)]))
    monkeypatch.delenv("SteamPath", raising=False)
    monkeypatch.delenv("SteamRoot", raising=False)
    found = cfg_utils.find_cs2_install_dir()
    assert found and os.path.basename(found) == "CS2 我自己改的名", found


def test_eco_qos_is_switched_off_without_touching_priority():
    calls = []

    class FakeKernel32:
        def GetCurrentProcess(self):
            return -1

        def SetProcessInformation(self, handle, klass, ptr, size):
            state = process_power.PROCESS_POWER_THROTTLING_STATE.from_address(ctypes_addr(ptr))
            calls.append((klass, state.Version, state.ControlMask, state.StateMask, size))
            return 1

        def SetPriorityClass(self, *a):
            raise AssertionError("不许提优先级（会抢 CS2 的输入线程）")

    assert process_power.opt_out_of_eco_qos(FakeKernel32()) is True
    assert calls == [(4, 1, 0x1, 0, 12)], calls


def ctypes_addr(byref_obj):
    import ctypes
    return ctypes.addressof(byref_obj._obj)

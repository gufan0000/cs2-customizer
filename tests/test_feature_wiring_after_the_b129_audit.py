# SPDX-License-Identifier: GPL-3.0-or-later
"""批 129：静默失败 / 线程 / 资源三个视角审出来、核实为真的功能接线缺陷。

每一条都是「开关拨了 / 按钮点了，界面说好了，实际没发生（或者发生了不该发生的）」。
判据落在行为上（调用真函数、看真结果），不落在源码长什么样上。

分母：批 129 审查员「静默失败 / Qt 线程 / 资源生命周期」三个视角报的条目里，核实为真、本批修的 8 条。
"""

from __future__ import annotations

import threading
import time
import types

from config import config


# ── 道具瞄点总开关：以前只写 config ───────────────────────────────────────

class _UtilityHandler:
    def __init__(self):
        self.calls = []
        self._runtime_ready = True
        self.utility_display = types.SimpleNamespace(hide=lambda: self.calls.append("hide"))

    def init_hotkey_listener(self):
        self.calls.append("start")

    def stop_hotkey_listener(self):
        self.calls.append("stop")


def _switch(monkeypatch, key, checked, handler):
    import gui_widget

    monkeypatch.setattr(config, "save_config", lambda *a, **k: None, raising=False)
    fake = types.SimpleNamespace(
        config=config, logger=types.SimpleNamespace(info=lambda *a: None, exception=lambda *a: None,
                                                    error=lambda *a: None),
        gsi_handlers={"utility": handler}, pages={},
        sender=lambda: None, _sync_master_switch_rows=lambda k: None,
        _flash_card_border=lambda s: None)
    gui_widget.MainWindow._on_switch_changed(fake, key, checked)


def test_turning_utility_guide_off_stops_its_hotkeys(monkeypatch):
    handler = _UtilityHandler()
    _switch(monkeypatch, "utility_guide_enabled", False, handler)
    assert "stop" in handler.calls and "hide" in handler.calls


def test_turning_utility_guide_on_starts_its_hotkeys_without_a_restart(monkeypatch):
    handler = _UtilityHandler()
    _switch(monkeypatch, "utility_guide_enabled", True, handler)
    assert handler.calls == ["start"]


# ── 击杀图标：拖大小滑条不许起一串装载线程 ───────────────────────────────

def test_dragging_the_icon_size_slider_runs_one_loader_at_a_time(qapp, monkeypatch):
    import kill_icon_overlay
    import kill_icon_player

    gate = threading.Event()
    started = []

    def slow_level(style, kills, variant):
        started.append(threading.current_thread().name)
        gate.wait(5)
        return None

    monkeypatch.setattr(kill_icon_player, "load_level_animation", slow_level)
    monkeypatch.setattr(kill_icon_overlay, "effective_scale", lambda *a, **k: 1.0)
    player = kill_icon_player.KillIconPlayer()
    player.current_style = "风格甲"
    for _ in range(40):                       # 40 档滑条
        player.update_scale(1.5)
    loaders = [t for t in threading.enumerate() if t.name == "KillIconLoad"]
    assert len(loaders) == 1, f"拖一次滑条起了 {len(loaders)} 条装载线程"
    assert player._pending_load == "风格甲"
    gate.set()
    for _ in range(100):                      # 正在装的那份作废，接着装最新那一份，然后停
        if player._loading_thread is None and player._pending_load is None:
            break
        time.sleep(0.02)
    assert player._loading_thread is None and player._pending_load is None


# ── 游戏内提示（OSD）：第一次在 GSI 线程里调用 ────────────────────────────

def test_the_osd_is_built_on_the_gui_thread_even_if_first_called_from_gsi(qapp, monkeypatch):
    from PySide6.QtCore import QThread

    import ui_osd

    monkeypatch.setattr(ui_osd.OsdNotifier, "_instance", None)
    ran_on = {}
    original = ui_osd.OsdNotifier._show_on_gui_thread

    def spy(self, text):
        ran_on["main"] = QThread.currentThread() is qapp.thread()
        return original(self, text)

    monkeypatch.setattr(ui_osd.OsdNotifier, "_show_on_gui_thread", spy)
    worker = threading.Thread(target=lambda: ui_osd.notify_osd("已套用 mirage 预设"))
    worker.start()
    worker.join()
    for _ in range(50):
        qapp.processEvents()
    assert ran_on.get("main") is True, "OSD 窗口在 GSI 线程里建 —— 会崩或被 except 吞掉不显示"
    window = ui_osd.OsdNotifier._instance._window
    if window is not None:
        window.hide()


# ── 音乐：整张歌单都放不出来时别无限重试 ──────────────────────────────────

def test_a_playlist_that_cannot_play_stops_instead_of_spinning(monkeypatch):
    import music_player

    timers = []

    class _Timer:
        def __init__(self, interval, fn):
            timers.append(fn)

        def start(self):
            return None

    monkeypatch.setattr(music_player.threading, "Timer", _Timer)
    player = music_player.MusicPlayer.__new__(music_player.MusicPlayer)
    player.playlist = [{"title": "a"}, {"title": "b"}, {"title": "c"}]
    player.logger = types.SimpleNamespace(error=lambda *a, **k: None)
    stopped = []
    player.stop = lambda: stopped.append(True)
    for _ in range(3):
        player._on_track_load_error({"title": "x"}, "文件不存在")
    assert len(timers) == 2 and stopped == [True], (timers, stopped)


# ── 设置 CS2 目录：联动配置没写进去时别说「成功」 ────────────────────────

def test_ensure_all_cfg_reports_whether_the_gsi_cfg_was_written(tmp_path, monkeypatch):
    import cfg_utils

    assert cfg_utils.ensure_all_cfg(str(tmp_path / "不存在的目录")) is False
    game = tmp_path / "cs2"
    (game / "game" / "csgo" / "cfg").mkdir(parents=True)
    monkeypatch.setattr(cfg_utils, "setup_autoexec", lambda d, allow_edit=True: None)
    assert cfg_utils.ensure_all_cfg(str(game)) is True


# ── 开镜热键：没挂上要说出来 ──────────────────────────────────────────────

def test_magnifier_says_when_a_hotkey_did_not_register(monkeypatch):
    import pages.magnifier_page as mp
    from core.hotkeys import registry

    monkeypatch.setattr(registry, "register_key", lambda *a, **k: None)
    monkeypatch.setattr(registry, "register_mouse", lambda *a, **k: None)
    monkeypatch.setattr(registry, "bindings_for_key", lambda *a, **k: [], raising=False)
    status = []
    page = types.SimpleNamespace(
        HOTKEY_OWNER="开镜放大", logger=types.SimpleNamespace(info=lambda *a: None, warning=lambda *a: None,
                                                              error=lambda *a: None),
        status_label=types.SimpleNamespace(setText=status.append))
    for name in dir(mp.MagnifierPage):
        if name.startswith(("_global_", "_clear_", "_unregister")):
            setattr(page, name, lambda *a, **k: None)
        elif name.isupper():                       # 键名映射表等类常量照搬
            setattr(page, name, getattr(mp.MagnifierPage, name))
    ok = mp.MagnifierPage._register_hotkeys(page, "右键", "右键")
    assert ok is False
    assert status and "没挂上" in status[-1], status


# ── 局内视角：没设 CS2 目录时别说「已保存到 game/csgo/cfg」 ──────────────

def test_viewmodel_save_without_a_game_dir_does_not_claim_success(monkeypatch):
    import pages.viewmodel_page as vp

    said = []
    monkeypatch.setattr(vp.QMessageBox, "information", lambda *a, **k: said.append(("info", a[1])))
    monkeypatch.setattr(vp.QMessageBox, "warning", lambda *a, **k: said.append(("warn", a[1])))
    monkeypatch.setattr(vp.QMessageBox, "critical", lambda *a, **k: said.append(("crit", a[1])))
    monkeypatch.setattr(config, "csgo_dir", "", raising=False)
    monkeypatch.setattr(config, "save_config", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(config, "check_hotkey_conflict", lambda *a, **k: None, raising=False)
    box = lambda value: types.SimpleNamespace(isChecked=lambda: value, text=lambda: "")  # noqa: E731
    page = types.SimpleNamespace(
        crosshair_reset_checkbox=box(False), cycle_key_input=box(""), auto_switch_checkbox=box(False),
        auto_switch_key_input=box(""), auto_switch_interval_input=types.SimpleNamespace(text=lambda: "3"),
        preset_vars=[], logger=types.SimpleNamespace(info=lambda *a: None, warning=lambda *a: None,
                                                     error=lambda *a: None),
        _mark_saved=lambda: None)
    vp.ViewmodelPage._save_viewmodel_cfg(page)
    assert ("info", "保存成功") not in said, "没设 CS2 目录也弹了「保存成功」"
    assert said and said[0][0] == "warn", said

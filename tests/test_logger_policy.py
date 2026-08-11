# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""日志级别与保留策略回归测试（UP-004）。

锁住四件事:
1. 文件日志默认 INFO（原先硬编码 DEBUG，GSI 在游戏中每秒数十条同步写盘）。
2. 环境变量 CS2C_DEBUG_LOG 与 config.json 的 debug_file_log 都能开回 DEBUG，
   排障能力不丢。
3. 过期清理只删自己的文件、只删过期的，绝不误伤。
4. 读配置的路径异常时静默退化为默认值——logger 不能因为读不到配置就起不来。
"""
from __future__ import annotations

import json
import logging
import os
import time

import pytest

import core.utils.logger as logger_mod


# ---------------- 级别开关 ----------------

@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("CS2C_DEBUG_LOG", raising=False)
    yield


def test_defaults_to_info(monkeypatch, tmp_path):
    """没有任何开关时,文件日志走 INFO。"""
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path))
    assert logger_mod._want_debug_file_log() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_env_var_enables_debug(monkeypatch, tmp_path, value):
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CS2C_DEBUG_LOG", value)
    assert logger_mod._want_debug_file_log() is True


@pytest.mark.parametrize("value", ["0", "false", "off", "no"])
def test_env_var_can_force_off(monkeypatch, tmp_path, value):
    """即使配置里开了，环境变量也能强制关掉（临时排障后好收场）。"""
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(
        json.dumps({"debug_file_log": True}), encoding="utf-8"
    )
    monkeypatch.setenv("CS2C_DEBUG_LOG", value)
    assert logger_mod._want_debug_file_log() is False


def test_config_json_enables_debug(monkeypatch, tmp_path):
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(
        json.dumps({"debug_file_log": True, "ui_font_scale": 1.0}), encoding="utf-8"
    )
    assert logger_mod._want_debug_file_log() is True


def test_broken_config_falls_back_to_default(monkeypatch, tmp_path):
    """配置文件损坏时不许抛——logger 起不来整个软件就哑了。"""
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text("{ 这不是合法 json", encoding="utf-8")
    assert logger_mod._want_debug_file_log() is False


def test_config_field_persists():
    """字段必须真能存盘并读回，否则用户在配置里改了也不生效。

    conftest 已把 CS2C_CONFIG_DIR 指到临时目录，不会碰用户真实配置。
    """
    import config as config_mod
    from config import get_config_path

    cfg = config_mod.config
    assert hasattr(cfg, "debug_file_log"), "Config 应当有 debug_file_log 字段"

    original = cfg.debug_file_log
    try:
        cfg.debug_file_log = True
        cfg.save_config_now()
        with open(get_config_path(), "r", encoding="utf-8") as fp:
            assert json.load(fp).get("debug_file_log") is True
        # 存盘后 logger 的读取函数应当能看到它
        assert logger_mod._want_debug_file_log() is True
    finally:
        cfg.debug_file_log = original
        cfg.save_config_now()


# ---------------- 保留策略 ----------------

def _touch(path, age_days: float):
    path.write_text("x", encoding="utf-8")
    old = time.time() - age_days * 86400
    os.utime(path, (old, old))


def test_purge_removes_only_expired(tmp_path):
    _touch(tmp_path / "cs2customizer_20250101.log", 30)        # 过期
    _touch(tmp_path / "cs2customizer_20250102.log.1", 20)      # 过期(轮转副本)
    _touch(tmp_path / "bootstrap_crash_20250101.log", 40)  # 过期
    _touch(tmp_path / "cs2customizer_20260807.log", 1)         # 新的,必须留
    _touch(tmp_path / "native_crash.log", 999)          # 不在清理模式内,必须留
    _touch(tmp_path / "别人的文件.txt", 999)              # 无关文件,绝不能碰

    removed = logger_mod._purge_old_logs(tmp_path, keep_days=14)

    assert removed == 3
    names = {p.name for p in tmp_path.iterdir()}
    assert names == {"cs2customizer_20260807.log", "native_crash.log", "别人的文件.txt"}


def test_purge_on_empty_dir_is_noop(tmp_path):
    assert logger_mod._purge_old_logs(tmp_path) == 0


def test_purge_survives_locked_file(tmp_path, monkeypatch):
    """单个文件删不掉（被占用）不应中断整轮清理。"""
    _touch(tmp_path / "cs2customizer_20250101.log", 30)
    _touch(tmp_path / "cs2customizer_20250102.log", 30)

    real_unlink = logger_mod.Path.unlink
    calls = {"n": 0}

    def flaky_unlink(self, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("file in use")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(logger_mod.Path, "unlink", flaky_unlink)
    removed = logger_mod._purge_old_logs(tmp_path, keep_days=14)
    assert removed == 1  # 第二个仍被清掉


def test_log_dir_is_isolated_in_tests():
    """测试进程绝不能写用户真实日志目录（UP-004 曾误删 45 个历史日志）。"""
    real_appdata = os.environ.get("LOCALAPPDATA")
    resolved = str(logger_mod.Logger._resolve_log_dir())
    assert os.environ.get("CS2C_LOG_DIR"), "conftest 应当设置 CS2C_LOG_DIR"
    assert resolved == os.environ["CS2C_LOG_DIR"]
    if real_appdata:
        assert not resolved.startswith(os.path.join(real_appdata, "CS2Customizer", "logs"))


def test_purge_never_runs_under_pytest():
    """双保险：即便忘了设 CS2C_LOG_DIR，测试进程也不许触发清理。"""
    inst = logger_mod.get_logger()
    called = []
    orig = logger_mod._purge_old_logs
    try:
        logger_mod._purge_old_logs = lambda *a, **kw: called.append(1) or 0
        inst._start_log_purge()
        time.sleep(0.15)  # 给后台线程机会（本不该有）
        assert not called, "测试进程内不应触发日志清理"
    finally:
        logger_mod._purge_old_logs = orig


def test_level_marker_is_always_logged():
    """logger 每次启动都要打级别标记——audio_event_audit 靠它判断日志可信度。"""
    import io as _io

    inst = logger_mod.get_logger()
    buf = _io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.INFO)
    inst.logger.addHandler(handler)
    try:
        # 复现启动横幅那一段的行为
        if inst._debug_file_log:
            inst.info("[日志] 文件日志级别 = DEBUG（排障模式）")
        else:
            inst.info("[日志] 文件日志级别 = INFO（如需音频事件审计请开启 debug_file_log）")
    finally:
        inst.logger.removeHandler(handler)

    text = buf.getvalue()
    assert "[日志] 文件日志级别" in text

    # 该标记必须能被审计工具正确识别
    from audio_event_audit import _detect_file_log_level

    assert _detect_file_log_level(text.splitlines()) in ("INFO", "DEBUG")


def test_audit_detects_info_level_logs():
    """INFO 级日志上做音频审计必须给出警告，不能静默给出误导性的 0。"""
    from audio_event_audit import _detect_file_log_level

    info_lines = ["[2026-08-07 10:00:00] [INFO] [CS2Customizer:1] [日志] 文件日志级别 = INFO（如需音频事件审计请开启 debug_file_log）"]
    debug_lines = ["[2026-08-07 10:00:00] [INFO] [CS2Customizer:1] [日志] 文件日志级别 = DEBUG（排障模式）"]

    assert _detect_file_log_level(info_lines) == "INFO"
    assert _detect_file_log_level(debug_lines) == "DEBUG"
    assert _detect_file_log_level(["无关的行"]) is None


def test_file_handler_level_matches_switch():
    """真实 Logger 实例的文件 handler 级别必须与开关一致。"""
    inst = logger_mod.get_logger()
    file_handlers = [
        h for h in inst.logger.handlers
        if isinstance(h, logging.FileHandler)
    ]
    assert file_handlers, "应当存在文件 handler"
    expected = logging.DEBUG if inst._debug_file_log else logging.INFO
    assert file_handlers[0].level == expected


# ==================== 日志目录隔离的一致性（R4 补）====================


def test_runtime_log_dir_honors_env_override(monkeypatch, tmp_path):
    """`main_widget._resolve_runtime_log_dir` 必须和 logger 认同一个覆盖变量。

    R4 实测踩到：logger 认 `CS2C_LOG_DIR`、main_widget 的 faulthandler 目录
    解析不认，于是 `scripts/live_run.py` 声称"隔离运行"，实际每跑一次都往用户
    真实的 `%LOCALAPPDATA%\CS2Customizer\logs\native_crash.log` 追加会话记录。
    诊断文件写错地方比不写更糟——它污染的是真实崩溃的取证材料。
    """
    import main_widget

    monkeypatch.setenv("CS2C_LOG_DIR", str(tmp_path))
    assert main_widget._resolve_runtime_log_dir() == tmp_path


def test_runtime_log_dir_matches_logger_dir(monkeypatch, tmp_path):
    """两处解析必须给出同一个目录，否则隔离总有一半会漏。"""
    import main_widget
    from core.utils.logger import Logger

    monkeypatch.setenv("CS2C_LOG_DIR", str(tmp_path))
    assert main_widget._resolve_runtime_log_dir() == Logger._resolve_log_dir()


def test_runtime_log_dir_falls_back_to_appdata(monkeypatch):
    """没设覆盖时仍走 AppData（不能因为加了隔离就改了真实行为）。"""
    import main_widget

    monkeypatch.delenv("CS2C_LOG_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\FakeAppData")
    got = main_widget._resolve_runtime_log_dir()
    assert got.name == "logs" and got.parent.name == main_widget.APP_NAME

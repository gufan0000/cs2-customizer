# SPDX-License-Identifier: GPL-3.0-or-later
"""显示层加固 / 首次渲染崩溃自愈逻辑回归测试。

覆盖 main_widget 中的哨兵 + 兼容模式自愈：
- 正常启动不进兼容模式
- 上次死在渲染（哨兵残留）→ 自动进兼容模式并落持久偏好
- 持久偏好存在 → 后续启动稳定走兼容模式（不反复横跳）
- 手动开关：环境变量 / 标志文件
"""

import importlib
import os

import pytest


@pytest.fixture
def mw(tmp_path, monkeypatch):
    """把 LOCALAPPDATA 指向临时目录，隔离真实用户数据；清空相关环境变量。"""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for key in (
        "CS2C_SAFE_MODE",
        "CS2C_SAFE_MODE_ACTIVE",
        "CS2C_DPI_ROUNDING",
        "QT_OPENGL",
        "QSG_RHI_BACKEND",
        "QT_ENABLE_HIGHDPI_SCALING",
        "QT_QPA_PLATFORM",
    ):
        monkeypatch.delenv(key, raising=False)
    module = importlib.import_module("main_widget")
    # argv 里不能残留 --safe
    monkeypatch.setattr(module.sys, "argv", ["main_widget.py"])
    return module


def test_normal_start_is_not_safe_mode(mw):
    safe, auto = mw._apply_display_hardening()
    assert safe is False
    assert auto is False
    assert not mw._safe_render_pref_path().exists()


def test_render_crash_triggers_auto_recovery(mw):
    # 模拟上次启动在 window.show() 崩溃：哨兵残留
    mw._mark_render_start()
    assert mw._render_sentinel_path().exists()

    safe, auto = mw._apply_display_hardening()
    assert safe is True
    assert auto is True
    # 持久偏好落盘，兼容模式环境变量全部就位（软件渲染 + FreeType 字体 + 关DPI）
    assert mw._safe_render_pref_path().exists()
    assert os.environ.get("QT_OPENGL") == "software"
    assert os.environ.get("QT_ENABLE_HIGHDPI_SCALING") == "0"
    assert os.environ.get("QT_QPA_PLATFORM") == "windows:fontengine=freetype"
    assert os.environ.get("CS2C_SAFE_MODE_ACTIVE") == "1"


def test_qt_message_handler_routes_warning_to_logger(mw):
    """Qt 的 qWarning 应被路由进日志——验证消息接管真实生效。"""
    import sys as _sys

    from PySide6.QtCore import QCoreApplication, qWarning

    captured = {"error": [], "warning": []}

    class _FakeLogger:
        def error(self, msg):
            captured["error"].append(str(msg))

        def warning(self, msg):
            captured["warning"].append(str(msg))

        def debug(self, msg):
            pass

    # 同上：只为让 QCoreApplication 活到用例结束
    _app = QCoreApplication.instance() or QCoreApplication(_sys.argv)
    mw._install_qt_message_handler(_FakeLogger())
    qWarning("ROUTED_MARKER_123")

    assert any("ROUTED_MARKER_123" in m for m in captured["warning"])
    assert all("[Qt警告]" in m for m in captured["warning"])


def test_persisted_pref_keeps_safe_mode_without_reflagging(mw):
    # 先制造一次自愈，落下持久偏好
    mw._mark_render_start()
    mw._apply_display_hardening()
    # 渲染成功清哨兵；偏好仍在
    mw._mark_render_ok()
    assert not mw._render_sentinel_path().exists()
    assert mw._safe_render_pref_path().exists()

    # 后续启动：仍走兼容模式，但 auto=False（不是本次新触发）
    safe, auto = mw._apply_display_hardening()
    assert safe is True
    assert auto is False


def test_sentinel_write_and_clear_roundtrip(mw):
    mw._mark_render_start()
    assert mw._render_sentinel_path().exists()
    mw._mark_render_ok()
    assert not mw._render_sentinel_path().exists()
    # 清理已不存在的哨兵不应抛错
    mw._mark_render_ok()


def test_env_var_forces_safe_mode(mw, monkeypatch):
    monkeypatch.setenv("CS2C_SAFE_MODE", "1")
    assert mw._is_safe_mode_requested() is True
    safe, auto = mw._apply_display_hardening()
    assert safe is True
    # 显式请求不是「自愈」
    assert auto is False


def test_flag_file_forces_safe_mode(mw):
    flag = mw._app_data_dir() / "safe_mode.flag"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("on", encoding="utf-8")
    assert mw._is_safe_mode_requested() is True


def test_hardening_never_raises_even_if_qt_missing(mw, monkeypatch):
    # 即便 Qt 相关调用抛错，加固也必须吞掉异常、返回而不崩启动
    import builtins

    real_import = builtins.__import__

    def _boom(name, *args, **kwargs):
        if name.startswith("PySide6"):
            raise RuntimeError("simulated Qt import failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _boom)
    # 不应抛异常
    safe, auto = mw._apply_display_hardening()
    assert safe in (True, False)

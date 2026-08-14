# SPDX-License-Identifier: GPL-3.0-or-later
"""死亡刷短视频设置页冒烟测试。"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from config import config  # noqa: E402
from core.fun.platforms import CUSTOM_KEY, resolve  # noqa: E402
from pages.fun_page import MODE_OPTIONS, FunPage  # noqa: E402


class _StubController:
    def __init__(self):
        self.calls: list[str] = []
        self.ok = True

    class _Signal:
        def connect(self, _slot):
            return None

    statusChanged = _Signal()

    def preheat(self):
        self.calls.append("preheat")
        return self.ok

    def shutdown(self):
        self.calls.append("shutdown")

    def preview(self):
        self.calls.append("preview")
        return self.ok

    def retract_now(self):
        self.calls.append("retract")

    def open_login(self):
        self.calls.append("login")
        return self.ok

    def reload_platform(self):
        self.calls.append("reload_platform")
        return self.ok


@pytest.fixture
def page(qapp, monkeypatch):
    monkeypatch.setattr(config, "fun_afterlife_enabled", False, raising=False)
    monkeypatch.setattr(config, "fun_afterlife_modes", ["deathmatch"], raising=False)
    # config 是全局单例，平台不隔离的话上一个用例改成 custom 会漏到下一个用例，
    # 下一个用例里 setCurrentIndex 索引没变、信号不发，断言就会假失败
    monkeypatch.setattr(config, "fun_afterlife_platform", "douyin", raising=False)
    monkeypatch.setattr(config, "fun_afterlife_url", "", raising=False)
    monkeypatch.setattr(config, "save_config", lambda *a, **k: None, raising=False)
    controller = _StubController()
    widget = FunPage(controller)
    yield widget, controller
    widget.deleteLater()


def test_page_builds(page):
    widget, _ = page
    assert widget.enable_box is not None
    assert len(widget._mode_boxes) == len(MODE_OPTIONS)


def test_loads_existing_modes(page):
    widget, _ = page
    assert widget._mode_boxes["deathmatch"].isChecked() is True
    assert widget._mode_boxes["competitive"].isChecked() is False


def test_toggling_mode_writes_config(page):
    widget, _ = page
    widget._mode_boxes["competitive"].setChecked(True)
    assert "competitive" in config.fun_afterlife_modes
    widget._mode_boxes["competitive"].setChecked(False)
    assert "competitive" not in config.fun_afterlife_modes


def test_enable_triggers_preheat_and_disable_triggers_shutdown(page):
    widget, controller = page
    widget.enable_box.setChecked(True)
    assert "preheat" in controller.calls
    assert config.fun_afterlife_enabled is True
    widget.enable_box.setChecked(False)
    assert "shutdown" in controller.calls
    assert config.fun_afterlife_enabled is False


def test_platform_switch_shows_url_only_for_custom(page):
    widget, controller = page
    widget.platform_combo.setCurrentIndex(widget.platform_combo.findData("douyin"))
    assert widget.url_row.isVisibleTo(widget) is False, "选抖音时不该让用户填网址"

    widget.platform_combo.setCurrentIndex(widget.platform_combo.findData(CUSTOM_KEY))
    assert widget.url_row.isVisibleTo(widget) is True
    assert widget.mobile_ua_box.isVisibleTo(widget) is True
    assert config.fun_afterlife_platform == CUSTOM_KEY


def test_platform_switch_reloads_browser(page):
    """网址和 UA 是启动参数，换平台必须整个重开浏览器才生效。"""
    widget, controller = page
    controller.calls.clear()
    widget.platform_combo.setCurrentIndex(widget.platform_combo.findData(CUSTOM_KEY))
    assert "reload_platform" in controller.calls


def test_custom_empty_url_resolves_to_douyin():
    """自定义留空不能让浏览器停在空白页。"""
    url, mobile = resolve(CUSTOM_KEY, custom_url="   ")
    assert url == "https://www.douyin.com/"
    assert mobile is True


def test_custom_url_is_used_as_is():
    url, mobile = resolve(CUSTOM_KEY, custom_url="https://example.com/feed", custom_mobile_ua=False)
    assert url == "https://example.com/feed"
    assert mobile is False


def test_unknown_platform_falls_back_to_douyin():
    url, mobile = resolve("nonexistent_platform")
    assert url == "https://www.douyin.com/"
    assert mobile is True


def test_login_button_text_follows_platform(page):
    widget, _ = page
    widget.platform_combo.setCurrentIndex(widget.platform_combo.findData("douyin"))
    assert "抖音" in widget.login_button.text()
    widget.platform_combo.setCurrentIndex(widget.platform_combo.findData(CUSTOM_KEY))
    assert "抖音" not in widget.login_button.text()


def test_status_warns_when_no_mode_selected(page):
    widget, _ = page
    widget._loading = True
    for box in widget._mode_boxes.values():
        box.setChecked(False)
    widget._loading = False
    widget.enable_box.setChecked(True)
    widget._refresh_status()
    assert "没有勾选" in widget.status_label.text()


def test_height_slider_updates_ratio(page):
    widget, _ = page
    widget.height_slider.setValue(60)
    assert widget.height_value_label.text() == "60%"
    assert abs(config.fun_afterlife_height_ratio - 0.6) < 1e-6


def test_buttons_reach_controller(page):
    widget, controller = page
    widget._on_preview_clicked()
    widget._on_retract_clicked()
    widget._on_login_clicked()
    assert controller.calls.count("preview") == 1
    assert controller.calls.count("retract") == 1
    assert controller.calls.count("login") == 1


def test_page_works_without_controller(qapp, monkeypatch):
    """controller 初始化失败时页面仍要能打开，不能连设置都进不去。"""
    monkeypatch.setattr(config, "save_config", lambda *a, **k: None, raising=False)
    widget = FunPage(None)
    widget._on_preview_clicked()
    widget._on_retract_clicked()
    widget._on_login_clicked()
    widget.enable_box.setChecked(True)  # 不应抛异常
    widget.deleteLater()

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
    # ⚠ RN-190（批 34）：手搓的 `enable_box` 换成了全站共用的就地总开关行
    #   （16 个首页功能开关里另外 15 个早就走它）。
    assert widget.master_switch_row is not None
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


def test_the_page_does_not_run_the_side_effects_itself(page):
    """⭐⭐ RN-190（批 34）：**这条判据的对象搬家了。**

    原来它验的是「在这一页拨开关 → 页面自己调 preheat/shutdown」。
    而那正是缺陷本身：同一件事两条链路，短的那条缺「同步首页那颗的显示」。
    ⇒ 副作用现在只挂在 `gui_widget._on_switch_changed` 上（唯一那条）。

    ⭐ 按批 33 那条：**判据的对象被撤掉时，要么改钉现在的唯一入口，
      要么删掉它；留着改成恒真是最坏的一种。**
    这里两件都做：① 页面自己不许再做（下面这条）；
    ② 那条唯一链路上确实有它（`test_the_only_chain_still_runs_them`）。
    """
    import ast
    import inspect
    import pages.fun_page as mod

    tree = ast.parse(inspect.getsource(mod))
    offenders = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("preheat", "shutdown"):
            offenders.append(f"{n.func.attr} @ line {n.lineno}")
    assert not offenders, (
        "页面又自己跑那串副作用了：" + ", ".join(offenders) + "\n"
        "⭐ 同一件事只能有一条链路；第二条一定会缺东西，而缺的那部分不报错。"
    )


def test_the_only_chain_still_runs_them():
    """② 那条唯一的链路上确实还有 preheat / shutdown。

    ⚠ 走 AST 查「装上了没有」——`controller.preheat()` 本身好不好使
    由 `test_afterlife_controller.py` 管（**只测「零件好使」证明不了
    「零件装上了」**，批 10/批 12 各栽过一次）。
    """
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "gui_widget.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.If):
            continue
        if "fun_afterlife_enabled" not in ast.dump(n.test):
            continue
        for c in ast.walk(n):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute):
                found.add(c.func.attr)
    assert {"preheat", "shutdown"} <= found, (
        f"`_on_switch_changed` 的 fun_afterlife 分支里只找到 {sorted(found)} —— "
        "那这一页的开关拨了之后浏览器不会预热/不会收掉。"
    )


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
    config.fun_afterlife_enabled = True   # 总开关现在是共用行读 config，不是页内复选框
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
    # ⚠ 没有主窗口时共用那行开关只记日志、不写 config（也不该抛）。
    widget.master_switch_row.set_checked_by_user(True)
    widget.deleteLater()

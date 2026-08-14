# SPDX-License-Identifier: GPL-3.0-or-later
"""死亡刷短视频编排器测试。

锁死的行为契约：
  死亡 → 显示 + 恢复播放 + 焦点给窗口
  复活 → 暂停 + 隐藏 + 焦点还给游戏，**绝不结束浏览器进程**
  再次死亡 → 复用同一窗口接着播，不重新启动
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtCore")

from core.fun import afterlife as af  # noqa: E402


class _FakeBrowser:
    """记录调用序列的假浏览器，不碰任何真窗口。"""

    def __init__(self):
        self.calls: list[str] = []
        self.launched = 0
        self.alive = False
        self._visible = False
        self.show_ok = True
        self.last_focus_restore = None
        self.url_value = "https://www.douyin.com/jingxuan"
        self.js_result = "clicked"
        self.last_js = None

    def launch(self, *, anchor_hwnd=0, start_hidden=True):
        self.launched += 1
        self.alive = True
        self._visible = not start_hidden
        self.calls.append("launch")
        return True

    def show(self, *, anchor_hwnd=0, take_focus=True):
        self.calls.append("show")
        if not self.show_ok:
            return False
        self._visible = True
        self.calls.append("resume")  # 真实现里 show() 末尾会 resume
        return True

    def hide(self, *, restore_focus_to=0):
        self.calls.append("pause")   # 真实现里 hide() 先 pause 再隐藏
        self.calls.append("hide")
        self._visible = False
        self.last_focus_restore = restore_focus_to

    def pause(self):
        self.calls.append("pause")

    def resume(self):
        self.calls.append("resume")

    def is_alive(self):
        return self.alive

    @property
    def visible(self):
        return self._visible

    def close(self):
        self.calls.append("close")
        self.alive = False

    # --- CDP 相关 ---
    def current_url(self):
        return self.url_value

    def eval_js(self, expression, timeout=10):
        self.calls.append("eval_js")
        self.last_js = expression
        return self.js_result


class _Cfg:
    fun_afterlife_enabled = True
    fun_afterlife_platform = "douyin"
    fun_afterlife_url = "https://example.invalid/"
    fun_afterlife_browser_path = ""
    fun_afterlife_mobile_ua = True
    fun_afterlife_side = "right"
    fun_afterlife_height_ratio = 0.82
    fun_afterlife_delay_ms = 0
    fun_afterlife_max_stay_sec = 180


@pytest.fixture
def ctl(monkeypatch, qapp, tmp_path):
    fake = _FakeBrowser()
    monkeypatch.setattr(af, "find_browser", lambda *_a, **_k: r"C:\fake\msedge.exe")
    monkeypatch.setattr(af, "find_game_window", lambda: 4242)
    monkeypatch.setattr(af, "force_foreground", lambda *_a, **_k: True)
    controller = af.AfterlifeController(_Cfg())
    monkeypatch.setattr(controller, "_build_browser", lambda: fake)
    monkeypatch.setattr(controller, "profile_dir", lambda: str(tmp_path))
    return controller, fake


def test_preheat_launches_hidden_and_pauses(ctl):
    controller, fake = ctl
    assert controller.preheat() is True
    assert fake.launched == 1
    assert fake.visible is False
    assert "pause" in fake.calls, "预热后必须暂停，否则会在后台一直放"


def test_preheat_is_idempotent(ctl):
    controller, fake = ctl
    controller.preheat()
    controller.preheat()
    controller.preheat()
    assert fake.launched == 1, "窗口只能启动一次，冷启动 3-5 秒摊到每次死亡上会毁掉节奏"


def test_death_shows_and_resumes(ctl):
    controller, fake = ctl
    controller._show_now()
    assert fake.visible is True
    assert "show" in fake.calls and "resume" in fake.calls


def test_respawn_pauses_and_hides_without_closing(ctl):
    """核心契约：复活只暂停+隐藏，绝不结束进程。"""
    controller, fake = ctl
    controller._show_now()
    fake.calls.clear()
    controller._handle_respawn()

    assert fake.calls == ["pause", "hide"], f"实际调用: {fake.calls}"
    assert "close" not in fake.calls, "复活时绝不能结束浏览器进程"
    assert fake.alive is True
    assert fake.visible is False
    assert fake.last_focus_restore == 4242, "焦点必须还给游戏窗口"


def test_second_death_reuses_same_window(ctl):
    """再次死亡复用同一窗口，从上次暂停处接着播。"""
    controller, fake = ctl
    controller._show_now()
    controller._handle_respawn()
    controller._show_now()
    assert fake.launched == 1, "第二次死亡不能重新启动浏览器"
    assert fake.visible is True


def test_abort_retracts(ctl):
    controller, fake = ctl
    controller._show_now()
    fake.calls.clear()
    controller._handle_abort("换图")
    assert "hide" in fake.calls
    assert "close" not in fake.calls


def test_stay_timeout_retracts(ctl):
    """GSI 断流时复活边沿永远不来，必须靠超时兜底收回。"""
    controller, fake = ctl
    controller._show_now()
    fake.calls.clear()
    controller._on_stay_timeout()
    assert "hide" in fake.calls


def test_retract_when_hidden_only_pauses(ctl):
    """窗口没显示时收回：只确保暂停，不重复隐藏。"""
    controller, fake = ctl
    controller.preheat()
    fake.calls.clear()
    controller._handle_respawn()
    assert fake.calls == ["pause"]


def test_circuit_breaker_after_repeated_failures(ctl):
    controller, fake = ctl
    fake.show_ok = False
    for _ in range(af.FAILURE_CIRCUIT_LIMIT):
        controller._show_now()
    assert controller._session_disabled is True

    # 停用后不再尝试
    fake.calls.clear()
    controller._show_now()
    assert fake.calls == []


def test_disabled_config_blocks_preheat(ctl):
    controller, fake = ctl
    controller.config.fun_afterlife_enabled = False
    try:
        assert controller.preheat() is False
        assert fake.launched == 0
    finally:
        controller.config.fun_afterlife_enabled = True


def test_missing_browser_is_reported(ctl, monkeypatch):
    controller, fake = ctl
    monkeypatch.setattr(af, "find_browser", lambda *_a, **_k: "")
    messages: list[str] = []
    controller.statusChanged.connect(messages.append)
    assert controller.preheat() is False
    assert fake.launched == 0
    assert any("浏览器" in m for m in messages)


def test_shutdown_closes_browser(ctl):
    """只有 shutdown 才真正结束进程。"""
    controller, fake = ctl
    controller.preheat()
    controller.shutdown()
    assert "close" in fake.calls
    assert controller.browser is None


def test_attach_handler_wires_edges(ctl):
    from gsi_handler_fun import GSIHandlerFun

    controller, fake = ctl
    handler = GSIHandlerFun()
    controller.attach_handler(handler)
    assert handler._on_death is not None
    assert handler._on_respawn is not None
    assert handler._on_abort is not None


def test_reload_platform_restarts_browser(ctl):
    """换平台：网址/UA 是启动参数，必须真的重开一次浏览器。"""
    controller, fake = ctl
    controller.preheat()
    assert fake.launched == 1
    fake.calls.clear()
    controller.reload_platform()
    assert "close" in fake.calls, "换平台必须先关掉旧窗口"
    assert fake.launched == 2, "换平台必须重新启动浏览器"


def test_reload_platform_noop_when_never_preheated(ctl):
    """没预热过就别为了换平台白白拉起一个进程。"""
    controller, fake = ctl
    assert controller.reload_platform() is False
    assert fake.launched == 0


def test_reload_platform_clears_circuit_breaker(ctl):
    """换平台等于用户主动干预，之前的连续失败熔断应当解除。"""
    controller, fake = ctl
    controller.preheat()
    fake.show_ok = False
    for _ in range(af.FAILURE_CIRCUIT_LIMIT):
        controller._show_now()
    assert controller._session_disabled is True
    fake.show_ok = True
    controller.reload_platform()
    assert controller._session_disabled is False


# ---- tab 纠正（抖音登录后会被固定重定向到精选网格页）----

def test_ensure_feed_clicks_when_landed_wrong(ctl):
    controller, fake = ctl
    controller.preheat()
    fake.calls.clear()
    assert controller.ensure_feed() is True
    assert "eval_js" in fake.calls
    assert "推荐" in fake.last_js
    assert "pause" in fake.calls, "切到视频流会自动起播，隐藏期间必须再暂停"


def test_ensure_feed_skips_when_already_on_feed(ctl):
    """已经在视频流上就别乱点，点一下反而可能切走。"""
    controller, fake = ctl
    controller.preheat()
    fake.url_value = "https://www.douyin.com/?is_from_mobile_home=1&recommend=1"
    fake.calls.clear()
    assert controller.ensure_feed() is True
    assert "eval_js" not in fake.calls


def test_ensure_feed_skips_for_custom_platform(ctl):
    """自定义网址没有 tab 纠正脚本，不能对人家的页面乱点。"""
    controller, fake = ctl
    controller.config.fun_afterlife_platform = "custom"
    try:
        controller.preheat()
        fake.calls.clear()
        assert controller.ensure_feed() is False
        assert "eval_js" not in fake.calls
    finally:
        controller.config.fun_afterlife_platform = "douyin"


def test_ensure_feed_survives_unreadable_url(ctl):
    """读不到地址（调试端点不可用）时安全退出，不能影响主功能。"""
    controller, fake = ctl
    controller.preheat()
    fake.url_value = ""
    fake.calls.clear()
    assert controller.ensure_feed() is False
    assert "eval_js" not in fake.calls


def test_ensure_feed_survives_js_failure(ctl):
    """JS 没点中（抖音改版）时保持原样，不报错、不影响弹出。"""
    controller, fake = ctl
    controller.preheat()
    fake.js_result = "not-found"
    assert controller.ensure_feed() is False


def test_ensure_feed_noop_without_browser(ctl):
    controller, _ = ctl
    assert controller.ensure_feed() is False


# ---- 预览不再自动收回 ----

def test_preview_does_not_auto_retract(ctl):
    """曾经写死 20 秒自动收回，用户正看着窗口自己消失，像出故障。"""
    controller, fake = ctl
    controller.preview()
    assert fake.visible is True
    assert controller._stay_timer.isActive() is False, "预览不得启动自动收回定时器"


def test_open_login_does_not_auto_retract(ctl):
    """登录要花时间（扫码），中途被收回就登不完。"""
    controller, fake = ctl
    controller.open_login()
    assert fake.visible is True
    assert controller._stay_timer.isActive() is False


def test_death_still_has_timeout_guard(ctl):
    """但正常死亡触发时，兜底超时必须还在——GSI 断流后要靠它收回。"""
    controller, fake = ctl
    controller._show_now()
    assert controller._stay_timer.isActive() is True

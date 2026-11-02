# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""首页那条状态带说的话（RN-532 / RN-531 / RN-403）。

三件事各有一条判据：

| RN | 钉住的那件事 |
|---|---|
| 532 | 状态条只说「能不能用」；外观偏好、账号不上条 |
| 531 | 报了故障的那句话，必须指出去哪修 |
| 403 | 紧凑档里那句玩家信息**不许被中间省略** |

⭐⭐ RN-403 顺出一条判据工艺：**不能问「装得下吗」** ——
省略**已经发生**了（`setText` 收到的就是省略后的串），所以量宽度永远答「装得下」。
⇒ 要问的是「这句话被省略过吗」，也就是**显示的文本和它的全文是否相等**。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

VIEWPORTS = {"完整": (1280, 800), "紧凑": (860, 640)}

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window(app, width=1280, height=800):
    import gui_widget
    from PySide6.QtCore import Qt

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.resize(width, height)
    win.show()
    for _ in range(4):
        app.processEvents()
    win.show_page("basic", animated=False, force=True)
    for _ in range(4):
        app.processEvents()
    return win


def _close(win, app):
    win._force_exit = True
    win.close()
    win.deleteLater()
    app.processEvents()


def test_the_strip_only_talks_about_whether_it_works(app):
    """⭐⭐ RN-532：先说能不能用。

    原先的状态带是「主题 / 界面 / 账号 / GSI / 音频 / 配置」，外观偏好排在最前（外审 3 发），
    而且「账号 · 未登录」穿警示色，让玩家以为必须注册才能用（外审 4 发）。
    批 148 起这几样都不上状态条了：警示色只留给真的会让它不响、不显示的事。
    """
    win = _window(app)
    try:
        view = win._home_readiness
        names = [check[0] for check in view.checks]
        assert names[:2] == ["CS2 目录", "游戏联动"], names
        said = " ".join([view.headline, win.system_status_label.text(), *names, *(c[1] for c in view.checks)])
        assert said.strip(), "状态条一个字都没说 —— 这条判据在空转"
        for word in ("主题", "界面", "登录", "账号"):
            assert word not in said, f"「{word}」又上了状态条：{said}"
    finally:
        _close(win, app)


def test_an_alarm_says_where_to_go_and_fix_it(app):
    """⭐⭐ RN-531：报了故障的那句话，必须指出去哪修。

    ⛔ 那句话不许指向「资源体检」：它是专家页，普通模式下没有入口（RN-134）。
    """
    from core.runtime.system_status_service import GSI_LINK_TEXT, READINESS_HEADLINE, RuntimeStatus, readiness_view

    for link in READINESS_HEADLINE:
        if link in ("connected", "no_game", "failed"):
            continue
        view = readiness_view(RuntimeStatus(
            gsi={"startup_error": ""}, audio_health={"ok": True}, config_dirty=False,
            last_error="", level="warn", gsi_link=link, gsi_cfg={"status": "ok"}))
        assert view.detail == GSI_LINK_TEXT[link][2], link
        assert "体检" not in view.detail, link


@pytest.mark.parametrize("viewport", sorted(VIEWPORTS))
def test_the_player_line_is_never_elided(app, viewport):
    """⭐⭐ RN-403：那句玩家信息不许被省略。

    ⛔ **不许问「装得下吗」**：省略已经发生了（`setText` 收到的就是省略后的串），
       量宽度永远答「装得下」——那正是这条缺陷躲过排版审计的方式。

    ⚠⚠ 第一版我断言「显示的 == 全文」，**判据当场把我自己修得不够的地方顶出来**：
      共享测试配置里那个 steamid 长达 18 字符，紧凑档仍要截。
      ⇒ 想清楚 RN-403 主张的到底是什么：它说的是**中间那截没了**
        （「当前玩…未记录」把「家ID: 」连同状态词一起吃掉），
        而把一串不透明 ID 的**尾巴**截掉、全文留在 tooltip 里，是可以接受的。
      ⭐ 所以判的是「只许从右边切」：显示出来的东西必须是全文的**前缀**。
        这条既逮得住原来那个缺陷，又不会逼产品去解决一个它无法解决的问题。
    """
    width, height = VIEWPORTS[viewport]
    win = _window(app, width, height)
    try:
        label = win.player_label
        shown = label.text()
        full = win._home_player_label_text(getattr(win.config, "player_steamid", ""))
        assert shown, "玩家信息那一行是空的 —— 这条判据在空转"
        assert label.toolTip() == full, (
            f"tooltip 里不是全文（「{label.toolTip()}」≠「{full}」）—— "
            "截断之后全文就只剩这一个去处了")
        head = shown.rstrip("…").rstrip(".")
        assert full.startswith(head), (
            f"{viewport}档里那一行显示的是「{shown}」，而全文是「{full}」——\n"
            "⭐ 它不是全文的前缀，说明被切掉的是**中间那截**，"
            "而那里正好是一句话里最要紧的部分。")
    finally:
        _close(win, app)

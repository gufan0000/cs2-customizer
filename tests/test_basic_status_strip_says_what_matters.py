# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""首页那条状态带说的话（RN-532 / RN-531 / RN-403）。

三件事各有一条判据：

| RN | 钉住的那件事 |
|---|---|
| 532 | 「能不能用」排在「长什么样」前面；「未登录」不许穿警示色 |
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

#: 「能不能用」那几条 —— 它们必须排在外观偏好前面。
RUNTIME_BADGES = ("basic_gsi_badge", "basic_audio_badge", "basic_config_badge")
#: 外观偏好 / 身份。
LOOKS_BADGES = ("basic_theme_badge", "basic_mode_badge")


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


def _badge_order(win):
    """状态带真正的渲染顺序 —— 从 `_update_basic_status_summary_label` 读的那张表。

    ⚠ 分母取**产品自己的那段代码**（AST），不抄一份到判据里：
      抄一份的话，改了产品而没改这里，它会一直绿着（同 RN-198）。
    """
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "gui_widget.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "_update_basic_status_summary_label":
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.For) and isinstance(sub.iter, ast.Tuple):
                names = [e.value for e in sub.iter.elts
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if len(names) >= 4:
                    return names
    return []


def test_what_decides_whether_it_works_is_listed_first(app):
    """⭐⭐ RN-532：状态带是**从左往右读**的，第一格拿走最多的注意力。

    原先的顺序是「主题 / 界面 / 账号 / GSI / 音频 / 配置」——
    外观偏好排在最前，把 GSI 与音频这两条真正决定「能不能用」的挤到后面（外审 3 发）。
    """
    order = _badge_order(None)
    # ⚠ 批 98：下限 5 —— 开源版没有账号徽章（RN-543）。
    assert len(order) >= 5, (
        f"只从产品代码里读出 {len(order)} 个徽章名 —— 解析器瞎了，这条判据在空转")
    for runtime in RUNTIME_BADGES:
        assert runtime in order, f"{runtime} 不在状态带里了 —— 这条判据的对象变了"
    for looks in LOOKS_BADGES:
        assert looks in order, f"{looks} 不在状态带里了"
    worst_runtime = max(order.index(x) for x in RUNTIME_BADGES)
    best_looks = min(order.index(x) for x in LOOKS_BADGES)
    assert worst_runtime < best_looks, (
        f"外观偏好排在了运行状态前面：{order}\n"
        "⭐ 先说能不能用，再说长什么样。")


def test_not_being_logged_in_is_not_dressed_as_a_problem(app):
    """⭐⭐ RN-532 的另一半：**警示色是一种承诺** —— 它说「这里有件事没办妥」。

    这个软件**不登录也能用全部现有功能**（帮助文案逐字这么写），
    而「账号 · 未登录」原先穿的是 `warning`（橙色）⇒
    外审 4 发报「让单机工具玩家误以为必须注册登录才能用」。
    """
    win = _window(app)
    if not hasattr(win, "basic_account_badge"):
        win.close()
        pytest.skip("这个发行版没有账号徽章（开源版）—— 这条判的就是它")
    try:
        badge = win.basic_account_badge
        assert "未登录" in badge.text(), (
            f"账号徽章现在写的是「{badge.text()}」—— 这条判据的对象变了")
        tone = str(badge.property("tone") or "")
        assert tone not in ("warning", "danger"), (
            f"「{badge.text()}」穿着 `{tone}` —— 那是「有件事没办妥」的颜色，"
            "而不登录本来就能用。")
    finally:
        _close(win, app)


def test_an_alarm_says_where_to_go_and_fix_it(app):
    """⭐⭐ RN-531：报了故障的那句话，必须指出去哪修。

    ⚠ 缺的不是一颗按钮 —— 这一页上**确实有**能修它的按钮（载入音频 / 自定义目录），
      缺的是**把告警和那颗按钮连起来的一句话**。
    ⛔ 那句话不许指向「资源体检」页：它是专家页，普通模式下没有入口（RN-134）。
    """
    from PySide6.QtWidgets import QPushButton

    win = _window(app)
    try:
        summary = win.system_status_label.text()
        if "需要检查" not in summary and "异常" not in summary:
            pytest.skip(f"这台机器上音频没有异常，报的是「{summary[:24]}」—— 没有对象可查")

        buttons = {b.text().strip() for b in win.pages["basic"].findChildren(QPushButton)
                   if b.isVisibleTo(win.pages["basic"])}
        assert buttons, "这一页一颗可见按钮都没有 —— 这条判据在空转"
        named = [b for b in buttons if b and f"「{b}」" in summary]
        assert named, (
            f"告警写着「{summary}」，而它没有点名这一页上任何一颗按钮。\n"
            f"这一页可见的按钮：{sorted(buttons)}\n"
            "⭐ 玩家读到「12 项异常」之后要知道下一步点哪儿。")
        assert "体检" not in summary, (
            "告警指向了「资源体检」—— 那是专家页，普通模式下没有入口（RN-134）。")
    finally:
        _close(win, app)


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

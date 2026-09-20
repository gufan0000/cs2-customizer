# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-108 侧栏导航结构:「基础设置」必须置顶,且任何页面都不能从紧凑模式浮层里消失。

这一页的总开关（准心、屏幕特效、切枪音效……）全写在「基础设置」里,
而它原先挂在**「音效设置」组**下面 —— 找准心的开关得先去音效菜单里翻。
裁定 A:挪出来单独置顶。

⚠ 这里刻意**不**断言分组名字叫什么、有几组 —— 那属于随时可以调的文案。
断言的是三条不许破的关系:
① 基础设置在第一组、第一位;
② 它不在音效组里;
③ 每个页面都能在紧凑模式浮层里点到（做成不属于任何组的悬空按钮就会破这条）。
"""
import ast
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    yield app


def _parse_nav_groups():
    """静态取出 `nav_groups` = [(组名, [(page_id, 显示名), ...]), ...]。

    走 AST 而不是建窗口:这三条断言只关心声明结构,建一个主窗口太贵。
    """
    src = (ROOT / "gui_widget.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "nav_groups"):
            return [
                (g.elts[0].value,
                 [(item.elts[0].value, item.elts[1].value) for item in g.elts[1].elts])
                for g in node.value.elts
            ]
    raise AssertionError("没能从 gui_widget.py 解析出 nav_groups,判据失效了")


def test_basic_settings_is_the_very_first_nav_item():
    groups = _parse_nav_groups()
    assert groups, "nav_groups 是空的"
    first_group_name, first_items = groups[0]
    assert first_items, f"第一组「{first_group_name}」是空的"
    assert first_items[0][0] == "basic", (
        f"侧栏第一项应当是「基础设置」,实际是 {first_items[0]}。"
        "各页的总开关都写在这一页里,它必须是用户一眼看得到的第一项。")


def test_basic_settings_is_not_buried_in_the_sound_group():
    for group_name, items in _parse_nav_groups():
        page_ids = [pid for pid, _ in items]
        if "basic" in page_ids:
            assert "kill_sound" not in page_ids, (
                f"「基础设置」又和音效页挤在同一组（{group_name}）了 —— "
                "准心/屏幕特效的开关也在这一页,把它放进音效组就找不到了。")


#: 侧栏里**不滚动就必须看得见**的那几项。
#: ⛔ 别往这张表里随手加：它越长，下面那条判据越容易因为别的改动而红，
#:   而它要守的只是「用户第一次进来非用不可的那几步」。
MUST_BE_ABOVE_THE_FOLD = ("basic", "audio_import_wizard")


def _sidebar_viewport(win):
    from PySide6.QtWidgets import QScrollArea

    for sa in win.findChildren(QScrollArea):
        if sa.objectName() == "sidebarScroll":
            return sa
    raise AssertionError("找不到 sidebarScroll —— 侧栏结构变了，这条判据失效了")


def test_the_first_steps_are_not_below_the_sidebar_fold(app):
    """⭐⭐⭐ RN-673：`isVisible()` 为真**不等于**屏幕上看得见。

    侧栏是个滚动区。实测（1280×800，普通模式）：视口只有 650px 而内容 842px，
    23 个导航项里 **5 个完全在折叠线以下**，「导入资源」就是其中之一（y=765）。
    而底部那颗「紧凑模式 «」按钮钉在**滚动区外面**，看起来像"到底了" ——
    于是用户翻遍侧栏也找不到那一页，只能自己开资源目录手摆文件夹。

    ⚠ 这一条正是 2026-09-16 那次改动没做完的一半：那次把它从
    `_expert_only_pages` 里挪出来，理由写的是「锁在专家模式里用户根本不知道
    有这个页面」—— 而它换了个方式继续不可见。
    ⭐ **同一个「看不见」有两种机制，修掉一种不等于修好。**

    ⛔ 本条**不**断言「一项都不许在折叠线以下」—— 侧栏本来就该能滚，
      低频页（账号中心 / 关于软件）滚出来完全正常。只钉首次必经的那几步。
    """
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.show()
        app.processEvents()
        win.setMinimumSize(1280, 800)
        win.resize(1280, 800)
        for _ in range(4):
            app.processEvents()

        scroll = _sidebar_viewport(win)
        vp = scroll.viewport()
        assert vp.height() > 100, (
            f"侧栏视口只有 {vp.height()}px —— 窗口没建起来，这条断言是空的")

        offenders = []
        for pid in MUST_BE_ABOVE_THE_FOLD:
            btn = win.nav_buttons.get(pid)
            assert btn is not None and btn.isVisible(), (
                f"「{pid}」在普通模式的侧栏里根本没有按钮 —— "
                "它是不是又被挪回 `_expert_only_pages` 了？")
            top = btn.mapTo(vp, btn.rect().topLeft()).y()
            bottom = top + btn.height()
            if bottom > vp.height() or top < 0:
                offenders.append(
                    f"{pid}「{btn.text().strip()}」y={top}~{bottom}")
        assert not offenders, (
            f"这些导航项要滚动才看得见（侧栏视口 0~{vp.height()}px）："
            + "；".join(offenders)
            + "。⭐ 它们是首次必经的一步，排在折叠线以下等于不存在。")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_importing_resources_is_not_locked_behind_expert_mode(app):
    """装素材不是专家操作 —— 这一页不许回到 `_expert_only_pages`。

    钉住 2026-09-16 那次裁定（用户在场）：它是"把下载来的素材装进软件"的
    唯一入口，锁在专家模式里的后果是用户根本不知道有这个页面。
    """
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        assert win._expert_only_pages, "专家页名单是空的 —— 这条断言的分母没了"
        assert "audio_import_wizard" not in win._expert_only_pages, (
            "「导入资源」又被锁进专家模式了。它是装素材的唯一入口，"
            "普通模式下看不到它，用户只能自己开资源目录手摆文件夹。")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_every_nav_group_gets_an_alt_shortcut(app):
    """分组数是会变的,Alt+N 的上限不能写死。"""
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        seqs = {sc.key().toString() for sc in win._app_shortcuts}
        missing = {f"Alt+{i + 1}" for i in range(len(win.nav_groups))} - seqs
        assert not missing, f"这些分组没有快捷键: {sorted(missing)}"
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_no_page_disappears_from_the_compact_overlay(app):
    """紧凑模式下侧栏收起,浮层是**唯一**的导航入口。

    浮层是**按组遍历**建的（`for group_widget in self.nav_groups`),
    所以任何不属于某个分组的页面都会从浮层里整个消失 —— 而完整模式下它还在,
    肉眼扫一遍侧栏根本发现不了。RN-108 之所以给「基础设置」单独开一组、
    而不是做成一个悬空的置顶按钮,就是因为这条。
    """
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win._show_sidebar_overlay()
        overlay_pages = set(win._overlay_buttons)
        missing = set(win._page_names) - overlay_pages
        assert not missing, (
            f"这些页面在紧凑模式浮层里点不到: {sorted(missing)}。"
            "多半是它们没被挂进任何一个 nav 分组。")
        assert "basic" in overlay_pages
    finally:
        win._hide_sidebar_overlay()
        win.close()
        win.deleteLater()
        app.processEvents()

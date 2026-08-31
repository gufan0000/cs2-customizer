# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 36 · RN-077 的**第四条漏网通路**：手搓卡片的副标题，判据一条都看不见。

## 怎么撞上的

`utility` 改完复跑外审，两轮 6 发反复报同一件事：
「卡片说明堆砌『放在一起方便维护素材』等**开发者视角的冗余废话**」。
去查 RN-077 —— 那条判据（`test_no_layout_self_talk_sitewide`）**就是为这件事写的**，
而且是绿的。

成因：它的抽取器走 AST，认的是**卡片工厂的实参**
（`SettingsCard(...)` / `_create_*_card(...)` 的 `description=` 或第 2 个位置参数）
和 `PAGE_LEAD` / `*_LEAD_TEXT` 常量。而 `utility_page.py` 的卡是**手搓**的：

    settings_frame = QFrame()
    settings_frame.setObjectName("card")
    ...
    settings_hint = QLabel("热键和显示模式放在一起，改完可以立刻切到其他标签继续维护。")
    settings_hint.setObjectName("hintLabel")

没有工厂，没有 `description=` ⇒ **抽取器视野之外**。

⭐⭐⭐ 这是同一条教训的**第四次**现身，RN-077 自己的 docstring 里前三次逐字写着：
  · 第一次：分母只有 2 页（音效家族）；
  · 第二次（RN-091）：音效家族走 `PAGE_LEAD` 类常量，实参通路抽到 **0 条**；
  · 第三次（RN-145）：页头文案有两种说法时 `description=` 收的是个名字，不是字面量；
  · **第四次（本条）：卡根本不是工厂造的。**
⭐⭐ 每一次的修法都是「再补一条通路」，而每一次补完，判据仍然只覆盖
  **我当时想得到的那些通路**。⇒ 这一条换个问法：**不问文案是怎么造出来的，
  只问用户屏幕上有没有这句话。**

## 分母：213 条可见 `hintLabel`，**3 条**命中

    utility        ['放在一起']  '热键和显示模式放在一起，改完可以立刻切到其他标签继续维护。'
    utility        ['收在一起']  '常用文件夹和刷新动作收在一起，方便边游戏边维护素材。'
    preset_center  ['放在一起']  '导出、导入和应用放在一起，连续处理预设包时更顺手。'

三条都是手搓卡片。⇒ 三条全改成功能描述，这条判据断言 **0**，不配棘轮。
⭐ 一个只剩 1 条的棘轮，等于把那一条**写进制度里保留下来**。

## ⭐⭐ 第四条是判据自己找出来的，而**我的普查脚本看不见它**

改完跑判据，红了 —— `account` 的底栏回执写着
「当前未登录 · 记住状态已开启 · **在上方卡片里**填好邮箱和密码，点那颗「登录账号」」。
而**同一支扫描逻辑**写成独立脚本跑两遍，两遍都报 **0 条**。

差别不在扫描，在**账号状态**：这台机器的配置里是登录着的，那句话属于**未登录**分支；
pytest 的 `conftest` 把配置沙箱化 ⇒ 未登录 ⇒ 那句话才显示出来。
⭐⭐⭐ **我的普查跑在「我的机器」上，判据跑在「新用户的机器」上** ——
两边扫到的 `hintLabel` 总数一模一样（213 条），差的是其中一条的内容。
⭐ 所以「213 == 213」这个看起来最像守卫的等式，**恰恰盖住了唯一的差异**：
  总量相等不代表看的是同一批文案。

⇒ 顺带把口径写清：这条判据扫的是**屏幕上所有 `hintLabel`**，
  包含卡片副标题、空状态提示、**以及底栏回执** —— 不只是「卡片副标题」。

## ⛔ 它替代不了 RN-077，两条都要留

  · 运行期只看得见**当前状态下显示出来的**那一条（空库 / 非空库的两句副标题
    只会出现一个），AST 通路两句都看得见；
  · AST 通路看得见**根本没被挂上去**的死文案（RN-009 族）。
⭐ 两条判据看的是同一件事的两个投影，谁也不包含谁。
"""
from __future__ import annotations

import os
import re
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

# ⭐ 词表**不另抄一份** —— 直接用 RN-077 那一份。
# 手写一份共用件的内容，等于把自己从后续每一次改进里摘出去（批 33 那条）。
from test_no_layout_self_talk_sitewide import LAYOUT_PATTERNS, LAYOUT_WORDS

#: 至少要扫到这么多条可见副标题，否则扫描器自己瞎了（实测 213 条）。
MIN_HINTS_SEEN = 150

#: 至少要走到这么多页 —— 分母走 `win._page_names`，不是 `win.pages`（懒加载）。
MIN_PAGES_SEEN = 25


@pytest.fixture(scope="module")
def visible_hints(qapp):
    """建一次窗、走一遍全站，收每页**当前真的显示着**的 `hintLabel` 文案。"""
    os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
    os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

    import _audit_neutralize as neutral
    import _ui_mode
    from config import config

    neutral.apply(config)
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.show()
        qapp.processEvents()
        win.setMinimumSize(1280, 800)
        win.resize(1280, 800)
        qapp.processEvents()

        page_ids = list(win._page_names.keys())
        neutral.apply(config, page_ids)
        page_ids = [p for p in page_ids if p not in neutral.unsafe_pages()]

        hints: list[tuple[str, str]] = []
        seen_pages = 0
        for page_id in page_ids:
            _ui_mode.goto(win, page_id)
            for _ in range(3):
                qapp.processEvents()
            page = win.pages.get(page_id)
            if page is None:
                continue
            seen_pages += 1
            for w in page.findChildren(QLabel):
                if w.objectName() != "hintLabel" or not w.isVisibleTo(page):
                    continue
                text = (w.text() or "").strip()
                if text:
                    hints.append((page_id, text))
        yield hints, seen_pages
    finally:
        win.close()
        qapp.processEvents()


def _offenders(hints):
    out = []
    for page_id, text in hints:
        bad = [w for w in LAYOUT_WORDS if w in text]
        bad += [m.group(0) for p in LAYOUT_PATTERNS for m in re.finditer(p, text)]
        if bad:
            out.append((page_id, sorted(set(bad)), text))
    return out


def test_the_runtime_scan_actually_sees_the_hints(visible_hints):
    """⭐ 空转守卫：先证明它看得见东西，再让它去做否定断言。

    ⚠ 这条判据整个存在的理由就是「上一条在空转」—— 它自己空转会很讽刺。
    """
    hints, seen_pages = visible_hints
    assert seen_pages >= MIN_PAGES_SEEN, (
        f"只走到 {seen_pages} 页 —— 分母错了。用 `win._page_names`，"
        "切页走 `_ui_mode.goto(force=True)`。"
    )
    assert len(hints) >= MIN_HINTS_SEEN, (
        f"只扫到 {len(hints)} 条可见 `hintLabel`，实测应有 213 条 —— "
        "`objectName == \"hintLabel\"` 的约定改了？"
    )


def test_the_word_list_is_the_shared_one(visible_hints):
    """⭐ 守卫②：词表必须是 RN-077 那一份，不许在本文件里抄一份。

    **手写一份共用件的内容，等于把自己从后续每一次改进里摘出去。**
    RN-077 的词表是攒了好几轮外审才长成现在这样的（「压成」「概况卡」是
    改完复跑那轮补的）；抄一份就意味着下一轮补的词只补在一边。
    """
    import test_no_layout_self_talk_sitewide as sitewide

    assert LAYOUT_WORDS is sitewide.LAYOUT_WORDS, "词表被抄了一份，不再是同一个对象"
    assert len(LAYOUT_WORDS) >= 30, f"共用词表只剩 {len(LAYOUT_WORDS)} 条，多半被改瘦了"


def test_no_card_subtitle_on_screen_talks_about_layout(visible_hints):
    """屏幕上不许有一条副标题在讲版面。

    ⛔ **不配棘轮** —— 实测就 3 条，全改掉，断言 0。
    ⭐ 一个只剩 1 条的棘轮，等于把那一条**写进制度里保留下来**。
    """
    hints, _ = visible_hints
    bad = _offenders(hints)
    assert not bad, (
        "这几条副标题在讲版面（它会随版面腐烂成谎话，RN-077）：\n"
        + "\n".join(f"  {pid:16s} {words} {text!r}" for pid, words, text in bad)
        + "\n⇒ 改成**这张卡能干什么**，不是**它为什么摆在这里**。"
    )

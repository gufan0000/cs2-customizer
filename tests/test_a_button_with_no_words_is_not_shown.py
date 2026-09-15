# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-649（批 98）：底栏的 extra 按钮没有文字就不许露面。

特殊音效页「借了要还」把构造期抓到的空字符串原样还回去（`configure_extra("", None, visible=True)`），
底栏「刷新风格列表」左边就多出一颗无字无图标的空白按钮 —— 外审 S3 两档 2/2，看图核实为真。
全仓这颗按钮没有 icon-only 用法（AST 查过），所以守在 `PageActionBar.configure_extra` 一处：
空文本 = 没内容 = 藏；有文字照旧。
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _denominator import must_scan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_configure_extra_hides_an_empty_button(qapp):
    from widgets.page_action_bar import PageActionBar

    bar = PageActionBar()
    bar.show()
    qapp.processEvents()
    bar.configure_extra("新建风格", None, visible=True)
    assert not bar.extra_btn.isHidden(), "有字的按钮被藏了 —— 守卫管太宽"
    bar.configure_extra("", None, visible=True)
    assert bar.extra_btn.isHidden(), "空文本的 extra 按钮还露着（RN-649）"
    bar.configure_extra("   ", None, visible=True)
    assert bar.extra_btn.isHidden(), "只有空白的文本也算没内容"
    bar.close()


def test_no_page_gives_the_extra_button_an_icon_instead_of_words():
    """前提守卫：这条「空文本 = 藏」只在没有 icon-only 用法时成立；谁给它 setIcon 就得回来改守卫。"""
    hits, calls = [], []
    for p in sorted((ROOT / "pages").glob("*.py")) + sorted((ROOT / "widgets").glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                if n.func.attr == "configure_extra":
                    calls.append(p.name)
                if n.func.attr == "setIcon" and isinstance(n.func.value, ast.Attribute) \
                        and n.func.value.attr == "extra_btn":
                    hits.append(f"{p.name}:{n.lineno}")
    must_scan(calls, "configure_extra 的调用点", least=5)
    assert not hits, f"extra 按钮出现了 icon 用法，「空文本就藏」的守卫要跟着改：{hits}"
